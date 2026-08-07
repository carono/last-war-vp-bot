r"""«Green» means a chunk reached the game recently — the rule, on its own (#1287).

The daemon has always been able to answer its port while nothing it sends reaches the
client. `up()` is a `socket.connect`; a ping proves the daemon's own thread is alive; the
pid it holds proves only that a process of that number exists. Measured over one day of
one profile's logs, **194 of 2 073 «warm» readings — 9 % — were taken while the client was
not up-and-online**, and three of them while there was no client process at all
(`docs/research/daemon-architecture.md` §3).

The only proof of «a call made now will reach the game and come back» is a chunk that
ran. It costs 62 ms, which is 22 ms more than comparing two integers — but it takes the
run lock, so nobody can afford to ask it on a poll. **So the daemon asks it of itself**:
every successful run stamps :meth:`Pulse.ok`, a self-probe fills the silences, and the
ping carries the AGE of the last chunk that landed. A reader then decides from a number
instead of from an inference.

None of that needs a game to be right, and the deciding is what has been wrong four times
running — so it lives here, alone, and both halves import it:

  * `tools/lua_daemon.py` keeps a :class:`Pulse` and reports :meth:`Pulse.state`;
  * `panel/runtime/daemon.py` turns a ping into :func:`verdict`.

A daemon that has been running since before this shipped says nothing about an age, and
it will go on running for days — that is what a warm daemon is for. :func:`verdict` falls
back to the pid comparison for exactly that case rather than calling every older daemon
dead.
"""
from __future__ import annotations

import time

#: How long the daemon may go without a chunk landing before it goes and tries one
#: itself. Ten seconds, and the number is chosen by what the PROBE costs the game rather
#: than by what it costs us: one invoke parks the client's main thread for about two
#: frames — 33 ms at 60 fps, and 200 ms at the 10 fps a disconnected session runs at
#: (`docs/research/headless-gpu.md`). At ten seconds that is under a percent of the
#: client's frames in the worst case, and zero whenever errands are running, because
#: their own successes reset the clock.
IDLE_PROBE_SEC = 10.0

#: How old the last landed chunk may be before a reader calls the daemon stale. Twice
#: the probe interval: one missed probe is a probe that queued behind a real call, which
#: is the ordinary case on a busy daemon and proves the very thing being asked about.
STALE_AFTER_SEC = 2 * IDLE_PROBE_SEC

#: Consecutive failures — of a self-probe or of a run — after which the daemon stops
#: holding the port and leaves.
#:
#: THREE, and the reason it is not one: a client that is restarting is unreachable for
#: the better part of a minute, and `follow_client` re-aims at it by itself. Leaving on
#: the first failure would turn every ordinary restart into a daemon restart as well.
#: Three failures at :data:`IDLE_PROBE_SEC` apart is half a minute of a daemon that
#: cannot drive anything, which is already longer than the cure takes.
LEAVE_AFTER_MISSES = 3


class Pulse:
    """Has a chunk reached the game lately, and is it time to go and find out?

    One per daemon. Not thread-safe by design and it does not need to be: the stamps are
    single assignments of a float, the reader is a ping on another thread, and a reading
    that is one tick stale is a reading of something that changes on a ten-second scale.
    """

    def __init__(self, idle_probe: float = IDLE_PROBE_SEC,
                 leave_after: int = LEAVE_AFTER_MISSES, clock=time.monotonic) -> None:
        self._idle_probe = float(idle_probe)
        self._leave_after = int(leave_after)
        self._clock = clock
        self._last_ok: "float | None" = None
        self._error: "str | None" = None
        self._misses = 0

    # -- stamping ------------------------------------------------------------
    def ok(self) -> None:
        """A chunk ran in the game and came back. Real errands count, not just probes.

        That is what makes the guarantee free while the panel is working: a busy daemon
        never probes at all, because every errand it serves is the proof.
        """
        self._last_ok = self._clock()
        self._error = None
        self._misses = 0

    def failed(self, error: BaseException | str) -> None:
        """A run or a probe did not reach the client. Does NOT clear the last success.

        The age is the reading; a failure only adds a reason and a strike. A caller that
        cleared `last_ok` here would make «nothing has landed for a while» and «the last
        thing to land failed» the same state, and only one of them is a reason to leave.
        """
        self._error = str(error)[:300] or error.__class__.__name__
        self._misses += 1

    # -- reading -------------------------------------------------------------
    def age(self) -> "float | None":
        """Seconds since the last chunk landed, or ``None`` if none ever has."""
        if self._last_ok is None:
            return None
        return max(0.0, self._clock() - self._last_ok)

    def due(self) -> bool:
        """Is a self-probe due? True while nothing has ever landed."""
        age = self.age()
        return True if age is None else age >= self._idle_probe

    def misses(self) -> int:
        return self._misses

    def should_leave(self) -> bool:
        """Has this daemon failed often enough that it should stop holding the port?

        The whole point of leaving rather than sitting there: a port nothing answers is
        a state the panel already knows how to cure (it starts a daemon), and a port
        answered by a daemon that cannot drive its client is the state that fooled every
        reader for a year.
        """
        return self._misses >= self._leave_after

    def state(self) -> dict:
        """What the ping carries. Keys are the wire's, and `None` is a real answer."""
        return {"last_ok_age": self.age(), "probe_error": self._error,
                "misses": self._misses}


