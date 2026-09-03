r"""Scheduled repeats of the panel's actions — the timer module.

A *timer* is a scenario plus a period: "collect the base every hour", "donate to
the alliance's technology every twenty minutes". While the panel is open
a background thread ticks; a timer whose last successful run is older than its
period runs its scenario headless (no window opened, no mouse) and writes down
when it finished. That record lives in the profile directory, so closing the
panel does not reset the clock — a timer that came due while it was shut fires
shortly after the next launch.

The list of timers is **data, not code, and it belongs to the profile**: it is
read from ``panel/profiles/<profile>/timers.json``, so a new timer is a new entry
in that file and nothing here has to change. Two accounts therefore keep two
different schedules — different timers, each with its own switch, period and args
— and switching profiles in the panel switches the whole set.

A profile that has none yet is seeded from the *template*, ``panel/timers.json``,
which is itself seeded from the hardcoded catalogue below the first time the
panel runs. So the chain is: built-in list → template (edit it to change what new
profiles start with) → the profile's own file (what actually runs, and what the
panel's checkboxes write to). The built-in list is also the last-resort fallback
if a profile's file is ever unreadable.

An errand that appears LATER — a new ability shipped with an update — is adopted
into every profile once, switched off, so it does not stay invisible to the
accounts that already had a file. It comes from the template *and* the built-in
list, because the template is a local file that an updated installation still has
last month's copy of. Deleting the errand afterwards keeps it deleted; the how and
the why are in :func:`adopt_new_errands` and :func:`offered_catalogue`.

    [
      {
        "name": "collect_base_resources",       // id: config key and record key
        "scenario": "collect_base_resources",   // one action, or a list (below)
        "interval_sec": 3600,
        "retry_sec": 300,                        // wait this long after a FAILED run
        "enabled": false,
        "args": {}
      },
      {
        "name": "quick_sweep",
        "scenario": ["collect_truck_resources", "collect_base_resources"],
        "interval_sec": 3600,
        "enabled": false,
        "args": {},
        "title": "Everything the base has banked"
      }
    ]

``scenario`` is one step or a list of them, run in order. A step is either the
name of an action script (``src/lastwar_bot/actions/<name>.md``) or, when no such
script exists, DSL source run as-is — so a timer can carry its commands inline::

    {"name": "quick_donate", "scenario": "TAP donate_1000 xall", "interval_sec": 1200}

``args`` is handed to the scenario as script variables (the same ``ctx.vars`` that
``READ_LUA … INTO x`` writes), so steps can test them with the ordinary
``IF x > 3`` conditions, and ``{name}`` in an inline step is replaced by the
matching value before it is parsed.

Every field except ``name`` and ``scenario`` may be left out: it then falls back
to the entry of the same name in the hardcoded catalogue, and failing that to the
module defaults. ``enabled`` and ``interval_sec`` are what the panel's own
checkbox and period write back to — the profile's file is the one source of truth
for its schedule, not a default some other setting overrides. **The whole entry is
editable from the Timers tab** (add / copy / edit / delete, steps and args
included, via :meth:`Catalogue.replace` and :meth:`Catalogue.remove`); the file
stays the record, and editing it by hand and pressing «⟳» works exactly as before.

What the module decides, and what it deliberately does not:

  * **A timer that has never run is due at once.** "Not collected for over an
    hour" is exactly what an empty record means, so the first tick after a fresh
    profile fires everything that is switched on.
  * **A failed run is not a run.** ``last_run`` only moves when the scenario
    really finished, so a run lost to a closed game is retried rather than
    silently skipped for another hour. To keep a permanently broken scenario from
    re-firing every tick, a failure parks that one timer for
    :data:`RETRY_HOLD_SEC`.
  * **One thing at a time, in one thread.** Every scheduled scenario runs on the
    single worker thread, fed by a queue — nothing ever runs in parallel with
    anything else. Two timers that come due in the same second go on the queue in
    order and the second waits for the first to finish; the "run now" button
    enqueues too, rather than starting a thread of its own. When the panel is busy
    with a button-driven action of its own, the errand stays queued and is taken
    up again a few seconds later, so it is delayed, never lost.

Nothing here imports Tk or the game: the panel passes in the settings, a runner
and a log sink, which keeps the decision — *what is due right now* — a plain
function that tests can call without a display or a running client.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace as _replace

from . import debug_log, paths
from .i18n import Message
from .profile import _write_json
from .runtime import settings_files

# The debug logger for a scheduler NOBODY GAVE ONE TO. The panel always hands each
# profile's own (`rt.dbg("timers")`); this fallback used to be the unscoped root,
# which is the FIRST open profile's `debug.log` — so a stray line was filed under an
# account it had nothing to do with. The WINDOW's file instead (#1306).
def _dbg_window():
    return debug_log.panel_logger("timers")

# How often the scheduler wakes up to look for a due timer. Well under the
# shortest sensible period, so a timer fires within a few seconds of coming due,
# and a tick that finds nothing costs one dict comparison. A timer configured
# with a period shorter than this simply fires once a tick.
TICK_SEC = 20.0

# Default hold after a failed run, before the timer is tried again. Per-timer now
# (``Timer.retry_sec``): a scenario that FAILs on a precondition it will soon meet
# (not on the base yet) wants a short retry, while a truly broken one should not
# re-fire every tick and fill the log with the same error. This is the fallback for
# an entry that does not set its own.
RETRY_HOLD_SEC = 300.0

# How long the worker sits still after the panel turns an errand down as busy.
# The errand stays in the queue either way; this is only about not asking again
# in a tight loop while a person's own button press runs its course.
BUSY_RETRY_SEC = 5.0

# How often a fire the GATE turned away is offered again (#1416). A push is not a
# clock: nothing brings it back by itself, so an errand refused because the game was
# not up, the daemon was down or the panel was stopped used to be thrown away — and
# «пропускаются события» is exactly what that looks like from outside. It waits here
# instead and is re-offered on this beat until the gate opens or its patience runs out.
GATE_RETRY_SEC = 10.0

# How long a fire may wait for its gate before it is given up as stale. A push is about
# a moment in the game — a rally that is out, a request that is open, a balance that
# just moved — and re-running it a quarter of an hour later presses at something that is
# no longer there. Long enough to outlast a restart of the client (measured at a median
# 184 s, `restart_game`), short enough that nothing acts on last hour's news.
GATE_KEEP_SEC = 600.0

# How many finished/cancelled/given-up errands the queue remembers, newest first —
# «Занятость» (#1500) reads this so a name that just left the queue does not read as
# «пропало без вести»: it says what it turned into instead. Bounded, and lost on a
# restart on purpose, exactly like `_gated` and every other in-memory queue reading —
# it is a checkpoint of the worker's own recent past, not game data (`CLAUDE.md`).
RECENT_KEEP = 20

# How often ONE errand may repeat the same reason for being skipped. A skip has to be
# said — «тихо не поехали» is exactly what #1281 was about, and a wire trigger can be
# refused hundreds of times an hour (a profile whose client is down heard 10 035 rally
# pushes on 2026-08-07 and its log carried 31 lines about it, none of them attached to a
# rally). Saying every one would drown the log; saying only the first hides how much is
# being lost. So the first is said at once and the rest are rolled up: the same reason
# repeats at most this often, carrying the count it has gathered since.
SKIP_NOTE_SEC = 60.0

# Bounds enforced on whatever the config asks for, so a hand-edited file cannot
# ask for a timer that fires every second or one that never fires at all.
MIN_INTERVAL_SEC = 10
MAX_INTERVAL_SEC = 7 * 24 * 3600
DEFAULT_INTERVAL_SEC = 3600

# THE GAME'S OWN ANSWER TO «WHEN AGAIN», when it has one (#1881).
#
# A period is a guess about a game that already knows. The tavern's free pulls are the
# case this was written for: they come back on two clocks of the server's own — one for
# the heroes and one for the survivors — and those clocks are not an hour, not the same
# as each other and not the same tomorrow. So a scenario that has READ such a clock
# leaves the answer in this variable and the schedule books the errand's next turn with
# it (:meth:`LastRunStore.mark_due_at`), which then wins over the row's period for that
# one turn.
#
# SECONDS FROM NOW, never an absolute stamp: this machine's clock and the game's
# disagree (`tools/lib/game_clock.py`), and the scenario is the only one of the two
# holding the game's. Absent or zero means the run had nothing to say, and then the
# configured period stands — so a reading that fails can never quietly stop a timer.
NEXT_RUN_VAR = "next_run_in"

# A DAY, and the reason it is a named constant rather than 86400 in three places:
# a period that is a WHOLE NUMBER OF DAYS is not scheduled like any other period.
#
# «Раз в сутки» never means «twenty-four hours after the last time». What the game
# actually hands out once a day — five robberies, the codename attacks, a donation
# quota — comes back at the warzone's own 00:00, and an errand chasing it on a plain
# 24-hour period drifts forward by however long each run took and by however long the
# panel was shut. It only has to drift past one reset to lose a whole day: the errand
# fires at 00:01, spends the day's quota, and is next due at 00:01 TOMORROW — one
# minute after the fresh quota arrived and twenty-three hours and fifty-nine minutes
# before anything touches it.
#
# So a day-long period is anchored instead: the next turn is the first SERVER midnight
# after the last run (:func:`next_after`). A run at 23:59 is followed by one a minute
# later, because a minute later is when there is something to do again. Everything
# shorter than a day is unchanged — an hourly collection has no boundary to respect,
# and neither has a period that is not a whole number of days (36 hours is not a daily
# errand and must not be turned into one).
DAY_SEC = 24 * 3600

PANEL_DIR = paths.PANEL_DIR
# The TEMPLATE, beside the profiles rather than beside the code (#1276): what a profile
# that has no timers of its own is seeded from, and nothing else. The catalogue a profile
# actually runs lives in its own directory (ProfileManager.timers_json), next to the
# record of when each of them last ran — so one account's schedule is not the other's.
TEMPLATE_FILE = paths.TIMERS_TEMPLATE


@dataclass(frozen=True)
class Timer:
    """One schedulable errand, as configured.

    ``scenario`` is a *sequence* because an errand is not always one press: a
    profile may want two recipes under a single switch and a single clock. The
    runner walks them in order and the errand only counts as done when the last
    one has finished — a first step that went through followed by a failed second
    is a failed errand, and the retry does both.

    That is a shape the operator may ask for, not one the built-ins reach for:
    two recipes on one clock can only ever have ONE period, and errands that
    genuinely want different ones — a donation every 20 minutes and a gift chest
    every six hours — must be two rows (:data:`SPLIT_ERRANDS`).
    """

    name: str                       # id — config key, record key, log name
    scenario: tuple[str, ...]       # action names and/or inline DSL source
    interval_sec: int = DEFAULT_INTERVAL_SEC
    # How long to wait before retrying after a FAILED run (a raised step or a FAIL in
    # the scenario). A success uses interval_sec; only a failure uses this.
    retry_sec: int = int(RETRY_HOLD_SEC)
    enabled: bool = False
    # «СРАЗУ, БЕЗ ОЧЕРЕДИ» (#1288). An errand the operator has marked this way does not
    # wait behind the ordinary work: it runs on a thread of its own, and it asks for the
    # client at a level that makes an ordinary errand step aside for it
    # (`panel/runtime/claims.py`). It is a property of the ERRAND and not of its name —
    # nothing anywhere reads a list of «the urgent ones», because whose errands are
    # urgent is one account's answer and not another's.
    #
    # It is for the errands that are cheap and pointless late. The alliance help is the
    # one the person named: a request pays only while it is open, the press takes two
    # seconds, and a fire waited a p90 of 8–10 s and a maximum of 1276 s for its turn on
    # 2026-08-07. It is NOT for a long errand — a `restart_game` marked this way would
    # hold the client for five minutes with nothing able to make it park.
    immediate: bool = False
    # WHICH WEEKDAYS THE ERRAND BELONGS TO — 1 = Monday … 7 = Sunday, empty for «any».
    #
    # A period cannot say «по воскресеньям». «Every seven days from the last run» drifts
    # by however long the run took and by however long the panel was shut, and it only
    # has to drift once to land on a Monday and stay there for good — which is the whole
    # of what a weekly event is not. So a row that names its days is not scheduled off
    # its period at all: it is due at the START of a matching GAME day it has not yet
    # run in, and at nothing else (:func:`next_weekly`).
    #
    # THE WEEKDAY IS THE GAME'S. The warzone's day turns at its own 00:00 — measured at
    # 02:00 UTC — so for two hours out of every twenty-four this machine already calls it
    # Monday while the game is still handing out Sunday's event. The boundary comes from
    # the profile's own `DayReset`, exactly as a daily errand's does.
    weekdays: tuple[int, ...] = ()
    args: dict = field(default_factory=dict)
    title: str | None = None        # row label straight from the config
    label_key: str | None = None    # …or a locale key, for the built-in entries

    def as_dict(self) -> dict:
        """The entry as it is written in the catalogue file."""
        out = {
            "name": self.name,
            "scenario": list(self.scenario) if len(self.scenario) != 1
            else self.scenario[0],
            "interval_sec": self.interval_sec,
            "retry_sec": self.retry_sec,
            "enabled": self.enabled,
        }
        if self.immediate:
            out["immediate"] = True
        if self.weekdays:
            out["weekdays"] = list(self.weekdays)
        if self.args:
            out["args"] = dict(self.args)
        if self.title:
            out["title"] = self.title
        return out


# The fallback catalogue: what ships in the box, what a missing file is seeded
# from, and what each field falls back to when an entry leaves it out. Every
# recipe behind these is headless (the gift one opens the alliance window inside
# the game and closes it again, still without touching the mouse), so a timer
# firing never takes the machine away from whoever is using it.
DEFAULT_TIMERS: tuple[Timer, ...] = (
    Timer(
        name="collect_base_resources",
        scenario=("collect_base_resources",),
        # An hour. The production buildings keep banking while nobody collects,
        # so the period is about not letting them sit full, not about a cap.
        interval_sec=3600,
        label_key="timers.item.collect_base_resources",
    ),
    Timer(
        name="donate_alliance_tech",
        scenario=("donate_alliance_tech",),
        # Twenty minutes, which is the rate the game hands the attempts back at.
        # This is the errand with something to lose: the attempts bank up to a cap
        # and every one that is still banked when the day turns is simply gone, so
        # it wants the short clock — and used to be denied it by sharing one with
        # the gifts.
        interval_sec=1200,
        # The press is headless and no-ops on an empty quota, so a failure means the
        # game was not answering; five minutes is soon enough to catch the attempts
        # before the next batch lands on top of them.
        retry_sec=300,
        enabled=False,
        label_key="timers.item.donate_alliance_tech",
    ),
    Timer(
        name="heal_units",
        scenario=("heal_units",),
        # HALF AN HOUR, AND IT IS THE SAFETY NET RATHER THAN THE SCHEDULE (#2085). The
        # errand's real clock is inside the game: the run arms a watch that collects a
        # finished heal, sends the next portion and asks the alliance on the client's own
        # calls (`OnQueueEnd`, `HospitalCureHandle`, `UpdateHospitalDeadInfo`) and on one
        # alarm pinned to the heal's own `endTime`. Nothing here polls anything.
        #
        # What this period is for is the two cases the watch cannot cover by itself: a
        # client restarted since the last run has a fresh VM and no hook at all, and a
        # watch that found nothing to do for an hour takes itself off the game's timer
        # (a timer in somebody else's game has to end). Both are mended by arming again,
        # which costs one round trip and no window.
        interval_sec=1800,
        # A failure here is a client that was not answering; a few minutes is soon enough.
        retry_sec=300,
        enabled=False,
        args={"portion": 0, "help": 1, "watch": 1},
        label_key="timers.item.heal_units",
    ),
    Timer(
        name="collect_alliance_gifts",
        scenario=("collect_alliance_gifts",),
        # Six hours. Nothing about a gift expires while it waits in the chest, and
        # this recipe — unlike the donation — opens a window in the game and closes
        # it again, so looking oftener costs the player's view for nothing.
        interval_sec=21600,
        retry_sec=300,
        enabled=False,
        label_key="timers.item.collect_alliance_gifts",
    ),
    Timer(
        name="collect_truck_resources",
        scenario=("collect_truck_resources",),
        # Four hours. The base truck's idle-reward accumulator fills slowly and one
        # claim empties it, so there is nothing to gain from looking oftener.
        interval_sec=14400,
        # These three FAIL when the base is not on screen (they can only act in the
        # city scene), so a short retry picks them up as soon as the player is home.
        retry_sec=300,
        enabled=False,
        label_key="timers.item.collect_truck_resources",
    ),
    Timer(
        name="collect_visitor_gifts",
        scenario=("collect_visitor_gifts",),
        # An hour. A gift-bearing survivor waits in the city queue until collected,
        # so hourly keeps the queue clear without pestering a mostly-empty one.
        interval_sec=3600,
        retry_sec=300,
        enabled=False,
        label_key="timers.item.collect_visitor_gifts",
    ),
    Timer(
        name="collect_vip_gifts",
        scenario=("collect_vip_gifts",),
        # An hour. Both rewards come back once a day and the gates are the SERVER's own
        # answer about today, so the only thing the period decides is how long after the
        # day turns over they are picked up. The run that finds nothing is one VM round
        # trip against the client's own memory — no question goes on the wire for it — so
        # looking hourly costs about as little as looking at all.
        interval_sec=3600,
        # A failure here is a client that was not answering; a few minutes is soon enough.
        retry_sec=300,
        enabled=False,
        label_key="timers.item.collect_vip_gifts",
    ),
    Timer(
        name="collect_shop_freebies",
        scenario=("collect_shop_freebies",),
        # SIX HOURS, and it is the person's own choice (#2395): «включить, но раз в 6
        # часов». Both claims come back once a game DAY and both gates are the server's
        # own answer about today, so the period decides nothing except how long after the
        # day turns over the free gift is picked up — four looks a day is more than
        # enough for two daily rewards, and an hourly one would only be cheaper to argue
        # for than to justify. A run with nothing waiting is one VM round trip against
        # the client's own record and not one question goes on the wire.
        interval_sec=21600,
        # A failure here is a client that was not answering; a few minutes is soon enough.
        retry_sec=300,
        enabled=False,
        label_key="timers.item.collect_shop_freebies",
    ),
    Timer(
        name="lucky_share",
        scenario=("share_lucky_packet",),
        # HALF AN HOUR, and it is the person's own choice (#2397): «раз в полчаса тоже
        # проверял». A surprise box sometimes drops a packet of free diamonds that may be
        # given away for ONE HOUR after the drop, so a half-hourly look catches one with
        # the window to spare — and the drop is rare enough that listening for it was
        # judged not worth it («слушать сейчас бесполезно, редкое событие»).
        #
        # THE LOOK IS LOCAL. The gate is `LuckyBuffManager.notSharedLuckyPacketList`
        # against the client's own clock, so a run with nothing waiting is one VM round
        # trip and not one question goes on the wire — which is what makes a period
        # affordable here at all (`CLAUDE.md`, «read once, then LISTEN»: what is forbidden
        # is asking the SERVER in the background).
        #
        # The other half of the answer is the hook that does not wait for this clock:
        # opening a chest from the bag runs the same check on the spot
        # (`actions/use_item.md`, `actions/open_explorer_chests.md`).
        interval_sec=1800,
        # A failure here is a client that was not answering, or a packet the chooser
        # refused; a few minutes is soon enough to try again inside the hour.
        retry_sec=300,
        enabled=False,
        label_key="timers.item.lucky_share",
    ),
    Timer(
        name="recruit_survivors",
        scenario=("recruit_survivors",),
        # An hour, the same cadence as the gifts — a recruitable survivor sits in the
        # same city queue, and the recipe no-ops when none is waiting.
        interval_sec=3600,
        retry_sec=300,
        enabled=False,
        label_key="timers.item.recruit_survivors",
    ),
    Timer(
        name="tavern_free_pull",
        scenario=("tavern_free_pull",),
        # An hour, and it is the FALLBACK rather than the schedule. Both recruit banners
        # hand their free pull back on a clock of the server's own, the two clocks differ
        # from each other, and the run reads the nearer of them and books its own next
        # turn with it (:data:`NEXT_RUN_VAR`). This period only decides when to look
        # again after a run that could not read one.
        interval_sec=3600,
        # A failure here is a client that was not answering — the recipe FAILs rather
        # than report «no free pull» over a banner it could not see — and that mends
        # itself in minutes.
        retry_sec=300,
        enabled=False,
        label_key="timers.item.tavern_free_pull",
    ),
    Timer(
        name="occupation_skills",
        scenario=("occupation_skills",),
        # SIX HOURS, AND IT IS THE FALLBACK RATHER THAN THE SCHEDULE. Every one of the
        # profession's active charges recovers on a countdown the SERVER sets — the reply
        # to a press carries it (`recover.cdEndTime`), 23.5 h for most of them and up to
        # 71.5 for the banner — so the run reads the soonest of those instants and books
        # its own next turn with it (:data:`NEXT_RUN_VAR`). Nothing here polls anything:
        # this period only decides when to look again after a run that could not read a
        # clock at all (a client that was not logged in, a tree with nothing learned).
        interval_sec=21600,
        # A failure is a client that could not answer for the mastery tree — the login
        # screen answers everything and knows nothing (`project_login_screen_lies`), and
        # the recipe FAILs rather than call an unreadable tree an empty one. That mends
        # itself in minutes.
        retry_sec=300,
        enabled=False,
        label_key="timers.item.occupation_skills",
    ),
    Timer(
        name="apply_ministry_interior",
        scenario=("apply_ministry_interior",),
        # Half an hour, and the retry is the same half hour on purpose. The recipe ends
        # as a FAILURE whenever the application did not go through (another post in hand,
        # the client's pre-flight closed, the server did not seat us), so `last_run` only
        # moves on a real application — which is exactly the asked-for behaviour: the
        # clock restarts on success and on nothing else, and a refused attempt is made
        # again in half an hour rather than sitting out a longer hold.
        interval_sec=1800,
        retry_sec=1800,
        enabled=False,
        label_key="timers.item.apply_ministry_interior",
    ),
    Timer(
        name="secret_tasks_day",
        scenario=("work_secret_tasks",),
        # A DAY, and it is the FALLBACK rather than the schedule — the same shape as
        # `tavern_free_pull` above and for a better reason than a guess.
        #
        # ONE ROW AND NOT TWO (#1903). The operator asked for a collector that takes each
        # reward as its task ripens, and for a daily errand that sends and collects
        # everything. Those are the same clock: a running task's `completionTime` is the
        # instant its reward becomes claimable, the instant its march slot stops being
        # held by an unclaimed reward, AND the instant its heroes are home to be sent
        # again. A second row would wake at exactly those instants, take the same game
        # claim and race this one over the same list.
        #
        # So the recipe reads the nearest finish and books its own next turn with it
        # (:data:`NEXT_RUN_VAR`), and this period only decides where a day with nothing
        # running starts from. Being a whole day it is anchored to the server's own
        # midnight (:data:`DAY_SEC`), which is what «раз в сутки» means for a quota.
        interval_sec=DAY_SEC,
        # FIVE MINUTES, and it was half an hour until #2073. A failure here is a client
        # that was not answering — and the retry hold is the one thing that outranks the
        # appointment the game named (:meth:`Catalogue.due_names` sits it out before it
        # ever looks at `due_at`). Half an hour of that is half an hour of a finished task
        # standing on the map to be robbed, and a client that is not answering costs one
        # cheap refusal to find out. Five minutes is still ten times the tick.
        retry_sec=300,
        enabled=False,
        # THE RULE, WRITTEN DOWN WHERE BOTH FRONT-ENDS CAN REACH IT (#2022). The knobs
        # were on «Командный пункт», which is dev-only — so on a live profile the day's
        # errand ran on the recipe's own defaults and nothing could be seen or changed.
        # These are those defaults, spelled out so the gear on «Таймеры» draws what is
        # really in force rather than a blank that reads as «off»
        # (`panel/runtime/errand_args.py`).
        args={"keep": 3, "use_diamonds": 1, "diamond_cap": 1200,
              "mega": 1, "dispatch": 1, "only_ur": 1},
        label_key="timers.item.secret_tasks_day",
    ),
    Timer(
        name="send_trucks",
        scenario=("send_trucks",),
        # A DAY, and a fallback rather than a schedule — the same shape as
        # `secret_tasks_day` above and for the same reason (#1908). The allowance is a
        # daily one, so a day with the whole fleet standing starts here; but a truck
        # that HAS gone out comes home at a moment the client knows to the millisecond,
        # and the recipe books its own next turn with it (:data:`NEXT_RUN_VAR`). A
        # second row on a period would wake between those instants, take the same game
        # claim and find a station with nothing standing at it.
        interval_sec=DAY_SEC,
        # A failure here is a client that was not answering — the presses no-op on a
        # locked or empty station. Half an hour, because the day has hours in it.
        retry_sec=1800,
        enabled=False,
        label_key="timers.item.send_trucks",
    ),
    # «ВЫПОЛНИТЬ ЗАДАНИЯ РАДАРА» IS NOT A ROW HERE ANY MORE (#2061) — the person's
    # words: «из таймеров убери таймер выполнить задания радара, который просто полностью
    # собирает задания, перенеси в чеклист». It claims what the board has ripened and runs
    # the errands that need no march: a thing a person does when they think of it, not a
    # thing worth a clock of its own beside `radar_full_cycle`, which already picks its own
    # mode from the game's weekday. The ability did not move — it is one recipe
    # (`actions/do_radar_tasks.md`) and «Чеклист» has pressed it since the checklist had
    # blind rows (`panel/tabs/checklist/model.py`, «radar»), which is where it lives now.
    Timer(
        name="radar_full_cycle",
        scenario=("radar_full_cycle",),
        # Half an hour. The board drips errands all day and the run is cheap when there is
        # nothing to do — but it SPENDS SQUADS on the days it marches, so the useful period
        # is «about how long a march takes», not «as often as possible».
        interval_sec=1800,
        retry_sec=300,
        # OFF by default like the rest of this catalogue. Switched on, this is the whole
        # radar on a clock: it picks its own mode from the game's weekday, so nothing has to
        # be changed on the row from one day to the next.
        enabled=False,
        # `duel_days` is the weekdays the radar scores on, 1 = Monday … 7 = Sunday, and the
        # default is the player's own answer — Monday, Wednesday, Friday, Saturday. It lives
        # HERE and not in the recipe because the duel's plan differs by season and by
        # warzone. `force` overrides the day (1 discharge, 2 hoard) for a week that is being
        # played by hand; `keep_free` is how many places the hoard keeps open.
        args={"duel_days": [1, 3, 5, 6], "force": 0, "keep_free": 3,
              "help": 1, "march": 1},
        label_key="timers.item.radar_full_cycle",
    ),
    Timer(
        name="do_radar_marches",
        scenario=("do_radar_marches",),
        # Twenty minutes. It spends SQUADS, and a squad is out for a march's travel time —
        # so the useful period is «about how long a march takes», not «as often as
        # possible». It sends nothing when every squad is out, and says so.
        interval_sec=1200,
        retry_sec=300,
        # OFF by default, and more deliberately than the rest of this catalogue: every
        # other row here spends a quota that dies at the reset, and this one spends the
        # squads a person may be saving for a rally.
        enabled=False,
        args={"place": 1, "forget": 0},
        label_key="timers.item.do_radar_marches",
    ),
    Timer(
        name="attack_codename_daily",
        scenario=("attack_codename_daily",),
        # A DAY, because the thing being spent is a day's worth of reward and there is
        # exactly one of it. The recipe asks the server how many attacks the day still
        # owes and sends only those, so a run that finds them already made is a clean
        # no-op — but running it oftener than the reward resets would buy nothing and
        # cost a squad's march every time.
        interval_sec=86400,
        # Fifteen minutes, and this is the errand's whole design rather than a fallback.
        # A run FAILS when the day still owes attacks and one could not be made — no
        # squad standing in the base, the boss not in the list yet — and every one of
        # those mends itself in minutes, usually because the squad this errand itself
        # just sent is on its way home. The retry re-asks the count and sends only what
        # is STILL owed, so a day is finished in two or three short goes rather than
        # abandoned after the first. A day the event does not run at all is a SUCCESS,
        # not a failure, so Sunday costs one run and not ninety-six.
        retry_sec=900,
        enabled=False,
        label_key="timers.item.attack_codename_daily",
    ),
    Timer(
        name="attack_crystal_boss_daily",
        scenario=("attack_crystal_boss_daily",),
        # A DAY, for the same reason its sister errand is: the thing being spent is a
        # day's worth of reward and there is exactly one of it. The recipe asks the
        # server how many attacks the day still owes and sends only those, so a run that
        # finds them already made is a clean no-op.
        interval_sec=86400,
        # Fifteen minutes, and it is the errand's design rather than a fallback. A run
        # FAILS when the day still owes attacks and one could not be made — no squad
        # standing in the base, the boss not in the list yet — and every one of those
        # mends itself in minutes, usually because the squad this errand itself just sent
        # is on its way home. The retry re-asks the count and sends only what is STILL
        # owed. A window that is shut is a SUCCESS, so it costs one run and not ninety.
        retry_sec=900,
        enabled=False,
        label_key="timers.item.attack_crystal_boss_daily",
    ),
    Timer(
        name="arena_3v3_battles",
        scenario=("arena_3v3_battles",),
        # AN HOUR, not a day, and the reason is the retry rather than the reward: the
        # wins are a day's worth and the recipe asks the server how many are still
        # missing, so a run that finds them made is a clean no-op costing two reads.
        # An hour is what makes a day whose first attempt landed on a client that was
        # loading, or in the minutes an event window was shut, finish itself anyway.
        interval_sec=3600,
        # Fifteen minutes. A run FAILS only when a battle could not be made at all —
        # no opponent came back, the send was refused, the client stopped answering —
        # and every one of those mends itself in minutes. A spent day and a shut event
        # are a STOP, so neither costs a retry.
        retry_sec=900,
        enabled=False,
        # The day's target and the ceiling on one run. Five wins is what the game's own
        # daily reward asks for; the cap is the day's 30 challenges, and the server's
        # count is what actually stops the loop.
        args={"wins": 5, "cap": 30},
        label_key="timers.item.arena_3v3_battles",
    ),
    Timer(
        name="sweep_star_servers",
        scenario=("sweep_star_servers",),
        # FOUR HOURS, and the number is about RIPENING rather than about how long a lap
        # takes (#1479). A lap of a fresh warzone found 91 star tiles of which 86 were
        # still maturing; the robbery is «Автолут ★»'s and it happens hours later, off a
        # list this errand filled. So the useful cadence is «be back through the day»,
        # and the recipe walks a DIFFERENT handful of warzones each time — the ones it
        # walked earlier today are written down and taken out of the choice.
        interval_sec=14400,
        # Twenty minutes. A run FAILS when the client is not answering or the map would
        # not come up, and both of those mend themselves in minutes — while a spent daily
        # quota is a clean STOP rather than a failure, so a finished day costs one run
        # every four hours and not one every twenty minutes.
        retry_sec=1200,
        enabled=False,
        # 5-10 is the operator's own bound and the model enforces it; six is a lap of
        # about twenty seconds, which leaves the client free for everything else.
        args={"count": 6},
        label_key="timers.item.sweep_star_servers",
    ),
    Timer(
        name="restart_game",
        scenario=("restart_game",),
        # Six hours. Nothing in the game is spent by a restart and nothing is lost —
        # the point is the client itself, which gets slower and less answerable the
        # longer one session lasts. Four restarts a day costs four times two minutes
        # of loading and buys a client that still replies at the end of the day.
        interval_sec=21600,
        # Ten minutes after a restart that did not come back. The recipe FAILs when
        # the base never appeared or the game link would not re-attach, and either
        # of those is worth another go soon — but not every tick, because a client
        # that will not start would otherwise be killed and relaunched all night.
        retry_sec=600,
        # OFF by default, like every other errand here. This one ends the session it
        # is run in, so it is the operator's decision and not a default.
        enabled=False,
        label_key="timers.item.restart_game",
    ),
    Timer(
        name="upgrade_decorations",
        scenario=("upgrade_decorations",),
        # Four hours (#1560). A step costs one spare duplicate of the same decoration,
        # and a spare is a rare thing to be holding — nothing forces this to run any
        # oftener than the ordinary play that turns those spares up, and the scenario's
        # own gate (`upgrade_decorations.md`) reads the count before pressing anything,
        # so a tick that finds none ready costs one Lua round trip and says so with
        # numbers rather than pressing blind.
        interval_sec=14400,
        # Five minutes. A run FAILS only when the client is not answering, which mends
        # itself soon — the gate itself never fails, it STOPs cleanly with nothing to do.
        retry_sec=300,
        # OFF by default, like every other errand here.
        enabled=False,
        label_key="timers.item.upgrade_decorations",
    ),
    Timer(
        name="exchange_treasure_pieces",
        scenario=("exchange_treasure_pieces",),
        # HALF AN HOUR. The board is the alliance's, so what it holds changes when a
        # mate posts something and at no other time — there is no clock in the game to
        # follow and no reward that expires. A tick costs two asks and one local
        # decision, and the recipe presses nothing when the rule says nothing is worth
        # taking, so this is cheap enough to run often and pointless to run oftener:
        # the offer we keep standing is what actually catches the trades, and it stands
        # between ticks.
        interval_sec=1800,
        # Five minutes. A run FAILS only when the client is not answering; a board with
        # nothing on it is a clean success that says so.
        retry_sec=300,
        enabled=False,
        # NO `args` BLOCK ON PURPOSE. The rule's two knobs and the «выставлять своё» box
        # live on «Обмен кусочками», and the page hands them over live
        # (`Schedule.register_args`, `panel/tabs/secret_tasks/pieces.py`). A block here
        # would be a second copy of the rule that stops agreeing with the page the first
        # time somebody moves it.
        label_key="timers.item.exchange_treasure_pieces",
    ),
    Timer(
        name="play_frontline_breakthrough",
        scenario=("play_frontline_breakthrough",),
        # SUNDAY, and named as a weekday rather than as a period (`Timer.weekdays`).
        # «Прорыв обороны» runs for one game day a week; an errand told to repeat every
        # seven days would drift off that day by however long each run took and by
        # however long the panel was shut, and once it had drifted past a boundary it
        # would spend the rest of its life firing on a Monday, when there is no event.
        weekdays=(7,),
        # The period is what the row falls back to if its days are ever cleared, and it
        # is never consulted while they are set.
        interval_sec=7 * DAY_SEC,
        # An hour. A run FAILS when the client is not answering or the event is not open
        # for this account yet — both of which mend themselves during the day — so a
        # Sunday that starts with a dead client is retried through the day rather than
        # written off, and at most twenty-four times rather than every twenty seconds.
        retry_sec=3600,
        enabled=False,
        # THREE GAMES, and the score is not the point: what the day owes is the event's
        # own «сыграй N раз», and each stage cleared also converts the soldiers left
        # into real units. The recipe plays whatever stage the client offers next, so
        # three rounds is three games whether they are won or lost.
        args={"rounds": 3},
        label_key="timers.item.play_frontline_breakthrough",
    ),
    Timer(
        name="work_alert_tower",
        scenario=("work_alert_tower",),
        # AN HOUR, and the row rarely uses it: the training march is four hours long and
        # the recipe hands back `next_run_in` off the game's own clock — a minute after
        # the march ends, which is when there is loot and a start to spend. The hour is
        # what is left when the client would not answer at all.
        interval_sec=3600,
        retry_sec=600,
        enabled=False,
        # THE THREE PERMISSIONS the run acts under, and their one home: what it may
        # hand over, whether it may open the box, whether it may spend the day's start.
        # Drawn by the gear on this board and on «Вышка оповещения» alike
        # (`panel/runtime/errand_args.py`), stored here and nowhere else.
        args={"give_goods": 1, "start_run": 1, "take_box": 1},
        label_key="timers.item.work_alert_tower",
    ),
    Timer(
        name="perform_arms_race",
        scenario=("perform_arms_race",),
        # A PERIOD THIS ROW NEVER USES WHILE THE GAME IS ANSWERING. «Гонка вооружений»
        # changes what it pays for every four hours on a schedule the server fixed a
        # week ahead, and the recipe reads the border off the calendar and hands it back
        # as `next_run_in` — so the turn is booked ON the border rather than ground out
        # against a clock that knows nothing about phases. Four hours is what is left if
        # the client would not answer at all, which is the phase length itself: a row
        # that has lost the calendar should look again no oftener than the event moves.
        interval_sec=4 * 3600,
        # Ten minutes. A failed run means the client was not there or the account has
        # not unlocked the event; both mend themselves, and a phase is four hours long,
        # so there is time to come back a few times without hammering anything.
        retry_sec=600,
        enabled=False,
        # WHETHER THE HERO PHASE MAY HIRE, and nothing else — how MANY hires is the
        # recipe's own `ARGS pulls` and this row holds no second opinion about it. The
        # four phases that spend speed-ups, drone data or troops are not automated at
        # all yet, so there is no knob here for them: a switch over a thing that cannot
        # happen is a switch that lies.
        args={"hero": 1},
        label_key="timers.item.perform_arms_race",
    ),
    Timer(
        name="open_explorer_chests",
        scenario=("open_explorer_chests",),
        # SIX HOURS, AND IT IS THE SAFETY NET RATHER THAN THE SCHEDULE (#2381). The keys
        # that open these chests are paid out by our OWN finished secret tasks and by
        # nothing else, so the purse cannot grow while nobody claims a task — which is
        # why the errand's real wake-up is the `explorer_chests` trigger on the claim's
        # own answer. This period is for the case that trigger cannot cover: a profile
        # that ran with the listener off, or claims that were made from the phone with
        # nothing listening. A run with no keys stops in one round trip and costs a
        # sentence in the log.
        interval_sec=6 * 3600,
        # A failure here is a client that was not answering; a few minutes is soon
        # enough for chests that nothing is counting down.
        retry_sec=300,
        enabled=False,
        # `keep` is how many keys are never spent (0 spends the purse), `max` how many
        # chests one run may open (0 = every one the keys buy). Both are the recipe's
        # own ARGS, and the gear on «Таймеры» edits exactly these.
        args={"keep": 0, "max": 0},
        label_key="timers.item.open_explorer_chests",
    ),
)


#: Errands that were ONE row and are now several — the old name mapped to the names it
#: became. Retired here rather than merely deleted, because a name has three lives: the
#: profile files that still list it, the local template that still offers it, and the
#: "already shown to this profile" record that must keep it from coming back. What is
#: done about each is in :func:`split_legacy_errands` and :func:`offered_catalogue`.
#:
#: `alliance_upkeep` was "donate, then claim the gifts" on a single switch and therefore
#: a single period — and the two halves do not want the same one. The donation attempts
#: bank up every 20 minutes and are lost at the end of the day if they are not spent,
#: while the gift chest keeps for hours; one clock could only ever be right for one of
#: them, and the hour it was set to was right for neither.
SPLIT_ERRANDS: dict[str, tuple[str, ...]] = {
    "alliance_upkeep": ("donate_alliance_tech", "collect_alliance_gifts"),
}

#: Errands this version no longer SCHEDULES at all — the old name, mapped to the
#: standing order that does the job now (or to an empty string when nothing replaced
#: it). A row here is deleted from a profile's file on the next start, and its switch
#: is carried over to the successor: an errand that was running goes on running, off
#: the listener instead of off a clock.
#:
#: `auto_treasure` is the first (#1886). Walking the map every five minutes for a chest
#: was measured twice at 19 and 21 chests found with OURS ZERO both times, and the row
#: spent its days reporting «нечего отправлять» — while the same recipe run by the
#: `treasure_auto` listener hears a chest in the second the client hears it. Two ways of
#: playing one recipe is two runs over one queue, and the clock was the worse of them.
RETIRED_ERRANDS: dict[str, str] = {
    "auto_treasure": "treasure_auto",
    # …and `do_radar_tasks` is the first with NOTHING to carry its switch to (#2061).
    # The person asked for the row to go — «из таймеров убери таймер выполнить задания
    # радара, который просто полностью собирает задания, перенеси в чеклист» — and there
    # is no listener that does the job instead: it is a press on «Чеклист», which is
    # where it has been all along (`panel/tabs/checklist/model.py`, «radar»). Removing it
    # from `DEFAULT_TIMERS` alone would have left it in every profile that ever ran,
    # because a profile's list is its own and outlives the built-ins (#2017) — the row
    # went on firing on this machine after the code was already without it.
    "do_radar_tasks": "",
}


#: What a retired errand used to run. An entry in a profile's file may leave the scenario
#: out and lean on the built-in of the same name (:func:`parse_catalogue`) — and a
#: retired name has no built-in any more, so without this the row would be dropped as
#: "nothing to run" and the operator's switch would go with it, before anything had the
#: chance to split it.
RETIRED_SCENARIOS: dict[str, tuple[str, ...]] = {
    "alliance_upkeep": ("donate_alliance_tech", "collect_alliance_gifts"),
    "do_radar_tasks": ("do_radar_tasks",),
}


def _as_scenario(raw) -> tuple[str, ...]:
    """Coerce a ``scenario`` field into a tuple of steps."""
    if isinstance(raw, str):
        steps = [raw]
    elif isinstance(raw, (list, tuple)):
        steps = [str(step) for step in raw]
    else:
        return ()
    return tuple(step for step in (s.strip() for s in steps) if step)


def _day_anchor(rec: dict) -> float:
    """The moment a run BEGAN, which is the one its next turn is measured from.

    ``last_run`` is when the run FINISHED, and for a plain period that is the honest
    anchor. For a daily one it is not: an errand that starts at 23:59:40 and takes forty
    seconds finishes on the far side of the reset, and anchoring on the finish would say
    «this run belongs to the new day» about a run that spent the OLD day's quota. The new
    day's would then sit untouched for twenty-four hours — the exact loss this whole
    change exists to stop, reintroduced by a rounding of one minute.

    So a run writes down when it began (:meth:`LastRunStore.mark_run`) and this reads it,
    falling back to ``last_run`` for the records written before it did — an old file
    schedules exactly as it always has and is corrected by its next run.
    """
    began = float(rec.get("began_at") or 0.0)
    last = float(rec.get("last_run") or 0.0)
    if began and (not last or began <= last):
        return began
    return last


def is_daily(period_sec: int) -> bool:
    """Is this period «раз в сутки» — a whole number of days, and so reset-anchored?

    Whole days only. 36 hours is a period somebody typed and not a daily errand, and
    rounding it to one would move a fire by up to a day in the name of a rule it was
    never asking for.
    """
    period = int(period_sec)
    return period >= DAY_SEC and period % DAY_SEC == 0


def next_after(last: float, period_sec: int, day=None) -> float:
    """When an errand that last ran at ``last`` is due again, in local ``time.time()``.

    Not daily, or no day boundary to anchor to: the period, exactly as before.

    Daily: the first SERVER midnight strictly after ``last``, plus the extra whole days
    a longer period asks for. **Strictly** after is the edge the whole thing turns on —
    a run that finished at the reset instant belongs to the day that has just started, so
    its next turn is tomorrow's boundary and not the one it is standing on. With «at or
    after» the errand would be due the moment it finished, and every tick for ever.

    A boundary in the PAST is the ordinary answer for a panel that slept through one, and
    it makes the errand due now — **once**. There is no salvo of missed days: the record
    that follows the run moves ``last`` to now, and the next boundary after now is
    tomorrow's. Three days asleep costs one run, not three.

    ``day`` is this profile's :class:`panel.runtime.day_reset.DayReset` (or anything with
    the same one method). ``None`` — a test, a scheduler built without a runtime — falls
    back to the plain period rather than to a boundary nobody could name.
    """
    period = int(period_sec)
    if day is None or not is_daily(period):
        return last + period
    try:
        first = float(day.next_reset_epoch(last))
    except Exception:                        # noqa: BLE001 — never the schedule
        return last + period
    return first + (period // DAY_SEC - 1) * DAY_SEC


def _as_weekdays(raw, fallback=()) -> tuple:
    """Coerce a ``weekdays`` field into a sorted tuple of 1…7. Junk falls back.

    Accepts what a file, a dialog and a JSON body each naturally hold: a list of
    numbers, a single number, or the text a person types into a field —
    ``"7"``, ``"1,3"``, ``"1 3 5"``. An empty value is «any day», which is what
    every errand that is not weekly answers.
    """
    if raw is None:
        return tuple(fallback)
    if isinstance(raw, str):
        parts = [p for p in raw.replace(",", " ").split() if p]
    elif isinstance(raw, (list, tuple, set)):
        parts = list(raw)
    else:
        parts = [raw]
    days = set()
    for part in parts:
        try:
            day = int(float(str(part).strip()))
        except (TypeError, ValueError):
            continue
        if 1 <= day <= 7:
            days.add(day)
    return tuple(sorted(days))


def _weekday_of(day, when: float) -> int:
    """Which weekday the GAME is on at ``when`` — 1 = Monday … 7 = Sunday.

    ``day`` is the profile's :class:`panel.runtime.day_reset.DayReset`. A test — or a
    scheduler built without a runtime — has none, and then the machine's own UTC day is
    the honest fallback: it is wrong by at most the boundary's phase, where refusing to
    answer would stop the errand firing at all.
    """
    if day is not None:
        try:
            return int(day.weekday(when))
        except Exception:                    # noqa: BLE001 — never the schedule
            pass
    return time.gmtime(when).tm_wday + 1


def _day_start(day, when: float) -> float:
    """When the GAME day containing ``when`` began, in local seconds."""
    if day is not None:
        try:
            return float(day.day_start_epoch(when))
        except Exception:                    # noqa: BLE001
            pass
    return when - (when % DAY_SEC)


def next_weekly(last: float, weekdays, day, now: float) -> float:
    """When a weekday-bound errand is due, in local ``time.time()`` seconds.

    The rule is one sentence: **the errand is due at the start of a matching GAME day
    it has not yet run in.** Nothing about the last run's clock time enters into it, so
    a run that takes an hour, a panel shut for a fortnight and a client that was down
    all morning all produce the same answer — today, if today is one of its days and it
    has not run since the day began; otherwise the start of the next matching day.

    A day-start in the PAST is how «due now» is said, exactly as :func:`next_after` says
    it, and it is due once: the record written by the run moves ``last`` past the day's
    start and the next answer is next week's. Three missed Sundays cost one run.
    """
    weekdays = tuple(weekdays)
    if not weekdays:
        return now
    start = _day_start(day, now)
    if _weekday_of(day, now) in weekdays and float(last) < start:
        return start
    step = start
    for _ in range(7):
        step += DAY_SEC
        if _weekday_of(day, step) in weekdays:
            return step
    return start + 7 * DAY_SEC


def _as_interval(raw, fallback: int) -> int:
    try:
        value = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return fallback
    return max(MIN_INTERVAL_SEC, min(MAX_INTERVAL_SEC, value))


def with_fields(base: Timer, *, name=None, title=None, interval=None, retry=None,
                scenario=None, args=None, enabled=None, immediate=None,
                weekdays=None) -> Timer:
    """One entry with some of its fields replaced — an editor's Save, with no display.

    The window's dialog and the phone's editor (#1976) both land here, so a field one
    of them forgets is not a field the other silently defaults away: what is not named
    keeps ``base``'s value, and everything that arrives as TEXT — a period typed into a
    box, ``"1,3"`` for the days, the steps one per line — is coerced by the same readers
    the file itself goes through.
    """
    fresh = base.name if name is None else str(name).strip()
    return Timer(
        name=fresh,
        scenario=(tuple(base.scenario) if scenario is None else _as_scenario(scenario)),
        interval_sec=(base.interval_sec if interval is None
                      else _as_interval(interval, base.interval_sec)),
        retry_sec=(base.retry_sec if retry is None
                   else _as_interval(retry, base.retry_sec)),
        enabled=(base.enabled if enabled is None else bool(enabled)),
        immediate=(base.immediate if immediate is None else bool(immediate)),
        weekdays=(tuple(base.weekdays) if weekdays is None else _as_weekdays(weekdays)),
        args=(dict(base.args) if args is None else dict(args)),
        title=(base.title if title is None else (str(title).strip() or None)),
        # The locale key belongs to the BUILT-IN entry of that name; a renamed row is no
        # longer that entry, and keeping it would show a translated label over the wrong
        # errand.
        label_key=(base.label_key if fresh == base.name else None))


class Catalogue:
    """The configured list of timers, plus whatever was wrong with the file.

    ``errors`` is not an exception on purpose: a typo in one entry must cost that
    entry, not the whole schedule, and the panel prints the complaints into its
    log where the person who typed them will see them.
    """

    def __init__(self, timers, path: str | None = None, errors=()) -> None:
        self.timers: tuple[Timer, ...] = tuple(timers)
        self.path = path
        self.errors: tuple[str, ...] = tuple(errors)
        # Errands that were dropped from this profile's file as RETIRED, and were
        # switched ON when they went (:func:`retire_errands`). Filled by
        # :func:`load_profile_catalogue`; the caller turns the successor listener on.
        self.retired_on: tuple[str, ...] = ()
        self._by_name = {timer.name: timer for timer in self.timers}

    # -- lookup -------------------------------------------------------------
    def __iter__(self):
        return iter(self.timers)

    def __len__(self) -> int:
        return len(self.timers)

    def by_name(self, name: str) -> Timer | None:
        return self._by_name.get(name)

    def names(self) -> list[str]:
        return [timer.name for timer in self.timers]

    # -- settings -----------------------------------------------------------
    def default_config(self) -> dict:
        """Each timer's switch and period as the catalogue asks for them.

        The panel's saved settings override this per profile; a timer the file
        marks ``"enabled": true`` therefore starts on for a profile that has
        never seen it, and stays as the operator left it afterwards.
        """
        return {timer.name: {"enabled": timer.enabled,
                             "interval_sec": timer.interval_sec,
                             "immediate": timer.immediate}
                for timer in self.timers}

    def normalize_config(self, raw) -> dict:
        """Coerce stored/typed settings into ``{name: {enabled, interval_sec}}``.

        The panel's spinboxes hand over strings, a profile saved before a timer
        existed has no entry for it, and one saved after a timer was deleted has
        an entry for nothing — so every value is re-derived here against the
        current catalogue rather than trusted. An unreadable period falls back to
        the configured one instead of dropping the row: a mistyped number must
        not silently disable a timer the operator believes is on.
        """
        raw = raw if isinstance(raw, dict) else {}
        out = self.default_config()
        for timer in self.timers:
            item = raw.get(timer.name)
            if not isinstance(item, dict):
                continue
            out[timer.name]["enabled"] = bool(item.get("enabled", timer.enabled))
            out[timer.name]["interval_sec"] = _as_interval(
                item.get("interval_sec", timer.interval_sec), timer.interval_sec)
            out[timer.name]["immediate"] = bool(
                item.get("immediate", timer.immediate))
        return out

    def with_settings(self, config: dict) -> "Catalogue":
        """A copy carrying the panel's switches and periods, ready to be saved.

        Only the row's own three — the switch, the period and «сразу» — move. The
        scenario, the args and the title are the operator's text: the Timers tab edits
        them through :meth:`replace`, which writes a whole entry deliberately, while a
        ticked box or a retyped period goes through here and must not be able to touch
        anything else on the row.
        """
        config = self.normalize_config(config)
        updated = []
        for timer in self.timers:
            item = config[timer.name]
            updated.append(Timer(
                name=timer.name, scenario=timer.scenario,
                interval_sec=int(item["interval_sec"]),
                retry_sec=timer.retry_sec,
                enabled=bool(item["enabled"]),
                immediate=bool(item["immediate"]),
                weekdays=tuple(timer.weekdays),
                args=dict(timer.args), title=timer.title,
                label_key=timer.label_key))
        return Catalogue(updated, self.path, self.errors)

    # -- editing (the Timers tab's Add / Duplicate / Delete / Edit) ----------
    #
    # Every one returns a NEW catalogue rather than mutating this one: the
    # scheduler thread reads `catalogue()` on its own clock, and swapping the
    # object it will read next is atomic where editing the list under it is not.
    def replace(self, timer: Timer) -> "Catalogue":
        """This catalogue with ``timer`` in place of the entry of the same name.

        An unknown name is appended, so "save what the dialog holds" is one call
        whether the dialog was opened on an existing row or on a new one.
        """
        out, replaced = [], False
        for existing in self.timers:
            if existing.name == timer.name:
                out.append(timer)
                replaced = True
            else:
                out.append(existing)
        if not replaced:
            out.append(timer)
        return Catalogue(out, self.path, self.errors)

    def remove(self, name: str) -> "Catalogue":
        """This catalogue without the named entry (a no-op if it is not in it)."""
        return Catalogue([t for t in self.timers if t.name != name],
                         self.path, self.errors)

    def unique_name(self, base: str) -> str:
        """``base``, or ``base_2`` / ``base_3`` … — the first one not taken.

        What Duplicate needs: the name is the id the schedule keys its clock on,
        so a copy must not answer to the original's record.
        """
        base = (base or "timer").strip() or "timer"
        if base not in self._by_name:
            return base
        n = 2
        while f"{base}_{n}" in self._by_name:
            n += 1
        return f"{base}_{n}"

    # -- the decision -------------------------------------------------------
    def due_names(self, config: dict, records: dict, now: float,
                  day=None) -> list[str]:
        """Which enabled timers are due at ``now``, the most overdue first.

        ``records`` is the last-run store's raw mapping (see
        :class:`LastRunStore`). A timer with no record has never run and is due
        immediately; one whose last attempt failed is held for
        :data:`RETRY_HOLD_SEC` before being offered again.

        ``day`` is the profile's server-day boundary, and a period of a whole number of
        days is anchored to it rather than counted off from the last run
        (:func:`next_after`).
        """
        out = []
        for timer in self.timers:
            item = config.get(timer.name) or {}
            if not item.get("enabled"):
                continue
            rec = records.get(timer.name) or {}
            # An attempt that is STILL OPEN counts as the last attempt. Without this a
            # long run — `restart_game` waits for a client to come up — stays overdue
            # for its whole length, so every tick offers it again and the queue fills
            # with copies of the errand that is already running (#1281).
            failed_at = max(float(rec.get("failed_at") or 0.0),
                            float(rec.get("started_at") or 0.0))
            if failed_at and now - failed_at < timer.retry_sec:
                continue
            last = _day_anchor(rec)
            due_at = float(rec.get("due_at") or 0.0)
            if due_at:
                # THE GAME NAMED THIS TURN (:data:`NEXT_RUN_VAR`), and it wins over the
                # row's period — which is only ever a guess at the same question.
                overdue = now - due_at
            elif timer.weekdays:
                # A NAMED WEEKDAY IS NOT A PERIOD (`Timer.weekdays`): the row is due at
                # the start of a matching game day it has not run in, and never on any
                # other day, whatever its period says.
                overdue = now - next_weekly(last, timer.weekdays, day, now)
            else:
                period = _as_interval(item.get("interval_sec"), timer.interval_sec)
                overdue = now - next_after(last, period, day)
            if overdue >= 0:
                out.append((overdue, timer.name))
        out.sort(key=lambda pair: pair[0], reverse=True)
        return [name for _overdue, name in out]

    def next_due(self, timer: Timer, config: dict, records: dict,
                 day=None) -> float | None:
        """Wall clock the timer fires at, ``0.0`` for "now" and ``None`` when off.

        The retry hold counts. A failed attempt leaves ``last_run`` where it was, so
        without it the row would say «сейчас» for the whole half hour the scheduler is
        deliberately sitting out — the display disagreeing with the schedule exactly in
        the case a retry hold exists for. Whichever of the two waits ends later wins.
        """
        item = config.get(timer.name) or {}
        if not item.get("enabled"):
            return None
        rec = records.get(timer.name) or {}
        last = _day_anchor(rec)
        failed_at = max(float(rec.get("failed_at") or 0.0),
                        float(rec.get("started_at") or 0.0))
        after_failure = failed_at + timer.retry_sec if failed_at else 0.0
        due_at = float(rec.get("due_at") or 0.0)
        if due_at:
            # The row shows the appointment the GAME made, for the same reason the
            # scheduler keeps it: a countdown to an hour from now over a free pull that
            # is four hours away is the display disagreeing with the schedule.
            return max(due_at, after_failure)
        if timer.weekdays:
            # Asked the same way the scheduler asks it, so the countdown a person reads
            # is the moment the row will actually fire on — including «never ran», which
            # for a weekly errand is «its next day», not «now».
            return max(next_weekly(last, timer.weekdays, day, time.time()),
                       after_failure)
        if not last:
            return max(0.0, after_failure)
        return max(next_after(last, _as_interval(item.get("interval_sec"),
                                                 timer.interval_sec), day),
                   after_failure)


# How the last attempt ended — what the Timers tab's status column says. The three
# states live here rather than in the panel because telling them apart is a decision
# about the record, not a paint job: a run that FAILED and one that has never happened
# both leave `last_run` at zero, and a row that showed them the same way would hide a
# timer that has been trying and getting nowhere for hours.
ATTEMPT_NONE = "none"        # never tried (or the record was lost)
ATTEMPT_OK = "ok"            # the last attempt finished clean
ATTEMPT_FAILED = "failed"    # the last attempt failed and is waiting out its retry


def last_attempt(records: dict, name: str) -> tuple[str, float]:
    """How ``name`` last ended, and when: ``(state, when)``.

    The later of the two timestamps wins, which is what makes this readable at all: a
    success clears the failure mark (:meth:`LastRunStore.mark_run`), and a failure
    leaves ``last_run`` alone, so "failed at 12:30 having last succeeded at 09:00" is
    the normal shape of a timer that is stuck — and the one worth showing.
    """
    rec = records.get(name) or {}
    last = float(rec.get("last_run") or 0.0)
    failed_at = float(rec.get("failed_at") or 0.0)
    if failed_at > last:
        return ATTEMPT_FAILED, failed_at
    if last:
        return ATTEMPT_OK, last
    return ATTEMPT_NONE, 0.0


def default_catalogue() -> Catalogue:
    """The hardcoded fallback, as a catalogue."""
    return Catalogue(DEFAULT_TIMERS)


def parse_catalogue(data, path: str | None = None,
                    fallback: "Catalogue | None" = None) -> Catalogue:
    """Build a catalogue from already-decoded JSON.

    Accepts either a bare list of entries or ``{"timers": [...]}``. The FILE owns
    the list — a timer deleted from it is gone — while each entry falls back
    field by field to the one of the same name in ``fallback`` (the template, and
    behind it the built-ins), so an entry may be as short as
    ``{"name": "collect_base_resources", "interval_sec": 1800}``.
    """
    fallback_timers = fallback.timers if fallback is not None else DEFAULT_TIMERS
    if isinstance(data, dict):
        data = data.get("timers")
    if not isinstance(data, list):
        return Catalogue(fallback_timers, path,
                         [Message("log.timers.not_a_list",
                                   "config is not a list of timers — using the defaults")])

    builtin = {timer.name: timer for timer in DEFAULT_TIMERS}
    builtin.update({timer.name: timer for timer in fallback_timers})
    timers, errors, seen = [], [], set()
    for index, raw in enumerate(data):
        if not isinstance(raw, dict):
            errors.append(Message("log.timers.not_an_object",
                                  f"entry #{index + 1} is not an object — skipped",
                                  n=index + 1))
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            errors.append(Message("log.timers.no_name",
                                  f"entry #{index + 1} has no name — skipped",
                                  n=index + 1))
            continue
        if name in seen:
            errors.append(Message("log.timers.twice",
                                  f"{name}: listed twice — the later entry is ignored",
                                  name=name))
            continue
        base = builtin.get(name)
        scenario = _as_scenario(raw.get("scenario"))
        if not scenario:
            scenario = base.scenario if base else RETIRED_SCENARIOS.get(name, ())
        if not scenario:
            errors.append(Message("log.timers.no_scenario",
                                  f"{name}: no scenario to run — skipped", name=name))
            continue
        # AN ARGUMENT THE ROW DOES NOT MENTION FALLS BACK TO THE BUILT-IN'S, exactly as
        # the period, the retry and the switch above it already do (#2022). It has to:
        # a row saved before an argument existed carries none of it, the recipe would
        # run on its own `ARGS` default — and the gear on «Таймеры» would draw a blank,
        # which for a switch reads as OFF. A knob showing «off» over a rule that is on
        # is worse than no knob at all. Whatever the row DOES say still wins, so a flag
        # somebody deliberately turned off stays off.
        args = raw.get("args")
        if base is not None and base.args:
            merged = dict(base.args)
            if isinstance(args, dict):
                merged.update(args)
            args = merged
        timers.append(Timer(
            name=name,
            scenario=scenario,
            interval_sec=_as_interval(
                raw.get("interval_sec"),
                base.interval_sec if base else DEFAULT_INTERVAL_SEC),
            retry_sec=_as_interval(
                raw.get("retry_sec"),
                base.retry_sec if base else int(RETRY_HOLD_SEC)),
            enabled=bool(raw.get("enabled", base.enabled if base else False)),
            immediate=bool(raw.get("immediate",
                                   base.immediate if base else False)),
            weekdays=_as_weekdays(raw.get("weekdays"),
                                  base.weekdays if base else ()),
            args=dict(args) if isinstance(args, dict) else {},
            title=(str(raw["title"]).strip() or None) if raw.get("title") else None,
            label_key=base.label_key if base else None,
        ))
        seen.add(name)

    if not timers:
        # An empty list is a legitimate answer — "this account schedules nothing"
        # — but a file whose every entry was junk is not, and falling back is the
        # kinder reading of it. The complaints above say which it was.
        if not errors:
            return Catalogue((), path)
        errors.append(Message("log.timers.none_usable",
                              "no usable timers in the config — using the defaults"))
        return Catalogue(fallback_timers, path, errors)
    return Catalogue(timers, path, errors)


def load_catalogue(path: str, seed_from=None) -> Catalogue:
    """Read a catalogue file, falling back to ``seed_from`` / the built-in list.

    A file that does not exist yet is *written* from the seed, so there is always
    something on disk to edit — which is the whole point: a new timer must be a
    new entry in a file, not a code change. A file that exists but cannot be read
    is NOT overwritten: the panel runs on the fallback and says so, leaving
    whatever the operator typed there for them to fix.
    """
    seed = seed_from if seed_from is not None else Catalogue(DEFAULT_TIMERS)
    # THE PROFILE'S OWN LIST IS IN ITS DATABASE (#2017) — carried across from the file
    # the first time it is read. A path in the source tree is a shipped TEMPLATE and
    # stays a file: it is code, and code does not live in an account's data.
    data = settings_files.read(path)
    if data is None:
        if not os.path.exists(path):
            fresh = Catalogue(seed.timers, path)
            save_catalogue(fresh, path)
            return fresh
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            return Catalogue(seed.timers, path, [f"{os.path.basename(path)}: {exc}"])
    return parse_catalogue(data, path, fallback=seed)


def load_template() -> Catalogue:
    """The template new profiles are seeded from (``panel/timers.json``)."""
    return load_catalogue(TEMPLATE_FILE)


#: Beside a profile's catalogue: every errand name this profile has ever been offered.
#: See :func:`adopt_new_errands` for why one file is not enough.
SEEN_SUFFIX = "_seen.json"


def seen_path(catalogue_path: str) -> str:
    """Where the record of "already offered to this profile" lives."""
    base, _ext = os.path.splitext(catalogue_path)
    return base + SEEN_SUFFIX


def _read_seen(path: str) -> "set[str] | None":
    """The names this profile has been offered, or ``None`` if never recorded."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return {str(name) for name in data} if isinstance(data, list) else None


