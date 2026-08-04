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

import threading

from .. import debug_log as dbgmod
from .. import i18n as i18nmod
from .. import profile as profilemod
from . import game_process
from .actions import ActionRunner, Outcome
from .activity import Activity
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
        # WHAT THIS PROFILE IS DOING RIGHT NOW (panel/runtime/activity.py). Handed to
        # the two things that block for whole seconds — bringing the daemon up and
        # playing a scenario — so the strip along the bottom of the window says which
        # of them the panel is inside, instead of the window simply going quiet. A
        # standalone tab has nobody listening and pays a dict insert for it.
        self.activity = Activity(name=self.profiles.active)
        # `token` and `target` are read lazily on purpose: both answer off `self.game`,
        # which is built on the next line. They are what makes this runtime's children
        # and this runtime's scenarios press THIS profile's client rather than whichever
        # one the process environment happens to name (#1206).
        self.children = ChildFactory(
            log=self.log, cwd=REPO,
            python=lambda: self.settings.opt_str("win_python"),
            # How a child's death gets onto the Tk thread. Was `root.after`, and it is
            # the queue now (#1226): a child is read by a thread of its own, so the
            # hand-over was a worker calling Tk — which blocks on the event loop and,
            # during the boot, raised «main thread is not in main loop» and killed the
            # reader before it could untick the checkbox (the paragraph in
            # `panel/childmon.py::_announce_exit` is about exactly that). The delay is
            # accepted and dropped: every caller passes 0, and «soon» is what a queue
            # gives. A runtime built with no root still has no Tk thread to get onto.
            port=self.daemon_port,
            schedule=(lambda _delay, call: self.post(call)) if root is not None else None,
            token=lambda: self.game.token,
            # Where this profile's children are written down, so a run that was killed
            # rather than closed does not leave its monitors sniffing for ever (#1212).
            # A callable, like the port and the lease: it has to follow a profile switch.
            registry=lambda: self.profiles.dir())
        self.game = GameLink(
            port=self.daemon_port,
            python=lambda: self.settings.opt_str("win_python"),
            log=self.log, env=self.children.env, cwd=REPO,
            daemon_script=LUA_DAEMON, on_state=daemon_state,
            debug=self.dbg("daemon"), activity=self.activity,
            # A callable, like the port: it has to follow a profile switch. This is
            # what stops the panel starting a daemon HERE for a client that lives in
            # another Windows session — it would bind the right port and then drive
            # this desktop's game, or nothing (#1218).
            user=lambda: game_process.profile_user(self.settings),
            # …and whose link this is, so every claim it takes is filed under the
            # profile and a refusal names the profile holding the client (#1226).
            name=lambda: self.profiles.active)
        self.actions = ActionRunner(log=self.log, target=self.game_target,
                                    activity=self.activity)
        self._schedule = None           # built on first ask (see the property below)
        self._squads = None             # …and so is the squad reader
        self._heartbeat = False         # only the shell beats (see start_heartbeat)
        self._lock = None               # this profile's instance lock, held open
        self._lock_on = None            # …and which profile it is holding
        # Which tabs this window actually built. Empty until somebody fills it, never
        # None — a tab reaching for another one asks `rt.tabs.get(id)` and gets `None`
        # for "not in this window", in the shell and standalone alike.
        from ..tabs import TabRegistry
        self.tabs = TabRegistry()
        # WHAT THE LAST RUN LEFT BEHIND (#1212). A panel that was killed rather than
        # closed — the task manager, a crash, the machine going down — leaves its
        # monitors running, and they go on spending the day's robberies beside the new
        # ones. Here rather than in the shell so a standalone tab cleans up too, and
        # before anything of this runtime's own is started so the log line reads in
        # order. Only children of a DEAD owner are touched: a panel open beside this one
        # keeps its own (panel/runtime/children.py).
        #
        # ON A THREAD, because this is `PanelRuntime.__init__` and that runs on the TK
        # THREAD, once per open profile. It walks the registry asking psutil whether each
        # owner is alive, which is `Process.status()` and `create_time()` per entry —
        # measured at ~300 ms, and with four profiles opening that is more than a second
        # of window that has not drawn yet (#1226). Nothing waits for the answer: it ends
        # processes the LAST run left behind, and a monitor that lives a second longer has
        # already lived since the previous panel closed.
        threading.Thread(target=self._reap, name="panel-reap", daemon=True).start()

    def _reap(self) -> None:
        """End what the LAST run left behind. On a thread of its own — see the caller."""
        try:
            self.children.reap()
        except Exception:                 # noqa: BLE001 — housekeeping, never the panel
            self.dbg("children").error("reap failed", exc_info=True)

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

    @property
    def squads(self):
        """Where every squad is and how much stamina is left (panel/runtime/squads.py).

        Built on first ask and nothing more: constructing it reads nothing, and the poll
        only runs while a tab is watching it. Here rather than on the «Ралли» tab
        because a squad standing in the base is the precondition of every send — the
        rally, the gather, the attack — and because a tab opened on its own has to be
        able to ask the same question the shell asks (§4).
        """
        if self._squads is None:
            from .squads import SquadReader
            self._squads = SquadReader(self)
        return self._squads

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
                   cancel=None, on_start=None, on_done=None, on_result=None) -> bool:
        """Run one scenario on a worker thread, under the game claim.

        ``False`` when the claim was refused — something else is driving the game — and
        then nothing was started and neither callback runs. ``on_start`` fires on the
        calling thread, ``on_done`` on the TK thread, because the things it undoes (a
        button's state, a row's marker) are widget state.

        ``on_result`` is for the caller that wants what the scenario *found*, not just
        that it finished: it is handed the :class:`~panel.runtime.actions.Outcome`, on
        the TK thread, before ``on_done``. A scenario built out of ``READ_LUA … INTO x``
        leaves its readings in ``outcome.ctx.vars``, which is how a tab shows a value off
        the live game without assembling one line of Lua of its own — the rule in
        `CLAUDE.md` that the panel plays scenarios and does not write them.

        Here rather than on a tab because three callers need exactly this: the Scenarios
        tab's «Запустить», the shell relaunching the client, and the graphics switch
        reading back what it just set. It is the only place the claim, the thread and the
        log line are spelled out together.
        """
        import threading

        if not self.game.claim(tag):
            self.log.say(tag, "busy")
            return False
        if on_start is not None:
            on_start()

        def work() -> None:
            outcome = None
            raised = ""
            try:
                on_event = lambda msg: self.log.put(f"[{tag}] {msg}")   # noqa: E731
                if on_result is None:
                    self.actions.run(name, args, hwnd=0, on_event=on_event,
                                     profile=None, cancel=cancel)
                else:
                    outcome = self.actions.play(name, args, hwnd=0, on_event=on_event,
                                                profile=None, cancel=cancel)
            except Exception as exc:                   # noqa: BLE001 — never the panel
                raised = str(exc)
                self.log.put(f"[{tag}] {name}: error: {exc}")
            finally:
                # RELEASE FIRST, then hand the result over. A callback's whole point is
                # often to start the NEXT scenario off what this one found — the graphics
                # switch reads the picture and then changes it — and a result delivered
                # while this run still holds the claim gets that second scenario refused
                # as "занят", from inside the very run that is holding it.
                self.game.release()
                # A run that RAISED has no Outcome — and the exception is the only
                # account of what went wrong, so it becomes the reason rather than being
                # dropped. Losing the lease to another profile reads as «the game was
                # taken», not as «the scenario gave no reason».
                if on_result is not None:
                    result = outcome if outcome is not None else Outcome(False, raised)
                    self._on_tk(lambda: on_result(result))
                if on_done is not None:
                    self._on_tk(on_done)
                self.game.on_settled()

        threading.Thread(target=work, daemon=True).start()
        return True

    def post(self, call) -> None:
        """Run ``call`` on the Tk thread soon — from any thread, without touching Tk.

        THE ONE HAND-OVER a tab or a worker should use. `root.after(0, …)` from a worker
        thread is not free: it makes two blocking trips into the Tcl interpreter and
        waits for the event loop, so one profile reporting its work sits on the thread
        that draws all the others (panel/runtime/tick.py, #1226). This costs a queue
        insert and cannot raise «main thread is not in main loop».
        """
        self.tick.post(call)

    #: The name this had while there was one profile and one caller. Kept because three
    #: modules and a test spell it, and because "on the Tk thread" is what it means.
    _on_tk = post

    def daemon_port(self) -> int:
        """The daemon this profile drives — a non-default port is another session's."""
        return self.settings.opt_int("daemon_port", low=1, high=65535)

    def game_target(self) -> dict:
        """Which client a scenario of THIS runtime drives, where it lives, under whose
        lease.

        Handed to the interpreter on every run (`Context.game_port` / `game_token` /
        `game_user`). Read fresh each time rather than snapshotted: the port and the
        session follow a profile switch or an edited setting, and the token is only
        there for as long as the claim is.

        The session is the one of the three that a launch can use. The port reaches a
        client through the daemon attached to it, and `START_GAME` runs when there is
        no client yet — so without this the launcher went onto the panel's own desktop
        whatever the profile said, which is a third client nobody asked for (#1218).
        """
        return {"game_port": self.daemon_port(), "game_token": self.game.token,
                "game_user": game_process.profile_user(self.settings)}

    # -- «I am still here» --------------------------------------------------
    def start_heartbeat(self) -> None:
        """Hold this profile, and say once a minute that the window is still answering.

        TWO signals, because one question is really two. The instance LOCK is held open
        for the life of the process, so «is a panel on this profile» is answered by the
        kernel and cannot go stale — it is released by the OS whatever ends the process.
        The BEAT is armed on `tick`, so it proves the thing a lock cannot: that the event
        loop is still turning. A window that has been white and unresponsive for an hour
        still holds its lock and stops beating, which is exactly how the hourly check
        (panel/runtime/autostart.py) tells a wedged panel from a working one.

        The lock follows the profile, because the panel does: switching profiles hands
        this window's claim to the new one and lets the old one go, so an autostart task
        for the profile just left can open a panel on it — which is the point of a task
        per profile.

        Only the SHELL starts this. A standalone tab is not the panel, and a beat from
        one would tell the check that a panel is running when none is.
        """
        from . import autostart as autostartmod

        self._heartbeat = True

        def beat() -> None:
            if self._lock_on != self.profiles.active:
                autostartmod.drop_lock(self._lock)
                self._lock = autostartmod.take_lock(self.profiles)
                self._lock_on = self.profiles.active
                if self._lock is None:
                    # Not refused — only noted. A window a person asked for opens; it is
                    # the UNASKED-FOR one the hourly check must not open, and it reads
                    # this same lock to decide.
                    self.log.say("panel", "log.autostart.second_panel",
                                 profile=self._lock_on)
            autostartmod.beat(self.profiles)
            self.tick.arm("heartbeat", int(autostartmod.BEAT_SEC * 1000), beat)

        beat()

    def stop_heartbeat(self) -> None:
        """The panel is closing on purpose — take the beat and the lock with it.

        A no-op for a window that never started one, which is what keeps a standalone
        tab's `shutdown` from deleting the running panel's heartbeat.
        """
        if not getattr(self, "_heartbeat", False):
            return
        from . import autostart as autostartmod

        self._heartbeat = False
        self.tick.disarm("heartbeat")
        autostartmod.clear(self.profiles)
        autostartmod.drop_lock(self._lock)
        self._lock, self._lock_on = None, None

    # -- teardown -----------------------------------------------------------
    def shutdown(self) -> None:
        self.stop_heartbeat()
        if self._squads is not None:
            self._squads.stop()
        self.tick.disarm_all()
        # EVERY child, not just the ones a tab remembered to stop. A tab's own
        # `shutdown` still runs first and still knows what its checkbox means; this is
        # the floor under it, and the only thing that catches a child whose tab was
        # never built, or whose stop was forgotten (#1212). Before the lease is let go,
        # so nothing that inherited it is still holding the game afterwards.
        stopped = self.children.stop_all()
        if stopped:
            self.log.say("panel", "log.children.stopped", count=stopped)
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
