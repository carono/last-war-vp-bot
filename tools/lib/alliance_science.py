r"""Alliance-tech (alliance science) donation — reusable core.

Single source of truth for "donate to the alliance's PRIORITY tech" on the Python
side, used by the standalone CLI (`tools/alliance_donate.py`). The DSL reaches the
same buttons through `TAP` and the catalogue in tools/lib/game_buttons.py — see the
recipe src/lastwar_bot/actions/donate_alliance_tech.md. Everything runs inside the
game's own Lua VM through any evaluator exposing `.run(chunk, marker, settle)` — the
warm daemon client or a local `LuaEval` (see tools/lib/lua_client.py).

The confirmed API (live-probed, game running) is written up in
docs/research/alliance-tech-donate.md. In short:

  DataCenter.AllianceScienceDataManager
    :GetCurRecommendScience()   -> the PRIORITY tech (a science-data object)
    :GetResDonateRestCount()    -> resource ("Donate 1000") attempts left today
    :GetResDonateMaxCount()     -> daily cap (30)
    :GetGoldDonateRestCount()   -> diamond-donate attempts left
    :GetCanDonate()             -> master gate

  The donation itself is `UIAllianceScienceInfoCtrl.OnResDonateClick(nil, scienceId,
  resType, resNum)` — headless, no window open, and safe to repeat inside one chunk;
  the Lua and the reverse-engineering behind it live in
  `lua_actions.alliance_donate_batch`. Each press sends `AlScienceDonateMessage`, on
  the wire `al.science.donate`.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lua_actions as _lua_actions  # noqa: E402

# A "run" is any `evaluator.run(chunk, marker=None, settle=1.4) -> list[str]`.
Run = Callable[..., list]
Log = Callable[[str], None]


# How long a chunk is given to reach Player.log before its lines are read back.
#
# Both numbers are read waits now: a donate round reports how many presses it fired
# (`fired=`) and the caller acts on it, exactly as a count read reports `rest=`. 0.1 s
# is enough for a line already written (measured: a round trip through the daemon plus
# the log read is ~0.15 s at settle=0); the count read keeps the longer 0.4 s it has
# always run at, just above the DSL's own 0.35 (script_engine._eval_lua_value).
_PRESS_SETTLE = 0.1
_READ_SETTLE = 0.4


def _L(name: str) -> str:
    """Lua logger prefix helper — mirrors the marker convention of the other tools."""
    return 'local L=function(s) CS.UnityEngine.Debug.LogError("%s "..tostring(s)) end' % name


def read_status(run: Run) -> dict:
    """Read the recommended tech and the donate counters. Read-only, no send."""
    lines = run(
        _L("DON") + r'''
local m=DataCenter.AllianceScienceDataManager
local rec=m:GetCurRecommendScience()
L("recId="..tostring(rec and rec.scienceId))
L("res="..tostring(rec and rec.res))
L("resNum="..tostring(rec and rec.resNum))
L("curLevel="..tostring(rec and rec.curLevel).."/"..tostring(rec and rec.maxLevel))
L("progress="..tostring(rec and rec.currentPro).."/"..tostring(rec and rec.needPro))
L("resRest="..tostring(m:GetResDonateRestCount()).."/"..tostring(m:GetResDonateMaxCount()))
L("goldRest="..tostring(m:GetGoldDonateRestCount()))
L("canDonate="..tostring(m:GetCanDonate()))
L("DON end")''', "DON", 1.4)
    out = {}
    for ln in lines:
        if "DON " not in ln:
            continue
        body = ln.split("DON ", 1)[1].strip()
        if "=" in body and body != "end":
            k, _, v = body.partition("=")
            out[k] = v
    return out


def _rest_count(run: Run, use_gold: bool) -> int:
    """Read the remaining donate attempts (resource or gold)."""
    getter = "GetGoldDonateRestCount" if use_gold else "GetResDonateRestCount"
    lines = run(
        _L("DON") + '\nL("rest="..tostring(DataCenter.AllianceScienceDataManager:%s()))'
        % getter, "DON", _READ_SETTLE)
    for ln in lines:
        if "rest=" in ln:
            try:
                return int(float(ln.split("rest=", 1)[1].split()[0]))
            except ValueError:
                return 0
    return 0


def press_donate(run: Run, use_gold: bool, cap: int | None,
                 settle_after: float = 0.5) -> int:
    """Donate every banked attempt (or `cap` of them). Returns the number of presses.

    One round = read the real count, spend exactly that many presses inside ONE Lua
    chunk, pause for the server, read again. Two or three rounds cover a whole quota,
    so a full 30 attempts cost seconds instead of half a minute — the round trip into
    the game VM (~0.15 s) is the entire cost of a press, and the loop inside the chunk
    is free. The chunk itself is `lua_actions.alliance_donate_batch`, the same one the
    DSL button `donate_1000` fires, and it needs no window open.

    CRITICAL, and the reason the chunk counts to a FIXED number: the remaining-attempts
    count only drops AFTER the server replies to `al.science.donate`, so a
    `while rest > 0` loop written in Lua never sees it fall, spins on the main thread
    and FREEZES the client. Nothing inside a round waits; the waiting happens here,
    between rounds, which is what `settle_after` is for.

    A round that fires nothing ends the loop, so a count that refuses to fall (or a
    batch that ran out of resources) stops the run instead of looping on it.
    """
    batch = _L("DON") + "\n" + _lua_actions.alliance_donate_batch(use_gold) \
        + '\nL("fired="..tostring(fired))'

    n = 0
    limit = cap if cap is not None else 1000  # hard backstop against a runaway loop
    while n < limit:
        rest = _rest_count(run, use_gold)
        want = min(rest, limit - n)
        if want <= 0:
            break
        lines = run("local n=%d\n%s" % (want, batch), "DON", _PRESS_SETTLE)
        fired = 0
        for ln in lines:
            if "fired=" in ln:
                try:
                    fired = int(float(ln.split("fired=", 1)[1].split()[0]))
                except ValueError:
                    fired = 0
        if fired <= 0:
            break
        n += fired
        time.sleep(settle_after)   # let the server apply this round before the next read
    return n


def donate_priority(run: Run, *, use_gold: bool = False, cap: int | None = None,
                    log: Log = print) -> dict:
    """Donate every accumulated attempt to the priority tech. Orchestrates the chain.

    No window is opened on the way: the donate call needs none (see `press_donate`), so
    the whole job is read the counters, spend them, read them back — the player's view
    is left exactly as it was found.

    Returns a result dict: {tech, level, pressed, before, after, skipped?}. `log` gets
    human-readable progress lines (defaults to print; the DSL passes its on_event).
    """
    st = read_status(run)
    log("priority tech: scienceId=%s level=%s progress=%s"
        % (st.get("recId"), st.get("curLevel"), st.get("progress")))
    log("attempts: resource=%s gold=%s canDonate=%s"
        % (st.get("resRest"), st.get("goldRest"), st.get("canDonate")))

    result = {"tech": st.get("recId"), "level": st.get("curLevel"),
              "before": st.get("resRest"), "pressed": 0, "after": st.get("resRest")}

    if st.get("canDonate") == "false" and not use_gold:
        log("nothing to do — GetCanDonate() is false (quota spent or no alliance)")
        result["skipped"] = True
        return result

    n = press_donate(run, use_gold=use_gold, cap=cap)
    result["pressed"] = n
    kind = "diamond" if use_gold else "resource"
    log("donated: %d %s press(es) to tech %s" % (n, kind, st.get("recId")))
    after = read_status(run)
    result["after"] = after.get("resRest")
    log("remaining: resource=%s gold=%s" % (after.get("resRest"), after.get("goldRest")))
    return result
