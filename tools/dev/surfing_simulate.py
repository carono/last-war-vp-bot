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
HUMAN_DIR = os.path.join("results", "street_run", "human")
LANE_NAME = {0: "left", 1: "centre", 2: "right"}
SIM_LUA_PATH = os.path.join(_ROOT, "lib", "surfing_sim.lua")

# How far apart the bands are laid down on the real track. Read straight off the human
# recordings: every obstacle a recorded run saw lands on a band template shifted by an exact
# multiple of 330 (645 of 645 static obstacles in run_002 bar 16 pickups). The chained replay
# used to space them 340 apart, which inserted a 10-unit strip of empty road at every seam —
# so it was judging a track the game never builds, at the one place the deaths happen.
BAND_PITCH = 330

# A frame sample is 15 game frames at 60 Hz.
FRAME_DT = 15 / 60.0

# The runner can FLY, and it is not a nicety — it is the only way past some of the track.
# The human recordings have three flights, and each begins the instant a pickup is taken and
# lasts exactly 11.0 s at cruise height (y=20), during which nothing on the ground touches the
# runner. In one of them the ground below held three oncoming trucks abreast, one per lane, with
# no gap at all: an exhaustive search of every jump, slide and lane change dies there, and the
# person sailed over it. A judge that cannot fly cannot be asked whether a route is survivable.
#
# `buffType == 3` is the flight buff itself (the aeroplane, id 100004). The other pickups that
# have produced a flight — the ally hero 100007 and the crate 110000 — are not flight at all
# but random boxes: their `randomData` rolls one of five or six buffs, of which the aeroplane
# is one. So they are a CHANCE of flight, never a certainty, and the feasibility search must
# not lean on them (see `flight_chance`).
FLIGHT_SECONDS = 11.0


