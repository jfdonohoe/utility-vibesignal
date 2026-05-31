"""Always-on-top floating panel (Tkinter, standard library) over the store.

A small borderless window that stays on top and shows one row per active
session, blocked first, refreshed about once a second. It is the desktop-GUI
sibling of panel.py (the terminal table) and the future physical light: all
three read the same store through resolve_per_session(), so this adds a
renderer without touching the hook layer.

Run with:
  Windows:        pythonw -m vibesignal widget    (no console window)
  macOS / Linux:  vibesignal widget &        (background the GUI)

Drag by the header; right-click to quit. On macOS, Control-click works too
because some Tk builds report the right mouse button as Button-2 rather than
Button-3, and Control-click is the historical single-button right-click chord.
"""
from __future__ import annotations

import sys
import time
import tkinter as tk
import tkinter.font as tkfont

from . import resolve
from .panel import _fmt_age


def _font_family() -> str:
    """Per-platform UI font family.

    Tk silently substitutes when a family is missing, but the substitute is
    often a poor visual match (Times on macOS, Courier on bare X). Naming the
    platform-native family up front keeps the panel legible without forcing a
    runtime font-list scan.
    """
    if sys.platform == "darwin":
        return "Helvetica Neue"  # ships with every macOS; SF Pro is unreliable via Tk
    if sys.platform == "win32":
        return "Segoe UI"
    return "DejaVu Sans"

# Soft light theme. A left accent bar per row carries the state color.
HEX = {
    "blocked": "#dc2626",  # red (needs you now)
    "done": "#2563eb",     # blue
    "working": "#16a34a",  # green
    "error": "#9333ea",    # violet (manual failure)
    "idle": "#9ca3af",     # grey
}
_BORDER = "#c9ced8"
_BG = "#e9ecf1"      # soft cool grey card (calmer than stark white)
_FG = "#272b31"
_DIM = "#6b7280"
_DIMMER = "#959ba4"
_RULE = "#d6dae1"
_HEADER = "#2b3038"

# When a session needs you, the whole panel goes red (violet for a manual error),
# not just one row, so a blocked session is unmissable across several windows. Other
# states keep the calm grey chrome.
_CALM = {"frame": _BORDER, "header_bg": _BG, "header_fg": _HEADER, "wash": _BG, "alarm": False}


def _palette(agg: str) -> dict:
    if agg == "blocked":
        return {"frame": "#dc2626", "header_bg": "#dc2626", "header_fg": "#ffffff",
                "wash": "#fdecec", "alarm": True}
    if agg == "error":
        return {"frame": "#9333ea", "header_bg": "#9333ea", "header_fg": "#ffffff",
                "wash": "#f5ecfd", "alarm": True}
    return _CALM


def glyph(state: str) -> str:
    """Filled dot for live states, hollow for idle (used in the header)."""
    return "○" if state == "idle" else "●"


def row_fields(row: dict, now: float):
    """Pure helper: (glyph, project, agent, state, age) display strings."""
    state = row.get("state", "idle")
    age = "—" if state == "working" else _fmt_age(now - row.get("ts", now))
    project = str(row.get("project") or "?")[:18]
    agent = str(row.get("agent") or "?")[:7]
    return glyph(state), project, agent, state, age


