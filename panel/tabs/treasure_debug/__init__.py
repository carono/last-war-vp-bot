"""The «Сокровища» debug page — every treasure message the game sees, as it sees it.

Two files, because they are read by different callers:

* :mod:`panel.tabs.treasure_debug.tab` — the page: the two switches, the feed, the
  filter, the saved fragment, the phone's copy. Needs Tk.
* :mod:`panel.tabs.treasure_debug.model` — what a drained message MEANS and the ring
  that keeps it. **No Tk**, so the parsing can be tested under a python with no display.

THE TAB IS IMPORTED LAZILY, as «События» and «Чеклист» are: a plain
``from panel.tabs.treasure_debug import model`` must not drag tkinter in behind it.
Anything else read off this package (``TreasureDebugTab`` — the registry's ``getattr``
included) comes from :mod:`~panel.tabs.treasure_debug.tab` the moment it is asked for.
"""
from __future__ import annotations

import importlib

#: The submodules, so a lookup for one of them never re-enters this hook.
_SUBMODULES = frozenset({"tab", "model"})


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