def offered_catalogue(template: "Catalogue | None" = None) -> Catalogue:
    """Everything this version has to offer a profile: the template, plus the built-ins.

    The template is a local file and is not shipped (it is written once, on the first
    run, and an operator may edit it), so an installation updated today has last
    month's template on disk. The built-in list below is what actually ships, which
    makes the union — the template first, since it is the one that was edited on
    purpose — the honest answer to "what should a profile be offered".

    A RETIRED name (:data:`SPLIT_ERRANDS`) is dropped from the template's half of that
    union: last month's template still lists it, and a profile created today must not be
    seeded with an errand this version has already replaced.
    """
    template = load_template() if template is None else template
    names = set(template.names())
    offered = [t for t in template.timers
               if t.name not in SPLIT_ERRANDS and t.name not in RETIRED_ERRANDS]
    offered += [t for t in DEFAULT_TIMERS if t.name not in names]
    return Catalogue(offered, template.path, template.errors)


def adopt_new_errands(catalogue: Catalogue, offered: Catalogue,
                      path: str) -> Catalogue:
    """Add errands this version offers that the profile has never been shown.

    A profile's file is written once, from the template, and is its own from then on
    — which is right for what it holds, and wrong for what it does not: a NEW ability
    shipped as a built-in errand would never reach an account that already had a
    file. "New timer, so open a JSON and copy the entry across" is not a feature.

    Copying the whole template over the file is not the answer either: the file owns
    the list on purpose (:func:`parse_catalogue`), and a deleted errand must stay
    deleted. So a second, tiny file remembers every name this profile has ever been
    OFFERED, and only names in neither are adopted — once. Delete a built-in
    afterwards and it stays gone, because it is in the record.

    The first run after this existed has no record; the profile's current names are
    taken as the record then, so an errand that shipped today is adopted and one the
    operator deleted long ago comes back that one time.

    Adopted entries arrive exactly as they are offered, which for every built-in means
    switched off: nothing starts pressing because the bot was updated.
    """
    record = seen_path(path)
    stored = _read_seen(record)
    first_time = stored is None
    known = set(catalogue.names())
    seen = set(known) if first_time else set(stored)
    fresh = [timer for timer in offered.timers
             if timer.name not in known and timer.name not in seen]
    if fresh:
        catalogue = Catalogue(list(catalogue.timers) + fresh,
                              catalogue.path or path, catalogue.errors)
        save_catalogue(catalogue, path)
    wanted = known | seen | set(offered.names())
    if first_time or wanted != seen:
        _write_json(record, sorted(wanted))
    return catalogue


