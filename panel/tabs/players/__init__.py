"""The «Игроки» tab — the register of everyone this account's laps have seen (#1335).

Two files, because one of them is a decision and the other is a window:

* :mod:`~panel.tabs.players.registry` — the store, the rule that a row leaves only when
  a person asks, and the whole of searching and sorting. No Tk, no game, no panel: it
  runs and is tested on its own;
* :mod:`~panel.tabs.players.tab` — the table, the filters and the phone's copy of them.

Imported lazily (PEP 562), as the other tab packages are: a module here should be
readable without dragging tkinter in behind it.
"""
from __future__ import annotations

import importlib

_SUBMODULES = frozenset({"tab", "registry"})


def __getattr__(name: str):
    """Everything the tab module holds, imported on first use (PEP 562)."""
    if name.startswith("_") or name in _SUBMODULES:
        raise AttributeError(name)
    tab = importlib.import_module(__name__ + ".tab")
    try:
        return getattr(tab, name)
    except AttributeError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}") from None
