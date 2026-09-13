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
from .progress import Progress
from .power import Power
from .recovery import Recovery as RecoveryState
from .header import StatusHeader
from .resource_book import ResourceBook
from .resources import BaseResources
from .errand_reads import DailyReads
from .bus import EventBus
from .children import ChildFactory
from .link import GameLink
from .day_reset import DayReset
from .gate import RELAUNCH_ACTIONS, LinkGate
from .health import ProfileHealth
from .status import StatusPoll
from .i18n import Translator
from .intake import Intake as IntakeLedger
from .interrupt import Interrupts
from .log import LogBus
# The SPOOL, not the pane: this module is imported by a panel that may have no Tk
# at all (`panel/headless.py`), and `log_view.py` draws (#1976, P3).
from .log_spool import LogSpool
from .paths import REPO
from .settings import DEFAULTS, SettingsBinder
from .tick import Ticker, ThreadTicker
from . import updates as updatesmod


#: EVERY scenario that puts the client back. A relaunch may be in flight exactly once,
#: whoever asked for it (:meth:`PanelRuntime._relaunch_lock`) — the watchdog, the
#: recovery verdict, the `restart_game` errand and the buttons all come through
#: `play_async`, which is why the lock can live there and cover all of them.
#:
#: A fifth way of putting the client back is one line here. `recover_from_kick` is in the
#: set although nothing plays it yet (`docs/research/session-kick.md`): the day it is
#: switched on it must already be inside the lock, not added to it afterwards.
#: ONE list, kept in `panel/runtime/gate.py`, because the relaunch lock and the
#: gate's exemption for these must never disagree about what a relaunch is (#1910).
RELAUNCHES = RELAUNCH_ACTIONS

#: How long after a relaunch finishes the next one is still refused. A client told to
#: start is not up yet, and the reading that triggered the first — «no process», «link
#: down» — is still true for a detector looking a second later. Half a minute is longer
#: than a launch takes to show a process and far shorter than any of the holds around it.
RELAUNCH_SETTLE_SEC = 30.0


