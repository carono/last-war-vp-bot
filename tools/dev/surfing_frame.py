#!/usr/bin/env python3
r"""One frame of Street Run, handed back to the planner.

A death record and a frame log both say WHAT the runner saw and what it decided; neither says
why. This asks the planner itself, on the same field, and then prints the field the way the
planner built it: which buckets each lane reads as blocked, by what, and how far the search
got. It is the difference between "reach counted down to zero and it never slid" and knowing
which of `solid`, `side` or `hole` shut the manoeuvre out.

The field is given as it appears in the logs — one obstacle per `x,z,mid` triple:

    python3 tools/dev/surfing_frame.py --pz 474.9 --lane 1 --speed 30 \
        36,488,200009 32,492,400001 40,504,400005

    # straight off a death record in results/street_run/ai_moves.log (the dobs block of the
    # Nth death from the end, 1 = the last one), replayed from `--pz` before the death z
    python3 tools/dev/surfing_frame.py --death 1 --before 12

`--py` is the runner's height (0 on the road, 4.30 on a roof plateau) and `--roof` says it is
up on the carriages, the two things a flat obstacle list cannot carry.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, os.path.join(os.path.dirname(_HERE), "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(_REPO)

import surfing_offline as O  # noqa: E402
import surfing_simulate as S  # noqa: E402

ACT = {0: "hold", 1: "left", 2: "right", 3: "hop", 4: "slide"}
LANE_X = {32: 0, 36: 1, 40: 2}
MOVES = os.path.join("results", "street_run", "ai_moves.log")


def load_death(nth: int):
    """The `nth`-from-last death in the moves log: (z, lane, speed, y, obstacles)."""
    with open(MOVES, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    idx = [i for i, ln in enumerate(lines) if ln.startswith("death z=")]
    if len(idx) < nth:
        raise SystemExit("only %d deaths in %s" % (len(idx), MOVES))
    i = idx[-nth]
    m = re.match(r"death z=([\d.]+) speed=(\S+) lane=(\S+) y=(\S+)", lines[i])
    if not m:
        raise SystemExit("could not read the death line: %s" % lines[i][:80])
    obs = []
    j = i + 1
    while j < len(lines) and lines[j].startswith("dobs "):
        f = lines[j][5:].split("|")
        if len(f) >= 5:
            obs.append((float(f[0]), float(f[1]), int(f[2]), float(f[3] or 0), f[4]))
        j += 1
    return float(m.group(1)), int(m.group(3)), float(m.group(2)), float(m.group(4)), obs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("field", nargs="*", help="obstacles as x,z,mid[,speed]")
    ap.add_argument("--death", type=int, help="replay the Nth death from the end of the log")
    ap.add_argument("--before", type=float, default=0.0,
                    help="metres before the death z to plan from (with --death)")
    ap.add_argument("--pz", type=float, default=0.0)
    ap.add_argument("--lane", type=int, default=1)
    ap.add_argument("--speed", type=float, default=30.0)
    ap.add_argument("--py", type=float, default=0.0)
    ap.add_argument("--roof", action="store_true")
    ap.add_argument("--buckets", type=int, default=60, help="how many buckets to print")
    a = ap.parse_args(argv)

    obs = []
    if a.death:
        dz, lane, speed, py, dobs = load_death(a.death)
        a.pz = dz - a.before
        a.lane, a.speed = lane, speed
        if not a.py:
            a.py = py
        a.roof = a.roof or py > 2.0
        obs = [(x, z, mid, sp) for x, z, mid, sp, _nm in dobs]
        print("death at z=%.1f lane=%d speed=%.0f y=%.2f — planning from z=%.1f"
              % (dz, lane, speed, py, a.pz))
    for tok in a.field:
        f = tok.split(",")
        obs.append((float(f[0]), float(f[1]), int(f[2]), float(f[3]) if len(f) > 3 else 0.0))
    if not obs:
        raise SystemExit("no obstacles given (pass x,z,mid triples or --death N)")

    _born, mons = S.load_config()
    bnds = S.load_bounds()
    kinds = {int(mid): S.classify(rec, bnds) for mid, rec in mons.items()}
    names = {int(mid): (rec.get("asset") or "").split("/")[-1].replace(".prefab", "")
             for mid, rec in mons.items()}
    rt, ai = O.new_vm()
    rt.execute("__SR_AI.kindOverride = {%s}" % S.kind_table(kinds))
    if ai["resetKinds"] is not None:
        ai["resetKinds"]()

    src = ",".join("{x=%g,z=%g,mid=%d,speed=%g}" % o for o in obs)
    field = rt.eval("function() return {%s} end" % src)()
    reach, act, az = ai["planRoute"](a.pz, a.lane, a.speed, field, False, a.roof, a.py)
    print("planner: reach=%d act=%s az=%d" % (int(reach), ACT.get(int(act), act), int(az)))
    why_d, why_r = ai["stat"]["whyD"], ai["stat"]["whyR"]
    print("first solid bucket per lane: %s | search reaches: %s"
          % ([int(why_d[l]) for l in range(3)], [int(why_r[l]) for l in range(3)]))

    # What each lane is, bucket by bucket, and which body owns the block. The planner keeps no
    # such record — it is rebuilt here from the same kinds and the same rounding, so a
    # disagreement between this and `whyD` is itself worth seeing.
    print()
    short = (lambda n: n.replace("O_env_ditiepaoku_", "").replace("A_Monster_surfing_", "")
             .replace("O_Object_", ""))
    print("bucket  %-20s %-20s %-20s" % ("left", "centre", "right"))
    own = {0: {}, 1: {}, 2: {}}
    for x, z, mid, sp in obs:
        k = kinds.get(mid)
        if not k or not k.get("solid"):
            continue
        back = k["back"] + float(ai["cfg"]["padExtra"])
        front = k["front"] + float(ai["cfg"]["padExtra"])
        lanes = [0, 1, 2] if k.get("lanes", 1) >= 3 else [LANE_X.get(int(round(x)), 1)]
        for ll in lanes:
            for j in range(int(z - back - a.pz), int(z + front - a.pz) + 2):
                if 0 <= j <= a.buckets:
                    own[ll].setdefault(j, names.get(mid, str(mid)))
    for j in range(0, a.buckets + 1):
        cells = []
        for ll in range(3):
            nm = own[ll].get(j)
            cells.append(short(nm or "")[:20].ljust(20))
        if any(c.strip() for c in cells):
            print("%6d  %s %s %s" % (j, *cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
