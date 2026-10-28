"""Config loading/saving: config.toml for behaviour, .env / environment for secrets."""
import json
import os
import re
import sys
import tomllib
from pathlib import Path

if getattr(sys, "frozen", False):  # packaged .exe: settings and data in %LOCALAPPDATA%\KeepSift
    ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "KeepSift"
    ROOT.mkdir(parents=True, exist_ok=True)
    BUNDLE = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))  # bundled icon, samples
else:
    ROOT = Path(__file__).resolve().parent.parent
    BUNDLE = ROOT
ASSETS = BUNDLE / "assets"
SAMPLES = BUNDLE / "samples"

DEFAULTS = {
    "account": {
        "address": "",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 465,
        "query": "in:inbox newer_than:3d",
        "max_per_run": 25,
        "batch_size": 20,
        "order": "newest",
        "max_fetch_mb": 3,
    },
    "llm": {
        "base_url": "http://localhost:8080/v1",
        "model": "",  # blank = first model the server lists
        "api_key": "",
        "classify_effort": "low",
        "draft_effort": "medium",
        "temperature": 0.0,
        "classify_max_tokens": 6000,
        "draft_max_tokens": 12000,
        "max_body_chars": 12000,
        "timeout": 300,
        "retries": 2,
        "parallel": 4,
    },
    "me": {"name": "", "about": "", "style": "", "signature": "", "language": ""},
    "prompts": {"classify_extra": "", "draft_extra": "", "classify_override": "", "draft_override": ""},
    "triage": {
        "vip_senders": [],
        "min_confidence_for_actions": 0.6,
        "keep_needs_reply_visible": True,
        "keep_urgent_visible": True,
        "keep_suspicious_visible": True,
        "reply_to_bulk": False,
        "reply_to_noreply": False,
    },
    "safety": {
        "dry_run": True,
        "auto_send": False,
        "send_allowlist": [],
        "send_blocklist": [],
        "max_sends_per_hour": 5,
        "max_sends_per_day": 20,
        "min_confidence_to_send": 0.85,
        "reply_all": False,
        "quote_original": True,
        "quote_max_lines": 80,
    },
    "labels": {
        "enabled": True,
        "prefix": "AI",
        "needs_reply": True,
        "needs_reply_name": "Needs Reply",
        "suspicious_name": "Suspicious",
        "review_name": "Review",
        "drafted_name": "Drafted",
        "auto_replied_name": "Auto-Replied",
        "processed": False,
        "processed_name": "Processed",
        "star_urgent": True,
        "star_needs_reply": False,
    },
    "deletion": {
        "enabled": True,
        "action": "label",
        "label_name": "To Delete",
        "archive_marked": False,
        "min_confidence": 0.9,
        "protect_purchases": True,
        "protect_attachments": True,
        "protect_starred": True,
        "label_protected": True,
        "protected_label_name": "Kept - Important",
        "extra_protect_keywords": [],
        "protect_senders": [],
    },
    "cleanup": {
        "categories": ["promotions", "social", "updates", "forums"],
        "older_than_days": 30,
        "action": "label",
        "model_check": True,
        "model_effort": "none",
        "model_chars": 4000,
        "max_size_kb": 500,
        "batch_size": 40,
        "label_kept": True,
    },
    "watch": {"interval_minutes": 5, "quiet_start": "", "quiet_end": ""},
    "category": [],
    "rule": [],
}

CATEGORY_DEFAULTS = {
    "name": "", "description": "", "label": True, "label_name": "", "star": False,
    "mark_read": False, "archive": False, "delete": False, "reply": "none", "priority": "",
    "draft_instructions": "",
}
RULE_DEFAULTS = {
    "from": "", "to": "", "subject": "", "body": "", "category": "", "priority": "", "ignore": False,
}
STARTER_CATEGORIES = [
    {"name": "Personal", "description": "Messages written by friends or family to the user.", "reply": "draft"},
    {"name": "Work", "description": "Messages from colleagues, clients or collaborators about work, projects, "
                                    "meetings or requests.", "reply": "draft",
     "draft_instructions": "Be professional. Never agree to deadlines or meetings: propose, or leave a "
                           "[CONFIRM] placeholder."},
    {"name": "Finance", "description": "Bills, invoices, receipts, payment failures, bank, tax and "
                                       "subscription billing."},
    {"name": "Notifications", "description": "Automated account, security, shipping and service notifications "
                                             "from apps or sites.", "mark_read": True, "archive": True},
    {"name": "Promotions", "description": "Marketing, newsletters, sales, deals and social media digests.",
     "mark_read": True, "archive": True},
    {"name": "Junk", "description": "Disposable mail with no lasting value: marketing blasts and sales you never "
                                    "act on, expired offers, social media pings, 'we miss you' emails, generic "
                                    "newsletters.", "mark_read": True, "delete": True},
    {"name": "Other", "description": "Anything that fits none of the above.", "reply": "draft"},
]
STARTER_RULES = [
    {"from": "*@github.com", "category": "Notifications"},
    {"from": "*@linkedin.com", "category": "Promotions"},
]
EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
PRIORITIES = ["urgent", "normal", "low"]
REPLY_MODES = ["none", "draft", "send"]
GMAIL_CATEGORIES = ["promotions", "social", "updates", "forums", "purchases"]


def _merge(base, over):
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_env(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _time_ok(s):
    return s == "" or re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s)


