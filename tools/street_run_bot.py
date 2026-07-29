#!/usr/bin/env python3
r"""Street Run («Уличный забег» / Ghost Parkour endless runner) bot harness.

The runner is a Subway-Surfers-style dodge game: run as far as possible, dodge
randomly spawning obstacles, arrow-key control, a handful of attempts per round.
See docs/research/street-run-parkour.md for the full reconnaissance.

Because the run is real-time, live state (player lane, obstacles) is read by
**vision** (mss screenshot + image processing), not Lua — a SafeDoString
round-trip is ~1 s, far too slow for a reflex loop. Lua is used only for meta:
checking event availability, remaining attempts, and (once open) starting a run
via DataCenter.LWGhostParkourDataManager.

Run under the Windows Python so it can reach the game + warm Lua daemon:

    C:\Python312\python.exe tools\street_run_bot.py probe        # is the event open? attempts left?
    C:\Python312\python.exe tools\street_run_bot.py shot [name.png]
    C:\Python312\python.exe tools\street_run_bot.py watch [sec]  # poll until the event opens
    C:\Python312\python.exe tools\street_run_bot.py calibrate [n]# grab N run frames for tuning
    C:\Python312\python.exe tools\street_run_bot.py run [fightType]  # play (blocked until open)

Status: `probe`/`shot`/`watch` work now. `run` refuses while the event is closed
(activityId=nil) and keeps 5 attempts in reserve for the user; its perception layer
is a calibration stub — the lane geometry and obstacle signature must be tuned on the
first live frames (`calibrate`, marked CALIBRATE) before `run` can actually dodge.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))

# ---------------------------------------------------------------------------
# Lua meta layer (event state, launch, attempt count)
# ---------------------------------------------------------------------------

_STATE_LUA = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRB "..tostring(s)) end
local m = DataCenter.LWSurfingDataManager
local function try(label, fn)
  local ok,res = pcall(fn)
  if ok then L(label.."="..tostring(res)) else L(label.."=nil") end
end
try("now",         function() return ChatInterface.getServerTime() end)
try("activityId",  function() return m:GetActId() end)
try("remainTimes", function() return m:GetRemainTimes() end)
try("round",       function() return m:GetRound() end)
try("highest",     function() return m:GetPersonalHightestScoreData() end)
try("todayScore",  function() return m:GetTodayPersonalProgressScore() end)
try("resurgeLimit",function() return m:GetResurgenceLimit() end)
try("endTime",     function() return m:GetTheBattleEndTime() end)
"""

_FETCH_LUA = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRB "..tostring(s)) end
local m = DataCenter.LWSurfingDataManager
-- refresh the activity roster, then pull surfing/parkour-specific info
pcall(function() DataCenter.ActivityListDataManager:RequestActivityData() end)
pcall(function() m:SendGetAllParkourInfosMessage() end)
L("fetch-requested")
"""

# Launch a run. The in-game «Начать» button is ReqFightStartCheck(restart): it
# validates the start-message cooldown (GetStartMsgCD/startMsgTs) and matching
# state, then sends MsgDefines.ParkourFightStartCheck; the server-approved flow
# lands in OnStartGame → the runner scene loads. (ReqStartGame(restart) sends the
# raw MsgDefines.ParkourFightStart and skips the checks.) restart=false = fresh run.
# Confirmed live 2026-07-29 via string.dump of LWSurfingDataManager.lua.
_START_LUA = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRB "..tostring(s)) end
local m = DataCenter.LWSurfingDataManager
local ok,err = pcall(function() m:ReqFightStartCheck(false) end)
L(ok and "start-check-sent" or ("start-err="..tostring(err)))
"""


