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


class Recovery:
    """One client's answer to «has it been deaf long enough to restart?»

    One instance per profile, kept by whoever polls the link. Not thread-safe on
    purpose — it is fed from the one poll that already exists, and a lock here would be
    a lock nobody needs.
    """

    __slots__ = ("_run", "_last", "_restarts", "_held")

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
        return {"deaf_for": self._run, "strikes": STRIKES,
                "restarts": self._restarts, "cooldown_left": left}

    # -- deciding ------------------------------------------------------------
    def note(self, link: str, now: float) -> "tuple | None":
        """Feed one link reading. Returns what to SAY and DO, or ``None`` for nothing.

        The answer is `(locale_key, fmt)` when something should be said, and the caller
        restarts the client exactly when the key is :data:`ACT` — one return value for
        both, so a caller cannot act without saying why, which is the whole of what went
        wrong the day nothing was said and nothing was done.
        """
        if link != game_link.LOST:
            # Anything else ends the run — including `offline`, which is the PROCESS
            # being gone and the watchdog's business, not this one's. Two things must
            # not both relaunch the same client.
            self._run = 0
            self._held = False
            return None

        self._run += 1
        if self._run < STRIKES:
            return None
        if self._run > STRIKES and self._held:
            return None                      # already waiting, already said so

        since = now - self._last if self._last else None
        if since is not None and since < COOLDOWN_SEC:
            self._held = True
            return (HOLD, {"mins": int((COOLDOWN_SEC - since) // 60) + 1})

        self._last = now
        self._restarts += 1
        self._run = 0                        # the next reading starts a fresh run
        self._held = False
        return (ACT, {"secs": STRIKES * 8})


#: The panel says this and then plays `restart_game`.
ACT = "log.game.deaf_restart"
#: …and this when it may not yet, so a wait never looks like nothing happening.
HOLD = "log.game.deaf_hold"
