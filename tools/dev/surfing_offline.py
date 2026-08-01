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

    python3 tools/dev/surfing_offline.py route run_002  # the exact route a human ran
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
    zmax = nrot * S.BAND_PITCH
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
            dist, dead, _ = run_group(rt, ov, band, hole_src[i], roof_src[i], lane0, speed, 0, S.BAND_PITCH + 10)
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


def _watch(rt, ai, rows):
    """Hand every planning frame to `rows`, with planRoute's own account of why it chose."""
    def snap():
        st = ai["stat"]
        d, r = st["whyD"], st["whyR"]
        return ("%d/%d/%d" % (d[0], d[1], d[2]), "%d/%d/%d" % (r[0], r[1], r[2]))

    rt.globals()["__SR_SIM"]["watch"] = (
        lambda pz, lane, sp, act, az, reach, roof, j, sl, sw:
        rows.append((pz, lane, sp, act, az, reach, roof, j, sl, sw) + snap()))


def _show_rows(rows, dist, span):
    """The decision stream over the last `span` metres — the frames where something changed.

    A run of identical "hold" decisions says nothing and buries the two frames that matter."""
    def show(row):
        pz, lane, sp, act, az, reach, roof, j, sl, sw, clear, dpreach = row
        print("  z=%7.1f lane=%-6s v=%4.1f act=%-5s in=%3d reach=%3d clear=%-12s "
              "dp=%-12s%s%s%s%s"
              % (pz, LANE_NAME[int(lane)], sp, ACT_NAME[int(act)], az, reach, clear,
                 dpreach, " roof" if roof else "", " air" if j else "",
                 " slide" if sl else "", " switching" if sw else ""))

    last, prev = None, None
    for row in rows:
        if row[0] < dist - span:
            continue
        key = tuple(int(row[i]) for i in (1, 3, 4, 6, 7, 8, 9))
        if key == prev and row[3] == 0:
            last = row
            continue
        if last is not None:
            show(last)
            last = None
        prev = key
        show(row)
    if last is not None:
        show(last)


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
    for lane0 in lanes:
        rows = []
        _watch(rt, ai, rows)
        dist, dead, _ = run_group(rt, ov, band_src[idx], hole_src[idx], roof_src[idx],
                                  lane0, speed, 0, S.BAND_PITCH + 10)
        rt.globals()["__SR_SIM"]["watch"] = None
        head = "start=%-6s dist=%.1f" % (LANE_NAME[lane0], dist)
        print("\n%s  %s" % (head, "survived" if dead is None else describe(dead, names)))
        if dead is None:
            continue
        _show_rows(rows, dist, span)
        print("  --- the track it was reading ---")
        cmd_where([str(dead["obz"]), "-", str(span)], cfg, band=idx)
    return 0


def route_accel(spec: str) -> float:
    """The speed ramp to replay a route at.

    From the recording itself where there is one, so the replay meets each obstacle at the
    speed the human met it; a fixed default would flatter or punish the planner for a reason
    unconnected to the route."""
    path = spec if os.path.exists(spec) else os.path.join(
        S.HUMAN_DIR, spec if spec.endswith(".txt") else spec + ".txt")
    if os.path.exists(path):
        return S.run_accel(path)
    if spec.startswith("pool:"):
        # a drawn route has no recording of its own, so it is run at the ramp the recordings
        # agree on — a nominal 0.0027 would meet every obstacle slower than the game ever does
        return S.run_accel(os.path.join(S.HUMAN_DIR, "run_002.txt"))
    return 0.0027


def resolve_route(spec: str):
    """The band chain a `route` argument names, plus where it came from.

    Either an explicit comma-separated band list, a human recording — a file path, or just
    ``run_002`` for one under results/street_run/human — or ``pool:N[:seed]``, a route of N
    bands DRAWN from the pool the way the game draws one. Returns ``(order, note)``.

    A drawn route is what makes a distance mean anything beyond this one recording. There are
    three recordings, and the planner has been read against them long enough that a good score
    on them says as much about the tuning as about the track; a fresh draw meets the same bands
    in orders nothing has been fitted to."""
    if "," in spec or spec.isdigit():
        return [b for b in spec.split(",") if b], "given on the command line"
    if spec.startswith("pool:"):
        parts = spec.split(":")
        n = int(parts[1])
        seed = int(parts[2]) if len(parts) > 2 else 1161
        return extend_route([], n, seed), "%d bands drawn from the pool (seed %d)" % (n, seed)
    path = spec
    if not os.path.exists(path):
        cand = os.path.join(S.HUMAN_DIR, spec if spec.endswith(".txt") else spec + ".txt")
        if not os.path.exists(cand):
            raise SystemExit("no such recording: %s (nor %s)" % (spec, cand))
        path = cand
    slots = S.band_order_from_run(path)
    named = [s for s in slots if s[1]]
    if not named:
        raise SystemExit("%s names no band at all — is it a Street Run recording?" % path)
    lost = named[0][0] // S.BAND_PITCH
    order = [s[1] for s in slots[lost:]]
    if any(b is None for b in order):
        gaps = [str(slots[lost + i][0]) for i, b in enumerate(order) if b is None]
        raise SystemExit("the recording has a hole at z=%s — no band explains it" % ",".join(gaps))
    note = "%s: %d bands" % (os.path.basename(path), len(order))
    if lost:
        # the frame buffer keeps only the last ~900 samples, so a long run's opening is gone
        note += " (the recording lost the first %d — %d m — to its frame buffer)" % (
            lost, lost * S.BAND_PITCH)
    return order, note


