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

And on top of all of it, one level up: a :class:`ProfileSession` is one OPEN profile
— a runtime plus its lifecycle — and a :class:`Workspace` is the set of them one
window holds. A panel with one profile open has one session and behaves exactly as it
always has (docs/research/multi-profile-panel.md).
"""
from __future__ import annotations

# FIRST: the bare-name imports below (lua_client, script_engine) need the repo's
# tools/ and src/ on sys.path, and `python -m panel.tabs.<id>` never runs
# panel/__main__.py, which is where that bootstrap used to live.
from . import paths  # noqa: F401  (imported for its side effect)
# `autostart` is deliberately NOT re-exported here. It is the one module in this package
# with a `__main__` of its own — the scheduler runs `-m panel.runtime.autostart` once an
# hour — and a submodule that the package imports on the way in is then loaded TWICE in
# that process: once under its own name, once as `__main__`. Python says so out loud
# ("found in sys.modules … prior to execution … unpredictable behaviour"), and two
# copies of a module holding a heartbeat file is not a thing to be casual about. Reach
# for it as `from .runtime import autostart`, which imports it exactly once.
from .actions import ACTIONS_DIR, ActionRunner, Outcome, action_titles, list_actions
from .activity import Activity, Step
from .bus import EventBus
from . import claims
from .children import ChildFactory
from .captures import CAPTURE_OPTIONS, SECRET_TASK_CAPTURE
from .daemon import GameLink
from . import diag
from . import game_process
from .host import PanelRuntime, standalone
from .i18n import Translator
from .log import LogBus
from . import reads
from .schedule import Schedule
from .session import ProfileSession, SessionScoped
from . import settings
from .settings import DEFAULTS, SettingsBinder
from . import squads
from .squads import Squad, SquadReader, SquadState
from .tick import Ticker, TkPost
from .workspace import Workspace
from . import updates

__all__ = ["paths", "reads", "diag", "game_process", "claims", "ACTIONS_DIR",
           "action_titles", "list_actions", "ActionRunner", "Activity", "Step",
           "Outcome", "PanelRuntime", "standalone", "ChildFactory", "EventBus", "GameLink", "LogBus",
           "DEFAULTS", "Schedule", "settings", "SettingsBinder", "Ticker", "TkPost",
           "Translator",
           "squads", "Squad", "SquadReader", "SquadState",
           "updates", "CAPTURE_OPTIONS", "SECRET_TASK_CAPTURE",
           "ProfileSession", "SessionScoped", "Workspace"]