def _eval(chunk: str, settle: float = 1.5) -> dict:
    """Run a Lua chunk through the warm daemon and parse `SRB key=val` lines."""
    from lua_client import get_evaluator

    ev = get_evaluator()
    try:
        lines = ev.run(chunk, marker="SRB ", settle=settle)
    finally:
        ev.close()
    out: dict[str, str] = {}
    for ln in lines:
        body = ln.split("SRB ", 1)[-1].strip()
        if "=" in body:
            k, v = body.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def read_state(fetch: bool = False) -> dict:
    if fetch:
        _eval(_FETCH_LUA, settle=2.0)
        time.sleep(1.0)
    return _eval(_STATE_LUA, settle=1.6)


def event_open(state: dict) -> bool:
    aid = state.get("activityId", "nil")
    return aid not in ("nil", "", "0")


def start_run():
    _eval(_START_LUA, settle=2.5)


_DISMISS_LUA = r"""
local m = DataCenter.LWSurfingDataManager
pcall(function() m:GoBackToActivityPanel() end)
"""


def _dismiss_popup():
    """Close the «Испытание окончено» result popup so the next run can start."""
    _eval(_DISMISS_LUA, settle=1.0)


# ---------------------------------------------------------------------------
# Vision + input layer (real-time reflex loop)
# ---------------------------------------------------------------------------

PID = 94880  # LastWar.exe — re-resolve with find_win() if the client restarted


def _win_libs():
    import mss  # noqa: F401
    import win32api  # noqa: F401
    import win32con  # noqa: F401
    import win32gui  # noqa: F401
    import win32process  # noqa: F401
    return mss, win32api, win32con, win32gui, win32process


def find_win(pid: int = PID):
    _, _, _, win32gui, win32process = _win_libs()
    hs = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            _, p = win32process.GetWindowThreadProcessId(h)
            if p == pid:
                r = win32gui.GetWindowRect(h)
                if r[2] - r[0] > 200 and r[3] - r[1] > 200:
                    hs.append((h, r))
        return True

    win32gui.EnumWindows(cb, None)
    return hs[0] if hs else (None, None)


def focus(h):
    _, win32api, win32con, win32gui, _ = _win_libs()
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    try:
        win32gui.ShowWindow(h, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(h)
    except Exception:
        pass
    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)


def grab(h, name: str | None = None):
    """Fast full-window grab (no focus trick — assumes the window is foreground)."""
    import mss
    import mss.tools
    _, _, _, win32gui, _ = _win_libs()
    r = win32gui.GetWindowRect(h)
    with mss.MSS() as sct:
        img = sct.grab({"left": r[0], "top": r[1],
                        "width": r[2] - r[0], "height": r[3] - r[1]})
    if name:
        out = os.path.abspath(os.path.join("results", name))
        mss.tools.to_png(img.rgb, img.size, output=out)
    return img, r


def press(key: str):
    """Send an arrow tap. Mapping (CALIBRATE live): left/right = lane, up = jump,
    down = slide."""
    import pydirectinput
    pydirectinput.PAUSE = 0.0
    pydirectinput.FAILSAFE = False
    pydirectinput.press(key)  # 'left' | 'right' | 'up' | 'down'


# --- perception (calibrated on results/street_run/frames/live_*.png) ---------
# Frame is the full client window (≈1531×997). Everything below is expressed as
# fractions of W/H so it survives a resize. Calibration facts from the live frames:
#   • The avatar wears a saturated BLUE helmet; during play it sits at y≈0.60 and its
#     x snaps to one of 3 lanes. Centre lane measured at x≈0.499.
#   • Coins are vivid YELLOW (hue ~20–40) — must NOT be read as obstacles.
#   • Obstacles (cars/trucks/containers/barriers) read as vivid non-yellow blobs or
#     dark blobs inside the road ahead of the avatar.

_HELMET_LO = (95, 110, 80)      # HSV lower for the blue helmet
_HELMET_HI = (125, 255, 255)
# lane x-centre at the avatar's depth, and classification thresholds
_LANE_SPLIT = (0.44, 0.56)      # x < .44 → left(0), .44–.56 → centre(1), > .56 → right(2)
# danger band ahead of the avatar (sampled at three depths) and per-depth lane spread
_BAND_DEPTHS = (0.34, 0.40, 0.47)
_OBST_THRESH = 0.12             # per-lane vivid-nonyellow+dark fraction that means "blocked"


