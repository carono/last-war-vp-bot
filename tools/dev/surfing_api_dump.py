#!/usr/bin/env python3
r"""Dump the Street Run («Уличный забег» / Surfing) runner API out of the live Lua VM.

The dodge quality is capped by two unknowns that only the client can answer:

  * **how the avatar is steered** — the keyboard is a ~0.1 s round trip through
    pydirectinput; if the runner logic exposes a lane-change / jump call, the dodge can be
    issued from Lua at frame precision instead;
  * **the motion constants** — lane-switch duration, jump airtime, obstacle z-extent —
    without them a route planner cannot know whether a gap is actually reachable.

This tool lists the runner's modules and their members, and (with `src`) prints the
readable strings of a chosen function via `string.dump` — the poor-man's decompiler used
elsewhere in this repo to tell a sender from a reply applier.

    C:\Python312\python.exe tools\dev\surfing_api_dump.py mods
    C:\Python312\python.exe tools\dev\surfing_api_dump.py api  [Module.Name]
    C:\Python312\python.exe tools\dev\surfing_api_dump.py src  Module.Name Method
    C:\Python312\python.exe tools\dev\surfing_api_dump.py live            # in-run objects
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

from lua_client import get_evaluator  # noqa: E402

MARK = "SAD "

_MODS = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SAD "..tostring(s)) end
local seen = {}
for k, v in pairs(package.loaded) do
  local lk = string.lower(k)
  if string.find(lk, "surfing", 1, true) or string.find(lk, "parkour", 1, true) then
    seen[#seen+1] = k
  end
end
table.sort(seen)
for _, k in ipairs(seen) do L("MOD " .. k) end
L("END " .. #seen)
"""

_API = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SAD "..tostring(s)) end
local ok, m = pcall(require, "%s")
if not ok or type(m) ~= "table" then L("ERR no-module") return end
local keys = {}
for k, v in pairs(m) do keys[#keys+1] = k end
table.sort(keys)
for _, k in ipairs(keys) do L("K " .. k .. " : " .. type(m[k])) end
L("END " .. #keys)
"""

# Readable string constants of one function — enough to tell what it sends/calls.
_SRC = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SAD "..tostring(s)) end
local ok, m = pcall(require, "%s")
if not ok or type(m) ~= "table" then L("ERR no-module") return end
local f = m["%s"]
if type(f) ~= "function" then L("ERR not-a-function") return end
local ok2, blob = pcall(string.dump, f)
if not ok2 then L("ERR nodump " .. tostring(blob)) return end
local out, cur = {}, {}
for i = 1, #blob do
  local c = blob:byte(i)
  if c >= 32 and c < 127 then cur[#cur+1] = string.char(c)
  else
    if #cur >= 4 then out[#out+1] = table.concat(cur) end
    cur = {}
  end
end
if #cur >= 4 then out[#out+1] = table.concat(cur) end
for _, s in ipairs(out) do L("S " .. s) end
L("END " .. #out .. " len=" .. #blob)
"""

# What the live run objects look like: the captured logic/manager plus the player object.
_LIVE = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SAD "..tostring(s)) end
local lg, mm = _G.__SR_LOGIC, _G.__SR_MM
L("logic=" .. tostring(lg ~= nil) .. " mm=" .. tostring(mm ~= nil))
local function dumpobj(tag, o, deep)
  if type(o) ~= "table" then L(tag .. " type=" .. type(o)) return end
  local keys = {}
  for k, v in pairs(o) do keys[#keys+1] = tostring(k) end
  table.sort(keys)
  for _, k in ipairs(keys) do
    local v = rawget(o, k)
    local t = type(v)
    local extra = ""
    if t == "number" or t == "boolean" or t == "string" then extra = " = " .. tostring(v) end
    L(tag .. "." .. k .. " : " .. t .. extra)
  end
  local mt = getmetatable(o)
  if mt and mt.__index and type(mt.__index) == "table" and deep then
    local mk = {}
    for k, v in pairs(mt.__index) do mk[#mk+1] = tostring(k) end
    table.sort(mk)
    for _, k in ipairs(mk) do L(tag .. ":" .. k .. " : " .. type(mt.__index[k])) end
  end
end
if lg then dumpobj("LOGIC", lg, true) end
if lg and lg.player then dumpobj("PLAYER", lg.player, true) end
if mm then dumpobj("MM", mm, true) end
L("END")
"""


def run(chunk: str, settle: float = 0.6):
    ev = get_evaluator()
    try:
        lines = ev.run(chunk, marker=MARK, settle=settle)
    finally:
        ev.close()
    out = []
    for ln in lines:
        if MARK in ln:
            out.append(ln.split(MARK, 1)[-1].rstrip())
    return out


def main(argv):
    cmd = argv[0] if argv else "mods"
    if cmd == "mods":
        for ln in run(_MODS):
            print(ln)
        return 0
    if cmd == "api":
        mod = argv[1] if len(argv) > 1 else "DataCenter.LWBattle.Logic.Surfing.SurfingLogic"
        for ln in run(_API % mod):
            print(ln)
        return 0
    if cmd == "src":
        if len(argv) < 3:
            print("usage: src Module.Name Method")
            return 1
        for ln in run(_SRC % (argv[1], argv[2]), settle=0.8):
            print(ln)
        return 0
    if cmd == "live":
        for ln in run(_LIVE, settle=0.8):
            print(ln)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
