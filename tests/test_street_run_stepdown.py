r"""What a runner may do sideways off a roof, and at what height.

There are two lane changes at roof level and the runner's own height decides which of them
exists. Both have killed a live run.

* **The step-down** (#1164) leaves a roof whose floor is gone by the handover and lands on the
  road. It went out at y = 4.20 up on the flat plateau, and the runner was dead six metres
  later (#1165). Every one of the seven step-downs in the human recordings starts between
  y = 2.0 and 3.2 — a runner already falling off the end.
* **The crossing along the roofs** is the other one, and it needs a floor under both lanes. It
  went out at y = 2.78 with the runner eight metres past the end of its roof and in free fall
  (#1166): `onRoof` is only a threshold on y, so the planner still believed there was roof
  under it — and the lane it crossed into was a ramp, whose roof span the model puts at full
  height over its whole body while the thing itself is a slope a metre off the ground.

So one number, `cfg.stepDownY`, splits them: falling, the runner may step down and nothing
else; on the plateau it may cross and nothing else. This is the guard on that.

Two fields. The first is built for the step-down — a roof about to end, a wall in the runner's
own lane beyond it, a clear lane beside it. The second is the frame the #1166 run died on,
carriage for carriage. What matters in both answers is not WHICH way the planner wants to go,
which never changes, but WHEN: `az` is the bucket the manoeuvre is scheduled at, and only
`az == 0` is issued this frame.

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

# The second field is the frame the #1166 run died on, taken from the obstacle list the run
# froze at its own death — every carriage it could see, at the z it saw them, with the three
# body lengths spelled out rather than looked up. The runner is in the left lane at 1060.2
# doing 30 u/s, eight metres past the end of the roof it had been riding, and the centre lane
# holds a ramp from 1055.3 to 1080. It crossed into that ramp and died 1.6 m later.
DEATH_KINDS = (
    "[10]={solid=true,jump=false,slide=false,sideOnly=true,carriage=true,ramp=true,"
    "ignore=false,back=33,front=0,lanes=1,speed=0,fly=0,buff=nil},"
    "[11]={solid=true,jump=false,slide=false,sideOnly=true,carriage=true,ramp=true,"
    "ignore=false,back=24.7,front=0,lanes=1,speed=0,fly=0,buff=nil},"
    "[12]={solid=true,jump=false,slide=false,sideOnly=false,carriage=true,ramp=false,"
    "ignore=false,back=41.2,front=0,lanes=1,speed=0,fly=0,buff=nil},"
    "[13]={solid=true,jump=false,slide=false,sideOnly=false,carriage=true,ramp=false,"
    "ignore=false,back=33,front=0,lanes=1,speed=0,fly=0,buff=nil}"
)
DEATH_FIELD = (
    "{{x=40,z=1064,mid=12,speed=0},{x=36,z=1080,mid=11,speed=0},{x=32,z=1108,mid=10,speed=0},"
    "{x=40,z=1116,mid=12,speed=0},{x=36,z=1124,mid=13,speed=0},{x=36,z=1168,mid=13,speed=0},"
    "{x=32,z=1172,mid=12,speed=0},{x=40,z=1172,mid=10,speed=0}}"
)
DEATH_PZ = 1060.2


def plan(ai, rt, py):
    """What the planner would do this frame, riding the roof at height `py`."""
    obs = rt.eval("function() return %s end" % FIELD)()
    reach, act, az = ai["planRoute"](PZ, 2, SPEED, obs, False, True, py)
    return int(act), int(az), int(reach)


def plan_death(ai, rt, py):
    """The same question on the frame the #1166 run died on, from the left lane."""
    obs = rt.eval("function() return %s end" % DEATH_FIELD)()
    reach, act, az = ai["planRoute"](DEATH_PZ, 0, SPEED, obs, False, True, py)
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

    # ---- the frame the #1166 run died on --------------------------------------------------
    rt.execute("__SR_AI.kindOverride = {%s}" % DEATH_KINDS)
    if ai["resetKinds"] is not None:
        ai["resetKinds"]()

    # 6. Falling, eight metres past the end of its roof: the crossing along the roofs is what
    #    the runner died doing, and it must not be issued. The lane it was entering is a ramp,
    #    so the step-down is not on offer either — the answer this frame is "hold".
    for py in (3.49, 2.78, 2.10):
        act, az, _ = plan_death(ai, rt, py)
        if az == 0 and act in (1, 2):
            fails.append("the #1166 death frame at y=%.2f: a lane change was issued "
                         "(act=%d az=%d) — the runner is in free fall with no roof under it"
                         % (py, act, az))

    # 7. …AND THE HEIGHT IS NO LONGER WHAT REFUSES IT (#1170), which is worth saying rather
    #    than quietly rewriting. This case used to demand the crossing back at y = 4.30 — the
    #    control that case 6 was catching the height and not the planner having lost the move.
    #    On the frame this field is taken from the runner is at 1060.2 and the nearest carriage
    #    in its own lane starts at 1075, fifteen metres up the road: it is standing on nothing.
    #    The planner could not see that when this file was written, because `autoStart` tested
    #    only the FAR end of a carriage and filled every bucket from here to it with roof; #1170
    #    added the near end, and the phantom roof went with it. So the answer on this field is
    #    now the same at every height — hold — and it is right for a stronger reason than the
    #    gate.
    #
    #    The height gate itself is still pinned, by cases 1-5 on the field where the runner
    #    really IS on a roof. What is left to check here is that the manoeuvre has not been
    #    lost: the route still means to cross, scheduled ahead at a bucket where there will be
    #    a roof under it, rather than dropped from the plan.
    for py in (4.30, 2.78):
        act, az, _ = plan_death(ai, rt, py)
        if not (act == 2 and az > 0):
            fails.append("the #1166 death frame at y=%.2f: the crossing should still be in the "
                         "route, scheduled ahead of the roofless stretch, got act=%d az=%d"
                         % (py, act, az))
    return fails


def test_step_down_is_gated_on_height():
    fails = check()
    assert not fails, "\n".join(fails)


if __name__ == "__main__":
    problems = check()
    for line in problems:
        print("FAIL " + line)
    print("PASS: the two roof-level moves split on the height" if not problems
          else "FAILED: %d of the height gate's cases" % len(problems))
    raise SystemExit(1 if problems else 0)
