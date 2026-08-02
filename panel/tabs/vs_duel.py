"""The «VS Duel» tab: what the bot is allowed to do on each day of the alliance duel.

The duel scores a DIFFERENT set of actions every weekday (docs/game/daily_cycle.md),
so the tab is a column of day groups — Monday to Saturday, the whole week the duel
runs — and each group holds the actions that day pays points for.

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
nobody is doing is not a choice. A day's own pick never greys out — one of its options
is always chosen.

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
#: TODO(#1200): EMPTY ON PURPOSE, and what the search for them turned up so far.
#:
#: The game's own translation tables (docs/research/game-locale-tables.md) were read for
#: this. What they DO carry is the ALLIANCE technology's two categories — key `454119`
#: «Развитие / Development / Entwicklung» and `454120` «Война / War / Krieg», sitting
#: right under `454117` «Технологии Альянса» — which is a different window from the one
#: the science minister's buff speeds up.
#:
#: For the player's OWN Tech Center the tables carry no category strip at all: the techs
#: are grouped into chapters, and only the late ones are named (`tech_name_13..18` —
#: Intercity Truck, Tank Mastery, Missile Mastery, Aircraft Mastery, The Age of Oil,
#: Tactical Weapon); the early chapters have no top-level name key. The other
#: Combat/Economy/Development pairs in the tables belong to provably other screens — the
#: buffs window (`110289`/`110290`), the headquarters talents (`131002`…`131005`) and the
#: shop's pack types (`100068`/`100069`).
#:
#: So a category written here would still be a guess, and it would aim a scenario at
#: something that may not exist. Until the real names are confirmed the picker offers
#: «any» alone; filling this tuple is all it takes to offer them — plus each new locale
#: key in EVERY shipped locale, like anything else a person reads (CLAUDE.md).
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
    """Every box of the week ticked, every ceiling empty, every pick on its default.

    The ground both sets are built from: a duel day is spent DOING the things, and what
    tells «hoard» from «push» apart is how much each is allowed to spend.
    """
    values: dict = {}
    for day, items in DAYS:
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
        #: day -> the names of every variable that belongs to it. What makes «read this
        #: day out of its set» and «write this day back» one line each.
        self._keys_by_day: dict = {day: [] for day, _items in DAYS}
        #: The sets themselves, and which one each day is played from.
        self._store = PresetStore()
        self._day_set: dict = {day: tk.StringVar(master=master,
                                                 value=self._store.first())
                               for day, _items in DAYS}
        #: The set the buttons at the top act on, its picker, and the day pickers — all
        #: re-filled when a set is added, renamed, dropped, or the language changes.
        self._managed = self._store.first()
        self._set_combo = None
        self._day_combos: dict = {}
        for day, items in DAYS:
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
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.tr(ttk.Label(bar, font=ui_font(size=15, weight="bold")),
                "tab.vs_duel").pack(side="left")

        self.tr(ttk.Label(self.parent, foreground="#888", wraplength=640,
                          justify="left"), "vsduel.hint").pack(
            anchor="w", padx=10, pady=(0, 6))

        self._build_sets_bar()

        scroll = ScrollableFrame(self.parent)
        scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for day, items in DAYS:
            box = self.tr(ttk.LabelFrame(scroll, padding=8), f"vsduel.day.{day}")
            box.pack(fill="x", padx=(0, 4), pady=(0, 8))
            self._build_day_set(box, day)
            self._build_items(box, day, items)
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

    def _build_day_set(self, box, day: str) -> None:
        """The day's own picker: which set this day is played from."""
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
                self._flags[name].set(bool(values.get(name, False)))
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

    def _build_items(self, box, day: str, items) -> None:
        """Draw a day's items into ``box`` — a group becomes a frame of its own."""
        for item in items:
            if isinstance(item, _Group):
                inner = self.tr(ttk.LabelFrame(box, padding=8), item.label)
                inner.pack(fill="x", pady=(2, 6))
                if item.hint:
                    self.tr(ttk.Label(inner, foreground="#888", wraplength=560,
                                      justify="left"), item.hint).pack(
                        anchor="w", pady=(0, 4))
                self._build_items(inner, day, item.items)
            elif isinstance(item, _Choice):
                self._build_day_choice(box, day, item)
            else:
                self._build_action(box, day, item)

    def _build_day_choice(self, box, day: str, choice: _Choice) -> None:
        """A decision the DAY makes, with no box above it — drawn as radio buttons.

        Nothing greys it out: one of its options is always chosen, so there is no state
        in which the pick means nothing (unlike a picker that belongs to an action).
        """
        name = f"{day}.{choice.key}"
        self.tr(ttk.Label(box), choice.label).pack(anchor="w", pady=(0, 2))
        for value, label in choice.options:
            self.tr(ttk.Radiobutton(box, variable=self._choices[name], value=value),
                    label).pack(anchor="w", padx=(24, 0), pady=(0, 2))
        ttk.Frame(box, height=4).pack()          # air before the boxes below

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

        A decision the day itself makes — Saturday's shield — is always there, under its
        own key as ``{"pick": <value>}``: one of its options is always chosen, so there
        is nothing for its absence to mean.

        FLAT across a day's groups: an action keeps its own key wherever it is drawn, so
        Wednesday answers with `research_speedup` and `research_start` side by side. The
        frame around the second one says WHEN it runs to the person; the scenario that
        runs it knows the same thing without being told twice.
        """
        out: dict = {}
        for name, items in DAYS:
            if name != day:
                continue
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

    # -- persistence -----------------------------------------------------------
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
