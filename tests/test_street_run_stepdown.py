r"""The sideways step off a roof, and the height it is allowed at.

Leaving a roof sideways where the roof runs out mid-change is a move the planner has (#1164)
and a move that has killed a live run (#1165): it went out at y = 4.20, up on the flat
plateau with the roof end two metres ahead, and the runner was dead six metres later, still
3.5 up and still moving across. Every one of the seven step-downs in the human recordings
starts between y = 2.0 and 3.2 — a runner already falling off the end. So the move is gated
on the height, and this is the guard on that gate.

It asks the planner one question on a field built for it: a runner riding a roof that is
about to end, a wall in its own lane beyond, a clear lane beside it. The answer that matters
is not WHICH way it wants to go — that is the same either way — but WHEN: `az` is the bucket
the manoeuvre is scheduled at, and only `az == 0` is issued this frame.

    python3 tests/test_street_run_stepdown.py     # standalone, prints PASS/FAIL

Exit codes (standalone): 0 = passed, 1 = failed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO / "tools" / "dev", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.chdir(_REPO)

import surfing_offline as O  # noqa: E402

PZ = 100.0
SPEED = 30.0
# Two kinds, hand-written rather than taken from the config, so the field says exactly one
# thing: a rideable carriage whose roof ends at 101, and a wall that closes the lane at 130.
KINDS = (
    "[1]={solid=true,jump=false,slide=false,sideOnly=true,carriage=true,ramp=true,"
    "ignore=false,back=25,front=0,lanes=1,speed=0,fly=0,buff=nil},"
    "[2]={solid=true,jump=false,slide=false,sideOnly=false,carriage=false,ramp=false,"
    "ignore=false,back=1,front=1,lanes=1,speed=0,fly=0,buff=nil}"
)
# x: 32 = left, 36 = centre, 40 = right. The runner rides the right lane's roof (76..101) and
# the same lane is walled at 130; the centre lane holds nothing at all.
FIELD = "{{x=40,z=101,mid=1,speed=0},{x=40,z=130,mid=2,speed=0}}"


def plan(ai, rt, py):
    """What the planner would do this frame, riding the roof at height `py`."""
    obs = rt.eval("function() return %s end" % FIELD)()
    reach, act, az = ai["planRoute"](PZ, 2, SPEED, obs, False, True, py)
    return int(act), int(az), int(reach)


def check():
    rt, ai = O.new_vm()
    rt.execute("__SR_AI.kindOverride = {%s}" % KINDS)
    if ai["resetKinds"] is not None:
        ai["resetKinds"]()
    fails = []

    # 1. On the plateau the move is refused NOW. The route may still mean to change lanes —
    #    it has to, the lane is walled — but not before the runner has come off the roof, so
    #    the manoeuvre is scheduled ahead and nothing is issued this frame.
    act, az, _ = plan(ai, rt, 4.30)
    if az == 0 and act in (1, 2):
        fails.append("plateau (y=4.30): a lane change was issued this frame (act=%d az=%d) — "
                     "the runner is standing on the roof, not falling off it" % (act, az))

    # 2. Just below the plateau it is refused too: 3.5 is the gate, and 3.6 is above it.
    act, az, _ = plan(ai, rt, 3.60)
    if az == 0 and act in (1, 2):
        fails.append("y=3.60: a lane change was issued (act=%d az=%d) above cfg.stepDownY" % (act, az))

    # 3. Falling off the end, it is the human move and it goes out now.
    act, az, _ = plan(ai, rt, 3.00)
    if not (az == 0 and act == 1):
        fails.append("y=3.00: expected the step down to the left to be issued now, "
                     "got act=%d az=%d" % (act, az))

    # 4. And the gate is a height, not a hard "no": raise it and the plateau move returns.
    #    This is what tells the guard apart from the planner simply having lost the move.
    ai["cfg"]["stepDownY"] = 5.0
    act, az, _ = plan(ai, rt, 4.30)
    if not (az == 0 and act == 1):
        fails.append("cfg.stepDownY=5.0, y=4.30: the move should be back, got act=%d az=%d"
                     % (act, az))
    ai["cfg"]["stepDownY"] = 3.5

    # 5. A caller that cannot measure a height does not get the move at all (the offline
    #    judge, whose runner is on the road the instant a roof ends).
    obs = rt.eval("function() return %s end" % FIELD)()
    _reach, act, az = ai["planRoute"](PZ, 2, SPEED, obs, False, True)
    if int(az) == 0 and int(act) in (1, 2):
        fails.append("no height given: a lane change was issued (act=%d az=%d)"
                     % (int(act), int(az)))
    return fails


def test_step_down_is_gated_on_height():
    fails = check()
    assert not fails, "\n".join(fails)


if __name__ == "__main__":
    problems = check()
    for line in problems:
        print("FAIL " + line)
    print("PASS: the step-down waits for the fall" if not problems
          else "FAILED: %d of the height gate's cases" % len(problems))
    raise SystemExit(1 if problems else 0)
