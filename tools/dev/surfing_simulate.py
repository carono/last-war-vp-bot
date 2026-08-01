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
    C:\Python312\python.exe tools\dev\surfing_simulate.py score      # one number, one round trip

``score`` replays every band from every start lane in a SINGLE call and prints how many
survive and how far they get in total. That is what makes the between-attempt learning
safe: a tuning the death record suggests can be judged offline, against the real track,
before it is ever allowed near a live attempt — and a suggestion that scores worse (adding
margin closes gaps that are genuinely passable) is simply not applied.

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
SIM_LUA_PATH = os.path.join(_ROOT, "lib", "surfing_sim.lua")


def sim_lua() -> str:
    """The judge itself — shared with the local runner (tools/dev/surfing_offline.py), so the
    two hosts cannot drift apart in what they call a death."""
    with open(SIM_LUA_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


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
    # a saw (dianju / TrapSaw) is a low hazard — hoppable (it also patrols sideways, but the
    # config gives it no speed and the offline replay cannot move it, so only the hop matters here)
    saw = "dianju" in asset or "saw" in asset
    jump = "mutong" in asset or "dizhalan" in asset or saw
    slide = "zhalan" in asset
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
    if "qiaodong" in asset:
        # the bridge deck is overhead (collider at y≈10-12) — a ground runner passes UNDER it,
        # so it is ignored, not a wall (see surfing_ai.lua). The real hazards beside a bridge
        # are the separate fence / driving-truck pieces, which are their own monsters.
        return {"solid": False, "ignore": True, "jump": False, "slide": False, "back": 0.0,
                "front": 0.0, "lanes": 1, "sideOnly": False, "carriage": False, "ramp": False,
                "speed": 0.0}
    # planRoute keys the ramp/roof logic off `carriage` and `ramp`, NOT off `sideOnly` — and
    # kindOf returns an override verbatim, so an override that omits those two fields makes
    # EVERY ramp read as a plain wall inside the planner. Offline that turned every carriage
    # band unsolvable (planRoute could see no route past the first ramp), which is exactly
    # the band class most deaths come from — so the offline judge was blind to the fixes that
    # mattered. Carry them, so the offline planner models ramps exactly as the live one does.
    speed = float(rec.get("move_speed") or 0)
    carriage = ("chexiang" in asset or "truck" in asset) and speed == 0
    ramp = carriage and "xiepo" in asset
    # ramps are ridden head-on and only kill from the side; plain carriages are walls
    side_only = ramp
    return {"solid": True, "jump": jump, "slide": slide, "back": back, "front": front,
            "lanes": lanes, "sideOnly": side_only, "carriage": carriage, "ramp": ramp,
            "speed": speed}


def roof_holes(rows, kinds, roof_gap: float = 16.0):
    """The gaps the runner has to hop while riding along the carriage roofs.

    A ramp piece starts a roof; the next carriage in the same lane continues it if it is
    close enough behind. Between two of them there is a hole down to the road, and falling
    into it kills — which is what ended a live run off the far end of a truck. The judge has
    to model it, or it cannot tell whether the planner's hop is scheduled correctly.
    """
    per_lane: dict[int, list] = {0: [], 1: [], 2: []}
    for x, z, mid in rows:
        k = kinds.get(mid) or {}
        name_is_car = k.get("back", 0) > 5 and k.get("lanes", 1) == 1 and not k.get("speed")
        if not name_is_car:
            continue
        lane = min(range(3), key=lambda i: abs(x - (32 + 4 * i)))
        per_lane[lane].append((z - k["back"], z + k.get("front", 0), k.get("sideOnly", False)))
    holes, roofs = [], []
    for lane, items in per_lane.items():
        items.sort()
        roof_until = None
        for z0, z1, is_ramp in items:
            cont = roof_until is not None and z0 - roof_until <= roof_gap
            if is_ramp or cont:
                # a seam-hole belongs ONLY between two carriages that actually chain (small
                # gap). A ramp starting a FRESH roof after a big gap is not a seam — the runner
                # was on the ground across that gap, not falling — so no hole there (the bug
                # marked a 1000-unit phantom hole down a whole lane and killed the run).
                if cont and z0 > roof_until:
                    holes.append((lane, roof_until, z0))
                roofs.append((lane, z0, z1))   # a rideable roof span (ramp-led chain)
                roof_until = z1
            else:
                roof_until = None
    return holes, roofs


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
if AI.resetKinds then AI.resetKinds() end
local obs = { %s }
local holes, roofs = { %s }, { %s }
local ZMAX, LANE0 = %s, %s
-- one band at a fixed speed, judged with the SAME seam/roof model as the score and chain
-- paths — an empty one used to make this command a laxer judge than the other two, so a band
-- could "die" here and pass there for no reason but which entry point was typed.
local pz, dead, moves = __SR_SIM.once(obs, holes, roofs, LANE0, 30, 0, ZMAX)
AI.kindOverride = {}
if dead then
  L(string.format("DEAD z=%%.1f x=%%s obz=%%.1f mid=%%s moves=%%d", pz,
    tostring(dead.x), dead.z or 0, tostring(dead.mid), moves))
else
  L(string.format("OK z=%%.1f moves=%%d", pz, moves))
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
        "[%d]={solid=%s,jump=%s,slide=%s,sideOnly=%s,carriage=%s,ramp=%s,ignore=%s,back=%g,front=%g,lanes=%d,speed=%g,buff=%s}"
        % (mid, str(k["solid"]).lower(), str(k["jump"]).lower(), str(k.get("slide", False)).lower(),
           str(k.get("sideOnly", False)).lower(),
           str(k.get("carriage", False)).lower(), str(k.get("ramp", False)).lower(),
           str(k.get("ignore", False)).lower(),
           k.get("back", 0), k.get("front", 0), k.get("lanes", 1), k.get("speed", 0),
           repr(k["buff"]) if k.get("buff") else "nil")
        for mid, k in kinds.items())
    obs = ",".join("{x=%g,z=%g,mid=%d,speed=%g}" % (x, z, mid, kinds[mid]["speed"])
                   for x, z, mid in rows)
    holes, roofs = roof_holes(rows, kinds)
    hole_src = ",".join("{%d,%g,%g}" % h for h in holes)
    roof_src = ",".join("{%d,%g,%g}" % r for r in roofs)
    lines = ev.run(sim_lua() + _SIM % (ov, obs, hole_src, roof_src, zmax, lane0),
                   marker=MARK, settle=6.0)
    for ln in lines:
        return ln.split(MARK, 1)[-1].rstrip()
    return "no-result"


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if argv and argv[0] == "score":
        return cmd_score(argv[1:])
    if argv and argv[0] == "chain":
        return cmd_chain(argv[1:])
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