def flight_chance(rec: dict) -> float:
    """How likely this pickup is to put the runner in the air: 1.0 for the aeroplane itself,
    the roll probability for a random box, 0 for everything else."""
    if rec.get("buffType") == 3:
        return 1.0
    rolls = rec.get("randomData") or []
    total = float(rec.get("para2") or 0) or sum(float(r.get("p") or 0) for r in rolls)
    if not rolls or not total:
        return 0.0
    return sum(float(r.get("p") or 0) for r in rolls if int(r.get("id") or 0) == 100004) / total


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
        chance = flight_chance(rec)
        return {"solid": False, "jump": False, "slide": False, "back": 0.0, "front": 0.0,
                "lanes": 1, "speed": 0.0,
                "fly": FLIGHT_SECONDS if chance >= 1.0 else 0.0, "flyChance": chance,
                "buff": (0.9 if strong else 0.25) if mt else 0.02}
    # a saw (dianju / TrapSaw) is a low hazard — hoppable (it also patrols sideways, but the
    # config gives it no speed and the offline replay cannot move it, so only the hop matters here)
    saw = "dianju" in asset or "saw" in asset
    jump = "mutong" in asset or "dizhalan" in asset or saw
    slide = "zhalan" in asset
    b = bounds.get(name)
    # A DRIVING truck's measured length is deliberately not used, and this is the one place the
    # decision lives. The measurement is not in doubt: the colliders are 23 / 31 / 40 units long
    # and the recordings agree to the metre — a person rides `move_2` from `pz - z = -31.0` to 0
    # and `move_3` from -40.0 to 0. It is the model AROUND the number that cannot carry it yet.
    # Given the honest lengths, every offline measure collapses: the per-band score falls
    # 141/144 -> 126/144, run_002 from 7390 m to 474, seed 4 from 11881 to 1669, and the
    # exhaustive search agrees the track has no way through — against a person who runs 12772 m
    # on it. Something else about a mover is wrong (how it is boarded, or where its body is
    # lethal, or the parked-then-oncoming motion), and until that is found the shorter
    # name-derived length is the better approximation of how much lane a truck really denies.
    # Restoring the measurement is a one-line change here and in surfing_ai.lua's `measure`.
    mover = (rec.get("move_speed") or 0) > 0
    if b and "back" in b and not (mover and "truck" in asset):
        back, front = b["back"], b.get("front", 1.0)
        lanes = 3 if b.get("sx", 0) > 6 else 1
    elif "chexiang" in asset or "truck" in asset:
        n = 1
        tail = asset.rsplit("_", 1)[-1].replace(".prefab", "")
        if tail.isdigit():
            n = int(tail)
        back, front, lanes = 8.24 * n, 0.2, 1
        if (rec.get("move_speed") or 0) > 0:
            # THE most load-bearing unmeasured number in the whole model. Length is read from
            # the "_N" in the prefab name, which is verified for the train carriages — bounds.json
            # measured them at 8.22 / 16.44 / 24.86 / 32.98 / 41.10, exactly 8.24xN. But the
            # driving trucks are `O_Object_high_truck_gold_move_N`, a different asset family
            # that nothing has ever measured, and elsewhere in this same config `_N` is a
            # VARIANT index (the bridge pieces qiaodong_1/2/3), not a segment count.
            #
            # It decides everything. Exhaustive search on run_002's route reaches 482 m of
            # 11880 at 24.7, and 5469 m at anything 16.5 or shorter — the "impassable" convoy
            # is that assumption and nothing else. The recordings refute 41.1 (they put the
            # person inside a truck they survived, which is also what the player reported live
            # about the old cfg.moverBack) but cannot separate 33 from 4: nobody ever ran that
            # close to one in its own lane.
            #
            # So the default is left alone rather than tuned to a number that flatters the bot,
            # and the assumption is named instead of buried. One live run with measure() over a
            # gold truck settles it; SR_MOVER_BACK re-runs any verdict against a candidate.
            back = float(os.environ.get("SR_MOVER_BACK") or back)
    else:
        back, front, lanes = 1.0, 1.0, 1
    if "qiaodong" in asset or "gaojiaqiao" in asset:
        # the bridge deck is overhead (collider at y≈10-15) — a ground runner passes UNDER it,
        # so it is ignored, not a wall (see surfing_ai.lua). The real hazards beside a bridge
        # are the separate fence / driving-truck pieces, which are their own monsters.
        # The viaduct (`gaojiaqiao`) is the same and was excluded until the recordings were
        # counted: a person is inside one on the ground 77 times across the three runs, in all
        # three lanes, and never dies there. Modelled solid it is 46 m of wall across the whole
        # road — `surfing_offline.py human run_002` reported it as nine of its ten "model says
        # WALL where the run went on".
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
    # A DRIVING truck carries a roof too, and is ridden along it exactly like a train carriage.
    # It was excluded from `carriage` on the assumption that only a parked body can be stood on,
    # and the recordings refute that in the plainest way there is: across run_001/2/3 a person is
    # inside a `truck_gold_move_2` body 59 times and a `move_3` 120 times, EVERY one of them at
    # roof height (y > 2) and none of them on the ground, with no carriage under them to explain
    # it. Those frames also settle the length the code has been guessing at since #1163: they run
    # from `pz - z = -31.0` and `-40.0` to 0 — the whole body — which is the collider's own
    # measured size.z to the metre, and not the 16.5 / 24.7 that `_N x 8.24` assumes.
    carriage = "chexiang" in asset or "truck" in asset
    # ... but only a parked one has a ramp to drive up. A truck is boarded from a neighbouring
    # roof, which is why it is roof without ever being mountable.
    ramp = carriage and speed == 0 and "xiepo" in asset
    # ramps are ridden head-on and only kill from the side; plain carriages are walls
    side_only = ramp
    return {"solid": True, "jump": jump, "slide": slide, "back": back, "front": front,
            "lanes": lanes, "sideOnly": side_only, "carriage": carriage, "ramp": ramp,
            "speed": speed}


def kind_table(kinds: dict) -> str:
    """The kind table as Lua source — the one description of the obstacles both hosts read.

    It lived twice, once per entry point, and a field added to one copy was simply missing from
    the other: that is how `carriage`/`ramp` once went astray and made every ramp read as a
    plain wall in half the runs."""
    return ",".join(
        "[%d]={solid=%s,jump=%s,slide=%s,sideOnly=%s,carriage=%s,ramp=%s,ignore=%s,"
        "back=%g,front=%g,lanes=%d,speed=%g,fly=%g,buff=%s}"
        % (mid, str(k["solid"]).lower(), str(k["jump"]).lower(), str(k.get("slide", False)).lower(),
           str(k.get("sideOnly", False)).lower(),
           str(k.get("carriage", False)).lower(), str(k.get("ramp", False)).lower(),
           str(k.get("ignore", False)).lower(),
           k.get("back", 0), k.get("front", 0), k.get("lanes", 1), k.get("speed", 0),
           k.get("fly", 0),
           repr(k["buff"]) if k.get("buff") else "nil")
        for mid, k in kinds.items())


JUMP_TIME = 0.72        # player.jumpDurationValue, live-read (see surfing_ai.lua cfg)


