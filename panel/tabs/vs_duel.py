"""The «VS Duel» tab: what the bot is allowed to do on each day of the alliance duel.

The duel scores a DIFFERENT set of actions every weekday (docs/game/daily_cycle.md),
so the tab is a column of day groups — Monday to Saturday — and each group holds the
actions that day pays points for. Monday is written out; the other five are empty
groups saying as much, so the shape of the week is visible before a later task fills
them in.

Two of Monday's actions spend something scarce enough to want a ceiling: hero
experience (counted in millions, the unit the game itself shows) and drone gears. The
number beside such a box is the MOST that action may spend on that day; an empty box
is «no ceiling of its own».

**Nothing here presses anything.** The tab is the plan — a set of choices kept in the
profile. Every ability is a scenario under `src/lastwar_bot/actions/` and the panel
only plays them (CLAUDE.md), so the day a scenario exists for one of these boxes the
wiring reads :meth:`plan` and runs it with those numbers. None of Monday's three
exists yet, which is why the tab needs no daemon, no client and no game.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..widgets import NumericEntry, ScrollableFrame, font as ui_font
from .base import PanelTab


class _Amount:
    """A number typed beside a box — the most that action may spend on that day."""

    def __init__(self, key: str, label: str, default: str = "") -> None:
        self.key, self.label, self.default = key, label, default


class _Action:
    """One scoring action of a duel day: a box, and its ceiling where it has one."""

    def __init__(self, key: str, label: str, amount: "_Amount | None" = None) -> None:
        self.key, self.label, self.amount = key, label, amount


#: The duel week, Monday first — the order the groups are drawn in. A day whose actions
#: are still to be written down carries an empty tuple and draws a «later» line, which
#: is all it takes to add one: put its actions here and give them locale keys.
DAYS: tuple = (
    ("mon", (
        _Action("drone_parts", "vsduel.mon.drone_parts"),
        _Action("hero_level", "vsduel.mon.hero_level",
                _Amount("hero_exp_m", "vsduel.mon.hero_exp_m")),
        _Action("drone_level", "vsduel.mon.drone_level",
                _Amount("drone_gears", "vsduel.mon.drone_gears")),
    )),
    ("tue", ()),
    ("wed", ()),
    ("thu", ()),
    ("fri", ()),
    ("sat", ()),
)


class VsDuelTab(PanelTab):
    """The duel plan: a group per day, a box per action, a ceiling where it spends."""

    ID = "vs_duel"
    TITLE_KEY = "tab.vs_duel"
    ORDER = 330
    LOCALE_NS = ("vsduel",)
    # Nothing is played from here yet, so the tab costs a profile nothing to switch on.
    NEEDS = frozenset()

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        master = rt.root
        #: "<day>.<action>" -> the box's variable.
        self._flags: dict = {}
        #: "<day>.<amount>" -> the ceiling's variable.
        self._amounts: dict = {}
        #: "<day>.<amount>" -> what an untouched profile puts in it. Kept, so a profile
        #: that never set a ceiling RESTORES the default rather than inheriting the
        #: number the previously open account happened to be left on.
        self._defaults: dict = {}
        #: "<day>.<amount>" -> (entry, the box it belongs to) — what greys a ceiling out
        #: while its action is unticked.
        self._entries: dict = {}
        for day, actions in DAYS:
            for action in actions:
                self._flags[f"{day}.{action.key}"] = tk.BooleanVar(master=master,
                                                                   value=False)
                if action.amount is not None:
                    name = f"{day}.{action.amount.key}"
                    self._amounts[name] = tk.StringVar(master=master,
                                                       value=action.amount.default)
                    self._defaults[name] = action.amount.default

    # -- UI -------------------------------------------------------------------
    def build(self) -> None:
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.tr(ttk.Label(bar, font=ui_font(size=15, weight="bold")),
                "tab.vs_duel").pack(side="left")

        self.tr(ttk.Label(self.parent, foreground="#888", wraplength=640,
                          justify="left"), "vsduel.hint").pack(
            anchor="w", padx=10, pady=(0, 6))

        scroll = ScrollableFrame(self.parent)
        scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for day, actions in DAYS:
            box = self.tr(ttk.LabelFrame(scroll, padding=8), f"vsduel.day.{day}")
            box.pack(fill="x", padx=(0, 4), pady=(0, 8))
            if not actions:
                self.tr(ttk.Label(box, foreground="#888"), "vsduel.later").pack(
                    anchor="w")
                continue
            for action in actions:
                self._build_action(box, day, action)
        self._sync_amounts()

    def _build_action(self, box, day: str, action: _Action) -> None:
        """One box, and — indented under it — the ceiling that action spends against."""
        flag = self._flags[f"{day}.{action.key}"]
        self.tr(ttk.Checkbutton(box, variable=flag, command=self._sync_amounts),
                action.label).pack(anchor="w", pady=(0, 2))
        if action.amount is None:
            return
        name = f"{day}.{action.amount.key}"
        row = ttk.Frame(box)
        row.pack(anchor="w", padx=(24, 0), pady=(0, 6))
        self.tr(ttk.Label(row, foreground="#888"), action.amount.label).pack(
            side="left", padx=(0, 6))
        entry = NumericEntry(row, width=8, textvariable=self._amounts[name])
        entry.pack(side="left")
        self._entries[name] = (entry, flag)

    def _sync_amounts(self) -> None:
        """Grey out a ceiling whose action is unticked — it has nothing to limit."""
        for entry, flag in self._entries.values():
            try:
                entry.configure(state=("normal" if flag.get() else "disabled"))
            except tk.TclError:                 # the window went away mid-callback
                pass

    # -- what the wiring reads -------------------------------------------------
    def plan(self, day: str) -> dict:
        """What is ticked for ``day``, each with its ceiling as a whole number.

        ``{"hero_level": 30}`` says «level the hero up, spending at most 30 million
        experience»; ``None`` as the value says the box is ticked and has no ceiling of
        its own (an empty field, or an action that spends nothing countable). An action
        that is not ticked is simply absent.
        """
        out: dict = {}
        for name, actions in DAYS:
            if name != day:
                continue
            for action in actions:
                if not self._flags[f"{day}.{action.key}"].get():
                    continue
                out[action.key] = (None if action.amount is None
                                   else self._amount(f"{day}.{action.amount.key}"))
        return out

    def _amount(self, name: str) -> "int | None":
        """The ceiling in a field as a whole number, or ``None`` for «no ceiling».

        An empty box, junk left by a hand-edited profile and a zero all read as «no
        ceiling» rather than as an error: the field aims a spend, so it always answers.
        """
        try:
            value = int(str(self._amounts[name].get()).strip() or 0)
        except (KeyError, TypeError, ValueError):
            return None
        return value if value > 0 else None

    # -- persistence -----------------------------------------------------------
    def config(self) -> dict:
        out = {name: bool(var.get()) for name, var in self._flags.items()}
        out.update({name: var.get() for name, var in self._amounts.items()})
        return out

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        for name, var in self._flags.items():
            var.set(bool(raw.get(name, False)))
        for name, var in self._amounts.items():
            var.set(str(raw.get(name, self._defaults.get(name, ""))))
        self._sync_amounts()

    def persist_vars(self) -> list:
        return list(self._flags.values()) + list(self._amounts.values())


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(VsDuelTab))