def extend_route(order, extra: int, seed: int = 1161):
    """Carry a recovered route on past its end with more bands from the same pool.

    The game draws each band from the pool it has; the recovered routes show it drawing with
    replacement and with no bar on drawing the same band twice running (run_002 has 313 313
    and 2006 2006 back to back). So the extension is a seeded draw from the pool, weighted by
    how often each band turned up across the recordings — which keeps the mix of band types
    the same rather than inventing an even one. Seeded, so an extended route is reproducible."""
    import glob
    import random
    weights: dict = {}
    for path in sorted(glob.glob(os.path.join(S.HUMAN_DIR, "run_*.txt"))):
        for _, band, _, _ in S.band_order_from_run(path):
            if band:
                weights[band] = weights.get(band, 0) + 1
    for band in order:
        weights.setdefault(band, 1)
    pool = sorted(weights)
    rng = random.Random(seed)
    return list(order) + rng.choices(pool, weights=[weights[b] for b in pool], k=extra)


def cmd_route(argv, cfg):
    """Replay the EXACT band chain a recorded human run went through.

    `chain` scans rotations of the whole pool in id order — useful for exercising seams, but
    it is not a track the game ever laid down. This replays a real one, at the speed ramp the
    human actually ran it at, so "would the autopilot have survived that 12.7 km run" is a
    question with an answer.

        route run_002                  # the recovered route, every start lane
        route run_002 1                # ... starting centre
        route run_002 1 extend=40      # ... carried on with 40 more bands from the pool
        route run_002 1 trace          # ... and print the decisions leading into the death
        route 2007,2003,315 1          # an explicit chain
    """
    if not argv:
        raise SystemExit("usage: route <recording|band,band,...> [start-lane] "
                         "[extend=N] [accel=A] [trace [span]]")
    order, note = resolve_route(argv[0])
    rest = argv[1:]
    lanes = [int(rest[0])] if rest and rest[0].lstrip("-").isdigit() else [0, 1, 2]
    extra, accel, seed = 0, None, 1161
    trace, span = "trace" in rest, 60.0
    for a in rest:
        if a.startswith("extend="):
            extra = int(a.split("=", 1)[1])
        elif a.startswith("accel="):
            accel = float(a.split("=", 1)[1])
        elif a.startswith("seed="):
            seed = int(a.split("=", 1)[1])
        elif a.startswith("span="):
            span = float(a.split("=", 1)[1])
    if accel is None:
        accel = route_accel(argv[0])
    if extra:
        order = extend_route(order, extra, seed)
        note += " + %d more from the pool (seed %d)" % (extra, seed)
    zmax = len(order) * S.BAND_PITCH
    print("route %s" % note)
    print("  %s" % " ".join(order))
    print("  %d m of track, speed 30 -> %.0f (accel %.5f)"
          % (zmax, min(30 + accel * zmax, 60), accel))
    rt, ai = new_vm(cfg)
    ov, band, hole, roof, _, names = S.build_field(accel=accel, order=order)
    worst = None
    for lane0 in lanes:
        rows = []
        if trace:
            _watch(rt, ai, rows)
        dist, dead, moves = run_group(rt, ov, band[0], hole[0], roof[0],
                                      lane0, 30, accel, zmax)
        rt.globals()["__SR_SIM"]["watch"] = None
        if dead is None:
            print("ok  start=%-6s dist=%6.0f of %d m  (%d moves)" % (
                LANE_NAME[lane0], dist, zmax, moves))
        else:
            slot = int(dist // S.BAND_PITCH)
            print("DIE start=%-6s dist=%6.0f of %d m  band %d (%s)  %s" % (
                LANE_NAME[lane0], dist, zmax, slot, order[min(slot, len(order) - 1)],
                describe(dead, names)))
            if trace:
                _show_rows(rows, dist, span)
                print("  --- the track it was reading ---")
                cmd_where([str(dead["obz"]), "-", str(span)], cfg, route=order)
        if worst is None or dist < worst:
            worst = dist
    print("ROUTE worst dist=%.0f of %d m" % (worst, zmax))
    return 0 if worst >= zmax else 1


def route_rows(order):
    """The chained obstacle field of a route as plain rows, plus the kind and name tables."""
    born, mon = S.load_config()
    kinds = {int(k): S.classify(v, S.load_bounds()) for k, v in mon.items()}
    per_band = S.bands(born, mon)
    rows, off = [], 0
    for band in order:
        for x, z, mid in per_band[band]:
            S.kind_for(kinds, mid)
            rows.append((x, z + off, mid))
        off += S.BAND_PITCH
    names = {int(k): (v.get("asset") or "").split("/")[-1].replace(".prefab", "")
             for k, v in mon.items()}
    return rows, kinds, names


class Track:
    """The judge's collision rules over one route, as a steppable machine.

    This exists to answer a question the planner cannot be asked: *is this route survivable at
    all?* A planner that dies at 356 m is either a bad planner or a route with no way through,
    and until those two are told apart, tuning is guessing. So the rules of
    ``surfing_sim.lua`` are restated here — and only here, for a SEARCH, never for a verdict:
    every path this finds is handed back to the real Lua judge to be confirmed (see
    ``cmd_feasible``), so a mistake in this restatement shows up as a path the judge rejects
    rather than as a false all-clear."""

    DT = 1 / 60.0
    SWITCH, JUMP, SLIDE = 0.16, 0.72, 0.50
    CAP = 60.0
    TRIGGER = 120.0    # SIM.moverTrigger — where a parked truck sets off

    def __init__(self, order, speed0=30.0, accel=0.0027, pad=0.0):
        rows, kinds, names = route_rows(order)
        # Clearance demanded of every body, at both ends. At 0 this is the judge's own
        # geometry and the ceiling it yields is the most anything could ever reach. Above 0 it
        # asks a different and more useful question: how far is the route passable if you
        # insist on running no closer than `pad` to anything? The planner runs at
        # cfg.padExtra = 1.5, so its distance can only be read against the ceiling at the
        # SAME clearance — measured against the pad-0 ceiling it is charged for refusing
        # manoeuvres whose whole margin is thinner than its own safety pad.
        #
        # It is NOT applied to a carriage that carries a roof. Keeping clear of a body is the
        # point of a clearance; a roof is a body the runner is meant to be standing on, and
        # padding it puts a phantom wall at the far end of every ride — the runner steps off
        # the roof at the body's true end and straight into the pad. That artefact produced a
        # blame verdict of its own before it was caught: "the run lost it at 125 m by not
        # hopping", 4.7 km before anything touched it.
        self.pad = pad
        self.names = names
        self.zmax = len(order) * S.BAND_PITCH
        # the same speed-derived roof reach the judge uses, so the ceiling and the replay
        # cannot disagree about which carriages chain
        holes, roofs = S.roof_holes(rows, kinds,
                                    speed_at=S.speed_profile(speed0, accel, self.CAP))
        self.holes, self.roofs = holes, roofs
        lane_of = (lambda x: min(range(3), key=lambda i: abs(x - (32 + 4 * i))))
        self.static, self.moving, self.fly = [], [], []
        for x, z, mid in rows:
            k = kinds[mid]
            if k.get("fly"):
                self.fly.append((lane_of(x), z, k["fly"]))
            if not k.get("solid"):
                continue
            back, front, ln = k.get("back", 0.0), k.get("front", 0.0), lane_of(x)
            ridden = any(r[0] == ln and r[1] <= z - back + 0.01 and z + front <= r[2] + 0.01
                         for r in roofs)
            p = 0.0 if ridden else pad
            rec = (ln, z, back + p, front + p,
                   k.get("lanes", 1),
                   bool(k.get("jump")), bool(k.get("slide")), bool(k.get("sideOnly")),
                   k.get("speed", 0.0), mid)
            (self.moving if k.get("speed") else self.static).append(rec)
        self.static.sort(key=lambda r: r[1] - r[2])
        self.speed0, self.accel = speed0, accel
        # pz and the clock depend only on the frame number — the avatar's speed is a function
        # of distance alone — so the whole timeline can be laid out once and shared by every
        # branch of the search. Indexed as the judge counts: its first pass is frame 1, at z=0.
        self.pz = [0.0, 0.0]
        while self.pz[-1] < self.zmax:
            p = self.pz[-1]
            self.pz.append(p + min(speed0 + p * accel, self.CAP) * self.DT)
        self.nframes = len(self.pz) - 2
        # A mover's clock starts when the RUNNER reaches it, and the runner's position is a
        # function of the frame alone — so every mover's set-off moment is fixed in advance and
        # does not vary between branches of the search.
        import bisect
        started = []
        for rec in self.moving:
            want = rec[1] - self.TRIGGER
            f = bisect.bisect_left(self.pz, want, 1)
            started.append(rec + (f * self.DT,))
        self.moving = started

    def roof_at(self, z, lane):
        for r in self.roofs:
            if r[0] == lane and r[1] <= z <= r[2]:
                return r
        return None

    def on_roof(self, z, lane):
        return self.roof_at(z, lane) is not None

    def _hits(self, frame, lane, held, level, switching, jumping, sliding, flying):
        """Did the avatar die crossing frame `frame`? Mirrors SIM.once's collision block."""
        z0, z1 = self.pz[frame], self.pz[frame + 1]
        # `level` is whether the runner is UP on the roofs — carried as state by `step`, not
        # asked of the current z, because a roof is mounted and not merely stood under
        if not flying and not level:
            t = frame * self.DT
            for ol, oz, back, front, lanes, jmp, sld, side, speed, mid in self.static:
                if oz - back >= z1:
                    break
                if oz + front <= z0:
                    continue
                hit = True if lanes >= 3 else (ol == held)
                if side and not switching:
                    hit = False
                if hit and not (jumping and jmp) and not (sliding and sld):
                    return mid
            for ol, oz, back, front, lanes, jmp, sld, side, speed, mid, t0 in self.moving:
                # parked on its spawn mark until the runner closed in, then oncoming
                z = oz if t < t0 else oz - speed * (t - t0)
                if z - back >= z1 or z + front <= z0:
                    continue
                hit = True if lanes >= 3 else (ol == held)
                if side and not switching:
                    hit = False
                if hit and not (jumping and jmp) and not (sliding and sld):
                    return mid
        if not jumping and not flying:
            for hl, h0, h1 in self.holes:
                if hl == lane and z1 > h0 and z0 < h1:
                    return -1
        return None

    def picks_up(self, frame, lane):
        """Seconds of flight collected crossing this frame, or 0."""
        z0, z1 = self.pz[frame], self.pz[frame + 1]
        for fl, fz, secs in self.fly:
            if fl == lane and z0 <= fz < z1:
                return secs
        return 0.0

    def start(self, lane0: int):
        """The state a run begins in: ``(frame, lane, up on the roofs, flight ends at)``."""
        return (1, lane0, self.on_roof(0.0, lane0), 0)

    def step(self, frame, lane, level, act, fly_until=0):
        """Take `act` at a decision frame and run on to the next one.

        `level` is whether the runner is up on the roofs — part of the state, because a roof is
        MOUNTED (head-on up a ramp, or landed on from a hop off another roof) and not merely
        stood under; `fly_until` is the frame the aeroplane buff wears off at. Returns the next
        decision point as ``(frame, lane, level, fly_until)``, or None if it died on the way."""
        sw_from = sw_to = lane
        sw_t = jt = sl_t = 0.0
        air_roof = False
        if act == 1 and lane > 0:
            sw_t, sw_from, sw_to, lane = self.SWITCH, lane, lane - 1, lane - 1
        elif act == 2 and lane < 2:
            sw_t, sw_from, sw_to, lane = self.SWITCH, lane, lane + 1, lane + 1
        elif act == 3:
            jt = self.JUMP
        elif act == 4:
            sl_t = self.SLIDE
        # `level` arrives as it stood at the PREVIOUS frame; the judge recomputes it at the top
        # of every frame and only then reads it into `airRoof`, so a hop taken here must be
        # charged with this frame's level, not the last one's
        took_off = act == 3
        prev_z, prev_held = self.pz[frame - 1], sw_from
        while frame <= self.nframes:
            secs = self.picks_up(frame, lane)
            if secs:
                fly_until = frame + int(secs / self.DT)
            # the judge hands the runner over at the midpoint of a change, not at its end
            held = sw_from if sw_t > self.SWITCH * 0.5 else sw_to
            z = self.pz[frame]
            over = self.roof_at(z, held)
            if frame < fly_until:
                level = False
            elif jt > 0 and air_roof:
                level = True
            elif over is None:
                level = False
            elif not level:
                # up off the road only by crossing the near end of a MOUNTABLE span (a ramp),
                # and without changing lane to do it — a step into a roofed lane off the road
                # goes into the carriage's flank, which is what `sideOnly` is for
                level = (prev_held == held and over[3] == 1
                         and not self.on_roof(prev_z, held))
            if took_off:
                air_roof, took_off = level, False
            if self._hits(frame, lane, held, level, sw_t > 0, jt > 0, sl_t > 0,
                          frame < fly_until) is not None:
                return None
            if sw_t > 0:
                sw_t -= self.DT
            if jt > 0:
                jt -= self.DT
            if sl_t > 0:
                sl_t -= self.DT
            prev_z, prev_held = z, held
            frame += 1
            # the judge only plans on odd frames, and only when nothing is in flight
            if sw_t <= 0 and jt <= 0 and sl_t <= 0 and frame % 2 == 1:
                return frame, lane, level, fly_until
        return frame, lane, level, fly_until


def cmd_feasible(argv, cfg):
    """Is there ANY way through this route — and if so, hand it to the judge to prove it.

    A search over the same rules the judge applies, from every start lane. Its answer is the
    thing that makes a planner's distance mean something: 356 m out of 11880 is a planner
    failure only if the other 11524 were there to be run.

        feasible run_002
        feasible run_002 1
        feasible run_002 1 pad=1.5    # ... insisting on 1.5 m of clearance, as the planner does
        feasible run_002 1 from=23    # ... the tail only, entered at the speed the run had there
    """
    if not argv:
        raise SystemExit("usage: feasible <recording|band,band,...> [start-lane] "
                         "[accel=A] [pad=P] [from=N]")
    order, note = resolve_route(argv[0])
    rest = argv[1:]
    lanes = [int(rest[0])] if rest and rest[0].lstrip("-").isdigit() else [0, 1, 2]
    accel = route_accel(argv[0])
    pad, skip, extra, seed = 0.0, 0, 0, 1161
    for a in rest:
        if a.startswith("accel="):
            accel = float(a.split("=", 1)[1])
        elif a.startswith("pad="):
            pad = float(a.split("=", 1)[1])
        elif a.startswith("from="):
            skip = int(a.split("=", 1)[1])
        elif a.startswith("extend="):
            extra = int(a.split("=", 1)[1])
        elif a.startswith("seed="):
            seed = int(a.split("=", 1)[1])
    if extra:
        order = extend_route(order, extra, seed)
        note += " + %d more from the pool (seed %d)" % (extra, seed)
    # Starting part-way along asks "is the REST of the route hairline too, or only this one
    # spot" — which a run from z=0 can never answer, because it never gets there. The entry
    # speed is the speed the run actually carries into that band, so the tail is stepped at
    # the pace it is really met at rather than from a standing 30.
    speed0 = 30.0
    if skip:
        speed0 = min(30.0 + accel * skip * S.BAND_PITCH, Track.CAP)
        order = order[skip:]
        note += ", from band %d (entered at %.0f u/s)" % (skip, speed0)
    tr = Track(order, speed0, accel, pad)
    print("feasible %s" % note)
    print("  %d m, %d frames, accel %.5f, clearance demanded %.2f m" %
          (tr.zmax, tr.nframes, accel, pad))
    rt, _ = new_vm(cfg)
    ov, band, hole, roof, _, names = S.build_field(accel=accel, order=order, speed0=speed0)
    worst = 0.0
    for lane0 in lanes:
        path = _search(tr, lane0)
        if path is None:
            reached = _furthest(tr, lane0)
            print("NO   start=%-6s no way through — the search dies by %.0f m of %d"
                  % (LANE_NAME[lane0], reached, tr.zmax))
            _explain_wall(tr, reached)
            worst = max(worst, reached)
            continue
        dist, dead = _replay_moves(rt, ov, band[0], hole[0], roof[0], lane0, accel,
                                   tr.zmax, path, tr, speed0)
        verdict = ("the judge agrees" if dead is None else
                   "BUT the judge kills it at %.0f — %s" % (dist, describe(dead, names)))
        print("yes  start=%-6s a %d-move path clears all %d m; %s"
              % (LANE_NAME[lane0], sum(1 for a in path.values() if a), tr.zmax, verdict))
        if dead is not None:
            return 1
    return 0


def _explain_wall(tr: Track, at: float, frame: int | None = None, span: float = 40.0,
                  pad: str = "       "):
    """What is standing at the point nothing gets past, and what could have carried the run
    over it. A bare "no way through" is not actionable; the bodies and the pickups are.

    Movers are printed where they ARE at that frame, not where they spawned. That distinction
    is the whole of a truck stream: `where` lays out spawn marks, and by the time the runner
    arrives an oncoming truck is tens of metres from its own — reading the spawn row as the
    cross-section under the runner is the misreading that cost this task a session."""
    if frame is None:
        frame = min(range(1, tr.nframes), key=lambda f: abs(tr.pz[f] - at))
    t = frame * tr.DT
    for ol, oz, back, front, lanes, jmp, sld, side, sp, mid in tr.static:
        if oz + front >= at - span and oz - back <= at + span:
            print("%sstanding  body=[%.1f,%.1f] lane=%-6s %s"
                  % (pad, oz - back, oz + front, LANE_NAME[ol], tr.names.get(mid, mid)))
    for ol, oz, back, front, lanes, jmp, sld, side, sp, mid, t0 in tr.moving:
        z = oz if t < t0 else oz - sp * (t - t0)
        if z + front >= at - span and z - back <= at + span:
            print("%soncoming  body=[%.1f,%.1f] lane=%-6s %s (%g u/s, spawned at %.0f%s)"
                  % (pad, z - back, z + front, LANE_NAME[ol], tr.names.get(mid, mid), sp, oz,
                     "" if t >= t0 else ", still parked"))
    for hl, h0, h1 in tr.holes:
        if h1 >= at - span and h0 <= at + span:
            print("%sSEAM      %.1f..%.1f lane=%s" % (pad, h0, h1, LANE_NAME[hl]))
    for rl, r0, r1, _mount in tr.roofs:
        if r1 >= at - span and r0 <= at + span:
            print("%sROOF      %.1f..%.1f lane=%s" % (pad, r0, r1, LANE_NAME[rl]))
    ahead = [f for f in tr.fly if at - 400 <= f[1] <= at]
    print("%saeroplanes on the %.0f m before it: %d" % (pad, min(at, 400.0), len(ahead)))


def _search(tr: Track, lane0: int):
    """A surviving action schedule, as ``{decision frame: action}`` — or None if there is none.

    Depth-first with a dead-end set: at a decision point every timer is zero, so the state is
    just ``(frame, lane)`` and a point that has failed once can never succeed."""
    dead_ends = set()
    stack = [tr.start(lane0) + (iter((0, 1, 2, 3, 4)),)]
    chosen: dict = {}
    while stack:
        frame, lane, level, fly, opts = stack[-1]
        nxt = next(opts, None)
        if nxt is None:
            dead_ends.add((frame, lane, level, fly))
            chosen.pop(frame, None)
            stack.pop()
            continue
        res = tr.step(frame, lane, level, nxt, fly)
        if res is None:
            continue
        if res in dead_ends:
            continue
        chosen[frame] = nxt
        if res[0] >= tr.nframes:
            return dict(chosen)
        stack.append(res + (iter((0, 1, 2, 3, 4)),))
    return None


def _alive(tr: Track, state, dead_ends: set, wins: set) -> bool:
    """Can anything at all reach the end of the route from `state`?

    The same depth-first walk as ``_search``, but asked of an arbitrary state and answered
    both ways: a state that failed can never succeed (``dead_ends``), and every state on a
    surviving path can (``wins``). Both caches are shared across queries, so asking it once
    per decision frame along a whole run costs about what one ``feasible`` costs."""
    if state[0] >= tr.nframes or state in wins:
        return True
    if state in dead_ends:
        return False
    stack = [(state, iter((0, 1, 2, 3, 4)))]
    while stack:
        st, opts = stack[-1]
        nxt = next(opts, None)
        if nxt is None:
            dead_ends.add(st)
            stack.pop()
            continue
        res = tr.step(st[0], st[1], st[2], nxt, st[3])
        if res is None or res in dead_ends:
            continue
        if res[0] >= tr.nframes or res in wins:
            for s, _ in stack:
                wins.add(s)
            wins.add(res)
            return True
        stack.append((res, iter((0, 1, 2, 3, 4))))
    return False


def _furthest(tr: Track, lane0: int) -> float:
    """How far anything gets when nothing gets through — where the route walls up."""
    return _furthest_from(tr, tr.start(lane0))


def _furthest_from(tr: Track, state) -> float:
    """The same, from an arbitrary state: how far a branch runs before it walls up.

    A blamed move is more legible with the distance beside it — "left walls up at 4853, hold
    runs the lot" says at a glance whether the mistake was a step into a short dead end or a
    step off the one line that goes."""
    dead_ends = set()
    best = 0.0
    stack = [state + (iter((0, 1, 2, 3, 4)),)]
    while stack:
        frame, lane, level, fly, opts = stack[-1]
        best = max(best, tr.pz[min(frame, tr.nframes)])
        nxt = next(opts, None)
        if nxt is None:
            dead_ends.add((frame, lane, level, fly))
            stack.pop()
            continue
        res = tr.step(frame, lane, level, nxt, fly)
        if res is None or res in dead_ends:
            continue
        stack.append(res + (iter((0, 1, 2, 3, 4)),))
    return best


def _replay_moves(rt, ov, band, hole, roof, lane0, accel, zmax, path, tr, speed0=30.0):
    """Push a fixed schedule of moves through the REAL Lua judge.

    The planner is swapped for one that reads the schedule, so the verdict on a searched path
    comes from ``surfing_sim.lua`` itself rather than from the search's own arithmetic.

    Keyed by DISTANCE, not by call count. The judge plans on odd frames but skips a call
    entirely while a change, hop or duck is in flight, so its Nth call is not its (2N-1)th
    frame — counting calls slid the whole schedule the moment the route made its first move,
    and the replay then died metres in on a fence it had been told to duck 40 m earlier.
    Distance is exact instead: both sides step `pz` with the same recurrence from the same
    start, so the values match to the bit."""
    rt.execute("__SR_PATH = {} __SR_IDX = 1")
    tbl = rt.globals()["__SR_PATH"]
    for i, frame in enumerate(sorted(f for f, a in path.items() if a), 1):
        tbl[i] = rt.eval("function(z, a) return {z = z, a = a} end")(tr.pz[frame], path[frame])
    rt.execute("""
    __SR_REAL_PLAN = __SR_REAL_PLAN or __SR_AI.planRoute
    __SR_AI.planRoute = function(pz, lane, speed, obs, flying, onRoof)
      local e = __SR_PATH[__SR_IDX]
      if e and pz >= e.z - 0.001 then
        __SR_IDX = __SR_IDX + 1
        return 0, e.a, 0
      end
      return 0, 0, 0
    end
    """)
    try:
        return run_group(rt, ov, band, hole, roof, lane0, speed0, accel, zmax)[:2]
    finally:
        rt.execute("__SR_AI.planRoute = __SR_REAL_PLAN")


ALIVE_ACT = {0: "hold", 1: "left", 2: "right", 3: "JUMP", 4: "SLIDE"}


def cmd_blame(argv, cfg):
    """The ONE decision that lost the run — not the obstacle that collected the body.

    ``route`` says where the planner died and ``feasible`` says the route was passable; between
    them sits the question neither answers: at which frame did the planner's own line stop
    being winnable? A death at 7390 m is usually the bill for a lane held 100 m earlier, and
    the obstacle that finally hit is the least informative thing about it.

    So the planner's line is walked forward, and at every decision point the exhaustive search
    is asked whether the end is still reachable *from here*. The first move after which the
    answer turns from yes to no is the mistake, and the moves that would have kept the run
    alive are printed beside it.

        blame run_002 1
        blame run_002 1 pad=1.5      # ... judged at the clearance the planner runs with
        blame run_002 1 extend=40    # ... on the route carried on with fresh bands
    """
    if not argv:
        raise SystemExit("usage: blame <recording|band,band,...> [start-lane] "
                         "[span=N] [pad=P] [extend=N] [seed=S]")
    order, note = resolve_route(argv[0])
    rest = argv[1:]
    lanes = [int(rest[0])] if rest and rest[0].lstrip("-").isdigit() else [0, 1, 2]
    accel = route_accel(argv[0])
    span, pad, extra, seed = 60.0, 0.0, 0, 1161
    for a in rest:
        if a.startswith("accel="):
            accel = float(a.split("=", 1)[1])
        elif a.startswith("span="):
            span = float(a.split("=", 1)[1])
        elif a.startswith("pad="):
            pad = float(a.split("=", 1)[1])
        elif a.startswith("extend="):
            extra = int(a.split("=", 1)[1])
        elif a.startswith("seed="):
            seed = int(a.split("=", 1)[1])
    if extra:
        order = extend_route(order, extra, seed)
        note += " + %d more from the pool (seed %d)" % (extra, seed)
    # The clearance the blame is judged at. At 0 a run is blamed for declining a manoeuvre
    # whose whole margin is centimetres, which is not a planner fault but a coin toss; at the
    # planner's own cfg.padExtra the verdict is one it could have acted on.
    tr = Track(order, 30.0, accel, pad)
    rt, ai = new_vm(cfg)
    ov, band, hole, roof, _, names = S.build_field(accel=accel, order=order)
    print("blame %s" % note)
    print("  %d m, %d frames, accel %.5f, clearance demanded %.2f m"
          % (tr.zmax, tr.nframes, accel, pad))
    dead_ends, wins = set(), set()
    rc = 0
    for lane0 in lanes:
        rows = []
        _watch(rt, ai, rows)
        dist, dead, _ = run_group(rt, ov, band[0], hole[0], roof[0], lane0, 30, accel, tr.zmax)
        rt.globals()["__SR_SIM"]["watch"] = None
        # the schedule the planner actually issued, keyed by distance — the judge plans on odd
        # frames but skips the call outright while a move is in flight, so a call index is not
        # a frame index (see _replay_moves)
        sched = {}
        for r in rows:
            sched[round(float(r[0]), 5)] = (int(r[3]) if int(r[4]) == 0 else 0, r)
        state = tr.start(lane0)
        if not _alive(tr, state, dead_ends, wins):
            print("  start=%-6s the route has no way through from this lane at all" % LANE_NAME[lane0])
            continue
        seen = []
        while state[0] < tr.nframes:
            ent = sched.get(round(tr.pz[state[0]], 5))
            act = ent[0] if ent else 0
            seen.append((state, act, ent[1] if ent else None))
            nxt = tr.step(state[0], state[1], state[2], act, state[3])
            if nxt is not None and _alive(tr, nxt, dead_ends, wins):
                state = nxt
                continue
            good, reach = [], []
            for alt in (0, 1, 2, 3, 4):
                res = tr.step(state[0], state[1], state[2], alt, state[3])
                if res is None:
                    reach.append("%s dies here" % ALIVE_ACT[alt])
                    continue
                if _alive(tr, res, dead_ends, wins):
                    good.append(alt)
                    reach.append("%s runs the lot" % ALIVE_ACT[alt])
                else:
                    reach.append("%s walls up at %.0f"
                                 % (ALIVE_ACT[alt], _furthest_from(tr, res)))
            z = tr.pz[state[0]]
            print("\n  start=%-6s LOST IT at z=%.1f in lane %s, %.0f m before the body hit at %.0f"
                  % (LANE_NAME[lane0], z, LANE_NAME[state[1]], dist - z, dist))
            print("      it chose      : %s" % ALIVE_ACT[act])
            print("      still winnable: %s" % (", ".join(ALIVE_ACT[a] for a in good) or "nothing"))
            print("      every move    : %s" % "; ".join(reach))
            if ent is not None:
                r = ent[1]
                print("      it believed   : reach=%d  first solid=%s  dp reaches=%s"
                      % (int(r[5]), r[10], r[11]))
            print("      --- the decisions leading in ---")
            _show_rows([s[2] for s in seen if s[2] is not None], z, span)
            print("      --- the field AT that frame (movers where they are, not where they "
                  "spawned) ---")
            _explain_wall(tr, z, state[0], span, pad="      ")
            rc = 1
            break
        else:
            print("  start=%-6s never left a winnable state — it ran the whole %d m"
                  % (LANE_NAME[lane0], tr.zmax))
        if dead is not None and state[0] >= tr.nframes:
            print("  (the judge still killed it at %.0f — the search model and the judge "
                  "disagree here)" % dist)
    return rc


def cmd_human(argv, cfg):
    """Hold the track model up against the one ground truth there is: a run that SURVIVED.

    The replay's verdict is only worth as much as its model of the ground, and a model can
    only be checked against something outside itself. A human recording is exactly that — a
    12.7 km path a person actually walked, position by position. So: lay the model's obstacle
    field over that path and ask where it claims the person was inside a wall, or on thin air
    while the recording has them riding a roof. Every hit is a place the model is wrong, or a
    place the person jumped or slid (which the recording cannot show, so hoppable and
    slideable pieces are reported apart from the ones nothing can save you from).

        human run_002
    """
    if not argv:
        raise SystemExit("usage: human <recording> [span]")
    order, note = resolve_route(argv[0])
    path = argv[0] if os.path.exists(argv[0]) else os.path.join(
        S.HUMAN_DIR, argv[0] if argv[0].endswith(".txt") else argv[0] + ".txt")
    slots = S.band_order_from_run(path)
    off0 = next(s[0] for s in slots if s[1])
    rows, kinds, names = route_rows(order)
    # judge the roof model at the speed the recording actually ran, not at a nominal 30
    holes, roofs = S.roof_holes(rows, kinds,
                                speed_at=S.speed_profile(30.0, S.run_accel(path)))
    print("human %s" % note)

    def lane_of(x):
        return min(range(3), key=lambda i: abs(x - (32 + 4 * i)))

    # A driving truck's template z is only where it SPAWNED — by the time the run reached it,
    # it had moved. Nothing about it can be checked against a recorded position, so it is left
    # out rather than counted as a model error. A ramp is left out too: it is ridden head-on,
    # and the recording has the run doing exactly that.
    solid = [(lane_of(x), z - kinds[mid].get("back", 0), z + kinds[mid].get("front", 0), mid)
             for x, z, mid in rows
             if kinds[mid].get("solid") and not kinds[mid].get("speed")
             and not kinds[mid].get("sideOnly")]
    frames = []
    with open(path, "r", encoding="utf-8") as fh:
        for ln in fh:
            p = ln.rstrip("\n").split("|")
            if len(p) < 8:
                continue
            frames.append((float(p[0]) - off0, int(p[1]), float(p[6].split(",")[0])))
    car_body = [(lane_of(x), z - kinds[mid].get("back", 0), z + kinds[mid].get("front", 0))
                for x, z, mid in rows if kinds[mid].get("carriage")]
    hard, soft, roof_miss, seam_hit = [], [], [], []
    for i in range(len(frames) - 1):
        z0, lane, y = frames[i]
        z1, lane1, _ = frames[i + 1]
        if z0 < 0:
            continue
        # Three heights, and conflating them is how this check misled a whole session. y≈20 is
        # FLIGHT (the aeroplane buff) — immune to everything, so it says nothing about roofs.
        # A carriage roof sits at y≈4: bounds.json puts the body top at y0 3.53 + sy 0.76.
        # Anything else off the ground is a hop, mid-arc.
        if y >= 15.0:
            continue
        if 3.0 <= y <= 8.0:
            if any(b0 <= z0 <= b1 for l_, b0, b1 in car_body if l_ == lane):
                if not any(r[0] == lane and r[1] <= z0 <= r[2] for r in roofs):
                    roof_miss.append((z0, lane))
            continue
        if y > 1.0 or lane != lane1:   # airborne, or mid-change: the lane it swept is not known
            continue
        for ln_, b0, b1, mid in solid:
            if ln_ != lane or b1 <= z0 or b0 >= z1:
                continue
            k = kinds[mid]
            (soft if (k.get("jump") or k.get("slide")) else hard).append((z0, lane, mid))
        for hl, h0, h1 in holes:
            if hl == lane and h1 > z0 and h0 < z1:
                seam_hit.append((z0, lane))
    total = len(frames)
    print("  %d frames, %.0f m of path" % (total, frames[-1][0] - max(frames[0][0], 0)))
    print("  model says WALL where the run went on (nothing survives these): %d" % len(hard))
    for z, lane, mid in hard[:20]:
        print("    z=%7.0f lane=%-6s %s" % (z + off0, LANE_NAME[lane], names.get(mid, mid)))
    print("  model says hoppable/slideable in the way (the run may well have hopped it): %d"
          % len(soft))
    on_car = sum(1 for z, lane, y in frames if 3.0 <= y <= 8.0
                 and any(b0 <= z <= b1 for l_, b0, b1 in car_body if l_ == lane))
    print("  model gives no roof where the run was riding a carriage (y≈4): %d of %d such frames"
          % (len(roof_miss), on_car))
    for z, lane in roof_miss[:20]:
        print("    z=%7.0f lane=%s" % (z + off0, LANE_NAME[lane]))
    print("  model puts a roof seam under the run while it was on the ground: %d" % len(seam_hit))
    return 0 if not hard and not roof_miss else 1


def score_local(cfg=None, lane0: int = 1, speed: int = 30):
    """The isolated per-band score as one number, for callers rather than the console.

    Same signature-in-spirit as ``surfing_simulate.score``: ``(passed, total, distance)``,
    so the between-attempt learner can judge a proposed tuning without the game."""
    rt, _ = new_vm(cfg or {})
    ov, band_src, hole_src, roof_src, _, _ = build_field_cached()
    passed, dist = 0, 0.0
    for i, band in enumerate(band_src):
        d, dead, _ = run_group(rt, ov, band, hole_src[i], roof_src[i], lane0, speed, 0, S.BAND_PITCH + 10)
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


def cmd_where(argv, cfg, band=None, route=None):
    """What the track actually holds around a distance — the context a death report lacks.

    `band=` restricts it to one band on its own (the isolated replay); `route=` lays out an
    explicit band chain (a recovered human route); otherwise the chained track at rotation
    `rot` is laid out, which is where the band seams live."""
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
    if route is not None:
        order = list(route)
    elif band is not None:
        order = [order[band]]
    else:
        order = order[rot % len(order):] + order[:rot % len(order)]
    rows, off = [], 0
    for band in order:
        for x, z, mid in per_band[band]:
            rows.append((x, z + off, mid, band))
        off += S.BAND_PITCH
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
    for lane, z0, z1, _mount in roofs:
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
    if cmd == "route":
        return cmd_route(args, cfg)
    if cmd == "human":
        return cmd_human(args, cfg)
    if cmd == "feasible":
        return cmd_feasible(args, cfg)
    if cmd == "blame":
        return cmd_blame(args, cfg)
    raise SystemExit(
        "unknown command %r (blame | chain | feasible | human | route | score | trace | where)"
        % cmd)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
