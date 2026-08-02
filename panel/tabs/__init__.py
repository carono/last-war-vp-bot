"""The tab registry: which tabs exist, in what order, and which are on by default.

An explicit table, not an import scan — and LAZY, so `python -m panel.tabs.rally`
imports one tab rather than fourteen, and so that a tab which fails to import is a
missing tab rather than a panel that will not open.

Which tabs a window actually shows is the PROFILE's business
(docs/research/panel-tabs-refactor.md §5):

* an id in the profile that no longer exists in code is skipped, with a log line — a
  profile written by a newer build must not break an older panel;
* a tab in code the profile has never heard of is appended at its ``ORDER``, enabled if
  ``DEFAULT_ENABLED`` — a new tab appears without editing every profile by hand;
* a tab whose import or ``build()`` raises is skipped and reported, and the rest of the
  panel still opens.
"""
from __future__ import annotations

import importlib


class TabSpec:
    """One registry entry. Holds the import path; loads the class on demand."""

    def __init__(self, tab_id: str, module: str, cls_name: str, order: int = 100,
                 default_enabled: bool = True) -> None:
        self.id = tab_id
        self.module = module
        self.cls_name = cls_name
        self.order = order
        self.default_enabled = default_enabled
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
    TabSpec("alliance",  "panel.tabs.alliance",  "AllianceTab",  order=200),
    TabSpec("profile",   "panel.tabs.profile",   "ProfileTab",   order=210),
    TabSpec("inventory", "panel.tabs.inventory", "InventoryTab", order=220),
    TabSpec("heroes",    "panel.tabs.heroes",    "HeroesTab",    order=230),
    TabSpec("accounts",  "panel.tabs.accounts",  "AccountsTab",  order=240),
    TabSpec("stats",     "panel.tabs.stats",     "StatsTab",     order=250),
)

BY_ID = {spec.id: spec for spec in TABS}


def resolve(enabled: "list | None" = None, order: "list | None" = None,
            on_unknown=None) -> list:
    """The specs to build, in the order to build them.

    ``enabled`` / ``order`` come from the profile's ``tabs`` block; ``None`` for either
    means "the defaults". ``on_unknown(tab_id)`` is told about an id in the profile that
    no longer exists in code.
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
        # A tab the profile has never heard of still appears, at its own order.
        chosen += [s.id for s in TABS if s.default_enabled and s.id not in chosen]

    ranked = {tab_id: i for i, tab_id in enumerate(order or ())}
    return sorted((BY_ID[t] for t in chosen),
                  key=lambda s: (ranked.get(s.id, len(ranked) + s.order), s.order))
