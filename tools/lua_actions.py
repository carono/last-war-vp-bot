r"""Single source of truth for the confirmed navigation Lua chunks.

Both the panel (via the warm daemon) and the standalone scripts build their in-game Lua
from here, so the recipes never drift. Each function returns a Lua string; run it through
any evaluator with a `.run(chunk, marker, settle)` method (LuaEval or the daemon client).

All recipes are the ones verified live this session — see docs/research/world-tiles.md and
docs/skills/sniff.md §7.
"""
from __future__ import annotations

HOME_SERVER = 935


def scene_world() -> str:
    """City -> World (renders the world scene)."""
    return 'pcall(function() SceneUtils.ChangeToWorld() end) CS.UnityEngine.Debug.LogError("ACT scene=world")'


def scene_city() -> str:
    """World -> City (home base)."""
    return 'pcall(function() SceneUtils.ChangeToCity() end) CS.UnityEngine.Debug.LogError("ACT scene=city")'


def current_server() -> str:
    """Log `ACT curserver=<id>` — the viewed world server (home = 935)."""
    return ('CS.UnityEngine.Debug.LogError("ACT curserver="..tostring('
            '(DataCenter.WorldFavoDataManager and DataCenter.WorldFavoDataManager.curServerId) or '
            '(DataCenter.WarFlagDataManager and DataCenter.WarFlagDataManager.curServerId) or %d))'
            % HOME_SERVER)


def goto_pos(x: int, y: int, server: int) -> str:
    """In-server camera jump to tile (x, y). Does NOT load a foreign server (use cross_jump)."""
    return ('pcall(function() GoToUtil.GotoPos(CS.UnityEngine.Vector3(%d*2+1,0,%d*2+1),105,nil,nil,%d,nil) end) '
            'CS.UnityEngine.Debug.LogError("ACT goto=%d,%d,%d")' % (x, y, server, x, y, server))


def cross_jump(server: int, home: int = HOME_SERVER, x=None, y=None) -> str:
    """Enter a FOREIGN server's world, fully loaded, with no teleport UI.

    Authorize (SetCrossEnableList) -> bulk-load (JumpToServerByServerId, always move-city)
    -> a main-thread watcher closes the UIMoveCity window the moment it opens (no fixed
    timeout; the world keeps streaming after). Optional pan to (x, y) once loaded. Returns
    immediately after arming; the close/pan run in-game on the main thread.
    """
    pan = ""
    if x is not None and y is not None:
        pan = ('TimerManager:GetInstance():DelayInvoke(function() '
               'pcall(function() GoToUtil.GotoPos(CS.UnityEngine.Vector3(%d*2+1,0,%d*2+1),105,nil,nil,%d,nil) end) '
               'pcall(function() SceneUtils.ClearLastRequestALPointsTime() end) '
               'pcall(function() SceneUtils.WorldSendGetALPointsRequest() end) end, 2.0) ' % (x, y, server))
    return (
        'local lst={} lst[0]={%d} lst[1]={%d} '
        'pcall(function() CrossServerUtil.SetCrossEnableList(lst) end) '
        'pcall(function() CrossServerUtil.JumpToServerByServerId(%d, MoveCrossServerType.BigMap3000, nil, 105, false) end) '
        '_G.__MCW=0 '
        'local function w() _G.__MCW=_G.__MCW+1 '
        '  local open=false pcall(function() open=UIManager.Instance:IsWindowOpen("UIMoveCity") end) '
        '  if open then pcall(function() local win=UIManager.Instance:GetWindow("UIMoveCity") '
        '      if win and win.Ctrl and win.Ctrl.CloseSelf then win.Ctrl:CloseSelf() end end) '
        '    CS.UnityEngine.Debug.LogError("ACT cross closed after ".._G.__MCW) '
        '  elseif _G.__MCW<120 then TimerManager:GetInstance():DelayInvoke(w,0.1) '
        '  else CS.UnityEngine.Debug.LogError("ACT cross gaveup") end end '
        'TimerManager:GetInstance():DelayInvoke(w,0.1) '
        '%s'
        'CS.UnityEngine.Debug.LogError("ACT cross armed srv=%d")' % (home, server, server, pan, server))


def back_home() -> str:
    """Return from a foreign server to the home server."""
    return ('TimerManager:GetInstance():DelayInvoke(function() '
            'pcall(function() CrossServerUtil.BackToSrcServer() end) '
            'pcall(function() CrossServerUtil.OnBackSelfServer() end) '
            'CS.UnityEngine.Debug.LogError("ACT back done") end, 0.4) '
            'CS.UnityEngine.Debug.LogError("ACT back armed")')
