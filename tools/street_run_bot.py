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

    os.makedirs(os.path.join("results", "street_run"), exist_ok=True)
    log = open(os.path.join("results", "street_run", "runs.log"), "a")
    remaining = int(st.get("remainTimes") or 0)
    print(f"Event open, {remaining} attempt(s) available.")
    # Leave `reserve` attempts for the user (task instruction: keep 5).
    while remaining > reserve:
        start_run()                    # ReqFightStartCheck → OnStartGame → runner scene
        time.sleep(3.0)                # wait for the surfing runner scene to load
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
        remaining = int(st.get("remainTimes") or remaining - 1)
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
        return cmd_calibrate(int(argv[1]) if len(argv) > 1 else 60)
    if cmd == "record":
        return cmd_record(int(argv[1]) if len(argv) > 1 else 120)
    if cmd == "run":
        return cmd_run(int(argv[1]) if len(argv) > 1 else 5)
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
