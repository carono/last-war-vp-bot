"""The «VS Duel» tab: what the bot is allowed to do on each day of the alliance duel.

The duel scores a DIFFERENT set of actions every weekday (docs/game/daily_cycle.md),
so the tab is a grid of day groups — Monday to Saturday, the whole week the duel runs,
two days to a row — and each group holds the actions that day pays points for. Two
columns rather than one because six groups in a single column is a page nobody can see
the week on: the first three days are read, the rest are scrolled to.

**The day's title is a box.** Unticking it says «this day is not played» — every action,
ceiling, detail and pick inside it goes grey at once, and :meth:`plan` answers with
nothing for it. Two things in the group stay live: the box itself, and the picker that
says which set the day is read from — see «the sets» below for why that one cannot go
grey with the day it selects.

Four shapes make up every group, and nothing else:

* **an action** — a box. Ticked means «do this on that day».
* **a ceiling** — the number beside an action that spends something scarce: hero
  experience (in millions, the unit the game itself shows) and drone gears. It is the
  MOST that action may spend that day; an empty field is «no ceiling of its own».
* **a detail** — a box that belongs to an action rather than being another action:
  break experience boxes out of the bag when what the account holds does not reach the
  ceiling, use a ministry to start a construction or a research. A pick from a list is
  the same thing in another shape — which research category to start.
* **a decision the DAY makes** — a pick with no box above it, drawn as radio buttons.
  Saturday's shield is one: the same points come either from two twelve-hour shields or
  from one that lasts a day, so the question is not whether but which.

A day may also hold a **group**: a named frame around some of its actions, for a day
whose points come from two different routines. Wednesday is the one — the research that
can be hurried and collected at any hour, and the loop that only runs inside the science
minister's five-minute buff — and the frame plus its one line about when it applies is
what keeps «speed the research up» and «start one and hurry it» from reading as the same
box written twice.

A detail and a ceiling go grey with their action, because a choice about something
nobody is doing is not a choice. No ACTION greys out a day's own pick — one of its
options is always chosen — but the day switching itself off does.

An action that scores on two different days is written ONCE and placed in both — the
hero (Monday and Thursday) and the drone components (Monday and Wednesday). They are
the same control with the same words; only the day's settings are separate, which is
what makes «Monday's ceiling» and «Thursday's ceiling» two numbers rather than one.

One week is not like the next, so the settings live in **sets** the operator keeps side
by side — «Накопление» and «Пуш» to start with — and every day says which set it is
played from. Monday may be hoarding while Saturday pushes. The widgets are a view of the
day's set: editing them writes into it, and switching a day's set puts the other week's
numbers on screen.

**Nothing here presses anything.** The tab is the plan — a set of choices kept in the
profile. Every ability is a scenario under `src/lastwar_bot/actions/` and the panel
only plays them (CLAUDE.md), so the day a scenario exists for one of these boxes the
wiring reads :meth:`plan` and runs it with those numbers. None of them exists yet,
which is why the tab needs no daemon, no client and no game.
"""
from __future__ import annotations

import itertools
import tkinter as tk
from tkinter import ttk

from ..widgets import NumericEntry, ScrollableFrame, font as ui_font, tk_stringvar
from .base import PanelTab

#: The scenario that writes the duel down — both sides, every day, into the profile's
#: own ranking history. The tab does not know what it does; it plays it and reports what
#: came back (CLAUDE.md: every ability is a scenario, the panel only plays them).
COLLECT_ACTION = "collect_vs_duel"

#: One per tab EVER BUILT, and the reason is the freeze of #1211. A ttk style belongs to
#: the interpreter, not to the widget that made it — so two open profiles showing this
#: tab shared `VsDuelWrap<indent>` between them, and one page's re-wrap re-laid the
#: other page out, whose <Configure> re-wrapped it back. Six day frames did the same to
#: each other inside a single tab. Measured: one tab settled in 1.1 s, three took 5.0 s,
#: and a single window resize with three of them open cost 4.4 seconds of re-wrapping —
#: in pages nobody was looking at. Every day frame gets a namespace of its own here, so
#: a wrap reaches exactly the widgets it is the wrap of.
_WRAP_NS = itertools.count()


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
    """A pick of one option out of several.

    ``options`` is ``((value, locale key), …)``: the value is what the profile keeps and
    what :meth:`VsDuelTab.plan` answers with, the key is what the person reads. The
    first option is the default.

    Two places and two shapes. Given to an action it belongs to it the way a
    :class:`_Sub` does — a dropdown, greyed out with its action. Placed in a day
    directly it is that day's own decision, with no box above it to switch off, and
    then ``radio=True`` draws it as a row of radio buttons: two ways of spending a day
    are read at a glance, where a list would hide one of them.
    """

    def __init__(self, key: str, label: str, options: tuple,
                 radio: bool = False) -> None:
        self.key, self.label, self.options = key, label, options
        self.radio = radio

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


class _Group:
    """A named block INSIDE a day: a routine of its own, under its own conditions.

    Wednesday is why it exists. Its research is two different routines, not one list of
    boxes: what runs at any hour of the day (speed the running research up, collect what
    is finished), and what only runs inside the science minister's buff — five minutes
    in which a research is started, hurried and collected, over and over until the window
    shuts. Same words in both would read as a duplicate; a frame around each, with a line
    saying when it applies, is what makes them two.

    The block is presentation and scope, not a namespace: the actions inside it keep
    their own keys, so the profile and :meth:`VsDuelTab.plan` stay flat.
    """

    def __init__(self, label: str, items: tuple, hint: str = "") -> None:
        self.label, self.items, self.hint = label, items, hint


