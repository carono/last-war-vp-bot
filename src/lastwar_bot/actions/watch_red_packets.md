# Stand an ear on the chat and take a share of every red packet somebody drops in it.
# ru: Караул на чат: ловить чужие красные пакеты и забирать свою долю алмазов.
#
# The other side of `share_lucky_packet.md` (#2397): there this account GAVE a packet of
# free diamonds away, here it TAKES its share of somebody else's. The share costs nothing
# — the diamonds are the server's — and the packet is emptied by whoever presses first,
# so the whole ability is a race and every link in the chain costs some of it.
#
# WHY AN EAR AND NOT A CLOCK. A packet is announced by ONE thing: a chat message
# (`post = 611`, `PostType.RedPackge_New`). The chat leg is TLS and cannot be sniffed
# (docs/research/chat.md), so there is no wire trigger to hang this on; and asking
# `get.alliance.red.packet` on a clock is exactly the background question `CLAUDE.md`
# forbids. What the client DOES give is the ingress the chat reader already uses:
# `Chat.Model.ChatMessage:onParseServerData` runs for every message the client parses,
# whether or not the chat window is open. So the press is made INSIDE the call that
# delivered the announcement — nothing polls, nothing waits its turn.
#
# WHAT LEAVES, MEASURED (#2405, live client, nothing sent while it was found):
#
#   * the announcement's attachment (`extra.customJsonParam`, JSON) is
#     `{uuid, packetId, goodsId, luckSiphonId, expiredTime, serverId, redPacketServerId,
#     hasRob}` — `uuid` names the packet, `packetId` is the red-packet template
#     (`lw_conveyluck.red_packet`), `goodsId` the reward goods, `luckSiphonId` the
#     `lw_conveyluck` row;
#   * the press is `MsgDefines.OpenRedPacket` = `open.red.packet`, and its message
#     carries FOUR fields — `uuid`, `cfgId`, `chatType`, `serverId`. The shape was read by
#     BUILDING the message in memory with sentinels and reading its own SFS object back,
#     never by sending one: `NewMessage('ARG1', 2222, 3333, 4444)` →
#     `uuid=ARG1 cfgId=2222 chatType=3333 serverId=4444`. **The fourth is not optional**:
#     without it the client's own serialiser refuses the send before a byte leaves —
#     `SFSDataSerializer.lua:39: bad argument #2 to 'pack' (number expected, got nil)`,
#     measured on the first live run of this recipe.
#   * `chatType` is `RedPacketManager.ChannelType` — World 1, Alliance 2, Season 3,
#     AliFriend 4 — and it is taken from the ROOM the message arrived in, never assumed.
#
# `cfgId` IS SENT AS `packetId`, AND THAT IS THE ONE GUESS IN HERE. The attachment holds
# two ids that could be it (`packetId` 502, `goodsId` 995002) and no live packet was
# available to settle it, so the recipe records which one it sent (`cfg=`) and the
# reading below reports what came of it. A refused open costs nothing and takes nothing.
#
# THE GATES, all local, all before anything leaves:
#   * not ours to take twice — the client's own daily count `GetRedPacketGetNum()`
#     against `GetRedPacketGetMaxNum()` (10 a day, measured);
#   * expired — `expiredTime` against the game's own clock (`GetServerTime`, ms), never
#     the PC's (docs/research/game-clock.md);
#   * another server — `redPacketServerId` against `LuaEntry.Player.serverId`; a packet
#     announced in a cross-server room is not ours to open;
#   * a room whose channel the client does not name — skipped rather than guessed at.
#
# EVERY PACKET IS PRESSED AT ONCE AND ONLY ONCE. The same message is parsed again when
# the client re-reads a room, and a second press at an emptied packet is refused by the
# server WITH A POPUP for the person to close — the lesson #2365 paid for on the
# fireworks. So the uuid of every packet pressed at is kept for the session and a
# repeat is `already`, not a second send. A send the CLIENT refused — one that never
# reached the socket — puts the uuid back, because nothing was taken and the next run
# has a real chance at it; only a send that LEFT holds the packet's name.
#
# The ear keeps its own ring in `DataCenter.__lw_rpw`, which `read_red_packet_watch.md`
# reads and clears. A client restart takes the VM and the hook with it, so the trigger
# `red_packet_watch` re-plays this recipe when the flag is gone — one round trip, and it
# says «уже стоит» when it is still there.
#
# IT CHAINS RATHER THAN REPLACES. `tools/chat_reader.py` wraps the same method for the
# chat tab; whichever is installed second calls the first, and re-arming notices its own
# wrapper and does nothing. If the reader re-installs afterwards it rebuilds from its own
# saved original and this hook is dropped — the poll trigger puts it back.
LUA (function() local B = DataCenter.__lw_rpw if B == nil then B = {on = false, heard = 0, taken = 0, failed = 0, skipped = 0, lastMs = -1, bestMs = -1, err = '', rows = {}} DataCenter.__lw_rpw = B end local CM = package.loaded['Chat.Model.ChatMessage'] if type(CM) ~= 'table' or type(CM.onParseServerData) ~= 'function' then B.on = false B.err = 'no chat class' return end _G.__lw_rp_take = function(msg) local B2 = DataCenter.__lw_rpw if B2 == nil then return end local post = nil pcall(function() post = tonumber(msg.post) end) if post ~= 611 then return end B2.heard = B2.heard + 1 local t0 = os.clock() local function note(word) B2.rows[#B2.rows + 1] = word while #B2.rows > 20 do table.remove(B2.rows, 1) end end local rj = package.loaded['rapidjson'] if type(rj) ~= 'table' then B2.failed = B2.failed + 1 note('no-json') return end local s = '' pcall(function() s = tostring((msg.extra or {}).customJsonParam or '') end) local ok, d = pcall(function() return rj.decode(s) end) if not ok or type(d) ~= 'table' or d.uuid == nil then B2.failed = B2.failed + 1 note('unreadable') return end local key = tostring(d.uuid) if B2.seen == nil then B2.seen = {} end if B2.seen[key] then B2.skipped = B2.skipped + 1 note('already') return end local M = DataCenter.RedPacketManager local inst = M and (M.Instance or M) local got, max = 0, 0 pcall(function() got = math.floor((inst:GetRedPacketGetNum() or 0) + 0) end) pcall(function() max = math.floor((inst:GetRedPacketGetMaxNum() or 0) + 0) end) if max > 0 and got >= max then B2.skipped = B2.skipped + 1 note('quota ' .. got .. '/' .. max) return end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerTime() or 0) + 0) end) if now <= 0 then now = os.time() * 1000 end local exp = math.floor((tonumber(d.expiredTime) or 0) + 0) if exp > 0 and exp <= now then B2.skipped = B2.skipped + 1 note('expired') return end local home = 0 pcall(function() home = math.floor((tonumber(tostring(LuaEntry.Player.serverId)) or 0) + 0) end) local theirs = math.floor((tonumber(d.redPacketServerId) or tonumber(d.serverId) or 0) + 0) if home > 0 and theirs > 0 and home ~= theirs then B2.skipped = B2.skipped + 1 note('another server') return end local room = '' pcall(function() room = tostring(msg.roomId or '') end) local chat = 0 if room:find('^alliance') then chat = 2 elseif room:find('^world') then chat = 1 elseif room:find('^season') then chat = 3 end if chat == 0 then B2.skipped = B2.skipped + 1 note('room ' .. (room:match('^(%a+)') or '?')) return end local cfg = math.floor((tonumber(d.packetId) or 0) + 0) B2.seen[key] = true local srv = math.floor((tonumber(d.redPacketServerId) or tonumber(d.serverId) or 0) + 0) local ok2, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.OpenRedPacket, tostring(d.uuid), cfg, chat, srv) end) local ms = math.floor((os.clock() - t0) * 1000) if ok2 then B2.taken = B2.taken + 1 B2.lastMs = ms if B2.bestMs < 0 or ms < B2.bestMs then B2.bestMs = ms end note('took cfg=' .. cfg .. ' chat=' .. chat .. ' srv=' .. srv .. ' ' .. ms .. 'ms') else B2.failed = B2.failed + 1 B2.err = tostring(why) B2.seen[key] = nil note('refused') end end if B.wrapper ~= nil and CM.onParseServerData == B.wrapper then B.on = true return end B.orig = CM.onParseServerData B.wrapper = function(self, ...) local r = {B.orig(self, ...)} pcall(_G.__lw_rp_take, self) return table.unpack(r) end CM.onParseServerData = B.wrapper B.on = true end)()
READ_LUA (function() local B = DataCenter.__lw_rpw if B == nil then return 'караул не встал' end if not B.on then return 'караул не встал: ' .. tostring(B.err) end return 'караул на чате: слышал ' .. B.heard .. ', забрал ' .. B.taken .. ', пропустил ' .. B.skipped .. ', не смог ' .. B.failed end)() INTO armed
LOG "Красные пакеты: {armed}"
