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


def _binder(rt):
    return getattr(rt, "settings", None)


def get(rt, key: str, default: bool = False) -> bool:
    """This profile's knob as a bool. The default when it has never been touched."""
    settings = _binder(rt)
    if settings is None:
        return bool(default)
    try:
        value = settings.opt(key)
    except Exception:                        # noqa: BLE001 — a reading, never the panel
        return bool(default)
    if value is None:
        return bool(default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def set(rt, key: str, on: bool) -> bool:     # noqa: A001 — the verb the callers want
    """Move it. ``False`` when it was already where the press asked for.

    The widget when there is one, the file when there is not — the distinction that
    makes this worth a module rather than a line at each caller.
    """
    on = bool(on)
    settings = _binder(rt)
    if settings is None:
        return False
    # BOTH HAVE TO AGREE BEFORE A PRESS IS «уже так». The widget and the file drift
    # apart on their own: the shell's snapshot writes a knob only when the Settings page
    # of THAT profile has been built (`panel/__main__.py::_collect_settings` reads
    # `_opt_vars`, and a tab builds when somebody first looks at it, #1215). So three
    # profiles nobody had opened the page of came back from a restart with the box on in
    # Tk and no line at all on disk — and a press that trusted the widget answered
    # «unchanged» and repaired nothing. Comparing both means the press is idempotent AND
    # puts the file right.
    stored = None
    try:
        stored = dict(settings.values).get(key)
    except Exception:                        # noqa: BLE001 — a reading, never the panel
        stored = None
    if get(rt, key) == on and stored is not None and bool(stored) == on:
        return False
    moved = False
    var = None
    try:
        var = settings.var(key)
    except Exception:                        # noqa: BLE001 — no binder is not a crash
        var = None
    if var is not None:
        try:
            var.set(on)
            moved = True
        except Exception:                    # noqa: BLE001 — the file below still stands
            var = None
    # AND THE FILE, ALWAYS — never `settings.changed()` alone, which is what the first
    # draft did and what cost a press (#1882). `changed()` asks the SHELL to write a
    # profile out, and the shell writes the ACTIVE one: pressed from the phone against a
    # profile that is open but not in front, it moved the widget and saved somebody
    # else's file, so the knob was in Tk and nowhere on disk until that profile closed.
    # This binder belongs to THIS profile, so writing through it lands in the right
    # `config.json` whichever profile the window happens to be showing.
    try:
        raw = dict(settings.values)
        raw[key] = on
        settings.values = raw
        settings.save(raw)
        moved = True
    except Exception:                        # noqa: BLE001 — one knob, never the panel
        pass
    return moved
