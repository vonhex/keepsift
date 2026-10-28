"""Desktop app: python -m keepsift.gui"""
import json
import os
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import agent, config, theme
from .config import ROOT
from .gui_cleanup import CleanupPanel
from .gui_settings import SettingsPanel
from .llm import LLM
from .mail import Gmail, parse_message
from .store import Store
from .theme import ScrollText

APP_NAME = "KeepSift"
TAGLINE = "Local-AI inbox cleanup that never loses what matters"
DB = config.db_path()
ACTIVITY_LOG = ROOT / "data" / "activity.log"


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_NAME)
        root.geometry("1220x800")
        root.minsize(940, 600)
        root.protocol("WM_DELETE_WINDOW", self.close)
        (ROOT / "data").mkdir(exist_ok=True)
        theme.set_icon(root)

        self.q = queue.Queue()
        self.busy = False
        self.watch_stop = None
        self.cancel = threading.Event()  # set by Stop; checked between emails
        self.live_confirmed = False
        self.history_rows = []

        self._build_header()
        self.status = ttk.Label(root, text="Ready", anchor="w", padding=(16, 6), style="Help.TLabel")
        self.status.pack(side="bottom", fill="x")
        ttk.Separator(root).pack(side="bottom", fill="x")
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=14, pady=(10, 6))
        self.buttons, self.try_btns = [], []
        self._build_home()
        self.cleanup = CleanupPanel(self.nb, self)
        self.nb.add(self.cleanup, text="  Cleanup  ")
        self._build_activity()
        self._build_history()
        self._build_try()
        self.try_btns += self.cleanup.buttons  # disabled while busy, like the other actions
        self.settings = SettingsPanel(self.nb, self)
        self.nb.add(self.settings, text="  Settings  ")

        theme.recolor(root)
        self.retheme()
        self.refresh_mode()
        self.refresh_history()
        try:
            self.interval.set(config.load()["watch"]["interval_minutes"])
        except BaseException:
            pass
        root.after(100, self._drain)
        root.after(300, self.check_model_quietly)
        if not config.is_configured():
            root.after(400, self.open_setup)

    # ---------- layout ----------

    def _build_header(self):
        head = ttk.Frame(self.root, padding=(18, 12, 18, 10))
        head.pack(fill="x")
        try:
            self.logo = tk.PhotoImage(file=str(config.ASSETS / "icon-40.png"))
            ttk.Label(head, image=self.logo).pack(side="left", padx=(0, 12))
        except tk.TclError:
            pass
        titles = ttk.Frame(head)
        titles.pack(side="left")
        ttk.Label(titles, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, text=TAGLINE, style="Subtitle.TLabel").pack(anchor="w")

        right = ttk.Frame(head)
        right.pack(side="right")
        self.theme_btn = ttk.Button(right, text="", width=8, command=self.toggle_theme)
        if theme.can_switch():
            self.theme_btn.pack(side="right", padx=(10, 0))
        self.stop_btn = ttk.Button(right, text="■  Stop", style="Stop.TButton", command=self.stop,
                                   state="disabled")
        self.stop_btn.pack(side="right", padx=(10, 0))
        self.root.bind("<Escape>", lambda e: self.stop())
        pills = ttk.Frame(right)
        pills.pack(side="right")
        self.model_pill = ttk.Label(pills, text="●  Model: checking...", style="Help.TLabel")
        self.model_pill.pack(anchor="e")
        self.gmail_pill = ttk.Label(pills, text="", style="Help.TLabel")
        self.gmail_pill.pack(anchor="e")
        self.mode_lbl = ttk.Label(pills, text="", style="Help.TLabel")
        self.mode_lbl.pack(anchor="e")
        ttk.Separator(self.root).pack(fill="x")

    def _card(self, parent, title, text):
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        ttk.Label(card, text=title, style="H2.TLabel").pack(anchor="w")
        ttk.Label(card, text=text, style="Help.TLabel", wraplength=470, justify="left").pack(anchor="w", pady=(4, 12))
        return card

    def _build_home(self):
        tab = ttk.Frame(self.nb, padding=(6, 14))
        self.nb.add(tab, text="  Home  ")
        self.tab_home = tab

        stats = ttk.Frame(tab)
        stats.pack(fill="x")
        self.stat_labels = {}
        for i, (key, label) in enumerate((("removed", "Cleaned up"), ("kept", "Protected from deletion"),
                                          ("sorted", "Emails sorted"), ("drafted", "Replies drafted"))):
            card = ttk.Frame(stats, style="Card.TFrame", padding=(18, 14))
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 12, 0))
            stats.columnconfigure(i, weight=1)
            self.stat_labels[key] = ttk.Label(card, text="0", style="Big.TLabel")
            self.stat_labels[key].pack(anchor="w")
            ttk.Label(card, text=label, style="Help.TLabel").pack(anchor="w")

        cards = ttk.Frame(tab)
        cards.pack(fill="both", expand=True, pady=(16, 0))
        cards.columnconfigure(0, weight=1, uniform="c")
        cards.columnconfigure(1, weight=1, uniform="c")

        a = self._card(cards, "Clean up your inbox",
                       "Bulk-remove old promotions, social and update emails, sender by sender. Anything with "
                       "product keys, activation links, codes, receipts or attachments is kept automatically.")
        a.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ttk.Button(a, text="Open Cleanup  →", style="Accent.TButton",
                   command=lambda: self.nb.select(self.cleanup)).pack(anchor="w")

        b = self._card(cards, "Sort new mail",
                       "Label and prioritise recent mail, flag phishing, and write reply drafts for you to "
                       "review. Preview shows what would happen without touching Gmail.")
        b.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        row = ttk.Frame(b, style="Card.TFrame")
        row.pack(anchor="w")
        for text, cmd, style in (("Preview", lambda: self.run(dry=True), "TButton"),
                                 ("Run now", lambda: self.run(dry=False), "Accent.TButton")):
            btn = ttk.Button(row, text=text, command=cmd, style=style)
            btn.pack(side="left", padx=(0, 8))
            self.buttons.append(btn)
        watch = ttk.Frame(b, style="Card.TFrame")
        watch.pack(anchor="w", pady=(12, 0))
        ttk.Label(watch, text="Keep sorting every", style="Card.TLabel").pack(side="left")
        self.interval = tk.IntVar(value=5)
        self.interval_box = ttk.Spinbox(watch, from_=1, to=1440, width=4, textvariable=self.interval)
        self.interval_box.pack(side="left", padx=6)
        ttk.Label(watch, text="min", style="Card.TLabel").pack(side="left", padx=(0, 10))
        self.watch_btn = ttk.Button(watch, text="Start watching", command=self.toggle_watch)
        self.watch_btn.pack(side="left")

        foot = ttk.Frame(tab)
        foot.pack(fill="x", pady=(16, 0))
        chk = ttk.Button(foot, text="Check connections", command=self.check)
        chk.pack(side="left")
        self.buttons.append(chk)
        ttk.Button(foot, text="Run setup again", command=self.open_setup).pack(side="left", padx=8)

    def _build_activity(self):
        tab = ttk.Frame(self.nb, padding=(6, 12))
        self.nb.add(tab, text="  Activity  ")
        self.tab_activity = tab
        self.activity = ScrollText(tab, font=theme.MONO, wrap="word", state="disabled")
        self.activity.pack(fill="both", expand=True)
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Clear", command=lambda: self._clear(self.activity)).pack(side="left")
        ttk.Button(row, text="Open full log", command=lambda: os.startfile(ACTIVITY_LOG)
                   if ACTIVITY_LOG.exists() else None).pack(side="left", padx=8)

    def _build_history(self):
        tab = ttk.Frame(self.nb, padding=(6, 12))
        self.nb.add(tab, text="  History  ")
        self.tab_history = tab

        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Category").pack(side="left")
        self.cat_filter = ttk.Combobox(top, state="readonly", width=16, values=["All"])
        self.cat_filter.set("All")
        self.cat_filter.pack(side="left", padx=(6, 14))
        self.cat_filter.bind("<<ComboboxSelected>>", lambda e: self.fill_history())
        ttk.Label(top, text="Search").pack(side="left")
        self.search = tk.StringVar()
        ttk.Entry(top, textvariable=self.search, width=32).pack(side="left", padx=6)
        self.search.trace_add("write", lambda *a: self.fill_history())
        ttk.Button(top, text="Refresh", command=self.refresh_history).pack(side="left", padx=8)
        self.count_lbl = ttk.Label(top, text="", style="Help.TLabel")
        self.count_lbl.pack(side="right")

        pane = ttk.PanedWindow(tab, orient="vertical")
        pane.pack(fill="both", expand=True)
        frame = ttk.Frame(pane)
        cols = (("time", 110), ("category", 110), ("priority", 80), ("reply", 80), ("deletion", 80),
                ("sender", 220), ("subject", 420))
        self.tree = ttk.Treeview(frame, columns=[c for c, _ in cols], show="headings", selectmode="browse")
        for name, width in cols:
            self.tree.heading(name, text=name.title(), anchor="w")
            self.tree.column(name, width=width, stretch=name == "subject")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_detail())
        self.tree.bind("<Double-1>", lambda e: self.open_in_gmail())
        pane.add(frame, weight=3)

        bottom = ttk.Frame(pane)
        btns = ttk.Frame(bottom)
        btns.pack(fill="x", pady=(10, 6))
        ttk.Button(btns, text="Open in Gmail", command=self.open_in_gmail).pack(side="left")
        ttk.Button(btns, text="Copy draft", command=self.copy_draft).pack(side="left", padx=8)
        self.detail = ScrollText(bottom, font=theme.FONT, wrap="word", height=12, state="disabled")
        self.detail.pack(fill="both", expand=True)
        pane.add(bottom, weight=2)

    def _build_try(self):
        tab = ttk.Frame(self.nb, padding=(6, 12))
        self.nb.add(tab, text="  Test emails  ")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(0, 8))
        self.try_btns += [
            ttk.Button(row, text="Open .eml files...", command=self.try_pick),
            ttk.Button(row, text="Run included samples", style="Accent.TButton", command=lambda: self.try_files(
                sorted(config.SAMPLES.glob("*.eml")))),
        ]
        for b in self.try_btns:
            b.pack(side="left", padx=(0, 8))
        self.force_draft = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Always draft a reply", variable=self.force_draft).pack(side="left", padx=8)
        ttk.Label(row, text="Nothing here touches Gmail.", style="Help.TLabel").pack(side="right")
        self.try_out = ScrollText(tab, font=theme.MONO, wrap="word", state="disabled")
        self.try_out.pack(fill="both", expand=True)

    # ---------- theme ----------

    def toggle_theme(self):
        new = "light" if theme.mode() == "dark" else "dark"
        theme.apply(self.root, new)
        theme.save_mode(new)
        self.retheme()

    def retheme(self):
        p = theme.pal()
        self.theme_btn.configure(text="☀  Light" if theme.mode() == "dark" else "☾  Dark")
        self.tree.tag_configure("urgent", foreground=p["warn"])
        self.tree.tag_configure("suspicious", foreground=p["bad"])
        self.tree.tag_configure("drafted", foreground=p["link"])

    # ---------- plumbing ----------

    def db(self):
        return DB

    def log(self, text):
        """Thread-safe: queue a line for the Activity tab and the log file."""
        self.q.put(("log", text))

    def _drain(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self._append(self.activity, val)
                    try:
                        with open(ACTIVITY_LOG, "a", encoding="utf-8") as f:
                            f.write(val + "\n")
                    except OSError:
                        pass
                elif kind == "try":
                    self._append(self.try_out, val)
                elif kind == "status":
                    self.status.configure(text=val)
                elif kind == "call":  # run a UI update on the main thread
                    val()
                elif kind == "history":
                    self.refresh_history()
                elif kind == "done":
                    self._set_busy(False)
                    self.status.configure(text="Stopped" if self.cancel.is_set() else val or "Ready")
                    self.refresh_stats()
                elif kind == "watch_stopped":
                    self.watch_stop = None
                    self.watch_btn.configure(text="Start watching", state="normal")
                    self._set_busy(False)
                    self.status.configure(text="Watching stopped")
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    @staticmethod
    def _append(widget, text):
        widget.configure(state="normal")
        widget.insert("end", text + "\n")
        widget.see("end")
        widget.configure(state="disabled")

    @staticmethod
    def _clear(widget):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.configure(state="disabled")

    def _set_busy(self, busy, keep_watch=False):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in self.buttons + self.try_btns:
            b.configure(state=state)
        self.interval_box.configure(state=state)
        self.stop_btn.configure(state="normal" if busy else "disabled")
        if not keep_watch:
            self.watch_btn.configure(state=state)

    def stop(self):
        """Stop whatever is running: a run, a test, a cleanup, or watching."""
        if not self.busy:
            return
        self.cancel.set()
        if self.watch_stop:
            self.watch_stop.set()
            self.watch_btn.configure(text="Stopping...", state="disabled")
        self.stop_btn.configure(state="disabled")
        self.status.configure(text="Stopping... (finishing the email in progress)")
        self.log("Stop requested: finishing the email in progress, nothing new will start.")

    def _start(self, label, fn):
        if self.busy:
            return
        self.cancel.clear()
        self._set_busy(True)
        self.status.configure(text=label + "...")

        def work():
            try:
                fn()
            except BaseException as e:  # config/credential problems raise SystemExit
                self.log(f"Error: {e}")
            finally:
                self.q.put(("done", None))

        threading.Thread(target=work, daemon=True).start()

    def _confirm_live(self):
        if self.live_confirmed:
            return True
        try:
            cfg = config.load()
        except BaseException as e:
            messagebox.showerror("Settings problem", str(e))
            return False
        msg = "This will apply labels, stars, mark-read/archive and save drafts in your Gmail."
        if cfg["safety"]["auto_send"]:
            msg += "\n\nAuto-send is ON: replies to allowlisted senders may be sent without review."
        self.live_confirmed = messagebox.askyesno("Sort for real?", msg + "\n\nContinue?")
        return self.live_confirmed

    def check_model_quietly(self):
        """Fill the header's model status without blocking the window."""
        def work():
            try:
                cfg = config.load()
                models = LLM(cfg["llm"]).ping()
                name = cfg["llm"]["model"] or (models[0] if models else "?")
                text, style = f"●  Model online · {name}", "Good.TLabel"
            except BaseException:
                text, style = "●  Model offline — check Settings → Model", "Bad.TLabel"
            self.q.put(("call", lambda: self.model_pill.configure(text=text, style=style)))
        threading.Thread(target=work, daemon=True).start()

    def open_setup(self):
        from .gui_setup import SetupWizard
        SetupWizard(self)

    # ---------- actions ----------

    def check(self):
        self.nb.select(self.tab_activity)
        self._start("Checking", self._do_check)

    def _do_check(self):
        cfg = config.load()
        try:
            self.log("Model OK: " + ", ".join(LLM(cfg["llm"]).ping()))
        except Exception as e:
            self.log(f"Model FAILED ({cfg['llm']['base_url']}): {e}")
        acct = cfg["account"]
        with Gmail(acct["address"], acct["password"], acct["imap_host"], acct["imap_port"]) as g:
            n = len(g.search(acct["query"]))
            self.log(f"Gmail OK as {acct['address']}: {n} messages match '{acct['query']}'; "
                     f"drafts folder {g.drafts_folder()}")
        self.check_model_quietly()

    def run(self, dry):
        if not dry and not self._confirm_live():
            return
        self.nb.select(self.tab_activity)
        self._start("Preview" if dry else "Sorting", lambda: self._do_run(dry))

    def _do_run(self, dry):
        cfg = config.load()
        acct = cfg["account"]
        self.log(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S}  {'PREVIEW' if dry else 'LIVE'} ===")
        with Gmail(acct["address"], acct["password"], acct["imap_host"], acct["imap_port"]) as g:
            agent.run(cfg, LLM(cfg["llm"], self.cancel), Store(DB), g, dry, report=self.log, cancel=self.cancel)
        self.q.put(("history", None))

    def toggle_watch(self):
        if self.watch_stop:
            self.stop()
            return
        if self.busy or not self._confirm_live():
            return
        try:
            minutes = max(1, int(self.interval.get()))
        except (tk.TclError, ValueError):
            minutes = 5
        stop = threading.Event()
        self.watch_stop = stop
        self.cancel.clear()
        self._set_busy(True, keep_watch=True)
        self.watch_btn.configure(text="Stop watching")
        self.nb.select(self.tab_activity)

        def loop():
            while not stop.is_set():
                try:
                    if agent.quiet_now(config.load()):
                        self.q.put(("status", "Watching: quiet hours, skipping"))
                    else:
                        self.q.put(("status", "Watching: sorting..."))
                        self._do_run(False)
                except BaseException as e:
                    self.log(f"Run failed: {e}")
                nxt = datetime.now() + timedelta(minutes=minutes)
                self.q.put(("status", f"Watching every {minutes} min: next run at {nxt:%H:%M}"))
                self.q.put(("call", self.refresh_stats))
                stop.wait(minutes * 60)
            self.q.put(("watch_stopped", None))

        threading.Thread(target=loop, daemon=True).start()

    def try_pick(self):
        files = filedialog.askopenfilenames(
            title="Choose emails", initialdir=config.SAMPLES,
            filetypes=[("Email files", "*.eml"), ("All files", "*.*")])
        if files:
            self.try_files([Path(f) for f in files])

    def try_files(self, files):
        if not files:
            return
        force = self.force_draft.get()
        self._clear(self.try_out)

        def work():
            cfg = config.load()
            llm = LLM(cfg["llm"], self.cancel)
            report = lambda text: self.q.put(("try", text))
            for i, path in enumerate(files):
                if self.cancel.is_set():
                    report(f"\nStopped. {len(files) - i} file(s) not tested.")
                    break
                report(f"\n### {path.name}")
                try:
                    agent.explain(llm, cfg, parse_message(path.read_bytes()), force, report)
                except Exception as e:
                    if not self.cancel.is_set():  # a Stop mid-answer isn't a failure
                        report(f"   failed: {e}")

        self._start(f"Testing {len(files)} email(s)", work)

    # ---------- history & stats ----------

    def refresh_stats(self):
        try:
            for key, n in Store(DB).stats().items():
                self.stat_labels[key].configure(text=f"{n:,}")
        except Exception:
            pass

    def refresh_history(self):
        try:
            self.history_rows = Store(DB).recent(1000)
            names = [c["name"] for c in config.load()["category"]]
            self.cat_filter.configure(values=["All"] + names)
        except BaseException:
            pass
        self.fill_history()
        self.refresh_stats()

    def fill_history(self):
        self.tree.delete(*self.tree.get_children())
        cat, term = self.cat_filter.get(), self.search.get().lower().strip()
        shown = 0
        for i, r in enumerate(self.history_rows):
            if cat != "All" and r["category"] != cat:
                continue
            if term and term not in f"{r['sender']} {r['subject']} {r['summary']}".lower():
                continue
            detail = json.loads(r["detail"] or "{}")
            tags = []
            if detail.get("classification", {}).get("suspicious"):
                tags.append("suspicious")
            elif r["priority"] == "urgent":
                tags.append("urgent")
            elif r["reply_action"] in ("drafted", "sent"):
                tags.append("drafted")
            when = datetime.fromisoformat(r["processed_at"]).astimezone().strftime("%m-%d %H:%M")
            self.tree.insert("", "end", iid=str(i), tags=tags, values=(
                when, r["category"], r["priority"], r["reply_action"], detail.get("deletion") or "",
                r["sender"], r["subject"]))
            shown += 1
        self.count_lbl.configure(text=f"{shown} of {len(self.history_rows)} shown")

    def _selected(self):
        sel = self.tree.selection()
        return self.history_rows[int(sel[0])] if sel else None

    def show_detail(self):
        r = self._selected()
        if not r:
            return
        d = json.loads(r["detail"] or "{}")
        cls, dr = d.get("classification", {}), d.get("draft") or {}
        lines = [
            r["subject"] or "(no subject)",
            f"From: {r['sender']}",
            f"{r['category']} / {r['priority']}   confidence {cls.get('confidence', '?')}   via {cls.get('source', '?')}"
            + ("   SUSPICIOUS" if cls.get("suspicious") else ""),
            "",
            r["summary"] or "",
            "",
            f"Actions: {r['actions'] or 'none'}",
            f"Reply: {r['reply_action']}",
        ]
        if d.get("deletion") == "kept":
            lines.append("Deletion: KEPT because " + "; ".join(d.get("deletion_blockers", [])))
        elif d.get("deletion"):
            lines.append(f"Deletion: {d['deletion']}")
        if cls.get("keep_reason"):
            lines.append(f"Worth keeping: {cls['keep_reason']}")
        if d.get("send_blockers"):
            lines.append("Not auto-sent because: " + "; ".join(d["send_blockers"]))
        if dr:
            lines += ["", f"Draft notes: {dr.get('notes', '')}", "-" * 60, dr.get("body", "")]
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", "\n".join(lines))
        self.detail.configure(state="disabled")

    def open_in_gmail(self):
        r = self._selected()
        if r and str(r["gm_msgid"]).isdigit():
            webbrowser.open(f"https://mail.google.com/mail/u/0/#all/{int(r['gm_msgid']):x}")

    def copy_draft(self):
        r = self._selected()
        body = (json.loads(r["detail"] or "{}").get("draft") or {}).get("body") if r else None
        if body:
            self.root.clipboard_clear()
            self.root.clipboard_append(body)
            self.status.configure(text="Draft copied to clipboard")

    def after_config_saved(self):
        self.live_confirmed = False  # safety settings may have changed
        self.refresh_mode()
        self.refresh_history()
        self.check_model_quietly()
        try:
            self.interval.set(config.load()["watch"]["interval_minutes"])
        except BaseException:
            pass
        self.status.configure(text="Settings saved")

    def refresh_mode(self):
        try:
            cfg = config.load()
            addr = cfg["account"]["address"]
            self.gmail_pill.configure(text=f"●  {addr}" if addr else "●  Gmail not set up",
                                      style="Help.TLabel" if addr else "Warn.TLabel")
            on = cfg["safety"]["auto_send"]
            self.mode_lbl.configure(text="●  Auto-send ON" if on else "●  Auto-send off",
                                    style="Bad.TLabel" if on else "Help.TLabel")
        except BaseException as e:
            self.mode_lbl.configure(text=f"Settings problem: {e}", style="Bad.TLabel")

    def close(self):
        if self.watch_stop:
            self.watch_stop.set()
        self.root.destroy()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on high-DPI screens
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("KeepSift.App")  # own taskbar icon
    except Exception:
        pass
    root = tk.Tk()
    theme.apply(root)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
