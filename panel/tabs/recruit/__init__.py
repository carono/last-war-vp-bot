"""The «Найм» tab — the two recruit banners, heroes and survivors.

Two files, because they are used by different callers:

* :mod:`panel.tabs.recruit.tab` — the tab: the cards, the six presses, the phone's
  screen. Needs Tk.
* :mod:`panel.tabs.recruit.model` — the banners and the parser. **No Tk**, so a reading
  can be tested under a python with no display.

THE TAB IS IMPORTED LAZILY, exactly as «События» is: a plain
``from panel.tabs.recruit import model`` must not drag tkinter in behind it.
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
