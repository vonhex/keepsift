"""Cleanup tab: scan Gmail's categories by sender, pick senders, clean them out safely."""
import tkinter as tk
from tkinter import messagebox, ttk

from . import cleanup, config
from .llm import LLM
from .mail import Gmail
from .store import Store

HELP_FG = "#5f6368"
CAT_LABELS = {"promotions": "Promotions", "social": "Social", "updates": "Updates",
              "forums": "Forums", "purchases": "Purchases"}


class CleanupPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=6)
        self.app = app
        self.groups, self.shown = [], []
        try:
            c = config.load()["cleanup"]
        except BaseException:
            c = config.DEFAULTS["cleanup"]

        # 1. scan
        scan = ttk.LabelFrame(self, text="1. Scan", padding=8)
        scan.pack(fill="x")
        ttk.Label(scan, text="Gmail tabs:").pack(side="left")
        self.cats = {}
        for key, label in CAT_LABELS.items():
            var = tk.BooleanVar(value=key in c["categories"])
            ttk.Checkbutton(scan, text=label, variable=var).pack(side="left", padx=(6, 0))
            self.cats[key] = var
        ttk.Label(scan, text="   older than").pack(side="left")
        self.older = tk.IntVar(value=c["older_than_days"])
        ttk.Spinbox(scan, from_=0, to=3650, width=5, textvariable=self.older).pack(side="left", padx=4)
        ttk.Label(scan, text="days").pack(side="left")
        self.recheck = tk.BooleanVar(value=False)
        ttk.Checkbutton(scan, text="Re-check emails kept last time", variable=self.recheck).pack(side="left", padx=(12, 0))
        self.scan_btn = ttk.Button(scan, text="Scan inbox", style="Accent.TButton", command=self.scan)
        self.scan_btn.pack(side="left", padx=12)
        self.scan_msg = ttk.Label(scan, text="Reads senders only (fast). Nothing is changed.", style="Help.TLabel")
        self.scan_msg.pack(side="left")

        # 2. pick senders
        pick = ttk.LabelFrame(self, text="2. Pick senders to clean out (Ctrl/Shift-click for several)", padding=8)
        top = ttk.Frame(pick)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Filter").pack(side="left")
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *a: self.fill())
        ttk.Entry(top, textvariable=self.filter, width=30).pack(side="left", padx=4)
        ttk.Button(top, text="Select all shown", command=self.select_all).pack(side="left", padx=(8, 4))
        ttk.Button(top, text="Select none", command=lambda: self.tree.selection_set(())).pack(side="left")
        self.sel_msg = ttk.Label(top, text="")
        self.sel_msg.pack(side="right")

        frame = ttk.Frame(pick)
        frame.pack(fill="both", expand=True)
        cols = (("sender", 260), ("name", 170), ("emails", 70), ("tab", 90), ("newest", 90), ("example", 420))
        self.tree = ttk.Treeview(frame, columns=[c for c, _ in cols], show="headings", selectmode="extended")
        for name, width in cols:
            self.tree.heading(name, text=name.title(), command=lambda n=name: self.sort_by(n))
            self.tree.column(name, width=width, stretch=name == "example",
                             anchor="e" if name == "emails" else "w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.update_selection())
        self.sort_key, self.sort_rev = "emails", True

        # 3. clean
        act = ttk.LabelFrame(self, text="3. Clean", padding=8)
        act.pack(side="bottom", fill="x")  # packed before the list so it never gets squeezed off
        pick.pack(fill="both", expand=True, pady=6)
        self.action = tk.StringVar(value=c["action"])
        ttk.Radiobutton(act, text="Label 'To Delete' (you delete in Gmail)", variable=self.action,
                        value="label").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(act, text="Move to Trash (recoverable 30 days)", variable=self.action,
                        value="trash").grid(row=0, column=1, sticky="w", padx=12)
        self.use_model = tk.BooleanVar(value=c["model_check"])
        ttk.Checkbutton(act, text="Double-check each email with the model (~0.8 s each; off = rules only, much faster)",
                        variable=self.use_model).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.preview = tk.BooleanVar(value=False)
        ttk.Checkbutton(act, text="Preview only (check everything, change nothing)",
                        variable=self.preview).grid(row=2, column=0, columnspan=2, sticky="w")
        self.clean_btn = ttk.Button(act, text="Clean selected senders", style="Accent.TButton", command=self.clean)
        self.clean_btn.grid(row=0, column=2, rowspan=3, padx=16, sticky="ns")
        self.bar = ttk.Progressbar(act, mode="determinate", length=260)
        self.bar.grid(row=0, column=3, sticky="we")
        self.prog = ttk.Label(act, text="", style="Help.TLabel")
        self.prog.grid(row=1, column=3, rowspan=2, sticky="nw")
        act.columnconfigure(3, weight=1)
        ttk.Label(act, style="Good.TLabel", text=(
            "✓  Every email is safety-checked first: keys, activation links, codes, receipts, attachments and "
            "starred mail are always kept (Settings → Deletion).")).grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

        self.buttons = [self.scan_btn, self.clean_btn]

    # ---------- scan ----------

    def _gmail(self, cfg):
        a = cfg["account"]
        return Gmail(a["address"], a["password"], a["imap_host"], a["imap_port"])

    def scan(self):
        cats = [k for k, v in self.cats.items() if v.get()]
        if not cats:
            messagebox.showinfo("Scan", "Tick at least one Gmail tab to scan.")
            return
        try:
            older = max(0, int(self.older.get()))
        except (tk.TclError, ValueError):
            older = 0
        recheck = self.recheck.get()
        self.app.nb.select(self.app.tab_activity)

        def work():
            cfg = config.load()
            self.app.log(f"\n=== Cleanup scan: {', '.join(cats)}, older than {older} days ===")
            with self._gmail(cfg) as g:
                groups, done = cleanup.scan(cfg, Store(self.app.db()), g, cats, older, report=self.app.log,
                                            cancel=self.app.cancel, recheck_kept=recheck)
            total = sum(x["count"] for x in groups)
            self.app.log(f"{total} emails from {len(groups)} senders still to clean"
                         + (f" ({done} already handled earlier, hidden)" if done else ""))
            self.app.q.put(("call", lambda: self._scanned(groups, total)))

        self.app._start("Scanning", work)

    def _scanned(self, groups, total):
        self.groups = groups
        self.scan_msg.configure(text=f"{total:,} emails from {len(groups):,} senders")
        self.app.nb.select(self)
        self.fill()

    def fill(self):
        term = self.filter.get().lower().strip()
        keyf = {"sender": lambda g: g["sender"], "name": lambda g: (g["name"] or "").lower(),
                "emails": lambda g: g["count"], "tab": lambda g: g["category"],
                "newest": lambda g: g["newest"], "example": lambda g: g["example"].lower()}[self.sort_key]
        self.shown = sorted((g for g in self.groups if not term
                             or term in f"{g['sender']} {g['name']} {g['example']}".lower()),
                            key=keyf, reverse=self.sort_rev)
        self.tree.delete(*self.tree.get_children())
        for i, g in enumerate(self.shown):
            self.tree.insert("", "end", iid=str(i), values=(
                g["sender"], g["name"], g["count"], CAT_LABELS.get(g["category"], g["category"]),
                g["newest"], g["example"]))
        self.update_selection()

    def sort_by(self, col):
        self.sort_rev = not self.sort_rev if self.sort_key == col else col in ("emails", "newest")
        self.sort_key = col
        self.fill()

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())

    def selected(self):
        return [self.shown[int(i)] for i in self.tree.selection()]

    def update_selection(self):
        sel = self.selected()
        n = sum(g["count"] for g in sel)
        self.sel_msg.configure(text=f"Selected: {len(sel):,} senders, {n:,} emails" if sel else "")

    # ---------- clean ----------

    def clean(self):
        sel = self.selected()
        if not sel:
            messagebox.showinfo("Clean", "Select one or more senders first (or 'Select all shown').")
            return
        items = [h for g in sel for h in g["items"]]
        action, use_model, preview = self.action.get(), self.use_model.get(), self.preview.get()
        mins = len(items) * (0.8 if use_model else 0.05) / 60  # measured ~0.8 s/email with the model, 4 slots
        what = ("check them and change nothing (preview)" if preview else
                "move the safe ones to Trash (recoverable for 30 days)" if action == "trash" else
                "label the safe ones 'To Delete' for you to delete in Gmail")
        if not messagebox.askyesno("Clean out emails?", (
                f"{len(items):,} emails from {len(sel):,} senders.\n\nThis will {what}.\n"
                f"Protected emails are kept and labelled.\n\nRough time: {max(1, round(mins)):,} min "
                f"({'with' if use_model else 'without'} the model double-check). You can Stop any time and "
                f"continue later.\n\nGo ahead?")):
            return
        self.app.nb.select(self.app.tab_activity)
        self.bar.configure(maximum=len(items), value=0)

        def progress(done, total, counts, eta):
            text = (f"{done:,}/{total:,} checked · {counts['removed']:,} "
                    f"{'to remove' if preview else 'removed'} · {counts['kept']:,} kept"
                    + (f" · {counts['failed']} failed" if counts['failed'] else "")
                    + (f"\nabout {eta / 60:.0f} min left" if eta >= 60 else ""))
            self.app.q.put(("call", lambda: (self.bar.configure(value=done), self.prog.configure(text=text))))

        def work():
            cfg = config.load()
            self.app.log(f"\n=== Cleanup{' PREVIEW' if preview else ''}: {len(items)} emails from "
                         f"{len(sel)} senders, {action}, model check {'on' if use_model else 'off'} ===")
            store = Store(self.app.db())
            with self._gmail(cfg) as g:
                cleanup.clean(cfg, LLM(cfg["llm"], self.app.cancel), store, g, items, action, use_model,
                              preview, report=self.app.log, progress=progress, cancel=self.app.cancel)
            if not preview:
                handled = store.cleanup_seen(h["gm_msgid"] for h in items)
                self.app.q.put(("call", lambda: self._cleaned(handled)))

        self.app._start("Cleaning", work)

    def _cleaned(self, handled):
        for g in self.groups:
            g["items"] = [h for h in g["items"] if h["gm_msgid"] not in handled]
            g["count"] = len(g["items"])
        self.groups = [g for g in self.groups if g["count"]]
        total = sum(g["count"] for g in self.groups)
        self.scan_msg.configure(text=f"{total:,} emails from {len(self.groups):,} senders left")
        self.fill()
