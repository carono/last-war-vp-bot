"""The game's clock, which is **not** this computer's clock.

Every timestamp the game hands out — a dispatch's `completionTime`, a tile's
`actEndTime`, a truck's arrival — is epoch milliseconds on the clock the client
and the server agree on, and the client keeps it as an offset from the device's
rather than reading the device's at all (`UITimeManager.serverDeltaTime`).

Measured live on 2026-08-04 the two were **eleven seconds apart**, and it is the
PC that is wrong: back-to-back samples put the Windows clock 10.93 s BEHIND the
WSL clock on the same machine, and the WSL one within a couple of seconds of real
UTC against an internet `Date:` header. The game's time matched real UTC. So the
game is right and the machine is slow — a Windows time-sync problem that would
also be worth fixing, and that the panel must not depend on anybody fixing. The
operator was reading 25-30 s of the same drift (task #1227).

Eleven seconds does not sound like much until you write it on screen. A tile the
game draws as «готово через 0:02» is drawn by the panel as «через 0:13», and the
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

The number read is the very one the client's own countdown uses:
`ActDispatchTaskDataManager.RefreshCompleteTimer`, string-dumped out of the live
VM, is `completionTime` minus a `curTime` from `UITimeManager` — and there is no
other event in it and no travel time added, which was the other thing #1227 had
to rule out.

**Unsynced is exactly today's behaviour.** Until somebody takes a sample the
offset is zero and `now_ms()` is `time.time()`, so a tool with no live VM (a
capture reading a pcap, a test) is neither better nor worse off than before.
Nothing here ever raises: an unreadable clock leaves the last known offset in
place, and a countdown that is out by the drift is still a countdown.

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

#: Anything before this is not a clock at all. A client that has not logged in has
#: no server time to give: `UITimeManager.serverDeltaTime` is still 0, so its
#: `GetServerTime()` answers with the process's own uptime — 6 280 648 ms on the
#: second client, an hour and three quarters after it was started (#1227). That is
#: not an error and nothing raises; it is simply a number, and believing it would
#: put the game's clock in 1970 and make every tile on the map read as long expired.
#: 1.5e12 ms is 2017-07 — after this game existed, before any plausible uptime.
EPOCH_FLOOR_MS = 1_500_000_000_000

#: …and a real clock is never this far from the machine's. Six hours is far wider
#: than any drift or time-zone confusion worth correcting and far narrower than the
#: half-century a bogus sample is out by.
MAX_SKEW_MS = 6 * 60 * 60 * 1000

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
    daemon), which is noise next to the drift being corrected.

    A sample that is not a clock is refused rather than believed — see
    :func:`plausible`. That is not a theoretical guard: a client sitting at the
    login screen answers with its own uptime, cheerfully and without an error.
    """
    global _offset_ms, _sampled_at
    if not plausible(server_ms):
        return _offset_ms
    _offset_ms = int(server_ms - (sent + back) / 2 * 1000)
    _sampled_at = time.time()
    return _offset_ms


def plausible(server_ms) -> bool:
    """Whether `server_ms` is a real epoch clock and not something else entirely.

    Two ways it is not. It can be a client's uptime, which is what a game that has
    not logged in hands out — no error, no zero, just a small number that would
    move the game's clock to 1970. And it can be an epoch clock that is hours away
    from this machine's, which is not a drift to correct but a sign the sample
    belongs to something else.

    Used as the login test too: a client that cannot say what time it is has not
    finished logging in, and nothing else it says about tiles or budgets is worth
    acting on either.
    """
    try:
        value = int(server_ms)
    except (TypeError, ValueError):
        return False
    if value < EPOCH_FLOOR_MS:
        return False
    return abs(value - int(time.time() * 1000)) <= MAX_SKEW_MS


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

    THE SETTLE IS A DEADLINE, NOT A PAUSE (`early`, #1290). The chunk reads a field the
    client already holds and logs it as it goes, so the answer is in the file before the
    injection returns; sitting out the whole second was pure waiting. Measured live:
    1055 ms patient against 90 ms early, for the same line. It matters far past this
    module — `session_ready` is the second half of the link gate every scenario passes
    through, so every recipe in the tree started a second sooner.

    The round trip is also what `note()` halves into a latency, and `early` only ends
    the WAIT sooner: `sent`/`back` still bracket the same injection, so the offset is if
    anything measured more tightly than before.
    """
    import lua_actions                       # lazy: keeps a plain import cheap

    try:
        sent = time.time()
        lines = ev.run(lua_actions.game_server_time(), MARKER, 1.0, early=True)
        back = time.time()
    except Exception:                        # noqa: BLE001 — an unread clock is not fatal
        return None
    server_ms = parse_ms(lines)
    if server_ms is None or not plausible(server_ms):
        # Nothing came back, or what came back is not a clock — a client at the
        # login screen answers with its own uptime. Either way this is not a
        # measurement, and `session_ready` reads the None as "not logged in".
        return None
    return note(server_ms, sent, back)


def session_ready(ev) -> bool:
    """Whether the client is far enough into a session to be worth asking anything.

    A client at the login screen answers every question — the alliance has no
    tasks, the own server is `-1`, the day's robberies read as all five unspent —
    and every one of those answers is a plausible-looking lie. It cannot say what
    time it is, though, so that is the question to ask first (#1227).

    False also when the daemon is down or the read failed: either way there is
    nothing to act on.

    **WHY THE CLOCK ALONE SAID YES TO A KICKED CLIENT** (#1270). The offset this reads
    is `UITimeManager.serverDeltaTime`, and the client keeps it as a difference from the
    DEVICE's clock rather than asking the server for the time (see the module note). It
    is set when the session begins and it survives the session ending: an account taken
    by another device leaves a client that still answers with a perfectly plausible
    epoch, and on 2026-08-07 this returned `True` for two and a quarter hours with the
    kick modal on screen. The clock proves the client HAS logged in. It has never proved
    the client still IS in a session, and reading it as though it did is the fifth
    instance of one reading being used to choose between two states
    (docs/research/server-link-status.md §5).

    So the kick is asked too, and only a POSITIVE one refuses: `game_kick.read` answers
    `None` for every way of not knowing, and this helper already fails closed on a read
    it could not make — turning «could not ask about the kick» into `False` as well would
    strand a healthy client behind a question nobody could answer.
    """
    if read(ev) is None:
        return False
    try:
        import game_kick                     # lazy: keeps a plain import cheap

        return game_kick.read(ev) is not True
    except Exception:                        # noqa: BLE001 — an unasked question is not a no
        return True


def parse_ms(lines) -> "int | None":
    """The game's clock out of a read that carries it, in ms. None if absent.

    Split out because the line rides along with the bigger reads that already talk
    to the VM (the alliance-task dumps, the robbery's status read), so they keep
    the offset fresh without paying for a round trip of their own.

    `NOWMS=` is the millisecond clock the client's own countdown uses; `NOW=` is
    the whole-second fallback of the same clock, kept because a chunk written
    before this one may still be in flight somewhere.
    """
    for line in lines or ():
        if "NOWMS=" in line:
            tail = line.split("NOWMS=", 1)[1].split()[0]
            try:
                return int(float(tail))
            except ValueError:
                return None
    for line in lines or ():
        if "NOW=" in line:
            tail = line.split("NOW=", 1)[1].split()[0]
            try:
                return int(float(tail)) * 1000
            except ValueError:
                return None
    return None