#: How long a run whose lease was taken by another errand waits for it back
#: before giving up (#1702). Long enough for any ordinary timer — they are
#: seconds — and short enough that a client which is genuinely somebody
#: else's does not hold a hunt in front of it.
LEASE_WAIT_SEC = 90.0
#: …and how long a DETACHED one waits (#2390). A background chain is the one
#: kind of run that is never in a hurry and always has somewhere to come back
#: to: its queue, its anchor and its march live in the game VM, so losing the
#: client is a PAUSE for it and not a death. Ninety seconds was written for a
#: press somebody is standing in front of; measured on a live panel, the golden
#: hunt was ended nine times in an hour by ordinary errands — treasures, banners,
#: alliance help — none of which lasted a minute, and it left the squad in the
#: field each time. Fifteen minutes is longer than any errand this panel has and
#: still short enough to give up on a client that is genuinely gone.
LEASE_WAIT_DETACHED_SEC = 900.0
LEASE_POLL_SEC = 2.0


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
        # WHICH CODE THIS PROCESS IS RUNNING, stamped now and never again
        # (`panel/runtime/updates.py::boot`). A runtime is made while the panel comes up,
        # in every front-end and in a standalone tab alike, so this is the earliest moment
        # every one of them shares — and early is the whole point: the stamp must name the
        # commit the process STARTED on, not one that landed hours into its life. The
        # version string cannot say that, and #1993 was reported delivered on it (#1994).
        updatesmod.boot()

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

        # The language is a PANEL setting, not a profile's (#1515) — one answer, read
        # off `profiles/settings.json` and applied to every open profile alike. `lang`
        # is only ever a `--lang` on the command line, overriding it for this one run.
        # A saved or requested language whose locale file is not on this machine —
        # somebody's own translation, a panel copied somewhere else, a file moved out
        # of panel/locales — is English and a line in the log, never a crash and never
        # a menu the language is missing from.
        saved_lang = lang or i18nmod.load_pref()
        unknown_lang = saved_lang if not i18nmod.known(saved_lang) else None
        self.i18n = Translator(i18nmod.DEFAULT_LANG if unknown_lang else saved_lang)

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

        # THE CLOCK, and which of the two it is (#1976, P3). With a window every
        # repeating callback rides Tk's `after` queue, because everything they touch is a
        # widget; with none, `ThreadTicker` runs the same chains on one thread of its own
        # and keeps the two guarantees the panel leans on — one thread, FIFO hand-overs.
        # A runtime with no root used to get a `Ticker` that armed NOTHING, which is a
        # schedule, a capture sweep and a status poll that never fire.
        self.tick = Ticker(root) if root is not None else ThreadTicker()
        # …and the bus hands its facts over the same way, so a listener runs where a
        # listener has always run: on the one thread, whoever published.
        self.bus = EventBus(root, post=(None if root is not None else self.tick.post),
                            arm=self.tick.arm)
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
        # …AND WHERE THE PRESS IN FLIGHT HAS GOT TO (panel/runtime/progress.py, #2742).
        # A restart is the longest thing a person ever asks the panel for — half a
        # minute of nothing on screen — and until this the only answer to «идёт ли оно
        # ещё» was a log line written before it started. Fed by the SCENARIO's own `STEP`
        # lines, so the phases are the ability's and not a second copy of them kept in
        # the panel; drawn by both front-ends out of this one object, for the same reason
        # `recovery` lives here.
        self.progress = Progress()
        # …AND THE ONE LIGHT ON THIS PROFILE'S TAB (panel/runtime/health.py, #1299).
        # Same arrangement as `recovery` and for the same reason: written by whoever
        # polls the link, drawn by BOTH front-ends — the window on the notebook tab, the
        # phone on the profile picker — out of one object. It is born amber: nothing has
        # read this profile yet, and «нечего сказать» may never be painted green.
        self.health = ProfileHealth()
        # …AND WHAT EACH RECEIVER WAS GIVEN AND WHAT BECAME OF IT
        # (panel/runtime/intake.py, #1523). The counters behind «события проглатываются»:
        # a receiver that drops what it is handed and a map that had nothing on it look
        # identical from outside, so every receiver records seen / kept / dropped / lost
        # and «Занятость» draws the lot. `lost` is the one that must stay at zero — an
        # accepted event is processed or queued, never discarded.
        self.intake = IntakeLedger()
        # …AND WHETHER ANYTHING AUTOMATIC MAY RUN AT ALL (panel/runtime/gate.py, #1393).
        # One question — «is this profile's daemon alive» — asked by the schedule in
        # front of every timer and every trigger, by the watchdog before it puts a client
        # back and by the recovery before it acts. It reads the light above rather than
        # probing for itself, so a tick costs a dict lookup; it is here rather than on
        # the schedule because the schedule is not the only thing that acts by itself,
        # and three detectors with three ideas of «may I» is how «Стоп всё» used to be
        # undone eight seconds after it was pressed.
        self.gate = LinkGate(self)
        # …AND WHO TAKES THE READINGS THE TWO ABOVE ARE MADE OF
        # (panel/runtime/status.py, #1984). It used to be the Tk shell's status poll, and
        # a panel with no window therefore took no readings at all: `health` stayed at
        # its born-amber `unread()` for as long as the process lived, the gate fell back
        # to its own reading, and the recovery — the crash restart, the kick's wait, the
        # maintenance knock — was never fed. It is the profile's now, so both panels run
        # it and only one of them draws.
        self.status = StatusPoll(self)
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
        # …and WHETHER THIS PROFILE WORKS AT ALL — the checkbox on «Главная»
        # (panel/runtime/power.py, #1882). A setting rather than a mark in memory: a
        # profile somebody switched off stays off across a restart of the panel, and
        # both front-ends draw the same flag, since when. It reads this profile's own
        # settings binder, so one account being off says nothing about the other.
        self.power = Power(self.settings)
        # …and WHAT THE BASE IS HOLDING RIGHT NOW (panel/runtime/resources.py, #1990).
        # The stock along the top of the game's own screen, drawn on the phone's front
        # page and refreshed by itself while somebody is looking. Here rather than on a
        # tab because the front page is not a tab, and because a reading that costs a
        # fifth of a second of the game link must be taken once per profile and shared —
        # never once per page that happens to be open.
        self.resources = BaseResources(self)
        # …and the ONE reading the errands page is allowed to take (#2019): the
        # truck's bubble and the dozen answers that ride in the same chunk, at
        # most once a minute and only while somebody is looking at the page. Per
        # profile for the same reason as the stock above — it reads THIS
        # account's client — and it starts nothing until a page asks.
        self.daily_reads = DailyReads(self)
        # …and THE DAY'S TALLY OF WHAT CAME IN (panel/runtime/resource_book.py, #2743):
        # everything that raised a balance, and — kept apart — what the base's own
        # buildings paid, which is what the card of «Сбор ресурсов» draws. Here rather
        # than on «Статистика» because that tab is `IN_DEVELOPMENT`: its trigger is on
        # in every live profile and its handler was bound to nothing.
        self.resource_book = ResourceBook(self)
        # …and WHO IS PLAYING AND WHERE THEY ARE STANDING (panel/runtime/header.py,
        # #2016) — the strip along the top of every screen on the phone: the character's
        # name and level, the warzone, the scene and the window on top of it. Here for
        # the same reason the stock is: it is not a tab's reading, it costs a fifth of a
        # second of the exclusive game link, and it must be taken once per profile and
        # shared rather than once per page that happens to be open.
        self.header = StatusHeader(self)
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
            log=self.log, cwd=REPO, on_state=daemon_state,
            debug=self.dbg("link"), activity=self.activity,
            # A callable, like the port: it has to follow a profile switch. This is
            # what decides whether the panel holds this client ITSELF or keeps a small
            # process beside it in another Windows session — a hijack finds its client
            # in the session it runs in, so a foreign one cannot be driven from here
            # (#1218, #1911).
            user=lambda: game_process.profile_user(self.settings),
            # …and whose link this is, so every claim it takes is filed under the
            # profile and a refusal names the profile holding the client (#1226).
            name=lambda: self.profiles.active)
        # A JUMP IS THE ONE MOVE THE PANEL ITSELF MAKES, so it is the one that can TELL
        # the header its reading is out of date (#2593). An event, not a clock: the strip
        # says which warzone the client is looking at, and it used to keep saying the old
        # one until something else happened to re-read it.
        self.game.on_moved = self.header.confirm_server
        # A server can also change outside this button: by hand in the client, during
        # a map walk, or through another mechanic.  The passive map capture publishes
        # the server only after incoming blocks confirm it.  Listen to that fact; do
        # not add another game poll.  The direct callback above remains separate so a
        # panel-made jump can update the header synchronously before its button unlocks.
        self.bus.subscribe("game.server", self.header.confirm_server)
        # The first header look often collides with the boot errands. Their RELEASE is
        # the event that retries it at the first real gap; waiting for another lucky
        # `/api/state` request left a green panel saying «game not read yet» (#2593).
        self.game.add_settled(self.header.on_settled)
        self.actions = ActionRunner(log=self.log, target=self.game_target,
                                    activity=self.activity,
                                    interrupts=self.interrupts,
                                    # …and how a run gets its lease back when the daemon
                                    # restarts underneath it (#1411). On the RUNNER
                                    # rather than on the callers, because it has to reach
                                    # every context there is: a press, a timer's errand,
                                    # an auto-order on its own worker.
                                    regain=self.regain_hook(),
                                    # …and WHOSE written-down answers its scenarios may
                                    # read (#1479). Both are properties that follow a
                                    # profile switch, so this is a callable like the
                                    # target above and never a snapshot.
                                    books=lambda: {"store": self.store,
                                                   "days": self.secret_days},
                                    # …and WHETHER ANYTHING MAY RUN AT ALL (#1910). The
                                    # gate was asked by the schedule, the watchdog and
                                    # the recovery, and by nothing else — so a tab's
                                    # poll, a wire handler joining a rally off the
                                    # capture's own reader and an auto-order re-armed on
                                    # the panel's clock all pressed into a client that
                                    # was not there, with a switched-off profile saying
                                    # so in the log and playing scenarios anyway. Asked
                                    # at the one door every scenario goes through, so
                                    # there is no fourth path to find next time.
                                    gate=lambda name, human: self.gate.blocks(
                                        name, human=human),
                                    # …and WHERE A RUN SAYS IT HAS GOT TO (#2742). Here
                                    # rather than on the callers for the reason every
                                    # other hook on this call is here: this is the one
                                    # door every scenario goes through, so a `STEP` is
                                    # heard whether the press came from the window, the
                                    # phone, the watchdog or a timer.
                                    progress=self.progress)
        self._schedule = None           # built on first ask (see the property below)
        self._chat_out = None       # …and the chat's own outgoing lane (#2594)
        self._squads = None             # …and so is the squad reader
        self._wire = None               # …and the one wire ear (panel/runtime/wire.py)
        self._banners = None            # …and what it heard about the banners out
        self._fireworks = None          # …and about the fireworks going off (#1677)
        self._rewards = None            # …and the reward popups it shut (#2027)
        self._market = None             # …and the Glittering Market's own ear (#2636)
        self._doomsday = None           # …and «Судный день»'s own ear (#2842)
        self._shops = None              # …and the shelves of every shop (#2666)
        self._invasion = None           # …and «Вторжение зомби»'s (#2647)
        self._arena = None              # …and the arena building's (#2688)
        self._players = None            # …and the register every source writes into
        self._secret_days = None        # …and the book of star-secret-task days (#1467)
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
        # THE REWARD BOOK STARTS LISTENING HERE, and it has to be here rather than on
        # first ask (#2027): the drains arrive as log lines while a recipe runs, so a
        # book nobody had built yet would have missed exactly the rows it exists for.
        # Building it costs a tap on the log bus — a substring test per line — and no
        # thread, no clock and no question of the game.
        try:
            self.rewards                                   # noqa: B018 — built to listen
        except Exception:                 # noqa: BLE001 — the panel still works
            self.dbg("rewards").error("could not start the reward book", exc_info=True)
        # …AND THE MARKET'S EAR, for the same reason (#2636): «Сверкающий рынок» has no
        # page of its own, so there is no tab whose opening could take the first reading.
        # It listens for the client entering the game and for the event's own score push,
        # and nothing here ticks (panel/runtime/market_live.py).
        try:
            self.market.start()
        except Exception:                 # noqa: BLE001 — the panel still works
            self.dbg("market").error("could not start the market watch", exc_info=True)
        # …AND «СУДНЫЙ ДЕНЬ»'s EAR (#2842), for the same reason again: the event runs on
        # a Sunday and its gifts appear while it runs, so the one moment a reading goes
        # out of date by itself is the event's own push. One reading when the client gets
        # into the game, one per push, and no clock (panel/runtime/doomsday_live.py).
        try:
            self.doomsday.start()
        except Exception:                 # noqa: BLE001 — the panel still works
            self.dbg("doomsday").error("could not start the doomsday watch",
                                       exc_info=True)
        # …AND THE SHOPS' EAR (#2666). «Магазин» has a page, but the AUTOBUY errand
        # spends the same reading and must work in a profile whose page is switched off
        # — so the ear is the profile's, not the tab's. One reading when the client gets
        # into the game, one when a balance moved, one after a purchase of ours, and no
        # clock anywhere (panel/runtime/shops_live.py).
        try:
            self.shops.start()
        except Exception:                 # noqa: BLE001 — the panel still works
            self.dbg("shops").error("could not start the shop watch", exc_info=True)
        # …AND THE ARENA'S (#2688). The building has no page either, and the person
        # asked its card to say WHICH arena is running and how the account stands in it.
        # One reading when the client gets into the game, then one alarm at the moment
        # the state is known to move — the event's own end, or the day's reset — because
        # the arena has no push at all (panel/runtime/arena_live.py).
        try:
            self.arena.start()
        except Exception:                 # noqa: BLE001 — the panel still works
            self.dbg("arena").error("could not start the arena watch", exc_info=True)
        # …AND THE INVASION'S, for the same reason again (#2647). «Вторжение зомби» is
        # what the golden zombies belong to, and a hunt started outside its window walks
        # the world scene, a squad refill, the day's free energy and a lap of the map to
        # find an empty list. The ear holds the last reading; the recipe holds the gate.
        try:
            self.invasion.start()
        except Exception:                 # noqa: BLE001 — the panel still works
            self.dbg("invasion").error("could not start the invasion watch",
                                       exc_info=True)
        try:
            moved = self.players.ensure_imported()
        except Exception:                 # noqa: BLE001 — the register still works
            self.dbg("store").error("importing players.json failed", exc_info=True)
            return
        if moved:
            self.log.say("panel", "log.store.imported", name="players", count=moved)

    @property
    def chat_out(self):
        """The chat's outgoing lane — a queue and a thread of its own (#2594).

        Built on first ask, like the schedule, and for the same reason: a panel where
        nobody has typed anything owns no thread for it. What it buys is the promise the
        person asked for in so many words — a message that could not go this second waits
        its turn instead of vanishing with the text that was typed
        (`panel/runtime/chat_outbox.py`).
        """
        if self._chat_out is None:
            from .chat_outbox import ChatOutbox
            self._chat_out = ChatOutbox(self)
        return self._chat_out

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
            # …and the one errand whose day-book has no tab to wire it (#2588): the
            # alliance gifts. Registering a report hook costs nothing until a run of
            # that errand finishes, and it is what lets the card say «собрано сегодня»
            # about GIFTS rather than about runs.
            from . import gift_book
            gift_book.wire(self)
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
    def fireworks(self):
        """What the wire has said about the fireworks over the map (#1677).

        Plain memory and one row in this profile's database — no game, no thread, no
        child of its own: the ear above fills it as the gift pushes arrive, because that
        push is the only announcement a firework ever gets. On the runtime rather than on
        a tab for the reason `banners` is: a receiver that lives on a page is absent in
        every profile that does not draw the page (panel/runtime/firework_wire.py).
        """
        if self._fireworks is None:
            from .firework_wire import FireworkBook
            self._fireworks = FireworkBook(self)
        return self._fireworks

    @property
    def market(self):
        """This profile's ear for «Сверкающий рынок» (#2636).

        On the runtime rather than on a page because the event HAS no page: its two
        cards live on «Таймеры», which draws rows and never reads the game. One reading
        when the client gets into the game, one more on the event's own push, and no
        clock anywhere (panel/runtime/market_live.py).
        """
        if self._market is None:
            from .market_live import MarketWatch
            self._market = MarketWatch(self)
        return self._market

    @property
    def doomsday(self):
        """This profile's ear for «Судный день» (#2842).

        On the runtime rather than on a page for the reason the market's is: the event
        is read by a card the phone draws and by the errand that collects its gifts, and
        both must work in a profile whose «События» page is switched off. One reading
        when the client gets into the game, one on the event's own quest push, and no
        clock anywhere (panel/runtime/doomsday_live.py).
        """
        if self._doomsday is None:
            from .doomsday_live import DoomsdayWatch
            self._doomsday = DoomsdayWatch(self)
        return self._doomsday

    @property
    def shops(self):
        """This profile's ear for the shelves of every shop the account has (#2666).

        On the runtime and not on «Магазин» for the reason the market's is on it: the
        SCHEDULE asks it — «Автопокупка» spends the same reading — and a profile that
        does not draw the page still has that errand. One reading when the client gets
        into the game, one when a balance push says something moved, one after a
        purchase of ours, and no clock anywhere (panel/runtime/shops_live.py).
        """
        if self._shops is None:
            from .shops_live import ShopWatch
            self._shops = ShopWatch(self)
        return self._shops

    @property
    def arena(self):
        """This profile's ear for the arena building (#2688).

        On the runtime rather than on a page because the arena HAS no page: its card
        lives on «Таймеры», which draws rows and never reads the game. One reading when
        the client gets into the game, then one alarm at the event's own end or the day's
        reset — the arena announces nothing, so those two known moments are all there is
        (panel/runtime/arena_live.py).
        """
        if self._arena is None:
            from .arena_live import ArenaWatch
            self._arena = ArenaWatch(self)
        return self._arena

    @property
    def invasion(self):
        """This profile's ear for «Вторжение зомби» (#2647).

        On the runtime rather than on «События» for the reason the market's is: the
        SCHEDULE asks it, and a profile that does not draw that tab still has the golden
        hunt as an errand. One reading when the client gets into the game, one more when
        the invasion's own record arrives, one per hunt run, and no clock anywhere
        (panel/runtime/invasion_live.py).
        """
        if self._invasion is None:
            from .invasion_live import InvasionWatch
            self._invasion = InvasionWatch(self)
        return self._invasion

    @property
    def rewards(self):
        """The book of reward popups this client raised (#2027).

        On the runtime rather than on a page for the same reason `fireworks` is: the ear
        is in the CLIENT and its drains arrive in the log whoever started the recipe, so
        a book that lived on a tab would be absent in every profile that does not draw
        that tab — and the rows would be lost rather than merely unseen.

        It starts listening the moment it is built, and building it is what
        :meth:`start_heartbeat` does at boot: nothing here polls, the tap is a substring
        test on lines the panel was writing anyway.
        """
        if self._rewards is None:
            from .rewards import RewardBook
            book = RewardBook(self.log, store=lambda: self.store,
                              activity=self.activity, say=self.say)
            book.listen()
            self._rewards = book
        return self._rewards

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
    def secret_days(self):
        """THIS PROFILE'S BOOK of star-secret-task days (#1467, `secret_day.py`).

        What a warzone did on a day, written down as it was seen, and the cycle derived
        from it. Built on first ask and rebuilt when the profile's database moves, for
        the same reason `players` is: a book that did not follow a profile switch would
        answer about the account it was opened under.
        """
        store = self.store
        if self._secret_days is not None and self._secret_days.store is not store:
            self._secret_days = None
        if self._secret_days is None:
            from .secret_day import SecretDayBook
            # THE DAY BOUNDARY IS ASKED, NOT ASSUMED: this profile already keeps the
            # client's own `GetTomorrowZero` across restarts (`day_reset.py`), and a book
            # that started at UTC midnight would age every warzone opened in the small
            # hours by a day — which is the whole basis of the star-day cycle (#1467).
            self._secret_days = SecretDayBook(
                store, reset=lambda: self.day.boundary_ms())
        return self._secret_days

    @property
    def store(self):
        """THIS PROFILE'S VIEW OF THE ONE DATABASE (#1398, #2025).

        One file for every account since #2025, and the isolation is the store's own
        `profile` rather than the path (`panel/runtime/store.py`). Built on first ask and
        **re-checked against the profile on every ask**: the runtime outlives a profile
        switch, and a store that did not follow would go on writing the previous
        account's register — the failure `docs/research/profile-isolation.md` is a list
        of. The check is a string compare; the store is only rebuilt when the profile has
        actually moved, and the one being left is closed rather than leaked.
        """
        want = self.profiles.store_db()
        whose = self.profiles.active
        # THE PATH NO LONGER MOVES (#2025) — there is one database — so the profile is
        # what is compared. A store that did not follow the switch would go on writing
        # the previous account's rows under the previous account's name, which is the
        # same failure as before with the file merged away.
        if self._store is not None and (self._store.path != want
                                        or self._store.profile != whose):
            try:
                self._store.close()
            except Exception:                                       # noqa: BLE001
                self.dbg("store").exception("could not close the previous store")
            self._store = None
        if self._store is None:
            from .store import Store, import_profile_db_once
            store = Store(want, whose)
            # WHAT THIS PROFILE HAD WHEN IT HAD A DATABASE OF ITS OWN (#2025) — its
            # register, its monsters, its ★ list, its ghost tiles, its map coverage and
            # its day counters. Once, on the first ask, before anything reads: a panel
            # that opened on the shared database with none of it would look exactly like
            # a panel that had forgotten the account, and the day counters are what stop
            # a quota being spent twice.
            try:
                carried = import_profile_db_once(
                    store, self.profiles.legacy_store_db())
            except Exception:                                       # noqa: BLE001
                self.dbg("store").exception("the old profile database was not imported")
            else:
                if carried:
                    self.dbg("store").info("carried the old profile database across: %s",
                                           carried)
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
    #: How many times a PATIENT run tries to take the client back after standing aside,
    #: and how long it waits between attempts (#1702). A detached chain lives for the
    #: length of a march, this account's schedule fires a rally join every few seconds,
    #: and every one of them outranks it — so «could not get the game back» is an ordinary
    #: minute rather than a broken client, and killing the run over it lost a chain that
    #: was three seconds from its next kill. Sixty seconds of `park` a time, five times.
    PARK_TRIES = 5
    PARK_RETRY_SEC = 1.0

    def yield_hook(self, tag: str = "timer", patient: bool = False):
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
            got = self.game.park(tag)
            if not got and patient:
                # A DETACHED run does not die because the schedule was busy (#1702). It
                # holds nothing while it waits, so the only cost of trying again is the
                # wait — and the alternative, live, was a chain killed at its third kill
                # by the account's own rally traffic.
                for _ in range(self.PARK_TRIES - 1):
                    time.sleep(self.PARK_RETRY_SEC)
                    self.log.say(tag, "priority.waiting", owner=who)
                    if self.game.park(tag):
                        got = True
                        break
            if not got:
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

    # -- getting the lease back after the daemon restarted (#1411) -----------
    def regain_hook(self, tag: str = "action", patient: bool = False):
        """A lease-regain callable for a run — `Context.regain`, played on a refusal.

        THE OTHER WAY A LEASE GOES, and until #1411 only one of them was answered. A run
        that PARKS knows it let the lease go, and `yield_hook` above hands it a new one on
        the way back. A run whose DAEMON restarted underneath it knows nothing at all: the
        token it was granted when its context was built is one the new daemon never issued,
        so every call from that moment on is refused as «lease lost» — for the rest of the
        run, because a token is read once and nothing ever re-read it.

        Nothing said so, either. `_eval_lua_value` reads a refused chunk as «could not
        ask», which is the right answer for a client that is still booting and the wrong
        one here: on 2026-08-14 an autoassist run went deaf mid-recipe and `launch_game`
        spent the last ten seconds of its cap failing to read a scene off a daemon that
        had been warm for three of them.

        So the run says so ONCE, in the log, and carries on — «продолжаю» is the honest
        report, because everything else about the run is still true. A lease that cannot
        be regained is said too and answered `False`, and then the interpreter raises the
        refusal it was holding: a run that does not hold the client may not press it.
        """
        def regain(ctx=None) -> bool:
            # …AND A LEASE SOMEBODY ELSE IS HOLDING IS WAITED FOR, NOT GIVEN UP ON
            # (#1702). The refusal has two authors and they want opposite answers. A
            # daemon that restarted hands the lease straight back — that is #1411 and it
            # is the `regain` below. A TIMER that took the client wants only its own
            # minute: the operator's hunt died with «lease lost — it expired or was taken
            # by default/timer» while the errand that took it had already finished, and a
            # run that has been walking a squad across the map for ten minutes should not
            # be ended by an errand that lasted twenty seconds.
            #
            # So the hook waits, briefly and out loud. Bounded because a lease that is
            # still somebody else's after a minute and a half is a client this run is not
            # going to get back, and hanging in front of it is worse than stopping.
            # A DETACHED chain waits far longer than a press does — see
            # :data:`LEASE_WAIT_DETACHED_SEC`.
            deadline = time.time() + (LEASE_WAIT_DETACHED_SEC if patient
                                      else LEASE_WAIT_SEC)
            said = False
            while not self.game.regain(tag):
                if time.time() >= deadline:
                    self.log.say(tag, "lease.gone")
                    return False
                if not said:
                    self.log.say(tag, "lease.waiting")
                    said = True
                time.sleep(LEASE_POLL_SEC)
            # THE SAME TWO LINES `step_aside` ENDS ON, and for the same reason: the token
            # on the context and the evaluator built with it are both the old lease.
            if ctx is not None:
                ctx.game_token = self.game.token
                ctx.evaluator = None
            self.log.say(tag, "lease.regained")
            return True

        return regain

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
                   priority: int = claims.HUMAN, human: bool = False,
                   inline: bool = False) -> bool:
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

        # WHERE A CALLBACK LANDS (#2594). Every caller of this until now was a press and
        # wanted its answer on the thread that draws; :meth:`play_now` is not — it is a
        # worker that came here for the CLAIM and wants the Outcome in its own hand,
        # because posting it to Tk and waiting for Tk to hand it back is a round trip
        # through the one thread the whole window shares. So `inline` says «I am already
        # on a thread that may block»: the run happens here and the callbacks are called
        # where they are made.
        deliver = (lambda call: call()) if inline else self._on_tk

        # THE GATE, BEFORE THE CLAIM AND BEFORE THE THREAD (#1910). `ActionRunner.run`
        # asks it too and is the guarantee — it is the door a caller that never comes
        # through here still has to pass — but a run refused down there has already
        # taken the relaunch lock, reserved the client and waited out a lease against a
        # daemon that is not answering. Asked here it costs a dict lookup, and the
        # sentence is the same one, said once.
        #
        # `human` is not defaulted to True however much this method's callers are
        # presses: the tab polls were coming through here as well, indistinguishable
        # from a button because a button is what everybody assumed. False is the
        # fail-safe direction — a caller nobody marked is held and says so.
        held = self.gate.blocks(name, human=human)
        if held:
            self.log.say(tag, held, name=name)
            if on_result is not None:
                deliver(lambda: on_result(Outcome(False, self.t(held, name=name))))
            if on_done is not None:
                deliver(on_done)
            return False

        if not self._relaunch_lock(name, tag):
            return False

        # A SCENARIO THAT SAID IT MUST NOT HOLD THE PANEL UP (#1702). `DETACH` in the file
        # drops the run to :data:`claims.DETACHED` — below an ordinary errand, so anybody
        # who wants the client outranks it — and hands it the step-aside hook, so it lets
        # go at the first statement boundary they ask. The press is answered the same way
        # it always was: this returns as soon as the run has been accepted.
        detached = self.actions.detached(name)
        if detached:
            priority = claims.DETACHED
            self.log.say(tag, "action.detached", name=name)
        # …AND ONE THAT DECLARED `SHARE` (#2404). It opens no window, so it keeps the
        # client only while it is talking to the game: :data:`claims.SHARED` is below
        # everything, which is what makes its step-aside hook answer ANY waiter rather
        # than only a more urgent one. A press by a person is still a press — the run is
        # not detached, the caller is answered as it always was — it merely does not sit
        # on the client through its own pauses.
        # …AND A PERSON'S PRESS IS NEVER DEMOTED BY IT (#2594). `SHARE` says how a run
        # HOLDS the client, not how hard it is to get: demoting a press to
        # :data:`claims.SHARED` means it outranks nothing at all, so the first thing
        # holding the client refuses it outright. Live on 2026-09-06 that is exactly what
        # a chat send would have become — eight «занят» in four minutes for one typed
        # line — and «нажал, а ничего не ушло» is the failure #1288 exists to remove.
        # So the demotion is for the runs nobody is waiting on; a press keeps its rank
        # and merely gains the step-aside hook below.
        shares = self.actions.shares(name)
        if shares and not detached and not human:
            priority = claims.SHARED

        held = self.game.reserve(tag, priority)
        if not held and not self.game.outranks(priority) and not shares:
            # Nothing to be done: whoever has the client is at least as urgent as this
            # press, and asking them to step aside for an equal would only shuffle the
            # order of two things that both have to happen.
            #
            # …EXCEPT FOR A SHARING RUN, WHICH QUEUES INSTEAD OF DYING (#2594). Waiting
            # costs the panel nothing when the waiter holds nothing: it hangs its demand
            # on the door and `claim_soon` below gives up after
            # :data:`~panel.runtime.link.YIELD_WAIT_SEC` with the same «занят» this line
            # would have said now. What that buys is the ordinary case — an equal holder
            # that finishes in two seconds — instead of dropping the person's message.
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
                    deliver(lambda: on_result(Outcome(False, self.t("busy"))))
                if on_done is not None:
                    deliver(on_done)
                return
            try:
                on_event = lambda msg: self.log.put(f"[{tag}] {msg}")   # noqa: E731
                # The step-aside hook goes to the DETACHED run only: an ordinary press is
                # already the most urgent thing there is, and one that parked for a
                # background errand would be the queue this whole area exists to remove.
                step_aside = (self.yield_hook(tag, patient=True)
                              if (detached or shares) else None)
                # …AND THE SAME PATIENCE ON THE WAY BACK (#2390). Stepping aside was
                # only half of it: a chain that let go politely still DIED the next
                # time somebody took the lease outright, because the regain hook it
                # inherited was the one written for a press. Its own hook waits the
                # detached while, and says so under this run's own tag rather than
                # under the runtime's, so the log names which run is waiting.
                come_back = self.regain_hook(tag, patient=detached)
                if on_result is None:
                    self.actions.run(name, args, hwnd=0, on_event=on_event,
                                     profile=None, cancel=cancel, tag=tag,
                                     human=human, yield_to=step_aside,
                                     regain=come_back)
                else:
                    outcome = self.actions.play(name, args, hwnd=0, on_event=on_event,
                                                profile=None, cancel=cancel, tag=tag,
                                                human=human, yield_to=step_aside,
                                                regain=come_back)
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
                    deliver(lambda: on_result(result))
                if on_done is not None:
                    deliver(on_done)
                self.game.settled()

        # NAMED, and named with the PROFILE (#1392). A thread list is the last resort of
        # every jam diagnosis, and `Thread-14` in a window holding four accounts says
        # neither what it is doing nor whose it is — which is exactly the confusion
        # profile isolation exists to prevent. Trimmed, because a thread name is carried
        # by the OS on some platforms.
        if inline:
            # ON THIS THREAD, under the claim that was just taken. The caller asked for
            # exactly that and is not the Tk thread — :meth:`play_now` says so in its
            # own docstring, and the assertion that keeps it true lives there.
            work()
            return True
        threading.Thread(target=work, daemon=True,
                         name=f"lw:{self.profiles.active}:{tag}:{name}"[:60]).start()
        return True

    def play_now(self, name: str, args: dict | None = None, *, tag: str = "action",
                 priority: int = claims.SHARED, human: bool = False,
                 cancel=None) -> Outcome:
        """Play a scenario ON THIS THREAD, under a proper claim, and hand back what it found.

        **NEVER from the Tk thread**: it blocks for as long as the scenario runs.

        WHY IT EXISTS (#2594). A tab that wanted a scenario's READINGS on its own worker
        had one option — `rt.actions.play(...)` — and that door takes **no game claim at
        all**. It only looks harmless: the run still asks the daemon, using whatever lease
        token the runtime happens to be holding, so it interleaves its calls into a timer's
        run and the two take the lease off each other. Measured on this account's own
        `panel.log` over 2026-09-03..06, with the chat as the only heavy user of that door:
        1538 translation batches whose own work is one call, one 3-second wait and two
        reads — median 5 s, p90 11 s, **max 127 s** — and 16 runs that ended
        «lease lost — it expired or was taken by default/timer». Both numbers are one bug:
        an unclaimed run fighting claimed ones.

        So this is the claimed version of the same call. It is `play_async` with the thread
        taken out: the same gate, the same relaunch lock, the same reserve/lease dance, the
        same `SHARE` step-aside and regain hooks — and the Outcome returned rather than
        posted. :data:`~panel.runtime.claims.SHARED` by default, because a caller that
        wants a reading on a background thread is exactly the run that should hold the
        client only while it is talking to it.
        """
        box: list = []
        self.play_async(name, args, tag=tag, priority=priority, human=human,
                        cancel=cancel, inline=True, on_result=box.append)
        # An empty box is the one path that answers before a context exists: the claim was
        # refused outright, which `play_async` reports by logging «занят» and returning.
        return box[0] if box else Outcome(False, self.t("busy"))

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

    def stop_heartbeat(self, why: str = "") -> None:
        """The panel is closing on purpose — leave a farewell and take the lock.

        A no-op for a window that never started one, which is what keeps a standalone
        tab's `shutdown` from deleting the running panel's heartbeat.

        `why` is what the note says (`panel/runtime/autostart.py::clear`): a plain close
        by default, «coming back» when the shutdown is half of a restart. The guard in
        the daemon reads it to tell a panel somebody closed from one that fell over
        (#1910), and the difference is only recordable HERE — afterwards there is no
        process left to ask.
        """
        if not getattr(self, "_heartbeat", False):
            return
        from . import autostart as autostartmod

        self._heartbeat = False
        self.tick.disarm("heartbeat")
        autostartmod.clear(self.profiles, why=why or autostartmod.CLOSED)
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
        # …and the day's tally lets the reading it listens to go (#2743).
        try:
            self.resource_book.shutdown()
        except Exception:                                           # noqa: BLE001
            pass
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
