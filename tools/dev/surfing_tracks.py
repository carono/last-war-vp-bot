#!/usr/bin/env python3
r"""How the Street Run track is generated, read off the config and checked against the recordings.

A run is a chain of 330-metre bands. Which band goes in which slot is not free: the stage
config names a pool per slot, and the recordings say the draw inside that pool is memoryless.
This module holds that model, recovers the band chain of a recording under it, reports what
the recordings say about the draw, and emits synthetic routes for testing the planner.

    python3 tools/dev/surfing_tracks.py model              # the generator, as the config states it
    python3 tools/dev/surfing_tracks.py chains             # every recording's band chain
    python3 tools/dev/surfing_tracks.py stats              # what the recordings say about the draw
    python3 tools/dev/surfing_tracks.py draw 40 7          # a route drawn the way the game draws
    python3 tools/dev/surfing_tracks.py routes --write     # the synthetic test set -> results/
    python3 tools/dev/surfing_tracks.py cover              # replay every (layout, speed), 3 lanes
    python3 tools/dev/surfing_tracks.py cover 1 speed=60   # one lane, one speed

Three things it is worth knowing before reading the numbers.

**A scene id is not a layout.** `412`, `512` and `612` all lay down the obstacles of born
pattern `312`; what differs is the pool they sit in and therefore the speed. So the thing to
cover is the *pair* (layout, speed), not the scene id and not the layout alone.

**Speed is a step, not a ramp.** Each pool has its own `speedZ`, and the recordings show the
runner change speed exactly at the band boundary — 30 through band 4, 40 through band 11, 50
through band 20, 60 after that. Anything that models speed as `speed0 + accel*z` meets every
obstacle at the wrong speed by up to 4 u/s and gets the seams worst of all.

**The config dump is partial.** `SurfingStageSceneTemplateManager` holds what the client has
parsed, so pools the recordings never reached are only half dumped. Every command here prints
what it had to leave out rather than quietly covering less than it claims.
"""
from __future__ import annotations

import collections
import json
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "lib"))

import surfing_simulate as S  # noqa: E402

STAGE_ID = "50000"
ROUTES_PATH = os.path.join("results", "street_run", "routes.json")
DEATHS_PATH = os.path.join("results", "street_run", "deaths.json")

# Recordings, in the order they were taken. `last_frames` is the autopilot's own frame buffer
# from a short attempt — one more sample of the opening, which the long human runs have lost.
RECORDINGS = [
    os.path.join(S.HUMAN_DIR, "run_001.txt"),
    os.path.join(S.HUMAN_DIR, "run_002.txt"),
    os.path.join(S.HUMAN_DIR, "run_003.txt"),
    os.path.join("results", "street_run", "last_frames.txt"),
]


# --------------------------------------------------------------------------- the generator

