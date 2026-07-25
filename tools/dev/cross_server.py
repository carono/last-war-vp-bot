r"""View another server's world map — full load, no teleport UI (no-click, out-of-process).

Problem: out of process, the ONLY call that bulk-loads a foreign server's world is
`CrossServerUtil.JumpToServerByServerId(...)`, and outside an active event it always enters
**move-city mode** — it opens the base-relocation window `UIMoveCity` (the "teleport"/переезд UI).
`CrossServerUtil.OnCrossServer(serverId)` gives a clean mode but does NOT bulk-load (empty map).

Solution (proven live): do the full move-city jump, then close ONLY the `UIMoveCity` window via its
own `Ctrl:CloseSelf()`. The full world stays loaded (~340-390 world clones) and the teleport UI is
gone. NEVER use `UIManager:DestroyAllWindow()` (it destroys the persistent HUD).

Recipe:
  1. CrossServerUtil.SetCrossEnableList({[0]={homeServer}, [1]={serverId}})   -- authorize the target
     (flips GetCrossEnableReason(serverId) from -2 Disable to a positive/enabled reason)
  2. CrossServerUtil.JumpToServerByServerId(serverId, MoveCrossServerType.BigMap3000, nil, 105, false)
     -- full bulk load; opens UIMoveCity
  3. UIManager.Instance:GetWindow("UIMoveCity").Ctrl:CloseSelf()              -- close ONLY that window
  4. (optional) GoToUtil.GotoPos(Vector3(X*2+1,0,Y*2+1),105,nil,nil,serverId,nil)  -- pan to fill more

Return home:  CrossServerUtil.BackToSrcServer() + CrossServerUtil.OnBackSelfServer()

    C:\Python312\python.exe tools\cross_server.py <serverId> [X Y]
    C:\Python312\python.exe tools\cross_server.py 972
    C:\Python312\python.exe tools\cross_server.py 972 561 492
    C:\Python312\python.exe tools\cross_server.py --home        # return to the home server
"""
import sys, time
sys.path.insert(0, "tools/lib")
from lua_client import get_evaluator  # daemon-backed when running, else a fresh local LuaEval

HOME_SERVER = "935"


def one(lines, needle):
    return " ".join(x for x in lines if needle in x)


def main():
    if len(sys.argv) < 2:
        print(__doc__); return

    ev = get_evaluator()

    def run(chunk, marker, settle=1.6):
        return ev.run(chunk, marker=marker, settle=settle)

    if sys.argv[1] == "--home":
        run('TimerManager:GetInstance():DelayInvoke(function() '
            'pcall(function() CrossServerUtil.BackToSrcServer() end) '
            'pcall(function() CrossServerUtil.OnBackSelfServer() end) '
            'CS.UnityEngine.Debug.LogError("H back") end, 0.4)', "H", 1.0)
        time.sleep(5)
        st = one(run('CS.UnityEngine.Debug.LogError("HS IsInOther="..'
                     'tostring(select(2,pcall(function() return CrossServerUtil.IsInOtherServer() end))))',
                     "HS", 1.0), "HS ")
        print("returned home:", st, flush=True)
        ev.close(); return

    srv = sys.argv[1]
    x = sys.argv[2] if len(sys.argv) > 3 else None
    y = sys.argv[3] if len(sys.argv) > 3 else None

    # 1) authorize the target, bulk-load via the move-city jump, and arm a MAIN-THREAD watcher that
    #    closes UIMoveCity the moment it opens — event-driven, no fixed timeout. The world keeps
    #    streaming in after the close (it is driven by world.get.block, not by that window).
    r = one(run(
        'local lst={} lst[0]={%s} lst[1]={%s} '
        'pcall(function() CrossServerUtil.SetCrossEnableList(lst) end) '
        'local ok=pcall(function() CrossServerUtil.JumpToServerByServerId(%s, MoveCrossServerType.BigMap3000, nil, 105, false) end) '
        '_G.__MCW=0 '
        'local function w() _G.__MCW=_G.__MCW+1 '
        '  local open=false pcall(function() open=UIManager.Instance:IsWindowOpen("UIMoveCity") end) '
        '  if open then pcall(function() local win=UIManager.Instance:GetWindow("UIMoveCity") '
        '      if win and win.Ctrl and win.Ctrl.CloseSelf then win.Ctrl:CloseSelf() end end) '
        '    CS.UnityEngine.Debug.LogError("MCW closed after ".._G.__MCW.." checks (~"..(_G.__MCW*0.1).."s)") '
        '  elseif _G.__MCW<120 then TimerManager:GetInstance():DelayInvoke(w,0.1) '
        '  else CS.UnityEngine.Debug.LogError("MCW gaveup (UIMoveCity never opened)") end end '
        'TimerManager:GetInstance():DelayInvoke(w,0.1) '
        'CS.UnityEngine.Debug.LogError("J ok="..tostring(ok).." reason="..'
        'tostring(select(2,pcall(function() return CrossServerUtil.GetCrossEnableReason(%s) end))))'
        % (HOME_SERVER, srv, srv, srv), "J", 1.6), "J ")
    print("jump:", r, flush=True)

    # 2) wait for the watcher to report the close (adaptive — polls the transition, not a fixed sleep)
    closed = ""
    for _ in range(10):
        time.sleep(0.6)
        closed = one(run(
            'local o=false pcall(function() o=UIManager.Instance:IsWindowOpen("UIMoveCity") end) '
            'CS.UnityEngine.Debug.LogError("C open="..tostring(o).." checks="..tostring(_G.__MCW or 0))',
            "C", 0.4), "C ")
        if "open=false" in closed and "checks=0" not in closed:
            break
    print("movecity:", closed, flush=True)

    # 3) optional pan to a specific coordinate to fill more of the map
    if x is not None and y is not None:
        run('pcall(function() GoToUtil.GotoPos(CS.UnityEngine.Vector3(%s*2+1,0,%s*2+1),105,nil,nil,%s,nil) end) '
            'pcall(function() SceneUtils.ClearLastRequestALPointsTime() end) '
            'pcall(function() SceneUtils.WorldSendGetALPointsRequest() end) '
            'CS.UnityEngine.Debug.LogError("G panned")' % (x, y, srv), "G", 1.6)

    time.sleep(2)
    v = one(run(
        'local cnt=0 pcall(function() local arr=CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) '
        'for i=0,arr.Length-1 do local mb=arr[i] if mb then local ok,go=pcall(function() return mb.gameObject end) '
        'if ok and go and string.find(go.name,"Clone") then cnt=cnt+1 end end end end) '
        'CS.UnityEngine.Debug.LogError("V clones="..cnt..'
        '" UIMoveCity_open="..tostring(select(2,pcall(function() return UIManager.Instance:IsWindowOpen("UIMoveCity") end)))..'
        '" IsInOther="..tostring(select(2,pcall(function() return CrossServerUtil.IsInOtherServer() end))))', "V", 1.4), "V ")
    print("result:", v, flush=True)
    print("target server: %s" % srv, flush=True)
    ev.close()


if __name__ == "__main__":
    main()
