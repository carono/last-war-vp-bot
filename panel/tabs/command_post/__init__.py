"""The «Секретный командный пункт» tab — the three raids the in-game panel offers.

One file: :mod:`~panel.tabs.command_post.tab` (the three pages). The «Операция Призрак»
STANDING ORDER used to be a second one here and is
:mod:`panel.tabs.secret_tasks.ghost_order` since #2010 — an order belongs on the page
holding the list it spends, and this tab is dev-only, so a profile with it switched off
had no order at all and no way to reach its switch from either front-end.

The tab is imported lazily (PEP 562), so this package can be read without dragging
tkinter in behind it.
"""
from __future__ import annotations

import importlib

_SUBMODULES = frozenset({"tab"})


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
