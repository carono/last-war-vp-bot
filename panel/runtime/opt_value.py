"""One profile's knob of ANY kind, read and written where it actually counts.

`panel/runtime/opt_switch.py` did this for booleans and said why: a knob on the Settings
page is a WIDGET first and a line in `config.json` second, so a write that only touched
the file is undone by the next save of that profile's widgets. Everything in that
paragraph is true of a number and of a string as well — and since the panel is growing a
front-end where the Settings page is a SCREEN rather than a page of Tk boxes (#1976),
the other kinds need the same door rather than a second one each.

WHAT IT ADDS over the boolean version: the TYPE. A knob's kind is decided by the default
it was declared with (`panel/runtime/settings.py::DEFAULTS` and whatever a tab has
registered), so «4000» typed on a phone lands as an int, «0.5» as a float, and a knob
declared `False` can never be stored as the string "False" — which is what makes an
`opt_bool` read it as true for ever after.

WHAT IT IS NOT. Not a place for a knob's MEANING, exactly as its boolean half is not:
what the port re-points, what the watchdog puts back, which capture an interval bounces
all stay where they already are. This only says: read this profile's value, and move it
in the one place that counts.

THE TK THREAD IS THE CALLER'S PROBLEM: the write touches a Tk variable when a window is
open, so whoever calls it from an HTTP worker hands it over (`panel/web/api.py::_on_tk`,
and `web_press` already runs there). With no window — a tab launched on its own, a test —
the file IS the knob and the same call does the right thing.
"""
from __future__ import annotations

#: The kinds a front-end knows how to draw. Anything else is shown as text, which is
#: what a knob nobody has thought about deserves — never a control that silently
#: rewrites a value it did not understand.
SWITCH, NUMBER, TEXT = "switch", "number", "text"


def _binder(rt):
    return getattr(rt, "settings", None)


def declared(rt, key: str):
    """What this knob was DECLARED with — the default, whatever a profile has done."""
    settings = _binder(rt)
    if settings is None:
        return None
    try:
        return settings.defaults.get(key)
    except Exception:                        # noqa: BLE001 — a reading, never the panel
        return None


def kind(rt, key: str) -> str:
    """Which control this knob wants, decided by the type it was declared with."""
    fallback = declared(rt, key)
    if isinstance(fallback, bool):
        return SWITCH
    if isinstance(fallback, (int, float)):
        return NUMBER
    return TEXT


def get(rt, key: str, default=None):
    """This profile's value, in the type it was declared with."""
    settings = _binder(rt)
    if settings is None:
        return default
    try:
        value = settings.opt(key)
    except Exception:                        # noqa: BLE001 — a reading, never the panel
        return default
    if value is None:
        return declared(rt, key) if default is None else default
    return coerce(rt, key, value)


def coerce(rt, key: str, value):
    """``value`` as the type this knob was declared with; the declared value if it will
    not convert.

    A HALF-TYPED BOX IS NEVER OBEYED — the rule `panel/runtime/settings.py` already
    states for its readers, applied at the WRITE now that a value can arrive from
    outside the window: an empty «лимит краж» read as 0 would silently stop the
    auto-loot, and a stray letter in a port would aim the panel at nothing.
    """
    fallback = declared(rt, key)
    if isinstance(fallback, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(fallback, int) and not isinstance(fallback, bool):
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return fallback
    if isinstance(fallback, float):
        try:
            return float(str(value).strip().replace(",", "."))
        except (TypeError, ValueError):
            return fallback
    return "" if value is None else str(value)


def set(rt, key: str, value) -> bool:        # noqa: A001 — the verb the callers want
    """Move it. ``False`` when it was already where the press asked for.

    The widget when there is one, the file when there is not — the distinction that
    makes this worth a module rather than a line at each caller. The file is written
    through THIS profile's binder, never `settings.changed()`, which asks the shell to
    write the ACTIVE profile out: pressed from the phone against a profile that is open
    but not in front, that moved the widget and saved somebody else's file (#1882).
    """
    settings = _binder(rt)
    if settings is None:
        return False
    want = coerce(rt, key, value)
    if get(rt, key) == want:
        return False
    var = None
    try:
        var = settings.var(key)
    except Exception:                        # noqa: BLE001 — no binder is not a crash
        var = None
    if var is not None:
        try:
            var.set(want)
        except Exception:                    # noqa: BLE001 — the file below still stands
            pass
    try:
        raw = dict(settings.values)
        raw[key] = want
        settings.values = raw
        settings.save(raw)
    except Exception:                        # noqa: BLE001 — one knob, never the panel
        return False
    return True