def walk_items(items):
    """Every item of a day in the order it is drawn, with the groups opened out.

    One place that knows a group holds items, so building, saving and planning cannot
    disagree about what a day contains.
    """
    for item in items:
        if isinstance(item, _Group):
            yield from walk_items(item.items)
        else:
            yield item


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
#: The Tech Center's own eighteen tabs, in the order the game draws them, as
#: ``(value, locale key)``.
#:
#: THE VALUE IS THE GAME'S OWN TAB ID, not a word — that is what a scenario will aim
#: with, and it does not move when the wording does. Where they come from, so nobody has
#: to find them twice (docs/research/tech-center-tabs.md): the running client's
#: `DataCenter.ScienceTemplateManager.scienceTabTemplateDic`, one record per tab with an
#: `id`, an `order` and a `name` that is a key into the game's own translation tables
#: (docs/research/game-locale-tables.md). The words below are the game's, read out of
#: those tables in each language — not a translation of the English.
#:
#: The id order is not the display order: the truck tab (13) is drawn tenth, and 10, 11
#: and 12 come after it. The list below is in DISPLAY order, which is what a person sees.
RESEARCH_CATEGORIES: tuple = (
    ("1", "vsduel.research_category.development"),
    ("2", "vsduel.research_category.economy"),
    ("3", "vsduel.research_category.hero"),
    ("4", "vsduel.research_category.units"),
    ("5", "vsduel.research_category.squad1"),
    ("6", "vsduel.research_category.squad2"),
    ("7", "vsduel.research_category.squad3"),
    ("8", "vsduel.research_category.squad4"),
    ("9", "vsduel.research_category.alliance_duel"),
    ("13", "vsduel.research_category.intercity_truck"),
    ("12", "vsduel.research_category.special_forces"),
    ("10", "vsduel.research_category.siege_to_seize"),
    ("11", "vsduel.research_category.defense_fortifications"),
    ("14", "vsduel.research_category.tank_mastery"),
    ("15", "vsduel.research_category.missile_mastery"),
    ("16", "vsduel.research_category.aircraft_mastery"),
    ("17", "vsduel.research_category.age_of_oil"),
    ("18", "vsduel.research_category.tactical_weapon"),
)

#: What the category picker holds while no particular category is chosen — and, for now,
#: the only thing it can hold.
CATEGORY_ANY = "any"


def _research_category() -> _Choice:
    return _Choice("category", "vsduel.research_category",
                   ((CATEGORY_ANY, "vsduel.research_category.any"),)
                   + RESEARCH_CATEGORIES)


#: The key, under each day, of the box in the group's title: «this day is played».
#: It is a setting like any other — it lives in the day's set, so a week of hoarding may
#: sit Thursday out while a week of pushing plays it.
DAY_ENABLED = "enabled"

#: How many day groups stand side by side. Six days, so two columns is three rows —
#: a week that fits on the page instead of a column that has to be scrolled through.
DAY_COLUMNS = 2

