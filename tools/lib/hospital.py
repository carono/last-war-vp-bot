r"""Heal wounded soldiers in the base hospital — the reusable core.

One press of the in-game cure button is one ``hospital.cure`` message that heals a batch
of wounded soldiers at once; the message shape and how the window builds it are written
up in ``lua_actions.hospital_cure`` / ``hospital_heal_all`` and
``docs/research/hospital-heal.md``. That research is grounded in two live traces
(``20260729_152749`` / ``152841``): the wire shape

    hospital.cure  {armyArray = [{armyId = <string>, healNum = <int>}, ...]}

is **proven**; the headless enumeration of *all* wounded (via
``T11Util.GetSelfCurSoldierData()``) still has one unconfirmed field name, so
:func:`heal_all` is best-effort and a safe no-op when it cannot build an army array —
see the module docstring notes there and run ``tools/scratch/_hospital_probe.lua`` to
close it.

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


def wounded_types(run: Run, settle: float = 0.35) -> "int | None":
    """How many soldier types have wounded to heal right now.

    ``None`` means the answer could not be read at all (daemon down, game restarting,
    Lua error) — which is not the same as zero and must not be treated as one. A confident
    zero is returned when the game is reachable but nothing is hurt (or the wounded-count
    field name still differs — a wrong guess reads as zero, never as a false positive).
    """
    chunk = ('local ok,v=pcall(function() return %s end) '
             'CS.UnityEngine.Debug.LogError("%s wounded="..(ok and tostring(v) or "ERR"))'
             % (lua_actions.hospital_wounded_count(), MARKER))
    try:
        lines = run(chunk, MARKER, settle)
    except (RuntimeError, OSError):
        return None
    for line in lines:
        if "wounded=" not in line:
            continue
        raw = line.split("wounded=", 1)[1].split()[0]
        try:
            return int(float(raw))
        except ValueError:              # "ERR" / "nil" — unreadable, not empty
            return None
    return None


# `heal_pending` is the task-tracker's name for the same wounded-type count.
heal_pending = wounded_types


def cure(run: Run, entries: Iterable[Tuple[object, int]],
         settle: float = 1.2) -> "str | None":
    """Heal the given ``(armyId, healNum)`` pairs in one ``hospital.cure``.

    The faithful, parameterised reproduction of the captured send — use it when the
    caller already knows the armyId(s) and counts. Returns the Lua error text, or None
    on success / when nothing was passed.
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
    skipped (unresolved ``T11Util`` shape) — in every case with a line through ``log``.
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
    try:
        lines = run(chunk, MARKER, settle)
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
