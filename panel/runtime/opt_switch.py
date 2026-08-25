"""One profile's boolean knob, read and written from wherever the press came from.

WHY IT EXISTS. A knob on the Settings page is a WIDGET first and a line in
`config.json` second: an open profile keeps its values in Tk variables and the shell's
auto-save writes the whole snapshot out, so a write that only touched the file is undone
by the next save and lost the moment anything else moves. `panel/runtime/power.py` had
already learned that for «Профиль работает»; this is the same write with the key left
open, so a second knob reachable from the phone does not need a second copy of it.

WHAT IT IS NOT. Not a place for a knob's MEANING. Whether the watchdog puts a client
back, what a port re-points, which capture an interval bounces — all of that stays where
it already is. This only says: read this profile's boolean, and move it in the one place
that counts.

THE TK THREAD IS THE CALLER'S PROBLEM, exactly as in `power.py`: the write touches a Tk
variable when a window is open, so whoever calls it from an HTTP worker hands it over
(`panel/web/api.py::_on_tk`). With no window — a tab launched on its own, a test — the
file IS the switch and the same call does the right thing.
"""
from __future__ import annotations

from . import opt_value


def _binder(rt):
    return getattr(rt, "settings", None)


def get(rt, key: str, default: bool = False) -> bool:
    """This profile's knob as a bool. The default when it has never been touched."""
    if _binder(rt) is None:
        return bool(default)
    value = opt_value.get(rt, key, default)
    return bool(value) if not isinstance(value, str) else \
        value.strip().lower() in ("1", "true", "yes", "on")


def set(rt, key: str, on: bool) -> bool:     # noqa: A001 — the verb the callers want
    """Move it. ``False`` when it was already where the press asked for.

    ONE DOOR NOW (#1976): the write itself is `panel/runtime/opt_value.py`, which does
    exactly what this module used to do and does it for numbers and strings as well.
    What stays here is the boolean READING — «1», «yes» and «on» are all true — because
    a knob that has been through an old profile's file can be any of them.
    """
    return opt_value.set(rt, key, bool(on))
