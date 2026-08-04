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

#: ``key -> owner`` for every claim currently held in this process.
_held: dict = {}
_lock = threading.Lock()

#: The key the foreground claim is filed under. A string rather than a tuple so it can
#: never collide with a client's ``(host, port)``.
FOREGROUND = "foreground"


def acquire(key, owner: str) -> "str | None":
    """Take ``key`` for ``owner``. ``None`` when it was taken; else who is holding it.

    Deliberately inverted — ``None`` means success — because the interesting answer is
    the WHO, and a caller that only wants a bool writes ``if acquire(...) is None``.
    """
    with _lock:
        held = _held.get(key)
        if held is not None:
            return held
        _held[key] = str(owner or "?")
        return None


def release(key) -> None:
    """Let ``key`` go. Harmless for one that is not held."""
    with _lock:
        _held.pop(key, None)


def holder(key) -> "str | None":
    """Who holds ``key``, or ``None``."""
    with _lock:
        return _held.get(key)


def held() -> dict:
    """Everything held right now — for a diagnostic, and for a test to assert emptiness."""
    with _lock:
        return dict(_held)


def clear() -> None:
    """Forget every claim. A test between cases; never the panel."""
    with _lock:
        _held.clear()


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
