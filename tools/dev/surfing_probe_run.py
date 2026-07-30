#!/usr/bin/env python3
r"""Freeze one Street Run attempt and dump everything the runner scene holds.

Costs ONE attempt. Starts a run, lets it load, then **pauses the game from Lua**
(`logic:PauseGame()`) so the scene can be inspected at leisure instead of during the ~3 s
an uncontrolled run survives. Dumps:

  * the logic instance's own fields (speed ramp, stage, distance, offsets);
  * the player unit (lane state: ``curLine`` / ``curX`` / ``targetX`` / ``lineChangeTimer``,
    jump/slide flags);
  * a sample of monster objects with every scalar field — the obstacle model;
  * the monster templates (``DataCenter.SurfingMonsterTemplateManager.monsterTemps``),
    which carry the type and the collider size a route planner needs;
  * the full look-ahead layout in ``farmMonster`` (the track as already decided by the
    client) — the raw material for the pattern study.

    C:\Python312\python.exe tools\dev\surfing_probe_run.py [--no-start] [--resume]
"""
from __future__ import annotations

import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "lib"))

from lua_client import get_evaluator  # noqa: E402

MARK = "SPR "

_INSTALL = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SPR "..tostring(s)) end
local okL,SL=pcall(require,"DataCenter.LWBattle.Logic.Surfing.SurfingLogic")
if okL and type(SL)=="table" and not SL.__srd_hooked then
  local o=SL.OnStart SL.OnStart=function(s,...) _G.__SR_LOGIC=s return o(s,...) end
  SL.__srd_hooked=true
end
local okM,MM=pcall(require,"Scene.LWBattle.Surfing.Monster.SurfingMonsterManager")
if okM and type(MM)=="table" and not MM.__srd_hooked then
  local o=MM.Init MM.Init=function(s,...) _G.__SR_MM=s return o(s,...) end
  MM.__srd_hooked=true
end
L("install ok")
"""

_START = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SPR "..tostring(s)) end
local ok,err = pcall(function() DataCenter.LWSurfingDataManager:ReqFightStartCheck(false) end)
L(ok and "start-sent" or ("start-err="..tostring(err)))
"""

_PAUSE = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SPR "..tostring(s)) end
local lg=_G.__SR_LOGIC
if not lg then L("no-logic") return end
local ok,err=pcall(function() lg:PauseGame() end)
L(ok and "paused" or ("pause-err="..tostring(err)))
"""

_DUMP = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SPR "..tostring(s)) end
local lg,mm=_G.__SR_LOGIC,_G.__SR_MM
if not lg then L("no-logic") return end

local function scalars(tag, o, limit)
  if type(o)~="table" then L(tag.." type="..type(o)) return end
  local ks={} for k,v in pairs(o) do ks[#ks+1]=tostring(k) end
  table.sort(ks)
  local n=0
  for _,k in ipairs(ks) do
    local v=rawget(o,k)
    local t=type(v)
    if t=="number" or t=="boolean" or t=="string" then
      L(tag.." "..k.." = "..tostring(v)); n=n+1
    elseif t=="table" then
      local c=0 for _ in pairs(v) do c=c+1 end
      L(tag.." "..k.." : table["..c.."]")
    end
    if limit and n>limit then break end
  end
end

-- 1. logic
scalars("LOGIC", lg)
for _,fn in ipairs({"GetMoveSpeed","GetJumpDuration","GetGravity","GetHeightLimit",
                    "GetTakeOffOffset","GetOffsetZ","GetStageId","GetGameScore",
                    "GetScoreMultiplier","GetCurDistanceData","GetCurDistanceView",
                    "GetPVEType","GetSwitchMonsterId"}) do
  local ok,v = pcall(function() return lg[fn](lg) end)
  L("FN "..fn.." = "..(ok and tostring(v) or "err"))
end

-- 2. player
local p=lg.player
scalars("PLAYER", p)
local okp,pos=pcall(function() return p:GetPosition() end)
if okp and pos then L("POS "..string.format("%.3f %.3f %.3f", pos.x, pos.y, pos.z)) end
for _,fn in ipairs({"IsGrounded","IsJumping","IsSliding","IsFlying","GetMoveSpeed"}) do
  local ok,v=pcall(function() return p[fn](p) end)
  L("PFN "..fn.." = "..(ok and tostring(v) or "err"))
end

-- 3. one monster of each distinct prefab, with all scalar fields
if mm then
  local seen={}
  local n=0
  for _,mon in pairs(mm.showList or {}) do
    if type(mon)=="table" then
      local nm="?" pcall(function() nm=mon.gameObject.name end)
      if not seen[nm] then
        seen[nm]=true; n=n+1
        L("MONSTER "..nm)
        scalars("  MON", mon)
        if n>=6 then break end
      end
    end
  end
end

-- 4. templates
local tm=DataCenter.SurfingMonsterTemplateManager
local temps = tm and tm.monsterTemps
if type(temps)=="table" then
  local cnt=0
  for id,t in pairs(temps) do
    cnt=cnt+1
    if cnt<=25 and type(t)=="table" then
      local ks={} for k,v in pairs(t) do if type(v)~="table" and type(v)~="function" then ks[#ks+1]=tostring(k).."="..tostring(v) end end
      table.sort(ks)
      L("TPL "..tostring(id).." { "..table.concat(ks,", ").." }")
    end
  end
  L("TPLCOUNT "..cnt)
else
  L("no-templates")
end
L("DUMPEND")
"""

