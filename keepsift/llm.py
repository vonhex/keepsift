"""Minimal client for the local OpenAI-compatible server (stdlib only)."""
import json
import re
import time
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


class Cancelled(Exception):
    pass


class LLM:
    def __init__(self, cfg, cancel=None):
        """cancel: optional threading.Event; setting it aborts in-flight requests within a token or two."""
        self.cancel = cancel
        self.base = cfg["base_url"].rstrip("/")
        self.model = cfg["model"]
        self.timeout = cfg["timeout"]
        self.retries = cfg["retries"]
        self.temperature = cfg.get("temperature", 0.0)
        self.headers = {"Content-Type": "application/json"}
        if cfg.get("api_key"):
            self.headers["Authorization"] = f"Bearer {cfg['api_key']}"

    def chat_json(self, system, user, schema, name, effort="low", max_tokens=4000):
        if not self.model:
            models = self.ping()
            if not models:
                raise LLMError("the model server lists no models")
            self.model = models[0]
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "reasoning_effort": effort,
            "max_tokens": max_tokens,
            "temperature": self.temperature,
            "stream": True,  # lets Stop hang up mid-answer, which also frees the server slot
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            },
        }
        return _parse_json(self._post("/chat/completions", body))

    def ping(self):
        req = urllib.request.Request(self.base + "/models", headers=self.headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            return [m["id"] for m in json.load(r)["data"]]

    def _stopped(self):
        return self.cancel is not None and self.cancel.is_set()

    def _read_stream(self, r):
        """Collect the answer from an SSE stream, hanging up as soon as cancel is set."""
        content, finish = [], None
        for raw in r:
            if self._stopped():
                raise Cancelled("stopped")
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            choice = (json.loads(payload).get("choices") or [{}])[0]
            content.append((choice.get("delta") or {}).get("content") or "")
            finish = choice.get("finish_reason") or finish
        if finish == "length":
            raise LLMError("hit max_tokens before finishing (reasoning too long?)")
        return "".join(content)

    def _post(self, path, body):
        data = json.dumps(body).encode()
        last = None
        for attempt in range(self.retries + 1):
            if self._stopped():
                raise Cancelled("stopped")
            try:
                req = urllib.request.Request(self.base + path, data=data, headers=self.headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return self._read_stream(r)
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {e.read()[:300]!r}"
                if 400 <= e.code < 500:
                    break
            except (urllib.error.URLError, TimeoutError, LLMError, KeyError, IndexError) as e:
                last = e
            if self.cancel is not None:
                self.cancel.wait(2 * (attempt + 1))
            else:
                time.sleep(2 * (attempt + 1))
        raise LLMError(f"LLM request failed: {last}")


def _parse_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise LLMError(f"Model did not return JSON: {text[:200]!r}")
