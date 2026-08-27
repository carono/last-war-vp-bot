"""The settings ONE errand carries — the gear on a timer's row or a trigger's block.

WHY IT EXISTS. A standing order is never only a switch. «Автолут ★» spends five
robberies a day and the level it spends them at decides whether that is a good day or a
wasted one; the rally auto-join sends squads and which of the four it may send is the
whole of what it does. Until now every one of those knobs lived on the page the order's
LIST lives on, and the order's switch lived there too — so the tab that shows every
standing order the panel has (`panel/tabs/timers.py`) showed a row of names and nothing
a person could act on. The person's decision, in their words: «теперь некоторые таймеры
и триггеры будут иметь настройки, чтобы прямо на вкладке с триггерами их править».

WHAT IT IS NOT. Not a new home for the values. A knob registered here goes on living
exactly where it already lived — the owning tab's variable, saved in that tab's own
block; or a profile setting, when the knob was already one. That is the point: the gear
and the page edit ONE value, so a level typed on «Секретки» is the level the gear shows
a second later and the other way round. Nothing is copied, nothing is migrated, and
there is no second file to disagree with the first.

    The gear is a VIEW of the owner's knob, never a copy of it.

WHAT A KNOB DECLARES: an id, a locale key, which control draws it, and — for a number —
its bounds. The kinds are `panel/runtime/opt_value.py`'s, deliberately, because the web
front-end already draws exactly those four and a fifth would need a renderer nobody has
written.

STANDING ORDERS. The same registry also holds the orders that are not in anybody's
catalogue: «Автолут ★» and «Автолут отрядов» are watchers a tab owns, with a switch of
their own, and they are drawn among the triggers because that is where a person looks
for a standing order. They are registered with a `get`/`set` for the switch and the same
options as anything else, and neither front-end has to know which of the three kinds of
errand it is drawing.
"""
from __future__ import annotations

from . import opt_value

#: The controls a front-end knows how to draw — `opt_value`'s, and for its reason: the
#: web renders these four and nothing else.
SWITCH, NUMBER, TEXT, CHOICE = (opt_value.SWITCH, opt_value.NUMBER,
                                opt_value.TEXT, opt_value.CHOICE)


class Option:
    """One knob of one errand: where it is drawn, and where its value really lives.

    Either ``setting`` (a key of this profile's own settings, read and written through
    :mod:`panel.runtime.opt_value`) or the ``get``/``set`` pair (the owner's variable).
    Never both — a knob with two homes is a knob with two answers.
    """

    __slots__ = ("key", "label_key", "label_fmt", "kind", "low", "high", "hint_key",
                 "setting", "_get", "_set", "options")

    def __init__(self, key: str, label_key: str, kind: str = NUMBER, *,
                 get=None, set=None,          # noqa: A002 — the words the callers want
                 setting: str = "", low=None, high=None, hint_key: str = "",
                 options=(), label_fmt=None) -> None:
        self.key = key
        self.label_key = label_key
        #: What goes into the label's placeholders — «Отряд {n}». The four squads of the
        #: auto-join are one key and four knobs, and a locale key per squad would be four
        #: strings saying the same thing in eleven files.
        self.label_fmt = dict(label_fmt or {})
        self.kind = kind
        self.low, self.high = low, high
        self.hint_key = hint_key
        self.setting = setting
        self._get, self._set = get, set
        #: For `CHOICE`: `({"value": id, "text": what it calls itself}, …)`.
        self.options = tuple(options or ())

    # -- the value ----------------------------------------------------------
    def read(self, rt):
        """What it is now. Never raises: a knob that cannot be read is not a crash."""
        try:
            if self._get is not None:
                return self._get()
            if self.setting:
                return opt_value.get(rt, self.setting)
        except Exception:                    # noqa: BLE001 — a reading, never the panel
            pass
        return "" if self.kind in (TEXT, NUMBER) else False

    def write(self, rt, value) -> bool:
        """Move it, where it actually lives. ``False`` when the write was refused.

        ON THE TK THREAD when the owner's home is a widget — which is every `get`/`set`
        knob here. Both callers are already there: the window's dialog is a widget, and
        a press off the phone is handed over by `panel/web/api.py::_on_tk`.
        """
        try:
            if self._set is not None:
                self._set(_as_kind(self.kind, value))
                return True
            if self.setting:
                opt_value.set(rt, self.setting, value)
                return True
        except Exception:                    # noqa: BLE001 — one knob, never the panel
            return False
        return False

    # -- how a front-end draws it -------------------------------------------
    def as_field(self, rt) -> dict:
        """The knob as the web's `Field` — the same shape «Настройки» sends."""
        field = {"key": self.key, "label": self.label_key,
                 "kind": self.kind, "value": self.read(rt)}
        if self.label_fmt:
            field["label_fmt"] = dict(self.label_fmt)
        if self.hint_key:
            field["hint"] = self.hint_key
        if self.low is not None:
            field["min"] = self.low
        if self.high is not None:
            field["max"] = self.high
        if self.options:
            field["options"] = [dict(opt) for opt in self.options]
        return field