#: Errands whose built-in RETRY HOLD this version corrects, mapped to the value the old
#: built-in had. A profile's row is saved with every field it was built from (#2017), so
#: an edit to :data:`DEFAULT_TIMERS` alone reaches only accounts that have never run —
#: on every account that has, the number the code now says is not the number that fires.
#:
#: `secret_tasks_day` is the first, and it is the whole of #2073's fourth defect: the
#: retry hold is the ONE thing that outranks the appointment the game named
#: (:meth:`Catalogue.due_names` sits it out before it ever looks at `due_at`), so half an
#: hour of it was half an hour of a finished task standing on the map to be robbed. The
#: built-in went 1800 -> 300 and four live profiles went on holding for 1800.
#:
#: A row is corrected only when it still carries EXACTLY the old built-in — a number
#: somebody typed themselves is theirs, and is left alone.
CORRECTED_RETRIES: dict[str, int] = {
    "secret_tasks_day": 1800,
}


def correct_stale_retries(catalogue: Catalogue, path: str) -> Catalogue:
    """Bring a stored row's retry hold up to the corrected built-in (:data:`CORRECTED_RETRIES`).

    The profile's list owns itself and nothing else may rewrite it — the same exception
    the split and the retirement have, for the same reason: a retry hold copied out of a
    built-in that has since been found wrong is not a decision the operator made, it is
    a defect saved into every account before it was found.
    """
    builtin = {timer.name: timer for timer in DEFAULT_TIMERS}
    out: list[Timer] = []
    changed = False
    for timer in catalogue.timers:
        was = CORRECTED_RETRIES.get(timer.name)
        base = builtin.get(timer.name)
        if (was is None or base is None
                or timer.retry_sec != was or base.retry_sec == was):
            out.append(timer)
            continue
        out.append(_replace(timer, retry_sec=base.retry_sec))
        changed = True
    if not changed:
        return catalogue
    fresh = Catalogue(out, catalogue.path or path, catalogue.errors)
    save_catalogue(fresh, path)
    return fresh


