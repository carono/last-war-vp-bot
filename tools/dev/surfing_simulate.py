#!/usr/bin/env python3
r"""Dry-run the Street Run autopilot against the real track — WITHOUT spending an attempt.

The track is not random. It is a chain of 330-metre **bands**, and every band's obstacles
come from the born templates dumped by ``surfing_dump_config.py`` — an absolute lane x and
world z each. So the route planner can be exercised on the genuine obstacle field, band by
band, as often as needed.

The simulation runs **inside the game's Lua VM** and calls the very same
``_G.__SR_AI.planRoute`` the live autopilot uses — one implementation, no drifting Python
mirror. It steps a virtual avatar at 60 Hz with the real motion constants (0.16 s lane
change, 0.72 s hop), applies the planner's moves, drives the moving obstacles at their own
speed, and collides against a *truth* model whose sizes are deliberately independent of the
planner's safety padding. Obstacle classification is injected from the config, so a band
whose templates the client has not loaded still simulates correctly.

    C:\Python312\python.exe tools\dev\surfing_simulate.py            # every band, every start lane
    C:\Python312\python.exe tools\dev\surfing_simulate.py 3001       # one band
    C:\Python312\python.exe tools\dev\surfing_simulate.py 3001 0     # one band, starting left

A band that dies prints the killing obstacle — the exact input for retuning
``tools/lib/surfing_ai.lua`` before burning a live attempt.
"""
from __future__ import annotations

import collections
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "lib"))

from lua_client import get_evaluator  # noqa: E402

MARK = "SSIM "
CONFIG = os.path.join("results", "street_run", "config")
LANE_NAME = {0: "left", 1: "centre", 2: "right"}


def load_config():
    try:
        with open(os.path.join(CONFIG, "born.json"), "r", encoding="utf-8") as fh:
            born = json.load(fh)
        with open(os.path.join(CONFIG, "mon.json"), "r", encoding="utf-8") as fh:
            mon = json.load(fh)
    except OSError as exc:
        raise SystemExit(
            "no track config in %s (%s).\nDump it first — the tables are populated while a "
            "surfing battle is loaded:\n"
            "    C:\\Python312\\python.exe tools\\dev\\surfing_dump_config.py" % (CONFIG, exc))
    return born, mon


