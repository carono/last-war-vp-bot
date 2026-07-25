r"""No-click SOLO monster attack — MODE 1 (uuid unknown): find + fetch + send, no UI hang.

Recipe (docs/research/world-monsters.md, final Finding):
  1. find a roaming WorldMonster0N(Clone) via its TouchObjectEventTrigger
  2. trig:OnClick()          -- opens UIWorldPoint; the SERVER returns the monster uuid
                                (uuid is NOT stored client-side; uuid=0 is rejected)
  3. read pid / uuid / serverId from the popup's UIWorldPointCtrl
  4. Ctrl:CloseSelf()        -- close ONLY the popup. NEVER UIManager:DestroyAllWindow()
                                (DestroyAllWindow destroys the persistent HUD = the "UI hang")
  5. TimerManager:GetInstance():DelayInvoke(fn, 0.5)   -- run the send on the MAIN THREAD
                                (a send from the SafeDoString hijack thread is dropped by the server)
  6. MarchUtil.SendCreateMarchMessage(formationUuid, ATTACK_MONSTER, pid, uuid, 1, 1, false, serverId, nil)

Verified live: IsHaveMarchInWorld() false->true, GetOwnerMarches() 0->1, HUD intact.
Run in World with a roaming solo monster in view (pan with GoToUtil.MoveToWorldPoint if needed).
Prints the pid/uuid/serverId it used — reuse them with solo_attack_direct.py (MODE 2, no OnClick).

    C:\Python312\python.exe tools\solo_attack.py
"""
import sys, time
sys.path.insert(0, "tools")
from lua_eval import LuaEval

DEFAULT_FORMATION = "1156814234542394473"


def one(lines, needle):
    return " ".join(x for x in lines if needle in x)


def main():
    ev = LuaEval()

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

    # 1) find a roaming monster + OnClick (opens UIWorldPoint, server returns uuid)
    clicked = one(run(r'''_G.TRIG=nil _G.CN=nil
local arr=CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour))
for i=0,arr.Length-1 do local mb=arr[i] if mb and mb:GetType().Name=='TouchObjectEventTrigger' then
  local ok,go=pcall(function() return mb.gameObject end)
  if ok and go then local p=go while p and not string.find(p.name,'WorldMonster') and p.transform.parent do p=p.transform.parent.gameObject end
    if p and string.find(p.name,'WorldMonster') and string.find(p.name,'Clone') and not string.find(p.name,'Boss') then _G.TRIG=mb _G.CN=p.name break end end end end
if _G.TRIG then pcall(function() _G.TRIG:OnClick() end) CS.UnityEngine.Debug.LogError("SEL clone="..tostring(_G.CN)) else CS.UnityEngine.Debug.LogError("SEL NO_MONSTER") end''', "SEL", 1.2), "SEL ")
    print(clicked, flush=True)
    if "NO_MONSTER" in clicked:
        print("no roaming monster in view (pan the camera first)", flush=True)
        ev.close(); return
    time.sleep(2.0)  # let the server point-detail load

    # 2) read pid/uuid/serverId from the popup Ctrl
    d = one(run(r'''local w=UIManager.Instance:GetStackTopWindow() local c=w and w.Ctrl
if not c then CS.UnityEngine.Debug.LogError("P no-popup top="..tostring(w and w.Name)) return end
local ca=0 pcall(function() ca=tonumber(c:GetMonsterData(c.uuid).canAttack) or 0 end)
CS.UnityEngine.Debug.LogError("P pid="..tostring(c.pointId).." uuid="..tostring(c.uuid).." srv="..tostring(c.serverId).." canAttack="..ca)''', "P", 1.4), "P ")
    print(d, flush=True)
    if "pid=nil" in d or "no-popup" in d:
        print("popup did not open", flush=True); ev.close(); return
    pid = d.split("pid=")[1].split()[0]
    uuid = d.split("uuid=")[1].split()[0]
    srv = d.split("srv=")[1].split()[0]
    srv = srv if srv not in ("nil", "") else "935"

    # 3) close ONLY the popup (keep the HUD)
    run(r'''local w=UIManager.Instance:GetStackTopWindow() local c=w and w.Ctrl
if c and c.CloseSelf then pcall(function() c:CloseSelf() end) end
CS.UnityEngine.Debug.LogError("CLOSED stack="..tostring(UIManager.Instance:GetStackWindowCount()))''', "CLOSED", 1.2)

    # 4) send on the MAIN THREAD via the game scheduler (one-shot)
    run((r'''TimerManager:GetInstance():DelayInvoke(function()
  local ok,err=pcall(function() MarchUtil.SendCreateMarchMessage(%s, MarchTargetType.ATTACK_MONSTER, %s, %s, 1, 1, false, %s, nil) end)
  CS.UnityEngine.Debug.LogError("SEND ok="..tostring(ok).." err="..tostring(err))
end, 0.5)
CS.UnityEngine.Debug.LogError("SCHEDULED")''' % (formation, pid, uuid, srv)), "SCHEDULED", 1.5)

    time.sleep(3.0)
    res = march_state()
    print("target: pid=%s uuid=%s serverId=%s" % (pid, uuid, srv), flush=True)
    print("result:", res, flush=True)
    print("MARCH LAUNCHED" if "HV=true" in res else "NO MARCH", flush=True)
    ev.close()


if __name__ == "__main__":
    main()
