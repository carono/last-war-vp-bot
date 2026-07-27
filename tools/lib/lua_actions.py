r"""Single source of truth for the confirmed navigation Lua chunks.

Both the panel (via the warm daemon) and the standalone scripts build their in-game Lua
from here, so the recipes never drift. Each function returns a Lua string; run it through
any evaluator with a `.run(chunk, marker, settle)` method (LuaEval or the daemon client).

All recipes are the ones verified live this session — see docs/research/world-tiles.md and
docs/skills/sniff.md §7.
"""
from __future__ import annotations

import os

# Home/world server id fallback, from env LW_DEFAULT_SERVER (0 = unknown; the live
# curServerId is preferred at call time, this is only used when it is missing).
HOME_SERVER = int(os.environ.get("LW_DEFAULT_SERVER") or 0)


def scene_world() -> str:
    """City -> World (renders the world scene)."""
    return 'pcall(function() SceneUtils.ChangeToWorld() end) CS.UnityEngine.Debug.LogError("ACT scene=world")'


def scene_city() -> str:
    """World -> City (home base)."""
    return 'pcall(function() SceneUtils.ChangeToCity() end) CS.UnityEngine.Debug.LogError("ACT scene=city")'


def current_server() -> str:
    """Log `ACT curserver=<id>` — the viewed world server (falls back to HOME_SERVER)."""
    return ('CS.UnityEngine.Debug.LogError("ACT curserver="..tostring('
            '(DataCenter.WorldFavoDataManager and DataCenter.WorldFavoDataManager.curServerId) or '
            '(DataCenter.WarFlagDataManager and DataCenter.WarFlagDataManager.curServerId) or %d))'
            % HOME_SERVER)


def jump_to_coord(x: int, y: int, server: int) -> str:
    """Jump to tile (x, y) on `server` — the game's OWN coordinate navigation.

    Reproduces exactly what the in-game "go to coordinate on server" flow does (open the
    magnifier, pick a target, jump), captured live with `tools/lua_trace.py` while the
    player used it by hand (Player.log):

        GoToUtil.GotoWorldPos(worldPos, 105, nil, nil, serverId)

    `worldPos` is the tile's world position `Vector3(x*2+1, 0, y*2+1)` (world = tile*2, the
    camera lands on the tile). This ONE call covers both cases: a foreign `server` loads and
    enters that server's world (`IsInOtherServer` -> true), the home `server` returns to /
    centres on it (`IsInOtherServer` -> false). No `UIMoveCity` teleport window, no
    authorize-list dance, no forced mid-switch window-close — so map input stays alive
    afterwards. Verified live: srv 972 -> inOther, srv 935 -> home, UIMoveCity never opens.

    Replaces the removed `GotoPos` camera crutch and the `JumpToServerByServerId` move-city
    hack (which popped `UIMoveCity`, force-closed it mid-switch, and left map taps dead).
    """
    sid = int(server)
    return ('pcall(function() GoToUtil.GotoWorldPos('
            'CS.UnityEngine.Vector3(%d*2+1,0,%d*2+1),105,nil,nil,%d) end) '
            'CS.UnityEngine.Debug.LogError("ACT jump=%d,%d srv=%d")'
            % (x, y, sid, x, y, sid))


def _pid(x: int, y: int) -> str:
    """Lua expression: tile index (pointId) for tile (x, y)."""
    return 'SceneUtils.TilePosToIndex(CS.UnityEngine.Vector2Int(%d,%d))' % (x, y)


def move_to_coord(x: int, y: int) -> str:
    """In-server move to tile (x, y) by its pointId — the game's OWN move-to-tile.

    `GoToUtil.MoveToWorldPoint(pid)` centres the camera on a tile on the CURRENT server and
    leaves the world/input state consistent. It takes no `serverId`, so it cannot switch
    servers — for a coordinate jump that may target another server use `jump_to_coord`
    (the game's own `GotoWorldPos` path). Kept as the same-server centring primitive
    (e.g. after a jump, before reading a tile). Verified live: camera centres on (x, y),
    UIManager stack stays empty.
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


def goto_server(server: int, in_move_to_state: bool = False) -> str:
    """Switch to another server's world the way the in-game UI does — the CLEAN path.

    This is the sequence the engine actually runs on a manual server switch, captured with
    `tools/lua_trace.py --dedup` while the player switched servers by hand (Player.log):

        CrossServerUtil.OnCrossServer(serverId)        -- enter the cross-server context
        GoToUtil.GotoServerZone(serverId, false)       -- navigate to that server's zone

    Notably the manual switch used NEITHER `CrossServerUtil.JumpToServerByServerId` NOR
    `SetCrossEnableList` — those belonged to the removed move-city bulk-load hack that also
    popped the `UIMoveCity` teleport window. `GotoServerZone` is the clean entry: no
    teleport UI, no authorize-list dance. It bulk-loads for targets the client is already
    authorized to view — i.e. servers in an active cross-server event group (e.g. the
    yuntie/meteorite battle group the traced switch belonged to).

    This is a bare server switch (no coordinate). To jump straight to a tile on another
    server prefer `jump_to_coord` (`GotoWorldPos`), which is what the in-game coordinate
    jump actually calls and which also enters the server cleanly.

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
