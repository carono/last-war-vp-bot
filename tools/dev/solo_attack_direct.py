r"""No-click SOLO monster attack — MODE 2 (uuid known): pure main-thread send, ZERO UI touch.

When the monster's pid/uuid/serverId are already known (e.g. captured earlier by solo_attack.py),
the OnClick/popup step is unnecessary: OnClick only exists to FETCH the uuid from the server. With
the uuid in hand, the march is created straight from the game's main-thread scheduler — no popup,
no CloseSelf, no HUD risk at all:

  TimerManager:GetInstance():DelayInvoke(function()
    MarchUtil.SendCreateMarchMessage(formationUuid, ATTACK_MONSTER, pid, uuid, 1, 1, false, serverId, nil)
  end, 0.5)

Verified live: IsHaveMarchInWorld() false->true, GetOwnerMarches() 0->1, nothing on screen touched.
The uuid must still resolve to a monster that exists on the server (same monster, alive).

    C:\Python312\python.exe tools\solo_attack_direct.py <pid> <uuid> [serverId] [formationUuid]
    # defaults reproduce the confirmed live shot:
    C:\Python312\python.exe tools\solo_attack_direct.py 507564 1397117506875008800 935
"""
import sys, time
sys.path.insert(0, "tools/lib")
from lua_client import get_evaluator  # daemon-backed when running, else a fresh local LuaEval

DEFAULT_FORMATION = "1156814234542394473"


def one(lines, needle):
    return " ".join(x for x in lines if needle in x)


def main():
    a = sys.argv[1:]
    pid = a[0] if len(a) > 0 else "507564"
    uuid = a[1] if len(a) > 1 else "1397117506875008800"
    srv = a[2] if len(a) > 2 else "935"
    formation = a[3] if len(a) > 3 else DEFAULT_FORMATION

    ev = get_evaluator()

    def run(chunk, marker, settle=1.6):
        return ev.run(chunk, marker=marker, settle=settle)

    def march_state():
        return one(run(
            'local wm=DataCenter.WorldMarchDataManager local o=wm:GetOwnerMarches() local n=0 '
            'if o then pcall(function() n=o.Count end) if n==nil then n=0 for _ in pairs(o) do n=n+1 end end end '
            'CS.UnityEngine.Debug.LogError("HV="..tostring(wm:IsHaveMarchInWorld()).." om="..tostring(n))',
            "HV", 1.0), "HV=")

    print("target: pid=%s uuid=%s serverId=%s formation=%s" % (pid, uuid, srv, formation), flush=True)
    print("BEFORE:", march_state(), flush=True)

    # ONLY the main-thread send. No OnClick, no search, no CloseSelf, no UI touch.
    run((r'''TimerManager:GetInstance():DelayInvoke(function()
  local ok,err=pcall(function() MarchUtil.SendCreateMarchMessage(%s, MarchTargetType.ATTACK_MONSTER, %s, %s, 1, 1, false, %s, nil) end)
  CS.UnityEngine.Debug.LogError("SEND ok="..tostring(ok).." err="..tostring(err))
end, 0.5)
CS.UnityEngine.Debug.LogError("SCHEDULED")''' % (formation, pid, uuid, srv)), "SCHEDULED", 1.5)

    time.sleep(3.0)
    res = march_state()
    print("AFTER:", res, flush=True)
    print("MARCH LAUNCHED" if "HV=true" in res else "NO MARCH (uuid may be stale / monster gone)", flush=True)
    ev.close()


if __name__ == "__main__":
    main()
