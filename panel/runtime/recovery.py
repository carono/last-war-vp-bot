"""A client that cannot be heard gets restarted — the decision, on its own.

There are two ways to lose an account without losing the process, and from the outside
they look identical: the server hangs up on an idle client, or the account is logged in
on another device and this session is KICKED (a single-session game — see
`docs/research/game-launch-and-scene-control.md` §5). Either way the window still draws,
every Lua getter still answers with the numbers it last received, and every send still
returns `true` while nothing arrives. That is `link == lost`
(`tools/lib/game_link.py`), and the only cure is a restart.

Nothing did it. On 2026-08-06 a client lost the server at 18:58, was still holding a
dead socket at 20:02 when it finally died, and was still dead two hours later: the
watchdog only reacts to the PROCESS going away, and the six-hourly `restart_game` timer
was both switched off and — had it been on — dropped every tick by a schedule gate that
refused everything while «the game is not running» (#1259).

WHAT THIS MODULE IS. The decision and nothing else: given a link state and a clock, may
the client be restarted right now, and what should be said about it. No Tk, no game, no
threads — so the rule can be driven by a test through every path, which matters more
here than anywhere else in the panel: **a false positive costs a live client**, and the
one thing worse than an account that quietly stopped playing is one that is restarted
every five minutes all night.

THE THREE THINGS THAT KEEP IT SAFE

* **A run of readings, not one.** A client reconnecting has, for a moment, exactly the
  sockets of one that has given up, so a single `lost` proves nothing. :data:`STRIKES`
  consecutive ones do — the same patience, and for the same reason, that the status
  strip already waits before it announces the loss at all.
* **`unknown` is never a reason.** A client in its first 45 seconds has its web sockets
  and its own loopback pair and no game socket yet; so does a machine that will not
  attribute a foreign process's sockets. Neither is a fault, and a restart loop built on
  «I cannot tell» would eat a healthy account alive. Only a POSITIVE `lost` counts, and
  anything else resets the run.
* **A cooldown between restarts.** A client that comes up and loses the server again —
  a broken network, a second device logged in and staying there — must not be relaunched
  every poll until morning. One restart per :data:`COOLDOWN_SEC`, and the wait is said
  out loud rather than passed over in silence.

THE FOURTH THING, AND THE REASON THIS FILE GREW (#1268): **restarting the right thing.**

A client that cannot be driven is not always a client that is broken. The panel drives it
through a warm Lua daemon, and the daemon holds a pid — so when the client is replaced,
a daemon that has not re-attached is pointing at a process that no longer exists. From
the schedule's side that looks exactly like a dead client: every errand fails, the link
readings look wrong, and the cure the watchdog knows is a restart.

It restarts the WRONG THING, and then it does it again. Live on 2026-08-07, from 03:14
to 04:05: the client was relaunched **six times in a row** and the link never came back,
because the fault was the daemon holding a dead pid and answering `snapshot failed err=5`
to everything (`lua_client.ClientGone`, #1266). Every relaunch made it worse — a new pid
the daemon knew even less about — and `launch_game` timed out on `WAIT scene == city`
each time, for five minutes each time. One `{"op":"shutdown"}` on the daemon fixed it in
two seconds. Nothing in the panel had ever tried that, because nothing in the panel could
tell the two faults apart.

Two readings tell them apart, and this module takes both:

* **the positive one — the daemon names the wrong client.** `{"op":"ping"}` answers the
  pid the daemon is attached to; the status poll already knows the pid that is running.
  Different pids (or a daemon naming none while a client runs) is not an inference, it is
  the fault itself, stated. That is :meth:`Recovery.note_daemon`;
* **the cumulative one — the cure is not working.** :data:`FRUITLESS` client restarts with
  the link never once coming back is, by itself, evidence that the thing being restarted
  is not the thing that is broken. So the blame moves rather than the count going up: the
  next act is a daemon restart, not a seventh client restart. That is inside
  :meth:`Recovery.note`.

The second is deliberately blind to WHY. It cannot know what else might be wrong — a dead
network, a server in maintenance, an account held on another device — and it does not
need to: it only needs to stop repeating a cure that has demonstrably not worked, and try
the one cheap thing nobody had tried. A daemon restart costs a fraction of a second and
takes nothing away from a client, which is why it is safe to reach for on a guess where a
client restart is not.

THE FIFTH THING (#1270): **a kick is a state, not a footnote on a lost link.**

The two ways of losing an account are not, in fact, symmetrical, and the difference was
paid for on 2026-08-07. A server that hangs up leaves the sockets half-closed and
`game_link` says `lost`. An account taken by another device can leave ONE established
conversation standing — five half-closed beside it, which is also what a perfectly
healthy client looks like — so the link reads `online`, `dead=0`, and every reading in
the panel agrees that nothing is wrong. The kick flag knew; it was simply never asked,
because it was asked only while the link already said `lost`. Two and a quarter hours of
timers went into a client that could not send, and not one of them failed.

So `kicked` is now read on every poll (`panel/__main__.py`, `tools/lib/game_kick.py`) and
is deaf ON ITS OWN. The reading had to get narrower to bear that weight — it is the
game's own sentence out of the client's own language tables, not «some dialog is open» —
and everything that makes a restart safe is unchanged around it.

…AND THE CURE FOR A KICK IS NOT THE CURE FOR A HANG-UP (#1291): **wait first.**

Naming the state was only half of it. The act stayed the same one — restart, at once —
and that act is wrong here, because a kick has an author. Somebody is holding the
account, on a phone or on another machine, and the panel taking it back a few seconds
later throws THEM out of the game; then their client takes it back and kicks this one,
and the two go round. Live on 2026-08-08 that was three restarts in a row, `launch_game`
timing out on each, and a daemon dying with every client — while the person was simply
trying to play.

So a kick earns :data:`KICK_HOLD_SEC` of being left completely alone — fifteen minutes by
default, a profile setting rather than a constant, because how long to give the other
device back is a decision about a person and not about a client. After the wait, the
ordinary scheme resumes exactly as it was: the strikes, the player gate, the cooldown, the
alternation. Nothing is skipped and nothing is added — the only change is WHEN.

**And the wait belongs to the client, not to this module.** Three things put a client
back: this decision, the process watchdog (`panel/__main__.py::_watchdog_check`) and the
`restart_game` errand, which `Schedule.gate` lets through precisely when the game looks
down. A hold only one of them respects is not a hold, so the deadline is a READING —
:meth:`Recovery.kick_hold_left` — and all three ask it.

…AND THE SIXTH, which is a reading rather than a cure: :meth:`Recovery.note_run`, the
count of errands that tried to press and pressed nothing. It is the only thing in that
morning's log that was ever true, and nothing was counting it.

THE SEVENTH (#1410): **a daemon that is DOWN had nobody to put it back.**

The branch above is about a daemon that ANSWERS while holding a client that has gone.
The other half — nothing answers the port at all — was nobody's business in a running
panel, and the reason is a circle: `GameLink.ensure()` is called from the errand path
(`panel/runtime/schedule.py`, `daemon.py`), and the gate (#1393) holds every errand
while the daemon is down. The one thing that would start it sits behind the gate that is
waiting for it. `note_daemon` cannot help either — its fault is a daemon that is UP.

Live on 2026-08-15 the client was relaunched at 00:21:42 and was back in the game by
00:22:16; the daemon stayed down for the next ten minutes and only came back when the
panel itself was restarted, and then in sixty seconds. The day before, the same hole was
2 min 42 s. Nothing was broken in the meantime — the timers did not fire, the triggers
did not poll, and the profile simply did not farm
(`docs/research/game-launch-and-scene-control.md` §6.2).

So :meth:`Recovery.note_daemon_down` is the third daemon reading, on its own run
(:data:`DOWN_STRIKES`) and the same cooldown as the other one, and its act is a START
rather than a restart — there is nothing there to shut down. It is deliberately NOT
asked about the client: a daemon binds its port whether or not a game is running (it
re-aims itself at one that appears), and «no client» is precisely the state where the
gate has to be open so the watchdog can put the client back.

WHAT MAY NOT START ONE is «Стоп всё»: stopping this profile's daemon is half of that
press, and a cure that undoes it eight seconds later is the bug #1393 exists to stop.
The caller feeds `down=False` while the profile is stopped — the same shape as the
kick's wait, where the state that must not be acted on never reaches the run at all.

WHAT IT DOES **NOT** DO. It does not pause the schedule, because the schedule already
pauses itself: while the client is not running, `Schedule.gate` holds every errand and
says `timers.log.skip_game`, and since #1259 it holds them PER ERRAND so the recovery
recipe is the one thing let through. That is the «режим пауз» this reuses rather than
reinventing — ordinary errands stop by themselves for as long as the restart takes and
start again on their own when the client is back, with no state to get stuck in.

It also does not decide whether the feature is ON: that is the profile's `watchdog`
switch, read by the caller. The panel's watchdog and this share it deliberately — from
the person's side they are one promise («поднимать игру при падении»), and a client that
is dead and one that is deaf are the same thing to whoever is not looking at the screen.
"""
from __future__ import annotations

