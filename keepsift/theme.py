"""Look and feel: Windows 11 style (Sun Valley ttk theme) in light or dark, plus colours for plain tk widgets.

sv-ttk is optional; without it the app falls back to the native theme and still works.
"""
import ctypes
import json
import tkinter as tk
from tkinter import ttk

from .config import ROOT

try:
    import sv_ttk
except ImportError:  # running from source without requirements installed
    sv_ttk = None

PALETTES = {
    "light": {
        "bg": "#fafafa", "surface": "#ffffff", "text": "#1b1b1f", "muted": "#5f6368", "border": "#e0e0e6",
        "accent": "#4f46e5", "good": "#15803d", "warn": "#b45309", "bad": "#c62828", "link": "#2563eb",
        "select": "#e0e7ff", "select_text": "#1b1b1f", "header": "#eef0ff",
    },
    "dark": {
        "bg": "#1c1c1c", "surface": "#232326", "text": "#f2f2f5", "muted": "#a3a3ad", "border": "#38383d",
        "accent": "#818cf8", "good": "#4ade80", "warn": "#fbbf24", "bad": "#f87171", "link": "#7aa7ff",
        "select": "#3730a3", "select_text": "#ffffff", "header": "#25253a",
    },
}
UI_FILE = ROOT / "data" / "ui.json"
FONT = ("Segoe UI", 10)
MONO = ("Cascadia Mono", 10)

_mode = "light"


def pal():
    return PALETTES[_mode]


def can_switch():
    return sv_ttk is not None


def mode():
    return _mode


def system_mode():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return "light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "dark"
    except Exception:
        return "light"


def saved_mode():
    try:
        return json.loads(UI_FILE.read_text(encoding="utf-8")).get("theme") or system_mode()
    except Exception:
        return system_mode()


def save_mode(m):
    try:
        UI_FILE.parent.mkdir(exist_ok=True)
        UI_FILE.write_text(json.dumps({"theme": m}), encoding="utf-8")
    except OSError:
        pass


def apply(root, m=None):
    """Set the theme for the whole app (call once at start, and again to switch)."""
    global _mode
    _mode = (m or saved_mode()) if sv_ttk is not None else "light"  # native theme has no dark mode
    p = pal()
    style = ttk.Style(root)
    if sv_ttk is not None:
        sv_ttk.set_theme(_mode, root)
        # The theme finishes applying on the next idle pass and would wipe styles set before that.
        root.update_idletasks()
        style.configure(".", background=p["bg"], foreground=p["text"])
    elif "vista" in style.theme_names():
        style.theme_use("vista")
        p["surface"] = p["bg"] = style.lookup("TFrame", "background") or "SystemButtonFace"
    root.configure(background=p["bg"])

    style.configure("Treeview", rowheight=30, font=FONT)
    style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10))
    style.map("Treeview", background=[("selected", p["select"])], foreground=[("selected", p["select_text"])])
    style.configure("TNotebook.Tab", padding=(14, 6))
    style.configure("Help.TLabel", foreground=p["muted"])
    style.configure("Good.TLabel", foreground=p["good"])
    style.configure("Bad.TLabel", foreground=p["bad"])
    style.configure("Warn.TLabel", foreground=p["warn"])
    style.configure("Link.TLabel", foreground=p["link"])
    style.configure("Title.TLabel", font=("Segoe UI Semibold", 17))
    style.configure("Subtitle.TLabel", foreground=p["muted"], font=("Segoe UI", 10))
    style.configure("H2.TLabel", font=("Segoe UI Semibold", 14))
    style.configure("Big.TLabel", font=("Segoe UI Semibold", 22))
    style.configure("Stop.TButton", foreground=p["bad"])
    style.configure("Pill.TLabel", padding=(10, 3), foreground=p["muted"])
    style.configure("PillOn.TLabel", padding=(10, 3), foreground=p["bad"])
    style.configure("Header.TFrame", background=p["header"])
    style.configure("Header.TLabel", background=p["header"])
    style.configure("HeaderTitle.TLabel", background=p["header"], font=("Segoe UI Semibold", 17))
    style.configure("HeaderSub.TLabel", background=p["header"], foreground=p["muted"])
    recolor(root)
    dark_titlebar(root, _mode == "dark")
    return _mode


def recolor(widget):
    """Colour the plain-tk widgets (Text, Listbox, Canvas) that ttk themes don't reach."""
    p = pal()
    for w in _walk(widget):
        try:
            if isinstance(w, tk.Text):
                w.configure(background=p["surface"], foreground=p["text"], insertbackground=p["text"],
                            selectbackground=p["select"], selectforeground=p["select_text"],
                            highlightthickness=1, highlightbackground=p["border"], highlightcolor=p["accent"],
                            relief="flat", borderwidth=0, padx=8, pady=6)
            elif isinstance(w, tk.Listbox):
                w.configure(background=p["surface"], foreground=p["text"], selectbackground=p["select"],
                            selectforeground=p["select_text"], highlightthickness=0, relief="flat",
                            borderwidth=0, activestyle="none")
            elif isinstance(w, tk.Canvas):
                w.configure(background=p["bg"], highlightthickness=0)
            elif isinstance(w, tk.Toplevel):
                w.configure(background=p["bg"])
                dark_titlebar(w, _mode == "dark")
        except tk.TclError:
            pass


class ScrollText(tk.Text):
    """Drop-in for tkinter's ScrolledText, but with a themed ttk scrollbar."""

    def __init__(self, master=None, **kw):
        self.frame = ttk.Frame(master)
        self.vbar = ttk.Scrollbar(self.frame, orient="vertical")
        self.vbar.pack(side="right", fill="y")
        kw["yscrollcommand"] = self.vbar.set
        super().__init__(self.frame, **kw)
        tk.Text.pack(self, side="left", fill="both", expand=True)
        self.vbar.configure(command=self.yview)
        for name in ("pack", "grid", "place", "pack_forget", "grid_forget", "place_forget",
                     "pack_configure", "grid_configure"):
            setattr(self, name, getattr(self.frame, name))


def _walk(w):
    yield w
    for child in w.winfo_children():
        yield from _walk(child)


def dark_titlebar(win, dark):
    """Windows 10/11: make the title bar match the theme."""
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), 4) == 0:
                break
    except Exception:
        pass


def set_icon(win):
    from .config import ASSETS
    try:
        win.iconbitmap(default=str(ASSETS / "icon.ico"))
    except Exception:
        pass
    try:
        img = tk.PhotoImage(file=str(ASSETS / "icon-64.png"))
        win.iconphoto(True, img)
        win._keepsift_icon = img  # keep a reference
    except Exception:
        pass
