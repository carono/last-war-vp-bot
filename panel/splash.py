"""A frameless splash screen shown while the panel boots.

A dark, centred ``CTkToplevel`` with the bot name, a progress bar and the current
step. It is driven synchronously from ``Panel.__init__`` — there is no mainloop
yet — so it renders through explicit ``update()`` calls and tweens the bar with
short sleeps. The main window stays ``withdraw()``-n until ``finish()`` fades this
out; then ``Panel`` calls ``deiconify()``.
"""
from __future__ import annotations

import time

import customtkinter as ctk

_DARK_BG = ("#f0f0f0", "#141414")
_BORDER = ("#c0c0c0", "#2a2a2a")
_SUBTLE = ("#666666", "#8a8a8a")
_STEP = ("#555555", "#aaaaaa")


class SplashScreen(ctk.CTkToplevel):
    """Boot splash. Call ``step(text, progress)`` per phase, then ``finish()``."""

    def __init__(self, master, title="Last War", subtitle="", width=440, height=250):
        super().__init__(master)
        self.overrideredirect(True)             # frameless — no title bar, no border
        self.configure(fg_color=_DARK_BG)
        self._center(width, height)
        try:
            self.attributes("-topmost", True)
        except Exception:           # noqa: BLE001 — a cosmetic attribute, never fatal
            pass

        # A 1px border so the frameless card reads as a window on any wallpaper.
        card = ctk.CTkFrame(self, corner_radius=0, fg_color=_DARK_BG,
                            border_width=1, border_color=_BORDER)
        card.pack(fill="both", expand=True)

        ctk.CTkLabel(card, text=title,
                     font=ctk.CTkFont(size=30, weight="bold")).pack(pady=(48, 0))
        if subtitle:
            ctk.CTkLabel(card, text=subtitle, text_color=_SUBTLE,
                         font=ctk.CTkFont(size=13)).pack(pady=(4, 0))

        self._bar = ctk.CTkProgressBar(card, width=320, height=8, corner_radius=4)
        self._bar.set(0.0)
        self._bar.pack(pady=(30, 10))

        self._step_lbl = ctk.CTkLabel(card, text="", text_color=_STEP,
                                      font=ctk.CTkFont(size=12))
        self._step_lbl.pack()

        self._progress = 0.0
        self._render()

    def _center(self, w: int, h: int) -> None:
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        # A frameless CTkToplevel does not take the new size on the first update —
        # the window manager needs a few event cycles to apply the geometry (it
        # otherwise stays at CTkToplevel's default 200×200). Pump a handful.
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
            self._bar.set(start + (target - start) * i / frames)
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
        # Hide now, destroy later. CTkToplevel scheduled a few after()s in its
        # __init__ (titlebar icon/colour ≤200ms, scaled min/max at 1000ms); with no
        # mainloop yet they only fire once the panel's loop starts. Destroying now
        # would leave them to fire on a dead window (a stray TclError), so hide the
        # splash and let it self-destroy once those have safely run on it.
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