def _as_kind(kind: str, value):
    """A value off a front-end, in the shape the owner's variable expects.

    A `SWITCH` is a bool whatever the wire said («on», 1, true); everything else is left
    a string, because a blank box means «no bound» to every reader here and a helpful
    `int("")` would turn it into a 0 — which, for «минимальный уровень», is every level
    there is (`panel/tabs/secret_tasks/autoloot.py`).
    """
    if kind == SWITCH:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    return "" if value is None else str(value)


class Order:
    """A standing order that is in no catalogue — a watcher a tab owns.

    It is drawn among the triggers because that is what it IS to a person: something
    that runs by itself once it is switched on. The `get`/`set` pair is its switch, in
    the tab's own variable, so ticking it here is the same act as ticking it there.
    """

    __slots__ = ("name", "label_key", "hint_key", "_get", "_set", "state")

    def __init__(self, name: str, label_key: str, *, get, set,   # noqa: A002
                 hint_key: str = "", state=None) -> None:
        self.name, self.label_key, self.hint_key = name, label_key, hint_key
        self._get, self._set = get, set
        #: What the order is DOING right now, as a callable answering one phrase — the
        #: reading «Автолут ★» already draws under its box («жду звезду», «лимит
        #: исчерпан»). A silent order and a stopped one look identical without it, which
        #: is what «автолут не работает совершенно» turned out to be (#1227).
        self.state = state

    def enabled(self) -> bool:
        try:
            return bool(self._get())
        except Exception:                    # noqa: BLE001 — a reading, never the panel
            return False

    def set_enabled(self, on: bool) -> bool:
        """Tick it. On the Tk thread — the switch is the owner's own variable."""
        try:
            self._set(bool(on))
            return True
        except Exception:                    # noqa: BLE001 — one switch, never the panel
            return False

    def state_text(self) -> str:
        if self.state is None:
            return ""
        try:
            return str(self.state() or "")
        except Exception:                    # noqa: BLE001 — a reading, never the panel
            return ""


class ErrandOptions:
    """Every errand's knobs, and the orders that are not in a catalogue.

    One per profile, held by that profile's :class:`panel.runtime.schedule.Schedule` —
    the same object that already collects what a tab brings with it, and the one both
    front-ends already reach for the timers and the triggers.
    """

    def __init__(self, rt) -> None:
        self.rt = rt
        self._options: dict = {}
        self._orders: dict = {}

    # -- what a tab brings with it ------------------------------------------
    def register(self, errand: str, options) -> None:
        """Declare one errand's knobs. Called with the tab, not with the widgets."""
        opts = tuple(options or ())
        if opts:
            self._options[errand] = opts

    def register_order(self, order: Order) -> None:
        """Declare a standing order — a switch of a tab's own, drawn among the
        triggers."""
        self._orders[order.name] = order

    def forget(self, errand: str) -> None:
        self._options.pop(errand, None)
        self._orders.pop(errand, None)

    # -- what a front-end asks ----------------------------------------------
    def spec(self, errand: str) -> tuple:
        return self._options.get(errand, ())

    def has(self, errand: str) -> bool:
        return bool(self._options.get(errand))

    def fields(self, errand: str) -> list:
        """One errand's knobs as the web's fields — empty for an errand with none."""
        return [opt.as_field(self.rt) for opt in self._options.get(errand, ())]

    def write(self, errand: str, key: str, value) -> bool:
        """Move one knob of one errand. ``False`` for a knob this errand has not got —
        which is what a press naming something nobody declared deserves."""
        for opt in self._options.get(errand, ()):
            if opt.key == key:
                return opt.write(self.rt, value)
        return False

    # -- the orders ---------------------------------------------------------
    def orders(self) -> tuple:
        """The standing orders, in the order they were registered."""
        return tuple(self._orders.values())

    def order(self, name: str):
        return self._orders.get(name)