def retire_errands(catalogue: Catalogue,
                   path: str) -> "tuple[Catalogue, tuple[str, ...]]":
    """Delete an errand this version no longer schedules; say which of them were ON.

    The profile's file owns its list (:func:`parse_catalogue`) and nothing else may
    rewrite it — with the same exception the split has: a row this version has RETIRED
    is not a row the operator chose to keep, it is one the panel no longer knows how to
    run on a clock. Left alone it would go on firing for ever, because its scenario is
    still there to play: `auto_treasure` names a recipe that exists and runs perfectly
    well — off the wrong door.

    So the row goes, the file is rewritten without it, and the name is written into the
    "already offered" record so a stale local template cannot hand it back on the next
    launch. What comes back is the catalogue and the names that were **switched on** when
    they were dropped: the caller turns the successor listener on for exactly those, so a
    profile that had the errand running keeps having it done.
    """
    stale = [t for t in catalogue.timers if t.name in RETIRED_ERRANDS]
    if not stale:
        return catalogue, ()
    kept = [t for t in catalogue.timers if t.name not in RETIRED_ERRANDS]
    was_on = tuple(t.name for t in stale if t.enabled)
    fresh = Catalogue(kept, catalogue.path or path, catalogue.errors)
    save_catalogue(fresh, path)

    record = seen_path(path)
    stored = _read_seen(record)
    if stored is None:
        # No record yet, and :func:`adopt_new_errands` is about to take the profile's
        # list as one — a list that no longer holds the retired name. Write it here from
        # the list as it was, exactly as the split does, so the retirement cannot undo
        # itself on the next launch.
        stored = set(catalogue.names())
    _write_json(record, sorted(stored | {t.name for t in stale}))
    return fresh, was_on


