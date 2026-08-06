"""The «Secret Tasks» tab — the starred raidable tiles, and the three orders behind them.

Six files, because the parts fail in different ways and are worth reading apart:

* :mod:`~panel.tabs.secret_tasks.tab` — the list, its countdowns and its two actions;
* :mod:`~panel.tabs.secret_tasks.grid` — the table both lists are drawn as: the columns,
  the colours, the sort keys and the per-second countdown, all of them testable without
  a Tk root;
* :mod:`~panel.tabs.secret_tasks.alliance` — the second table (#1244), a mirror of the
  game's own alliance list rather than a working list of its own;
* :mod:`~panel.tabs.secret_tasks.capture` — the passive pcap child that feeds the list;
* :mod:`~panel.tabs.secret_tasks.autoloot` — the standing order that spends the day's
  five robberies, and therefore the delicate one (#1099);
* :mod:`~panel.tabs.secret_tasks.sweep` — the camera walk that keeps the capture fed.

The tab is imported lazily (PEP 562) for the same reason the rally package does it: a
module here should be readable without dragging tkinter in behind it.
"""
from __future__ import annotations

import importlib

_SUBMODULES = frozenset({"tab", "grid", "alliance", "capture", "autoloot", "sweep"})


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
