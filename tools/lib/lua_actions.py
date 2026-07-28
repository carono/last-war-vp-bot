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


# ---------------------------------------------------------------------------
# Chat send (DM / room). Reverse-engineered live from a PM trace to EleNita
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
# trace to EleNita — see docs/research/chat-coord-share.md.
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


def _ministry_gate(position_id: int) -> str:
    """Lua expression: may an application for `position_id` be sent right now?

    Two conditions, because the client's own pre-flight only covers the first:

    * `CheckCanApply(id)` — already holding a post, still on this post's cooldown.
    * the conqueror check for `type == 1` posts (the zone-war commanders).
      `CheckCanApply` returns **true** for those even when the zone war is over and
      nobody may have them, so relying on it alone puts a doomed request on the wire:
      the server answers `kingdom.position.apply` with `errorCode officer_apply_045`,
      `errorMsg "not conqueror <alliance uuid>"`, and the client raises the matching
      toast. Observed live against the Administrative Commander post.

    The conqueror half is verified only in the negative (a non-conqueror is correctly
    blocked); no conqueror account was available to confirm it opens.
    """
    return (
        "(function() local M=DataCenter.OfficialApplyManager "
        "local G=DataCenter.GovernmentManager "
        "if not M:CheckCanApply('%d') then return false end "
        "local t=DataCenter.GovernmentTemplateManager:GetTemplate('%d') "
        "if t and t.type==1 then return G:IsConqueror(G.curDataServerId) and true or false end "
        "return true end)()" % (int(position_id), int(position_id))
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
# a number, so `TAP help_ally_all xall` never fires a press the chunk then declines
# to make — and never spends a server round trip on an empty list.
def alliance_help_pending() -> str:
    """Lua *expression* -> how many alliancemates are waiting for help right now.

    Non-self entries of `GetAllianceHelpList()`; my own open requests sit in the same
    list (`isSelf == true`) and are not helpable, so they are skipped.
    """
    return ("(function() local n = 0 "
            "for _, it in ipairs(DataCenter.AllianceHelpDataManager:GetAllianceHelpList() or {}) do "
            "if not it.isSelf then n = n + 1 end end "
            "return n end)()")


def alliance_help_all() -> str:
    """Answer every pending alliance help request in one message (`al.help.all`)."""
    return ("if %s > 0 then "
            "local Z = CS.UnityEngine.Vector3.zero "
            "SFSNetwork.SendMessage(MsgDefines.AlHelpAll, "
            "math.floor(UITimeManager:GetInstance():GetServerTime()), Z, Z, nil, true) end"
            % alliance_help_pending())


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
