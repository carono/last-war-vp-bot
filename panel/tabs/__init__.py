"""The tab registry: which tabs exist, in what order, and which are on by default.

An explicit table, not an import scan — and LAZY, so `python -m panel.tabs.rally`
imports one tab rather than fourteen, and so that a tab which fails to import is a
missing tab rather than a panel that will not open.

Which tabs a window actually shows is the PROFILE's business
(docs/research/panel-tabs-refactor.md §5):

* an id in the profile that no longer exists in code is skipped, with a log line — a
  profile written by a newer build must not break an older panel;
* a tab in code the profile has NEVER HEARD OF is appended at its ``ORDER``, enabled if
  ``DEFAULT_ENABLED`` — a new tab appears without editing every profile by hand. Which
  is why the profile also keeps ``tabs.known``: without it "switched off" and "did not
  exist yet" look identical, and every tab an operator unticked would come straight
  back on the next start;
* a tab whose import or ``build()`` raises is skipped and reported, and the rest of the
  panel still opens.

…with ONE thing the profile does not get a say in: a tab still being written
(``TabSpec(in_development=True)`` / ``PanelTab.IN_DEVELOPMENT``) is not shown at all
unless the profile is in DEVELOPMENT MODE, which is «Разработка» being switched on and
nothing else (:data:`DEV_TAB`, #1273). The gate FILTERS and never edits: the profile's
own tick list and every tab's settings block are left exactly as they are, so nothing is
lost by a tab going quiet and nothing has to be restored when it comes back.
"""
from __future__ import annotations

import importlib
import threading


def _on_tk_thread() -> bool:
    """Is this the thread the event loop runs on? (The main one, in the panel and in
    `python -m panel.tabs.<id>` alike.) A widget may be made nowhere else."""
    return threading.current_thread() is threading.main_thread()


class TabSpec:
    """One registry entry. Holds the import path; loads the class on demand."""

    def __init__(self, tab_id: str, module: str, cls_name: str, order: int = 100,
                 default_enabled: bool = True, title_key: str | None = None,
                 aggregates: bool = False, in_development: bool = False) -> None:
        self.id = tab_id
        self.module = module
        self.cls_name = cls_name
        self.order = order
        self.default_enabled = default_enabled
        # Still being written (#1273) — hidden unless the profile is in DEVELOPMENT MODE
        # (`DEV_TAB` below). Declared here as well as on the class for the same reason
        # `aggregates` is: :func:`resolve` decides what to build before anything is
        # imported, and importing every module to read one boolean would undo the
        # laziness this table exists for. The contract test pins the two to each other.
        self.in_development = in_development
        # Whether this tab draws parts CONTRIBUTED BY OTHER TABS — «Настройки» and its
        # per-tab pages (§6). Declared here as well as on the class for the same reason
        # `title_key` is: :func:`build_order` has to answer before anything is imported,
        # and importing fifteen modules in one event-loop turn to read one boolean is
        # exactly the start-up stall the staged build exists to avoid (#1226). The
        # contract test pins the two to each other.
        self.aggregates = aggregates
        # The notebook needs a label BEFORE the tab is built — and importing a module
        # just to read one string would undo the laziness the registry exists for. By
        # convention that label is `tab.<id>`; the contract test pins every class to it.
        self.title_key = title_key or f"tab.{tab_id}"
        self._cls = None

    def load(self):
        """The tab class. Raises if the module does not import — the caller decides."""
        if self._cls is None:
            self._cls = getattr(importlib.import_module(self.module), self.cls_name)
        return self._cls

    def __repr__(self) -> str:
        return f"<TabSpec {self.id} order={self.order}>"


