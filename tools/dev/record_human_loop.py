#!/usr/bin/env python3
r"""Resilient recorder for HUMAN-played Street Run runs.

The in-driver record loop kept crashing on long expert runs — a daemon round-trip hiccups on a
multi-minute poll, and the Windows console choked on a non-ASCII tick. This standalone loop is
hardened for exactly that: it reconnects through transient evaluator errors and prints ASCII
only. It arms recording (bot observes, never drives), waits for the human to start a run,
follows it to the end, drains the perceived-field frames to results/street_run/human/run_NNN.txt,
then re-arms for the next — until no new run starts for a while (the human is done).

    C:\Python312\python.exe tools\dev\record_human_loop.py
"""
from __future__ import annotations
import glob
import os
import sys
import time

sys.path.insert(0, os.path.join("tools", "lib"))
from lua_client import get_evaluator  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MARK = "SRAI "
HUMAN_DIR = os.path.join("results", "street_run", "human")
IDLE_EXIT = 200.0   # seconds without a new run before we assume the human is done

_ARM = ('local AI=_G.__SR_AI if not AI then return end\n'
        'AI.enabled=false AI.record=true AI.frames={}\n'
        'CS.UnityEngine.Debug.LogError("SRAI ST armed=1")')
_STATUS = ('local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end\n'
           'local AI=_G.__SR_AI local s=AI and AI.stat or {}\n'
           'L(string.format("ST state=%s z=%s dead=%s frames=%s", tostring(s.state),'
           ' tostring(s.z), tostring(s.dead), tostring(AI and #(AI.frames or {}))))')
_DRAIN = ('local function L(s) CS.UnityEngine.Debug.LogError("SRAI "..tostring(s)) end\n'
          'local AI=_G.__SR_AI local Fr=AI and AI.frames or {}\n'
          'for i=1,#Fr do L("FRAME "..Fr[i]) end')


class Bridge:
    """A get_evaluator() wrapper that reconnects on any error, so a daemon hiccup on a long
    poll never kills the recording."""
    def __init__(self):
        self.ev = get_evaluator()

    def run(self, chunk, settle):
        for _ in range(4):
            try:
                return list(self.ev.run(chunk, marker=MARK, settle=settle))
            except Exception as exc:
                print("  reconnect (%s)" % exc)
                try:
                    self.ev.close()
                except Exception:
                    pass
                time.sleep(1.0)
                self.ev = get_evaluator()
        return []

    def status(self):
        out = {}
        for ln in self.run(_STATUS, 0.3):
            if "SRAI ST " in ln:
                for part in ln.split("SRAI ST ", 1)[-1].split():
                    if "=" in part:
                        k, v = part.split("=", 1)
                        out[k] = v
        return out


def main():
    os.makedirs(HUMAN_DIR, exist_ok=True)
    b = Bridge()
    run_no = len(glob.glob(os.path.join(HUMAN_DIR, "run_*.txt")))
    print("RESILIENT RECORD LOOP. Play runs one after another; each auto-saves. "
          "Stop by not starting a new run for %ds." % IDLE_EXIT)
    while True:
        try:
            if _one_iteration(b, run_no):
                run_no += 1
            else:
                return
        except Exception as exc:               # never let one bad round trip kill the loop
            print("  loop error, re-arming (%s)" % exc)
            time.sleep(1.0)
            try:
                b.ev = get_evaluator()
            except Exception:
                pass


def _one_iteration(b, run_no):
    """Arm, wait for a run, record it, save it. Returns True if a run was saved, False if the
    human stopped (no new run within IDLE_EXIT)."""
    if True:
        b.run(_ARM, 0.4)
        print("Ready — press Start and play (run %d so far)." % run_no)
        t0, started = time.time(), False
        while time.time() - t0 < IDLE_EXIT:
            st = b.status()
            if st.get("state") == "3" and float(st.get("frames") or 0) > 0:
                started = True
                break
            time.sleep(0.6)
        if not started:
            print("No new run for %ds — stopping (%d runs saved)." % (IDLE_EXIT, run_no))
            return
        print("  recording...")
        last_z, stall = -1.0, time.time()
        while True:
            st = b.status()
            z = float(st.get("z") or 0)
            if z > last_z + 0.5:
                last_z, stall = z, time.time()
            elif st.get("dead") == "true" or st.get("state") != "3" or time.time() - stall > 4.0:
                break
            print("    z=%.0f frames=%s" % (z, st.get("frames")), end="\r")
            time.sleep(0.5)
        print(" " * 50, end="\r")
        frames = []
        for ln in b.run(_DRAIN, 6.0):
            if "SRAI FRAME " in ln:
                frames.append(ln.split("SRAI FRAME ", 1)[-1].rstrip())
        run_no += 1
        out = os.path.join(HUMAN_DIR, "run_%03d.txt" % run_no)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(frames))
        print("[saved] run %d: %.0f m, %d frames -> %s" % (run_no, last_z, len(frames), out))


if __name__ == "__main__":
    main()
