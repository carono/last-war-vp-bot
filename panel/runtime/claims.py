"""What two open profiles must take turns over, held once for the whole process (#1226).

Everything else about a profile is its own — its runtime, its daemon, its schedule, its
log — and that is the point of `docs/research/multi-profile-panel.md`. Two things are
not, and both of them are shared because of what is on the OTHER side of the panel:

* **A client.** One game client may be driven by one thing at a time. Normally each
  profile has its own (its own daemon on its own port), and then there is nothing to
  share — but two profiles pointed at the SAME port are two views of one client, which
  is the accident a person makes by copying a profile and forgetting to change the port
  (§4.3). :func:`acquire` keyed by ``(host, port)`` is what makes them take turns.

* **The foreground.** Last War ignores `PostMessage`, so a scenario that CLICKS or LOOKS
  has to bring its client to the front and keep it there (`inputs.click(mode=
  "foreground")`, and `FIND` screenshots the window). One desktop has one foreground, so
  two such scenarios on one desktop do not take turns by themselves — they interleave,
  and each presses into whichever window the other has just raised. A profile whose
  client lives in its own Windows session is EXEMPT: its desktop is its own, and making
  it wait for this one would be inventing a conflict that does not exist.

WHY THE DAEMON'S LEASE IS NOT ENOUGH for the first of those. `tools/lib/game_lease.py`
is the authority whenever it can be reached, and `GameLink._claim_lease` says so. But it
answers *yes* when there is no daemon to ask — "nothing else can be driving the game
either" — which was true of one panel process and is not true of four profiles in one.
This registry is the in-process half that closes it, taken BEFORE the daemon is asked so
a refusal costs nothing.

WHY NOT A LOCK. A lock says "wait"; every caller here wants "say so and come back
later" — a timer re-queues its errand, a button says «занят», the map sweep keeps its
waypoint. So the registry hands out an OWNER instead: the answer to a refused claim is
the name of whoever is holding it, which is what turns «занято» into «занято профилем
alice» in the log.

Nothing here is per-window: two panels are two processes and the daemon's lease is what
separates those. This is one process, several profiles.
"""
from __future__ import annotations

import threading

#: ``key -> (owner, level)`` for every claim currently held in this process.
_held: dict = {}
#: ``key -> {token: (level, owner)}`` — everybody WAITING for a key they outrank the
#: holder of. See :func:`demand`.
_wanted: dict = {}
_lock = threading.Lock()
#: Ever-increasing, so two demands from two threads are never the same token.
_serial = 0

#: The key the foreground claim is filed under. A string rather than a tuple so it can
#: never collide with a client's ``(host, port)``.
FOREGROUND = "foreground"

#: HOW URGENT A CLAIM IS (#1288). Higher wins, and the numbers are ordered rather than
#: named so that a comparison is the whole rule.
#:
#: Measured on 2026-08-07, one profile's `panel.log`: **343 presses in one day** were
#: turned away with «занят — дождись завершения текущего действия», and an
#: `alliance_help` fire — an errand that runs in two seconds and pays nothing once the
#: request has closed — waited a p90 of 8–10 s and a maximum of 1276 s for its turn
#: behind the ordinary queue. One queue for everything prices a button press at whatever
#: the longest background errand happens to be (`restart_game` holds it for a median of
#: 304 s).
BACKGROUND = 0     #: the schedule's ordinary errands, the rally loops, a sweep
EXPRESS = 1        #: an errand whose catalogue entry says «сразу» — it must not queue
HUMAN = 2          #: somebody is at a button, in the window or on the phone


def acquire(key, owner: str, urgency: int = BACKGROUND) -> "str | None":
    """Take ``key`` for ``owner``. ``None`` when it was taken; else who is holding it.

    Deliberately inverted — ``None`` means success — because the interesting answer is
    the WHO, and a caller that only wants a bool writes ``if acquire(...) is None``.

    ``urgency`` is remembered alongside the owner and is what :func:`wanted` compares
    against: it says how hard it would be to justify making this holder wait. Named so
    rather than ``level`` because :func:`level` reads it back, and a parameter that
    shadows the function answering it is a trap for the next edit.
    """
    with _lock:
        held = _held.get(key)
        if held is not None:
            return held[0]
        _held[key] = (str(owner or "?"), int(urgency))
        return None