# The whole decided layout ahead: farmMonster is what the client has already placed.
_LAYOUT = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SPR "..tostring(s)) end
local lg,mm=_G.__SR_LOGIC,_G.__SR_MM
if not (lg and mm) then L("no-inst") return end
local pz=0 pcall(function() pz=lg.player:GetPosition().z end)
L("PZ "..string.format("%.2f", pz))
local rows={}
local function collect(tbl, tag)
  for _,mon in pairs(tbl or {}) do
    if type(mon)=="table" then
      local z = mon.dataZ or (mon.curWorldPos and mon.curWorldPos[3]) or 0
      local nm="?" pcall(function() nm=mon.gameObject.name end)
      if nm=="?" then nm = tostring(mon.metaId or mon.bornId or "?") end
      rows[#rows+1]=string.format("%s|%s|%.2f|%s|%s|%s", tag, tostring(mon.x),
          z, tostring(mon.unitType), tostring(mon.metaId or mon.bornId), nm)
    end
  end
end
collect(mm.farmMonster, "F")
collect(mm.showList, "S")
-- flush in blocks: one LogError per line costs a stack trace, so batch them
local buf={}
for i=1,#rows do
  buf[#buf+1]=rows[i]
  if #buf>=40 then L("ROWS "..table.concat(buf,";")) buf={} end
end
if #buf>0 then L("ROWS "..table.concat(buf,";")) end
L("LAYOUTEND "..#rows)
"""


def ev_run(ev, chunk, settle=0.6):
    return [ln.split(MARK, 1)[-1].rstrip() for ln in ev.run(chunk, marker=MARK, settle=settle)
            if MARK in ln]


def main(argv):
    # Template names carry CJK — the console's cp1251 would abort the dump.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    start = "--no-start" not in argv
    ev = get_evaluator()
    try:
        for ln in ev_run(ev, _INSTALL):
            print(ln)
        if start:
            for ln in ev_run(ev, _START, settle=2.0):
                print(ln)
            print("waiting for the runner scene...")
            ok = False
            for _ in range(40):
                out = ev_run(ev, r"""
local function L(s) CS.UnityEngine.Debug.LogError("SPR "..tostring(s)) end
local lg=_G.__SR_LOGIC
L("ready="..tostring(lg~=nil and lg.player~=nil))
""", settle=0.15)
                if any("ready=true" in o for o in out):
                    ok = True
                    break
                time.sleep(0.25)
            if not ok:
                print("scene never became readable")
                return 1
            time.sleep(0.7)
            for ln in ev_run(ev, _PAUSE, settle=0.4):
                print(ln)
        out = ev_run(ev, _DUMP, settle=1.2)
        for ln in out:
            print(ln)
        rows = ev_run(ev, _LAYOUT, settle=1.2)
        outdir = os.path.join("results", "street_run", "layout")
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(outdir, "layout_%d.txt" % int(time.time()))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(rows))
        print("layout rows -> %s (%d log lines)" % (path, len(rows)))
    finally:
        ev.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
