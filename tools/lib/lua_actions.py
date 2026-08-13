r"""Single source of truth for the confirmed navigation Lua chunks.

Both the panel (via the warm daemon) and the standalone scripts build their in-game Lua
from here, so the recipes never drift. Each function returns a Lua string; run it through
any evaluator with a `.run(chunk, marker, settle)` method (LuaEval or the daemon client).

All recipes are the ones verified live this session — see docs/research/world-tiles.md and
docs/skills/sniff-capture.md §7.
"""
from __future__ import annotations

import os

from rally_kinds import KIND_OF_NAME

# Home/world server id fallback, from env LW_DEFAULT_SERVER (0 = unknown; the live
# curServerId is preferred at call time, this is only used when it is missing).
HOME_SERVER = int(os.environ.get("LW_DEFAULT_SERVER") or 0)


def _kind_table() -> str:
    """The species table as a Lua literal — `name key -> kind` (#1317).

    Built once from `rally_kinds.KIND_OF_NAME`, which was read out of the live config
    rather than written by hand, so a season that adds a boss is a data change here and
    a locale line in the panel, never a new branch in this chunk.
    """
    body = ",".join("['%s']='%s'" % (key, kind)
                    for key, kind in sorted(KIND_OF_NAME.items()))
    return "local KIND_OF_NAME = {%s} " % body


def scene_world() -> str:
    """City -> World (renders the world scene)."""
    return 'pcall(function() SceneUtils.ChangeToWorld() end) CS.UnityEngine.Debug.LogError("ACT scene=world")'


def scene_city() -> str:
    """World -> City (home base)."""
    return 'pcall(function() SceneUtils.ChangeToCity() end) CS.UnityEngine.Debug.LogError("ACT scene=city")'


def current_server_expr() -> str:
    """Lua EXPRESSION for the server the client is looking at (HOME_SERVER if it will not say).

    An expression rather than only a chunk, because the answer is worth more inside
    another chunk than as a round trip of its own: reading it first and then acting on
    it cost a whole extra call to the VM — measured at 570-1300 ms in front of every
    coordinate jump, which was the second the panel felt slower than the game (#1230).
    """
    # `tonumber(tostring(…))` because the id is read off a C# field and is passed on to
    # a call that wants a number: it was a Python `int()` of the logged text before this
    # was ever a Lua expression, and the coercion has to survive the move.
    return ('(tonumber(tostring('
            '(DataCenter.WorldFavoDataManager and DataCenter.WorldFavoDataManager.curServerId) or '
            '(DataCenter.WarFlagDataManager and DataCenter.WarFlagDataManager.curServerId) or %d)) or %d)'
            % (HOME_SERVER, HOME_SERVER))


def current_server() -> str:
    """Log `ACT curserver=<id>` — the viewed world server (falls back to HOME_SERVER)."""
    return ('CS.UnityEngine.Debug.LogError("ACT curserver="..tostring(%s))'
            % current_server_expr())


#: The camera height the in-game coordinate jump uses — the client's own `InitZoom`.
#: Every jump that is about ONE tile keeps it: it is the height at which a person can
#: read the tile they landed on.
JUMP_ZOOM = 105

#: The highest camera height at which the server still sends SECRET-TASK tiles, and the
#: number a map sweep wants (task #1265, docs/research/map-sweep-zoom.md). Tile loading
#: is gated on the client's LOD, whose ladder is 150 / 250 / 400 / 600 / 1200 / … — so
#: 600 is the top of LOD 4, and 601 is LOD 5, where `f2=17` tiles stop arriving
#: altogether while bases, mines and strongholds keep coming. Measured live: one jump
#: at 105 loaded 9 secret tasks, the same jump at 600 loaded 112.
SWEEP_ZOOM_MAX = 600

#: The highest camera height at which the map still arrives AT ALL — the top of LOD 5.
#: Secret-task and ghost-recon tiles are already gone here (that is what
#: `SWEEP_ZOOM_MAX` is for), but bases, mines, alliance cities and strongholds still
#: come, and they come over four times the ground per jump. One step higher — 1200, LOD
#: 6 — and `world.get.block` answers with no tiles at all: the client has switched to the
#: coarse big-map layer, which is a different message. So this is literally the last
#: height at which player bases can be collected (#1265).
#:
#: 1199 and not 1200 on purpose. The client stores the height as a float and hands back
#: a hair MORE than it was given (1200 reads as 1200.0001), and the LOD ladder compares
#: on `>=` — so asking for exactly 1200 lands in LOD 6 and fetches nothing.
BASE_ZOOM_MAX = 1199

#: How far apart two waypoints of a FAST lap are. One jump at `SWEEP_ZOOM_MAX` loads
#: ±48 tiles in its shortest direction, so 90 overlaps by a few tiles at every seam and
#: a 1000-tile server is an 11 × 11 grid.
FAST_STEP = 90

#: The three heights the panel offers, `id -> (camera height, sweep step)`, named by what
#: each is FOR rather than by its number: a person choosing between them is choosing what
#: they want to see, not a camera setting.
#:
#: The step of each is what a live lap measured, not what the geometry suggested. At
#: `tasks` a lap of step 90 finds every secret task a lap of step 45 finds (604 against
#: 603 — the difference is tiles expiring mid-run), so 90 is complete for what that level
#: is FOR. At `bases`, where the tiles are far denser, the count does keep climbing:
#: 4 502 bases at step 150, **4 818 at 100**, 4 945 at 70 — so 100 is where the curve
#: flattens against the clock (~5 s a lap against 13). A step belongs to its height and
#: is meaningless without it.
ZOOM_LEVELS: dict = {
    "tile": (JUMP_ZOOM, 24),
    "tasks": (SWEEP_ZOOM_MAX, FAST_STEP),
    "bases": (BASE_ZOOM_MAX, 100),
}

#: What a jump with no height asked for uses — the game's own, so that a coordinate
#: clicked in the log still lands where a person can read the tile.
DEFAULT_ZOOM_LEVEL = "tile"


#: The heights a LAP is worth walking at (#1272). «Тайл» is not among them and must not
#: come back: a lap at 105 needs a 24-tile step, which is 88 SECONDS of camera against 6
#: at 600 — and it finds nothing the 600 lap does not, because 600 is the ceiling at
#: which the client still asks for secret tasks at all (docs/research/map-sweep-zoom.md).
#:
#: It used to be offered because one control drove both the lap and every JUMP, so
#: anybody who wanted to land on a readable tile picked «тайл» and thereby signed up for
#: an 88-second sweep. Jumps do not take a height any more — they are always the tile
#: view, decided in one place (`GameLink.jump`) — so this control is about the lap and
#: nothing else.
SWEEP_LEVELS = ("tasks", "bases")


def zoom_level(name: "str | None") -> tuple:
    """``(height, step)`` of a named level, falling back to the tile view.

    An unknown name is answered rather than raised on: the name comes out of a saved
    profile, and a panel that will not draw because a settings file has an old word in
    it is worse than one that opens at the close view.
    """
    return ZOOM_LEVELS.get(name or "", ZOOM_LEVELS[DEFAULT_ZOOM_LEVEL])

#: Seconds between two waypoints of a fast lap. The client fires one `world.get.block`
#: per view change with no debounce, so the floor is not the camera — it is the wire.
#: Measured: 0.05 delivered 100/100 responses, and asking for 0.01 still delivered
#: 121/121 while the traffic took 2.9 s to drain, so anything below ~0.02 buys nothing.
FAST_INTERVAL = 0.05


def jump_to_coord(x: int, y: int, server: "int | None" = None,
                  zoom: "int | None" = None) -> str:
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
    afterwards. Verified live: srv 300 -> inOther, srv 100 -> home, UIMoveCity never opens.

    Replaces the removed `GotoPos` camera crutch and the `JumpToServerByServerId` move-city
    hack (which popped `UIMoveCity`, force-closed it mid-switch, and left map taps dead).

    ``server=None`` means "the one being looked at", and the chunk asks the game for it
    ITSELF (`current_server_expr`). A coordinate without a server is the ordinary case —
    a link clicked in the log, a row in «Командный пункт» — and the panel used to answer
    it with a separate read before the jump: one more trip through the Lua VM, one more
    settle, and the game only started moving after both (#1230).

    ``zoom`` is the second argument of that call — the camera's height, which decides how
    much map the client asks the server for. It defaults to the game's own `JUMP_ZOOM`,
    so a jump that is about one tile is unchanged. A sweep looking for tiles passes
    `SWEEP_ZOOM_MAX` instead and covers roughly twelve times the ground per jump.

    **Set it BEFORE the jump when it matters.** `GotoWorldPos` tweens position and zoom
    together, so a jump that also zooms out spends its last frames over the target at a
    lower height — and picks up tiles the height being asked for would never have loaded.
    A sweep is unaffected because every waypoint uses the same number, but a measurement
    that changes it per jump is measuring the tween (#1265).
    """
    sid = str(int(server)) if server is not None else current_server_expr()
    height = int(JUMP_ZOOM if zoom is None else zoom)
    return ('local srv=%s pcall(function() GoToUtil.GotoWorldPos('
            'CS.UnityEngine.Vector3(%d*2+1,0,%d*2+1),%d,nil,nil,srv) end) '
            'CS.UnityEngine.Debug.LogError("ACT jump=%d,%d srv="..tostring(srv))'
            % (sid, x, y, height, x, y))


#: Lua that finds the live `WorldScene` MonoBehaviour and caches it in `_G.WS`. The
#: scene is not a Lua global — it is a C# component on the `World` GameObject — and it
#: is replaced whenever the world is re-entered, so the cache is validated rather than
#: trusted.
#:
#: THE VALUE IS CHECKED, NOT MERELY THE ACCESS (#1296). A destroyed Unity object does not
#: throw when a member is read off it — it answers `nil` — so a guard that only asked
#: whether the read succeeded kept a dead scene for ever, and everything hanging off it
#: (`PointManager`, `TileCount`, `CurTilePos`) was `nil` with nothing saying why. Caught
#: live: a treasure lap reported 121 waypoints scheduled and 0 read, because `WS` was a
#: WorldScene from a session that had ended. Reading `CurTilePos` and requiring a VALUE
#: costs the same one access and re-finds the live one instead.
FIND_WORLD_SCENE = (
    'local WS=_G.WS local __ok, __cur = pcall(function() return WS and WS.CurTilePos end) '
    'if not __ok or __cur == nil then '
    'local arr=CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) '
    'for i=0,arr.Length-1 do if arr[i] and arr[i]:GetType().Name=="WorldScene" then '
    'WS=arr[i] break end end _G.WS=WS end ')


def fast_map_sweep(zoom: "int | None" = None, step: "int | None" = None,
                   interval: "float | None" = None,
                   server: "int | None" = None) -> str:
    """One lap of the WHOLE server map, scheduled inside the game — the fast swipe.

    A lap driven from Python is a lap of round trips: ~150 ms each way, so 121 waypoints
    is twenty seconds of socket and almost no game. This hands the entire waypoint list
    to the game's own `TimerManager:DelayInvoke` in ONE call. The game then walks it at
    `interval`, the view rect moves every time, and — because the client does not
    debounce map requests — a `world.get.block` goes out for each. The answers land in
    the ordinary passive capture the panel already runs.

    **This is the thing that was thought impossible.** The note under task #1053 said a
    scripted camera move emits no map traffic and only a human drag gesture does, so the
    sweep had to be somebody's wrist. That was true of the REMOVED `GotoPos` crutch and
    is not true of `GotoWorldPos`, which is the game's own coordinate jump: measured
    live, 121 scheduled jumps produced 121 requests and 121 responses, with no gesture,
    no focus and no pixels (#1265). Nothing needs to be imitated.

    The grid is built from the scene's OWN `TileCount`, so it is a lap of whatever server
    is being looked at rather than of a number written down here. Waypoints run
    serpentine — the camera never travels the long way between two neighbours.

    `zoom` picks WHAT the lap collects, and there are only two heights worth passing:
    `SWEEP_ZOOM_MAX` (secret tasks, ghost recon and everything else) or `BASE_ZOOM_MAX`
    (four times the ground, bases and mines, no tasks). Above the second one the client
    fetches nothing at all.

    Measured live on a 1000 × 1000 server, one lap at `SWEEP_ZOOM_MAX`: **2.6 s**, 121
    requests, 20 742 tiles, 597 distinct secret tasks and 189 ghost-recon tiles. The same
    lap at `BASE_ZOOM_MAX` needs 49 waypoints and finds 4 762 bases in 2.6 s.

    `server` NAMES the server the waypoints are walked on (#1280). Left out, the lap asks
    the client — `current_server_expr()`, which reads `WorldFavoDataManager.curServerId`
    and falls back to `HOME_SERVER` (0 unless the machine sets it). That answer is a
    cached manager field rather than the camera: «перехожу на другой сервер, жму обход —
    возвращает на предыдущий», live. So a caller that knows where the person actually is
    — the panel's «Сервер» box, filled by «↻ сервер» and by every jump — says so, and
    the guess stays only for callers that have nothing to say.
    """
    height = int(SWEEP_ZOOM_MAX if zoom is None else zoom)
    stride = max(1, int(FAST_STEP if step is None else step))
    gap = max(0.0, float(FAST_INTERVAL if interval is None else interval))
    where = str(int(server)) if server else current_server_expr()
    return (FIND_WORLD_SCENE + '''
local DC = DataCenter.ActDispatchTaskDataManager
-- EVERY WAYPOINT IS SCHEDULED AT ONCE, so a lap cannot be called back — the game's own
-- timer owns them from here (#1272). What it CAN be is disowned: each closure checks the
-- run token it was scheduled under, and `fast_map_sweep_stop` bumps it. A stopped lap
-- therefore costs the timers that are still pending exactly one comparison each.
DC.__lw_sweep_run = (tonumber(DC.__lw_sweep_run) or 0) + 1
local run = DC.__lw_sweep_run
local srv=%s
local size = 1000
pcall(function() size = WS.TileCount.x end)
local step, half = %d, math.floor(%d / 2)
local axis = {}
local v = half
while v < size do axis[#axis+1] = v v = v + step end
local V3, tm = CS.UnityEngine.Vector3, TimerManager:GetInstance()
local n = 0
for row = 1, #axis do
  local y = axis[row]
  for col = 1, #axis do
    -- Serpentine: every other row is walked backwards, so consecutive waypoints are
    -- neighbours and the camera never crosses the map between two of them.
    local x = axis[(row %% 2 == 1) and col or (#axis - col + 1)]
    n = n + 1
    tm:DelayInvoke(function()
      if DC.__lw_sweep_run ~= run then return end
      pcall(function() GoToUtil.GotoWorldPos(V3(x*2+1, 0, y*2+1), %d, 0, nil, srv) end)
    end, (n - 1) * %f)
  end
end
CS.UnityEngine.Debug.LogError("ACT sweep n="..n.." zoom=%d step=%d span="
  ..string.format("%%.1f", (n - 1) * %f).." size="..tostring(size))
''' % (where, stride, stride, height, gap, height, stride, gap))


def fast_map_sweep_stop() -> str:
    """Disown every waypoint a lap still has pending — «Остановить» (#1272).

    The lap hands its whole waypoint list to the game's own timer in one call, so there
    is nothing to cancel and no handle to cancel it with. Bumping the run token is the
    interruption: each pending closure compares it before moving the camera and returns
    when it does not match. The camera stops at wherever it had got to.
    """
    return ("local DC = DataCenter.ActDispatchTaskDataManager "
            "DC.__lw_sweep_run = (tonumber(DC.__lw_sweep_run) or 0) + 1 "
            'CS.UnityEngine.Debug.LogError("ACT sweep_stopped run="'
            "..tostring(DC.__lw_sweep_run))")


def fast_sweep_seconds(step: "int | None" = None, interval: "float | None" = None,
                       size: int = 1000) -> float:
    """How long one `fast_map_sweep` lap takes, so a caller can wait it out.

    The waypoint count is the same arithmetic the Lua does; `size` is the server's tile
    count, which only matters for the estimate — the lap itself asks the scene.
    """
    stride = max(1, int(FAST_STEP if step is None else step))
    gap = max(0.0, float(FAST_INTERVAL if interval is None else interval))
    per_axis = len(range(stride // 2, size, stride))
    return (per_axis * per_axis - 1) * gap


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


# ---------------------------------------------------------------------------
# Chat send (DM / room). Reverse-engineered live from a PM trace to <Player9>
# (task #1085): text, inline emoji and stickers. See docs/research/chat-send.md.
#
# Every chat send funnels through ONE choke point in the client:
#     ChatManager2:__sendToRoom(roomId, msg, extra, reply, isProxy, post)
# which builds and fires both wire commands (`lw.user.push.chat.msg` + the
# `chat.stat` telemetry twin). `extra` is an optional msgExtra table (srcLang,
# post, atUids, ...) — every field is read defensively, so an empty `{}` sends a
# clean plain message. `reply`=nil, `isProxy`=0, `post`=nil are the text defaults
# captured on the wire.
#
# Room id shapes (docs/research/chat.md §2):
#   DM        custom_<peerUid>_<selfUid>_v2
#   World     country_<server>
#   National  custom_lang_<lang>_<server>
#   Alliance  alliance_<serverId>_<allianceId>
#
# Inline emoji are Private Use Area glyphs (U+E000-U+F8FF) sitting *inside* the
# msg string; emoji id -> PUA is `ChatEmojiTemplateManager:GetEmojiDataById(id).name`
# (a PUA hex stem, e.g. 101 -> "e006" -> U+E006). Resolve those to real chars in
# the caller and hand the finished string here, so this recipe stays a pure send.
#
# Stickers are NOT text — they ride their own manager entry:
#     ChatEmojiTemplateManager:TrySendSticker(roomId, stickerId)


def _lua_bytes(s: str) -> str:
    """A Lua expression rebuilding `s` byte-for-byte via string.char.

    Avoids all quoting/escaping hazards for Cyrillic / CJK / PUA-emoji text when the
    chunk is shipped to the daemon and compiled by xLua (Lua strings are byte arrays).
    """
    b = s.encode("utf-8")
    if not b:
        return '""'
    return "string.char(" + ",".join(str(x) for x in b) + ")"


def chat_send_text(room_id: str, msg: str) -> str:
    """Send `msg` (already-assembled text, may contain inline PUA emoji) to `room_id`."""
    return (
        'pcall(function() local CM=ChatManager2 local inst=CM.GetInstance(CM) '
        'CM.__sendToRoom(inst, %s, %s, {}, nil, 0, nil) end) '
        'CS.UnityEngine.Debug.LogError("ACT chat_sent")'
        % (_lua_bytes(room_id), _lua_bytes(msg))
    )


def chat_send_sticker(room_id: str, sticker_id: int) -> str:
    """Send sticker `sticker_id` to `room_id` via the emoji/sticker manager."""
    return (
        'pcall(function() local em=DataCenter.ChatEmojiTemplateManager '
        'em:TrySendSticker(%s, %d) end) '
        'CS.UnityEngine.Debug.LogError("ACT chat_sticker_sent")'
        % (_lua_bytes(room_id), int(sticker_id))
    )


# ---------------------------------------------------------------------------
# Coordinate ("point") share. Reverse-engineered live for task #1089 from a PM
# trace to <Player9> — see docs/research/chat-coord-share.md.
#
# A shared coordinate is NOT text: it is `post = 13` (PostType.Text_PointShare)
# plus an `attachmentId` JSON blob describing the map object. The base `msg` is
# the literal placeholder "?" — the client renders the bubble from attachmentId
# (ChatMessage:getMessageWithExtra()).
#
# It also does NOT ride `ChatManager2:__sendToRoom`: that path rebuilds `extra`
# and silently drops attachmentId (verified — the echo came back with an empty
# attachment and "this message type is not supported by your game version").
# Shares go out as their own command class, `Chat.NetMessage.ChatShareCommand`,
# dispatched on the chat connection:
#
#     ChatManager2:GetInstance().Net:SendSFSMessage(<cmd>, param)
#
# `ChatShareCommand:OnCreate(param)` reads, in order:
#     post, lang, msg, roomId, tradeName, itemIds, tradePoint, attachmentId,
#     chatType, langRoomLang, toUser, reportUid, cardUuid, planIndex, bossUid,
#     ossAddress, serverIdEx, introductionEx, freeEx
# — everything past `attachmentId` belongs to other share kinds and may be nil.
#
# The command differs per channel (ChatMsgDefines):
#     DM        chat.room.send   (ChatSharePerson)   + toUser = peer uid
#     World     chat.country     (ChatShareCountry)
#     National  chat.country     + langRoomLang = <lang>
#     Alliance  al.msg           (ChatShareAlliance)

POST_POINT_SHARE = 13          # PostType.Text_PointShare

CMD_SHARE_DM = "chat.room.send"
CMD_SHARE_COUNTRY = "chat.country"
CMD_SHARE_ALLIANCE = "al.msg"


def chat_share_cmd(room_id: str) -> str:
    """The share command for a room id (see the table above)."""
    if room_id.startswith("alliance_"):
        return CMD_SHARE_ALLIANCE
    if room_id.startswith("country_") or room_id.startswith("custom_lang_"):
        return CMD_SHARE_COUNTRY
    return CMD_SHARE_DM


def _lua_opt(key: str, value) -> str:
    """`key=<lua>` fragment, or '' when the value is unset (keeps the field nil)."""
    if value in (None, ""):
        return ""
    return "%s=%s, " % (key, _lua_bytes(str(value)))


def chat_share_point(room_id: str, attachment_json: str, post: int = POST_POINT_SHARE,
                     lang: str = "ru", to_user=None, lang_room=None, cmd=None) -> str:
    """Share a map coordinate (`attachment_json`) into `room_id`.

    `attachment_json` is the already-serialised attachmentId blob — the caller owns its
    shape, since it differs per object kind (bare point, mine, monster, secret task...).
    """
    return (
        'pcall(function() local CM=ChatManager2 local inst=CM.GetInstance(CM) '
        'inst.Net:SendSFSMessage(%s, {post=%d, lang=%s, msg="?", roomId=%s, '
        'attachmentId=%s, %s%schatType=0}) end) '
        'CS.UnityEngine.Debug.LogError("ACT chat_point_sent")'
        % (_lua_bytes(cmd or chat_share_cmd(room_id)), int(post), _lua_bytes(lang),
           _lua_bytes(room_id), _lua_bytes(attachment_json),
           _lua_opt("toUser", to_user), _lua_opt("langRoomLang", lang_room))
    )


# --------------------------------------------------------------------------
# Government / ministry — the server's kingdom positions ("министерство")
# --------------------------------------------------------------------------
# The President appoints eight posts; a player asks for one by submitting an
# application. On the wire that is a single command, `kingdom.position.apply`,
# whose only field `positionId` is serialised as a UtfString.
#
# POSITION IDS ARE STRINGS, EVERYWHERE. `GetCanApplyGovernmentList()` hands back
# `"10007"`, not `10007`, and the apply manager keys its own tables the same way, so
# `CheckCanApply(10007)` answers **false** while `CheckCanApply("10007")` answers the
# truth — a silent wrong answer, not an error. Passing a number to
# `SendKingdomPositionApply` is the louder half of the same rule: the client's
# serialiser then throws "attempt to get length of a number value"
# (SFSDataSerializer). Every chunk below quotes the id for exactly this reason.
#
# Ids and names were read live off `GovernmentTemplateManager:GetTemplateName(id)`.
# The template's `type` field splits them into two families that are NOT applied for
# on the same terms: `type == 0` is the ordinary ministry, `type == 1` are the zone-war
# commanders, which only the conqueror may ask for. `slug` is the name the DSL `TAP`
# catalogue uses (tools/lib/game_buttons.py generates one button per post).
# See docs/research/ministry.md.
MINISTRY_POSTS: dict[int, tuple[str, str, str]] = {
    # id: (slug, English gloss, the in-game Russian name)
    10002: ("vice_president", "Vice President", "Вице-президент"),
    10003: ("minister_strategy", "Minister of Strategy", "Министр стратегии"),
    10004: ("minister_defence", "Minister of Defence", "Министр обороны"),
    10005: ("minister_construction", "Minister of Construction", "Министр строительства"),
    10006: ("minister_science", "Minister of Science", "Министр науки"),
    10007: ("minister_interior", "Minister of the Interior", "Министр внутренних дел"),
    10008: ("commander_military", "Military Commander", "Военный командир"),
    10009: ("commander_admin", "Administrative Commander", "Административный командир"),
}

# slug -> id, for CLI arguments that name a post instead of numbering it.
MINISTRY_SLUGS: dict[str, int] = {slug: pid for pid, (slug, _, _) in MINISTRY_POSTS.items()}


def ministry_apply_cooldown_ms(position_id: int) -> str:
    """Lua *expression* -> milliseconds left on the apply cooldown for `position_id`.

    `0` when the post may be asked for now (and when the reading is unavailable, so an
    unknown client cannot lock the ability out). Roughly 1_800_000 straight after an
    application — the same half hour the resign lock runs for.

    This is the real pre-flight, and it is NOT the one the manager advertises.
    `GetOwnApplyCD` reads `ownApplyTimeList[id]` against a config value and the server
    clock; read live it answered `1_696_421` (~28 min) 45 s after an application, and a
    large negative number for posts never asked for. Sending anyway earns
    `errorCode E000000, errorMsg "in cd"` and a toast — the trap the collect-readiness
    gate exists for.

    The id is a STRING here for the usual reason, and this one is worth naming twice:
    `GetOwnApplyCD(10007)` answers a flat `0` — "go ahead" — while
    `GetOwnApplyCD('10007')` answers the truth.
    """
    return ("(function() local ok, cd = pcall(function() "
            "return DataCenter.OfficialApplyManager:GetOwnApplyCD('%d') end) "
            "if not ok or type(cd) ~= 'number' or cd < 0 then return 0 end "
            "return math.floor(cd) end)()" % int(position_id))


def _ministry_gate(position_id: int) -> str:
    """Lua expression: may an application for `position_id` be sent right now?

    Four conditions, and the client's own `CheckCanApply` is only the weakest of them.
    Read back, that method walks `GetCanApplyGovernmentList()` and answers whether the
    id is *in the list* — it is a "does this post exist" test, not a permission one,
    which is why it says `true` while a post is held, while the cooldown runs, and for
    the commander posts nobody may have. Everything it does not cover has to be here,
    because every miss is a request that leaves the client, is rejected, and puts a
    toast in the player's face:

    * `CheckCanApply(id)` — the post is one of the applicable ones at all.
    * the apply cooldown (`ministry_apply_cooldown_ms`) — `errorMsg "in cd"`.
    * a post already held — `errorMsg "has position"`, observed live holding 10005.
    * the conqueror check for `type == 1` posts (the zone-war commanders): the server
      answers `errorCode officer_apply_045`, `errorMsg "not conqueror <alliance uuid>"`.
      Observed live against the Administrative Commander post.

    The conqueror half is verified only in the negative (a non-conqueror is correctly
    blocked); no conqueror account was available to confirm it opens.
    """
    return (
        "(function() local M=DataCenter.OfficialApplyManager "
        "local G=DataCenter.GovernmentManager "
        "if not M:CheckCanApply('%d') then return false end "
        "if %s > 0 then return false end "
        "local ok, own = pcall(function() return M:GetOwnPositionId() end) "
        "if ok and (tonumber(own) or 0) > 0 then return false end "
        "local t=DataCenter.GovernmentTemplateManager:GetTemplate('%d') "
        "if t and t.type==1 then return G:IsConqueror(G.curDataServerId) and true or false end "
        "return true end)()" % (int(position_id), ministry_apply_cooldown_ms(position_id),
                                int(position_id))
    )


def ministry_apply(position_id: int) -> str:
    """Submit an application for kingdom position `position_id`.

    Headless — no window has to be open. The in-game "Подать заявку" button is
    `UIOfficialApplyCtrl:SendKingdomPositionApply(positionId)`, and that method never
    touches `self`, so the module table can stand in for the window controller.

    Gated by `_ministry_gate` — without it the application still leaves the client and
    comes back as a server-side rejection with a player-facing toast, the same trap as
    the resource-collect readiness gate.
    """
    return (
        "local M = DataCenter.OfficialApplyManager "
        "local id = '%d' "
        "if %s then "
        "M:SetViewPositionId(id) "
        "local C = require('UI.UIGovernment.OfficialApply.Controller.UIOfficialApplyCtrl') "
        "C.SendKingdomPositionApply(C, id) end" % (int(position_id), _ministry_gate(position_id))
    )


def ministry_can_apply(position_id: int) -> str:
    """Lua *expression* -> 1 when an application for `position_id` would be accepted.

    Numeric on purpose: it is what `TAP <post> xall` counts down and what a recipe reads
    with `READ_LUA … INTO <var>` to decide whether to bother applying at all. Mirrors
    `ministry_apply`'s gate exactly, so `xall` never reports a press that the chunk then
    silently declines to make.
    """
    return "(%s and 1 or 0)" % _ministry_gate(position_id)


def ministry_own_position() -> str:
    """Lua *expression* -> the id of the post you hold right now, `0` when none.

    The one reading that says whether an application went through: the server grants an
    accepted application straight away, so a round trip later the held post either is the
    one asked for or the request did not take. Proven both ways —
    `0` -> `10007` on the application recorded in docs/research/ministry.md, and unmoved
    at `10005` when the server answered `errorMsg "has position"`.

    It is also the reading that says an application must NOT be sent at all: the server
    refuses one from a player who already holds a post, and `CheckCanApply` does not
    cover that (it answers `true` while a post is held). Without the check the request
    leaves the client, is rejected, and the player gets a toast for it.

    Numeric, so a recipe can test it with the ordinary `IF post == 10007` conditions.
    """
    return ("(function() local ok, p = pcall(function() "
            "return DataCenter.OfficialApplyManager:GetOwnPositionId() end) "
            "if not ok or p == nil then p = DataCenter.GovernmentManager.self_positionId end "
            "return tonumber(p) or 0 end)()")


def ministry_queue_len(position_id: int) -> str:
    """Lua *expression* -> how many players are queued for `position_id`.

    The list is server-fed and NOT pushed: it only holds data after
    `ministry_fetch_queues()` has been run and the reply has landed (~1 s).
    """
    return ("(function() local n=0 "
            "for _ in pairs(DataCenter.OfficialApplyManager:GetApplyList('%d') or {}) do n=n+1 end "
            "return n end)()" % int(position_id))


def ministry_held_minutes(position_id: int) -> str:
    """Lua *expression* -> how many minutes the current holder of `position_id` has sat.

    -1 when the post is vacant (or its holder has not been loaded yet), so a recipe can
    tell "empty seat" from "just appointed".
    """
    return ("(function() local i=DataCenter.GovernmentManager:GetPositionInfoByPositionId('%d') "
            "if not i or not i.appointTime or i.appointTime==0 then return -1 end "
            "return (UITimeManager.Instance:GetSocketTime()-i.appointTime)/60000 end)()"
            % int(position_id))


def ministry_fetch_board() -> str:
    """Load the board: the kingdom's post holders, plus every applicant queue.

    Two requests, both fire-and-forget — read the result from a SEPARATE chunk after a
    settle (never loop-and-wait inside one chunk, it freezes the client):

      * `get.kingdom.positions <the loaded kingdom>` refreshes the holder table.
      * `kingdom.position.apply.list` per post fills the applicant queues, which are
        never pushed and stay empty until asked for.

    The kingdom asked about is `GovernmentManager.curDataServerId` — whichever one the
    client currently has loaded. No attempt is made to pin the board to "my own"
    kingdom: the logged-in account is not a constant (operators switch accounts), and
    the client may be showing a kingdom it was merely browsing. So the reader gets
    what is actually there rather than an assertion — every board row carries its
    holder's server, which makes whose ministry is on screen visible.
    """
    return ("local M = DataCenter.OfficialApplyManager "
            "local G = DataCenter.GovernmentManager "
            "pcall(function() SFSNetwork.SendMessage('get.kingdom.positions', G.curDataServerId) end) "
            "for _, id in pairs(M:GetCanApplyGovernmentList() or {}) do "
            "pcall(function() M:SendKingdomPositionApplyList(id) end) end "
            'CS.UnityEngine.Debug.LogError("ACT ministry_board_requested")')


# --------------------------------------------------------------------------
# Alliance tech — the "Donate 1000" button of the priority science
# --------------------------------------------------------------------------
# `UIAllianceScienceInfoCtrl:OnResDonateClick(scienceId, resType, resNum, btnPos,
# techPointPos)` is the whole donation. Read back with `string.dump`, its body is:
#
#     if LuaEntry.Resource:GetCntByResType(resType) < need then
#         UIUtil.ShowTipsId(...); LWResourceLackUtil.GotoResLack(...); return end
#     if DataCenter.AllianceScienceDataManager:GetResDonateRestCount() <= 0 then ... end
#     SFSNetwork.SendMessage(MsgDefines.AlScienceDonate, ...)   -- 'al.science.donate'
#
# — no `self` field is touched (the dump lists `self` as an unused parameter, and
# `btnPos`/`techPointPos` only anchor the reward-fly animation). So the press does NOT
# need the detail window, or any window: `require`-ing the controller module and calling
# the method with `nil` for self sends the donation from a closed base view. Confirmed
# live with `GetStackTopWindow() == nil`: attempts 14 -> 13.
#
# Both gates read state the server has not yet updated — a donation in flight lowers
# neither the resource count nor the attempt count until `al.science.donate` comes back —
# which is what makes BATCHING work: `n` presses inside ONE Lua call all pass the gate
# and all reach the server. Proven live: one chunk with n=5 took attempts 13 -> 8, and a
# second with n=8 emptied the quota, each in ~0.2 s. That is the whole point of
# `alliance_donate_batch`: a round trip to the VM costs ~0.15 s while the loop inside it
# is free, so a full 30-attempt quota is one call, not thirty.
#
# The freeze pitfall of docs/research/alliance-tech-donate.md still stands and is the
# reason the loop counts to a FIXED `n` instead of looping until the count drops: a
# `while rest > 0` in Lua would spin on a value that cannot change before the frame ends
# and hang the client. The caller reads the real count, presses exactly that many, and
# re-reads to confirm — the count is still the stop condition, just not per press.
_SCIENCE_CTRL = "UI.UIAlliance.UIAllianceScienceInfo.Controller.UIAllianceScienceInfoCtrl"


def alliance_donate_rest(use_gold: bool = False) -> str:
    """Lua *expression* -> donation attempts still banked today (resource, or diamond)."""
    getter = "GetGoldDonateRestCount" if use_gold else "GetResDonateRestCount"
    return "DataCenter.AllianceScienceDataManager:%s()" % getter


def alliance_donate_press(use_gold: bool = False) -> str:
    """One donation to the priority tech — headless, no window open."""
    return alliance_donate_batch(use_gold, times="1", quiet=True)


def alliance_donate_batch(use_gold: bool = False, times: str = "n",
                          quiet: bool = False) -> str:
    """Donate `times` times to the priority tech in ONE game-VM call.

    `times` defaults to the Lua local `n`, which the caller prepends
    (`local n = 7 ` .. this chunk). Unless `quiet`, the chunk reports how many
    presses it actually fired as `ACT fired=<k>` — `k` is below `n` only when the
    run went broke mid-batch.

    The resource check mirrors the controller's own gate, so a batch that would run
    out of resources stops instead of walking into `GotoResLack` (which pops the
    buy-resources window). Like every other counter here it lags the server by a
    round trip, so it catches "already broke", not "broke on this press".
    """
    method = "OnGoldDonateClick" if use_gold else "OnResDonateClick"
    args = "rec.scienceId, rec.goldNum, nil, nil" if use_gold \
        else "rec.scienceId, rec.res, rec.resNum, nil, nil"
    afford = "true" if use_gold else \
        "LuaEntry.Resource:GetCntByResType(rec.res) >= rec.resNum"
    report = "" if quiet else \
        ' CS.UnityEngine.Debug.LogError("ACT fired="..tostring(fired))'
    return (
        "local rec = DataCenter.AllianceScienceDataManager:GetCurRecommendScience() "
        "local ctrl = require('%s') "
        "local fired = 0 "
        "if rec then for _ = 1, %s do "
        "if not (%s) then break end "
        "ctrl.%s(nil, %s) "
        "fired = fired + 1 "
        "end end%s" % (_SCIENCE_CTRL, times, afford, method, args, report)
    )


# --------------------------------------------------------------------------
# Alliance help — the "Помочь всем" button
# --------------------------------------------------------------------------
# `DataCenter.AllianceHelpDataManager:OnHelpAll(otherHelpInfoList)` looks like the
# action and is not: its whole body is `self.otherHelpInfoList = ...` plus
# `self:SetHelpNum(...)`, and its only caller is `AlHelpAllMessage:HandleMessage`.
# It is the *reply applier*. Calling it directly empties the pending list on screen
# and sends nothing — the request vanishes, no alliancemate is helped. That was the
# bug in the first version of this recipe (trace 20260728_232122).
#
# The press is `UILWAlHelpCtrl:OnClickHelpAll`, whose one network line is
#
#     SFSNetwork.SendMessage(MsgDefines.AlHelpAll,   -- 'al.help.all'
#                            curTime, helpAllBtnPos, toPos, nil, true)
#
# and `AlHelpAllMessage:OnCreate` puts exactly ONE field into the SFSObject —
# `cmdBaseTime`. The trailing arguments are kept client-side as `_helpBtnPos` /
# `_flyToPos` / `_isOnlyDisperse` / `_isOnlyShowDiff` and only drive the reward-fly
# animation, so the send needs no window open: `Vector3.zero` twice stands in for the
# on-screen button, matching the real click's `nil, true` tail. Confirmed live —
# `--> al.help.all cmdBaseTime=…` followed by the server's `<-- al.help.all`, with the
# pending list dropping to zero.
#
# The controller gates the send on `can_help` (at least one entry that is not mine),
# and shows tip 390170 otherwise. `alliance_help_pending()` is that same predicate as
# a number — but it is only HALF of "somebody is waiting", and on its own it is the
# half that a headless bot almost never sees. `push.al.help.new` does not put the new
# request into `GetAllianceHelpList()`; its handler only does
# `SetHelpNum(GetHelpNum() + 1)`. The list is filled by the help window's own query and
# rewritten by the `al.help.all` reply, so with no window ever opened it holds nothing
# but my own requests, and a list-only gate declines every request that arrives while
# the bot is running (four live pushes, four refusals — task #1113).
# `alliance_help_waiting()` therefore takes the larger of the two signals, and that is
# what both the chunk gate and the button's `xall` counter use. The red-point count is
# reset by the server's reply (5 -> 0, observed on the wire), so it terminates the loop.
def alliance_help_pending() -> str:
    """Lua *expression* -> alliancemates waiting for help *in the client's list*.

    Non-self entries of `GetAllianceHelpList()`; my own open requests sit in the same
    list (`isSelf == true`) and are not helpable, so they are skipped. Blind to a
    request that has only just arrived — see `alliance_help_waiting()`.
    """
    return ("(function() local n = 0 "
            "for _, it in ipairs(DataCenter.AllianceHelpDataManager:GetAllianceHelpList() or {}) do "
            "if not it.isSelf then n = n + 1 end end "
            "return n end)()")


def alliance_help_red_point() -> str:
    """Lua *expression* -> the red-point count `push.al.help.new` increments."""
    return "(DataCenter.AllianceHelpDataManager:GetHelpNum() or 0)"


def alliance_help_waiting() -> str:
    """Lua *expression* -> how many alliancemates are waiting, by either reading."""
    return "math.max(%s, %s)" % (alliance_help_pending(), alliance_help_red_point())


def alliance_help_all() -> str:
    """Answer every pending alliance help request in one message (`al.help.all`)."""
    return "if %s > 0 then %s end" % (alliance_help_waiting(), alliance_help_send())


def alliance_help_send() -> str:
    """The bare `al.help.all` send, with **no** client-side gate in front of it.

    `alliance_help_all()` above is this plus the gate, which is what a `TAP` wants: it
    decides and sends in one game-VM call. A caller that has ALREADY decided must not go
    through it — the gate would re-run on the Python side's back and turn the press into
    a silent no-op (that is exactly how the auto-helper came to log "helped 6" with
    nothing on the wire). `tools/lib/alliance_help.py` reads both signals itself, prints
    which one saw the request, and sends this.
    """
    return ("local Z = CS.UnityEngine.Vector3.zero "
            "SFSNetwork.SendMessage(MsgDefines.AlHelpAll, "
            "math.floor(UITimeManager:GetInstance():GetServerTime()), Z, Z, nil, true)")


# --------------------------------------------------------------------------
# City visitor — the queue, and which field says what kind a visitor is
# --------------------------------------------------------------------------
# Visitors queue up outside the base in `DataCenter.CityVisitorManager`; a new
# arrival pushes `push.user.visitor.change`. Each queue entry is a wrapper
# `{data = <visitor>, model = <view>}` returned by `GetQueueAllVisitorData(<queue>)`,
# so every field below lives one level in, on `.data` / `.model`.
#
# There is more than ONE queue, and a kind does not get to pick which: the manager
# keeps two, `GetQueueAllVisitorData(1)` and `(2)` (0 and 3+ raise). Live, gift
# visitors sat in queue 1 while the waiting survivor sat in queue 2 — so anything
# that reads a single queue silently cannot see half the visitors, which is what
# `recruit_survivors` was doing. The client itself takes the queue as a parameter
# next to the kind (`GetReceiveAllGiftUidList(<eventType>, <queue>, <max>)`). Both
# queues are therefore scanned, each in its own pcall so a queue the manager does
# not keep is skipped rather than fatal.
#
# The kind is `data.eventType`, and *that* is what indexes the global `VisitorType`
# enum — MERCHANT=1, GIFT=2, RECRUITMENT=3, BATTLE=4, WORKER_LOTTERY=5, …
# The client agrees: `AddVisitor` compares `eventType` against
# `VisitorType.AllianceCongratulation`, and `GetReceiveAllGiftUidList` filters the
# queue on `data.eventType == <the VisitorType asked for>`.
#
# `data.visitorId` is NOT the kind — it is a plain per-arrival counter. A live
# queue read (task #1122) showed four visitors numbered 3, 4, 5, 6 that were all
# `eventType == 2` (GIFT), which is how the earlier `visitorId == VisitorType.X`
# test came to be wrong in both directions: the gift press matched nothing at all
# (no visitor is ever numbered 2 while queued), and the recruit press fired at
# whoever happened to be the *third* visitor of the session regardless of kind.
#
# A visitor is only pressable once it has walked up: `model.isArrival` is true and
# `model.isFinish` false. A queue entry can exist before that (the fourth visitor
# above had a bare model — not spawned yet) and the client leaves those alone.
_VISITOR_QUEUES = (1, 2)


def _visitor_scan(body: str) -> str:
    """Lua statements: run `body` for every entry of every visitor queue.

    `body` is spliced in with the loop variables `d` (the entry's `.data`) and `m`
    (its `.model`) in scope. Each queue is fetched in its own pcall: the manager
    answers for 1 and 2 and raises for the rest, and a client that keeps a different
    number of them should cost this a queue, not the whole reading.
    """
    return ("local __M = DataCenter.CityVisitorManager "
            "for __q = %d, %d do "
            "local __ok, __lst = pcall(__M.GetQueueAllVisitorData, __M, __q) "
            "if __ok and __lst then "
            "for _, e in ipairs(__lst) do local d, m = e and e.data, e and e.model "
            "%s end end end" % (_VISITOR_QUEUES[0], _VISITOR_QUEUES[1], body))


def _visitor_kind_ready(kind: str, fallback: int) -> str:
    """Lua condition snippet: `d` is a waiting visitor of `VisitorType.<kind>`.

    Expects the loop variables `d` (the entry's `.data`) and `m` (its `.model`) to
    be in scope; `fallback` is the enum value to use if the `VisitorType` global
    is missing.
    """
    return ("d and m and d.eventType == ((VisitorType and VisitorType.%s) or %d) "
            "and m.isArrival and not m.isFinish" % (kind, fallback))


def _visitor_count(kind: str, fallback: int) -> str:
    """Lua *expression* -> how many waiting visitors of that kind are queued anywhere."""
    return ("(function() local n = 0 %s return n end)()"
            % _visitor_scan("if %s then n = n + 1 end" % _visitor_kind_ready(kind, fallback)))


def _visitor_operate_first(kind: str, fallback: int) -> str:
    """Send `visitor.operate {uid, operate = 1}` for the front waiting visitor of a kind.

    Gated on the matching count so a queue with nobody of that kind waiting never
    spends a server round trip. The send returns out of both loops, so exactly one
    visitor is pressed however many queues had a candidate.
    """
    return ("(function() if %s <= 0 then return end %s end)()"
            % (_visitor_count(kind, fallback),
               _visitor_scan("if %s then "
                             "SFSNetwork.SendMessage(MsgDefines.VisitorOperateMessage, d.uid, 1) "
                             "return end" % _visitor_kind_ready(kind, fallback))))


# --------------------------------------------------------------------------
# City visitor — recruit a waiting survivor ("Собрать выжившего")
# --------------------------------------------------------------------------
# A waiting survivor is a queue entry of kind `VisitorType.RECRUITMENT` (3). The
# recruit press (the «Нанять»/agree button of UIWorkerDetailRecruit) sends ONE
# message, seen whole in trace 20260729_145441 «Собрать выжившего»:
#
#     SFSNetwork.SendMessage(MsgDefines.VisitorOperateMessage, uid, 1)
#       -- MsgDefines.VisitorOperateMessage == 'visitor.operate'
#       -- SFSObject: PutLong('uid', <visitor uid>) + PutInt('operate', 1)
#
# `operate = 1` is accept/recruit (the button was `agreeBtn`); no other operate
# value was observed. The message body is exactly {uid, operate}, so the send
# needs no window open — the uid is read straight off the queued visitor's data.
def visitor_recruit_pending() -> str:
    """Lua *expression* -> how many queued visitors are recruitable survivors."""
    return _visitor_count("RECRUITMENT", 3)


def visitor_recruit_survivor() -> str:
    """Recruit the first waiting survivor visitor (`visitor.operate {uid, operate=1}`)."""
    return _visitor_operate_first("RECRUITMENT", 3)


# --------------------------------------------------------------------------
# City visitor — collect a gift-bearing survivor ("Собрать подарки выжившего")
# --------------------------------------------------------------------------
# A *gift* visitor is the same CityVisitorManager queue mechanic as the recruit
# survivor above — only the kind differs: `data.eventType == VisitorType.GIFT` (2)
# instead of RECRUITMENT (3). Tapping such a visitor and collecting its gift sends
# the identical one-shot message, captured whole in trace 20260729_151712
# «Собрать подарки выжившего»:
#
#     SFSNetwork.SendMessage(MsgDefines.VisitorOperateMessage, uid, 1)
#       -- visitor.operate  {uid = <visitor uid>, operate = 1}
#
# After the send the client flew a coin-box reward (`UIUtil.DoFly(7, 1,
# icon_coinbox, ...)`) and destroyed the UICityVisitor window — i.e. operate=1
# means "collect the gift" here just as it means "accept" for a recruit. Because
# the body is only {uid, operate}, no window need be open: the uid is read
# straight off the queued visitor's data, exactly like the recruit path.
#
# The count is cross-checked against the client's own batch-claim list,
# `GetReceiveAllGiftUidList(VisitorType.GIFT, 1, n)`: on a live queue of four gift
# visitors, one of them not yet arrived, both said 3.
def visitor_gift_pending() -> str:
    """Lua *expression* -> how many queued visitors are gift-bearing survivors."""
    return _visitor_count("GIFT", 2)


def visitor_gift_collect() -> str:
    """Collect the first gift-bearing survivor (`visitor.operate {uid, operate=1}`)."""
    return _visitor_operate_first("GIFT", 2)


# --------------------------------------------------------------------------
# Occupation ("profession") skills — the Mastery tree
# --------------------------------------------------------------------------
# In game these are «навыки профессии»: the active skills of the profession the
# player picked (`home_id` 101 = Инженер / Engineer, 102 = Военный лидер / Warlord).
# On the wire one press is a single command:
#
#     --> use.desert.talent.skill  {skillId = "10113"}
#     <-- use.desert.talent.skill  {skillId, type = 1018, todayTimes = 1,
#                                   recover = {lastTime, duration, num, max, type,
#                                              cdEndTime},
#                                   exeObj = {reward = [...], lucky, bTypes, ...}}
#
# `recover` is the charge counter: `num` charges banked out of `max`, refilling
# `duration` ms after `lastTime`. That reply is what puts the skill on cooldown —
# nothing client-side does, which is why the re-fire guard below exists.
#
# The owning manager is `DataCenter.MasteryManager`:
#
#   * `UseSkill(skillId, pointId, msgId, serverId)` — what the in-game useBtn calls
#     (LWUIMasterySkillUseInWorldCell:OnBtnClickFunc). It routes on where the skill
#     is cast from and, for a no-target skill, ends in the sender.
#   * `SendUseSkillMsg(skillTemp, param, msgId)` — THE SENDER (its constants carry
#     `SFSNetwork | SendMessage | MsgDefines | MasteryUseSkill`).
#   * `HandleUseSkill(msg)` — the reply applier (rewards, popups,
#     `SetSkillCdAndEffectTime`). Calling it sends nothing; it is not the press.
#
# Verified without spending a charge: with `SendUseSkillMsg` and
# `SFSNetwork.SendMessage` temporarily stubbed out, `MasteryManager:UseSkill(10113)`
# — no pointId, no serverId — arrived at
# `SendUseSkillMsg(skillTemp{id=10113}, param=nil, msgId='use.desert.talent.skill')`,
# byte-for-byte the send the human click produced in trace
# `20260729_010052_навыки_профессии` (`SFSNetwork.SendMessage <- use.desert.talent.skill,
# 10113, nil`). No confirmation dialog on the way. See
# docs/research/occupation-skills.md.

# `MasterySkillState` (a game global). Only `Normal` may be pressed.
MASTERY_STATE_NONE, MASTERY_STATE_NORMAL, MASTERY_STATE_LOCKED = 0, 1, 2
MASTERY_STATE_CD, MASTERY_STATE_COVERED = 3, 4
MASTERY_STATE_NOUSE, MASTERY_STATE_EFFECT = 5, 6
MASTERY_STATE_NAMES: dict[int, str] = {
    MASTERY_STATE_NONE: "none",
    MASTERY_STATE_NORMAL: "ready",
    MASTERY_STATE_LOCKED: "locked",
    MASTERY_STATE_CD: "cooldown",
    MASTERY_STATE_COVERED: "covered",     # superseded by a higher tier of the same node
    MASTERY_STATE_NOUSE: "no-use",
    MASTERY_STATE_EFFECT: "in-effect",
}

# How long a just-fired skill stays excluded from the "ready" list. The client only
# learns about the new cooldown when the server's reply lands (~0.2-8 s observed), so
# without this a second press in that window would fire the SAME skill twice. Anything
# longer than the round trip and shorter than a real cooldown (>= 23 h) works.
MASTERY_REFIRE_GUARD_MS = 120_000


def _occupation_ready_ids() -> str:
    """Lua *expression* -> array of skill ids that can be fired right now, headless.

    Three filters, all of them load-bearing:

    * `active_skills` — passive nodes have no press at all.
    * `CheckUsePosition(MasterySkillUsePosType.SkillView)` — the skill is cast from the
      skill panel and needs NO target. The others (`Building`, `Field`, …) send a march
      or want a map point, and firing them blind would aim at nothing; they are left to
      a future targeted recipe.
    * `GetMasteryGroupSkillState(masteryId) == Normal` — the client's own gate. `CD`,
      `Locked` and `Covered` all read as "not now", and pressing anyway earns a
      server-side rejection with a player-facing toast (the same trap as the
      resource-collect readiness gate).

    Plus the re-fire guard: ids stamped by `apply_next_occupation_skill()` less than
    `MASTERY_REFIRE_GUARD_MS` ago are dropped, so `xall` cannot double-fire one skill
    while its cooldown is still in flight. The stamps live on the manager table
    (`__lw_fired`) rather than in a global — this VM rejects some new globals.
    """
    return (
        "(function() local M=DataCenter.MasteryManager "
        "local d=M:GetData() if not d then return {} end "
        "local now=UITimeManager:GetInstance():GetServerTime() "
        "local fired=M.__lw_fired or {} local out={} "
        "for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do "
        "local sid=M:GetCurSkillIdByMasteryId(mid) "
        "local t=sid and M:GetSkillTemplate(sid) "
        "if t and t.active_skills "
        "and t:CheckUsePosition(MasterySkillUsePosType.SkillView) "
        "and M:GetMasteryGroupSkillState(mid)==MasterySkillState.Normal "
        "and (now-(fired[sid] or 0))>%d then out[#out+1]=sid end end "
        "return out end)()" % MASTERY_REFIRE_GUARD_MS
    )


def occupation_skills_ready_count() -> str:
    """Lua *expression* -> how many no-target profession skills are off cooldown.

    What `TAP use_profession_skill xall` counts down, and what a recipe reads with
    `READ_LUA … INTO n` to decide whether the panel is worth opening at all.
    """
    return "#%s" % _occupation_ready_ids()


def apply_next_occupation_skill() -> str:
    """Fire the first ready no-target profession skill (one press, one skill).

    One press per chunk on purpose: the charge only drops when the server answers, and
    a `while ready > 0 do press() end` inside a single chunk would spin the game's main
    thread and freeze the client. `xall` re-reads the count between presses instead.
    """
    return (
        "local M=DataCenter.MasteryManager "
        "local ids=%s local sid=ids[1] "
        "if sid then M.__lw_fired=M.__lw_fired or {} "
        "M.__lw_fired[sid]=UITimeManager:GetInstance():GetServerTime() "
        "pcall(function() M:UseSkill(sid) end) "
        'CS.UnityEngine.Debug.LogError("ACT occupation_skill_used "..tostring(sid)) end'
        % _occupation_ready_ids()
    )


def skill_cooldown_remaining(skill_id: int) -> str:
    """Lua *expression* -> milliseconds until `skill_id` can be fired again.

    `0` = a charge is banked right now. `-1` = the question does not apply — the id is
    not an active skill of this profession, or its node is `Locked` / `Covered` (a tier
    superseded by a higher one, which carries no charge data at all and would otherwise
    read as a confident, wrong "ready now").

    This is `GetSkillAvailableTime` — the epoch-ms the NEXT charge lands, which is the
    server's `recover.cdEndTime` — minus the server clock, never the local one: the two
    drift, and every timestamp in this subsystem is server time.

    Milliseconds because that is what the game stores; a recipe that wants minutes
    divides. Deliberately independent of the re-fire guard in
    `apply_next_occupation_skill()` — this answers "what does the GAME think", which is
    what a scheduler wants when deciding how long to sleep before coming back.
    """
    return (
        "(function() local M=DataCenter.MasteryManager "
        "local d=M:GetData() if not d then return -1 end "
        "for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do "
        "local sid=M:GetCurSkillIdByMasteryId(mid) "
        "if sid==%d then "
        "local t=M:GetSkillTemplate(sid) "
        "if not (t and t.active_skills) then return -1 end "
        "local st=M:GetMasteryGroupSkillState(mid) "
        "if st==MasterySkillState.Locked or st==MasterySkillState.Covered "
        "or st==MasterySkillState.None then return -1 end "
        "local avail=d:GetSkillAvailableTime(sid) or 0 "
        "if avail==0 then return 0 end "
        "local left=avail-UITimeManager:GetInstance():GetServerTime() "
        "if left<0 then left=0 end return left end end "
        "return -1 end)()" % int(skill_id)
    )


def skill_can_use(skill_id: int) -> str:
    """Lua *expression* -> 1 when `skill_id` is a no-target skill that may be fired now.

    Numeric so a recipe can gate on it, and so `TAP <one skill> xall` stops at one press.
    """
    return ("(function() for _,sid in ipairs(%s) do "
            "if sid==%d then return 1 end end return 0 end)()"
            % (_occupation_ready_ids(), int(skill_id)))


def apply_occupation_skill(skill_id: int) -> str:
    """Fire one specific profession skill by id, gated by `skill_can_use`.

    For pinning a routine to a named skill («Быстрое Производство» and nothing else).
    Ungated it would still leave the client and come back as a rejection toast.
    """
    return ("if %s==1 then local M=DataCenter.MasteryManager "
            "M.__lw_fired=M.__lw_fired or {} "
            "M.__lw_fired[%d]=UITimeManager:GetInstance():GetServerTime() "
            "pcall(function() M:UseSkill(%d) end) end"
            % (skill_can_use(skill_id), int(skill_id), int(skill_id)))


def occupation_skills_dump() -> str:
    """Reader chunk: one `ACT S …` line per active skill of the current profession.

    Fields: `sid` skill id, `mid` mastery node, `st` MasterySkillState, `pos` where it is
    cast from (`SkillView` = no target), `num`/`max` banked charges, `avail` epoch-ms the
    next charge lands (0 = now), `cd` the full cooldown in minutes, and `name`, hex-encoded
    because the display name is localised and the log channel is ASCII-only.
    """
    return (
        "local M=DataCenter.MasteryManager local d=M:GetData() "
        'local function hex(s) return (tostring(s):gsub(".", '
        'function(c) return string.format("%02x", string.byte(c)) end)) end '
        "local names={} for k,v in pairs(MasterySkillUsePosType) do names[v]=k end "
        'CS.UnityEngine.Debug.LogError("ACT now "..tostring(UITimeManager:GetInstance():GetServerTime())'
        '.." home "..tostring(d and d.home_id).." lv "..tostring(d and d.level)) '
        "if not d then return end "
        "for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do "
        "local sid=M:GetCurSkillIdByMasteryId(mid) "
        "local t=sid and M:GetSkillTemplate(sid) "
        "if t and t.active_skills then "
        "local pos='' for v=0,9 do if t:CheckUsePosition(v) then pos=(names[v] or tostring(v)) end end "
        "local c=d:GetSkillChargeData(sid) "
        'CS.UnityEngine.Debug.LogError(string.format('
        '"ACT S sid=%s mid=%s st=%s pos=%s num=%s max=%s avail=%s cd=%s name=%s", '
        "tostring(sid), tostring(mid), tostring(M:GetMasteryGroupSkillState(mid)), pos, "
        "tostring(c and c.num or 0), tostring(c and c.max or 0), "
        "tostring(d:GetSkillAvailableTime(sid) or 0), tostring(t.cd_time), "
        "hex(UIUtil:GetString(t.name)))) end end"
    )


# --------------------------------------------------------------------------
# Secret-task robbery — «кража секретки»
# --------------------------------------------------------------------------
# A secret task (hero dispatch) sitting on another player's tile can be robbed
# three times before its loot slots are full. On the wire one robbery is a
# single command with no coordinate in it at all:
#
#     --> hero.dispatch.steal   {uuid, targetServer}
#     <-- push.hero.dispatch.mission.steal {pointId, serverId, worldId, playerInfo}
#     <-- hero.dispatch.steal   {reward[], ownerInfo, recordUuid, todayStealNum, ...}
#
# The Lua side, pinned live against the VM for task #1099 (traces
# `20260729_013329_кража_серкетки` / `20260729_013404_Кража_секретки`; both
# traffic checkpoints came back with keepalives only, so the wire half is the
# 2026-07-19 capture written up in docs/research/protocol.md §7):
#
#   * `MsgDefines.DispatchSteal` = `hero.dispatch.steal`.
#   * `Net.Msgs.DispatchTask.DispatchStealMessage:OnCreate(uuid, targetServer)`
#     puts exactly two fields in the SFSObject — `PutLong uuid`,
#     `PutInt targetServer`. So the send needs NO window open and no map tap.
#   * The in-game press is `UIWorldPointBtn:onDispatchTaskClick(btnType)` with
#     `btnType == WorldPointBtnType.DispatchTaskSteal` (54 — the same 54 the
#     trace passes to `LoadPath.GetBuildBtnSpritePath`, i.e. the «украсть»
#     icon). Its whole network line is that one `SFSNetwork.SendMessage`.
#   * `DispatchStealMessage:HandleMessage` is the reply applier (rewards,
#     `ShowReward`, `UpdateTodayNum`, `UpdateSteal`) — calling it sends nothing.
#     Same trap as `AllianceHelpDataManager:OnHelpAll`; the press is the send.
#
# THE TARGET IS A `uuid`, NOT A COORDINATE. A caller holding only x/y resolves
# it first with `secret_task_request_detail()` + `secret_task_uuid_at()` (the
# `world.get.detail.new` round trip the client itself fires when a marker is
# tapped) — verified live: asking for a known alliance task's pointId returned
# the same uuid the dispatch record carries.
#
# See docs/research/secret-task-steal.md.

# `WorldPointType.HERO_DISPATCH` — the pointType `world.get.detail.new` wants
# for a secret-task marker (and the `f2 = 17` tiles the map scanner decodes).
SECRET_TASK_POINT_TYPE = 17

# `WorldPointBtnType.DispatchTaskSteal` — the popup button this recipe replaces.
# Not used by the send (the send is the message, not the button); kept because it
# is what identifies the traced click.
SECRET_TASK_STEAL_BTN = 54


def secret_task_steals_left() -> str:
    """Lua *expression* -> how many robberies the account may still make today.

    `GetDispatchSetting("steal_count")` is the daily cap (5 on the live account) and
    `GetTodayStealNum()` what has been spent; the server resets both. This is the ONE
    gate that is fully readable client-side, which is why every press below carries it
    and why it is the `count_lua` of the `steal_secret_task` button.

    The other conditions `onDispatchTaskClick` checks — the tile's own looter list
    (`stealList:Contains(selfUid)`, max three) and its `protect_times` window — hang off
    the world object of a tile that is currently rendered, so they are NOT answerable
    for an arbitrary uuid. Those stay the server's job: a robbery it refuses comes back
    as `hero.dispatch.steal` with an `errorCode` and the client pops the matching tip.
    """
    return ("(function() local M=DataCenter.ActDispatchTaskDataManager "
            "local cap=tonumber(M:GetDispatchSetting('steal_count')) or 0 "
            "local used=tonumber(M:GetTodayStealNum()) or 0 "
            "local left=cap-used if left<0 then left=0 end return left end)()")


def secret_task_request_detail(x: int, y: int, server: int) -> str:
    """Ask the server for the marker detail of tile (x, y) — the uuid lookup.

    This is the first of the two messages a manual robbery sends: tapping a secret-task
    marker fires `world.get.detail.new {point, serverId, 0, pointType = 17, uid = ""}`,
    and the reply is parsed into `WorldPointDetailManager`, keyed by pointId. Read the
    uuid out of it with `secret_task_uuid_at()` AFTER a settle — never in the same
    chunk, the reply has not landed yet.
    """
    return ('pcall(function() SFSNetwork.SendMessage("world.get.detail.new", %s, %d, 0, %d, "") end) '
            'CS.UnityEngine.Debug.LogError("ACT detail_requested %d,%d srv=%d")'
            % (_pid(x, y), int(server), SECRET_TASK_POINT_TYPE, x, y, int(server)))


def secret_task_uuid_at(x: int, y: int) -> str:
    """Lua *expression* -> the task uuid cached for tile (x, y), or 0.

    `0` means "not asked for yet, or the reply has not arrived" — not "no task there".
    The cache is per pointId and survives across chunks, so the usual shape is
    request -> wait -> read.
    """
    return ("(function() local d=DataCenter.WorldPointDetailManager:GetDetailByPointId(%s) "
            "return (d and d.uuid) or 0 end)()" % _pid(x, y))


def secret_task_owner_at(x: int, y: int) -> str:
    """Lua *expression* -> the uid of the player whose task sits on tile (x, y), or 0.

    From the same cached detail. Lets a caller refuse to rob its own or an
    alliancemate's task before spending one of the day's five attempts.
    """
    return ("(function() local d=DataCenter.WorldPointDetailManager:GetDetailByPointId(%s) "
            "return (d and d.uid) or 0 end)()" % _pid(x, y))


def secret_task_steal(uuid: int, server: int) -> str:
    """Rob the secret task `uuid` on `server` — one `hero.dispatch.steal`.

    Headless: no marker tap, no `UIWorldPoint` window, no camera move. Gated on the
    daily budget so a spent account does not put a doomed message on the wire (the
    server would answer with an errorCode and the client would raise a toast — the same
    trap as the resource-collect readiness gate).
    """
    return ('if %s > 0 then '
            'pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchSteal, %d, %d) end) '
            'CS.UnityEngine.Debug.LogError("ACT steal_sent uuid=%d srv=%d") end'
            % (secret_task_steals_left(), int(uuid), int(server), int(uuid), int(server)))


def secret_task_leave_message(record_uuid: int, msg_id: int, server: int) -> str:
    """Leave the robbed player one of the canned emoji («стикер вдогонку»).

    The optional second half of the flow: the reward window that opens after a
    successful robbery has an emoji strip, and picking one fires
    `MsgDefines.DispatchLeaveMessage` = `hero.dispatch.leave.message`
    ({`recordUuid`, `msgId`, `targetServer`}) — read off
    `UIDispatchTaskRewardView:OnStealMessageBtnClick`.

    `record_uuid` is the `recordUuid` from the robbery's own reply (NOT the task uuid),
    and `msg_id` one of the ids in `GetStealEmojiList()` (11 of them live). Pure
    flavour — it pays nothing and is not part of the loot.
    """
    return ('pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchLeaveMessage, %d, %d, %d) end) '
            'CS.UnityEngine.Debug.LogError("ACT steal_message_sent record=%d msg=%d")'
            % (int(record_uuid), int(msg_id), int(server), int(record_uuid), int(msg_id)))


# --- the target queue ------------------------------------------------------
# `TAP` takes no arguments, so a button cannot be told *which* task to rob. The
# targets are therefore parked in the game VM — on the dispatch manager's own
# table (`__lw_steal_queue`), because this VM rejects some new globals — and the
# button robs the first one and drops it. Filling the queue is the job of
# `tools/steal_secret_task.py`: it is the side that can scan the map, resolve a
# coordinate to a uuid across a round trip, and drop what is already looted out.
# The same split as the profession skills: one press = one action, `xall` walks
# the set, and the count is re-read between presses.

def secret_task_queue_set(targets) -> str:
    """Replace the steal queue with `targets` — an iterable of (uuid, server) pairs."""
    items = ",".join("{uuid=%d,server=%d}" % (int(u), int(s)) for u, s in targets)
    return ("local M=DataCenter.ActDispatchTaskDataManager M.__lw_steal_queue={%s} "
            % items + _STEAL_MARK
            + 'CS.UnityEngine.Debug.LogError("ACT steal_queue_set "'
              '..tostring(#M.__lw_steal_queue))')


# WHAT THE SERVER SAYS WHEN THE TILE IS GONE, and why the spam has to hear it (#1272).
#
# `DispatchStealMessage:HandleMessage` is `errorCode -> UIUtil.ShowTipsId(errCode)`, and
# the errorCode IS the message key — the same shape the assist's refusal came back as.
# Read out of the live client's own `dispatch_des*` family:
#
#   dispatch_des040  «Это задание выполнено, украсть его невозможно.»
#   dispatch_des041  «Невозможно выполнить: срок задачи истек.»
#   dispatch_des042  «Задание уже взято»
#   dispatch_des043  «Это задание больше не доступно»
#
# All four mean the same thing to us: THERE IS NOTHING THERE ANY MORE. And the family
# holds no «ещё не готово» at all, which is the other half of the finding — an early
# press is answered by silence rather than by a refusal, so «any tip at all» would have
# been a workable rule too. These four are named anyway: a tip we have not met should
# leave the loop pressing, not stop it.
#
# Without this the loop had exactly two stop conditions — the counter moving, and the
# button's cap. Live, that read as `TAP Rob a secret task xall -> 60 press(es)` on one
# tile: sixty questions to a server that had already answered the first one.
STEAL_GONE_TIPS = ("dispatch_des040", "dispatch_des041",
                   "dispatch_des042", "dispatch_des043")

#: Lua that records the tip a refusal raises, so a loop can read the server's answer.
#: Installed once, idempotent, and a pass-through — it takes nothing away from the game.
#:
#: It stamps the tip into a field PER SPAM (#1294): the robbery clears `__lw_steal_tip`
#: when it arms a tile and the star sprint clears `__lw_assist_tip` when it arms a task,
#: so neither can read the other's refusal and stop on it. One hook, two mailboxes —
#: `UIUtil.ShowTipsId` is the game's single tip door and wrapping it twice would leave a
#: shim behind on every re-install.
#:
#: The guard carries a VERSION. A client that has been up since before this change has
#: the one-mailbox hook installed and would never fill `__lw_assist_tip`, so the sprint
#: would read every refusal as silence and press out its whole cap. Bumping the key
#: re-installs over it; the old shim stays in the chain and keeps working.
_TIP_HOOK = (
    "if not M.__lw_tip_hooked_v2 then M.__lw_tip_hooked_v2 = true "
    "local orig = UIUtil.ShowTipsId "
    "UIUtil.ShowTipsId = function(id, ...) "
    "pcall(function() local D=DataCenter.ActDispatchTaskDataManager "
    "D.__lw_steal_tip = tostring(id) D.__lw_assist_tip = tostring(id) end) "
    "return orig(id, ...) end end ")

#: The old name, kept because it reads better where the robbery arms its mark.
_STEAL_TIP_HOOK = _TIP_HOOK

#: …and the expression that reads it back: 1 when the server has said the tile is gone.
_STEAL_GONE = ("(function() local M=DataCenter.ActDispatchTaskDataManager "
               "local t=tostring(M.__lw_steal_tip or '') "
               + " ".join("if t=='%s' then return 1 end" % k for k in STEAL_GONE_TIPS)
               + " return 0 end)()")


def secret_task_gone() -> str:
    """Lua *expression* -> 1 when the server has answered «there is nothing there».

    The third outcome, beside «taken» and «not yet». It is terminal: pressing again is
    asking a question already answered, and the row it belongs to is not a target any
    more — which is why the panel takes it off the list rather than leaving it to say
    «готово к сбору» about a tile somebody else has emptied.
    """
    return _STEAL_GONE


# THE ONLY HONEST «IT WORKED» THERE IS (#1272). A robbery is confirmed by the SERVER
# and by nothing else: `DispatchStealMessage:HandleMessage` takes the error branch on a
# refusal and, on success, hands `UpdateTodayNum` the server's own `todayStealNum` out
# of the reply. Nothing is incremented locally, so the counter moving is the reply
# landing — and a send that got a tip back leaves it exactly where it was.
#
# That is what lets the press be REPEATED. `__lw_steal_mark` is the counter as it stood
# when the head of the queue was armed; while it has not moved, the head has not been
# taken and pressing again is worth doing. It is stamped when the queue is set and
# re-stamped when the head is dropped, so it always belongs to the target being pressed.
_STEAL_MARK = ("M.__lw_steal_mark=tonumber(M:GetTodayStealNum()) or 0 "
               "M.__lw_steal_tip=nil " + _STEAL_TIP_HOOK)


def secret_task_taken() -> str:
    """Lua *expression* -> 1 when the server has confirmed a robbery of the armed head.

    The counter against the mark, and that is the whole test. A `steal_sent` line proves
    a frame left the client; only this proves the server took it.
    """
    return ("(function() local M=DataCenter.ActDispatchTaskDataManager "
            "local now=tonumber(M:GetTodayStealNum()) or 0 "
            "local mark=tonumber(M.__lw_steal_mark) "
            "if mark == nil then return 0 end "
            "if now ~= mark then return 1 end return 0 end)()")


def secret_task_queue_pop() -> str:
    """Drop the head of the queue and re-arm the mark on whatever is now in front.

    Called between targets rather than before a send (which is what
    `steal_next_secret_task` used to do): the head has to survive its own press so that
    the press can be REPEATED until the server answers. A head that was never taken is
    dropped here too — after the spam has spent its cap on it, that tile is gone, taken
    by somebody else, or out of reach, and every one of those means «the next one».

    IT SAYS WHAT HAPPENED, PER TARGET (#1272). `ACT steal_done uuid=<u> how=<…>` — one of
    `taken` (the counter moved: ours), `gone` (the server said there is nothing there:
    the row is not a target any anymore and the panel takes it off the list) or
    `unanswered` (the spam ran out its cap without either: the row stays, because nothing
    said it should not). The verdict is read BEFORE the mark is re-armed, or it would be
    the next target's.
    """
    return ("local M=DataCenter.ActDispatchTaskDataManager "
            "local q=M.__lw_steal_queue or {} local t=table.remove(q,1) "
            "local how='unanswered' "
            "if %s == 1 then how='gone' elseif %s == 1 then how='taken' end "
            "local tip=tostring(M.__lw_steal_tip or '') "
            'CS.UnityEngine.Debug.LogError("ACT steal_done uuid="..tostring(t and t.uuid or 0)'
            '.." how="..how.." tip="..tip) '
            % (secret_task_gone(), secret_task_taken())
            + _STEAL_MARK +
            'CS.UnityEngine.Debug.LogError("ACT steal_queue_pop left="..tostring(#q))')


def secret_task_queue_clear() -> str:
    """Empty the steal queue (a recipe should not inherit yesterday's targets)."""
    return ("local M=DataCenter.ActDispatchTaskDataManager M.__lw_steal_queue={} "
            'CS.UnityEngine.Debug.LogError("ACT steal_queue_cleared")')


def secret_task_queue_len() -> str:
    """Lua *expression* -> how many targets are still queued."""
    return ("(function() local M=DataCenter.ActDispatchTaskDataManager "
            "return #(M.__lw_steal_queue or {}) end)()")


def secret_task_steals_pending() -> str:
    """Lua *expression* -> is the head of the queue still worth pressing? (1 or 0)

    The button's `count_lua`, and it answers a different question since #1272. It used
    to be «how many targets are left», which made `xall` press each of them once; it is
    now «press the SAME one again», and `xall` becomes the spam loop the race needs:

      * there is a head to press,
      * the day's budget is not spent,
      * the server has not confirmed this one yet (`secret_task_taken`),
      * and it has not said the tile is GONE either (`secret_task_gone`) — «задание уже
        взято», «больше не доступно», «срок истёк». That answer is terminal: pressing
        again is asking a question the server has already answered, and it is what turned
        one live press into `xall -> 60 press(es)` against a tile that no longer existed.

    **A tile is pressed BEFORE it matures on purpose.** There is no penalty for it — the
    server answers «ещё не готово», the counter does not move and nothing is spent
    (`DispatchStealMessage:HandleMessage`) — and a raidable star is taken in the first
    instant it exists, so the only way to be first is to be already pressing. The clock
    is deliberately NOT part of this gate: the recipe is played inside the window, and
    what stops the loop is the server saying yes, not our own idea of when it should.
    """
    return ("(function() local q=%s local b=%s local t=%s local g=%s "
            "if q>0 and b>0 and t==0 and g==0 then return 1 end return 0 end)()"
            % (secret_task_queue_len(), secret_task_steals_left(),
               secret_task_taken(), secret_task_gone()))


def steal_next_secret_task() -> str:
    """Rob the head of the queue — and LEAVE IT THERE, so it can be pressed again.

    One press per chunk, as before: `todayStealNum` only moves when the server's reply
    lands, so a `while` inside one chunk would spin the game's main thread and press
    against a stale budget.

    THE HEAD IS NO LONGER DROPPED BEFORE THE SEND (#1272). It used to be, so that a
    refusal cost a queue entry rather than wedging `xall` on a doomed uuid for ever —
    and that made the press a one-shot, which loses every race that is decided in
    fractions of a second. Now the head survives its own press, `count_lua` stops the
    loop the moment the SERVER confirms (`secret_task_taken`), and `max_taps` bounds the
    spam on a tile that will never answer. `secret_task_queue_pop` is what moves on.
    """
    return ("local M=DataCenter.ActDispatchTaskDataManager "
            "local q=M.__lw_steal_queue or {} local t=q[1] "
            "if t and %s > 0 then "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchSteal, t.uuid, t.server) end) "
            'CS.UnityEngine.Debug.LogError("ACT steal_sent uuid="..tostring(t.uuid)'
            '.." srv="..tostring(t.server)) end' % secret_task_steals_left())


# --------------------------------------------------------------------------
# Re-reading the STATE of tiles already on the list — «Обновить состояние» (#1272)
# --------------------------------------------------------------------------
# A different question from every read above, and the one nothing could answer. The
# alliance table (`secret_task_all_alliance`) knows only MY alliance's tasks — live: 189
# of them, none starred, all at home — so it cannot say a word about the strangers' tiles
# the map capture found, which is the whole of the ★ list. The capture only re-sees a
# tile when the map is driven over it again. Between those, a row went on saying «готово
# к сбору» about a tile somebody had emptied minutes ago.
#
# The per-tile authority is the one a marker tap uses: `world.get.detail.new`, keyed by
# pointId, answered into `WorldPointDetailManager` and readable by pointId afterwards.
# Measured live: a real tile answers with a 45-field record carrying `uuid`, `uid`,
# `serverId` and `expireTime`; **a point with no task on it answers with no detail at
# all** — `GetDetailByPointId` stays nil.
#
# WHICH MAKES «NIL» AMBIGUOUS ON ITS OWN, and that is the trap this task has already
# been caught by once (#1272, `_answerable`): a reply that never arrived looks exactly
# like «there is nothing there». So the probe sends a CONTROL point along with the batch
# — a tile the client itself says exists — and the reader reports whether that one came
# back. Without the control answering, a nil says nothing and no row is dropped.
#
# What the detail does NOT carry is the loot count: `stealInfoList` is not in it, so
# «сколько раз уже ограбили» still comes from the alliance table for the tiles it covers
# and from the capture for the rest.

def secret_task_detail_probe(tiles, control=None) -> str:
    """Ask the server about each `(x, y, server)` tile — plus a control point.

    The tile index is computed in the VM (`SceneUtils.TilePosToIndex`), so nothing out
    here has to know how a coordinate is packed into a pointId. The list is parked in
    order; :func:`secret_task_detail_read` reports back BY THAT ORDER, which is what lets
    a caller line the answers up with its own rows without re-deriving anything.

    Fire and forget: the replies land on their own and are read after a settle, never in
    this chunk.
    """
    items = ",".join(
        "{x=%d,y=%d,s=%d}" % (int(x), int(y), int(srv)) for x, y, srv in tiles)
    # The control is picked in the VM when the caller does not name one: the client's own
    # alliance table is a list of tiles it is sure exist, and one of them answering is
    # what turns «no detail» from «I heard nothing» into «there is nothing there».
    ctrl = (("{p=%d,s=%d}" % (int(control[0]), int(control[1]))) if control else
            "(function() for _, v in pairs(DataCenter.ActDispatchTaskDataManager"
            ".allianceTask or {}) do return {p=v.pointId, s=v.targetServer} end "
            "return nil end)()")
    return ("local M=DataCenter.ActDispatchTaskDataManager "
            "M.__lw_detail_ask={} M.__lw_detail_ctrl=%s "
            "for _, it in ipairs({%s}) do "
            "local pid = SceneUtils.TilePosToIndex(CS.UnityEngine.Vector2Int(it.x, it.y)) "
            "M.__lw_detail_ask[#M.__lw_detail_ask+1] = {p=pid, s=it.s} "
            "pcall(function() SFSNetwork.SendMessage('world.get.detail.new', pid, it.s, 0, %d, '') end) "
            "end "
            "if M.__lw_detail_ctrl then pcall(function() "
            "SFSNetwork.SendMessage('world.get.detail.new', M.__lw_detail_ctrl.p, "
            "M.__lw_detail_ctrl.s, 0, %d, '') end) end "
            'CS.UnityEngine.Debug.LogError("ACT detail_asked "..tostring(#M.__lw_detail_ask))'
            % (ctrl, items, SECRET_TASK_POINT_TYPE, SECRET_TASK_POINT_TYPE))


def secret_task_detail_read() -> str:
    """Emit what came back: one `ACT DT …` per asked tile, in order, and the control.

    `DT i=<n> uuid=<u> expire=<ms>` — `uuid=0` means no detail at all, which is what a
    point with no task on it answers (measured live). `DT_CONTROL ok=<0|1>` is whether
    the tile we KNOW exists answered, and it is the difference between «there is nothing
    there» and «nothing came back»: without it a silent link reads as an empty map, which
    is how a list gets deleted for a fault of its own connection (#1272).
    """
    return ("local M=DataCenter.ActDispatchTaskDataManager "
            "local D=DataCenter.WorldPointDetailManager "
            "for i, it in ipairs(M.__lw_detail_ask or {}) do "
            "local d = D:GetDetailByPointId(it.p) "
            'CS.UnityEngine.Debug.LogError("ACT DT i="..tostring(i)'
            '.." uuid="..tostring((d and d.uuid) or 0)'
            '.." expire="..tostring((d and d.expireTime) or 0)) end '
            "local ok = 0 "
            "if M.__lw_detail_ctrl then "
            "local c = D:GetDetailByPointId(M.__lw_detail_ctrl.p) "
            "if c and (tonumber(c.uuid) or 0) > 0 then ok = 1 end end "
            'CS.UnityEngine.Debug.LogError("ACT DT_CONTROL ok="..tostring(ok))')


# The clock the client draws its OWN countdowns with, in milliseconds, as a Lua
# statement that leaves it in a local called `nowms`.
#
# `UITimeManager.Instance:GetServerTime()` is the one to ask, and it is not a
# guess: `ActDispatchTaskDataManager.RefreshCompleteTimer`, string-dumped out of
# the live VM, computes its countdown as `completionTime` minus a `curTime` taken
# from exactly this manager (task #1227). It is the server's clock kept as an
# offset from the device's — `self.serverDeltaTime` — so it does NOT move with the
# PC's own time.
#
# `ChatInterface.getServerTime()` is the fallback, the same clock in whole
# seconds. Measured together they agree to the second (…337743 ms vs …337 s), so
# the fallback costs precision and nothing else.
_SERVER_NOW_MS = (
    'local nowms = 0 '
    'pcall(function() nowms = UITimeManager.Instance:GetServerTime() end) '
    'nowms = math.floor(tonumber(nowms) or 0) '
    'if nowms <= 0 then nowms = (tonumber(ChatInterface.getServerTime()) or 0) * 1000 end ')


def game_server_time() -> str:
    """Emit the game's own clock, in milliseconds — `ACT NOWMS=<ms>`.

    This is the clock every timestamp the game hands out is stamped on, and it is
    the one the client's own countdowns are drawn against — so anything asking
    «how long until this tile is raidable» or «has the dispatch finished yet» has
    to be judged by it rather than by the PC's clock. The two are not the same:
    the machine this was written on ran eleven seconds SLOW against real UTC, and
    the operator was reading 25-30 s of that on the tab (task #1227).

    `tools/lib/game_clock.py` keeps the difference; this is the read.
    """
    return (_SERVER_NOW_MS
            + 'CS.UnityEngine.Debug.LogError("ACT NOWMS="..tostring(nowms))')


# --------------------------------------------------------------------------
# Helping an alliancemate's secret task — `hero.dispatch.assist`
# --------------------------------------------------------------------------
# A THIRD thing, and not the alliance «Помочь всем» (#1272). `al.help.all`
# answers building/research requests and is unlimited; this answers the alliance's
# own FINISHED hero-dispatch tasks, costs one of five a day, and is what the daily
# plan means by «помочь выполнить 5 секретных заданий ранга UR или Звезда».
#
#     --> hero.dispatch.assist   {uuid: long, targetServer: int}
#     <-- hero.dispatch.assist   {errorCode | reward[], …}
#
# Read out of the live client (docs/research/secret-task-assist.md):
#
#   * the press is `DispatchTaskItem:OnGoClick` — one
#     `SFSNetwork.SendMessage(MsgDefines.DispatchAssist, infos.uuid, infos.targetServer)`
#     behind a `GetTodayAssistNum() < GetDispatchSetting("aid_count")` gate;
#   * the message class puts exactly those two fields on the wire
#     (`DispatchAssistMessage:OnCreate` — `PutLong(uuid)`, `PutInt(targetServer)`),
#     so it is headless: no window, no marker tap, no camera move;
#   * a task is helpable while it is FINISHED and unrewarded, which is precisely
#     what `GetAllianceAssisTaskCount()` counts (72 = the finished tasks, live).
#
# THE LIST GOES STALE AND THAT IS THE WHOLE TRAP. The client only learns that a
# task has been helped by somebody else when a push tells it, and a headless bot
# has no window open to ask. Sending against a stale entry is answered with
# `dispatch_des028` — «Спасибо, но задача уже решена с помощью других лиц» — and
# `todayAssistNum` does not move, so it reads exactly like a bot that pressed
# nothing. Live, the first two attempts failed that way and the third, sent right
# after `GetAllAllianceTasksFromServer()`, took the counter 0 -> 1.

def secret_task_assists_left() -> str:
    """Lua *expression* -> helps the account may still send today.

    `GetDispatchSetting("aid_count")` is the daily cap (5 on the live account) and
    `GetTodayAssistNum()` what has been spent. The same shape as
    `secret_task_steals_left`, and a DIFFERENT budget: robbing and helping have a cap
    each, and spending one does not touch the other.
    """
    return ("(function() local M=DataCenter.ActDispatchTaskDataManager "
            "local cap=tonumber(M:GetDispatchSetting('aid_count')) or 0 "
            "local used=tonumber(M:GetTodayAssistNum()) or 0 "
            "local left=cap-used if left<0 then left=0 end return left end)()")


def secret_task_assist_refresh() -> str:
    """Ask the server for the alliance's task list again — `hero.dispatch.alliance.list`.

    The first half of every help, and not optional (see the block above): the local copy
    keeps tasks other people have already helped with, and the server refuses those with
    a tip rather than with anything the budget records. Fire-and-forget — the reply lands
    on its own thread, so a caller reads the list AFTER a settle, never in this chunk.
    """
    return ('pcall(function() DataCenter.ActDispatchTaskDataManager'
            ':GetAllAllianceTasksFromServer() end) '
            'CS.UnityEngine.Debug.LogError("ACT assist_list_requested")')


def secret_task_assist_rule(level_min: int, star_wait_min: int = 0) -> str:
    """Park the help rule in the VM: the lowest level, and how long a star is worth.

    `TAP` takes no arguments, so the rule cannot travel with the press — it is left on
    the dispatch manager's own table, the same place the robbery queue lives, because
    this VM rejects some new globals. The RANK half of the rule is not a setting: only
    the top two ranks are ever helped, and a star always outranks a UR
    (see :data:`_ASSIST_SCAN`).

    `star_wait_min` is the second half of the priority: the longest a ripening star may
    hold one of the day's five back. `0` means «hold for any star that can ripen at all
    today» — the bound then comes from the task's own expiry and the daily reset alone.
    """
    return ("local M=DataCenter.ActDispatchTaskDataManager M.__lw_assist_level=%d "
            "M.__lw_assist_wait_ms=%d "
            'CS.UnityEngine.Debug.LogError("ACT assist_rule level="..tostring(%d)'
            '.." star_wait_min="..tostring(%d))'
            % (int(level_min), int(star_wait_min) * 60000,
               int(level_min), int(star_wait_min)))


#: When the day the daily counters belong to rolls over, in ms past midnight UTC.
#:
#: 02:00 UTC, measured rather than assumed: 597 of 636 secret-task tiles in one capture
#: shared a single expiry of 01:59:59 UTC and the rest fell on adjacent days
#: (`docs/research/protocol.md`, «Expiry is a daily reset»), and the treasure activity's
#: own `expire` landed on the same boundary (`docs/research/world-treasures.md`). It is
#: what «до конца дня» means for a help that has to be spent before the five come back.
_DAY_RESET_MS = 2 * 3600 * 1000

#: One walk over `allianceTask`, leaving the whole decision in locals (#1292).
#:
#: What it leaves behind, all judged on the GAME's clock and on the task's own config row
#: (`lw_dispatch_tasks` through `v.cfg` — never the cfgId's digits, #1267):
#:
#:   * `sready` / `uready` — helpable NOW: finished, unrewarded, unexpired, at or above
#:     the parked level. A star counts as a star even when it is also `color = 5`;
#:   * `bstar` / `bur` — the best of each, highest level first;
#:   * `spend` — starred tasks still COUNTING DOWN that can still be helped today, with
#:     `seta` the wait to the nearest of them, `slvl` its level and `bnext` the task
#:     itself. Each one holds back one of the day's helps;
#:   * `slate` — starred tasks that cannot make it: they ripen after their own
#:     `actEndTime`, after the daily reset, or after the parked wait bound. Waiting for
#:     one of those spends nothing and gains nothing, so they are counted and said out
#:     loud rather than silently waited on;
#:   * `left` — helps still in today's budget;
#:   * `best` — what a press would take: a ready star always, and a ready UR only while
#:     there are more helps left than there are stars worth waiting for.
#:
#: THE PRIORITY IS THE POINT. «Звезда в приоритете, UR только если звёзд нет» (#1292):
#: the old rank was `lvl*2+spec`, so a level-7 UR beat a level-6 star and the star was
#: gone by the time it mattered. A star is rare — one alliance task in two hundred
#: carried `is_special = 1` against 34 finished URs (#1272) — which is exactly why the
#: budget waits for one rather than racing it, and exactly why the wait needs a floor
#: under it: 34 URs sitting unspent all day is the other way to waste the five.
_ASSIST_SCAN = (
    "local M=DataCenter.ActDispatchTaskDataManager "
    + _SERVER_NOW_MS +
    "local now=nowms local low=tonumber(M.__lw_assist_level) or 0 "
    "local wait=tonumber(M.__lw_assist_wait_ms) or 0 "
    "local left=" + secret_task_assists_left() + " "
    # The next boundary the daily counters roll over on, on the game's own clock.
    + ("local dayend=(math.floor((now-%d)/86400000)+1)*86400000+%d "
       % (_DAY_RESET_MS, _DAY_RESET_MS)) +
    "local sready,uready,spend,seta,slvl,slate=0,0,0,-1,0,0 "
    "local bstar,bsrank,bur,burank,bnext=nil,-1,nil,-1,nil "
    "for _,v in pairs(M.allianceTask or {}) do "
    "local done=tonumber(v.completionTime) or 0 "
    "local rewarded=tonumber(v.rewarded) or 0 "
    "local exp=tonumber(v.actEndTime) or 0 "
    "local lvl,spec,colour=0,0,0 "
    "pcall(function() lvl=tonumber(v.cfg:getValue('level')) or 0 "
    "spec=tonumber(v.cfg:getValue('is_special')) or 0 "
    "colour=tonumber(v.cfg:getValue('color')) or 0 end) "
    "if done>0 and rewarded==0 and (exp==0 or now<exp) and lvl>=low then "
    "if done<=now then "
    "if spec==1 then sready=sready+1 "
    "if lvl>bsrank then bstar,bsrank=v,lvl end "
    "elseif colour>=5 then uready=uready+1 "
    "if lvl>burank then bur,burank=v,lvl end end "
    "elseif spec==1 then "
    "local lim=dayend if exp>0 and exp<lim then lim=exp end "
    "if done<lim and (wait<=0 or done-now<=wait) then spend=spend+1 "
    "if seta<0 or done-now<seta then seta=done-now slvl=lvl bnext=v end "
    "else slate=slate+1 end "
    "end end end "
    "local best=bstar if best==nil and left-spend>0 then best=bur end ")


def secret_task_assist_scan() -> str:
    """Walk the alliance list once and park the reading the recipe branches on.

    A snapshot rather than seven separate reads: the recipe asks six questions of it
    («is a star ready», «is one coming», «how long», «what level», «has one run out of
    day», «is there a UR at all») and they must all be answers to the SAME walk — a star
    that ripens between two reads would otherwise be waited for and helped in the same
    breath, or neither.

    Each answer is parked as a PLAIN NUMBER of its own on the dispatch manager — the
    same table the level and the robbery queue already live on — so the recipe reads one
    with `(tonumber(…__lw_star_left) or 0)` and a scan that never ran reads as zero
    rather than as a nil index that would fail the run. `__lw_star_eta` is in MINUTES,
    rounded up, and `-1` when there is no star to wait for: «готова через 0 минут» about
    a star forty seconds away is the kind of countdown #1227 was about.

    `__lw_star_eta_sec` IS THE SAME WAIT IN SECONDS, and it is what the sprint is
    scheduled off (#1294). A star matures at a moment the client already knows to the
    millisecond — `completionTime` is on the task — so nothing has to poll to DISCOVER
    readiness; the only question is being there when it arrives. Rounded DOWN, so the
    schedule lands a shade early rather than a shade late, and `-1` for «no star coming»
    exactly as the minutes are.

    Says what it saw on the way past — `ACT assist_scan star_ready=… ur_ready=…
    star_pending=… star_eta_min=… star_eta_sec=… star_lvl=… star_late=… left=…` — so the
    decision below it can be read back out of a log without re-asking the game.
    """
    return ("pcall(function() " + _ASSIST_SCAN +
            "local etamin=-1 if seta>=0 then etamin=math.ceil(seta/60000) end "
            "local etasec=-1 if seta>=0 then etasec=math.floor(seta/1000) end "
            # What is actually being HELD, which is not the same as how many stars are
            # coming: three ripening stars hold nothing at all out of a spent budget,
            # and a recipe that says «придерживаю 3 из 0» is reporting arithmetic
            # rather than the day (#1292, seen live).
            "local hold=spend if hold>left then hold=left end "
            "M.__lw_star_ready=sready M.__lw_star_ur=uready M.__lw_star_pending=spend "
            "M.__lw_star_eta=etamin M.__lw_star_level=slvl M.__lw_star_late=slate "
            "M.__lw_star_left=left M.__lw_star_hold=hold M.__lw_star_eta_sec=etasec "
            'CS.UnityEngine.Debug.LogError("ACT assist_scan star_ready="..tostring(sready)'
            '.." ur_ready="..tostring(uready).." star_pending="..tostring(spend)'
            '.." star_eta_min="..tostring(etamin).." star_eta_sec="..tostring(etasec)'
            '.." star_lvl="..tostring(slvl)'
            '.." star_late="..tostring(slate).." left="..tostring(left)'
            '.." hold="..tostring(hold)) end)')


def secret_task_star_field(name: str) -> str:
    """Lua *expression* -> one number :func:`secret_task_assist_scan` parked.

    `ready` / `ur` / `pending` / `eta` / `eta_sec` / `level` / `late` / `left` / `hold`.
    Zero when nothing has been scanned yet, which is the honest answer for a recipe that
    has not looked: no star ready, no star coming, nothing to hold back.
    """
    return ("(tonumber(DataCenter.ActDispatchTaskDataManager.__lw_star_%s) or 0)" % name)


def secret_task_assists_pending() -> str:
    """Lua *expression* -> presses `assist_secret_task` can still make.

    The button's `count_lua`, re-read by `xall` between presses, and where the priority
    is actually SPENT rather than merely described:

        ready stars, up to the budget
      + ready URs, but only into what is left AFTER one help is set aside for every
        star still ripening today

    So five helps and two ripening stars buy three URs now and keep two in hand; five
    helps and five ripening stars buy nothing at all and say so. A star that cannot
    ripen in time was never counted into `spend`, so it holds nothing back.
    """
    return ("(function() %s "
            "local n=sready if n>left then n=left end "
            "local room=left-n-spend "
            "if room>0 then local u=uready if u>room then u=room end n=n+u end "
            "return n end)()" % _ASSIST_SCAN)


def assist_next_secret_task() -> str:
    """Help the best matching alliance task — one press, one `hero.dispatch.assist`.

    `best` is a ready star when there is one and a ready UR only when the reserve allows
    it (:data:`_ASSIST_SCAN`), so the press cannot spend on a UR what the count above is
    holding for a star.

    The chosen task is dropped from the LOCAL list before the send
    (`DeleteAllianceTasks`, which is what the reply's own handler does on success). That
    is what keeps `xall` moving: a refusal («уже решена с помощью других лиц») leaves the
    budget untouched, so a press that did not drop its target would pick the same doomed
    uuid on every round until the loop's cap. It costs nothing to drop — the next
    `hero.dispatch.alliance.list` brings back whatever is still real.
    """
    return (_ASSIST_SCAN +
            "if best and left > 0 then local u,s=best.uuid,best.targetServer "
            "pcall(function() M:DeleteAllianceTasks(u) end) "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchAssist, u, s) end) "
            'CS.UnityEngine.Debug.LogError("ACT assist_sent uuid="..tostring(u)'
            '.." srv="..tostring(s)) end')


# --------------------------------------------------------------------------
# The star sprint — being there in the second the star matures (#1294)
# --------------------------------------------------------------------------
# WHAT WAS MEASURED. Live acceptance of #1292 caught the whole problem in one reading:
# the day's only ripe star was gone from the alliance list in UNDER TWO MINUTES, taken by
# alliancemates, and `star_ready` never once read non-zero. The reserve had done its job
# — a help was being held — and the help was still not spent, because a look every five
# minutes cannot land inside a two-minute window. Waiting for a star and then arriving
# late loses twice: the URs went unspent too.
#
# THE CLOCK IS ALREADY IN THE CLIENT'S HAND, and that is what makes this cheap. A task
# carries `completionTime`, so the moment it matures is known to the millisecond as soon
# as the ordinary five-minute poll has seen it — live, three level-7 stars announced
# themselves 78, 79 and 233 minutes ahead. Nothing has to poll faster to DISCOVER
# readiness. What is needed is to be pressing when it arrives, which is one scheduled
# wake-up and a few seconds of spam — not a shorter period all day.
#
# SO IT IS THE ROBBERY'S SHAPE, aimed at a moment instead of at a tile (#1272): arm the
# target a couple of seconds early, press as fast as the channel allows, and stop on the
# SERVER — the daily counter moving, or a tip that says the task is not there any more.
#
# PRESSING EARLY IS FREE, on the same evidence the robbery rests on.
# `DispatchAssistMessage:HandleMessage` takes the `errorCode` branch on a refusal and
# raises a tip; `todayAssistNum` is only ever set from the SUCCESS branch, out of the
# server's own reply (docs/research/secret-task-assist.md). A press against a task that
# has not finished yet therefore spends nothing — exactly as a robbery a second too early
# does — so the loop may start before the countdown ends and let the server decide when
# «yes» begins.

#: Tips that mean «this task cannot be helped any more» — terminal for the sprint.
#:
#: `dispatch_des028` is the one that cost two of the day's five before it was understood
#: («Спасибо, но задача уже решена с помощью других лиц»), and it is the exact answer a
#: LOST race gives: somebody else got there first. `dispatch_des041` is the task's own
#: expiry. Anything else the server says leaves the loop pressing, for the reason the
#: robbery's list gives: a tip we have not met before must not be read as a refusal.
ASSIST_GONE_TIPS = ("dispatch_des028", "dispatch_des041")

#: 1 when the server has said the armed task is not helpable any more.
_ASSIST_GONE = ("(function() local M=DataCenter.ActDispatchTaskDataManager "
                "local t=tostring(M.__lw_assist_tip or '') "
                + " ".join("if t=='%s' then return 1 end" % k for k in ASSIST_GONE_TIPS)
                + " return 0 end)()")


def secret_task_assist_gone() -> str:
    """Lua *expression* -> 1 when the server has refused the armed task terminally."""
    return _ASSIST_GONE


def secret_task_assist_taken() -> str:
    """Lua *expression* -> 1 when the server has confirmed a help of the armed task.

    `todayAssistNum` against the mark stamped when the target was armed, and that is the
    whole test — the counter reaches the client only on the reply's success branch, so a
    `assist_sprint_sent` line proves a frame left and nothing more.
    """
    return ("(function() local M=DataCenter.ActDispatchTaskDataManager "
            "local now=tonumber(M:GetTodayAssistNum()) or 0 "
            "local mark=tonumber(M.__lw_assist_mark) "
            "if mark == nil then return 0 end "
            "if now ~= mark then return 1 end return 0 end)()")


def secret_task_assist_sprint_arm() -> str:
    """Choose the star to sprint at, stamp the baseline, and open the window.

    The target is the ready star if the scan found one and otherwise the NEAREST RIPENING
    one — the sprint is played a couple of seconds early on purpose, so at arming time the
    star it is aimed at usually has not matured yet. Only a star: a UR is not worth a spam
    loop (thirty-four of them sat unhelped in one live reading) and the ordinary recipe
    spends those at its own pace.

    Parks `__lw_assist_target` (uuid + server, and the level for the log), the counter
    mark the presses are judged against, a fresh tip mailbox and the deadline the loop
    stops at. Says `ACT assist_armed lvl=… eta_sec=… window=…`, or `ACT assist_armed
    none` when the scan found no star at all — a sprint with nothing to press must say so
    rather than look like a silent success.

    How wide the window is comes off `__lw_assist_window_ms`, parked by the recipe from
    its own `ARGS` a line earlier, because a `TAP` carries no arguments. Twenty seconds
    when nothing has parked one.
    """
    return (_ASSIST_SCAN +
            "local t=bstar or bnext "
            "M.__lw_assist_tip=nil "
            "M.__lw_assist_mark=tonumber(M:GetTodayAssistNum()) or 0 "
            "M.__lw_assist_presses=0 "
            "local win=tonumber(M.__lw_assist_window_ms) or 20000 "
            "M.__lw_assist_deadline=now+win "
            "if t==nil or left<=0 then M.__lw_assist_target=nil "
            'CS.UnityEngine.Debug.LogError("ACT assist_armed none left="..tostring(left)) '
            "else local eta=0 local d=tonumber(t.completionTime) or 0 "
            "if d>now then eta=math.floor((d-now)/1000) end "
            "local lvl=0 pcall(function() lvl=tonumber(t.cfg:getValue('level')) or 0 end) "
            "M.__lw_assist_target={uuid=t.uuid,server=t.targetServer,level=lvl} "
            'CS.UnityEngine.Debug.LogError("ACT assist_armed lvl="..tostring(lvl)'
            '.." eta_sec="..tostring(eta).." window="..tostring(math.floor(win/1000))'
            '.." left="..tostring(left)) end ' + _TIP_HOOK)


def secret_task_assist_sprint_pending() -> str:
    """Lua *expression* -> is the armed star still worth pressing again? (1 or 0)

    The sprint's `count_lua`, and the same four questions the robbery's asks: there is a
    target, the day's budget is not spent, the server has not confirmed this one, and it
    has not said the task is gone. Plus the one the robbery does not need — the window,
    because a star that never matures (a mate who cancelled, a clock that was wrong)
    would otherwise be pressed until the button's cap every single time.
    """
    return ("(function() local M=DataCenter.ActDispatchTaskDataManager "
            "if M.__lw_assist_target==nil then return 0 end "
            + _SERVER_NOW_MS +
            "local dl=tonumber(M.__lw_assist_deadline) or 0 "
            "if dl>0 and nowms>dl then return 0 end "
            "local b=%s local t=%s local g=%s "
            "if b>0 and t==0 and g==0 then return 1 end return 0 end)()"
            % (secret_task_assists_left(), secret_task_assist_taken(),
               secret_task_assist_gone()))


def secret_task_assist_sprint_press() -> str:
    """Press the armed star once — one `hero.dispatch.assist`, and LEAVE IT ARMED.

    The opposite of :func:`assist_next_secret_task`, which drops its target from the local
    list before sending so that `xall` moves on. Here the target has to survive its own
    press, because pressing it AGAIN is the entire point: the loop ends when the server
    answers, not when the client has asked once.
    """
    return ("local M=DataCenter.ActDispatchTaskDataManager "
            "local t=M.__lw_assist_target "
            "if t and %s > 0 then "
            "M.__lw_assist_presses=(tonumber(M.__lw_assist_presses) or 0)+1 "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchAssist, "
            "t.uuid, t.server) end) "
            'CS.UnityEngine.Debug.LogError("ACT assist_sprint_sent n="'
            '..tostring(M.__lw_assist_presses)) end' % secret_task_assists_left())


def secret_task_assist_sprint_verdict() -> str:
    """Say what the sprint did, disarm, and leave the numbers a measurement needs.

    `ACT assist_sprint_done how=<taken|gone|unanswered> lvl=<n> presses=<n> tip=<id>` —
    the same three outcomes the robbery reports per target, for the same reason: «took
    it», «somebody else did» and «the server never answered» are three different days and
    they look identical in a log that only says the spam ended.

    `presses` is the measurement the task asked for (#1294): how many attempts a taken
    star costs, and how many a lost one burns.
    """
    return ("local M=DataCenter.ActDispatchTaskDataManager "
            "local t=M.__lw_assist_target local how='unanswered' "
            "if %s == 1 then how='taken' elseif %s == 1 then how='gone' end "
            "local lvl=0 if t then lvl=tonumber(t.level) or 0 end "
            'CS.UnityEngine.Debug.LogError("ACT assist_sprint_done how="..how'
            '.." lvl="..tostring(lvl)'
            '.." presses="..tostring(tonumber(M.__lw_assist_presses) or 0)'
            '.." tip="..tostring(M.__lw_assist_tip or "")) '
            "M.__lw_assist_target=nil"
            % (secret_task_assist_taken(), secret_task_assist_gone()))


def dispatch_task_cfg_rank(cfg_ids) -> str:
    """Emit `ACT CFG cfg=<id> lvl=<n> spec=<0|1>` for each secret-task TEMPLATE id.

    The game's own `lw_dispatch_tasks` row, asked for a bare cfgId — with no live task
    record to hang it off. Every other reader in this repo reaches `level` /
    `is_special` through `v.cfg`, the row already attached to an entry in `allianceTask`
    / `singleTask`, so a tile that came off a PCAP had nothing to ask and fell back to
    the digits — which call a `60009903` template «level 99, starred» where the game
    calls it «level 7, not starred» (#1267). That fallback is fine for a decoder with no
    client in the room; it is not fine for the thing that spends one of five raids a day
    (#1188), and the panel and the tool both have a client.

    `LocalController.instance` is a FUNCTION and not a field — `instance:getLine(…)`
    raises «attempt to index a function value». The path was read out of the bytecode of
    `ActDispatchTaskDataManager:UpdateOneAllianceTask` (`string.dump`, then its string
    constants in order), which is the method that attaches `cfg` to a task in the first
    place; it is written up in docs/research/secret-task-steal.md §6c.

    A template the client has no row for emits `lvl=0 spec=0`, which `proto.task_rank`
    already reads as «the config said nothing» and answers from the digits — so an
    unknown id degrades to exactly the behaviour there was before, never to a silent
    «not starred».
    """
    ids = ",".join(str(int(c)) for c in cfg_ids)
    return (
        'pcall(function() '
        'for _, cfg in ipairs({%s}) do '
        'local lvl, spec = 0, 0 '
        'pcall(function() '
        'local row = LocalController.instance():getLine(TableName.LwDispatchTask, cfg) '
        'lvl = tonumber(row:getValue("level")) or 0 '
        'spec = tonumber(row:getValue("is_special")) or 0 end) '
        'CS.UnityEngine.Debug.LogError("ACT CFG cfg="..tostring(cfg)'
        '.." lvl="..tostring(lvl).." spec="..tostring(spec)) '
        'end end)' % ids)


#: The last line both alliance reads print — the sentinel that ends the wait for
#: them (#1272). They are the panel's most frequent reads and a flat settle was what
#: they cost: 1.1 s per ready-row poll and per «Обновить состояние», with the daemon's
#: lock held for all of it, so every other call queued behind a read that had already
#: answered. `early` cannot help here — a hundred `Debug.LogError` lines do not always
#: land inside the quiet window it guesses by, so cutting the wait short truncated the
#: list. A last line of its own removes the guess (`lua_eval.collect`).
VT_END = "VT_END"


def secret_task_raidable_alliance() -> str:
    """Emit every alliance secret task that is raidable *right now*, straight from the VM.

    The client already keeps a parsed, always-current copy of the alliance's hero
    dispatch tasks in `ActDispatchTaskDataManager.allianceTask` (see
    project_secret_task_list) — the same list a member's shared secret task lands in
    the instant the push arrives. Reading it needs no pcap and no map panning, so a
    tile is knowable the moment the game knows it rather than whenever the sweep next
    pans over it. That is what lets the auto-loot react in a second or two instead of
    waiting out a capture tick.

    Only the tasks that pass the raid gate are emitted — dispatch finished
    (`completionTime` set and not in the future), not expired (`actEndTime` ahead), and
    a free loot slot (`#stealInfoList < 3`) — so the output is the handful of currently
    lootable tiles, not the whole 100+ row table. Each line carries what a steal target
    needs: `uuid`, `cfgId` (level + star split off it in Python), `srv` (targetServer),
    the tile `x`/`y` for the label, and the loot count. The per-tile conditions the
    server owns (my own past loots, the protect window, sector range) stay its call, the
    same as every other route into `hero.dispatch.steal`.

    Marker-tagged `ACT VT …` lines, one per raidable task; parsed by
    `steal_secret_task._vm_raidable_tasks`.
    """
    return (
        'pcall(function() '
        'local m = DataCenter.ActDispatchTaskDataManager '
        + _SERVER_NOW_MS +
        'local now = nowms local n = 0 '
        'CS.UnityEngine.Debug.LogError("ACT NOWMS="..tostring(nowms)) '
        'for _, v in pairs(m.allianceTask or {}) do '
        'local done = tonumber(v.completionTime) or 0 '
        'local exp = tonumber(v.actEndTime) or 0 '
        'local steals = #(v.stealInfoList or {}) '
        'if done > 0 and done <= now and (exp == 0 or now < exp) and steals < 3 then '
        'n = n + 1 '
        'local x, y = 0, 0 '
        'pcall(function() local tp = SceneUtils.IndexToTilePos(v.pointId) x, y = tp.x, tp.y end) '
        # The task's OWN config row — `lw_dispatch_tasks`, by column name, exactly
        # as `dispatch_tasks._DUMP_LUA` reads it. Without these two the parser has
        # only the cfgId's digits, which call a level-7 tile «level 99» (#1267).
        'local lvl, spec = 0, 0 '
        'pcall(function() lvl = tonumber(v.cfg:getValue("level")) or 0 '
        'spec = tonumber(v.cfg:getValue("is_special")) or 0 end) '
        'CS.UnityEngine.Debug.LogError("ACT VT uuid="..tostring(v.uuid)'
        '.." cfg="..tostring(v.cfgId).." srv="..tostring(v.targetServer)'
        '.." x="..tostring(x).." y="..tostring(y).." steals="..tostring(steals)'
        '.." lvl="..tostring(lvl).." spec="..tostring(spec)'
        '.." done="..tostring(done).." exp="..tostring(exp)) '
        'end end '
        'CS.UnityEngine.Debug.LogError("ACT %s n="..tostring(n)) end)'
        % VT_END)


def secret_task_all_alliance() -> str:
    """Emit every *live* alliance secret task, whether its dispatch is done yet or not.

    A wider read than `secret_task_raidable_alliance`: the raid gate here keeps the
    tile on the map (not expired, `actEndTime` ahead) and a loot slot free
    (`#stealInfoList < 3`), but does NOT require the dispatch to have finished
    (`completionTime <= now`). So the output also carries the tasks still counting down
    to raidability — what the «Secret Tasks» tab needs to show a per-tile timer «готово
    через …» and then flip a row to raidable the moment its clock runs out.

    Same `ACT VT …` line shape as the raidable read, so both parse through
    `steal_secret_task._parse_vt_lines`; `completionTime` (`done`) tells the two states
    apart on the Python side. `completionTime` must be set (`> 0`) — a tile with no
    finish time has no countdown to draw.

    IT ENDS BY SAYING SO — `ACT VT_END n=<lines>` (#1272). The read is the panel's most
    frequent one (every ready-row poll, every «Обновить состояние») and it used to be paid
    for with a flat 1.1 s settle, because there was no way to know the answer was
    complete: a hundred `Debug.LogError` lines do not always land inside the 20 ms quiet
    window `early` guesses by, so cutting the wait short truncated the list. A last line
    of its own removes the guess — see :data:`VT_END` and `lua_eval.collect`.
    """
    return (
        'pcall(function() '
        'local m = DataCenter.ActDispatchTaskDataManager '
        + _SERVER_NOW_MS +
        'local now = nowms local n = 0 '
        'CS.UnityEngine.Debug.LogError("ACT NOWMS="..tostring(nowms)) '
        'for _, v in pairs(m.allianceTask or {}) do '
        'local done = tonumber(v.completionTime) or 0 '
        'local exp = tonumber(v.actEndTime) or 0 '
        'local steals = #(v.stealInfoList or {}) '
        'if done > 0 and (exp == 0 or now < exp) and steals < 3 then '
        'n = n + 1 '
        'local x, y = 0, 0 '
        'pcall(function() local tp = SceneUtils.IndexToTilePos(v.pointId) x, y = tp.x, tp.y end) '
        # The task's OWN config row — `lw_dispatch_tasks`, by column name, exactly
        # as `dispatch_tasks._DUMP_LUA` reads it. Without these two the parser has
        # only the cfgId's digits, which call a level-7 tile «level 99» (#1267).
        'local lvl, spec = 0, 0 '
        'pcall(function() lvl = tonumber(v.cfg:getValue("level")) or 0 '
        'spec = tonumber(v.cfg:getValue("is_special")) or 0 end) '
        'CS.UnityEngine.Debug.LogError("ACT VT uuid="..tostring(v.uuid)'
        '.." cfg="..tostring(v.cfgId).." srv="..tostring(v.targetServer)'
        '.." x="..tostring(x).." y="..tostring(y).." steals="..tostring(steals)'
        '.." lvl="..tostring(lvl).." spec="..tostring(spec)'
        '.." done="..tostring(done).." exp="..tostring(exp)) '
        'end end '
        'CS.UnityEngine.Debug.LogError("ACT %s n="..tostring(n)) end)'
        % VT_END)


# --------------------------------------------------------------------------
# Ghost recon robbery — «Операция Призрак» / ghost.recon.steal
# --------------------------------------------------------------------------
# A DIFFERENT feature from the secret-task robbery above, despite the similar
# shape. «Секретка» is the hero dispatch that sits on a player's own tile and
# rides `hero.dispatch.*`; «Операция Призрак» is the weekly co-op event whose
# squads sit on `f2 = 29` tiles and ride `ghost.recon.*`. Both can be robbed,
# the commands are different, and the two daily budgets are counted separately.
# See docs/research/ghost-recon-steal.md and secret-task-steal.md.
#
# The wire side was captured in task #1005 (`results/ghost1005/steal.json`):
#
#     --> ghost.recon.steal  {uuid, ownerServer}
#     <-- ghost.recon.steal  {reward[], recordUuid, stealTimes, ownerInfo,
#                             cfgId, ownerUid, ownerServer, uuid}
#
# The Lua side was pinned live for this task:
#
#   * `MsgDefines.GhostReconSteal` = `ghost.recon.steal`, and
#     `GhostReconStealMessage:OnCreate(uuid, ownerServer)` puts exactly two
#     fields in the SFSObject — `PutLong uuid`, `PutInt ownerServer`.
#   * The press lives in the giant map-button dispatcher
#     `UIWorldPointBtn:OnBtnClick`, in the branch for
#     `WorldPointBtnType.GhostreconTaskSteal` (96); its constants read
#     `… GhostReconSteal | ownerServer …`, i.e. that one SendMessage.
#   * `GhostReconStealMessage:HandleMessage` is the reply applier
#     (`RewardManager:AddRewardsAndRes`, `ActGhostreconManager:GhostReconStealHandler`,
#     `UIUtil.ShowTipsId` on an errorCode). Calling it sends nothing.
#
# The owning manager is `DataCenter.ActGhostreconManager`: `taskList` (the
# squads the client knows, each with `uuid`, `cfgId`, `ownerId`, `ownerServer`,
# `targetServer`, `pointId`, `completionTime`, `actEndTime` and a `stealList` of
# past thieves), `stealTimes` (spent today), `GetNowSettingCfg().stealCount`
# (the daily cap, 5), `dispatchStealRange` (the set of servers that may be
# robbed at all) and `IsOpenDay()`.

# `GhostreconPointStealType`, the game's own verdict on one tile.
GHOST_STEAL_PREVIEW, GHOST_STEAL_CAN = 1, 2
GHOST_STEAL_UNSTEAL, GHOST_STEAL_UNSHOW = 3, 4
GHOST_STEAL_NAMES: dict[int, str] = {
    GHOST_STEAL_PREVIEW: "preview",     # visible, not robbable yet
    GHOST_STEAL_CAN: "can-steal",
    GHOST_STEAL_UNSTEAL: "no-steal",    # budget spent / already robbed by me
    GHOST_STEAL_UNSHOW: "not-shown",    # still running, or no template
}

# `WorldPointBtnType.GhostreconTaskSteal` — the map button this replaces. Not
# used by the send (the send is the message); kept because it names the click.
GHOST_RECON_STEAL_BTN = 96


def ghost_recon_is_open() -> str:
    """Lua *expression* -> 1 while the ghost-recon event is running today.

    `IsOpenDay()` compares the server clock against `openTime` for the same server
    day. Outside the event the whole feature is dark: `taskList` is empty, no tile
    carries a steal button, and a robbery would be refused — so every press below
    checks this first rather than putting a doomed message on the wire.
    """
    return "(DataCenter.ActGhostreconManager:IsOpenDay() and 1 or 0)"


def ghost_recon_steals_left() -> str:
    """Lua *expression* -> ghost-recon robberies still available today.

    `GetNowSettingCfg().stealCount` is the daily cap (5 on the live config) and
    `stealTimes` what has been spent. Counted separately from the secret-task
    budget in `secret_task_steals_left()` — the two features share nothing but
    the idea.
    """
    return ("(function() local M=DataCenter.ActGhostreconManager "
            "local cfg=M:GetNowSettingCfg() "
            "local cap=tonumber(cfg and cfg.stealCount) or 0 "
            "local used=tonumber(M.stealTimes) or 0 "
            "local left=cap-used if left<0 then left=0 end return left end)()")


def _ghost_task_by_uuid() -> str:
    """Lua chunk fragment: `find(uuid)` -> the task record, or nil.

    Looks in `taskList` (the squads the client actually has data for) — the alliance
    list is deliberately not searched: `ActGhostreconAllianceTaskInfo` carries neither
    `completionTime` nor `stealList`, so it cannot answer whether a tile is robbable.
    """
    return ("local function find(u) "
            "for _,t in ipairs(DataCenter.ActGhostreconManager.taskList or {}) do "
            "if tostring(t.uuid)==tostring(u) then return t end end return nil end ")


# The client's own verdict, `ActGhostreconManager:GetPointStealType(cfgId,
# completionTime, stealList)`, is the right gate for the TIMING half — it knows the
# template, the protect window and whether the squad has finished. It is called
# below with an EMPTY looter list on purpose:
#
#   passing a non-empty `stealList` throws inside the game
#   (`ActGhostreconManager.lua:570: attempt to index a nil value (field 'player')`
#   — the client reads `LuaEntry.player`, lowercase, which does not exist in this
#   VM; `LuaEntry.Player` does).
#
# Verified live: `GetPointStealType(60302, <finished>, {})` -> 2 (CanSteal),
# `GetPointStealType(60302, <still running>, {})` -> 4 (UnShow), and any non-empty
# list -> that error. So the looter half is counted here instead, from the record's
# own `stealList` against the template's `stealMaxtimes` (3 on cfg 60302), which is
# the same arithmetic the crashing branch was doing.
def ghost_recon_steal_state(uuid: int) -> str:
    """Lua *expression* -> `GhostreconPointStealType` for `uuid` (0 = unknown task).

    Numeric so a caller can tell *why* a target was skipped: 2 is robbable, 1 is
    visible but not yet, 3 is "not for me" (budget spent / already robbed), 4 is
    still running. 0 means the client has no record of that uuid at all — ask the
    server for the lists first (`ghost_recon_refresh()`).
    """
    return ("(function() %s local t=find(%d) if not t then return 0 end "
            "local M=DataCenter.ActGhostreconManager "
            "local ok,st=pcall(function() "
            "return M:GetPointStealType(t.cfgId, t.completionTime, {}) end) "
            "if not ok then return 0 end return st end)()"
            % (_ghost_task_by_uuid(), int(uuid)))


def ghost_recon_can_steal(uuid: int) -> str:
    """Lua *expression* -> 1 when `uuid` may be robbed right now.

    Four conditions, and every one of them is the client's own:

    * the event is open today;
    * the game's verdict for the tile is `CanSteal` (finished, past its protect
      window, template known);
    * the squad is somebody else's — robbing my own is not a thing;
    * the tile has a free loot slot and I am not already in its `stealList`
      (counted here rather than by the game, see the note above);
    * the owner's server is inside `dispatchStealRange`, the event's reachable set.

    All of it is advisory in the same way the secret-task gate is: the server has the
    last word and answers a refused robbery with an errorCode plus a toast.
    """
    return (
        "(function() if %s==0 then return 0 end "
        "%s local t=find(%d) if not t then return 0 end "
        "local M=DataCenter.ActGhostreconManager "
        "local me=tostring(LuaEntry.Player.uid) "
        "if tostring(t.ownerId)==me then return 0 end "
        "local tpl=M:GetTaskTemplate(t.cfgId) if not tpl then return 0 end "
        "local n=0 for _,s in ipairs(t.stealList or {}) do n=n+1 "
        "if tostring(s.uid)==me then return 0 end end "
        "if n>=(tonumber(tpl.stealMaxtimes) or 3) then return 0 end "
        "local srv=t.ownerServer or t.targetServer "
        "if srv and (M.dispatchStealRange or {})[srv]~=true then return 0 end "
        "local ok,st=pcall(function() "
        "return M:GetPointStealType(t.cfgId, t.completionTime, {}) end) "
        "if not ok or st~=GhostreconPointStealType.CanSteal then return 0 end "
        "if %s<=0 then return 0 end return 1 end)()"
        % (ghost_recon_is_open(), _ghost_task_by_uuid(), int(uuid),
           ghost_recon_steals_left())
    )


def ghost_recon_refresh() -> str:
    """Ask the server for both ghost-recon task lists (own/known + alliance).

    Fire-and-forget: read the result from a SEPARATE chunk after a settle, never by
    looping inside this one. Without it a fresh client has an empty `taskList` and
    every target reads as unknown.
    """
    return ("pcall(function() SFSNetwork.SendMessage(MsgDefines.GhostreconGetTaskList) end) "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.GhostReconGetAllianceTaskList) end) "
            'CS.UnityEngine.Debug.LogError("ACT ghost_lists_requested")')


def ghost_recon_targets_dump() -> str:
    """Reader chunk: one `ACT G …` line per ghost-recon squad the client knows.

    Fields: `uuid`, `cfg` template id, `owner` uid, `srv` the owner's server, `tsrv`
    the server the squad is sent to, `x`/`y` (from `pointId`), `done` completion
    epoch-ms, `ends` the EVENT's own end, `exp` the task's expiry (the end of the event
    day, and the only one of the two anybody can count down to), `looted` how many of
    the template's slots are spent, `state` the game's `GhostreconPointStealType`, `raw` the task's OWN state
    (0 empty slot / 2 running / 3 done — `GHOST_STATE_*`), `mine` when the squad is my
    own, `al` the owning alliance's id, and `name` — the owner's nickname, hex-encoded
    because a nickname may hold spaces and any script at all.

    **The level, the rarity and the star come from the event's OWN config row**, not
    from the cfgId's digits: `lvl` / `colour` / `spec` are `GetTaskTemplate(cfgId)`'s
    `level` / `color` / `special`, and `slots` is its `stealMaxtimes`. The digits are
    only a fallback on the Python side, for a template the client has not loaded. That
    is the lesson #1244 cost on the other robbery, where home-made arithmetic invented
    both a star and a «level 99» (task #1251).

    `raw` and `state` are different questions and both are wanted: an EMPTY dispatch
    slot of mine has no squad, no tile and no coordinate, yet `GetPointStealType` still
    answers 2 for it. A reader that shows one as a target shows «✅ готово» on a slot
    nobody has filled (#1251).

    The owner's NAME is not on the task either — it is in the squad's own member list,
    against the member whose uid is the owner's. That is the only place the client
    keeps it, and it is what a list of «who of my alliance is running what» is for.

    A robbery needs `uuid` + `ownerServer`, both of which are printed, so this is the
    list a queue is built from.
    """
    return (
        "local M=DataCenter.ActGhostreconManager "
        "local me=tostring(LuaEntry.Player.uid) "
        "local function hex(s) return (tostring(s):gsub('.',function(c) "
        "return string.format('%%02x',c:byte()) end)) end "
        'CS.UnityEngine.Debug.LogError("ACT ghost open="..tostring(M:IsOpenDay())'
        '.." left="..tostring(%s).." known="..tostring(#(M.taskList or {}))) '
        "for _,t in ipairs(M.taskList or {}) do "
        "local x,y=0,0 pcall(function() local tp=SceneUtils.IndexToTilePos(t.pointId) "
        "x,y=tp.x,tp.y end) "
        "local n=0 for _,s in ipairs(t.stealList or {}) do n=n+1 end "
        "local ok,st=pcall(function() "
        "return M:GetPointStealType(t.cfgId, t.completionTime, {}) end) "
        "local lvl,colour,spec,slots=0,0,0,0 "
        "pcall(function() local c=M:GetTaskTemplate(t.cfgId) "
        "lvl=tonumber(c.level) or 0 colour=tonumber(c.color) or 0 "
        "spec=c.special and 1 or 0 slots=tonumber(c.stealMaxtimes) or 0 end) "
        "local who='' pcall(function() for _,mem in ipairs(t.memberList or {}) do "
        "local mi=mem.memberInfo or mem "
        "if tostring(mi.uid)==tostring(t.ownerId) then who=tostring(mi.name or '') end "
        "end end) "
        'CS.UnityEngine.Debug.LogError("ACT G uuid="..tostring(t.uuid)'
        '.." cfg="..tostring(t.cfgId).." owner="..tostring(t.ownerId)'
        '.." srv="..tostring(t.ownerServer or t.targetServer)'
        '.." tsrv="..tostring(t.targetServer)'
        '.." x="..tostring(x).." y="..tostring(y)'
        '.." done="..tostring(t.completionTime).." ends="..tostring(t.actEndTime)'
        '.." exp="..tostring(t.taskExpireTime)'
        '.." looted="..tostring(n).." state="..tostring(ok and st or 0)'
        '.." raw="..tostring(t.state)'
        '.." lvl="..tostring(lvl).." colour="..tostring(colour)'
        '.." spec="..tostring(spec).." slots="..tostring(slots)'
        '.." al="..tostring(t.allianceId).." name="..hex(who)'
        '.." mine="..tostring(tostring(t.ownerId)==me)) end'
        % ghost_recon_steals_left()
    )


def ghost_recon_templates_dump() -> str:
    """Reader chunk: one `ACT TPL …` line per ghost-recon template the client holds.

    The event's own config table, keyed by cfgId: `lvl` the level the game shows,
    `colour` the rarity it paints, `spec` whether it draws a star, `slots` how many
    robberies a tile allows and `dur` how long a squad stays out. Seventeen rows live.

    This is what lets a tile read off the MAP say the same things as one read out of
    the client's own list (#1251): the tile carries a cfgId and nothing else, and
    splitting that id into a level is the arithmetic that invented «level 99» on the
    other robbery. One read, cached by the caller for as long as the client runs — a
    config table does not change under a running client.
    """
    return (
        "local M=DataCenter.ActGhostreconManager "
        "for id,c in pairs(M.templates or {}) do "
        'CS.UnityEngine.Debug.LogError("ACT TPL cfg="..tostring(id)'
        '.." lvl="..tostring(c.level).." colour="..tostring(c.color)'
        '.." spec="..tostring(c.special and 1 or 0)'
        '.." slots="..tostring(c.stealMaxtimes).." dur="..tostring(c.time)) end'
    )


def ghost_recon_alliance_request() -> str:
    """Ask the server for the alliance's ghost-recon list — ONCE, to seed an empty one.

    The list normally needs no asking: the client keeps it and
    `push.ghost.recon.alliance.single` moves it, which is why the panel reads local
    state (:func:`ghost_recon_alliance_dump`) and polls nothing. But a client that has
    not had the event's window opened this session has never been sent the list at all,
    and an empty table is then indistinguishable from «the alliance has nothing out».
    The game's own window does exactly this in its `OnEnable`; this is that one message
    and nothing else (#1251).

    Fire-and-forget: read the result from a SEPARATE chunk after a settle.
    """
    return ("pcall(function() "
            "SFSNetwork.SendMessage(MsgDefines.GhostReconGetAllianceTaskList) end) "
            'CS.UnityEngine.Debug.LogError("ACT ghost_alliance_requested")')


def ghost_recon_alliance_dump() -> str:
    """Reader chunk: one `ACT A …` line per ghost-recon squad the ALLIANCE has out.

    A different manager from :func:`ghost_recon_targets_dump` and a different question.
    `ActGhostreconManager.taskList` is what THIS account is involved in — my own three
    slots and whatever else the client happens to have been told about. The window the
    player actually reads («Операция Призрак» → задания альянса) draws
    `ActGhostreconAllianceManager.allianceTaskList`, which is the whole alliance's, all
    of it at once — twelve rows live where the other list carried four (#1251).

    **Nothing here asks the server.** The list is already in the client and a push
    (`push.ghost.recon.alliance.single`) keeps it that way; the window's own
    `OnEnable` re-requests it, this does not.

    Fields: `uuid`, `cfg` template id, `owner` uid, `name` the leader's nickname
    (hex-encoded — it may hold spaces), `srv` the server the squad was sent to, `x`/`y`
    (from `pointId`), `start` when the squad set out, `state` the game's
    `GhostreconPointStealType`, `members` how many are on it — and the template's own
    `lvl` / `colour` / `spec` / `slots` / `dur`.

    **The clock is `start + dur`, not a field.** This record has no completion time at
    all; the event's config row carries how long a squad is out (`time`), so when it is
    back is arithmetic over two READ values rather than a guess. What is genuinely not
    in this list is how many times the tile has been robbed — there is no `stealList`
    on it — so a reader must leave that empty rather than invent it.
    """
    return (
        "local A=DataCenter.ActGhostreconAllianceManager "
        "local M=DataCenter.ActGhostreconManager "
        "local function hex(s) return (tostring(s):gsub('.',function(c) "
        "return string.format('%02x',c:byte()) end)) end "
        'CS.UnityEngine.Debug.LogError("ACT ghost_alliance n="'
        "..tostring(#(A.allianceTaskList or {}))) "
        "for _,t in ipairs(A.allianceTaskList or {}) do "
        "local x,y=0,0 pcall(function() local tp=SceneUtils.IndexToTilePos(t.pointId) "
        "x,y=tp.x,tp.y end) "
        "local lvl,colour,spec,slots,dur=0,0,0,0,0 "
        "pcall(function() local c=M:GetTaskTemplate(t.cfgId) "
        "lvl=tonumber(c.level) or 0 colour=tonumber(c.color) or 0 "
        "spec=c.special and 1 or 0 slots=tonumber(c.stealMaxtimes) or 0 "
        "dur=tonumber(c.time) or 0 end) "
        "local ok,st=pcall(function() "
        "return M:GetPointStealType(t.cfgId, t.teamStartTime+dur, {}) end) "
        "local who='' pcall(function() "
        "who=tostring(((t.leaderMemberInfo or {}).memberInfo or {}).name or '') end) "
        "local n=0 for _ in pairs(t.memberList or {}) do n=n+1 end "
        'CS.UnityEngine.Debug.LogError("ACT A uuid="..tostring(t.uuid)'
        '.." cfg="..tostring(t.cfgId).." owner="..tostring(t.ownerId)'
        '.." srv="..tostring(t.targetServer)'
        '.." x="..tostring(x).." y="..tostring(y)'
        '.." start="..tostring(t.teamStartTime)'
        '.." lvl="..tostring(lvl).." colour="..tostring(colour)'
        '.." spec="..tostring(spec).." slots="..tostring(slots).." dur="..tostring(dur)'
        '.." state="..tostring(ok and st or 0).." members="..tostring(n)'
        '.." name="..hex(who)) end'
    )


def ghost_recon_steal(uuid: int, owner_server: int) -> str:
    """Rob ghost-recon squad `uuid` on `owner_server` — one `ghost.recon.steal`.

    Headless: no tile tap, no popup, no march. Gated on the day's budget and on the
    event being open, so a spent or closed day never puts a doomed message on the
    wire. The per-tile conditions are `ghost_recon_can_steal()`'s job — this one
    takes a target the caller has already vetted (or is deliberately re-trying).
    """
    return ('if %s > 0 and %s > 0 then '
            'pcall(function() SFSNetwork.SendMessage(MsgDefines.GhostReconSteal, %d, %d) end) '
            'CS.UnityEngine.Debug.LogError("ACT ghost_steal_sent uuid=%d srv=%d") end'
            % (ghost_recon_is_open(), ghost_recon_steals_left(),
               int(uuid), int(owner_server), int(uuid), int(owner_server)))


def ghost_recon_leave_message(record_uuid: int, msg_id: int, owner_server: int) -> str:
    """Leave the robbed squad's owner one of the canned messages.

    `ghost.recon.leave.message {msgId, recordUuid, ownerServer}` — the follow-up
    captured in #1005, keyed by the `recordUuid` the robbery's reply carries (NOT the
    task uuid). Pure flavour; it pays nothing.
    """
    return ('pcall(function() SFSNetwork.SendMessage(MsgDefines.GhostReconLeaveMessage, '
            '%d, %d, %d) end) '
            'CS.UnityEngine.Debug.LogError("ACT ghost_message_sent record=%d msg=%d")'
            % (int(msg_id), int(record_uuid), int(owner_server),
               int(record_uuid), int(msg_id)))


# --- the ghost-recon target queue -----------------------------------------
# Same reason as the secret-task queue: `TAP` takes no arguments, so the targets
# are parked on the manager's own table and the button robs them one per press.
# A separate table from `__lw_steal_queue` so the two features can never rob each
# other's targets with the wrong command.

def ghost_recon_queue_set(targets) -> str:
    """Replace the ghost-recon queue with `targets` — (uuid, owner_server) pairs."""
    items = ",".join("{uuid=%d,server=%d}" % (int(u), int(s)) for u, s in targets)
    return ("local M=DataCenter.ActGhostreconManager M.__lw_ghost_queue={%s} "
            'CS.UnityEngine.Debug.LogError("ACT ghost_queue_set "..tostring(#M.__lw_ghost_queue))'
            % items)


def ghost_recon_queue_clear() -> str:
    """Empty the ghost-recon queue."""
    return ("local M=DataCenter.ActGhostreconManager M.__lw_ghost_queue={} "
            'CS.UnityEngine.Debug.LogError("ACT ghost_queue_cleared")')


def ghost_recon_queue_len() -> str:
    """Lua *expression* -> how many ghost-recon targets are queued."""
    return ("(function() return #(DataCenter.ActGhostreconManager.__lw_ghost_queue or {}) end)()")


def ghost_recon_steals_pending() -> str:
    """Lua *expression* -> presses `steal_ghost_recon` can still make.

    `min(queued, robberies left today)`, and 0 whenever the event is closed — the
    button's `count_lua`, so `xall` stops at the queue, at the cap, or at the end of
    the event, whichever comes first.
    """
    return ("(function() if %s==0 then return 0 end "
            "local q=%s local b=%s if q<b then return q end return b end)()"
            % (ghost_recon_is_open(), ghost_recon_queue_len(), ghost_recon_steals_left()))


def steal_next_ghost_recon() -> str:
    """Rob the first queued ghost-recon target (one press, one squad).

    The target is popped BEFORE the send, so a refused robbery costs one queue entry
    rather than wedging `xall` on the same doomed uuid. One press per chunk: the
    budget only moves when the server's reply lands.
    """
    return ("local M=DataCenter.ActGhostreconManager "
            "local q=M.__lw_ghost_queue or {} local t=table.remove(q,1) "
            "if t and %s > 0 and %s > 0 then "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.GhostReconSteal, "
            "t.uuid, t.server) end) "
            'CS.UnityEngine.Debug.LogError("ACT ghost_steal_sent uuid="..tostring(t.uuid)'
            '.." srv="..tostring(t.server)) end'
            % (ghost_recon_is_open(), ghost_recon_steals_left()))


# ---------------------------------------------------------------------------
# World-map treasures ("сокровища на карте") — dig march + claim.
# ---------------------------------------------------------------------------
# Reverse-engineered from a live capture (task #1107, docs/research/world-treasures.md).
# A treasure is a `world.get.block` / `push.world.point.update` tile with
# `WorldPointType.TREASURE == 21`; the alliance marches onto it to dig, and the
# finisher claims the reward. Two network moves, both taken verbatim from the trace
# and from the already-working attack / ghost-recon primitives:
#
#   * DIG  = MarchUtil.SendCreateMarchMessage(formation, MarchTargetType.DETECT_TREASURE,
#            pid, uuid, 1, 1, false, serverId, nil) — the SAME launch primitive as
#            attack/scout/collect (see attack.py / world-monsters.md Finding 17), only the
#            MarchTargetType changes: DETECT_TREASURE (50) same-server, CROSS_DETECT_TREASURE
#            (182) for a treasure on another server. Scheduled on the main thread via
#            TimerManager:DelayInvoke because a cold SendCreateMarchMessage from the hijack
#            thread is created but dropped by the server (attack.py).
#   * CLAIM = SFSNetwork.SendMessage(MsgDefines.DetectEventClaimTreasure, uuid, targetServer)
#            — the exact call the in-game "раскопать/забрать" finish fires (trace:
#            SFSObject PutLong "uuid" + PutInt "targetServer"). A pure network send, so it
#            needs no main-thread scheduling — identical shape to ghost-recon steal.
#
# NOT PROVEN LIVE YET: no treasure was on the map during the analysis
# (ActDetectTreasureDataManager.treasures_num == 0), so neither call has been fired
# end-to-end. The server gates both on the per-day dig/claim limit
# (ActDetectTreasureDataManager:CheckTreasureReachDailyLimit).

MARCH_DETECT_TREASURE = 50         # MarchTargetType.DETECT_TREASURE (same server)
MARCH_CROSS_DETECT_TREASURE = 182  # MarchTargetType.CROSS_DETECT_TREASURE (other server)


def dig_treasure_march(pid, uuid, server, formation, cross: bool = False) -> str:
    """Send a squad to dig the treasure at tile `pid` (uuid/server from its point data).

    `formation` is a squad formation UUID (as in attack.py / rally_join.py). `cross=True`
    uses MarchTargetType.CROSS_DETECT_TREASURE for a treasure sitting on another server;
    same-server digs use DETECT_TREASURE. All ids are passed as bare Lua numeric literals
    (Lua 5.3 int64), so a 19-digit uuid survives intact.
    """
    target = "CROSS_DETECT_TREASURE" if cross else "DETECT_TREASURE"
    return (
        'TimerManager:GetInstance():DelayInvoke(function() '
        'local ok,err=pcall(function() '
        'MarchUtil.SendCreateMarchMessage(%s, MarchTargetType.%s, %s, %s, 1, 1, false, %s, nil) '
        'end) '
        'CS.UnityEngine.Debug.LogError("ACT dig_treasure_sent ok="..tostring(ok).." err="..tostring(err)) '
        'end, 0.5) '
        'CS.UnityEngine.Debug.LogError("ACT dig_treasure_armed pid=%s target=%s")'
        % (formation, target, pid, uuid, server, pid, target)
    )


def claim_treasure(uuid, server) -> str:
    """Claim (take) a dug treasure by its `uuid` on `server` — the finisher's send.

    `SFSNetwork.SendMessage(MsgDefines.DetectEventClaimTreasure, uuid, targetServer)`,
    exactly what the in-game finish button fires; the message builder packs uuid->PutLong,
    server->PutInt. Headless, no window, no scheduling (pure network send).
    """
    return (
        'pcall(function() SFSNetwork.SendMessage(MsgDefines.DetectEventClaimTreasure, %s, %s) end) '
        'CS.UnityEngine.Debug.LogError("ACT claim_treasure_sent uuid=%s srv=%s")'
        % (uuid, server, uuid, server)
    )


# --- Treasure work queue (find -> dig-if-digging / claim-if-dug) -------------
# The recipe layer. Targets are parked OUTSIDE (a finder), exactly like ghost recon,
# because a DSL `TAP` takes no arguments. The finder fills a list on the VM:
#
#     DataCenter.__lw_treasure_queue = {
#       { pid=<tileIndex>, uuid=<long>, server=<int>,
#         dug=<bool>,       -- is it already dug? (wire point field 7 / operator uid present)
#         cross=<bool>,     -- treasure sits on another server? (server ~= home)
#         formation=<uuid>, -- squad to send to dig it (optional)
#       }, ...
#     }
#
# `dug` is the "копается vs раскопано" split proven from the capture
# (docs/research/world-treasures.md): while the treasure is still being dug the point
# carries NO operator uid (wire f11.7 absent); once fully dug that field is filled with
# the finisher's uid. The finder sets `dug` from that. `work_next_treasure` then does
# the right thing per target — dig it if still digging, claim it if dug.
#
# A shared default squad for the dig, when a queue entry has no `formation`:
#     DataCenter.__lw_treasure_formation = <formation uuid>


def treasure_queue_len() -> str:
    """Lua *expression* -> how many treasures are queued (0 when the finder found none)."""
    return "(function() return #(DataCenter.__lw_treasure_queue or {}) end)()"


def treasure_head_state() -> str:
    """Lua *expression* -> head target state: 1 dug (claim), 0 digging (dig), -1 empty."""
    return ("(function() local q=DataCenter.__lw_treasure_queue or {} local t=q[1] "
            "if not t then return -1 end return t.dug and 1 or 0 end)()")


def dig_head_treasure() -> str:
    """Pop the head treasure and send a squad to DIG it (still-being-dug target).

    The head is removed first (like `steal_next_ghost_recon`) so a refused march costs one
    queue entry rather than wedging `xall` on the same target — the finder re-adds it next
    scan while it is still digging. Scheduled on the main thread (a cold
    `SendCreateMarchMessage` from the hijack thread is created but dropped). Squad =
    `entry.formation`, else the shared `DataCenter.__lw_treasure_formation`; with neither it
    is popped and logged, not retried.
    """
    return (
        "local q=DataCenter.__lw_treasure_queue or {} local t=table.remove(q,1) "
        "if t then local fm=t.formation or DataCenter.__lw_treasure_formation "
        "if fm then TimerManager:GetInstance():DelayInvoke(function() "
        "pcall(function() MarchUtil.SendCreateMarchMessage(fm, "
        "t.cross and MarchTargetType.CROSS_DETECT_TREASURE or MarchTargetType.DETECT_TREASURE, "
        "t.pid, t.uuid, 1, 1, false, t.server, nil) end) "
        'CS.UnityEngine.Debug.LogError("ACT treasure_dig pid="..tostring(t.pid).." srv="..tostring(t.server)) '
        'end, 0.5) '
        'else CS.UnityEngine.Debug.LogError("ACT treasure_dig_skip no formation (set DataCenter.__lw_treasure_formation)") end '
        "end"
    )


def claim_head_treasure() -> str:
    """Pop the head treasure and CLAIM it (already-dug target) — the finisher's send.

    Direct network send (no scheduling needed), same shape as `steal_next_ghost_recon`.
    """
    return (
        "local q=DataCenter.__lw_treasure_queue or {} local t=table.remove(q,1) "
        "if t then pcall(function() SFSNetwork.SendMessage(MsgDefines.DetectEventClaimTreasure, t.uuid, t.server) end) "
        'CS.UnityEngine.Debug.LogError("ACT treasure_claim uuid="..tostring(t.uuid).." srv="..tostring(t.server)) end'
    )


def treasure_queue_dump() -> str:
    """Reader chunk: one `ACT TQ …` line per parked treasure, with its map position.

    `park_treasures` already logs what it parked, but only as it parks — a caller that
    wants to SHOW the queue (the panel's «Скрытые сокровища» list) needs to be able to
    re-read it, and needs the tile position a `pid` stands for. Fields: `i` the queue
    slot (1-based, what `dig_head_treasure`/`claim_head_treasure` spend in order), `pid`,
    `uuid`, `srv`, `dug` (already dug → claim, else dig) and `x`/`y` off
    `SceneUtils.IndexToTilePos`, the same conversion every other tile read uses.

    Emits nothing but the lines — reading the queue never changes it.
    """
    return (
        "local q=DataCenter.__lw_treasure_queue or {} "
        'CS.UnityEngine.Debug.LogError("ACT treasure_queue "..tostring(#q)) '
        "for i,t in ipairs(q) do "
        "local x,y=0,0 pcall(function() local tp=SceneUtils.IndexToTilePos(t.pid) "
        "x,y=tp.x,tp.y end) "
        'CS.UnityEngine.Debug.LogError("ACT TQ i="..tostring(i).." pid="..tostring(t.pid)'
        '.." uuid="..tostring(t.uuid).." srv="..tostring(t.server)'
        '.." dug="..tostring(t.dug and 1 or 0).." x="..tostring(x).." y="..tostring(y)) end'
    )


def treasure_formation_set(formation) -> str:
    """Park the squad `dig_head_treasure` should march with (`__lw_treasure_formation`).

    A queue entry may carry its own `formation`; this is the shared fallback, set once
    so a dig started from a list (the panel) does not have to rewrite every entry.

    `formation` goes in as a bare Lua literal, like every other uuid in this module —
    they are 19-digit numbers and Lua 5.3 integers hold them exactly.
    """
    return ("DataCenter.__lw_treasure_formation=%s "
            'CS.UnityEngine.Debug.LogError("ACT treasure_formation="..tostring('
            "DataCenter.__lw_treasure_formation))" % int(formation))


# --- The finder: is there a treasure right now? -----------------------------
# `DataCenter.ActDetectTreasureDataManager` is a pure reply cache, verified live via
# `string.dump` (task #1116): `GetArrData` only reads `self.dataDict[activityId]`, and
# only `OnGetArrDataMsg` ever writes it (it also sets `treasures_num`). So the client
# knows about a treasure exactly when a `activity.detect.list` reply has arrived —
# nothing polls on its own, and the dict stays empty for a whole session when the
# alliance's detect event dropped nothing.
#
# `treasure_refresh_request` re-asks the server (the message needs an activityId — sent
# with none it dies in the serializer: "bad argument #2 to 'pack'"). The ids to ask for
# are the manager's own `dailyGot` keys, which are the treasure cfg groups the account
# tracks a per-day count for.


def treasure_refresh_request(activity_ids) -> str:
    """Ask the server to (re-)send the detect-treasure list for each activity id.

    Fire-and-forget: the reply lands in `OnGetArrDataMsg`, so read the manager back a
    couple of seconds later (`treasure_state`).
    """
    ids = ",".join(str(int(i)) for i in activity_ids)
    return (
        "for _,id in ipairs({%s}) do "
        "local ok,err=pcall(function() SFSNetwork.SendMessage(MsgDefines.ActivityDetectList, id) end) "
        'CS.UnityEngine.Debug.LogError("ACT treasure_ask id="..tostring(id).." ok="..tostring(ok).." err="..tostring(err)) '
        "end" % ids
    )


def treasure_state() -> str:
    """Log the manager's treasure state — the "is there anything to dig?" read.

    Emits, all prefixed `ACT`:
      * `treasures_num=<n>`      — the count from the last list reply
      * `treasure_daily <cfgId>=<n>` — per-group takes already used today
      * `treasure_rec ...`       — one line per record found in `dataDict`, as raw
        `key=value` pairs
    The record lines are dumped raw on purpose: no treasure has ever been in the dict
    while looking (it was empty in both the #1107 RE and the #1116 check), so the exact
    field names are unconfirmed — the first live treasure prints its own shape here.
    """
    return (
        "local m=DataCenter.ActDetectTreasureDataManager "
        'CS.UnityEngine.Debug.LogError("ACT treasures_num="..tostring(m and m.treasures_num)) '
        "if m then "
        "for k,v in pairs(m.dailyGot or {}) do "
        'CS.UnityEngine.Debug.LogError("ACT treasure_daily "..tostring(k).."="..tostring(v)) end '
        "local function dump(t,depth,path) "
        "local flat,nested={},{} "
        "for k,v in pairs(t) do if type(v)=='table' then nested[#nested+1]={k,v} "
        "elseif type(v)~='function' then flat[#flat+1]=tostring(k)..'='..tostring(v) end end "
        "if #flat>0 then CS.UnityEngine.Debug.LogError('ACT treasure_rec '..path..' '..table.concat(flat,' ')) end "
        "if depth<3 then for _,kv in ipairs(nested) do dump(kv[2],depth+1,path..'.'..tostring(kv[1])) end end "
        "end "
        "local n=0 for k,v in pairs(m.dataDict or {}) do n=n+1 "
        "if type(v)=='table' then dump(v,1,tostring(k)) end end "
        'CS.UnityEngine.Debug.LogError("ACT treasure_dict_count="..tostring(n)) '
        "end"
    )


def park_treasures(home_server: int = 0) -> str:
    """Fill `DataCenter.__lw_treasure_queue` from the manager, for `work_treasure.md`.

    Walks `dataDict` for records carrying a point id and a uuid, and parks one queue
    entry each: `{pid, uuid, server, dug, cross}`. `dug` comes from the operator-uid
    field (present once the tile is fully dug — the split proven on the wire in
    docs/research/world-treasures.md); `cross` from the treasure's server differing
    from `home_server`. Field names are probed against several spellings because the
    record shape has never been seen populated — see `treasure_state`.

    Logs `ACT treasure_parked <n>` and one `ACT treasure_target ...` line per entry.
    """
    return (
        "local m=DataCenter.ActDetectTreasureDataManager local q={} "
        "local function pick(t,...) for _,k in ipairs({...}) do local v=t[k] "
        "if v~=nil and v~='' and v~=0 then return v end end return nil end "
        "local function take(rec) "
        "local pid=pick(rec,'pointId','point_id','pid','index','tileIndex') "
        "local uuid=pick(rec,'uuid','treasureUuid','treasure_uuid','id') "
        "if not pid or not uuid then return end "
        "local srv=pick(rec,'targetServer','serverId','srcServer','server') or %d "
        "local op=pick(rec,'operatorUid','operator','operatorId','uid','userId') "
        "q[#q+1]={pid=pid,uuid=uuid,server=srv,dug=(op~=nil),cross=(tonumber(srv)~=%d)} "
        "CS.UnityEngine.Debug.LogError('ACT treasure_target pid='..tostring(pid)..' uuid='..tostring(uuid)"
        "..' srv='..tostring(srv)..' dug='..tostring(op~=nil)) end "
        "local function walk(t,depth) "
        "local isrec=false for _,k in ipairs({'pointId','point_id','pid','uuid'}) do "
        "if t[k]~=nil then isrec=true end end "
        "if isrec then take(t) return end "
        "if depth<3 then for _,v in pairs(t) do if type(v)=='table' then walk(v,depth+1) end end end end "
        "if m then for _,v in pairs(m.dataDict or {}) do if type(v)=='table' then walk(v,1) end end end "
        "DataCenter.__lw_treasure_queue=q "
        "CS.UnityEngine.Debug.LogError('ACT treasure_parked '..tostring(#q))"
        % (int(home_server), int(home_server))
    )


# --- The watcher: every treasure message the client sees, kept until read ---
# What it is for. A treasure is a RACE and a rarity at once — the chest is out for
# minutes, the alliance digs it together, and the whole exchange is over before anybody
# can start a sniffer. So the messages have to be caught by something that was already
# listening, and kept until a person gets round to reading them. That is this: a hook on
# the client's own two network doors, writing into a ring buffer that lives in the game
# VM, drained by whoever asks.
#
# WHY THE BUFFER IS IN THE GAME AND NOT IN THE PANEL. The panel is restarted, switched
# profiles, minimised and closed; the client is not. A buffer on the panel's side loses
# exactly the messages that arrive while nobody is looking, which is every message worth
# having. In the VM it survives a panel restart and costs a table.
#
# WHAT IT HOOKS. `SFSNetwork.SendMessage(cmd, ...)` and `SFSNetwork.HandleMessage(cmd,
# obj, ...)` — both plain dot-functions taking the command name first, confirmed in the
# 2026-08-07 «сбор сокровища» trace where every send and every push goes through them
# (docs/research/world-treasures.md). Hooking the pair catches the whole ability without
# knowing which manager fires it: the dig march goes out through `MarchUtil.
# SendCreateMarchMessage`, which itself calls `SFSNetwork.SendMessage`.
#
# NOT AT THE SAME TIME AS THE TRACER. `lua_trace` wraps ~6500 functions including these
# two. Running both means each unwraps the other's wrapper on the way out, and the loser
# is whichever restored last. Record with ONE of them.
#
# THE FILTER, and why it is names rather than a manager. `wide` off keeps anything whose
# command carries `treasure` or `detect`, plus a `world.march.*` SEND whose target type
# is a treasure march (50 same-server / 182 cross-server). That is the three things a
# person watching wants — the chest appearing, the squad going out, the chest being
# taken — and nothing else. `wide` on keeps every message the client sends or handles,
# for the session where the question is «what did I miss».

#: How many messages the ring holds before the oldest is dropped. Each entry is a
#: command name and a flattened field list, so a few hundred is kilobytes.
TREASURE_WATCH_CAP = 400

#: Target types of a march that is digging a treasure (`MarchTargetType`), the two the
#: filter lets through from `world.march.*`: same server, and cross-server.
TREASURE_MARCH_TARGETS = (50, 182)

# The shared helpers the install chunk defines as locals and the closures capture. Kept
# as one string so the install is readable; `W` is the buffer table, looked up fresh so
# a re-install with a different `wide`/`cap` takes effect without re-wrapping.
_WATCH_HELPERS = r"""
local W = DataCenter.__lw_treasure_watch
local function nowms() local ms=0
  pcall(function() ms=UITimeManager.Instance:GetServerTime() end)
  ms = math.floor(tonumber(ms) or 0)
  if ms <= 0 then ms = (tonumber(ChatInterface.getServerTime()) or 0) * 1000 end
  return ms end
local function short(v)
  local s = tostring(v)
  if #s > 160 then s = s:sub(1,160) .. "..." end
  return s end
local function keep(dir, cmd, a1, a2)
  if not W.on then return false end
  if type(cmd) ~= "string" then return false end
  if W.wide then return true end
  if cmd:find("treasure", 1, true) or cmd:find("detect", 1, true) then return true end
  if dir == "out" and cmd:find("world.march.", 1, true) then
    for _, want in ipairs(W.marches or {}) do
      if tonumber(a1) == want or tonumber(a2) == want then return true end
    end
  end
  return false end
-- READ A MESSAGE BODY WHICHEVER SHAPE IT IS. An outgoing message is an SFSObject and
-- answers `SFSObject.GetKeys`; an INCOMING one, by the time `HandleMessage` gets it, is
-- a plain Lua table and answers nothing at all — `GetKeys` returns empty, so every push
-- the ring recorded came out with `f=""` and the harvest below could never read a uuid.
-- Found live on 2026-08-08 with a probe on a real `push.detect.treasure.claim`:
-- `KEYS[] PAIRS[operator=table uuid=…]` (#1296). So both are tried, SFSObject first.
local function getdata(obj, k)
  local v
  local ok = pcall(function() v = SFSObject.GetData(obj, k) end)
  if ok and v ~= nil then return v end
  ok = pcall(function() v = obj[k] end)
  if ok then return v end
  return nil end
local function fields(obj)
  local out = {}
  local keys = nil
  pcall(function()
    local ks = SFSObject.GetKeys(obj)
    if ks ~= nil and #ks > 0 then keys = ks end
  end)
  if keys ~= nil then
    for i, k in ipairs(keys) do
      if i > 24 then break end
      local v = getdata(obj, k)
      if type(v) == "table" then v = "{...}" end
      out[#out+1] = tostring(k) .. "=" .. short(v)
    end
  else
    pcall(function()
      local seen = 0
      for k, v in pairs(obj) do
        seen = seen + 1
        if seen > 24 then break end
        if type(v) == "table" then v = "{...}" end
        out[#out+1] = tostring(k) .. "=" .. short(v)
      end
    end)
  end
  return table.concat(out, " ") end
local function args(...)
  local out = {}
  local n = select("#", ...)
  if n > 8 then n = 8 end
  for i = 1, n do
    local v = select(i, ...)
    if type(v) == "table" then v = "{...}" end
    out[#out+1] = "a" .. i .. "=" .. short(v)
  end
  return table.concat(out, " ") end
local function push(dir, cmd, info)
  W.seq = (W.seq or 0) + 1
  W.items[#W.items+1] = {i=W.seq, t=nowms(), d=dir, c=tostring(cmd), f=info}
  while #W.items > (W.cap or 400) do
    table.remove(W.items, 1)
    W.drop = (W.drop or 0) + 1
  end end
local function jint(s, k)
  return tonumber(s:match('"' .. k .. '"%s*:%s*(%-?%d+)')) end
local function harvest(cmd, obj)
  local A = DataCenter.__lw_treasure_auto
  if not A or not A.on then return end
  if type(cmd) ~= "string" then return end
  if not cmd:find("treasure", 1, true) then return end
  -- A REFUSED CLAIM IS NOT SILENT AFTER ALL (#1296, caught on a live map). The reply to
  -- `detect.event.claim.treasure` comes back under the same name, and when the server
  -- says no it carries `errorCode` and `errorMsg` — the first one seen was
  -- `801354 player not in same alliance`. It names no chest, so it cannot be pinned on a
  -- target; what it CAN do is turn «nothing happened» into the server's own sentence, so
  -- the run says why instead of retrying four times into the dark.
  if cmd == "detect.event.claim.treasure" then
    local code = getdata(obj, "errorCode")
    if code ~= nil and tostring(code) ~= "0" then
      A.last_error = tostring(code) .. " " .. tostring(getdata(obj, "errorMsg") or "")
      A.last_error_at = nowms()
      -- …AND IT IS PINNED ON A CHEST AFTER ALL (#1318). The reply names none, which is why
      -- this used to be a floating sentence in a log — but the claim that provoked it has a
      -- name, and the watch writes down which chest it claimed last (`A.claim_uuid`). That
      -- is enough for the two codes that are verdicts: «claim repeat» is a chest this
      -- account already has, and «not in same alliance» is one it never had. Both end a
      -- retry loop that would otherwise run until the chest expired.
      --
      -- Only while the claim is FRESH: a code arriving a minute later belongs to whatever
      -- was claimed since, and pinning it on the wrong chest would write off a good one.
      local key = A.claim_uuid
      if key ~= nil and (tonumber(A.claim_at) or 0) > 0
         and nowms() - A.claim_at < 15000 then
        for _, t in ipairs(A.targets or {}) do
          if tostring(t.uuid) == tostring(key) then t.err = tonumber(code) end
        end
      end
    end
  end
  if cmd:find("claim", 1, true) then
    -- The alliance's own feed of the dig: one of these per member who has finished
    -- their part. It is NOT «somebody else took it» — every digger claims their own
    -- gift — so it is read as «this chest is dug and payable», never as a loss.
    local u = getdata(obj, "uuid")
    if u == nil then return end
    local key = tostring(u)
    local known = false
    for _, t in ipairs(A.targets or {}) do
      if tostring(t.uuid) == key then known = true
        if not t.dug then t.dug = nowms() end end
    end
    -- A CHEST NOBODY SHARED IS STILL A CHEST (#1296, learned on the first live one).
    -- The alliance dug a treasure for twenty minutes and not one `world.treasure.share.
    -- chat` crossed the wire — the share is a thing a PLAYER does, and often nobody
    -- does it. This broadcast, on the other hand, arrives once per member who finishes,
    -- and it carries the two things a CLAIM needs: the uuid and (from us) the server.
    -- It cannot carry a march — there is no tile in it — so the target is parked
    -- `claim_only`, and the step claims it without ever pretending a squad was sent.
    -- That is exactly the path that took a live chest on 2026-08-08 by hand.
    A.seen = A.seen or {}
    if not known and not A.seen[key] then
      A.seen[key] = nowms()
      A.targets = A.targets or {}
      A.targets[#A.targets+1] = {uuid = u, pid = 0, x = 0, y = 0, server = 0,
                                 at = nowms(), dug = nowms(), claim_only = true,
                                 src = "dig-feed"}
      A.news = (A.news or 0) + 1
    end
    return
  end
  -- The announcement. A chest shared into alliance chat travels as an ordinary chat
  -- post whose `attachmentId` is a JSON blob; which key it arrives under is not
  -- guaranteed, so every string field is looked at and the one that carries a
  -- `shareType` with a `uuid` wins. Nothing else in the message is read.
  local blob
  local function look(v)
    if type(v) == "string" and v:find("shareType", 1, true)
       and v:find("uuid", 1, true) then blob = v end end
  local keys = nil
  pcall(function()
    local ks = SFSObject.GetKeys(obj)
    if ks ~= nil and #ks > 0 then keys = ks end end)
  if keys ~= nil then
    for _, k in ipairs(keys) do look(getdata(obj, k)) end
  else
    pcall(function() for _, v in pairs(obj) do look(v) end end)
  end
  if blob == nil then return end
  local uuid, x, y = jint(blob, "uuid"), jint(blob, "x"), jint(blob, "y")
  if uuid == nil or x == nil or y == nil then return end
  local key = tostring(uuid)
  A.seen = A.seen or {}
  if A.seen[key] then return end
  A.seen[key] = nowms()
  local pid = 0
  pcall(function()
    pid = SceneUtils.TilePosToIndex(CS.UnityEngine.Vector2Int(x, y)) end)
  local sid = jint(blob, "sid")
  A.targets = A.targets or {}
  A.targets[#A.targets+1] = {uuid=uuid, pid=pid, x=x, y=y,
                             server=sid or 0, at=nowms(), src="chat"}
  A.news = (A.news or 0) + 1
end
"""


def treasure_watch_install(cap: int = TREASURE_WATCH_CAP) -> str:
    """Start (or re-arm) the watcher, and say what it is now — `ACT treasure_watch …`.

    Idempotent by construction: the two doors are wrapped once and the wrappers read
    `W.wide` / `W.cap` out of the buffer table on every call, so pressing this again
    with a different `DataCenter.__lw_treasure_watch_wide` changes what is kept without
    a second layer of wrapping. Nothing already in the ring is thrown away.

    The whole hook body is inside `pcall`, and a hook that throws must never break the
    client's networking: the original is called outside the guard, so a bug here costs
    a missing log line and not a dropped message.

    TWO CONSUMERS SHARE THE ONE HOOK (#1296). The ring buffer above is the debug page's;
    the auto-treasure errand needs the same two doors to hear a chest being announced,
    and a SECOND pair of wrappers on the same functions is how an unwrap loses a hook.
    So `harvest` runs from the same wrapper, gated on its own switch
    (`DataCenter.__lw_treasure_auto.on`) rather than on `W.on` — the auto errand listens
    with the ring off, and the ring records with the auto errand off.
    """
    return (
        "local D = DataCenter "
        "if not D.__lw_treasure_watch then D.__lw_treasure_watch = "
        "{seq=0, drop=0, items={}, on=false} end "
        "D.__lw_treasure_watch.cap = " + str(int(cap)) + " "
        "D.__lw_treasure_watch.wide = D.__lw_treasure_watch_wide and true or false "
        "D.__lw_treasure_watch.marches = {"
        + ",".join(str(int(t)) for t in TREASURE_MARCH_TARGETS) + "} "
        + _WATCH_HELPERS +
        "if not W.hooked then "
        "W.origSend = SFSNetwork.SendMessage "
        "W.origRecv = SFSNetwork.HandleMessage "
        "SFSNetwork.SendMessage = function(cmd, ...) "
        "local okk, want = pcall(keep, 'out', cmd, (select(1, ...)), (select(2, ...))) "
        "if okk and want then local oka, info = pcall(args, ...) "
        "if oka then pcall(push, 'out', cmd, info) end end "
        "return W.origSend(cmd, ...) end "
        "SFSNetwork.HandleMessage = function(cmd, obj, ...) "
        "local okk, want = pcall(keep, 'in', cmd, nil) "
        "if okk and want then local okf, info = pcall(fields, obj) "
        "if okf then pcall(push, 'in', cmd, info) end end "
        "pcall(harvest, cmd, obj) "
        "return W.origRecv(cmd, obj, ...) end "
        "W.hooked = true end "
        "W.on = true "
        'CS.UnityEngine.Debug.LogError("ACT treasure_watch on=1 wide="'
        '..tostring(W.wide and 1 or 0).." cap="..tostring(W.cap)'
        '.." buf="..tostring(#W.items))'
    )


def treasure_watch_stop() -> str:
    """Stop keeping messages, and put the client's two doors back as they were.

    The wrappers are removed rather than left recording into a buffer nobody drains: a
    hook that stays on is a hook the next person has to remember about, and the tracer
    would then wrap a wrapper. What is already in the ring survives — stopping is not
    the same as throwing away, and the last thing recorded is usually the interesting
    one.

    THE DOORS ARE ONLY PUT BACK WHEN NOBODY ELSE IS LISTENING (#1296). The auto-treasure
    errand hears a chest through this same pair of wrappers, so unhooking while its
    switch is on would leave it deaf with nothing on screen to say so. Then the ring is
    merely muted (`on = false`) and the reply says `hooked=1`, which is the honest
    answer: the recording stopped, the hook did not.
    """
    return (
        "local W = DataCenter.__lw_treasure_watch "
        "local A = DataCenter.__lw_treasure_auto "
        "local auto = (A ~= nil and A.on) and true or false "
        "if W then W.on = false "
        "if W.hooked and not auto then "
        "if W.origSend then SFSNetwork.SendMessage = W.origSend end "
        "if W.origRecv then SFSNetwork.HandleMessage = W.origRecv end "
        "W.hooked = false end end "
        'CS.UnityEngine.Debug.LogError("ACT treasure_watch on=0 hooked="'
        "..tostring(((W or {}).hooked) and 1 or 0)"
        '.." auto="..tostring(auto and 1 or 0)'
        '.." buf="..tostring(#((W or {}).items or {})))'
    )


def treasure_watch_drain(limit: int = 25, budget: int = 6000) -> str:
    """Lua *expression* -> a JSON object of the oldest messages, REMOVING them.

    Shaped for `READ_LUA … INTO feed`: one value, one line, no newline in it. The reader
    gets ``{"on":0|1,"wide":0|1,"n":<taken>,"more":<still queued>,"drop":<dropped since
    the last drain>,"seq":<total ever>,"items":[{"i","t","d","c","f"}…]}`` — `t` is the
    GAME's clock in milliseconds (`docs/research/game-clock.md`; the PC's lies), `d` is
    `in`/`out`, `c` the command and `f` its fields flattened to `k=v` pairs.

    TWO CAPS, because the answer travels as one log line. `limit` is how many entries at
    most, `budget` how many characters at most — whichever is reached first stops the
    drain and the rest is reported as `more`, so a caller loops until `more` is zero
    instead of losing the tail to a truncated line. `drop` is reported once and cleared:
    it is the ring's own confession that it overflowed, and it must not be counted twice.
    """
    return (
        "(function() "
        "local W = DataCenter.__lw_treasure_watch "
        'if not W then return \'{"on":0,"wide":0,"n":0,"more":0,"drop":0,"seq":0,"items":[]}\' end '
        "local function q(s) s = tostring(s or '') "
        "if #s > 400 then s = s:sub(1,400) .. '...' end "
        "s = s:gsub('\\\\', '\\\\\\\\'):gsub('\"', '\\\\\"'):gsub('%c', ' ') "
        "return '\"' .. s .. '\"' end "
        "local items = W.items or {} "
        "local parts, used = {}, 0 "
        "while #parts < " + str(int(limit)) + " and #items > 0 and used < "
        + str(int(budget)) + " do "
        "local it = table.remove(items, 1) "
        "local one = '{\"i\":' .. tostring(it.i or 0) .. ',\"t\":' .. tostring(it.t or 0) "
        ".. ',\"d\":' .. q(it.d) .. ',\"c\":' .. q(it.c) .. ',\"f\":' .. q(it.f) .. '}' "
        "used = used + #one "
        "parts[#parts+1] = one end "
        "local drop = W.drop or 0 W.drop = 0 "
        "return '{\"on\":' .. tostring(W.on and 1 or 0) "
        ".. ',\"wide\":' .. tostring(W.wide and 1 or 0) "
        ".. ',\"n\":' .. tostring(#parts) "
        ".. ',\"more\":' .. tostring(#items) "
        ".. ',\"drop\":' .. tostring(drop) "
        ".. ',\"seq\":' .. tostring(W.seq or 0) "
        ".. ',\"items\":[' .. table.concat(parts, ',') .. ']}' "
        "end)()"
    )


def treasure_watch_state() -> str:
    """Lua *expression* -> `on=<0|1> wide=<0|1> buf=<n> seq=<n> drop=<n> cap=<n>`.

    A look that changes nothing — what the drain would say, without spending the ring.
    Used to answer «is it listening?» after a client restart, which wipes the buffer
    along with the rest of the VM and is the one thing a person cannot tell by waiting.
    """
    return (
        "(function() local W = DataCenter.__lw_treasure_watch "
        "if not W then return 'on=0 wide=0 buf=0 seq=0 drop=0 cap=0' end "
        "return 'on=' .. tostring(W.on and 1 or 0) "
        ".. ' wide=' .. tostring(W.wide and 1 or 0) "
        ".. ' buf=' .. tostring(#(W.items or {})) "
        ".. ' seq=' .. tostring(W.seq or 0) "
        ".. ' drop=' .. tostring(W.drop or 0) "
        ".. ' cap=' .. tostring(W.cap or 0) end)()"
    )


# --- The auto errand: a chest announced -> a squad out -> the gift taken ------
# The three moments of the ability, driven by the client's own announcement instead of
# by a sweep of the map (#1296, docs/research/world-treasures.md).
#
# WHY IT IS NOT A MAP SWEEP. A chest is out for minutes and the alliance digs it
# together; a poll of the world would have to re-ask the map every few seconds to catch
# one, which costs a `world.get.block` round trip per look and still arrives late. The
# client is already told the moment a chest is shared into alliance chat — the trace of
# 2026-08-08 has the whole exchange in four messages — so the ear goes where the news
# already lands: the hook above, and a Lua table the errand reads. The «poll» this ships
# with reads that LOCAL table, one expression through the daemon, and never touches the
# network.
#
# WHY IT CANNOT BE A WIRE TRIGGER. The announcement is a chat post, and the chat
# broadcast rides a TLS websocket this repository cannot sniff
# (`docs/research/chat-system.md`): the 2026-08-08 capture has the message in the Lua
# trace and NOT on the wire beside it. So `panel/triggers.py`'s ordinary wire listener
# is deaf to it by construction, and the poll is not a shortcut — it is the only door.
#
# THE STATE, all of it in the game VM so a panel restart loses nothing:
#
#     DataCenter.__lw_treasure_auto = {
#       on      = true,                 -- the harvest switch (see treasure_watch_install)
#       seen    = { ["<uuid>"] = <ms> },-- announcements already turned into a target
#       news    = <n>,                  -- how many the hook has added, ever
#       targets = { { uuid, pid, x, y, server, at,   -- the announcement
#                     sent, squad,                  -- the march that went out
#                     dug,                          -- push.detect.treasure.claim seen
#                     claimed, done, why } },
#     }
#
# Each target walks new -> sent -> (dug) -> claimed -> done, and every step is written
# down where the next run can read it, because a run may be interrupted at any point:
# the errand is idempotent by state, not by luck.

#: How long after the march goes out the claim may be tried even though no
#: `push.detect.treasure.claim` was heard for that chest. The push is the honest gate
#: and this is the fallback: the alliance's feed may have arrived while the client was
#: reconnecting, and a chest that is dug and never claimed is the whole reward lost.
TREASURE_ARRIVE_GRACE_SEC = 240

#: How long a target is worked before it is written off. A chest that is neither claimed
#: nor dug by then is gone from the map — the point expires — and keeping it would mean
#: sending squads at an empty tile for ever.
TREASURE_TARGET_TTL_SEC = 1800

#: How long between two claims on the same chest, in milliseconds, by try number — and
#: there is no longer a cap on the tries (#1318). «Продолжать попытки, пока сокровище не
#: будет взято или не исчезнет»: the four-try cap wrote a chest off while it was still on
#: the map, which is the whole reward lost for a reason that mends itself in seconds. So a
#: chest is now worked until it is PAID (the reward window, or the server's own «claim
#: repeat») or until it is gone (its own `expireTime`, or the ttl), and the ramp is what
#: keeps that from being a flood: the first retries are fast because the interesting case
#: is a claim that raced the server by a fraction of a second, and the tail is slow because
#: a chest that has refused eight times is refusing for a reason a ninth send will not fix.
TREASURE_CLAIM_RAMP_MS = (500, 1000, 2000, 4000, 8000, 15000)

#: How long between two claims on the same chest once the ramp above is spent.
TREASURE_CLAIM_RETRY_SEC = 15

#: How long after a claim the reward window still counts as ITS reward. A refused claim
#: says nothing at all — measured live on 2026-08-08 against a uuid that cannot exist: no
#: message tip, no window, no error, and the reply comes back under the same command name
#: with no readable fields. So «did it pay?» has exactly one observable answer, the
#: `UIGiftPackageRewardGet` the client raises on a successful claim, and it is only read
#: as ours while it is this fresh — any window later than that could be any other reward.
TREASURE_PAID_WINDOW_SEC = 20

#: How long a march is given to APPEAR before its absence is believed. A squad whose
#: march the server has not confirmed yet still reads free — measured live on 2026-08-08:
#: the send went out at 21:01:50, the report five seconds later said `free=3 busy=0`, and
#: `GetOwnerFormationMarch` answered nil for a march that was on its way. So «no march» in
#: the first seconds after a send means «not answered yet», never «over», and a claim let
#: through by that reading is refused in the silence a refusal comes in. Twenty seconds is
#: comfortably longer than a server ever took to answer here, and shorter than the retry —
#: so it costs a chest nothing.
TREASURE_MARCH_SETTLE_SEC = 20

#: …and what that silence means once it has lasted (#1318). A march that never appears is
#: not a march that is over — it is a send the client DROPPED, which it does without a word
#: for a formation already committed (`docs/research/world-treasures.md`). Before this, the
#: settle above turned exactly that case into «the squad has been and come back», and the
#: claim went out into a road nobody had walked: «отправка отряда работает через раз» is
#: this, seen from the player's chair. So a send with no march behind it is re-sent instead,
#: and a chest that has swallowed this many sends is written off with a word that says so.
TREASURE_RESEND_TRIES = 3

#: `MarchStatus.TREASURE_DIGGING` (`docs/research/squad-state.md`). A march in this state
#: carries the dig's OWN deadline in `endTime` — the moment the chest finishes being dug —
#: which is the whole of the timing this errand is built on: the claim is scheduled AT that
#: millisecond rather than discovered by a panel that happens to look afterwards.
TREASURE_DIG_STATUS = 19

#: `MarchStatus.BACK_HOME` — the squad's dig is over and it is walking home. The fallback
#: reading of «our part is done» for a client that never showed the digging state.
TREASURE_HOME_STATUS = 4

#: How early a known dig deadline is pinned with a one-shot of the game's own timer, in
#: milliseconds. The watch below already runs every fifth of a second while a chest is
#: live; this is what turns «within 200 ms» into «in the frame the dig ends», and it is
#: only armed for a deadline that is actually near, so a chest an hour out costs nothing.
TREASURE_DUE_ARM_MS = 5000

#: The server's own answers to a claim, and both are VERDICTS rather than noise (#1318).
#: `801348 claim repeat` means this account has already had this chest — which is a paid
#: chest seen from the other side, and the one honest end to a retry loop when the reward
#: window was missed. `801354 player not in same alliance` means the chest was never ours
#: to take. Either way the target is finished; anything else is a refusal worth retrying.
TREASURE_ERR_CLAIM_REPEAT = 801348
TREASURE_ERR_NOT_IN_ALLIANCE = 801354

#: How often the in-game watch looks while a chest is live, and while none is, in seconds.
#: The busy period is what the acceptance criterion rests on — «ВСЕ сокровища всегда забраны
#: в первую секунду» — and it costs one `GetOwnerFormationMarch` per chest out.
TREASURE_REAP_FAST_SEC = 0.2
TREASURE_REAP_IDLE_SEC = 2.0

#: How long the watch keeps looping with nothing to work before it stops itself. It is a
#: self-rescheduling timer inside somebody's game client, so it must have an end: the
#: panel's own poll re-arms it on the next tick, and a panel that has been closed leaves
#: nothing running a quarter of an hour later.
TREASURE_REAP_STOP_SEC = 900

#: `WorldPointType.TREASURE` — the same number the wire calls `f2` and the pcap scanner
#: filters on (docs/research/world-treasures.md).
TREASURE_POINT_TYPE = 21

#: The box the watch reads around the camera, and how often — the SECOND ear (#1318).
#: Half the width of the press the panel makes (`TREASURE_LOOK_BOX`) because this one runs
#: inside the game between panel ticks: 41 × 41 tiles is about four milliseconds, against
#: the thirty-odd of the full one. It never moves the camera and never asks the server.
TREASURE_REAP_LOOK_BOX = 20
TREASURE_REAP_LOOK_SEC = 3


def treasure_auto_arm(squads=(1, 2, 3, 4),
                      grace_sec: int = TREASURE_ARRIVE_GRACE_SEC,
                      ttl_sec: int = TREASURE_TARGET_TTL_SEC) -> str:
    """Switch the harvest on and park what the errand is allowed to spend.

    `squads` is which squad slots may be sent, in the order they may be spent — the
    1/2/3/4 the player sees in the dispatch panel, same meaning as the rally's.

    Idempotent, and deliberately does NOT clear the targets: an arm is what a restarted
    panel does on its first tick, and throwing the queue away there would lose a chest
    that was announced while nothing was watching.
    """
    slots = ",".join(str(int(s)) for s in squads) or "1,2,3,4"
    return (
        "local D = DataCenter "
        "if not D.__lw_treasure_auto then D.__lw_treasure_auto = "
        "{seen={}, targets={}, news=0} end "
        "local A = D.__lw_treasure_auto "
        "A.on = true "
        "A.squads = {" + slots + "} "
        "A.grace = " + str(int(grace_sec)) + " "
        "A.ttl = " + str(int(ttl_sec)) + " "
        'CS.UnityEngine.Debug.LogError("ACT treasure_auto on=1 squads="'
        '..tostring(#A.squads).." queued="..tostring(#(A.targets or {}))'
        '.." news="..tostring(A.news or 0))'
    )


def treasure_auto_arm_parked() -> str:
    """The same arm, reading its settings out of what the recipe parked first.

    A `TAP` carries no arguments (`docs/dsl.md`), so the values a recipe was given travel
    the way the rally's squads travel: parked on the VM ahead of the press and read here.

      * `DataCenter.__lw_treasure_squads` — the slots that may be spent, a Lua list;
      * `DataCenter.__lw_treasure_grace`  — seconds after the march before a claim may be
                                            tried without having heard the dig;
      * `DataCenter.__lw_treasure_ttl`    — seconds a chest is worked before it is written
                                            off as gone from the map.

    Each falls back to the built-in default when nothing was parked, so the button is
    pressable on its own from the Scenarios page.
    """
    return (
        # The claim half is parked here, on every arm — the definition IS the deployment
        # (#1318). A client running since before an edit to this file would otherwise go on
        # claiming by last week's rules with nothing on screen to say so.
        _TREASURE_TICK +
        "local D = DataCenter "
        "if not D.__lw_treasure_auto then D.__lw_treasure_auto = "
        "{seen={}, targets={}, news=0} end "
        "local A = D.__lw_treasure_auto "
        "A.on = true "
        "local s = D.__lw_treasure_squads "
        "if type(s) ~= 'table' or #s == 0 then s = {1,2,3,4} end "
        "A.squads = s "
        "A.grace = tonumber(D.__lw_treasure_grace) or "
        + str(int(TREASURE_ARRIVE_GRACE_SEC)) + " "
        "A.ttl = tonumber(D.__lw_treasure_ttl) or "
        + str(int(TREASURE_TARGET_TTL_SEC)) + " "
        'CS.UnityEngine.Debug.LogError("ACT treasure_auto on=1 squads="'
        '..tostring(#A.squads).." grace="..tostring(A.grace)'
        '.." queued="..tostring(#(A.targets or {}))'
        '.." news="..tostring(A.news or 0))'
    )


def treasure_auto_disarm() -> str:
    """Switch the harvest off; the queue and the hook are left as they are.

    Off means «stop turning announcements into targets», not «forget what you know»: a
    target already halfway through — a squad out, the gift not taken — is still worth
    finishing by hand, and the debug page can still read the queue.
    """
    return (
        "local A = DataCenter.__lw_treasure_auto "
        "if A then A.on = false end "
        'CS.UnityEngine.Debug.LogError("ACT treasure_auto on=0 queued="'
        "..tostring(#((A or {}).targets or {})))"
    )


def treasure_auto_check() -> str:
    """Lua *expression* -> true when the auto errand has something to do right now.

    What the poll trigger asks every few seconds. It reads LOCAL state only — no send,
    no map, no window — so the cost is one daemon round trip (~0.15 s with the daemon
    free) and nothing the game can notice.

    True in three cases, and only the first is the obvious one:

      * **an unfinished target** — a chest is queued and its next step is owed;
      * **no ear at all** — a client restart wipes the VM and with it the hook, and a
        poll that only ever asked about targets would then wait for ever for a chest it
        could not hear. So «nobody is listening» is itself work, and the errand's first
        step is to arm;
      * **the client is in the WORLD** (#1296). The third door is not an ear: nothing
        tells the client about a chest that is merely lying there, so somebody has to
        look — and since the whole-server lap was deleted, looking means reading the box
        the camera is already in, which costs a hundredth of a second and moves nothing.
        So «we are on the map» is reason enough to run, every tick, and in the city this
        clause is false and the errand stays quiet.
    """
    return (
        "(function() "
        "local D = DataCenter "
        "local W = D.__lw_treasure_watch "
        "local A = D.__lw_treasure_auto "
        "if A == nil or not A.on then return true end "
        "if W == nil or not W.hooked then return true end "
        "for _, t in ipairs(A.targets or {}) do if not t.done then return true end end "
        # ON THE MAP IS REASON ENOUGH. There is no period to compare against any more:
        # the look reads one box of the point manager and moves nothing, so the only
        # question left is whether there is anything to look AT — and in the city the
        # point manager is not there to read.
        "local world = false "
        "pcall(function() world = SceneUtils.GetIsInWorld() and true or false end) "
        "if world then return true end "
        "return false end)()"
    )


#: The claim half of the errand, as ONE Lua function parked on the VM (#1318).
#:
#: WHY IT IS A FUNCTION AND NOT A CHUNK. Everything else in this file is a chunk the panel
#: sends when it wants something done, which means it happens when the PANEL looks — and
#: the panel looks every ten seconds, with a twenty-second cooldown behind it. Measured
#: against the criterion the player set («в первую секунду»), that is the whole bug: a
#: chest whose dig finished a tenth of a second after a tick waits out the rest of the tick
#: AND the cooldown before anybody asks. Nothing in the chunk was slow; the QUESTION was
#: being asked late.
#:
#: So the question moved into the client. `A.tick` is defined here, called by the game's
#: own timer every fifth of a second while a chest is live, called again by a one-shot
#: pinned to the exact millisecond a dig ends, and called by the panel's step at the end of
#: every press. All three run the same code and the state they walk is the same table, so
#: two of them landing together costs one extra `GetOwnerFormationMarch` and nothing else.
_TREASURE_TICK = '''
local D = DataCenter
if not D.__lw_treasure_auto then D.__lw_treasure_auto = {seen={}, targets={}, news=0} end
D.__lw_treasure_auto.tick = function()
  local A = DataCenter.__lw_treasure_auto
  if A == nil then return end
  local P = LuaEntry.Player
  -- THE GAME'S CLOCK, never this machine's (docs/research/game-clock.md). Every deadline
  -- compared below — the dig's own `endTime`, the chest's `expireTime` — is stamped by the
  -- server, so a PC running two minutes fast would claim two minutes early, for ever.
  local now = 0
  pcall(function()
    now = math.floor(tonumber(UITimeManager.Instance:GetServerTime()) or 0) end)
  if now <= 0 then pcall(function()
    now = math.floor((tonumber(ChatInterface.getServerTime()) or 0) * 1000) end) end
  if now <= 0 then A.tick_why = "no-clock" return end
  A.tick_at = now
  A.ticks = (tonumber(A.ticks) or 0) + 1
  local wm = DataCenter.WorldMarchDataManager
  local home_srv = tonumber(P.serverId) or 0
  local ttl = (tonumber(A.ttl) or %(ttl)d) * 1000
  local grace = (tonumber(A.grace) or %(grace)d) * 1000
  local ramp = {%(ramp)s}
  -- The one observable proof that a claim was PAID: the window the client raises on a
  -- successful one. A refused claim is silent (docs/research/world-treasures.md).
  local reward = false
  pcall(function() reward = UIManager.Instance:IsWindowOpen(
    UIWindowNames.UIGiftPackageRewardGet) and true or false end)
  local live, claimed, paid, expired, waiting, resent = 0, 0, 0, 0, 0, 0
  for _, t in ipairs(A.targets or {}) do
   if not t.done then
    -- 1. WHAT THE SERVER SAID ABOUT THIS CHEST. The reply to a claim carries an
    -- `errorCode`, and the hook pins it on whichever target claimed last (`A.claim_uuid`),
    -- so two of the codes are verdicts rather than a line in a log: «claim repeat» is a
    -- chest this account already has, and «not in same alliance» is a chest it never had.
    -- Anything else is a refusal that may mend itself, and the retry ramp keeps trying.
    local code = tonumber(t.err)
    t.err = nil
    if code == %(err_repeat)d then
      t.done, t.why, t.done_at, t.paid = true, "already-had-it", now, now
    elseif code == %(err_foreign)d then
      t.done, t.why, t.done_at = true, "foreign", now
    end
    -- 2. PAID — the reward window, while it is fresh enough to be OURS.
    if not t.done and t.claimed ~= nil and reward
       and now - (tonumber(t.claimed) or 0) <= %(paid_win)d then
      t.done, t.why, t.paid, t.done_at = true, "paid", now, now
    end
    -- 3. GONE — the chest's own deadline first, the errand's guess second.
    if not t.done and (((tonumber(t.at) or 0) > 0 and now - (tonumber(t.at) or 0) > ttl)
       or ((tonumber(t.expire) or 0) > 0 and now > tonumber(t.expire))) then
      t.done, t.why, t.done_at = true, "expired", now
    end
    if t.done then
      t.state = tostring(t.why)
      if t.why == "paid" or t.why == "already-had-it" then
        paid = paid + 1
        A.paid_all = (tonumber(A.paid_all) or 0) + 1
        -- THE NUMBER THE ACCEPTANCE CRITERION IS READ OFF. `ready_at` is the moment the
        -- chest BECAME takeable — the dig's own deadline where the game gave one — and
        -- `claim_at` is when the first claim for it left. Their difference is the answer
        -- to «в первую секунду?» in milliseconds, per chest, and it is kept as the last
        -- one and as the worst one so a good average cannot hide a bad chest.
        if (tonumber(t.ready_at) or 0) > 0 and (tonumber(t.claim_at) or 0) > 0 then
          t.lag = t.claim_at - t.ready_at
          A.lag_ms = t.lag
          if t.lag > (tonumber(A.lag_worst) or -1) then A.lag_worst = t.lag end
        end
      elseif t.why == "expired" then expired = expired + 1 end
    else
      live = live + 1
      -- 4. WHERE OUR OWN SQUAD IS. The march object is the only thing that can say, and
      -- what it says has three shapes: it is walking there, it is DIGGING (and then its
      -- `endTime` is the moment the dig ends — the whole point of this watch), or it is on
      -- its way home, which means our part is done.
      local m = nil
      local lost = false
      if t.squad_uuid ~= nil then pcall(function()
        m = wm:GetOwnerFormationMarch(P.uid, t.squad_uuid, P.allianceId) end) end
      if m ~= nil then
        t.march_seen = true
        local sn = tonumber(m.status)
        local ss = "" pcall(function() ss = tostring(m.status) end)
        local et = nil pcall(function() et = tonumber(m.endTime) end)
        if sn == %(dig_status)d or ss:find("TREASURE_DIGGING", 1, true) ~= nil then
          t.digging = true
          if et ~= nil and et > 0 then t.due = et end
        elseif sn == %(home_status)d or ss:find("BACK_HOME", 1, true) ~= nil then
          if t.back_at == nil then t.back_at = now end
        elseif et ~= nil and et > 0 then
          t.arrive = et
        end
      elseif t.sent ~= nil then
        if t.march_seen then
          -- A march that WAS there and is not: the squad has been and gone.
          if t.gone_at == nil then t.gone_at = now end
        else
        -- HOW MANY TIMES WE ACTUALLY LOOKED, not just how long it has been. The clock
        -- alone is not enough to call a send lost: a client the watch is not running on is
        -- only looked at when the panel presses, and a chest twelve tiles from the base
        -- could be marched, dug and walked home between two of those presses — which would
        -- read as «the march never appeared» and send a second squad at a chest that had
        -- already been dug. Three sightings of an empty road, and only then.
        t.looks = (tonumber(t.looks) or 0) + 1
        if (tonumber(t.looks) or 0) >= 3
           and now - (tonumber(t.sent) or 0) >= %(settle)d then
          -- …and a march that was NEVER there is a send the client dropped without a
          -- word. Re-send it; do not read the silence as a squad that has been.
          t.sent, t.squad, t.squad_uuid = nil, nil, nil
          t.due, t.digging, t.armed, t.arrive, t.looks = nil, nil, nil, nil, nil
          t.resends = (tonumber(t.resends) or 0) + 1
          resent = resent + 1
          lost = true
          if t.resends > %(resends)d then
            -- EVERY SEND SWALLOWED, and the chest is NOT written off — it is claimed
            -- blind. Two things look like this from here: a client dropping our marches,
            -- and a march this reading simply cannot see. The second one would cost the
            -- whole gift for a chest that was already dug, so the last word is left to the
            -- server: the claim goes out, and «claim repeat» / «not in same alliance» /
            -- silence are three different answers, all of them better than a guess.
            t.claim_only, t.blind = true, true
          end
        end
        end
      end
      if not t.done then
       -- 5. IS IT TAKEABLE, AND SINCE WHEN? The anchor matters as much as the answer: a
       -- claim is measured against the moment the chest became takeable, not against the
       -- tick that noticed.
       local ready, anchor = false, nil
       if lost then
         t.state = "march-lost:resend" .. tostring(t.resends)
         waiting = waiting + 1
       else
        if t.claim_only and t.sent == nil then
          ready, anchor = true, (tonumber(t.dug) or tonumber(t.at) or now)
        elseif t.sent ~= nil then
          if (tonumber(t.due) or 0) > 0 and now >= tonumber(t.due) then
            ready, anchor = true, tonumber(t.due)
          elseif t.back_at ~= nil then ready, anchor = true, t.back_at
          elseif t.gone_at ~= nil then ready, anchor = true, t.gone_at
          elseif t.dug ~= nil and m == nil and t.march_seen
                 and now - (tonumber(t.sent) or 0) >= grace then
            ready, anchor = true, now
          end
        end
        if ready and t.ready_at == nil then t.ready_at = anchor or now end
        if ready then
          local n = tonumber(t.tries) or 0
          -- The gap AFTER n tries, so the first retry is the ramp's first step and not its
          -- second. A chest is only ever cooling once it has been claimed at least once.
          local wait = ramp[math.max(1, n)] or ramp[#ramp]
          if t.claimed ~= nil and now - (tonumber(t.claimed) or 0) < wait then
            waiting = waiting + 1
            -- …unless the claim went out THIS millisecond, which is what a press looks
            -- like from the second pass it makes: the word «claim1» is what happened, and
            -- «waiting» would describe the same instant as if nothing had.
            if t.claimed ~= now then t.state = "claimed-waiting" .. tostring(n) end
          else
            t.tries = n + 1
            local srv = ((tonumber(t.server) or 0) ~= 0) and tonumber(t.server) or home_srv
            -- WHICH CHEST THE NEXT `errorCode` BELONGS TO. The reply names no chest, so
            -- the only honest way to read it is to know which one was claimed last.
            A.claim_uuid = tostring(t.uuid)
            A.claim_at = now
            local ok, err = pcall(function()
              SFSNetwork.SendMessage(MsgDefines.DetectEventClaimTreasure, t.uuid, srv) end)
            if ok then
              t.claimed = now
              claimed = claimed + 1
              A.claims_all = (tonumber(A.claims_all) or 0) + 1
              if t.claim_at == nil then
                t.claim_at = now
                t.lag = now - (tonumber(t.ready_at) or now)
                A.lag_ms = t.lag
                if t.lag > (tonumber(A.lag_worst) or -1) then A.lag_worst = t.lag end
              end
              t.state = "claim" .. tostring(t.tries)
            else
              t.state = "claim-threw:" .. tostring(err)
            end
          end
        else
          waiting = waiting + 1
          if t.blind then t.state = "march-never-left:claiming"
          elseif t.sent == nil then t.state = "to-send"
          elseif t.digging then
            t.state = "digging-" .. tostring(math.max(0, math.floor(
              ((tonumber(t.due) or now) - now) / 1000))) .. "s"
          elseif not t.march_seen then t.state = "march-unanswered"
          -- OUR OWN LEGS, said apart from anybody else's (#1296). «The alliance has dug it
          -- and our squad is still on the road» is the state that hid a hundred seconds of
          -- burnt claims inside the word «digging»; it has its own word for that reason.
          elseif t.dug ~= nil then t.state = "dug-still-marching"
          else t.state = "marching" end
        end
        -- 6. THE MILLISECOND ITSELF. A dig deadline that is near is pinned with a one-shot
        -- of the game's own timer, so the claim leaves in the frame the dig ends instead of
        -- on whichever fifth of a second comes next. Armed once per deadline.
        if (tonumber(t.due) or 0) > 0 and not ready then
          local dt = tonumber(t.due) - now
          if dt > 0 and dt <= %(arm_ms)d and t.armed ~= t.due then
            t.armed = t.due
            pcall(function() TimerManager:GetInstance():DelayInvoke(function()
              local AA = DataCenter.__lw_treasure_auto
              if AA ~= nil and AA.tick ~= nil then pcall(AA.tick) end
            end, dt / 1000) end)
          end
        end
       end
      end
    end
   end
  end
  A.t_live, A.t_claimed, A.t_paid = live, claimed, paid
  A.t_expired, A.t_waiting, A.t_resent = expired, waiting, resent
  -- …AND THE SAME NUMBERS ADDED UP FOR WHOEVER IS HOLDING A PRESS. A step asks this
  -- function twice — once to resolve the queue before it spends a squad on it, once to
  -- claim what became takeable — and the second pass would otherwise report zero of what
  -- the first one did. The step zeroes these on its way in; the game's own timer never
  -- touches them.
  A.s_claimed = (tonumber(A.s_claimed) or 0) + claimed
  A.s_paid = (tonumber(A.s_paid) or 0) + paid
  A.s_expired = (tonumber(A.s_expired) or 0) + expired
  A.s_resent = (tonumber(A.s_resent) or 0) + resent
  A.claim_sent = claimed
end
''' % {"ttl": int(TREASURE_TARGET_TTL_SEC), "grace": int(TREASURE_ARRIVE_GRACE_SEC),
       "ramp": ", ".join(str(int(ms)) for ms in TREASURE_CLAIM_RAMP_MS),
       "paid_win": int(TREASURE_PAID_WINDOW_SEC) * 1000,
       "err_repeat": int(TREASURE_ERR_CLAIM_REPEAT),
       "err_foreign": int(TREASURE_ERR_NOT_IN_ALLIANCE),
       "dig_status": int(TREASURE_DIG_STATUS), "home_status": int(TREASURE_HOME_STATUS),
       "settle": int(TREASURE_MARCH_SETTLE_SEC) * 1000,
       "resends": int(TREASURE_RESEND_TRIES), "arm_ms": int(TREASURE_DUE_ARM_MS)}


def treasure_tick_define() -> str:
    """Park (or replace) `A.tick` — the claim half of the errand, as game-side code.

    Idempotent and deliberately re-run on every arm and every step: the definition IS the
    deployment. A client that has been running since before an edit to this file would
    otherwise keep claiming with last week's rules, and there is nothing on screen to say
    so.
    """
    return _TREASURE_TICK


def treasure_reaper_install() -> str:
    """Start the game-side watch that takes a chest the moment its dig ends (#1318).

    «Таймер работать с наивысшим приоритетом, отслеживать время завершения раскопки и в ту
    же микросекунду забирать сокровище, и продолжать попытки, пока сокровище не будет взято
    или не исчезнет.» This is that timer, and it lives where the deadline lives.

    WHAT IT ACTUALLY WAITS FOR. A dig march carries `MarchStatus.TREASURE_DIGGING` and,
    with it, an `endTime` — the server's own millisecond for when the digging finishes
    (`docs/research/squad-state.md`). So the watch does not guess and does not poll the
    server: it reads our own march, learns the deadline the first time the squad starts
    digging, and pins a one-shot of the game's timer to it. Between deadlines it looks
    every fifth of a second, which is what catches the chests whose deadline never arrives
    in a readable form — a claim-only target heard through the alliance's dig feed, a march
    that ends by going home.

    THREE THINGS IT DOES BESIDES CLAIMING, all of them cheap:

      * **it watches for a send that never happened.** A march the client dropped in
        silence used to be read as a march that was over, and the claim went out into an
        empty road (`TREASURE_RESEND_TRIES`);
      * **it reads the box the camera is in**, every few seconds, out of the client's own
        point manager — the second of the two ears the panel is asked to keep open. It
        never moves the camera, never changes the zoom and never asks the server, and in
        the city it does nothing at all;
      * **it stops itself.** This is a self-rescheduling timer inside somebody's game, so
        it ends after `TREASURE_REAP_STOP_SEC` with nothing to work. The panel's poll
        re-arms it on the next tick; a panel that has been closed leaves nothing behind.

    Re-arming is safe and is how a code change is deployed: the run token is bumped, every
    loop scheduled under the old one returns on its next wake, and exactly one loop is left
    running. The queue itself is never touched.
    """
    return _TREASURE_TICK + _TREASURE_REAP_LOOP


def treasure_reaper_start() -> str:
    """The same watch, for a caller that has just parked `A.tick` itself.

    The arm below defines the tick — it is the recipe's first press, so the definition is
    always the current one — and the button that composes the two would otherwise carry
    nine kilobytes of the same Lua twice.
    """
    return _TREASURE_REAP_LOOP


_TREASURE_REAP_LOOP = '''
local A = DataCenter.__lw_treasure_auto
if A == nil then A = {seen={}, targets={}, news=0} DataCenter.__lw_treasure_auto = A end
A.reap = (tonumber(A.reap) or 0) + 1
local token = A.reap
A.reap_on = true
A.reap_started = A.tick_at or 0
-- THE SECOND EAR: what the client can see from where it already stands. Not a lap — the
-- whole-server walk was deleted for costing 48 s of camera and finding other people's
-- chests (#1296) — one box around the camera, read out of the point manager the client
-- fills for itself. It runs off `_G.WS` and never goes looking for the scene: finding it
-- costs a `FindObjectsOfType` over every MonoBehaviour in the game, which is the panel's
-- own press to pay, not a background timer's.
local function look()
  local A = DataCenter.__lw_treasure_auto
  local now = tonumber(A.tick_at) or 0
  if now <= 0 then return end
  if (tonumber(A.look_at) or 0) > 0 and now - A.look_at < %(look_sec)d then return end
  A.look_at = now
  local inworld = false
  pcall(function() inworld = SceneUtils.GetIsInWorld() and true or false end)
  if not inworld then A.look_why = "city" return end
  local scene = _G.WS
  local pm = nil
  pcall(function() pm = scene and scene.PointManager end)
  if pm == nil then A.look_why = "no-point-manager" return end
  local cx, cy = -1, -1
  pcall(function() cx, cy = scene.CurTilePos.x, scene.CurTilePos.y end)
  cx, cy = math.floor(tonumber(cx) or -1), math.floor(tonumber(cy) or -1)
  if cx < 0 or cy < 0 then A.look_why = "no-camera-tile" return end
  local size = 1000
  pcall(function() size = scene.TileCount.x end)
  local srv = tonumber(LuaEntry.Player.serverId) or 0
  local mine = tostring(LuaEntry.Player.allianceId or "")
  local box = %(look_box)d
  local x0, x1 = math.max(0, cx - box), math.min(size - 1, cx + box)
  local y0, y1 = math.max(0, cy - box), math.min(size - 1, cy + box)
  local found, ours, foreign = 0, 0, 0
  for ty = y0, y1 do
    local base = ty * size + 1
    for tx = x0, x1 do
      local info = nil
      pcall(function() info = pm:GetPointInfo(base + tx) end)
      if info ~= nil then
        local pt = nil
        pcall(function() pt = tonumber(info.PointType) end)
        if pt == %(point_type)d then
          local uuid = nil
          pcall(function() uuid = info.uuid end)
          if uuid ~= nil and tostring(uuid) ~= "0" then
            found = found + 1
            local ally = "" pcall(function() ally = tostring(info.allianceId or "") end)
            -- A CHEST BELONGS TO AN ALLIANCE and the game refuses everybody else's
            -- (errorCode 801354). Eighteen of the first nineteen ever seen were foreign.
            if mine ~= "" and ally ~= "" and ally ~= mine then foreign = foreign + 1
            else
              ours = ours + 1
              local key = tostring(uuid)
              local seen_here = nil
              for _, t in ipairs(A.targets or {}) do
                if tostring(t.uuid) == key then seen_here = t end end
              if seen_here ~= nil then
                -- The door that has the TILE upgrades a target that arrived without one.
                if (tonumber(seen_here.pid) or 0) == 0 then
                  seen_here.pid, seen_here.x, seen_here.y = base + tx, tx, ty
                  seen_here.claim_only = false
                  seen_here.src = tostring(seen_here.src or "?") .. "+eye"
                end
              else
                local who = "" pcall(function() who = tostring(info.ownerUid or "") end)
                local exp = 0 pcall(function() exp = tonumber(info.expireTime) or 0 end)
                A.seen = A.seen or {}
                A.seen[key] = A.seen[key] or now
                A.targets = A.targets or {}
                A.targets[#A.targets+1] = {uuid = uuid, pid = base + tx, x = tx, y = ty,
                  server = tonumber(info.serverId) or srv, at = now, src = "eye",
                  expire = exp, dug = ((who ~= "" and who ~= "0") and now or nil)}
                A.news = (tonumber(A.news) or 0) + 1
              end
            end
          end
        end
      end
    end
  end
  A.look_why = "looked"
  A.look_found, A.look_ours, A.look_foreign = found, ours, foreign
end
local tm = TimerManager:GetInstance()
local function loop()
  local A = DataCenter.__lw_treasure_auto
  if A == nil or A.reap ~= token or not A.reap_on then return end
  if A.tick ~= nil then pcall(A.tick) end
  pcall(look)
  local busy = (tonumber(A.t_live) or 0) > 0
  local now = tonumber(A.tick_at) or 0
  if busy or (tonumber(A.reap_busy_at) or 0) == 0 then A.reap_busy_at = now end
  -- A TIMER IN SOMEBODY ELSE'S GAME HAS TO END. Nothing to work for a quarter of an hour
  -- and the loop stops; the panel's poll arms it again the moment it next looks.
  if now > 0 and not busy and now - (tonumber(A.reap_busy_at) or now) > %(stop_ms)d then
    A.reap_on = false
    CS.UnityEngine.Debug.LogError("ACT treasure_reaper idle-stop ticks="
      .. tostring(A.ticks or 0))
    return
  end
  tm:DelayInvoke(loop, busy and %(fast)s or %(idle)s)
end
tm:DelayInvoke(loop, %(fast)s)
CS.UnityEngine.Debug.LogError("ACT treasure_reaper on=1 run=" .. tostring(token)
  .. " queued=" .. tostring(#(A.targets or {})))
''' % {"look_sec": int(TREASURE_REAP_LOOK_SEC) * 1000,
       "look_box": int(TREASURE_REAP_LOOK_BOX), "point_type": int(TREASURE_POINT_TYPE),
       "stop_ms": int(TREASURE_REAP_STOP_SEC) * 1000,
       "fast": repr(float(TREASURE_REAP_FAST_SEC)),
       "idle": repr(float(TREASURE_REAP_IDLE_SEC))}


def treasure_reaper_stop() -> str:
    """Stop the game-side watch; the queue and the ear are left exactly as they are.

    Bumping the run token is the whole of it — a loop already scheduled cannot be cancelled,
    so it is disowned instead and returns on its next wake (the same way a map lap is
    stopped). What the watch knew stays on the VM: a chest halfway through is still worth
    finishing, by the panel's press or by the next arm.
    """
    return (
        "local A = DataCenter.__lw_treasure_auto "
        "if A ~= nil then A.reap = (tonumber(A.reap) or 0) + 1 A.reap_on = false end "
        'CS.UnityEngine.Debug.LogError("ACT treasure_reaper on=0 ticks="'
        "..tostring((A or {}).ticks or 0))"
    )


def treasure_reaper_state() -> str:
    """Lua *expression* -> what the watch is doing, and the number the criterion needs.

    ``on=<0|1> ticks=<n> live=<n> claims=<n> paid=<n> lag=<ms> worst=<ms> eye=<why>`` —
    `lag` is the milliseconds between a chest becoming takeable and the first claim for it
    leaving, which is «в первую секунду» said as a number rather than as an impression,
    and `worst` is the worst one this client has seen so an average cannot hide a bad chest.
    `-1` for either means no chest has been taken yet.
    """
    return (
        "(function() local A = DataCenter.__lw_treasure_auto "
        "if A == nil then return 'on=0 ticks=0 live=0 claims=0 paid=0 "
        "lag=-1 worst=-1 eye=never' end "
        "return 'on=' .. tostring((A.reap_on and A.reap_on ~= 0) and 1 or 0) "
        ".. ' ticks=' .. tostring(A.ticks or 0) "
        ".. ' live=' .. tostring(A.t_live or 0) "
        ".. ' claims=' .. tostring(A.claims_all or 0) "
        ".. ' paid=' .. tostring(A.paid_all or 0) "
        ".. ' lag=' .. tostring(A.lag_ms or -1) "
        ".. ' worst=' .. tostring(A.lag_worst or -1) "
        ".. ' eye=' .. tostring(A.look_why or 'never') end)()"
    )


def treasure_auto_step() -> str:
    """Work every queued chest one step, in ONE chunk — and say what it did.

    A CHEST IS A RACE, so this is one call and not eight. The rally join was measured at
    5.48 s across its readings and 0.19 s once they became local variables inside a
    single chunk (#1281); a treasure has the same shape — it is out for minutes and the
    alliance is digging it — so the sieve, the pairing, the send and the claim all happen
    here, and the recipe only reads the sentence back.

    What one step is, per target:

      * **new** — pick the nearest free squad and march it onto the tile. Same
        `MarchUtil.SendCreateMarchMessage` the game's own dig ends at, type 50 for a
        chest on this server and 182 for one on another (`docs/research/
        world-treasures.md`), called STRAIGHT rather than behind
        `TimerManager:DelayInvoke` — the rally join proved the direct send works from the
        daemon's thread, and a send behind a timer cannot say whether it threw.
      * **anything else** — `A.tick`, and not this chunk (#1318). Waiting for a dig to end
        and claiming the moment it does is a question of MILLISECONDS, and a chunk the
        panel sends is asked every ten seconds at best. So the claim half lives in the game
        (`_TREASURE_TICK`), is driven by the game's own timer, and is called from here as
        the last thing this press does — a press is never slower than the watch, and the
        watch never waits for a press.

    A REFUSED CLAIM IS SILENT, and the whole shape above exists because of it. Measured
    live on 2026-08-08 against a uuid that cannot exist: **no message tip, no window, no
    thrown error**, and the reply arrives under the same command name carrying no readable
    fields. So «the send returned cleanly» proves nothing, and the first version of this
    chunk — which treated it as payment — wrote a chest off while the alliance was still
    digging it, in exactly the case the grace was added for: a squad still walking when the
    clock ran out. Two corrections came out of that, and neither is optional:

      * the grace waits for the CLOCK **and** for the march to be over
        (`GetOwnerFormationMarch` on the squad that was sent — the target keeps that
        squad's uuid for this reason). A chest 300 tiles out lives longer than any grace
        worth having;
      * a claim is proven by the `UIGiftPackageRewardGet` the client raises on a paid one,
        read only while it is fresh; a chest whose tries all ran out is written off as
        `claim-unconfirmed`, never as `claimed`.

    AND THE DIG FEED DOES NOT OVERRULE OUR OWN MARCH — the second correction, measured on
    the first chest this account ever had of its own (#1296). `t.dug` used to skip the
    march test entirely, on the reading that a dug chest is claimable. It is not: a chest
    the ALLIANCE has dug is not a chest THIS account has dug, and the claim is refused
    until our squad has done its part. Live, on a chest twelve tiles from home: the march
    went out at 20:55:41 and the first claim at 20:55:43, two seconds later, with the squad
    barely out of the base — all four tries spent inside 124 s, every one refused in
    silence, and the chest written off. So `not marching` now gates the feed exactly as it
    gates the clock, and a chest waiting on our own legs says `dug-still-marching` rather
    than hiding inside `digging`.

    A SPENT CHEST STAYS IN THE LIST, which is the other half of that bug. The prune used
    to drop every finished target, and `treasure_scan_harvest` looks for duplicates among
    the targets it can see — so the lap five minutes later re-queued the chest it had just
    written off, sent a SECOND squad at it and burned four more claims, round and round for
    as long as the chest was on the map. Finished targets are now kept until their ttl
    runs out: skipped by the step (`live` takes only what is not `done`), recognised by the
    harvest, and counted apart in the report as `spent=` so `queued=` still means work.

    «NEAREST» IS HONEST ABOUT ITS OWN LIMIT, and this is worth reading before trusting
    the word. A squad has no position of its own — read live off
    `ArmyFormationDataManager`, a formation carries its army, its slot and its heroes and
    NO tile — and a squad that is free is by definition standing in the base. So every
    free squad is the same distance from the chest, and «the nearest squad» can only be
    honestly resolved as «the nearest CHEST first, with the lowest free slot», which is
    what this does: targets are ordered by their distance from the base, and the report
    names the distance it went by. A squad already marching is never counted as nearer,
    because it is not free.

    THE PER-DAY LIMIT IS THE SERVER'S. `CheckTreasureReachDailyLimit` gates both the dig
    and the claim, and a refusal comes back as the server's own answer rather than as a
    thrown error — so a send that goes out and pays nothing is reported as sent, and the
    day's allowance is not something this chunk pretends to know.
    """
    return (
        "local A = DataCenter.__lw_treasure_auto "
        "if A == nil then A = {seen={}, targets={}, news=0} "
        "DataCenter.__lw_treasure_auto = A end "
        "local P = LuaEntry.Player "
        "local now = 0 pcall(function() "
        "now = math.floor(tonumber(UITimeManager.Instance:GetServerTime()) or 0) end) "
        "if now <= 0 then pcall(function() "
        "now = math.floor((tonumber(ChatInterface.getServerTime()) or 0) * 1000) end) end "
        "local grace = (tonumber(A.grace) or " + str(int(TREASURE_ARRIVE_GRACE_SEC))
        + ") * 1000 "
        "local ttl = (tonumber(A.ttl) or " + str(int(TREASURE_TARGET_TTL_SEC))
        + ") * 1000 "
        "local home_srv = tonumber(P.serverId) or 0 "
        # The base's own tile — where a free squad stands, and what the ordering of the
        # chests is measured from.
        "local hx, hy = 0, 0 "
        "pcall(function() local tp = SceneUtils.IndexToTilePos(tonumber(P.world_main_pos)) "
        "hx, hy = tonumber(tp.x) or 0, tonumber(tp.y) or 0 end) "
        # The squads that could go: in the allowed slots, with an army, not marching.
        "local allow = {} "
        "for _, s in ipairs(A.squads or {1,2,3,4}) do allow[tonumber(s) or -1] = true end "
        "local afd = DataCenter.ArmyFormationDataManager "
        "local wm = DataCenter.WorldMarchDataManager "
        "local free, empties, busy, dry = {}, {}, 0, 0 "
        "for _, f in pairs(afd.ArmyFormationList) do "
        "local idx = -1 pcall(function() idx = tonumber(f.index) or -1 end) "
        "if allow[idx] then "
        "local n = 0 pcall(function() n = tonumber(f.totalSoldierNum) or 0 end) "
        "local out = false "
        "pcall(function() out = (wm:GetOwnerFormationMarch("
        "P.uid, f.uuid, P.allianceId) ~= nil) end) "
        "if out then busy = busy + 1 elseif n <= 0 then dry = dry + 1 "
        "empties[#empties+1] = f.uuid "
        "else free[#free+1] = {slot=idx, uuid=f.uuid, n=n} end end end "
        "table.sort(free, function(a, b) return a.slot < b.slot end) "
        # A SQUAD THAT READS EMPTY IS USUALLY A SQUAD NOBODY HAS ASKED ABOUT (#1285, and
        # measured again here: the same three squads read 3123/2631/2565 and then 0/0/0
        # twenty minutes later, with the army untouched in the game). The client's
        # counter is a reply cache; one request puts the real number back in ~0.4 s with
        # nothing on screen. So a run that has a chest and no squad to send ASKS, marks
        # that it asked, and lets the recipe come round again — refusing on a number
        # nobody has fetched is refusing on nothing.
        "A.asked = false "
        "if #free == 0 and #empties > 0 then "
        "for _, u in ipairs(empties) do pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.GetFormationSoldier, u) end) end "
        "A.asked = true end "
        # The chests, nearest first — the only place the word «nearest» can be earned
        # (see the docstring).
        # HOW FAR EVERY CHEST IS, AND WHICH DOOR IT CAME THROUGH — measured before anything
        # is decided, because the words below are written on chests the tick may finish.
        "for _, t in ipairs(A.targets or {}) do if not t.done then "
        "t.d = math.max(math.abs((tonumber(t.x) or 0) - hx), "
        "math.abs((tonumber(t.y) or 0) - hy)) "
        # WHICH DOOR THIS CHEST CAME THROUGH, and how long ago — because «a chest was
        # worked» is half an answer: the three doors fail in different ways (nobody shared
        # it / the dig feed carries no tile / nobody has looked that way yet), and a log
        # that does not say which one let this chest in cannot tell a working door from a
        # lucky one.
        "t.tag = tostring(t.src or '?') "
        "if (tonumber(t.at) or 0) > 0 and now > 0 then "
        "t.tag = t.tag .. '/' .. tostring(math.floor((now - t.at) / 1000)) .. 's' end "
        "end end "
        # THE WATCH RUNS FIRST, and this is not a nicety: a chest whose minutes on the map
        # are over is written off by the tick, and a step that built its list before asking
        # would send a squad at a tile that expired a minute ago.
        "A.s_claimed, A.s_paid, A.s_expired, A.s_resent = 0, 0, 0, 0 "
        "if A.tick ~= nil then pcall(A.tick) end "
        "local live = {} "
        "for _, t in ipairs(A.targets or {}) do if not t.done then "
        "live[#live+1] = t end end "
        "table.sort(live, function(a, b) return (a.d or 0) < (b.d or 0) end) "
        # WHAT THE SEND HALF OWNS, and what it stopped owning (#1318). Everything about a
        # chest that has ALREADY got a squad — is the dig over, is it takeable, has the
        # server paid — is `A.tick`, because those questions have to be asked in
        # milliseconds and this chunk is asked in tens of seconds. What is left here is the
        # pairing: which chest, which squad, and the march itself.
        "local sent, notes, mine = 0, {}, {} "
        "local fi = 1 "
        "for _, t in ipairs(live) do "
        # A chest with a squad out, or one that only ever had a uuid to claim, is the
        # watch's business — this loop leaves it alone and the note comes off the word the
        # watch wrote on it.
        "if t.sent ~= nil or t.claim_only then "
        "else "
        # New: the nearest free squad goes out. `fi` walks the free list so two chests
        # in the same minute never get the same squad.
        "local f = free[fi] "
        "if f == nil then mine[#mine+1] = {t, 'no-free-squad'} "
        # THE CAMERA DOES NOT HAVE TO BE ON THE CHEST — checked, because for a while it
        # looked as though it did (#1296). A send with the camera elsewhere once produced
        # nothing on the wire, and a send with the camera on the tile produced the message
        # at once; the difference turned out to be the SQUAD, not the view. Measured again
        # with the camera parked 500 tiles away and every squad genuinely free, the march
        # went out exactly as before. What the client does drop in silence is a march for a
        # formation that is already committed — and a squad whose march the server has not
        # confirmed yet still reads free here, which is what the first reading caught. The
        # watch is what notices afterwards that this send left no march at all, and sends
        # again rather than claiming into an empty road.
        "else fi = fi + 1 "
        "local srv = tonumber(t.server) or home_srv "
        "local target = (srv ~= 0 and srv ~= home_srv) and "
        + str(int(MARCH_CROSS_DETECT_TREASURE)) + " or "
        + str(int(MARCH_DETECT_TREASURE)) + " "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(f.uuid, target, t.pid, t.uuid, 1, 1, false, "
        "srv, nil) end) "
        # The squad's UUID rides with the target, not just its slot: the «is it still
        # walking?» test the watch makes asks about THIS squad's march, and a slot number
        # cannot.
        "if ok then t.sent, t.squad, t.squad_uuid = now, f.slot, f.uuid sent = sent + 1 "
        "t.march_seen, t.due, t.armed, t.gone_at, t.back_at = nil, nil, nil, nil, nil "
        "mine[#mine+1] = {t, 'squad' .. tostring(f.slot)} "
        "else mine[#mine+1] = {t, 'march-threw:' .. tostring(err)} end "
        "end end end "
        # …AND THEN THE CLAIM HALF, AT ONCE. The same function the game's own timer calls,
        # run here so a press is never slower than the watch it shares its state with — and
        # so a client whose watch has idled out still claims on a press.
        "if A.tick ~= nil then pcall(A.tick) end "
        # …and the send half keeps its own words. The watch writes a word on every live
        # chest, and a chest this press has just marched at — or could find no squad for —
        # would otherwise be described by what it looks like a fifth of a second later
        # («marching», «to-send») rather than by what this press DID about it.
        "for _, r in ipairs(mine) do r[1].state = r[2] end "
        # A FINISHED CHEST IS REMEMBERED, NOT FORGOTTEN — and the difference is a second
        # march (#1296). The prune used to drop every `done` target, and the lap that came
        # round five minutes later looked for a duplicate among the LIVE targets only: the
        # chest it had just written off was `new` again, got a fresh squad sent at it and
        # burned another four claims, for as long as it stayed on the map. So a spent chest
        # stays in the list until its ttl runs out — the step skips it (`live` takes only
        # what is not done) and the harvest recognises it (`already-queued`).
        "local keep, alive = {}, 0 "
        "for _, t in ipairs(A.targets or {}) do "
        "if not t.done then keep[#keep+1] = t alive = alive + 1 "
        "elseif now > 0 and now - (tonumber(t.done_at) or 0) < ttl then "
        "keep[#keep+1] = t end end "
        "A.targets = keep "
        "local spent = #keep - alive "
        # The notes are written LAST, off the word the watch left on each chest, so the
        # line says where every one of them actually stands rather than where it stood
        # before the claim half ran.
        "for _, t in ipairs(A.targets or {}) do "
        "if t.d ~= nil and (not t.done or t.done_at == now) then "
        "notes[#notes+1] = 'x' .. tostring(t.d) .. '/' .. tostring(t.tag) "
        ".. ':' .. tostring(t.state or '?') "
        ".. ((tonumber(t.lag) ~= nil) and ('/lag' .. tostring(t.lag) .. 'ms') or '') "
        "end end "
        "A.report = 'sent=' .. tostring(sent) "
        ".. ' claimed=' .. tostring(A.s_claimed or 0) "
        ".. ' paid=' .. tostring(A.s_paid or 0) "
        ".. ' waiting=' .. tostring(A.t_waiting or 0) "
        ".. ' expired=' .. tostring(A.s_expired or 0) "
        ".. ' queued=' .. tostring(alive) "
        # What is being held only so it is not started over. Said when there is any, so a
        # queue that reads 0 and a list that is not empty are never the same line.
        ".. (spent > 0 and (' spent=' .. tostring(spent)) or '') "
        # A SEND THAT LEFT NO MARCH, said out loud (#1318). This is «отправка отряда
        # работает через раз» in one word: the client dropped the march and the watch is
        # sending it again, which used to be invisible because the silence read as a squad
        # that had been and come back.
        ".. ((tonumber(A.s_resent) or 0) > 0 "
        "and (' resent=' .. tostring(A.s_resent)) or '') "
        ".. ' free=' .. tostring(#free) .. ' busy=' .. tostring(busy) "
        ".. ' empty=' .. tostring(dry) "
        ".. (A.asked and ' asked-for-army' or '') "
        ".. ' news=' .. tostring(A.news or 0) "
        # THE NUMBER THE PLAYER ASKED FOR, on every line. `lag` is how long the last chest
        # taken had to wait between becoming takeable and its first claim leaving, and
        # `worst` is the worst this client has ever managed. «В первую секунду» is a
        # measurement, so it is reported as one.
        ".. ((tonumber(A.lag_ms) ~= nil) and (' lag=' .. tostring(A.lag_ms) .. 'ms') or '') "
        ".. ((tonumber(A.lag_worst) ~= nil) "
        "and (' worst=' .. tostring(A.lag_worst) .. 'ms') or '') "
        ".. ' watch=' .. tostring((A.reap_on and 1) or 0) "
        # …and what the SERVER last said no to, if it said anything. A claim it refuses
        # answers with an `errorCode`, and a run that claimed and was refused otherwise
        # reads as a run that did nothing at all.
        ".. ((A.last_error and now > 0 and (tonumber(A.last_error_at) or 0) > 0 "
        "and now - A.last_error_at < 60000) "
        "and (' server-said=[' .. tostring(A.last_error) .. ']') or '') "
        ".. ' [' .. table.concat(notes, ' ') .. ']' "
        "A.did = sent + (tonumber(A.s_claimed) or 0) "
        'CS.UnityEngine.Debug.LogError("ACT treasure_auto_step " .. A.report)'
    )


def treasure_queue_one_parked() -> str:
    """Put ONE named chest into the errand's queue — the press a single row makes (#1318).

    A row on «Командный пункт» knows exactly which chest it is drawn for, and until now
    each of its two buttons drove the game by hand: «Копать» assembled a march, «Забрать»
    sent one claim and reported the send as the result. A send that returns cleanly proves
    nothing (`docs/research/world-treasures.md`), which is precisely why the player found
    the button unreliable — it said «взято» and nothing arrived.

    So a row now parks its chest here and the ERRAND takes it: the same queue, the same
    squad pairing, the same watch that claims at the dig's deadline and keeps trying until
    the chest is paid or gone. The recipe is `actions/take_treasure.md`; a `TAP` carries no
    arguments, so what it was given travels on the VM as
    `DataCenter.__lw_treasure_one = {uuid=…, server=…, pid=…, x=…, y=…}` — the same hand-off
    the rally's join uses for its squads.

    A chest already in the queue is UPGRADED rather than duplicated: a target heard through
    the dig feed carries a uuid and no tile, and a row that has one fills it in — which is
    the difference between «claim it and hope» and «march on it». A chest already spent is
    started over on purpose: this is somebody pressing the button, and the press means «try
    it again» in the one case a person can see something the errand cannot.
    """
    return (
        "local D = DataCenter "
        "if not D.__lw_treasure_auto then D.__lw_treasure_auto = "
        "{seen={}, targets={}, news=0} end "
        "local A = D.__lw_treasure_auto "
        "local one = D.__lw_treasure_one or {} "
        "local uuid = one.uuid "
        "local now = 0 pcall(function() "
        "now = math.floor(tonumber(UITimeManager.Instance:GetServerTime()) or 0) end) "
        "if now <= 0 then pcall(function() "
        "now = math.floor((tonumber(ChatInterface.getServerTime()) or 0) * 1000) end) end "
        "if uuid == nil or tostring(uuid) == '0' then "
        'CS.UnityEngine.Debug.LogError("ACT treasure_one none") return end '
        "local key = tostring(uuid) "
        "local pid = tonumber(one.pid) or 0 "
        "local found = nil "
        "for _, t in ipairs(A.targets or {}) do "
        "if tostring(t.uuid) == key then found = t end end "
        "local what = 'new' "
        "if found ~= nil then what = 'again' "
        "found.done, found.why, found.state = nil, nil, nil "
        "found.tries, found.claimed, found.err = 0, nil, nil "
        "found.at = now "
        "if pid > 0 and (tonumber(found.pid) or 0) == 0 then "
        "found.pid, found.x, found.y = pid, tonumber(one.x) or 0, tonumber(one.y) or 0 "
        "found.claim_only = false what = 'upgraded' end "
        "if (tonumber(one.server) or 0) ~= 0 then found.server = tonumber(one.server) end "
        "else "
        "A.seen = A.seen or {} A.seen[key] = A.seen[key] or now "
        "A.targets = A.targets or {} "
        "A.targets[#A.targets+1] = {uuid = uuid, pid = pid, "
        "x = tonumber(one.x) or 0, y = tonumber(one.y) or 0, "
        "server = tonumber(one.server) or 0, at = now, src = 'row', "
        "claim_only = (pid == 0)} "
        "A.news = (tonumber(A.news) or 0) + 1 end "
        'CS.UnityEngine.Debug.LogError("ACT treasure_one " .. what .. " queued="'
        "..tostring((function() local n = 0 "
        "for _, t in ipairs(A.targets or {}) do if not t.done then n = n + 1 end end "
        "return n end)()))"
    )


def treasure_auto_report() -> str:
    """Lua *expression* -> the sentence the last step wrote, or a word saying it never ran."""
    return ("(DataCenter.__lw_treasure_auto and DataCenter.__lw_treasure_auto.report "
            "or 'the step left no report — the press did not run')")


def treasure_auto_did() -> str:
    """Lua *expression* -> how many sends the last step made (a march or a claim)."""
    return ("(function() local A = DataCenter.__lw_treasure_auto "
            "if A == nil then return 0 end return tonumber(A.did) or 0 end)()")


def treasure_auto_dump() -> str:
    """Lua *expression* -> one line per queued chest: where it is and what stage it is at.

    A reading, for the log and for the debug page. Positions and uuids are the account's
    own and belong on screen, never in this repository (CLAUDE.md).
    """
    return (
        "(function() local A = DataCenter.__lw_treasure_auto "
        "if A == nil then return 'the auto errand has never been armed' end "
        "local out = {} "
        "for i, t in ipairs(A.targets or {}) do "
        "local st = 'new' "
        "if t.claimed then st = 'claimed' elseif t.dug then st = 'dug' "
        "elseif t.sent then st = 'digging' end "
        "out[#out+1] = tostring(i) .. ') @[' .. tostring(t.x) .. ',' .. tostring(t.y) "
        ".. '|' .. tostring(t.server) .. '] ' .. st "
        ".. (t.squad and (' squad' .. tostring(t.squad)) or '') end "
        "if #out == 0 then return 'no chest is queued (on=' "
        ".. tostring(A.on and 1 or 0) .. ', heard=' .. tostring(A.news or 0) .. ')' end "
        "return table.concat(out, ' ; ') end)()"
    )


# --- The third door: a sweep of the MAP itself -------------------------------
# «Скрытые сокровища не собираются, если они просто на карте, даже если карту обновлять,
# проверяется не то, должно сканироваться карта на предмет сокровищ, а не только
# слушаться пуш шаринга.» The two doors above are both somebody TELLING the client about
# a chest — the alliance chat share, which a player may simply never send, and the dig
# broadcast, which carries a uuid and no tile. Neither of them looks at the map, so a
# chest that is merely LYING there is invisible to both.
#
# WHAT «ОБНОВИТЬ» ASKS, AND WHY IT IS NOT THIS. The refresh on «Командный пункт» sends
# `activity.detect.list` and reads `ActDetectTreasureDataManager` — the account's own
# detect-event list, i.e. the chests THIS alliance's event placed. A chest another
# alliance put out, or one this client was never told about, is not in that reply no
# matter how often it is asked for. That is the «проверяется не то» exactly.
#
# AND THE MAP IS NOT READABLE OFF THE LUA WIRE. Measured live on 2026-08-08: with the
# watcher in `wide` mode (it keeps every command), three jumps at height 600 produced no
# `world.get.block` in the ring at all — only ordinary pushes. The map stream is decoded
# on the C# side and never reaches `SFSNetwork.HandleMessage`, so no hook in Lua can hear
# it and the pcap scanners (`tools/dev/treasure_capture.py`) exist for that reason.
#
# WHAT IS READABLE is the client's OWN point manager, which is what the zoom research
# measured the map with (docs/research/map-sweep-zoom.md §2):
#
#     WS.PointManager:GetPointInfo(pid)   -- nil when the client does not know that tile
#     info.PointType == 21               -- WorldPointType.TREASURE, the wire's `f2`
#     info.uuid, info.serverId           -- read live off a neighbouring kind:
#                                        -- HeroDispatchMissionPointInfo answers
#                                        -- uuid=<19 digits> serverId=<n> cfgId=<n>
#
# …and its one limit is the whole design here: **it only holds what is in view**. Jump
# away and the old tiles go back to unknown. So the scrape has to ride the sweep, one box
# per waypoint, which is what this does — the waypoint list goes to the game's own timer
# exactly as `fast_map_sweep` schedules it, and a second timer a moment behind each jump
# reads the box that jump loaded.
#
# Measured on the live client (1000 × 1000 server, height 600, step 90): a 121 × 121 box
# is **0.040 s** inside the VM, and the tile index needs no call at all —
# `pid = y * size + x + 1` was checked against `SceneUtils.TilePosToIndex` at four
# coordinates and agrees. The whole lap is that box times the waypoint count, spread over
# the lap rather than spent in one place.

#: How long after a waypoint's jump its box is read, and how long the camera then stands
#: still — the two numbers that decide what a lap comes home with, and both are measured.
#:
#: A jump asks the server for its tiles and the point manager fills in ONE step: read live
#: at two spots, the box was empty at 0.05 / 0.10 / 0.15 s and complete at 0.20–0.30 s
#: (1250 and 319 tiles respectively), and no later reading added a single one. So the lag
#: is a shade past the fill and the pause is a shade past the lag.
#:
#: **This is why a treasure lap is not the 6.5 s the plain sweep is.** `fast_map_sweep`
#: moves the camera every 0.05 s because a pcap listener catches the replies whenever they
#: land; a lap that READS the client has to be standing where it is looking. Measured: at
#: 0.05 s a whole lap of 121 waypoints knew 2599 tiles in total — twenty a stop, against
#: the 500–1250 a stop holds when it is given its quarter of a second.
TREASURE_SCAN_LAG = 0.30

#: …and the pause between two waypoints. 121 waypoints at this is about 48 s of camera,
#: which is the honest price of reading the map out of the client rather than off a wire.
TREASURE_SCAN_STEP_SEC = 0.40


#: How often the map is worth re-reading. A chest is out for MINUTES and the alliance
#: digs it together, so the useful cadence is minutes — five of them here. The errand's
#: own tick is ten seconds and hears the two announcement doors in that second; the lap
#: is the door for a chest nobody announced, and it costs a camera that walks the whole
#: server, so it is deliberately the slowest of the three.
TREASURE_SCAN_EVERY_SEC = 300


def treasure_scan_sweep(zoom: "int | None" = None, step: "int | None" = None,
                        interval: "float | None" = None,
                        server: "int | None" = None,
                        lag: float = TREASURE_SCAN_LAG) -> str:
    """One lap of the whole map that READS it — every `PointType 21` tile it passes.

    The lap itself is `fast_map_sweep`'s: the waypoints are handed to the game's own
    `TimerManager` in one call and walked inside the game, so nothing here is a round trip
    per stop. What is added is a second timer per waypoint, `lag` behind the jump, which
    reads the box that jump loaded out of `WorldScene.PointManager` and keeps the chests —
    and a PAUSE, because a camera that has already left is a box that reads empty
    (:data:`TREASURE_SCAN_LAG`).

    The findings land in `DataCenter.__lw_treasure_scan.found`, keyed by uuid so a chest
    seen from two overlapping boxes is one finding. Nothing is sent, nothing is claimed
    and no window opens: the lap moves the camera and reads memory.

    A lap can be disowned exactly as the plain sweep can — both share
    `DataCenter.ActDispatchTaskDataManager.__lw_sweep_run`, so `fast_map_sweep_stop()`
    stops this one too, and the scrapes check the same token before touching anything.

    EVERY NUMBER CAN BE PARKED, because a `TAP` carries no arguments (`docs/dsl.md`) and
    this is meant to be pressed by a recipe: `DataCenter.__lw_treasure_scan_cfg`
    (`{zoom, step, every, lag, server}`) is read first and the arguments here are the
    fallback for each one, so the same button works pressed bare.
    """
    height = int(SWEEP_ZOOM_MAX if zoom is None else zoom)
    stride = max(1, int(FAST_STEP if step is None else step))
    gap = max(0.0, float(TREASURE_SCAN_STEP_SEC if interval is None else interval))
    where = str(int(server)) if server else current_server_expr()
    return (FIND_WORLD_SCENE + '''
local DC = DataCenter.ActDispatchTaskDataManager
local S = {found = {}, n = 0, done = 0, tiles = 0, known = 0, chests = 0,
           errs = 0, blind = 0}
DataCenter.__lw_treasure_scan = S
DC.__lw_sweep_run = (tonumber(DC.__lw_sweep_run) or 0) + 1
local run = DC.__lw_sweep_run
S.run = run
local cfg = DataCenter.__lw_treasure_scan_cfg or {}
local srv = tonumber(cfg.server) or 0
if srv == 0 then srv = %s end
local size = 1000
pcall(function() size = WS.TileCount.x end)
S.server = srv
local height = tonumber(cfg.zoom) or %d
local step = math.max(1, math.floor(tonumber(cfg.step) or %d))
local gap = math.max(0, tonumber(cfg.every) or %f)
local lag = math.max(0, tonumber(cfg.lag) or %f)
local half = math.floor(step / 2)
-- The box each waypoint reads. Half a step covers the strip between two neighbouring
-- waypoints exactly; the margin is for the map's edge rows, where the axis stops short
-- of the border.
local box = half + 8
local axis = {}
local v = half
while v < size do axis[#axis+1] = v v = v + step end
local V3, tm = CS.UnityEngine.Vector3, TimerManager:GetInstance()
-- One member at a time and each read guarded: a point info is a C# object whose class
-- differs per kind, so a field the treasure class does not have would throw where a
-- missing value is wanted instead.
local function get(o, k)
  local ok, v = pcall(function() return o[k] end)
  if ok then return v end
  return nil
end
local function scrape(cx, cy)
  if DC.__lw_sweep_run ~= run then return end
  -- THE SCENE IS LOOKED UP AGAIN, not held. A WorldScene is replaced whenever the world
  -- is re-entered and a destroyed one answers `nil` to everything without throwing, so a
  -- lap that captured it at the start would read an empty map in silence — which is
  -- exactly what happened the first time this ran live (121 waypoints scheduled, 0 read).
  local scene = _G.WS
  local pm = scene and scene.PointManager
  if pm == nil then S.blind = (S.blind or 0) + 1 return end
  local x0, x1 = math.max(0, cx - box), math.min(size - 1, cx + box)
  local y0, y1 = math.max(0, cy - box), math.min(size - 1, cy + box)
  for ty = y0, y1 do
    local base = ty * size + 1
    for tx = x0, x1 do
      local ok, info = pcall(function() return pm:GetPointInfo(base + tx) end)
      if ok then
        S.tiles = S.tiles + 1
        -- HOW MANY OF THOSE THE CLIENT ACTUALLY KNEW, which is the difference between «no
        -- chest on the map» and «the lap ran over a client nobody was answering». `tiles`
        -- is only how many ids were asked about — it is the same number on a dead link.
        if info ~= nil then S.known = S.known + 1 end
        if info ~= nil and (tonumber(get(info, "PointType")) or -1) == %d then
          local uuid = get(info, "uuid")
          if uuid ~= nil and tostring(uuid) ~= "0" then
            local key = tostring(uuid)
            if S.found[key] == nil then
              S.chests = S.chests + 1
              -- `TreasurePointInfo`, read off the first chests ever scanned live
              -- (2026-08-08): `uuid`, `serverId`, `allianceId`, `allianceAbbr`,
              -- `expireTime`, `ownerUid`. Two of those matter here.
              --
              -- `ownerUid` is the wire's `f11.7` — the finisher — and it is READ AS A
              -- HINT rather than as a verdict, which is the difference that matters.
              -- Measured on the first live lap: 19 chests out of 19 carried it, and the
              -- one of them this account could reason about (its own alliance's) answered
              -- a claim with `errorCode 801348 — claim repeat`. So it does look like «this
              -- chest has been worked», but no chest has ever been caught WITHOUT it, and
              -- a gate needs a success recording (`CLAUDE.md`).
              --
              -- Read as a hint it cannot do harm: `dug` OPENS the claim, it does not close
              -- the march — a target with no squad out still goes to the «new» branch and
              -- marches first (see `treasure_auto_step`). Being wrong here costs one claim
              -- that the server answers with a code the run now prints. Being wrong the
              -- other way — writing a chest off as unworkable — would cost the chest.
              --
              -- `expireTime` is the chest's OWN deadline, in the game's milliseconds. It
              -- beats any age the errand could keep: a chest is worked until the map
              -- takes it away, and the map says when that is.
              local who = tostring(get(info, "ownerUid") or "")
              S.found[key] = {uuid = uuid, pid = base + tx, x = tx, y = ty,
                              server = tonumber(get(info, "serverId")) or srv,
                              expire = tonumber(get(info, "expireTime")) or 0,
                              owner = who,
                              alliance = tostring(get(info, "allianceId") or ""),
                              dug = (who ~= "" and who ~= "0")}
            end
          end
        end
      else
        S.errs = S.errs + 1
      end
    end
  end
  S.done = S.done + 1
end
local n = 0
for row = 1, #axis do
  local y = axis[row]
  for col = 1, #axis do
    local x = axis[(row %% 2 == 1) and col or (#axis - col + 1)]
    n = n + 1
    local at = (n - 1) * gap
    tm:DelayInvoke(function()
      if DC.__lw_sweep_run ~= run then return end
      pcall(function() GoToUtil.GotoWorldPos(V3(x*2+1, 0, y*2+1), height, 0, nil, srv) end)
    end, at)
    tm:DelayInvoke(function() pcall(scrape, x, y) end, at + lag)
  end
end
S.n = n
S.span = (n - 1) * gap + lag
CS.UnityEngine.Debug.LogError("ACT treasure_scan n="..n.." zoom="..height.." step="..step
  .." box="..box.." span="..string.format("%%.1f", S.span).." size="..tostring(size)
  .." srv="..tostring(srv))
''' % (where, height, stride, gap, float(lag), TREASURE_POINT_TYPE))


#: How far around the camera a look reads, in tiles. Not a view rect — the point manager
#: holds what the client has been ANSWERED about, which is a good deal more than the glass
#: shows and costs nothing extra to walk. A 121 × 121 box is the same size as one waypoint
#: of the old lap, measured at 0.03–0.04 s inside the VM.
TREASURE_LOOK_BOX = 60


def treasure_look_around() -> str:
    """Read the chests in what the client is ALREADY looking at. Moves nothing.

    THE LAP IS GONE AND THIS IS WHAT REPLACED IT (#1296). Walking the whole server every
    few minutes was measured and was not worth its camera: two full laps found 19 and 21
    chests, and **ours was zero both times** — a chest of one's own alliance is placed in
    the hive, not out on the open map, so 48 s of camera every five minutes bought a
    census of other people's treasure. What is worth keeping is the READING, which was
    never the expensive half: the client's own `WorldScene.PointManager` holds every tile
    it has been answered about, so a chest we drive past is a chest we can see for free.

    So this is the same scrape as the lap's, with the jumps taken out: one box around
    where the camera happens to be, whenever the errand ticks and the client is in the
    world. It never jumps, never changes the zoom and never touches the server — a person
    playing on the map notices nothing at all, which is the whole point of hanging it on
    an ordinary tick.

    Its findings land in `DataCenter.__lw_treasure_scan.found` exactly as the lap's did, so
    :func:`treasure_scan_harvest` reads it unchanged — and a chest seen twice stays one.
    `n`/`done` are 1: one box, read once.

    The manual lap (`actions/scan_treasures.md`) is still there for somebody who WANTS a
    census, and is off unless pressed.
    """
    return (FIND_WORLD_SCENE + '''
local S = {found = {}, n = 1, done = 0, tiles = 0, known = 0, chests = 0,
           errs = 0, blind = 0, span = 0, look = true}
DataCenter.__lw_treasure_scan = S
local world = false
pcall(function() world = SceneUtils.GetIsInWorld() and true or false end)
if not world then
  S.why = "not-in-world"
  CS.UnityEngine.Debug.LogError("ACT treasure_look not-in-world")
  return
end
local scene = _G.WS
local pm = scene and scene.PointManager
if pm == nil then
  S.blind, S.why = 1, "no-point-manager"
  CS.UnityEngine.Debug.LogError("ACT treasure_look no-point-manager")
  return
end
local size = 1000
pcall(function() size = scene.TileCount.x end)
-- WHERE THE CAMERA ALREADY IS. Not chosen, not moved to — read.
local cx, cy = -1, -1
pcall(function() cx, cy = scene.CurTilePos.x, scene.CurTilePos.y end)
cx, cy = math.floor(tonumber(cx) or -1), math.floor(tonumber(cy) or -1)
if cx < 0 or cy < 0 then
  S.why = "no-camera-tile"
  CS.UnityEngine.Debug.LogError("ACT treasure_look no-camera-tile")
  return
end
S.at_x, S.at_y = cx, cy
local srv = 0
pcall(function() srv = tonumber(LuaEntry.Player.serverId) or 0 end)
S.server = srv
local box = %d
local function get(o, k)
  local ok, v = pcall(function() return o[k] end)
  if ok then return v end
  return nil
end
local x0, x1 = math.max(0, cx - box), math.min(size - 1, cx + box)
local y0, y1 = math.max(0, cy - box), math.min(size - 1, cy + box)
for ty = y0, y1 do
  local base = ty * size + 1
  for tx = x0, x1 do
    local ok, info = pcall(function() return pm:GetPointInfo(base + tx) end)
    if ok then
      S.tiles = S.tiles + 1
      if info ~= nil then S.known = S.known + 1 end
      if info ~= nil and (tonumber(get(info, "PointType")) or -1) == %d then
        local uuid = get(info, "uuid")
        if uuid ~= nil and tostring(uuid) ~= "0" then
          local key = tostring(uuid)
          if S.found[key] == nil then
            S.chests = S.chests + 1
            local who = tostring(get(info, "ownerUid") or "")
            S.found[key] = {uuid = uuid, pid = base + tx, x = tx, y = ty,
                            server = tonumber(get(info, "serverId")) or srv,
                            expire = tonumber(get(info, "expireTime")) or 0,
                            owner = who,
                            alliance = tostring(get(info, "allianceId") or ""),
                            dug = (who ~= "" and who ~= "0")}
          end
        end
      end
    else
      S.errs = S.errs + 1
    end
  end
end
S.done, S.why = 1, "looked"
CS.UnityEngine.Debug.LogError("ACT treasure_look at=" .. tostring(cx) .. "," .. tostring(cy)
  .. " tiles=" .. tostring(S.tiles) .. " known=" .. tostring(S.known)
  .. " chests=" .. tostring(S.chests))
''' % (int(TREASURE_LOOK_BOX), TREASURE_POINT_TYPE))


def treasure_scan_state() -> str:
    """Lua *expression* -> how far the lap has got and what it has found so far.

    ``done=<n>/<n> chests=<n> tiles=<n> span=<s> errs=<n>`` — a reading, so a recipe can
    say whether it waited long enough instead of assuming it did. `done` short of `n`
    means the lap is still walking (or was stopped); `tiles` is how many point ids were
    looked at, which is the difference between «no chest on the map» and «the point
    manager answered nothing at all».
    """
    return (
        "(function() local S = DataCenter.__lw_treasure_scan "
        "if S == nil then return 'no lap has been run' end "
        "local c = 0 for _ in pairs(S.found or {}) do c = c + 1 end "
        "return 'done=' .. tostring(S.done or 0) .. '/' .. tostring(S.n or 0) "
        ".. ' chests=' .. tostring(c) "
        ".. ' tiles=' .. tostring(S.tiles or 0) "
        ".. ' known=' .. tostring(S.known or 0) "
        ".. ' blind=' .. tostring(S.blind or 0) "
        ".. ' span=' .. string.format('%.1f', tonumber(S.span) or 0) "
        ".. ' errs=' .. tostring(S.errs or 0) end)()"
    )


def treasure_scan_harvest() -> str:
    """Turn what the lap found into targets of the auto errand — the third door.

    THREE DOORS, ONE LIST. A chest that arrives twice is one target and keeps whichever
    half of the truth each door has: the dig feed brings a uuid and no tile (`claim_only`),
    and this brings the tile — so a target already queued without one is UPGRADED here
    rather than duplicated, and stops being claim-only the moment a squad can be sent to
    it. `A.seen` is not consulted for that: it remembers uuids the hook has already turned
    into targets, and a chest still on the map is worth marching at whether or not the
    hook heard of it first.

    A CHEST BELONGS TO AN ALLIANCE, and this is where the lap earns its keep. The first
    live lap found nineteen chests on the map and the account could take none of them:
    the claims came back `errorCode 801354 — player not in same alliance`. A detect-event
    treasure is placed by ONE alliance's event and dug by ITS members, so a chest whose
    `allianceId` is not this player's is not a chest this player has, however plainly it
    is drawn on the map. They are counted as `foreign=` and never queued — a march at one
    spends a squad on a tile the server will not pay for.

    **AND THE THREE NUMBERS ARE SAID SEPARATELY, ALWAYS.** «Found 19» on its own is a
    promise of nineteen gifts, and eighteen of those nineteen are somebody else's chest
    that this account cannot touch — so the report leads with `found=` / `ours=` /
    `foreign=` and never with a single total. A number that does not distinguish two
    states is worse than no number: it reads as good news and is not.

    Nothing is sent from here. The step that follows is the one that marches and claims.
    """
    return (
        "local S = DataCenter.__lw_treasure_scan "
        "local D = DataCenter "
        "if not D.__lw_treasure_auto then D.__lw_treasure_auto = "
        "{seen={}, targets={}, news=0} end "
        "local A = D.__lw_treasure_auto "
        "local now = 0 pcall(function() "
        "now = math.floor(tonumber(UITimeManager.Instance:GetServerTime()) or 0) end) "
        "if now <= 0 then pcall(function() "
        "now = math.floor((tonumber(ChatInterface.getServerTime()) or 0) * 1000) end) end "
        "local mine = '' "
        "pcall(function() mine = tostring(LuaEntry.Player.allianceId or '') end) "
        "local fresh, grown, known, foreign = 0, 0, 0, 0 "
        "for key, f in pairs((S or {}).found or {}) do "
        "if mine ~= '' and tostring(f.alliance or '') ~= '' "
        "and tostring(f.alliance) ~= mine then foreign = foreign + 1 "
        "else "
        "local seen_here = nil "
        "for _, t in ipairs(A.targets or {}) do "
        "if tostring(t.uuid) == key then seen_here = t end end "
        "if seen_here ~= nil then "
        # The tile is the thing this door has and the others may not. A target parked by
        # the dig feed carries a uuid and zeros; filling those in is what turns it from
        # «claim it and hope» into «march on it».
        "if (tonumber(seen_here.pid) or 0) == 0 then "
        "seen_here.pid, seen_here.x, seen_here.y = f.pid, f.x, f.y "
        "seen_here.server = tonumber(f.server) or seen_here.server "
        "seen_here.claim_only = false "
        "seen_here.src = tostring(seen_here.src or '?') .. '+scan' "
        "grown = grown + 1 "
        "else known = known + 1 end "
        "else "
        "A.seen = A.seen or {} A.seen[key] = A.seen[key] or now "
        "A.targets = A.targets or {} "
        "A.targets[#A.targets+1] = {uuid = f.uuid, pid = f.pid, x = f.x, y = f.y, "
        "server = tonumber(f.server) or 0, at = now, src = 'scan', "
        "expire = tonumber(f.expire) or 0, "
        "dug = (f.dug and now or nil)} "
        "A.news = (A.news or 0) + 1 "
        "fresh = fresh + 1 end end end "
        "local looked = tonumber((S or {}).tiles) or 0 "
        "local ours = fresh + grown + known "
        "A.scan_at = now "
        # The three numbers, kept as numbers as well as said in a sentence — the panel
        # draws them apart from each other and must not have to parse a line to do it.
        "A.scan_found = ours + foreign "
        "A.scan_ours = ours "
        "A.scan_foreign = foreign "
        "A.scan_report = 'found=' .. tostring(ours + foreign) "
        ".. ' ours=' .. tostring(ours) .. ' foreign=' .. tostring(foreign) "
        ".. ' (new=' .. tostring(fresh) .. ' upgraded=' .. tostring(grown) "
        ".. ' already-queued=' .. tostring(known) .. ')' "
        ".. ' waypoints=' .. tostring((S or {}).done or 0) "
        ".. '/' .. tostring((S or {}).n or 0) "
        ".. ' tiles=' .. tostring(looked) "
        ".. ' known=' .. tostring(tonumber((S or {}).known) or 0) "
        # The chests still to be worked — NOT the length of the list, which also holds the
        # ones already spent and kept only so the next lap does not start them over.
        ".. ' queued=' .. tostring((function() local n = 0 "
        "for _, t in ipairs(A.targets or {}) do if not t.done then n = n + 1 end end "
        "return n end)()) "
        'CS.UnityEngine.Debug.LogError("ACT treasure_scan_harvest " .. A.scan_report)'
    )


def treasure_scan_report() -> str:
    """Lua *expression* -> the sentence the last harvest wrote."""
    return ("(DataCenter.__lw_treasure_auto and "
            "DataCenter.__lw_treasure_auto.scan_report "
            "or 'no lap has been harvested')")


def treasure_scan_counts() -> str:
    """Lua *expression* -> `found=<n> ours=<n> foreign=<n> queued=<n> ago=<s>`.

    THE SPLIT IS THE POINT. A lap of a live map found nineteen chests and eighteen of
    them belonged to other alliances, which the server refuses outright — so a screen or
    a log line saying «19 found» promises nineteen gifts and delivers one. This is what
    the panel draws, and it draws the three numbers apart.

    `ago` is seconds since the last lap on the GAME's clock, or `-1` when none has been
    walked in this client — the same distinction: «none found» and «never looked» are
    different answers and must not share a zero.
    """
    return (
        "(function() local A = DataCenter.__lw_treasure_auto "
        "if A == nil or (tonumber(A.scan_at) or 0) <= 0 then "
        "return 'found=0 ours=0 foreign=0 queued=0 ago=-1' end "
        "local now = 0 pcall(function() "
        "now = math.floor(tonumber(UITimeManager.Instance:GetServerTime()) or 0) end) "
        "local ago = -1 "
        "if now > 0 then ago = math.floor((now - A.scan_at) / 1000) end "
        "return 'found=' .. tostring(tonumber(A.scan_found) or 0) "
        ".. ' ours=' .. tostring(tonumber(A.scan_ours) or 0) "
        ".. ' foreign=' .. tostring(tonumber(A.scan_foreign) or 0) "
        ".. ' queued=' .. tostring(#(A.targets or {})) "
        ".. ' ago=' .. tostring(ago) end)()"
    )


def treasure_scan_ask(every_sec: int = TREASURE_SCAN_EVERY_SEC) -> str:
    """Decide whether a lap is worth walking right now, and park the answer.

    `DataCenter.__lw_treasure_scan_due` becomes `1` or `0`, which is what the recipe
    reads: a `TAP` returns nothing, and the rule belongs here rather than copied into a
    recipe where it would drift from this one.

    Three questions, all local and all cheap, because this is asked on the errand's own
    tick and a lap that cannot help must not cost one:

      * is the client in the WORLD? The point manager belongs to the world scene, and a
        lap started from the city would move the camera out from under whoever is
        looking at their base;
      * has `every_sec` passed since the last lap? A chest is out for minutes, so the
        map is worth re-reading in minutes and not in seconds;
      * is the client answering at all? Without the game's own clock there is no telling
        one lap from the next, and a lap walked on a client that is loading is a camera
        thrown across a map nobody is connected to.

    A queue that already has chests in it is NOT a reason to skip: a chest placed a
    minute ago is exactly what the lap is for, and the errand works several at once.

    The period is `DataCenter.__lw_treasure_scan_cfg.every` when the recipe parked one,
    and `every_sec` otherwise. **Deciding it is due STAMPS the clock**, so a tick that
    asks twice does not walk two laps — and a lap that then fails to start still costs
    the period rather than being retried every ten seconds.
    """
    return (
        "local D = DataCenter "
        "local cfg = D.__lw_treasure_scan_cfg or {} "
        "local every = math.max(0, tonumber(cfg.every_sec) or "
        + str(int(every_sec)) + ") "
        "local world = false "
        "pcall(function() world = SceneUtils.GetIsInWorld() and true or false end) "
        "local now = 0 pcall(function() "
        "now = math.floor(tonumber(UITimeManager.Instance:GetServerTime()) or 0) end) "
        "local A = D.__lw_treasure_auto "
        "local last = tonumber(A and A.scan_at) or 0 "
        "local why = 'due' "
        "local due = 1 "
        "if not world then due, why = 0, 'not-in-world' "
        "elseif now <= 0 then due, why = 0, 'no-game-clock' "
        "elseif every <= 0 then due, why = 0, 'switched-off' "
        "elseif last > 0 and now - last < every * 1000 then due, why = 0, "
        "'last-lap-' .. tostring(math.floor((now - last) / 1000)) .. 's-ago' end "
        "if due == 1 and A ~= nil then A.scan_at = now end "
        "D.__lw_treasure_scan_due = due "
        'CS.UnityEngine.Debug.LogError("ACT treasure_scan_due " .. tostring(due) '
        '.. " " .. why .. " every=" .. tostring(every))'
    )


# --------------------------------------------------------------------------
# Hospital — heal wounded soldiers ("Лечение юнитов")
# --------------------------------------------------------------------------
# The base hospital (`LWUIHospital`, view `LWUIHospitalView`) heals wounded soldiers.
# One press of its cure button sends ONE message — the wire shape captured in
# `20260729_152749` / `20260729_152841`, the caller side read off the live VM
# (docs/research/hospital-heal.md):
#
#     SFSNetwork.SendMessage(MsgDefines.HospitalCure, {      -- "hospital.cure"
#         armyArray = { {armyId = <string>, count = <int>}, ... },
#         gold      = 0,           -- gold spent on the heal (0 = the free heal)
#     })
#
# The message class `HospitalCureMessage` renames the per-entry `count` to `healNum`
# on the wire (`PutUtfString(armyId, tostring(one.armyId))` + `PutInt(healNum, …)`),
# which is why the trace shows `healNum` and the caller passes `count`. `gold` is NOT
# optional (the serialiser packs it as an int; a missing one aborts the send with
# "bad argument #2 to 'pack'"), and `worldType` the class fills in itself.
#
# Do NOT add `goldForTime` / `goldForResource` / `itemIds`: they belong to the
# pay-to-finish branch, and passing them even as 0/"" makes `OnCreate` skip `armyArray`
# altogether, so the server answers errorCode E000000 and nothing heals. The recorded
# human press (20260729_182527, no dedup) puts exactly armyArray + gold + worldType.
#
# The wounded list is `DataCenter.HospitalManager.allHospital`, keyed by armyId. A row
# carries exactly three server fields (`HospitalInfo`: armyId, heal, dead):
#
#     allHospital[3014] = {armyId = 3014, dead = 365, heal = 0}
#       -- dead : wounded of that type waiting in the hospital — the pool to heal
#       -- heal : how many of them are already in treatment
#
# (`curCount`, if present, is NOT from the server: the window stamps its own suggested
# amount onto the row — the slice of the wounded that fits the player's chosen cure
# time. Reading it as the wounded count gives a number that is only there after the
# window has been opened, which is why the heal is built from `dead`.)
#
# so the whole thing runs headless — no window is opened.
def _hospital_army_literal(entries) -> str:
    """Render `[(armyId, count), ...]` as the Lua `armyArray` table literal.

    armyId is forced to a string (UtfString on the wire), the count to an int.
    """
    parts = []
    for army_id, count in entries:
        parts.append('{armyId="%s",count=%d}' % (str(army_id), int(count)))
    return "{" + ",".join(parts) + "}"


# `SFSNetwork.SendMessage("hospital.cure", param)` CANNOT be used for this message.
# `HospitalCureMessage:OnCreate` silently declines to build `armyArray` from a param
# handed to it that way — the message goes out with only `gold` + `worldType`, and the
# server answers `errorCode E000000` (verified live many times, with every spelling of
# the entry fields, on a clean VM, with and without the hospital window open).
#
# What works is to build the message and hand it to the transport directly — which is
# all `SendMessage` itself does, minus the OnCreate step we cannot make cooperate:
#
#     local cls = GetMsgType("hospital.cure")     -- both live in SendMessage's upvalues
#     local msg = cls:NewMessage({gold = 0})      -- fills gold + worldType
#     ... build the SFSArray of {armyId, healNum} by hand ...
#     msg.sfsObj:PutSFSArray("armyArray", arr)
#     Network:SendLuaMessage("hospital.cure", msg:ToBinary())
#
# The command name is required as the first argument — `SendLuaMessage(bin)` alone is
# accepted by the client and never reaches the server. Proven live 2026-07-29: the
# server replied `{_id, _time, gold, hospitalArray, queue, resource}` (no errorCode) and
# 3013 moved dead=39 -> dead=34, heal=5.
_HOSPITAL_TRANSPORT = (
    "local __f = SFSNetwork.SendMessage local __GMT, __NET local __i = 1 "
    "while true do local n, v = debug.getupvalue(__f, __i) if not n then break end "
    "if n == 'GetMsgType' then __GMT = v end "
    "if n == 'Network' then __NET = v end __i = __i + 1 end "
    "if not (__GMT and __NET) then error('hospital: transport not found') end "
    "local __cure = function(army) "
    "if #army == 0 then error('no wounded soldiers') end "
    "local cls = __GMT('hospital.cure') "
    "local msg = cls:NewMessage({gold = 0}) "
    "local arr = SFSArray.New() "
    "for _, e in ipairs(army) do "
    "local o = SFSObject.New() "
    "o:PutUtfString('armyId', tostring(e[1])) "
    "o:PutInt('healNum', math.floor(e[2])) "
    "arr:AddSFSObject(o) end "
    "msg.sfsObj:PutSFSArray('armyArray', arr) "
    "__NET:SendLuaMessage('hospital.cure', msg:ToBinary()) "
    "return #army end "
)


def hospital_cure(entries) -> str:
    """Heal the given soldier types in one `hospital.cure`.

    `entries` is an iterable of `(armyId, count)` pairs — the faithful, parameterised
    reproduction of the in-game press, for when the caller already knows which types to
    heal and how many of each. `gold` goes out as 0: the free heal.
    """
    entries = list(entries)
    army = "{" + ",".join('{"%s",%d}' % (str(a), int(c)) for a, c in entries) + "}"
    return ('local ok,err = pcall(function() %s __cure(%s) end) '
            'CS.UnityEngine.Debug.LogError("ACT hospital_cure entries=%d ok="..tostring(ok)'
            '..(ok and "" or (" err="..tostring(err))))'
            % (_HOSPITAL_TRANSPORT, army, len(entries)))


def hospital_wounded_count() -> str:
    """Lua *expression* -> how many soldier types currently have wounded to heal.

    Counts `DataCenter.HospitalManager.allHospital` rows with a positive `dead` — the
    same rows the hospital window lists. Returns 0 when the manager is not loaded yet,
    so the gate reads as a safe "nothing to heal" rather than an error.
    """
    return ("(function() "
            "local m = DataCenter and DataCenter.HospitalManager "
            "if not m or type(m.allHospital) ~= 'table' then return 0 end "
            "local n = 0 "
            "for _, h in pairs(m.allHospital) do "
            "if type(h)=='table' and type(h.dead)=='number' and h.dead > 0 then n = n + 1 end end "
            "return n end)()")


def hospital_wounded_total() -> str:
    """Lua *expression* -> how many wounded soldiers are lying in the hospital.

    The SUM of `dead` across the rows `hospital_wounded_count()` merely counts, which
    is the number a person reads ("681 раненых") rather than the three or four soldier
    types they are spread over. A gate wants the count — one press heals every type at
    once — so this one is for display only.
    """
    return ("(function() "
            "local m = DataCenter and DataCenter.HospitalManager "
            "if not m or type(m.allHospital) ~= 'table' then return 0 end "
            "local n = 0 "
            "for _, h in pairs(m.allHospital) do "
            "if type(h)=='table' and type(h.dead)=='number' and h.dead > 0 then n = n + h.dead end end "
            "return n end)()")


def hospital_heal_all() -> str:
    """Heal EVERY wounded soldier type in one `hospital.cure`.

    Builds the armyArray from `DataCenter.HospitalManager.allHospital` — one entry per
    type with `dead > 0`, healing the whole batch of each. That is more than the window
    pre-fills (it suggests only as many as fit the player's chosen cure time), and it is
    what "heal them all" means. Sends nothing (a logged no-op) when nothing is wounded.

    """
    return (
        "local ok,err = pcall(function() "
        + _HOSPITAL_TRANSPORT +
        "local m = DataCenter and DataCenter.HospitalManager "
        "if not m or type(m.allHospital) ~= 'table' then error('HospitalManager not loaded') end "
        "local army = {} "
        "for _, h in pairs(m.allHospital) do "
        "if type(h)=='table' and h.armyId and type(h.dead)=='number' and h.dead > 0 then "
        "army[#army+1] = {tostring(h.armyId), math.floor(h.dead)} end end "
        "__cure(army) "
        'CS.UnityEngine.Debug.LogError("ACT hospital_heal_all types="..#army) '
        "end) "
        'if not ok then CS.UnityEngine.Debug.LogError("ACT hospital_heal_all skip: "..tostring(err)) end'
    )


def hospital_collect() -> str:
    """Collect the healed soldiers — the game's own "receive" press, headless.

    The window's receive button is `HospitalManager:CheckSendFinish(buildUuid)`, which
    does all of the gating itself: it only sends `queue.finish` when the hospital queue
    has actually reached the Finish state, and it refuses (with the game's own tip) when
    the soldiers would overflow the barracks. So this is safe to press at any time — a
    heal still running costs one no-op call.
    """
    return (
        "local ok,err = pcall(function() "
        "local m = DataCenter and DataCenter.HospitalManager "
        "if not m or not m.CheckSendFinish then error('HospitalManager not loaded') end "
        "m:CheckSendFinish(m:GetCurHospitalBuildUuid()) "
        'CS.UnityEngine.Debug.LogError("ACT hospital_collect pressed") '
        "end) "
        'if not ok then CS.UnityEngine.Debug.LogError("ACT hospital_collect skip: "..tostring(err)) end'
    )


def hospital_healed_ready() -> str:
    """Lua *expression* -> 1 when a finished heal is waiting to be collected, else 0.

    The hospital queue (`NewQueueType.Hospital`) reaches `NewQueueState.Finish` (3) when
    its timer runs out; until then collecting is a no-op, so this is what gates the
    `collect_healed` press.
    """
    return ("(function() "
            "local q = DataCenter and DataCenter.QueueDataManager "
            "if not q or not NewQueueType or not NewQueueState then return 0 end "
            "local ok, queue = pcall(function() return q:GetQueueByType(NewQueueType.Hospital) end) "
            "if not ok or type(queue) ~= 'table' then return 0 end "
            "if queue.state == NewQueueState.Finish then return 1 end "
            "return 0 end)()")


def hospital_wounded_probe() -> str:
    """Dump the hospital's own wounded list — one line per soldier type.

    Prints `DataCenter.HospitalManager.allHospital` (armyId, dead, heal) plus the
    hospital queue's state and how many building queues are free, which together are
    everything the heal and the collect press depend on. Handy to confirm before/after a
    heal that the counts actually moved, and to tell a rejected heal from a busy base.
    """
    return (
        "local L=function(s) CS.UnityEngine.Debug.LogError('HOSP '..tostring(s)) end "
        "pcall(function() "
        "local m = DataCenter and DataCenter.HospitalManager "
        "if not m or type(m.allHospital) ~= 'table' then L('HospitalManager not loaded') return end "
        "local rows = {} "
        "for id, h in pairs(m.allHospital) do "
        "rows[#rows+1] = tostring(id)..': dead='..tostring(h.dead)..' heal='..tostring(h.heal) end "
        "table.sort(rows) "
        "for _, r in ipairs(rows) do L(r) end "
        "local q = DataCenter.QueueDataManager:GetQueueByType(NewQueueType.Hospital) "
        "L('queue state='..tostring(q and q.state)..' endTime='..tostring(q and q.endTime)"
        "..' helpNum='..tostring(q and q.helpNum)) "
        "L('free build queues='..tostring(%s)) "
        "end)" % free_build_queues()
    )


# --------------------------------------------------------------------------
# Ask the alliance to speed a queue up ("Запрос помощи")
# --------------------------------------------------------------------------
# A press of its own, positional arguments — NOT a param table
# (recording 20260729_182527, docs/research/hospital-heal.md §4):
#
#     SFSNetwork.SendMessage(MsgDefines.AllianceCallHelp, uuid, 1, qType, "1")
#       -> PutLong(uuid, <queue uuid>)  PutInt(type, 1)
#          PutInt(qType, <queue type>)  PutUtfString(itemId, "1")
#
# `itemId` MUST be a string: passing the number 1 dies in the serialiser with
# "attempt to get length of a number value" before the message leaves the client. The
# trace cannot tell the two apart — it prints both as `1`.
#
# `qType` is the queue's own `type` (3 = Hospital), so the same message asks for help on
# any queue. `isHelped` on the queue is the state: 0 = no request standing, 1 = asked.
# Gating on it keeps a repeat run from re-asking, and it is what flips after a successful
# send (proven live: hospital queue isHelped 0 -> 1, allies answered within seconds).
def alliance_call_help_all() -> str:
    """Ask the alliance to speed up every working queue that has no request standing."""
    return (
        "local ok,err = pcall(function() "
        "local q = DataCenter and DataCenter.QueueDataManager "
        "if not q or type(q.queueDic) ~= 'table' or not NewQueueState then "
        "error('QueueDataManager not loaded') end "
        "local n = 0 "
        "for _, v in pairs(q.queueDic) do "
        "if type(v)=='table' and v.state == NewQueueState.Work and v.isHelped ~= 1 then "
        "SFSNetwork.SendMessage(MsgDefines.AllianceCallHelp, v.uuid, 1, v.type, '1') "
        "n = n + 1 end end "
        'CS.UnityEngine.Debug.LogError("ACT alliance_call_help_all asked="..n) '
        "end) "
        'if not ok then CS.UnityEngine.Debug.LogError("ACT alliance_call_help_all skip: "..tostring(err)) end'
    )


def queues_needing_help() -> str:
    """Lua *expression* -> how many working queues have no help request standing."""
    return ("(function() "
            "local q = DataCenter and DataCenter.QueueDataManager "
            "if not q or type(q.queueDic) ~= 'table' or not NewQueueState then return 0 end "
            "local n = 0 "
            "for _, v in pairs(q.queueDic) do "
            "if type(v)=='table' and v.state == NewQueueState.Work and v.isHelped ~= 1 then "
            "n = n + 1 end end "
            "return n end)()")


def free_build_queues() -> str:
    """Lua *expression* -> how many building queues (`NewQueueType.Default`) are idle.

    Diagnostic only. A heal does NOT need one: a recorded human press went through with
    all four Default queues working, which retired the earlier «Очередь на строительство
    заполнена» theory (docs/research/hospital-heal.md §5).
    """
    return ("(function() "
            "local q = DataCenter and DataCenter.QueueDataManager "
            "if not q or type(q.queueDic) ~= 'table' or not NewQueueType or not NewQueueState then return 0 end "
            "local n = 0 "
            "for _, v in pairs(q.queueDic) do "
            "if type(v)=='table' and v.type == NewQueueType.Default and v.state == NewQueueState.Free then "
            "n = n + 1 end end "
            "return n end)()")


# --------------------------------------------------------------------------
# Alliance rally: join the live ones, one squad each
# --------------------------------------------------------------------------
# «Присоединиться к ралли». The engine side is `tools/rally_join.py` and
# `docs/research/rally-join.md`; this is the same thing as a pressable button so a
# recipe (and therefore a timer) can do it.
#
#   * a rally is a world march with `teamUuid ~= 0`; its LEADER is the march whose
#     `uuid == teamUuid - 1`, and that leader carries the join parameters
#     (`teamUuid`, `targetPos`, `serverId`);
#   * joining is `MarchUtil.SendCreateMarchMessage(formationUuid, 6, targetPos,
#     teamUuid, 1, 1, false, server, nil)`, scheduled on the main thread;
#   * WHICH squad goes is the first argument: the formation whose `index` is the
#     slot the player sees (1/2/3), read live off
#     `DataCenter.ArmyFormationDataManager.ArmyFormationList`;
#   * the send silently no-ops while every formation is COLD (`totalSoldierNum`
#     0). `MarchUtil.OnClickStartMarch` warms them but opens the dispatch panel,
#     so it is followed by `GoToUtil.CloseAllWindows()` — the game's own close,
#     not `DestroyAllWindow` (that one kills the HUD). Already warm -> no UI at all.
#
# One press = one squad -> one rally, so a recipe says `TAP join_rally xall` and
# the squads parked in `DataCenter.__lw_rally_squads` are spent one per rally.
# Two things are excluded from the candidates, which is what makes "squads 2 and 3
# join TWO DIFFERENT rallies" true rather than hopeful:
#   * rallies the player already has a march in (`GetOwnerMarches`), and
#   * rallies joined by an earlier press in this same run
#     (`DataCenter.__lw_rally_joined`) — the server's own reply takes seconds to
#     arrive, so waiting for it would let the next press pick the same rally again.

# Shared prelude: `squads` (the parked queue, default 1/2/3), and `rallies` — the
# joinable ones, ordered by team uuid so the pick is stable between two calls.
_RALLY_PRELUDE = (
    "local wm=DataCenter.WorldMarchDataManager "
    "local function g(mo,k) local ok,v=pcall(function() return mo[k] end) "
    "if ok then return v end return nil end "
    # A dictionary enumerator yields KeyValuePairs, a list one yields the item —
    # take .Value when there is one.
    "local function cur(e) local mo=e.Current local ok,v=pcall(function() return mo.Value end) "
    "if ok and v~=nil then return v end return mo end "
    "local taken=DataCenter.__lw_rally_joined or {} "
    "local om=wm:GetOwnerMarches() "
    "if om then local e=om:GetEnumerator() while e:MoveNext() do local mo=cur(e) "
    "local t=g(mo,'teamUuid') if t~=nil and tostring(t)~='0' then taken[tostring(t)]=true end "
    "end end "
    "local rallies={} local col=wm:GetAllMarches() "
    "if col then local e=col:GetEnumerator() while e:MoveNext() do local mo=cur(e) "
    "local team=g(mo,'teamUuid') local ts=tostring(team) "
    "if team~=nil and ts~='0' and ts~='nil' and not taken[ts] then "
    "local lead=false pcall(function() lead=(tostring(g(mo,'uuid'))==tostring(team-1)) end) "
    # TWO PLACES, AND THEY ARE NOT THE SAME PLACE. `point` is where the rally is GOING
    # — the monster — and it is what a listing should show. `joinpoint` is where a
    # JOINER marches: the troops gather at the base of whoever raised the banner and
    # set off from there together, so a join ends at the leader's own tile (`startPos`,
    # `homePos` behind it). Every member march of every rally read live says the same:
    # its `targetPos` is the leader's tile and its `homePos` is the member's own base.
    #
    # Sending the monster made the client fly the camera to the monster and the server
    # refuse the march as «invalid end point» — the destination was real, it just was
    # not a place a joining squad may be sent to. The player spotted it from the camera:
    # joining by hand moves the view to the PLAYER doing the rallying, the bot's press
    # moved it to the monster.
    "if lead then rallies[#rallies+1]={team=team,point=g(mo,'targetPos'),"
    "joinpoint=(g(mo,'startPos') or g(mo,'homePos') or g(mo,'targetPos')),"
    "server=(g(mo,'serverId') or g(mo,'targetServer'))} end "
    "end end end "
    "table.sort(rallies,function(a,b) return tostring(a.team)<tostring(b.team) end) "
    "local squads=DataCenter.__lw_rally_squads or {1,2,3} "
)


# OURS, NOT EVERY BANNER ON THE MAP. `GetAllMarches()` returns every march the client
# can see, and a rally belonging to another alliance cannot be joined at all — the
# server refuses it, which is the «invalid end point» the player was shown and which
# cost this ability weeks of looking in the wrong place (#1237). The marches carry
# `allianceName`; the PLAYER does not, and no alliance manager on the client will hand
# it over — so it is learned from any march of our own on the map (`ownerUid == P.uid`)
# and remembered, because there are minutes when we have none out and the answer must
# not go with them.
#
# Learned and not configured, deliberately: an alliance name typed into a setting is one
# more thing to be wrong after a merge or a rename, and it would be an account's own
# identifier living in a file (`CLAUDE.md`).
_RALLY_MINE = (
    "local P = LuaEntry.Player "
    "if col then local e2 = col:GetEnumerator() while e2:MoveNext() do local m2 = cur(e2) "
    "local u, an = nil, nil "
    "pcall(function() u = tostring(m2.ownerUid) an = tostring(m2.allianceName) end) "
    "if u == tostring(P.uid) and an ~= nil and an ~= '' and an ~= 'nil' then "
    "DataCenter.__lw_my_alliance = an end end end "
    "local mine = DataCenter.__lw_my_alliance "
)

#: The prelude the JOIN side uses: every rally out, narrowed to this alliance's. Kept
#: apart from `_RALLY_PRELUDE` because the monitor's listing wants what is on the map,
#: the whole map — «who is rallying right now» is a different question from «what may I
#: join». Falls open when the alliance could not be learned: a gate that cannot see must
#: not refuse (the same rule the squad sieve follows), and a press at a rally we cannot
#: join costs one refusal rather than a missed one.
_RALLY_PRELUDE_MINE = (
    _RALLY_PRELUDE + _RALLY_MINE +
    "local ours = {} "
    "if col and mine then local e3 = col:GetEnumerator() while e3:MoveNext() do "
    "local m3 = cur(e3) local t3, n3 = nil, nil "
    "pcall(function() t3 = m3.teamUuid n3 = tostring(m3.allianceName) end) "
    "if t3 ~= nil and tostring(t3) ~= '0' and n3 == mine then ours[tostring(t3)] = true end "
    "end end "
    "if mine ~= nil then local kept = {} "
    "for _, r in ipairs(rallies) do if ours[tostring(r.team)] then kept[#kept+1] = r end end "
    "rallies = kept end "
    # On the JOIN side `point` IS the gathering tile: everything downstream of this
    # prelude sends a squad, and a squad marches to the leader's base (see `joinpoint`
    # in `_RALLY_PRELUDE`). The listing side keeps the two apart and shows the monster.
    "for _, r in ipairs(rallies) do if r.joinpoint ~= nil then r.point = r.joinpoint end end "
)


def rally_squads_set(squads) -> str:
    """Park the squad slots a run may spend, and forget the previous run's joins."""
    slots = ",".join(str(int(s)) for s in squads)
    return ("DataCenter.__lw_rally_squads={%s} DataCenter.__lw_rally_joined={} "
            'CS.UnityEngine.Debug.LogError("ACT rally_squads_set {%s}")' % (slots, slots))


def rally_joins_pending() -> str:
    """Lua *expression* -> presses `join_rally` can still make.

    `min(squads still parked, rallies not already joined)` — so `xall` stops both
    when the squads run out and when there is no fresh rally left, and is a clean
    no-op when the map is quiet.
    """
    return ("(function() %s "
            "if #squads<#rallies then return #squads end return #rallies end)()"
            % _RALLY_PRELUDE)


def rally_joinable_count() -> str:
    """Lua *expression* -> how many rallies are out that this account is not in.

    The press's own gate is `min(squads, rallies)`; this is the rallies half on its
    own, so a recipe can tell «there was nothing to join» from «there was, and the
    join did not happen». Those are the two endings that used to look identical, and
    the second one is a fault while the first is an ordinary quiet minute.
    """
    return "(function() %s return #rallies end)()" % _RALLY_PRELUDE_MINE


def rally_day_count() -> str:
    """Lua *expression* -> `"<done> <max>"` — the day's rallies, as the GAME counts them.

    `DataCenter.MonsterManager` keeps the account's own daily rally-boss counter and the
    threshold beside it — `daily_kill_boss` / `kill_boss_max_num`, reached through
    `GetKillBossNum()` and `GetMaxKillBossNum()` (docs/research/rally-join.md, «The game
    keeps the count itself»). It is per ACCOUNT, kept by the server and reset on the
    server's own day, which is why nothing here counts anything and no PC clock is
    consulted.

    It counts a rally that FINISHED and paid, so it lags the joins in flight by however
    many squads are out — measured live at 275 against 320 joins the panel had recorded
    over the same day. That is the honest limit of it and it is the number the ceiling is
    judged against all the same, because it is the only one the game keeps
    (`rally_join_all`, #1317).

    `"-1 -1"` when the manager cannot be reached — «unreadable», never «none today».
    """
    return ("(function() local a, b = -1, -1 "
            "pcall(function() local MM = DataCenter.MonsterManager "
            "a = MM:GetKillBossNum() b = MM:GetMaxKillBossNum() end) "
            "return tostring(math.floor(tonumber(a) or -1)) .. ' ' .. "
            "tostring(math.floor(tonumber(b) or -1)) end)()")


def server_day_end() -> str:
    """Lua *expression* -> the ms at which the SERVER's day turns, or 0.

    `UITimeManager:GetInstance():GetTomorrowZero()` — the client's own answer, and the
    only honest one: the boundary is 02:00 UTC on the warzone this was measured on
    (#1188) and there is nothing that says every warzone shares it. Anything a daily
    budget of ours resets on is judged against this rather than against a date the PC
    works out for itself (#1317).
    """
    return ("(function() local v = 0 "
            "pcall(function() v = UITimeManager:GetInstance():GetTomorrowZero() end) "
            "return math.floor(tonumber(v) or 0) end)()")


def rally_joined_count() -> str:
    """Lua *expression* -> how many of OUR squads are standing in a rally right now.

    Read before the press and again after it, and the difference is the only honest
    answer to «did that do anything». The press cannot answer it for itself: the send
    is scheduled onto the game's own timer and returns before the server has replied,
    so a press that «worked» and a press that vanished return exactly the same thing
    (docs/research/rally-join.md).
    """
    return ("(function() local P=LuaEntry.Player "
            "local wm=DataCenter.WorldMarchDataManager "
            "local afd=DataCenter.ArmyFormationDataManager local n=0 "
            "for _,f in pairs(afd.ArmyFormationList) do pcall(function() "
            "local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) "
            "if m~=nil and tostring(m.teamUuid)~=\"0\" then n=n+1 end end) end "
            "return n end)()")


def rally_join_all() -> str:
    """Join EVERY rally that can be joined right now — sieve, pair and send, in ONE chunk.

    THE WHOLE ABILITY IN A SINGLE CALL, and the reason is a measurement rather than a
    taste for short code. A call into the game VM cost **1.3 s at best and 10–19 s under
    the panel's ordinary background load** on the live client (task #1281,
    `tools/dev/rally_latency.py`; the client itself was at 59 fps, so none of it is the
    game's). The recipe this replaces took EIGHT readings before it sent anything —
    measured at 100 s to the send, twice over — and a banner during an event is gone in
    a fraction of that. Everything that used to be a reading is now a local variable:

      * which rallies are out that belong to this alliance and we are not already in
        (`_RALLY_PRELUDE_MINE`);
      * which of the parked squads are standing at home, idle, and have soldiers;
      * the pairing, one squad per rally, in the order both arrived;
      * the send itself, the same `SendCreateMarchMessage` the game's own squad screen
        ends at (`rally_join_send` — the type is the SECOND argument, #1277);
      * and the count of our squads standing in rallies BEFORE any of it, so the recipe
        can prove afterwards that the map moved.

    THE DOORS ARE HERE TOO, for the same reason: a check in front of this chunk is a
    second call on the one path measured in fractions of a second. The day's ceiling
    against the game's own counter (`__lw_rally_cap` → `-4`), the per-kind budgets and
    the kind filter the panel parks, and the SOLDIER FLOOR — `__lw_rally_min_soldiers`,
    how many soldiers must be standing in the base before a banner is worth a squad at
    all (`-5`, #1317). The pool it is judged against is the one the sieve already reads.

    EVERY SQUAD AND EVERY RALLY LEFT BEHIND IS NAMED. `DataCenter.__lw_rally_report` is
    a sentence the recipe reads back and logs: how many were sent, how many rallies were
    out, and one word per squad that was passed over — `out` (marching, gathering,
    already in a rally), `empty` (no soldiers), `no-formation` (the game knows no squad
    in that slot) — plus the server's own refusal for a send that threw. «Тихо не
    поехали» is what this exists to make impossible.

    NOTHING IS OPENED ON SCREEN BY THIS CHUNK, and on the path that catches a banner
    nothing is opened at all. The march itself never needed a window — that is the whole
    finding, and it is the same one «Кодовое имя» rests on (#1259): five screens a person
    walks converge on one send, and the target is addressed by uuid.

    The one thing a window still does is FILL AN EMPTY SQUAD from the base's pool, and
    the client refuses a squad with no soldiers before a byte leaves. That is not the
    march, so it is not on the march's path: this chunk reports such a squad as `empty`
    and sets `__lw_rally_todo = -1`, and the recipe decides — after the fast send has
    already gone out for every squad that had an army — whether to spend the four extra
    calls opening the game's own screen for the ones that had not.

    A JOIN IS MARKED THE MOMENT IT IS SENT (`__lw_rally_joined`), because the server
    takes seconds to answer and two squads landing on one banner is worse than a slow
    join. The marks are PRUNED first against the rallies actually on the map, so a
    banner that came down and a banner we failed to join both stop being marked — a mark
    that outlived its rally is how «joined once, never again» would look.
    """
    return (
        # The marks first, and only the ones whose rally is still out. Before the
        # prelude, which reads this table to decide what is already ours.
        "local wm0 = DataCenter.WorldMarchDataManager "
        "local live = {} local c0 = wm0 and wm0:GetAllMarches() "
        "if c0 then local e0 = c0:GetEnumerator() while e0:MoveNext() do local m0 = e0.Current "
        "local ok0, v0 = pcall(function() return m0.Value end) if ok0 and v0 ~= nil then m0 = v0 end "
        "local ok1, t0 = pcall(function() return m0.teamUuid end) "
        "if ok1 and t0 ~= nil then live[tostring(t0)] = true end end end "
        # A MARK MUST NOT OUTLIVE THE SQUAD IT STANDS FOR (#1281). It exists to bridge the
        # seconds between a send and the server confirming it, so that two squads are not
        # spent on one banner. Keeping it for as long as the BANNER lives is too long: a
        # squad comes home, the rally is still standing and could be joined again, and the
        # run says «no rally we are not already in» — which by then is false. Seen live:
        # `seen=6 ours=6 already_in=0 rallies=0`, six banners of ours, a march of ours in
        # none of them, and every one of them held shut by a mark.
        #
        # So a mark AGES. It is dropped when the banner is gone (as before), and also once
        # it has survived two runs with no march of ours in that team — by which point the
        # server has long since answered and the mark is standing for nothing.
        "local om0 = wm0 and wm0:GetOwnerMarches() local ours_in = {} "
        "if om0 then local e7 = om0:GetEnumerator() while e7:MoveNext() do local m7 = e7.Current "
        "local ok7, v7 = pcall(function() return m7.Value end) if ok7 and v7 ~= nil then m7 = v7 end "
        "local ok8, t7 = pcall(function() return m7.teamUuid end) "
        "if ok8 and t7 ~= nil then ours_in[tostring(t7)] = true end end end "
        "local keep = {} "
        "for k, age in pairs(DataCenter.__lw_rally_joined or {}) do "
        "if live[k] then "
        "if ours_in[k] then keep[k] = 0 "
        "else local a = (tonumber(age) or 0) + 1 if a < 2 then keep[k] = a end end end end "
        "DataCenter.__lw_rally_joined = keep "
        # HOW MANY SQUADS THIS BANNER HAS ALREADY SWALLOWED (#1281). `__lw_rally_shut`
        # empties every run on purpose — a refusal is only terminal while the banner
        # stands, and a squad that came home deserves a second look. What it cannot see
        # is a banner asked again and again across runs: measured over three and a half
        # hours, one banner took FOURTEEN squads and let none of them in, and eighteen
        # banners between them ate 108 of the 137 sends that reached nothing.
        #
        # A retry is still worth having — 9 of the 114 banners we got into took more than
        # one send, all of them landing on the second or third, 6 to 11 seconds later. So
        # the count is kept per banner for as long as the banner is on the map and the
        # third failure is the last: it keeps 8 of those 9 and saves 51 sends that could
        # not have worked. The count is cleared the moment a march of ours stands in that
        # team, so a banner we are IN is never charged for the tries it took.
        "local tries = {} "
        "for k, n in pairs(DataCenter.__lw_rally_tries or {}) do "
        "if live[k] and not ours_in[k] then tries[k] = tonumber(n) or 0 end end "
        "DataCenter.__lw_rally_tries = tries " +
        _RALLY_PRELUDE_MINE +
        # What the run will be judged against: our squads standing in a rally right now.
        "local before = 0 "
        "local afd = DataCenter.ArmyFormationDataManager "
        "for _, f in pairs(afd.ArmyFormationList) do pcall(function() "
        "local m = wm:GetOwnerFormationMarch(P.uid, f.uuid, P.allianceId) "
        "if m ~= nil and tostring(m.teamUuid) ~= '0' then before = before + 1 end end) end "
        "DataCenter.__lw_rally_before = before "
        # HOW MANY SOLDIERS THE PLAYER OWNS AT ALL — the difference between «this squad
        # has not been topped up» and «there are not enough troops in the base to fill
        # any squad» (#1281). One reading, ahead of the sieve, so both words below cost
        # nothing extra. `0` when it cannot be read, and then the sieve says the milder
        # of the two rather than inventing a wall.
        "local pool = 0 "
        "pcall(function() pool = tonumber("
        "DataCenter.SoldierDataManager:GetPlayerSoldiersTotalNum()) or 0 end) "
        # The sieve, with a word for every squad it drops. A squad whose state cannot be
        # read at all is KEPT: a gate that cannot see must not refuse (#1237).
        "local home, skipped, unchecked = {}, {}, {} "
        "for _, s in ipairs(squads) do "
        "local f = nil "
        "for _, v in pairs(afd.ArmyFormationList) do "
        "local ok, idx = pcall(function() return v.index end) "
        "if ok and tonumber(idx) ~= nil and tonumber(idx) == tonumber(s) then f = v end end "
        "if f == nil then skipped[#skipped+1] = tostring(s)..':no-formation' "
        "else "
        "local st = tonumber(f.state) "
        "local ok, idle = pcall(function() return f:IsFree() end) "
        "local free = true if ok and idle ~= nil then free = (idle and true or false) end "
        # FILL IT, THEN MEASURE IT — the order the player asked for, and the game's own
        # filler is what does both (#1281). `ArmyFormation:ConscriptSoldier()` is the
        # method the squad screen runs: it draws from `SoldierDataManager:GetInsideSoldiers()`
        # up to what the squad's heroes can carry, and on the way it WRITES the ceiling
        # into `heroTotalSoldierCapacity`. Nothing in it sends: read off its own
        # constants, it touches the soldier pool, the hero table and its own fields and
        # no message at all.
        #
        # That call is why the check works headless. Without it the ceiling is simply
        # absent — measured live on three squads, `GetAllHeroSoldierCapacity()` answered
        # 0 before and 3123 / 2631 / 2565 immediately after, and the game's own dispatch
        # screen had shown «3,123/3,123 units» for the first of them
        # (docs/research/world-monsters.md, finding 10). Until this line the gate could
        # only ever see a ceiling on a client whose dispatch screen had been rendered by
        # hand.
        "pcall(function() f:ConscriptSoldier() end) "
        # A SQUAD BELOW ITS OWN CEILING IS NOT SENT, and the ceiling is the one the
        # squad's heroes can carry rather than whatever happens to be standing in it.
        # `totalSoldierNum` is what is in it now, and it reads 0 until the army has been
        # asked for, which is why nothing may be decided from it before the recipe's
        # `formation.get.soldier` has run (#1285) — the fill above works from the pool,
        # not from the squad, so it does not stand in for that request.
        #
        # A ceiling that cannot be read does not refuse: an unreadable gate must not
        # shut, the same rule the state check above follows.
        "local n = 0 pcall(function() n = tonumber(f.totalSoldierNum) or 0 end) "
        "local cap = 0 pcall(function() cap = math.floor(tonumber(f:GetAllHeroSoldierCapacity()) or 0) end) "
        "if st ~= nil and not (st == 0 and free) then skipped[#skipped+1] = tostring(s)..':out' "
        "elseif n <= 0 then skipped[#skipped+1] = tostring(s)..':empty' "
        # THE TWO REASONS ARE NOT THE SAME REASON, and that is the whole point of
        # splitting them. «Not topped up» is a minute's work for the player; «there are
        # not enough soldiers in the base to fill one squad» is a wall, and an auto-join
        # that goes quiet against a wall must SAY which wall. Measured on the live
        # account the day this was written: three squads holding 1725/1724/1725 against
        # ceilings of 3123/2631/2565, out of 1727 soldiers owned in total — so not one
        # squad could be filled, and a single unnamed «passed over» would have read as an
        # ordinary quiet evening for as long as the barracks stayed that size.
        "elseif cap > 0 and n < cap then "
        "if pool > 0 and pool < cap then "
        "skipped[#skipped+1] = tostring(s)..':short-of-troops('..n..'/'..cap..', base has '..pool..')' "
        "else skipped[#skipped+1] = tostring(s)..':not-full('..n..'/'..cap..')' end "
        "else home[#home+1] = {slot = s, uuid = f.uuid} "
        # A SQUAD THAT WENT WITHOUT THE CEILING BEING CHECKED SAYS SO (#1281). The
        # ceiling is `heroTotalSoldierCapacity`, and a headless client leaves it nil
        # until the game's own dispatch screen has been rendered once — the same
        # recompute that flips `canMarch` (docs/research/world-monsters.md, finding 10).
        # An unreadable gate must not refuse, so the squad goes; what it must not do is
        # go SILENTLY, or «the full-squad check does nothing» looks exactly like «every
        # squad was full».
        "if not (cap > 0) then unchecked[#unchecked+1] = tostring(s) end end end end "
        # THE DENOMINATOR, counted rather than guessed (#1281). «Six banners» is not six
        # chances: the list the client keeps holds every team on the map — other
        # alliances', and the ones we are already standing in. Without the split, «two
        # were missed» cannot be said or denied, which is exactly what the summary had to
        # admit. One more pass over the collection already in hand, so it costs nothing.
        # WHAT KIND OF RALLY EACH ONE IS, and it is a real question rather than a
        # placeholder (#1281). The budget has had three keys since it was written —
        # `monster`, `zombie_invasion` (uncapped on purpose), `alliance_drill` — and no
        # classifier at all: the reading that was supposed to tell them apart assigned
        # the SAME key to every rally, so an invasion boss, which the event does not
        # ration, spent the ordinary monsters' twenty a day.
        #
        # The march itself cannot answer: every leader on the map reads `monsterId=0`,
        # `monsterType=0`, `type=ASSEMBLY_MARCH`. What CAN is the event's own list of
        # monsters (`ActivityMonsterInvasionDataManager.monsterInvasionData`, fields
        # `selfMonsters` / `aliMonsters`), so a rally whose target is in it is an
        # invasion boss and everything else is an ordinary monster.
        #
        # Indexed by uuid AND by tile, because the element shape could not be read from a
        # live event — the lists are empty between waves — and a key that is not there
        # simply never matches. `inv_ok` says whether the lists could be read at all,
        # which is the difference between «this is not an invasion boss» and «nobody
        # could tell», and the report says which.
        "local inv_set, inv_ok = {}, false "
        "pcall(function() local im = DataCenter.ActivityMonsterInvasionDataManager "
        "local d = im and im.monsterInvasionData "
        "if d ~= nil then inv_ok = true "
        "for _, nm in ipairs({'selfMonsters', 'aliMonsters'}) do "
        "local lst = nil pcall(function() lst = d[nm] end) "
        "if type(lst) == 'table' then for kk, mon in pairs(lst) do "
        "inv_set[tostring(kk)] = true "
        "pcall(function() if mon.uuid ~= nil then inv_set[tostring(mon.uuid)] = true end end) "
        "pcall(function() if mon.pointId ~= nil then inv_set['p'..tostring(mon.pointId)] = true end end) "
        "pcall(function() if mon.point ~= nil then inv_set['p'..tostring(mon.point)] = true end end) "
        "end end end end end) "
        # WHAT EACH BANNER IS GOING FOR, off the wire. The push carries
        # `targetContentId` — the monster's config id — and the client's own march record
        # drops it (25 of the push's 33 fields survive into `GetAllMarches()`, not this
        # one), so the panel hears it and parks it here as `team:contentId,…` (#1281).
        # `lw_world_monster` turns it into a type and a level: 7 is the zombie line
        # (Invading Zombies / Zombie Boss), 8 is the Doom line (Роковая Элита).
        "local target_of_team = {} "
        # HOW MANY OF THEM THERE WERE, remembered before anything is looked up (#1323).
        # An empty map is not «this banner is new», it is «this profile cannot name a
        # single banner», and the two produce the same `monster` in the count while
        # meaning opposite things.
        "local tgt_n = 0 "
        "pcall(function() for pair in string.gmatch(tostring("
        "DataCenter.__lw_rally_targets or ''), '[^,]+') do "
        "local team, cid = string.match(pair, '(%d+):(%d+)') "
        "if team ~= nil then target_of_team[team] = tonumber(cid) tgt_n = tgt_n + 1 end end end) "
        "local LCI = nil pcall(function() LCI = LocalController.instance() end) "
        + _kind_table() +
        # AN UNKNOWN ROW ANSWERS WITH AN EMPTY STRING, NOT NIL — measured live: asking
        # `lw_world_monster` for an id it has never heard of came back `type=''`, and a
        # first version of the branch below turned that into the key `monster_type_`
        # with nothing after it. Empty is «no answer», and «no answer» has to be the
        # unheard-of case rather than a species with a blank name (#1281).
        # THE SPECIES IS ITS `name` KEY, NOT ITS `type` (#1317). Read out of the live
        # config: «Роковая Элита» (`300602`) sits under three different types across
        # seasons, and type 8 is not it at all — that is the Doom WALKER line
        # (`monster_boss_name_001`, «Разрушитель»), which is what the old `doom_elite`
        # key had been counting. `activity` is what marks an event's monsters, and 107 is
        # the General's Trial, whose two species are the ones the player names as «простые
        # и элитные»: `2010220` Vanguard Instructors and `challenge_zombie_001` Elite
        # Instructor.
        "local function monster_of(cid) "
        "if LCI == nil or cid == nil then return nil, nil, nil, nil end "
        "local ty, lv, nm, act = nil, nil, nil, nil "
        "pcall(function() ty = LCI:getValue('lw_world_monster', cid, 'type', nil) end) "
        "pcall(function() lv = LCI:getValue('lw_world_monster', cid, 'level', nil) end) "
        "pcall(function() nm = LCI:getValue('lw_world_monster', cid, 'name', nil) end) "
        "pcall(function() act = LCI:getValue('lw_world_monster', cid, 'activity', nil) end) "
        "if ty ~= nil and tostring(ty) == '' then ty = nil end "
        "if lv ~= nil and tostring(lv) == '' then lv = nil end "
        "if nm ~= nil and tostring(nm) == '' then nm = nil end "
        "if act ~= nil and tostring(act) == '' then act = nil end "
        "return ty, lv, nm, act end "
        # THE ALLIANCE EXERCISE NAMES ITS OWN BOSS, and that is the only exact way to know
        # one: the drill's boss is not a species on the map but a uuid the manager carries
        # (`AllyDrillDataManager.actInfo.data.bossUuid` / `bossPointId`, read live for
        # #1317 while a drill was running).
        "local drill_uuid, drill_point = nil, nil "
        "pcall(function() local d = DataCenter.AllyDrillDataManager.actInfo.data "
        "drill_uuid = d and d.bossUuid drill_point = d and d.bossPointId end) "
        # THE INVASION EVENT STILL ANSWERS FIRST: its own monster lists are the only thing
        # that marks a banner as one the event does not ration, and that is a different
        # question from what species is standing on the tile.
        "local function kind_of(r) "
        "local cid = target_of_team[tostring(r.team)] "
        "local ty, lv, nm, act = monster_of(cid) "
        "r.level = lv r.mtype = ty "
        "if drill_uuid ~= nil and r.target ~= nil "
        "and tostring(r.target) == tostring(drill_uuid) then return 'alliance_drill', true end "
        "if drill_point ~= nil and r.point ~= nil "
        "and tostring(r.point) == tostring(drill_point) then return 'alliance_drill', true end "
        "if inv_ok then "
        "local tu = r.target "
        "if tu ~= nil and inv_set[tostring(tu)] then return 'zombie_invasion', true end "
        "if r.point ~= nil and inv_set['p'..tostring(r.point)] then return 'zombie_invasion', true end end "
        # …then the event a species belongs to, and then the species itself — which is the
        # split the player reads off the screen.
        "if nm ~= nil then local hit = KIND_OF_NAME[tostring(nm)] "
        "if hit ~= nil then return hit, true end end "
        "if act ~= nil and tostring(act) == '107' then return 'general_trial', true end "
        "if ty ~= nil and tonumber(ty) ~= nil then "
        "if tonumber(ty) == 8 then return 'doom_walker', true end "
        "if tonumber(ty) == 7 then return 'zombie_boss', true end "
        # A ROW THE NAME TABLE CANNOT NAME IS NOT A KIND OF ITS OWN (#1323). This used to
        # answer `monster_type_<n>`, and that key is in nobody's vocabulary: the panel's
        # caps file is seeded from `rally_kinds.KIND_ORDER`, so such a key has no cap, is
        # never handed a budget, is never shown on the tab and never appears in
        # `over_budget` — while the tally counts joins under it all day. The key a join is
        # COUNTED under and the key the door looks a budget up by have to be one key or
        # the door is open by construction. So an unnamed row is the fallback kind, the
        # type is kept for the report (`r.unnamed`), and nothing is spent from a budget
        # nobody could set.
        "r.unnamed = tonumber(ty) "
        "return 'monster', false end "
        # NOT HEARD OF, and said so rather than assumed. A banner raised before the panel
        # started listening has no push behind it, so its kind is genuinely unknown; it is
        # counted as an ordinary monster because something must be counted, and the report
        # says how many were counted that way.
        "return 'monster', false end "
        # HOW MANY SEATS THE BANNER HAS, and how many are taken. The wire says the size
        # (`assemblyMarchMax`, measured live at 5) and the client's own march list says
        # the occupancy — every member march of a rally is in it, which is how the count
        # stays right without waiting for another push. The panel parks the sizes here
        # as `team:max,…` exactly as it parks the targets (#1281).
        # AND HOW FULL IT WAS WHEN WE LAST HEARD IT (#1281). The occupancy used to be
        # counted in the client alone, on the argument that its march list is current at
        # the moment of the send while a push is as old as the last one we heard. The
        # wire says otherwise: over three and a half hours, 21 squads were sent at a
        # banner the wire had last announced as 5 of 5 and NOT ONE of them reached it,
        # while the client's own count of those same banners still showed a seat. Both
        # numbers are floors of the truth — a march the other side has not told us about
        # is missing from ours, and a member who joined since the last push is missing
        # from theirs — so the sieve believes the LARGER, and only a banner both agree is
        # open stays a candidate.
        "local max_of, wire_taken = {}, {} "
        "pcall(function() for pair in string.gmatch(tostring("
        "DataCenter.__lw_rally_slots or ''), '[^,]+') do "
        "local team, tk, mx = string.match(pair, '(%d+):(%d+)/(%d+)') "
        "if team == nil then team, mx = string.match(pair, '(%d+):(%d+)') end "
        "if team ~= nil then max_of[team] = tonumber(mx) "
        "if tk ~= nil then wire_taken[team] = tonumber(tk) end end end end) "
        # Banners this run has already been refused by — the recipe writes them here when
        # a send produced no march, and they are not offered again inside the same run.
        "local blocked = {} "
        "pcall(function() for k in pairs(DataCenter.__lw_rally_shut or {}) do "
        "blocked[tostring(k)] = true end end) "
        "local seen_t, our_t, end_of, target_of, count_of = {}, {}, {}, {}, {} "
        "if col then local e9 = col:GetEnumerator() while e9:MoveNext() do local m9 = cur(e9) "
        "local t9 = g(m9, 'teamUuid') local ts9 = tostring(t9) "
        "if t9 ~= nil and ts9 ~= '0' and ts9 ~= 'nil' then seen_t[ts9] = true "
        "count_of[ts9] = (count_of[ts9] or 0) + 1 "
        "local u9 = g(m9, 'uuid') local lead9 = false "
        "pcall(function() lead9 = (tostring(u9) == tostring(t9 - 1)) end) "
        "if lead9 then end_of[ts9] = tonumber(g(m9, 'endTime')) or 0 "
        "target_of[ts9] = g(m9, 'targetUuid') end "
        "local n9 = tostring(g(m9, 'allianceName')) "
        "if mine ~= nil and n9 == mine then our_t[ts9] = true end end end end "
        # THE BANNERS THE CLIENT HAS NOT HEARD OF YET (#1301), and they are the whole of
        # the delay a person sees. Everything above this line reads `GetAllMarches()`,
        # and that table is a MEDIAN OF 10 s behind the push that announced the banner
        # (p25 8.1 s, p75 19.1 s, max 62 s, over 31 banners) — in 23 of 26 late cases it
        # only learned about the banner once somebody ELSE had joined it. The trigger
        # itself is instant: 0.005 s from the wire to the fire, 0.3 s from there to the
        # send. So a run woken by a push spent its 0.3 s, found nothing, and truthfully
        # reported `rallies=0` — measured end to end at 16:19:49.682 push → 16:19:50.175
        # send → `sent=0 rallies=0 seen=0`, and the same banner joined at 16:19:58 the
        # moment a refresh push made the client notice it.
        #
        # The push carries everything the send needs from the first byte, so the panel
        # parks it here as `team:tile/server,…` (`rallytab.point_map`) and a banner the
        # wire has announced becomes a candidate with the address off the wire. It is
        # ONLY ever an addition: a team the client already lists is skipped here and
        # stays the client's, and one we already have a march in (`taken`) or have been
        # refused by this run (`blocked`) is skipped as it would be anywhere else.
        #
        # THEY GO IN FRONT, because that is the point: a banner the client has not caught
        # up with is by definition the freshest one on the map, and the ones already in
        # its table have had at least one run to be taken.
        #
        # NOT PUT THROUGH THE ALLIANCE SIEVE, and it does not need to be: these arrive on
        # `push.alliance.march.*`, which is this alliance's own stream. The sieve above
        # exists because `GetAllMarches()` returns both sides of a war; the wire does not.
        #
        # A uuid THAT DOES NOT SURVIVE THE ROUND TRIP IS DROPPED. A teamUuid is 19 digits;
        # an integer Lua holds exactly and a double does not, and a send aimed at a
        # rounded uuid reaches nothing while reporting cleanly — the failure this ability
        # already spent weeks in (#1237). `tostring(tonumber(t)) == t` is the whole test:
        # it holds on an integer VM and fails on the scientific notation a float gives
        # back, so the candidate is simply left to the client rather than sent into the
        # void.
        "local from_wire = {} "
        "pcall(function() local ahead = {} "
        "for pair in string.gmatch(tostring("
        "DataCenter.__lw_rally_points or ''), '[^,]+') do "
        "local team, pt, sv = string.match(pair, '(%d+):(%d+)/(%d+)') "
        "if team ~= nil and not seen_t[team] and not taken[team] and not blocked[team] then "
        "local tn = tonumber(team) local pn, sn = tonumber(pt), tonumber(sv) "
        "if tn ~= nil and tostring(tn) == team and pn ~= nil and sn ~= nil then "
        "ahead[#ahead+1] = {team = tn, point = pn, server = sn} "
        "from_wire[#from_wire+1] = team end end end "
        "if #ahead > 0 then for _, r in ipairs(rallies) do ahead[#ahead+1] = r end "
        "rallies = ahead end end) "
        # A RALLY THAT HAS ALREADY ARRIVED IS NOT A RALLY TO JOIN (#1281). The client
        # keeps a resolved banner in its march table — same teamUuid, same
        # `type=ASSEMBLY_MARCH`, `status` still saying MOVING — so nothing in the shape
        # of the entry says it is over. `endTime` does, and it is the only field that
        # does: nine «banners» on the map at 18:52 and every one of them had arrived,
        # the oldest thirty-two minutes earlier. Squads were being sent at all of them,
        # the server dropped every send without a word on screen, and the run reported
        # «sent=3 … joined=0» — fifteen sends and no march in one quarter of an hour.
        #
        # This is also the correction to a claim made earlier in this task: «six joinable
        # banners held shut by a mark» were six banners that had already been fought.
        # Ageing the marks did not free them, it removed the accidental guard that was
        # keeping squads off them.
        "local now_ms = 0 "
        "pcall(function() now_ms = UITimeManager:GetInstance():GetServerTime() end) "
        "local arrived = {} "
        "if now_ms > 0 then local still = {} "
        "for _, r in ipairs(rallies) do local et = end_of[tostring(r.team)] "
        "if et == nil or et <= 0 or et > now_ms then still[#still+1] = r "
        "else arrived[#arrived+1] = tostring(r.team) end end "
        "rallies = still end "
        # A BANNER STILL GATHERING CAN STILL BE SHUT (#1281). The player watched the
        # Marshal event and named it: the list of active rallies is full of banners that
        # have not left yet and have no seat left in them, and every squad we owned was
        # being thrown at one. `endTime` cannot see that — it says the banner is still
        # standing, which is true. Seats can: nine banners measured on the wire during
        # that event and every one of them read 5 of 5.
        #
        # A banner whose size we never heard is NOT filtered — an unheard size is not a
        # full banner, and the refusal path below is what catches those.
        "local full = {} "
        "local still2 = {} "
        "for _, r in ipairs(rallies) do local ts = tostring(r.team) "
        "local mx, taken = max_of[ts], count_of[ts] or 0 "
        "local wt = wire_taken[ts] "
        "local src = 'client' "
        "if wt ~= nil and wt > taken then taken = wt src = 'wire' end "
        "local spent = tonumber(tries[ts] or 0) or 0 "
        "if blocked[ts] then full[#full+1] = ts..':refused-full' "
        "elseif spent >= 3 then full[#full+1] = ts..':swallowed('..spent..' squads, none arrived)' "
        "elseif mx ~= nil and mx > 0 and taken >= mx then "
        "full[#full+1] = ts..':banner-full('..taken..'/'..mx..' by '..src..')' "
        "else still2[#still2+1] = r end end "
        "rallies = still2 "
        "local function _n(t) local k = 0 for _ in pairs(t) do k = k + 1 end return k end "
        # COUNTED FROM OUR OWN MARCHES, not from the marks. `taken` also carries the
        # teams this run has just SENT to, and a mark outlives the squad that came home —
        # so counting it answered «already_in=6» on an account with three squads, which is
        # a number that cannot be true. The honest reading is a march of ours standing in
        # that team right now, which is the same thing `before` is counted from.
        "local seen_n, our_n, in_n = _n(seen_t), _n(our_t), 0 "
        "local om2 = wm:GetOwnerMarches() "
        "if om2 then local e8 = om2:GetEnumerator() while e8:MoveNext() do local m8 = cur(e8) "
        "local t8 = g(m8, 'teamUuid') local ts8 = tostring(t8) "
        "if t8 ~= nil and ts8 ~= '0' and seen_t[ts8] then in_n = in_n + 1 end end end "
        # Pair and send. One squad per rally, both in the order they arrived. EVERY BANNER
        # IS NAMED — the one it went to, and the one it did not and why — so «not a banner
        # missed» can be checked one at a time instead of as a total (#1281).
        # THE DAY'S CEILING, AND IT IS THE GAME'S OWN NUMBER (#1317). `daily_kill_boss`
        # is what the client counts rally bosses with — one per rally that finished and
        # paid today, kept by the server and reset on the SERVER's day, so it needs no
        # tally of ours and no PC clock.
        #
        # It was a READING here until #1317 and it is a door again, which is a reversal
        # worth spelling out. #1281 took the door out for a good reason — the panel's own
        # tally was twelve ahead of the game's and had been refusing banners the account
        # was entitled to since 19:42 — and drew the wrong conclusion from a true fact:
        # past twenty the game stops PAYING, it does not stop the joining. The player has
        # since said what that costs: «лимит Роковой Элиты стоит 20, а бот целый день
        # цепляется к стягам» — a squad in an unpaid rally is a squad away from home for
        # nothing, all evening. So the door is back, with the tally taken out of it: the
        # count is the game's (`GetKillBossNum`), the ceiling is the person's
        # (`__lw_rally_cap`, 0 = no ceiling), and nothing here is written down.
        #
        # A GATE THAT CANNOT SEE DOES NOT REFUSE: an unreadable `kb` joins as before.
        "local kb, kbmax, kbleft = nil, nil, nil "
        "pcall(function() local MM = DataCenter.MonsterManager "
        "kb = MM:GetKillBossNum() kbmax = MM:GetMaxKillBossNum() "
        "kbleft = MM:GetRestKillBossNum() end) "
        "local cap = tonumber(DataCenter.__lw_rally_cap) or 0 "
        "local capped = (cap > 0 and tonumber(kb) ~= nil and tonumber(kb) >= cap) "
        # …AND THE SOLDIERS IN THE BASE, WHICH IS A DOOR OVER THE WHOLE RUN (#1317).
        #
        # «Сделай число в панели, и будем сравнивать кол солдат в казарме с указанным,
        # если меньше, автостяги останавливаем.» One number typed by the person, one
        # reading off the game, and nothing goes out while the reading is the smaller —
        # no shares, no sums of the squads' ceilings, no arithmetic about how many squads
        # it would fill.
        #
        # THE READING IS `pool` — `SoldierDataManager:GetPlayerSoldiersTotalNum()`, the
        # soldiers standing IN THE BASE, which the sieve above was already asking for.
        # It is the pool the game's own squad filler draws from: it falls when a march
        # leaves and rises when one returns, so soldiers out with a squad are not in it.
        # The report names it (`in_base=`) rather than leaving «казарма» to be guessed at.
        #
        # A GATE THAT CANNOT SEE DOES NOT REFUSE: `pool` is 0 when the reading failed, and
        # then this door stands open exactly as it did before it existed.
        "local minpool = tonumber(DataCenter.__lw_rally_min_soldiers) or 0 "
        "local short_pool = (minpool > 0 and pool > 0 and pool < minpool) "
        # …AND THE CEILING PER KIND (#1317). `kind:left,…`, parked by the panel, which is
        # the only thing that can count them: the client keeps ONE daily rally counter and
        # no per-species number anywhere — every manager was walked for #1317 and there is
        # none. So the panel's tally is the source, the person's number is the cap, and
        # what happens HERE is the decision: a banner of a kind with nothing left is
        # passed over and named, and each send spends one from the kind it went to, so two
        # banners of the same kind in one press cannot both take the last one.
        #
        # A kind with NO entry is unlimited, exactly as `0` means in the panel's file.
        "local kind_left = {} "
        "pcall(function() for pair in string.gmatch(tostring("
        "DataCenter.__lw_rally_kind_left or ''), '[^,]+') do "
        "local k, n = string.match(pair, '([%w_]+):(%-?%d+)') "
        "if k ~= nil then kind_left[k] = tonumber(n) end end end) "
        # …AND THE DOOR IS MADE CHECKABLE FROM THE RUN'S OWN LINE (#1322). The budget that
        # was in force is remembered before a single send spends from it, and the report
        # names it for every kind this run actually looked at. A door that refuses nothing
        # and a door that was never handed a number read exactly alike in the log —
        # `kind_capped=` simply never appeared — and for a whole day that was the
        # difference between a cap of 20 and thirty joins of «Элитные инструкторы».
        "local kind_left0, kind_n = {}, 0 "
        "for k, v in pairs(kind_left) do kind_left0[k] = v kind_n = kind_n + 1 end "
        "local kind_seen = {} "
        # …AND THE KINDS THE PERSON SIMPLY DOES NOT WANT (#1317). A filter, not a budget:
        # nothing is counted, so nothing can drift — «цепляться к этим, к тем не
        # цепляться» is answerable exactly, because the kind of a banner is known here
        # BEFORE a squad leaves. `kind_skip` is a plain list of kinds, and a banner of one
        # is passed over and named `kind-off`.
        "local kind_off = {} "
        "pcall(function() for k in string.gmatch(tostring("
        "DataCenter.__lw_rally_kind_skip or ''), '[^,]+') do kind_off[k] = true end end) "
        "local kind_blocked = {} "
        "local kind_dropped = {} "
        "local sent, errs, went, left_over, kinds, went_kind = 0, {}, {}, {}, {}, {} "
        "local sent_teams = {} "
        "local unknown_kind = 0 "
        "local pairs_n = #home if #rallies < pairs_n then pairs_n = #rallies end "
        "local qi = 0 "
        "for i = 1, #rallies do local r = rallies[i] "
        "r.target = target_of[tostring(r.team)] "
        "local kind, known = kind_of(r) "
        "if not known then unknown_kind = unknown_kind + 1 end "
        "kind_seen[kind] = true "
        # The day is spent: every banner is NAMED as passed over for that reason rather
        # than silently skipped, so «nothing went out» never reads as «no rally was out».
        "if capped then left_over[#left_over+1] = tostring(r.team)..':day-capped' "
        # …the base has not got the soldiers the person asked for, and every banner is
        # NAMED as passed over for that reason: a quiet evening and a base being refilled
        # are different sentences (#1317).
        "elseif short_pool then left_over[#left_over+1] = "
        "tostring(r.team)..':low-on-soldiers('..pool..'/'..minpool..')' "
        # …a kind the person has switched off, which is a different sentence again: it is
        # not «today is spent», it is «not this kind at all» (#1317).
        "elseif kind_off[kind] then "
        "kind_dropped[kind] = (kind_dropped[kind] or 0) + 1 "
        "left_over[#left_over+1] = tostring(r.team)..':kind-off('..kind..')' "
        # …and so is a banner whose KIND is spent, with the kind in the word: «нечего
        # слать» and «этого вида на сегодня хватит» are different answers (#1317).
        "elseif kind_left[kind] ~= nil and kind_left[kind] >= 0 and kind_left[kind] <= 0 then "
        "kind_blocked[kind] = (kind_blocked[kind] or 0) + 1 "
        "left_over[#left_over+1] = tostring(r.team)..':kind-capped('..kind..')' "
        "elseif qi >= #home then left_over[#left_over+1] = tostring(r.team)..(#home == 0 and ':no-squad' or ':squads-spent') "
        "else qi = qi + 1 local q = home[qi] "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(q.uuid, 6, r.point, r.team, 1, 1, false, r.server, nil) end) "
        "if ok then sent = sent + 1 keep[tostring(r.team)] = 0 "        # age 0: freshly sent
        # One off the kind's budget, HERE and not in the panel afterwards: two banners of
        # one kind in a single press would otherwise both be measured against the same
        # «one left» (#1317).
        "if kind_left[kind] ~= nil and kind_left[kind] > 0 then "
        "kind_left[kind] = kind_left[kind] - 1 end "
        "tries[tostring(r.team)] = (tonumber(tries[tostring(r.team)] or 0) or 0) + 1 "
        "sent_teams[#sent_teams+1] = tostring(r.team) "
        "went[#went+1] = tostring(r.team)..'/s'..tostring(q.slot) "
        "kinds[#kinds+1] = kind "
        "went_kind[#went_kind+1] = tostring(r.team)..'='..kind"
        "..((r.level ~= nil) and (' lv'..tostring(r.level)) or '')"
        # …and the type of a row the name table could not name, which is the one thing
        # lost by counting it as the fallback kind rather than as `monster_type_<n>`
        # (#1323). Said here, where a person can read it, instead of in a key nothing
        # can cap.
        "..((r.unnamed ~= nil) and (' type'..tostring(r.unnamed)..' unnamed') or '') "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_all send squad="..tostring(q.slot)'
        '.." team="..tostring(r.team).." point="..tostring(r.point).." server="..tostring(r.server)) '
        "else errs[#errs+1] = tostring(q.slot)..':'..tostring(err) "
        "left_over[#left_over+1] = tostring(r.team)..':refused' end end end "
        "DataCenter.__lw_rally_joined = keep "
        "DataCenter.__lw_rally_sent = sent "
        "DataCenter.__lw_rally_kinds = table.concat(kinds, ',') "
        # WHERE THIS PASS SENT, so the recipe can take those banners out and go to the
        # next ones when the server answers «Rally participant full» (game key 390857).
        "DataCenter.__lw_rally_sent_teams = table.concat(sent_teams, ',') "
        # WHAT THE RECIPE DOES NEXT, decided here so it costs no reading of its own.
        # `sent` when anything went; `-1` when nothing did and the only thing in the way
        # was an EMPTY squad with a rally standing there for it — the one case the
        # headless send cannot cover, because the client refuses a squad with no soldiers
        # before a byte leaves and only the game's own screen fills one from the base's
        # pool; `0` when there is nothing to be done at all.
        "local empty, under, walled = 0, 0, 0 "
        "for _, s in ipairs(skipped) do "
        "if string.find(s, ':empty', 1, true) then empty = empty + 1 end "
        "if string.find(s, ':not-full(', 1, true) then under = under + 1 end "
        "if string.find(s, ':short-of-troops(', 1, true) then walled = walled + 1 end end "
        "DataCenter.__lw_rally_todo = sent "
        "if sent == 0 and empty > 0 and #rallies > 0 then DataCenter.__lw_rally_todo = -1 end "
        # `-2` and `-3` — «a banner is standing and every squad that could go is under
        # strength» (#1281), told apart because the answer is different. `-2` is a squad
        # the player can top up; `-3` is a base that has not got the soldiers to fill one
        # squad, which is a wall rather than a chore and must never read as an ordinary
        # quiet minute. Both rank BELOW `-1`: `-1` is answered by ASKING the game for the
        # army and trying again, and a run with one unasked squad should try that first —
        # under-strength is only reported when there is nothing left to try.
        "if sent == 0 and empty == 0 and (walled > 0 or under > 0) and #rallies > 0 then "
        "DataCenter.__lw_rally_todo = (walled > 0) and -3 or -2 end "
        # `-4` — the day's ceiling is reached (#1317). It OUTRANKS every other verdict:
        # a squad standing empty on a day the person has already spent is not a reason to
        # fetch an army, and the recipe stops on this before it reaches its `todo < 0`
        # branch. Only ever set when the game answered with a number of its own.
        # `-5` — the base is under the soldier floor the person set (#1317). It ranks
        # above the under-strength verdicts for the same reason `-4` does: nothing about
        # a squad is the news, the BASE is, and fetching an army for a squad that may not
        # be spent anyway is a call spent on a run that is already refused.
        "if short_pool then DataCenter.__lw_rally_todo = -5 end "
        # …and the day's ceiling outranks even that: «сегодня всё» is the more final of
        # the two, and a base that fills up later still has nothing to join today.
        "if capped then DataCenter.__lw_rally_todo = -4 end "
        "local report = 'sent='..sent..' rallies='..#rallies..' free='..#home "
        # The split that makes «rallies=1» readable: of every team on the map, how many
        # are this alliance's and how many we are already standing in. `joinable` is the
        # denominator «not one missed» is measured against; the rest are not chances.
        "report = report..' seen='..seen_n..' ours='..our_n..' already_in='..in_n "
        # …and how many of the candidates the client could not have offered. A run whose
        # every send went to a wire-only banner reads `seen=0 rallies=2` otherwise, which
        # is a pair of numbers that cannot both be true (#1301).
        "if #from_wire > 0 then report = report..' from_wire=['"
        "..table.concat(from_wire, ' ')"
        "..'] (heard on the wire, not yet in the march table the client keeps)' end "
        # THE EVENT'S OWN NUMBER, beside ours. The invasion rations attacks itself
        # (`attackNum`), and our per-day cap is a different thing with a different unit —
        # so both are shown and neither is substituted for the other, and a person
        # reading «nothing was sent» can see whose ceiling it was (#1281).
        "local inv_n = nil "
        "pcall(function() inv_n = DataCenter.ActivityMonsterInvasionDataManager"
        ".monsterInvasionData.attackNum end) "
        "if inv_n ~= nil then report = report..' game_attackNum='..tostring(inv_n) end "
        "if #went > 0 then report = report..' to=['..table.concat(went, ' ')..']' end "
        "if #went_kind > 0 then report = report..' going_for=['..table.concat(went_kind, ' ')..']' end "
        "if kb ~= nil then report = report..' trophies='..tostring(kb)..'/'..tostring(kbmax) "
        "if kbleft ~= nil and tonumber(kbleft) ~= nil and tonumber(kbleft) <= 0 then "
        "report = report..' -- past the trophy threshold: the game pays nothing more today' end end "
        # THE DOOR SAYS SO IN THE RUN'S OWN SENTENCE (#1317), with both numbers: the
        # game's count and the ceiling it was judged against. `cap=0` is «no ceiling» and
        # says nothing at all, exactly as it did before the door existed.
        "if cap > 0 then report = report..' cap='..tostring(kb)..'/'..cap "
        "if capped then report = report..' -- the ceiling for today is reached, so nothing "
        "was sent' end end "
        # …AND THE SOLDIER FLOOR, WITH BOTH NUMBERS AND THE NAME OF THE READING, whether
        # or not it shut anything (#1317). `in_base` is the soldiers standing in the base
        # (`GetPlayerSoldiersTotalNum`, the pool the squad filler draws from) — named
        # here because «казарма» could be read as more than one number, and a door that
        # does not say what it compared cannot be argued with.
        "if minpool > 0 then report = report..' in_base='..pool..'/'..minpool "
        "if short_pool then report = report..' -- fewer soldiers in the base "
        "(GetPlayerSoldiersTotalNum) than the floor set in «Автостяг», so nothing "
        "was sent' "
        "elseif not (pool > 0) then report = report..' (the number of soldiers in the "
        "base could not be read — the floor did not refuse anything)' end end "
        # THE BUDGET THIS RUN WAS ACTUALLY HANDED, for every kind it saw (#1322). `kind:N`
        # is what that kind had left when the press started, `none` is a kind the panel
        # named no ceiling for, and `(the panel handed no per-kind budget at all)` is the
        # sentence that would have told us in one line why nothing was ever capped. Said
        # whether or not anything was held back, because the whole failure was a door that
        # stayed silent while it stood open: `kind_capped=` never appeared, and neither
        # does it on an evening when every kind is well inside its allowance.
        "local kbud = {} "
        "for k in pairs(kind_seen) do local v = kind_left0[k] "
        "kbud[#kbud+1] = k..':'..((v == nil) and 'none' or tostring(v)) end "
        "table.sort(kbud) "
        "if #kbud > 0 then report = report..' kind_budget=['..table.concat(kbud, ' ')..']' "
        "if kind_n == 0 then report = report..' (the panel handed no per-kind budget at all)' end end "
        # …and which KINDS held a banner back, with how many each (#1317). Said even when
        # something else went out, because «two of the four were the wrong kind today» is
        # exactly the sentence a person needs to change a number with.
        "local kb_parts = {} "
        "for k, n in pairs(kind_blocked) do kb_parts[#kb_parts+1] = k..'x'..n end "
        "table.sort(kb_parts) "
        "if #kb_parts > 0 then report = report..' kind_capped=['..table.concat(kb_parts, ' ')"
        "..'] (this kind has had its allowance for today)' end "
        # …and the kinds that were passed over because nobody wants them. Named the same
        # way and kept apart from the budget, so «я это выключил» never reads as «на
        # сегодня хватит» (#1317).
        "local ko_parts = {} "
        "for k, n in pairs(kind_dropped) do ko_parts[#ko_parts+1] = k..'x'..n end "
        "table.sort(ko_parts) "
        "if #ko_parts > 0 then report = report..' kind_off=['..table.concat(ko_parts, ' ')"
        "..'] (this kind is switched off in «Автостяг»)' end "
        # WHAT COULD NOT BE NAMED, AND WHY — and the «why» is the whole of #1323. The
        # sentence here used to blame the event list, which is one of three reasons and
        # not the common one: a banner's KIND is `targetContentId`, that field is on the
        # push and in no reading the client keeps (docs/research/rally-join.md), and the
        # panel parks it per banner. A profile whose targets arrive empty therefore
        # classifies every banner as the fallback `monster`, spends one bucket's budget
        # all day and leaves every kind the person actually capped at zero — which reads
        # in the log exactly like an evening of ordinary monsters. So the count of parked
        # targets is said beside the count of banners nothing could name.
        "if unknown_kind > 0 then report = report..' unclassified='..unknown_kind "
        "if tgt_n == 0 then report = report..' (no banner targets were parked at all, so "
        "the kind of every banner fell back to \"monster\" — a per-kind budget cannot "
        "bite here, whatever the panel handed over)' "
        "else report = report..' (no target for this banner, or the event lists could "
        "not be read — counted as \"monster\", said rather than assumed)' end end "
        "if #arrived > 0 then report = report..' arrived=['..table.concat(arrived, ' ')..']' end "
        "if #full > 0 then report = report..' no_seat=['..table.concat(full, ' ')..']' end "
        "if #left_over > 0 then report = report..' passed=['..table.concat(left_over, ' ')..']' end "
        "if #skipped > 0 then report = report..' left=['..table.concat(skipped, ' ')..']' end "
        "if #unchecked > 0 then report = report..' ceiling-unknown=['..table.concat(unchecked, ' ')"
        "..'] (the game has not filled in how many soldiers fit — sent without the full-squad check)' end "
        "if #errs > 0 then report = report..' refused=['..table.concat(errs, ' ')..']' end "
        "if #rallies == 0 then report = report..' -- no rally of this alliance is out that we are not already in' "
        "elseif #home == 0 then report = report..' -- not one of the chosen squads can be sent' "
        "elseif sent < #rallies then report = report..' -- more rallies than squads to spend' end "
        "DataCenter.__lw_rally_report = report "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_all "..report)'
    )


# --------------------------------------------------------------------------
# Alliance rally: JOIN one THROUGH THE GAME'S OWN SCREENS
# --------------------------------------------------------------------------
# The direct send does not work and it is not for want of trying: the message the bot
# builds matches the player's argument for argument (docs/research/rally-join.md), and
# the server still creates no march — until #1238 found that both were being aimed at the
# monster instead of the tile the joiners gather on. `rally_join_send` is the join with no
# screen at all; what is below it is the FALLBACK, and it earns its keep by filling a
# squad that has no soldiers in it. It walks the windows the way `create_rally.md` drives
# the raise, waiting for STATES rather than sleeping:
#
#     OnClickStartMarch -> UIFormationSelectListV2 -> pick the squad -> OnCheckTime
#
# Read off a trace of a HAND-MADE join: `OnClickStartMarch(6, point, team, -1, 1, 7,
# server, 0, 10)` is what opens that screen — note the `10`, which the old fire-and-
# forget warm-up passed as `0` — and the screen is the SAME one the create side already
# picks a squad on, so the last two steps are the create side's, spelled for the join.
#
# THE SCREEN IS NOT CLOSED BY ANY OF THIS. The old press opened it and shut it again in
# the same breath, which is why the send that followed had nothing behind it — the same
# lesson #1172 paid for on the create side: the popup a button lives on must stay up
# until the button has been pressed. The screen closes itself when the launch succeeds.
_RALLY_JOIN_PARAMS = "local p = DataCenter.__lw_rally_join or {} "


def rally_join_arm() -> str:
    """Pick the rally to join and the squad to send, and park both. Presses nothing.

    First rally the account is not already in; of the sieved squads, **the first one that
    can actually be sent** — that is, one with soldiers in it. The sieve upstream only
    asks whether a squad is at home and idle, and a squad can be both of those and still
    be empty; taking it anyway is what sends an otherwise headless join through the
    windows, because an empty squad is the one case the send cannot cover (#1238).

    Falls back to the first sieved squad when none has soldiers — then the screen path
    below fills it, which is what the screen is for. So the choice never REFUSES a join,
    it only prefers the one that needs nothing opened.

    Parked because `TAP` carries no arguments and every step below reads it back.
    """
    return (
        _RALLY_PRELUDE_MINE +
        "local r = rallies[1] "
        "local afd = DataCenter.ArmyFormationDataManager "
        # index -> formation uuid + how many soldiers are standing in it, read once
        "local uuid_of, soldiers_of = {}, {} "
        "for _, v in pairs(afd.ArmyFormationList) do "
        "local ok, idx = pcall(function() return v.index end) "
        "if ok and idx ~= nil then local key = tostring(idx) "
        "pcall(function() uuid_of[key] = v.uuid end) "
        "local n = 0 pcall(function() n = tonumber(v.totalSoldierNum) or 0 end) "
        "soldiers_of[key] = n end end "
        "local slot = nil "
        "for _, s in ipairs(squads) do "
        "if slot == nil and (soldiers_of[tostring(s)] or 0) > 0 then slot = s end end "
        "if slot == nil then slot = squads[1] end "
        "if slot == nil or r == nil then DataCenter.__lw_rally_join = nil "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_arm none squads="..#squads'
        '.." rallies="..#rallies) return end '
        "local fu = uuid_of[tostring(slot)] "
        "if fu == nil then DataCenter.__lw_rally_join = nil "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_arm noformation squad="..tostring(slot)) '
        "return end "
        "DataCenter.__lw_rally_join = {squad = slot, formation = fu, point = r.point, "
        "team = r.team, server = r.server} "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_arm squad="..tostring(slot)'
        '.." soldiers="..tostring(soldiers_of[tostring(slot)])'
        '.." team="..tostring(r.team).." point="..tostring(r.point))'
    )


def rally_join_armed() -> str:
    """Lua *expression* -> 1 when there is a rally to join and a squad to join it with."""
    return ("(function() local p = DataCenter.__lw_rally_join "
            "if p == nil or p.formation == nil then return 0 end return 1 end)()")


def rally_join_soldiers() -> str:
    """Lua *expression* -> soldiers standing in the armed squad, or -1 if unreadable.

    The one thing the squad screen does that the send cannot do for itself: a squad with
    heroes and NO soldiers is refused by the client before a byte leaves — the send's own
    constants are `hasSolider` and `GameDialogDefine.ADD_SOLDIER`, and what the player is
    shown is the «add soldiers» tip rather than an error.

    Nothing here can put soldiers in an empty squad, so a run that reads 0 has nothing to
    send with: either the screen fills the squad from the base's pool, or — when the pool
    is empty too, which is what an evening of rallies leaves behind — the answer is the
    hospital and not this ability.
    """
    return ("(function() local p = DataCenter.__lw_rally_join "
            "if p == nil or p.formation == nil then return -1 end "
            "local afd = DataCenter.ArmyFormationDataManager local n = -1 "
            "for _, f in pairs(afd.ArmyFormationList) do "
            "local ok, u = pcall(function() return f.uuid end) "
            "if ok and tostring(u) == tostring(p.formation) then "
            "pcall(function() n = tonumber(f.totalSoldierNum) or -1 end) end end "
            "return n end)()")


def rally_join_send() -> str:
    """Join the armed rally with NO screen: build the march message and send it.

    This is the same call the game itself ends up making — the squad screen's launch
    walks `OnCheckTime` -> `OnCreateClick` -> `TryStartMarch` -> this — and its Lua reads
    nothing off any window: the payload comes from `GetFormationStartPos` and
    `ArmyFormationDataManager:GetOneArmyInfoByUuid`, i.e. from the squad itself.

    What made the direct send look impossible for weeks was the END POINT, not the path:
    it was aimed at the monster the rally is going to attack instead of the tile the
    joiners gather on (#1237, and `joinpoint` in `_RALLY_PRELUDE`). Every other
    explanation chased — the thirteenth argument, the hero arrays, the message body —
    sat downstream of that.

    Called straight, not through `TimerManager:DelayInvoke` as the old press was: the
    screen's own launch runs synchronously from this same daemon thread and works, and a
    send hidden behind a timer cannot say whether it threw — which is half of what a run
    needs to know when nothing appears on the map.
    """
    return (
        _RALLY_JOIN_PARAMS +
        "if p.formation == nil then error('no rally armed for this run') end "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(p.formation, 6, p.point, p.team, 1, 1, false, "
        "p.server, nil) end) "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_send squad="..tostring(p.squad)'
        '.." team="..tostring(p.team).." point="..tostring(p.point)'
        '.." server="..tostring(p.server).." ok="..tostring(ok).." err="..tostring(err))'
    )


def rally_join_in() -> str:
    """Lua *expression* -> 1 when one of our marches is already standing in the armed rally.

    Asked between the screenless send and the fallback that opens the screens, because a
    send that landed a moment late must not cost a SECOND squad: the ability spends one
    squad per rally and the whole point of the fallback is the case where nothing was
    spent at all.
    """
    return (
        "(function() local p = DataCenter.__lw_rally_join if p == nil then return 0 end "
        "local P = LuaEntry.Player local wm = DataCenter.WorldMarchDataManager "
        "local col = wm:GetAllMarches() if col == nil then return 0 end "
        "local e = col:GetEnumerator() while e:MoveNext() do local mo = e.Current "
        "local ok, v = pcall(function() return mo.Value end) if ok and v ~= nil then mo = v end "
        "local t, u = nil, nil pcall(function() t = mo.teamUuid u = mo.ownerUid end) "
        "if t ~= nil and tostring(t) == tostring(p.team) "
        "and tostring(u) == tostring(P.uid) then return 1 end end "
        "return 0 end)()")


def squads_fill_empty() -> str:
    """Ask the server for the army of every parked squad the client shows as empty.

    THE EMPTY SQUAD WAS NEVER EMPTY — the client simply had not asked (#1285). A squad
    reads `totalSoldierNum = 0` with `soldiers = {}` in a session where nothing has
    needed the number yet, and everything downstream treats that as «no army»: the send
    refuses it before a byte leaves (`hasSolider`, `GameDialogDefine.ADD_SOLDIER`), the
    join sieve reports it as `empty`, and the run ends having spent nothing.

    One message fixes it and no window is opened::

        SFSNetwork.SendMessage(MsgDefines.GetFormationSoldier, formationUuid)
                               -- «formation.get.soldier»

    Measured live on a client whose three squads all read 0 while the base held
    thousands of soldiers: **0 -> a full squad in 0.37 s**, that time including the two
    VM round trips around it. The reply lands in `RefreshFormationSoldier`, which fills
    `formation.soldiers` (posIndex -> {soldierId = count, supply}) and the total the
    gates read. So this is a FETCH, not a recruitment: it makes the client agree with
    the server about an army the server already had.

    None of the client's own fillers can do it. `AutoInitFormationData`,
    `AutoAddSoldierByForm`, `AutoAddSoldier` (both `useForm`) and `FetchFormationSoldier`
    were each pressed on a live empty squad and each returned cleanly having changed
    nothing (0 -> 0). They all draw on `ArmyManager:GetArmyFreeList()`, which walks
    `ArmyManager.allArmy` — and that table is EMPTY on a client that has not been sent
    `army.info`. Asking for `army.info` by hand does not fill it either.

    A SQUAD THAT IS STILL 0 AFTER THIS IS GENUINELY EMPTY, and that is the reading the
    caller wants: `squads_filled_count()` counts the ones that came back with an army,
    and a run that asked and got nothing may say «the squad is empty» and mean it.

    Which squads it asks for is parked in `DataCenter.__lw_fill_squads` (the slots the
    player sees, 1/2/3/4); with nothing parked it asks for every squad the game knows.
    `TAP` carries no arguments of its own, which is why it is parked rather than passed.
    """
    return (
        "local afd = DataCenter.ArmyFormationDataManager "
        "local want = nil local list = DataCenter.__lw_fill_squads "
        "if type(list) == 'table' and #list > 0 then want = {} "
        "for _, s in ipairs(list) do want[tostring(s)] = true end end "
        "local asked, held, names, refused = 0, 0, {}, {} "
        "for _, f in pairs(afd.ArmyFormationList) do "
        "local idx, uuid, num = nil, nil, 0 "
        "pcall(function() idx = f.index uuid = f.uuid "
        "num = tonumber(f.totalSoldierNum) or 0 end) "
        "if idx ~= nil and (want == nil or want[tostring(idx)]) then "
        "if num > 0 then held = held + 1 else "
        "local ok, err = pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.GetFormationSoldier, uuid) end) "
        "if ok then asked = asked + 1 names[#names + 1] = tostring(idx) "
        "else refused[#refused + 1] = tostring(idx) .. ':' .. tostring(err) end "
        "end end end "
        "DataCenter.__lw_fill_asked = asked "
        "DataCenter.__lw_fill_wanted = names "
        "DataCenter.__lw_fill_report = 'asked=' .. tostring(asked) "
        ".. ' already-loaded=' .. tostring(held) "
        ".. ((#names > 0) and (' squads=[' .. table.concat(names, ' ') .. ']') or '') "
        ".. ((#refused > 0) and (' refused=[' .. table.concat(refused, ' ') .. ']') or '') "
        'CS.UnityEngine.Debug.LogError("ACT squads_fill_empty "'
        "..DataCenter.__lw_fill_report)"
    )


def squads_filled_count() -> str:
    """Lua *expression* -> how many of the squads just asked for now hold an army.

    Counted over `DataCenter.__lw_fill_wanted` — the slots `squads_fill_empty` actually
    sent a request for — so a squad that was already loaded is not counted as a success
    this press did not earn, and a squad the server answered for with nothing stays at
    zero and is the honest «this one really is empty».

    **-1 means nothing was asked for** — every chosen squad already held its army, or the
    press did not run. A third answer rather than a zero, because the recipe polls on
    `filled == 0` and a run with nothing to wait for must not spend the poll: this is
    CALLed from `join_rally.md` with a banner standing on the map.

    NOT ONE BRACE IN IT, and that is a constraint rather than a style: `actions/
    fill_empty_squads.md` inlines this same text in a `READ_LUA`, and the DSL reads `{…}`
    inside a line as one of the run's own arguments. A Lua table constructor in a recipe
    is an argument the recipe never declared, so the set-of-wanted-slots this would
    naturally be written with is a nested loop instead — over at most four squads.
    """
    return (
        "(function() local names = DataCenter.__lw_fill_wanted "
        "if type(names) ~= 'table' or #names == 0 then return -1 end "
        "local afd = DataCenter.ArmyFormationDataManager local n = 0 "
        "for _, f in pairs(afd.ArmyFormationList) do "
        "local idx, num = nil, 0 "
        "pcall(function() idx = f.index num = tonumber(f.totalSoldierNum) or 0 end) "
        "if idx ~= nil and num > 0 then "
        "for _, s in ipairs(names) do "
        "if tostring(s) == tostring(idx) then n = n + 1 end end end end "
        "return n end)()"
    )


def join_next_rally() -> str:
    """Send the next parked squad to the next rally it is not already in.

    One press per chunk: the squad is dropped from the queue and the rally marked
    as taken BEFORE the send, so a refused join costs one squad rather than wedging
    `xall` on the same rally forever.

    Superseded by `rally_join_send` + the fallback in `actions/join_rally.md`, which
    ask the map whether the send achieved anything instead of assuming it did. Kept
    because `tools/rally_join.py` drives the same shape from a shell, and corrected
    to `joinpoint` with it: this one spent months aiming at the monster.
    """
    return (
        _RALLY_PRELUDE +
        "local slot=squads[1] local r=rallies[1] "
        "if slot==nil or r==nil then "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_skip squads="..#squads.." rallies="..#rallies) '
        "return end "
        "local formation=nil local warm=false "
        "local afd=DataCenter.ArmyFormationDataManager "
        "for _,v in pairs(afd.ArmyFormationList) do "
        "local ok,idx=pcall(function() return v.index end) "
        "if ok and tostring(idx)==tostring(slot) then pcall(function() formation=v.uuid end) end "
        "local ok2,n=pcall(function() return v.totalSoldierNum end) "
        "if ok2 and (n or 0)>0 then warm=true end end "
        "table.remove(squads,1) DataCenter.__lw_rally_squads=squads "
        "if formation==nil then "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_skip no formation for squad "..tostring(slot)) '
        "return end "
        "local taken2=DataCenter.__lw_rally_joined or {} taken2[tostring(r.team)]=true "
        "DataCenter.__lw_rally_joined=taken2 "
        # Where the JOINER goes — the leader's own tile — and not where the rally is
        # going. See `joinpoint` in `_RALLY_PRELUDE`.
        "local jp = r.joinpoint or r.point "
        "if not warm then "
        "pcall(function() MarchUtil.OnClickStartMarch(6,jp,r.team,-1,1,7,r.server,0,0) end) "
        "pcall(function() GoToUtil.CloseAllWindows() end) end "
        "TimerManager:GetInstance():DelayInvoke(function() pcall(function() "
        "MarchUtil.SendCreateMarchMessage(formation,6,jp,r.team,1,1,false,r.server,nil) "
        "end) end,0.5) "
        'CS.UnityEngine.Debug.LogError("ACT rally_join squad="..tostring(slot)'
        '.." team="..tostring(r.team).." point="..tostring(jp)'
        '.." server="..tostring(r.server).." warmed="..tostring(not warm))'
    )


# --------------------------------------------------------------------------
# Alliance rally: RAISE one («Стягивание»)
# --------------------------------------------------------------------------
# The CREATE side — the other half of the join above. `tools/rally_create.py`
# drives it from Python and `docs/research/rally-create.md` is the write-up; these
# are the same four presses as pressable buttons, so a recipe (and therefore the
# Scenarios tab and a timer) can raise a banner.
#
# It is a FLOW, not a single send, and each press needs the window the previous one
# opened to actually be there:
#
#     «лупа» (UISearch) -> the target's popup (UIWorldPoint)
#         -> the squad screen (UIFormationSelectListV2 / …New) -> launch
#
# So the presses stay four separate buttons with the polls between them written in
# the recipe (`WHILE` + `WAIT` + `READ_LUA`), never a Lua loop waiting on the server
# inside one chunk — that is the client freeze docs/dsl.md warns about.
#
# WHAT to rally is parked first, the same trick the join side uses for its squads:
# `TAP` carries no arguments, so `actions/create_rally.md` writes the run's target
# into `DataCenter.__lw_rally_create` and every press below reads it back.
#
#     DataCenter.__lw_rally_create = {
#         squad     = 1,          -- the slot the player sees (1/2/3/4)
#         level     = 35,         -- 1..200, clamped by the search press
#         kind      = "boss",     -- "boss" = Роковая Элита, "monster" = field monster
#         formation = <uuid>,     -- the squad's formation, resolved when parked
#     }
#
# `formation` is resolved at park time, BEFORE anything is opened, so a squad that
# does not exist stops the recipe instead of leaving a monster popup hanging open on
# the map (the same order rally_create.create_on_level keeps).

# The parked run, and the «лупа» tab its kind maps to. The tab numbers are the
# UISearchType enum read live: 5 = Boss (the Fatal Elite, `find.monster.boss`),
# 1 = Monster (ordinary field monsters, `find.monster`) — docs/research/rally-elite-search.md.
_RALLY_CREATE_PARAMS = "local p = DataCenter.__lw_rally_create or {} "
_RALLY_SEARCH_TAB = "local st = 5 if tostring(p.kind) == 'monster' then st = 1 end "

# The two windows the squad screen can be, depending on the `formation_v2_switch` config.
_FORMATION_WIN = (
    "local function _isformation(w) return w ~= nil and "
    "(w.Name == 'UIFormationSelectListV2' or w.Name == 'UIFormationSelectListNew') end "
)


def rally_create_arm() -> str:
    """Finish the parked run: resolve the squad's formation and note the rally count.

    The recipe parks the three plain values it was given (`squad`, `level`, `kind`);
    this fills in the two the game has to be asked for, BEFORE anything is opened:

    * `formation` — the uuid of the squad slot the player sees. Formations live in
      `ArmyFormationDataManager.ArmyFormationList` keyed by uuid, each carrying an
      `index` = that slot number, and the formation uuid is the first argument of the
      send the launch button eventually makes. A slot with no formation leaves this
      nil, which is the recipe's cue to stop before a target popup is left hanging
      open on the map.
    * `before` — how many rallies of ours are already out, so the raise can be
      *measured* afterwards rather than assumed from a press that returned cleanly.
    """
    return (
        "local p = DataCenter.__lw_rally_create or {} "
        "local afd = DataCenter.ArmyFormationDataManager "
        "for _, v in pairs(afd.ArmyFormationList) do "
        "local ok, idx = pcall(function() return v.index end) "
        "if ok and tostring(idx) == tostring(p.squad) then "
        "pcall(function() p.formation = v.uuid end) end end "
        "p.before = %s "
        "DataCenter.__lw_rally_create = p "
        'CS.UnityEngine.Debug.LogError("ACT rally_arm squad="..tostring(p.squad)'
        '.." level="..tostring(p.level).." kind="..tostring(p.kind)'
        '.." formation="..tostring(p.formation).." rallies="..tostring(p.before))'
        % own_rally_count()
    )


def rally_armed() -> str:
    """Lua *expression* -> 1 when the parked run has a squad the game knows."""
    return ("(((DataCenter.__lw_rally_create or {}).formation ~= nil) and 1 or 0)")


def rally_raised() -> str:
    """Lua *expression* -> rallies of ours gained since `rally_create_arm()` ran.

    1 once the banner is standing. Reading the DIFFERENCE rather than the count is
    what makes this work with rallies already out — a player leading one elsewhere
    starts from a non-zero count.
    """
    return "(%s - ((DataCenter.__lw_rally_create or {}).before or 0))" % own_rally_count()


def rally_search_open() -> str:
    """Open the world-map search («лупа») — the window the level is typed into."""
    return "UIManager.Instance:OpenWindow(UIWindowNames.UISearch)"


def rally_search_fire() -> str:
    """Set the parked level on the parked tab and press the magnifier.

    `OnSearchClick(type, subType)` reads the level back through
    `GetCurNumBySearchType` and fires the server request; subType 0 is the default
    sub-tab (a nil one trips the game's own recorder). The answer is not waited for
    here — the server flies the camera in and opens the target's popup by itself
    (`OnSearchEnd` -> `GoToUtil.MoveToWorldMarchAndOpen`), which the recipe polls for.

    The level is clamped to 1..200, the range both tabs accept; a level the server
    has nothing for simply comes back empty, like any other miss.
    """
    return (
        _RALLY_CREATE_PARAMS + _RALLY_SEARCH_TAB +
        "local lvl = tonumber(p.level) or 1 "
        "if lvl < 1 then lvl = 1 end if lvl > 200 then lvl = 200 end "
        "local w = UIManager.Instance:GetStackTopWindow() "
        "if not w or w.Name ~= 'UISearch' then "
        "error('the search window is not open (top is '..tostring(w and w.Name)..')') end "
        "w.Ctrl:SetCurNumBySearchType(st, lvl, 0) "
        "w.Ctrl:OnSearchClick(st, 0) "
        'CS.UnityEngine.Debug.LogError("ACT rally_search level="..lvl.." type="..st)'
    )


def rally_target_state() -> str:
    """Lua *expression* -> what the search brought up: 1 ralliable, -1 not, 0 nothing yet.

    The reliable test is the popup's own action button, not `canAttack`: a rally
    target carries exactly one and it names itself `RallyBoss`, while a soloable
    monster names itself `AttackMonster` and nothing turns that into a rally.

    `0` also covers "the window is up but its monster data has not landed yet" — the
    data arrives a beat after the window — so the recipe polls this until it moves.
    """
    return (
        "(function() local w = UIManager.Instance:GetStackTopWindow() "
        "if not w or w.Name ~= 'UIWorldPoint' then return 0 end "
        "local c = w.Ctrl local lvl = nil "
        "pcall(function() lvl = c:GetMonsterData(c.uuid).level end) "
        "if lvl == nil then return 0 end "
        "local b = '?' pcall(function() b = tostring(c:GetPointBtnEnumName(w.View.btnList[1])) end) "
        "if b == 'RallyBoss' then return 1 end return -1 end)()"
    )


def rally_banner_press() -> str:
    """Press «Стягивание» on the open target popup.

    Exactly the two arguments the button's own handler passes —
    `OnClickStartMarch(RALLY_FOR_BOSS, pointId, uuid)` — and the game fills the rest
    (server, wait time, auto-return) in on the squad screen it opens. THE POPUP MUST
    STILL BE ON TOP: closing it first is what made the target "hide" with nothing
    pressed.
    """
    return (
        "local w = UIManager.Instance:GetStackTopWindow() "
        "if not w or w.Name ~= 'UIWorldPoint' then "
        "error('the target popup is not open (top is '..tostring(w and w.Name)..')') end "
        "MarchUtil.OnClickStartMarch(MarchTargetType.RALLY_FOR_BOSS, w.Ctrl.pointId, w.Ctrl.uuid) "
        'CS.UnityEngine.Debug.LogError("ACT rally_banner point="..tostring(w.Ctrl.pointId)'
        '.." uuid="..tostring(w.Ctrl.uuid))'
    )


def rally_panel_ready() -> str:
    """Lua *expression* -> 1 once the squad screen the rally press opens is on top."""
    return ("(function() " + _FORMATION_WIN +
            "if _isformation(UIManager.Instance:GetStackTopWindow()) then return 1 end "
            "return 0 end)()")


def rally_squad_pick() -> str:
    """Pick the parked squad on the open squad screen.

    `View:OnSelectClick` is the tap (it repaints the cells and the cost),
    `Ctrl:SetSelectFormationUuid` is what the tap ultimately records; both are done
    so the screen and the send agree. Nothing is sent here — the launch is a press of
    its own, and the recipe only makes it once the pick has been read back.
    """
    return (
        _FORMATION_WIN + _RALLY_CREATE_PARAMS +
        "local w = UIManager.Instance:GetStackTopWindow() "
        "if not _isformation(w) then "
        "error('the squad screen is not open (top is '..tostring(w and w.Name)..')') end "
        "if p.formation == nil then error('no squad parked for this run') end "
        "pcall(function() w.View:OnSelectClick(p.formation) end) "
        "w.Ctrl:SetSelectFormationUuid(p.formation) "
        'CS.UnityEngine.Debug.LogError("ACT rally_squad sel="..tostring(w.Ctrl.selectFormationUuid))'
    )


def rally_squad_picked() -> str:
    """Lua *expression* -> 1 when the open squad screen really holds the parked squad."""
    return (
        "(function() " + _FORMATION_WIN + _RALLY_CREATE_PARAMS +
        "local w = UIManager.Instance:GetStackTopWindow() "
        "if not _isformation(w) then return 0 end "
        "if p.formation ~= nil and tostring(w.Ctrl.selectFormationUuid) == tostring(p.formation) "
        "then return 1 end return 0 end)()"
    )


def rally_launch() -> str:
    """Press the squad screen's launch button.

    `Ctrl:OnCheckTime(formationUuid, destroyTimeIndex)` is what its View calls: the
    game's own pre-checks (rally cap, wait-time and transport warnings) and then
    `OnCreateClick` -> `SendCreateMarchMessage`. The screen closes itself on success.
    """
    return (
        _FORMATION_WIN + _RALLY_CREATE_PARAMS +
        "local w = UIManager.Instance:GetStackTopWindow() "
        "if not _isformation(w) then "
        "error('the squad screen is not open (top is '..tostring(w and w.Name)..')') end "
        "w.Ctrl:OnCheckTime(p.formation, nil) "
        'CS.UnityEngine.Debug.LogError("ACT rally_launch formation="..tostring(p.formation))'
    )


def own_rally_count() -> str:
    """Lua *expression* -> how many of the player's own marches are part of a rally.

    A raised banner adds one. That increase is the only thing that proves a rally
    went out: a plain march count moves for unrelated reasons, and
    `IsHaveMarchInWorld()` is already true whenever anything at all is out.
    """
    return (
        "(function() local wm = DataCenter.WorldMarchDataManager "
        "local om = wm:GetOwnerMarches() local n = 0 "
        "if om then local e = om:GetEnumerator() while e:MoveNext() do "
        "local mo = e.Current.Value if mo == nil then mo = e.Current end "
        "local ok, t = pcall(function() return mo.teamUuid end) "
        "if ok and t ~= nil and tostring(t) ~= '0' and tostring(t) ~= 'nil' then n = n + 1 end "
        "end end return n end)()"
    )


# --------------------------------------------------------------------------
# The resource truck standing on the base ("Сбор ресурсов с грузовика")
# --------------------------------------------------------------------------
# Recording `20260730_130004_Сбор_ресурсов_с_грузовика` — the player tapped the
# truck parked on the base, pressed "collect", then closed the congratulation
# modal. The whole flow is ONE command sent three times with a different
# `action`, and the trace (filter=SFS, dedup=false) spells it out:
#
#     SFSNetwork.SendMessage <- lw.pve.idle.reward, 0     -- tap: read what is banked
#       -> SFSObject.PutInt(action, 0)
#     SFSNetwork.SendMessage <- lw.pve.idle.reward, 1     -- "collect": take it
#       -> push.resource.item.update                      -- the resources land
#     SFSNetwork.SendMessage <- lw.pve.idle.reward, 0     -- modal closed: re-read
#
# So the payload is a single int (`{"action":N}` on the wire) and there is no
# uuid, no world position and no bubble to hunt for — `action=1` *is* the
# collect, headless, with nothing open. The captured reply to `action=1` carries
# the whole banked pile in one go (`reward:[{type:1,…},{type:20,…},{type:31,…},
# {type:27,…}]` plus the `dominator*` bonus lists and a fresh
# `lastIdleRewardTimeStamp`), which is why this is a single press and not `xall`:
# one claim empties the accumulator.
#
# Note this is NOT the `BuildBubbleType.TruckReward` bubble press behind the
# older `collect_trucks` button. That one was derived from a *deduped* trace
# (`20260728_171442`, `dedup=True`), so it never showed a wire command at all;
# this recording is the first one that does, and the command it shows is the
# base's idle-reward accumulator.
#
# There is no readiness gate here yet: the client-side counter that says how much
# is banked is only known from the `action=0` reply, which a single Lua chunk
# cannot read back. A claim on an empty accumulator therefore costs one refused
# call (the server's own tip), the same shape as the hospital collect press.

_TRUCK_REWARD_MSG = "lw.pve.idle.reward"


def truck_reward_refresh() -> str:
    """Ask the server what the base's resource truck is currently holding.

    `lw.pve.idle.reward` with `action=0` — the read the client fires both when the
    truck is tapped and again after the reward modal is closed. Sends nothing else
    and changes nothing; it just makes the client's own numbers current.
    """
    return (
        "local ok,err = pcall(function() "
        "SFSNetwork.SendMessage('%s', 0) "
        'CS.UnityEngine.Debug.LogError("ACT truck_reward_refresh sent") '
        "end) "
        'if not ok then CS.UnityEngine.Debug.LogError("ACT truck_reward_refresh skip: "..tostring(err)) end'
        % _TRUCK_REWARD_MSG
    )


def truck_reward_collect() -> str:
    """Collect the resource truck parked on the base — the "collect" press itself.

    `lw.pve.idle.reward` with `action=1`, exactly what the recorded press sent. One
    call takes everything the accumulator holds (base resources plus the bonus
    lists), so pressing it twice in a row has nothing left to take — do not loop it.
    Nothing needs to be open: no window, no bubble, no camera position.
    """
    return (
        "local ok,err = pcall(function() "
        "SFSNetwork.SendMessage('%s', 1) "
        'CS.UnityEngine.Debug.LogError("ACT truck_reward_collect sent") '
        "end) "
        'if not ok then CS.UnityEngine.Debug.LogError("ACT truck_reward_collect skip: "..tostring(err)) end'
        % _TRUCK_REWARD_MSG
    )


def base_collect_ready_count() -> str:
    """Lua *expression* -> how many base buildings have something banked to collect.

    THE SAME PREDICATE THE PRESS USES, deliberately: `collect_base_resources` sweeps
    every production line whose `GetBuildingCurrStorage(uuid)` is at least 1, because
    that is precisely what the server accepts (below 1 it answers 602026 «still in
    production» and the client pops a toast per building — task #1087). Counting by
    any other rule would give a checklist that says «4 ready» where the press finds
    none, and the two would drift apart the first time either changed.

    A read: it collects nothing and sends nothing.
    """
    return ("(function() local plm=DataCenter.ProductLineManager local n=0 "
            "for _,u in pairs(plm:GetAllBuildUuids() or {}) do "
            "local ok,stor=pcall(function() return plm:GetBuildingCurrStorage(u) end) "
            "if ok and (stor or 0)>=1 then n=n+1 end end return n end)()")


def trucks_ready_count() -> str:
    """Lua *expression* -> how many supply trucks have arrived and are waiting.

    The bubbles `collect_trucks` taps, counted rather than pressed:
    `BuildBubbleType.TruckReward` / `TruckReady`. A truck still on the road wears
    `TruckTravelling` and is not counted — it is not work the person can do yet.
    """
    return ("(function() local m=DataCenter.BuildBubbleManager local BT=_G.BuildBubbleType "
            "if not m or not BT then return 0 end local n=0 "
            "for _,v in pairs(m.allBuildBubble or {}) do "
            "local ty=v.param and v.param.buildBubbleType "
            "if ty==BT.TruckReward or ty==BT.TruckReady then n=n+1 end end "
            "return n end)()")


# --------------------------------------------------------------------------
# Sending trade trucks out ("Отправка грузовиков")
# --------------------------------------------------------------------------
# A DIFFERENT truck from the two above. `trucks_ready_count` counts the supply
# trucks that have ARRIVED at the base and `truck_reward_*` empties the idle
# accumulator parked on it; these three read the TRADE STATION — the fleet the
# player dispatches to another server and other players rob on the way
# (`UILWTruckSuperDeparture`, docs/research/ui-open.md).
#
# `DataCenter.LWMyStationDataManager` owns all of it, and the three numbers a
# person actually wants are already computed there rather than derivable from the
# fleet list (read live, #1249):
#
#   GetDepartureCount()      how many went out today
#   GetMaxDailyCount()       today's allowance — the BASE four plus whatever the
#                            «Extra Truck» tech adds, so never a constant
#   GetRealReadyCount()      how many could go out RIGHT NOW: trucks standing at
#                            the station in `TruckStationState.Ready`, capped by
#                            what is left of the allowance
#
# Every one of them is nil-guarded on `IsTruckFunctionLock()` FIRST, and that
# guard is the whole point: the trade station is locked until the base reaches
# level 8, and a locked client still answers `GetDepartureCount() == 0`. Drawn
# straight, that reads as «nothing sent yet today» on an account that cannot send
# anything at all — a to-do the person can never tick off. Returning nil instead
# makes the reading say `-`, which the checklist draws as «state unknown»
# (`panel/tabs/checklist/model.py`: a feature this account has not unlocked is
# exactly one of the things a dash is for).
#
# There is NO press here yet. Dispatching is `train.send` / `train.batch.send`
# with an escorting squad per truck and a rarity refresh in front of it; until
# that is a scenario, the panel reads these and offers no button (#1249).
#
# Every call is wrapped in its own parentheses before `tonumber`: these three
# return TWO values, and `tonumber(a, b)` reads the second as a base, which fails
# with «string expected, got number» rather than with a wrong count.

_TRUCK_STATION = ("local M=DataCenter and DataCenter.LWMyStationDataManager "
                  "if not M or M:IsTruckFunctionLock() then return nil end ")


def truck_dispatch_left() -> str:
    """Lua *expression* -> trade-truck dispatches still banked today, or nil.

    The quota's remaining half, the same shape every other daily allowance on the
    board is read in (`secret_task_steals_left`): allowance minus what has gone,
    floored at zero so a cap that shrinks mid-day cannot show a negative.
    """
    return ("(function() " + _TRUCK_STATION +
            "local cap=tonumber((M:GetMaxDailyCount())) or 0 "
            "local used=tonumber((M:GetDepartureCount())) or 0 "
            "local left=cap-used if left<0 then left=0 end return left end)()")


def truck_dispatch_cap() -> str:
    """Lua *expression* -> how many trade trucks may go out today at all, or nil.

    Four to start with and more with the «Extra Truck» tech, which is why it is
    read rather than written down: the number differs per account and grows.
    """
    return ("(function() " + _TRUCK_STATION +
            "return tonumber((M:GetMaxDailyCount())) or 0 end)()")


def truck_dispatch_ready() -> str:
    """Lua *expression* -> trade trucks that could be dispatched right now, or nil.

    The client's own `GetRealReadyCount`: trucks standing at the station in
    `TruckStationState.Ready`, capped by what is left of today's allowance. So it
    is «how many presses are available», not «how many trucks exist» — a fleet of
    four with one dispatch left answers 1.
    """
    return ("(function() " + _TRUCK_STATION +
            "return tonumber((M:GetRealReadyCount())) or 0 end)()")


def secret_task_steal_cap() -> str:
    """Lua *expression* -> the daily robbery cap (5 on the live account).

    Split out from :func:`secret_task_steals_left` so a reading can show «2 из 5» and
    not just «3 left»: a quota is only readable as spent-of-allowed, and the allowed
    half is a server setting that has changed before.
    """
    return ("(tonumber(DataCenter.ActDispatchTaskDataManager:"
            "GetDispatchSetting('steal_count')) or 0)")


def ghost_recon_steal_cap() -> str:
    """Lua *expression* -> the ghost-recon daily robbery cap. See the note above."""
    return ("(function() local cfg=DataCenter.ActGhostreconManager:GetNowSettingCfg() "
            "return tonumber(cfg and cfg.stealCount) or 0 end)()")


# --- Base decorations: the handbook's upgrade press --------------------------
# Session `20260730_142543_Повышение_украшений` recorded the press itself; the rest
# of this was read out of the live Lua VM afterwards, because the first recipe built
# from the wire alone did nothing in game (task #1125).
#
# The wire, from the trace (the tracer ran with `filter="SFS"`, so ONLY SFS calls were
# recorded — the building/handbook/cell taps are simply not in the file, and their
# absence there proves nothing about them):
#
#     SFSNetwork.SendMessage <- decorator.progress.upgrade, <buildUuid>, 1
#       SFSObject.PutLong  buildUuid, <buildUuid>
#       SFSObject.PutInt   num, 1
#
# The two parameters are NOT free-form:
#
#   * `buildUuid` is the decoration GROUP's representative building, the one
#     `BuildManager:GetMaxLvBuildDataByBuildId(itemId)` returns. Fed that itemId
#     (103401000) it hands back exactly the uuid in the recording. Any other building
#     of the same decoration is the wrong target — sending one is accepted by the
#     client and changes nothing (proven live).
#   * `num` is a COUNT of progress steps to buy, not a slot index: the real press,
#     `UIDecorationAdvanceUpgrade:OnLevelUpClick`, sends `curCanUpgradeNum`, which is
#     1 for a single tap and more for a long press.
#
# The first gate is `BuildingUtils.IsExistAdvanceUpgrade(itemId, level)` — the decoration
# has an "advance upgrade" step at its current level. Without it the server refuses the
# send outright: `errorCode = building_center_tips4`,
# `errorMsg = "building no extra_lvup_para"` (captured live off the reply).
#
# The second gate is the material, and it is a SPARE DUPLICATE of the decoration, not a
# currency. `BuildingUtils.GetDecorateUpLevelBuilds(buildData)` returns the feed cells the
# window renders, one per level that can be fed in:
#
#     {itemId = 103404001, count = 2, needScore = 484, nextScore = 486, levelTemplate, buildData}
#
# `count` is how many steps are buyable right now — the spare copies held, capped by what
# is still missing to the next star threshold (`math.min` inside the reader). It is exactly
# the `curCanUpgradeNum` the real press sends. One spare copy = one progress point.
#
# `BuildManager:IsCanUpgradeDecoration(itemId, level, buildData)` is NOT this gate, and an
# earlier revision of this block wrongly used it. It returns `hasCount, upgradeNeedCount`
# in *glue value* (`equal_glue_value` off the level template) and prices the ordinary
# decoration LEVEL upgrade — 29160 for level 6 -> 7 — against holdings of ~110. Read as a
# material gate it is never satisfiable, so the button never pressed. Proven wrong by the
# 20260730_162054 recording: the player upgraded 103402000 by hand while that pair read
# 110 / 29160, and the window's own readout was the spare count (green `1/100` before the
# press, red `0/99` after) with the star bar moving 386 -> 387 of 486.
#
# So one press is: pick a decoration group that passes both gates, resolve its uuid from
# the itemId, send `{buildUuid, num}`. No window is opened; the handbook the player walked
# through is UI only.
#
# Proven live on 2026-07-30 by this button, one step at a time, on decoration 103404000
# (level 6, two spares banked): the star score went 484/486 -> 485/486 and the spare count
# 2 -> 1, so the press moved real progress and the game charged for it. The uuid it sent is
# the one `GetMaxLvBuildDataByBuildId` resolves — the same identity both hand recordings
# put on the wire for their own groups.

_DECOR_UPGRADE_MSG_KEY = "MsgDefines.DecoratorProgressUpgradeMessage"

# Walks the decoration groups and hands each one that has an upgrade step to `cb` as
# `(itemId, buildData, steps)`, where `steps` is how many progress steps the banked spare
# duplicates would buy right now (0 = nothing to feed). Shared by the count, the press and
# the dump so the three can never disagree about what "ready" means.
_DECOR_SCAN = (
    "local bm=DataCenter.BuildManager "
    "local function scan(cb) "
    "for itemId in pairs(bm:GetAllDecoratorBuildingData() or {}) do "
    "local ok,d=pcall(function() return bm:GetMaxLvBuildDataByBuildId(itemId) end) "
    "if ok and d then "
    "local ok2,adv=pcall(function() return BuildingUtils.IsExistAdvanceUpgrade(itemId,d.level) end) "
    "if ok2 and adv then "
    "local ok3,cells=pcall(function() return BuildingUtils.GetDecorateUpLevelBuilds(d) end) "
    "local steps=0 "
    "if ok3 and type(cells)=='table' then "
    "for _,c in pairs(cells) do local n=tonumber(c.count) if n and n>0 then steps=steps+n end end end "
    "if cb(itemId,d,steps) then return true end end end end return false end "
)


def decoration_upgrade_ready_count() -> str:
    """Lua *expression* -> how many progress steps are affordable across all decorations.

    This is a count of STEPS, not of decorations: a group holding two spare duplicates
    contributes two, so `TAP upgrade_decoration xall` spends every one of them. Zero is
    the normal reading — a spare copy of a decoration is a rare thing to be holding.
    """
    return ("(function() %s local n=0 "
            "scan(function(_,_,steps) n=n+steps end) "
            "return n end)()" % _DECOR_SCAN)


def upgrade_next_decoration(count: int = 1) -> str:
    """Upgrade the first decoration that is ready — the whole press, self-contained.

    Finds the group itself (no target has to be parked first), resolves the uuid the
    game would use and sends `count` progress steps. With nothing ready it logs why
    and sends nothing, so running it on a schedule costs one VM call and no refusals.

    One step per press by default: the reply refreshes the group, so the next press
    re-reads what is left instead of trusting a stale count.
    """
    return (
        "%s local fired=false "
        "scan(function(itemId,d,steps) "
        "if steps>0 then "
        "local num=math.min(%d,steps) "
        "pcall(function() SFSNetwork.SendMessage(%s, d.uuid, num) end) "
        'CS.UnityEngine.Debug.LogError("ACT decor_upgrade item="..tostring(itemId)..'
        '" uuid="..tostring(d.uuid).." lv="..tostring(d.level)..'
        '" num="..tostring(num).." of "..tostring(steps)) '
        "fired=true return true end end) "
        'if not fired then CS.UnityEngine.Debug.LogError("ACT decor_upgrade_skip nothing ready") end'
        % (_DECOR_SCAN, int(count), _DECOR_UPGRADE_MSG_KEY)
    )


def decoration_upgrade(item_id: int, count: int = 1) -> str:
    """Upgrade one named decoration group by its `item_id` — the targeted press.

    The uuid is resolved in game (`GetMaxLvBuildDataByBuildId`), never hard-coded: it
    belongs to the account and changes when the group's top building does.
    """
    return (
        "local bm=DataCenter.BuildManager "
        "local ok,d=pcall(function() return bm:GetMaxLvBuildDataByBuildId(%d) end) "
        "if ok and d then "
        "pcall(function() SFSNetwork.SendMessage(%s, d.uuid, %d) end) "
        'CS.UnityEngine.Debug.LogError("ACT decor_upgrade item=%d uuid="..tostring(d.uuid).." num=%d") '
        'else CS.UnityEngine.Debug.LogError("ACT decor_upgrade_skip item=%d not on the base") end'
        % (int(item_id), _DECOR_UPGRADE_MSG_KEY, int(count), int(item_id), int(count), int(item_id))
    )


def decoration_state_dump() -> str:
    """Log every decoration that has an upgrade step, with the steps its spares would buy.

    This is the "why is nothing happening?" reading: a line per group with how many steps
    its spares would buy and a READY marker on the ones a press would actually take.

    The star score is printed only for a group that has something to feed. With no spare
    banked the reader's `needScore` degenerates to `nextScore`, which would read as "this
    one is maxed out" when it only means "nothing to feed here" — so that line says
    `no-spares` and the threshold instead of a score it cannot know.
    """
    return (
        "%s local n,ready=0,0 "
        "scan(function(itemId,d,steps) n=n+1 "
        "if steps>0 then ready=ready+1 end "
        "local score,goal='?','?' "
        "pcall(function() local cells=BuildingUtils.GetDecorateUpLevelBuilds(d) "
        "for _,c in pairs(cells or {}) do goal=c.nextScore "
        "if tonumber(c.count) and tonumber(c.count)>0 then score=c.needScore end end end) "
        'CS.UnityEngine.Debug.LogError("ACT decor item="..tostring(itemId)..'
        '" uuid="..tostring(d.uuid).." lv="..tostring(d.level)..'
        '" score="..(steps>0 and (tostring(score).."/"..tostring(goal)) '
        'or ("no-spares (goal "..tostring(goal)..")"))..'
        '" steps="..tostring(steps)..(steps>0 and "  READY" or "")) end) '
        'CS.UnityEngine.Debug.LogError("ACT decor_groups="..tostring(n).." ready="..tostring(ready))'
        % _DECOR_SCAN
    )


def decorations_window() -> str:
    """Open the base's decoration window — the manual path, for looking at it."""
    return ("pcall(function() UIManager.Instance:OpenWindow(UIWindowNames.UIDecorationMain) end) "
            'CS.UnityEngine.Debug.LogError("ACT decorations_window opened")')


# --------------------------------------------------------------------------
# The account's characters, and switching the client to one of them
# --------------------------------------------------------------------------
# The list is what the server answers to `account.login.new` — one entry per
# character, parsed into `DataCenter.AccountManager.rolesList`. Where it comes
# from, and why the client's login cache is NOT it, is docs/research/account-list.md.
#
# Switching used to reproduce the LOGIN SCREEN's cell handler
# (`UIAccountListCell.OnBtnSelectClick`), which builds its message out of
# `AccountManager.param` — a table only that screen fills. From inside a session it
# therefore sent `az.account.login` with an empty `userName` and the server answered
# `120618 email format error` (captured, #1190). It reported "sent" and switched
# nothing.
#
# The game's own route is the CHARACTER screen's cell: `UIRolesCell:OnBtnClick`
# opens `UIWindowNames.UIRoleLogin` for the picked role, and that window's
# «войти» press is `UIRoleLoginView:OnClickLogin`, whose whole body (read out of the
# live VM with `string.dump`) is:
#
#     CS.AccountCredentialManager.ClearAll()
#     CS.AccountCredentialManager.SetServerNetInfo(param.ip, param.port, param.zone)
#     CS.AccountCredentialManager.SetLoginKey(param.loginKey)
#     CS.AccountCredentialManager.SetUID(param.gameUid)
#     CS.AccountCredentialManager.Save()
#     CS.AIHelp.AIHelpProxy.Logout()
#     EventManager:GetInstance():Broadcast(EventId.SwitchAccount)
#     SFSNetwork.SendMessage(MsgDefines.UserCleanPost)
#
# — i.e. write the picked character's credentials over the saved ones, then tell the
# server the session is done with. Every field it needs (`ip`, `port`, `zone`,
# `loginKey`, `gameUid`) is in the role record the server sent; nothing is invented
# and no window has to be opened. `ip` is a pipe-separated list of hosts and `port` a
# string — both are passed on exactly as the game passes them.
#
# That is NOT the whole press, and the missing half cost a live run that did nothing:
# the relog is done by the REPLY to `user.clean.post`. Its handler
# (`Net.Msgs.Account.UserCleanPostMessage:HandleMessage`) is one call —
# `CS.SwitchAccountCheckGameVersionTools.ReloadGameByCheckLauncherVersion()` — and
# that is what actually drops the session and logs back in with what was just saved.
# Sent from inside a session by hand, that reply never came: the handler was hooked
# and watched for 14 s across three sends and never fired, while the client sat on the
# old character. So the press makes the same call itself, right after the send.
#
# Proven live (#1192, 2026-08-02): 100 -> 200 and back, in-process — the game keeps
# its pid, so the Lua daemon survives the relog and the panel needs no reattach. The
# client comes back on the new character's base about ten seconds later.

#: Where the recipe parks the server id to switch to (`TAP` carries no arguments).
_SWITCH_VAR = "DataCenter.__lw_switch_account"

#: Walk `rolesList` and hand each real character to `fn`. The screen prepends an
#: `isEmpty` placeholder (its "add a character" slot) which is not a character.
_ROLES_SCAN = (
    "local function scan(fn) "
    "local roles = DataCenter.AccountManager.rolesList "
    "if type(roles) ~= 'table' then return end "
    "for _, v in pairs(roles) do "
    "if type(v) == 'table' and not v.isEmpty then fn(v) end end end "
)


def account_roles_request() -> str:
    """Ask the server for this account's characters — headless, opens no window.

    `account.login.new` carries only the device id, and the reply lands
    asynchronously as `push.account.login.new`, which fills
    `DataCenter.AccountManager.rolesList`. Poll :func:`account_roles_count` after it
    rather than expecting the list to be there when this returns.
    """
    return (
        "local ok,err = pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.AccountLoginNew) "
        'CS.UnityEngine.Debug.LogError("ACT account_roles_request sent") '
        "end) "
        'if not ok then CS.UnityEngine.Debug.LogError("ACT account_roles_request skip: "..tostring(err)) end'
    )


def account_roles_count() -> str:
    """Expression: how many characters the server has named so far (0 before it answers)."""
    return ("(function() local n = 0 %s scan(function() n = n + 1 end) return n end)()"
            % _ROLES_SCAN)


def account_switch_target() -> str:
    """Expression: can the parked server id be switched to right now?

    ``1`` the character is there and is not the one in play, ``0`` no character of
    this account is on that server, ``-1`` that character is already in play. The
    recipe turns each into its own refusal, so "nothing happened" is never the answer.
    """
    return (
        "(function() local sid = tostring(%s or 0) local hit = 0 %s "
        "scan(function(v) if tostring(v.id) == sid then hit = 1 end end) "
        "if hit == 0 then return 0 end "
        "local cur = 0 pcall(function() cur = LuaEntry.Player.serverId end) "
        "if tostring(cur) == sid then return -1 end return 1 end)()"
        % (_SWITCH_VAR, _ROLES_SCAN)
    )


def account_switch_press() -> str:
    """Switch the live client to the character parked in ``__lw_switch_account``.

    The «войти» press of the game's own `UIRoleLogin` window plus the relog its reply
    would have triggered, run without opening anything (see the block comment above).
    Saves that character's credentials over the current ones, tells the server the
    session is done, and reloads the client — which comes back on the new character
    about ten seconds later, in the same process.

    Fire-and-forget: the reconnect cannot be observed from inside the same chunk, so
    the recipe checks afterwards that `LuaEntry.Player.serverId` moved.
    """
    return (
        "local ok,err = pcall(function() "
        "local sid = tostring(%s or 0) local role %s "
        "scan(function(v) if tostring(v.id) == sid then role = v end end) "
        "if role == nil then "
        'CS.UnityEngine.Debug.LogError("ACT account_switch skip: no character on "..sid) return end '
        "local A = CS.AccountCredentialManager "
        "A.ClearAll() "
        "A.SetServerNetInfo(role.ip, role.port, role.zone) "
        "A.SetLoginKey(role.loginKey) "
        "A.SetUID(role.gameUid) "
        "A.Save() "
        "pcall(function() CS.AIHelp.AIHelpProxy.Logout() end) "
        "EventManager:GetInstance():Broadcast(EventId.SwitchAccount) "
        "SFSNetwork.SendMessage(MsgDefines.UserCleanPost) "
        'CS.UnityEngine.Debug.LogError("ACT account_switch sent server="..sid) '
        # The relog itself — what the reply to `user.clean.post` does in the game, and
        # what nothing does when the message is sent by hand. Last, so a client that
        # goes down mid-call has already saved the credentials it will come back with.
        "CS.SwitchAccountCheckGameVersionTools.ReloadGameByCheckLauncherVersion() "
        "end) "
        'if not ok then CS.UnityEngine.Debug.LogError("ACT account_switch skip: "..tostring(err)) end'
        % (_SWITCH_VAR, _ROLES_SCAN)
    )


def account_switch_arm(serverid) -> str:
    """Park the server id the next :func:`account_switch_press` should switch to."""
    return "%s = %d" % (_SWITCH_VAR, int(serverid))


def account_current_server() -> str:
    """Expression: the server of the character in play (0 while the client is reconnecting).

    `WorldFavoDataManager.curServerId` is empty on a freshly logged-in client, so the
    player's own record is asked first and that is only the fallback.
    """
    return ("(function() local cur = 0 "
            "pcall(function() cur = LuaEntry.Player.serverId end) "
            "if not cur or tonumber(cur) == nil or tonumber(cur) == 0 then "
            "pcall(function() cur = DataCenter.WorldFavoDataManager.curServerId end) end "
            "return tonumber(cur) or 0 end)()")


def account_roles_dump() -> str:
    """Log one `ACT R …` line per character, with everything the server said about it.

    Text fields are hex-encoded because the log line is read back through a marker
    that is not binary-safe and nicknames are not ASCII. `tools/account_switch.py`
    parses these lines; the panel's «Аккаунты» tab draws them.
    """
    return (
        "local function hex(s) return (tostring(s):gsub('.', function(c) "
        "return string.format('%%02x', c:byte()) end)) end "
        "local function L(s) CS.UnityEngine.Debug.LogError('ACT '..s) end "
        "pcall(function() "
        "L('cur='..tostring(%s)) %s "
        "scan(function(v) L('R serverid='..tostring(v.id)"
        "..' gameUid='..tostring(v.gameUid)"
        "..' level='..tostring(v.gameUserLevel or 0)"
        "..' power='..tostring(v.power or 0)"
        "..' picVer='..tostring(v.picVer or 0)"
        "..' nick='..hex(tostring(v.gameUserName or ''))"
        "..' zone='..hex(tostring(v.zone or ''))"
        "..' alliance='..hex(tostring(v.alAbbr or ''))"
        "..' uuid='..hex(tostring(v.uuid or ''))"
        "..' pic='..hex(tostring(v.pic or ''))) end) end)"
        % (account_current_server(), _ROLES_SCAN)
    )


# --------------------------------------------------------------------------
# «Кодовое имя» — the world-boss event (`Codename`, the game's own key 100086)
# --------------------------------------------------------------------------
# The event puts one boss on the world map for a few hours at a time («Кодовое имя
# 87/39/64», one per pair of weekdays) and asks for three attacks on it. Attempts
# themselves are UNLIMITED — the game's own rules say so and the client agrees
# (`attackMaxNum = -1`) — so the thing the day owes is not an allowance being spent
# but a count being reached: three attacks earn the reward, and the biggest single
# hit is what the daily ranking is made of.
#
# Everything below reads or presses `DataCenter.ActBossDataManager`, which is where
# the client keeps the whole event:
#
#   IsBossAvailable()      is the boss attackable RIGHT NOW: a stage with a start
#                          and an end, checked against the server's clock. The event
#                          runs Monday to Saturday and the stage covers the whole day
#                          (23 hours from the server's midnight), so outside it means
#                          Sunday, not «between windows». The four times in
#                          `bossRefreshTimeSvr` are when the boss RESPAWNS during the
#                          day, not four separate windows.
#
#                          IT ANSWERS «no» ON A CLIENT THAT HAS NOT ASKED. The stage
#                          list it reads (`stageTimeList`) arrives only in the reply to
#                          `user.get.act.boss.march`, which the game itself sends when
#                          it opens the event's own screen. A panel that never asked
#                          reads a nil list and draws «событие не идёт» over a running
#                          event — which is exactly what happened until #1259. Every
#                          reading of this manager therefore sends `codename_fetch()`
#                          first and waits for `codename_loaded()`.
#   actBossTransTimes      attacks made in the current window. The server owns it:
#                          it is refreshed by `UserGetActBossMarch` and announced as
#                          `OnActBossAttackTimesRefresh`, so it counts an attack sent
#                          from anywhere — this panel, the phone, the person playing.
#   rewardMaxTimes         how many attacks earn the reward. Three, from the config,
#                          read rather than written down here.
#   maxDamage              the biggest single hit, which is the number the ranking
#                          uses and the number the person wants to see.
#   GetActBossDataList()   the boss instances themselves: uuid, monsterId, startPos
#                          and the window they live in.
#
# The reverse-engineering is docs/research/codename-event.md.
_CODENAME_MGR = "DataCenter.ActBossDataManager"
_CODENAME_PARAMS = "local p = DataCenter.__lw_codename or {} "


def codename_fetch() -> str:
    """Ask the server for the event's bosses and its stage — the game's own get.

    `user.get.act.boss.march` is what the client sends for itself (`RefreshTransTime`)
    and what the reply handler `RefreshActBossDataList` fills BOTH `stageTimeList` and
    `actBossDataList` from. Nothing is changed by it: it is a read of the server's
    state, and the game fires it whenever it opens the event's screen.

    It has to be sent by us because nothing else will. `RefreshTransTime` returns early
    on a client whose stage list is still nil — the very state a panel-driven client is
    always in — so the manager would sit empty for the whole session and every reading
    beside it would be last session's or none. Send this, wait for `codename_loaded()`,
    then read.
    """
    return ('pcall(function() SFSNetwork.SendMessage(MsgDefines.UserGetActBossMarch) end) '
            'CS.UnityEngine.Debug.LogError("ACT codename_fetch sent")')


def codename_loaded() -> str:
    """Lua *expression* -> 1 once the fetch's reply has landed, else 0.

    The stage list is the thing the reply brings and the thing `IsBossAvailable()`
    reads, so its arrival is what «the answer is now worth reading» means. It stays 0
    on a day the event does not run — there is no stage to send — which is why every
    caller waits for it with a LIMIT rather than until it turns 1.
    """
    return ("((type(%s.stageTimeList) == 'table') and 1 or 0)" % _CODENAME_MGR)


def codename_open() -> str:
    """Lua *expression* -> 1 while the boss can be attacked right now, else 0.

    Ask `codename_fetch()` first and wait for `codename_loaded()`, or this answers «no»
    on a running event — the stage list it reads arrives only in that reply.

    The gate the whole feature hangs off: outside a window there is no boss on the
    map, and every count beside it is last window's. Drawn as «событие не идёт»
    rather than as a zero, because those are different answers.
    """
    return ("(function() local ok, v = pcall(function() return %s:IsBossAvailable() end) "
            "if not ok then return nil end return (v and 1 or 0) end)()" % _CODENAME_MGR)


def codename_attacks_made() -> str:
    """Lua *expression* -> attacks made on the boss in the current window."""
    return ("(function() local ok, v = pcall(function() return %s.actBossTransTimes end) "
            "if not ok then return nil end return math.floor(tonumber(v) or 0) end)()"
            % _CODENAME_MGR)


def codename_attacks_needed() -> str:
    """Lua *expression* -> how many attacks earn the reward (three, from the config)."""
    return ("(function() local ok, v = pcall(function() return %s.rewardMaxTimes end) "
            "if not ok then return nil end return math.floor(tonumber(v) or 0) end)()"
            % _CODENAME_MGR)


def codename_attacks_left() -> str:
    """Lua *expression* -> how many of the day's attacks are still owed, or nil.

    `needed - made`, floored at zero, and nil when either half could not be read — the
    same three-way answer every other reading here gives, because «none left» and
    «nobody knows» are different states and a caller that conflates them either skips a
    day's reward or marches at a client that cannot answer.

    One copy of the arithmetic, spelled here rather than in each caller: the «События»
    board draws it, `read_codename_event.md` reports it and `attack_codename_daily.md`
    loops on it, and a board that said two while the loop believed three would be worse
    than no number at all.
    """
    return ("(function() local a = %s local n = %s if a == nil or n == nil then "
            "return nil end local l = n - a if l < 0 then l = 0 end return l end)()"
            % (codename_attacks_made(), codename_attacks_needed()))


def codename_max_damage() -> str:
    """Lua *expression* -> the biggest single hit landed on the boss.

    What the daily ranking is made of, per the event's own rules: only the highest
    damage dealt in ONE attack counts.
    """
    return ("(function() local ok, v = pcall(function() return %s.maxDamage end) "
            "if not ok then return nil end return math.floor(tonumber(v) or 0) end)()"
            % _CODENAME_MGR)


def codename_targets() -> str:
    """Lua *expression* -> how many boss instances the client has on the map."""
    return ("(function() local ok, l = pcall(function() return %s:GetActBossDataList() end) "
            "if not ok or type(l) ~= 'table' then return nil end "
            "local n = 0 for _ in pairs(l) do n = n + 1 end return n end)()" % _CODENAME_MGR)


def codename_seconds_left() -> str:
    """Lua *expression* -> seconds left in the open window, or nil when none is open."""
    return ("(function() local ok, st = pcall(function() return %s:GetAttackStageData() end) "
            "if not ok or type(st) ~= 'table' then return nil end "
            "local e = tonumber(st.endTime) if e == nil then return nil end "
            "local now = tonumber(UITimeManager:GetInstance():GetServerTime()) or 0 "
            "local left = e - now if left < 0 then left = 0 end "
            "return math.floor(left) end)()" % _CODENAME_MGR)


def codename_arm() -> str:
    """Set the attack run up: pick the boss, pick a free squad, note the count.

    All three before anything is opened, for the reason `rally_create_arm` does the
    same: a run that finds out at the last press that there was no squad has already
    flown the camera across the map and left a popup open on it.

    * `uuid` / `point` / `server` — the boss. Taken from `GetActBossDataList()`, whose
      entries carry the uuid the march is addressed to and a `startPos` the map index
      is made of. `startPos` is read through every shape it is known to take (a
      table with `x`/`y`, a pair, a ready-made index), because the list is empty
      outside a window and there was no live one to look at when this was written.
    * `formation` — the FIRST squad standing in the base. «Свободный отряд» is what
      the button says and what it means: a squad already marching, gathering or
      standing in somebody else's rally cannot be sent, and the game only says so at
      the last press.
    * `before` — attacks made so far, so the attack can be MEASURED afterwards rather
      than assumed from a press that returned cleanly.
    """
    return (
        _CODENAME_PARAMS +
        "p.uuid, p.point, p.server, p.formation = nil, nil, nil, nil "
        "pcall(function() "
        "local lst = %(mgr)s:GetActBossDataList() "
        "for _, b in pairs(lst or {}) do "
        "if p.uuid == nil then "
        "p.uuid = b.uuid "
        "pcall(function() p.server = tonumber(b.serverId) or tonumber(b.srcServer) end) "
        "local sp = b.startPos "
        "if type(sp) == 'table' then "
        "local x, y = tonumber(sp.x), tonumber(sp.y) "
        "if x ~= nil and y ~= nil then p.point = math.floor(y) * 1000 + math.floor(x) "
        "else p.point = tonumber(sp[1]) end "
        "else p.point = tonumber(sp) end "
        "end end end) "
        "pcall(function() "
        "local best = nil "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "local idx = tonumber(v.index) "
        "local st = tonumber(v.state) "
        "local ok, idle = pcall(function() return v:IsFree() end) "
        "local free = true if ok and idle ~= nil then free = (idle and true or false) end "
        "if idx ~= nil and st == 0 and free and (best == nil or idx < best.idx) then "
        "best = {idx = idx, uuid = v.uuid} end end "
        "if best ~= nil then p.formation, p.squad = best.uuid, best.idx end end) "
        "p.before = %(made)s "
        "DataCenter.__lw_codename = p "
        'CS.UnityEngine.Debug.LogError("ACT codename_arm boss="..tostring(p.uuid)'
        '.." point="..tostring(p.point).." squad="..tostring(p.squad)'
        '.." formation="..tostring(p.formation).." attacks="..tostring(p.before))'
        % {"mgr": _CODENAME_MGR, "made": codename_attacks_made()}
    )


def codename_armed() -> str:
    """Lua *expression* -> what the arm found: 1 all set, 0 no boss, -1 no free squad."""
    return (
        "(function() " + _CODENAME_PARAMS +
        "if p.uuid == nil or p.point == nil then return 0 end "
        "if p.formation == nil then return -1 end return 1 end)()"
    )


def codename_send() -> str:
    """Send the squad at the boss — the whole attack, in one call, with no window.

    This is the LAST thing the squad screen does when a person taps «Марш», with the
    arguments it passes, read off the wire while the player made one attack by hand
    (#1259) and then reproduced byte for byte:

        SendCreateMarchMessage(formation, DIRECT_ATTACK_ACT_BOSS, point, uuid,
                               timeIndex = 1, autoBackHome = 1, needSoldier = false,
                               targetServerId = server, destroyTimeIndex = nil)

    so nothing between the event's «Атака» and that call has to be walked at all: no
    camera flight, no tile waiting to be streamed in, no popup, no squad screen. The
    boss is addressed by uuid, and the server builds the path itself — the message that
    leaves carries `start;target` as a pair it works out from the formation.

    `CROSS_DIRECT_ATTACK_ACT_BOSS` when the boss stands on another server; the arm parks
    its `serverId` so this can tell.

    Scheduled on the main thread through `TimerManager:DelayInvoke`, for the reason
    every other launch in this file is (`attack.py`): a cold send from the hijack
    thread returns `true` and is dropped by the server.
    """
    return (
        _CODENAME_PARAMS +
        "if p.formation == nil or p.uuid == nil then error('nothing armed for this run') end "
        "local kind = MarchTargetType.DIRECT_ATTACK_ACT_BOSS "
        "local home = nil pcall(function() home = tonumber(LuaEntry.Player:GetSelfServerId()) end) "
        "if p.server ~= nil and home ~= nil and tonumber(p.server) ~= home then "
        "kind = MarchTargetType.CROSS_DIRECT_ATTACK_ACT_BOSS end "
        "TimerManager:GetInstance():DelayInvoke(function() "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(p.formation, kind, p.point, p.uuid, "
        "1, 1, false, p.server, nil) end) "
        'CS.UnityEngine.Debug.LogError("ACT codename_send ok="..tostring(ok).." err="..tostring(err)) '
        "end, 0.4) "
        'CS.UnityEngine.Debug.LogError("ACT codename_send scheduled squad="..tostring(p.squad)'
        '.." boss="..tostring(p.uuid).." kind="..tostring(kind))'
    )


def codename_sent() -> str:
    """Lua *expression* -> attacks gained since the arm ran. 1 once one has gone out.

    The DIFFERENCE, not the count: a window the person has already attacked in starts
    from a non-zero number, and the server owns the counter, so this is the one thing
    that proves an attack was really launched rather than merely pressed.
    """
    return ("((%s or 0) - ((DataCenter.__lw_codename or {}).before or 0))"
            % codename_attacks_made())


# ---------------------------------------------------------------------------
# «Вход с другого устройства» — the kick, as the CLIENT shows it
# ---------------------------------------------------------------------------
# The game is single-session: logging the account in elsewhere kicks this client and
# puts a modal on it. CAUGHT LIVE on 2026-08-06 with the player kicking it on purpose
# while this polled twice a second — the whole recording, and the two guesses it
# disproved, is docs/research/session-kick.md.
#
# THE WINDOW IS `UICommonMessageTip`, and it is NOT `UIDisconnect` or
# `UICrossDisconnect` — those two exist, and stayed shut. Its `View.tipText` carries the
# message, word for word:
#
#     Внимание
#     В ваш аккаунт был выполнен вход с другого устройства     (the game's key E100083)
#
# AND IT IS INVISIBLE TO THE WINDOW STACK. The window sets `DontPushWindowStack`, so
# `GetStackTopWindow()` answers nil and `WindowStack` is empty with the modal plainly on
# screen. That is exactly how the earlier reading concluded «a kick leaves no trace in
# the client» — wrong accessor as well as wrong moment. `IsWindowOpen` is the only one
# that sees it.
#
# `UICommonMessageTip` is a GENERIC dialog and is not, by itself, proof of a kick — the
# client uses it for anything. While the question was asked ONLY on a lost link the pair
# was conclusive enough (a merely stranded client shows no window at all, watched live
# twice): lost link + a message tip with text = kicked.
#
# THAT PAIR IS NOT THE QUESTION ANY MORE (#1270). A kick can sit behind a link that reads
# `online` — one established socket out of six — so the flag is now asked on every poll
# and in front of every send, and on a healthy client «some dialog is open» would be a
# false kick, whose cure is a restart. So the expression hands back the TEXT and
# `tools/lib/game_kick.py` decides, by comparing it with the game's own wording for key
# `E100083` out of the client's own language tables. One reading, and the strength of
# the evidence is judged where the sentences are.

def kick_tip() -> str:
    """Lua *expression* -> the text of the open message dialog, or '' if none is open.

    Both halves matter. `IsWindowOpen` first, because `GetWindow` hands back a window
    that has been CLOSED with its last text still on it — a stale sentence read off a
    shut dialog would be a kick that ended minutes ago. And the text rather than a flag,
    because the dialog is generic: the words are the only thing that tells a kick from
    every other message the client puts up (`tools/lib/game_kick.py`).

    Answers '' for anything it cannot read, so it can only ever ADD a reason, never
    remove one.
    """
    return ("(function() local ok, v = pcall(function() "
            "local m = UIManager.Instance "
            "if not m:IsWindowOpen('UICommonMessageTip') then return '' end "
            "local w = m:GetWindow('UICommonMessageTip') "
            "local t = w and w.View and w.View.tipText "
            "return t == nil and '' or tostring(t) end) "
            "if not ok then return '' end return v end)()")


# ---------------------------------------------------------------------------
# The keyboard macros: send the squad the game is ALREADY asking for (#1283)
# ---------------------------------------------------------------------------
# A person clicks a target on the map — a monster, a mine, another player's base,
# anything — presses the popup's action, and the game puts up the squad-selection
# screen. Everything the march needs is on that screen by then, and #1283 read it off
# a live client rather than guessing:
#
#     UIFormationSelectListV2  (or …New, depending on the `formation_v2_switch` config)
#         Ctrl.targetType      -- MarchTargetType: 7 rally, 11 attack a base, 1 a
#                                 monster, 2 gather, 6 join a rally, …
#         Ctrl.targetPoint     -- the target's tile index
#         Ctrl.targetUuid      -- the target's server uuid, which is what addresses it
#         Ctrl.targetServerId  -- whose server it stands on
#         Ctrl.timeIndex       -- the wait slot (a rally's countdown; 1 for a plain march)
#         Ctrl.autoBackHome    -- come back by itself
#         Ctrl.selectFormationUuid -- the squad the screen has highlighted
#
# The class is readable WITHOUT the window being open —
# `UIManager.Instance.windowsConfig[UIWindowNames.UIFormationSelectListV2].Ctrl` is the
# class table — which is how those names were found: `string.dump` on its `InitData`
# and `OnCreateClick` ([[project_lua_string_dump_decompile]]).
#
# Two different sends, on purpose:
#
#   * keys 1..4 press the screen's OWN launch button, `Ctrl:OnCheckTime(formation, nil)`
#     -> `OnCreateClick` -> `SendCreateMarchMessage`. The macro replaces the mouse and
#     nothing else, so every pre-check the game makes for that target type — stamina,
#     power warnings, the rally cap, the transport warning — still happens, and the
#     screen closes itself exactly as it does under a finger. This is the same press
#     `rally_launch` makes;
#   * CapsLock has no screen to press, so it sends `SendCreateMarchMessage` itself with
#     the arguments the last launch went out with, the way `codename_send` does.
#
# Both are parked in the game VM rather than in the panel: `TAP` carries no arguments,
# and the memory has to outlive the scenario that filled it.
#
#     DataCenter.__lw_macro      = {squad, formation, type, point, target, server,
#                                   timeIndex, back, need, before}
#     DataCenter.__lw_macro_last = the same, as the last launch actually sent it
#
# docs/research/march-hotkeys.md is the write-up.

_MACRO = "local p = DataCenter.__lw_macro or {} "
_MACRO_LAST = "local m = DataCenter.__lw_macro_last or {} "

#: The two windows the squad screen can be — the same pair `_FORMATION_WIN` names for
#: the rally flow, found wherever it sits rather than only on top: a confirmation the
#: game puts over it must not read as "the person never opened one".
_MACRO_FIND = (
    "local function _findscreen() "
    "local m = UIManager.Instance "
    "local top = m:GetStackTopWindow() "
    "if top ~= nil and (top.Name == 'UIFormationSelectListV2' "
    "or top.Name == 'UIFormationSelectListNew') then return top end "
    "local found = nil "
    "for _, n in ipairs({'UIFormationSelectListV2', 'UIFormationSelectListNew'}) do "
    "pcall(function() if found == nil and m:IsWindowOpen(n) then found = m:GetWindow(n) end end) "
    "end return found end "
)


#: The click watcher (#1328). Two halves, both parked in the game's VM:
#:
#:   * `DataCenter.__lw_pick_read(ctrl)` — turn ONE world-point popup controller into a
#:     pin: the tile, the uuid, whose server it stands on, what kind of point it is, and
#:     — the part that decides everything — WHICH march the macro would send at it;
#:   * a wrapper around `UIWorldPointCtrl:InitData`, the method the popup fills itself in
#:     with. The class table is `UIManager.Instance.windowsConfig[UIWindowNames
#:     .UIWorldPoint].Ctrl` and every instance indexes into it, so wrapping it once
#:     catches every click there is — a finger on the map, `GoToUtil.OnClickWorldPoint`,
#:     a jump out of the magnifier — without the panel polling anything.
#:
#: THE KIND IS READ, NEVER GUESSED. `WorldPointUIType` and `MarchTargetType` are the
#: game's own enums, asked for BY NAME, so a season that renumbers them changes nothing
#: here. Four kinds are supported and the rest are refused by name in the log:
#:
#:     Monster / Boss  -> ATTACK_MONSTER, and only when the point's own monster detail
#:                        says `canAttack == 1`. `0` is a rally-only target, which is
#:                        raised through its own screen and never by this macro — the
#:                        same refusal `macro_repeat` has made since #1283;
#:     City            -> ATTACK_CITY, unless the base is the player's own;
#:     CollectPoint    -> COLLECT (a resource tile addresses by tile, `uuid` is 0);
#:     CollectArmy     -> ATTACK_ARMY_COLLECT (somebody else's squad, mid-gather).
#:
#: `GetMonsterData` MUST be passed the uuid — called bare it answers a one-field stub
#: with `canAttack = 0` and every monster reads as rally-only (world-monsters.md,
#: Finding 8). It is called here, at pin time, because the popup's controller is the only
#: thing that can answer it and it is gone by the time a key is pressed.
_PICK_READ = (
    "DataCenter.__lw_pick_read = function(s) "
    "local U = WorldPointUIType or {} local M = MarchTargetType or {} "
    "local p = {} "
    "pcall(function() p.point = tonumber(s.pointId) end) "
    "pcall(function() p.target = s.uuid end) "
    "pcall(function() p.kind = tonumber(s.type) end) "
    "pcall(function() p.server = tonumber(s.serverId) end) "
    "pcall(function() p.at = tonumber(UITimeManager:GetInstance():GetServerSeconds()) end) "
    "pcall(function() p.home = tonumber(LuaEntry.Player.serverId) end) "
    "pcall(function() p.who = tostring(LuaEntry.Player.uid) end) "
    "p.mine = 0 "
    "pcall(function() if tostring(s.ownerUid) == tostring(LuaEntry.Player.uid) "
    "then p.mine = 1 end end) "
    # WHO OPENED THIS POPUP — the person, or the panel? The bot opens world-point popups
    # of its own all day (a rally hunt, a treasure sweep, a jump to coordinates), and a
    # macro that took the newest one would put somebody's squad on the tile an automation
    # was looking at rather than the one they clicked. A scripted open runs INSIDE a
    # chunk this repository sent, and a chunk compiled from a string reports
    # `short_src = [string "…"]`, while the game's own Lua reports its file path — so the
    # stack says which it was. (The proof it was worth doing: the very first pin caught
    # live came from the panel's own automation, not from a finger. And `short_src`, not
    # `source`: the raw source of a `SafeDoString` chunk is just its name.)
    "p.script = 0 "
    "pcall(function() for lvl = 1, 14 do local i = debug.getinfo(lvl, 'S') "
    "if i == nil then break end "
    "if string.sub(tostring(i.short_src or ''), 1, 7) == '[string' then "
    "p.script = 1 break end "
    "end end) "
    "p.can = -1 "
    "for n, v in pairs(U) do if tonumber(v) == p.kind then p.kindname = tostring(n) end end "
    "if p.kind ~= nil and (p.kind == U.Monster or p.kind == U.Boss) then "
    # A monster whose detail cannot be read at all is a monster that needs a banner, not
    # an unknown kind of point: `0` before the call, so a failed read refuses with the
    # sentence that fits rather than with «the macro does not march on that».
    "p.can = 0 "
    "pcall(function() local md = s:GetMonsterData(s.uuid) "
    "p.can = tonumber(md and md.canAttack) or 0 end) "
    "if p.can == 1 then p.mtt = tonumber(M.ATTACK_MONSTER) end "
    "elseif p.kind ~= nil and p.kind == U.City then "
    "if p.mine == 0 then p.mtt = tonumber(M.ATTACK_CITY) end "
    "elseif p.kind ~= nil and p.kind == U.CollectPoint then "
    "p.mtt = tonumber(M.COLLECT) "
    "elseif p.kind ~= nil and p.kind == U.CollectArmy then "
    "p.mtt = tonumber(M.ATTACK_ARMY_COLLECT) end "
    "if p.point ~= nil then local _y = math.floor(p.point / 1000) "
    "p.desc = tostring(p.kindname) .. ' @[' .. tostring(p.point - _y * 1000) "
    ".. ',' .. tostring(_y) .. '|' .. tostring(p.server or p.home) .. ']' end "
    "return p end "
)

#: Wrap `InitData` once and leave it wrapped. The original is kept on the class under a
#: name of ours, which is also the flag that says it has been done — a second arming is
#: a no-op rather than a wrapper around a wrapper. The reader above is re-assigned every
#: time regardless, so a client that was armed by an older panel picks up a fixed one.
#:
#: The original runs FIRST and unprotected: `InitData` is what fills the popup in, and a
#: popup that opened blank because a macro was listening would be a far worse bug than
#: any this file fixes. Everything of ours is inside `pcall`, and its return values are
#: handed back untouched.
_PICK_ARM = _PICK_READ + (
    "pcall(function() "
    "local cfg = UIManager.Instance.windowsConfig[UIWindowNames.UIWorldPoint] "
    "local cls = cfg and cfg.Ctrl "
    "if cls == nil then return end "
    "if rawget(cls, '__lw_pick_orig') ~= nil then return end "
    "local orig = cls.InitData "
    "if type(orig) ~= 'function' then return end "
    "cls.__lw_pick_orig = orig "
    "cls.InitData = function(s, ...) "
    "local r = table.pack(orig(s, ...)) "
    "pcall(function() DataCenter.__lw_macro_pick = DataCenter.__lw_pick_read(s) end) "
    "return table.unpack(r, 1, r.n) end "
    "end) "
)

#: The popup itself, wherever it sits — the same shape `_MACRO_FIND` uses for the squad
#: screen, and for the same reason: a confirmation the game puts over it must not read
#: as «there is nothing open».
_PICK_FIND = (
    "local function _findpopup() "
    "local m = UIManager.Instance "
    "local top = m:GetStackTopWindow() "
    "if top ~= nil and top.Name == 'UIWorldPoint' then return top end "
    "local found = nil "
    "pcall(function() if m:IsWindowOpen('UIWorldPoint') then "
    "found = m:GetWindow('UIWorldPoint') end end) "
    "return found end "
)


def macro_pick_arm() -> str:
    """Lua *statement* -> arm the click watcher, and say nothing if it already is.

    Cheap enough to run in front of every key press, which is where it runs: `macro_send`
    starts with it, so a client that restarted between two presses is watched again
    without anybody noticing. See :data:`_PICK_ARM` for what it wraps and why.
    """
    return _PICK_ARM


def macro_pick_result() -> str:
    """Lua *expression* -> the pinned target's kind, as the game names it, `?` if none."""
    return "tostring((DataCenter.__lw_macro_pick or {}).kindname or '?')"


def macro_pick_desc() -> str:
    """Lua *expression* -> what the last press aimed at, in words. `-` when it aimed at
    the open squad screen instead, because that target was never a pin."""
    return "tostring((DataCenter.__lw_macro or {}).desc or '-')"


def own_march_count() -> str:
    """Lua *expression* -> how many marches of ours are out right now, -1 if unreadable.

    The proof a macro really sent something. A press that returned cleanly proves the
    call ran; this is the number the SERVER moves, and it moves for a march of any kind
    — an attack, a gather, a rally — which is exactly the range of targets a macro is
    pointed at. `own_rally_count()` above counts the subset that is part of a rally.
    """
    return (
        "(function() local ok, n = pcall(function() "
        "local om = DataCenter.WorldMarchDataManager:GetOwnerMarches() local c = 0 "
        "if om then local e = om:GetEnumerator() while e:MoveNext() do c = c + 1 end end "
        "return c end) if not ok then return -1 end return n end)()"
    )


def macro_send() -> str:
    """Send the chosen squad at whatever the person last chose, in ONE call (#1290/#1328).

    Two ways to a target, tried in that order inside one chunk:

    1. **The squad screen, if one is open** — the #1283 path, unchanged. Everything the
       march needs is on that screen, the launch is the game's own `Ctrl:OnCheckTime`, and
       the macro replaces the MOUSE and nothing else.
    2. **The target the person CLICKED, if no screen is open** (#1328). The click watcher
       (:data:`_PICK_ARM`) pinned it the moment the map tap opened its popup, so the send
       goes out with no window at all — the shape `macro_repeat` has been proving since
       #1283. If nothing is pinned but the popup is still open, it is read on the spot:
       that covers the very first press after a client restart, when the watcher was
       armed a moment too late to have seen the click.

    The order is deliberate. A person who has opened the squad screen went that way on
    purpose, and the screen's own target is both fresher and more complete (a rally's wait
    slot is a field of the screen, not of the tile).

    WHAT IT DECIDED lands in `DataCenter.__lw_macro.result`, which the recipe reads back
    (`macro_result`) to say WHICH of the two, or WHICH refusal:

    ``1`` the open screen's launch was pressed · ``2`` the pinned target was marched on
    directly · ``0`` no screen and nothing clicked · ``-1`` the game has no squad with
    that number · ``-2`` the screen is open and its target could not be read · ``-3`` the
    screen's own launch raised · ``-4`` the pin is older than the run allows · ``-5`` the
    macro does not march on that kind of point · ``-6`` the pinned monster is rally-only ·
    ``-7`` the player is not on the world map any more · ``-8`` the pin belongs to another
    account or another home server · ``-9`` the popup was opened by the PANEL rather than
    by the person, and a bot's own sightseeing is not a target anybody chose.

    The pin is NOT consumed by a successful send, on purpose: three keys in a row put
    three squads on one target, which is what a person clicking a boss wants. What ends it
    is time, the scene, and the account — never the panel's own bookkeeping.

    NOTHING ASKS THE SCREEN WHETHER THE MARCH NEEDS SOLDIERS. `NeedTakeArmy` called bare
    answers `true`, the send then goes out with `needSoldier = true`, and the server
    accepts the call and creates no march — an afternoon of #1283 went into that. The
    direct send passes `false` for the same reason, as every proven send here does.
    """
    return (
        _MACRO + _MACRO_FIND + _PICK_FIND + _PICK_ARM +
        "p.type, p.point, p.target, p.server = nil, nil, nil, nil "
        "p.timeIndex, p.back, p.formation, p.err = nil, nil, nil, nil "
        "p.desc, p.age, p.kind = nil, nil, nil "
        "p.result = 0 "
        "(function() "
        "local w = _findscreen() "
        "p.screen = (w ~= nil) and 1 or 0 "
        "if w ~= nil then "
        "local c = w.Ctrl "
        "pcall(function() p.type = tonumber(c.targetType) end) "
        "pcall(function() p.point = tonumber(c.targetPoint) end) "
        "pcall(function() p.target = c.targetUuid end) "
        "pcall(function() p.server = tonumber(c.targetServerId) end) "
        "pcall(function() p.timeIndex = tonumber(c.timeIndex) end) "
        "pcall(function() p.back = tonumber(c.autoBackHome) end) "
        "pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if tonumber(v.index) == tonumber(p.squad) then p.formation = v.uuid end end end) "
        "if p.target == nil or p.type == nil then p.result = -2 return end "
        "if p.formation == nil then p.result = -1 return end "
        "p.before = %(count)s "
        "DataCenter.__lw_macro_last = {squad = p.squad, formation = p.formation, "
        "type = p.type, point = p.point, target = p.target, server = p.server, "
        "timeIndex = p.timeIndex, back = p.back, before = p.before} "
        "pcall(function() w.View:OnSelectClick(p.formation) end) "
        "pcall(function() w.Ctrl:SetSelectFormationUuid(p.formation) end) "
        "local ok, err = pcall(function() w.Ctrl:OnCheckTime(p.formation, nil) end) "
        "if not ok then p.result = -3 p.err = tostring(err) return end "
        "p.result = 1 return end "
        # --- no screen: the target the person's own click pinned ---------------
        "local q = DataCenter.__lw_macro_pick "
        "if q == nil or q.point == nil then "
        "local pop = _findpopup() "
        # Read on the spot, and NOT counted as a scripted open even though this chunk is
        # one: nothing is being opened here, a popup that is already up is being read, and
        # a popup standing open at the moment of the key press is the strongest evidence
        # of what is chosen there is.
        "if pop ~= nil then pcall(function() "
        "q = DataCenter.__lw_pick_read(pop.Ctrl) q.script = 0 "
        "DataCenter.__lw_macro_pick = q end) end end "
        "if q == nil or q.point == nil then p.result = 0 return end "
        "p.desc, p.kind = q.desc, q.kindname "
        "local now = 0 "
        "pcall(function() now = tonumber(UITimeManager:GetInstance():GetServerSeconds()) or 0 end) "
        "p.age = (q.at ~= nil and now > 0) and (now - q.at) or 0 "
        "local inworld = false "
        "pcall(function() inworld = SceneUtils.GetIsInWorld() and true or false end) "
        "local who = '' pcall(function() who = tostring(LuaEntry.Player.uid) end) "
        "local home = 0 pcall(function() home = tonumber(LuaEntry.Player.serverId) or 0 end) "
        "if (q.who ~= nil and q.who ~= who) or (q.home ~= nil and tonumber(q.home) ~= home) "
        "then p.result = -8 return end "
        "if not inworld then p.result = -7 return end "
        "if q.script == 1 then p.result = -9 return end "
        "if p.age > (tonumber(p.stale) or 180) then p.result = -4 return end "
        "if q.can == 0 then p.result = -6 return end "
        "if q.mtt == nil then p.result = -5 return end "
        "pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if tonumber(v.index) == tonumber(p.squad) then p.formation = v.uuid end end end) "
        "if p.formation == nil then p.result = -1 return end "
        "p.type, p.point, p.target = q.mtt, q.point, q.target or 0 "
        "p.server, p.timeIndex, p.back = q.server or home, 1, 1 "
        "p.before = %(count)s "
        "DataCenter.__lw_macro_last = {squad = p.squad, formation = p.formation, "
        "type = p.type, point = p.point, target = p.target, server = p.server, "
        "timeIndex = p.timeIndex, back = p.back, before = p.before} "
        # THE SEND CARRIES ITS OWN COPY, and that is not tidiness. `p` IS
        # `DataCenter.__lw_macro`, one table shared by every press, and the send is a third
        # of a second late on purpose (a cold one is created and dropped). Three keys in a
        # row on one boss — the thing this recipe is FOR — would otherwise have the second
        # press overwrite the squad the first one was about to march with.
        "local _f, _t, _pt, _tg, _sv = p.formation, p.type, p.point, p.target, p.server "
        "TimerManager:GetInstance():DelayInvoke(function() "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(_f, _t, _pt, _tg, 1, 1, false, _sv, nil) end) "
        'CS.UnityEngine.Debug.LogError("ACT macro_send pinned ok="..tostring(ok)'
        '.." err="..tostring(err)) '
        "end, 0.3) "
        "pcall(function() local pop = _findpopup() "
        "if pop ~= nil and pop.Ctrl and pop.Ctrl.CloseSelf then pop.Ctrl:CloseSelf() end end) "
        "p.result = 2 "
        "end)() "
        "DataCenter.__lw_macro = p "
        'CS.UnityEngine.Debug.LogError("ACT macro_send squad="..tostring(p.squad)'
        '.." result="..tostring(p.result).." screen="..tostring(p.screen)'
        '.." type="..tostring(p.type).." point="..tostring(p.point)'
        '.." target="..tostring(p.target).." server="..tostring(p.server)'
        '.." kind="..tostring(p.kind).." age="..tostring(p.age)'
        '.." formation="..tostring(p.formation).." marches="..tostring(p.before)'
        '.." err="..tostring(p.err))'
        % {"count": own_march_count()}
    )


def macro_result() -> str:
    """Lua *expression* -> what :func:`macro_send` decided. See it for the five values."""
    return "(tonumber((DataCenter.__lw_macro or {}).result) or 0)"


def macro_sent() -> str:
    """Lua *expression* -> marches gained since `macro_send()` ran. 1 once one is out."""
    return "((%s) - ((DataCenter.__lw_macro or {}).before or 0))" % own_march_count()


def macro_repeat_ready() -> str:
    """Lua *expression* -> whether the last macro march can be sent again as it stands.

    ``1`` yes · ``0`` nothing has been sent by a macro yet · ``-1`` the last one was a
    RALLY, and a rally is not repeatable this way.

    The same three answers :func:`macro_repeat` now parks in `result` — this is the
    reading with nothing sent, kept for a caller that wants to ASK (a tab showing what
    CapsLock would do). CapsLock itself does not ask first any more (#1290): asking cost
    a whole round trip in front of a key press, and the refusal has to be made inside the
    send's own chunk regardless.

    The rally case is not squeamishness. A banner is raised through the squad screen's
    own launch, which fills in a wait slot and a disband time the screen owns; the plain
    `SendCreateMarchMessage` this key makes has never been proven for a rally type, and
    the one time #1283 tried it live the client went down mid-run. Nothing pins that
    crash on the send — but «unproven» plus «the client restarted while it ran» is not a
    thing to keep pointing at somebody's account, and re-raising a banner is not what
    «повторить последний марш» is for anyway.

    `MarchUtil.IsRallyMarch` is the GAME's own answer to «is this a rally type», which
    is better than a list of numbers copied out of an enum that grows every season.
    """
    return (
        "(function() " + _MACRO_LAST +
        "if m.formation == nil or m.target == nil or m.type == nil then return 0 end "
        "local rally = false "
        "pcall(function() rally = MarchUtil.IsRallyMarch(m.type) and true or false end) "
        "if rally then return -1 end "
        "return 1 end)()"
    )


def macro_repeat() -> str:
    """Send the last macro march again — same squad, same target, and no window at all.

    The whole point of the key: the screen is not opened, the camera is not moved and
    the target is not clicked. It is the send `macro_send` ends at, made directly with
    the arguments that went out last time — the shape `codename_send` proved: the target
    is addressed by uuid, so the server works the path out for itself.

    Scheduled through `TimerManager:DelayInvoke` for the reason every launch in this
    file is: a cold send is created and dropped.

    IT DECIDES FOR ITSELF, AND PARKS THE ANSWER (#1290). The recipe used to ask
    `macro_repeat_ready` first and only then press — a round trip in front of a key
    press, for a question this chunk has to answer again anyway. So the gate is here,
    and `result` says which of the three happened:

    ``1`` the send is scheduled · ``0`` nothing has been sent by a macro yet ·
    ``-1`` the last one was a RALLY.

    The rally refusal is not squeamishness. A banner is raised through the squad screen's
    own launch, which fills in a wait slot and a disband time the screen owns; the plain
    `SendCreateMarchMessage` this key makes has never been proven for a rally type, and
    the one time #1283 tried it live the client went down mid-run. `MarchUtil.IsRallyMarch`
    is the GAME's own answer, so a rally type added next season is covered without
    anybody copying an enum.
    """
    return (
        _MACRO_LAST +
        "m.result = 0 "
        "(function() "
        "if m.formation == nil or m.target == nil or m.type == nil then return end "
        "local rally = false "
        "pcall(function() rally = MarchUtil.IsRallyMarch(m.type) and true or false end) "
        "if rally then m.result = -1 return end "
        "m.before = %(count)s "
        "TimerManager:GetInstance():DelayInvoke(function() "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(m.formation, m.type, m.point, m.target, "
        "m.timeIndex or 1, m.back or 1, false, m.server, nil) end) "
        'CS.UnityEngine.Debug.LogError("ACT macro_repeat ok="..tostring(ok).." err="..tostring(err)) '
        "end, 0.3) "
        "m.result = 1 "
        "end)() "
        "DataCenter.__lw_macro_last = m "
        'CS.UnityEngine.Debug.LogError("ACT macro_repeat scheduled squad="..tostring(m.squad)'
        '.." result="..tostring(m.result).." type="..tostring(m.type)'
        '.." target="..tostring(m.target).." marches="..tostring(m.before))'
        % {"count": own_march_count()}
    )


def macro_repeat_result() -> str:
    """Lua *expression* -> what :func:`macro_repeat` decided. See it for the three values."""
    return "(tonumber((DataCenter.__lw_macro_last or {}).result) or 0)"


def macro_repeat_sent() -> str:
    """Lua *expression* -> marches gained since `macro_repeat()` scheduled its send."""
    return ("((%s) - ((DataCenter.__lw_macro_last or {}).before or 0))"
            % own_march_count())


def macro_last_squad() -> str:
    """Lua *expression* -> the squad number of the last macro march, 0 if there is none."""
    return "(tonumber((DataCenter.__lw_macro_last or {}).squad) or 0)"


# ---------------------------------------------------------------------------
# «Найм» — the recruit banners: heroes and survivors, x1 / x10 / x100
# ---------------------------------------------------------------------------
# Two messages, both read off a live trace of the player pulling by hand (run
# 20260813_103441, «найм героев») and then confirmed field by field in the VM:
#
#     --> lottery.hero.card    {id (string), isTen (int), useFree (int)}  + the cost item
#     --> lottery.worker.card  {useFree (int), isTen (int), officerId (int)}
#
# `isTen` IS NOT A FLAG. The trace only ever carried 0 and 1 — a single pull and a ten —
# so a x100 button had nothing to send. The client's own enum answers it:
# `UIHeroMultiRecruitType = { Ten = 1, OneHundred = 2 }`, and the view picks the value
# with it (`UIHeroRecruitView.ExecuteMultiRecruitAction`, read with `string.dump`). So
# the field is a SIZE — 0 single, 1 ten, 2 hundred — and the hundred is derived from the
# game's own table rather than guessed off two samples.
#
# THE FREE PULL IS THE GAME'S ANSWER, never a count kept here. Both banners have one and
# they are not the same shape: a hero banner refreshes its free pull daily
# (`LotteryInfo:IsSupportFreeRecruit()` / `:CanFreeRecruit()`, `dailyFreeNextFreshTime`),
# and the survivors' one runs on a timer of its own
# (`WorkerLotteryInfo:CanFreeRecruit()`, `nextFreeTime`). Both gates are CALLED rather
# than reimplemented: the client compares its own clock its own way, and a copy of that
# arithmetic here is one build away from disagreeing with what the person sees.
#
# The reverse-engineering, the fields and what each one meant live, is
# docs/research/recruit-draw.md.

#: How a count maps onto the wire's `isTen` — the client's own `UIHeroMultiRecruitType`.
RECRUIT_SIZES = {1: 0, 10: 1, 100: 2}

#: The two banners this ability knows, as the scenario spells them.
RECRUIT_KINDS = ("hero", "worker")

# The Lua that finds the hero banner to pull on. `DataCenter.__lw_recruit_lottery` names
# one when the caller picked it; otherwise the first of the client's own current recruit
# ids that actually resolves — the list carries ids whose banner has not been loaded, and
# those answer `nil` rather than an empty banner.
_RECRUIT_HERO_INFO = (
    "local function heroInfo() "
    "local M = DataCenter.LotteryDataManager "
    "local want = tostring(DataCenter.__lw_recruit_lottery or '') "
    "if want ~= '' then "
    "local ok, v = pcall(function() return M:GetLotteryDataById(want) end) "
    "if ok and v ~= nil then return v, want end "
    "ok, v = pcall(function() return M:GetLotteryDataById(tonumber(want)) end) "
    "if ok and v ~= nil then return v, want end "
    "return nil, want end "
    "for _, id in pairs(M.curRecruitIdList or {}) do "
    "local ok, v = pcall(function() return M:GetLotteryDataById(id) end) "
    "if ok and v ~= nil then return v, tostring(id) end end "
    "return nil, '' end "
)

# …and the survivors' one, which the client keeps as a single banner: the config row in
# `LotteryDataManager` (the officer id the message carries) and the account's own data
# (`WorkerLotteryDataManager`) with the free timer on it.
_RECRUIT_WORKER_INFO = (
    "local function workerInfo() "
    "local M = DataCenter.LotteryDataManager "
    "local cfg, wl = nil, nil "
    "pcall(function() cfg = M:GetOnlyWorkerLotteryData() end) "
    "pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) "
    "return wl, cfg end "
)

# A cost is a pair {itemId, itemNum}: `GetCostItems()` holds the single and the ten,
# `recruit100CostInfo` the hundred. Everything is wrapped, so a banner that is missing a
# hundred costs one zero rather than the whole reading.
_RECRUIT_COST = (
    # THE TICKET ID IS A STRING AND STAYS ONE. The client keeps `itemId` as text and the
    # message puts it on the wire with `PutUtfString`, so a `tonumber()` on the way past
    # — the obvious tidy-up — makes the client's own serializer throw «attempt to get
    # length of a number value» and NOTHING leaves. Caught on the first live pull; the
    # same value read back as a string sent cleanly. `GetItemById` takes it either way.
    "local function costOf(info, size) "
    "local id, num = '', 0 "
    "pcall(function() "
    "if size == 2 then local c = info:GetHundredCost() "
    "if c ~= nil then id = c.itemId num = tonumber(c.itemNum) or 0 end "
    "else local list = info:GetCostItems() or {} local c = list[size + 1] "
    "if c ~= nil then id = c.itemId num = tonumber(c.itemNum) or 0 end end "
    "end) return id, num end "
    "local function have(itemId) local n = 0 "
    "pcall(function() local it = DataCenter.ItemData:GetItemById(itemId) "
    "n = tonumber(it and it.count) or 0 end) return n end "
)

# The free pull, asked of the game and normalised. `free` is the client's own answer,
# `next` is when it comes back — in epoch SECONDS whichever unit the banner keeps it in
# (the hero one counts seconds, the survivors' one milliseconds).
_RECRUIT_FREE = (
    "local function secs(v) local n = tonumber(v) or 0 "
    "if n > 100000000000 then n = n / 1000 end return math.floor(n) end "
)


def recruit_state() -> str:
    """Lua *expression* -> one line saying what both banners can do right now.

    ``now=<server seconds> | hero id=… support=1 free=0 next=… item=… have=… c1=1
    c10=10 c100=100 total=… limit=… | worker id=… support=1 free=1 next=0 item=…
    have=… c1=1 c10=10 c100=100``

    * ``support`` — has this banner a free pull at all (a hero banner may not);
    * ``free``    — is it available THIS MOMENT, the client's own gate;
    * ``next``    — when it comes back, epoch seconds; ``0`` when it is available now;
    * ``item`` / ``have`` — the ticket the pulls are paid in and how many are held;
    * ``c1`` / ``c10`` / ``c100`` — what one, ten and a hundred cost in that ticket;
    * ``total`` / ``limit`` — pulls made on the hero banner and its ceiling, ``0`` when
      the banner does not keep one.

    A banner the client cannot answer for is left out of the line entirely, which is how
    «the client is not logged in» tells itself apart from «no free pull today».
    """
    return (
        "(function() "
        + _RECRUIT_HERO_INFO + _RECRUIT_WORKER_INFO + _RECRUIT_COST + _RECRUIT_FREE +
        "local out = {} "
        "local now = 0 pcall(function() now = math.floor(tonumber("
        "UITimeManager:GetInstance():GetServerSeconds()) or 0) end) "
        "out[#out+1] = 'now='..now "
        "local hi, hid = heroInfo() "
        "if hi ~= nil then "
        "local sup, free = 0, 0 "
        "pcall(function() sup = hi:IsSupportFreeRecruit() and 1 or 0 end) "
        "pcall(function() free = hi:CanFreeRecruit() and 1 or 0 end) "
        "local nxt = 0 if free == 0 and sup == 1 then nxt = secs(hi.dailyFreeNextFreshTime) end "
        "local id1, n1 = costOf(hi, 0) local _, n10 = costOf(hi, 1) local _, n100 = costOf(hi, 2) "
        "local total, limit = 0, 0 "
        "pcall(function() total = math.floor(tonumber(hi.totalLottery) or 0) end) "
        "pcall(function() limit = math.floor(tonumber(hi.totalLotteryLimit) or 0) end) "
        "out[#out+1] = 'hero id='..hid..' support='..sup..' free='..free..' next='..nxt"
        "..' item='..id1..' have='..have(id1)..' c1='..n1..' c10='..n10..' c100='..n100"
        "..' total='..total..' limit='..limit end "
        "local wl, wcfg = workerInfo() "
        "if wl ~= nil then "
        "local free = 0 pcall(function() free = wl:CanFreeRecruit() and 1 or 0 end) "
        "local nxt = 0 if free == 0 then nxt = secs(wl.nextFreeTime) end "
        "local id1, n1 = costOf(wl, 0) local _, n10 = costOf(wl, 1) "
        "local n100 = 0 "
        "pcall(function() local c = wcfg and wcfg.recruit100CostInfo "
        "if c ~= nil then n100 = tonumber(c.itemNum) or 0 end end) "
        "local wid = 0 pcall(function() wid = math.floor(tonumber(wcfg and wcfg.id) or 0) end) "
        "out[#out+1] = 'worker id='..wid..' support=1 free='..free..' next='..nxt"
        "..' item='..id1..' have='..have(id1)..' c1='..n1..' c10='..n10..' c100='..n100 end "
        "return table.concat(out, ' | ') end)()"
    )


def recruit_draw() -> str:
    """Pull on the banner parked in ``DataCenter.__lw_recruit_*`` — one message, no window.

    The caller parks three things first (``recruit_draw.md`` does it in one `LUA` line,
    the way `join_rally.md` parks its squads — a `TAP` carries no arguments of its own):

    * ``__lw_recruit_kind``    — ``hero`` or ``worker``;
    * ``__lw_recruit_count``   — ``1``, ``10`` or ``100``;
    * ``__lw_recruit_free``    — ``auto`` (spend the free pull when there is one and the
      count is 1), ``no`` (never), ``only`` (send NOTHING unless the pull is free);
    * ``__lw_recruit_lottery`` — which hero banner, empty for the one the client shows.

    **Every refusal is loud** (`docs/skills/sniff.md` §8.0a): the ticket count is checked
    against the game's own cost before anything leaves, and a pull that cannot be paid
    for writes why into ``__lw_recruit_report`` and sends nothing, rather than being
    refused by the server in a tip nobody reads.
    """
    return (
        _RECRUIT_HERO_INFO + _RECRUIT_WORKER_INFO + _RECRUIT_COST +
        "DataCenter.__lw_recruit_sent = 0 "
        "DataCenter.__lw_recruit_report = '' "
        "DataCenter.__lw_recruit_before = nil "
        "local kind = tostring(DataCenter.__lw_recruit_kind or 'hero') "
        "local count = math.floor(tonumber(DataCenter.__lw_recruit_count) or 1) "
        "local want = tostring(DataCenter.__lw_recruit_free or 'auto') "
        "local sizes = {[1] = 0, [10] = 1, [100] = 2} "
        "local size = sizes[count] "
        "if size == nil then "
        "DataCenter.__lw_recruit_report = 'count='..count..' is not 1, 10 or 100 — nothing sent' "
        "return end "
        "local info, cfg, id = nil, nil, '' "
        "if kind == 'worker' then info, cfg = workerInfo() "
        "if cfg ~= nil then pcall(function() id = tostring(math.floor(tonumber(cfg.id) or 0)) end) end "
        "else info, id = heroInfo() end "
        "if info == nil then "
        "DataCenter.__lw_recruit_report = 'kind='..kind..' — the client has no such banner "
        "loaded (not logged in, or the recruit screen has never been opened) — nothing sent' "
        "return end "
        "local free = 0 pcall(function() free = info:CanFreeRecruit() and 1 or 0 end) "
        "local useFree = 0 "
        "if want ~= 'no' and free == 1 and count == 1 then useFree = 1 end "
        "if want == 'only' and useFree == 0 then "
        "DataCenter.__lw_recruit_report = 'kind='..kind..' count='..count..' — the free pull is "
        "not available and «only free» was asked for — nothing sent' "
        "return end "
        "local itemId, itemNum = costOf(info, size) "
        "if kind == 'worker' and size == 2 then "
        "pcall(function() local c = cfg and cfg.recruit100CostInfo "
        "if c ~= nil then itemId = c.itemId itemNum = tonumber(c.itemNum) or 0 end end) end "
        "local held = have(itemId) "
        "if useFree == 0 and (itemNum <= 0 or held < itemNum) then "
        "DataCenter.__lw_recruit_report = 'kind='..kind..' count='..count..' cost='..itemNum"
        "..' of item '..itemId..' have='..held..' — not enough tickets, nothing sent' "
        "return end "
        # WHAT THE PULL IS MEASURED AGAINST, taken before the send: the tickets held
        # with the free pull's own gate under them. A pull that is refused by the
        # server returns just as cleanly as one it takes, so the recipe waits for THIS
        # number to move and calls the run failed when it never does.
        "local free_before = 0 pcall(function() free_before = info:CanFreeRecruit() and 1 or 0 end) "
        "DataCenter.__lw_recruit_before = have(itemId) * 2 + free_before "
        "local ok, err = pcall(function() "
        "if kind == 'worker' then "
        "SFSNetwork.SendMessage(MsgDefines.LotteryWorkerCard, useFree, size, math.floor(tonumber(id) or 0)) "
        "else "
        "SFSNetwork.SendMessage(MsgDefines.LotteryHeroCard, id, size, useFree, itemId) end end) "
        "if ok then DataCenter.__lw_recruit_sent = 1 end "
        "DataCenter.__lw_recruit_report = 'kind='..kind..' banner='..id..' count='..count"
        "..' isTen='..size..' useFree='..useFree..' cost='..(useFree == 1 and 0 or itemNum)"
        "..' item='..itemId..' have='..held..' sent='..tostring(ok)..' err='..tostring(err) "
        'CS.UnityEngine.Debug.LogError("ACT recruit_draw "..DataCenter.__lw_recruit_report)'
    )


def recruit_report() -> str:
    """Lua *expression* -> what :func:`recruit_draw` did, in its own words."""
    return ("(DataCenter.__lw_recruit_report or "
            "'the pull left no report — the press did not run')")


def recruit_sent() -> str:
    """Lua *expression* -> ``1`` when a pull actually left, ``0`` when it was refused."""
    return "(tonumber(DataCenter.__lw_recruit_sent) or 0)"


def recruit_verify() -> str:
    """Lua *expression* -> a number that MOVES when a pull really happened.

    Two things can pay for a pull and only one of them is tickets, so the proof has to
    cover both: the ticket count halves the number and the free pull's own gate is the
    unit under it. A paid pull drops the tickets, a free one flips
    ``CanFreeRecruit()`` from 1 to 0 — either way this value is different afterwards,
    and a press the server ignored leaves it exactly where it was.

    It is NOT the button's `verify_lua`, and that is deliberate: a press that decided on
    purpose to send nothing — no free pull with «only free» asked for, not enough
    tickets — moves nothing either, and a button-level check reports that as «pressed
    and nothing moved» over a refusal the recipe has already explained in words. So the
    recipe reads :func:`recruit_sent` first and only then waits on this.
    """
    return (
        "(function() "
        + _RECRUIT_HERO_INFO + _RECRUIT_WORKER_INFO + _RECRUIT_COST +
        "local kind = tostring(DataCenter.__lw_recruit_kind or 'hero') "
        "local info = nil "
        "if kind == 'worker' then info = (workerInfo()) else info = (heroInfo()) end "
        "if info == nil then return -1 end "
        "local itemId = 0 pcall(function() itemId = (costOf(info, 0)) end) "
        "local free = 0 pcall(function() free = info:CanFreeRecruit() and 1 or 0 end) "
        "return have(itemId) * 2 + free end)()"
    )


def recruit_moved() -> str:
    """Lua *expression* -> ``1`` once the game has caught up with a pull that was sent.

    The difference against the reading :func:`recruit_draw` took before the send. `0`
    while the server has not answered yet, so a recipe polls it for a second or two —
    and a `0` that never becomes `1` is the one honest way to say «it went out and
    nothing came of it».
    """
    return ("((DataCenter.__lw_recruit_before ~= nil and "
            "(%s) ~= DataCenter.__lw_recruit_before) and 1 or 0)" % recruit_verify())
