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
local m = DataCenter.LWGhostParkourDataManager
local function try(label, fn)
  local ok,res = pcall(fn)
  if ok then L(label.."="..tostring(res)) else L(label.."=nil") end
end
try("now",            function() return ChatInterface.getServerTime() end)
try("activityId",     function() return m:GetActivityId() end)
try("beginTime",      function() return m:GetBeginTime() end)
try("roundEndTime",   function() return m:GetRoundEndTime() end)
try("nextRoundTime",  function() return m:GetNextRoundTime() end)
try("remainTimes",    function() return m:GetRemainTimes() end)
try("remainChallenge",function() return m:GetRemainChallengeTimes() end)
try("allChallenge",   function() return m:GetAllChallengeTimes() end)
try("endlessSwitch",  function() return m:GetEndlessModeSwitch() end)
try("round",          function() return m:GetGhostParkourRound() end)
try("highest",        function() return m:GetPersonalHightestScore() end)
"""

_FETCH_LUA = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRB "..tostring(s)) end
local m = DataCenter.LWGhostParkourDataManager
-- refresh the activity roster, then pull parkour-specific info
pcall(function() DataCenter.ActivityListDataManager:RequestActivityData() end)
pcall(function() m:SendGetGhostParkourInfosMessage() end)
L("fetch-requested")
"""

# Launch a run. ReqStartGame(fightType, restart) sends MsgDefines.GhostParkourFightStart;
# the server reply lands in OnStartGame → LWBattleManager:Enter(PVEType.GhostParkour,...)
# which loads the runner scene. fightType is an enum (personal vs endless etc.) — CONFIRM
# LIVE via string.dump once the event is open. restart=false for a fresh run.
_START_LUA = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRB "..tostring(s)) end
local m = DataCenter.LWGhostParkourDataManager
local ok,err = pcall(function() m:ReqStartGame(%d, false) end)
L(ok and "start-sent" or ("start-err="..tostring(err)))
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


def start_run(fight_type: int = 1):
    _eval(_START_LUA % fight_type, settle=2.5)


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


# --- perception stub -------------------------------------------------------
# CALIBRATE: on the first live run, capture a few frames of UIGhostParkourBattleMain
# and fill in: the road ROI, number of lanes, the player-marker signature, and the
# obstacle signature (colour/edge). Until then this returns "unknown" and the run
# loop declines to act rather than flailing blindly.

def detect(img) -> dict:
    """Return {'player_lane': int|None, 'obstacle_lane': int|None, 'dead': bool}.
    Placeholder — see CALIBRATE note above."""
    return {"player_lane": None, "obstacle_lane": None, "dead": False}


def decide(state: dict) -> str | None:
    """Given detect() output, return an arrow key or None. Dodge sideways away from
    an obstacle sharing the player's lane."""
    pl, ol = state.get("player_lane"), state.get("obstacle_lane")
    if pl is None or ol is None or pl != ol:
        return None
    return "left" if pl > 0 else "right"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_probe():
    st = read_state(fetch=True)
    print("Ghost Parkour / «Уличный забег» state:")
    for k in ("now", "activityId", "beginTime", "roundEndTime", "nextRoundTime",
              "remainTimes", "remainChallenge", "allChallenge", "endlessSwitch",
              "round", "highest"):
        print(f"  {k:16s} = {st.get(k, '?')}")
    if event_open(st):
        print("\n=> EVENT OPEN. Attempts left:",
              st.get("remainTimes", st.get("remainChallenge", "?")))
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
    begin. Does NOT auto-play (the detector needs calibrating on real frames first)."""
    print("Watching for «Уличный забег» to open (Ctrl-C to stop)...")
    while True:
        st = read_state(fetch=True)
        if event_open(st):
            print("EVENT OPEN! activityId=", st.get("activityId"),
                  "attempts=", st.get("remainTimes", st.get("remainChallenge")))
            print("Run `street_run_bot.py calibrate` then `run`.")
            return 0
        print("  closed; next check in", int(interval), "s")
        time.sleep(interval)


def cmd_calibrate(n: int = 30, delay: float = 0.15):
    """Capture N frames while a run is on screen, into results/street_run/, so the
    lane geometry + obstacle signature in detect() can be tuned. Start a run first."""
    outdir = os.path.join("results", "street_run")
    os.makedirs(outdir, exist_ok=True)
    h, _ = find_win()
    if h is None:
        print("no game window"); return 1
    focus(h); time.sleep(0.5)
    for i in range(n):
        grab(h, os.path.join("street_run", f"frame_{i:03d}.png"))
        time.sleep(delay)
    print(f"saved {n} frames to {outdir}")
    return 0


def cmd_run(fight_type: int = 1):
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

    os.makedirs(os.path.join("results", "street_run"), exist_ok=True)
    log = open(os.path.join("results", "street_run", "runs.log"), "a")
    remaining = int(st.get("remainTimes") or st.get("remainChallenge") or 0)
    print(f"Event open, {remaining} attempt(s) available.")
    # Leave 5 attempts in reserve for the user (task instruction).
    reserve = 5
    while remaining > reserve:
        start_run(fight_type)          # ReqStartGame → OnStartGame → runner scene
        time.sleep(3.0)                # wait for UIGhostParkourBattleMain / scene load
        # reflex loop until death:
        deadline = time.time() + 300
        while time.time() < deadline:
            img, _ = grab(h)
            s = detect(img)            # CALIBRATE: real lane/obstacle detection
            if s["dead"]:
                break
            key = decide(s)
            if key:
                press(key)
            time.sleep(0.01)           # detect() must stay <16 ms once calibrated
        st = read_state()
        dist = st.get("highest", "?")
        log.write(f"attempt remaining={remaining} best={dist}\n"); log.flush()
        remaining = int(st.get("remainTimes") or st.get("remainChallenge") or remaining - 1)
        print("attempt done, remaining:", remaining, "best:", dist)
    print("Stopped with", remaining, "attempts in reserve for the user.")
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
        return cmd_calibrate(int(argv[1]) if len(argv) > 1 else 30)
    if cmd == "run":
        return cmd_run(int(argv[1]) if len(argv) > 1 else 1)
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
