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
  the fault itself, stated. It cannot happen any more — the panel attaches to the client
  itself and follows it across a restart (#1911) — and the reading is gone with it;
* **the cumulative one — the cure is not working.** Client restarts with the link never
  once coming back are counted and drawn (`fruitless`), because «второй впустую» is worth
  seeing. Until #1911 they moved the blame onto the daemon; there is no daemon to blame
  now, so the count informs and decides nothing.

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
ordinary scheme resumes exactly as it was: the strikes, the player gate and the cooldown. Nothing is skipped and nothing is added — the only change is WHEN.

**And the wait belongs to the client, not to this module.** Three things put a client
back: this decision, the process watchdog (`panel/__main__.py::_watchdog_check`) and the
`restart_game` errand, which `Schedule.gate` lets through precisely when the game looks
down. A hold only one of them respects is not a hold, so the deadline is a READING —
:meth:`Recovery.kick_hold_left` — and all three ask it.

…AND THE SIXTH, which is a reading rather than a cure: :meth:`Recovery.note_run`, the
count of errands that tried to press and pressed nothing. It is the only thing in that
morning's log that was ever true, and nothing was counting it.

THE SEVENTH, AND IT DELETED THE OTHER SIX HALVES (#1911): **there is no daemon.**

Everything above about a daemon — one holding a client that has gone, one nothing
answers at all, the alternation that moved the blame between the two cures, the wait
that doubled to half an hour while the starts kept failing — described a process that no
longer exists. The panel holds the client itself (`panel/runtime/lua_service.py`), so
«the panel is running» and «the link is there» are one fact, and the only thing left to
restart is the CLIENT.

What replaced the readings is one verdict, made by the status poll out of two
independent questions (`tools/lib/profile_health.py`): does a chunk land in the client's
VM, and does the game SERVER answer a question only it can answer. This module is fed
the amber those two make together — «there is a client and the server is silent» — and
never the amber that means our own attach is broken, because the cure for our bug is a
fix and not a relaunch.

THE SOCKET TABLE IS GONE FROM THE EVIDENCE ENTIRELY. It cannot say which conversation is
the game: on 2026-08-24 `classify` read `lost` for hours while the server answered every
probe, and the gate built on it refused every rally join the profile had (#1910).

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
import profile_health

#: Consecutive `lost` readings before a restart is allowed. The status poll runs every
#: eight seconds, so three is about half a minute of a client that cannot be heard —
#: long enough to sit out a reconnect, short enough that an account is not idle for
#: hours. Deliberately larger than the strip's own announce threshold: saying «связь
#: пропала» costs a log line and being wrong about it costs nothing, while acting on it
#: costs a client.
#:
#: FIVE SINCE #1910, and the number is the smaller half of the change. «Не слышен
#: серверу 24 с» was `STRIKES * 8` — three readings at the poll's nominal rate — and the
#: operator's report is that it fires on clients that are alive. So the run is longer AND
#: it must SPAN :data:`LOST_SPAN_SEC` of wall clock, because readings are not time: the
#: socket table is shared and cached (`game_link.MACHINE_TTL_SEC`), and #1702 measured an
#: announce and a restart eight seconds apart under a rule that claimed twenty-four.
#:
#: And the run is no longer sufficient BY ITSELF — see :data:`PROBE_FAILS`. Sockets are
#: one family of evidence; a restart now needs two.
STRIKES = 5

#: …and how long that run must cover. A minute of a client that cannot be heard, MEASURED
#: rather than multiplied out of the poll interval.
LOST_SPAN_SEC = 60.0

#: …AND THE SAME QUESTION FOR A CLIENT NOTHING REACHES AT ALL (#2578). The branch that
#: ends in :data:`ACT_HUNG` is the ONE branch with no second opinion behind it: the
#: confirmation rides the client's own Lua VM, and `unprobeable` means precisely that
#: nothing gets into that VM, so the probe is skipped and the minute above is the whole
#: of the evidence. A minute is not enough, because it is also what a client that is
#: still LOADING looks like from outside — nothing enters its VM either, for exactly the
#: same reason and with exactly the same readings.
#:
#: Measured live on 2026-09-06, a second account's client on a machine already running
#: one: 307 s from the launcher spawning it to the game server answering, its working
#: set climbing 74 → 1027 MB the whole way. The old minute fired at 65 s, five times over,
#: and every one of those restarts killed a client that was four fifths of the way up.
#: Ten minutes is that measurement with room to spare rather than a number chosen to
#: clear it — a slower disk, a bigger patch or a colder cache all land inside it, and a
#: client that is genuinely wedged is still put back inside the same quarter hour.
#:
#: NOT a licence to widen the ordinary branch: a client whose SOCKETS went is answered by
#: the probe, which is a question and not a guess, and it keeps its minute.
HUNG_SPAN_SEC = 600.0

#: HOW MANY SERVER PROBES MUST FAIL before a client is called deaf (#1910).
#:
#: The second, independent family of evidence, and the one that is active rather than
#: inferred: ask the game SERVER something only it can answer and require the answer.
#: `read_server_info` about somebody else's warzone is that question — the client holds
#: its own warzone's opening moment and answers about it out of its own memory, so only a
#: FOREIGN one is a real round trip. A client whose socket the far end has closed cannot
#: answer it: the send returns `true` and nothing arrives.
#:
#: Why not the server CLOCK, which was the first proposal: `GetServerTime()` is the local
#: tick plus a `serverDeltaTime` fixed at login (`tools/lib/game_clock.py`), so it goes on
#: advancing in a client that is receiving nothing. It would have read «alive» in exactly
#: the case it was meant to catch.
PROBE_FAILS = 2

#: How long a probe may take before it counts as failed. Measured on a healthy client on
#: 2026-08-24 — five consecutive probes, every one inside a second — so eight seconds is
#: the status poll's own interval and eight times the observed cost.
PROBE_DEADLINE_SEC = 8.0

#: …and the shortest gap between two probes that both count. Two questions asked in the
#: same breath are one question: a reconnecting client is briefly unable to answer either.
PROBE_GAP_SEC = 20.0

#: HOW LONG AN ANSWERED PROBE IS BELIEVED FOR (#1910, found live).
#:
#: The socket reading can be wrong for HOURS — measured on this machine the same evening:
#: `classify` said `lost` continuously while the server was answering every probe. The
#: decision therefore kept reaching the confirmation, and the confirmation kept asking:
#: one round trip into the game every twenty-five seconds, for ever, to re-establish a
#: fact that had not changed. A server that answered is a client that is talking, and
#: that is worth five minutes of not asking again.
PROBE_OK_HOLD_SEC = 300.0

#: …and how often the REFUSAL is said while it stays true. Same reasoning and the same
#: number as the daemon's standing failure (`GameLink.FAIL_SAY_SEC`): the first one is
#: news, the hundredth is the noise this codebase keeps relearning. Live it was two lines
#: every twenty-five seconds.
CONFIRM_SAY_SEC = 300.0

#: THE SHORTEST GAP BETWEEN TWO STRIKES THAT COUNT (#1702). Three consecutive `lost`
#: readings are meant to be «about half a minute of a client that cannot be heard» — and
#: they are only that if the three are three independent LOOKS. They were not: the socket
#: table is shared between profiles and cached for two seconds
#: (`game_link.MACHINE_TTL_SEC`), the status poll can fire several times inside one
#: window, and the panel's own sentence about it («уже 24 с») is `STRIKES * 8` computed
#: rather than measured. Live on 2026-08-22 the announce and the restart were **eight
#: seconds apart**, not twenty-four, and the client that was relaunched had been talking
#: to the server a moment earlier.
#:
#: Three quarters of the poll interval, for the same reason the watchdog's own spacing
#: uses that number: the poll jitters, and an exact comparison would drop the strike that
#: is genuinely due.
STRIKE_GAP_SEC = 6.0

#: Seconds between two restarts of the same client. Ten minutes: a restart plus a login
#: is about a minute, so this leaves nine for the account to prove it can stay on before
#: anything touches it again.
COOLDOWN_SEC = 600.0

#: …AND HOW FAR THAT WAIT GROWS WHEN THE CURE KEEPS NOT WORKING (#2446).
#:
#: A flat ten minutes is right for the first attempt and wrong for the sixth: a client
#: that has been put back five times and is still deaf is not going to be cured by a
#: sixth relaunch inside the same ten minutes, and the log fills with acts instead of
#: with the one fact worth reading — that the cure is not working. So the wait is
#: :data:`COOLDOWN_SEC` multiplied by the number of restarts that changed nothing
#: (`_fruitless`, which a single green reading wipes), and capped here. The FIRST wait
#: is unchanged at ten minutes — one restart that has not yet had time to prove itself
#: is not evidence of anything — and it is the second that starts costing: 10 → 10 → 20
#: → 30 → 40 → 50 → 60 minutes and no further.
#:
#: The ceiling is an hour rather than «for ever» on purpose. Whatever is wrong may be
#: outside the machine — a network, a server, a router that reboots at four — and a
#: panel that has given up permanently is a panel somebody has to notice before the
#: account plays again.
COOLDOWN_MAX_SEC = 3600.0

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

#: HOW LONG THE GATE ABOVE MAY POSTPONE A RESTART, in seconds. Fifteen minutes.
#:
#: The gate had no end at all, and that was the bug (#1888). It holds for exactly as
#: long as somebody keeps touching the keyboard, so on a machine a person WORKS at, a
#: client that lost the server at three o'clock is still lost at midnight — and the log
#: says «не трогаю ещё 5 мин» every few seconds without ever meaning it. Live on
#: 2026-08-23 that was three hours of a deaf client: `held_by=player`, the cooldown long
#: expired, forty-four strikes counted, and the one restart that did happen that day
#: landed at 15:42 only because the person had stepped away from the machine.
#:
#: A LOST LINK IS NOT A SESSION ANYBODY IS PLAYING, and that is what makes the bound
#: safe. While the link reads `lost`, nothing the person does in that window reaches the
#: server: the account is already out of the game, and the restart takes nothing from
#: them that the server has not taken already. The five minutes of patience stay — a
#: client reconnecting is worth sitting out, and #1259 is why — and after them the
#: client is put back whoever is at the keyboard, in its own sentence so the two cases
#: can never be read as one.
PLAYER_HOLD_MAX_SEC = 900.0

#: Client restarts with the link never once coming back, kept as a NUMBER TO SHOW.
#:
#: Until #1911 it moved the blame: two fruitless restarts and the next act was a daemon
#: restart instead. There is no daemon, so there is nothing to alternate with — but the
#: count is still the honest evidence that the cure is not working, and a person reading
#: «второй перезапуск подряд впустую» can tell the difference between a panel that is
#: fixing something and one that is repeating itself.
FRUITLESS = 2

#: Consecutive readings of «the client is showing the kick modal» before it is acted on.
#: Two, and for a reason of its own rather than the link's five:
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

    __slots__ = ("_probe_fails", "_probe_at", "_probe_flying", "_probe_want",
                 "_confirm_held", "_confirm_at", "_probe_last_ok",
                 "_run", "_run_at", "_lost_since",
                 "_last", "_restarts", "_held", "_why", "_kicks",
                 "_fruitless", "_blame", "_kick_run", "_barren", "_barren_said",
                 "kick_hold_sec", "_kick_until", "_kick_armed", "_kick_held",
                 "_kick_wait", "_kick_acted",
                 "stalled_grace_sec", "stalled_cooldown_sec",
                 "_stalled_since", "_stalled_last", "_stalled_held",
                 "_stalled_restarts")

    def __init__(self) -> None:
        #: THE SECOND FAMILY OF EVIDENCE (#1910): failed server probes in a row.
        self._probe_fails = 0
        #: When the last probe was STARTED — the deadline and the gap are both off this.
        self._probe_at = 0.0
        #: Is one in flight? A probe is asked for here and answered by the panel, so the
        #: two are a request and a reply rather than a call.
        self._probe_flying = False
        #: Does the decision WANT one? Set the moment everything else says «restart», so
        #: a healthy account never pays for a probe at all.
        self._probe_want = False
        #: …and whether the wait for confirmation has already been said, and when.
        self._confirm_held = False
        self._confirm_at = 0.0
        #: When a probe last came back OK — the contrary signal, for the log line.
        self._probe_last_ok = 0.0
        #: Consecutive `lost` readings so far.
        self._run = 0
        self._run_at = 0.0
        #: When the current run of `lost` readings began, in the caller's wall clock, or
        #: 0.0 while the link is fine. `_run` counts READINGS and the player gate needs a
        #: DURATION — see :data:`PLAYER_HOLD_MAX_SEC`.
        self._lost_since = 0.0
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
        #: Client restarts with the link never once coming back since. Drawn, because
        #: «второй перезапуск подряд впустую» is worth seeing; it decides nothing.
        self._fruitless = 0
        #: "" | "client" — WHAT this thinks is broken, for both front-ends. There is
        #: only one thing left it can be: the panel holds the link itself now (#1911).
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

    def player_hold_left(self, now: float) -> int:
        """Seconds the «somebody is at the machine» gate may still postpone a restart.

        A FACT WITH A CLOCK, for the same reason :meth:`kick_hold_left` is one: a hold
        that only the decision honours is not a hold, and both front-ends draw it. Zero
        means the patience is spent — the client is restarted on the next reading even
        with a person at the keyboard, because the link has been lost the whole time and
        a lost link is not a session anybody is playing (#1888).

        Zero as well while the link is fine: there is nothing to postpone.
        """
        if not self._lost_since:
            return 0
        return max(0, int(self._lost_since + PLAYER_HOLD_MAX_SEC - now))

    def cooldown_sec(self) -> float:
        """How long THIS client must be left alone after a restart (#2446).

        :data:`COOLDOWN_SEC` while the cure is working, and one more helping of it for
        every restart that changed nothing (`_fruitless`, wiped by a single green
        reading), up to :data:`COOLDOWN_MAX_SEC`. A number rather than a constant so the
        log line and the decision quote the same thing — «жду 10 мин» said six times in
        an hour while the client is restarted six times is what a flat cooldown looks
        like from outside, and it is indistinguishable from a panel doing nothing.
        """
        return min(COOLDOWN_SEC * max(1, self._fruitless), COOLDOWN_MAX_SEC)

    def state(self, now: float) -> dict:
        """What both front-ends draw: the run, the count, and the cooldown left.

        Data, not words — the window and the phone say it in their own language out of
        the same numbers (`CLAUDE.md`, «Not one word of the panel is written in the
        panel»).
        """
        left = 0
        if self._last:
            left = max(0, int(self._last + COOLDOWN_SEC - now))
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
                # …and how long the account is being left to whoever took it. Drawn on
                # both front-ends with a countdown, because «панель ничего не делает» and
                # «панель ждёт четырнадцать минут» look identical otherwise — and the
                # person waiting is usually the one who took the account (#1291).
                "kick_hold_left": self.kick_hold_left(now),
                "kick_hold_of": int(self.kick_hold_sec),
                # …and the OTHER hold that has a person on the end of it: somebody at
                # this machine. Drawn as a countdown for the reason the kick's is —
                # «панель ничего не делает» and «панель ждёт ещё четыре минуты» look
                # identical otherwise — and because until #1888 this one had no end at
                # all, so there was no number to draw.
                "player_hold_left": self.player_hold_left(now),
                "player_hold_of": int(PLAYER_HOLD_MAX_SEC),
                # How many client restarts have been spent without the link ever coming
                # back. Shown because it is the evidence, not the verdict: a person
                # seeing «2 подряд впустую» can tell that the panel is about to change
                # its mind, and why.
                "fruitless": self._fruitless,
                # …AND THE CONFIRMATION (#1910): how many server probes have gone
                # unanswered out of how many a restart needs. Drawn because it is the
                # difference between «панель вот-вот перезапустит» and «панель считает
                # клиент живым», which used to be one indistinguishable silence.
                "probe": self.probe_state(now),
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
    def note(self, deaf: bool, now: float,
             idle_sec: "float | None" = None,
             kicked: bool = False, talking: bool = False,
             running: bool = True, unprobeable: bool = False) -> "tuple | None":
        """Feed one verdict about the link. What to SAY and DO, or ``None`` for nothing.

        ``deaf`` is the amber the status poll made (#1911): there IS a client, chunks
        reach its Lua VM or its window is wedged, and the game server is not answering.
        **It is never the amber that blames OUR OWN wiring** — an attach that fails is a
        bug to fix and restarting a client over it is #1268's six pointless relaunches
        with the evidence in hand.

        THE SOCKET TABLE IS NOT AN INPUT ANY MORE. It cannot say which conversation is
        the game: measured on this machine, `classify` said `lost` continuously for a
        night while the server answered every probe (#1910). What is left is what was
        always the honest half — an active question to the server and the answer coming
        back.

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

        A kick reported for a client that is not there is ignored: no process, nothing
        on screen, and therefore nothing that can be showing a modal. That reading
        belongs to the watchdog and two things must not relaunch one client.

        **`unprobeable` IS THE STATE THAT COST A NIGHT (#2446), and it is a DEADLOCK
        rather than a missing rule.** It means the caller could not get a chunk into the
        client's Lua VM at all — its plumbing reading is anything but `LANDING`, which
        covers both shapes this can take: a client whose main thread never reaches its
        park (`CLIENT_HUNG`, `NOT_LANDING`) and one the panel has never managed to attach
        to, so nothing has ever come back out of it and there is no age to judge
        (`PLUMBING_UNASKED`). Both arrive here as `deaf` — the second by falling through
        `profile_health.verdict` to `NO_TRAFFIC` — and both used to hit the confirmation
        below and stop there **for ever**.

        Because the confirmation is a round trip THROUGH the very VM that cannot be
        reached. The caller only sends a probe while the plumbing is `LANDING`; a probe
        that is never sent is never a failed probe; so the count sits at nought and the
        cure is withheld waiting for an answer to a question the panel had structurally
        decided not to ask. Live on 2026-09-05, `client-busy` from 00:41, and every five
        minutes until past 06:43:

            пока НЕ перезапускаю: сокеты потеряны на 579 взглядах за 4682 с,
            но проб сервера без ответа только 0 из 2

        Six hours, no restart, the schedule held throughout, and no other cure could take
        it either: the process watchdog only reacts to a pid going away, and the
        maintenance knock stands down on exactly this reading.

        So it is EXEMPT from the confirmation, as a kick is and for the same kind of
        reason: there is nothing to confirm. A kick is the game's own sentence; this is a
        direct reading of our own end of the wire, and it owes nothing to the socket
        table the confirmation exists to second-guess. **The exemption is narrow**: a
        client whose chunks DO land and whose server is merely silent is still probed, or
        #1910's night comes back — the sockets said `lost` for hours while the server
        answered every question.

        Every other gate is unchanged and still in front of it — the run of five readings
        over a minute, the person at the keyboard, the kick's wait and the cooldown,
        which now GROWS (:data:`COOLDOWN_MAX_SEC`) so that a cure which is not working is
        repeated less and less rather than every ten minutes until morning.
        """
        kicked = bool(kicked)
        # A CLIENT THAT IS THERE AND NOT SHOWING THE MODAL is the account being ours
        # again — the reading that ends a kick's wait. ``running`` is why it is not
        # simply «not deaf» (#1911): a client that has been CLOSED is not deaf either,
        # and clearing on that would hand the account straight back to the watchdog in
        # the middle of the quarter of an hour the other device was being given (#1291).
        if not deaf and not kicked and bool(running):
            # The cure WORKED — and only a GREEN reading says so, because only the
            # server answering proves anything about the link. A client that is merely
            # up is what every relaunch produces for a minute either way.
            if bool(talking):
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

        # WHAT COUNTS AS A DEAF READING (#1911): the caller's amber, and nothing else.
        suspect = bool(deaf)
        if not suspect and not kicked:
            # Anything else ends the run — including «no client», which is the PROCESS
            # being gone and the watchdog's business, not this one's. Two things must
            # not both relaunch the same client.
            self._run = 0
            self._lost_since = 0.0
            self._held = False
            # ANY CONTRARY SIGNAL OBLITERATES THE CASE AGAINST THE CLIENT (#1910):
            # evidence for «deaf» has to be evidence taken while it was deaf, all of
            # it, or a restart is assembled out of two unrelated bad minutes an hour
            # apart. The ANSWER the server gave stays (#1911) — it is what the light is
            # made of, and wiping it here flapped the strip green-amber-green.
            self._probe_settle()
            # …but a kick's wait outlives the reading that started it, and so must the
            # word for it: a client that went offline mid-wait (the person closed it, or
            # it gave up) is still being waited out, and a strip that went blank here
            # would say «nothing is happening» through the fifteen minutes when
            # something very deliberately is (#1291).
            self._why = "kick" if self.kick_hold_left(now) > 0 else ""
            return None

        if suspect:
            # THE CLOCK THE PLAYER GATE READS. Stamped on the first reading of a run and
            # cleared with the run, so it measures «how long has this client been deaf»
            # and not «how many times have we looked».
            if not self._run:
                self._lost_since = now
            # …AND A STRIKE HAS TO BE A FRESH LOOK (:data:`STRIKE_GAP_SEC`). Two readings
            # inside one cache window are one reading counted twice, and this counter is
            # what decides whether a client is restarted.
            #
            # The reading is not otherwise thrown away: a kick is a reading of the game's
            # OWN words rather than an inference off a cached socket table, so its
            # counter and its wait go on being kept underneath this.
            if not self._run or (now - self._run_at) >= STRIKE_GAP_SEC:
                self._run_at = now
                self._run += 1
        # A kick and a hang-up can be true at once — the sockets went AND the modal is
        # up, which is the ordinary shape of a kick — so the run each of them has to
        # clear is checked separately and whichever is satisfied first decides. A kick
        # is the shorter of the two because it is a reading of the game's own words.
        # …AND THE RUN MUST COVER :data:`LOST_SPAN_SEC` OF WALL CLOCK (#1910). Five
        # readings are five readings; the question is «has this client been deaf for a
        # minute», and the poll's rate is not a clock (#1702 measured three «strikes» in
        # eight seconds). A kick keeps its own shorter run: it is the game's own words,
        # not an inference off a cached socket table.
        deaf_for = (now - self._lost_since) if self._lost_since else 0.0
        # …and the span depends on WHICH evidence this is (#2578). A client nothing
        # reaches has no confirmation coming — the probe travels through the VM that
        # cannot be reached — so this run is the only thing standing between a loading
        # client and a restart. See :data:`HUNG_SPAN_SEC`.
        span = HUNG_SPAN_SEC if unprobeable else LOST_SPAN_SEC
        long_enough = self._run >= STRIKES and deaf_for >= span
        if not long_enough and self._kick_run < KICK_STRIKES:
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
        #
        # …AND IT HAS AN END NOW (#1888). It used to have none: it held for exactly as
        # long as somebody kept touching the keyboard, which on a machine a person works
        # at is all day. The patience is unchanged and the bound is
        # :data:`PLAYER_HOLD_MAX_SEC` — after that the client is put back anyway, and it
        # says so in its own words rather than borrowing the ordinary sentence.
        player_here = idle_sec is not None and idle_sec < PLAYER_QUIET_SEC
        if player_here and self.player_hold_left(now) > 0:
            if self._why == "player":
                return None
            self._why = "player"
            # The SMALLER of the two deadlines, because either one can be the one that
            # ends the wait and a countdown that names the wrong one is a countdown the
            # log will be caught out on.
            left = min(PLAYER_QUIET_SEC - idle_sec, self.player_hold_left(now))
            return (BUSY, {"mins": int(left // 60) + 1})

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
        wait = self.cooldown_sec()
        if since is not None and since < wait:
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
            return (HOLD, {"mins": int((wait - since) // 60) + 1,
                           "n": self._restarts})

        # THERE IS ONE CURE NOW, AND SO THERE IS NOTHING TO ALTERNATE WITH (#1911).
        # This is where two fruitless client restarts used to move the blame onto the
        # daemon and restart that instead. There is no daemon: the panel holds the link
        # itself, and the state that alternation was invented for — a daemon answering
        # its port while holding a client that has gone — cannot exist. `_fruitless` is
        # still counted and still drawn, because «второй перезапуск подряд впустую» is
        # worth seeing; it simply no longer decides anything.
        # ===== THE CONFIRMATION (#1910) ======================================
        # Everything above has said «restart». This is the second, independent family of
        # evidence, and it is asked LAST on purpose: a healthy account never reaches this
        # line, so the probe costs nothing until something is genuinely wrong.
        #
        # A KICK IS EXEMPT. There is nothing to confirm — the game has said in its own
        # words that the account is on another device (§5.3), and a probe would only ask
        # a client that is deliberately not being talked to.
        # …AND A CLIENT WE CANNOT REACH AT ALL IS EXEMPT TOO (#2446), for the reason
        # spelled out in the docstring: the confirmation travels THROUGH the client's Lua
        # VM, and `unprobeable` is precisely «nothing gets into that VM». Asking for it is
        # asking a question that cannot be delivered and then refusing to act because no
        # answer came back.
        if not kicked and not unprobeable and self._probe_fails < PROBE_FAILS:
            self._why = "confirm"
            self._probe_want = True
            if self._confirm_held and (now - self._confirm_at) < CONFIRM_SAY_SEC:
                return None
            self._confirm_held = True
            self._confirm_at = now
            # THE SYMMETRIC LINE: why the restart is NOT happening, in the same numbers
            # the act would have quoted. Without it a restart withheld and a restart
            # never considered look identical, which is the whole failure mode this
            # module keeps rediscovering.
            return (HOLD_CONFIRM, {"looks": self._run, "secs": int(deaf_for),
                                   "fails": self._probe_fails, "need": PROBE_FAILS})

        # CAPTURED BEFORE THE RESETS BELOW. The line quotes what was MEASURED, and the
        # counters are about to go back to zero for the next incident.
        looks = self._run
        self._last = now
        self._restarts += 1
        self._fruitless += 1                 # …until a reading says ONLINE
        self._blame = "client"
        self._run = 0                        # the next reading starts a fresh run
        self._lost_since = 0.0
        self._kick_run = 0
        # …and the wait is spent. A kick that survives this restart is a NEW episode and
        # buys its own fifteen minutes: the account is still on the other device, and the
        # answer to that is the same answer as the first time.
        self._kick_clear()
        self._held = False
        self._why = ""
        probe_fails, probe_secs = self._probe_fails, int(now - self._probe_at) \
            if self._probe_at else 0
        self._probe_clear()
        # The two are the same act and NOT the same event, so they are not the same
        # sentence: «связь пропала» is the server having stopped answering, and
        # «вход с другого устройства» is somebody holding the account. A log that
        # says which is a log somebody can act on.
        if kicked:
            self._kicks += 1
            return (ACT_KICK, {})
        if player_here:
            # THE GATE RAN OUT RATHER THAN OPENED (#1888). Somebody is at this machine
            # and the client is being restarted regardless, because the link has been
            # lost longer than :data:`PLAYER_HOLD_MAX_SEC` and a lost link is not a
            # session anybody is playing. Its own sentence: whoever was looking at that
            # window is owed the reason it closed.
            return (ACT_BUSY, {"mins": int(PLAYER_HOLD_MAX_SEC // 60)})
        if unprobeable:
            # ITS OWN SENTENCE (#2446). :data:`ACT` quotes failed server probes, and
            # this is the one case where there can never be any — so sharing the line
            # would print «0 проб» beside a restart and read as the bug it fixes. It
            # carries the attempt number and the next wait, because the one thing a
            # person reading a repeated restart needs is whether it is repeating.
            return (ACT_HUNG, {"secs": int(deaf_for), "looks": looks,
                               "n": self._restarts,
                               "again": int(self.cooldown_sec() // 60),
                               "idle": int(idle_sec) if idle_sec is not None else -1})
        # ON WHAT BASIS, IN NUMBERS (#1910). It used to say «не слышен серверу 24 с»,
        # and the 24 was `STRIKES * 8` — arithmetic, not a measurement, over a poll that
        # jitters. Everything here was counted: how many independent looks, how long the
        # loss has actually lasted, how many server probes went unanswered and how long
        # the person has been away from the machine. A restart nobody can argue with
        # afterwards is a restart nobody can correct.
        return (ACT, {"looks": looks, "secs": int(deaf_for),
                      "fails": probe_fails, "probe_secs": probe_secs,
                      "idle": int(idle_sec) if idle_sec is not None else -1})

    # -- the second family of evidence: an active server probe (#1910) --------
    def _probe_clear(self) -> None:
        """Forget every probe. Called whenever the client proves it is talking."""
        self._probe_fails = 0
        self._probe_at = 0.0
        self._probe_flying = False
        self._probe_want = False
        self._probe_last_ok = 0.0
        self._confirm_held = False
        self._confirm_at = 0.0

    def _probe_settle(self) -> None:
        """Forget the DOUBT and keep the PROOF (#1911).

        The difference matters now that the light itself is «did the server answer»:
        wiping `_probe_last_ok` on a healthy reading turned green back to amber until
        the next probe went out, and the strip flapped between the two every couple of
        minutes. What a contrary signal obliterates is the case AGAINST the client — the
        failed probes, the flight, the want — never the answer that came back.
        """
        self._probe_fails = 0
        self._probe_flying = False
        self._probe_want = False
        self._confirm_held = False
        self._confirm_at = 0.0

    def probe_due(self, now: float) -> bool:
        """Should the panel ask the server something RIGHT NOW? (#1910)

        `True` only when the decision has already got as far as «restart» and is waiting
        on confirmation, and only once per :data:`PROBE_GAP_SEC` — two questions asked in
        one breath are one question, and a reconnecting client fails both.

        A probe that never came back is counted as a failure HERE rather than by a timer:
        the poll comes round every eight seconds anyway, so the deadline is checked by
        whoever asks next. That keeps the whole mechanism inside the one thread that
        already polls, which is what the rest of this module is built on.
        """
        if self._probe_flying:
            if (now - self._probe_at) < PROBE_DEADLINE_SEC:
                return False                 # still within its deadline; wait
            # IT NEVER ANSWERED. That IS the failure this probe exists to detect: a
            # stranded client accepts the send and nothing comes back.
            self._probe_flying = False
            self._probe_fails += 1
        if not self._probe_want:
            return False
        if self._probe_last_ok and (now - self._probe_last_ok) < PROBE_OK_HOLD_SEC:
            # THE SERVER ANSWERED RECENTLY. Nothing about the client has changed since,
            # and the sockets have been wrong about it for the whole of that window —
            # asking again is a round trip spent re-proving what is already known.
            return False
        if self._probe_fails >= PROBE_FAILS:
            # ENOUGH ASKED. The confirmation is complete and the decision acts on the
            # next reading; another question would change nothing — and in a caller that
            # keeps asking until it is told to stop, «nothing» has no bottom.
            return False
        return not self._probe_at or (now - self._probe_at) >= PROBE_GAP_SEC

    #: HOW OFTEN THE SERVER IS ASKED WHEN NOTHING IS WRONG (#1911).
    #:
    #: Green means «the server answered», so the light needs an answer that is not too
    #: old — and an answer that is never refreshed turns amber for want of asking, which
    #: is exactly the amber this model exists to make meaningful. Two minutes: a round
    #: trip measured at under a second, asked once per two minutes, is 0.008 % of a
    #: profile's time and keeps the green inside :data:`PROBE_OK_HOLD_SEC` with a wide
    #: margin.
    PROBE_REFRESH_SEC = 120.0

    def probe_idle_due(self, now: float) -> bool:
        """Should the panel ask the server just to keep the LIGHT honest? (#1911)

        Separate from :meth:`probe_due`, which asks only when a restart is already
        being considered. This one is the ordinary heartbeat of the three statuses: a
        profile nobody is restarting still has to be able to go green.
        """
        if self._expire(now):
            return True
        if self._probe_flying:
            return False
        if self._probe_last_ok and (now - self._probe_last_ok) < self.PROBE_REFRESH_SEC:
            return False
        return not self._probe_at or (now - self._probe_at) >= PROBE_GAP_SEC

    def _expire(self, now: float) -> bool:
        """Count a probe that never came back. ``True`` if one has just been written off.

        A probe that never answered IS the failure this whole reading exists to detect:
        a stranded client accepts the send and nothing comes back. Checked by whoever
        asks next rather than by a timer, so the mechanism stays inside the one thread
        that already polls.
        """
        if self._probe_flying and (now - self._probe_at) >= PROBE_DEADLINE_SEC:
            self._probe_flying = False
            self._probe_fails += 1
            return True
        return False

    def server_state(self, now: float) -> str:
        """What the light is told about the server: one of `profile_health`'s three ids.

        `ANSWERING` is the only thing that earns green, and it has a shelf life
        (:data:`PROBE_OK_HOLD_SEC`) — «the server replied» is a statement about a moment.
        """
        if self.link_confirmed(now):
            return profile_health.ANSWERING
        if self._probe_fails:
            return profile_health.SILENT
        return profile_health.SERVER_UNASKED

    def server_answered_at(self) -> float:
        """WHEN the game server last answered us — `0.0` if it never has (#2061).

        The light is green because of a moment, and the person asked to see the moment:
        «показывай» — the age beside the colour. Green has a shelf life of
        :data:`PROBE_OK_HOLD_SEC`, so «сервер ответил 4 мин назад» is a green a person can
        judge for themselves, and a silent five minutes stops being invisible.
        """
        return float(self._probe_last_ok or 0.0)

    def probe_started(self, now: float) -> None:
        """One probe has just been sent. Its deadline runs from here."""
        self._probe_at = now
        self._probe_flying = True

    def note_probe(self, ok: bool, now: float) -> None:
        """The probe came back. ``ok`` means the SERVER answered.

        An answer is a contrary signal and wipes the count — the client is demonstrably
        talking, whatever its socket table looked like a moment ago. A refusal adds one.
        """
        self._probe_flying = False
        if ok:
            self._probe_last_ok = now
            self._probe_fails = 0
            self._probe_want = False
            # `_confirm_held` is deliberately NOT cleared: the refusal is still true and
            # still the same refusal, and clearing it here is what made the sentence
            # repeat every twenty-five seconds live. It is re-armed by time
            # (:data:`CONFIRM_SAY_SEC`) and by the link coming back, nothing else.
            return
        self._probe_fails += 1

    def probe_unstarted(self, now: float) -> None:
        """The probe could not even be SENT — the game was busy with something else.

        Not evidence either way, and that cuts BOTH ways (#1976). It must not add a
        strike: a busy client is not a deaf one, which is what `note_probe(False)` would
        say. It must not add a SUCCESS either, which is what this used to do — and a
        success is what paints the light green, so «мы не смогли спросить» became «сервер
        ответил» and held it for five minutes. Green is the server answering and nothing
        else; a question nobody managed to ask leaves the light exactly where it was.

        So: nothing is in flight, no deadline is running, and the next poll asks again
        without waiting out the gap between two real probes.
        """
        self._probe_flying = False
        self._probe_at = 0.0

    def link_confirmed(self, now: float) -> bool:
        """Did the game SERVER answer us recently? (#1910)

        The one positive fact this module holds about the link, and the only thing that
        may paint it green when the socket table will not commit: an active question the
        server itself answered. It has a shelf life on purpose — the SAME one the probe
        already trusts an answer for (:data:`PROBE_OK_HOLD_SEC`) — because «the server
        replied» is a statement about a moment, and a moment that is far enough back is
        not a statement about now.

        Read by whoever DRAWS, and it never asks anything: the answer was measured when
        the decision needed it, and painting a strip may not be the thing that spends a
        round trip (the same rule `panel/runtime/health.py` keeps about its own light).
        """
        return bool(self._probe_last_ok
                    and (now - self._probe_last_ok) < PROBE_OK_HOLD_SEC)

    def probe_state(self, now: float = 0.0) -> dict:
        """What both front-ends draw about the confirmation. Numbers, never words.

        `now` comes from the caller for the reason every other clock in this module
        does: it has no import of its own and must not grow one — a decision module that
        reads the wall clock is a decision module a test cannot drive.
        """
        return {"fails": self._probe_fails, "of": PROBE_FAILS,
                "flying": self._probe_flying, "wanted": self._probe_want,
                # …AND WHETHER THE SERVER HAS ANSWERED RECENTLY (#1910). Drawn on both
                # front-ends: it is what makes a link the sockets will not vouch for
                # read as live rather than as «не подтверждено».
                "confirmed": self.link_confirmed(now),
                "for_sec": int(PROBE_OK_HOLD_SEC)}

    def note_session(self, playing: "bool | None", talking: bool, now: float,
                     idle_sec: "float | None" = None, running: bool = True,
                     wiring_bad: bool = False) -> "tuple | None":
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
        * ``False`` — the login screen, demonstrably: asked what time it is, the client
          handed out its own uptime (#1299). **The only value that is ever acted on.**
        * ``None``  — nobody could ask. **Not evidence, and never a reason to restart a
          client** (#2060). It used to be folded into ``False`` on the grounds that a
          client the panel cannot talk to is no more use than one at the login screen —
          true of the USE and false of the CURE, because «мы не смогли спросить» is
          exactly what our own broken plumbing looks like, and #1268's rule is that our
          plumbing is fixed and never restarted over. It neither knocks nor clears: a
          client that was demonstrably at the login screen and then went quiet keeps its
          clock, and the knock waits until the client can be asked again.

        **A restart cannot reopen a server, and that is not what it is for.** A client
        left on the maintenance dialog stays there after the door opens; the knock is how
        the account is playing again within a quarter hour of the server coming back
        rather than whenever somebody notices.

        Every gate the other cures have applies here unchanged and in the same order:
        a client that is GONE is the watchdog's business and one whose PLUMBING is ours
        to fix is nobody's to restart (``running`` and ``wiring_bad`` say which, #2060),
        a person at the machine wins, and a kick's wait is not interrupted to knock.
        """
        if not running or wiring_bad:
            # NOT THIS BRANCH'S CLIENT, and the test is now WHO ELSE OWNS THE FAULT
            # (#2060). No process at all is the watchdog's. Nothing landing in the VM is
            # OURS — `CLIENT_HUNG` and `NO_CONNECTION`, the states #1268 forbids
            # restarting a client over, and the forbidding stands: a chunk that will not
            # land is a bug of ours to fix, and six pointless relaunches were committed
            # on purpose to prove it.
            #
            # It used to ask `if not talking`, which meant «is the game SERVER answering»
            # — a far wider net than the one the other branches actually take, so the
            # intersection belonged to nobody. Live on 2026-08-28: a client up, driveable
            # and sitting outside the game for 24 975 s with every timer stopped.
            #
            # `talking` is still taken and still drawn by the caller, and it decides
            # nothing here: whether the SERVER answers is not how this branch tells its
            # own client from somebody else's — `playing` is.
            self._stalled_clear()
            return None
        if playing is None:
            # NOBODY COULD ASK — and that is not evidence (#2060). Neither knocks nor
            # clears: a client that was demonstrably at the login screen and then went
            # quiet keeps the clock it had earned, and nothing is restarted on a silence
            # that is just as likely to be our own end of the wire.
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


#: The panel says this and then plays `restart_game`.
ACT = "log.game.deaf_restart"
#: …and this while the sockets say «deaf» and the SERVER PROBE has not agreed yet
#: (#1910). The symmetric half of the line above: a restart withheld and a restart never
#: considered are the same silence otherwise, and the person's complaint was precisely
#: that the panel restarts on an impression. Now both directions carry their numbers.
HOLD_CONFIRM = "log.game.deaf_confirm"
#: …and this when it may not yet, so a wait never looks like nothing happening.
HOLD = "log.game.deaf_hold"
#: …and this when somebody is playing. The client is left exactly alone.
BUSY = "log.game.deaf_busy"
#: The same act, a different event: the client was KICKED — the account was logged in
#: somewhere else and the client is showing the game's own «вход с другого устройства»
#: (`tools/lib/game_kick.py`, the game's key `E100083`). Worth its own sentence,
#: because «связь пропала» and «у вас забрали аккаунт» want different things done.
ACT_KICK = "log.game.kick_restart"

#: …and the same act again when the PLAYER gate ran out rather than opened (#1888). The
#: client is put back with somebody at the keyboard, because the link has been lost for
#: :data:`PLAYER_HOLD_MAX_SEC` and nothing that person does in that window is reaching
#: the server. Its own sentence rather than a share of :data:`ACT`: whoever was looking
#: at the window is owed the reason it closed, and a log that cannot tell «restarted
#: because nobody was there» from «restarted although somebody was» is a log that cannot
#: answer the only question asked about this branch.
ACT_BUSY = "log.game.deaf_restart_busy"

#: …AND THE CLOSED DOOR (#1549). Its own key rather than a share of `ACT`, because it is
#: the one restart in this module that does not mean anything is broken: the client is
#: fine, the server is shut, and the knock is how the panel finds out it has opened.
ACT_STALLED = "log.game.stalled_restart"

#: …AND THE CLIENT NOTHING REACHES (#2446) — wedged, or never attached to at all. Its
#: own key rather than a share of :data:`ACT`, because the evidence is not the same
#: evidence: :data:`ACT` quotes failed server probes, and this is the one case where
#: there can never be any — the probe rides the VM that cannot be reached. Six hours of
#: «0 из 2» is what sharing the sentence would have gone on looking like.
ACT_HUNG = "log.game.hung_restart"
#: …and the wait in front of it: the account is on another device, and it is being left
#: there for :data:`KICK_HOLD_SEC` before anything is done about it (#1291). Said once
#: per kick with the minutes left, and drawn as a countdown by both front-ends — a panel
#: that has decided to do nothing for a quarter of an hour and says nothing about it is
#: indistinguishable from one that has not noticed.
HOLD_KICK = "log.game.kick_hold"

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
RESTARTS = frozenset({ACT, ACT_BUSY, ACT_KICK, ACT_STALLED, ACT_HUNG})

#: …and the subset that means «this restart is because the account was TAKEN». Asked as a
#: set for the same reason as above: `key == ACT` is what once left a kicked client
#: announced and never restarted, and a caller comparing against one constant is a caller
#: that will be wrong the day a second kick act appears. What hangs off it is the
#: escalating wait — see `Recovery.note_kick_restart`.
KICK_ACTS = frozenset({ACT_KICK})

#: …and the answers that are only ever SAID. A set of its own rather than «everything not
#: in the others», so that adding an act and forgetting to wire it fails loudly instead
#: of quietly becoming a sentence — which is exactly how `ACT_KICK` spent a night being
#: announced and never performed. A key in none of the four sets is a bug, and
#: `tests/test_panel_recovery.py` says so.
SAYINGS = frozenset({SAY_BARREN})