def load_bounds():
    """Collider extents measured off the live objects (street_run_ai.py bounds)."""
    path = os.path.join(CONFIG, "bounds.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def classify(rec: dict, bounds: dict) -> dict:
    """What kills, what can be hopped, how far the thing reaches along the track and how
    fast it drives — the planner's rule restated over the config, using the measured
    collider extents where a prefab has been seen live.

    The carriages are the reason this matters: they hang 25-41 units BEHIND their anchor z,
    so a "half-extent around z" model both blocks free track ahead and misses the body that
    actually kills."""
    asset = (rec.get("asset") or "").lower()
    name = (rec.get("asset") or "").split("/")[-1].replace(".prefab", "")
    if (rec.get("collide_damage") or 0) <= 0:
        mt = rec.get("monster_type") or 0
        strong = mt in (5, 7, 8, 9)
        return {"solid": False, "jump": False, "slide": False, "back": 0.0, "front": 0.0,
                "lanes": 1, "speed": 0.0, "buff": (0.9 if strong else 0.25) if mt else 0.02}
    if "xiepo" in asset:      # ramp on-piece: the runner mounts it (see surfing_ai.lua)
        return {"solid": False, "jump": False, "slide": False, "back": 0.0, "front": 0.0,
                "lanes": 1, "speed": 0.0}
    jump = "mutong" in asset or "dizhalan" in asset
    slide = "zhalan" in asset or "qiao" in asset
    b = bounds.get(name)
    if b and "back" in b:
        back, front = b["back"], b.get("front", 1.0)
        lanes = 3 if b.get("sx", 0) > 6 else 1
    elif "chexiang" in asset or "truck" in asset:
        n = 1
        tail = asset.rsplit("_", 1)[-1].replace(".prefab", "")
        if tail.isdigit():
            n = int(tail)
        back, front, lanes = 8.24 * n, 0.2, 1
    else:
        back, front, lanes = 1.0, 1.0, 1
    if "qiao" in asset:
        # the gate is the near edge of the deck, not the whole deck (see surfing_ai.lua)
        back, front, lanes = 34.0, -31.5, 3
    return {"solid": True, "jump": jump, "slide": slide, "back": back, "front": front,
            "lanes": lanes, "speed": float(rec.get("move_speed") or 0)}


def bands(born, mon):
    """Group the born templates into their 330 m bands, keyed by the band id."""
    out = collections.defaultdict(list)
    for rec in born.values():
        coord = rec.get("coord") or []
        monster = rec.get("monster") or []
        if len(coord) < 3 or not monster:
            continue
        band = str(rec["id"])[:-3]
        out[band].append((float(coord[0]), float(coord[2]), int(monster[0])))
    for rows in out.values():
        rows.sort(key=lambda r: r[1])
    return out


_SIM = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SSIM "..tostring(s)) end
local AI = _G.__SR_AI
if not AI or not AI.planRoute then L("no-autopilot") return end
AI.kindOverride = { %s }
local obs = { %s }
local ZMAX, LANE0 = %s, %s
local function laneOf(x)
  local l = math.floor((x - 36) / 4 + 0.5) + 1
  if l < 0 then l = 0 elseif l > 2 then l = 2 end
  return l
end
local speed, dt = 30, 1/60
local pz, lane = 0, LANE0
local swT, swFrom, swTo, jT, slT = 0, LANE0, LANE0, 0, 0
local dead, frame, moves, t = nil, 0, 0, 0
local live, window = {}, {}
for i = 1, #obs do live[i] = {x = obs[i].x, z = obs[i].z, mid = obs[i].mid, speed = obs[i].speed} end
while pz < ZMAX and not dead do
  frame = frame + 1
  t = t + dt
  for i = 1, #live do
    if live[i].speed > 0 then live[i].z = obs[i].z + live[i].speed * t end
  end
  if frame %% 2 == 1 and swT <= 0 and jT <= 0 and slT <= 0 then
    local n = 0
    for i = 1, #live do
      local o = live[i]
      if o.z > pz - 10 and o.z < pz + 200 then n = n + 1 window[n] = o end
    end
    for i = #window, n + 1, -1 do window[i] = nil end
    local reach, act, az = AI.planRoute(pz, lane, speed, window)
    if az == 0 and act ~= 0 then
      if act == 1 and lane > 0 then
        swT, swFrom, swTo, lane = 0.16, lane, lane - 1, lane - 1 moves = moves + 1
      elseif act == 2 and lane < 2 then
        swT, swFrom, swTo, lane = 0.16, lane, lane + 1, lane + 1 moves = moves + 1
      elseif act == 3 then
        jT = 0.72 moves = moves + 1
      elseif act == 4 then
        slT = 0.50 moves = moves + 1
      end
    end
  end
  -- collision against the TRUE extents (no planner padding): [z - back, z + front],
  -- across every lane the body covers
  local z0, z1 = pz, pz + speed * dt
  for i = 1, #live do
    local o = live[i]
    local k = AI.kindOverride[o.mid]
    if k and k.solid then
      if z1 > o.z - k.back and z0 < o.z + k.front then
        local ol = laneOf(o.x)
        local hit
        if k.lanes >= 3 then
          hit = true
        elseif swT > 0 then
          hit = (ol == swFrom or ol == swTo)
        else
          hit = (ol == lane)
        end
        if hit and not (jT > 0 and k.jump) and not (slT > 0 and k.slide) then dead = o end
      end
    end
  end
  if swT > 0 then swT = swT - dt end
  if jT > 0 then jT = jT - dt end
  if slT > 0 then slT = slT - dt end
  pz = z1
end
AI.kindOverride = {}
if dead then
  L(string.format("DEAD z=%%.1f x=%%s obz=%%.1f mid=%%s lane=%%d moves=%%d", pz,
    tostring(dead.x), dead.z, tostring(dead.mid), lane, moves))
else
  L(string.format("OK z=%%.1f lane=%%d moves=%%d", pz, lane, moves))
end
"""


def kind_for(kinds: dict, mid: int) -> dict:
    """Templates load lazily, so a band can name one the client has never seen. Fall back on
    the id family — 4xxxxx/3xxxxx are the long carriage/bridge pieces, 2xxxxx the small
    ground obstacles — and never guess "harmless"."""
    k = kinds.get(mid)
    if k is not None:
        return k
    big = 300000 <= mid < 500000
    k = {"solid": True, "jump": False, "slide": False, "back": 24.0 if big else 1.0,
         "front": 1.0, "lanes": 1, "speed": 0.0}
    kinds[mid] = k
    return k


def simulate(ev, rows, kinds, lane0, zmax):
    for _, _, mid in rows:
        kind_for(kinds, mid)
    ov = ",".join(
        "[%d]={solid=%s,jump=%s,slide=%s,back=%g,front=%g,lanes=%d,speed=%g,buff=%s}"
        % (mid, str(k["solid"]).lower(), str(k["jump"]).lower(), str(k.get("slide", False)).lower(),
           k.get("back", 0), k.get("front", 0), k.get("lanes", 1), k.get("speed", 0),
           repr(k["buff"]) if k.get("buff") else "nil")
        for mid, k in kinds.items())
    obs = ",".join("{x=%g,z=%g,mid=%d,speed=%g}" % (x, z, mid, kinds[mid]["speed"])
                   for x, z, mid in rows)
    lines = ev.run(_SIM % (ov, obs, zmax, lane0), marker=MARK, settle=6.0)
    for ln in lines:
        return ln.split(MARK, 1)[-1].rstrip()
    return "no-result"


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    born, mon = load_config()
    bounds = load_bounds()
    kinds = {int(k): classify(v, bounds) for k, v in mon.items()}
    names = {int(k): (v.get("asset") or "").split("/")[-1].replace(".prefab", "")
             for k, v in mon.items()}
    per_band = bands(born, mon)
    want = argv[0] if argv else None
    lanes = [int(argv[1])] if len(argv) > 1 else [0, 1, 2]
    ev = get_evaluator()
    failures = 0
    try:
        for band in sorted(per_band):
            if want and band != want:
                continue
            rows = per_band[band]
            for lane0 in lanes:
                res = simulate(ev, rows, kinds, lane0, 340)
                mark = "ok  " if res.startswith("OK") else "DIE "
                if res.startswith("DEAD"):
                    failures += 1
                    mid = res.split("mid=")[1].split()[0]
                    res += "  (%s)" % names.get(int(mid), mid)
                print("%s band %-6s start=%-6s %s" % (mark, band, LANE_NAME[lane0], res))
    finally:
        ev.close()
    print("\n%d failing (band, start lane) combinations" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
