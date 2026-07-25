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

This tool also LISTENS: DataCenter.WorldMarchDataManager:GetAllMarches() enumerates every
world march; team marches (teamUuid != 0) are rallies, grouped by teamUuid with the leader
being the march whose uuid == teamUuid - 1. That yields the join parameters straight from
the game (no pcap) — teamUuid, targetPos = targetPointId, serverId — so --list / --watch /
--leader work on live state.

Usage:
    # listen
    ...\python.exe tools\rally_join.py --list [--me <yourName>]
    ...\python.exe tools\rally_join.py --watch [--auto-join] [--me <yourName>]
    # join
    ...\python.exe tools\rally_join.py --leader <name-or-mask> --me <yourName>
    ...\python.exe tools\rally_join.py --team <teamUuid> --point <targetPointId> --server <serverId>
    # decline / leave
    ...\python.exe tools\rally_join.py --cancel --leader <name-or-mask> --me <yourName>
    ...\python.exe tools\rally_join.py --cancel --team <teamUuid> --member <memberUuid>

Notes:
  * A march no-ops on a COLD formation (soldiers=0). do_join uses the first warm formation and
    only warms a cold one via OnClickStartMarch — which opens the dispatch panel, so it is then
    closed with GoToUtil.CloseAllWindows(). A normal (already-warm) join opens NO UI.
  * DECLINE sends `alliance.team.retreat` directly. MarchUtil.CancelRallyByMember only pops a
    confirm dialog; the retreat message is what OK sends, so we send it straight (no popup).
  * ``--me`` matches your handle as a substring (names carry tags, e.g. "8888 Rock 8888").
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


def formation_by_squad(run, squad):
    """Return the formation UUID for in-game squad slot `squad` (1/2/3), or None.

    Formations live in DataCenter.ArmyFormationDataManager.ArmyFormationList keyed by uuid;
    each carries `index` = the squad number the player sees in the dispatch UI. The first arg
    of SendCreateMarchMessage is this formation uuid, so this is how a specific squad is sent.
    """
    rows = run(
        r'''local afd=DataCenter.ArmyFormationDataManager
for k,v in pairs(afd.ArmyFormationList) do if type(v)=='table' or type(v)=='userdata' then
  local ok,idx=pcall(function() return v.index end)
  if ok and tostring(idx)=='%d' then
    CS.UnityEngine.Debug.LogError('SQUAD uuid='..tostring(v.uuid)) end
end end
CS.UnityEngine.Debug.LogError('SQUAD end')''' % squad, "SQUAD", 1.2)
    line = one(rows, "SQUAD uuid=")
    if "uuid=" not in line:
        return None
    return line.split("uuid=")[1].split()[0]


def list_squads(run):
    """Print all formations as squad slots (index -> uuid, soldiers)."""
    return run(
        r'''local afd=DataCenter.ArmyFormationDataManager
for k,v in pairs(afd.ArmyFormationList) do if type(v)=='table' or type(v)=='userdata' then
  CS.UnityEngine.Debug.LogError('SQUAD index='..tostring(v.index)..' uuid='..tostring(v.uuid)
    ..' soldiers='..tostring(v.totalSoldierNum)) end
end''', "SQUAD index=", 1.2)


def own_marches(run):
    """(count of the player's own world marches, IsHaveMarchInWorld) — the reliable join signal.

    GetAllianceMarchesInTeam() returns nil in xLua so it cannot be counted; a successful join
    instead shows up as a new owner march heading to the rally point (and IsHaveMarchInWorld).
    """
    rows = run(
        r'''local wm=DataCenter.WorldMarchDataManager local n=0
local om=wm:GetOwnerMarches() if om then local e=om:GetEnumerator() while e:MoveNext() do n=n+1 end end
CS.UnityEngine.Debug.LogError("OM n="..n.." have="..tostring(wm:IsHaveMarchInWorld()))''',
        "OM n=", 1.0)
    s = one(rows, "OM n=")
    try:
        return int(s.split("OM n=")[1].split()[0]), ("have=true" in s)
    except Exception:
        return -1, False


