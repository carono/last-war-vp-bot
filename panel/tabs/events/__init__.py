"""The «События» tab — what the game's events are doing, one block per event.

Two files, because they are used by different callers:

* :mod:`panel.tabs.events.tab` — the tab: the blocks, the press, the phone's screen.
  Needs Tk.
* :mod:`panel.tabs.events.model` — the catalogue, the parser and the three states.
  **No Tk**, so a reading can be tested under a python with no display.

THE TAB IS IMPORTED LAZILY, exactly as «Чеклист» is: a plain
``from panel.tabs.events import model`` must not drag tkinter in behind it. Anything else
read off this package (``EventsTab`` — the registry's ``getattr`` included) comes from
:mod:`~panel.tabs.events.tab` the moment it is asked for.
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
