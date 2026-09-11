# Listen for an alliancemate asking for help in the Restricted Area Training.
# ru: Слушать просьбы союзников о помощи в тренировке запретной зоны.
#
# WHY AN EAR AND NOT A POLL. The plea is a CHAT card — post type 730,
# `T11IdleGameAllianceHelp`, «Дорогие могущественные союзники, мне очень нужна ваша
# помощь!» — and the alliance broadcast rides a TLS websocket this repository cannot
# decode (`docs/research/chat.md` §1). The game's own plain-TCP push next door,
# `push.idle.game.events`, announces MY OWN events and never somebody else's plea:
# measured live 2026-09-11, it arrived every couple of minutes on an account nobody had
# shared anything to. So the only ear there is sits INSIDE the client, on the parse the
# chat reader already wraps — `Chat.Model.ChatMessage.onParseServerData` — and the panel
# reads what it parked (`docs/research/idle-game-alliance-help.md`).
#
# NON-DESTRUCTIVE AND IDEMPOTENT. The pristine parse is saved once and always called; the
# recorder runs inside a `pcall`, so a card the client changes the shape of costs a
# dropped entry and never the chat. Running this twice rebuilds the wrapper from the
# saved original rather than growing a chain — the same discipline
# `docs/research/chat-lua-readout.md` sets out.
#
# It presses NOTHING. What it leaves behind is a queue in the game VM:
#
#     DataCenter.__lw_help_queue = { {uid = "<owner>", uuid = <event uuid>,
#                                    eventId = <id>, t = <serverTime ms>}, … }
#
# read back by `help_ally_training.md`, which is what actually joins.
SHARE
ARGS cap = 20
LUA local D = DataCenter local C = package.loaded['Chat.Model.ChatMessage'] if not D.__lw_help_queue then D.__lw_help_queue = {} end D.__lw_help_cap = {cap} if not C.__lw_help_orig then C.__lw_help_orig = C.onParseServerData end C.onParseServerData = function(self, ...) local r = { C.__lw_help_orig(self, ...) } pcall(function() if tonumber(self.post) ~= 730 then return end local blob = '' local ex = self.getExtra and self:getExtra() if type(ex) == 'table' then for _, v in pairs(ex) do blob = blob .. ' ' .. tostring(v) end end local uuid = blob:match('"eventUuid"%s*:%s*"?(%d+)') or blob:match('"uuid"%s*:%s*"?(%d+)') local eid = blob:match('"eventId"%s*:%s*"?(%d+)') or blob:match('"id"%s*:%s*"?(%d+)') local uid = blob:match('"uid"%s*:%s*"?(%d+)') or tostring(self.senderUid) local Q = DataCenter.__lw_help_queue for _, e in ipairs(Q) do if tostring(e.uuid) == tostring(uuid) then return end end table.insert(Q, {uid = tostring(uid), uuid = uuid, eventId = eid, t = tonumber(self.serverTime) or 0, blob = blob:sub(1, 400)}) while #Q > (DataCenter.__lw_help_cap or 20) do table.remove(Q, 1) end end) return table.unpack(r) end
READ_LUA (function() return #(DataCenter.__lw_help_queue or {}) end)() INTO parked
LOG "listening for «помощь союзников» cards — {parked} waiting"
