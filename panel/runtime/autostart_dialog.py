"""«Автозапуск»: one switch for the whole machine — one section of «Параметры» (#1506, #1509).

It used to live on the profile's own «Настройки» tab → «Игра» (`panel/tabs/settings.py`),
a page inside one
profile — which was the wrong shape from the start: `panel/runtime/autostart.py`
registers exactly ONE Windows task for the whole panel, whatever profiles happen to be
open in it (#1207), so every profile's page drew the same tick with a different
account's name over it (#1506). It then got its own entry on the menu bar; now it is one
row in the sidebar of the single «Параметры» modal (`panel/runtime/settings_dialog.py`,
#1509) beside «Веб», «Профиль» and «Язык» — every switch that belongs to the window
rather than to an account, behind one door instead of four.

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


def build(parent, rt_get, t) -> "_AutostartSection":
    """Build the section INTO ``parent`` — a content frame `settings_dialog.py` owns.

    ``rt_get()`` is the profile on screen NOW — see `web_dialog.build` for why this is
    a callable rather than a runtime.
    """
    return _AutostartSection(parent, rt_get, t)


class _AutostartSection:
    """One switch, one note, and what it is set to do."""

    def __init__(self, parent, rt_get, t) -> None:
        self._rt_get = rt_get
        self._t = t

        frm = ttk.Frame(parent)
        frm.pack(fill="both", expand=True)
        self._frame = frm

        self._on = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text=t("autostart.enable"), variable=self._on,
                        command=self._toggled).pack(anchor="w")

        # THE ONE SENTENCE THAT EXPLAINS WHY THIS IS NOT ON A PROFILE'S PAGE — the same
        # reason «Веб» carries one: a profile's own tab would draw one machine-wide task
        # with a different account's name over it every time.
        ttk.Label(frm, text=t("autostart.shared"), foreground="#888", wraplength=480,
                  justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(frm, text=t("autostart.hint"), foreground="#888", wraplength=480,
                  justify="left").pack(anchor="w", pady=(6, 0))

        self._note = ttk.Label(frm, wraplength=480, justify="left")
        self._note.pack(anchor="w", pady=(10, 0))

        self._reload()

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
            messagebox.showerror(self._t("menu.autostart"), said,
                                 parent=self._frame.winfo_toplevel())
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
        except Exception:                    # noqa: BLE001 — a log line, never the section
            pass

    # -- what the section shows ---------------------------------------------------
    def _reload(self) -> None:
        """Re-read the scheduler and the last hourly verdict — never a saved tick.

        `schtasks /Query` is a subprocess (~60 ms measured); a section built on demand
        can afford it, unlike a tab redrawn on every profile switch.
        """
        rt = self._rt_get()
        try:
            info = autostartmod.status(rt.profiles)
        except Exception:                    # noqa: BLE001 — the note stays blank
            return
        if not self._frame.winfo_exists():
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
