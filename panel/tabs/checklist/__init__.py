"""The «Чеклист» tab — the errands of a day, and what is left of them.

Two files, because they are used by different callers:

* :mod:`panel.tabs.checklist.tab` — the tab: the rows, the editor, the phone's screen.
  Needs Tk.
* :mod:`panel.tabs.checklist.model` — the list, the ticks and the day a tick belongs to.
  **No Tk**, so the day boundary can be tested under a python with no display.

THE TAB IS IMPORTED LAZILY, exactly as «Ралли» is: a plain
``from panel.tabs.checklist import model`` must not drag tkinter in behind it. Anything
else read off this package (``ChecklistTab`` — the registry's ``getattr`` included) comes
from :mod:`~panel.tabs.checklist.tab` the moment it is asked for.
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
