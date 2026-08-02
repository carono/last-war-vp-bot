r"""Street Run — the memory between attempts: why each run died, and what to change.

A run costs one of the day's ~30 attempts, so an attempt that teaches nothing is wasted.
This module keeps a durable record of every death (``results/street_run/deaths.json``),
works out **what killed it** from the obstacle field the autopilot froze at that instant,
and turns the accumulated tally into a small set of tuning overrides that
``street_run_ai.py`` pushes into the running autopilot before the next attempt.

The point is not a learning algorithm for its own sake — it is that the failures are
*specific*, and each one implies a specific correction:

===========================  ==================================================
cause                        what it means / what is adjusted
===========================  ==================================================
``ramp_head_on``             died inside a ramp it drove straight into — ramps are
                             not rideable after all → ``rampSolid``
``roof``                     died on a carriage believed roof-connected → the roof
                             does not carry that far → shrink ``roofGap``
``side_entry``               died in a body it changed lane into → the sweep needs
                             more room → widen ``padExtra``
``wall``                     died in a body it should never have entered → the
                             route cut it too fine → widen ``padExtra``
``fence`` / ``bridge``       died at something a duck clears → the duck was
                             mistimed → widen ``padExtra`` slightly
``unknown``                  nothing known was in that lane. NOT auto-tuned: the
                             honest answer is that the model is blind here, and
                             guessing a knob would paper over it. Reported instead.
===========================  ==================================================

Every adjustment is bounded and monotone, and the raw record is kept, so a bad inference
can be re-derived from scratch rather than being baked in.
"""
from __future__ import annotations

import json
import os
import time

STORE = os.path.join("results", "street_run", "deaths.json")
BOUNDS = os.path.join("results", "street_run", "config", "bounds.json")

# how far a body reaches back from its anchor, when it has never been measured live
_CAR_UNIT = 8.24
_BRIDGE_BACK = 34.0

# bounds on what the learner may do to the autopilot
LIMITS = {
    "padExtra": (1.0, 4.0),
    "roofGap": (0.0, 20.0),
}


