r"""No-click resource GATHER march — MODE 1 (OnClick): find a mine, read pid via its popup, send.

Mirrors tools/solo_attack.py but for resource tiles ("mines": CollectResourceWood_world /
CollectResourceStone_world clones). Resource tiles have **uuid=0** (identified by pointId alone),
so unlike monsters no server uuid-fetch is required — but this MODE still uses the map-tap popup to
read the pid, then closes it cleanly and sends:

  1. find a CollectResource*_world(Clone) via its TouchObjectEventTrigger
  2. trig:OnClick()          -- opens UIWorldPoint for the mine
  3. read pid / serverId from the popup Ctrl (uuid is 0 for a resource tile)
  4. Ctrl:CloseSelf()        -- close ONLY the popup. NEVER UIManager:DestroyAllWindow() (kills the HUD)
  5. TimerManager:GetInstance():DelayInvoke(fn, 0.5)   -- send on the MAIN THREAD
  6. MarchUtil.SendCreateMarchMessage(formationUuid, COLLECT, pid, 0, 1, 1, false, serverId, nil)

Verified live: IsHaveMarchInWorld() false->true, GetOwnerMarches() 0->1, HUD intact.
For a fully-no-click variant (no OnClick, pid read from the clone position) use gather_direct.py.

    C:\Python312\python.exe tools\gather.py
"""
import sys, time
sys.path.insert(0, "tools")
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

    # 1) find a mine clone + OnClick (opens UIWorldPoint)
    clicked = one(run(r'''_G.TRIG=nil _G.CN=nil
local arr=CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour))
for i=0,arr.Length-1 do local mb=arr[i] if mb and mb:GetType().Name=='TouchObjectEventTrigger' then
  local ok,go=pcall(function() return mb.gameObject end)
  if ok and go then local p=go while p and not string.find(p.name,'CollectResource') and p.transform.parent do p=p.transform.parent.gameObject end
    if p and string.find(p.name,'CollectResource') and string.find(p.name,'Clone') then _G.TRIG=mb _G.CN=p.name break end end end end
if _G.TRIG then pcall(function() _G.TRIG:OnClick() end) CS.UnityEngine.Debug.LogError("SEL mine="..tostring(_G.CN)) else CS.UnityEngine.Debug.LogError("SEL NO_MINE") end''', "SEL", 1.2), "SEL ")
    print(clicked, flush=True)
    if "NO_MINE" in clicked:
        print("no mine with a trigger in view (pan the camera first)", flush=True)
        ev.close(); return
    time.sleep(2.0)

    # 2) read pid/serverId from the popup Ctrl (uuid=0 for a resource tile)
    d = one(run(r'''local w=UIManager.Instance:GetStackTopWindow() local c=w and w.Ctrl
if not c then CS.UnityEngine.Debug.LogError("P no-popup top="..tostring(w and w.Name)) return end
CS.UnityEngine.Debug.LogError("P pid="..tostring(c.pointId).." uuid="..tostring(c.uuid).." srv="..tostring(c.serverId))''', "P", 1.4), "P ")
    print(d, flush=True)
    if "pid=nil" in d or "no-popup" in d:
        print("popup did not open", flush=True); ev.close(); return
    pid = d.split("pid=")[1].split()[0]
    srv = d.split("srv=")[1].split()[0]
    srv = srv if srv not in ("nil", "") else "935"

    # 3) close ONLY the popup (keep the HUD)
    run(r'''local w=UIManager.Instance:GetStackTopWindow() local c=w and w.Ctrl
if c and c.CloseSelf then pcall(function() c:CloseSelf() end) end
CS.UnityEngine.Debug.LogError("CLOSED stack="..tostring(UIManager.Instance:GetStackWindowCount()))''', "CLOSED", 1.2)

    # 4) main-thread send (uuid=0 for a resource tile)
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
