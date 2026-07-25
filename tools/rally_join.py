r"""No-click rally JOIN / CANCEL — pure main-thread send, ZERO UI touch.

Same technique as tools/solo_attack_direct.py: the in-game «Join rally» / «Decline»
button only exists to gather the rally parameters and dispatch the network message on
the game's main thread. With the parameters already known (captured from
``push.alliance.march.refresh`` by rally_monitor.py), the message is sent straight from
the main-thread scheduler — no popup, no CloseSelf, no HUD risk:

  JOIN   TimerManager:GetInstance():DelayInvoke(function()
           MarchUtil.SendCreateMarchMessage(formationUuid, 6, targetPointId,
                                             teamUuid, 1, 1, false, server, nil)
         end, 0.5)

  CANCEL TimerManager:GetInstance():DelayInvoke(function()
           MarchUtil.CancelRallyByMember(teamUuid, memberUuid)
         end, 0.5)

Signatures confirmed via tools/_rally_join_trace.py (task #1043 / lua_trace sessions):
  * SendCreateMarchMessage(formationUuid, targetType=6, targetPointId, teamUuid,
                           1, 1, false, server, nil)  -- join an existing rally
  * CancelRallyByMember(teamUuid, memberUuid)          -- leave/decline a rally

The rally parameters come from ``push.alliance.march.refresh``:
  teamUuid       -- rally team UUID (non-zero identifies the rally)
  targetPointId  -- rally target tile ID
  server         -- rally target server
  memberUuid     -- player's own march UUID within members[] (ownerUid == player), for cancel

Usage:
    C:\Python312\python.exe tools\rally_join.py --team <teamUuid> --point <targetPointId> --server <serverId>
    C:\Python312\python.exe tools\rally_join.py --cancel --team <teamUuid> --member <memberUuid>

``--formation`` overrides the formation UUID; by default the first loaded formation
(soldiers > 0) is picked from DataCenter.ArmyFormationDataManager (a march silently
no-ops with an empty formation).
"""
import argparse
import sys
import time

sys.path.insert(0, "tools")
from lua_client import get_evaluator  # daemon-backed when running, else a fresh local LuaEval

# Rally target type for joining an existing alliance rally (confirmed via lua_trace).
RALLY_TARGET_TYPE = 6
# Fallback if no loaded formation can be resolved and none is passed on the CLI.
DEFAULT_FORMATION = "1156814234542394473"


def one(lines, needle):
    return " ".join(x for x in lines if needle in x)


def pick_formation(run):
    """Return the UUID of the first loaded formation (soldiers > 0), or None.

    Same source as mini_kill_rally.py: a march created with an empty/cold formation
    silently no-ops, so join must ride a formation that actually has soldiers.
    """
    rows = run(
        r'''local afd=DataCenter.ArmyFormationDataManager local pick=nil
for k,v in pairs(afd.ArmyFormationList) do if type(v)=='table' then
  local sol=tonumber(v.totalSoldierNum) or 0
  if sol>0 and pick==nil then pick=v end end end
if pick then CS.UnityEngine.Debug.LogError("FM PICK uuid="..tostring(pick.uuid))
else CS.UnityEngine.Debug.LogError("FM PICK none") end''',
        "FM PICK", 1.4)
    line = one(rows, "FM PICK")
    if "none" in line or "uuid=" not in line:
        return None
    return line.split("uuid=")[1].split()[0]


def team_count(run):
    """Number of alliance team-marches the player is part of (join changes this)."""
    rows = run(
        r'''local wm=DataCenter.WorldMarchDataManager local t=wm:GetAllianceMarchesInTeam() local n=0
if t then pcall(function() n=t.Count end) if n==nil or n=="nil" then n=0 for _ in pairs(t) do n=n+1 end end end
CS.UnityEngine.Debug.LogError("TC="..tostring(n))''',
        "TC=", 1.0)
    s = one(rows, "TC=")
    try:
        return int(s.split("TC=")[1].split()[0])
    except Exception:
        return -1


def do_join(run, ev, args):
    formation = args.formation or pick_formation(run) or DEFAULT_FORMATION
    print("JOIN: team=%s point=%s server=%s formation=%s"
          % (args.team, args.point, args.server, formation), flush=True)
    before = team_count(run)
    print("BEFORE: team marches=%d" % before, flush=True)

    # ONLY the main-thread send. No UI touch.
    run((r'''TimerManager:GetInstance():DelayInvoke(function()
  local ok,err=pcall(function() MarchUtil.SendCreateMarchMessage(%s, %d, %s, %s, 1, 1, false, %s, nil) end)
  CS.UnityEngine.Debug.LogError("JOIN ok="..tostring(ok).." err="..tostring(err))
end, 0.5)
CS.UnityEngine.Debug.LogError("SCHEDULED")'''
         % (formation, RALLY_TARGET_TYPE, args.point, args.team, args.server)),
        "SCHEDULED", 1.5)

    time.sleep(3.0)
    after = team_count(run)
    print("AFTER: team marches=%d" % after, flush=True)
    print("RALLY JOINED" if after > before else
          "JOIN NOT CONFIRMED (rally may be full/gone, or formation empty)", flush=True)


def do_cancel(run, ev, args):
    print("CANCEL: team=%s member=%s" % (args.team, args.member), flush=True)
    before = team_count(run)
    print("BEFORE: team marches=%d" % before, flush=True)

    run((r'''TimerManager:GetInstance():DelayInvoke(function()
  local ok,err=pcall(function() MarchUtil.CancelRallyByMember(%s, %s) end)
  CS.UnityEngine.Debug.LogError("CANCEL ok="..tostring(ok).." err="..tostring(err))
end, 0.5)
CS.UnityEngine.Debug.LogError("SCHEDULED")'''
         % (args.team, args.member)),
        "SCHEDULED", 1.5)

    time.sleep(3.0)
    after = team_count(run)
    print("AFTER: team marches=%d" % after, flush=True)
    print("RALLY CANCELLED" if after < before else
          "CANCEL NOT CONFIRMED (member may not have been in this rally)", flush=True)


def main():
    ap = argparse.ArgumentParser(
        description="No-click rally join / cancel via xLua DoString.")
    ap.add_argument("--cancel", action="store_true",
                    help="leave/decline a rally instead of joining")
    ap.add_argument("--team", required=True,
                    help="rally teamUuid (from push.alliance.march.refresh)")
    ap.add_argument("--point", help="rally targetPointId (join only)")
    ap.add_argument("--server", help="rally target serverId (join only)")
    ap.add_argument("--member",
                    help="player's own march UUID within the rally (cancel only)")
    ap.add_argument("--formation",
                    help="formation UUID to send (join only; default = first loaded)")
    args = ap.parse_args()

    if args.cancel:
        if not args.member:
            ap.error("--cancel requires --member (player's own march UUID in the rally)")
    else:
        if not (args.point and args.server):
            ap.error("join requires --point and --server")

    ev = get_evaluator()

    def run(chunk, marker, settle=1.6):
        return ev.run(chunk, marker=marker, settle=settle)

    try:
        if args.cancel:
            do_cancel(run, ev, args)
        else:
            do_join(run, ev, args)
    finally:
        ev.close()


if __name__ == "__main__":
    main()
