"""The boot splash (panel/splash.py).

A frameless CTkToplevel that must actually take its requested size (CTkToplevel
defaults to 200×200 and needs a few update cycles to accept a new geometry —
regression-guarded here), show its steps, and fade/close without raising. Needs
the Windows Python with a working Tk display; skips otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _skip(exc=None) -> None:
    print(f"  SKIP no tkinter / display: {exc}" if exc else
          "  SKIP tkinter not importable — run under the Windows Python")


def test_splash_sizes_shows_steps_and_closes():
    try:
        import customtkinter as ctk
    except Exception as exc:                             # noqa: BLE001
        _skip(exc)
        return
    try:
        from panel.splash import SplashScreen
        root = ctk.CTk()
        root.withdraw()
    except Exception as exc:                             # noqa: BLE001
        _skip(exc)
        return
    try:
        splash = SplashScreen(root, title="Last War", subtitle="Control Panel",
                              width=440, height=250)
        splash.update_idletasks()
        splash.update()
        # It must take the requested size, not CTkToplevel's default 200×200.
        assert splash.winfo_width() == 440, splash.winfo_width()
        assert splash.winfo_height() == 250, splash.winfo_height()
        assert splash.winfo_children(), "splash built no content"

        # Steps advance the bar monotonically, 0..1, without raising.
        splash.step("Loading the profile…", 0.2)
        assert abs(splash._progress - 0.2) < 1e-6, splash._progress
        splash.step("Connecting…", 0.9)
        assert abs(splash._progress - 0.9) < 1e-6, splash._progress
        # Out-of-range is clamped.
        splash.step("x", 5.0)
        assert splash._progress == 1.0, splash._progress

        # finish() fades, hides and schedules its own close — never raises, and
        # leaves the window hidden (not yet destroyed).
        splash.finish("Ready")
        assert splash.winfo_exists(), "finish() destroyed the splash immediately"
        assert not splash.winfo_ismapped(), "finish() did not hide the splash"
    finally:
        root.destroy()


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
