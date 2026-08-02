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
from .. import i18n as i18nmod
from .. import profile as profilemod
from .actions import ActionRunner
from .bus import EventBus
from .children import ChildFactory
from .daemon import GameLink
from .i18n import Translator
from .log import LogBus
from .paths import LUA_DAEMON, REPO
from .settings import DEFAULTS, SettingsBinder
from .tick import Ticker


class PanelRuntime:
    """Everything a tab may lean on. Built once, per window."""

    def __init__(self, root, profiles=None, defaults: dict | None = None,
                 lang: str | None = None, echo_log: bool = False,
                 daemon_state=None, scope: str | None = None) -> None:
        self.root = root
        self.profiles = profiles if profiles is not None else profilemod.ProfileManager()
        # This runtime's slice of the debug log (panel/debug_log.py). `None` is the
        # shared tree — which is every window there has ever been until a second
        # profile is opened beside the first, and then the second one names a scope so
        # the two profiles' `debug.log`s fill independently (#1206). A SLOT, not a
        # profile name: switching this runtime's profile re-points the same scope at
        # the new profile's file rather than starting a third one.
        self.scope = scope

        # EVERY window starts from the panel's own knobs, whether or not its builder
        # named them: `win_python` is what the child factory below launches with, and a
        # standalone tab whose binder held nothing spawned its captures with an empty
        # path and drew its Settings rows into a KeyError (#1191). A caller may add to
        # them (a tab's `SETTINGS`); nothing has to re-state them.
        self.settings = SettingsBinder(self.profiles, {**DEFAULTS, **(defaults or {})})
        self.settings.load()
        # One Tk variable per knob, BEFORE any tab is built — a row that binds to one
        # has to find it there.
        if root is not None:
            self.settings.create_vars(root)

        # A profile — or a `--lang` on the command line — may name a language whose
        # locale file is not on this machine: somebody's own translation, a panel copied
        # somewhere else, a file moved out of panel/locales. That is English and a line
        # in the log, never a crash and never a menu the language is missing from.
        # `Translator(DEFAULT_LANG)` rather than `set_lang` on purpose: a fallback must
        # not rewrite the remembered choice, so the language comes back by itself the
        # moment the file does.
        saved_lang = lang or self.settings.values.get("language")
        unknown_lang = saved_lang if (saved_lang
                                      and not i18nmod.known(saved_lang)) else None
        # A SCOPED runtime is one of several open profiles, and its language is that
        # profile's business alone: writing the machine-wide fallback there would rename
        # the language of every OTHER profile that has never chosen one (#1206).
        self.i18n = Translator(i18nmod.DEFAULT_LANG if unknown_lang else None,
                               persist=scope is None)
        if saved_lang and not unknown_lang:
            self.i18n.set_lang(saved_lang)

        dbgmod.configure(self.profiles.debug_log(), scope=self.scope)
        self.log = LogBus(translate=self.i18n.t,
                          debug_logger=self.dbg("ui"), echo=echo_log)
        self.log.open_file(self.profiles.panel_log())
        # Said only now: the log is what it is said into, and it needs the translator.
        if unknown_lang:
            self.log.say("panel", "log.lang.unknown",
                         lang=unknown_lang, used=self.i18n.lang)

        self.tick = Ticker(root)
        self.bus = EventBus(root)
        # `token` and `target` are read lazily on purpose: both answer off `self.game`,
        # which is built on the next line. They are what makes this runtime's children
        # and this runtime's scenarios press THIS profile's client rather than whichever
        # one the process environment happens to name (#1206).
        self.children = ChildFactory(
            log=self.log, cwd=REPO,
            python=lambda: self.settings.opt_str("win_python"),
            port=self.daemon_port, schedule=root.after,
            token=lambda: self.game.token)
        self.game = GameLink(
            port=self.daemon_port,
            python=lambda: self.settings.opt_str("win_python"),
            log=self.log, env=self.children.env, cwd=REPO,
            daemon_script=LUA_DAEMON, on_state=daemon_state,
            debug=self.dbg("daemon"))
        self.actions = ActionRunner(log=self.log, target=self.game_target)
        self._schedule = None           # built on first ask (see the property below)
        self._heartbeat = False         # only the shell beats (see start_heartbeat)
        # Which tabs this window actually built. Empty until somebody fills it, never
        # None — a tab reaching for another one asks `rt.tabs.get(id)` and gets `None`
        # for "not in this window", in the shell and standalone alike.
        from ..tabs import TabRegistry
        self.tabs = TabRegistry()

    @property
    def schedule(self):
        """The errands on a clock and the ones the wire sets off — built on first ask.

        Built, not STARTED: constructing it reads the profile's two catalogues and
        nothing else, so a tab that merely wants to draw the rows costs nothing. Only
        `start()` puts a scheduler thread and a listener per trigger behind it, and only
        the shell calls that — a standalone «Ралли» window must not quietly begin
        running the whole account's errands (§4.3).
        """
        if self._schedule is None:
            from .schedule import Schedule
            self._schedule = Schedule(self)
        return self._schedule

    @schedule.setter
    def schedule(self, value) -> None:
        self._schedule = value

    # -- the shorthands every tab uses constantly ---------------------------
    def dbg(self, component: str = "panel"):
        """This runtime's technical logger for one component (panel/debug_log.py).

        Always through here rather than `debug_log.get_logger` directly: the module
        function writes into the SHARED file, which is the right answer for one open
        profile and the wrong one for two.
        """
        return dbgmod.get_logger(component, scope=self.scope)

    def t(self, key: str, **fmt) -> str:
        return self.i18n.t(key, **fmt)

    def tr(self, widget, key: str, option: str = "text", **fmt):
        return self.i18n.tr(widget, key, option, **fmt)

    def say(self, tag: str, key: str, **fmt) -> None:
        self.log.say(tag, key, **fmt)

    def put(self, line: str) -> None:
        self.log.put(line)

    # -- pressing a scenario in the background ------------------------------
    def play_async(self, name: str, args: dict | None = None, *, tag: str = "action",
                   cancel=None, on_start=None, on_done=None) -> bool:
        """Run one scenario on a worker thread, under the game claim.

        ``False`` when the claim was refused — something else is driving the game — and
        then nothing was started and neither callback runs. ``on_start`` fires on the
        calling thread, ``on_done`` on the TK thread, because the things it undoes (a
        button's state, a row's marker) are widget state.

        Here rather than on a tab because two callers need exactly this: the Scenarios
        tab's «Запустить» and the shell relaunching the client. It is the only place
        the claim, the thread and the log line are spelled out together.
        """
        import threading

        if not self.game.claim(tag):
            self.log.say(tag, "busy")
            return False
        if on_start is not None:
            on_start()

        def work() -> None:
            try:
                self.actions.run(name, args, hwnd=0,
                                 on_event=lambda msg: self.log.put(f"[{tag}] {msg}"),
                                 profile=None, cancel=cancel)
            except Exception as exc:                   # noqa: BLE001 — never the panel
                self.log.put(f"[{tag}] {name}: error: {exc}")
            finally:
                self.game.release()
                if on_done is not None:
                    try:
                        self.root.after(0, on_done)
                    except Exception:                  # noqa: BLE001 — the window is gone
                        pass
                self.game.on_settled()

        threading.Thread(target=work, daemon=True).start()
        return True

    def daemon_port(self) -> int:
        """The daemon this profile drives — a non-default port is another session's."""
        return self.settings.opt_int("daemon_port", low=1, high=65535)

    def game_target(self) -> dict:
        """Which client a scenario of THIS runtime drives, and under whose lease.

        Handed to the interpreter on every run (`Context.game_port` / `game_token`).
        Read fresh each time rather than snapshotted: the port follows a profile switch
        or an edited setting, and the token is only there for as long as the claim is.
        """
        return {"game_port": self.daemon_port(), "game_token": self.game.token}

    # -- «I am still here» --------------------------------------------------
    def start_heartbeat(self) -> None:
        """Say once a minute that this panel is alive — from the Tk queue, deliberately.

        The scheduled hourly check (panel/runtime/autostart.py) reads that file to decide whether
        to open the panel. Armed on `tick`, so what it proves is not «the process exists»
        but «the event loop is still turning»: a window that has been white and
        unresponsive for an hour stops writing it, which is exactly the case a plain
        process-list check cannot tell from a working panel.

        Only the SHELL starts it. A standalone tab is not the panel, and a beat from one
        would tell the check that a panel is running when none is.
        """
        from . import autostart as autostartmod

        self._heartbeat = True

        def beat() -> None:
            autostartmod.beat(self.profiles)
            self.tick.arm("heartbeat", int(autostartmod.BEAT_SEC * 1000), beat)

        beat()

    def stop_heartbeat(self) -> None:
        """The panel is closing on purpose — take the file with it.

        A no-op for a window that never started one, which is what keeps a standalone
        tab's `shutdown` from deleting the running panel's heartbeat.
        """
        if not getattr(self, "_heartbeat", False):
            return
        from . import autostart as autostartmod

        self._heartbeat = False
        self.tick.disarm("heartbeat")
        autostartmod.clear(self.profiles)

    # -- teardown -----------------------------------------------------------
    def shutdown(self) -> None:
        self.stop_heartbeat()
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
    # PINNED when a profile was named: opening one tab against another profile is not
    # the same as telling the panel to switch to it, and until this it was — the next
    # `python -m panel` came up on whatever profile the last standalone tab was given.
    profiles = profilemod.ProfileManager(pin=profile or None)
    rt = PanelRuntime(root, profiles=profiles, defaults=defaults, lang=lang,
                      echo_log=True)
    if port:
        rt.daemon_port = lambda: int(port)      # noqa: E731 — one run, not the profile
        rt.game._port = rt.daemon_port
        rt.children._port = rt.daemon_port
        rt.game.rebind()
    return rt