def speed_profile(speed0: float = 30.0, accel: float = 0.0, cap: float = 60.0, steps=None):
    """The runner's speed as a function of distance — the judge's own model, as a callable.

    `steps` is the real thing: `[(z0, speed), ...]`, the speed held from `z0` until the next
    entry. The game changes speed at a band boundary and holds it flat across the band (the
    pool's own `speedZ`), so a ramp `speed0 + accel*z` is the wrong shape — it is out by up to
    4 u/s in the middle of a band and worst of all at the boundary. `accel` stays for the
    recordings, which are replayed at the ramp fitted from the recording itself."""
    if steps:
        marks = sorted(steps)
        zs = [z for z, _ in marks]

        def at(z):
            lo, hi = 0, len(marks) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if zs[mid] <= z:
                    lo = mid
                else:
                    hi = mid - 1
            return min(marks[lo][1], cap)
        return at
    return lambda z: min(speed0 + accel * z, cap)


def roof_holes(rows, kinds, roof_gap: float = 16.0, speed_at=None):
    """The gaps the runner has to hop while riding along the carriage roofs.

    A ramp piece starts a roof; the next carriage in the same lane continues it if it is
    close enough behind. Between two of them there is a hole down to the road, and falling
    into it kills — which is what ended a live run off the far end of a truck. The judge has
    to model it, or it cannot tell whether the planner's hop is scheduled correctly.
    """
    # How far a roof carries to the next carriage is NOT a constant: the gap is crossed by
    # hopping it, so the reach is the hop — jumpTime * speed. Measured on the human recordings:
    # all 40 roof-to-roof crossings satisfy gap <= 0.72 * speed, the greediest using 75% of it
    # (23.6 m at 48 u/s). A flat 16 denied three of them — 19.0, 23.0 and 23.6 m gaps the person
    # rode across — and broke the chain onto ground that was walled off. `roof_gap` is kept as a
    # floor so a slow chain never does worse than before.
    speed_at = speed_at or (lambda z: 30.0)
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
            reach = max(roof_gap, JUMP_TIME * speed_at(z0))
            cont = roof_until is not None and z0 - roof_until <= reach
            if is_ramp or cont:
                # a seam-hole belongs ONLY between two carriages that actually chain (small
                # gap). A ramp starting a FRESH roof after a big gap is not a seam — the runner
                # was on the ground across that gap, not falling — so no hole there (the bug
                # marked a 1000-unit phantom hole down a whole lane and killed the run).
                if cont and z0 > roof_until:
                    holes.append((lane, roof_until, z0))
                # the 4th field says whether this span can be MOUNTED from the road. Only a
                # ramp can: a plain carriage chained behind one is roof to a runner already
                # up there and a wall to one on the ground, and the judge needs to tell the
                # two apart (see SIM.once).
                roofs.append((lane, z0, z1, 1 if is_ramp else 0))
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


def read_run(path: str):
    """A recorded human run as ``(player_z, static obstacles seen)``.

    A frame is ``pz|lane|act|reach|firstSolid|reachable|y,busy|x,z,mid,speed ...``. Only the
    obstacles standing still are collected: a moving one reports where it had driven to by
    that frame, which is nothing the band template can be matched against."""
    zs, obs = [], set()
    with open(path, "r", encoding="utf-8") as fh:
        for ln in fh:
            parts = ln.rstrip("\n").split("|")
            if len(parts) < 8:
                continue
            zs.append(float(parts[0]))
            for tok in parts[7].split():
                f = tok.split(",")
                if len(f) == 4 and float(f[3]) == 0:
                    obs.add((int(f[0]), int(f[1]), int(f[2])))
    return zs, obs


def band_order_from_run(path: str, min_hits: int = 4):
    """Which bands a recorded run went through, in order.

    A recording carries no band id at all — only the obstacles the runner had in view. But
    every band is a fixed template list, so each 330-metre slot can be named by asking which
    band, shifted to that slot, explains the obstacles seen there. Returns one entry per slot:
    ``(offset, band id or None, matched, seen)``, so a caller can tell a confident naming from
    a slot the recording never got a look at (the frame buffer holds only the last ~900
    samples, so a long run loses its opening bands entirely)."""
    born, mon = load_config()
    per_band = {b: rows for b, rows in bands(born, mon).items()
                if max(z for _, z, _ in rows) <= BAND_PITCH + 10}
    zs, obs = read_run(path)
    if not zs:
        return []
    rounded = {(x, round(z), mid) for x, z, mid in obs}
    out = []
    for off in range(0, int(max(zs)) + BAND_PITCH, BAND_PITCH):
        seen = sum(1 for _, z, _ in rounded if off < z <= off + BAND_PITCH)
        scored = sorted(
            ((sum(1 for x, z, mid in rows if (x, round(z) + off, mid) in rounded), b)
             for b, rows in per_band.items()), reverse=True)
        hits, band = scored[0]
        out.append((off, band if hits >= min_hits else None, hits, seen))
    return out


