r"""No-click resource GATHER march — MODE 2 (direct): read pid from the clone position, ZERO UI touch.

Resource tiles ("mines": CollectResourceWood_world / CollectResourceStone_world clones) have
**uuid=0** — identified by pointId alone — so NO OnClick/popup is ever needed. Read the pid straight
from the nearest mine clone's world position and send on the main thread:

  local pid = SceneUtils.WorldToTileIndex(mineClone.transform.position)
  TimerManager:GetInstance():DelayInvoke(function()
    MarchUtil.SendCreateMarchMessage(formationUuid, MarchTargetType.COLLECT, pid, 0, 1, 1, false, serverId, nil)
  end, 0.5)
  -- COLLECT = 2 ; targetUuid = 0 (resource tile) ; send runs on the MAIN THREAD
  --   (a send from the SafeDoString hijack thread is dropped by the server)

Verified live: IsHaveMarchInWorld() false->true, GetOwnerMarches() 0->1, HUD untouched.
Run in World with a mine in view (pan with GoToUtil.MoveToWorldPoint if needed).

    C:\Python312\python.exe tools\gather_direct.py
"""
import sys, time
sys.path.insert(0, "tools/lib")
from lua_client import get_evaluator  # daemon-backed when running, else a fresh local LuaEval

DEFAULT_FORMATION = "1156814234542394473"
COLLECT = "MarchTargetType.COLLECT"  # = 2


def one(lines, needle):
    return " ".join(x for x in lines if needle in x)


def main():
    ev = get_evaluator()

    def run(chunk, marker, settle=1.6):
        return ev.run(chunk, marker=marker, settle=settle)

    def march_state():
        return one(run(
            'local wm=DataCenter.WorldMarchDataManager local o=wm:GetOwnerMarches() local n=0 '
            'if o then pcall(function() n=o.Count end) if n==nil then n=0 for _ in pairs(o) do n=n+1 end end end '
            'CS.UnityEngine.Debug.LogError("HV="..tostring(wm:IsHaveMarchInWorld()).." om="..tostring(n))',
            "HV", 1.0), "HV=")

    form = one(run(
        'local afd=DataCenter.ArmyFormationDataManager local u=0 '
        'for k,v in pairs(afd.ArmyFormationList) do if type(v)=="table" then u=v.uuid break end end '
        'CS.UnityEngine.Debug.LogError("F uuid="..tostring(u))', "F", 1.2), "F ")
    formation = form.split("uuid=")[1].split()[0] if "uuid=" in form else DEFAULT_FORMATION
    if formation in ("0", "nil", ""):
        formation = DEFAULT_FORMATION

    print("baseline:", march_state(), flush=True)

    # find the nearest mine clone; read pid straight from its world position (NO OnClick)
    d = one(run(r'''local arr=CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour))
local mine=nil
for i=0,arr.Length-1 do local mb=arr[i] if mb then local ok,go=pcall(function() return mb.gameObject end)
  if ok and go and string.find(go.name,'CollectResource') and string.find(go.name,'Clone') then mine=go break end end end
if not mine then CS.UnityEngine.Debug.LogError("M NO_MINE") return end
local pid=SceneUtils.WorldToTileIndex(mine.transform.position)
local srv=935 pcall(function() srv=DataCenter.WorldMarchDataManager.serverId or 935 end)
CS.UnityEngine.Debug.LogError("M mine="..mine.name.." pid="..tostring(pid).." srv="..tostring(srv))''', "M", 1.4), "M ")
    print(d, flush=True)
    if "NO_MINE" in d:
        print("no mine in view (pan the camera first)", flush=True); ev.close(); return
    pid = d.split("pid=")[1].split()[0]
    srv = d.split("srv=")[1].split()[0]
    srv = srv if srv not in ("nil", "") else "935"

    # main-thread send (uuid=0 for a resource tile), no UI touch at all
    run((r'''TimerManager:GetInstance():DelayInvoke(function()
  local ok,err=pcall(function() MarchUtil.SendCreateMarchMessage(%s, %s, %s, 0, 1, 1, false, %s, nil) end)
  CS.UnityEngine.Debug.LogError("SEND ok="..tostring(ok).." err="..tostring(err))
end, 0.5)
CS.UnityEngine.Debug.LogError("SCHEDULED")''' % (formation, COLLECT, pid, srv)), "SCHEDULED", 1.5)

    time.sleep(3.0)
    res = march_state()
    print("target: pid=%s uuid=0 serverId=%s type=COLLECT(2)" % (pid, srv), flush=True)
    print("result:", res, flush=True)
    print("GATHER MARCH LAUNCHED" if "HV=true" in res else "NO MARCH", flush=True)
    ev.close()


if __name__ == "__main__":
    main()