def release(key) -> None:
    """Let ``key`` go. Harmless for one that is not held."""
    with _lock:
        _held.pop(key, None)


def holder(key) -> "str | None":
    """Who holds ``key``, or ``None``."""
    with _lock:
        entry = _held.get(key)
        return entry[0] if entry is not None else None


def level(key) -> int:
    """How urgent the holder of ``key`` said it was. :data:`BACKGROUND` for a free key.

    A free key answering ``BACKGROUND`` rather than ``None`` is deliberate: every
    caller of this is about to compare, and «nobody is holding it» loses every
    comparison exactly as «a background errand is» does — which is right, because in
    both cases the newcomer may simply take it.
    """
    with _lock:
        entry = _held.get(key)
        return entry[1] if entry is not None else BACKGROUND


def held() -> dict:
    """Everything held right now — for a diagnostic, and for a test to assert emptiness."""
    with _lock:
        return {key: entry[0] for key, entry in _held.items()}


def clear() -> None:
    """Forget every claim, and every demand. A test between cases; never the panel."""
    with _lock:
        _held.clear()
        _wanted.clear()


# -- «step aside, this one matters more» (#1288) ----------------------------------
#
# A demand is NOT a lock and takes nothing: it is a note on the door saying that
# somebody more urgent is waiting outside. The holder reads it at its own checkpoints
# and decides to park; nothing here can make it. That is the whole reason this is a
# registry of notes rather than a pre-emptive lock — a scenario driving the game has to
# choose its own moment to let go, and the only moments that are safe are the ones it
# knows about (a statement boundary, a poll inside a WAIT).


def demand(key, urgency: int, owner: str):
    """Note that ``owner`` wants ``key`` at ``urgency``. Hands back a token to withdraw.

    Always succeeds and never blocks — the caller goes on to poll :func:`acquire` as
    it would have anyway. What this buys is that the CURRENT holder can now find out
    that waiting outside is somebody it should step aside for, which is the one fact
    an ordinary lock throws away.
    """
    global _serial
    with _lock:
        _serial += 1
        token = _serial
        _wanted.setdefault(key, {})[token] = (int(urgency), str(owner or "?"))
        return token


def withdraw(key, token) -> None:
    """Take a demand back off the door. Harmless for one already gone."""
    if token is None:
        return
    with _lock:
        waiting = _wanted.get(key)
        if waiting is None:
            return
        waiting.pop(token, None)
        if not waiting:
            _wanted.pop(key, None)


def wanted(key, above: int) -> "str | None":
    """Who is waiting for ``key`` at a level ABOVE ``above``, or ``None``.

    The holder asks this with its own level and parks when the answer is a name. The
    most urgent waiter is the one named, so a log line says who the run stepped aside
    for rather than merely that it did.
    """
    with _lock:
        waiting = _wanted.get(key)
        if not waiting:
            return None
        best = max(waiting.values())
        return best[1] if best[0] > int(above) else None


class Foreground:
    """The desktop's one foreground, as a context manager. ``taken`` says who has it.

    Used as::

        with Foreground(owner, exempt=is_rdp_profile) as fg:
            if fg.taken:
                return fail(fg.taken)      # somebody else is looking at the screen
            ...click, screenshot, click...

    ``exempt`` is a profile whose client is in ANOTHER Windows session: it has a desktop
    of its own, so it neither takes this nor waits for it.
    """

    __slots__ = ("owner", "exempt", "taken")

    def __init__(self, owner: str, exempt: bool = False) -> None:
        self.owner = str(owner or "?")
        self.exempt = bool(exempt)
        #: Who held it when we asked, or ``None`` — including when we did not ask.
        self.taken: "str | None" = None

    def __enter__(self) -> "Foreground":
        if not self.exempt:
            self.taken = acquire(FOREGROUND, self.owner)
        return self

    def __exit__(self, *_exc) -> bool:
        if not self.exempt and self.taken is None:
            release(FOREGROUND)
        return False