def _bounds():
    try:
        with open(BOUNDS, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def body_of(name: str, z: float, bounds: dict):
    """Absolute z-interval a prefab occupies, plus how wide it is across the lanes."""
    b = bounds.get(name)
    if b and "back" in b:
        return z - b["back"], z + b.get("front", 1.0), b.get("sx", 3.5)
    low = name.lower()
    if "chexiang" in low or "truck" in low:
        tail = low.rsplit("_", 1)[-1]
        n = int(tail) if tail.isdigit() else 1
        return z - _CAR_UNIT * n, z + 0.2, 3.5
    if "qiao" in low:
        return z - _BRIDGE_BACK, z + 2.5, 20.0
    return z - 1.0, z + 1.0, 3.5


def parse_log(path: str):
    """Pull every death record out of an ai_moves.log, newest last."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    out, cur = [], None
    for ln in lines:
        if ln.startswith("death "):
            rec = {"obs": [], "trace": []}
            for part in ln[6:].split():
                if "=" in part:
                    k, v = part.split("=", 1)
                    rec[k] = v
            cur = rec
            out.append(cur)
        elif ln.startswith("dobs ") and cur is not None:
            f = ln[5:].split("|")
            if len(f) >= 5:
                cur["obs"].append({"x": float(f[0]), "z": float(f[1]), "mid": f[2],
                                   "speed": float(f[3] or 0), "name": f[4].replace("(Clone)", "")})
        elif ln.startswith("trace ") and cur is None:
            pass
    return out


def classify(rec: dict, bounds: dict) -> dict:
    """Name the thing that killed this run, and the shape of the mistake."""
    try:
        z = float(rec.get("z", 0))
        lane = int(rec.get("lane", -1))
    except (TypeError, ValueError):
        return {"cause": "unknown", "killer": None, "z": 0.0}
    lane_of = {32: 0, 36: 1, 40: 2}
    hits = []
    ramps = {0: [], 1: [], 2: []}
    for o in rec["obs"]:
        nm = o["name"]
        if "score_gold" in nm:
            continue
        # A bridge deck cannot kill: it is 11-15 m up and the runner passes under it, which the
        # recordings show 77 times over. What it CAN do is take the blame — its body is 34-46 m
        # long and 19-64 wide, so it covers more of the track than everything else put together
        # and any death inside one used to be named after it. That is how `bridge` came to be
        # the second-largest cause in the record, and it is why the viaduct spent a session
        # being modelled as a wall. Left out of the running, a death near a bridge is reported
        # as what it is: unexplained.
        if "qiaodong" in nm or "gaojiaqiao" in nm:
            continue
        z0, z1, sx = body_of(nm, o["z"], bounds)
        lanes = [0, 1, 2] if sx > 6 else [lane_of.get(int(o["x"]), -1)]
        if "chexiang" in nm.lower():
            for ll in lanes:
                if ll >= 0:
                    ramps[ll].append((z0, z1, "xiepo" in nm.lower()))
        if z0 - 2 <= z <= z1 + 2 and lane in lanes:
            hits.append((nm, z0, z1))
    if not hits:
        return {"cause": "unknown", "killer": None, "z": z}
    # the nearest-fitting body is the one it was inside
    nm, z0, z1 = min(hits, key=lambda h: abs(h[1] - z))
    low = nm.lower()
    mid_entry = (z - z0) > 4.0     # well inside the body, not at its leading edge
    if "xiepo" in low:
        cause = "side_entry" if mid_entry else "ramp_head_on"
    elif "chexiang" in low or "truck" in low:
        roofed = any(r[2] for r in ramps.get(lane, []) if r[1] <= z0 + 0.01 and r[1] >= z0 - 20)
        cause = "roof" if roofed else ("side_entry" if mid_entry else "wall")
    elif "zhalan" in low:
        cause = "fence"
    elif "qiao" in low:
        cause = "bridge"
    else:
        cause = "wall"
    return {"cause": cause, "killer": nm, "z": z}


def load_store() -> dict:
    try:
        with open(STORE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"deaths": [], "cfg": {}}


def save_store(store: dict) -> None:
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=1, sort_keys=True)


def record(store: dict, rec: dict, dist: float, lives: int, version: str = "") -> dict:
    """Add one classified death to the store and return it."""
    bounds = _bounds()
    cls = classify(rec, bounds)
    entry = {
        "t": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dist": round(dist, 1),
        "lives": lives,
        "z": cls["z"],
        "cause": cls["cause"],
        "killer": cls["killer"],
        "lane": rec.get("lane"),
        "speed": rec.get("speed"),
        "y": rec.get("y"),
        "version": version,
    }
    store.setdefault("deaths", []).append(entry)
    return entry


def tally(store: dict) -> dict:
    counts: dict[str, int] = {}
    for d in store.get("deaths", []):
        counts[d["cause"]] = counts.get(d["cause"], 0) + 1
    return counts


def derive_cfg(store: dict) -> dict:
    """Turn the tally into autopilot overrides.

    Deliberately blunt and bounded: a cause has to show up repeatedly before it moves a
    knob, and every knob is clamped. Nothing here can make the planner reckless — the
    adjustments only ever add margin or remove an assumption.
    """
    counts = tally(store)
    cfg: dict[str, float | bool] = {}

    # ramps: two head-on deaths inside one and the "rideable" assumption is simply wrong
    if counts.get("ramp_head_on", 0) >= 2:
        cfg["rampSolid"] = True

    # the roof does not carry as far as assumed — pull the gap in, one step per death
    roof = counts.get("roof", 0)
    if roof:
        cfg["roofGap"] = max(LIMITS["roofGap"][0], 16.0 - 4.0 * roof)

    # margin: the clean "we cut it too fine" failures
    tight = counts.get("wall", 0) + counts.get("side_entry", 0) + counts.get("fence", 0) \
        + counts.get("bridge", 0)
    if tight >= 2:
        cfg["padExtra"] = min(LIMITS["padExtra"][1], 1.5 + 0.25 * (tight - 1))

    return cfg


def summary(store: dict) -> str:
    deaths = store.get("deaths", [])
    if not deaths:
        return "no deaths recorded yet"
    counts = tally(store)
    dists = [d["dist"] for d in deaths if d.get("dist")]
    best = max(dists) if dists else 0
    recent = dists[-5:]
    lines = [
        "attempts recorded : %d" % len(deaths),
        "best distance     : %.0f m" % best,
        "last five         : %s" % ", ".join("%.0f" % d for d in recent),
        "causes            : %s" % ", ".join("%s=%d" % kv for kv in sorted(counts.items())),
    ]
    killers: dict[str, int] = {}
    for d in deaths:
        if d.get("killer"):
            killers[d["killer"]] = killers.get(d["killer"], 0) + 1
    if killers:
        top = sorted(killers.items(), key=lambda kv: -kv[1])[:4]
        lines.append("top killers       : %s" % ", ".join("%s x%d" % kv for kv in top))
    cfg = derive_cfg(store)
    lines.append("derived tuning    : %s" % (cfg or "none (defaults hold)"))
    return "\n".join(lines)
