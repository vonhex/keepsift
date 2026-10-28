"""First-run setup wizard: Gmail login, local model, your name. Opens automatically until Gmail is set up."""
import os
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

from . import config, theme
from .config import ROOT
from .llm import LLM
from .mail import Gmail

# Common local OpenAI-compatible servers, tried in this order by "Find my model".
KNOWN_SERVERS = [
    ("llama.cpp server", "http://localhost:8080/v1"),
    ("LM Studio", "http://localhost:1234/v1"),
    ("Ollama", "http://localhost:11434/v1"),
    ("vLLM / other", "http://localhost:8000/v1"),
    ("text-generation-webui", "http://localhost:5000/v1"),
]


class SetupWizard(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Set up KeepSift")
        self.geometry("700x600")
        self.resizable(False, False)
        self.transient(app.root)

        cfg = self._current_config()
        config.load_env(ROOT / ".env")
        self.addr = tk.StringVar(value=os.environ.get("GMAIL_ADDRESS", ""))
        self.pw = tk.StringVar(value=os.environ.get("GMAIL_APP_PASSWORD", ""))
        self.url = tk.StringVar(value=cfg["llm"]["base_url"])
        self.model = tk.StringVar(value=cfg["llm"]["model"])
        self.name = tk.StringVar(value=cfg["me"]["name"])
        self.sig = tk.StringVar(value=cfg["me"]["signature"].replace("\n", " / "))

        self.body = ttk.Frame(self, padding=(32, 26, 32, 10))
        self.body.pack(fill="both", expand=True)
        ttk.Separator(self).pack(fill="x")
        nav = ttk.Frame(self, padding=(32, 14))
        nav.pack(fill="x")
        self.dots = ttk.Label(nav, text="", style="Help.TLabel")
        self.dots.pack(side="left")
        self.next_btn = ttk.Button(nav, text="Next", style="Accent.TButton", width=12, command=self.next)
        self.next_btn.pack(side="right")
        self.back_btn = ttk.Button(nav, text="Back", width=10, command=self.back)
        self.back_btn.pack(side="right", padx=8)
        self.skip_btn = ttk.Button(nav, text="Set up later", command=self.destroy)
        self.skip_btn.pack(side="right", padx=8)

        self.pages = [self.page_welcome, self.page_gmail, self.page_model, self.page_you, self.page_done]
        self.i = 0
        self.show()
        theme.recolor(self)
        self.grab_set()

    @staticmethod
    def _current_config():
        try:
            return config.load()
        except BaseException:
            return config.starter_config()

    # ---------- navigation ----------

    def show(self):
        for w in self.body.winfo_children():
            w.destroy()
        self.pages[self.i]()
        last = self.i == len(self.pages) - 1
        self.back_btn.configure(state="normal" if 0 < self.i < len(self.pages) - 1 else "disabled")
        self.next_btn.configure(text="Finish" if last else "Save & continue" if self.i == 3 else "Next")
        self.skip_btn.configure(state="disabled" if last else "normal")
        self.dots.configure(text="   ".join("●" if k == self.i else "○" for k in range(len(self.pages))))

    def next(self):
        if self.i == 3:
            self.save()
        if self.i == len(self.pages) - 1:
            self.destroy()
            return
        self.i += 1
        self.show()

    def back(self):
        self.i = max(0, self.i - 1)
        self.show()

    # ---------- helpers ----------

    def _title(self, text, sub=""):
        ttk.Label(self.body, text=text, style="Title.TLabel").pack(anchor="w")
        if sub:
            ttk.Label(self.body, text=sub, style="Help.TLabel", wraplength=620, justify="left").pack(
                anchor="w", pady=(4, 16))

    def _field(self, parent, label, var, show=None, width=44):
        ttk.Label(parent, text=label).pack(anchor="w", pady=(8, 2))
        e = ttk.Entry(parent, textvariable=var, width=width, show=show or "")
        e.pack(anchor="w")
        return e

    def _link(self, parent, text, url):
        lab = ttk.Label(parent, text=text, style="Link.TLabel", cursor="hand2")
        lab.bind("<Button-1>", lambda e: webbrowser.open(url))
        return lab

    def _bg(self, fn, done):
        """Run fn off the UI thread; done(result, error) runs back on it."""
        box = {}

        def work():
            try:
                box["r"] = fn()
            except BaseException as e:
                box["e"] = e

        t = threading.Thread(target=work, daemon=True)
        t.start()

        def poll():
            if not self.winfo_exists():
                return
            if t.is_alive():
                self.after(100, poll)
            else:
                done(box.get("r"), box.get("e"))

        poll()

    # ---------- pages ----------

    def page_welcome(self):
        try:
            self._logo = tk.PhotoImage(file=str(config.ASSETS / "icon-64.png"))
            ttk.Label(self.body, image=self._logo).pack(anchor="w", pady=(0, 14))
        except tk.TclError:
            pass
        self._title("Welcome to KeepSift",
                    "KeepSift cleans out and sorts your Gmail using an AI model running on your own computer "
                    "or server. Your email is never sent to a cloud AI.")
        for line in ("Clean up thousands of old promotions, social and update emails, sender by sender.",
                     "A safety net keeps anything with product keys, activation links, codes, receipts or "
                     "attachments, no matter what.",
                     "Sort new mail, flag phishing, and draft replies for you to review."):
            ttk.Label(self.body, text="✓  " + line, wraplength=600, justify="left").pack(anchor="w", pady=4)
        ttk.Label(self.body, text="Setup takes about two minutes.", style="Help.TLabel").pack(anchor="w", pady=(18, 0))

    def page_gmail(self):
        self._title("Connect Gmail",
                    "KeepSift signs in with a Gmail app password: a separate 16-letter password just for this "
                    "app, which you can revoke any time. Your normal password is never used.")
        steps = ttk.Frame(self.body)
        steps.pack(anchor="w", fill="x")
        ttk.Label(steps, text="1.  Turn on 2-Step Verification (if it isn't already):").grid(row=0, column=0, sticky="w")
        self._link(steps, "open", "https://myaccount.google.com/signinoptions/twosv").grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(steps, text="2.  Create an app password, name it 'KeepSift':").grid(row=1, column=0, sticky="w", pady=4)
        self._link(steps, "open", "https://myaccount.google.com/apppasswords").grid(row=1, column=1, sticky="w", padx=6)
        ttk.Label(steps, text="3.  Make sure IMAP is on (Gmail → Settings → Forwarding and POP/IMAP):").grid(
            row=2, column=0, sticky="w")
        self._link(steps, "open", "https://mail.google.com/mail/u/0/#settings/fwdandpop").grid(
            row=2, column=1, sticky="w", padx=6)
        self._field(self.body, "Gmail address", self.addr)
        self._field(self.body, "App password", self.pw, show="•")
        row = ttk.Frame(self.body)
        row.pack(anchor="w", pady=(14, 0))
        ttk.Button(row, text="Test login", command=self.test_gmail).pack(side="left")
        self.gmail_msg = ttk.Label(row, text="", wraplength=470)
        self.gmail_msg.pack(side="left", padx=12)

    def test_gmail(self):
        addr, pw = self.addr.get().strip(), self.pw.get().replace(" ", "").strip()
        self.gmail_msg.configure(text="Signing in...", style="Help.TLabel")

        def check():
            with Gmail(addr, pw) as g:
                return len(g.search("in:inbox"))

        def done(n, err):
            if err:
                msg = str(err)
                if "AUTHENTICATIONFAILED" in msg or "Invalid credentials" in msg:
                    msg = "Gmail rejected the login. Check the address and app password (not your normal password)."
                self.gmail_msg.configure(text="✗  " + msg, style="Bad.TLabel")
            else:
                self.gmail_msg.configure(text=f"✓  Signed in. {n:,} emails in your inbox.", style="Good.TLabel")

        self._bg(check, done)

    def page_model(self):
        self._title("Find your AI model",
                    "KeepSift needs an OpenAI-compatible model server: llama.cpp, LM Studio, Ollama, vLLM and "
                    "others all work. It can be on this PC or another machine on your network.")
        ttk.Button(self.body, text="Find my model automatically", style="Accent.TButton",
                   command=self.scan_models).pack(anchor="w")
        ttk.Label(self.body, text="Or enter the server address:").pack(anchor="w", pady=(16, 2))
        ttk.Combobox(self.body, textvariable=self.url, width=46,
                     values=[u for _, u in KNOWN_SERVERS]).pack(anchor="w")
        ttk.Label(self.body, text="Model").pack(anchor="w", pady=(10, 2))
        self.model_box = ttk.Combobox(self.body, textvariable=self.model, width=46)
        self.model_box.pack(anchor="w")
        ttk.Label(self.body, text="Leave the model blank to use the first one the server offers.",
                  style="Help.TLabel").pack(anchor="w", pady=(2, 0))
        row = ttk.Frame(self.body)
        row.pack(anchor="w", pady=(14, 0))
        ttk.Button(row, text="Test this address", command=self.test_model).pack(side="left")
        self.model_msg = ttk.Label(row, text="", wraplength=470)
        self.model_msg.pack(side="left", padx=12)

    def _ping(self, url):
        cfg = dict(config.DEFAULTS["llm"], base_url=url, timeout=5)
        return LLM(cfg).ping()

    def scan_models(self):
        self.model_msg.configure(text="Looking...", style="Help.TLabel")
        candidates = [self.url.get().strip()] + [u for _, u in KNOWN_SERVERS]

        def scan():
            for url in dict.fromkeys(c for c in candidates if c):
                try:
                    return url, self._ping(url)
                except Exception:
                    continue
            return None, []

        def done(res, err):
            url, models = res or (None, [])
            if not url:
                self.model_msg.configure(text="✗  No model server found on the usual ports. Start your server, "
                                              "or type its address (e.g. http://192.168.1.20:8080/v1).",
                                         style="Bad.TLabel")
                return
            self.url.set(url)
            self._got_models(models)

        self._bg(scan, done)

    def test_model(self):
        self.model_msg.configure(text="Connecting...", style="Help.TLabel")
        self._bg(lambda: self._ping(self.url.get().strip()),
                 lambda models, err: self.model_msg.configure(
                     text=f"✗  Couldn't reach it: {err}", style="Bad.TLabel") if err else self._got_models(models))

    def _got_models(self, models):
        self.model_box.configure(values=models)
        if models and self.model.get() not in models:
            self.model.set(models[0])
        self.model_msg.configure(text=f"✓  Connected. {len(models)} model(s) available.", style="Good.TLabel")

    def page_you(self):
        self._title("About you", "Used when KeepSift writes reply drafts for you. You can fine-tune tone, "
                                 "categories and rules later in Settings.")
        name = self._field(self.body, "Your name", self.name)
        name.bind("<FocusOut>", lambda e: self.sig.get() or self.sig.set(f"Thanks, / {self.name.get()}"))
        self._field(self.body, "Sign-off  (use  /  for a new line)", self.sig, width=56)
        ttk.Label(self.body, text="Nothing is sent or deleted without you: sorting starts in preview, and "
                                  "cleanup asks before it changes anything.", style="Help.TLabel",
                  wraplength=600, justify="left").pack(anchor="w", pady=(22, 0))

    def save(self):
        addr, pw = self.addr.get().strip(), self.pw.get().replace(" ", "").strip()
        env = ROOT / ".env"
        lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
        keep = [l for l in lines if not l.strip().startswith(("GMAIL_ADDRESS=", "GMAIL_APP_PASSWORD="))]
        env.write_text("\n".join(keep + [f"GMAIL_ADDRESS={addr}", f"GMAIL_APP_PASSWORD={pw}"]) + "\n",
                       encoding="utf-8")
        os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"] = addr, pw

        path = ROOT / "config.toml"
        cfg = config.check_text(path.read_text(encoding="utf-8")) if path.exists() else config.starter_config()
        cfg["llm"]["base_url"] = self.url.get().strip() or cfg["llm"]["base_url"]
        cfg["llm"]["model"] = self.model.get().strip()
        cfg["me"]["name"] = self.name.get().strip()
        cfg["me"]["signature"] = "\n".join(p.strip() for p in self.sig.get().split("/")).strip()
        path.write_text(config.dump(cfg), encoding="utf-8")
        self.app.settings.load()
        self.app.after_config_saved()

    def page_done(self):
        self._title("You're all set", "Here's a good way to start:")
        for line in ("Open Cleanup and click Scan inbox to see which senders fill your inbox.",
                     "Pick a few obvious junk senders, tick Preview only, and check what KeepSift would keep.",
                     "Happy with it? Run it for real. Everything removed goes to Trash for 30 days first."):
            ttk.Label(self.body, text="→  " + line, wraplength=600, justify="left").pack(anchor="w", pady=4)
        ttk.Button(self.body, text="Open Cleanup now", style="Accent.TButton",
                   command=lambda: (self.destroy(), self.app.nb.select(self.app.cleanup))).pack(anchor="w", pady=(20, 0))