def verdict(reply: dict, running_pid: "int | None" = None,
            stale_after: float = STALE_AFTER_SEC) -> str:
    """``"none"`` / ``"stale"`` / ``"live"`` from one `{"op":"ping"}` answer.

    ONE RULE, in one place, because the panel asks it from three sides — the status
    poll, `ensure()` before it says «already warm», and the recovery deciding whether to
    restart the daemon or the client — and the three used to be three readings.

    Order matters, and it is the order of how sure each answer is:

    1. **nothing answered** → `none`. The cure is to start a daemon.
    2. **a chunk has not landed for longer than `stale_after`** → `stale`. This is the
       reading the whole task exists for, and it is a FACT rather than an inference: the
       daemon itself failed to get a trivial chunk into the game.
    3. **the pid it holds is not the client that is running** → `stale`. Kept for the
       daemon that is too old to carry an age, and as the answer to «attached to the
       wrong client», which a live age cannot see.
    4. otherwise `live`.

    A daemon with NO age at all (one built before this shipped) is judged by rule 3
    alone. It is not stale for being old: a warm daemon runs for days, and a fix that
    only worked once somebody restarted the thing being fixed would be a fix for
    tomorrow's incident.
    """
    if not reply or not reply.get("ok"):
        return "none"
    running = _as_pid(running_pid)
    if not running:
        # NO CLIENT RUNNING IS NOBODY'S FAULT, and it is asked FIRST because every
        # reading below would otherwise convict a daemon of it: an idle machine has no
        # chunk to land, so the age is old or missing and the pid is `None`. Restarting
        # a daemon for having no game to drive is a loop with no bottom, and «I could
        # not tell» may never be the reason for one (the rule `panel/runtime/recovery.py`
        # already keeps for `unknown` link readings).
        return "live"
    age = reply.get("last_ok_age")
    if isinstance(age, (int, float)) and age > stale_after:
        return "stale"
    if age is None and reply.get("warm") is False:
        # A daemon that never got hold of a client and cannot say how long ago. It has
        # no evaluator at all, so nothing sent to it can reach the game.
        return "stale"
    if _as_pid(reply.get("pid")) != running:
        return "stale"
    return "live"


def landed_recently(reply: dict, stale_after: float = STALE_AFTER_SEC) -> bool:
    """Has a chunk reached the game lately? The reader's cheap question.

    :func:`verdict` answers «what is wrong and what cures it», which needs the pid that
    is running and therefore a walk of the process list (~45 ms). A caller that only
    wants to know whether it may read the game needs none of that: the age is one ping
    away, and a ping is 0.8 ms even while the daemon's run lock is fully occupied.

    A daemon too old to carry an age falls back to `warm` — the best it can say — for
    the same reason :func:`verdict` falls back to the pid: a warm daemon runs for days,
    and nothing here may declare one dead for predating the field.
    """
    if not reply or not reply.get("ok"):
        return False
    age = reply.get("last_ok_age")
    if isinstance(age, (int, float)):
        return age <= stale_after
    return bool(reply.get("warm"))


def _as_pid(value) -> "int | None":
    """``value`` as a process id, or ``None`` — the wire says `null`, JSON says string."""
    try:
        return int(value) or None
    except (TypeError, ValueError):
        return None
