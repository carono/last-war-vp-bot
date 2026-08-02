"""What a panel tab may lean on — in the shell, and when launched on its own.

`Panel(tk.Tk)` grew into two things at once: the application window, and the runtime
underneath every tab. That is why a tab cannot be run by itself today — it reaches into
the window for the language, the log, the profile, the daemon and the child processes.

This package is the second of those two things, pulled out. A tab is handed a
:class:`PanelRuntime` and asks it for what it needs; the shell and the standalone
harness assemble the same object, so a tab cannot tell which one it is in.

The migration is deliberately gradual (docs/research/panel-tabs-refactor.md §10): the
panel keeps its familiar `_t` / `_tr` / `_arm` method names as one-line delegations onto
the runtime while the tabs move out one at a time, and they go away in the last wave.

What is here now: the translator, the ticker, the event bus, the capture list, the log
sink, the child factory, the game link, the action runner and the settings binder —
all of wave 0. The schedule follows with the Timers tab.
"""
from __future__ import annotations

# FIRST: the bare-name imports below (lua_client, script_engine) need the repo's
# tools/ and src/ on sys.path, and `python -m panel.tabs.<id>` never runs
# panel/__main__.py, which is where that bootstrap used to live.
from . import paths  # noqa: F401  (imported for its side effect)
from .actions import ACTIONS_DIR, ActionRunner, Outcome, action_titles, list_actions
from .bus import EventBus
from .children import ChildFactory
from .captures import CAPTURE_OPTIONS, SECRET_TASK_CAPTURE
from .daemon import GameLink
from . import game_process
from .host import PanelRuntime, standalone
from .i18n import Translator
from .log import LogBus
from . import reads
from .schedule import Schedule
from .settings import SettingsBinder
from .tick import Ticker

__all__ = ["paths", "reads", "game_process", "ACTIONS_DIR",
           "action_titles", "list_actions", "ActionRunner", "Outcome", "PanelRuntime", "standalone", "ChildFactory", "EventBus", "GameLink", "LogBus",
           "Schedule", "SettingsBinder", "Ticker", "Translator",
           "CAPTURE_OPTIONS", "SECRET_TASK_CAPTURE"]
