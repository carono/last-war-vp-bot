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


def _pid(x: int, y: int) -> str:
    """Lua expression: tile index (pointId) for tile (x, y)."""
    return 'SceneUtils.TilePosToIndex(CS.UnityEngine.Vector2Int(%d,%d))' % (x, y)


def move_to_coord(x: int, y: int) -> str:
    """In-server move to tile (x, y) by its pointId — the game's OWN move-to-tile.

    This is the real coordinate jump, not the `GotoPos` camera-only tween (see
    `goto_pos`). `GoToUtil.MoveToWorldPoint(pid)` is the path the client itself uses
    to centre on a tile, so it leaves the world/input state consistent — unlike a raw
    camera pan, after which a following map tap can fail to land. Verified live: camera
    centres on (x, y), UIManager stack stays empty. No `serverId` arg — same-server only.
    """
    return ('pcall(function() GoToUtil.MoveToWorldPoint(%s) end) '
            'CS.UnityEngine.Debug.LogError("ACT moveto=%d,%d")' % (_pid(x, y), x, y))


def click_world_point(x: int, y: int, ptype: int = 0, uuid: int = 0) -> str:
    """Perform the in-engine map CLICK on tile (x, y) — navigate AND select in one call.

    `GoToUtil.OnClickWorldPoint(pid, type, uuid)` is exactly what a real tap on the map
    triggers: it moves to the tile and opens its `UIWorldPoint` interaction popup with the
    detail loaded. Using it replaces the fragile "camera-jump + pydirectinput pixel tap"
    crutch (whose tap "doesn't land" / under-sends) — the click happens inside the game, so
    there is nothing to miss. Verified live: reopens UIWorldPoint for the target tile.

    `ptype` = MarchTargetType and `uuid` = the tile's server uuid, both from the tile's
    world.get.block data. Monsters need the real server uuid; own resource/base tiles
    accept uuid=0. When you only have coordinates (no tile data), prefer `move_to_coord`
    to centre the view, then read the tile, then click with its real (type, uuid).
    """
    return ('pcall(function() GoToUtil.OnClickWorldPoint(%s,%d,%s) end) '
            'CS.UnityEngine.Debug.LogError("ACT click=%d,%d type=%d")'
            % (_pid(x, y), ptype, uuid, x, y, ptype))


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


def goto_server(server: int, in_move_to_state: bool = False) -> str:
    """Switch to another server's world the way the in-game UI does — the CLEAN path.

    This is the sequence the engine actually runs on a manual server switch, captured with
    `tools/lua_trace.py --dedup` while the player switched servers by hand (Player.log):

        CrossServerUtil.OnCrossServer(serverId)        -- enter the cross-server context
        GoToUtil.GotoServerZone(serverId, false)       -- navigate to that server's zone

    Notably the manual switch used NEITHER `CrossServerUtil.JumpToServerByServerId` NOR
    `SetCrossEnableList` — those belong to the move-city bulk-load hack (`cross_jump`) that
    also pops the `UIMoveCity` teleport window. `GotoServerZone` is the clean entry: no
    teleport UI, no authorize-list dance. It bulk-loads for targets the client is already
    authorized to view — i.e. servers in an active cross-server event group (e.g. the
    yuntie/meteorite battle group the traced switch belonged to). For an arbitrary
    out-of-event server, `cross_jump` (move-city + close UIMoveCity) is still the fallback.

    `in_move_to_state` is `GotoServerZone`'s second arg (the traced call passed `false`).
    """
    sid = int(server)
    return (
        'pcall(function() CrossServerUtil.OnCrossServer(%d) end) '
        'pcall(function() GoToUtil.GotoServerZone(%d, %s) end) '
        'CS.UnityEngine.Debug.LogError("ACT gotoserver srv=%d reason="..'
        'tostring(select(2,pcall(function() return CrossServerUtil.GetCrossEnableReason(%d) end))))'
        % (sid, sid, "true" if in_move_to_state else "false", sid, sid))


def back_home() -> str:
    """Return from a foreign server to the home server."""
    return ('TimerManager:GetInstance():DelayInvoke(function() '
            'pcall(function() CrossServerUtil.BackToSrcServer() end) '
            'pcall(function() CrossServerUtil.OnBackSelfServer() end) '
            'CS.UnityEngine.Debug.LogError("ACT back done") end, 0.4) '
            'CS.UnityEngine.Debug.LogError("ACT back armed")')
