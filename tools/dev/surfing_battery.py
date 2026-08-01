#!/usr/bin/env python3
r"""Every standing measurement of the Street Run planner, in one run.

A planner change moves several numbers at once and the interesting ones are rarely the one
being aimed at: a tuning that adds a kilometre to a drawn route and quietly drops two bands
of the isolated score is a loss, and there is no way to see that from a single command. So
this runs the whole battery and prints it as one block, small enough to paste into a commit.

    python3 tools/dev/surfing_battery.py                 # the planner as it stands
    python3 tools/dev/surfing_battery.py cfg padExtra=2  # ... with a tuning
    SR_AI_LUA=/tmp/ai_before.lua python3 tools/dev/surfing_battery.py   # ... a past revision

What is in it, and why each earns its place:

* **per-band, three start lanes** — the isolated score. It is the only measurement that
  covers every band in the pool, so it is the regression guard: a change that helps one route
  and breaks a band class shows up here and nowhere else.
* **run_002** — the one route a person actually ran, at the speed ramp they ran it at.
* **five drawn routes** — bands drawn the way the game draws them (`pool:36:SEED`). The three
  recordings have been read against the planner long enough that a good score on them says as
  much about the tuning as about the track; a fresh draw does not.
* **the ceiling beside each distance** — what the exhaustive search reaches while insisting on
  the same 1.5 m of clearance the planner keeps. A distance without its ceiling cannot be read
  at all: run_002 dies at 7390 of 11880 and is at its own ceiling, seed 3 dies at 508 of 11880
  and is at its own ceiling, and seed 2 dies at 4853 with the whole route open ahead of it.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import surfing_offline as O  # noqa: E402
import surfing_simulate as S  # noqa: E402

# the clearance the ceilings are measured at: the planner's own cfg.padExtra, because a
# planner that keeps 1.5 m cannot be charged for declining a manoeuvre 3 cm wide
PAD = 1.5
SEEDS = (1, 2, 3, 4, 5)


def band_score(cfg):
    rt, _ = O.new_vm(cfg)
    ov, band_src, hole_src, roof_src, _, _ = S.build_field()
    passed = 0
    for lane0 in (0, 1, 2):
        for i, band in enumerate(band_src):
            _, dead, _ = O.run_group(rt, ov, band, hole_src[i], roof_src[i],
                                     lane0, 30, 0, S.BAND_PITCH + 10)
            if dead is None:
                passed += 1
    return passed, 3 * len(band_src)


def one_route(cfg, spec, ceiling=True):
    """(planner distance, ceiling at PAD or None, total) for one route, from centre."""
    order, _ = O.resolve_route(spec)
    accel = O.route_accel(spec)
    zmax = len(order) * S.BAND_PITCH
    rt, _ = O.new_vm(cfg)
    ov, band, hole, roof, _, _ = S.build_field(accel=accel, order=order)
    dist, _, _ = O.run_group(rt, ov, band[0], hole[0], roof[0], 1, 30, accel, zmax)
    top = None
    if ceiling:
        tr = O.Track(order, 30.0, accel, PAD)
        top = zmax if O._search(tr, 1) is not None else O._furthest(tr, 1)
    return dist, top, zmax


def main(argv):
    cfg: dict = {}
    it = iter(argv)
    for a in it:
        if a == "cfg":
            for pair in it:
                if "=" not in pair:
                    break
                k, v = pair.split("=", 1)
                cfg[k] = (v == "true") if v in ("true", "false") else float(v)
    if cfg:
        print("cfg %s" % " ".join("%s=%g" % (k, v) for k, v in sorted(cfg.items())))
    print("planner %s" % os.path.basename(O.AI_LUA))
    passed, total = band_score(cfg)
    print("per-band, three start lanes   %d/%d" % (passed, total))
    print("%-14s %8s %8s   %s" % ("route", "planner", "ceiling", "of"))
    rows = [("run_002", "run_002")] + [("pool:36:%d" % s, "seed %d" % s) for s in SEEDS]
    share = []
    for spec, label in rows:
        dist, top, zmax = one_route(cfg, spec)
        share.append(dist / top if top else 1.0)
        print("%-14s %8.0f %8.0f   %d m%s"
              % (label, dist, top, zmax, "   AT ITS CEILING" if dist >= top - 5 else ""))
    print("share of the ceiling reached  %.0f%% (mean of %d routes)"
          % (100 * sum(share) / len(share), len(share)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