import game_link

#: Consecutive `lost` readings before a restart is allowed. The status poll runs every
#: eight seconds, so three is about half a minute of a client that cannot be heard —
#: long enough to sit out a reconnect, short enough that an account is not idle for
#: hours. Deliberately larger than the strip's own announce threshold: saying «связь
#: пропала» costs a log line and being wrong about it costs nothing, while acting on it
#: costs a client.
STRIKES = 3

#: Seconds between two restarts of the same client. Ten minutes: a restart plus a login
#: is about a minute, so this leaves nine for the account to prove it can stay on before
#: anything touches it again.
COOLDOWN_SEC = 600.0

#: How recently somebody must have touched this machine for the client to be left alone.
#:
#: THE RESTART CLOSES THE WINDOW SOMEBODY MAY BE PLAYING IN. On 2026-08-06 it did: the
#: person logged in, the link dropped a couple of minutes later, and at 21:44:16 this
#: threw them out of the game to «fix» it. An account being played is not an account in
#: trouble, and the automation must never be the thing that ends a session.
#:
#: Five minutes of no keyboard and no mouse in the client's own Windows session. It does
#: NOT see somebody playing the same account from a PHONE — nothing local can — and that
#: case is worse, because restarting here takes the account back off them. Whether to
#: hold off on a kick for that reason is a decision for the person, written up in
#: docs/research/server-link-status.md rather than guessed at here.
PLAYER_QUIET_SEC = 300.0

#: Consecutive readings of «the daemon is attached to a client that is not the one
#: running» before it is restarted. Two, not three: unlike a link reading this is not an
#: inference — the two pids either match or they do not — and the only reason to wait at
#: all is that a daemon is legitimately a few seconds behind a client that has just been
#: replaced. The poll is eight seconds, so two is the shortest patience that survives
#: that and nothing more.
DAEMON_STRIKES = 2

#: Consecutive readings of «nothing answers this profile's port» before a daemon is
#: STARTED. Two, for the same reason as :data:`DAEMON_STRIKES` and one more of its own: a
#: daemon somebody else is already bringing up — the boot's own `ensure`, the «⭮» button,
#: «Включить обратно» — is down for the seconds that takes, and a start racing a start is
#: a second process that cannot bind the port. Two readings is sixteen seconds of the
#: status poll, which is longer than any of those needs to get the port bound.
DOWN_STRIKES = 2

#: How far the wait between two STARTS of a daemon may grow, in seconds. Half an hour.
#:
#: The first wait is :data:`DAEMON_COOLDOWN_SEC` and it doubles for as long as the starts
#: do not take, because some of them never will: a profile whose client lives in a
#: Windows session nobody is logged into answers «nobody is logged on as …» in a fraction
#: of a second, for ever. Live on 2026-08-15 that was one act, two `[daemon]` lines and a
#: hold, every two minutes, in a profile that could not have a daemon at all.
#:
#: A ceiling and not an abandonment: half an hour is still fifty attempts a day, and the
#: first reading of a daemon that answers puts the wait back to the ordinary one — so the
#: profile whose session comes back at lunchtime is farming again within the half hour,
#: with the log of the morning it could not costing thirty lines instead of seven hundred.
DOWN_WAIT_MAX_SEC = 1800.0

#: Seconds between two restarts of the same daemon. Two minutes rather than the client's
#: ten: a daemon comes back in under a second and takes nothing away from anybody, so the
#: cost of trying again soon is a log line — where a client restart costs a login and,
#: if somebody is playing, their session.
DAEMON_COOLDOWN_SEC = 120.0

#: Client restarts with the link never once coming back, before the blame moves to the
#: daemon. Two: the first restart is the ordinary cure and is usually right, the second
#: is already suspicious, and by the third the evidence that this is not the fault being
#: fixed is better than the evidence that it is. Live it took SIX before a person looked.
FRUITLESS = 2

#: Consecutive readings of «the client is showing the kick modal» before it is acted on.
#: Two, and for the same reason as :data:`DAEMON_STRIKES` rather than the link's three:
#: this is not an inference off a socket table but the game's OWN sentence, read out of
#: the dialog and matched against the client's own language tables
#: (`tools/lib/game_kick.py`). The only thing a second reading buys is not acting on a
#: single unlucky poll.
KICK_STRIKES = 2

#: How long a kicked client is left completely alone, in seconds. Fifteen minutes.
#:
#: THIS IS A WAIT FOR A PERSON, NOT FOR A MACHINE, and that is why it is minutes rather
#: than the seconds every other patience in this file is measured in. A kick means the
#: account is being played somewhere else; restarting takes it off whoever is playing,
#: and their client takes it straight back — the loop that ran three times over on
#: 2026-08-08 with `launch_game` timing out on each pass. Long enough that a person who
#: sat down to play gets a session rather than a fight, short enough that an account
#: taken by a device nobody is at is farming again within the quarter hour.
#:
#: A DEFAULT, not a rule: the panel reads `kick_hold_min` off the profile and writes it
#: into :attr:`Recovery.kick_hold_sec`, so a person who wants an hour (or nothing at all)
#: types it instead of editing this.
KICK_HOLD_SEC = 900.0

