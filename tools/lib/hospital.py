r"""Heal wounded soldiers in the base hospital — the reusable core.

One press of the in-game cure button is one ``hospital.cure`` message that heals a batch
of wounded soldiers at once; the message and where its numbers come from are written up
in ``lua_actions`` (the hospital section) and ``docs/research/hospital-heal.md``:

    hospital.cure  {armyArray = [{armyId = <string>, count = <int>}, ...], gold = 0}

The wounded themselves are ``DataCenter.HospitalManager.allHospital`` — one row per
soldier type, ``dead`` being the wounded waiting and ``heal`` those already in
treatment. Collecting the healed soldiers is the manager's own
``CheckSendFinish``, which sends ``queue.finish`` once the heal timer has run out.

The shape above is what a recorded human press actually sends — `armyArray` and `gold`,
nothing else. Sending the pay-to-finish fields alongside (`goldForTime`, `goldForResource`,
`itemIds`) makes the client build the message WITHOUT `armyArray` and the server answer
`E000000`; that bug is fixed, but a scripted heal has not yet been watched moving the
wounded count, so treat :func:`heal_all` as unproven in outcome.

Building queues are NOT a gate: the player's own heal went through with all four of them
working. An earlier version of this module claimed otherwise.

Everything runs through any evaluator exposing ``.run(chunk, marker, settle)`` — the warm
daemon client or a local ``LuaEval`` (see ``tools/lib/lua_client.py``).
"""
from __future__ import annotations

import os
import sys
from typing import Callable, Iterable, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lua_actions  # noqa: E402

# A "run" is any `evaluator.run(chunk, marker=None, settle=1.2) -> list[str]`.
Run = Callable[..., list]
Log = Callable[[str], None]

MARKER = "HOSP"


def _count(run: Run, expr: str, tag: str, settle: float) -> "int | None":
    """Evaluate a Lua counting expression. ``None`` = unreadable, never a silent zero."""
    chunk = ('local ok,v=pcall(function() return %s end) '
             'CS.UnityEngine.Debug.LogError("%s %s="..(ok and tostring(v) or "ERR"))'
             % (expr, MARKER, tag))
    try:
        lines = run(chunk, MARKER, settle)
    except (RuntimeError, OSError):
        return None
    needle = tag + "="
    for line in lines:
        if needle not in line:
            continue
        raw = line.split(needle, 1)[1].split()[0]
        try:
            return int(float(raw))
        except ValueError:              # "ERR" / "nil" — unreadable, not empty
            return None
    return None


def wounded_types(run: Run, settle: float = 0.35) -> "int | None":
    """How many soldier types have wounded to heal right now.

    ``None`` means the answer could not be read at all (daemon down, game restarting,
    Lua error) — which is not the same as zero and must not be treated as one. A
    confident zero is returned when the game is reachable and nothing is hurt.
    """
    return _count(run, lua_actions.hospital_wounded_count(), "wounded", settle)


def healed_ready(run: Run, settle: float = 0.35) -> "int | None":
    """1 when a finished heal is waiting to be collected, 0 while it is still running."""
    return _count(run, lua_actions.hospital_healed_ready(), "ready", settle)


def free_build_queues(run: Run, settle: float = 0.35) -> "int | None":
    """How many building queues are idle. Diagnostic only — a heal does NOT need one."""
    return _count(run, lua_actions.free_build_queues(), "freeq", settle)


# `heal_pending` is the task-tracker's name for the same wounded-type count.
heal_pending = wounded_types


def cure(run: Run, entries: Iterable[Tuple[object, int]],
         settle: float = 1.2) -> "str | None":
    """Heal the given ``(armyId, count)`` pairs in one ``hospital.cure``.

    The faithful, parameterised reproduction of the in-game press — use it when the
    caller already knows the armyId(s) and counts. Returns the Lua error text, or None
    on success / when nothing was passed. A server-side refusal (a busy base, say) does
    not surface here: it comes back asynchronously as the game's own on-screen tip.
    """
    entries = list(entries)
    if not entries:
        return None
    chunk = lua_actions.hospital_cure(entries)
    try:
        run(chunk, "ACT", settle)
    except (RuntimeError, OSError) as exc:
        return str(exc)
    return None


def heal_all(run: Run, log: "Log | None" = None, settle: float = 1.2) -> int:
    """Heal every wounded soldier type once. Returns how many types it healed.

    Gated on there being wounded to heal, the same way the in-game press is only useful
    with hurt soldiers, so a healthy army costs no server round trip. Returns 0 when
    nothing was wounded, when the game VM could not be reached, or when the send was
    skipped — in every case with a line through ``log``.

    The count returned is how many soldier types went into the message, not a promise that
    the server accepted it — a refusal comes back asynchronously as the game's own tip.
    """
    say: Log = log or (lambda _m: None)
    n = wounded_types(run)
    if n is None:
        say("game VM unreachable — no heal sent")
        return 0
    if n <= 0:
        say("no wounded soldiers — nothing to heal")
        return 0
    chunk = ('local ok,err=pcall(function() %s end) '
             'CS.UnityEngine.Debug.LogError("%s heal="..(ok and "ok" or ("ERR:"..tostring(err))))'
             % (lua_actions.hospital_heal_all(), MARKER))
    # No marker: the send reports itself under `ACT` and the wrapper under `HOSP`, and the
    # reader filters on one marker only — asking for either would throw the other away.
    try:
        lines = run(chunk, None, settle)
    except (RuntimeError, OSError) as exc:
        say(f"hospital.cure failed: {exc}")
        return 0
    for line in lines:
        if "heal=ERR:" in line:
            say(f"hospital.cure failed: {line.split('heal=ERR:', 1)[1].strip()}")
            return 0
        if "hospital_heal_all skip:" in line:
            say(f"heal skipped: {line.split('skip:', 1)[1].strip()}")
            return 0
    say(f"healed {n} soldier type(s)")
    return n


def collect(run: Run, log: "Log | None" = None, settle: float = 1.0) -> int:
    """Collect the healed soldiers. Returns 1 when the press went out, else 0.

    Gated on the heal queue having actually finished, so pressing at any time is safe:
    a heal still running costs nothing. The press itself is the game's own
    ``CheckSendFinish``, which refuses again on its side if the soldiers would overflow
    the barracks — that refusal shows as the game's tip, not as a return value here.
    """
    say: Log = log or (lambda _m: None)
    ready = healed_ready(run)
    if ready is None:
        say("game VM unreachable — nothing collected")
        return 0
    if ready <= 0:
        say("no finished heal to collect")
        return 0
    try:
        lines = run(lua_actions.hospital_collect(), "ACT", settle)
    except (RuntimeError, OSError) as exc:
        say(f"collect failed: {exc}")
        return 0
    for line in lines:
        if "hospital_collect skip:" in line:
            say(f"collect skipped: {line.split('skip:', 1)[1].strip()}")
            return 0
    say("collected the healed soldiers")
    return 1
