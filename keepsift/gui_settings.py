"""Settings screen: every config option as a form control with an explanation. No TOML needed."""
import copy
import os
import re
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from .theme import ScrollText as ScrolledText

from . import agent, config, theme
from .config import CATEGORY_DEFAULTS, DEFAULTS, EFFORTS, ROOT, RULE_DEFAULTS
from .llm import LLM
from .mail import parse_message

UI = ("Segoe UI", 10)
MONO = theme.MONO
HELP_FG = "#5f6368"

YES_NO_PRIORITY = [("", "Let the model decide"), ("urgent", "Always urgent"),
                   ("normal", "Always normal"), ("low", "Always low")]

ALWAYS_PROTECTED = (
    "Always protected, whatever the settings above say: product, license, serial and activation keys; "
    "game/CD/Steam keys, redeem codes and gift cards; anything shaped like a key (ABCDE-12345-FGHIJ); "
    "activation, verification, sign-in, download, reset and invite links (including hidden link targets "
    "in HTML emails); one-time codes, 2FA and recovery codes, password resets and security alerts; "
    "anything the model says has lasting value; and emails that are VIP, urgent, suspicious or need a reply. "
    "A rule can't skip these checks either: if a rule sends an email to a deleting category, the model "
    "still checks it."
)

# (key, label, kind, help, opts)
# kinds: str, text, list (one per line), int/float (opts = min, max, step), bool, choice/combo (opts = values)
PAGES = {
    "Account": [
        ("account.query", "Which emails to look at", "str",
         "A Gmail search, exactly like the Gmail search box. Examples: in:inbox newer_than:3d  ·  "
         "in:inbox is:unread  ·  in:inbox -category:promotions"),
        ("account.max_per_run", "Max emails per run", "int",
         "Caps how many new emails one run handles, so a full inbox doesn't take forever.", (1, 1000, 1)),
        ("account.batch_size", "Batch size", "int",
         "Emails are downloaded, analysed and filed this many at a time. Progress is saved after each "
         "batch, so a big run can be stopped and resumed. 20 is a good default.", (1, 500, 1)),
        ("account.order", "When there are more than that, do first", "choice",
         "", [("newest", "Newest emails"), ("oldest", "Oldest emails")]),
        ("account.max_fetch_mb", "Max download per email (MB)", "int",
         "Emails bigger than this are cut off. Only attachments are lost; the text is near the start.", (1, 50, 1)),
        ("account.imap_host", "IMAP server", "str", "Leave as imap.gmail.com for Gmail."),
        ("account.imap_port", "IMAP port", "int", "", (1, 65535, 1)),
        ("account.smtp_host", "SMTP server", "str", "Only used for automatically sent replies."),
        ("account.smtp_port", "SMTP port", "int", "", (1, 65535, 1)),
    ],
    "Model": [
        ("llm.base_url", "Server address", "str", "Your local OpenAI-compatible server, ending in /v1."),
        ("llm.model", "Model", "combo", "Click 'Detect models' below to list what the server offers."),
        ("llm.api_key", "API key", "str", "Only if your server needs one. Leave blank otherwise."),
        ("llm.classify_effort", "Thinking effort when sorting", "choice",
         "How hard the model thinks before sorting an email. 'low' is quick and accurate enough for most mail.",
         EFFORTS),
        ("llm.draft_effort", "Thinking effort when writing replies", "choice",
         "Higher gives more careful replies but takes longer.", EFFORTS),
        ("llm.temperature", "Creativity (temperature)", "float",
         "0 = consistent, predictable answers (recommended). Higher = more varied wording.", (0, 2, 0.1)),
        ("llm.classify_max_tokens", "Token budget for sorting", "int",
         "Includes thinking. Raise it if the log shows 'hit max_tokens'.", (500, 65536, 500)),
        ("llm.draft_max_tokens", "Token budget for replies", "int", "Same, for drafting.", (500, 65536, 500)),
        ("llm.max_body_chars", "Max email length sent to the model", "int",
         "Longer emails are cut to this many characters. Long threads mostly repeat old quoted text.",
         (1000, 500000, 1000)),
        ("llm.parallel", "Emails analysed at once", "int",
         "Match your server's slot count (yours has 4).", (1, 32, 1)),
        ("llm.timeout", "Timeout (seconds)", "int", "How long to wait for one answer.", (10, 3600, 10)),
        ("llm.retries", "Retries", "int", "Attempts after a failed request.", (0, 10, 1)),
    ],
    "You & style": [
        ("me.name", "Your name", "str", "So the model knows who it is writing as."),
        ("me.about", "About you", "text",
         "Context for sorting and replies: your job, projects, the people you deal with, and things you "
         "never agree to by email. The more specific, the better.", 6),
        ("me.style", "How your replies should sound", "text",
         "e.g. Friendly, direct and brief. Plain text. No corporate filler.", 3),
        ("me.signature", "Sign-off", "text", "Added to the end of every draft exactly as written.", 3),
        ("me.language", "Reply language", "str",
         "Leave blank to answer in whatever language each email is written in, or name one (e.g. English)."),
    ],
    "Sorting": [
        ("triage.vip_senders", "VIP senders", "list",
         "Always marked urgent and never archived. One per line; wildcards work: boss@work.com, *@family.org"),
        ("triage.min_confidence_for_actions", "Minimum confidence to act", "float",
         "If the model is less sure than this (0 to 1), the email gets the Review label and is never "
         "archived or marked read.", (0, 1, 0.05)),
        ("triage.keep_needs_reply_visible", "Never archive or mark read emails that need a reply", "bool", ""),
        ("triage.keep_urgent_visible", "Never archive or mark read urgent emails", "bool", ""),
        ("triage.keep_suspicious_visible", "Never archive or mark read suspicious emails", "bool",
         "So you see phishing warnings instead of having them silently filed away."),
        ("triage.reply_to_bulk", "Write drafts for newsletters and mailing lists", "bool",
         "Normally skipped: nobody reads replies to a newsletter."),
        ("triage.reply_to_noreply", "Write drafts for no-reply addresses", "bool", "Normally skipped."),
    ],
    "Labels & stars": [
        ("labels.enabled", "Add Gmail labels", "bool", "Turn off to sort without labelling anything."),
        ("labels.prefix", "Label folder", "str",
         "Labels go under this folder, e.g. AI gives AI/Work, AI/Finance. Leave blank for top-level labels."),
        ("labels.needs_reply", "Label emails that need a reply", "bool", ""),
        ("labels.needs_reply_name", "  Its name", "str", ""),
        ("labels.suspicious_name", "Label for suspicious emails", "str", ""),
        ("labels.review_name", "Label for low-confidence emails", "str", ""),
        ("labels.drafted_name", "Label when a draft was written", "str", ""),
        ("labels.auto_replied_name", "Label when a reply was sent automatically", "str", ""),
        ("labels.processed", "Label every processed email", "bool", "Handy for searching what the tool has seen."),
        ("labels.processed_name", "  Its name", "str", ""),
        ("labels.star_urgent", "Star urgent emails", "bool", ""),
        ("labels.star_needs_reply", "Star emails that need a reply", "bool", ""),
    ],
    "Replies & sending": [
        ("safety.quote_original", "Quote the original email under drafts", "bool", ""),
        ("safety.quote_max_lines", "  Max quoted lines", "int", "", (0, 1000, 10)),
        ("safety.reply_all", "Reply to everyone (reply-all)", "bool",
         "Off = reply only to the sender. With auto-send, every recipient must be on the allowlist."),
        ("safety.auto_send", "Allow sending replies without my review", "bool",
         "Master switch. Even when on, a reply is only sent if its category is set to auto-send, every "
         "recipient is on the allowlist, the draft has no [CONFIRM] gaps, and every check below passes. "
         "Everything else becomes a draft."),
        ("safety.send_allowlist", "Who may get automatic replies", "list",
         "One per line; wildcards work: *@mycompany.com, partner@example.com"),
        ("safety.send_blocklist", "Never auto-send to", "list", "Overrides the allowlist."),
        ("safety.min_confidence_to_send", "Minimum confidence to auto-send", "float", "0 to 1.", (0, 1, 0.05)),
        ("safety.max_sends_per_hour", "Max automatic replies per hour", "int", "", (0, 1000, 1)),
        ("safety.max_sends_per_day", "Max automatic replies per day", "int", "", (0, 10000, 1)),
        ("safety.dry_run", "Command line runs preview by default", "bool",
         "Affects 'python -m keepsift run/watch' without --live. The GUI buttons always say which they do."),
    ],
    "Deletion": [
        ("deletion.enabled", "Allow sorting emails for deletion", "bool",
         "Only categories with 'Sort for deletion' ticked (Categories page) are ever considered."),
        ("deletion.action", "What to do with deletable emails", "choice",
         "Labelling is the safe default: you review the label in Gmail and delete in bulk. Trash is "
         "recoverable for 30 days. Nothing is ever permanently deleted.",
         [("label", "Label them 'To Delete' for me to review"), ("trash", "Move them to Gmail Trash")]),
        ("deletion.label_name", "  'To Delete' label name", "str", ""),
        ("deletion.archive_marked", "  Also remove labelled emails from the inbox", "bool", ""),
        ("deletion.min_confidence", "Minimum confidence to delete", "float",
         "The model must be at least this sure of the category (0 to 1).", (0, 1, 0.05)),
        ("deletion.protect_purchases", "Protect receipts, orders, invoices, tickets, warranties and tax documents",
         "bool", ""),
        ("deletion.protect_attachments", "Protect emails with attachments", "bool", ""),
        ("deletion.protect_starred", "Protect starred emails", "bool", ""),
        ("deletion.extra_protect_keywords", "Also protect emails containing", "list",
         "One word or phrase per line, e.g. your bank's name, 'tracking number', 'membership'."),
        ("deletion.protect_senders", "Never delete from these senders", "list",
         "One per line; wildcards work: *@mybank.com"),
        ("deletion.label_protected", "Label emails that were protected from deletion", "bool",
         "So you can see what the safety net caught and why (details in History)."),
        ("deletion.protected_label_name", "  Its name", "str", ""),
    ],
    "Cleanup": [
        ("cleanup.categories", "Gmail tabs ticked by default", "list",
         "One per line, from: promotions, social, updates, forums, purchases."),
        ("cleanup.older_than_days", "Only emails older than (days)", "int",
         "Leaves recent mail alone. 0 = any age.", (0, 3650, 1)),
        ("cleanup.action", "Default action", "choice", "",
         [("label", "Label 'To Delete' for me to review"), ("trash", "Move to Gmail Trash")]),
        ("cleanup.model_check", "Double-check each email with the model by default", "bool",
         "Safer (catches personal mail, receipts the rules can't see) but ~0.8 s per email. "
         "Off = keyword/link rules only, a few minutes for thousands of emails."),
        ("cleanup.model_effort", "Model thinking for the double-check", "choice",
         "'none' is fastest and gave the same answers as 'low' in testing.", EFFORTS),
        ("cleanup.model_chars", "Characters of each email the model reads", "int", "",
         (500, 50000, 500)),
        ("cleanup.max_size_kb", "Keep emails bigger than (KB)", "int",
         "Bigger emails are kept without downloading them, so nothing is removed unchecked. "
         "Also limits how much is downloaded (Gmail allows roughly 2.5 GB per day over IMAP).",
         (50, 25000, 50)),
        ("cleanup.batch_size", "Batch size", "int", "Emails downloaded and checked at a time.", (1, 500, 5)),
        ("cleanup.label_kept", "Label kept emails 'Kept - Important'", "bool", ""),
    ],
    "Prompts": [
        ("prompts.classify_extra", "Extra instructions for sorting", "text",
         "Added to the built-in instructions. e.g. 'Anything from my landlord is urgent. "
         "School newsletters are Personal, not Promotions.'", 4),
        ("prompts.draft_extra", "Extra instructions for replies", "text",
         "e.g. 'Never mention prices. Suggest a quick call when a topic is complicated.'", 4),
        ("prompts.classify_override", "Replace the sorting prompt entirely (advanced)", "text",
         "Leave blank to use the built-in prompt. Placeholders: {who} {about} {categories} {extra} {untrusted}", 8),
        ("prompts.draft_override", "Replace the reply prompt entirely (advanced)", "text",
         "Leave blank to use the built-in prompt. Placeholders: {who} {about} {style} {language} "
         "{category_instructions} {signature} {extra} {untrusted}", 8),
    ],
    "Schedule": [
        ("watch.interval_minutes", "Check for new mail every (minutes)", "int",
         "Used by Watch, here and on the command line.", (1, 1440, 1)),
        ("watch.quiet_start", "Quiet hours from (HH:MM)", "str",
         "Watch skips runs between these times, e.g. 22:00 to 07:00. Leave both blank to always run."),
        ("watch.quiet_end", "Quiet hours until (HH:MM)", "str", ""),
    ],
}

