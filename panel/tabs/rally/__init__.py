"""The «Ралли» tab — raising one, hearing about one, and the budget for both.

Four files, because the subject has four parts that are used by different people:

* :mod:`panel.tabs.rally.tab` — the tab itself: the create form, the run loop, the
  push monitor with its alert and its join. Needs Tk.
* :mod:`panel.tabs.rally.autorally` — the «Авторалли» page the tab contributes to
  Settings (which squads may go, the drill, the daily caps). Needs Tk.
* :mod:`panel.tabs.rally.limits` — the daily budget's gate. **No Tk**, because the
  schedule asks it before letting the «rally_auto_join» trigger run, in a profile that
  may not show this tab at all.
* ``__main__`` — `python -m panel.tabs.rally`, which opens the tab on its own.

THE TAB IS IMPORTED LAZILY, and that is what the last bullet is worth: a plain
``from panel.tabs.rally import limits`` must not drag tkinter in behind it, or the
budget could only be spent by a window. Anything else read off this package
(``RallyTab``, ``join_squads``, the level range) comes from :mod:`~panel.tabs.rally.tab`
the moment it is asked for — the registry's ``getattr(module, "RallyTab")`` included.
"""
from __future__ import annotations

import importlib

#: The submodules, so a lookup for one of them never re-enters this hook. `from . import
#: tab` falls back to `getattr(package, "tab")` when the import raises, which without
#: this is an infinite recursion instead of the ImportError it should be.
_SUBMODULES = frozenset({"tab", "autorally", "limits"})


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