#: How much each kick that comes straight back ADDS to the wait, and how far it may grow.
#:
#: 15 → 30 → 45 MINUTES, and this is a policy that already existed and was never once
#: applied. It was written into the `session_kick` poll trigger (`panel/triggers.py`,
#: `BackoffPolicy`, #1142) — and no poll trigger had ever fired, because the marker was
#: matched against itself lowered (#1296). So for as long as it has existed, every kick
#: has drawn the same fifteen minutes, however many of them there were.
#:
#: It belongs HERE because this module is the one that acts. The person's own words were
#: about the fifteen minutes, and the reasoning is unchanged from the trigger's: somebody
#: is holding the account, and an account that keeps being taken back is an account two
#: clients are fighting over. Each round of that fight should cost more patience than the
#: last, and the escalation should be forgotten once a session finally holds.
KICK_HOLD_STEP_SEC = 900.0
KICK_HOLD_MAX_SEC = 2700.0

#: A kick this long or longer after the last one is a FRESH incident: the wait goes back
#: to :data:`KICK_HOLD_SEC`. Ten minutes — long enough that a session which held that
#: long was genuinely this client's, short enough that an evening of separate kicks is
#: not treated as one escalating fight.
KICK_STABILITY_SEC = 600.0

#: Errands that tried a counted press and fired NOTHING, before the panel says so.
#:
#: «Успешно ничего» is what the fifth form of this failure looks like from the log
#: (`docs/research/server-link-status.md` §5.3): every timer reports OK, every `TAP …
#: xall` answers `0 press(es)`, and the client is reading its own stale memory. It is
#: the same kind of evidence as :data:`FRUITLESS` — a cure, or here an errand, repeated
#: with nothing ever changing — and it is deliberately NOT a cure of its own: a healthy
#: account late in the day genuinely has nothing left to press, and restarting a client
#: for being finished would be the same mistake in the other direction.
#:
#: Eight is roughly «every errand on the clock has come round and done nothing», which
#: on a spent account is ordinary and on a deaf one is the only thing in the log that
#: was ever true.
BARREN = 8

#: HOW LONG A CLIENT MAY BE UP, CONNECTED AND STILL NOT IN A SESSION before it is put
#: back — the maintenance case (#1549), and the login screen with it.
#:
#: The state was recorded live on 2026-08-19 (docs/research/server-maintenance.md): the
#: process was there, the sockets were established, the daemon was warm, the panel's own
#: line read `game=up link=online daemon=warm` for the whole window — and the account was
#: not in the game, because the server was closed. Every reading this module already
#: takes says «fine». `link` is ONLINE, so :meth:`note` does nothing; there is no kick;
#: the daemon is neither stale nor down. **Nothing in the panel had a cure for it**, and
#: the operator's own instruction is the cure: «при техобслуживании клиент перезапускай
#: каждые 15 минут».
#:
#: Why a restart helps at all, since it plainly cannot reopen the server: a client left
#: on the maintenance dialog does not come back by itself when the door opens. The
#: restart is how the panel KNOCKS — and the account is playing again within a quarter
#: hour of the server returning instead of whenever somebody notices.
#:
#: The grace is deliberately longer than a login takes. `launch_game` waits up to 300 s
#: for `scene == city`, so anything shorter would fight an ordinary start-up and put a
#: client back that was three seconds from being in the game.
STALLED_GRACE_SEC = 420.0

#: …and how often it may be knocked on. The operator's own number, and the same one a
#: kick already uses, for a related reason: this is a wait on something outside the
#: machine, and there is nothing to be gained by asking more often than the thing can
#: change.
STALLED_COOLDOWN_SEC = 900.0


