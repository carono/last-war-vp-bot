#!/usr/bin/env python3
r"""Street Run («Уличный забег» / Surfing) autopilot driver — v2, in-VM.

The dodge itself lives in ``tools/lib/surfing_ai.lua`` and runs inside the game's Lua VM,
one decision per frame with zero input latency (see that file for why). This script only:

  * **installs** the autopilot (compiling it through ``load()`` so syntax/runtime errors
    come back instead of being swallowed by ``SafeDoString``);
  * **starts attempts**, watches the telemetry the autopilot leaves in ``_G.__SR_AI.stat``,
    revives, dismisses the result popup, and logs how far each attempt got;
  * keeps a **reserve** of attempts for the person playing.

No window focus, no key presses, no screenshots — the runner is driven by the same calls
the game's own input handler makes.

    C:\Python312\python.exe tools\street_run_ai.py install
    C:\Python312\python.exe tools\street_run_ai.py status
    C:\Python312\python.exe tools\street_run_ai.py run [reserve] [revives]
    C:\Python312\python.exe tools\street_run_ai.py stats      # what the deaths say so far
    C:\Python312\python.exe tools\street_run_ai.py learn      # re-derive the record from the log
    C:\Python312\python.exe tools\street_run_ai.py off        # disable the autopilot

`run` loops over attempts until only `reserve` are left, and between them it LEARNS: each
death is classified against the obstacle field frozen at that instant, folded into
`results/street_run/deaths.json`, and any tuning that record implies is scored offline
against the real track before it is allowed near the next attempt. The number of attempts
a day is the game's, not ours — about 30 — so an attempt that teaches nothing is the one
resource actually worth protecting.
"""
from __future__ import annotations

import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))

sys.path.insert(0, os.path.join(_HERE, "dev"))

import surfing_simulate  # noqa: E402
import surfing_stats  # noqa: E402
from lua_client import get_evaluator  # noqa: E402

MARK = "SRAI "
AI_LUA = os.path.join(_HERE, "lib", "surfing_ai.lua")
RESULT_DIR = os.path.join("results", "street_run")


def _lines(ev, chunk, settle=0.6):
    return [ln.split(MARK, 1)[-1].rstrip()
            for ln in ev.run(chunk, marker=MARK, settle=settle) if MARK in ln]


def _kv(lines):
    out = {}
    for ln in lines:
        if ln.startswith("ST ") and "=" in ln:
            for part in ln[3:].split(" "):
                if "=" in part:
                    k, v = part.split("=", 1)
                    out[k] = v
    return out


def install(ev) -> bool:
    """Compile + run the autopilot source in the VM. ``SafeDoString`` swallows errors, so
    the source is passed through ``load()`` and the compile/runtime error is logged back."""
    with open(AI_LUA, "r", encoding="utf-8") as fh:
        src = fh.read()
    if "]==]" in src:
        raise RuntimeError("surfing_ai.lua contains the long-bracket terminator ]==]")
    chunk = (
        'local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end\n'
        "local src = [==[\n" + src + "\n]==]\n"
        'local f, err = load(src, "surfing_ai")\n'
        'if not f then L("compile-error: " .. tostring(err)) return end\n'
        "local ok, err2 = pcall(f)\n"
        'if not ok then L("runtime-error: " .. tostring(err2)) end\n'
    )
    out = _lines(ev, chunk, settle=1.0)
    for ln in out:
        print("  " + ln)
    return not any("error" in ln for ln in out)


_STATUS = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
local AI = _G.__SR_AI
if not AI then L("ST installed=0") return end
local s = AI.stat or {}
L(string.format("ST installed=1 enabled=%s state=%s z=%.1f maxz=%.1f lane=%s act=%s reach=%s obs=%s frames=%s moves=%s dead=%s",
  tostring(AI.enabled), tostring(s.state), s.z or 0, s.maxz or 0, tostring(s.lane),
  tostring(s.act), tostring(s.reach), tostring(s.obs), tostring(s.frames),
  tostring(s.moves), tostring(s.dead)))