def warm_formation(run, point, team, server):
    """Load the (otherwise cold, soldiers=0) formation for this rally target, then close its UI.

    MarchUtil.SendCreateMarchMessage silently no-ops on a cold formation. OnClickStartMarch —
    the game's own «в поход» entry — populates the formation soldier counts (verified: 0 ->
    3123), but it also OPENS the dispatch/formation panel and leaves it hanging. So we close
    it right after with GoToUtil.CloseAllWindows() (the same close the game runs in this flow),
    which clears the march popups without touching the HUD (unlike DestroyAllWindow).

    Only needed when no formation is warm yet — do_join skips this entirely otherwise, so a
    normal join opens no UI at all.
    """
    run(r'''pcall(function() MarchUtil.OnClickStartMarch(6, %s, %s, -1, 1, 7, %s, 0, 0) end)
CS.UnityEngine.Debug.LogError("WARM done")''' % (point, team, server), "WARM done", 1.5)


def close_dispatch_ui(run):
    """Close the march/formation dispatch panel via the game's own GoToUtil.CloseAllWindows()."""
    run('pcall(function() GoToUtil.CloseAllWindows() end) CS.UnityEngine.Debug.LogError("UICLOSED")',
        "UICLOSED", 0.8)


def list_rallies(run):
    """Return the alliance rallies (стяги) currently visible in the world, one per rally.

    Reads DataCenter.WorldMarchDataManager:GetAllMarches() — a C# dictionary of every world
    march — via GetEnumerator, and keeps team marches (teamUuid != 0). Marches are grouped by
    teamUuid into rallies; the LEADER of a rally is the march whose uuid == teamUuid - 1 (the
    game numbers a rally's teamUuid as leaderUuid + 1, confirmed live). The leader march
    carries the rally's join parameters: teamUuid, targetPos (= targetPointId) and serverId.

    Each returned dict: {team, leader, point, server, members}. See docs/research/rally-join.md.
    """
    rows = run(
        r'''local wm=DataCenter.WorldMarchDataManager local col=wm:GetAllMarches()
if not col then CS.UnityEngine.Debug.LogError('RALLY end') return end
local e=col:GetEnumerator()
local function g(mo,k) local ok,v=pcall(function() return mo[k] end) if ok then return v end return nil end
local leaders,counts={},{}
while e:MoveNext() do local mo=e.Current.Value if mo==nil then mo=e.Current end
  local team=g(mo,'teamUuid') local ts=tostring(team)
  if team~=nil and ts~='0' and ts~='nil' then
    counts[ts]=(counts[ts] or 0)+1
    local isLeader=false pcall(function() isLeader=(tostring(g(mo,'uuid'))==tostring(team-1)) end)
    if isLeader then leaders[ts]={owner=tostring(g(mo,'ownerName')),
      point=tostring(g(mo,'targetPos')), srv=tostring(g(mo,'serverId') or g(mo,'targetServer'))} end
  end
end
for ts,info in pairs(leaders) do
  -- leader name is emitted LAST because it can contain spaces (e.g. "8888 Rock 8888").
  CS.UnityEngine.Debug.LogError('RALLY team='..ts..' point='..info.point
    ..' server='..info.srv..' members='..tostring(counts[ts])..' leader='..info.owner)
end
CS.UnityEngine.Debug.LogError('RALLY end')''',
        "RALLY", 1.4)
    out = []
    for ln in rows:
        if "RALLY team=" not in ln:
            continue
        d = {}
        for part in ("team", "point", "server", "members"):
            if part + "=" in ln:
                d[part] = ln.split(part + "=")[1].split()[0]
        # leader is last so it keeps spaces (names like "8888 Rock 8888")
        if "leader=" in ln:
            d["leader"] = ln.split("leader=", 1)[1].strip()
        out.append(d)
    return out


