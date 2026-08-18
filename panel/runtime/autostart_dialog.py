"""«Автозапуск» as a menu entry: one switch for the whole machine (#1506).

It used to live on «Настройки» (`panel/tabs/settings.py`), a page inside one profile —
which was the wrong shape from the start: `panel/runtime/autostart.py` registers exactly
ONE Windows task for the whole panel, whatever profiles happen to be open in it (#1207),
so every profile's «Настройки» drew the same tick with a different account's name over
it. This is the shape the panel already uses for the other things that belong to the
WINDOW rather than to an account — «Веб» (`web_dialog.py`) and «Серверы»
(`servers_dialog.py`): a modal off the menu bar, opened on demand, thrown away when it
closes.

WHAT IT SHOWS IS ASKED OF WINDOWS, NEVER REMEMBERED. `autostartmod.status()` calls
`schtasks /Query` itself — a task removed by hand in `taskschd.msc`, or one left over
from a machine this profile was copied from, reads as what it actually is. A saved tick
here would be the second source of truth `CLAUDE.md` names as the exact class of bug this
project has already been bitten by once.

THE PHONE HAS THE SAME SWITCH, on purpose and by agreement (unlike «Веб», which does
not): turning the hourly watchdog off is not the channel the phone is reached through —
losing it costs a restart that would otherwise have happened by itself, not the ability
to ask for one. `panel/web/api.py` serves the same reading and the same press as the
`autostart` screen, off this module's own `status` / `set_enabled` — one door, two
front-ends, see `docs/panel-tabs.md`.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import autostart as autostartmod
from .. import i18n as i18nmod

#: The one dialog this process has open, if any — a second «Автозапуск» raises it
#: instead of drawing a second copy of the same switch.
_OPEN = None


def open_dialog(parent, rt_get, t) -> "tk.Toplevel | None":
    """Show the autostart switch. ``rt_get()`` is the profile on screen NOW.

    A callable rather than a runtime for the same reason `web_dialog.open_dialog` takes
    one: the dialog outlives a profile switch, and a press belongs in whichever
    profile's log is on screen when it happens, not in the one that was showing when the
    window opened.
    """
    global _OPEN
    if _OPEN is not None and _OPEN.alive():
        _OPEN.lift()
        return _OPEN.win
    _OPEN = _AutostartDialog(parent, rt_get, t)
    return _OPEN.win


def close_dialog() -> None:
    """Shut it if it is open — the window is closing, or the language changed."""
    global _OPEN
    dialog, _OPEN = _OPEN, None
    if dialog is not None:
        dialog.destroy()


class _AutostartDialog:
    """The modal itself: one switch, one note, and what it is set to do."""

    def __init__(self, parent, rt_get, t) -> None:
        self._rt_get = rt_get
        self._t = t

        self.win = win = tk.Toplevel(parent)
        win.title(t("menu.autostart"))
        win.resizable(False, False)
        win.transient(parent)
        win.protocol("WM_DELETE_WINDOW", self._close)

        frm = ttk.Frame(win)
        frm.pack(fill="both", expand=True, padx=14, pady=14)

        self._on = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text=t("autostart.enable"), variable=self._on,
                        command=self._toggled).pack(anchor="w")

        # THE ONE SENTENCE THAT EXPLAINS WHY THIS IS NOT ON A TAB — the same reason
        # «Веб» carries one (`web_dialog.py`): a profile's own page would draw one
        # machine-wide task with a different account's name over it every time.
        ttk.Label(frm, text=t("autostart.shared"), foreground="#888", wraplength=520,
                  justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(frm, text=t("autostart.hint"), foreground="#888", wraplength=520,
                  justify="left").pack(anchor="w", pady=(6, 0))

        self._note = ttk.Label(frm, wraplength=520, justify="left")
        self._note.pack(anchor="w", pady=(10, 0))

        buttons = ttk.Frame(frm)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text=t("profile.close"), command=self._close).pack(
            side="right")

        self._reload()

    # -- lifecycle ------------------------------------------------------------
    def alive(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def lift(self) -> None:
        try:
            self.win.lift()
            self.win.focus_set()
        except tk.TclError:
            pass

    def destroy(self) -> None:
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    def _close(self) -> None:
        global _OPEN
        _OPEN = None
        self.destroy()

    # -- the switch -------------------------------------------------------------
    def _toggled(self) -> None:
        """Register or remove the ONE task — and say why if Windows refused.

        The box snaps back to whatever the scheduler actually holds afterwards (via
        `_reload`), so a refusal (no administrator rights, group policy, no `schtasks`
        at all) leaves a tick that tells the truth rather than one that merely
        remembers the click.
        """
        rt = self._rt_get()
        want = bool(self._on.get())
        try:
            autostartmod.set_enabled(rt.profiles, want)
        except RuntimeError as exc:
            said = i18nmod.translated(self._t, exc)
            messagebox.showerror(self._t("menu.autostart"), said, parent=self.win)
            self._rt_say(rt, "log.autostart.failed", error=said)
        else:
            if want:
                # ONE panel with the whole set (#1207) — «для профиля X» would be a
                # promise this task does not make.
                self._rt_say(rt, "log.autostart.on",
                             profiles=", ".join(autostartmod.open_set(rt.profiles)))
            else:
                self._rt_say(rt, "log.autostart.off")
        self._reload()

    def _rt_say(self, rt, key: str, **fmt) -> None:
        try:
            rt.say("autostart", key, **fmt)
        except Exception:                    # noqa: BLE001 — a log line, never the dialog
            pass

    # -- what the dialog shows ---------------------------------------------------
    def _reload(self) -> None:
        """Re-read the scheduler and the last hourly verdict — never a saved tick.

        `schtasks /Query` is a subprocess (~60 ms measured); a modal opened on demand
        can afford it, unlike a tab redrawn on every profile switch.
        """
        rt = self._rt_get()
        try:
            info = autostartmod.status(rt.profiles)
        except Exception:                    # noqa: BLE001 — the dialog stays, blank
            return
        if not self.alive():
            return
        self._on.set(info.registered)
        lines = []
        if not info.supported:
            lines.append(self._t("autostart.state.unsupported"))
        elif info.registered:
            lines.append(self._t("autostart.state.on", task=info.task))
            lines.append(self._t("autostart.state.profiles",
                                 profiles=", ".join(info.profiles)))
            if not info.elevated:
                lines.append(self._t("autostart.state.limited"))
        else:
            lines.append(self._t("autostart.state.off"))
        last = self._last_check(info.last)
        if last:
            lines.append(last)
        self._note.configure(text="\n".join(lines))

    def _last_check(self, last: dict) -> str:
        """One sentence about the last hourly look — a key per verdict, spelled out.

        Built as a `t(...)` per branch rather than an assembled key: a key put together
        at run time is one `tests/test_panel_i18n.py` cannot see.
        """
        state = str((last or {}).get("state") or "")
        if not state:
            return ""
        when = time.strftime("%d.%m %H:%M", time.localtime(last.get("ts") or 0))
        if state == "running":
            return self._t("autostart.check.running", when=when)
        if state == "started":
            return self._t("autostart.check.started", when=when)
        if state == "restarted":
            return self._t("autostart.check.restarted", when=when)
        return self._t("autostart.check.failed", when=when, error=last.get("error") or "")
