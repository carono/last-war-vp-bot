#!/usr/bin/env python3
r"""Dump the Street Run track's generative config out of the live client — the pattern study.

The runner's track is not random noise: it is assembled from a small library of **born
patterns** (obstacle groups with fixed lane/offset coordinates) laid down inside 66-unit
scene chunks, and the chunk pool + run speed change with distance. Three config tables
hold all of it, and the client parses them into Lua at run start:

  ``SurfingStageTemplateManager``       — the stage (50000): scene pools, hero, camera.
  ``SurfingStageSceneTemplateManager``  — distance bands: ``max_meters``, ``speedZ``,
                                          the ``sceneIds`` pool and ``farmMonster`` list.
  ``SurfingMonsterBornTemplateManager`` — the 50-odd **patterns**: for each, the monster
                                          ids and their ``coord`` (lane x / z offsets).

Written to ``results/street_run/config/*.json`` so the planner and the offline simulator
can be tuned without touching the game. Run it while a surfing battle is loaded (the
tables are populated on stage load; a paused run is ideal).

    C:\Python312\python.exe tools\dev\surfing_dump_config.py
"""
from __future__ import annotations

import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "lib"))

from lua_client import get_evaluator  # noqa: E402

MARK = "SDC "

# One LogError per record: every call costs a stack trace in Player.log, so the record is
# serialised compactly (a JSON-ish flat encoding) instead of one line per field.
_DUMP = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SDC "..tostring(s)) end

-- minimal serialiser: tables become {k=v,...} / [v,v,...], scalars stringify
local function ser(v, depth)
  depth = depth or 0
  local t = type(v)
  if t == "number" or t == "boolean" then return tostring(v) end
  if t == "string" then return '"' .. v:gsub('"', "'") .. '"' end
  if t ~= "table" or depth > 4 then return '"<' .. t .. '>"' end
  local isArr = true
  local n = 0
  for k in pairs(v) do
    n = n + 1
    if type(k) ~= "number" then isArr = false end
  end
  local parts = {}
  if isArr then
    for i = 1, n do parts[#parts+1] = ser(v[i], depth + 1) end
    return "[" .. table.concat(parts, ",") .. "]"
  end
  local ks = {}
  for k in pairs(v) do if k ~= "_class_type" and k ~= "__ctype" then ks[#ks+1] = tostring(k) end end
  table.sort(ks)
  for _, k in ipairs(ks) do parts[#parts+1] = '"' .. k .. '":' .. ser(v[k], depth + 1) end
  return "{" .. table.concat(parts, ",") .. "}"
end

local function dump(tag, mgr, field)
  local m = DataCenter[mgr]
  local tbl = m and m[field]
  if type(tbl) ~= "table" then L("MISS " .. tag) return end
  local n = 0
  for id, t in pairs(tbl) do
    n = n + 1
    L(tag .. " " .. tostring(id) .. " " .. ser(t))
  end
  L("COUNT " .. tag .. " " .. n)
end

dump("BORN",  "SurfingMonsterBornTemplateManager", "monsterBornTemps")
dump("SCENE", "SurfingStageSceneTemplateManager",  "stageSceneTemps")
dump("MON",   "SurfingMonsterTemplateManager",     "monsterTemps")
dump("STAGE", "SurfingStageTemplateManager",       "stageTemps")
L("END")
"""


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ev = get_evaluator()
    try:
        lines = ev.run(_DUMP, marker=MARK, settle=3.0)
    finally:
        ev.close()
    buckets: dict[str, dict] = {"BORN": {}, "SCENE": {}, "MON": {}, "STAGE": {}}
    counts = {}
    for ln in lines:
        body = ln.split(MARK, 1)[-1].strip()
        tag, _, rest = body.partition(" ")
        if tag == "COUNT":
            k, _, v = rest.partition(" ")
            counts[k] = int(v)
            continue
        if tag not in buckets:
            continue
        ident, _, payload = rest.partition(" ")
        try:
            buckets[tag][ident] = json.loads(payload)
        except ValueError:
            buckets[tag][ident] = {"_raw": payload}
    outdir = os.path.join("results", "street_run", "config")
    os.makedirs(outdir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for tag, data in buckets.items():
        if not data:
            print("%-6s : EMPTY (table not loaded — start/pause a run first)" % tag)
            continue
        path = os.path.join(outdir, "%s.json" % tag.lower())
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
        print("%-6s : %4d records -> %s (reported %s)" % (tag, len(data), path, counts.get(tag, "?")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
