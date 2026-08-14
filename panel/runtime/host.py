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
import time

from .. import debug_log as dbgmod
from .. import i18n as i18nmod
from .. import profile as profilemod
from . import claims
from . import game_process
from .actions import ActionRunner, Outcome
from .activity import Activity
from .panic import Panic as PanicState
from .recovery import Recovery as RecoveryState
from .bus import EventBus
from .children import ChildFactory
from .daemon import GameLink
from .day_reset import DayReset
from .gate import DaemonGate
from .health import ProfileHealth
from .i18n import Translator
from .interrupt import Interrupts
from .log import LogBus
from .log_view import LogSpool
from .paths import LUA_DAEMON, REPO
from .settings import DEFAULTS, SettingsBinder
from .tick import Ticker


#: EVERY scenario that puts the client back. A relaunch may be in flight exactly once,
#: whoever asked for it (:meth:`PanelRuntime._relaunch_lock`) — the watchdog, the
#: recovery verdict, the `restart_game` errand and the buttons all come through
#: `play_async`, which is why the lock can live there and cover all of them.
#:
#: A fifth way of putting the client back is one line here. `recover_from_kick` is in the
#: set although nothing plays it yet (`docs/research/session-kick.md`): the day it is
#: switched on it must already be inside the lock, not added to it afterwards.
RELAUNCHES = frozenset({"launch_game", "restart_game", "recover_from_kick"})

