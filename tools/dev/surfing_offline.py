#!/usr/bin/env python3
r"""Run the Street Run autopilot against the real track with NO game running at all.

``surfing_simulate.py`` pushes the judge into the live client's Lua VM. That is the honest
place to check that the installed planner behaves — but it costs a round trip per rotation,
it freezes the client for minutes while the replay runs (a whole chained scan took ~11 min),
and a frozen client is one that can be lost. None of that is acceptable as the inner loop of
"tune, judge, tune again".

So the same two Lua files are loaded into a LOCAL Lua instead (``lupa``):

  * ``tools/lib/surfing_ai.lua``  — the planner, byte for byte the one the live run installs;
  * ``tools/lib/surfing_sim.lua`` — the judge, byte for byte the one the in-VM replay uses.

Nothing is reimplemented in Python; the game-side globals the planner touches at load time
(``CS.UnityEngine.Debug``, ``DataCenter``, ``require``, ``typeof``) are stubbed, and every
obstacle kind is injected through ``AI.kindOverride`` exactly as the in-VM replay injects it,
so ``templateOf`` is never reached. The obstacle field itself comes from
``surfing_simulate.build_field`` — the same function, the same track.

    python3 tools/dev/surfing_offline.py chain          # every start lane x every band order
    python3 tools/dev/surfing_offline.py chain 1        # one start lane
    python3 tools/dev/surfing_offline.py score          # per-band replay, fixed speed
    python3 tools/dev/surfing_offline.py cfg padExtra=2 chain 1     # judge a tuning
    python3 tools/dev/surfing_offline.py where 306      # what is on the track around z=306

`cfg` overrides are applied to ``AI.cfg`` after the file loads and before the kind cache is
dropped, which is what lets a tuning be judged before it is ever allowed near a live attempt.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "lib"))

import surfing_simulate as S  # noqa: E402

# Which planner to host. Overridable so a previous revision can be replayed against the same
# track for comparison — "did this change help" is otherwise unanswerable once the file moves on:
#   git show HEAD:tools/lib/surfing_ai.lua > /tmp/ai_before.lua
#   SR_AI_LUA=/tmp/ai_before.lua python3 tools/dev/surfing_offline.py chain 1
AI_LUA = os.environ.get("SR_AI_LUA") or os.path.join(_ROOT, "lib", "surfing_ai.lua")
LANE_NAME = S.LANE_NAME

# the game-side surface the planner touches while loading; none of it is used once
# AI.kindOverride carries every kind on the track
_STUBS = """
CS = {UnityEngine = {Debug = {LogError = function(s) __SR_LOG[#__SR_LOG + 1] = tostring(s) end}}}
DataCenter = {}
function typeof(x) return nil end
local _require = require
function require(n) return {} end
"""


def new_vm(cfg: dict | None = None):
    """A local Lua holding the real planner and the real judge."""
    try:
        import lupa
    except ImportError:
        # a plain error, not SystemExit: this is imported as a library by the between-attempt
        # learner, which has to be able to catch it and fall back
        raise RuntimeError(
            "lupa is not installed — this runner needs a local Lua "
            "(python -m pip install lupa; or use the in-VM runner tools/dev/surfing_simulate.py)")
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.execute("__SR_LOG = {}")
    rt.execute(_STUBS)
    for path in (AI_LUA, S.SIM_LUA_PATH):
        with open(path, "r", encoding="utf-8") as fh:
            rt.execute(fh.read())
    ai = rt.globals()["_G"]["__SR_AI"]
    if ai is None or ai["planRoute"] is None:
        raise RuntimeError("the planner did not load — check tools/lib/surfing_ai.lua")
    for key, val in (cfg or {}).items():
        ai["cfg"][key] = val
    if ai["resetKinds"] is not None:
        ai["resetKinds"]()
    return rt, ai


def run_group(rt, ov: str, band: str, hole: str, roof: str,
              lane0: int, speed: float, accel: float, zmax: float):
    """One replay through the shared judge. Returns (distance, death or None, moves)."""
    rt.execute("__SR_AI.kindOverride = {%s}" % ov)
    if rt.globals()["_G"]["__SR_AI"]["resetKinds"] is not None:
        rt.globals()["_G"]["__SR_AI"]["resetKinds"]()
    # band/hole/roof already arrive brace-wrapped from build_field — one group each
    fn = rt.eval(
        "function(l, s, a, zm) return __SR_SIM.once(%s, %s, %s, l, s, a, zm) end"
        % (band, hole, roof))
    pz, dead, moves = fn(lane0, speed, accel, zmax)
    if dead is not None:
        dead = {"mid": int(dead["mid"] or 0), "x": float(dead["x"] or 0),
                "obz": float(dead["z"] or 0), "seam": bool(dead["seam"])}
    return float(pz), dead, int(moves)


def describe(dead: dict, names: dict) -> str:
    if dead["seam"]:
        return "roof seam (a drop between two carriages) at %.0f" % dead["obz"]
    return "%s at %.0f (x=%.0f, lane %s)" % (
        names.get(dead["mid"], dead["mid"]), dead["obz"], dead["x"],
        LANE_NAME[min(range(3), key=lambda i: abs(dead["x"] - (32 + 4 * i)))])


def cmd_chain(argv, cfg):
    """The chained-track scan: every band order, so band seams are exercised."""
    lanes = [int(argv[0])] if argv and argv[0].lstrip("-").isdigit() else [0, 1, 2]
    rt, _ = new_vm(cfg)
    nrot = len(S.bands(*S.load_config()))
    zmax = nrot * 340
    worst_overall = None
    for lane0 in lanes:
        worst = None
        for rot in range(nrot):
            ov, band, hole, roof, _, names = S.build_field(accel=0.0027, rot=rot)
            dist, dead, _ = run_group(rt, ov, band[0], hole[0], roof[0],
                                      lane0, 30, 0.0027, zmax)
            tag = "ok " if dead is None else "DIE"
            note = "" if dead is None else "  " + describe(dead, names)
            print("%s start=%-6s rot=%-2d dist=%6.0f%s" % (tag, LANE_NAME[lane0], rot, dist, note))
            if worst is None or dist < worst[1]:
                worst = (rot, dist, dead, names)
        print("  -> start=%-6s worst rot=%d dist=%.0f of %d m" %
              (LANE_NAME[lane0], worst[0], worst[1], zmax))
        if worst_overall is None or worst[1] < worst_overall[1]:
            worst_overall = worst
    print("CHAIN worst dist=%.0f of %d m" % (worst_overall[1], zmax))
    return 0


def cmd_score(argv, cfg):
    """The per-band replay at a fixed speed — the isolated score, guarded against regression."""
    lanes = [int(argv[0])] if argv and argv[0].lstrip("-").isdigit() else [0, 1, 2]
    speed = 30
    for a in argv:
        if a.startswith("speed="):
            speed = int(a.split("=", 1)[1])
    rt, _ = new_vm(cfg)
    ov, band_src, hole_src, roof_src, _, names = S.build_field()
    total_pass, total_all, total_dist = 0, 0, 0.0
    for lane0 in lanes:
        passed = 0
        for i, band in enumerate(band_src):
            dist, dead, _ = run_group(rt, ov, band, hole_src[i], roof_src[i], lane0, speed, 0, 340)
            total_dist += dist
            if dead is None:
                passed += 1
            else:
                print("DIE start=%-6s band %-2d dist=%6.1f  %s"
                      % (LANE_NAME[lane0], i, dist, describe(dead, names)))
        total_pass += passed
        total_all += len(band_src)
        print("  -> start=%-6s %d/%d bands" % (LANE_NAME[lane0], passed, len(band_src)))
    print("SCORE passed=%d of=%d dist=%.0f speed=%d" % (total_pass, total_all, total_dist, speed))
    return 0 if total_pass == total_all else 1


ACT_NAME = {0: "-", 1: "left", 2: "right", 3: "JUMP", 4: "SLIDE"}


def cmd_trace(argv, cfg):
    """Replay ONE band and print what the planner decided on the way to its death.

    The score line says which obstacle killed the run; only the decision stream says why the
    planner walked into it — whether it never saw a way past, or saw one and mistimed it."""
    if not argv:
        raise SystemExit("usage: trace <band-index> [start-lane] [speed] [span]")
    idx = int(argv[0])
    lanes = [int(argv[1])] if len(argv) > 1 else [0, 1, 2]
    speed = float(argv[2]) if len(argv) > 2 else 30
    span = float(argv[3]) if len(argv) > 3 else 60.0
    rt, ai = new_vm(cfg)
    ov, band_src, hole_src, roof_src, kinds, names = S.build_field()
    order = sorted(S.bands(*S.load_config()))
    print("band %d (id %s), speed %g" % (idx, order[idx], speed))

    def snap():
        """planRoute's own account: per lane, how far it is clear and how far the DP got."""
        st = ai["stat"]
        d, r = st["whyD"], st["whyR"]
        return ("%d/%d/%d" % (d[0], d[1], d[2]), "%d/%d/%d" % (r[0], r[1], r[2]))

    for lane0 in lanes:
        rows = []
        rt.globals()["__SR_SIM"]["watch"] = (
            lambda pz, lane, sp, act, az, reach, roof, j, sl, sw:
            rows.append((pz, lane, sp, act, az, reach, roof, j, sl, sw) + snap()))
        dist, dead, _ = run_group(rt, ov, band_src[idx], hole_src[idx], roof_src[idx],
                                  lane0, speed, 0, 340)
        rt.globals()["__SR_SIM"]["watch"] = None
        head = "start=%-6s dist=%.1f" % (LANE_NAME[lane0], dist)
        print("\n%s  %s" % (head, "survived" if dead is None else describe(dead, names)))
        if dead is None:
            continue
        last, prev = None, None

        def show(row):
            pz, lane, sp, act, az, reach, roof, j, sl, sw, clear, dpreach = row
            print("  z=%7.1f lane=%-6s v=%4.1f act=%-5s in=%3d reach=%3d clear=%-12s "
                  "dp=%-12s%s%s%s%s"
                  % (pz, LANE_NAME[int(lane)], sp, ACT_NAME[int(act)], az, reach, clear,
                     dpreach, " roof" if roof else "", " air" if j else "",
                     " slide" if sl else "", " switching" if sw else ""))

        for row in rows:
            pz, lane, act, az, reach, roof, j, sl, sw = (
                row[0], row[1], row[3], row[4], row[5], row[6], row[7], row[8], row[9])
            if pz < dist - span:
                continue
            # only the frames where something changed — a run of identical "hold" decisions
            # says nothing and buries the two frames that matter
            key = (int(lane), int(act), int(az), int(roof), int(j), int(sl), int(sw))
            if key == prev and act == 0:
                last = row
                continue
            if last is not None:
                show(last)
                last = None
            prev = key
            show(row)
        if last is not None:
            show(last)
        print("  --- the track it was reading ---")
        cmd_where([str(dead["obz"]), "-", str(span)], cfg, band=idx)
    return 0


def score_local(cfg=None, lane0: int = 1, speed: int = 30):
    """The isolated per-band score as one number, for callers rather than the console.

    Same signature-in-spirit as ``surfing_simulate.score``: ``(passed, total, distance)``,
    so the between-attempt learner can judge a proposed tuning without the game."""
    rt, _ = new_vm(cfg or {})
    ov, band_src, hole_src, roof_src, _, _ = build_field_cached()
    passed, dist = 0, 0.0
    for i, band in enumerate(band_src):
        d, dead, _ = run_group(rt, ov, band, hole_src[i], roof_src[i], lane0, speed, 0, 340)
        dist += d
        if dead is None:
            passed += 1
    return passed, len(band_src), dist


_FIELD_CACHE = {}


def build_field_cached(accel: float = 0.0, rot: int = 0):
    key = (accel, rot)
    if key not in _FIELD_CACHE:
        _FIELD_CACHE[key] = S.build_field(accel, rot)
    return _FIELD_CACHE[key]


def cmd_where(argv, cfg, band=None):
    """What the track actually holds around a distance — the context a death report lacks.

    `band=` restricts it to one band on its own (the isolated replay); otherwise the chained
    track at rotation `rot` is laid out, which is where the band seams live."""
    if not argv:
        raise SystemExit("usage: where <z> [rot|-] [span]   |   trace ... uses band=")
    at = float(argv[0])
    sel = argv[1] if len(argv) > 1 else "0"
    rot = 0
    if sel.startswith("b"):          # "b7" — band 7 on its own, as the isolated replay sees it
        band = int(sel[1:])
    elif sel not in ("-",):
        rot = int(sel)
    span = float(argv[2]) if len(argv) > 2 else 40.0
    born, mon = S.load_config()
    bounds = S.load_bounds()
    kinds = {int(k): S.classify(v, bounds) for k, v in mon.items()}
    per_band = S.bands(born, mon)
    order = sorted(per_band)
    if band is not None:
        order = [order[band]]
    else:
        order = order[rot % len(order):] + order[:rot % len(order)]
    rows, off = [], 0
    for band in order:
        for x, z, mid in per_band[band]:
            rows.append((x, z + off, mid, band))
        off += 340
    names = {int(k): (v.get("asset") or "").split("/")[-1].replace(".prefab", "")
             for k, v in mon.items()}
    holes, roofs = S.roof_holes([(x, z, m) for x, z, m, _ in rows], kinds)
    print("track around z=%.0f (rot=%d, +/-%.0f)" % (at, rot, span))
    for x, z, mid, band in sorted(rows, key=lambda r: r[1]):
        if abs(z - at) > span:
            continue
        k = S.kind_for(kinds, mid)
        lane = min(range(3), key=lambda i: abs(x - (32 + 4 * i)))
        flags = [n for n in ("solid", "jump", "slide", "carriage", "ramp", "sideOnly", "ignore")
                 if k.get(n)]
        print("  z=%8.1f lane=%-6s %-34s body=[%.1f,%.1f] %s"
              % (z, LANE_NAME[lane], names.get(mid, mid), z - k.get("back", 0),
                 z + k.get("front", 0), ",".join(flags)))
    for lane, z0, z1 in holes:
        if z1 >= at - span and z0 <= at + span:
            print("  SEAM  lane=%-6s %.1f..%.1f (a drop between roofs)" % (LANE_NAME[lane], z0, z1))
    for lane, z0, z1 in roofs:
        if z1 >= at - span and z0 <= at + span:
            print("  ROOF  lane=%-6s %.1f..%.1f (rideable)" % (LANE_NAME[lane], z0, z1))
    return 0


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cfg: dict = {}
    rest: list = []
    it = iter(argv)
    for a in it:
        if a == "cfg":
            for pair in it:
                if "=" not in pair:
                    rest.append(pair)
                    break
                key, val = pair.split("=", 1)
                cfg[key] = (val == "true") if val in ("true", "false") else float(val)
        else:
            rest.append(a)
    cmd = rest[0] if rest else "chain"
    args = rest[1:]
    if cmd == "chain":
        return cmd_chain(args, cfg)
    if cmd == "score":
        return cmd_score(args, cfg)
    if cmd == "where":
        return cmd_where(args, cfg)
    if cmd == "trace":
        return cmd_trace(args, cfg)
    raise SystemExit("unknown command %r (chain | score | trace | where)" % cmd)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