class Widget:
    def __init__(self, interval_ms: int = 1000):
        self.interval_ms = interval_ms
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", 0.97)
        except tk.TclError:
            pass
        # The root acts as a 1px border so the panel reads on a light desktop.
        self.root.configure(bg=_BORDER)
        self.card = tk.Frame(self.root, bg=_BG)
        self.card.pack(fill="both", expand=True, padx=1, pady=1)

        fam = _font_family()
        self._f_title = tkfont.Font(family=fam, size=9, weight="bold")
        self._f_proj = tkfont.Font(family=fam, size=9)
        self._f_dim = tkfont.Font(family=fam, size=8)
        self._f_dot = tkfont.Font(family=fam, size=10)

        self.header = tk.Frame(self.card, bg=_BG)
        self.header.pack(fill="x", padx=11, pady=(5, 4))
        self._agg_dot = tk.Label(self.header, text="●", bg=_BG, fg=_DIMMER, font=self._f_dot)
        self._agg_dot.pack(side="left")
        self._title = tk.Label(self.header, text=" vibesignal", bg=_BG, fg=_HEADER,
                               font=self._f_title)
        self._title.pack(side="left")
        self._count = tk.Label(self.header, text="", bg=_BG, fg=_DIMMER, font=self._f_dim)
        self._count.pack(side="right")

        self._rule = tk.Frame(self.card, bg=_RULE, height=1)
        self._rule.pack(fill="x", padx=11)

        self.body = tk.Frame(self.card, bg=_BG)
        self.body.pack(fill="both", expand=True, padx=(8, 12), pady=(5, 8))
        self.body.grid_columnconfigure(0, minsize=4)              # accent bar
        self.body.grid_columnconfigure(1, minsize=118, weight=1)  # project
        self.body.grid_columnconfigure(2, minsize=46)             # agent
        self.body.grid_columnconfigure(3, minsize=54)             # state
        self.body.grid_columnconfigure(4, minsize=40)             # age

        for w in (self.root, self.card, self.header, self._agg_dot, self._title, self._count):
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<Button-3>", self._menu)
            if sys.platform == "darwin":
                # Some macOS Tk builds report the right mouse button as Button-2,
                # and Control-click is the historical single-button right-click.
                # Binding both keeps the Quit menu reachable on every Mac setup.
                w.bind("<Button-2>", self._menu)
                w.bind("<Control-Button-1>", self._menu)

        self._cells: list[tk.Widget] = []
        self._drag = (0, 0)
        self._tick()
        self.root.after(60, self._reposition)

    def _menu(self, event):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Quit panel", command=self.root.destroy)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _start_drag(self, event):
        self._drag = (event.x, event.y)

    def _on_drag(self, event):
        x = self.root.winfo_x() + (event.x - self._drag[0])
        y = self.root.winfo_y() + (event.y - self._drag[1])
        self.root.geometry(f"+{x}+{y}")

    def _screen_workarea(self):
        """(left, top, right, bottom) of the desktop work area.

        Per-platform: Windows uses SystemParametersInfoW SPI_GETWORKAREA so the
        taskbar is excluded; macOS uses NSScreen.visibleFrame (via pyobjc, if
        installed) so the menu bar and Dock are excluded, falling back to a
        28/80 px heuristic when pyobjc is absent; other systems fall back to
        the full screen.
        """
        if sys.platform == "darwin":
            try:
                from AppKit import NSScreen  # pyobjc; best-effort
                screen = NSScreen.mainScreen()
                if screen is not None:
                    visible = screen.visibleFrame()
                    full = screen.frame()
                    # NSScreen uses bottom-left origin; Tk uses top-left. Flip Y
                    # against the screen's OWN top edge, not against full.size.height
                    # alone, so the math stays correct when mainScreen() resolves
                    # to a non-primary display (origin.y != 0 in a vertical
                    # multi-display layout).
                    screen_top = full.origin.y + full.size.height
                    left = int(visible.origin.x)
                    right = int(visible.origin.x + visible.size.width)
                    top = int(screen_top - (visible.origin.y + visible.size.height))
                    bottom = int(screen_top - visible.origin.y)
                    return left, top, right, bottom
            except Exception:
                pass
            # Heuristic without pyobjc: subtract the menu bar (~28) and a
            # bottom-Dock-sized strip (~80). Assumes a bottom Dock; a left or
            # right Dock will overlap the widget at the default x=14 origin.
            # Install pyobjc-framework-Cocoa for true Dock-aware placement.
            sh = self.root.winfo_screenheight()
            sw = self.root.winfo_screenwidth()
            return 0, 28, sw, sh - 80
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            # SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _reposition(self):
        self.root.update_idletasks()
        left, _top, _right, bottom = self._screen_workarea()
        height = self.root.winfo_height()
        self.root.geometry(f"+{left + 14}+{bottom - height - 12}")

    def _tick(self):
        rows = resolve.resolve_per_session()
        agg, _color = resolve.resolve_color()
        now = time.time()

        pal = _palette(agg)
        wash, hbg = pal["wash"], pal["header_bg"]

        # Whole-panel alarm: the frame and header go red (violet for error) and the
        # body is tinted, so a blocked session is visible without reading any row.
        self.root.configure(bg=pal["frame"])
        self.card.configure(bg=wash)
        self.card.pack_configure(padx=(3 if pal["alarm"] else 1),
                                 pady=(3 if pal["alarm"] else 1))
        self.body.configure(bg=wash)
        self.header.configure(bg=hbg)
        self._rule.configure(bg=(hbg if pal["alarm"] else _RULE))
        self._title.configure(bg=hbg, fg=pal["header_fg"])
        self._agg_dot.configure(bg=hbg, fg=("#ffffff" if pal["alarm"] else HEX.get(agg, _DIMMER)))
        self._count.configure(text=(f"{len(rows)}" if rows else ""), bg=hbg,
                              fg=("#ffffff" if pal["alarm"] else _DIMMER))

        for w in self._cells:
            w.destroy()
        self._cells = []

        if not rows:
            lbl = tk.Label(self.body, text="no active sessions", bg=wash, fg=_DIM,
                           font=self._f_dim, anchor="w")
            lbl.grid(row=0, column=1, columnspan=4, sticky="w", pady=2)
            self._cells.append(lbl)
        else:
            for i, r in enumerate(rows):
                _g, project, agent, state, age = row_fields(r, now)
                color = HEX.get(state, _FG)
                bar = tk.Frame(self.body, bg=color)
                bar.grid(row=i, column=0, sticky="nsew", padx=(0, 9), pady=2)
                cells = [
                    bar,
                    tk.Label(self.body, text=project, bg=wash, fg=_FG, font=self._f_proj, anchor="w"),
                    tk.Label(self.body, text=agent, bg=wash, fg=_DIM, font=self._f_dim, anchor="w"),
                    tk.Label(self.body, text=state, bg=wash, fg=color, font=self._f_dim, anchor="w"),
                    tk.Label(self.body, text=age, bg=wash, fg=_DIMMER, font=self._f_dim, anchor="e"),
                ]
                cells[1].grid(row=i, column=1, sticky="w", pady=1)
                cells[2].grid(row=i, column=2, sticky="w", padx=(8, 0), pady=1)
                cells[3].grid(row=i, column=3, sticky="w", padx=(8, 0), pady=1)
                cells[4].grid(row=i, column=4, sticky="e", padx=(8, 0), pady=1)
                self._cells.extend(cells)

        self.root.after(self.interval_ms, self._tick)

    def run(self):
        self.root.mainloop()


def main(interval_ms: int = 1000) -> int:
    Widget(interval_ms=interval_ms).run()
    return 0


if __name__ == "__main__":
    main()