#: The duel week, Monday first — the order the groups are drawn in, left to right and
#: then down, so the week reads the way it is written. A day whose actions are still to
#: be written down carries an empty tuple and draws a «later» line, which is all it takes
#: to add one: put its actions here and give them locale keys.
DAYS: tuple = (
    ("mon", (
        _drone_parts(),
        _hero_level(),
        _Action("drone_level", "vsduel.drone_level",
                _Amount("drone_gears", "vsduel.drone_gears")),
        # Last of the day on purpose: it is the one with a clock on it — the squads have
        # to be digging BEFORE the daily reset for the points to count.
        _Action("mines_before_reset", "vsduel.mines_before_reset"),
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
        # Two routines, not one list: see _Group. The first is the day's ordinary
        # research work; the second only happens while the minister's buff is up.
        _Group("vsduel.wed.running", (
            _Action("research_speedup", "vsduel.research_speedup"),
            _Action("research_collect", "vsduel.research_collect"),
        ), hint="vsduel.wed.running.hint"),
        _Group("vsduel.wed.ministry", (
            _Action("research_start", "vsduel.research_start",
                    choice=_research_category()),
        ), hint="vsduel.wed.ministry.hint"),
    )),
    ("thu", (
        _hero_level(),
        _Action("hero_rank_ur", "vsduel.hero_rank_ur"),
        _Action("hero_rank_ssr", "vsduel.hero_rank_ssr"),
        # The extra chests are not a second thing to do: they are how far the wall is
        # pushed when what is already in the bag runs out — the hero's experience boxes
        # in another shape.
        _Action("honour_wall", "vsduel.honour_wall",
                subs=(_Sub("extra_chests", "vsduel.honour_wall_chests"),)),
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
    ("sat", (
        # The shield is not «do it or do not» but «which way»: the same day's points come
        # either from two twelve-hour shields or from one that lasts a day. So it is a
        # pick rather than a box — there is no state in which neither is chosen.
        _Choice("shield", "vsduel.shield",
                (("twice_12h", "vsduel.shield.twice_12h"),
                 ("once_24h", "vsduel.shield.once_24h")), radio=True),
        _Action("shield_buy", "vsduel.shield_buy"),
        _Action("mine_points", "vsduel.mine_points"),
    )),
)


# ---------------------------------------------------------------------------
# the sets of settings, and the two a fresh profile starts with
# ---------------------------------------------------------------------------
#
# One week is not like the next: an alliance saving itself for a push spends nothing it
# does not have to, and the week it pushes it spends everything. So the settings are
# kept in SETS, and each day says which set it is played from — Monday may be hoarding
# while Saturday pushes.
#
# A set holds the whole week (`{"mon.hero_level": True, "mon.hero_exp_m": "30", …}`),
# and a day reads only its own keys out of it. That is what lets two days share a set
# without treading on each other: editing Monday writes Monday's keys, and nothing else.

#: The two sets a fresh profile is given. Ids are stable strings; the NAME comes from a
#: locale key until somebody renames it, because a set called «Накопление» in a German
#: panel would be a word written in the code (CLAUDE.md).
PRESET_HOARD = "hoard"
PRESET_PUSH = "push"


def _base_values() -> dict:
    """Every day played, every box of the week ticked, every ceiling empty, every pick
    on its default.

    The ground both sets are built from: a duel day is spent DOING the things, and what
    tells «hoard» from «push» apart is how much each is allowed to spend.
    """
    values: dict = {}
    for day, items in DAYS:
        values[f"{day}.{DAY_ENABLED}"] = True
        for item in walk_items(items):
            if isinstance(item, _Choice):
                values[f"{day}.{item.key}"] = item.default
                continue
            values[f"{day}.{item.key}"] = True
            if item.amount is not None:
                values[f"{day}.{item.amount.key}"] = item.amount.default
            for sub in item.subs:
                values[f"{day}.{item.key}.{sub.key}"] = True
            if item.choice is not None:
                values[f"{day}.{item.key}.{item.choice.key}"] = item.choice.default
    return values


#: What each set changes about the ground. Only the things that SPEND something the
#: account is storing: breaking experience boxes out of the bag, buying shields, and
#: whether Saturday's day of cover costs one shield or two.
#:
#: TODO(#1200): the two ceilings — millions of experience on Monday and Thursday, gears
#: on Monday — are left EMPTY in both sets, which reads as «no ceiling». «Hoard» is
#: supposed to hold them down to what the 7.2 M points of the chests actually need, and
#: nobody has told the panel how many millions and how many gears that is. A number
#: invented here would be a budget an operator believes is theirs; the boxes stay empty
#: until the real ones are known.
_HOARD_OVERRIDES = {
    "mon.hero_level.exp_boxes": False,
    "thu.hero_level.exp_boxes": False,
    "sat.shield_buy": False,
    "sat.shield": "once_24h",
}

_PUSH_OVERRIDES = {
    "mon.hero_level.exp_boxes": True,
    "thu.hero_level.exp_boxes": True,
    "sat.shield_buy": True,
    "sat.shield": "twice_12h",
}


def default_presets() -> list:
    """The two sets a profile that has never seen this tab is given."""
    hoard = dict(_base_values())
    hoard.update(_HOARD_OVERRIDES)
    push = dict(_base_values())
    push.update(_PUSH_OVERRIDES)
    return [{"id": PRESET_HOARD, "name_key": "vsduel.preset.hoard", "name": "",
             "values": hoard},
            {"id": PRESET_PUSH, "name_key": "vsduel.preset.push", "name": "",
             "values": push}]


class PresetStore:
    """The sets, in the order they are offered — no Tk, so it can be read on its own.

    A record is ``{"id", "name_key", "name", "values"}``. ``name_key`` is what the two
    shipped sets are called (a locale key, so they read in the panel's language);
    renaming one replaces it with a ``name`` the person typed, and from then on that is
    what it is called in every language — it is theirs, not ours.
    """

    def __init__(self, records=None) -> None:
        self._items: list = []
        for record in (records if isinstance(records, list) else []):
            if not isinstance(record, dict) or not record.get("id"):
                continue
            self._items.append({
                "id": str(record["id"]),
                "name_key": str(record.get("name_key") or ""),
                "name": str(record.get("name") or ""),
                "values": dict(record.get("values") or {}),
            })
        if not self._items:
            self._items = default_presets()

    # -- reading --------------------------------------------------------------
    def ids(self) -> list:
        return [item["id"] for item in self._items]

    def has(self, pid: str) -> bool:
        return any(item["id"] == pid for item in self._items)

    def index_of(self, pid: str) -> int:
        for i, item in enumerate(self._items):
            if item["id"] == pid:
                return i
        return 0

    def first(self) -> str:
        return self._items[0]["id"]

    def values(self, pid: str) -> dict:
        for item in self._items:
            if item["id"] == pid:
                return item["values"]
        return self._items[0]["values"]

    def name(self, pid: str, translate) -> str:
        """What this set is called, in the panel's language where it is ours."""
        for item in self._items:
            if item["id"] == pid:
                return item["name"] or translate(item["name_key"])
        return ""

    def names(self, translate) -> list:
        return [self.name(pid, translate) for pid in self.ids()]

    def as_list(self) -> list:
        return [dict(item, values=dict(item["values"])) for item in self._items]

    # -- changing -------------------------------------------------------------
    def add(self, name: str, values: dict) -> str:
        """A new set, named by the person and seeded with ``values``. Returns its id."""
        taken = set(self.ids())
        pid, n = "set", 1
        while f"{pid}{n}" in taken:
            n += 1
        pid = f"{pid}{n}"
        self._items.append({"id": pid, "name_key": "", "name": name,
                            "values": dict(values)})
        return pid

    def rename(self, pid: str, name: str) -> None:
        for item in self._items:
            if item["id"] == pid:
                item["name"], item["name_key"] = name, ""

    def remove(self, pid: str) -> bool:
        """Drop a set. The LAST one cannot go — a day has to be played from something."""
        if len(self._items) < 2:
            return False
        before = len(self._items)
        self._items = [item for item in self._items if item["id"] != pid]
        return len(self._items) < before

    def put(self, pid: str, values: dict) -> None:
        """Write a day's values back into the set it is played from."""
        for item in self._items:
            if item["id"] == pid:
                item["values"].update(values)


class VsDuelTab(PanelTab):
    """The duel plan: a group per day, a box per action, and — under an action — the
    ceiling it spends against and the boxes and pickers that say how it is done.

    The whole thing is kept in SETS the operator switches between, one chosen per day
    (see the section above this class)."""

    ID = "vs_duel"
    TITLE_KEY = "tab.vs_duel"
    ORDER = 330
    #: Still being written: hidden unless «Разработка» is on (#1273). The mark
    #: comes off when this tab's abilities are proven live and said so in
    #: `docs/farming.md` (`PanelTab.IN_DEVELOPMENT`).
    IN_DEVELOPMENT = True
    LOCALE_NS = ("vsduel",)
    #: The client, to read the duel out of, and the scenarios, to read WITH. The plan
    #: itself still costs nothing — this is what «Записать дуэль» needs (#1304).
    NEEDS = frozenset({"daemon", "actions"})

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
        #: its picker, as "<the dependent's own name>" -> (widget, the variables that
        #: ALL have to be on for it to be live, the state to put it back into). The
        #: day's own box is one of those variables, so a day switched off greys what its
        #: actions carry without every caller having to remember it.
        self._dependents: dict = {}
        #: What goes grey with the DAY and nothing else: the action boxes themselves,
        #: the labels beside the ceilings, a day's own radio buttons, a group's frame
        #: and its line of explanation. As (widget, day's variable, the live state).
        self._day_gated: list = []
        #: The day frame -> the widgets in it whose text re-wraps to its width, each
        #: with how far it is indented inside the frame. Half a panel is not wide enough
        #: for «Открывать сундуки опыта героя при необходимости» on one line, and a
        #: fixed `wraplength` would be wrong at every width but the one it was measured
        #: at, so the wrapping follows the frame instead. See :meth:`_rewrap`.
        self._wrapped: dict = {}
        #: This tab's own corner of the style database, and a number per day frame in
        #: it (see :data:`_WRAP_NS`). Nothing this tab configures may be read by another
        #: tab — or by another day of this one.
        self._wrap_ns = f"VsDuel{next(_WRAP_NS)}"
        self._box_no: dict = {}
        #: The week is drawn on first show, not at build time (see :meth:`build`), and
        #: this says whether it has been. Everything a set, a plan or a saved profile
        #: needs exists whatever it says: the variables are made below, in `__init__`.
        self._week = None
        self._week_built = False
        #: The wrap each of those styles is currently set to — what keeps :meth:`_rewrap`
        #: from configuring a style to the width it already has, and so from a
        #: <Configure> that feeds itself.
        self._wrap_at: dict = {}
        #: The day frames with a re-wrap already queued for idle time — what turns a
        #: burst of <Configure> into one pass. See :meth:`_rewrap_soon`.
        self._rewrap_due: dict = {}
        #: "<day>.<action>.<choice>" -> (combobox, the choice) — what a language change
        #: has to re-fill, since a combobox's list is not a widget option `tr` can set.
        self._combos: dict = {}
        #: day -> the names of every variable that belongs to it. What makes «read this
        #: day out of its set» and «write this day back» one line each.
        self._keys_by_day: dict = {day: [] for day, _items in DAYS}
        #: The sets themselves, and which one each day is played from.
        self._store = PresetStore()
        self._day_set: dict = {day: tk.StringVar(master=master,
                                                 value=self._store.first())
                               for day, _items in DAYS}
        #: What the last «Записать дуэль» came back with, and whether one is running.
        #: In `__init__` rather than `build()` because a saved block, a phone's screen
        #: and the button itself all reach a tab nobody has opened (docs/panel-tabs.md).
        self._collected = tk_stringvar(master)
        self._collecting = False
        #: The counts of the last read — sides, days, rows — or None before the first.
        self._collect_counts = None
        #: The set the buttons at the top act on, its picker, and the day pickers — all
        #: re-filled when a set is added, renamed, dropped, or the language changes.
        self._managed = self._store.first()
        self._set_combo = None
        self._day_combos: dict = {}
        for day, items in DAYS:
            name = f"{day}.{DAY_ENABLED}"
            self._flags[name] = tk.BooleanVar(master=master, value=True)
            # A set written before a day could be sat out has no such key, and the
            # absence has to read as ON: those weeks were played in full.
            self._defaults[name] = True
            self._keys_by_day[day].append(name)
            for item in walk_items(items):
                if isinstance(item, _Choice):           # the day's own pick
                    name = f"{day}.{item.key}"
                    self._choices[name] = tk.StringVar(master=master,
                                                       value=item.default)
                    self._defaults[name] = item.default
                    self._keys_by_day[day].append(name)
                    continue
                action = item
                name = f"{day}.{action.key}"
                self._flags[name] = tk.BooleanVar(master=master, value=False)
                self._keys_by_day[day].append(name)
                if action.amount is not None:
                    name = f"{day}.{action.amount.key}"
                    self._amounts[name] = tk.StringVar(master=master,
                                                       value=action.amount.default)
                    self._defaults[name] = action.amount.default
                    self._keys_by_day[day].append(name)
                for sub in action.subs:
                    name = f"{day}.{action.key}.{sub.key}"
                    self._flags[name] = tk.BooleanVar(master=master, value=False)
                    self._keys_by_day[day].append(name)
                if action.choice is not None:
                    name = f"{day}.{action.key}.{action.choice.key}"
                    self._choices[name] = tk.StringVar(master=master,
                                                       value=action.choice.default)
                    self._defaults[name] = action.choice.default
                    self._keys_by_day[day].append(name)

    # -- UI -------------------------------------------------------------------
    def build(self) -> None:
        """The tab's frame and its top row — NOT the week (#1211).

        The six day frames are some two hundred widgets that lay out against each other
        in two uniform columns, and building them cost **2.3 seconds of the page build**
        against 67–210 ms for every other tab in the panel. A profile's page is built
        when the panel opens and when a profile is switched to for the first time, so
        that was two and a half seconds of a window that answered nothing, for a tab
        nobody had asked to see.

        Nothing but the widgets waits: every variable, every default and every key of
        the week is made in `__init__`, so the plan the duel scenarios read, the
        settings the profile saves and the sets they live in all answer exactly the same
        before the week is drawn as after it. :meth:`on_show` draws it, once.
        """
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.tr(ttk.Label(bar, font=ui_font(size=15, weight="bold")),
                "tab.vs_duel").pack(side="left")

        # «Записать дуэль» — a press that STARTS the reading and then says what came
        # back. It marks nothing: the line beside it is the answer the game gave, so a
        # week with a missing day goes on saying so until the game says otherwise.
        self.tr(ttk.Button(bar, command=self.collect), "vsduel.collect").pack(
            side="right")
        ttk.Label(bar, textvariable=self._collected, foreground="#888").pack(
            side="right", padx=(0, 10))

        self.tr(ttk.Label(self.parent, foreground="#888", wraplength=640,
                          justify="left"), "vsduel.hint").pack(
            anchor="w", padx=10, pady=(0, 6))

        self._build_sets_bar()

        self._week = ScrollableFrame(self.parent)
        self._week.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._refresh_set_lists()
        self._load_all_days()
        self._retranslate_choices()
        self._sync_dependents()
        self._paint_collected()

    def _build_week(self) -> None:
        """The six day frames, drawn once — the first time somebody looks at the tab."""
        if self._week_built or getattr(self, "_week", None) is None:
            return
        self._week_built = True
        scroll = self._week
        # `uniform` is what keeps the columns the same width whatever is inside them:
        # without it Friday's six one-line boxes would squeeze the column Monday's
        # ceilings are in, and the week would look ragged.
        for column in range(DAY_COLUMNS):
            scroll.columnconfigure(column, weight=1, uniform="vsduel.day")
        for index, (day, items) in enumerate(DAYS):
            box = ttk.LabelFrame(scroll, padding=8)
            box.grid(row=index // DAY_COLUMNS, column=index % DAY_COLUMNS,
                     sticky="nsew", padx=(0, 6), pady=(0, 8))
            self._wrapped[box] = []
            self._build_day_switch(box, day)
            self._build_day_set(box, day)
            self._build_items(box, day, items, day_box=box)
            box.bind("<Configure>", lambda _e, b=box: self._rewrap_soon(b))
        # The widgets are a VIEW of the sets, so they are filled from them here — the
        # values themselves have been right since `apply_config`, whenever that was.
        self._refresh_set_lists()
        self._load_all_days()
        self._retranslate_choices()
        self._sync_dependents()

    # -- the sets ------------------------------------------------------------
    def _build_sets_bar(self) -> None:
        """The row that makes, renames and drops sets. Which set the buttons act on is
        its own picker: with a set chosen per day there is no «current» one."""
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(0, 6))
        self.tr(ttk.Label(bar), "vsduel.sets").pack(side="left", padx=(0, 6))
        self._set_combo = ttk.Combobox(bar, state="readonly", width=24)
        self._set_combo.pack(side="left")
        self._set_combo.bind("<<ComboboxSelected>>", self._on_managed)
        self.tr(ttk.Button(bar, command=self._new_set), "vsduel.sets.new").pack(
            side="left", padx=(8, 0))
        self.tr(ttk.Button(bar, command=self._rename_set), "vsduel.sets.rename").pack(
            side="left", padx=(4, 0))
        self.tr(ttk.Button(bar, command=self._delete_set), "vsduel.sets.delete").pack(
            side="left", padx=(4, 0))
        self.tr(ttk.Label(self.parent, foreground="#888", wraplength=640,
                          justify="left"), "vsduel.sets.hint").pack(
            anchor="w", padx=10, pady=(0, 6))

    def _build_day_switch(self, box, day: str) -> None:
        """The day's name, drawn AS the box that says whether the day is played.

        The group's title and the switch are one widget rather than two: a title with a
        box under it would read as "Monday, and by the way here is an action called
        Monday". Tk's own idiom for this is `labelwidget`, and the label is where the eye
        goes first — which is what a master switch wants to be.
        """
        switch = self.tr(
            ttk.Checkbutton(box, variable=self._flags[f"{day}.{DAY_ENABLED}"],
                            command=self._sync_dependents), f"vsduel.day.{day}")
        box.configure(labelwidget=switch)

    def _build_day_set(self, box, day: str) -> None:
        """The day's own picker: which set this day is played from.

        It does NOT go grey with the day, and that is deliberate: the box above it lives
        IN the set this picker chooses, so greying the picker would trap a day that was
        switched off — to move it to a week where it is played you would first have to
        switch it back on in the week where it is not.
        """
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(0, 6))
        self.tr(ttk.Label(row, foreground="#888"), "vsduel.day.set").pack(
            side="left", padx=(0, 6))
        combo = ttk.Combobox(row, state="readonly", width=24)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _e, d=day: self._on_day_set(d))
        self._day_combos[day] = combo

    def _refresh_set_lists(self) -> None:
        """Re-fill every picker from the store and show what each one is on.

        Called after a set is made, renamed or dropped — and on a language change, since
        the two shipped sets are named by a locale key.
        """
        names = self._store.names(self.t)
        if not self._store.has(self._managed):
            self._managed = self._store.first()
        for day, var in self._day_set.items():
            if not self._store.has(var.get()):
                var.set(self._store.first())
        try:
            if self._set_combo is not None:
                self._set_combo.configure(values=names)
                self._set_combo.current(self._store.index_of(self._managed))
            for day, combo in self._day_combos.items():
                combo.configure(values=names)
                combo.current(self._store.index_of(self._day_set[day].get()))
        except tk.TclError:
            pass

    def _on_managed(self, _event=None) -> None:
        index = self._set_combo.current()
        ids = self._store.ids()
        if 0 <= index < len(ids):
            self._managed = ids[index]

    def _on_day_set(self, day: str) -> None:
        """This day is played from another set now: keep the old one, show the new."""
        index = self._day_combos[day].current()
        ids = self._store.ids()
        if not (0 <= index < len(ids)) or ids[index] == self._day_set[day].get():
            return
        self._store_day(day)                     # what is on screen belongs to the OLD set
        self._day_set[day].set(ids[index])
        self._load_day(day)
        self._sync_dependents()

    def _day_values(self, day: str) -> dict:
        """What this day's widgets are showing, as a set stores it."""
        out: dict = {}
        for name in self._keys_by_day[day]:
            if name in self._flags:
                out[name] = bool(self._flags[name].get())
            elif name in self._amounts:
                out[name] = self._amounts[name].get()
            else:
                out[name] = self._choices[name].get()
        return out

    def _store_day(self, day: str) -> None:
        self._store.put(self._day_set[day].get(), self._day_values(day))

    def _store_all_days(self) -> None:
        for day, _items in DAYS:
            self._store_day(day)

    def _load_day(self, day: str) -> None:
        """Put the set this day is played from into its widgets."""
        values = self._store.values(self._day_set[day].get())
        for name in self._keys_by_day[day]:
            if name in self._flags:
                # Only the day's own box has a default; every action box that a set is
                # silent about stays unticked, as it always did.
                self._flags[name].set(bool(values.get(
                    name, self._defaults.get(name, False))))
            elif name in self._amounts:
                self._amounts[name].set(str(values.get(
                    name, self._defaults.get(name, ""))))
            else:
                self._choices[name].set(str(values.get(
                    name, self._defaults.get(name, ""))))
        self._retranslate_choices()

    def _load_all_days(self) -> None:
        for day, _items in DAYS:
            self._load_day(day)

    def _current_values(self) -> dict:
        """Everything on screen right now, across the days — what a new set starts as."""
        out: dict = {}
        for day, _items in DAYS:
            out.update(self._day_values(day))
        return out

    def _ask_name(self, title: str, prompt: str, initial: str = "") -> str:
        from tkinter import simpledialog

        answer = simpledialog.askstring(self.t(title), self.t(prompt),
                                        initialvalue=initial, parent=self.rt.root)
        return (answer or "").strip()

    def _name_taken(self, name: str) -> bool:
        return name.casefold() in {n.casefold() for n in self._store.names(self.t)}

    def _refuse(self, key: str) -> None:
        from tkinter import messagebox

        messagebox.showerror(self.t("vsduel.sets.refused"), self.t(key),
                             parent=self.rt.root)

    def _new_set(self) -> None:
        """A new set, holding what is on screen now — so it is edited from where the
        person is rather than from nothing."""
        name = self._ask_name("vsduel.sets.new.title", "vsduel.sets.new.prompt")
        if not name:
            return
        if self._name_taken(name):
            self._refuse("vsduel.sets.taken")
            return
        self._store_all_days()
        self._managed = self._store.add(name, self._current_values())
        self._refresh_set_lists()
        self.rt.settings.changed()

    def _rename_set(self) -> None:
        old = self._store.name(self._managed, self.t)
        name = self._ask_name("vsduel.sets.rename.title", "vsduel.sets.rename.prompt",
                              old)
        if not name or name == old:
            return
        if self._name_taken(name):
            self._refuse("vsduel.sets.taken")
            return
        self._store.rename(self._managed, name)
        self._refresh_set_lists()
        self.rt.settings.changed()

    def _delete_set(self) -> None:
        from tkinter import messagebox

        name = self._store.name(self._managed, self.t)
        if len(self._store.ids()) < 2:
            self._refuse("vsduel.sets.last_one")
            return
        if not messagebox.askyesno(self.t("vsduel.sets.delete.title"),
                                   self.t("vsduel.sets.delete.confirm", name=name),
                                   parent=self.rt.root):
            return
        self._store_all_days()
        gone = self._managed
        self._store.remove(gone)
        # A day left pointing at nothing is played from the first set instead — and it
        # is RELOADED, or it would keep showing numbers that no longer belong anywhere.
        for day, var in self._day_set.items():
            if var.get() == gone:
                var.set(self._store.first())
        self._managed = self._store.first()
        self._refresh_set_lists()
        self._load_all_days()
        self._sync_dependents()
        self.rt.settings.changed()

    def _build_items(self, box, day: str, items, day_box, indent: int = 0) -> None:
        """Draw a day's items into ``box`` — a group becomes a frame of its own.

        ``day_box`` is the DAY's frame however deep the recursion goes, and ``indent``
        is how far into it this level already sits: the two are what let the text wrap
        to the column it is drawn in (:meth:`_rewrap`).
        """
        for item in items:
            if isinstance(item, _Group):
                inner = ttk.LabelFrame(box, padding=8)
                # A LabelFrame has no state of its own, so its title is a Label rather
                # than a `text=` — otherwise the frame's name would stay black over a
                # day that is switched off, and only the day's frames would say so.
                title = self.tr(ttk.Label(inner, style="TLabelframe.Label"), item.label)
                inner.configure(labelwidget=self._gate_by_day(day, title))
                self._wraps(day_box, title, indent + 20)
                inner.pack(fill="x", pady=(2, 6))
                if item.hint:
                    hint = self._gate_by_day(day, self.tr(
                        ttk.Label(inner, foreground="#888", justify="left"), item.hint))
                    hint.pack(anchor="w", pady=(0, 4))
                    self._wraps(day_box, hint, indent + 20)
                self._build_items(inner, day, item.items, day_box, indent + 20)
            elif isinstance(item, _Choice):
                self._build_day_choice(box, day, item, day_box, indent)
            else:
                self._build_action(box, day, item, day_box, indent)

    def _build_day_choice(self, box, day: str, choice: _Choice, day_box,
                          indent: int) -> None:
        """A decision the DAY makes, with no box above it — drawn as radio buttons.

        No ACTION greys it out: one of its options is always chosen, so there is no state
        in which the pick means nothing (unlike a picker that belongs to an action). The
        day itself still does — a day nobody plays makes no decisions.
        """
        name = f"{day}.{choice.key}"
        label = self._gate_by_day(day, self.tr(ttk.Label(box), choice.label))
        label.pack(anchor="w", pady=(0, 2))
        self._wraps(day_box, label, indent)
        for value, label in choice.options:
            button = self._gate_by_day(day, self.tr(
                ttk.Radiobutton(box, variable=self._choices[name], value=value), label))
            button.pack(anchor="w", padx=(24, 0), pady=(0, 2))
            self._wraps(day_box, button, indent + 24)
        ttk.Frame(box, height=4).pack()          # air before the boxes below

    def _build_action(self, box, day: str, action: _Action, day_box,
                      indent: int) -> None:
        """One box, and — indented under it — what only makes sense while it is ticked:
        the ceiling it spends against, its detail boxes, its picker."""
        day_on = self._flags[f"{day}.{DAY_ENABLED}"]
        flag = self._flags[f"{day}.{action.key}"]
        button = self._gate_by_day(day, self.tr(
            ttk.Checkbutton(box, variable=flag, command=self._sync_dependents),
            action.label))
        button.pack(anchor="w", pady=(0, 2))
        self._wraps(day_box, button, indent)
        if action.amount is not None:
            name = f"{day}.{action.amount.key}"
            row = self._indented(box)
            self._gate_by_day(day, self.tr(ttk.Label(row, foreground="#888"),
                                           action.amount.label)).pack(
                side="left", padx=(0, 6))
            entry = NumericEntry(row, width=8, textvariable=self._amounts[name])
            entry.pack(side="left")
            self._dependents[name] = (entry, (day_on, flag), "normal")
        for sub in action.subs:
            name = f"{day}.{action.key}.{sub.key}"
            widget = self.tr(ttk.Checkbutton(box, variable=self._flags[name]),
                             sub.label)
            widget.pack(anchor="w", padx=(24, 0), pady=(0, 2))
            self._wraps(day_box, widget, indent + 24)
            self._dependents[name] = (widget, (day_on, flag), "normal")
        if action.choice is not None:
            name = f"{day}.{action.key}.{action.choice.key}"
            row = self._indented(box)
            self._gate_by_day(day, self.tr(ttk.Label(row, foreground="#888"),
                                           action.choice.label)).pack(
                side="left", padx=(0, 6))
            combo = ttk.Combobox(row, state="readonly", width=28)
            combo.pack(side="left")
            combo.bind("<<ComboboxSelected>>",
                       lambda _e, n=name: self._on_choice(n))
            self._combos[name] = (combo, action.choice)
            # Back to READONLY rather than «normal»: a combobox left normal is one a
            # person can type anything into, and the list is the whole point of it.
            self._dependents[name] = (combo, (day_on, flag), "readonly")
        if action.amount is not None or action.subs or action.choice is not None:
            ttk.Frame(box, height=4).pack()      # air before the next action's box

    def _indented(self, box):
        """A row under an action, offset so it reads as belonging to the box above."""
        row = ttk.Frame(box)
        row.pack(anchor="w", padx=(24, 0), pady=(0, 2))
        return row

    #: Off a day frame's width before its text has to wrap: the frame's own padding on
    #: both sides, its border, and the room a box or a radio button's indicator takes.
    _WRAP_MARGIN = 44
    #: No column is ever narrower than this for wrapping purposes — below it the words
    #: would break one per line, which is worse to read than a little clipping.
    _WRAP_FLOOR = 150

    def _wraps(self, day_box, widget, indent: int) -> None:
        """Say that ``widget``'s text re-wraps to ``day_box``, ``indent`` px in.

        A ttk Label takes `wraplength` as an option; a ttk Checkbutton and Radiobutton
        do NOT — the option exists only on the label ELEMENT inside them, reachable
        through a style. So a box is given a style of its own per indent, and the wrap
        is set on the style rather than on the widget.

        PER DAY FRAME AND PER TAB, not per indent (#1211). The six columns are the same
        width (`uniform`), so one style each looked like waste — but a style is the
        interpreter's, and configuring one re-lays out every widget wearing it. Sharing
        it meant Monday's re-wrap moved Tuesday, whose <Configure> re-wrapped Monday,
        across all six days AND across every open profile's copy of this tab. The waste
        is a dozen style names; what it buys is a re-wrap that stops.
        """
        style = ""
        if not isinstance(widget, ttk.Label):
            number = self._box_no.setdefault(day_box, len(self._box_no))
            style = f"{self._wrap_ns}b{number}i{indent}.{widget.winfo_class()}"
            widget.configure(style=style)
        self._wrapped.setdefault(day_box, []).append((widget, indent, style))

    def _rewrap_soon(self, day_box) -> None:
        """Re-wrap ``day_box`` once the layout has stopped moving.

        The first time the page is built the six frames go through several widths each
        before they settle, and a wrap done on every one of them re-lays the whole page
        out again — for a second or two the tab shows half-drawn lines over the
        half-drawn lines under them. Coalescing the whole storm into one idle-time pass
        makes the first paint the only one anybody sees.
        """
        if self._rewrap_due.get(day_box):
            return
        try:
            self._rewrap_due[day_box] = day_box.after_idle(self._rewrap, day_box)
        except tk.TclError:                 # the page went away mid-layout
            pass

    def on_show(self) -> None:
        """Somebody opened the duel: draw the week if it is not drawn, then wrap it.

        Both halves are here for the same reason — the week is the expensive thing in
        this tab and nothing that is not being looked at should pay for it (#1211). The
        wrap in particular refuses to run on a page nobody is looking at, and while the
        panel is building its tabs, or showing another profile, this one is exactly that.
        """
        self._build_week()
        for day_box in list(self._wrapped):
            self._rewrap(day_box)

    def _rewrap(self, day_box) -> None:
        """The day's column changed width — re-wrap the text in it.

        Nothing is re-set to the value it already has: a wrap re-lays the frame out,
        which fires <Configure> again, and an unguarded handler would do that for ever.

        AND NOTHING AT ALL while the page is off screen (#1211). A tab being built, or
        one belonging to a profile whose page is behind another, still gets <Configure>
        for every width its column passes through — and answering them re-laid out a
        page nobody could see, in the middle of the build of the page they COULD. The
        width is read again in :meth:`on_show`, which is the first moment the answer
        matters and the first moment it is right.
        """
        self._rewrap_due.pop(day_box, None)
        try:
            if not day_box.winfo_ismapped():
                return
            width = day_box.winfo_width()
        except tk.TclError:
            return
        if width <= 1:                     # not mapped yet; <Configure> will come again
            return
        styles = ttk.Style(day_box)
        for widget, indent, style in self._wrapped.get(day_box, ()):
            wrap = max(self._WRAP_FLOOR, width - self._WRAP_MARGIN - indent)
            try:
                if style:
                    if self._wrap_at.get(style) != wrap:
                        self._wrap_at[style] = wrap
                        styles.configure(style, wraplength=wrap)
                elif int(widget.cget("wraplength") or 0) != wrap:
                    widget.configure(wraplength=wrap)
            except (tk.TclError, ValueError):
                pass

    def _gate_by_day(self, day: str, widget):
        """Make ``widget`` go grey when ``day`` is switched off. Returns it, so it can
        be packed in the same breath it is registered in."""
        self._day_gated.append((widget, self._flags[f"{day}.{DAY_ENABLED}"],
                                str(widget.cget("state")) or "normal"))
        return widget

    def _sync_dependents(self) -> None:
        """Grey out what nobody is doing: everything in a day that is not played, and —
        inside a day that is — what an unticked action carries, since its ceiling has
        nothing to limit and its detail boxes have nothing to be a detail of."""
        for widget, day_on, live in self._day_gated:
            try:
                widget.configure(state=(live if day_on.get() else "disabled"))
            except tk.TclError:                 # the window went away mid-callback
                pass
        for widget, flags, live in self._dependents.values():
            try:
                widget.configure(state=(live if all(f.get() for f in flags)
                                        else "disabled"))
            except tk.TclError:
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
        # The two shipped sets are named by a locale key, so their pickers say the old
        # language until they are re-filled.
        self._refresh_set_lists()

    # -- what the wiring reads -------------------------------------------------
    def plan(self, day: str) -> dict:
        """What is ticked for ``day``, each action with its ceiling and its details.

        ``{"hero_level": {"limit": 30, "exp_boxes": True}}`` says «level the hero up,
        spending at most 30 million experience, and open experience boxes if that is
        what it takes to get there». ``"limit": None`` says the action has no ceiling —
        an empty field, or an action that spends nothing countable. An action that is
        not ticked is simply absent, and so is a day nobody has written actions for.

        A day whose box in the group's title is unticked is not played at all, and
        answers with ``{}`` — not with the actions that happen to be ticked inside it.
        That is the ONE thing that empties a day the person can still see filled in: the
        boxes keep what they were set to, so switching the day back on brings its plan
        back exactly as it was.

        A decision the day itself makes — Saturday's shield — is always there, under its
        own key as ``{"pick": <value>}``: one of its options is always chosen, so there
        is nothing for its absence to mean. Unless, of course, the day is not played.

        FLAT across a day's groups: an action keeps its own key wherever it is drawn, so
        Wednesday answers with `research_speedup` and `research_start` side by side. The
        frame around the second one says WHEN it runs to the person; the scenario that
        runs it knows the same thing without being told twice.
        """
        out: dict = {}
        for name, items in DAYS:
            if name != day:
                continue
            if not self._flags[f"{day}.{DAY_ENABLED}"].get():
                return {}
            for item in walk_items(items):
                if isinstance(item, _Choice):
                    out[item.key] = {"pick": self._choices[f"{day}.{item.key}"].get()}
                    continue
                action = item
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

    # -- writing the duel down --------------------------------------------------
    def collect(self) -> bool:
        """Play the scenario that writes the duel down. ``False`` if it could not start.

        The tab holds no opinion about what the duel IS — which message asks for it,
        which days come back, how a side is told from the other. All of that is
        `actions/collect_vs_duel.md`; this passes the profile's own ranking history as
        the place to write it and reports the counts the scenario left behind.
        """
        if self._collecting:
            return False
        self._collecting = True
        self._paint_collected()
        started = self.rt.play_async(
            COLLECT_ACTION, args={"store": self.rt.profiles.leaderboard_db()},
            tag="vsduel", on_result=self._collect_back, on_done=self._collect_done)
        if not started:
            self._collecting = False
            self._paint_collected()
            self.say("vsduel", "vsduel.collect.busy")
        return started

    def _collect_back(self, outcome) -> None:
        """What the scenario left in its own variables — never a guess of ours."""
        variables = (getattr(getattr(outcome, "ctx", None), "vars", {}) or {})
        if outcome is None or not getattr(outcome, "ok", False):
            self._collect_counts = None
            return
        self._collect_counts = {
            "sides": int(variables.get("VS_SIDES") or 0),
            "days": int(variables.get("VS_DAYS") or 0),
            "rows": int(variables.get("VS_ROWS") or 0),
        }

    def _collect_done(self) -> None:
        self._collecting = False
        self._paint_collected()
        counts = self._collect_counts
        if counts:
            self.say("vsduel", "vsduel.collect.done", **counts)
        else:
            self.say("vsduel", "vsduel.collect.nothing")

    def _paint_collected(self) -> None:
        """The line beside the button: reading, what came back, or never asked."""
        if self._collecting:
            self._collected.set(self.t("vsduel.collect.reading"))
        elif self._collect_counts:
            self._collected.set(self.t("vsduel.collect.done",
                                       **self._collect_counts))
        else:
            self._collected.set(self.t("vsduel.collect.never"))

    # -- persistence -----------------------------------------------------------
    # -- the phone ------------------------------------------------------------
    #
    # LOOKING, NOT EDITING. The plan is a week of ticked boxes and typed amounts, and
    # editing that with a thumb on a bus is how somebody spends a day's speedups on
    # the wrong day. What is worth carrying is the answer to «what is today for» —
    # which is one card, read off the boxes the window already holds.
    WEB_SCREEN = True

    def web_view(self) -> "dict | None":
        """Today's plan: what is ticked, and how much each is allowed to spend."""
        import time as _time

        day = DAYS[min(_time.localtime().tm_wday, len(DAYS) - 1)][0]
        items = []
        for item in walk_items(dict(DAYS)[day]):
            name = f"{day}.{item.key}"
            var = self._flags.get(name) or self._choices.get(name)
            if var is None:
                continue
            try:
                value = var.get()
            except Exception:              # noqa: BLE001 — a half-built window
                continue
            if isinstance(value, bool) and not value:
                continue                   # an unticked line is not part of today
            facts = []
            amount = getattr(item, "amount", None)
            if amount is not None and self._amounts.get(f"{day}.{amount.key}") is not None:
                try:
                    facts.append({"label": amount.label_key,
                                  "value": str(self._amounts[f"{day}.{amount.key}"].get())})
                except Exception:          # noqa: BLE001
                    pass
            # The line is one of the panel's own words, so it travels as a KEY.
            items.append({"label": item.label_key, "facts": facts})
        enabled = self._flags.get(f"{day}.{DAY_ENABLED}")
        # A phone can reach a tab whose window half was never drawn, so the line is
        # composed here rather than read out of whatever `build()` happened to leave.
        self._paint_collected()
        # The same press and the same reading the window has (#1304). It is a READ —
        # nothing is spent and nothing is marked — so it is exactly the kind of thing
        # worth having on a phone: the duel is written down from wherever you are, and
        # the line says what the game answered, not what anybody ticked.
        return {"cards": [{"title": f"vsduel.day.{day}", "items": items,
                           "empty": "vsduel.day.off"
                           if enabled is not None and not enabled.get()
                           else "vsduel.empty"},
                          {"title": "vsduel.collect",
                           "rows": [{"label": "vsduel.collect.last",
                                     "value": self._collected.get()}]}],
                "actions": [{"id": "collect", "label": "vsduel.collect"}]}

    def web_press(self, action, args) -> dict:
        if action != "collect":
            return {"error": "unknown"}
        return {"ok": self.collect()}

    def config(self) -> dict:
        """The sets, and which one each day is played from.

        What is on screen is folded back into the sets first: the widgets are a VIEW of
        the day's set, and a save that skipped this would write yesterday's values.
        """
        self._store_all_days()
        return {"presets": self._store.as_list(),
                "days": {day: var.get() for day, var in self._day_set.items()}}

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._store = PresetStore(raw.get("presets"))
        # A profile written before the sets existed holds one flat week. It is not
        # thrown away: it becomes the first set's values, and every day is played from
        # it — the operator finds their own choices where they left them.
        if not isinstance(raw.get("presets"), list) or not raw.get("presets"):
            flat = {k: v for k, v in raw.items() if k not in ("presets", "days")}
            if flat:
                self._store.put(self._store.first(), flat)
        days = raw.get("days") if isinstance(raw.get("days"), dict) else {}
        for day, var in self._day_set.items():
            wanted = str(days.get(day, "")) or self._store.first()
            var.set(wanted if self._store.has(wanted) else self._store.first())
        if not self._store.has(self._managed):
            self._managed = self._store.first()
        self._refresh_set_lists()
        self._load_all_days()
        self._sync_dependents()

    def persist_vars(self) -> list:
        return (list(self._flags.values()) + list(self._amounts.values())
                + list(self._choices.values()) + list(self._day_set.values()))


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(VsDuelTab))