def _to_bgr(img):
    """mss screenshot → BGR uint8 ndarray."""
    import numpy as np
    a = np.frombuffer(img.bgra, np.uint8).reshape(img.height, img.width, 4)
    return a[:, :, :3]


def _lane_centres(yr: float):
    """3 lane x-centres at depth yr, converging toward the vanishing point."""
    t = max(0.0, min(1.0, (yr - 0.28) / (0.60 - 0.28)))
    spread = 0.02 + (0.12 - 0.02) * t
    return (0.5 - spread, 0.5, 0.5 + spread)


def detect(img) -> dict:
    """{'player_lane': 0|1|2|None, 'blocked': [bool,bool,bool], 'dead': bool}."""
    import cv2, numpy as np
    bgr = _to_bgr(img)
    H, W = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    # dead: the «Испытание окончено» card is a big near-white panel centre-screen
    card = hsv[int(H * 0.20):int(H * 0.46), int(W * 0.34):int(W * 0.66)]
    near_white = ((card[:, :, 1] < 60) & (card[:, :, 2] > 205)).mean()
    dead = near_white > 0.25

    # player lane from the blue-helmet centroid in the bottom-centre ROI
    m = cv2.inRange(hsv, _HELMET_LO, _HELMET_HI)
    roi = np.zeros((H, W), np.uint8)
    roi[int(H * 0.50):int(H * 0.72), int(W * 0.34):int(W * 0.66)] = 255
    m = cv2.bitwise_and(m, roi)
    xs = np.where(m > 0)[1]
    if len(xs) >= 80:
        px = xs.mean() / W
        player = 0 if px < _LANE_SPLIT[0] else (2 if px > _LANE_SPLIT[1] else 1)
    else:
        player = None

    # obstacle per lane, ADAPTIVE to the current frame's lighting (a fixed threshold
    # fails — road brightness swings scene to scene). Reference = the road patch right
    # in front of the avatar (almost always clear). An obstacle pixel is markedly
    # DARKER or MORE saturated than that reference; bright gold coins are carved out.
    hue = hsv[:, :, 0].astype(int); sat = hsv[:, :, 1].astype(int); val = hsv[:, :, 2].astype(int)
    ref = hsv[int(H * 0.53):int(H * 0.57), int(W * 0.47):int(W * 0.53)]
    road_v = float(np.median(ref[:, :, 2])); road_s = float(np.median(ref[:, :, 1]))
    coin = (val > 175) & (hue >= 12) & (hue <= 45) & (sat > 110)
    obst = ((val < road_v - 45) | (sat > road_s + 70)) & (~coin)
    blocked = [False, False, False]
    for yr in _BAND_DEPTHS:
        y = int(H * yr); dy = int(H * 0.03); dx = int(W * 0.03)
        for lane, cx in enumerate(_lane_centres(yr)):
            x = int(W * cx)
            frac = obst[y - dy:y + dy, x - dx:x + dx].mean()
            if frac > _OBST_THRESH:
                blocked[lane] = True
    return {"player_lane": player, "blocked": blocked, "dead": dead}