def run_accel(path: str, speed0: float = 30.0, cap: float = 60.0) -> float:
    """The speed ramp a recorded run actually ran at, as the judge's single `accel` number.

    The judge models speed as ``min(speed0 + accel*z, cap)``; the recording gives the true
    speed at every sample (the distance between two frames over their fixed interval). Fitting
    the one against the other is what keeps a replay from clearing a gap the human had to take
    at a speed the replay never reached."""
    zs, _ = read_run(path)
    obs = [(zs[i], (zs[i + 1] - zs[i]) / FRAME_DT) for i in range(len(zs) - 1)]
    if not obs:
        return 0.0
    best = None
    for step in range(1, 1201):
        a = step / 200000.0
        err = sum((min(speed0 + a * z, cap) - s) ** 2 for z, s in obs)
        if best is None or err < best[1]:
            best = (a, err)
    return best[0]


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
    ov = kind_table(kinds)
    obs = ",".join("{x=%g,z=%g,mid=%d,speed=%g}" % (x, z, mid, kinds[mid]["speed"])
                   for x, z, mid in rows)
    holes, roofs = roof_holes(rows, kinds)
    hole_src = ",".join("{%d,%g,%g}" % h for h in holes)
    roof_src = ",".join("{%d,%g,%g,%d}" % r for r in roofs)
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
                res = simulate(ev, rows, kinds, lane0, BAND_PITCH + 10)
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
    zmax = nb * BAND_PITCH
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


def build_field(accel: float = 0.0, rot: int = 0, order: list | None = None,
                speed0: float = 30.0, steps=None):
    """The obstacle field as Lua source: the kind table, and per group the obstacles, the roof
    seams and the rideable roof spans. Shared with the local runner (surfing_offline.py) so
    both hosts judge the SAME track — a fix that only helps because the two disagree about
    what is on the ground would be worthless.

    `order` chains an EXPLICIT band list (the one a recorded run actually went through, see
    ``band_order_from_run``) instead of the whole pool in id order. `speed0` is the speed the
    track is ENTERED at — it only matters for the roof reach, which is the hop and so scales
    with speed, and it is not 30 when a caller replays the tail of a route on its own.
    `steps` gives the roof reach the real step profile instead (see `speed_profile`), which is
    what a route drawn from the generator runs at."""
    born, mon = load_config()
    bounds = load_bounds()
    kinds = {int(k): classify(v, bounds) for k, v in mon.items()}
    per_band = bands(born, mon)
    for rows in per_band.values():
        for _, _, mid in rows:
            kind_for(kinds, mid)
    if accel > 0 or order:
        # CHAIN: concatenate the bands into one long track so band SEAMS appear — that is where
        # the live roof-descent deaths happen and an isolated band can't show them. `rot`
        # rotates the band order so different seams are exercised (the live order is random),
        # unless an explicit `order` is given. One "band" is fed, and ZMAX is the whole length.
        if not order:
            order = sorted(per_band)
            order = order[rot % len(order):] + order[:rot % len(order)]
        chained, off = [], 0
        for band in order:
            for x, z, mid in per_band[band]:
                chained.append((x, z + off, mid))
            off += BAND_PITCH
        groups = [chained]
    else:
        groups = [per_band[b] for b in sorted(per_band)]
    band_src, hole_src, roof_src = [], [], []
    for rows in groups:
        band_src.append("{" + ",".join(
            "{x=%g,z=%g,mid=%d,speed=%g}" % (x, z, mid, kinds[mid]["speed"])
            for x, z, mid in rows) + "}")
        holes, roofs = roof_holes(rows, kinds,
                                  speed_at=speed_profile(speed0, accel, steps=steps))
        hole_src.append("{" + ",".join("{%d,%g,%g}" % h for h in holes) + "}")
        roof_src.append("{" + ",".join("{%d,%g,%g,%d}" % r for r in roofs) + "}")
    ov = kind_table(kinds)
    names = {int(k): (v.get("asset") or "").split("/")[-1].replace(".prefab", "")
             for k, v in mon.items()}
    return ov, band_src, hole_src, roof_src, kinds, names


def score(ev, lane0: int = 1, speed: int = 30, accel: float = 0.0,
          zmax: int = BAND_PITCH + 10, rot: int = 0):
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
