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

…AND THE SIXTH, which is a reading rather than a cure: :meth:`Recovery.note_run`, the
count of errands that tried to press and pressed nothing. It is the only thing in that
morning's log that was ever true, and nothing was counting it.

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


class Recovery:
    """One client's answer to «has it been deaf long enough to restart?»

    One instance per profile, kept by whoever polls the link. Not thread-safe on
    purpose — it is fed from the one poll that already exists, and a lock here would be
    a lock nobody needs.
    """

    __slots__ = ("_run", "_last", "_restarts", "_held", "_why", "_kicks",
                 "_stale_run", "_daemon_last", "_daemon_restarts", "_daemon_held",
                 "_fruitless", "_blame", "_kick_run", "_barren", "_barren_said")

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

    # -- reading -------------------------------------------------------------
    @property
    def restarts(self) -> int:
        """How many restarts this client has been given since the panel opened."""
        return self._restarts

    @property
    def deaf_for(self) -> int:
        """Consecutive `lost` readings right now — 0 when the link is fine."""
        return self._run

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
                "daemon_restarts": self._daemon_restarts,
                "daemon_cooldown_left": daemon_left,
                # How many client restarts have been spent without the link ever coming
                # back. Shown because it is the evidence, not the verdict: a person
                # seeing «2 подряд впустую» can tell that the panel is about to change
                # its mind, and why.
                "fruitless": self._fruitless,
                # …and the reading that says nothing is reaching the game at all, while
                # every other one still looks healthy: errands that pressed nothing.
                "barren": self._barren, "barren_of": BARREN}

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
            self._why = ""
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
        if idle_sec is not None and idle_sec < PLAYER_QUIET_SEC:
            if self._why == "player":
                return None
            self._why = "player"
            return (BUSY, {"mins": int((PLAYER_QUIET_SEC - idle_sec) // 60) + 1})

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

#: The daemon is attached to a client that is not there — the positive reading, two pids
#: that do not match. Restarting the CLIENT here is the six-times mistake (#1268).
ACT_DAEMON = "log.game.daemon_restart"
#: …and the cumulative one: this many client restarts have not brought the link back, so
#: the thing being restarted is not the thing that is broken. Says the count, because the
#: count is the argument.
ACT_DAEMON_STUCK = "log.game.daemon_after_restarts"
#: …and the daemon's own «too soon», so its wait is never silent either.
HOLD_DAEMON = "log.game.daemon_hold"

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
RESTARTS = frozenset({ACT, ACT_KICK})

#: …and every answer that means «restart the DAEMON now». Kept as its own set for the
#: same reason the other one exists rather than as an `if key == …`: the two acts arrive
#: from two different methods and a caller that tested one constant would wire half of
#: it, which is precisely the bug this file already carries a paragraph about.
DAEMON_RESTARTS = frozenset({ACT_DAEMON, ACT_DAEMON_STUCK})

#: …and the answers that are only ever SAID. A third set rather than «everything not in
#: the other two», so that adding an act and forgetting to wire it fails loudly instead
#: of quietly becoming a sentence — which is exactly how `ACT_KICK` spent a night being
#: announced and never performed. A key in none of the three sets is a bug, and
#: `tests/test_panel_recovery.py` says so.
SAYINGS = frozenset({SAY_BARREN})
