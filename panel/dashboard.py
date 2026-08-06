r"""The account dashboard — every daily budget on one strip, read in one call.

What the panel could never say before: *does today need me at all?* Everything that
answers it — how many robberies are left, whether the base is worth collecting, how
many mates are waiting for help, how many wounded are lying in the hospital — was
already written as a one-line Lua expression, but only ever evaluated *inside* a
press (`Button.count_lua` in tools/lib/game_buttons.py) and thrown away. This module
reads the same expressions on their own and hands the numbers back.

Three things live here and nothing else:

  * :data:`READINGS` — the list. One entry per number on the strip: an id, the Lua
    expression that produces it, the locale key of its short label, and whether a
    zero is worth showing. **Adding a number to the dashboard is adding a line
    here** plus its two locale strings.
  * :func:`build_chunk` — all of them as ONE game-VM call. A round trip costs
    ~0.15 s and the loop inside the VM is free, so thirteen readings cost the same
    as one; polling every 30 s is then nil. Each expression is wrapped in its own
    ``pcall``, so a manager that is not loaded yet (or an expression that breaks
    after a client update) costs that one reading and not the strip.
  * :func:`parse` — the answer line back into ``{id: number | None}``. ``None`` is
    "this one could not be read", which the renderer shows as ``?`` rather than as
    a zero — a budget that reads 0 and a budget that could not be read must never
    look the same.

Nothing here imports Tk or talks to the daemon: the panel passes the chunk to the
evaluator it already has and hands the lines back. That keeps "which numbers, and
what do they mean" a plain function a test can call with no display and no game.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

# tools/lib is already on sys.path when the panel imports us; a bare import keeps
# this module usable from a test that only put the repo root there.
_TOOLS_LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "tools", "lib")
if _TOOLS_LIB not in sys.path:
    sys.path.insert(0, _TOOLS_LIB)
import lua_actions      # noqa: E402

from . import debug_log

# Component debug logger (panel/debug_log.py). The panel wires the rotating file
# under it; here we only note how many readings each poll resolved.
_dbg = debug_log.get_logger("dashboard")

# The marker the chunk logs its answer under (see tools/lib/lua_eval.py — the
# evaluator returns the answer-log lines containing it).
MARKER = "DASH"
# The DEADLINE the poll gives that answer, not a pause: the caller asks for it
# `early`, so the wait ends the moment the line has landed (#1230, #1232). One
# `Debug.LogError`, and the chunk answers itself — nothing here waits on the server.
SETTLE = 0.6
# A reading that could not be evaluated.
UNREADABLE = "?"


@dataclass(frozen=True)
class Reading:
    """One number on the strip.

    ``quiet_at_zero`` is the difference between a *budget* and a *queue*. "кражи 0"
    is worth saying — it means the day is spent and no scan will help. "ждут помощи
    0" is not: it is the normal state, and a strip of ten zeroes is a strip nobody
    reads. So budgets stay on screen at zero and queues drop off it.
    """

    key: str                    # id: the parsed dict's key, and the log's
    expr: str                   # Lua expression -> a number
    label_key: str              # locale key of the short label on the strip
    quiet_at_zero: bool = True


# The strip, in reading order: what the day gives me, what is waiting for me, what
# is going on in the base. Kept to the things a person acts on — this is a display
# over the existing gates, not a new place where the bot decides anything.
READINGS: tuple[Reading, ...] = (
    # -- the day's budgets: shown even at zero, because zero is the news ------
    Reading("secret_steals", lua_actions.secret_task_steals_left(),
            "dash.secret_steals", quiet_at_zero=False),
    Reading("ghost_steals", lua_actions.ghost_recon_steals_left(),
            "dash.ghost_steals", quiet_at_zero=False),
    Reading("donate", lua_actions.alliance_donate_rest(),
            "dash.donate", quiet_at_zero=False),
    # -- what is waiting: only there when there is something ------------------
    Reading("help_waiting", lua_actions.alliance_help_waiting(), "dash.help_waiting"),
    Reading("wounded", lua_actions.hospital_wounded_total(), "dash.wounded"),
    Reading("healed", lua_actions.hospital_healed_ready(), "dash.healed"),
    Reading("visitors", lua_actions.visitor_recruit_pending(), "dash.visitors"),
    Reading("visitor_gifts", lua_actions.visitor_gift_pending(), "dash.visitor_gifts"),
    Reading("skills", lua_actions.occupation_skills_ready_count(), "dash.skills"),
    Reading("rally_joins", lua_actions.rally_joins_pending(), "dash.rally_joins"),
    Reading("treasures", lua_actions.treasure_queue_len(), "dash.treasures"),
    Reading("help_queues", lua_actions.queues_needing_help(), "dash.help_queues"),
    Reading("free_queues", lua_actions.free_build_queues(), "dash.free_queues"),
)

KEYS: tuple[str, ...] = tuple(r.key for r in READINGS)
BY_KEY: dict[str, Reading] = {r.key: r for r in READINGS}


def build_chunk(readings: "tuple[Reading, ...] | None" = None) -> str:
    """Every reading as ONE Lua chunk that logs ``DASH k=v k=v …``.

    Each expression sits in its own ``pcall``: the hospital manager is not loaded
    until the base screen is up, `ActGhostreconManager` answers nothing outside the
    event's days, and either would otherwise take the whole strip down with it. A
    failed one reports :data:`UNREADABLE` and the rest still arrive.
    """
    readings = READINGS if readings is None else readings
    lines = [
        "local out = {} ",
        "local function P(k, f) local ok, v = pcall(f) "
        "out[#out+1] = k .. '=' .. (ok and tostring(v) or '%s') end " % UNREADABLE,
    ]
    for r in readings:
        lines.append("P('%s', function() return %s end) " % (r.key, r.expr))
    lines.append('CS.UnityEngine.Debug.LogError("%s " .. table.concat(out, " "))'
                 % MARKER)
    return "".join(lines)


def parse(lines, debug=None) -> dict:
    """The chunk's answer line back into ``{key: int | float | None}``.

    ``debug`` is the caller's technical logger (`rt.dbg("dashboard")`); without one the
    module's own is used, which is the shared file — right for one open profile, and
    the reason a second one passes its own (#1206).

    ``None`` for anything the VM could not evaluate *and* for anything the line did
    not mention at all, so a caller never has to tell a missing key from a broken
    one — both mean "no reading", and the strip prints them the same.

    Reads the LAST matching line: a poll that overlapped a previous one would
    otherwise be answered with the older numbers.
    """
    dbg = debug if debug is not None else _dbg
    out: dict = {key: None for key in KEYS}
    payload = None
    for line in lines or ():
        _head, sep, tail = line.partition(MARKER + " ")
        if sep:
            payload = tail
    if payload is None:
        dbg.debug("no answer line (marker %r) in the poll output", MARKER)
        return out
    for token in payload.split():
        key, sep, raw = token.partition("=")
        if not sep or key not in out:
            continue
        out[key] = _number(raw)
    dbg.debug("read %d/%d readings", sum(v is not None for v in out.values()), len(out))
    return out


def _number(raw: str):
    """A Lua ``tostring`` of a number back into one; anything else is no reading.

    Lua prints an integer count as ``3`` on 5.3+ and as ``3.0`` on 5.1 — both have
    to read as 3, so the float is taken first and narrowed.
    """
    raw = (raw or "").strip()
    if not raw or raw == UNREADABLE:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return int(value) if value.is_integer() else value


def visible(values: dict, readings: "tuple[Reading, ...] | None" = None) -> list:
    """The readings worth putting on the strip, as ``(Reading, value)``.

    A queue reading of exactly 0 is dropped (see :class:`Reading`); an unreadable
    one is kept, because "не читается" is something the operator needs to see —
    that is what a dead daemon or a client update looks like from here.
    """
    readings = READINGS if readings is None else readings
    out = []
    for r in readings:
        value = values.get(r.key)
        if r.quiet_at_zero and value == 0:
            continue
        out.append((r, value))
    return out
