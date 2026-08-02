"""PanelRuntime — the handle a tab is given, assembled the same way in both modes.

A tab is handed one of these and asks it for what it needs. The SHELL builds one around
its window; :func:`standalone` builds one around a bare root for
``python -m panel.tabs.<id>``. A tab cannot tell which it is in, and that is the whole
point (docs/research/panel-tabs-refactor.md §4).

The only difference between the two is the log: the shell has a widget draining the
sink, a standalone tab has the console it was launched from. Both leave the same record
in the profile's `panel.log` and `debug.log`.
"""
from __future__ import annotations

from .. import debug_log as dbgmod
from .. import profile as profilemod
from .actions import ActionRunner
from .bus import EventBus
from .children import ChildFactory
from .daemon import GameLink
from .i18n import Translator
from .log import LogBus
from .paths import LUA_DAEMON, REPO
from .settings import SettingsBinder
from .tick import Ticker


class PanelRuntime:
    """Everything a tab may lean on. Built once, per window."""

    def __init__(self, root, profiles=None, defaults: dict | None = None,
                 lang: str | None = None, echo_log: bool = False,
                 daemon_state=None) -> None:
        self.root = root
        self.profiles = profiles if profiles is not None else profilemod.ProfileManager()

        self.settings = SettingsBinder(self.profiles, defaults)
        self.settings.load()

        saved_lang = lang or self.settings.values.get("language")
        self.i18n = Translator()
        if saved_lang:
            self.i18n.set_lang(saved_lang)

        dbgmod.configure(self.profiles.debug_log())
        self.log = LogBus(translate=self.i18n.t,
                          debug_logger=dbgmod.get_logger("ui"), echo=echo_log)
        self.log.open_file(self.profiles.panel_log())

        self.tick = Ticker(root)
        self.bus = EventBus(root)
        self.children = ChildFactory(
            log=self.log, cwd=REPO,
            python=lambda: self.settings.opt_str("win_python"),
            port=self.daemon_port, schedule=root.after)
        self.game = GameLink(
            port=self.daemon_port,
            python=lambda: self.settings.opt_str("win_python"),
            log=self.log, env=self.children.env, cwd=REPO,
            daemon_script=LUA_DAEMON, on_state=daemon_state,
            debug=dbgmod.get_logger("daemon"))
        self.actions = ActionRunner(log=self.log)
        self.schedule = None            # brought up only when a tab's NEEDS asks
        # Which tabs this window actually built. Empty until somebody fills it, never
        # None — a tab reaching for another one asks `rt.tabs.get(id)` and gets `None`
        # for "not in this window", in the shell and standalone alike.
        from ..tabs import TabRegistry
        self.tabs = TabRegistry()

    # -- the shorthands every tab uses constantly ---------------------------
    def t(self, key: str, **fmt) -> str:
        return self.i18n.t(key, **fmt)

    def tr(self, widget, key: str, option: str = "text", **fmt):
        return self.i18n.tr(widget, key, option, **fmt)

    def say(self, tag: str, key: str, **fmt) -> None:
        self.log.say(tag, key, **fmt)

    def put(self, line: str) -> None:
        self.log.put(line)

    def daemon_port(self) -> int:
        """The daemon this profile drives — a non-default port is another session's."""
        return self.settings.opt_int("daemon_port", low=1, high=65535)

    # -- teardown -----------------------------------------------------------
    def shutdown(self) -> None:
        self.tick.disarm_all()
        self.game.release()
        self.log.close_file()


def standalone(profile: str | None = None, lang: str | None = None,
               port: int | None = None, defaults: dict | None = None,
               root=None) -> PanelRuntime:
    """A runtime for one tab launched on its own.

    ``port`` overrides the profile's daemon port for this run only and is never written
    back — pointing a tab at the other client's daemon should not edit the profile.
    """
    profiles = profilemod.ProfileManager()
    if profile:
        profiles.set_active(profile)
    rt = PanelRuntime(root, profiles=profiles, defaults=defaults, lang=lang,
                      echo_log=True)
    if port:
        rt.daemon_port = lambda: int(port)      # noqa: E731 — one run, not the profile
        rt.game._port = rt.daemon_port
        rt.children._port = rt.daemon_port
        rt.game.rebind()
    return rt