def split_legacy_errands(catalogue: Catalogue, offered: Catalogue,
                         path: str) -> Catalogue:
    """Replace a retired errand with the rows it became, keeping its switch.

    The profile's file owns its list (:func:`parse_catalogue`) and nothing else may
    rewrite it — which is right for everything except this: an errand that was SPLIT is
    not a row the operator chose to keep, it is one this version no longer knows how to
    run on a single clock. Left alone, an account that had `alliance_upkeep` switched on
    would go on donating once an hour for ever while the panel showed it two new rows,
    switched off, doing the same work on the right periods.

    So the old row is taken out and the ones it became are put IN ITS PLACE, each with
    its own built-in period and **the switch the operator had set** — an errand that was
    running keeps running, one that was off stays off. Nothing is invented: if the
    profile already has one of the new rows (adopted, or typed by hand) that one is left
    exactly as it is.

    The retired name also goes into the "already shown" record, so a stale local template
    that still offers it cannot hand it back on the next launch.
    """
    stale = [t for t in catalogue.timers if t.name in SPLIT_ERRANDS]
    if not stale:
        return catalogue
    builtin = {timer.name: timer for timer in DEFAULT_TIMERS}
    before = set(catalogue.names())
    out: list[Timer] = []
    for timer in catalogue.timers:
        parts = SPLIT_ERRANDS.get(timer.name)
        if parts is None:
            out.append(timer)
            continue
        for part in parts:
            base = offered.by_name(part) or builtin.get(part)
            if base is None or any(t.name == part for t in out) or part in before:
                continue
            out.append(Timer(
                name=base.name, scenario=base.scenario,
                interval_sec=base.interval_sec, retry_sec=base.retry_sec,
                weekdays=tuple(base.weekdays),
                # The one thing carried across the split: the operator's decision.
                enabled=timer.enabled,
                args=dict(base.args), title=base.title, label_key=base.label_key))
    fresh = Catalogue(out, catalogue.path or path, catalogue.errors)
    save_catalogue(fresh, path)

    record = seen_path(path)
    stored = _read_seen(record)
    if stored is None:
        # No record yet, and :func:`adopt_new_errands` is about to take the profile's
        # list as one. Its list no longer holds the retired name, so write the record
        # HERE from the list as it was — otherwise a stale template would offer the old
        # errand straight back, and the split would undo itself on every launch. What
        # goes in is exactly what that first-time branch would have written.
        stored = before | set(offered.names())
    _write_json(record, sorted(stored | before | {t.name for t in out}))
    return fresh


def load_profile_catalogue(path: str) -> Catalogue:
    """The catalogue a profile runs, seeded from the template when it has none.

    A file that did not exist is written from the template; one that did keeps every
    word of what is in it, gains the errands this version has learnt since
    (:func:`adopt_new_errands`), has any errand this version has SPLIT replaced by
    the rows it became (:func:`split_legacy_errands`), and loses any errand this version
    has RETIRED (:func:`retire_errands`) — with the names that were switched on when they
    went left on ``catalogue.retired_on`` for the caller to act on. A retry hold this
    version has CORRECTED is brought up to the built-in's
    (:func:`correct_stale_retries`), because a row saved with the old one goes on
    holding for it for ever.
    """
    template = load_template()
    offered = offered_catalogue(template)
    # «Fresh» is now «nothing has ever been saved», in the database OR in a file
    # that has not been carried across yet (#2017).
    fresh_profile = not settings_files.exists(path)
    catalogue = load_catalogue(path, seed_from=offered)
    if fresh_profile:
        # It IS everything on offer, so all of it counts as offered — otherwise a row
        # deleted tomorrow would be re-adopted the day after as "new".
        _write_json(seen_path(path),
                    sorted(set(offered.names()) | set(catalogue.names())))
        return catalogue
    if not _readable(path):
        # Unreadable: what came back is the FALLBACK, not this profile's list. Deciding
        # what it is missing from that would write our guess over the operator's file.
        return catalogue
    # The retirement and the split run FIRST: they are the ones that have to see the
    # file as it was written, and they settle the "already shown" record the adoption
    # below reads.
    catalogue, retired_on = retire_errands(catalogue, path)
    catalogue = split_legacy_errands(catalogue, offered, path)
    catalogue = correct_stale_retries(catalogue, path)
    catalogue = adopt_new_errands(catalogue, offered, path)
    catalogue.retired_on = retired_on
    return catalogue