class TabRegistry:
    """The tabs a window actually built, by id — what ``rt.tabs`` is.

    A TAB MAY BE ABSENT: switched off in the profile, or skipped because it failed to
    build. So everything reaching across tabs goes through :meth:`get` and tolerates
    ``None`` (docs/research/panel-tabs-refactor.md §2). The panel already did this by
    accident (`getattr(self, "_secret_tasks_tab", None)`); here it is the contract.
    """

    def __init__(self) -> None:
        self._live: dict = {}
        #: Told about every tab this registry draws, once each — the container's hook
        #: for what can only be done to a tab that HAS widgets: tracing the variables
        #: it makes for the auto-save. ``None`` in a window that does not persist.
        self.on_realized = None

    def add(self, tab) -> None:
        self._live[tab.ID] = tab

    def get(self, tab_id: str):
        """The live tab, or ``None`` if this window does not have it.

        DRAWN BEFORE IT IS HANDED OVER, when the caller is the Tk thread: a tab reaching
        for another one wants to read its widgets, and since #1215 a tab nobody has
        opened has none yet (`PanelTab.LAZY`). Off the Tk thread nothing is drawn — a
        widget may only be made where the event loop is — so a background caller gets
        the tab as it stands and must hand the drawing over itself (`rt.post`) if it
        needs more than the tab's own state.
        """
        tab = self._live.get(tab_id)
        if tab is not None and _on_tk_thread():
            self.realize(tab)
        return tab

    def peek(self, tab_id: str):
        """The tab as it stands — undrawn if nobody has looked at it. ``None`` if absent.

        For the container and for tests: everything else wants :meth:`get`, which hands
        over a tab that is ready to be talked to.
        """
        return self._live.get(tab_id)

    def realize(self, tab) -> bool:
        """Draw ``tab`` if it is not drawn, and tell the container. ``True`` if it drew.

        The ONE door to `PanelTab.realize`, so that whatever the container has to do to
        a freshly drawn tab happens however it came to be drawn — shown in the notebook,
        opened on the phone, or reached for by another tab.

        A stand-in that is not a `PanelTab` — a test's fake screen, say — counts as
        drawn: it has no widgets to wait for and nothing here to draw them with.
        """
        if tab is None or getattr(tab, "built", True):
            return False
        tab.realize()
        if self.on_realized is not None:
            self.on_realized(tab)
        return True

    @property
    def live(self) -> list:
        """Every tab of this window, in the order they were added — drawn or not.

        What the lifecycle loops walk, and they check `tab.built` before touching one:
        an undrawn tab started nothing and holds nothing, so there is nothing in it for
        «Стоп всё», a profile switch or a shutdown to reach.
        """
        return list(self._live.values())

    @property
    def drawn(self) -> list:
        """Only the tabs somebody has looked at — the ones with widgets to talk to."""
        return [tab for tab in self._live.values() if tab.built]

    def __contains__(self, tab_id: str) -> bool:
        return tab_id in self._live

    def __len__(self) -> int:
        return len(self._live)


#: The tab whose being switched on IS «development mode» (#1273).
#:
#: There is no separate switch for it, on purpose. «Разработка» already means «this
#: profile is for working on the bot» — it ships off, it holds the sniffers and the
#: `actions/*.md` list, and a person who has ticked it has said the only thing a second
#: checkbox would have asked. A switch of its own would be a second answer to one
#: question, and the first time the two disagreed there would be nothing to settle it
#: with; this way the mode is visible in the same list that shows what it unhides.
DEV_TAB = "develop"

# Order numbers are spaced so a tab can be slotted between two without renumbering.
TABS: tuple = (
    TabSpec("checklist", "panel.tabs.checklist", "ChecklistTab", order=20),
    TabSpec("events",    "panel.tabs.events",    "EventsTab",    order=25),
    TabSpec("timers",    "panel.tabs.timers",    "TimersTab",    order=30),
    TabSpec("settings",  "panel.tabs.settings",  "SettingsTab",  order=40,
            aggregates=True),
    # …and no `web` at order 45: the remote control is one server for the whole WINDOW,
    # so its switch, port and token are a menu entry and a panel-wide block in
    # `profiles/settings.json` rather than a page inside one account (#1313).
    # `panel/runtime/web_control.py` owns them; `panel/profile.py::migrate_web_settings`
    # brought the profiles' copies across and swept the retired id out of their lists.
    TabSpec("chat",      "panel.tabs.chat",      "ChatTab",      order=50,
            in_development=True),
    TabSpec("alliance",  "panel.tabs.alliance",  "AllianceTab",  order=200,
            in_development=True),
    TabSpec("profile",   "panel.tabs.profile",   "ProfileTab",   order=210,
            in_development=True),
    TabSpec("inventory", "panel.tabs.inventory", "InventoryTab", order=220,
            in_development=True),
    TabSpec("heroes",    "panel.tabs.heroes",    "HeroesTab",    order=230,
            in_development=True),
    TabSpec("accounts",  "panel.tabs.accounts",  "AccountsTab",  order=240,
            in_development=True),
    TabSpec("stats",     "panel.tabs.stats",     "StatsTab",     order=250,
            in_development=True),
    TabSpec("rally",     "panel.tabs.rally",     "RallyTab",     order=300),
    TabSpec("secret_tasks", "panel.tabs.secret_tasks", "SecretTasksTab",
            order=310),
    TabSpec("command_post", "panel.tabs.command_post", "CommandPostTab",
            order=320, in_development=True),
    TabSpec("vs_duel",   "panel.tabs.vs_duel",   "VsDuelTab",    order=330,
            in_development=True),
    TabSpec("treasure_debug", "panel.tabs.treasure_debug", "TreasureDebugTab",
            order=340, default_enabled=False, in_development=True),
    TabSpec("develop",   "panel.tabs.develop",   "DevelopTab",   order=900,
            default_enabled=False),
)