CATEGORY_FIELDS = [
    ("name", "Name", "str", ""),
    ("description", "What belongs here", "text",
     "The model reads this to decide. Be concrete: who it's from, what it's about.", 3),
    ("reply", "Replies", "choice", "",
     [("none", "Don't reply"), ("draft", "Write a draft for me to review"),
      ("send", "Write a reply and auto-send it when allowed")]),
    ("draft_instructions", "How to reply to these", "text",
     "Optional, e.g. 'Be formal. Never agree to a deadline; propose one with a [CONFIRM] placeholder.'", 3),
    ("priority", "Priority", "choice", "", YES_NO_PRIORITY),
    ("label", "Add a Gmail label", "bool", ""),
    ("label_name", "  Label name", "str", "Blank = the category name."),
    ("star", "Star these", "bool", ""),
    ("mark_read", "Mark as read", "bool", ""),
    ("delete", "Sort for deletion", "bool",
     "Only if deletion is allowed (Deletion page). Every email still passes the safety checks first."),
    ("archive", "Archive (remove from inbox)", "bool",
     "Emails that need a reply, are urgent or suspicious stay in the inbox regardless (see Sorting)."),
]

RULE_FIELDS = [
    ("from", "Sender is", "str", "Wildcards work: *@github.com, alerts@*"),
    ("to", "Sent to", "str", "Matches any To/Cc address, e.g. you+shopping@gmail.com"),
    ("subject", "Subject contains", "str", "Plain text or a regular expression, ignores case: invoice|receipt"),
    ("body", "Body contains", "str", "Same, searched in the email text."),
    ("ignore", "Ignore these completely", "bool", "No model, no labels, nothing. The category below is unused."),
    ("category", "Put in category", "choice", "", []),
    ("priority", "Priority", "choice", "",
     [("", "Low (default)"), ("urgent", "Urgent"), ("normal", "Normal"), ("low", "Low")]),
]