def _readable(path: str) -> bool:
    """Did this profile's own list come back — rather than the fallback?

    In the database since #2017, with the file as the thing it was imported from; a
    store nobody could read answers `None` and the caller keeps the seed rather than
    writing our guess over the operator's list.
    """
    if settings_files.read(path) is not None:
        return True
    try:
        with open(path, encoding="utf-8") as fh:
            json.load(fh)
    except (OSError, ValueError):
        return False
    return True


def save_catalogue(catalogue: Catalogue, path: str | None = None) -> None:
    """Write a catalogue back out — into the profile's database, or a template file.

    A profile's list is a SETTING and settings are rows now (#2017,
    `panel/runtime/settings_files.py`). The shipped template is the one thing here that
    is still a file, because it is part of the repository rather than of an account.
    """
    where = path or catalogue.path or TEMPLATE_FILE
    rows = [timer.as_dict() for timer in catalogue.timers]
    if not settings_files.write(where, rows):
        _write_json(where, rows)


class LastRunStore:
    """When each timer last ran, kept next to the profile it belongs to.

    One small JSON file, ``{name: {"last_run": epoch, "failed_at": epoch,
    "started_at": epoch}}``, rewritten whole on every mark. Read errors degrade to
    "nothing ever ran", which makes a corrupted file cost one extra run rather than a
    crash at launch. A profile switch calls :meth:`set_path` — the clock belongs to the
    account, not to the panel.

    THE START IS WRITTEN DOWN, NOT ONLY THE END (#1281). A run that never came back —
    the panel was closed or killed while it was in flight — used to leave no trace at
    all: `last_run` stayed where it was, no failure was recorded, and the errand was
    overdue again the moment a fresh panel read the file. That is how `restart_game`
    became unkillable on 2026-08-07: every start closed the client, waited five minutes
    for a scene that never came, and was killed mid-wait by the restart the person did
    to escape it — so each new panel saw an errand that had never been tried, fired it
    within seconds, and closed the client again. Restarting the panel could not help,
    because the thing that survived the restart was the ABSENCE of a record.

    So an attempt is stamped before it runs and cleared when it ends either way, and
    :meth:`sweep_unfinished` turns a stamp left behind by a dead process into an
    ordinary failure — which the retry hold already knows what to do with.
    """

    def __init__(self, path: str) -> None:
        self._lock = threading.Lock()
        self._path = path
        self._data = self._read(path)
        #: Errands whose last attempt never reported back, found when this file was
        #: read. Taken by the panel with :meth:`take_unfinished` and SAID — a run
        #: written off in silence is how the last one hid for a whole evening.
        self._unfinished = self._sweep()

    # -- location -----------------------------------------------------------
    @property
    def path(self) -> str:
        return self._path

    def set_path(self, path: str) -> None:
        """Point at another profile's file and reload from it."""
        with self._lock:
            self._path = path
            self._data = self._read(path)
        self._unfinished = self._sweep()

    # -- reading ------------------------------------------------------------
    def records(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._data.items()}

    def last_run(self, name: str) -> float:
        with self._lock:
            return float((self._data.get(name) or {}).get("last_run") or 0.0)

    def take_unfinished(self) -> list[str]:
        """Names whose attempt was still open when this file was read, once.

        Read by whoever is in a position to say it out loud; emptied by the reading, so
        it is said when it is found and not on every paint.
        """
        with self._lock:
            names, self._unfinished = list(self._unfinished), []
        return names

    # -- writing ------------------------------------------------------------
    def mark_started(self, name: str, when: float | None = None) -> None:
        """An attempt is beginning. Cleared by whichever of the two marks ends it.

        A REAL start also spends whatever the game had said about this turn
        (:meth:`mark_due_at`): the appointment is being kept, so the next one is read
        again rather than inherited. ``when=0.0`` — the un-stamp of an errand a busy
        panel never tried — leaves it standing, because that turn is still ahead.
        """
        stamp = float(when if when is not None else time.time())
        fields = {"started_at": stamp}
        if stamp:
            fields["due_at"] = 0.0
        self._update(name, fields)

    def mark_run(self, name: str, when: float | None = None) -> None:
        """Record a successful run, clearing any earlier failure hold.

        ``began_at`` is kept alongside — when the run STARTED, taken off the open
        attempt this success is closing. A daily errand's next turn is measured from it
        rather than from the finish, so a run that straddles the server's midnight is
        still charged to the day it spent (:func:`_day_anchor`). With no open attempt to
        read (a `run_one` that was never stamped, a test) the finish stands in for it.
        """
        done = float(when if when is not None else time.time())
        with self._lock:
            began = float((self._data.get(name) or {}).get("started_at") or 0.0)
        self._update(name, {"last_run": done, "failed_at": 0.0, "started_at": 0.0,
                            "began_at": began if began and began <= done else done})

    def mark_failed(self, name: str, when: float | None = None) -> None:
        """Record a failed attempt — the period keeps running, the retry waits."""
        self._update(name, {"failed_at": float(when if when is not None else time.time()),
                            "started_at": 0.0})

    def mark_due_at(self, name: str, when: float) -> None:
        """WHEN THE GAME SAID to come back — for this one turn (:data:`NEXT_RUN_VAR`).

        Written by whoever played the errand, out of the run's own variables, and read
        by :meth:`Catalogue.due_names` in place of the row's period. Cleared the moment
        the errand really starts, so a stale appointment cannot hold a timer shut: the
        worst a lost reading ever costs is one turn on the configured period.
        """
        self._update(name, {"due_at": max(0.0, float(when))})

    def _sweep(self) -> list[str]:
        """Write off attempts nobody ever finished, and name them.

        A stamp older than both marks belongs to a process that is not here any more:
        this file is read at start-up and on a profile switch, and in both cases nothing
        of the previous run is still going. Treated as a FAILURE rather than as "never
        tried", so the errand waits out its retry instead of firing the instant the
        panel is back — which is the whole reason the stamp exists.
        """
        found, changed = [], False
        with self._lock:
            for name, rec in list(self._data.items()):
                started = float((rec or {}).get("started_at") or 0.0)
                if not started:
                    continue
                rec = dict(rec)
                if started > float(rec.get("last_run") or 0.0) and \
                        started > float(rec.get("failed_at") or 0.0):
                    found.append(name)
                    rec["failed_at"] = started
                rec["started_at"] = 0.0
                self._data[name] = rec
                changed = True
            if changed:
                _write_json(self._path, self._data)
        return found

    def _update(self, name: str, fields: dict) -> None:
        with self._lock:
            rec = dict(self._data.get(name) or {})
            rec.update(fields)
            self._data[name] = rec
            _write_json(self._path, self._data)

    @staticmethod
    def _read(path: str) -> dict:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}


#: WHO asked for a run that is not on the clock. `scheduled` answers «the period came
#: round»; these two answer the other case, which used to be one word for two very
#: different events: a person pressing «Запустить», and a TRIGGER firing on its own. The
#: log said «запуск вручную» for both, so a self-firing trigger was indistinguishable
#: from somebody's thumb — the same class of fault as a poll that wrote nothing whether
#: it said no or had never run (#1296).
BY_HAND = "hand"
BY_TRIGGER = "trigger"