def do_join(run, ev, team, point, server, formation_arg=None):
    # Prefer an already-warm formation so we open NO UI. Only if every formation is cold
    # (soldiers=0, which makes the send a silent no-op) do we warm via OnClickStartMarch —
    # which opens the dispatch panel — and immediately close it again.
    # Ensure formations are warm (soldiers=0 makes the send a silent no-op). OnClickStartMarch
    # warms ALL squads for the target at once, so warm only when none is warm yet — then the
    # explicitly chosen squad (formation_arg) is usable too. Warming opens the dispatch panel,
    # so close it again; an already-warm join opens no UI.
    if pick_formation(run) is None:
        warm_formation(run, point, team, server)
        close_dispatch_ui(run)
    formation = formation_arg or pick_formation(run) or DEFAULT_FORMATION
    print("JOIN: team=%s point=%s server=%s formation=%s"
          % (team, point, server, formation), flush=True)
    before, _ = own_marches(run)
    print("BEFORE: own marches=%d" % before, flush=True)

    # The main-thread send. No UI touch.
    run((r'''TimerManager:GetInstance():DelayInvoke(function()
  local ok,err=pcall(function() MarchUtil.SendCreateMarchMessage(%s, %d, %s, %s, 1, 1, false, %s, nil) end)
  CS.UnityEngine.Debug.LogError("JOIN ok="..tostring(ok).." err="..tostring(err))
end, 0.5)
CS.UnityEngine.Debug.LogError("SCHEDULED")'''
         % (formation, RALLY_TARGET_TYPE, point, team, server)),
        "SCHEDULED", 1.5)

    time.sleep(3.0)
    after, have = own_marches(run)
    print("AFTER: own marches=%d (IsHaveMarchInWorld=%s)" % (after, have), flush=True)
    # A real join creates a NEW own march. IsHaveMarchInWorld alone is not proof — the player
    # may already have unrelated marches out (it was true before), so require a count increase.
    joined = after > before
    print("RALLY JOINED" if joined else
          "JOIN NOT CONFIRMED — no new march created (send needs the panel-confirm context "
          "that OnClickStartMarch->confirm sets up; direct SendCreateMarchMessage no-ops)",
          flush=True)
    return joined


def do_watch(run, ev, interval, auto_join, me=None, formation_arg=None):
    """Poll for joinable rallies; print each new one. With auto_join, join the first new one.

    Rallies led by `me` (your own handle) are skipped — you cannot join a rally you created.
    """
    print("WATCH: polling joinable rallies every %ds — Ctrl+C to stop%s"
          % (interval, "  (auto-join ON)" if auto_join else ""), flush=True)
    seen = set()
    try:
        while True:
            rallies = [r for r in list_rallies(run) if r.get("leader") != me]
            fresh = [r for r in rallies if r.get("team") and r["team"] not in seen]
            for r in fresh:
                seen.add(r["team"])
                print("%s  RALLY team=%s leader=%s point=%s server=%s members=%s"
                      % (time.strftime("%H:%M:%S"), r["team"], r.get("leader"),
                         r.get("point"), r.get("server"), r.get("members")), flush=True)
            if auto_join and fresh:
                r = fresh[0]
                if r.get("point") and r.get("server"):
                    print("-> auto-joining team=%s (leader %s)" % (r["team"], r.get("leader")), flush=True)
                    do_join(run, ev, r["team"], r["point"], r["server"], formation_arg)
                    return
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[watch] stopped", flush=True)


def my_member_uuid(run, team, me):
    """Find your own (ownerName contains `me`) march UUID inside rally `team`, or None."""
    rows = run(
        r'''local wm=DataCenter.WorldMarchDataManager local col=wm:GetAllMarches()
local e=col:GetEnumerator()
local function g(mo,k) local ok,v=pcall(function() return mo[k] end) if ok then return v end return nil end
while e:MoveNext() do local mo=e.Current.Value if mo==nil then mo=e.Current end
  if tostring(g(mo,'teamUuid'))=='%s' then
    CS.UnityEngine.Debug.LogError('MEMBER uuid='..tostring(g(mo,'uuid'))..' owner='..tostring(g(mo,'ownerName')))
  end
end
CS.UnityEngine.Debug.LogError('MEMBER end')''' % team, "MEMBER", 1.4)
    needle = (me or "").lower()
    for ln in rows:
        if "MEMBER uuid=" in ln and "owner=" in ln:
            owner = ln.split("owner=", 1)[1].strip()
            if needle and needle in owner.lower():
                return ln.split("uuid=")[1].split()[0]
    return None


def do_cancel(run, ev, team, member=None, me=None):
    # Resolve my member march if not given explicitly (needs --me to match my name).
    if not member:
        if not me:
            print("CANCEL needs --member, or --me to auto-resolve it", flush=True)
            return False
        member = my_member_uuid(run, team, me)
        if not member:
            print("you have no march in team %s (already left, or wrong team)" % team, flush=True)
            return False
    print("DECLINE: team=%s member=%s" % (team, member), flush=True)

    # Send alliance.team.retreat directly. MarchUtil.CancelRallyByMember pops a confirm dialog;
    # the retreat message is what that dialog sends on OK, so we send it straight — no popup.
    run(r'''pcall(function() SFSNetwork.SendMessage("alliance.team.retreat", %s, %s) end)
CS.UnityEngine.Debug.LogError("RETREAT sent")''' % (team, member), "RETREAT sent", 1.5)

    time.sleep(2.0)
    still = my_member_uuid(run, team, me) if me else None
    left = (me is not None and still is None)
    print("RALLY DECLINED (left the rally)" if left else
          "DECLINE SENT (unverified — pass --me to confirm you left)", flush=True)
    return left