class Field:
    def __init__(self, parent, row, label, kind, help="", opts=None):
        self.label, self.kind, self.opts = label.strip(), kind, opts
        self.var = None
        if kind == "bool":
            self.var = tk.BooleanVar()
            ttk.Checkbutton(parent, text=label.strip(), variable=self.var).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(8, 0),
                padx=(20, 0) if label.startswith(" ") else 0)
        else:
            ttk.Label(parent, text=label.strip()).grid(
                row=row, column=0, sticky="nw", pady=(9, 0), padx=(20 if label.startswith(" ") else 0, 12))
            if kind in ("text", "list"):
                self.w = tk.Text(parent, height=opts or 3, width=72, wrap="word", font=UI,
                                 relief="solid", borderwidth=1, undo=True)
            elif kind in ("choice", "combo"):
                self.var = tk.StringVar()
                self.w = ttk.Combobox(parent, textvariable=self.var, width=44,
                                      state="readonly" if kind == "choice" else "normal")
                self.set_choices(opts or [])
            elif kind in ("int", "float"):
                lo, hi, step = opts
                self.var = tk.StringVar()
                self.w = ttk.Spinbox(parent, from_=lo, to=hi, increment=step, textvariable=self.var, width=12)
            else:
                self.var = tk.StringVar()
                self.w = ttk.Entry(parent, textvariable=self.var, width=60)
            self.w.grid(row=row, column=1, sticky="w", pady=(8, 0))
        if help:
            ttk.Label(parent, text=help, style="Help.TLabel", wraplength=640, justify="left").grid(
                row=row + 1, column=1 if kind != "bool" else 0, columnspan=1 if kind != "bool" else 2,
                sticky="w", padx=(22, 0) if kind == "bool" else 0)

    def set_choices(self, opts):
        pairs = [o if isinstance(o, tuple) else (o, o) for o in opts]
        self.to_label = dict(pairs)
        self.to_value = {lbl: val for val, lbl in pairs}
        self.w.configure(values=[lbl for _, lbl in pairs])

    def set(self, value):
        if self.kind in ("text", "list"):
            self.w.delete("1.0", "end")
            self.w.insert("1.0", "\n".join(value) if self.kind == "list" else (value or ""))
            self.w.edit_reset()
        elif self.kind == "bool":
            self.var.set(bool(value))
        elif self.kind in ("choice", "combo"):
            self.var.set(self.to_label.get(value, "" if value is None else str(value)))
        else:
            self.var.set("" if value is None else str(value))

    def get(self):
        if self.kind == "text":
            return self.w.get("1.0", "end-1c").strip()
        if self.kind == "list":
            return [x.strip() for x in re.split(r"[\n,]", self.w.get("1.0", "end-1c")) if x.strip()]
        if self.kind == "bool":
            return self.var.get()
        raw = self.var.get().strip()
        if self.kind in ("choice", "combo"):
            return self.to_value.get(raw, raw)
        try:
            if self.kind == "int":
                return int(float(raw))
            if self.kind == "float":
                return float(raw)
        except ValueError:
            raise ValueError(f"'{self.label}' needs a number (got '{raw}').")
        return raw


class ScrollFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.inner = ttk.Frame(canvas, padding=(14, 4, 14, 14))
        self.inner.columnconfigure(1, weight=1)
        self.inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        wheel = lambda e: canvas.yview_scroll(int(-e.delta / 120), "units")
        self.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", wheel))
        self.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        self.canvas = canvas


def _heading(parent, row, title, intro=""):
    ttk.Label(parent, text=title, style="H2.TLabel").grid(row=row, column=0, columnspan=2, sticky="w")
    if intro:
        ttk.Label(parent, text=intro, style="Help.TLabel", wraplength=760, justify="left").grid(
            row=row + 1, column=0, columnspan=2, sticky="w", pady=(2, 4))
    return row + 2


class ListEditor(ttk.Frame):
    """Edit a list of records (categories, rules): list on the left, form on the right."""

    def __init__(self, parent, title, intro, fields, defaults, title_fn):
        super().__init__(parent)
        self.defaults, self.title_fn = defaults, title_fn
        self.items, self.cur = [], None

        head = ttk.Frame(self, padding=(14, 4, 14, 0))
        head.pack(fill="x")
        _heading(head, 0, title, intro)

        body = ttk.Frame(self, padding=(14, 6, 0, 0))
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="y")
        self.lb = tk.Listbox(left, width=30, font=UI, exportselection=False, activestyle="none")
        self.lb.pack(fill="y", expand=True)
        self.lb.bind("<<ListboxSelect>>", lambda e: self._select())
        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(6, 0))
        for text, cmd in (("Add", self.add), ("Copy", self.duplicate), ("Delete", self.delete),
                          ("▲", lambda: self.move(-1)), ("▼", lambda: self.move(1))):
            ttk.Button(btns, text=text, command=cmd, width=6 if len(text) > 1 else 3).pack(side="left", padx=(0, 3))

        sf = ScrollFrame(body)
        sf.pack(side="left", fill="both", expand=True)
        self.fields = {}
        for i, (key, label, kind, help, *opts) in enumerate(fields):
            self.fields[key] = Field(sf.inner, i * 2, label, kind, help, opts[0] if opts else None)

    def load(self, items):
        self.items = [{**self.defaults, **copy.deepcopy(i)} for i in items]
        self.cur = None
        self._redraw()
        if self.items:
            self._show(0)

    def get_items(self):
        self._commit()
        return copy.deepcopy(self.items)

    def _redraw(self):
        self.lb.delete(0, "end")
        for item in self.items:
            self.lb.insert("end", self.title_fn(item))

    def _commit(self):
        if self.cur is not None and self.cur < len(self.items):
            for key, f in self.fields.items():
                self.items[self.cur][key] = f.get()
            self.lb.delete(self.cur)
            self.lb.insert(self.cur, self.title_fn(self.items[self.cur]))

    def _show(self, idx):
        self.cur = idx
        for key, f in self.fields.items():
            f.set(self.items[idx].get(key, self.defaults.get(key)))
        self.lb.selection_clear(0, "end")
        self.lb.selection_set(idx)
        self.lb.see(idx)

    def _select(self):
        sel = self.lb.curselection()
        if sel and sel[0] != self.cur:
            self._commit()
            self._show(sel[0])

    def add(self, item=None):
        self._commit()
        self.items.append(item or dict(self.defaults))
        self._redraw()
        self._show(len(self.items) - 1)

    def duplicate(self):
        if self.cur is not None:
            self._commit()
            self.add(copy.deepcopy(self.items[self.cur]))

    def delete(self):
        if self.cur is None:
            return
        del self.items[self.cur]
        self.cur = None
        self._redraw()
        if self.items:
            self._show(0)
        else:
            for f in self.fields.values():
                f.set(None)

    def move(self, step):
        if self.cur is None:
            return
        self._commit()
        j = self.cur + step
        if 0 <= j < len(self.items):
            self.items[self.cur], self.items[j] = self.items[j], self.items[self.cur]
            self._redraw()
            self._show(j)


class SettingsPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.fields = {}       # "section.key" -> Field
        self.page_keys = {}    # page name -> [keys]
        self.pages = {}

        bar = ttk.Frame(self, padding=(8, 8, 8, 6))
        bar.pack(fill="x")
        ttk.Button(bar, text="Save settings", style="Accent.TButton", command=self.save).pack(side="left")
        ttk.Button(bar, text="Undo unsaved changes", command=self.load).pack(side="left", padx=6)
        self.defaults_btn = ttk.Button(bar, text="Restore this page's defaults", command=self.restore_page)
        self.defaults_btn.pack(side="left")
        self.msg = ttk.Label(bar, text="", style="Help.TLabel")
        self.msg.pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.nav = tk.Listbox(body, width=20, font=("Segoe UI", 11), exportselection=False,
                              activestyle="none", borderwidth=0, highlightthickness=0)
        self.nav.pack(side="left", fill="y", padx=(8, 0), pady=4)
        self.nav.bind("<<ListboxSelect>>", lambda e: self._nav())
        ttk.Separator(body, orient="vertical").pack(side="left", fill="y", padx=6)
        self.content = ttk.Frame(body)
        self.content.pack(side="left", fill="both", expand=True)

        for name, specs in PAGES.items():
            sf = ScrollFrame(self.content)
            row = _heading(sf.inner, 0, name)
            if name == "Account":
                row = self._account_box(sf.inner, row)
            self.page_keys[name] = []
            for key, label, kind, help, *opts in specs:
                self.fields[key] = Field(sf.inner, row, label, kind, help, opts[0] if opts else None)
                self.page_keys[name].append(key)
                row += 2
            if name == "Model":
                self._model_buttons(sf.inner, row)
            if name == "Deletion":
                ttk.Label(sf.inner, text=ALWAYS_PROTECTED, style="Good.TLabel", wraplength=760,
                          justify="left").grid(row=row, column=0, columnspan=2, sticky="w", pady=(14, 0))
            if name == "Prompts":
                ttk.Button(sf.inner, text="Show the exact prompts the model will get",
                           command=self.preview_prompts).grid(row=row, column=1, sticky="w", pady=12)
            self._add_page(name, sf)

        self.cats = ListEditor(
            self.content, "Categories",
            "Every email lands in exactly one category. The model picks it using each category's "
            "description, so describe them clearly. Order doesn't matter, except the last one is the fallback.",
            CATEGORY_FIELDS, CATEGORY_DEFAULTS, lambda c: c["name"] or "(unnamed)")
        self._add_page("Categories", self.cats)

        self.rules = ListEditor(
            self.content, "Rules",
            "Rules run before the model, top to bottom. The first rule whose filled-in conditions all match "
            "decides the category instantly, without asking the model. Good for senders you always treat the same.",
            RULE_FIELDS, RULE_DEFAULTS, self._rule_title)
        self.rules.lb.bind("<FocusIn>", lambda e: self._refresh_rule_categories(), add="+")
        self._add_page("Rules", self.rules)

        self._add_page("Advanced (raw file)", self._raw_page())
        self.load()
        self.nav.selection_set(0)
        self._nav()

    # ---------- pages ----------

    def _add_page(self, name, frame):
        self.pages[name] = frame
        self.nav.insert("end", "  " + name)

    def _nav(self):
        sel = self.nav.curselection()
        if not sel:
            return
        name = self.nav.get(sel[0]).strip()
        if name == "Rules":
            self._refresh_rule_categories()
        for f in self.pages.values():
            f.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.current = name
        self.defaults_btn.configure(state="normal" if name in PAGES else "disabled")

    def _account_box(self, parent, row):
        box = ttk.LabelFrame(parent, text="Gmail login (saved to .env, separately from other settings)", padding=10)
        box.grid(row=row, column=0, columnspan=2, sticky="we", pady=(6, 6))
        config.load_env(ROOT / ".env")
        self.addr = tk.StringVar(value=os.environ.get("GMAIL_ADDRESS", ""))
        self.pw = tk.StringVar(value=os.environ.get("GMAIL_APP_PASSWORD", ""))
        ttk.Label(box, text="Gmail address").grid(row=0, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.addr, width=40).grid(row=0, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(box, text="App password").grid(row=1, column=0, sticky="w")
        pw = ttk.Entry(box, textvariable=self.pw, width=40, show="•")
        pw.grid(row=1, column=1, sticky="w", padx=6, pady=2)
        show = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Show", variable=show,
                        command=lambda: pw.configure(show="" if show.get() else "•")).grid(row=1, column=2)
        ttk.Button(box, text="Save login", command=self.save_env).grid(row=0, column=3, rowspan=2, padx=12)
        link = ttk.Label(box, text="How to create an app password (needs 2-Step Verification)",
                         style="Link.TLabel", cursor="hand2")
        link.grid(row=2, column=1, columnspan=3, sticky="w", padx=6)
        link.bind("<Button-1>", lambda e: webbrowser.open("https://myaccount.google.com/apppasswords"))
        return row + 1

    def _model_buttons(self, parent, row):
        f = ttk.Frame(parent)
        f.grid(row=row, column=1, sticky="w", pady=12)
        ttk.Button(f, text="Detect models", command=self.detect_models).pack(side="left")
        ttk.Button(f, text="Test with a sample email", command=self.test_model).pack(side="left", padx=6)

    def _raw_page(self):
        f = ttk.Frame(self.content, padding=(14, 4, 14, 14))
        _heading(f, 0, "Advanced (raw file)",
                 "The same settings as config.toml text. Only needed for bulk edits; the other pages are easier. "
                 "Saving here replaces everything above.")
        bar = ttk.Frame(f)
        bar.grid(row=2, column=0, sticky="w", pady=(0, 6))
        ttk.Button(bar, text="Save file", command=self.save_raw).pack(side="left")
        ttk.Button(bar, text="Reload file", command=self.load).pack(side="left", padx=6)
        self.raw = ScrolledText(f, font=MONO, wrap="none", undo=True)
        self.raw.grid(row=3, column=0, sticky="nsew")
        f.rowconfigure(3, weight=1)
        f.columnconfigure(0, weight=1)
        return f

    def _rule_title(self, r):
        cond = " ".join(x for x in (r["from"], r["to"] and f"to:{r['to']}",
                                    r["subject"] and f"subj:{r['subject']}",
                                    r["body"] and f"body:{r['body']}") if x)
        return f"{cond or '(empty)'} → {'ignore' if r['ignore'] else r['category'] or '?'}"

    def _refresh_rule_categories(self):
        names = [c["name"] for c in self.cats.get_items() if c["name"]]
        self.rules.fields["category"].set_choices(names)

    # ---------- load / save ----------

    def load(self):
        text = (ROOT / "config.toml").read_text(encoding="utf-8")
        try:
            cfg = config.check_text(text)
        except SystemExit as e:
            messagebox.showerror("config.toml has a problem", f"{e}\n\nFix it on the Advanced page.")
            cfg = copy.deepcopy(DEFAULTS)
        for key, f in self.fields.items():
            sec, k = key.split(".")
            f.set(cfg[sec][k])
        self.cats.load(cfg["category"])
        self._refresh_rule_categories()
        self.rules.load(cfg["rule"])
        self.raw.delete("1.0", "end")
        self.raw.insert("1.0", text)
        self.raw.edit_reset()
        self.msg.configure(text="Loaded config.toml")

    def collect(self):
        """Current form values as a validated config dict. Raises ValueError/SystemExit."""
        cfg = copy.deepcopy(DEFAULTS)
        for key, f in self.fields.items():
            sec, k = key.split(".")
            cfg[sec][k] = f.get()
        cfg["category"] = self.cats.get_items()
        cfg["rule"] = self.rules.get_items()
        text = config.dump(cfg)
        return config.check_text(text), text

    def save(self):
        try:
            _, text = self.collect()
        except (ValueError, SystemExit) as e:
            messagebox.showerror("Can't save yet", str(e))
            return
        (ROOT / "config.toml").write_text(text, encoding="utf-8")
        self.load()
        self.msg.configure(text="Saved ✓")
        self.app.after_config_saved()

    def save_raw(self):
        text = self.raw.get("1.0", "end-1c")
        try:
            config.check_text(text)
        except SystemExit as e:
            messagebox.showerror("Can't save", str(e))
            return
        (ROOT / "config.toml").write_text(text, encoding="utf-8")
        self.load()
        self.msg.configure(text="Saved ✓")
        self.app.after_config_saved()

    def restore_page(self):
        keys = self.page_keys.get(self.current, [])
        if keys and messagebox.askyesno("Restore defaults", f"Reset everything on '{self.current}' to defaults?\n"
                                        "(Nothing is saved until you click Save settings.)"):
            for key in keys:
                sec, k = key.split(".")
                self.fields[key].set(DEFAULTS[sec][k])

    def save_env(self):
        addr, pw = self.addr.get().strip(), self.pw.get().strip()
        path = ROOT / ".env"
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        keep = [l for l in lines if not l.strip().startswith(("GMAIL_ADDRESS=", "GMAIL_APP_PASSWORD="))]
        path.write_text("\n".join(keep + [f"GMAIL_ADDRESS={addr}", f"GMAIL_APP_PASSWORD={pw}"]) + "\n",
                        encoding="utf-8")
        os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"] = addr, pw
        self.msg.configure(text="Login saved ✓")

    # ---------- helpers that talk to the model ----------

    def _bg(self, fn, done):
        """Run fn in a thread, then done(result, error) back on the UI thread."""
        box = {}

        def work():
            try:
                box["r"] = fn()
            except BaseException as e:
                box["e"] = e

        t = threading.Thread(target=work, daemon=True)
        t.start()

        def poll():
            if t.is_alive():
                self.after(100, poll)
            else:
                done(box.get("r"), box.get("e"))

        poll()

    def _llm_cfg(self):
        llm = copy.deepcopy(DEFAULTS["llm"])
        for key in llm:
            llm[key] = self.fields[f"llm.{key}"].get()
        return llm

    def detect_models(self):
        try:
            llm = LLM(self._llm_cfg())
        except ValueError as e:
            messagebox.showerror("Model settings", str(e))
            return
        self.msg.configure(text="Asking the server...")

        def done(models, err):
            if err:
                self.msg.configure(text="")
                messagebox.showerror("Couldn't reach the server", str(err))
                return
            self.fields["llm.model"].set_choices(models)
            if self.fields["llm.model"].get() not in models and models:
                self.fields["llm.model"].set(models[0])
            self.msg.configure(text=f"Found {len(models)} model(s)")

        self._bg(llm.ping, done)

    def test_model(self):
        try:
            cfg, _ = self.collect()
        except (ValueError, SystemExit) as e:
            messagebox.showerror("Fix settings first", str(e))
            return
        cfg["account"]["address"] = os.environ.get("GMAIL_ADDRESS", "")
        sample = config.SAMPLES / "1-coworker.eml"
        lines = []
        self.msg.configure(text="Testing with your unsaved settings...")

        def done(_, err):
            self.msg.configure(text="")
            if err:
                messagebox.showerror("Test failed", str(err))
            else:
                self._show_text("Model test (sample: coworker asking for a review)", "\n".join(lines))

        self._bg(lambda: agent.explain(LLM(cfg["llm"]), cfg, parse_message(sample.read_bytes()),
                                       True, lines.append), done)

    def preview_prompts(self):
        try:
            cfg, _ = self.collect()
        except (ValueError, SystemExit) as e:
            messagebox.showerror("Fix settings first", str(e))
            return
        cfg["account"]["address"] = os.environ.get("GMAIL_ADDRESS", "")
        cat = next((c for c in cfg["category"] if c["reply"] != "none"), cfg["category"][0])
        text = ("=== SORTING PROMPT ===\n\n" + agent.classify_prompt(cfg)
                + f"\n\n\n=== REPLY PROMPT (for category '{cat['name']}') ===\n\n" + agent.draft_prompt(cfg, cat))
        self._show_text("Prompts the model will get", text)

    def _show_text(self, title, text):
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("900x620")
        st = ScrolledText(win, font=MONO, wrap="word")
        st.pack(fill="both", expand=True, padx=12, pady=12)
        st.insert("1.0", text)
        st.configure(state="disabled")
        theme.recolor(win)
