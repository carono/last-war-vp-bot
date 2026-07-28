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

    Fields: `uuid`, `cfg` template id, `owner` uid, `srv` the owner's server, `x`/`y`
    (from `pointId`), `done` completion epoch-ms, `ends` the tile's expiry, `looted`
    how many of the template's slots are spent, `state` the game's
    `GhostreconPointStealType`, and `mine` when the squad is my own.

    A robbery needs `uuid` + `ownerServer`, both of which are printed, so this is the
    list a queue is built from.
    """
    return (
        "local M=DataCenter.ActGhostreconManager "
        "local me=tostring(LuaEntry.Player.uid) "
        'CS.UnityEngine.Debug.LogError("ACT ghost open="..tostring(M:IsOpenDay())'
        '.." left="..tostring(%s).." known="..tostring(#(M.taskList or {}))) '
        "for _,t in ipairs(M.taskList or {}) do "
        "local x,y=0,0 pcall(function() local tp=SceneUtils.IndexToTilePos(t.pointId) "
        "x,y=tp.x,tp.y end) "
        "local n=0 for _,s in ipairs(t.stealList or {}) do n=n+1 end "
        "local ok,st=pcall(function() "
        "return M:GetPointStealType(t.cfgId, t.completionTime, {}) end) "
        'CS.UnityEngine.Debug.LogError("ACT G uuid="..tostring(t.uuid)'
        '.." cfg="..tostring(t.cfgId).." owner="..tostring(t.ownerId)'
        '.." srv="..tostring(t.ownerServer or t.targetServer)'
        '.." x="..tostring(x).." y="..tostring(y)'
        '.." done="..tostring(t.completionTime).." ends="..tostring(t.actEndTime)'
        '.." looted="..tostring(n).." state="..tostring(ok and st or 0)'
        '.." mine="..tostring(tostring(t.ownerId)==me)) end'
        % ghost_recon_steals_left()
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
