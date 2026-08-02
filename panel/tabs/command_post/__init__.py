"""The «Секретный командный пункт» tab — the three raids the in-game panel offers.

Two files: :mod:`~panel.tabs.command_post.tab` (the three pages) and
:mod:`~panel.tabs.command_post.ghost` (the «Операция Призрак» standing order, which the
ghost page switches on and which has to keep running whether or not anybody is looking).

The tab is imported lazily (PEP 562), so the order module can be read without dragging
tkinter in behind it.
"""
from __future__ import annotations

import importlib

_SUBMODULES = frozenset({"tab", "ghost"})


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