BY_ID = {spec.id: spec for spec in TABS}


def ranker(order: "list | None" = None):
    """The sort key tabs are placed by: the PROFILE's order first, the declared one next.

    A function rather than a constant because the shell orders its own non-plugin tabs
    («Главная», the three still to move) into the same sequence — one rule, so the tab
    bar reads the same whichever half a tab comes from.
    """
    ranked = {tab_id: i for i, tab_id in enumerate(order or ())}

    def key(tab_id: str, default_order: int):
        return (ranked.get(tab_id, len(ranked) + default_order), default_order)
    return key


def chosen_ids(enabled: "list | None" = None, known: "list | None" = None,
               on_unknown=None) -> list:
    """The tabs this profile ASKS FOR — before the development gate is applied.

    Separate from :func:`resolve` because the «Вкладки» page needs both answers: what a
    profile asked for is what its tick boxes have to show, and a tab hidden by the gate
    must keep the answer it was given rather than be quietly unticked by a page it was
    not on (#1273).
    """
    if enabled is None:
        return [s.id for s in TABS if s.default_enabled]
    chosen = []
    for tab_id in enabled:
        if tab_id in BY_ID:
            chosen.append(tab_id)
        elif on_unknown is not None:
            on_unknown(tab_id)
    seen = set(known if known is not None else enabled)
    chosen += [s.id for s in TABS
               if s.default_enabled and s.id not in seen and s.id not in chosen]
    return chosen


def dev_mode(enabled: "list | None" = None, known: "list | None" = None) -> bool:
    """Is this profile in DEVELOPMENT MODE — i.e. is «Разработка» switched on? (#1273)

    The one definition, asked here by everything that needs it, so «what counts as
    development mode» cannot come to mean two things in two files (:data:`DEV_TAB`).
    """
    return DEV_TAB in chosen_ids(enabled, known)


def listed(enabled: "list | None" = None, known: "list | None" = None) -> list:
    """The specs «Настройки → Вкладки» offers a tick for, in the order they sit in.

    Every tab, unless the profile is out of development mode — then the ones still being
    written are not offered either, because a box for a tab that cannot appear is a box
    that does nothing and says nothing about why.
    """
    specs = sorted(TABS, key=lambda s: s.order)
    if dev_mode(enabled, known):
        return specs
    return [s for s in specs if not s.in_development]


def resolve(enabled: "list | None" = None, order: "list | None" = None,
            known: "list | None" = None, on_unknown=None) -> list:
    """The specs to build, in the order to build them.

    ``enabled`` / ``order`` / ``known`` come from the profile's ``tabs`` block; ``None``
    for any of them means "the defaults". ``on_unknown(tab_id)`` is told about an id in
    the profile that no longer exists in code.

    ``known`` is every tab this profile has already been offered. A tab that is in it
    and not in ``enabled`` was switched OFF and stays off; a tab in neither is new and
    appears. Falling back to ``enabled`` when the profile has no ``known`` list is what
    keeps a profile written before this existed behaving as it did.

    AND THEN THE DEVELOPMENT GATE (#1273): a tab marked `in_development` is dropped
    unless «Разработка» is among the chosen — whatever the profile says about it. That
    is a filter and not an edit: the profile's own list is left alone, so a tab ticked
    before it was marked comes straight back the moment the mode is on or the mark comes
    off, with its settings block untouched throughout.
    """
    chosen = chosen_ids(enabled, known, on_unknown)
    if DEV_TAB not in chosen:
        chosen = [t for t in chosen if not BY_ID[t].in_development]

    key = ranker(order)
    return sorted((BY_ID[t] for t in chosen), key=lambda s: key(s.id, s.order))


def build_order(specs) -> list:
    """The order the tabs are FILLED in — which is not the order they sit in.

    The notebook's pages are added in the profile's order and stay there; this is only
    the sequence they are built in, and one tab cares about it: «Настройки» is an
    AGGREGATOR (§6). It draws a page per tab that declares a `SETTINGS_PAGE_KEY`, and it
    can only draw the tabs that exist by the time it is built — so it has to be built
    after every one of them.

    It was not. «Настройки» sits at order 40 and «Ралли» at 300, so the settings page
    was drawn while `rt.tabs.live` still held two tabs, and «Авторалли» — the page whose
    squad list IS the auto-join's `squads` argument — was silently never drawn at all
    (#1237). Nothing failed: the aggregator collected the pages that were there, the
    auto-join read an empty list, and the operator had no control to fix it with.

    Ordering the BUILD rather than moving the tab is what keeps both true: «Настройки»
    stays third in the tab bar, where a person expects it, and is filled last.
    """
    return sorted(specs, key=lambda spec: 1 if spec.aggregates else 0)
