r"""Single source of truth for the confirmed navigation Lua chunks.

Both the panel (via the warm daemon) and the standalone scripts build their in-game Lua
from here, so the recipes never drift. Each function returns a Lua string; run it through
any evaluator with a `.run(chunk, marker, settle)` method (LuaEval or the daemon client).

All recipes are the ones verified live this session — see docs/research/world-tiles.md and
docs/skills/sniff-capture.md §7.
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


def jump_to_coord(x: int, y: int, server: "int | None" = None) -> str:
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
    """
    sid = str(int(server)) if server is not None else current_server_expr()
    return ('local srv=%s pcall(function() GoToUtil.GotoWorldPos('
            'CS.UnityEngine.Vector3(%d*2+1,0,%d*2+1),105,nil,nil,srv) end) '
            'CS.UnityEngine.Debug.LogError("ACT jump=%d,%d srv="..tostring(srv))'
            % (sid, x, y, x, y))


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
            'CS.UnityEngine.Debug.LogError("ACT steal_queue_set "..tostring(#M.__lw_steal_queue))'
            % items)


def secret_task_queue_clear() -> str:
    """Empty the steal queue (a recipe should not inherit yesterday's targets)."""
    return ("local M=DataCenter.ActDispatchTaskDataManager M.__lw_steal_queue={} "
            'CS.UnityEngine.Debug.LogError("ACT steal_queue_cleared")')


def secret_task_queue_len() -> str:
    """Lua *expression* -> how many targets are still queued."""
    return ("(function() local M=DataCenter.ActDispatchTaskDataManager "
            "return #(M.__lw_steal_queue or {}) end)()")


def secret_task_steals_pending() -> str:
    """Lua *expression* -> presses `steal_secret_task` can still make.

    `min(queued targets, robberies left today)` — the button's `count_lua`, so `xall`
    stops both when the queue runs dry and when the daily cap is reached, and never
    spends a round trip on a press the gate would decline anyway.
    """
    return ("(function() local q=%s local b=%s if q<b then return q end return b end)()"
            % (secret_task_queue_len(), secret_task_steals_left()))