class Generator:
    """The slot -> pool -> speed schedule, exactly as `stage.json` states it.

    `pre_scene` is 66 m of empty road and carries no band. Then `start_scene` is band 0,
    `surfing_scene` reads `"N;a,b,c"` — play N bands drawn from that pool — and `infinite_scene`
    is drawn from for every band after those run out."""

    def __init__(self):
        self.born, self.mon = S.load_config()
        with open(os.path.join(S.CONFIG, "scene.json"), "r", encoding="utf-8") as fh:
            self.scene = json.load(fh)
        with open(os.path.join(S.CONFIG, "stage.json"), "r", encoding="utf-8") as fh:
            self.stage = json.load(fh)[STAGE_ID]
        # a band is a fixed template list; the ones spanning more than one band length are the
        # sky_score coin trails (108/109/110), which are an overlay and never a slot
        self.layouts = {b: rows for b, rows in S.bands(self.born, self.mon).items()
                        if max(z for _, z, _ in rows) <= S.BAND_PITCH + 10}
        self.layout_of = {}
        for sid, rec in self.scene.items():
            pref = {str(m)[:-3] for m in (rec.get("farmMonster") or [])}
            if len(pref) == 1:
                self.layout_of[int(sid)] = pref.pop()
        self.segments = [(1, [int(x) for x in self.stage["start_scene"]])]
        for entry in self.stage["surfing_scene"]:
            count, ids = entry.split(";")
            self.segments.append((int(count), [int(x) for x in ids.split(",")]))
        self.infinite = [int(x) for x in self.stage["infinite_scene"]]

    def segment_of(self, idx: int):
        """`(first slot, span or None, pool ids)` for the segment band `idx` falls in."""
        first = 0
        for count, ids in self.segments:
            if idx < first + count:
                return first, count, ids
            first += count
        return first, None, self.infinite

    def pool(self, idx: int) -> list:
        return self.segment_of(idx)[2]

    def speed(self, idx: int) -> float:
        """The speed the whole of band `idx` runs at — one number, not a ramp."""
        speeds = {self.scene[str(s)]["speedZ"] for s in self.pool(idx) if str(s) in self.scene}
        return float(sorted(speeds)[0]) if speeds else 30.0

    def known(self, idx: int) -> dict:
        """`layout -> scene id` for the entries of this slot's pool that were dumped."""
        out = {}
        for sid in self.pool(idx):
            lay = self.layout_of.get(sid)
            if lay in self.layouts:
                out[lay] = sid
        return out

    def scene_for(self, idx: int, layout: str):
        return self.known(idx).get(layout)

    def draw(self, count: int, seed: int) -> list:
        """A route drawn the way the game draws one: each slot uniform over its own pool.

        Only the dumped entries can be drawn — a layout with no template cannot be replayed.
        `stats` prints how large that gap is per pool."""
        rng = random.Random(seed)
        return [rng.choice(sorted(self.known(i))) for i in range(count)]

    def extend(self, order, extra: int, seed: int, first: int = 0) -> list:
        """Carry a chain on past its end, drawing each new band from the slot it lands in."""
        rng = random.Random(seed)
        out = list(order)
        for i in range(extra):
            out.append(rng.choice(sorted(self.known(first + len(out)))))
        return out

    def speed_runs(self, count: int, first: int = 0):
        """The route split into its constant-speed stretches: `(offset in the route, span,
        speed)`, where the route's own first band is absolute slot `first`.

        A recording that lost its opening to the frame buffer does not start at band 0, so the
        slot — and with it the speed — has to be counted from where the chain really begins."""
        runs, slot = [], first
        while slot < first + count:
            seg_first, span, _ = self.segment_of(slot)
            span = (seg_first + span - slot) if span else (first + count - slot)
            span = min(span, first + count - slot)
            speed = self.speed(slot)
            if runs and runs[-1][2] == speed:
                runs[-1] = (runs[-1][0], runs[-1][1] + span, speed)
            else:
                runs.append((slot - first, span, speed))
            slot += span
        return runs


def route_speed_steps(gen: Generator, route: dict):
    """The speed profile a catalogue route runs at.

    A `game` route walks the schedule, so its speed steps where the slots step. Every other
    kind is a probe of ONE pool and holds that pool's speed for its whole length — a sweep of
    the 40-pool laid 24 bands long would otherwise run its tail at 50 and 60, which are speeds
    the game never gives those layouts."""
    if route.get("speed") is None:
        return speed_steps(gen, len(route["bands"]), route["first"])
    return [(0.0, float(route["speed"]))]


def speed_steps(gen: Generator, count: int, first: int = 0):
    """The route's speed as `[(z, speed), ...]` — what the judge and the search both take.

    z is measured from the start of the route, not from the start of the run, so a chain that
    begins at band 4 still starts at z = 0. Speed is held from each z until the next entry,
    which is exactly what the game does: flat across a band, a step on the boundary."""
    return [(off * S.BAND_PITCH, speed)
            for off, _span, speed in gen.speed_runs(count, first)]


# ------------------------------------------------------------------------- naming a recording

