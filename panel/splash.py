"""A frameless splash screen shown while the panel boots.

A dark, centred ``tk.Toplevel`` with the bot name, a progress bar and the current
step. It is driven synchronously from ``Panel.__init__`` — there is no mainloop
yet — so it renders through explicit ``update()`` calls and tweens the bar with
short sleeps. The main window stays ``withdraw()``-n until ``finish()`` fades this
out; then ``Panel`` calls ``deiconify()``.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

_BG = "#141414"
_BORDER = "#2a2a2a"
_TITLE = "#f0f0f0"
_SUBTLE = "#8a8a8a"
_STEP = "#aaaaaa"


class SplashScreen(tk.Toplevel):
    """Boot splash. Call ``step(text, progress)`` per phase, then ``finish()``."""

    def __init__(self, master, title="Last War", subtitle="", width=440, height=250):
        super().__init__(master)
        self.overrideredirect(True)             # frameless — no title bar, no border
        self.configure(bg=_BG)
        self._center(width, height)
        try:
            self.attributes("-topmost", True)
        except Exception:           # noqa: BLE001 — a cosmetic attribute, never fatal
            pass

        # A 1px border so the frameless card reads as a window on any wallpaper.
        card = tk.Frame(self, bg=_BG, highlightbackground=_BORDER,
                        highlightcolor=_BORDER, highlightthickness=1, bd=0)
        card.pack(fill="both", expand=True)

        tk.Label(card, text=title, bg=_BG, fg=_TITLE,
                 font=("Segoe UI", 30, "bold")).pack(pady=(48, 0))
        if subtitle:
            tk.Label(card, text=subtitle, bg=_BG, fg=_SUBTLE,
                     font=("Segoe UI", 13)).pack(pady=(4, 0))

        self._bar = ttk.Progressbar(card, length=320, mode="determinate", maximum=1.0)
        self._bar.configure(value=0.0)
        self._bar.pack(pady=(30, 10))

        self._step_lbl = tk.Label(card, text="", bg=_BG, fg=_STEP,
                                  font=("Segoe UI", 12))
        self._step_lbl.pack()

        self._progress = 0.0
        self._render()

    def _center(self, w: int, h: int) -> None:
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        # Pump a few event cycles so the window manager applies the new geometry
        # before the first synchronous render.
        for _ in range(6):
            self._render()

    def _render(self) -> None:
        try:
            self.update()
        except Exception:           # noqa: BLE001 — window may already be gone
            pass

    def step(self, text: str, progress: float | None = None) -> None:
        """Show ``text`` as the current step and, if given, tween the bar to
        ``progress`` (0..1) smoothly."""
        try:
            self._step_lbl.configure(text=text)
        except Exception:           # noqa: BLE001
            return
        if progress is None:
            self._render()
            return
        target = max(0.0, min(1.0, progress))
        start = self._progress
        frames = 14
        for i in range(1, frames + 1):
            self._bar.configure(value=start + (target - start) * i / frames)
            self._render()
            time.sleep(0.010)
        self._progress = target

    def finish(self, text: str | None = None) -> None:
        """Fill the bar, fade the window out, hide it, then destroy it shortly
        after the mainloop starts."""
        if text is not None:
            try:
                self._step_lbl.configure(text=text)
            except Exception:       # noqa: BLE001
                pass
        self.step(self._step_lbl.cget("text"), 1.0)
        try:
            for alpha in range(10, -1, -1):
                self.attributes("-alpha", alpha / 10)
                self._render()
                time.sleep(0.018)
        except Exception:           # noqa: BLE001 — no alpha support: just close
            pass
        # Hide now, destroy later — there is no mainloop yet, so let any pending
        # after() callbacks fire on a live (hidden) window before it is torn down.
        try:
            self.withdraw()
        except Exception:           # noqa: BLE001
            pass
        try:
            self.after(4000, self._safe_close)
        except Exception:           # noqa: BLE001
            self._safe_close()

    def _safe_close(self) -> None:
        try:
            if self.winfo_exists():
                self.destroy()
        except Exception:           # noqa: BLE001
            pass
