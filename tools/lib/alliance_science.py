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

  Open+donate chain (each step lands the next frame, so it is staged as separate
  daemon chunks): OpenWindow(UIAllianceScience) -> list.Ctrl:OnScienceInfoClick(rec,tab)
  -> info.Ctrl:OnResDonateClick(scienceId, resType, resNum). The press sends
  `AlScienceDonateMessage` on the wire as `al.science.donate`.
"""
from __future__ import annotations

import time
from typing import Callable

# A "run" is any `evaluator.run(chunk, marker=None, settle=1.4) -> list[str]`.
Run = Callable[..., list]
Log = Callable[[str], None]


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


def open_detail(run: Run) -> bool:
    """Open Alliance Tech and drill into the recommended tech's detail window.

    Staged as separate chunks because OpenWindow / OnScienceInfoClick each take a
    frame to land — the window is only reachable via GetStackTopWindow on the next
    call. Returns True once the top window is UIAllianceScienceInfo.
    """
    run(_L("DON") + r'''
pcall(function() UIManager.Instance:OpenWindow(UIWindowNames.UIAllianceScience) end)
L("opened list")''', "DON", 2.0)
    time.sleep(1.2)
    run(_L("DON") + r'''
local w=UIManager.Instance:GetStackTopWindow()
if w and tostring(w.Name)=="UIAllianceScience" then
  local rec=DataCenter.AllianceScienceDataManager:GetCurRecommendScience()
  pcall(function() w.Ctrl:OnScienceInfoClick(rec, nil) end)
  L("info clicked")
else
  L("list not on top: "..tostring(w and w.Name))
end''', "DON", 2.0)
    time.sleep(1.2)
    lines = run(_L("DON") + r'''
local w=UIManager.Instance:GetStackTopWindow()
L("top="..tostring(w and w.Name))''', "DON", 1.4)
    return any("top=UIAllianceScienceInfo" in ln for ln in lines)


def _rest_count(run: Run, use_gold: bool) -> int:
    """Read the remaining donate attempts (resource or gold)."""
    getter = "GetGoldDonateRestCount" if use_gold else "GetResDonateRestCount"
    lines = run(
        _L("DON") + '\nL("rest="..tostring(DataCenter.AllianceScienceDataManager:%s()))'
        % getter, "DON", 0.4)
    for ln in lines:
        if "rest=" in ln:
            try:
                return int(float(ln.split("rest=", 1)[1].split()[0]))
            except ValueError:
                return 0
    return 0


def press_donate(run: Run, use_gold: bool, cap: int | None,
                 settle_after: float = 0.12, recheck_every: int = 5) -> int:
    """Press the donate button once per chunk until attempts run out (or `cap`). Returns presses.

    CRITICAL: one press per Lua chunk, with a pause between presses. A donation only
    lowers the remaining-attempts count AFTER the server replies to `al.science.donate`,
    so a tight in-Lua `while` loop never sees the count drop, spins forever on the
    main thread and FREEZES the client. Looping here (Python side) with a pause between
    presses lets the round-trip land — mirrors the DSL recipe donate_alliance_tech.md.

    The remaining-attempts count is re-read once every `recheck_every` presses, not
    before each one: a press spends exactly one attempt, and one past the quota is
    gated server-side, so the extra read only cost wall-clock. That, plus the short
    `settle_after`, is what makes this run at the pace of holding the button in game.
    """
    method = "OnGoldDonateClick" if use_gold else "OnResDonateClick"
    # Res press: (scienceId, resType, resNum). Gold press: (scienceId, goldNum).
    # btnPos/techPointPos are only the fly-animation anchors — nil is fine.
    args = "rec.scienceId, rec.goldNum, nil, nil" if use_gold \
        else "rec.scienceId, rec.res, rec.resNum, nil, nil"
    press = _L("DON") + r'''
local m=DataCenter.AllianceScienceDataManager
local w=UIManager.Instance:GetStackTopWindow()
if not (w and tostring(w.Name)=="UIAllianceScienceInfo") then L("no detail: "..tostring(w and w.Name)) return end
local rec=m:GetCurRecommendScience()
pcall(function() w.Ctrl:%s(%s) end)
L("pressed one")''' % (method, args)

    n = 0
    limit = cap if cap is not None else 1000  # hard backstop against a runaway loop
    every = max(1, recheck_every)
    rest = 0
    while n < limit:
        if n % every == 0:                 # re-read the real count once per batch
            rest = _rest_count(run, use_gold)
        if rest <= 0:
            break
        run(press, "DON", 0.3)
        n += 1
        rest -= 1                          # assumed; the next re-read corrects it
        time.sleep(settle_after)   # let the server apply this donation before the next press
    return n


def donate_priority(run: Run, *, use_gold: bool = False, cap: int | None = None,
                    log: Log = print) -> dict:
    """Donate every accumulated attempt to the priority tech. Orchestrates the chain.

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

    if not open_detail(run):
        log("could not reach the tech detail window (open Alliance Tech from the city view)")
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
