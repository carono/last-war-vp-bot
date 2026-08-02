#!/usr/bin/env python3
r"""Resilient recorder for HUMAN-played Street Run runs.

The in-driver record loop kept crashing on long expert runs — a daemon round-trip hiccups on a
multi-minute poll, and the Windows console choked on a non-ASCII tick. This standalone loop is
hardened for exactly that: it reconnects through transient evaluator errors and prints ASCII
only. It arms recording (bot observes, never drives), waits for the human to start a run,
follows it to the end, drains the perceived-field frames to results/street_run/human/run_NNN.txt,
then re-arms for the next — until no new run starts for a while (the human is done).

Two things a recorder of somebody else's play must not do, and this one does not:

* **Do not poll while the run is on.** Every read hijacks the game's main thread; at the old
  two-a-second cadence that is a stutter every half second in a run the person is trying to
  set a record with. The end of a run is not urgent news — it is polled at `--poll` seconds
  (default 10), and the frames are safe until then because of the next point.
* **Do not lose a run to the next one.** The planner clears its frame buffer in `OnStart`, so
  a person who dies and immediately presses Start again used to erase the run that had just
  finished before it could be drained. A second `OnStart` wrapper installed here stashes the
  finished buffer first, so the drain can happen whenever there is a quiet moment — draining
  is ~900 log lines inside one frame and is only ever done between runs.

Each run is saved with a header naming the session, the wall clock, the distance and what the
event had left at that moment, and one line goes into results/street_run/human/index.tsv. The
header is a `#` comment line, which every reader of these files skips (they need eight
`|`-separated fields), so `surfing_offline.py human run_004` keeps working.

    C:\Python312\python.exe tools\dev\record_human_loop.py
    C:\Python312\python.exe tools\dev\record_human_loop.py --label live1169 --poll 10
"""
from __future__ import annotations
import argparse
import glob
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_ROOT, "tools", "lib"))
sys.path.insert(0, os.path.join(_ROOT, "tools"))
from lua_client import get_evaluator  # noqa: E402
from street_run_ai import install as install_ai  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MARK = "SRAI "
HUMAN_DIR = os.path.join(_ROOT, "results", "street_run", "human")
INDEX = os.path.join(HUMAN_DIR, "index.tsv")
IDLE_EXIT = 900.0   # seconds without a new run before we assume the person is done

# Observe only: the planner keeps perceiving and recording, and never touches the controls.
_ARM = ('local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end\n'
        'local AI=_G.__SR_AI if not AI then L("ST armed=0") return end\n'
        'AI.enabled=false AI.record=true AI.done=AI.done or {} AI.seq=AI.seq or 0\n'
        'L("ST armed=1")')

