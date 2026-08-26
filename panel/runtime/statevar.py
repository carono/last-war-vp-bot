"""A tab's state, with or without a window under it (#1976, P3).

Every tab keeps what it knows in Tk variables — 126 of them across the panel — and that
was the right place while a variable's job was to feed a widget: a `StringVar` IS the
label, and the trace that saves the profile is the same trace that redraws. With the
window going (`docs/research/panel-service-and-spa-plan.md` P3), a variable has to keep
working where there is no Tk at all: a panel serving a phone through the service holds the
same schedule, the same standing orders and the same settings, and none of them has a
widget to write into.

SO THE VARIABLE IS ASKED FOR RATHER THAN CONSTRUCTED. :func:`string`, :func:`boolean`,
:func:`integer` and :func:`number` hand back a REAL Tk variable when there is a window to
own it — so `textvariable=` keeps working, unchanged, for as long as Tk is here — and a
plain one when there is not. The two have the same surface: `get`, `set`, `trace_add`, and
that is the whole of what this codebase asks of a variable.

WHY NOT A SUBCLASS OF THE TK ONE. Because the point is to be importable with no `tkinter`
at all — the acceptance test of P3 is that the panel imports none — and a subclass would
need it before it could decide it does not.

WHAT A `trace_add` IS HERE. Tk's, narrowed to what the panel uses: `"write"`, and a
callable that takes the three arguments Tk passes and ignores them. Every caller in this
repository writes `lambda *_a: …`, so the shape is the same on both sides.
"""
from __future__ import annotations

_MODES = ("write",)


class StateVar:
    """One value, and whoever wants to hear that it changed. No Tk, no thread of its own.

    NO LOCK, deliberately, and it is the same reasoning `widgets.var_mirror` gives: the
    writer is the clock's thread or the request that came in on it, a reader that is one
    write behind is a reader that will be asked again in a second, and a lock here would
    be a lock on every knob in the panel for a race nobody has ever seen.
    """

    __slots__ = ("_value", "_watchers", "_kind")

    def __init__(self, value=None, kind=str) -> None:
        self._kind = kind
        self._value = self._coerce(value)
        self._watchers: list = []

    # -- the Tk surface -----------------------------------------------------
    def get(self):
        return self._value

    def set(self, value) -> None:
        self._value = self._coerce(value)
        for watcher in list(self._watchers):
            try:
                watcher("", "", "write")
            except Exception:                    # noqa: BLE001 — as Tk swallows one
                pass

    def trace_add(self, mode: str, func):
        """Listen for writes. Returns a handle `trace_remove` accepts, as Tk's does."""
        if mode not in _MODES or func is None:
            return None
        self._watchers.append(func)
        return func

    def trace_remove(self, mode: str, handle) -> None:
        try:
            self._watchers.remove(handle)
        except ValueError:
            pass

    # -- and the little that is ours ----------------------------------------
    def _coerce(self, value):
        if self._kind is str:
            return "" if value is None else str(value)
        if self._kind is bool:
            return bool(value)
        try:
            return self._kind(value if value is not None else 0)
        except (TypeError, ValueError):
            return self._kind(0)

    def __repr__(self) -> str:
        return f"<StateVar {self._value!r}>"


def _tk_var(master, kind, value):
    """The window's own variable, when there is a window. ``None`` when there is not."""
    if master is None:
        return None
    try:
        import tkinter as tk
    except Exception:                            # noqa: BLE001 — a panel with no Tk built
        return None
    made = {str: tk.StringVar, bool: tk.BooleanVar,
            int: tk.IntVar, float: tk.DoubleVar}[kind]
    try:
        return made(master=master, value=value)
    except Exception:                            # noqa: BLE001 — no root, a dead window
        return None


def var(master, kind=str, value=None):
    """A variable owned by ``master`` if there is one, a plain one if there is not."""
    default = {str: "", bool: False, int: 0, float: 0.0}[kind] if value is None else value
    found = _tk_var(master, kind, default)
    return found if found is not None else StateVar(default, kind)


def string(master, value: str = "") -> "StateVar":
    return var(master, str, value)


def boolean(master, value: bool = False) -> "StateVar":
    return var(master, bool, value)


def integer(master, value: int = 0) -> "StateVar":
    return var(master, int, value)


def number(master, value: float = 0.0) -> "StateVar":
    return var(master, float, value)