_SCORE = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SSIM "..tostring(s)) end
local AI = _G.__SR_AI
if not AI or not AI.planRoute then L("no-autopilot") return end
AI.kindOverride = { %s }
if AI.resetKinds then AI.resetKinds() end
local bands = { %s }
local holes = { %s }
local roofs = { %s }
local LANE0, SPEED, ACCEL, ZMAX = %s, %s, %s, %s
local passed, total, dist, deaths = __SR_SIM.score(bands, holes, roofs, LANE0, SPEED, ACCEL, ZMAX)
AI.kindOverride = {}
if #bands == 1 then
  for i = 1, #deaths do
    local d = deaths[i]
    L(string.format("DEATH z=%%.0f mid=%%s x=%%s obz=%%.0f", d.z, tostring(d.mid),
      tostring(d.x), d.obz or 0))
  end
end
L(string.format("SCORE passed=%%d of=%%d dist=%%.0f", passed, total, dist))
"""


def cmd_score(argv):
    """One number for the whole track: how many bands survive from one start lane.

    Kept to a single start lane per call on purpose — replaying all thirty combinations
    inside one frame froze the client badly enough to lose the process."""
    lane0 = int(argv[0]) if argv and argv[0].lstrip("-").isdigit() else 1
    speed = 30
    for a in argv:
        if a.startswith("speed="):
            speed = int(a.split("=", 1)[1])
    ev = get_evaluator()
    try:
        res = score(ev, lane0, speed)
    finally:
        ev.close()
    print("SCORE passed=%d of=%d dist=%.0f" % res)
    return 0


def cmd_chain(argv):
    """One long chained run over every band back-to-back with accelerating speed — the closest
    offline proxy to a live run, so band-seam roof-descents can be iterated without attempts."""
    lane0 = int(argv[0]) if argv and argv[0].lstrip("-").isdigit() else 1
    born, mon = load_config()
    nb = len(bands(born, mon))
    zmax = nb * 340
    ev = get_evaluator()
    worst = None
    try:
        for rot in range(nb):        # scan band orders — the live order is random, so seams vary
            _, _, dist = score(ev, lane0, speed=30, accel=0.0027, zmax=zmax, rot=rot)
            print("  rot=%2d dist=%.0f" % (rot, dist))
            if worst is None or dist < worst[1]:
                worst = (rot, dist)
    finally:
        ev.close()
    print("CHAIN start=%s worst rot=%d dist=%.0f of %d m" % (LANE_NAME[lane0], worst[0], worst[1], zmax))
    return 0


def build_field(accel: float = 0.0, rot: int = 0):
    """The obstacle field as Lua source: the kind table, and per group the obstacles, the roof
    seams and the rideable roof spans. Shared with the local runner (surfing_offline.py) so
    both hosts judge the SAME track — a fix that only helps because the two disagree about
    what is on the ground would be worthless."""
    born, mon = load_config()
    bounds = load_bounds()
    kinds = {int(k): classify(v, bounds) for k, v in mon.items()}
    per_band = bands(born, mon)
    for rows in per_band.values():
        for _, _, mid in rows:
            kind_for(kinds, mid)
    if accel > 0:
        # CHAIN: concatenate every band into one long track (offset 340 each) so band SEAMS
        # appear — that is where the live roof-descent deaths happen and an isolated band can't
        # show them. `rot` rotates the band order so different seams are exercised (the live
        # order is random). One "band" is fed, and ZMAX is the whole length.
        order = sorted(per_band)
        order = order[rot % len(order):] + order[:rot % len(order)]
        chained, off = [], 0
        for band in order:
            for x, z, mid in per_band[band]:
                chained.append((x, z + off, mid))
            off += 340
        groups = [chained]
    else:
        groups = [per_band[b] for b in sorted(per_band)]
    band_src, hole_src, roof_src = [], [], []
    for rows in groups:
        band_src.append("{" + ",".join(
            "{x=%g,z=%g,mid=%d,speed=%g}" % (x, z, mid, kinds[mid]["speed"])
            for x, z, mid in rows) + "}")
        holes, roofs = roof_holes(rows, kinds)
        hole_src.append("{" + ",".join("{%d,%g,%g}" % h for h in holes) + "}")
        roof_src.append("{" + ",".join("{%d,%g,%g}" % r for r in roofs) + "}")
    ov = ",".join(
        "[%d]={solid=%s,jump=%s,slide=%s,sideOnly=%s,carriage=%s,ramp=%s,ignore=%s,back=%g,front=%g,lanes=%d,speed=%g,buff=%s}"
        % (mid, str(k["solid"]).lower(), str(k["jump"]).lower(), str(k.get("slide", False)).lower(),
           str(k.get("sideOnly", False)).lower(),
           str(k.get("carriage", False)).lower(), str(k.get("ramp", False)).lower(),
           str(k.get("ignore", False)).lower(),
           k.get("back", 0), k.get("front", 0), k.get("lanes", 1), k.get("speed", 0),
           repr(k["buff"]) if k.get("buff") else "nil")
        for mid, k in kinds.items())
    names = {int(k): (v.get("asset") or "").split("/")[-1].replace(".prefab", "")
             for k, v in mon.items()}
    return ov, band_src, hole_src, roof_src, kinds, names


def score(ev, lane0: int = 1, speed: int = 30, accel: float = 0.0, zmax: int = 340, rot: int = 0):
    """Replay every band from one start lane through the live planner at `speed` u/s. Returns
    ``(passed, total, distance)`` — the objective the between-attempt learner is judged on.
    Run at the higher speeds a long run reaches (45/60) to expose hops that overshoot.
    `accel`/`zmax` are for the chained-track run (cmd_chain): speed climbs with distance."""
    ov, band_src, hole_src, roof_src, _, _ = build_field(accel, rot)
    lines = ev.run(sim_lua() + _SCORE % (ov, ",".join(band_src), ",".join(hole_src),
                                         ",".join(roof_src), lane0, speed, accel, zmax),
                   marker=MARK, settle=float(os.environ.get("SSIM_SETTLE", "8")))
    for ln in lines:
        body = ln.split(MARK, 1)[-1].strip()
        if body.startswith("DEATH "):
            print("  " + body)
        if body.startswith("SCORE "):
            d = dict(p.split("=", 1) for p in body[6:].split())
            return int(d["passed"]), int(d["of"]), float(d["dist"])
    return 0, 0, 0.0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