class Recovery:
    """One client's answer to «has it been deaf long enough to restart?»

    One instance per profile, kept by whoever polls the link. Not thread-safe on
    purpose — it is fed from the one poll that already exists, and a lock here would be
    a lock nobody needs.
    """

    __slots__ = ("_run", "_last", "_restarts", "_held", "_why", "_kicks",
                 "_stale_run", "_down_run", "_down_last", "_down_wait", "_down_held",
                 "_daemon_last", "_daemon_restarts", "_daemon_held",
                 "_fruitless", "_blame", "_kick_run", "_barren", "_barren_said",
                 "kick_hold_sec", "_kick_until", "_kick_armed", "_kick_held",
                 "_kick_wait", "_kick_acted",
                 "stalled_grace_sec", "stalled_cooldown_sec",
                 "_stalled_since", "_stalled_last", "_stalled_held",
                 "_stalled_restarts")

    def __init__(self) -> None:
        #: Consecutive `lost` readings so far.
        self._run = 0
        #: When the last restart was ASKED FOR, or 0.0 for never.
        self._last = 0.0
        #: How many this client has had. Shown, so «работает» and «перезапускается по
        #: кругу» cannot look the same on the strip.
        self._restarts = 0
        #: Whether the current run has already said «too soon», so the wait is reported
        #: once rather than every poll.
        self._held = False
        #: "" | "cooldown" | "player" — what the front-ends draw as the reason.
        self._why = ""
        #: How many of those restarts were a KICK rather than a silent hang-up.
        self._kicks = 0
        #: Consecutive readings of «the daemon names a client that is not running».
        self._stale_run = 0
        #: Consecutive readings of «nothing answers this profile's port» (#1410). Its own
        #: run, because it is the OTHER daemon fault and the two are never true at once:
        #: a daemon cannot both answer for the wrong client and not answer at all.
        self._down_run = 0
        #: When a daemon was last STARTED, and how long until another may be. Its own
        #: clock and its own wait, because this wait GROWS while the starts do not take
        #: — see :meth:`note_daemon_down`.
        self._down_last = 0.0
        self._down_wait = 0.0
        #: Whether the current wait has already been said. Its own flag for the same
        #: reason: `_daemon_held` is cleared by the stale branch on every poll, and a
        #: down daemon is never stale, so sharing it said the line every eight seconds.
        self._down_held = False
        #: When the daemon was last restarted, or 0.0 for never.
        self._daemon_last = 0.0
        #: How many daemon restarts this profile has had. Drawn beside the client's, so
        #: «перезапускается клиент по кругу» and «перезапускается демон по кругу» cannot
        #: be told apart by guessing.
        self._daemon_restarts = 0
        #: Whether the current daemon run has already said «too soon».
        self._daemon_held = False
        #: Client restarts since the link was last ONLINE. The count that moves the
        #: blame: a cure that has not worked twice is evidence about the diagnosis.
        self._fruitless = 0
        #: "" | "client" | "daemon" — WHAT this thinks is broken, for both front-ends.
        #: A person watching a restart is owed the answer to «что именно чинится».
        self._blame = ""
        #: Consecutive readings of the kick modal. Its own run, because a kick is its own
        #: state and is true at moments when the link reads perfectly ONLINE (#1270).
        self._kick_run = 0
        #: Errands in a row that tried a counted press and fired nothing at all.
        self._barren = 0
        #: Whether the current barren streak has already been said, so it is one line and
        #: not one a minute.
        self._barren_said = False
        #: How long a kick buys the client. Public and writable: the panel sets it from
        #: the profile's `kick_hold_min` on every poll, so an edit on the Settings page
        #: applies without a restart, exactly as every other knob there does.
        self.kick_hold_sec = KICK_HOLD_SEC
        #: When the current kick's wait runs out, or 0.0 for «no kick is being waited
        #: out». An ABSOLUTE deadline rather than a countdown, so it survives a client
        #: that goes offline mid-wait — which is precisely when the watchdog would
        #: otherwise put it back and undo the whole thing.
        self._kick_until = 0.0
        #: Whether THIS kick episode has already been given its wait. Without it an
        #: expired deadline would re-arm on the next reading — the modal is still on
        #: screen — and the client would be waited out for ever instead of restarted.
        self._kick_armed = False
        #: Whether the current wait has already been said, so it is one line and a
        #: counter on the strip rather than a line every eight seconds.
        self._kick_held = False
        # THE ADAPTIVE PART OF THE WAIT (#1296). `_kick_wait` is what the NEXT kick will
        # be given — `kick_hold_sec` for a fresh incident, a step more for each kick that
        # comes straight back, capped. `_kick_acted` is when this client was last put back
        # because of a kick, which is what «straight back» is measured from: the question
        # is whether the session HELD, and that is time after the restart rather than time
        # between two readings.
        self._kick_wait = 0.0
        self._kick_acted = 0.0
        # THE MAINTENANCE / LOGIN-SCREEN CASE (#1549). Public and writable like
        # `kick_hold_sec`, and for the same reason: how long to leave a closed server
        # alone is a decision about the world rather than about a client, so the panel
        # writes both off the profile on every poll.
        self.stalled_grace_sec = STALLED_GRACE_SEC
        self.stalled_cooldown_sec = STALLED_COOLDOWN_SEC
        #: When this client was first seen up-and-connected-but-not-playing, **-1.0 for
        #: «it is playing»**. An ABSOLUTE stamp rather than a run of readings: the session
        #: question is throttled to once every 24 s and the poll is faster than that, so
        #: counting readings would measure the poll and not the fault.
        #:
        #: The «never» value is -1 and not 0 on purpose. Every other clock in this file
        #: uses 0.0 because it is compared against `time.time()`, which is never zero —
        #: but this one is also the flag for «is it stalled at all», and `if not
        #: self._stalled_since` reads a legitimate stamp of zero as «no». The first draft
        #: did exactly that and never knocked once under a test clock starting at 0.
        self._stalled_since = -1.0
        #: When it was last knocked on, and whether the wait has already been said.
        self._stalled_last = 0.0
        self._stalled_held = False
        #: How many of the restarts above were this — drawn apart from the others,
        #: because «сервер закрыт, стучимся» and «клиент оглох» mean different things.
        self._stalled_restarts = 0

    # -- reading -------------------------------------------------------------
    @property
    def restarts(self) -> int:
        """How many restarts this client has been given since the panel opened."""
        return self._restarts

    @property
    def deaf_for(self) -> int:
        """Consecutive `lost` readings right now — 0 when the link is fine."""
        return self._run

    def kick_hold_left(self, now: float) -> int:
        """Seconds this client is still owed after a kick — 0 when nothing is owed.

        **The reading every restarter asks, and the whole reason the wait works.** Three
        different things put a client back: the decision in :meth:`note`, the process
        watchdog, and the `restart_game` errand that `Schedule.gate` deliberately lets
        through while the game looks down. A wait honoured by one of them is not a wait —
        the other two would relaunch the client inside the same minute and the person
        holding the account would be thrown out anyway, which is the bug (#1291).

        So it is a fact with a clock, not a branch: whoever is about to touch the client
        asks it first, and anything above zero means «not this one, not yet».
        """
        if not self._kick_until:
            return 0
        return max(0, int(self._kick_until - now))

    def state(self, now: float) -> dict:
        """What both front-ends draw: the run, the count, and the cooldown left.

        Data, not words — the window and the phone say it in their own language out of
        the same numbers (`CLAUDE.md`, «Not one word of the panel is written in the
        panel»).
        """
        left = 0
        if self._last:
            left = max(0, int(self._last + COOLDOWN_SEC - now))
        daemon_left = 0
        if self._daemon_last:
            daemon_left = max(0, int(self._daemon_last + DAEMON_COOLDOWN_SEC - now))
        # …and the start's own wait, which is a different clock and can be far longer
        # (#1410). ONE number on the strip, because from outside there is one daemon and
        # one «сколько ещё ждать» — the larger of the two is the honest answer.
        daemon_left = max(daemon_left, int(self.down_wait_left(now)))
        return {"deaf_for": self._run, "strikes": STRIKES,
                "restarts": self._restarts, "kicks": self._kicks,
                "cooldown_left": left,
                # Why nothing is happening, when nothing is: the person asked to see
                # that a restart is being WITHHELD rather than simply not occurring.
                "held_by": self._why,
                # …and WHAT is being blamed, which is the other half of the same
                # question and the one nothing could answer before #1268. A client
                # restart and a daemon restart look identical from outside — both are
                # «панель что-то перезапускает» — and they mean opposite things about
                # where the fault is.
                "blame": self._blame,
                "daemon_stale": self._stale_run,
                "daemon_strikes": DAEMON_STRIKES,
                # …and the other daemon fault, which has to be its own number on both
                # front-ends: «держит не тот клиент» and «не отвечает вовсе» are drawn
                # off `blame == daemon` alike, and a strip that says the first while the
                # second is true sends a person looking for a process that is not there.
                "daemon_down": self._down_run,
                "down_strikes": DOWN_STRIKES,
                "daemon_restarts": self._daemon_restarts,
                "daemon_cooldown_left": daemon_left,
                # …and how long the account is being left to whoever took it. Drawn on
                # both front-ends with a countdown, because «панель ничего не делает» and
                # «панель ждёт четырнадцать минут» look identical otherwise — and the
                # person waiting is usually the one who took the account (#1291).
                "kick_hold_left": self.kick_hold_left(now),
                "kick_hold_of": int(self.kick_hold_sec),
                # How many client restarts have been spent without the link ever coming
                # back. Shown because it is the evidence, not the verdict: a person
                # seeing «2 подряд впустую» can tell that the panel is about to change
                # its mind, and why.
                "fruitless": self._fruitless,
                # …and the reading that says nothing is reaching the game at all, while
                # every other one still looks healthy: errands that pressed nothing.
                "barren": self._barren, "barren_of": BARREN,
                # …AND THE CLOSED-DOOR CASE (#1549): how long this client has been up,
                # connected and not in the game, how long until the next knock, and how
                # many knocks it has had. Its own three numbers rather than a share of
                # the client's, because every other restart in this module means «что-то
                # сломано» and this one means «сервер закрыт, ждём» — and a person told
                # the wrong one of those does the wrong thing about it.
                "stalled_for": self.stalled_for(now),
                "stalled_of": int(self.stalled_grace_sec),
                "stalled_next": self.stalled_next(now),
                "stalled_restarts": self._stalled_restarts}

    def stalled_for(self, now: float) -> int:
        """Seconds this client has been up-and-connected without being in a session."""
        if self._stalled_since < 0:
            return 0
        return int(max(0.0, now - self._stalled_since))

    def stalled_next(self, now: float) -> int:
        """Seconds until the next knock — 0 when one may be made right now."""
        if self._stalled_since < 0:
            return 0
        due = self._stalled_since + self.stalled_grace_sec
        if self._stalled_last:
            due = max(due, self._stalled_last + self.stalled_cooldown_sec)
        return max(0, int(due - now))

    # -- deciding ------------------------------------------------------------
    def note(self, link: str, now: float,
             idle_sec: "float | None" = None,
             kicked: bool = False) -> "tuple | None":
        """Feed one link reading. Returns what to SAY and DO, or ``None`` for nothing.

        The answer is `(locale_key, fmt)` when something should be said, and the caller
        restarts the client exactly when the key is :data:`ACT` — one return value for
        both, so a caller cannot act without saying why, which is the whole of what went
        wrong the day nothing was said and nothing was done.

        **`kicked` is not a footnote on a lost link — it is a state of its own** (#1270).
        It used to be read only while `link == lost`, and a kick behind ONE surviving
        socket therefore reads `online`: the account was taken at ~04:38 on 2026-08-07,
        the strip said online, and nothing asked the one flag that knew until a person
        looked at 07:27. So a positive kick is «deaf» whatever the sockets say, on its
        own shorter patience (:data:`KICK_STRIKES`) — it is the game's own sentence
        rather than an inference — and every gate below it is unchanged: the person at
        the machine still wins, the cooldown still holds, and the cure is still the one
        act that was already wired.

        The one state a kick may NOT override is `offline`: no process, nothing on
        screen, and therefore nothing that can be showing a modal. That reading belongs
        to the watchdog and two things must not relaunch one client — the rule this
        module has kept since it was written, and a `kicked` left over from the poll
        before must not be the thing that breaks it.
        """
        kicked = bool(kicked) and link != game_link.OFFLINE
        if link == game_link.ONLINE and not kicked:
            # The cure WORKED — whatever it was. This is the only reading that clears
            # the fruitless count, and it has to be ONLINE rather than «not lost»: a
            # client that has just been relaunched is `offline` and then `unknown` for
            # most of a minute on its way to either outcome, and counting those as
            # success would reset the evidence every single restart and the blame would
            # never move.
            self._fruitless = 0
            self._blame = ""
            # …and the kick's wait is over the moment the account is demonstrably ours
            # again. ONLINE **and** no modal is the only reading that says so; a client
            # that has merely gone offline mid-wait proves nothing and must keep its
            # wait, or the watchdog puts it straight back (#1291).
            self._kick_clear()

        if kicked:
            self._kick_run += 1
        else:
            self._kick_run = 0

        if link != game_link.LOST and not kicked:
            # Anything else ends the run — including `offline`, which is the PROCESS
            # being gone and the watchdog's business, not this one's. Two things must
            # not both relaunch the same client.
            self._run = 0
            self._held = False
            # …but a kick's wait outlives the reading that started it, and so must the
            # word for it: a client that went offline mid-wait (the person closed it, or
            # it gave up) is still being waited out, and a strip that went blank here
            # would say «nothing is happening» through the fifteen minutes when
            # something very deliberately is (#1291).
            self._why = "kick" if self.kick_hold_left(now) > 0 else ""
            return None

        if link == game_link.LOST:
            self._run += 1
        # A kick and a hang-up can be true at once — the sockets went AND the modal is
        # up, which is the ordinary shape of a kick — so the run each of them has to
        # clear is checked separately and whichever is satisfied first decides. A kick
        # is the shorter of the two because it is a reading of the game's own words.
        if self._run < STRIKES and self._kick_run < KICK_STRIKES:
            return None

        # SOMEBODY IS AT THE MACHINE. Not a reason to restart — a reason not to: the
        # restart would close the window they are playing in, which is what it did once.
        #
        # STILL FIRST, in front of the kick's own wait (#1291), because the two hold for
        # different lengths of time and this is the one that has no end: the wait runs
        # out after fifteen minutes and this lasts exactly as long as somebody keeps
        # touching the keyboard. Reaching the wait first would start its clock under a
        # person who is still playing and act the moment they paused. The two are about
        # different people anyway — this one is at THIS machine, the kick is on another
        # device (#1268) — and neither replaces the other.
        if idle_sec is not None and idle_sec < PLAYER_QUIET_SEC:
            if self._why == "player":
                return None
            self._why = "player"
            return (BUSY, {"mins": int((PLAYER_QUIET_SEC - idle_sec) // 60) + 1})

        # A KICK IS SOMEBODY ELSE'S SESSION, AND IT GETS ITS TIME (#1291). Everything
        # below this — the cooldown, the alternation — is about a client that has lost
        # the server on its own. A kick has an author, and taking the account back off
        # them in half a minute starts a fight neither side can win: their client kicks
        # this one back, this one restarts again, and the log fills with `launch_game`
        # timeouts while a person tries to play.
        #
        # Armed once per episode and only on a run of readings, exactly like the act it
        # replaces: a single unlucky poll must not cost a quarter of an hour of farming
        # any more than it may cost a restart. Zero minutes disarms the whole thing for
        # whoever wants the old behaviour back — that is what a setting is for.
        if kicked and not self._kick_armed:
            self._kick_armed = True
            self._kick_until = now + self._kick_next_wait(now)
            self._kick_held = False
        left = self.kick_hold_left(now)
        if left > 0:
            # Said ONCE per wait and re-checked every poll — the shape the cooldown
            # already has, and for the reason written there: a hold that suppresses the
            # act along with the sentence is a client nobody ever comes back to.
            self._why = "kick"
            if self._kick_held:
                return None
            self._kick_held = True
            # Rounded UP, not «floor plus one» like the cooldowns above: those count
            # down from a number nobody was told, while this one is announced the
            # instant it is armed, and «жду 16 минут» out of a fifteen-minute setting
            # is the panel disagreeing with the field the person typed it in.
            return (HOLD_KICK, {"mins": -(-left // 60)})

        since = now - self._last if self._last else None
        if since is not None and since < COOLDOWN_SEC:
            # Waiting. Said ONCE per wait, not once a poll — but the wait is re-checked
            # every time, which is the whole of the bug that was here: `_held` used to
            # suppress the ACT as well, so a link that never came back was restarted
            # once, told «жду 7 мин» once, and then left alone FOR EVER. Live, on
            # 2026-08-06, that left a deaf client sitting from 21:47 with the cooldown
            # long expired and the schedule failing every errand against it.
            self._why = "cooldown"
            if self._held:
                return None
            self._held = True
            return (HOLD, {"mins": int((COOLDOWN_SEC - since) // 60) + 1})

        # THE CURE HAS NOT WORKED, SO TRY THE OTHER ONE. Two client restarts with the
        # link never once coming back say more about the diagnosis than about the
        # client, and the thing nobody had tried is one port away. This is the guard
        # that turns six identical restarts into an ALTERNATION (#1268).
        #
        # Alternation, not replacement, and the difference is the whole safety of it.
        # Booking the daemon and leaving the count where it was would mean the client is
        # never restarted again — one stuck loop swapped for another, and worse, because
        # the client cure is the one that works most of the time. So the count resets
        # here: client, client, daemon, client, client, daemon… Neither cure is ever
        # abandoned, and no cure is repeated more than :data:`FRUITLESS` times without
        # something else being tried in between. `test_a_link_that_never_comes_back_is_
        # retried_after_every_cooldown` is what says so — it caught exactly this
        # regression in the first draft of this branch.
        #
        # Booked against the DAEMON's clock and the client's counters are left alone:
        # this is not a client restart being withheld, it is a different act.
        #
        # A KICK IS EXEMPT, because the alternation exists for a diagnosis nobody has.
        # Here there is one, in the game's own words: the account is on another device,
        # and no daemon on this machine has anything to do with that. Restarting it
        # would be reaching for the wrong thing on purpose — the mistake #1268 is about,
        # committed with the evidence in hand.
        if self._fruitless >= FRUITLESS and not kicked:
            self._blame = "daemon"
            since_d = now - self._daemon_last if self._daemon_last else None
            if since_d is not None and since_d < DAEMON_COOLDOWN_SEC:
                self._why = "daemon_cooldown"
                if self._daemon_held:
                    return None
                self._daemon_held = True
                return (HOLD_DAEMON,
                        {"mins": int((DAEMON_COOLDOWN_SEC - since_d) // 60) + 1})
            spent = self._fruitless
            self._daemon_last = now
            self._daemon_restarts += 1
            self._daemon_held = False
            self._fruitless = 0              # …so the client is tried again next round
            self._run = 0
            self._kick_run = 0
            self._held = False
            self._why = ""
            return (ACT_DAEMON_STUCK, {"n": spent})

        self._last = now
        self._restarts += 1
        self._fruitless += 1                 # …until a reading says ONLINE
        self._blame = "client"
        self._run = 0                        # the next reading starts a fresh run
        self._kick_run = 0
        # …and the wait is spent. A kick that survives this restart is a NEW episode and
        # buys its own fifteen minutes: the account is still on the other device, and the
        # answer to that is the same answer as the first time.
        self._kick_clear()
        self._held = False
        self._why = ""
        # The two are the same act and NOT the same event, so they are not the same
        # sentence: «связь пропала» is the server having stopped answering, and
        # «вход с другого устройства» is somebody holding the account. A log that
        # says which is a log somebody can act on.
        if kicked:
            self._kicks += 1
            return (ACT_KICK, {})
        return (ACT, {"secs": STRIKES * 8})

    def note_session(self, playing: "bool | None", link: str, now: float,
                     idle_sec: "float | None" = None) -> "tuple | None":
        """The client is up and connected — but is it IN THE GAME? (#1549)

        THE STATE NOTHING HAD A CURE FOR. Every other branch in this module is fed by a
        reading that goes bad: the sockets half-close, the account is taken, the daemon
        points at a dead pid. Server maintenance breaks none of them. Recorded live
        (docs/research/server-maintenance.md): `game=up link=online daemon=warm` for the
        whole window, no kick, no stale daemon — and the account sitting on «Сервер
        находится на техническом обслуживании» while every errand failed one by one.

        So this asks the one question the others do not: is the client PLAYING. The
        answer comes from `game_clock.session_state` by way of the panel's own poll, in
        three values and all three matter:

        * ``True``  — in a session. The clock is cleared and nothing is owed.
        * ``False`` — the login screen, demonstrably. The state this cures.
        * ``None``  — nobody could ask (the VM will not answer, which is ALSO what
          maintenance looks like from here). Treated as not-playing, deliberately: a
          client the panel cannot talk to for seven minutes is no more use than one at
          the login screen, and the cure is the same knock.

        **A restart cannot reopen a server, and that is not what it is for.** A client
        left on the maintenance dialog stays there after the door opens; the knock is how
        the account is playing again within a quarter hour of the server coming back
        rather than whenever somebody notices.

        Every gate the other cures have applies here unchanged and in the same order:
        an OFFLINE or LOST client is somebody else's business (the watchdog's, and
        :meth:`note`'s), a person at the machine wins, and a kick's wait is not
        interrupted to knock on a door.
        """
        if link != game_link.ONLINE:
            # Not this branch's client: no process, or a link that has gone. Both have
            # their own cure and two of them must not restart one client.
            self._stalled_clear()
            return None
        if playing:
            # It is in the game. Whatever this was, it is over — including the count,
            # so a day with three separate maintenance windows reads as three.
            self._stalled_clear()
            return None
        if self._stalled_since < 0:
            self._stalled_since = now
            return None
        if self.stalled_next(now) > 0:
            return None

        # SOMEBODY IS AT THE MACHINE — the same first gate as every other cure here, and
        # first for the same reason: this would close the window they are looking at, and
        # a person staring at a maintenance dialog is exactly the person most likely to
        # be sitting in front of one.
        if idle_sec is not None and idle_sec < PLAYER_QUIET_SEC:
            self._why = "player"
            return None
        # …AND A KICK'S WAIT IS NOT INTERRUPTED TO KNOCK ON A DOOR (#1291). A kicked
        # client is not in a session either, so without this the two cures would take
        # turns on the same client and the kick's whole patience would be spent.
        if self.kick_hold_left(now) > 0:
            self._why = "kick"
            return None

        self._stalled_last = now
        self._stalled_restarts += 1
        self._restarts += 1
        self._held = False
        self._why = "stalled"
        self._blame = "client"
        return (ACT_STALLED, {"mins": int(self.stalled_for(now) // 60),
                              "again": int(self.stalled_cooldown_sec // 60),
                              "n": self._stalled_restarts})

    def _stalled_clear(self) -> None:
        """It is playing (or gone): forget the clock, the wait and the count."""
        self._stalled_since = -1.0
        self._stalled_last = 0.0
        self._stalled_held = False
        self._stalled_restarts = 0
        if self._why == "stalled":
            self._why = ""

    def _kick_next_wait(self, now: float) -> float:
        """How long THIS kick is given — 15 → 30 → 45 min while they keep coming back.

        The policy the `session_kick` trigger carried and never once applied: no poll
        trigger had ever fired (#1296), so every kick there has ever been drew the same
        fifteen minutes however many of them there were. It lives here now, in the module
        that actually acts.

        Measured from the last time this client was PUT BACK because of a kick, not from
        the last reading — the question is «did the session hold?», and that is time after
        the restart. A kick sooner than :data:`KICK_STABILITY_SEC` after one is the same
        fight returning and costs a step more patience, capped at :data:`KICK_HOLD_MAX_SEC`;
        a kick later than that is a fresh incident and goes back to the profile's own
        `kick_hold_sec`.

        Zero disarms everything, exactly as before: a person who sets the hold to nothing
        gets no wait and no escalation either.
        """
        base = max(0.0, self.kick_hold_sec)
        if base <= 0:
            self._kick_wait = 0.0
            return 0.0
        if not self._kick_acted or (now - self._kick_acted) >= KICK_STABILITY_SEC:
            self._kick_wait = base
        else:
            grown = (self._kick_wait or base) + KICK_HOLD_STEP_SEC
            self._kick_wait = min(grown, max(base, KICK_HOLD_MAX_SEC))
        return self._kick_wait

    def note_kick_restart(self, now: float) -> None:
        """The client was just put back BECAUSE of a kick — start the stability clock.

        Called by whoever carries the act out, beside its own bookkeeping: this module
        decides and says, it never restarts anything itself, so it cannot know the moment
        on its own. Without this call the escalation never escalates — every kick would
        look like a fresh incident — which is precisely the shape the unapplied policy
        had.
        """
        self._kick_acted = now

    def _kick_clear(self) -> None:
        """Forget the current kick episode — its wait, and that it had one.

        The ESCALATION is deliberately not cleared here: this runs when the client comes
        back online, and «the client is up» is not yet «the session held». What forgets the
        escalation is time — :data:`KICK_STABILITY_SEC` of it, measured in
        :meth:`_kick_next_wait` — because that is the only evidence that the other device
        has actually let go.
        """
        self._kick_until = 0.0
        self._kick_armed = False
        self._kick_held = False
        if self._why == "kick":
            self._why = ""

    def note_run(self, tried: int, fired: int) -> "tuple | None":
        """Feed the outcome of one errand: counted presses ATTEMPTED, and presses MADE.

        «Успешно ничего» — the shape the fifth form of this failure had in the log
        (`docs/research/server-link-status.md` §5.3). Every timer reported OK and every
        one of them answered `TAP … xall -> 0 press(es)`, because the client was reading
        its own stale memory: the quota it thought it had spent, the list it thought was
        empty. Nothing in the panel counted that, so from outside two and a quarter hours
        of doing nothing looked exactly like two and a quarter hours of having nothing
        left to do.

        **Evidence, never a cure**, and that is the whole design of it. A healthy account
        late in the day genuinely presses nothing all evening; restarting a client for
        being finished would be the same mistake this file is about, made in the other
        direction. So :data:`BARREN` errands in a row that tried and fired nothing earn a
        SENTENCE — once per streak, drawn by both front-ends while it lasts — and the
        acts stay where they are.

        Only COUNTED presses are fed here. A plain `TAP x3` fires blind and learns
        nothing about whether the game noticed, so it is evidence of neither kind; a
        gated one (`xall`, a batch) reads the button's own count in the same call it
        presses, which is what makes a zero mean something.
        """
        if tried <= 0:
            return None                      # nothing was attempted — no evidence either way
        if fired > 0:
            self._barren = 0
            self._barren_said = False
            return None
        self._barren += 1
        if self._barren < BARREN or self._barren_said:
            return None
        self._barren_said = True
        return (SAY_BARREN, {"n": self._barren})

    def note_daemon(self, stale: bool, now: float) -> "tuple | None":
        """Feed one reading of «is the daemon on the client that is actually running?»

        ``stale`` is a FACT the caller established by comparing two pids — the one
        `{"op":"ping"}` names and the one the status poll found — not a guess. ``False``
        covers both «they match» and «there is nothing to compare», because a daemon that
        is down, or a machine with no client running, is not this fault and must not be
        restarted on the strength of an unanswered question.

        Returns `(locale_key, fmt)` or ``None``, exactly like :meth:`note`; the caller
        restarts the DAEMON when the key is in :data:`DAEMON_RESTARTS`.

        Why this is a separate reading rather than another branch of :meth:`note`: it is
        true at times when the link is perfectly ONLINE. That was the live shape of it —
        six sockets established, the strip saying «онлайн», and every errand failing —
        and a decision hung off `link == lost` would never once have been asked.
        """
        if not stale:
            self._stale_run = 0
            self._daemon_held = False
            if self._why.startswith("daemon"):
                self._why = ""
            if self._blame == "daemon":
                self._blame = ""
            return None

        self._stale_run += 1
        self._blame = "daemon"
        if self._stale_run < DAEMON_STRIKES:
            return None

        since = now - self._daemon_last if self._daemon_last else None
        if since is not None and since < DAEMON_COOLDOWN_SEC:
            # Same shape as the client's wait, and the same bug avoided: the hold is
            # re-checked every reading and only the SENTENCE is suppressed, so a daemon
            # that stays stale is restarted again the moment the cooldown expires
            # rather than being told about once and abandoned.
            self._why = "daemon_cooldown"
            if self._daemon_held:
                return None
            self._daemon_held = True
            return (HOLD_DAEMON, {"mins": int((DAEMON_COOLDOWN_SEC - since) // 60) + 1})

        self._daemon_last = now
        self._daemon_restarts += 1
        self._stale_run = 0
        self._daemon_held = False
        self._why = ""
        return (ACT_DAEMON, {})

    def note_daemon_down(self, down: bool, now: float) -> "tuple | None":
        """Feed one reading of «does anything answer this profile's port at all?» (#1410)

        ``down`` is a FACT the caller established by probing the port, with one thing
        already decided for it: a profile somebody has stopped with «Стоп всё» feeds
        ``False``, because its daemon is down BECAUSE it was stopped, and putting it back
        is undoing the press rather than curing a fault.

        Returns `(locale_key, fmt)` or ``None``, exactly like :meth:`note_daemon`; the
        caller STARTS a daemon when the key is in :data:`DAEMON_STARTS` — never restarts
        one, because there is nothing there to shut down and the log would say so.

        Deliberately blind to the client. A daemon binds its port whether or not a game
        is running and re-aims itself at one that appears, and «no client» is exactly the
        state where the port has to answer: with it dead the gate holds every errand, and
        the watchdog's own relaunch is one of them.

        On the SAME cooldown as the other daemon cure, and on purpose: there is one
        daemon per profile, so «it was touched two minutes ago» is one fact about one
        thing. A start that does not take — a Windows session nobody is logged into, an
        interpreter that is not there — is therefore retried every
        :data:`DAEMON_COOLDOWN_SEC` for as long as it keeps failing, with a line each
        time. That is the same promise the client's cure makes, for the same reason: a
        cure that is tried once and then abandoned is how a profile spends a night doing
        nothing while the panel believes it has done its part.
        """
        if not down:
            self._down_run = 0
            self._down_held = False
            # …and the growth is spent: a port that answers is the only evidence there is
            # that a start took, so the NEXT incident begins at the ordinary wait again.
            self._down_wait = 0.0
            if self._why.startswith("daemon"):
                self._why = ""
            if self._blame == "daemon" and not self._stale_run:
                self._blame = ""
            return None

        self._down_run += 1
        self._blame = "daemon"
        if self._down_run < DOWN_STRIKES:
            return None

        left = self.down_wait_left(now)
        if left > 0:
            # ITS OWN «said once», and that is not tidiness (#1410). `_daemon_held`
            # belongs to the stale branch, which is fed on every poll too and clears the
            # flag whenever the daemon is not stale — a daemon that is DOWN is never
            # stale, so the two together said this line every eight seconds. Live for a
            # minute and a half before it was noticed.
            self._why = "daemon_cooldown"
            if self._down_held:
                return None
            self._down_held = True
            return (HOLD_DAEMON_DOWN, {"mins": int(left // 60) + 1})

        # THE PREVIOUS START DID NOT TAKE, and this is the only place that can tell:
        # the daemon is down and one was already asked for. Some of them never will —
        # a profile whose client lives in a Windows session nobody is logged into fails
        # in a fraction of a second, every time, for ever — so the wait doubles rather
        # than the panel repeating the same two minutes all night. It is still never
        # abandoned: :data:`DOWN_WAIT_MAX_SEC` is the ceiling, and the first reading of a
        # daemon that answers puts it back to the ordinary wait.
        # A zero wait means the last start TOOK — or that there has not been one. Either
        # way this is a fresh incident and gets the ordinary two minutes; anything else
        # is the same incident going round again.
        self._down_wait = (min(self._down_wait * 2, DOWN_WAIT_MAX_SEC)
                           if self._down_wait else DAEMON_COOLDOWN_SEC)
        self._down_last = now
        self._daemon_restarts += 1
        self._down_run = 0
        self._down_held = False
        self._why = ""
        return (ACT_DAEMON_DOWN, {})

    def down_wait_left(self, now: float) -> float:
        """Seconds before another daemon may be STARTED — 0.0 when one may be now."""
        if not self._down_last:
            return 0.0
        wait = self._down_wait or DAEMON_COOLDOWN_SEC
        return max(0.0, self._down_last + wait - now)


#: The panel says this and then plays `restart_game`.
ACT = "log.game.deaf_restart"
#: …and this when it may not yet, so a wait never looks like nothing happening.
HOLD = "log.game.deaf_hold"
#: …and this when somebody is playing. The client is left exactly alone.
BUSY = "log.game.deaf_busy"
#: The same act, a different event: the client was KICKED — the account was logged in
#: somewhere else and the client is showing the game's own «вход с другого устройства»
#: (`tools/lib/game_kick.py`, the game's key `E100083`). Worth its own sentence,
#: because «связь пропала» and «у вас забрали аккаунт» want different things done.
ACT_KICK = "log.game.kick_restart"

#: …AND THE CLOSED DOOR (#1549). Its own key rather than a share of `ACT`, because it is
#: the one restart in this module that does not mean anything is broken: the client is
#: fine, the server is shut, and the knock is how the panel finds out it has opened.
ACT_STALLED = "log.game.stalled_restart"
#: …and the wait in front of it: the account is on another device, and it is being left
#: there for :data:`KICK_HOLD_SEC` before anything is done about it (#1291). Said once
#: per kick with the minutes left, and drawn as a countdown by both front-ends — a panel
#: that has decided to do nothing for a quarter of an hour and says nothing about it is
#: indistinguishable from one that has not noticed.
HOLD_KICK = "log.game.kick_hold"

#: The daemon is attached to a client that is not there — the positive reading, two pids
#: that do not match. Restarting the CLIENT here is the six-times mistake (#1268).
ACT_DAEMON = "log.game.daemon_restart"
#: …and the cumulative one: this many client restarts have not brought the link back, so
#: the thing being restarted is not the thing that is broken. Says the count, because the
#: count is the argument.
ACT_DAEMON_STUCK = "log.game.daemon_after_restarts"
#: …and the daemon's own «too soon», so its wait is never silent either.
HOLD_DAEMON = "log.game.daemon_hold"

#: NOTHING answers the port — the other daemon fault, and the one a running panel had no
#: cure for at all (#1410). The act is a START: `ensure()`, not `restart()`, because there
#: is no daemon there to be shut down and a «перезапускаю» over an empty port is a
#: sentence that sends the next reader looking for a process that never existed.
ACT_DAEMON_DOWN = "log.game.daemon_down"
#: …and its own «too soon». Its own key rather than :data:`HOLD_DAEMON`, because the two
#: waits are in front of different acts: one is a restart held, this one is a start held,
#: and a person reading «недавно уже перезапускался» over a daemon that has not been
#: running at all is being told something that did not happen.
HOLD_DAEMON_DOWN = "log.game.daemon_down_hold"

#: Errands keep succeeding at nothing. Says the count and NOTHING ELSE — see
#: :meth:`Recovery.note_run` for why this one may not become an act.
SAY_BARREN = "log.game.barren"

#: EVERY answer that means «restart the client now». A caller asks this set, never one
#: constant: :data:`ACT_KICK` was added beside :data:`ACT` and the panel went on testing
#: `key == ACT`, so from 2026-08-06 a kicked client was TOLD to restart and never was —
#: the sentence went into the log, `note` booked the restart (the counter went up and
#: the ten-minute cooldown started), and nothing touched the client. Live that left it
#: deaf from 22:48 to 23:07, when it finally died on its own and the process watchdog —
#: the other half — picked it up. A third act is one line here and works everywhere.
RESTARTS = frozenset({ACT, ACT_KICK, ACT_STALLED})

#: …and the subset that means «this restart is because the account was TAKEN». Asked as a
#: set for the same reason as above: `key == ACT` is what once left a kicked client
#: announced and never restarted, and a caller comparing against one constant is a caller
#: that will be wrong the day a second kick act appears. What hangs off it is the
#: escalating wait — see `Recovery.note_kick_restart`.
KICK_ACTS = frozenset({ACT_KICK})

#: …and every answer that means «restart the DAEMON now». Kept as its own set for the
#: same reason the other one exists rather than as an `if key == …`: the two acts arrive
#: from two different methods and a caller that tested one constant would wire half of
#: it, which is precisely the bug this file already carries a paragraph about.
DAEMON_RESTARTS = frozenset({ACT_DAEMON, ACT_DAEMON_STUCK})

#: …and every answer that means «START a daemon now» — a third family, because it is a
#: third ACT and not a third way of saying one of the two above. A daemon that is down is
#: started (`GameLink.ensure`), never restarted: `restart` shuts one down first, and over
#: an empty port that is a shutdown that fails, a line saying so, and a start that would
#: have happened anyway. Its own set for the reason the other two have one — a caller
#: asks which family a key is in, so a fourth act cannot end up announced and never done.
DAEMON_STARTS = frozenset({ACT_DAEMON_DOWN})

#: …and the answers that are only ever SAID. A set of its own rather than «everything not
#: in the others», so that adding an act and forgetting to wire it fails loudly instead
#: of quietly becoming a sentence — which is exactly how `ACT_KICK` spent a night being
#: announced and never performed. A key in none of the four sets is a bug, and
#: `tests/test_panel_recovery.py` says so.
SAYINGS = frozenset({SAY_BARREN})