#: How long after a relaunch finishes the next one is still refused. A client told to
#: start is not up yet, and the reading that triggered the first — «no process», «link
#: down» — is still true for a detector looking a second later. Half a minute is longer
#: than a launch takes to show a process and far shorter than any of the holds around it.
RELAUNCH_SETTLE_SEC = 30.0


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
        # …AND WHO DRAINS IT (panel/runtime/log_view.py, #1391). The queue is emptied by
        # the spool and not by a widget: the pane lives on «Разработка» now, which most
        # profiles do not have and none of them has before somebody opens it — and a
        # queue nobody drains grows without bound while a `panel.log` nobody writes is a
        # session with no record of itself. The shell pumps this per profile on its own
        # clock; a pane, when there is one, attaches and draws the history it finds.
        self.log_spool = LogSpool(self.log)
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
        # WHETHER THIS CLIENT HAS GONE DEAF (panel/runtime/recovery.py). Fed by whoever
        # polls the link — the window's status poll — and read by BOTH front-ends, which
        # is why it lives here and not on the window: the phone draws the same run of
        # bad readings, the same restart count and the same cooldown, out of the same
        # object, and a second copy of that bookkeeping is a second answer waiting to
        # disagree with the first.
        self.recovery = RecoveryState()
        # …AND THE ONE LIGHT ON THIS PROFILE'S TAB (panel/runtime/health.py, #1299).
        # Same arrangement as `recovery` and for the same reason: written by whoever
        # polls the link, drawn by BOTH front-ends — the window on the notebook tab, the
        # phone on the profile picker — out of one object. It is born amber: nothing has
        # read this profile yet, and «нечего сказать» may never be painted green.
        self.health = ProfileHealth()
        # …AND WHETHER ANYTHING AUTOMATIC MAY RUN AT ALL (panel/runtime/gate.py, #1393).
        # One question — «is this profile's daemon alive» — asked by the schedule in
        # front of every timer and every trigger, by the watchdog before it puts a client
        # back and by the recovery before it acts. It reads the light above rather than
        # probing for itself, so a tick costs a dict lookup; it is here rather than on
        # the schedule because the schedule is not the only thing that acts by itself,
        # and three detectors with three ideas of «may I» is how «Стоп всё» used to be
        # undone eight seconds after it was pressed.
        self.gate = DaemonGate(self)
        # …AND WHEN THIS PROFILE'S WARZONE STARTS A NEW DAY (panel/runtime/day_reset.py).
        # Everything the game hands out once a day comes back at the server's own 00:00,
        # which is neither this machine's midnight nor the same on every warzone — so the
        # boundary is read from THIS profile's client and kept in THIS profile's
        # directory. A daily errand's next turn is anchored to it (`panel/timers.py`) and
        # «до сброса» on the checklist is counted from it.
        self.day = DayReset(self)
        # THE RELAUNCH LOCK (:meth:`_relaunch_lock`). Which relaunch scenario is running
        # right now, and when the last one finished — the two facts that make «put the
        # client back» a thing exactly one caller can be doing, whoever asks.
        self._relaunching = ""
        self._relaunch_at = 0.0
        self._relaunch_at_lock = threading.Lock()
        # …and whether «Стоп всё» is holding this profile still, since when
        # (panel/runtime/panic.py). Both front-ends put a MARK on it: the one
        # line in the log that used to say it scrolls away, and a profile that
        # is stopped looks exactly like one that is merely idle.
        self.panic = PanicState()
        # WHICH SCENARIOS ARE RUNNING RIGHT NOW, and the press that ends them
        # (panel/runtime/interrupt.py). Here rather than on the window because the runner
        # below has to fill it and both front-ends have to read it: the footer's
        # «Прервать» and the phone's are one register and one press, not two that have to
        # agree. Handed to the runner, which is the one door every scenario goes through —
        # a press, a timer's errand, an auto-order on its own worker.
        self.interrupts = Interrupts()
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
                                    activity=self.activity,
                                    interrupts=self.interrupts)
        self._schedule = None           # built on first ask (see the property below)
        self._squads = None             # …and so is the squad reader
        self._wire = None               # …and the one wire ear (panel/runtime/wire.py)
        self._banners = None            # …and what it heard about the banners out
        self._players = None            # …and the register every source writes into
        self._store = None              # …and this profile's database (#1398)
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
        self._warm()

    def _warm(self) -> None:
        """Do the one-off work a profile owes, HERE rather than on the Tk thread (#1398).

        Bringing `players.json` into the database is a second or two once in the life of
        a profile — 11.5 MB parsed and 17 374 rows written on the largest live one. It
        happens on whichever thread first asks for the register, and doing it here means
        that thread is never the one drawing the window.

        Nothing waits for it and nothing depends on it: a tab that asks first simply does
        the import itself, and one that asks second finds it done.
        """
        try:
            moved = self.players.ensure_imported()
        except Exception:                 # noqa: BLE001 — the register still works
            self.dbg("store").error("importing players.json failed", exc_info=True)
            return
        if moved:
            self.log.say("panel", "log.store.imported", name="players", count=moved)

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

    @property
    def wire(self):
        """This profile's ONE wire ear, shared by everything that wants a push.

        Built on first ask and it spawns nothing until somebody subscribes, so a
        profile with every trigger switched off pays nothing. Each subscription used to
        be a capture process of its own, decoding the same traffic again for one
        command name — the bill was listeners × profiles (panel/runtime/wire.py).
        """
        if self._wire is None:
            from .wire import WireHub
            self._wire = WireHub(self)
        return self._wire

    @property
    def banners(self):
        """What the wire has said about the rallies standing on the map (#1323).

        Plain memory — no game, no thread, no child of its own: the ear above fills it
        as the pushes arrive, and the auto-join reads it for the one thing that exists
        nowhere else, which monster each banner is going for. Empty is a fine answer and
        costs a join nothing; what it cannot be any more is ABSENT, which is what it was
        in a profile whose window does not show the «Ралли» tab — the kind of every
        banner then fell back to `monster` and every per-kind cap the person had set was
        left at zero for good (panel/runtime/rally_wire.py).
        """
        if self._banners is None:
            from .rally_wire import BannerBook
            self._banners = BannerBook(self)
        return self._banners

    @property
    def players(self):
        """THE ONE ENTRANCE to this profile's register of players (#1371).

        Here rather than on the «Игроки» tab because the tab is not the only place the
        panel meets a player: the banner block, the chat, the alliance roster and every
        tile with an owner see one too, and all of them were throwing it away. A feeder
        calls `rt.players.sighted(records, source=…)` and nothing else — five copies of
        «open the file, merge, save» is how two of them end up disagreeing.

        Built on first ask, reads nothing but its own file, and asks the game NOTHING —
        every source is something the panel is already told (`panel/runtime/players.py`).
        """
        if self._players is None:
            from .players import PlayerBook
            # THIS PROFILE'S DATABASE, and the old file so the first run can bring it
            # in — once, keeping the file (#1398, `panel/runtime/store.py`).
            self._players = PlayerBook(self.store, self.profiles.players_json())
        return self._players

    @property
    def store(self):
        """THIS PROFILE'S DATABASE (#1398, panel/runtime/store.py).

        One per profile, in the profile's own directory. Built on first ask and
        **re-checked against the profile on every ask**: the runtime outlives a profile
        switch, and a store that did not follow would go on writing the previous
        account's register — the failure `docs/research/profile-isolation.md` is a list
        of. The check is a string compare; the store is only rebuilt when the path has
        actually moved, and the one being left is closed rather than leaked.
        """
        want = self.profiles.store_db()
        if self._store is not None and self._store.path != want:
            try:
                self._store.close()
            except Exception:                                       # noqa: BLE001
                self.dbg("store").exception("could not close the previous store")
            self._store = None
        if self._store is None:
            from .store import Store
            store = Store(want)
            # A background write has nobody waiting on it, so a job that fails alone
            # would fail in silence. It says so in THIS profile's debug log.
            store._failed = lambda job: self.dbg("store").exception(   # noqa: SLF001
                "a store job failed: %r", job)
            self._store = store
        return self._store

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

    # -- stepping aside for something more urgent (#1288) --------------------
    def yield_hook(self, tag: str = "timer"):
        """A step-aside callable for a BACKGROUND run, or ``None`` when it cannot park.

        Handed to the interpreter as `Context.yield_to`, which calls it between
        statements, between the presses of a repeat and between the polls of a WAIT.
        Those are the moments a scenario is between two thoughts rather than inside
        one, and they are the only ones at which letting the client go is honest.

        WHAT IT DOES, AND WHY IT SAYS IT. A run that steps aside has stopped for a
        reason nobody watching can see, and a run that came back has resumed something
        they had stopped expecting — so both are one line, naming who it was for. #1288
        asks for exactly that: «если что-то прервано или отложено ради приоритетного —
        сказать, что и почему».

        Losing the client on the way back is a FAILURE and is raised: the alternative
        is a scenario going on pressing a client it does not hold, which is the one
        thing the claim exists to prevent. The scheduler turns the raise into a logged
        failure and a retry hold, exactly as it does for a step that would not run.
        """
        def step_aside(ctx=None) -> None:
            who = self.game.yielded_to()
            if who is None:
                return
            self.log.say(tag, "priority.parked", owner=who)
            if not self.game.park(tag):
                raise RuntimeError(self.t("priority.lost", owner=who))
            # THE LEASE IS A NEW ONE. Standing aside let the old one go, and the run's
            # context is carrying both the token it was granted and an evaluator built
            # with it — so without this every call after the first park would be
            # refused as a lost lease, which reads in the log as the game going deaf.
            if ctx is not None:
                ctx.game_token = self.game.token
                ctx.evaluator = None
            self.log.say(tag, "priority.resumed", owner=who)

        return step_aside

    # -- pressing a scenario in the background ------------------------------
    def _relaunch_lock(self, name: str, tag: str) -> bool:
        """May a scenario that puts the client back start? One at a time, whoever asks.

        FOUR THINGS RELAUNCH THIS CLIENT and they do not know about each other: the
        process watchdog (`panel/__main__.py::_watchdog_check`), the recovery verdict
        (`RESTARTS`), the `restart_game` errand on its clock, and a person's button in
        the window or on the phone. Everything that kept them apart until now was
        TIMING — a hold here, a cooldown there — and timing is exactly what fails on the
        day it matters: a kicked account had six kicks in one morning, and each of them
        is a moment when two detectors see the same «down» in the same second.

        The claim below does not cover this. A claim is held for the length of a
        scenario and released when it ends, so «launch_game finished» and «the client is
        up» are different moments: the second detector takes the freed claim and
        launches a client that is already starting. That is the relaunch war, and it is
        won by arithmetic rather than by luck only if there is a lock.

        So: while a relaunch scenario is running, another one is refused; and for
        :data:`RELAUNCH_SETTLE_SEC` after one finishes, another is still refused,
        because a client told to start is not up yet and the reading that started the
        first is still true.

        Refusals are SAID, never silent — a watchdog that quietly did nothing is the
        thing this whole area keeps relearning (#1259, #1296). Anything that is not a
        relaunch passes straight through and pays a dict lookup.
        """
        if name not in RELAUNCHES:
            return True
        now = time.monotonic()
        with self._relaunch_at_lock:
            busy = self._relaunching
            if not busy:
                since = now - self._relaunch_at
                if self._relaunch_at and since < RELAUNCH_SETTLE_SEC:
                    self.log.say(tag, "log.game.relaunch_settling",
                                 name=name, secs=int(RELAUNCH_SETTLE_SEC - since))
                    self.dbg("panel").info(
                        "relaunch %s refused: %s finished %.1fs ago", name, "one",
                        since)
                    return False
                self._relaunching = name
                return True
        # Somebody is already putting the client back. Say WHICH, because «занято» with
        # no owner is how a person ends up restarting the panel to find out.
        self.log.say(tag, "log.game.relaunch_busy", name=name, running=busy)
        self.dbg("panel").info("relaunch %s refused: %s is already running", name, busy)
        return False

    def _relaunch_done(self, name: str, *, started: bool) -> None:
        """Give the relaunch lock back.

        Called from the run's `finally` when the scenario really ran, and from every
        EARLY exit of :meth:`play_async` when it did not — a claim refused, an exception
        before the thread starts. A lock taken and not given back is worse than no lock:
        it would refuse every relaunch from then on, and the client would stay down for
        good the first time something else happened to hold the game. `started` decides
        whether the settle applies: a scenario that never ran left no client starting to
        wait for.
        """
        if name not in RELAUNCHES:
            return
        with self._relaunch_at_lock:
            if self._relaunching == name:
                self._relaunching = ""
            if started:
                self._relaunch_at = time.monotonic()

    def play_async(self, name: str, args: dict | None = None, *, tag: str = "action",
                   cancel=None, on_start=None, on_done=None, on_result=None,
                   priority: int = claims.HUMAN) -> bool:
        """Run one scenario on a worker thread, under the game claim.

        ``False`` when the claim was refused — something else is driving the game — and
        then nothing was started and neither callback runs. ``on_start`` fires on the
        calling thread, ``on_done`` on the TK thread, because the things it undoes (a
        button's state, a row's marker) are widget state.

        ``priority`` is :data:`claims.HUMAN` by default because every caller of this is
        a press: a button in the window, a hotkey, a screen on the phone, the shell
        putting the client back. A press that finds a BACKGROUND errand on the client
        no longer gives up — it hangs a demand on the door and the WORKER waits for the
        errand to park (:meth:`~panel.runtime.daemon.GameLink.claim_soon`). The Tk
        thread never waits: it learns only that the run has been accepted, which is
        what «нажал — действие» has to mean from the window's side (#1288).

        NOT ONE BYTE OF I/O HAPPENS ON THE CALLING THREAD (#1331). The claim is taken in
        two halves — :meth:`~panel.runtime.daemon.GameLink.reserve` here, which is two
        dictionaries under two locks, and the daemon's lease on the worker below, which
        is a round trip to another process and was measured at 6–28 s against a busy
        daemon. It used to be one call on this thread, and since a press from the phone
        is answered by handing this to the Tk thread and waiting a second and a half for
        it, the phone was told the press was «unknown» while the scenario it started ran
        perfectly well. A lease refused therefore arrives the way a refused
        :meth:`claim_soon` already did: «занято» in the log and a failed
        :class:`~panel.runtime.actions.Outcome` to ``on_result``, not a ``False`` here.

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

        AND IT IS WHERE THE RELAUNCH LOCK LIVES, for the same reason: it is the one door
        every caller comes through. Four different things put a client back — the process
        watchdog, the recovery verdict, the `restart_game` errand and a person's button —
        and the claim below does NOT stop two of them going at once: a relaunch releases
        the claim when its scenario ends, so a second detector a second later is a second
        launch. See :meth:`_relaunch_lock`.
        """
        import threading

        if not self._relaunch_lock(name, tag):
            return False

        held = self.game.reserve(tag, priority)
        if not held and not self.game.outranks(priority):
            # Nothing to be done: whoever has the client is at least as urgent as this
            # press, and asking them to step aside for an equal would only shuffle the
            # order of two things that both have to happen.
            self.log.say(tag, "busy")
            # …and the relaunch lock goes straight back: nothing was started, so nothing
            # is putting the client back and the next caller must not be refused.
            self._relaunch_done(name, started=False)
            return False
        if not held:
            self.log.say(tag, "priority.ahead",
                         owner=self.game.claimed_by() or "?", name=name)
        if on_start is not None:
            on_start()

        def work() -> None:
            outcome = None
            raised = ""
            # The rest of the claim, HERE rather than on the thread that pressed: the
            # lease is a round trip and this thread is the one that may afford to wait
            # for it (#1331). `reserve` already took the two local locks, so this only
            # asks the daemon; a run that did not reserve asks for the lot and waits for
            # whoever is holding it to park.
            got = self.game.lease(tag) if held else self.game.claim_soon(tag, priority)
            if not got:
                # Either the run holding the client never reached a moment it could park
                # at — it is inside a call into the game — or the daemon's lease belongs
                # to somebody else. Refusing is what the press did before this existed,
                # and it is still the honest answer.
                self.log.say(tag, "busy")
                # Nothing was played, so the lock is given back WITHOUT a settle — there
                # is no client starting up to wait for.
                self._relaunch_done(name, started=False)
                if on_result is not None:
                    self._on_tk(lambda: on_result(Outcome(False, self.t("busy"))))
                if on_done is not None:
                    self._on_tk(on_done)
                return
            try:
                on_event = lambda msg: self.log.put(f"[{tag}] {msg}")   # noqa: E731
                if on_result is None:
                    self.actions.run(name, args, hwnd=0, on_event=on_event,
                                     profile=None, cancel=cancel, tag=tag)
                else:
                    outcome = self.actions.play(name, args, hwnd=0, on_event=on_event,
                                                profile=None, cancel=cancel, tag=tag)
            except Exception as exc:                   # noqa: BLE001 — never the panel
                raised = str(exc)
                self.log.put(f"[{tag}] {name}: error: {exc}")
            finally:
                # The lock outlives the run by a settle: a client that has just been
                # told to start is not up yet, and a detector looking a second later
                # sees the same «down» that started this one.
                self._relaunch_done(name, started=True)
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

        # NAMED, and named with the PROFILE (#1392). A thread list is the last resort of
        # every jam diagnosis, and `Thread-14` in a window holding four accounts says
        # neither what it is doing nor whose it is — which is exactly the confusion
        # profile isolation exists to prevent. Trimmed, because a thread name is carried
        # by the OS on some platforms.
        threading.Thread(target=work, daemon=True,
                         name=f"lw:{self.profiles.active}:{tag}:{name}"[:60]).start()
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
        if self._wire is not None:
            self._wire.stop()
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
        # LAST, and after the children: whatever they were feeding has had its chance to
        # be queued, and `close()` waits for the writer to run what is still in hand.
        # A store nobody ever asked for was never opened, and closing it is not a reason
        # to open one.
        if self._store is not None:
            try:
                self._store.close()
            except Exception:                                       # noqa: BLE001
                self.dbg("store").exception("could not close the store")
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