if AI.err then L("ST err=" .. tostring(AI.err)) end
"""

_META = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
local m = DataCenter.LWSurfingDataManager
local function try(k, fn) local ok, v = pcall(fn) L("ST " .. k .. "=" .. (ok and tostring(v) or "nil")) end
try("remain", function() return m:GetRemainTimes() end)
try("best", function() return m:GetPersonalHightestScoreData() end)
try("act", function() return m:GetActId() end)
"""

_START = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
local ok, err = pcall(function() DataCenter.LWSurfingDataManager:ReqFightStartCheck(false) end)
L(ok and "ST start=1" or ("ST start=0 err=" .. tostring(err)))
"""

_DISMISS = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
local ok = pcall(function() DataCenter.LWSurfingDataManager:GoBackToActivityPanel() end)
L("ST dismiss=" .. tostring(ok))
"""

# What the finished attempt left behind: the moves it issued, the last seconds of its own
# perception, and — the part that actually drives the next fix — the obstacle field frozen
# at the instant of death.
_DRAIN = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
local AI = _G.__SR_AI
if not AI then return end
local function flush(tag, buf)
  local out = {}
  for i = 1, #buf do
    out[#out + 1] = buf[i]
    if #out >= 30 then L(tag .. " " .. table.concat(out, ";")) out = {} end
  end
  if #out > 0 then L(tag .. " " .. table.concat(out, ";")) end
end
flush("MOVES", AI.log or {})
local t = AI.trace or {}
local tail = {}
for i = math.max(1, #t - 60), #t do tail[#tail + 1] = t[i] end
flush("TRACE", tail)
if AI.death then
  L(string.format("DEATH z=%.1f speed=%s lane=%s y=%.2f x=%.2f anim=%s units=%s",
    AI.stat.deathz or 0, tostring(AI.stat.deathspeed), tostring(AI.stat.deathlane),
    AI.stat.deathy or 0, AI.stat.deathx or 0, tostring(AI.stat.deathanim),
    tostring(AI.stat.deathunits)))
  flush("DOBS", AI.death)
end
-- the whole run's perceived field, one frame per line (batching risks a truncated log line)
local Fr = AI.frames or {}
for i = 1, #Fr do L("FRAME " .. Fr[i]) end
AI.log = {} AI.trace = {} AI.frames = {} AI.death = nil
"""


_APPLY_CFG = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
local AI = _G.__SR_AI
if not AI then L("ST cfg=0") return end
%s
if AI.resetKinds then AI.resetKinds() end
L("ST cfg=1")
"""


def _push_cfg(ev, cfg: dict):
    if not cfg:
        return
    body = "\n".join(
        "AI.cfg[%r] = %s" % (k, "true" if v is True else "false" if v is False else repr(v))
        for k, v in sorted(cfg.items()))
    body = body.replace("'", '"')
    _lines(ev, _APPLY_CFG % body, settle=0.5)


def _apply_cfg(ev, cfg: dict, baseline: dict | None = None):
    """Adopt the learner's overrides only if the track agrees with them.

    What the death record suggests is a hypothesis, not an improvement: the obvious rule —
    "we keep clipping things, so add margin" — makes the runner strictly worse, because the
    extra margin closes gaps that are genuinely passable (measured: padExtra 4.0 drops the
    offline replay from 9 bands to 8). So a proposal is scored against the real track before
    and after, and kept only when it does not lose ground. Nothing reaches a live attempt on
    a guess.
    """
    if not cfg:
        return False
    before = surfing_simulate.score(ev)
    _push_cfg(ev, cfg)
    after = surfing_simulate.score(ev)
    # a tie is not evidence: leave a working configuration alone unless the replay is
    # actually better on it
    better = (after[0], after[2]) > (before[0], before[2])
    if better:
        print("  tuning kept: %s  (offline %d/%d -> %d/%d bands)"
              % (cfg, before[0], before[1], after[0], after[1]))
        return True
    _push_cfg(ev, dict(baseline or {}))
    print("  tuning REJECTED: %s would score %d/%d vs %d/%d — reverted"
          % (cfg, after[0], after[1], before[0], before[1]))
    return False


_RESTORE = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
pcall(function() SceneUtils.ChangeToCity() end)
pcall(function() UIManager.Instance:OpenWindow(UIWindowNames.UIMain) end)
L("ST restored=1")
"""


def _restore_ui(ev):
    """Put the client back on the base with its HUD up.

    `GoBackToActivityPanel()` closes the runner and its UI, but a run started headlessly
    was never opened from the event panel, so there is nothing underneath to go back to:
    the window stack ends up empty and whoever is at the machine sees a black screen.
    Sending the client to the city scene and re-opening the main window fixes it.
    """
    _lines(ev, _RESTORE, settle=3.0)
    print("client returned to the base")


def cmd_status(ev):
    st = _kv(_lines(ev, _STATUS, settle=0.35))
    meta = _kv(_lines(ev, _META, settle=0.35))
    print("autopilot :", "installed" if st.get("installed") == "1" else "NOT installed")
    if st.get("installed") == "1":
        print("  enabled=%s state=%s z=%s maxz=%s lane=%s obs=%s frames=%s moves=%s"
              % (st.get("enabled"), st.get("state"), st.get("z"), st.get("maxz"),
                 st.get("lane"), st.get("obs"), st.get("frames"), st.get("moves")))
        if st.get("err"):
            print("  ERROR in tick: %s" % st["err"])
    print("event     : attempts=%s best=%s activity=%s"
          % (meta.get("remain"), meta.get("best"), meta.get("act")))
    return 0


def _one_attempt(ev, revives: int, log):
    """Start one attempt, follow it to the end, return (distance, lives)."""
    _lines(ev, _START, settle=2.0)
    # wait for the runner scene: the autopilot starts counting frames as soon as it runs
    t0 = time.time()
    started = False
    while time.time() - t0 < 25:
        st = _kv(_lines(ev, _STATUS, settle=0.2))
        if st.get("state") == "3" and float(st.get("frames") or 0) > 0:
            started = True
            break
        time.sleep(0.4)
    if not started:
        print("  scene never started")
        _lines(ev, _DISMISS, settle=0.8)
        return 0.0, 0

    lives = 1
    best_z = 0.0
    stall_since = time.time()
    last_z = -1.0
    while True:
        st = _kv(_lines(ev, _STATUS, settle=0.2))
        z = float(st.get("z") or 0)
        maxz = float(st.get("maxz") or 0)
        best_z = max(best_z, maxz)
        if st.get("err"):
            print("  tick error: %s" % st["err"])
        if z > last_z + 0.5:
            last_z = z
            stall_since = time.time()
        elif time.time() - stall_since > 2.5:
            # the run stopped advancing: dead, or the result popup is up
            if lives <= revives and _revive(ev):
                lives += 1
                stall_since = time.time()
                last_z = -1.0
                print("  revived (life %d)" % lives)
                continue
            break
        print("    z=%.0f lane=%s obs=%s moves=%s" % (z, st.get("lane"), st.get("obs"),
                                                      st.get("moves")), end="\r")
        time.sleep(0.5)
    print(" " * 60, end="\r")
    log.write("# attempt ended at z=%.0f, lives=%d\n" % (best_z, lives))
    death = None
    frames = []
    for ln in _lines(ev, _DRAIN, settle=3.0):
        tag, _, body = ln.partition(" ")
        if tag in ("MOVES", "TRACE", "DOBS"):
            for row in body.split(";"):
                log.write("%s %s\n" % (tag.lower(), row))
            if tag == "DOBS" and death is not None:
                for row in body.split(";"):
                    f = row.split("|")
                    if len(f) >= 5:
                        death["obs"].append({"x": float(f[0]), "z": float(f[1]), "mid": f[2],
                                             "speed": float(f[3] or 0),
                                             "name": f[4].replace("(Clone)", "")})
        elif tag == "DEATH":
            log.write("death %s\n" % body)
            death = {"obs": []}
            for part in body.split():
                if "=" in part:
                    k, v = part.split("=", 1)
                    death[k] = v
        elif tag == "FRAME":
            frames.append(body)
    log.flush()
    # the whole run's perceived field, freshest attempt wins — the route replay reads this
    with open(os.path.join(RESULT_DIR, "last_frames.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(frames))
    return best_z, lives, death


# Reviving through `logic:RebirthGame()` sends the proper server request, but it is the
# result popup's button that normally does it — so nothing closes «Испытание окончено» and
# the run carries on underneath a dead card left on screen. Destroy that one window (only
# it: `logic:CloseWindows()` would take the run's HUD with it).
_REVIVE = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
local lg = _G.__SR_LOGIC
if not lg then L("ST revive=0") return end
local ok = pcall(function() lg:RebirthGame() end)
local closed = pcall(function()
  local um = UIManager:GetInstance()
  if um:IsWindowOpen(UIWindowNames.UISurfingBattleFailure) then
    um:DestroyWindow(UIWindowNames.UISurfingBattleFailure)
  end
end)
L("ST revive=" .. tostring(ok) .. " closed=" .. tostring(closed))
"""


def _revive(ev) -> bool:
    st = _kv(_lines(ev, _REVIVE, settle=1.5))
    if st.get("revive") != "true":
        return False
    # confirm the run actually resumed
    for _ in range(10):
        s = _kv(_lines(ev, _STATUS, settle=0.2))
        if s.get("state") == "3" and s.get("dead") != "true":
            return True
        time.sleep(0.4)
    return False


def cmd_run(ev, reserve: int, revives: int):
    meta = _kv(_lines(ev, _META, settle=0.4))
    if meta.get("act") in (None, "nil", "0"):
        print("Event «Уличный забег» is not open.")
        return 2
    remaining = int(float(meta.get("remain") or 0))
    print("attempts=%d best=%s | reserve=%d revives=%d" % (remaining, meta.get("best"), reserve, revives))
    if not install(ev):
        print("autopilot failed to install — aborting")
        return 1
    # recording leaves the bot disabled (it only observes); a run must re-enable it, or it
    # sits idle and the attempt is wasted.
    _lines(ev, 'if _G.__SR_AI then _G.__SR_AI.enabled = true end\n'
               'CS.UnityEngine.Debug.LogError("SRAI ST reon=1")', settle=0.3)
    os.makedirs(RESULT_DIR, exist_ok=True)
    runlog = open(os.path.join(RESULT_DIR, "ai_moves.log"), "a", encoding="utf-8")
    summary = open(os.path.join(RESULT_DIR, "ai_runs.log"), "a", encoding="utf-8")
    # Everything learnt so far goes in before the first attempt of the session, so a run
    # never repeats a lesson an earlier one already paid an attempt for.
    store = surfing_stats.load_store()
    baseline = dict(store.get("cfg") or {})
    if _apply_cfg(ev, surfing_stats.derive_cfg(store), baseline):
        store["cfg"] = surfing_stats.derive_cfg(store)
        surfing_stats.save_store(store)
    attempt = 0
    try:
        while remaining > reserve:
            attempt += 1
            print("attempt %d (attempts left %d)" % (attempt, remaining))
            dist, lives, death = _one_attempt(ev, revives, runlog)
            _lines(ev, _DISMISS, settle=1.0)
            time.sleep(0.8)
            meta = _kv(_lines(ev, _META, settle=0.4))
            new_remaining = int(float(meta.get("remain") or (remaining - 1)))
            line = ("%s attempt=%d dist=%.0f lives=%d best=%s remaining=%d"
                    % (time.strftime("%H:%M:%S"), attempt, dist, lives,
                       meta.get("best"), new_remaining))
            print("  " + line)
            summary.write(line + "\n")
            summary.flush()
            # Learn from this attempt before spending the next one: classify what killed
            # it, fold it into the record, and push any resulting tuning into the VM.
            if death:
                entry = surfing_stats.record(store, death, dist, lives, version="v16")
                surfing_stats.save_store(store)
                print("  death: %s at %.0f m (%s)"
                      % (entry["cause"], entry["z"], entry["killer"] or "nothing in that lane"))
                proposal = surfing_stats.derive_cfg(store)
                if proposal != baseline and _apply_cfg(ev, proposal, baseline):
                    baseline = proposal
                    store["cfg"] = proposal
                    surfing_stats.save_store(store)
            if new_remaining >= remaining:      # the attempt was not consumed — stop looping
                print("  attempt count did not drop; stopping to avoid a spin")
                break
            remaining = new_remaining
    finally:
        runlog.close()
        summary.close()
        print()
        print(surfing_stats.summary(store))
    _restore_ui(ev)
    print("done; %d attempts left in reserve" % remaining)
    return 0


_RECORD_ON = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
local AI = _G.__SR_AI
if not AI then L("ST rec=0") return end
AI.enabled = false   -- observe only: the human drives
AI.record = true
AI.frames = {}
L("ST rec=1")
"""

_RECORD_OFF = 'if _G.__SR_AI then _G.__SR_AI.record = false end\n' \
              'CS.UnityEngine.Debug.LogError("SRAI ST recoff=1")'


HUMAN_DIR = os.path.join(RESULT_DIR, "human")


def _record_one(ev, start_wait: float):
    """Arm recording, wait for a human run to start, follow it to the end, return its frames
    and distance (or None if no run started within start_wait)."""
    _lines(ev, _RECORD_ON, settle=0.5)
    t0 = time.time()
    started = False
    while time.time() - t0 < start_wait:
        st = _kv(_lines(ev, _STATUS, settle=0.3))
        if st.get("state") == "3" and float(st.get("frames") or 0) > 0:
            started = True
            break
        time.sleep(0.6)
    if not started:
        return None, 0.0
    print("  идёт запись…")
    last_z, stall = -1.0, time.time()
    while True:
        st = _kv(_lines(ev, _STATUS, settle=0.3))
        z = float(st.get("z") or 0)
        if z > last_z + 0.5:
            last_z, stall = z, time.time()
        elif st.get("dead") == "true" or time.time() - stall > 4.0:
            break
        print("    z=%.0f lane=%s" % (z, st.get("lane")), end="\r")
        time.sleep(0.4)
    print(" " * 50, end="\r")
    frames = []
    for ln in _lines(ev, _DRAIN, settle=5.0):
        tag, _, body = ln.partition(" ")
        if tag == "FRAME":
            frames.append(body)
    return frames, last_z


def cmd_record(ev, loop: bool):
    """Record HUMAN-played runs: the bot observes but never drives, so expert play can be
    replayed (tools/dev/surfing_route_html.py human) and compared with the bot's model — the
    fastest way to find where the model or the policy is wrong.

    `loop` keeps recording run after run, auto-saving each to results/street_run/human/run_NNN.txt,
    until no new run starts for a while (the human is done). One-shot writes human_frames.txt."""
    if not install(ev):
        print("autopilot failed to install — aborting")
        return 1
    if not loop:
        print("ЗАПИСЬ. Сыграй ОДИН забег: открой «Уличный забег» → «Начать» → играй до смерти.")
        frames, dist = _record_one(ev, 300)
        _lines(ev, _RECORD_OFF, settle=0.3)
        if frames is None:
            print("Забег не начался — отменено.")
            return 1
        with open(os.path.join(RESULT_DIR, "human_frames.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(frames))
        print("Записано %d кадров (~%.0f м) -> human_frames.txt" % (len(frames), dist))
        return 0
    os.makedirs(HUMAN_DIR, exist_ok=True)
    import glob
    run_no = len(glob.glob(os.path.join(HUMAN_DIR, "run_*.txt")))
    print("ЗАПИСЬ (ЦИКЛ). Играй забеги один за другим — каждый сохранится сам. "
          "Останови, когда наиграешься (я или таймаут 200с без нового забега).")
    while True:
        print("Готов к забегу — нажми «Начать» и играй." if run_no else
              "Жду первый забег — «Начать» и играй.")
        frames, dist = _record_one(ev, 200)
        if frames is None:
            print("Нового забега нет 200с — останавливаю запись (%d забегов сохранено)." % run_no)
            _lines(ev, _RECORD_OFF, settle=0.3)
            return 0
        run_no += 1
        out = os.path.join(HUMAN_DIR, "run_%03d.txt" % run_no)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(frames))
        print("✔ Забег %d: %.0f м, %d кадров -> %s" % (run_no, dist, len(frames), out))


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cmd = argv[0] if argv else "status"
    ev = get_evaluator()
    try:
        if cmd == "install":
            return 0 if install(ev) else 1
        if cmd == "status":
            return cmd_status(ev)
        if cmd == "off":
            _lines(ev, 'local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end\n'
                       'if _G.__SR_AI then _G.__SR_AI.enabled = false end L("ST off=1")', settle=0.4)
            print("autopilot disabled")
            return 0
        if cmd == "on":
            _lines(ev, 'local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end\n'
                       'if _G.__SR_AI then _G.__SR_AI.enabled = true end L("ST on=1")', settle=0.4)
            print("autopilot enabled")
            return 0
        if cmd == "record":
            return cmd_record(ev, loop=("loop" in argv[1:]))
        if cmd == "stats":
            print(surfing_stats.summary(surfing_stats.load_store()))
            return 0
        if cmd == "learn":
            # Re-derive the whole record from the raw run log. The log is the source of
            # truth; deaths.json is only the digest, so a wrong inference can be undone by
            # re-running this after the classifier changes.
            store = {"deaths": []}
            for rec in surfing_stats.parse_log(os.path.join(RESULT_DIR, "ai_moves.log")):
                surfing_stats.record(store, rec, float(rec.get("z", 0)), 1, version="replay")
            surfing_stats.save_store(store)
            print(surfing_stats.summary(store))
            return 0
        if cmd == "bounds":
            # The collider extents the autopilot measured this session. Persisted so the
            # offline simulator collides against real sizes instead of guesses.
            out = _lines(ev, r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
local AI = _G.__SR_AI
if not AI or not AI.bounds then L("B none") return end
for nm, v in pairs(AI.bounds) do L("B " .. nm .. "  " .. v) end
""", settle=0.8)
            import json
            path = os.path.join("results", "street_run", "config", "bounds.json")
            data = {}
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            for ln in sorted(out):
                print(ln)
                if not ln.startswith("B "):
                    continue
                name, _, rest = ln[2:].partition("  ")
                rec = {}
                for part in rest.split():
                    if "=" in part:
                        k, v = part.split("=", 1)
                        try:
                            rec[k] = float(v)
                        except ValueError:
                            pass
                if rec:
                    data[name.replace("(Clone)", "")] = rec
            if data:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=1, sort_keys=True)
                print("-> %s (%d prefabs)" % (path, len(data)))
            return 0
        if cmd == "run":
            return cmd_run(ev,
                           int(argv[1]) if len(argv) > 1 else 5,
                           int(argv[2]) if len(argv) > 2 else 0)
        print(__doc__)
        return 1
    finally:
        ev.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