def decide(state: dict) -> str | None:
    """Lane-switch away from a blocked lane toward a clear one. (Jump/slide ↑/↓ are
    left out of v1 — the frames don't yet distinguish a jumpable vs slideable obstacle,
    and a wrong guess kills the run faster than a mis-timed lane change.)"""
    pl = state.get("player_lane")
    blocked = state.get("blocked") or [False, False, False]
    if pl is None or not blocked[pl]:
        return None
    # player's lane is blocked → step to a clear neighbour, preferring the centre
    if pl == 1:
        if not blocked[0] and blocked[2]:
            return "left"
        if not blocked[2] and blocked[0]:
            return "right"
        if not blocked[2]:
            return "right"
        if not blocked[0]:
            return "left"
        return "up"                    # both sides blocked → try a jump
    if pl == 0:
        return "right" if not blocked[1] else ("up")
    if pl == 2:
        return "left" if not blocked[1] else ("up")
    return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_probe():
    st = read_state(fetch=True)
    print("«Уличный забег» / Surfing (LWSurfingDataManager) state:")
    for k in ("now", "activityId", "remainTimes", "round", "highest",
              "todayScore", "resurgeLimit", "endTime"):
        print(f"  {k:14s} = {st.get(k, '?')}")
    if event_open(st):
        print("\n=> EVENT OPEN. Attempts left:", st.get("remainTimes", "?"),
              "| best distance:", st.get("highest", "?"))
    else:
        print("\n=> EVENT CLOSED (activityId is nil). Cannot start a run yet.")
    return 0


def cmd_shot(name="sr_now.png"):
    h, _ = find_win()
    if h is None:
        print("no game window"); return 1
    focus(h); time.sleep(0.8)
    grab(h, name)
    print("saved results/" + name)
    return 0