def steal_next_secret_task() -> str:
    """Rob the first queued target and drop it from the queue (one press, one task).

    One press per chunk on purpose: `todayStealNum` only moves when the server's reply
    lands, so a `while` inside one chunk would both spin the game's main thread and rob
    against a stale budget. The target is removed BEFORE the send, so a refused robbery
    (expired tile, slots full, already robbed by me) costs one queue entry rather than
    wedging `xall` on the same doomed uuid forever.
    """
    return ("local M=DataCenter.ActDispatchTaskDataManager "
            "local q=M.__lw_steal_queue or {} local t=table.remove(q,1) "
            "if t and %s > 0 then "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchSteal, t.uuid, t.server) end) "
            'CS.UnityEngine.Debug.LogError("ACT steal_sent uuid="..tostring(t.uuid)'
            '.." srv="..tostring(t.server)) end' % secret_task_steals_left())


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
        'local now = nowms '
        'CS.UnityEngine.Debug.LogError("ACT NOWMS="..tostring(nowms)) '
        'for _, v in pairs(m.allianceTask or {}) do '
        'local done = tonumber(v.completionTime) or 0 '
        'local exp = tonumber(v.actEndTime) or 0 '
        'local steals = #(v.stealInfoList or {}) '
        'if done > 0 and done <= now and (exp == 0 or now < exp) and steals < 3 then '
        'local x, y = 0, 0 '
        'pcall(function() local tp = SceneUtils.IndexToTilePos(v.pointId) x, y = tp.x, tp.y end) '
        'CS.UnityEngine.Debug.LogError("ACT VT uuid="..tostring(v.uuid)'
        '.." cfg="..tostring(v.cfgId).." srv="..tostring(v.targetServer)'
        '.." x="..tostring(x).." y="..tostring(y).." steals="..tostring(steals)'
        '.." done="..tostring(done).." exp="..tostring(exp)) '
        'end end end)')


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
    """
    return (
        'pcall(function() '
        'local m = DataCenter.ActDispatchTaskDataManager '
        + _SERVER_NOW_MS +
        'local now = nowms '
        'CS.UnityEngine.Debug.LogError("ACT NOWMS="..tostring(nowms)) '
        'for _, v in pairs(m.allianceTask or {}) do '
        'local done = tonumber(v.completionTime) or 0 '
        'local exp = tonumber(v.actEndTime) or 0 '
        'local steals = #(v.stealInfoList or {}) '
        'if done > 0 and (exp == 0 or now < exp) and steals < 3 then '
        'local x, y = 0, 0 '
        'pcall(function() local tp = SceneUtils.IndexToTilePos(v.pointId) x, y = tp.x, tp.y end) '
        'CS.UnityEngine.Debug.LogError("ACT VT uuid="..tostring(v.uuid)'
        '.." cfg="..tostring(v.cfgId).." srv="..tostring(v.targetServer)'
        '.." x="..tostring(x).." y="..tostring(y).." steals="..tostring(steals)'
        '.." done="..tostring(done).." exp="..tostring(exp)) '
        'end end end)')


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


def rally_join_open() -> str:
    """Press the game's «go on this march» entry, which opens the squad screen.

    The arguments are the ones a hand-made join was recorded making, in that order:
    target type 6 (`MarchTargetType.JOIN_RALLY`), the rally's tile, the rally id, then
    the constants the screen wants. It opens `UIFormationSelectListV2` and is NOT
    followed by a close.
    """
    return (
        _RALLY_JOIN_PARAMS +
        "if p.formation == nil then error('no rally armed for this run') end "
        "MarchUtil.OnClickStartMarch(6, p.point, p.team, -1, 1, 7, p.server, 0, 10) "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_open point="..tostring(p.point))'
    )


def rally_join_screen() -> str:
    """Lua *expression* -> 1 when the squad screen the join needs is on top."""
    return ("(function() " + _FORMATION_WIN +
            "local w = UIManager.Instance:GetStackTopWindow() "
            "if _isformation(w) then return 1 end return 0 end)()")


def rally_join_alive() -> str:
    """Lua *expression* -> 1 while the armed rally is still standing on the map.

    A rally is minutes at best and SECONDS during an event, and this flow takes a few
    of them: arm, open the screen, wait for it, pick, launch. A banner that came down in
    between leaves the launch pointing at a tile that is no longer a rally — which the
    server refuses, and which the player is shown as «invalid end point».

    That is not the same failure as «everything was pressed and nothing happened», and
    reading it here is what tells the two apart instead of leaving both to look like the
    ability being broken.
    """
    return (
        "(function() local p = DataCenter.__lw_rally_join if p == nil then return 0 end "
        "local wm = DataCenter.WorldMarchDataManager local col = wm:GetAllMarches() "
        "if col == nil then return 1 end "
        "local e = col:GetEnumerator() while e:MoveNext() do "
        "local mo = e.Current local ok, v = pcall(function() return mo.Value end) "
        "if ok and v ~= nil then mo = v end "
        "local t = nil pcall(function() t = mo.teamUuid end) "
        "if t ~= nil and tostring(t) == tostring(p.team) then return 1 end end "
        "return 0 end)()"
    )


def rally_join_squad() -> str:
    """Pick the parked squad on the open screen — the tap, and what the tap records."""
    return (
        _FORMATION_WIN + _RALLY_JOIN_PARAMS +
        "local w = UIManager.Instance:GetStackTopWindow() "
        "if not _isformation(w) then "
        "error('the squad screen is not open (top is '..tostring(w and w.Name)..')') end "
        "pcall(function() w.View:OnSelectClick(p.formation) end) "
        "w.Ctrl:SetSelectFormationUuid(p.formation) "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_squad sel="'
        '..tostring(w.Ctrl.selectFormationUuid))'
    )


def rally_join_picked() -> str:
    """Lua *expression* -> 1 when the open screen really holds the parked squad."""
    return (
        "(function() " + _FORMATION_WIN + _RALLY_JOIN_PARAMS +
        "local w = UIManager.Instance:GetStackTopWindow() "
        "if not _isformation(w) then return 0 end "
        "if p.formation ~= nil and tostring(w.Ctrl.selectFormationUuid) == tostring(p.formation) "
        "then return 1 end return 0 end)()"
    )


def rally_join_launch() -> str:
    """Press the screen's own launch. The screen closes itself when it is accepted."""
    return (
        _FORMATION_WIN + _RALLY_JOIN_PARAMS +
        "local w = UIManager.Instance:GetStackTopWindow() "
        "if not _isformation(w) then "
        "error('the squad screen is not open (top is '..tostring(w and w.Name)..')') end "
        "w.Ctrl:OnCheckTime(p.formation, nil) "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_launch formation="'
        '..tostring(p.formation))'
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
#     SFSNetwork.SendMessage <- decorator.progress.upgrade, 1156814307842051185, 1
#       SFSObject.PutLong  buildUuid, 1156814307842051185
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
# 2 -> 1, so the press moved real progress and the game charged for it. The uuid it sent,
# 1156814744896916569, is the one `GetMaxLvBuildDataByBuildId` resolves — the same identity
# both hand recordings put on the wire for their own groups.

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
# client uses it for anything. What makes the pair conclusive is that it is asked ONLY
# while the link is already `lost`, and a merely stranded client shows NO window at all
# (watched live, twice). So: lost link + a message tip with text = kicked.

def kicked_out() -> str:
    """Lua *expression* -> 1 when the client is showing the «logged in elsewhere» modal.

    The difference between «the server stopped answering» and «somebody took the
    account», which matters because they want opposite things done: a stranded client
    should be restarted, and a kicked one means a person is playing somewhere else.

    Answers 0 for anything it cannot read, so it can only ever ADD a reason, never
    remove one.
    """
    return ("(function() local ok, v = pcall(function() "
            "local m = UIManager.Instance "
            "if not m:IsWindowOpen('UICommonMessageTip') then return 0 end "
            "local w = m:GetWindow('UICommonMessageTip') "
            "local t = w and w.View and w.View.tipText "
            "if t == nil or tostring(t) == '' then return 0 end "
            "return 1 end) if not ok then return 0 end return v end)()")


def kick_message() -> str:
    """Lua *expression* -> the text the modal is showing, or '' — for the log and a trace.

    Read alongside :func:`kicked_out` when something is being written down: the WORDS are
    what a person recognises, and they are what proved this flag rather than any amount
    of reasoning about sockets.
    """
    return ("(function() local ok, v = pcall(function() "
            "local w = UIManager.Instance:GetWindow('UICommonMessageTip') "
            "local t = w and w.View and w.View.tipText "
            "return t == nil and '' or tostring(t) end) "
            "if not ok then return '' end return v end)()")
