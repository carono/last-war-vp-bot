"""The game's clock, which is **not** this computer's clock.

Every timestamp the game hands out — a dispatch's `completionTime`, a tile's
`actEndTime`, a truck's arrival — is epoch milliseconds on the clock the client
and the server agree on, and that clock is its own thing. Measured live on
2026-08-04 it ran **12 seconds ahead** of the PC it was playing on, while that PC
was within two seconds of real UTC: the drift is the game's, not the machine's,
so "just fix the computer's time" does not close it and it grows until the
client next re-syncs (the operator had been reading 25-30 s of it, task #1227).

Twelve seconds does not sound like much until you write it on screen. A tile the
game draws as «готово через 0:02» is drawn by the panel as «через 0:14», and the
person watching the two side by side has no way to tell which one is lying. It
is worse than cosmetic for the robbery: `SecretTask.can_loot` is exactly the
comparison «has `completionTime` passed *yet*», so a countdown that is a quarter
of a minute behind the game's own says "not yet" to a tile the server would
already pay out on — and the five daily robberies are the scarce thing.

So the answer is to stop comparing the game's timestamps with `time.time()` and
compare them with the game's clock instead. This module holds the difference:

    game_clock.read(ev)             # one round trip, ~0.2 s through a warm daemon
    game_clock.now_ms()             # "now" as the GAME counts it
    proto.SecretTask.can_loot       # …and everything built on it follows

**Unsynced is exactly today's behaviour.** Until somebody takes a sample the
offset is zero and `now_ms()` is `time.time()`, so a tool with no live VM (a
capture reading a pcap, a test) is neither better nor worse off than before.
Nothing here ever raises: an unreadable clock leaves the last known offset in
place, and a wrong-by-twelve-seconds countdown is still a countdown.

**One offset for the whole process, on purpose.** A panel drives several
profiles and so several clients, but they are all playing the same game against
the same time source, and the number being corrected is that source's drift from
the local machine — not something an account owns. If two clients on one machine
are ever found to disagree by more than the round trip, this is the note that
was wrong.
"""
from __future__ import annotations

import time

#: The marker the server-time read tags its line with, as every other Lua read.
MARKER = "ACT"

#: game-clock milliseconds minus local milliseconds, as of the last sample.
_offset_ms = 0
#: Host wall clock of that sample; 0.0 while nothing has ever been read.
_sampled_at = 0.0


def now_ms() -> int:
    """"Now" in the game's milliseconds — what its timestamps must be judged by."""
    return int(time.time() * 1000) + _offset_ms


def offset_ms() -> int:
    """How far ahead of this machine the game's clock is running (may be negative)."""
    return _offset_ms


def synced() -> bool:
    """Whether the offset is a measurement rather than the zero default."""
    return _sampled_at > 0.0


def age_seconds() -> float:
    """Seconds since the last sample; `inf` while there has never been one."""
    if not _sampled_at:
        return float("inf")
    return max(0.0, time.time() - _sampled_at)


def note(server_ms: int, sent: float, back: float) -> int:
    """Record one (server time, round trip) sample and return the new offset.

    `sent` / `back` are the host's `time.time()` either side of the read, so the
    reading is charged to the middle of the round trip — the moment the VM most
    likely answered. What is left over is half the round trip (~0.1 s on a warm
    daemon) plus the whole-second granularity of the game's own answer, both of
    which are noise next to the drift being corrected.

    A nonsense sample (a zero, a value from a client that has not logged in) is
    refused rather than believed: a clock that has been moved to 1970 would make
    every tile in the panel raidable at once.
    """
    global _offset_ms, _sampled_at
    if server_ms <= 0:
        return _offset_ms
    _offset_ms = int(server_ms - (sent + back) / 2 * 1000)
    _sampled_at = time.time()
    return _offset_ms


def reset() -> None:
    """Forget the measurement — the unsynced state a fresh process starts in."""
    global _offset_ms, _sampled_at
    _offset_ms = 0
    _sampled_at = 0.0


def read(ev) -> "int | None":
    """Ask the live VM what time it is and keep the answer. Offset, or None.

    None means the read brought nothing back (no daemon, no client, a busy VM) —
    the previous offset stays in force, because a stale measurement of a drift
    that moves by seconds a day beats no measurement at all.
    """
    import lua_actions                       # lazy: keeps a plain import cheap

    try:
        sent = time.time()
        lines = ev.run(lua_actions.game_server_time(), MARKER, 1.0)
        back = time.time()
    except Exception:                        # noqa: BLE001 — an unread clock is not fatal
        return None
    seconds = parse(lines)
    if seconds is None:
        return None
    return note(seconds * 1000, sent, back)


def parse(lines) -> "int | None":
    """The `ACT NOW=<seconds>` line of a read, as whole seconds. None if absent.

    Split out because the same line rides along with the bigger reads that
    already talk to the VM (the alliance-task dumps), so they can keep the offset
    fresh without paying for a round trip of their own.
    """
    for line in lines or ():
        if "NOW=" not in line:
            continue
        tail = line.split("NOW=", 1)[1].split()[0]
        try:
            return int(float(tail))
        except ValueError:
            return None
    return None