def cmd_watch(interval: float = 300.0):
    """Poll until «Уличный забег» opens, then stop so a live calibration+run pass can
    begin. Does NOT auto-play (the detector needs calibrating on real frames first).

    Durable/observable for a detached pythonw launch: appends a heartbeat to
    results/street_run/watch.log every poll, and on open drops a sentinel
    results/street_run/EVENT_OPEN.txt (activityId + attempts) so a supervising
    session can detect the open without watching stdout."""
    outdir = os.path.join("results", "street_run")
    os.makedirs(outdir, exist_ok=True)
    logp = os.path.join(outdir, "watch.log")
    sentinel = os.path.join(outdir, "EVENT_OPEN.txt")
    # Stale sentinel from a previous window would falsely signal "open".
    if os.path.exists(sentinel):
        os.remove(sentinel)

    def hb(msg: str):
        line = f"{int(time.time())} {msg}"
        print(line, flush=True)
        with open(logp, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    hb("watch start; interval=%ds" % int(interval))
    while True:
        try:
            st = read_state(fetch=True)
        except Exception as e:  # daemon/game hiccup — keep the watcher alive
            hb("probe-error: %r" % e)
            time.sleep(interval)
            continue
        if event_open(st):
            att = st.get("remainTimes", st.get("remainChallenge", "?"))
            hb("EVENT OPEN activityId=%s attempts=%s" % (st.get("activityId"), att))
            with open(sentinel, "w", encoding="utf-8") as f:
                f.write("activityId=%s\nattempts=%s\nnow=%s\n"
                        % (st.get("activityId"), att, st.get("now")))
            hb("wrote sentinel %s; run calibrate then run" % sentinel)
            return 0
        hb("closed; next check in %ds" % int(interval))
        time.sleep(interval)


def cmd_calibrate(n: int = 60, delay: float = 0.08):
    """Start one real run and capture N frames of the runner into
    results/street_run/frames/, so the lane geometry + obstacle signature in
    detect() (and the input model) can be tuned. Costs one attempt."""
    st = read_state(fetch=True)
    if not event_open(st):
        print("Event «Уличный забег» is not open — nothing to calibrate."); return 2
    outdir = os.path.join("results", "street_run", "frames")
    os.makedirs(outdir, exist_ok=True)
    h, _ = find_win()
    if h is None:
        print("no game window"); return 1
    focus(h); time.sleep(0.6)
    print("attempts before:", st.get("remainTimes"))
    start_run()                        # ReqFightStartCheck → OnStartGame → runner scene
    time.sleep(3.0)                    # let the scene load
    for i in range(n):
        grab(h, os.path.join("street_run", "frames", f"frame_{i:03d}.png"))
        time.sleep(delay)
    after = read_state().get("remainTimes")
    print(f"saved {n} frames to {outdir}; attempts after: {after}")
    return 0


def cmd_record(n: int = 120, delay: float = 0.06):
    """Capture-only: grab N frames at `delay` spacing into results/street_run/frames/
    WITHOUT starting a run. Launch this (backgrounded), then fire a run — or let the
    user play one — so the frames cover live gameplay from t≈0, not just the death
    popup. Reveals lane geometry, obstacle look, and (watching the avatar) the input
    model."""
    outdir = os.path.join("results", "street_run", "frames")
    os.makedirs(outdir, exist_ok=True)
    h, _ = find_win()
    if h is None:
        print("no game window"); return 1
    focus(h); time.sleep(0.3)
    for i in range(n):
        grab(h, os.path.join("street_run", "frames", f"rec_{i:03d}.png"))
        time.sleep(delay)
    print(f"saved {n} frames to {outdir}")
    return 0


def cmd_run(reserve: int = 5):
    st = read_state(fetch=True)
    if not event_open(st):
        print("Event «Уличный забег» is not open (activityId=nil). Nothing to run.")
        print("Use `watch` to wait for it, then `calibrate` on the first live frames")
        print("(the perception layer in detect() is a CALIBRATE stub until then).")
        return 2

    h, _ = find_win()
    if h is None:
        print("no game window"); return 1
    focus(h); time.sleep(0.8)

    outdir = os.path.join("results", "street_run")
    os.makedirs(outdir, exist_ok=True)
    log = open(os.path.join(outdir, "runs.log"), "a", encoding="utf-8")
    remaining = int(st.get("remainTimes") or 0)
    best0 = st.get("highest", "?")
    print(f"Event open, {remaining} attempt(s); best so far {best0}. Reserve={reserve}.")
    attempt = 0
    while remaining > reserve:
        attempt += 1
        focus(h); time.sleep(0.3)
        start_run()                    # ReqFightStartCheck → OnStartGame → runner scene
        # wait for the runner scene: the avatar (blue helmet) appears
        loaded = False
        t_load = time.time() + 8
        while time.time() < t_load:
            if detect(grab(h)[0]).get("player_lane") is not None:
                loaded = True; break
            time.sleep(0.15)
        if not loaded:
            print(f"attempt {attempt}: scene did not load; abort this attempt")
            _dismiss_popup(); remaining = int(read_state().get("remainTimes") or remaining - 1)
            continue
        # reflex loop until death (or a hard cap)
        cooldown = 0.0
        deadline = time.time() + 120
        while time.time() < deadline:
            s = detect(grab(h)[0])
            if s["dead"]:
                break
            now = time.time()
            if now >= cooldown:
                key = decide(s)
                if key:
                    press(key)
                    cooldown = now + 0.28   # let the lane change settle before re-deciding
        # record the result: snapshot the «Испытание окончено» popup + read best
        grab(h, os.path.join("street_run", f"result_{attempt:02d}.png"))
        st = read_state()
        best = st.get("highest", "?")
        remaining = int(st.get("remainTimes") or remaining - 1)
        line = (f"attempt {attempt}: remaining={remaining} best={best} "
                f"(popup=results/street_run/result_{attempt:02d}.png)")
        log.write(line + "\n"); log.flush()
        print(line)
        _dismiss_popup(); time.sleep(0.6)   # clear the popup before the next start
    print(f"Stopped with {remaining} attempts in reserve. Best distance: "
          f"{read_state().get('highest', '?')}")
    log.close()
    return 0


def main(argv):
    cmd = argv[0] if argv else "probe"
    if cmd == "probe":
        return cmd_probe()
    if cmd == "shot":
        return cmd_shot(argv[1] if len(argv) > 1 else "sr_now.png")
    if cmd == "watch":
        return cmd_watch(float(argv[1]) if len(argv) > 1 else 300.0)
    if cmd == "calibrate":
        return cmd_calibrate(int(argv[1]) if len(argv) > 1 else 60)
    if cmd == "record":
        return cmd_record(int(argv[1]) if len(argv) > 1 else 120)
    if cmd == "run":
        return cmd_run(int(argv[1]) if len(argv) > 1 else 5)
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