def validate(cfg):
    """Fill per-item defaults and raise SystemExit with a readable message on bad values."""
    if not cfg["category"]:
        raise SystemExit("Define at least one category.")
    cats = []
    for c in cfg["category"]:
        c = {**CATEGORY_DEFAULTS, **c}
        if not c["name"].strip():
            raise SystemExit("Every category needs a name.")
        if c["reply"] not in REPLY_MODES:
            raise SystemExit(f"Category {c['name']}: reply must be one of {REPLY_MODES}.")
        if c["priority"] not in ["", *PRIORITIES]:
            raise SystemExit(f"Category {c['name']}: priority must be blank or one of {PRIORITIES}.")
        cats.append(c)
    names = [c["name"] for c in cats]
    if len(set(names)) != len(names):
        raise SystemExit("Category names must be unique.")
    cfg["category"] = cats

    rules = []
    for r in cfg["rule"]:
        r = {**RULE_DEFAULTS, **r}
        label = r["from"] or r["to"] or r["subject"] or r["body"]
        if not label:
            raise SystemExit("Every rule needs at least one of from, to, subject or body.")
        if not r["ignore"] and r["category"] not in names:
            raise SystemExit(f"Rule '{label}' points at unknown category '{r['category']}'.")
        if r["priority"] not in ["", *PRIORITIES]:
            raise SystemExit(f"Rule '{label}': priority must be blank or one of {PRIORITIES}.")
        for key in ("subject", "body"):
            try:
                re.compile(r[key])
            except re.error as e:
                raise SystemExit(f"Rule '{label}': {key} is not a valid regex ({e}).")
        rules.append(r)
    cfg["rule"] = rules

    llm = cfg["llm"]
    for key in ("classify_effort", "draft_effort"):
        if llm[key] not in EFFORTS:
            raise SystemExit(f"llm.{key} must be one of {EFFORTS}.")
    if cfg["deletion"]["action"] not in ("label", "trash"):
        raise SystemExit("deletion.action must be label or trash.")
    if cfg["cleanup"]["action"] not in ("label", "trash"):
        raise SystemExit("cleanup.action must be label or trash.")
    if cfg["cleanup"]["model_effort"] not in EFFORTS:
        raise SystemExit(f"cleanup.model_effort must be one of {EFFORTS}.")
    bad = set(cfg["cleanup"]["categories"]) - set(GMAIL_CATEGORIES)
    if bad:
        raise SystemExit(f"cleanup.categories: unknown {sorted(bad)}; use {GMAIL_CATEGORIES}.")
    if cfg["account"]["order"] not in ("newest", "oldest"):
        raise SystemExit("account.order must be newest or oldest.")
    for key in ("quiet_start", "quiet_end"):
        if not _time_ok(cfg["watch"][key]):
            raise SystemExit(f"watch.{key} must be HH:MM (24h) or blank.")
    return cfg


def db_path():
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    legacy = data / "gmailmgr.db"  # name used before the KeepSift rename
    return legacy if legacy.exists() and not (data / "keepsift.db").exists() else data / "keepsift.db"


def starter_config():
    """A sensible first config: Gmail-like categories plus a couple of rules."""
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg["category"] = [dict(CATEGORY_DEFAULTS, **c) for c in STARTER_CATEGORIES]
    cfg["rule"] = [dict(RULE_DEFAULTS, **r) for r in STARTER_RULES]
    return cfg


def is_configured():
    """True once the first-run setup has saved a Gmail login."""
    load_env(ROOT / ".env")
    return bool(os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD"))


def load(path=None):
    load_env(ROOT / ".env")
    path = Path(path) if path else ROOT / "config.toml"
    if not path.exists():
        if path != ROOT / "config.toml":
            raise SystemExit(f"Config not found: {path}")
        path.write_text(dump(starter_config()), encoding="utf-8")
    with open(path, "rb") as f:
        cfg = validate(_merge(DEFAULTS, tomllib.load(f)))
    cfg["account"]["address"] = os.environ.get("GMAIL_ADDRESS", cfg["account"]["address"])
    cfg["account"]["password"] = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    cfg["data_dir"] = ROOT / "data"
    cfg["data_dir"].mkdir(exist_ok=True)
    cfg["db_path"] = db_path()
    return cfg


def category(cfg, name):
    for cat in cfg["category"]:
        if cat["name"] == name:
            return cat
    return cfg["category"][-1]


def label(cfg, name):
    prefix = cfg["labels"]["prefix"].strip().strip("/")
    return f"{prefix}/{name}" if prefix else name


# ---------- saving ----------

def _toml(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)  # JSON strings are valid TOML basic strings


def dump(cfg):
    """Serialise a config dict (the shape of DEFAULTS) to TOML text."""
    out = ["# KeepSift settings. Edit in the GUI (Settings tab) or by hand.",
           "# Secrets (GMAIL_ADDRESS, GMAIL_APP_PASSWORD) live in .env, not here.", ""]
    for section, defaults in DEFAULTS.items():
        if not isinstance(defaults, dict):
            continue
        out.append(f"[{section}]")
        for key in defaults:
            if section == "account" and key == "address":
                continue
            out.append(f"{key} = {_toml(cfg.get(section, {}).get(key, defaults[key]))}")
        out.append("")
    for table, defaults in (("rule", RULE_DEFAULTS), ("category", CATEGORY_DEFAULTS)):
        for item in cfg.get(table, []):
            out.append(f"[[{table}]]")
            for key, default in defaults.items():
                val = item.get(key, default)
                if table == "rule" and val == default and key != "category":
                    continue  # keep rules short: only the fields that matter
                out.append(f"{key} = {_toml(val)}")
            out.append("")
    return "\n".join(out)


def check_text(text):
    """Parse + validate TOML text without saving. Returns the merged config or raises SystemExit."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"Invalid TOML: {e}")
    return validate(_merge(DEFAULTS, data))
