r"""Attack an enemy base and send a scout plane — no-click, main-thread send.

Same launch primitive as the confirmed solo monster attack (world-monsters.md
Finding 17) and resource collect (world-tiles.md): the march is created straight
from the game's own scheduler, changing only the MarchTargetType.

    ATTACK_CITY = 11   -- attack an enemy player base
    SCOUT_CITY  = 17   -- scout an enemy player base (the "plane")

A cold send from the SafeDoString hijack thread returns ok=true but is dropped by
the server, so the call is scheduled on the main thread:

    TimerManager:GetInstance():DelayInvoke(function()
      MarchUtil.SendCreateMarchMessage(formationUuid, targetType, pid, uuid,
                                       1, 1, false, serverId, nil)
    end, 0.5)

pid  = enemy tile index (targetPoint), uuid = enemy base server uuid,
serverId = target server. Fetch them by selecting the base in-game once
(OnClickWorldTile -> world.get.detail.new returns the uuid) or via the world-clone
reader. See docs/research/attack-and-scout.md.

Usage::

    C:\Python312\python.exe tools\attack.py attack <pid> <uuid> [serverId] [formationUuid]
    C:\Python312\python.exe tools\attack.py scout  <pid> <uuid> [serverId] [formationUuid]
    C:\Python312\python.exe tools\attack.py scout-report [--open]
"""
import sys
import time

sys.path.insert(0, "tools/lib")
from lua_client import get_evaluator  # daemon-backed when running, else a fresh local LuaEval

# First loaded squad; overridable on the CLI. Same default as solo_attack_direct.py.
DEFAULT_FORMATION = "1156814234542394473"
DEFAULT_SERVER = "935"

TARGET_TYPES = {"attack": "ATTACK_CITY", "scout": "SCOUT_CITY"}


def _one(lines, needle):
    return " ".join(x for x in lines if needle in x)


def _march_state(ev):
    """(IsHaveMarchInWorld, owner-march count) — the reliable launch signal."""
    return _one(ev.run(
        'local wm=DataCenter.WorldMarchDataManager local o=wm:GetOwnerMarches() local n=0 '
        'if o then pcall(function() n=o.Count end) if n==nil then n=0 for _ in pairs(o) do n=n+1 end end end '
        'CS.UnityEngine.Debug.LogError("HV="..tostring(wm:IsHaveMarchInWorld()).." om="..tostring(n))',
        marker="HV", settle=1.0), "HV=")


def launch(kind, pid, uuid, srv, formation):
    """Send an ATTACK_CITY (11) or SCOUT_CITY (17) march at <pid>/<uuid>."""
    target = TARGET_TYPES[kind]
    ev = get_evaluator()
    print("%s: pid=%s uuid=%s serverId=%s formation=%s (MarchTargetType.%s)"
          % (kind, pid, uuid, srv, formation, target), flush=True)
    print("BEFORE:", _march_state(ev), flush=True)

    ev.run((r'''TimerManager:GetInstance():DelayInvoke(function()
  local ok,err=pcall(function()
    MarchUtil.SendCreateMarchMessage(%s, MarchTargetType.%s, %s, %s, 1, 1, false, %s, nil)
  end)
  CS.UnityEngine.Debug.LogError("SEND ok="..tostring(ok).." err="..tostring(err))
end, 0.5)
CS.UnityEngine.Debug.LogError("SCHEDULED")''' % (formation, target, pid, uuid, srv)),
        marker="SCHEDULED", settle=1.5)

    time.sleep(3.0)
    res = _march_state(ev)
    print("AFTER:", res, flush=True)
    print("MARCH LAUNCHED" if "HV=true" in res
          else "NO MARCH (uuid may be stale / base shielded or moved)", flush=True)
    ev.close()


def scout_report(open_ui=False):
    """Report whether a new scout report is waiting; optionally open the mailbox."""
    ev = get_evaluator()
    line = _one(ev.run(
        'local rd=nil pcall(function() rd=CommonUtil.PlayerPrefsGetTable("WORLD_SCOUT_RED_DOT") end) '
        'local has=false if rd then if type(rd)=="table" then for _ in pairs(rd) do has=true break end '
        'else has=true end end '
        'CS.UnityEngine.Debug.LogError("SCOUTRD has="..tostring(has))',
        marker="SCOUTRD", settle=1.0), "SCOUTRD")
    print("scout red-dot:", line or "(unknown)", flush=True)
    print("new scout report waiting" if "has=true" in line
          else "no unread scout report", flush=True)
    if open_ui:
        ev.run('pcall(function() GoToUtil.GotoOpenView("UILWMailMain") end) '
               'CS.UnityEngine.Debug.LogError("MAILOPEN")', marker="MAILOPEN", settle=1.0)
        print("opened mailbox (UILWMailMain) — scout report is a fightType 8 battle mail", flush=True)
    ev.close()


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return
    cmd = a[0]
    if cmd == "scout-report":
        scout_report(open_ui="--open" in a)
        return
    if cmd not in TARGET_TYPES:
        print("unknown command %r (attack | scout | scout-report)" % cmd)
        sys.exit(2)
    if len(a) < 3:
        print("usage: attack.py %s <pid> <uuid> [serverId] [formationUuid]" % cmd)
        sys.exit(2)
    pid, uuid = a[1], a[2]
    srv = a[3] if len(a) > 3 else DEFAULT_SERVER
    formation = a[4] if len(a) > 4 else DEFAULT_FORMATION
    launch(cmd, pid, uuid, srv, formation)


if __name__ == "__main__":
    main()