def main():
    ap = argparse.ArgumentParser(
        description="No-click rally listen / join / cancel via xLua DoString.")
    ap.add_argument("--list", action="store_true",
                    help="print the joinable rallies visible right now, then exit")
    ap.add_argument("--watch", action="store_true",
                    help="poll for joinable rallies and print each new one (Ctrl+C to stop)")
    ap.add_argument("--auto-join", action="store_true",
                    help="with --watch: join the first new rally that appears")
    ap.add_argument("--interval", type=int, default=5,
                    help="--watch poll interval in seconds (default 5)")
    ap.add_argument("--me", help="your own handle — rallies you lead are skipped (can't self-join)")
    ap.add_argument("--leader", help="join the rally led by this player (resolves team/point/server)")
    ap.add_argument("--cancel", action="store_true",
                    help="leave/decline a rally instead of joining")
    ap.add_argument("--team", help="rally teamUuid (join/cancel a specific rally)")
    ap.add_argument("--point", help="rally targetPointId (join only)")
    ap.add_argument("--server", help="rally target serverId (join only)")
    ap.add_argument("--member",
                    help="player's own march UUID within the rally (cancel only)")
    ap.add_argument("--formation",
                    help="formation UUID to send (join only; overrides --squad)")
    ap.add_argument("--squad", type=int, choices=(1, 2, 3),
                    help="which squad slot to send (1/2/3); default = first loaded")
    ap.add_argument("--list-squads", action="store_true",
                    help="print your squad slots (index -> uuid, soldiers), then exit")
    args = ap.parse_args()

    if not (args.list or args.watch or args.list_squads):
        if args.cancel:
            if not (args.team or args.leader):
                ap.error("--cancel requires --team or --leader (plus --member or --me)")
            if not (args.member or args.me):
                ap.error("--cancel requires --member, or --me to auto-resolve it")
        elif not (args.leader or (args.team and args.point and args.server)):
            ap.error("join requires --team, --point and --server "
                     "(or --leader NAME / --list / --watch)")

    ev = get_evaluator()

    def run(chunk, marker, settle=1.6):
        return ev.run(chunk, marker=marker, settle=settle)

    def resolve_leader():
        needle = args.leader.lower()
        return next((r for r in list_rallies(run)
                     if needle in (r.get("leader") or "").lower()), None)  # substring / mask

    def formation_arg():
        """Resolve the formation UUID from --formation / --squad (None = auto-pick first loaded)."""
        if args.formation:
            return args.formation
        if args.squad:
            uuid = formation_by_squad(run, args.squad)
            if not uuid:
                print("no squad %d found — showing squads:" % args.squad, flush=True)
                for ln in list_squads(run):
                    print("  " + ln, flush=True)
            return uuid
        return None

    try:
        if args.list_squads:
            for ln in list_squads(run):
                print(ln, flush=True)
        elif args.list:
            rallies = list_rallies(run)
            if not rallies:
                print("no rallies visible right now", flush=True)
            for r in rallies:
                mine = " (yours)" if args.me and r.get("leader") == args.me else ""
                print("team=%s leader=%s point=%s server=%s members=%s%s"
                      % (r.get("team"), r.get("leader"), r.get("point"),
                         r.get("server"), r.get("members"), mine), flush=True)
        elif args.watch:
            do_watch(run, ev, args.interval, args.auto_join, args.me, formation_arg())
        elif args.cancel:
            team = args.team
            if not team and args.leader:
                m = resolve_leader()
                if not m:
                    print("no rally whose leader matches %r is visible" % args.leader, flush=True)
                    return
                team = m["team"]
            do_cancel(run, ev, team, args.member, args.me)
        elif args.leader:
            match = resolve_leader()
            if not match:
                print("no rally whose leader matches %r is visible right now" % args.leader,
                      flush=True)
            else:
                print("resolved leader %s -> team=%s point=%s server=%s members=%s"
                      % (args.leader, match["team"], match["point"], match["server"],
                         match.get("members")), flush=True)
                do_join(run, ev, match["team"], match["point"], match["server"], formation_arg())
        else:
            do_join(run, ev, args.team, args.point, args.server, formation_arg())
    finally:
        ev.close()


if __name__ == "__main__":
    main()
