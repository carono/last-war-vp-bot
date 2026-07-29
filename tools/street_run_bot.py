#!/usr/bin/env python3
r"""Street Run («Уличный забег» / Surfing endless runner) bot harness.

The runner is a Subway-Surfers-style 3-lane dodge game: run as far as possible, dodge
randomly spawning obstacles (cars/trucks/concrete + orange barriers/barrels), arrow-key
control (←/→ lane, ↑ jump), a handful of attempts per round plus 3 coin-priced revives.
See docs/research/street-run-parkour.md for the full reconnaissance.

Two state layers exist:

  * **Lua scene reader (preferred, task #1103)** — `tools/lib/surfing_reader.py`. During a
    run every obstacle is a monster object in `SurfingMonsterManager.showList` with exact
    lane (`.x` ∈ {32,36,40}), distance (`.dataZ`), type (`.gameObject.name`/`.unitType`)
    and the player at `SurfingLogic.player:GetPosition()`. This gives deterministic
    look-ahead (~5 s) instead of pixels. Commands: `readtest` (observe), `runlua`
    (autopilot). A daemon read is ~0.09 s (~11 Hz).
  * **Vision (legacy)** — mss screenshot + image processing (`detect`/`decide`, `run`).
    Kept for comparison; the Lua reader supersedes it. See docs/research/street-run-parkour.md.

Lua `DataCenter.LWSurfingDataManager` also holds meta: event availability, remaining
attempts, starting a run (ReqFightStartCheck). Reviving is a UI button click (the Lua
ReqRebirthGame does not revive).

Run under the Windows Python so it can reach the game + warm Lua daemon:

    C:\Python312\python.exe tools\street_run_bot.py probe        # is the event open? attempts left?
    C:\Python312\python.exe tools\street_run_bot.py shot [name.png]
    C:\Python312\python.exe tools\street_run_bot.py test [rec_]  # OFFLINE: detect() on saved frames
    C:\Python312\python.exe tools\street_run_bot.py watch [sec]  # poll until the event opens
    C:\Python312\python.exe tools\street_run_bot.py calibrate [n]# grab N run frames for tuning
    C:\Python312\python.exe tools\street_run_bot.py readtest [sec]        # LUA reader, observe-only
    C:\Python312\python.exe tools\street_run_bot.py runlua [reserve] [revives] [debug]  # LUA autopilot
    C:\Python312\python.exe tools\street_run_bot.py run [reserve] [revives] [debug] [boxed]  # vision (legacy)

`run` keeps `reserve` attempts for the user (default 5), spends `revives` coin-priced
revives per run to extend it (0..3, default 0 — revives cost 100/1000/2000+ coins),
`debug`=1 logs each frame's perception to results/street_run/debug_NN.log, and `boxed`
(up|down|none, default up) is the action taken when boxed in with a LOW obstacle ahead
(jumping a tall barrier is fatal, so ↑ is height-gated; ↓ slide is untested).

Realistic ceiling (proven live, server 935): the vision reflex dodges ~100-160 m per
life; with 3 revives a run reaches ~440-600 m per attempt (deterministic, not luck). The
human record 8185 m — let alone 20000 m — is NOT reachable by this pipeline: at ~15 fps
the loop cannot thread the fast obstacle spawns reliably, and the cartoon palette makes
lit barrels pixel-identical to coins.
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


# Revive on the death popup: continue the SAME run from where it died (distance keeps
# accumulating). 3 revives per run, x100 parkour coins each. Reviving multiplies the
# effective per-run distance, so a run that reaches D metres per life can reach ~4·D.
# NB: the raw Lua `m:ReqRebirthGame()` does NOT revive (verified live — the popup still
# reports 3/3 after it). Revival is driven by the «Воскрешение ×100» button, so we click
# it. Button centre measured on the «Испытание окончено» popup at ≈(0.565·W, 0.59·H).
_REVIVE_BTN = (0.565, 0.59)


def revive(h):
    """Click the «Воскрешение ×100» button on the death popup to continue the run."""
    import pydirectinput
    pydirectinput.PAUSE = 0.0
    pydirectinput.FAILSAFE = False
    _, _, _, win32gui, _ = _win_libs()
    r = win32gui.GetWindowRect(h)
    x = int(r[0] + _REVIVE_BTN[0] * (r[2] - r[0]))
    y = int(r[1] + _REVIVE_BTN[1] * (r[3] - r[1]))
    pydirectinput.moveTo(x, y)
    pydirectinput.click(x, y)


# ---------------------------------------------------------------------------
# Vision + input layer (real-time reflex loop)
# ---------------------------------------------------------------------------

PID = 94880  # LastWar.exe — re-resolve with find_win() if the client restarted

# Revives to spend per run to extend it (0..3). Distance carries over each revive, so
# more revives → more metres, at 100 parkour coins each. Set via the `run` CLI args —
# env vars are NOT used because WSL does not export them to the Windows Python.
REVIVES_PER_RUN = 0
DEBUG = False


def _win_libs():
    import mss  # noqa: F401
    import win32api  # noqa: F401
    import win32con  # noqa: F401
    import win32gui  # noqa: F401
    import win32process  # noqa: F401
    return mss, win32api, win32con, win32gui, win32process


def _game_pid() -> int:
    """Live LastWar.exe pid — the client self-restarts into new pids, so never trust a
    hardcoded one. Falls back to the PID constant if the probe helper is unavailable."""
    try:
        from il2cpp_probe import find_game_pid
        return find_game_pid()
    except Exception:
        return PID


def find_win(pid: int | None = None):
    if pid is None:
        pid = _game_pid()
    _, win32api, win32con, win32gui, win32process = _win_libs()
    hs = []
    minimized = []      # the game window when minimized sits off-screen at ~(-32000,-32000)

    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            _, p = win32process.GetWindowThreadProcessId(h)
            if p == pid:
                r = win32gui.GetWindowRect(h)
                if r[2] - r[0] > 200 and r[3] - r[1] > 200:
                    hs.append((h, r))
                elif win32gui.GetWindowText(h) == "Last War-Survival Game":
                    minimized.append(h)
        return True

    win32gui.EnumWindows(cb, None)
    if hs:
        return hs[0]
    # No usable window but the client is minimized — restore it (input needs it on-screen)
    if minimized:
        h = minimized[0]
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        try:
            win32gui.ShowWindow(h, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(h)
        except Exception:
            pass
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.6)
        r = win32gui.GetWindowRect(h)
        if r[2] - r[0] > 200 and r[3] - r[1] > 200:
            return (h, r)
    return (None, None)


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


# --- perception (v2, calibrated on results/street_run/frames/rec_*.png) -------
# Frame is the full client window (≈1531×997). Everything below is a fraction of
# W/H so it survives a resize. The cartoon palette makes a fixed colour threshold
# useless and even per-pixel classification unreliable (gold coins ≈ brown barrels;
# a white crosswalk ≈ a pale concrete barrier). v2 therefore leans on TWO robust
# ideas instead of a perfect pixel label:
#   1. Blob geometry — a real obstacle is a large, solid component; coins are small
#      round blobs, lane dashes/crosswalks are thin, poles are thin diagonals. Filter
#      the obstacle mask by connected-component size and shape.
#   2. Differential decide() — the game always leaves a passable lane, so an obstacle
#      manifests as ONE lane much more blocked than a neighbour. A row that blocks all
#      three lanes equally is a ground marking (crosswalk) or noise, not a wall: hold.
# Calibration facts (rec_*.png, server 935): avatar wears a saturated BLUE helmet,
# sits centre (x≈0.49·W, y≈0.62·H); asphalt is H≈15 S≈75 V≈140; concrete barriers are
# brighter + desaturated (V≈170 S≈50); trucks are vivid off-brown hues; barrels are
# muted brown with dark banding; coins are bright gold (S>180 V>180).

_HELMET_LO = (95, 110, 80)      # HSV lower for the blue helmet
_HELMET_HI = (125, 255, 255)
_LANE_SPLIT = (0.45, 0.55)      # avatar px<.45 → left(0), .45–.55 → centre(1), >.55 → right(2)
# danger band ahead of the avatar (nearest→farthest); farther depths give lead time
_BAND_DEPTHS = (0.32, 0.38, 0.44, 0.50, 0.55)
_OBST_THRESH = 0.14             # per-lane blocked fraction that means "blocked"
_ROAD_HUE = 16                  # asphalt hue (brownish grey)
_SCALE = 2                      # process at 1/_SCALE resolution for speed


def _to_bgr(img):
    """mss screenshot → BGR uint8 ndarray."""
    import numpy as np
    a = np.frombuffer(img.bgra, np.uint8).reshape(img.height, img.width, 4)
    return a[:, :, :3]


def _lane_centres(yr: float):
    """3 lane x-centres at depth yr, converging toward the vanishing point."""
    t = max(0.0, min(1.0, (yr - 0.28) / (0.60 - 0.28)))
    spread = 0.03 + (0.14 - 0.03) * t
    return (0.5 - spread, 0.5, 0.5 + spread)


def _obstacle_mask(hsv, H, W):
    """Binary mask of real obstacles inside the road trapezoid, coins/markings/poles
    filtered out by colour + connected-component shape. Returns (mask, road_s, road_v)."""
    import cv2, numpy as np
    hue = hsv[:, :, 0].astype(np.int16)
    sat = hsv[:, :, 1].astype(np.int16)
    val = hsv[:, :, 2].astype(np.int16)
    # robust asphalt reference: median over a wide low road band (asphalt dominates,
    # so stray coins/markings don't move the median — unlike a single centre patch,
    # which the coin trail sits right on top of).
    band = hsv[int(H * 0.46):int(H * 0.60), int(W * 0.30):int(W * 0.70)]
    road_s = float(np.median(band[:, :, 1])); road_v = float(np.median(band[:, :, 2]))
    huedist = np.minimum(np.abs(hue - _ROAD_HUE), 180 - np.abs(hue - _ROAD_HUE))
    colored = (huedist > 22) & (sat > 70)                       # trucks (blue/red/green)
    pale = (val > road_v + 22) & (sat < road_s - 10) & (sat > 30)  # concrete (not pure-white markings)
    dark = val < road_v - 42                                    # undersides, deep shadow, cast shadows (barrels)
    highsat = (sat > road_s + 78) & (val > 90)                  # barrels, orange barriers & vivid props
    # NB: do NOT colour-carve coins here — a LIT barrel is bright saturated gold, pixel-
    # identical to a coin (both H≈18 S≈170 V≈220). Carving gold pixels deletes the barrel
    # and kills the run. Coins are told apart from barrels/barriers by WIDTH below: a coin
    # is a narrow blob (~0.02·W), a barrel/barrier is wide (>0.06·W).
    m = (colored | pale | dark | highsat).astype(np.uint8) * 255
    # keep only the road trapezoid — drops sky, buildings, sidewalks
    roi = np.zeros((H, W), np.uint8)
    pts = np.array([[int(W * 0.43), int(H * 0.30)], [int(W * 0.57), int(H * 0.30)],
                    [int(W * 0.78), int(H * 0.61)], [int(W * 0.22), int(H * 0.61)]], np.int32)
    cv2.fillConvexPoly(roi, pts, 255)
    m = cv2.bitwise_and(m, roi)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    # shape filter: keep solid chunky obstacles; drop coins (narrow gold), thin markings,
    # thin diagonal poles.
    n, lbl, st, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    a_min = (H * W) * 0.00035        # ~scale-invariant minimum obstacle area
    coin_w = W * 0.055              # gold blobs narrower than this are coins, not barrels
    for i in range(1, n):
        a = st[i, cv2.CC_STAT_AREA]
        w = st[i, cv2.CC_STAT_WIDTH]; h = st[i, cv2.CC_STAT_HEIGHT]
        if a < a_min:
            continue
        ar = w / max(h, 1); sol = a / max(w * h, 1)
        if ar > 2.4 and h < H * 0.06:      # thin & wide → crosswalk stripe / lane dash
            continue
        if sol < 0.22:                     # thin diagonal → lamp pole / lane line
            continue
        comp = lbl == i
        mh = float(np.median(hue[comp])); ms = float(np.median(sat[comp])); mv = float(np.median(val[comp]))
        gold = (10 <= mh <= 26) and ms > 150 and mv > 165
        if gold and w < coin_w:            # narrow bright-gold blob → coin trail, safe
            continue
        keep[comp] = 255
    return keep, road_s, road_v


def detect(img) -> dict:
    """{'player_lane': 0|1|2|None, 'blocked': [f,f,f] (0..1 per lane), 'dead': bool}."""
    import cv2, numpy as np
    bgr = _to_bgr(img)
    if _SCALE != 1:
        bgr = cv2.resize(bgr, (bgr.shape[1] // _SCALE, bgr.shape[0] // _SCALE),
                         interpolation=cv2.INTER_AREA)
    H, W = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    # dead: the «Испытание окончено» card is a big near-white panel centre-screen
    card = hsv[int(H * 0.20):int(H * 0.46), int(W * 0.34):int(W * 0.66)]
    near_white = ((card[:, :, 1] < 60) & (card[:, :, 2] > 205)).mean()
    dead = near_white > 0.25

    # player lane from the blue-helmet centroid in the bottom-centre ROI
    m = cv2.inRange(hsv, _HELMET_LO, _HELMET_HI)
    roi = np.zeros((H, W), np.uint8)
    roi[int(H * 0.50):int(H * 0.72), int(W * 0.32):int(W * 0.68)] = 255
    m = cv2.bitwise_and(m, roi)
    xs = np.where(m > 0)[1]
    if len(xs) >= 40:
        px = xs.mean() / W
        player = 0 if px < _LANE_SPLIT[0] else (2 if px > _LANE_SPLIT[1] else 1)
    else:
        player = None

    keep, _, _ = _obstacle_mask(hsv, H, W)
    blocked = [0.0, 0.0, 0.0]
    for yr in _BAND_DEPTHS:
        y = int(H * yr); dy = max(2, int(H * 0.030)); dx = max(2, int(W * 0.035))
        for lane, cx in enumerate(_lane_centres(yr)):
            x = int(W * cx)
            frac = keep[y - dy:y + dy, x - dx:x + dx].mean() / 255.0
            if frac > blocked[lane]:
                blocked[lane] = frac

    # Is the obstacle dead ahead LOW (a barrel — hoppable) or TALL (an orange/concrete
    # barrier — a jump into it is fatal, proven live)? Height proxy = the topmost
    # obstacle-pixel y in the player's near-lane column. A barrel's top sits low
    # (y≳0.52·H); a barrier/truck rises higher (y≲0.46·H). Only a LOW obstacle is jumpable.
    low_ahead = False
    if player is not None:
        cx = _lane_centres(0.50)[player]
        x = int(W * cx); dx = max(2, int(W * 0.05))
        col = keep[int(H * 0.40):int(H * 0.62), max(0, x - dx):x + dx]
        rows = np.where(col.any(axis=1))[0]
        if len(rows):
            top = (int(H * 0.40) + int(rows.min())) / H
            low_ahead = top > 0.50
    return {"player_lane": player, "blocked": blocked, "dead": dead, "low_ahead": low_ahead}


# Jump policy. JUMP_TH = the player-lane fill above which we JUMP when no genuinely-clear
# side lane exists (barrels / low barriers are ground obstacles the avatar can hop). Set
# lower to jump more eagerly. TARGET_CLEAR = a side lane must be at least this empty to be
# worth switching into (a relatively-better but still-blocked lane is a trap).
JUMP_TH = 0.28
TARGET_CLEAR = 0.22
# Boxed-in action when NO clear side lane and the obstacle looks LOW/hoppable. Height
# gating matters: a jump into a TALL orange/concrete barrier is fatal (proven live), so
# blind jumping is worse than holding — only jump a low obstacle. 'down' (slide) is left
# available for testing but OFF by default: whether the game's barriers are slide-under
# is unverified (the live test was cut short by a concurrent-login session kick).
BOXED_ACTION = "up"      # 'up' (jump low obstacle) | 'down' (slide) | 'none' (hold)


def decide(state: dict) -> str | None:
    """Prefer stepping into a genuinely-clear side lane; if boxed with a LOW obstacle dead
    ahead, jump it (a barrel is hoppable — but a tall barrier is not, so we gate on
    height). A row blocked ~equally across all lanes is a crosswalk/marking artifact →
    hold. Returns 'left'|'right'|'up'|'down'|None."""
    pl = state.get("player_lane")
    b = state.get("blocked") or [0.0, 0.0, 0.0]
    if pl is None:
        return None
    LOW = 0.12                           # own lane this clear → no need to move
    MARGIN = 0.10                        # a neighbour must beat the current lane by this much
    if b[pl] < LOW:
        return None
    if pl == 1:
        cand = [(0, "left"), (2, "right")]
    elif pl == 0:
        cand = [(1, "right")]
    else:
        cand = [(1, "left")]
    best = min(cand, key=lambda c: b[c[0]])   # least-blocked reachable lane
    # step aside only if the target lane is both clearer AND genuinely open
    if b[best[0]] < b[pl] - MARGIN and b[best[0]] < TARGET_CLEAR:
        return best[1]
    # boxed in (no open side lane). Only act on a LOW obstacle — jumping a tall barrier
    # kills the run; holding at least doesn't make it worse.
    if b[pl] > JUMP_TH and BOXED_ACTION != "none":
        if BOXED_ACTION == "up" and not state.get("low_ahead"):
            return None                  # tall obstacle → a jump won't clear it → hold
        return BOXED_ACTION
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


class _FileImg:
    """Adapter so detect() can run on a saved PNG (offline detector tuning)."""
    def __init__(self, path):
        import cv2, numpy as np
        bgr = cv2.imread(path)
        self.height, self.width = bgr.shape[:2]
        self.bgra = np.dstack([bgr, np.full((self.height, self.width), 255, np.uint8)]).tobytes()


def cmd_test(pattern="rec_"):
    """Offline: run detect()/decide() on saved gameplay frames and write annotated
    copies to results/street_run/annot_*.png. No game window, no attempts spent —
    the loop for tuning the detector before burning a live run."""
    import cv2, glob, os
    frames = sorted(glob.glob(f"results/street_run/frames/{pattern}*.png"))
    outdir = os.path.join("results", "street_run")
    lane_names = {0: "L", 1: "C", 2: "R", None: "?"}
    for f in frames:
        img = _FileImg(f)
        s = detect(img)
        if s["dead"]:
            continue
        key = decide(s)
        b = s["blocked"]; pl = s["player_lane"]
        print(f"{os.path.basename(f):16s} pl={lane_names[pl]} "
              f"blocked=[{b[0]:.2f},{b[1]:.2f},{b[2]:.2f}] -> {key}")
        vis = cv2.imread(f); H, W = vis.shape[:2]
        for yr in _BAND_DEPTHS:
            for lane, cx in enumerate(_lane_centres(yr)):
                x = int(W * cx); y = int(H * yr)
                col = (0, 0, 255) if b[lane] > _OBST_THRESH else (0, 200, 0)
                cv2.circle(vis, (x, y), 6, col, 2)
        cv2.putText(vis, f"pl={lane_names[pl]} {b[0]:.2f}/{b[1]:.2f}/{b[2]:.2f} {key}",
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        cv2.imwrite(os.path.join(outdir, "annot_" + os.path.basename(f)), vis)
    print("annotated frames -> results/street_run/annot_*.png")
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
        # reflex loop until death, reviving up to REVIVES_PER_RUN times to extend the
        # same run (distance carries over). A short ring keeps the frame just before
        # death so the killing obstacle can be studied offline (death_*.png).
        import mss.tools
        dbg = None
        if DEBUG:
            dbg = open(os.path.join(outdir, f"debug_{attempt:02d}.log"), "w", encoding="utf-8")
        life = 0
        frames = 0
        t0 = time.time()
        while True:
            cooldown = 0.0
            deadline = time.time() + 180
            prev = None
            while time.time() < deadline:
                img = grab(h)[0]
                s = detect(img)
                if s["dead"]:
                    break
                prev = img
                now = time.time()
                key = None
                if now >= cooldown:
                    key = decide(s)
                    if key:
                        press(key)
                        cooldown = now + 0.18   # let the lane change settle before re-deciding
                frames += 1
                if dbg is not None:
                    b = s["blocked"]
                    dbg.write(f"{now - t0:6.2f} pl={s['player_lane']} "
                              f"b=[{b[0]:.2f},{b[1]:.2f},{b[2]:.2f}] key={key}\n")
                    dbg.flush()
            # snapshot the frame that killed this life (for offline failure analysis)
            if prev is not None:
                mss.tools.to_png(prev.rgb, prev.size, output=os.path.abspath(
                    os.path.join("results", "street_run", f"death_{attempt:02d}_{life}.png")))
            if life < REVIVES_PER_RUN:
                time.sleep(1.2)          # let the «Испытание окончено» popup render
                focus(h); time.sleep(0.2)
                revive(h)                # click «Воскрешение ×100»
                # wait for the runner scene to resume (popup gone, avatar back)
                resumed = False
                t_res = time.time() + 8
                while time.time() < t_res:
                    d = detect(grab(h)[0])
                    if not d["dead"] and d.get("player_lane") is not None:
                        resumed = True; break
                    time.sleep(0.2)
                if resumed:
                    life += 1
                    focus(h)
                    continue
            break
        fps = frames / max(time.time() - t0, 0.01)
        if dbg is not None:
            dbg.close()
        # record the result: snapshot the «Испытание окончено» popup + read best
        grab(h, os.path.join("street_run", f"result_{attempt:02d}.png"))
        st = read_state()
        best = st.get("highest", "?")
        remaining = int(st.get("remainTimes") or remaining - 1)
        line = (f"attempt {attempt}: remaining={remaining} best={best} fps={fps:.1f} "
                f"(popup=results/street_run/result_{attempt:02d}.png)")
        log.write(line + "\n"); log.flush()
        print(line)
        _dismiss_popup(); time.sleep(0.6)   # clear the popup before the next start
    print(f"Stopped with {remaining} attempts in reserve. Best distance: "
          f"{read_state().get('highest', '?')}")
    log.close()
    return 0


# ---------------------------------------------------------------------------
# Lua-reader autopilot (replaces the vision detect()/decide() with an exact,
# look-ahead read of SurfingMonsterManager.showList — see tools/lib/surfing_reader.py)
# ---------------------------------------------------------------------------

def _read_loop(reader, h, log, dbg, revives: int):
    """One life+revives with the Lua reader driving the dodge. Returns the last player z
    reached (a distance proxy). Death is detected when player Z stalls (it climbs at
    ~speed/s while alive)."""
    import time as _t
    from surfing_reader import decide
    life = 0
    last_z = -1.0
    z_stall_t = _t.time()
    cooldown = 0.0
    while True:
        deadline = _t.time() + 240
        while _t.time() < deadline:
            s = reader.read()
            now = _t.time()
            if not s.get("ok"):
                # scene not readable (between lives / loading). Treat a long gap as death.
                if now - z_stall_t > 2.0:
                    break
                _t.sleep(0.1)
                continue
            _, pz = s["player"]
            if pz > last_z + 0.05:
                last_z = pz
                z_stall_t = now
            elif now - z_stall_t > 1.2:       # z frozen ~1.2 s → dead (or paused)
                break
            key = None
            if now >= cooldown:
                key = decide(s)
                if key:
                    press(key)
                    cooldown = now + 0.16
            if dbg is not None:
                near = [o for o in s["obstacles"] if o["obstacle"] and o["dz"] > -6][:4]
                brief = " ".join("%s@L%d/%.0f" % (o["kind"], o["lane"], o["dz"]) for o in near)
                dbg.write("z=%.1f lane=%d key=%s | %s\n" % (pz, s["lane"], key, brief))
                dbg.flush()
        # life ended
        if life < revives:
            _t.sleep(1.2); focus(h); _t.sleep(0.2)
            revive(h)
            resumed = False
            t_res = _t.time() + 8
            while _t.time() < t_res:
                d = reader.read()
                if d.get("ok"):
                    resumed = True; break
                _t.sleep(0.2)
            if resumed:
                life += 1; z_stall_t = _t.time(); focus(h); continue
        break
    return last_z


def cmd_readtest(secs: float = 8.0):
    """OBSERVE-ONLY proof: install the reader, start ONE run, and print the live obstacle
    field + what decide() WOULD do — no key presses. Confirms the Lua read replaces vision.
    Costs one attempt."""
    from lua_client import get_evaluator
    from surfing_reader import SurfReader, decide, lane_threats
    st = read_state(fetch=True)
    if not event_open(st):
        print("Event «Уличный забег» is not open — cannot readtest."); return 2
    ev = get_evaluator()
    reader = SurfReader(ev)
    try:
        reader.install()
        _eval(_START_LUA, settle=2.0)
        print("run started; reading scene (observe-only, no input)...")
        t_end = time.time() + secs
        n = 0
        while time.time() < t_end:
            s = reader.read()
            if not s.get("ok"):
                print("  [read] %s" % s.get("reason")); time.sleep(0.15); continue
            near, jump = lane_threats(s)
            hazards = [o for o in s["obstacles"] if o["obstacle"] and o["dz"] > -6][:5]
            desc = ", ".join("%s L%d dz=%.0f%s" % (o["kind"], o["lane"], o["dz"],
                             "(hop)" if o["jumpable"] else "") for o in hazards)
            print("  z=%.1f lane=%d near=%s -> %s | %s"
                  % (s["player"][1], s["lane"],
                     [None if v is None else round(v) for v in near], decide(s), desc))
            n += 1
            time.sleep(0.12)
        print("read %d frames" % n)
    finally:
        ev.close()
    return 0


def cmd_runlua(reserve: int = 5, revives: int = 0):
    """Autopilot driven by the Lua scene reader (no vision). Keeps `reserve` attempts,
    spends `revives` per run. Presses arrows via pydirectinput, so the window is focused."""
    from lua_client import get_evaluator
    from surfing_reader import SurfReader
    st = read_state(fetch=True)
    if not event_open(st):
        print("Event «Уличный забег» is not open (activityId=nil)."); return 2
    h, _ = find_win()
    if h is None:
        print("no game window"); return 1
    outdir = os.path.join("results", "street_run")
    os.makedirs(outdir, exist_ok=True)
    log = open(os.path.join(outdir, "runs_lua.log"), "a", encoding="utf-8")
    ev = get_evaluator()
    reader = SurfReader(ev)
    remaining = int(st.get("remainTimes") or 0)
    print("Event open, %d attempt(s); best %s. Reserve=%d revives=%d (LUA reader)"
          % (remaining, st.get("highest", "?"), reserve, revives))
    attempt = 0
    try:
        reader.install()
        while remaining > reserve:
            attempt += 1
            focus(h); time.sleep(0.3)
            _eval(_START_LUA, settle=2.0)          # start_run
            # wait for the scene to become readable
            loaded = False
            t_load = time.time() + 10
            while time.time() < t_load:
                if reader.read().get("ok"):
                    loaded = True; break
                time.sleep(0.2)
            if not loaded:
                print("attempt %d: scene did not load" % attempt)
                _dismiss_popup(); remaining = int(read_state().get("remainTimes") or remaining - 1)
                continue
            focus(h); time.sleep(0.2)
            dbg = open(os.path.join(outdir, "runlua_%02d.log" % attempt), "w", encoding="utf-8") if DEBUG else None
            reached = _read_loop(reader, h, log, dbg, revives)
            if dbg is not None:
                dbg.close()
            st = read_state()
            best = st.get("highest", "?")
            remaining = int(st.get("remainTimes") or remaining - 1)
            line = ("attempt %d: reached~z=%.0f remaining=%d best=%s"
                    % (attempt, reached, remaining, best))
            log.write(line + "\n"); log.flush(); print(line)
            _dismiss_popup(); time.sleep(0.6)
    finally:
        ev.close(); log.close()
    print("Stopped with %d attempts in reserve. Best: %s"
          % (remaining, read_state().get("highest", "?")))
    return 0


def main(argv):
    global REVIVES_PER_RUN, DEBUG, BOXED_ACTION
    cmd = argv[0] if argv else "probe"
    if cmd == "probe":
        return cmd_probe()
    if cmd == "readtest":
        return cmd_readtest(float(argv[1]) if len(argv) > 1 else 8.0)
    if cmd == "runlua":
        if len(argv) > 3 and argv[3] in ("1", "debug", "true"):
            DEBUG = True
        return cmd_runlua(int(argv[1]) if len(argv) > 1 else 5,
                          int(argv[2]) if len(argv) > 2 else 0)
    if cmd == "test":
        return cmd_test(argv[1] if len(argv) > 1 else "rec_")
    if cmd == "shot":
        return cmd_shot(argv[1] if len(argv) > 1 else "sr_now.png")
    if cmd == "watch":
        return cmd_watch(float(argv[1]) if len(argv) > 1 else 300.0)
    if cmd == "calibrate":
        return cmd_calibrate(int(argv[1]) if len(argv) > 1 else 60)
    if cmd == "record":
        return cmd_record(int(argv[1]) if len(argv) > 1 else 120)
    if cmd == "run":
        # run [reserve] [revives] [debug] [boxed_action]
        if len(argv) > 2:
            REVIVES_PER_RUN = max(0, min(3, int(argv[2])))
        if len(argv) > 3 and argv[3] in ("1", "debug", "true"):
            DEBUG = True
        if len(argv) > 4 and argv[4] in ("up", "down", "none"):
            BOXED_ACTION = argv[4]
        return cmd_run(int(argv[1]) if len(argv) > 1 else 5)
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
