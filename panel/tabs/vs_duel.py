"""The «VS Duel» tab: what the bot is allowed to do on each day of the alliance duel.

The duel scores a DIFFERENT set of actions every weekday (docs/game/daily_cycle.md),
so the tab is a column of day groups — Monday to Saturday — and each group holds the
actions that day pays points for. Saturday is still an empty group saying its actions
come later; the rest are written out.

Three shapes make up every group, and nothing else:

* **an action** — a box. Ticked means «do this on that day».
* **a ceiling** — the number beside an action that spends something scarce: hero
  experience (in millions, the unit the game itself shows) and drone gears. It is the
  MOST that action may spend that day; an empty field is «no ceiling of its own».
* **a detail** — a box that belongs to an action rather than being another action:
  break experience boxes out of the bag when what the account holds does not reach the
  ceiling, use a ministry to start a construction or a research. A pick from a list is
  the same thing in another shape — which research category to start.

A detail and a ceiling go grey with their action, because a choice about something
nobody is doing is not a choice.

An action that scores on two different days is written ONCE and placed in both — the
hero (Monday and Thursday) and the drone components (Monday and Wednesday). They are
the same control with the same words; only the day's settings are separate, which is
what makes «Monday's ceiling» and «Thursday's ceiling» two numbers rather than one.

**Nothing here presses anything.** The tab is the plan — a set of choices kept in the
profile. Every ability is a scenario under `src/lastwar_bot/actions/` and the panel
only plays them (CLAUDE.md), so the day a scenario exists for one of these boxes the
wiring reads :meth:`plan` and runs it with those numbers. None of them exists yet,
which is why the tab needs no daemon, no client and no game.
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


class _Sub:
    """A box that belongs to an action — a detail of HOW it is done, not another action.

    Drawn indented under its action and switched off with it, because a choice about an
    action nobody is doing is not a choice at all.
    """

    def __init__(self, key: str, label: str) -> None:
        self.key, self.label = key, label


class _Choice:
    """A pick from a list, belonging to an action the way a :class:`_Sub` does.

    ``options`` is ``((value, locale key), …)``: the value is what the profile keeps and
    what :meth:`VsDuelTab.plan` answers with, the key is what the person reads. The
    first option is the default.
    """

    def __init__(self, key: str, label: str, options: tuple) -> None:
        self.key, self.label, self.options = key, label, options

    @property
    def default(self) -> str:
        return self.options[0][0] if self.options else ""

    def index_of(self, value: str) -> int:
        for i, (option, _label) in enumerate(self.options):
            if option == value:
                return i
        return 0


class _Action:
    """One scoring action of a duel day: a box, its ceiling, and its own details."""

    def __init__(self, key: str, label: str, amount: "_Amount | None" = None,
                 subs: tuple = (), choice: "_Choice | None" = None) -> None:
        self.key, self.label, self.amount = key, label, amount
        self.subs, self.choice = subs, choice


# --- the actions that score on more than one day, written once ---------------

def _hero_level() -> _Action:
    """«Level the hero up» — the box, the ceiling in millions of experience, and the
    detail that opens experience boxes when the account's own is not enough.

    Monday and Thursday both score it and it must read and behave identically on both,
    so it is built here rather than spelled twice. Each day still keeps its OWN
    settings: the config keys carry the day (`mon.hero_exp_m` / `thu.hero_exp_m`).
    """
    return _Action("hero_level", "vsduel.hero_level",
                   _Amount("hero_exp_m", "vsduel.hero_exp_m"),
                   subs=(_Sub("exp_boxes", "vsduel.hero_exp_boxes"),))


def _drone_parts() -> _Action:
    """«Open drone components» — Monday's and Wednesday's, the same box on both."""
    return _Action("drone_parts", "vsduel.drone_parts")


#: The research categories «start a new research» may be aimed at, as
#: ``(value, locale key)``.
#:
#: TODO(#1200): EMPTY ON PURPOSE. The game's own category names have not been read off
#: a live client yet, and a category invented here would aim the scenario at something
#: that does not exist. Until they are known the picker offers «any» alone; filling this
#: tuple is all it takes to offer them — plus each new locale key in EVERY shipped
#: locale, like anything else a person reads (CLAUDE.md).
RESEARCH_CATEGORIES: tuple = ()

#: What the category picker holds while no particular category is chosen — and, for now,
#: the only thing it can hold.
CATEGORY_ANY = "any"


def _research_category() -> _Choice:
    return _Choice("category", "vsduel.research_category",
                   ((CATEGORY_ANY, "vsduel.research_category.any"),)
                   + RESEARCH_CATEGORIES)


#: The duel week, Monday first — the order the groups are drawn in. A day whose actions
#: are still to be written down carries an empty tuple and draws a «later» line, which
#: is all it takes to add one: put its actions here and give them locale keys.
DAYS: tuple = (
    ("mon", (
        _drone_parts(),
        _hero_level(),
        _Action("drone_level", "vsduel.drone_level",
                _Amount("drone_gears", "vsduel.drone_gears")),
    )),
    ("tue", (
        _Action("build_speedup", "vsduel.build_speedup"),
        _Action("build_collect", "vsduel.build_collect"),
        _Action("survivor_tickets", "vsduel.survivor_tickets"),
        _Action("build_start", "vsduel.build_start",
                subs=(_Sub("ministry", "vsduel.build_ministry"),)),
    )),
    ("wed", (
        _drone_parts(),
        _Action("research_speedup", "vsduel.research_speedup"),
        _Action("research_collect", "vsduel.research_collect"),
        _Action("research_start", "vsduel.research_start",
                subs=(_Sub("ministry", "vsduel.research_ministry"),),
                choice=_research_category()),
    )),
    ("thu", (
        _hero_level(),
        _Action("hero_rank_ur", "vsduel.hero_rank_ur"),
        _Action("hero_rank_ssr", "vsduel.hero_rank_ssr"),
        _Action("honour_wall", "vsduel.honour_wall"),
        _Action("honour_wall_chests", "vsduel.honour_wall_chests"),
        _Action("exclusive_weapon", "vsduel.exclusive_weapon"),
    )),
    ("fri", (
        _Action("lord_rank", "vsduel.lord_rank"),
        _Action("lord_train", "vsduel.lord_train"),
        _Action("lord_skills", "vsduel.lord_skills"),
        _Action("lord_level", "vsduel.lord_level"),
        _Action("unit_train", "vsduel.unit_train"),
        _Action("unit_upgrade", "vsduel.unit_upgrade"),
    )),
    ("sat", ()),
)


class VsDuelTab(PanelTab):
    """The duel plan: a group per day, a box per action, and — under an action — the
    ceiling it spends against and the boxes and pickers that say how it is done."""

    ID = "vs_duel"
    TITLE_KEY = "tab.vs_duel"
    ORDER = 330
    LOCALE_NS = ("vsduel",)
    # Nothing is played from here yet, so the tab costs a profile nothing to switch on.
    NEEDS = frozenset()

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        master = rt.root
        #: "<day>.<action>" (and "<day>.<action>.<detail>") -> the box's variable.
        self._flags: dict = {}
        #: "<day>.<amount>" -> the ceiling's variable.
        self._amounts: dict = {}
        #: "<day>.<action>.<choice>" -> the picked VALUE (never the label on screen).
        self._choices: dict = {}
        #: "<day>.<amount>" -> what an untouched profile puts in it. Kept, so a profile
        #: that never set a ceiling RESTORES the default rather than inheriting the
        #: number the previously open account happened to be left on.
        self._defaults: dict = {}
        #: What an unticked action greys out with it — its ceiling, its detail boxes and
        #: its picker, as "<the dependent's own name>" -> (widget, action's variable,
        #: the state to put it back into).
        self._dependents: dict = {}
        #: "<day>.<action>.<choice>" -> (combobox, the choice) — what a language change
        #: has to re-fill, since a combobox's list is not a widget option `tr` can set.
        self._combos: dict = {}
        for day, actions in DAYS:
            for action in actions:
                self._flags[f"{day}.{action.key}"] = tk.BooleanVar(master=master,
                                                                   value=False)
                if action.amount is not None:
                    name = f"{day}.{action.amount.key}"
                    self._amounts[name] = tk.StringVar(master=master,
                                                       value=action.amount.default)
                    self._defaults[name] = action.amount.default
                for sub in action.subs:
                    self._flags[f"{day}.{action.key}.{sub.key}"] = tk.BooleanVar(
                        master=master, value=False)
                if action.choice is not None:
                    name = f"{day}.{action.key}.{action.choice.key}"
                    self._choices[name] = tk.StringVar(master=master,
                                                       value=action.choice.default)
                    self._defaults[name] = action.choice.default

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
        self._retranslate_choices()
        self._sync_dependents()

    def _build_action(self, box, day: str, action: _Action) -> None:
        """One box, and — indented under it — what only makes sense while it is ticked:
        the ceiling it spends against, its detail boxes, its picker."""
        flag = self._flags[f"{day}.{action.key}"]
        self.tr(ttk.Checkbutton(box, variable=flag, command=self._sync_dependents),
                action.label).pack(anchor="w", pady=(0, 2))
        if action.amount is not None:
            name = f"{day}.{action.amount.key}"
            row = self._indented(box)
            self.tr(ttk.Label(row, foreground="#888"), action.amount.label).pack(
                side="left", padx=(0, 6))
            entry = NumericEntry(row, width=8, textvariable=self._amounts[name])
            entry.pack(side="left")
            self._dependents[name] = (entry, flag, "normal")
        for sub in action.subs:
            name = f"{day}.{action.key}.{sub.key}"
            widget = self.tr(ttk.Checkbutton(box, variable=self._flags[name]),
                             sub.label)
            widget.pack(anchor="w", padx=(24, 0), pady=(0, 2))
            self._dependents[name] = (widget, flag, "normal")
        if action.choice is not None:
            name = f"{day}.{action.key}.{action.choice.key}"
            row = self._indented(box)
            self.tr(ttk.Label(row, foreground="#888"), action.choice.label).pack(
                side="left", padx=(0, 6))
            combo = ttk.Combobox(row, state="readonly", width=24)
            combo.pack(side="left")
            combo.bind("<<ComboboxSelected>>",
                       lambda _e, n=name: self._on_choice(n))
            self._combos[name] = (combo, action.choice)
            # Back to READONLY rather than «normal»: a combobox left normal is one a
            # person can type anything into, and the list is the whole point of it.
            self._dependents[name] = (combo, flag, "readonly")
        if action.amount is not None or action.subs or action.choice is not None:
            ttk.Frame(box, height=4).pack()      # air before the next action's box

    def _indented(self, box):
        """A row under an action, offset so it reads as belonging to the box above."""
        row = ttk.Frame(box)
        row.pack(anchor="w", padx=(24, 0), pady=(0, 2))
        return row

    def _sync_dependents(self) -> None:
        """Grey out what an unticked action carries — its ceiling has nothing to limit,
        its detail boxes have nothing to be a detail of."""
        for widget, flag, live in self._dependents.values():
            try:
                widget.configure(state=(live if flag.get() else "disabled"))
            except tk.TclError:                 # the window went away mid-callback
                pass

    # -- the pickers -----------------------------------------------------------
    def _on_choice(self, name: str) -> None:
        """A pick was made: keep the VALUE, not the words that were on screen."""
        combo, choice = self._combos[name]
        index = combo.current()
        if 0 <= index < len(choice.options):
            self._choices[name].set(choice.options[index][0])

    def _retranslate_choices(self) -> None:
        """Re-fill every picker's list in the current language and re-show its value.

        A combobox's list is not a widget option, so `tr` cannot carry it through a
        language change the way it does a label.
        """
        for name, (combo, choice) in self._combos.items():
            try:
                combo.configure(values=[self.t(key) for _v, key in choice.options])
                combo.current(choice.index_of(self._choices[name].get()))
            except tk.TclError:
                pass

    def on_language_change(self) -> None:
        self._retranslate_choices()

    # -- what the wiring reads -------------------------------------------------
    def plan(self, day: str) -> dict:
        """What is ticked for ``day``, each action with its ceiling and its details.

        ``{"hero_level": {"limit": 30, "exp_boxes": True}}`` says «level the hero up,
        spending at most 30 million experience, and open experience boxes if that is
        what it takes to get there». ``"limit": None`` says the action has no ceiling —
        an empty field, or an action that spends nothing countable. An action that is
        not ticked is simply absent, and so is a day nobody has written actions for.
        """
        out: dict = {}
        for name, actions in DAYS:
            if name != day:
                continue
            for action in actions:
                if not self._flags[f"{day}.{action.key}"].get():
                    continue
                entry = {"limit": (None if action.amount is None
                                   else self._amount(f"{day}.{action.amount.key}"))}
                for sub in action.subs:
                    entry[sub.key] = bool(
                        self._flags[f"{day}.{action.key}.{sub.key}"].get())
                if action.choice is not None:
                    entry[action.choice.key] = self._choices[
                        f"{day}.{action.key}.{action.choice.key}"].get()
                out[action.key] = entry
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
        out.update({name: var.get() for name, var in self._choices.items()})
        return out

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        for name, var in self._flags.items():
            var.set(bool(raw.get(name, False)))
        for name, var in self._amounts.items():
            var.set(str(raw.get(name, self._defaults.get(name, ""))))
        for name, var in self._choices.items():
            var.set(str(raw.get(name, self._defaults.get(name, ""))))
        self._retranslate_choices()
        self._sync_dependents()

    def persist_vars(self) -> list:
        return (list(self._flags.values()) + list(self._amounts.values())
                + list(self._choices.values()))


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(VsDuelTab))