# The stash. `surfing_ai.lua` already wraps OnStart and clears AI.frames there; this wraps that
# wrapper and moves the finished buffer aside first, so a run survives until it is drained even
# if the next one has already started. Idempotent — the guard is on the module table, which
# outlives a re-install, and only a fresh Lua VM (a game restart) puts it back.
_HOOK = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
local AI = _G.__SR_AI
if not AI then L("ST hook=0") return end
AI.done = AI.done or {}
AI.seq = AI.seq or 0
local ok, SL = pcall(require, "DataCenter.LWBattle.Logic.Surfing.SurfingLogic")
if not ok or not SL then L("ST hook=0") return end
if SL.__srrec == nil then
  SL.__srrec = SL.OnStart
  SL.OnStart = function(self, ...)
    local A = _G.__SR_AI
    if A then
      local F = A.frames or {}
      if A.record and #F > 0 then
        A.done[#A.done + 1] = {seq = A.seq, frames = F, z = (A.stat and A.stat.maxz) or 0}
        while #A.done > 6 do table.remove(A.done, 1) end
      end
      A.seq = (A.seq or 0) + 1
    end
    return SL.__srrec(self, ...)
  end
end
L("ST hook=1")
"""

_STATUS = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
local AI = _G.__SR_AI
if not AI then L("ST installed=0") return end
local s = AI.stat or {}
L(string.format("ST installed=1 rec=%s state=%s z=%.1f maxz=%.1f dead=%s frames=%d seq=%d done=%d",
  tostring(AI.record), tostring(s.state), s.z or 0, s.maxz or 0, tostring(s.dead),
  #(AI.frames or {}), AI.seq or 0, #(AI.done or {})))
"""

# One finished run out of the stash, oldest first. Expensive (one log line per frame, all inside
# a single game frame), so the loop only ever calls it between runs.
_DRAIN_STASH = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
local AI = _G.__SR_AI
local D = AI and AI.done or {}
if #D == 0 then L("RUN none") return end
local r = table.remove(D, 1)
L(string.format("RUN seq=%s z=%.1f n=%d", tostring(r.seq), r.z or 0, #r.frames))
for i = 1, #r.frames do L("FRAME " .. r.frames[i]) end
L("END")
"""

# The run that has just ended and was never stashed (no OnStart followed it). Clearing the buffer
# here is what keeps it from being saved a second time.
_DRAIN_LIVE = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
local AI = _G.__SR_AI
if not AI then L("RUN none") return end
local F = AI.frames or {}
if #F == 0 then L("RUN none") return end
L(string.format("RUN seq=%s z=%.1f n=%d", tostring(AI.seq), (AI.stat and AI.stat.maxz) or 0, #F))
for i = 1, #F do L("FRAME " .. F[i]) end
AI.frames = {}
L("END")
"""

_META = r"""
local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end
local m = DataCenter.LWSurfingDataManager
local function try(k, fn) local ok, v = pcall(fn) L("ST " .. k .. "=" .. (ok and tostring(v) or "nil")) end
try("remain", function() return m:GetRemainTimes() end)
try("best", function() return m:GetPersonalHightestScoreData() end)
try("act", function() return m:GetActId() end)
"""


class Bridge:
    """A get_evaluator() wrapper that reconnects on any error, so a daemon hiccup on a long
    poll never kills the recording."""
    def __init__(self):
        self.ev = get_evaluator()

    def run(self, chunk, settle):
        # BaseException, not Exception: a failed reconnect ends in `raise SystemExit(...)`
        # deep in the local evaluator's game-process probe, and catching only Exception let
        # that kill a recording mid-session with nothing but exit code 1 to show for it.
        for _ in range(4):
            try:
                return list(self.ev.run(chunk, marker=MARK, settle=settle))
            except BaseException as exc:
                print("  reconnect (%s)" % exc)
                try:
                    self.ev.close()
                except BaseException:
                    pass
                time.sleep(2.0)
                try:
                    self.ev = get_evaluator()
                except BaseException as exc2:
                    print("  evaluator unavailable (%s)" % exc2)
        return []

    def kv(self, chunk, settle=0.3):
        out = {}
        for ln in self.run(chunk, settle):
            if "SRAI ST " in ln:
                for part in ln.split("SRAI ST ", 1)[-1].split():
                    if "=" in part:
                        k, v = part.split("=", 1)
                        out[k] = v
        return out

    def status(self):
        return self.kv(_STATUS)

    def meta(self):
        return self.kv(_META, settle=0.4)


def _next_run_no() -> int:
    """The next free run_NNN, read off the directory so a restart never overwrites."""
    used = [0]
    for path in glob.glob(os.path.join(HUMAN_DIR, "run_*.txt")):
        m = re.search(r"run_(\d+)\.txt$", os.path.basename(path))
        if m:
            used.append(int(m.group(1)))
    return max(used) + 1


def _save(frames, dist, meta, label, note=""):
    """One run to its own file, with a header naming it, plus a line in the index."""
    os.makedirs(HUMAN_DIR, exist_ok=True)
    no = _next_run_no()
    path = os.path.join(HUMAN_DIR, "run_%03d.txt" % no)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    # No `|` anywhere in this line: a frame is eight `|`-separated fields, and every reader of
    # these files skips a line by counting them. A header punctuated with pipes counts as a
    # frame and lands in the parser as `float('# run_004 ')`.
    header = ("# run_%03d  %s  label=%s  human-played  %.0f m  %d frames  "
              "attempts-left=%s  best=%s%s"
              % (no, stamp, label, dist, len(frames),
                 meta.get("remain", "?"), meta.get("best", "?"),
                 ("  " + note) if note else ""))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header + "\n")
        fh.write("\n".join(frames) + "\n")
    new_index = not os.path.exists(INDEX)
    with open(INDEX, "a", encoding="utf-8") as fh:
        if new_index:
            fh.write("file\twhen\tlabel\tsource\tmetres\tframes\tattempts_left\tbest\tnote\n")
        fh.write("%s\t%s\t%s\thuman\t%.0f\t%d\t%s\t%s\t%s\n"
                 % (os.path.basename(path), stamp, label, dist, len(frames),
                    meta.get("remain", "?"), meta.get("best", "?"), note))
    print("[saved] %s: %.0f m, %d frames" % (os.path.basename(path), dist, len(frames)))
    return path


def _collect(b, chunk):
    """Drain one run out of the VM: (frames, distance) or (None, 0) when there was nothing."""
    frames, dist = [], 0.0
    for ln in b.run(chunk, 6.0):
        if "SRAI FRAME " in ln:
            frames.append(ln.split("SRAI FRAME ", 1)[-1].rstrip())
        elif "SRAI RUN " in ln:
            body = ln.split("SRAI RUN ", 1)[-1]
            if body.startswith("none"):
                return None, 0.0
            for part in body.split():
                if part.startswith("z="):
                    dist = float(part[2:])
    if not frames:
        return None, 0.0
    return frames, dist


def _drain_stashed(b, label):
    """Everything already finished and set aside, oldest first."""
    saved = 0
    while True:
        frames, dist = _collect(b, _DRAIN_STASH)
        if frames is None:
            return saved
        _save(frames, dist, b.meta(), label, note="stashed (next run had already started)")
        saved += 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--label", default="live", help="tag written into every run's header")
    ap.add_argument("--poll", type=float, default=5.0,
                    help="seconds between reads WHILE A RUN IS ON (default 5; each read "
                         "hijacks the game's main thread, so keep it coarse — the gap "
                         "between two runs can be shorter than this, which is what the "
                         "OnStart stash is there for)")
    ap.add_argument("--idle", type=float, default=IDLE_EXIT,
                    help="stop after this many seconds with no new run (default 900)")
    args = ap.parse_args(argv)

    os.makedirs(HUMAN_DIR, exist_ok=True)
    b = Bridge()
    if b.status().get("installed") != "1":
        print("planner not in the VM yet - installing it (observe only)")
        if not install_ai(b.ev):
            print("install failed - is the game up and the daemon attached?")
            return 1
    if b.kv(_ARM, 0.4).get("armed") != "1":
        print("arming failed - the planner is not in the VM")
        return 1
    hook = b.kv(_HOOK, 0.5)
    if hook.get("hook") != "1":
        print("WARNING: the OnStart stash did not install - a run started before its "
              "predecessor is drained would be lost")
    meta = b.meta()
    print("RECORDER ARMED (observe only, the bot never drives). event=%s attempts-left=%s best=%s"
          % (meta.get("act"), meta.get("remain"), meta.get("best")))
    print("Play your runs one after another - each one saves itself to %s." % HUMAN_DIR)
    print("Stop by not starting a new run for %ds (or Ctrl-C)." % args.idle)
    # Nothing is drained here on purpose: a restart mid-session must not dump ~900 log lines
    # into the frame of a run somebody is in the middle of. The loop drains between runs.

    seq = int(b.status().get("seq") or 0)
    idle_since = time.time()
    prev_frames = -1
    while True:
        try:
            st = b.status()
        except Exception as exc:
            print("  loop error, retrying (%s)" % exc)
            time.sleep(2.0)
            continue
        if st.get("installed") != "1":
            # the game restarted: the VM is fresh, so put the planner and the stash back
            print("VM lost the planner (game restart?) - reinstalling")
            try:
                install_ai(b.ev)
                b.run(_ARM, 0.4)
                b.kv(_HOOK, 0.5)
            except Exception as exc:
                print("  reinstall failed (%s)" % exc)
            time.sleep(3.0)
            continue
        cur = int(st.get("seq") or 0)
        running = st.get("state") == "3" and st.get("dead") != "true"
        if cur != seq:
            seq = cur
            idle_since = time.time()
        n_frames = int(st.get("frames") or 0)
        if running:
            print("    running: z=%s m, frames=%s" % (st.get("z"), st.get("frames")))
            idle_since = time.time()
            prev_frames = n_frames
            time.sleep(args.poll)
            continue
        # not running: this is the quiet moment to write anything that is waiting
        saved = _drain_stashed(b, args.label)
        # A run is only over when its buffer has stopped growing. Without that check a poll
        # landing in the moment a run is loading — ticking already, `state` not yet 3 — would
        # drain it half-way and split one run across two files.
        settled = n_frames > 0 and n_frames == prev_frames
        prev_frames = n_frames
        if settled:
            frames, dist = _collect(b, _DRAIN_LIVE)
            if frames is not None:
                _save(frames, dist, b.meta(), args.label)
                saved += 1
                prev_frames = 0
        if saved:
            idle_since = time.time()
            print("Ready for the next run.")
        if time.time() - idle_since > args.idle:
            print("No new run for %ds - stopping." % args.idle)
            return 0
        time.sleep(2.0)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nstopped by hand")