class TimerScheduler:
    """One background thread and a queue: everything ORDINARY runs single-file.

    **No ordinary errand ever runs in parallel with another.** The thread is both
    the clock and the only worker: on each tick it puts the errands that have come
    due on the queue, then takes them off one at a time and runs each to
    completion. Two timers that come due in the same second do not race — the
    second one waits in the queue until the first has finished. The row's "run
    now" button does not start a thread of its own either; it *enqueues*, so a
    press during a running errand takes its turn behind it instead of being
    dropped or overlapping it.

    Being both clock and worker is why the wait is on the queue rather than a
    sleep: an errand enqueued by hand is picked up at once, while an idle stretch
    still wakes on the tick.

    **THE ONE EXCEPTION IS «СРАЗУ»** (:attr:`Timer.immediate`, #1288). An errand the
    operator has marked that way does not use this queue at all: it runs on a thread of
    its own (:meth:`_express`) and takes its turn on the CLIENT instead, through a claim
    at a level an ordinary errand steps aside for (`panel/runtime/claims.py`). So two
    errands may be in flight here — but never two in the game, because the claim still
    hands the client from one to the other and never shares it. The flag exists because
    the queue priced a two-second alliance-help press at whatever the longest background
    errand happened to be: `restart_game` holds the client for a median of 304 s, and a
    help request pays nothing once it has closed.

    Collaborators are all callables, so nothing about Tk or the game leaks in:

      * ``catalogue()`` -> the current :class:`Catalogue` (a callable, so the file
                          can be re-read while the panel is open);
      * ``config()``   -> the normalised settings dict (read fresh every tick, so
                          a checkbox or period change applies without a restart);
      * ``runner(timer)`` -> ``True`` when the errand really ran, ``False`` when it
                          could not be started right now (the panel is busy with a
                          button-driven action) — then it stays queued and is
                          retried — and it raises for a real failure;
      * ``log(key, **fmt)`` -> a locale key plus its placeholders;
      * ``gate()``     -> a locale key explaining why nothing may run yet
                          (game not running), or ``None`` to proceed.

    The gate's complaint is said once per stretch, not once per tick: with the
    game closed overnight a 20-second tick would otherwise write 1800 identical
    lines into the log.
    """

    def __init__(self, *, store: LastRunStore, catalogue, config, runner, log,
                 gate=None, tick: float = TICK_SEC,
                 busy_retry: float = BUSY_RETRY_SEC, debug=None,
                 translate=None, day=None, label: str = "") -> None:
        # `debug` is the OWNING RUNTIME's technical logger (`rt.dbg("timers")`), so two
        # open profiles keep two debug.logs (#1206). The module-level one is the
        # fallback for a scheduler built without a runtime, which is what the tests do.
        self._dbg = debug if debug is not None else _dbg_window()
        self._store = store
        self._catalogue = catalogue
        self._config = config
        self._runner = runner
        self._log = log
        # `log` says a locale KEY as a whole line; `translate` turns one into words that
        # can go INSIDE a line. A skip needs the second: the errand's name, the count and
        # the reason belong in one sentence (:meth:`note_skip`). Optional, so a test can
        # build a scheduler without an i18n at all and read the raw key back.
        self._translate = translate
        # THIS PROFILE's server-day boundary (`panel/runtime/day_reset.py`), or `None`
        # for a scheduler built without a runtime. A period of whole days is anchored to
        # it instead of being counted off the last run — see :func:`next_after`.
        self._day = day
        # WHOSE scheduler this is, written into the names of the threads it starts
        # (#1392). One window holds four profiles and four schedulers, and a thread list
        # in which all four are called `panel-timers` cannot say which account's errand
        # is the one that has been running for six minutes. Empty for a scheduler built
        # without a runtime — a test — which keeps the plain name it always had.
        self._label = str(label or "")
        self._gate = gate
        self._tick = tick
        self._busy_retry = busy_retry
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._gate_said: str | None = None
        # The work queue. Items are (name, scheduled) — `scheduled` only picks the
        # log line. `_queued` keeps a name from being lined up twice: a second
        # press while the first is still waiting would run the errand twice in a
        # row for no reason.
        self._queue: "queue.Queue[tuple[str, bool]]" = queue.Queue()
        self._queued: set[str] = set()
        # WHEN each of those names was lined up, on the monotonic clock. A queue that
        # says only WHAT is waiting cannot say what a jam is: three errands behind one
        # slow run and three errands that arrived this second look identical (#1392).
        # Filled wherever a name enters `_queued`, emptied wherever it leaves.
        self._queued_at: dict[str, float] = {}
        # WHO lined it up and HOW — a clock, a press (window or phone: the same call
        # either way, `panel/web/api.py::run_timer`/`run_action`), or an event
        # (`BY_TRIGGER` — a push, which is what an autoloot or a rally-join fires from).
        # Filled and emptied alongside `_queued_at`, for the same rows (#1500).
        self._queued_meta: dict[str, tuple[bool, str]] = {}
        # Errands NOT in the catalogue that were handed to the queue directly —
        # a trigger's scenario (panel/triggers.py). They share the one worker and the
        # dedup set, but the worker cannot look them up in `catalogue()`, so it keeps
        # them here by name for the length of the run. Anything with `.name` and
        # `.scenario` (a Trigger) works — the runner only reads those.
        self._adhoc: dict = {}
        # Names the UI asked to take back off the queue. Marked rather than removed
        # (a Queue cannot be searched), and dropped by the worker when it gets there.
        self._cancelled: set[str] = set()
        # The errand being run right now, if any. `_queued` cannot tell waiting from
        # running (a claim covers both), and `cancel` has to: one is cancellable and
        # the other is not.
        self._running: str | None = None
        #: …and since when, so «идёт» can say for how long (:meth:`queue_state`).
        self._running_since = 0.0
        # …and the errands marked «сразу», which do NOT run on the worker and so cannot
        # be that one name (#1288). A set, because several of them may be in flight at
        # once — each on its own thread, each taking its turn on the client through the
        # claim rather than through this queue.
        self._express_running: set[str] = set()
        # How an express errand gets its thread. A collaborator like every other one
        # here, so a test can run it inline and read the outcome without joining
        # anything (`_spawn_thread` is what the panel uses).
        self._spawn = self._spawn_thread
        # Names whose moment came again WHILE they were running. A push that lands
        # mid-run used to be dropped by the claim below, which is how a second banner
        # raised while the first was being joined was lost without a word (#1281): the
        # run in flight had already read the map and could not know about it. Marked
        # here and re-queued the moment the run lets go, so the burst costs one extra
        # run rather than a rally. A name merely WAITING in the queue is still
        # coalesced — that run has not looked at anything yet and will see the new
        # rally by itself.
        self._refire: set[str] = set()
        # Names parked because the panel was busy, so the retries stay quiet: the
        # queue re-offers them every `BUSY_RETRY_SEC` and only the first offer is
        # worth a «стартую» line. Emptied the moment one of them actually runs.
        self._busy_held: set[str] = set()
        # FIRES WAITING FOR THEIR GATE (#1416): `name -> (errand, scheduled, by, since,
        # last offer)`. A clock brings a timer back by itself; a push has nothing to
        # bring it back, so a gate refusal used to be the end of it — the event was
        # dropped and nothing but a rolled-up skip line said so. They wait here and are
        # re-offered every `GATE_RETRY_SEC` until the gate opens (`_retry_gated`), and
        # are given up only when they are older than `GATE_KEEP_SEC` — said out loud,
        # because an event nobody could act on is news whichever way it ends.
        self._gated: dict = {}
        # Repeated skips, rolled up: name -> [reason, count, last-said-monotonic].
        self._skips: dict = {}
        # WHAT JUST LEFT THE QUEUE, newest first — «не пропадает молча» (#1500). A row
        # in the live queue that finishes, is cancelled or is given up behind its gate
        # stops answering `queue_state()` the instant it does, and without this a jam
        # read a second late looked exactly like a jam that had never happened.
        self._recent: deque = deque(maxlen=RECENT_KEEP)
        self._queue_lock = threading.Lock()
        # Wall clock the worker may take from the queue again, set when the panel
        # turns an errand down as busy. Without it the item goes straight back on
        # the queue and the thread spins on a button press that takes a minute.
        self._hold_until = 0.0

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        name = "panel-timers" + (f":{self._label}" if self._label else "")
        self._thread = threading.Thread(target=self._loop, daemon=True, name=name)
        self._thread.start()
        self._dbg.info("scheduler started")

    def stop(self) -> None:
        self._stop.set()
        self._dbg.info("scheduler stopped")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- the queue ----------------------------------------------------------
    def request(self, timer: Timer) -> bool:
        """Ask for an errand by hand ("run now"). ``False`` if already queued.

        Called from the UI thread and returns immediately — the errand runs on the
        worker like a scheduled one, so it cannot overlap whatever is running.
        """
        return self._enqueue(timer.name, scheduled=False, by=BY_HAND)

    def submit(self, errand) -> bool:
        """Queue an errand that is NOT in the catalogue — a trigger's scenario.

        The trigger watcher (panel/triggers.py) calls this when a push lands, so the
        scenario runs on THIS one worker, single-file with the scheduled timers and
        never in parallel with them. ``errand`` needs only ``.name`` and
        ``.scenario`` (a :class:`~panel.triggers.Trigger`); it is remembered by name
        for the run because the worker looks errands up in the catalogue and this one
        is not there.

        Returns WHAT HAPPENED to the fire, because «dropped» and «will run» used to be
        the same `False` and the caller logged «запускаю сценарий» over both (#1281):

        * ``"queued"``  — it is on the queue and will run;
        * ``"waiting"`` — one of the same name is already queued and has not looked at
          anything yet, so it will see whatever this fire was about; the burst
          coalesces to one press, which is what that coalescing is for;
        * ``"refired"`` — one of the same name is RUNNING. It has already read the
          game and cannot know about this, so the name is marked and re-queued the
          moment it lets go (:meth:`_release`). This is the case that used to lose a
          rally: a second banner going up while the first was being joined.

        Every one of the three is truthy, so a caller that only asked «did it take it»
        still gets a yes — none of these three means the fire was thrown away.
        """
        express = bool(getattr(errand, "immediate", False))
        with self._queue_lock:
            if errand.name in self._queued:
                self._adhoc.setdefault(errand.name, errand)
                if errand.name == self._running or errand.name in self._express_running:
                    self._refire.add(errand.name)
                    return "refired"
                return "waiting"
            self._adhoc[errand.name] = errand
            if not express:
                self._queued.add(errand.name)
                self._queued_at[errand.name] = time.monotonic()
                self._queued_meta[errand.name] = (False, BY_TRIGGER)
        if express:
            # Outside the lock: `_express` takes it to claim the name for itself, and
            # re-checks there, so the gap above cannot let two runs through.
            return "queued" if self._express(errand.name, False,
                                             refire=True) else "waiting"
        self._queue.put((errand.name, False, BY_TRIGGER))
        return "queued"

    # -- «сразу, без очереди» (#1288) ---------------------------------------
    def _errand(self, name: str):
        """The catalogue entry of that name, or the submitted one standing in for it."""
        errand = self._catalogue().by_name(name)
        if errand is None:
            with self._queue_lock:
                errand = self._adhoc.get(name)
        return errand

    def _is_immediate(self, name: str) -> bool:
        """Has this errand been marked «сразу»?"""
        return bool(getattr(self._errand(name), "immediate", False))

    def _express(self, name: str, scheduled: bool, refire: bool = False,
                 by: str = BY_HAND) -> bool:
        """Run ``name`` NOW, on a thread of its own. ``False`` if one is already going.

        The queue is what makes an errand wait, and the flag's whole meaning is that
        this one does not: the worker may be five minutes inside a `restart_game`, and
        an alliance help request that arrives then pays nothing by the time it is its
        turn. So the express errand skips the queue entirely and the CLAIM does the
        serialising instead — `Schedule.run_errand` asks for the client at EXPRESS,
        which makes the ordinary errand step aside at its next statement
        (`panel/runtime/daemon.py::claim_soon`). Two chunks still never go into the game
        VM at once; what has gone is one of the three places they were made to queue.

        Still deduped through `_queued`, so a burst of pushes is one run and not ten,
        and still released through `_release`, so a fire that landed mid-run re-arms it
        exactly as it does for a queued errand.
        """
        errand = self._errand(name)
        if errand is None:
            return False
        # THE GATE IS ASKED HERE TOO, and it was not (#1281). An express errand skips
        # the queue, and with it `_run_queued` — the one place a refusal was read. So
        # `rally_auto_join`, which is exactly the errand somebody would mark «сразу»,
        # raised a run for every banner on the map whatever the answer would have been.
        # Asked BEFORE the name is claimed and the thread is spawned: no run, no queue
        # slot, and the reason rolled up with a count like any other skip.
        if self._gate is not None:
            reason = self._gate(name)
            if reason:
                self.note_skip(name, reason)
                self._gate_said = reason
                # …AND IT WAITS RATHER THAN DYING (#1416). This is a PUSH: nothing in
                # the panel will bring it back, so a gate refusal here used to be an
                # event silently thrown away — the very «пропускаются событий» this
                # was reported as. Parked, and re-offered when the gate opens.
                self._park_gated(name, errand, scheduled, by, reason)
                return False
        with self._queue_lock:
            if name in self._queued:
                # A FIRE landing mid-run is re-armed (`refire`); a CLOCK finding the
                # same errand still going is not. The two look alike here and are not:
                # a push is news the run in flight could not have seen, and a tick is
                # the same errand coming round again while it is still busy.
                if refire and (name == self._running
                               or name in self._express_running):
                    self._refire.add(name)
                return False
            self._queued.add(name)
            self._queued_at[name] = time.monotonic()
            self._queued_meta[name] = (bool(scheduled), by)
            self._express_running.add(name)

        def work() -> None:
            busy = False
            try:
                _ok, busy = self.run_one(errand, scheduled=scheduled, by=by)
            except Exception:                             # noqa: BLE001
                # `run_one` already records and logs a failing errand; this is the
                # floor under a thread that must never take the panel with it.
                self._dbg.error("express run of %s failed", name, exc_info=True)
            finally:
                with self._queue_lock:
                    self._express_running.discard(name)
                if busy:
                    # It waited its twelve seconds and the client is still held by
                    # something it does not outrank — another express errand, or a
                    # person's own press. Then the flag has nothing left to offer and
                    # the errand takes its turn like any other: onto the queue, claim
                    # kept, so nothing lines it up twice while it waits.
                    self._queue.put((name, scheduled, by))
                else:
                    self._release(name)

        self._spawn(work, f"panel-timer:{self._label}:{name}" if self._label
                    else f"panel-timer-{name}")
        return True

    @staticmethod
    def _spawn_thread(work, label: str) -> None:
        threading.Thread(target=work, name=label[:60], daemon=True).start()

    def _enqueue(self, name: str, scheduled: bool, by: str = BY_HAND) -> bool:
        if self._is_immediate(name):
            return self._express(name, scheduled, by=by)
        with self._queue_lock:
            if name in self._queued:
                return False
            self._queued.add(name)
            self._queued_at[name] = time.monotonic()
            self._queued_meta[name] = (bool(scheduled), by)
        self._queue.put((name, scheduled, by))
        return True

    def park_gated(self, errand, reason: "str | None" = None) -> None:
        """Hold a fire that never reached the queue at all — the panel was stopped.

        `Schedule.submit` asks its own gate before this scheduler is involved (a fire
        that reaches the queue has already cost a name and a slot), so the refusal
        happened one layer up and the errand has to be handed in from there — WHY, if
        the caller has it, so the row this fire draws on «Занятость» does not have to
        guess (#1500).
        """
        name = str(getattr(errand, "name", "") or "")
        if name:
            self._park_gated(name, errand, False, BY_TRIGGER, reason)

    def _park_gated(self, name: str, errand, scheduled: bool, by: str,
                    reason: "str | None" = None) -> None:
        """Keep a fire the gate turned away, so it can be offered again (#1416).

        THE GUARANTEE THIS EXISTS FOR: a listener either acts on an event at once or
        queues it, but the event is acted on. Being busy may DELAY the work; it may not
        cancel it. Everything else in this scheduler already honours that — a busy panel
        re-queues, a run in flight re-fires — and the gate was the one door that simply
        dropped what came through it.

        One entry per NAME, and a second fire of the same name refreshes it rather than
        stacking: the errand re-reads the game when it finally runs, so two parked copies
        would be one press made twice. That is the same coalescing `submit` already does
        for a name waiting in the queue.

        Its own age is kept from the FIRST fire, not the last, so a push that keeps
        arriving cannot hold a stale errand alive for ever. ``reason`` is the GATE's own
        locale key (already computed by the caller — this never asks the gate itself)
        so a live reading can say WHY without a second question to the game.
        """
        if errand is None:
            return
        with self._queue_lock:
            old = self._gated.get(name)
            since = old[3] if old else time.monotonic()
            self._gated[name] = (errand, bool(scheduled), by, since, 0.0, reason)
            self._adhoc.setdefault(name, errand)
        self._dbg.info("parked %s behind the gate", name)

    def _retry_gated(self) -> list:
        """Offer every parked fire again, and give up the ones that have gone stale.

        Called from the tick, so it runs on the scheduler's own thread and costs a dict
        walk. The GATE is asked per name, exactly as `enqueue_due` asks it: the errand
        that puts the client back must not be held behind the client being down.

        Returns the names it re-queued — what the tests read.
        """
        if not self._gated:
            return []
        now = time.monotonic()
        out, dropped = [], []
        with self._queue_lock:
            parked = list(self._gated.items())
        for name, (errand, scheduled, by, since, last, _reason) in parked:
            if now - since >= GATE_KEEP_SEC:
                dropped.append((name, scheduled, by))
                continue
            if last and now - last < GATE_RETRY_SEC:
                continue
            reason = self._gate(name) if self._gate is not None else None
            if reason:
                with self._queue_lock:
                    if name in self._gated:
                        self._gated[name] = (errand, scheduled, by, since, now, reason)
                continue
            with self._queue_lock:
                self._gated.pop(name, None)
            if self._enqueue(name, scheduled, by):
                out.append(name)
        for name, scheduled, by in dropped:
            with self._queue_lock:
                self._gated.pop(name, None)
            # SAID OUT LOUD. An event given up on is the thing the operator was told
            # would never happen, so it is never silent — even though giving it up is
            # the right answer once its moment has passed. And it stays visible a while
            # longer still, in `recent()` — a row that vanished off the gated list said
            # nothing about WHERE it went until #1500.
            self._log("timers.log.gate_expired", name=name,
                      secs=int(GATE_KEEP_SEC))
            self._note_done(name, by, scheduled, "gate_expired")
            self._dbg.warning("gave up %s — %.0fs behind the gate", name, GATE_KEEP_SEC)
        return out

    def gated(self) -> list:
        """The fires waiting for their gate, oldest first — for «Занятость» (#1416)."""
        now = time.monotonic()
        with self._queue_lock:
            rows = [{"name": name, "secs": max(0.0, now - since), "scheduled": bool(s),
                     "by": b, "reason": reason}
                    for name, (_e, s, b, since, _l, reason) in self._gated.items()]
        return sorted(rows, key=lambda row: -row["secs"])

    def _note_done(self, name: str, by: str, scheduled: bool, outcome: str) -> None:
        """Remember what a queue entry turned into — the other half of #1500.

        A row a person was told «в очереди» about must not simply stop answering: this
        is what lets a live view say «выполнено» / «отменено» / «просрочено, ждало
        ворота» for the last :data:`RECENT_KEEP` of them instead of nothing at all.
        """
        with self._queue_lock:
            self._recent.appendleft({"name": name, "by": by, "scheduled": bool(scheduled),
                                     "outcome": outcome, "when": time.monotonic()})

    def recent(self) -> list:
        """The last errands to leave the queue, newest first, with their age in seconds."""
        now = time.monotonic()
        with self._queue_lock:
            rows = list(self._recent)
        return [{**row, "secs": max(0.0, now - row["when"])} for row in rows]

    def _requeue(self, name: str, scheduled: bool, by: str = BY_HAND) -> None:
        """Put a turned-down errand back on the queue, still claimed.

        At the back, not the front: it was never started, so nothing is half done,
        and whatever is queued behind it came due just as much. Keeping its claim
        is what stops the next tick from lining the same errand up twice.
        """
        self._queue.put((name, scheduled, by))

    def _release(self, name: str) -> None:
        with self._queue_lock:
            # Its moment came again while it was running (:meth:`submit`): put it
            # straight back rather than letting go of it. The claim is KEPT — it never
            # leaves the queued set — so nothing else can line the same name up twice
            # in between, and the errand it re-runs is the same one it just finished.
            refire = name in self._refire
            self._refire.discard(name)
            if not refire:
                self._queued.discard(name)
                self._queued_at.pop(name, None)
                self._queued_meta.pop(name, None)
                self._adhoc.pop(name, None)   # a submitted trigger errand is done with
                # The cancel mark goes with the claim. A cancel that arrived while the
                # errand was already running is refused (see `cancel`), but a mark left
                # behind by any other race would silently swallow the NEXT run of the
                # same errand — a bug that would look like a timer that fires once and
                # then skips a turn for no reason.
                self._cancelled.discard(name)
                # THE WORKER IS IDLE NOW, and `queue_state()` has to say so (#1500):
                # `_running` was set for the length of this call and nothing else ever
                # cleared it on the ordinary finish path, so between one run ending and
                # the next one starting a live view kept reporting the LAST errand as
                # still going, with its age climbing for as long as the queue happened
                # to sit empty. Only when it is still THIS name — a refire (above) put
                # it straight back on the worker's plate and is about to run it again.
                if self._running == name:
                    self._running = None
                    self._running_since = 0.0
                return
        # AN ERRAND MARKED «СРАЗУ» RE-FIRES THE WAY IT FIRED. Putting it on the queue
        # would hand the second push exactly the wait the flag exists to remove — and
        # it is the second push that matters here: the first is the burst's, and the
        # one that landed mid-run is the request the run could not have seen.
        if self._is_immediate(name):
            with self._queue_lock:
                self._queued.discard(name)     # `_express` claims the name itself
                self._queued_at.pop(name, None)
                self._queued_meta.pop(name, None)
            if not self._express(name, False, refire=True, by=BY_TRIGGER):
                with self._queue_lock:
                    self._adhoc.pop(name, None)
            return
        self._queue.put((name, False, BY_TRIGGER))

    def pending(self) -> set[str]:
        """Names currently queued or being run — for tests and the row painter."""
        with self._queue_lock:
            return set(self._queued)

    def queue_state(self) -> dict:
        """The queue as data: what runs, what waits, how long, and what is held (#1392).

        The one reading a jam is diagnosed from. `running` is the errand on the single
        worker and `express` the ones that skipped the queue and are taking their turn on
        the CLIENT instead; `waiting` is everything else lined up, longest wait first —
        which is the order they came, so «кто за кем» is the list. `held` names the
        errands parked because the panel was busy and `hold_secs` how much of that hold
        is left.

        One pass under the queue's own lock and no I/O: this is read by a debugger that
        refreshes once a second and must never be the reason the queue is slow.
        """
        now = time.monotonic()
        with self._queue_lock:
            running, since = self._running, self._running_since
            express = sorted(self._express_running)
            waiting = [(name, self._queued_at.get(name, now),
                       self._queued_meta.get(name, (False, BY_HAND)))
                       for name in self._queued
                       if name != running and name not in self._express_running]
            held = sorted(self._busy_held)
            refire = sorted(self._refire)
            cancelled = sorted(self._cancelled)
        # WHO lined it up and HOW (#1500) travel beside the wait itself, so a live view
        # can say «таймер» / «кнопка» / «событие» without a second question to anything.
        waiting = [{"name": name, "secs": max(0.0, now - at),
                   "scheduled": bool(meta[0]), "by": meta[1]}
                  for name, at, meta in waiting]
        waiting.sort(key=lambda row: row["secs"], reverse=True)
        return {
            "running": running or "",
            "running_secs": max(0.0, now - since) if running else 0.0,
            "express": express,
            "waiting": waiting,
            "held": held,
            "hold_secs": max(0.0, self._hold_until - time.time()),
            "refire": refire,
            "cancelled": cancelled,
            # …and the fires waiting for a door rather than for a worker (#1416). They
            # are not «в очереди» — the queue would run them — and a reading that left
            # them out is what made a delayed event look like a dropped one.
            "gated": self.gated(),
            # …and what just left, so a row a person was told «в очереди» about does not
            # simply stop answering the moment it finishes (#1500).
            "recent": self.recent(),
            "alive": self.running,
        }

    def cancel(self, name: str) -> bool:
        """Take a WAITING errand back off the queue. ``False`` if there is none.

        The Timers tab had no cancel at all: a «Запустить» pressed by mistake, or a
        tick that queued three errands behind a slow one, could only be waited out.

        The item is not plucked out of the queue — a ``queue.Queue`` cannot be
        searched — it is *marked*, and the worker drops it when it comes off.

        An errand that is **already running** is not cancellable and says so
        (``False``): the press is in flight, and killing a scenario mid-call into
        the game is exactly what the Scenarios tab's Stop refuses to do too. Saying
        "taken off the queue" about a run that then completes would be a lie the
        operator acts on.
        """
        with self._queue_lock:
            if name not in self._queued or name == self._running \
                    or name in self._express_running:
                return False
            self._cancelled.add(name)
            return True

    def _take_cancelled(self, name: str) -> bool:
        """Was ``name`` cancelled while it waited? Clears the mark either way."""
        with self._queue_lock:
            if name in self._cancelled:
                self._cancelled.discard(name)
                return True
            return False

    # -- the clock ----------------------------------------------------------
    def _loop(self) -> None:
        next_tick = 0.0                      # tick immediately on the first pass
        while not self._stop.is_set():
            try:
                now = time.monotonic()
                if now >= next_tick:
                    self.enqueue_due()
                    next_tick = now + self._tick
                # Wait on the QUEUE, not on a sleep: a "run now" press has to be
                # picked up at once, and an idle stretch still wakes on the tick.
                wait = max(0.05, next_tick - time.monotonic())
                if self._hold_until > time.time():
                    # The panel is busy with a button-driven action; sit the hold
                    # out rather than taking work we cannot start.
                    self._stop.wait(min(wait, self._hold_until - time.time()))
                    continue
                try:
                    name, scheduled, by = self._queue.get(timeout=wait)
                except queue.Empty:
                    continue
                self._run_queued(name, scheduled, by)
            except Exception as exc:                      # noqa: BLE001
                # A scheduler that dies takes every timer with it, silently —
                # so nothing above is allowed to escape this loop.
                self._log("timers.log.tick_error", error=exc)
                self._dbg.error("tick error", exc_info=True)
                self._stop.wait(self._tick)

    def enqueue_due(self, now: float | None = None) -> list[str]:
        """Queue every errand that has come due. Returns the names it queued.

        …and, FIRST, whatever is waiting behind the gate (#1416): a push has no clock of
        its own, so this beat is what brings it back once the game is up again.
        """
        queued = self._retry_gated()
        now = time.time() if now is None else now
        catalogue = self._catalogue()
        config = catalogue.normalize_config(self._config())
        pending = catalogue.due_names(config, self._store.records(), now, self._day)
        if not pending:
            return queued
        if self._gate is not None:
            # PER ERRAND, not per tick. The gate that matters is «the game is not
            # running», and the errand that PUTS IT BACK is on this very list: a
            # blanket refusal dropped `restart_game` for the one reason it exists,
            # and a client that died at eight in the evening was still dead at ten
            # with the schedule reporting «пропускаю: игра не запущена» all night
            # (#1259). So each name is asked about separately, and the recovery ones
            # are let through.
            allowed, refused = [], None
            for name in pending:
                reason = self._gate(name)
                if reason:
                    refused = reason
                else:
                    allowed.append(name)
            if refused and refused != self._gate_said:
                self._log(refused)
                self._gate_said = refused
            if not allowed:
                return queued
            pending = allowed
        self._gate_said = None
        return queued + [name for name in pending if self._enqueue(name, scheduled=True)]

    def _run_queued(self, name: str, scheduled: bool, by: str = BY_HAND) -> str:
        """Take one errand off the queue and run it.

        Returns ``"ran"`` / ``"skipped"`` / ``"busy"``. ``"busy"`` is the caller's
        signal to stop working the queue for now: the errand has been put back and
        re-running the pass would take the very same item straight off again.
        """
        if self._take_cancelled(name):       # the UI took it back while it waited
            self._log("timers.log.cancelled", name=name)
            self._note_done(name, by, scheduled, "cancelled")
            self._release(name)
            return "skipped"
        timer = self._catalogue().by_name(name)
        if timer is None:                    # a submitted trigger errand, or…
            with self._queue_lock:
                timer = self._adhoc.get(name)
        if timer is None:                    # …deleted from the config mid-run
            self._release(name)
            return "skipped"
        if self._gate is not None:
            reason = self._gate(name)
            if reason:
                # The game went away between queueing and running: drop it rather
                # than fail it — the next tick queues it again, unchanged. SAID WITH
                # THE ERRAND'S NAME AND A COUNT (#1281): «жду запуска игры» once an
                # hour told nobody that two hundred rally pushes had been refused for
                # it, and a skip with nothing attached to it reads as nothing at all.
                self.note_skip(name, reason)
                self._gate_said = reason
                self._release(name)
                # A TIMER comes back on its own clock; A FIRE DOES NOT (#1416). The
                # comment above — «the next tick queues it again» — is true of the
                # catalogue's errands and was never true of a trigger's: its moment
                # was a push that has already gone. So an ad-hoc errand is parked and
                # re-offered when the gate opens, and a catalogue timer is left to its
                # clock exactly as before.
                if timer is not None and self._catalogue().by_name(name) is None:
                    self._park_gated(name, timer, scheduled, by, reason)
                return "skipped"
        # Mark it as running for the whole call, so `cancel` can tell "waiting in
        # the queue" (cancellable) from "in flight" (not) — and so a fire landing
        # mid-run is re-armed rather than coalesced away (`submit`). Cleared inside
        # `_release`, under the same lock, or a fire arriving in the gap between the
        # two would see neither a running errand nor a free queue and be dropped.
        with self._queue_lock:
            self._running = name
            self._running_since = time.monotonic()
        try:
            ok, busy = self.run_one(timer, scheduled=scheduled, by=by)
        finally:
            if busy:
                with self._queue_lock:
                    self._running = None
        if busy:
            self._hold_until = time.time() + self._busy_retry
            self._requeue(name, scheduled)   # stays claimed: it is still waiting
            return "busy"
        self._note_done(name, by, scheduled, "done" if ok else "failed")
        self._release(name)
        return "ran" if ok else "skipped"

    def note_skip(self, name: str, reason: str, **fmt) -> bool:
        """Say that ``name`` did not run, and why — rolled up when it keeps happening.

        The first time a reason appears it is said at once. While the SAME reason keeps
        coming back for the same errand it is said again at most every
        :data:`SKIP_NOTE_SEC`, carrying how many skips have piled up since the last
        line. A different reason starts over, because that is news.

        Returns whether a line was written, which is what the tests read.
        """
        now = time.monotonic()
        with self._queue_lock:
            note = self._skips.get(name)
            if note is not None and note[0] == reason:
                note[1] += 1
                if now - note[2] < SKIP_NOTE_SEC:
                    return False
                count, note[1], note[2] = note[1], 0, now
            else:
                self._skips[name] = [reason, 0, now]
                count = 1
        if count > 1:
            self._log("timers.log.skipped_times", name=name, count=count,
                      reason=self._reason_text(reason, **fmt))
        else:
            self._log("timers.log.skipped_once", name=name,
                      reason=self._reason_text(reason, **fmt))
        self._dbg.info("skipped %s x%d — %s", name, count, reason)
        return True

    def _reason_text(self, reason: str, **fmt) -> str:
        """A skip's reason as WORDS, whether it arrived as a locale key or a sentence.

        The gate answers in locale keys (`timers.log.skip_game`) and a caller may hand in
        a finished sentence; both have to end up inside one line rather than being logged
        as a line of their own, which is what let «жду запуска игры» float free of the
        errand it was about.
        """
        translate = getattr(self, "_translate", None)
        if translate is not None:
            try:
                return str(translate(reason, **fmt))
            except Exception:                # noqa: BLE001 — a word, never the skip
                pass
        return reason

    def tick_once(self, now: float | None = None) -> list[str]:
        """Queue what is due and work the queue off, in order. Names that ran.

        Exactly what the loop does over one tick, minus the waiting — which is
        what makes the schedule's behaviour testable without threads at all.
        """
        self.enqueue_due(now)
        return self.drain()

    def drain(self) -> list[str]:
        """Run the queue down, one errand at a time, until it is empty or held."""
        ran = []
        while not self._stop.is_set():
            if self._hold_until > time.time():
                break                        # the panel is busy — the rest waits
            try:
                name, scheduled, by = self._queue.get_nowait()
            except queue.Empty:
                break
            status = self._run_queued(name, scheduled, by)
            if status == "busy":
                # It went back on the queue: stop the pass, or the next lap would
                # pull the same item off again and ask the busy panel in a spin.
                break
            if status == "ran":
                ran.append(name)
        return ran

    def run_one(self, timer: Timer, scheduled: bool = False,
                by: str = BY_HAND) -> tuple[bool, bool]:
        """Run one errand and record the outcome. Returns ``(ran, busy)``.

        ``busy`` is the one outcome that is not a verdict on the errand: the panel
        had a button-driven action of its own in flight, so the errand has not been
        tried at all and the caller keeps it queued. A raise is a real failure
        (recorded, held back); anything else is a run (recorded, clock reset).

        Both the tick and the "run now" button come through here, which is what
        makes a manual press restart the period exactly like an automatic run.
        """
        if scheduled:
            # A NAME WAITING OUT A BUSY PANEL SAYS «стартую» ONCE, NOT EVERY RETRY.
            # The queue re-offers it every `BUSY_RETRY_SEC`, and each offer used to
            # write two lines — one claiming it was starting and one saying it was
            # not. Two errands parked behind a stuck run buried an evening's log in
            # 1698 lines of it, which is the log being useless exactly when somebody
            # is reading it to find out what went wrong (#1281).
            if timer.name not in self._busy_held:
                self._log("timers.log.fire", name=timer.name,
                          mins=self._minutes_since(timer.name))
            self._dbg.info("fire %s (scheduled)", timer.name)
        else:
            # WHO asked, in the person's own log. «запуск вручную» over a trigger's
            # own fire is a log that cannot tell a thumb from an automation, and that is
            # exactly what somebody reads this line to find out (#1296).
            if by == BY_TRIGGER:
                self._log("timers.log.by_trigger", name=timer.name)
            else:
                self._log("timers.log.manual", name=timer.name)
            self._dbg.info("fire %s (%s)", timer.name, by)
        # Stamped BEFORE the run, so a panel that dies mid-errand leaves a record of
        # the attempt rather than of nothing at all (`LastRunStore.sweep_unfinished`).
        self._store.mark_started(timer.name)
        try:
            started = self._runner(timer)
        except Exception as exc:                          # noqa: BLE001
            self._store.mark_failed(timer.name)
            self._log("timers.log.failed", name=timer.name, error=exc)
            self._dbg.error("run of %s failed", timer.name, exc_info=True)
            return False, False
        if not started:
            # Not an attempt: nothing was tried, so the stamp comes straight back off
            # or a busy panel would put every errand behind it into a retry hold.
            self._store.mark_started(timer.name, 0.0)
            # Rolled up like any other reason an errand did not run: said at once,
            # then at most once a minute with how many attempts piled up behind it.
            self.note_skip(timer.name, "timers.reason.busy")
            self._busy_held.add(timer.name)
            self._dbg.warning("skipped %s — panel busy", timer.name)
            return False, True
        self._busy_held.discard(timer.name)
        self._store.mark_run(timer.name)
        self._log("timers.log.done", name=timer.name)
        self._dbg.info("done %s", timer.name)
        return True, False

    def _minutes_since(self, name: str) -> int:
        last = self._store.last_run(name)
        if not last:
            return 0
        return int((time.time() - last) // 60)
