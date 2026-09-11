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
#                                    eventId = <id>, t = <serverTime ms>,
#                                    raw = "<the card's own extra, verbatim>"}, … }
#
# read back by `help_ally_training.md`, which is what actually joins.
#
# WHY `raw`, AND WHY THE FIELDS ARE DUG FOR RATHER THAN NAMED (#2755, the live pass).
# The card's payload is not in the message body: `msg` is the one sentence
# «Дорогие могущественные союзники…» and everything else rides `msg.extra`, whose values
# are STRINGS of JSON — `msg:getExtra()` hands back a decoded `json.object` whose
# `tostring` is a pointer, which is what an earlier version of this ear matched its
# regexes against and therefore always parked a plea with no uuid in it. So the extra is
# read the way `watch_red_packets.md` reads its own: value by value, decoded with
# `rapidjson`, then walked for a key called `eventUuid`/`eventId`. `raw` is kept beside
# the dug-out fields so the first live card can be read off the log rather than guessed
# at a second time.
#
# VERSIONED. `__lw_help.ver` names the shape of this wrapper; a run whose version
# differs unhooks the old one and installs the new, so an edit to this file reaches a
# client that has been up for days. Same version, same wrapper — nothing is done.
SHARE
ARGS cap = 20
LUA (function() local D = DataCenter local CM = package.loaded['Chat.Model.ChatMessage'] if type(CM) ~= 'table' or type(CM.onParseServerData) ~= 'function' then D.__lw_help_err = 'no chat class' return end local VER = 'ear3' local B = D.__lw_help if type(B) ~= 'table' then B = {} D.__lw_help = B end D.__lw_help_queue = D.__lw_help_queue or {} D.__lw_help_cap = {cap} B.take = function(msg) local Q = DataCenter.__lw_help_queue local p = nil pcall(function() p = tonumber(msg.post) end) if p ~= 730 then return end local raw, uuid, eid, owner = '', nil, nil, nil local function dig(t, depth) if type(t) ~= 'table' or depth > 4 then return end for k, v in pairs(t) do local ks = tostring(k) if type(v) == 'table' then dig(v, depth + 1) else local vs = tostring(v) if ks == 'eventUuid' or (ks == 'uuid' and uuid == nil) then uuid = vs elseif ks == 'eventId' or (ks == 'id' and eid == nil) then eid = vs elseif ks == 'eventPlayerUuid' then owner = vs end end end end local rj = package.loaded['rapidjson'] pcall(function() local ex = msg.extra if type(ex) == 'table' then for k, v in pairs(ex) do local vs = tostring(v) raw = raw .. ' ' .. tostring(k) .. '=' .. vs:sub(1, 200) if type(rj) == 'table' and vs:find('^%s*[%[{]') then local ok, d = pcall(function() return rj.decode(vs) end) if ok then dig(d, 1) end end if type(v) == 'table' then dig(v, 1) end end end end) local uid = owner pcall(function() uid = owner or tostring(msg.senderUid) end) local st = 0 pcall(function() st = tonumber(msg.serverTime) or 0 end) local key = tostring(uuid or ('uid:' .. tostring(uid) .. ':' .. tostring(st))) for _, e in ipairs(Q) do if tostring(e.key) == key then return end end table.insert(Q, {key = key, uid = uid, uuid = uuid, eventId = eid, t = st, raw = raw:sub(1, 400)}) while #Q > (tonumber(DataCenter.__lw_help_cap) or 20) do table.remove(Q, 1) end end if B.ver == VER and B.wrapper ~= nil and CM.onParseServerData == B.wrapper then return end if B.wrapper ~= nil and CM.onParseServerData == B.wrapper and B.orig ~= nil then CM.onParseServerData = B.orig end B.orig = CM.onParseServerData B.wrapper = function(self, ...) local r = {B.orig(self, ...)} pcall(B.take, self) return table.unpack(r) end CM.onParseServerData = B.wrapper B.ver = VER end)()
READ_LUA (function() return #(DataCenter.__lw_help_queue or {}) end)() INTO parked
LOG "listening for «помощь союзников» cards — {parked} waiting"
