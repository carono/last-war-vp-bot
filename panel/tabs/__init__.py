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
"""
from __future__ import annotations

import importlib


class TabSpec:
    """One registry entry. Holds the import path; loads the class on demand."""

    def __init__(self, tab_id: str, module: str, cls_name: str, order: int = 100,
                 default_enabled: bool = True, title_key: str | None = None,
                 aggregates: bool = False) -> None:
        self.id = tab_id
        self.module = module
        self.cls_name = cls_name
        self.order = order
        self.default_enabled = default_enabled
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

    def add(self, tab) -> None:
        self._live[tab.ID] = tab

    def get(self, tab_id: str):
        """The live tab, or ``None`` if this window does not have it."""
        return self._live.get(tab_id)

    @property
    def live(self) -> list:
        """Every built tab, in the order they were added — what the lifecycle loops walk."""
        return list(self._live.values())

    def __contains__(self, tab_id: str) -> bool:
        return tab_id in self._live

    def __len__(self) -> int:
        return len(self._live)


# Order numbers are spaced so a tab can be slotted between two without renumbering.
TABS: tuple = (
    TabSpec("scenarios", "panel.tabs.scenarios", "ScenariosTab", order=20),
    TabSpec("timers",    "panel.tabs.timers",    "TimersTab",    order=30),
    TabSpec("settings",  "panel.tabs.settings",  "SettingsTab",  order=40,
            aggregates=True),
    TabSpec("web",       "panel.tabs.web",       "WebTab",       order=45),
    TabSpec("chat",      "panel.tabs.chat",      "ChatTab",      order=50),
    TabSpec("alliance",  "panel.tabs.alliance",  "AllianceTab",  order=200),
    TabSpec("profile",   "panel.tabs.profile",   "ProfileTab",   order=210),
    TabSpec("inventory", "panel.tabs.inventory", "InventoryTab", order=220),
    TabSpec("heroes",    "panel.tabs.heroes",    "HeroesTab",    order=230),
    TabSpec("accounts",  "panel.tabs.accounts",  "AccountsTab",  order=240),
    TabSpec("stats",     "panel.tabs.stats",     "StatsTab",     order=250),
    TabSpec("rally",     "panel.tabs.rally",     "RallyTab",     order=300),
    TabSpec("secret_tasks", "panel.tabs.secret_tasks", "SecretTasksTab",
            order=310),
    TabSpec("command_post", "panel.tabs.command_post", "CommandPostTab",
            order=320),
    TabSpec("vs_duel",   "panel.tabs.vs_duel",   "VsDuelTab",    order=330),
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
    """
    if enabled is None:
        chosen = [s.id for s in TABS if s.default_enabled]
    else:
        chosen = []
        for tab_id in enabled:
            if tab_id in BY_ID:
                chosen.append(tab_id)
            elif on_unknown is not None:
                on_unknown(tab_id)
        seen = set(known if known is not None else enabled)
        chosen += [s.id for s in TABS
                   if s.default_enabled and s.id not in seen and s.id not in chosen]

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