def chain_from_run(gen: Generator, path: str, min_hits: int = 4):
    """Which band sat in each slot of a recording, named inside the slot's own pool.

    `surfing_simulate.band_order_from_run` asks the same question of the whole library at once.
    Asking it of the pool the generator allows is both a tighter answer and a test: if the two
    disagree anywhere, either the naming or the generator is wrong. They do not disagree.

    Returns one row per slot: `dict(idx, off, seen, layout, hits, second, margin, scene, free)`
    where `free` is the unrestricted winner and `second` the runner-up inside the pool."""
    zs, obs = S.read_run(path)
    if not zs:
        return []
    rounded = {(x, round(z), mid) for x, z, mid in obs}
    rows = []
    for idx in range(int(max(zs)) // S.BAND_PITCH + 1):
        off = idx * S.BAND_PITCH
        seen = sum(1 for _, z, _ in rounded if off < z <= off + S.BAND_PITCH)

        def score(layout):
            return sum(1 for x, z, mid in gen.layouts[layout]
                       if (x, round(z) + off, mid) in rounded)

        inside = sorted(((score(b), b) for b in gen.known(idx)), reverse=True)
        free = sorted(((score(b), b) for b in gen.layouts), reverse=True)[0]
        hits, layout = inside[0] if inside else (0, None)
        second = inside[1] if len(inside) > 1 else (0, None)
        named = layout if hits >= min_hits else None
        rows.append(dict(idx=idx, off=off, seen=seen, layout=named, hits=hits,
                         second=second[1], second_hits=second[0],
                         scene=gen.scene_for(idx, named) if named else None,
                         speed=gen.speed(idx), free=free[1] if free[0] >= min_hits else None,
                         free_hits=free[0], pool=len(gen.known(idx))))
    return rows


def deaths_bands(gen: Generator):
    """The bands a live bot death can name, out of `deaths.json`.

    A death carries no field, only where the runner was, which lane, and what hit it. That is
    still a name when exactly one layout in the slot's pool has that object in that lane just
    ahead of where the runner stopped. Most deaths leave several candidates; the ones that do
    not are extra samples of the draw at the low slots, where the long recordings have nothing
    (their frame buffer has already rolled over by the time they are saved)."""
    try:
        with open(DEATHS_PATH, "r", encoding="utf-8") as fh:
            rec = json.load(fh)
    except OSError:
        return []
    names = {int(k): (v.get("asset") or "").split("/")[-1].replace(".prefab", "")
             for k, v in gen.mon.items()}
    out = []
    for row in rec.get("deaths", []):
        if row.get("version") == "replay" or not row.get("killer"):
            continue
        z = float(row["z"])
        idx = int(z // S.BAND_PITCH)
        rest = z - idx * S.BAND_PITCH
        lane_x = 32 + 4 * int(row["lane"])
        cands = set()
        for layout in gen.known(idx):
            for x, bz, mid in gen.layouts[layout]:
                # the killer's anchor is its far end, so it stands a body length ahead of where
                # the runner stopped; 55 is the longest body on the track (a carriage)
                if abs(x - lane_x) < 0.6 and names.get(mid) == row["killer"] and -3 <= bz - rest <= 55:
                    cands.add(layout)
                    break
        out.append((idx, sorted(cands), row))
    return out


# ------------------------------------------------------------------------------- the commands

def cmd_model(argv, gen: Generator):
    """Print the schedule the config states, and how much of each pool was dumped."""
    print("stage %s: pre_scene %s m of empty road, then bands of %d m" %
          (STAGE_ID, gen.scene[str(gen.stage["pre_scene"])]["max_meters"], S.BAND_PITCH))
    first = 0
    rows = list(gen.segments) + [(None, gen.infinite)]
    for count, ids in rows:
        known = [s for s in ids if gen.layout_of.get(s) in gen.layouts]
        span = "%2d..%-3d" % (first, first + count - 1) if count else "%2d..    " % first
        zspan = "z %5d..%-6s" % (first * S.BAND_PITCH,
                                 (first + count) * S.BAND_PITCH if count else "")
        print("  band %s  %s  speed %2.0f  pool %2d ids, %2d dumped" %
              (span, zspan, gen.speed(first), len(ids), len(known)))
        if count:
            first += count
    print("\nthe same layout runs in several pools at different speeds — cover the pair:")
    pairs = collections.defaultdict(set)
    for idx in (0, 1, 2, 5, 12, 21):
        for layout in gen.known(idx):
            pairs[layout].add(gen.speed(idx))
    multi = {b: sorted(v) for b, v in pairs.items() if len(v) > 1}
    print("  %d layouts dumped in all, %d of them at more than one speed (%d configurations)" %
          (len(pairs), len(multi), sum(len(v) for v in pairs.values())))
    print("  e.g. " + ", ".join("%s at %s" % (b, "/".join("%.0f" % s for s in v))
                                for b, v in sorted(multi.items())[:4]))
    sky = [b for b, rows_ in S.bands(gen.born, gen.mon).items()
           if b not in gen.layouts]
    if sky:
        print("\n  overlay layouts (not slots): %s — %s" %
              (", ".join(sorted(sky)), "the flight coin trails, 250 coins at y=20 over 1250 m"))
    return 0


def cmd_chains(argv, gen: Generator):
    """Name every slot of every recording, and check the naming against the generator."""
    paths = argv or RECORDINGS
    conform = miss = agree = named = 0
    for path in paths:
        if not os.path.exists(path):
            cand = os.path.join(S.HUMAN_DIR, path if path.endswith(".txt") else path + ".txt")
            if not os.path.exists(cand):
                raise SystemExit("no such recording: %s" % path)
            path = cand
        rows = chain_from_run(gen, path)
        print("=== %s" % os.path.basename(path))
        for r in rows:
            if not r["seen"]:
                print("  band %2d  nothing in view (the frame buffer had rolled over)" % r["idx"])
                continue
            if not r["layout"]:
                print("  band %2d  UNNAMED — %d obstacles seen, best %s with %d" %
                      (r["idx"], r["seen"], r["free"], r["free_hits"]))
                miss += 1
                continue
            named += 1
            conform += 1
            agree += 1 if r["free"] == r["layout"] else 0
            print("  band %2d  scene %-6s layout %-5s speed %2.0f  %2d of %2d obstacles "
                  "(runner-up %s with %d, pool %d)" %
                  (r["idx"], r["scene"], r["layout"], r["speed"], r["hits"], r["seen"],
                   r["second"], r["second_hits"], r["pool"]))
    print("\n%d slots named. %d lie in the pool the generator allows for their slot; the "
          "unrestricted naming agrees on %d of them." % (named, conform, agree))
    if miss:
        print("%d slots have obstacles no allowed layout explains — those are the ones to "
              "look at before trusting the rest." % miss)
    return 0


def cmd_stats(argv, gen: Generator):
    """What the recordings say about the draw itself."""
    draws = collections.defaultdict(list)          # segment first slot -> [layout, ...]
    seq = collections.defaultdict(list)            # per recording, per segment
    for path in RECORDINGS:
        if not os.path.exists(path):
            continue
        rows = chain_from_run(gen, path)
        for r in rows:
            if not r["layout"]:
                continue
            first = gen.segment_of(r["idx"])[0]
            draws[first].append(r["layout"])
            seq[(os.path.basename(path), first)].append((r["idx"], r["layout"]))

    # a death that names its band outright is a draw like any other, and it lands at the low
    # slots the long recordings have lost — without them band 1 has a single sample
    from_deaths = collections.Counter()
    for idx, cands, _row in deaths_bands(gen):
        if len(cands) == 1:
            draws[gen.segment_of(idx)[0]].append(cands[0])
            from_deaths[gen.segment_of(idx)[0]] += 1

    print("--- how the draw comes out, over every named slot of every recording")
    total_draws = 0
    for first in sorted(draws):
        got = draws[first]
        pool_all = len(gen.pool(first))
        pool_known = len(gen.known(first))
        distinct = len(set(got))
        # if the draw were uniform over the whole pool, this many draws would be expected to
        # turn up this many distinct values
        expect = pool_all * (1 - ((pool_all - 1) / pool_all) ** len(got))
        top = collections.Counter(got).most_common(3)
        print("  band %2d+  %2d draws%s, %2d distinct (uniform over %d predicts %.1f) "
              "most often %s" %
              (first, len(got), " (%d of them off a death)" % from_deaths[first]
               if from_deaths[first] else "", distinct, pool_all, expect,
               ", ".join("%s x%d" % t for t in top)))
        total_draws += len(got)
        if distinct > pool_known:
            print("      NOTE only %d of the pool is dumped, yet more than that was drawn" %
                  pool_known)

    print("\n--- does a band depend on the one before it")
    pairs = repeats = 0
    expect_rep = 0.0
    examples = []
    for key, rows in sorted(seq.items()):
        rows.sort()
        for a, b in zip(rows, rows[1:]):
            if b[0] != a[0] + 1:
                continue
            pairs += 1
            expect_rep += 1.0 / len(gen.pool(b[0]))
            if a[1] == b[1]:
                repeats += 1
                examples.append("%s bands %d,%d both %s" % (key[0], a[0], b[0], a[1]))
    print("  %d consecutive pairs inside one pool, %d of them the same band twice "
          "(a memoryless draw predicts %.1f)" % (pairs, repeats, expect_rep))
    for ex in examples:
        print("      %s" % ex)
    print("  a band that could not follow itself, or a bag dealt without replacement, would "
          "have produced none of these.")

    print("\n--- what the bot's own deaths add at the low slots")
    named = collections.defaultdict(collections.Counter)
    total = unique = 0
    for idx, cands, _row in deaths_bands(gen):
        total += 1
        if len(cands) == 1:
            unique += 1
            named[idx][cands[0]] += 1
    print("  %d deaths carry a killer; %d of them name their band outright" % (total, unique))
    for idx in sorted(named):
        print("      band %d: %s" % (idx, ", ".join("%s x%d" % t
                                                    for t in named[idx].most_common())))
    print("\n%d slots of live track in all. The schedule is fixed and the draw inside it is "
          "not: there is no order to recover past the pools." % total_draws)
    return 0


def cmd_draw(argv, gen: Generator):
    """Draw one route the way the game draws it and print it ready to replay."""
    count = int(argv[0]) if argv else 40
    seed = int(argv[1]) if len(argv) > 1 else 1163
    order = gen.draw(count, seed)
    print("route of %d bands, seed %d:" % (count, seed))
    print("  " + ",".join(order))
    for first, span, speed in gen.speed_runs(count):
        print("  bands %2d..%-2d at %2.0f u/s: %s" %
              (first, first + span - 1, speed, ",".join(order[first:first + span])))
    return 0


def synthetic_routes(gen: Generator, seeds=range(1, 9), length: int = 40):
    """The synthetic test set.

    Four kinds, because a route says different things depending on how it was built:

    * `opening` — every start band against every band 1. Sixteen tracks, and the whole of the
      bot's live distribution lives inside them, so they are the set to be green on first.
    * `sweep` — one pool laid end to end, forwards and backwards. Every layout of the pool at
      its own speed, and 2N of the seams between them, in two replays instead of N.
    * `game` — a route drawn slot by slot the way the game draws one. What a run actually is.
    * `seam` — a layout whose roof runs to the end of its band, followed by one whose roof
      starts at the beginning of its own. The seam between two carriage groups is where the
      live roof deaths happen, and it only exists between two bands. Both at 30 and at 60,
      because the hop that has to clear it grows with the speed."""
    out = []
    starts = sorted(gen.known(0))
    seconds = sorted(gen.known(1))
    for a in starts:
        for b in seconds:
            out.append(dict(name="opening-%s-%s" % (a, b), kind="opening",
                            bands=[a, b], speed=gen.speed(0), first=0,
                            note="band 0 x band 1 — the stretch every attempt runs"))
    for first in (2, 5, 12, 21):
        pool = sorted(gen.known(first))
        speed = gen.speed(first)
        out.append(dict(name="sweep-%02.0f" % speed, kind="sweep", bands=pool,
                        speed=speed, first=first,
                        note="every dumped layout of the band-%d pool, in id order" % first))
        out.append(dict(name="sweep-%02.0f-rev" % speed, kind="sweep", bands=pool[::-1],
                        speed=speed, first=first,
                        note="the same pool reversed — the other %d seams" % (len(pool) - 1)))
    for seed in seeds:
        order = gen.draw(length, seed)
        out.append(dict(name="game-%d" % seed, kind="game", bands=order, speed=None,
                        first=0, runs=gen.speed_runs(length),
                        note="drawn slot by slot, seed %d; speed steps with the slot" % seed))
    for first in (2, 21):
        speed = gen.speed(first)
        tail, head = seam_layouts(gen, first)
        for a in tail:
            for b in head:
                out.append(dict(name="seam-%02.0f-%s-%s" % (speed, a, b), kind="seam",
                                bands=[a, b], speed=speed, first=first,
                                note="a roof running off the end of its band into the next "
                                     "band's, at %.0f u/s" % speed))
    return out


def seam_layouts(gen: Generator, idx: int, edge: float = 40.0):
    """`(tail, head)` — the layouts of a pool whose roof reaches the end of the band, and the
    ones whose roof starts at the beginning of it. Chain one of each and the band boundary
    falls in the middle of a roof ride, which is the only way to build that seam on purpose."""
    bounds = S.load_bounds()
    kinds = {int(k): S.classify(v, bounds) for k, v in gen.mon.items()}
    tail, head = [], []
    for layout in sorted(gen.known(idx)):
        rows = gen.layouts[layout]
        for _x, _z, mid in rows:
            S.kind_for(kinds, mid)
        _holes, roofs = S.roof_holes(rows, kinds, speed_at=S.speed_profile(gen.speed(idx), 0))
        if any(z1 >= S.BAND_PITCH - edge for _l, _z0, z1, _r in roofs):
            tail.append(layout)
        if any(z0 <= edge for _l, z0, _z1, _r in roofs):
            head.append(layout)
    return tail, head


def cmd_routes(argv, gen: Generator):
    """Print the synthetic test set, and write it where a battery can pick it up."""
    routes = synthetic_routes(gen)
    by_kind = collections.Counter(r["kind"] for r in routes)
    for kind in ("opening", "sweep", "game", "seam"):
        rows = [r for r in routes if r["kind"] == kind]
        print("--- %s: %d routes" % (kind, len(rows)))
        for r in rows[:3]:
            print("    %-18s %2d bands  %s" %
                  (r["name"], len(r["bands"]),
                   "speed %2.0f" % r["speed"] if r["speed"] else "speed steps with the slot"))
            print("        %s" % ",".join(r["bands"][:12]) +
                  (" ..." if len(r["bands"]) > 12 else ""))
        if len(rows) > 3:
            print("    ... and %d more" % (len(rows) - 3))
    print("\n%d routes, %d band slots in all." %
          (len(routes), sum(len(r["bands"]) for r in routes)))
    print("replay one with:  python3 tools/dev/surfing_offline.py route <bands> 1")
    if "--write" in argv:
        payload = dict(
            note="Synthetic Street Run routes, built from the generator in stage.json:50000. "
                 "`speed` is the constant the whole route runs at; a route with `runs` changes "
                 "speed at a band boundary and must be replayed one run at a time.",
            pitch=S.BAND_PITCH, kinds=dict(by_kind), routes=routes)
        with open(ROUTES_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, sort_keys=True)
        print("written to %s" % ROUTES_PATH)
    else:
        print("(--write to save them to %s)" % ROUTES_PATH)
    return 0


def _provenance(path: str) -> str:
    """Which revision of a Lua file a battery ran against — a pass count means nothing without
    it, and the two files under tools/lib are edited while the planner is being worked on."""
    import subprocess
    name = os.path.basename(path)
    try:
        run = lambda args: subprocess.run(args, cwd=_ROOT, capture_output=True,
                                          text=True, timeout=10).stdout.strip()
        dirty = run(["git", "status", "--porcelain", "--", os.path.abspath(path)])
        head = run(["git", "rev-parse", "--short", "HEAD"])
    except Exception:
        return name
    return "%s @ %s%s" % (name, head or "?", " + uncommitted edits" if dirty else "")


def cmd_cover(argv, gen: Generator):
    """Replay every (layout, speed) the generator can lay down, from every start lane.

    The per-band score has always run the whole library at a flat 30 u/s, which prices a band
    that only ever appears at 60 at a speed it never runs at, and never runs the ones that do
    appear at 30 at anything else. This runs each pair once, at the speed its pool gives it."""
    import surfing_offline as O

    lanes = [int(a) for a in argv if a.isdigit()]
    lanes = lanes or [0, 1, 2]
    want = [float(a.split("=", 1)[1]) for a in argv if a.startswith("speed=")]
    configs = []
    for first in (0, 1, 2, 5, 12, 21):
        speed = gen.speed(first)
        if want and speed not in want:
            continue
        for layout in sorted(gen.known(first)):
            if any(c[0] == layout and c[1] == speed for c in configs):
                continue
            configs.append((layout, speed, first))
    print("%d configurations x %d start lanes; ~%.0f s" %
          (len(configs), len(lanes), 2.2 * len(configs) * len(lanes)))
    print("planner %s, judge %s" % (_provenance(O.AI_LUA), _provenance(S.SIM_LUA_PATH)))
    rt, _ai = O.new_vm()
    ov, _b, _h, _r, _k, names = S.build_field()
    passed = collections.Counter()
    failed = []
    for layout, speed, first in configs:
        _ov, band, hole, roof, _kinds, _n = S.build_field(order=[layout], speed0=speed)
        for lane in lanes:
            dist, dead, _moves = O.run_group(rt, ov, band[0], hole[0], roof[0], lane, speed,
                                             0, S.BAND_PITCH + 10)
            if dead is None:
                passed[speed] += 1
            else:
                failed.append((layout, speed, first, lane, dist, O.describe(dead, names)))
                print("DIE  layout %-5s at %2.0f u/s (band %2d+) from %-6s  %6.1f m  %s" %
                      (layout, speed, first, S.LANE_NAME[lane], dist, O.describe(dead, names)))
    total = len(configs) * len(lanes)
    print("\nCOVER passed=%d of=%d" % (sum(passed.values()), total))
    for speed in sorted(passed):
        n = sum(1 for c in configs if c[1] == speed) * len(lanes)
        print("  %2.0f u/s: %d of %d" % (speed, passed[speed], n))
    if failed:
        print("  the configurations that fail are the whole of the ceiling — every one of them "
              "is a band the game can draw at any time.")
    return 0 if not failed else 1


def cmd_catalogue(argv, gen: Generator):
    """Run the catalogue through the planner — every route at its own speed steps.

    `cover` asks whether a band is survivable on its own. This asks the question a run asks:
    does the planner get through a track the game could lay down, with the seams in it and the
    speed stepping where the game steps it.

        catalogue                # every route, from the centre lane
        catalogue 0 1 2          # ... from all three
        catalogue kind=opening   # one kind only (opening, sweep, game, seam)
    """
    import surfing_offline as O

    lanes = [int(a) for a in argv if a.isdigit()] or [1]
    kinds = [a.split("=", 1)[1] for a in argv if a.startswith("kind=")]
    routes = [r for r in synthetic_routes(gen) if not kinds or r["kind"] in kinds]
    print("%d routes x %d start lanes" % (len(routes), len(lanes)))
    print("planner %s, judge %s" % (_provenance(O.AI_LUA), _provenance(S.SIM_LUA_PATH)))
    rt, _ai = O.new_vm()
    tally = collections.defaultdict(lambda: [0, 0])
    for route in routes:
        order = route["bands"]
        first = route["first"]
        steps = route_speed_steps(gen, route)
        zmax = len(order) * S.BAND_PITCH
        ov, band, hole, roof, _k, names = S.build_field(order=order, speed0=steps[0][1],
                                                        steps=steps)
        for lane in lanes:
            dist, dead, _moves = O.run_group(rt, ov, band[0], hole[0], roof[0], lane,
                                             steps[0][1], 0, zmax, steps)
            tally[route["kind"]][1] += 1
            if dead is None:
                tally[route["kind"]][0] += 1
            else:
                slot = min(int(dist // S.BAND_PITCH), len(order) - 1)
                at = S.speed_profile(steps=steps)(slot * S.BAND_PITCH)
                print("DIE  %-18s from %-6s %6.0f of %5d m  band %d (%s at %2.0f u/s)  %s" %
                      (route["name"], S.LANE_NAME[lane], dist, zmax, slot, order[slot],
                       at, O.describe(dead, names)))
    print("\nCATALOGUE passed=%d of=%d" %
          (sum(v[0] for v in tally.values()), sum(v[1] for v in tally.values())))
    for kind in sorted(tally):
        print("  %-8s %d of %d" % (kind, tally[kind][0], tally[kind][1]))
    return 0 if all(v[0] == v[1] for v in tally.values()) else 1


COMMANDS = {"model": cmd_model, "chains": cmd_chains, "stats": cmd_stats,
            "draw": cmd_draw, "routes": cmd_routes, "cover": cmd_cover,
            "catalogue": cmd_catalogue, "catalog": cmd_catalogue}


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not argv or argv[0] not in COMMANDS:
        print(__doc__.strip())
        return 2
    return COMMANDS[argv[0]](argv[1:], Generator())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
