# Trade treasure-map pieces with the alliance: take the good offers, stand one of our own.
# ru: Обмен кусочками карты сокровищ с альянсом: принять выгодные, выставить своё.
#
# WHERE IT LIVES IN THE GAME. «Мобильный отряд» — the screen the secret tasks are on —
# has a second tab: the alliance's board of piece swaps. A dig spends ONE OF EACH of the
# set's pieces, so the number of digs left is the SMALLEST of the seven counts and
# nothing else; a pile of the eighth copy of one piece is worth exactly zero until it
# becomes a copy of the scarcest one. That is the whole reason this ability exists, and
# the whole reason its rule is the shape it is.
#
# THE RULE, agreed with the operator on 2026-08-25 and deliberately the strictest of the
# three that were offered — «только добор минимума»:
#
#     take an offer only when the piece it PAYS is the scarcest we hold,
#     and the piece it ASKS FOR is at least `gap` above that minimum.
#
# So every accepted trade raises the floor by one and can never lower it. `gap` is an
# argument rather than a constant because the operator's own answer may change with the
# event: 1 is «anything spare», 2 keeps a cushion.
#
# WHICH SIDE OF A RECORD IS WHICH — measured, not guessed (#1975). A record carries
# `needFragment` and `costFragment`, and both readings were plausible until our own
# offer was posted and read back live: `hero.dispatch.call.fragment.exchange`
# {type, needFragment, costFragment} came back as a record with exactly those two
# fields, so they are the OWNER's — what the owner needs, and what the owner pays.
# From the accepter's side that is inverted:
#
#     we GIVE  record.needFragment      (what its owner is short of)
#     we GET   record.costFragment      (what its owner is paying with)
#
# Reading it the other way round would spend our scarcest piece on our most plentiful
# one — the exact opposite of the rule — which is why it was worth one live posting to
# settle.
#
# THE SENDS, all of them one table and confirmed by building each message offline with a
# recording parameter table (`docs/research/treasure-piece-exchange.md`):
#
#     hero.dispatch.get.alliance.exchange.info    {type}   -- the board of offers
#     hero.dispatch.get.exchange.info             {type}   -- our own standing offer
#     hero.dispatch.fragment.exchange             {uuid}      -- accept somebody's offer
#     hero.dispatch.call.fragment.exchange        {type, needFragment, costFragment}
#     hero.dispatch.cancel.fragment.exchange      {uuid}      -- withdraw our own
#
# WHAT A POSTED OFFER COSTS: one copy of the piece it PAYS with, held back for as long
# as it stands, and handed straight back when it is withdrawn. Measured live twice, and
# the first measurement was wrong in a way worth recording: posting an offer and
# cancelling it in one run showed the seven counts identical on both sides — which reads
# as «nothing is escrowed» and is really «the cancel gave it back». Counting while the
# offer was still up showed the paid piece one lower, and withdrawing it put it back.
#
# It does not change the default. We always pay with the piece we hold MOST of, and the
# floor is the piece we hold LEAST of, so the held-back copy can never be the one that
# decides how many digs are left. It is why the offer step refuses to post at all when
# the seven are level: with nothing spare, a standing offer really would cost a dig.
#
# THE TWO PIECE IDS GO OUT AS INTEGERS, and `math.floor` is not decoration. The ids come
# out of the client's own config as Lua FLOATS — they print as `771011.0` — and an offer
# posted with one is refused by the server with `errorCode = E000000, errorMsg = "not
# fragment item"`, which reads exactly like «you do not hold that piece» about a piece
# there are twenty of. The identical post with an integer literal is accepted. Caught by
# the wire watch (`actions/dev/_t1975_push.md`) after a run that reported a posted offer
# and left the board empty.
#
# NO DAILY CAP IS KNOWN. Nothing in the client's own books counts exchanges the way
# `hero.dispatch.list` counts the day's steals and assists, and none was found. `limit`
# is therefore OURS, not the game's: a ceiling on how many offers one run may take, so a
# board that has filled up overnight cannot empty our spare pieces in one tick. If the
# server does have a cap it will refuse, and the refusal shows in the log like any other.
#
# WHICH SET. `kind` is the splinter set: 1 «Мобильный отряд» pieces, 2 season synthesis,
# 3 cooking ingredients, 4 the dig-treasure pieces. 4 is the one the current event runs
# and therefore the default; a set the account has no pieces of answers «nothing to
# trade» in one round trip and presses nothing.

ARGS kind = 4
ARGS accept = 1
ARGS offer = 1
ARGS gap = 1
ARGS limit = 3

LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchTreasureGetALInfo, {type = {kind}}) end) pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchTreasureGetSelfInfo, {type = {kind}}) end)
WAIT 2

READ_LUA (function() local kind = {kind} local gap = {gap} local budget = {limit} local doit = {accept} local M = DataCenter.SplinterExchangeManager local info = M and M.exchangeInfoList and M.exchangeInfoList[kind] if info == nil then return 'no such exchange set: ' .. tostring(kind) end local ids = info.fragGoodsIdList or {} local have = {} local order = {} for _, id in ipairs(ids) do have[id + 0] = 0 order[#order+1] = id + 0 end if #order == 0 then return 'the set is empty on this account' end pcall(function() for _, it in pairs(DataCenter.ItemData.ItemInfos or {}) do local id = it.itemId if id ~= nil and have[id + 0] ~= nil then have[id + 0] = have[id + 0] + ((it.count or 0) + 0) end end end) local function num(n) return string.format('%d', n) end local function floor() local m = nil for _, id in ipairs(order) do local n = have[id] if m == nil or n < m then m = n end end return m or 0 end local was = floor() local mine = '' pcall(function() local s = M:GetSelfExchangeData(kind) if s then mine = tostring(s.ownerId or '') end end) local list = {} pcall(function() list = M:GetAlExchangeDataList(kind) or {} end) local took, seen, why = 0, 0, {} for _, r in pairs(list) do seen = seen + 1 local give = (r.needFragment or 0) + 0 local get = (r.costFragment or 0) + 0 local owner = tostring(r.ownerId or '') local m = floor() if mine ~= '' and owner == mine then why[#why+1] = 'ours' elseif have[give] == nil or have[get] == nil then why[#why+1] = 'another-set' elseif have[get] ~= m then why[#why+1] = num(get) .. ':not-the-scarcest(' .. have[get] .. '>' .. m .. ')' elseif have[give] < m + gap then why[#why+1] = num(give) .. ':nothing-spare(' .. have[give] .. '<' .. (m + gap) .. ')' elseif budget <= 0 then why[#why+1] = 'over-this-run-s-ceiling' elseif doit == 0 then why[#why+1] = 'reading-only' else local ok = pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchTreasureALExchange, {uuid = r.uuid}) end) if ok then took = took + 1 budget = budget - 1 have[give] = have[give] - 1 have[get] = have[get] + 1 else why[#why+1] = 'the-send-was-refused' end end end local p = {} for _, id in ipairs(order) do p[#p+1] = num(id) .. ':' .. have[id] end return 'took=' .. took .. ' offers=' .. seen .. ' digs=' .. was .. '->' .. floor() .. ' have=[' .. table.concat(p, ' ') .. '] passed=[' .. table.concat(why, ' ') .. ']' end)() INTO report
LOG "the board, and what the rule made of it: {report}"

READ_LUA (function() local kind = {kind} local M = DataCenter.SplinterExchangeManager local info = M and M.exchangeInfoList and M.exchangeInfoList[kind] if info == nil then return 0 end local list = {} pcall(function() list = M:GetAlExchangeDataList(kind) or {} end) local n = 0 for _ in pairs(list) do n = n + 1 end return n end)() INTO offers
IF offer > 0
    READ_LUA (function() local kind = {kind} local M = DataCenter.SplinterExchangeManager local info = M and M.exchangeInfoList and M.exchangeInfoList[kind] if info == nil then return 'no such set' end local ids = info.fragGoodsIdList or {} local have = {} local order = {} for _, id in ipairs(ids) do have[id + 0] = 0 order[#order+1] = id + 0 end if #order == 0 then return 'the set is empty on this account' end pcall(function() for _, it in pairs(DataCenter.ItemData.ItemInfos or {}) do local id = it.itemId if id ~= nil and have[id + 0] ~= nil then have[id + 0] = have[id + 0] + ((it.count or 0) + 0) end end end) local want, pay = order[1], order[1] for _, id in ipairs(order) do if have[id] < have[want] then want = id end if have[id] > have[pay] then pay = id end end local suuid, sneed, scost = -1, 0, 0 pcall(function() local s = M:GetSelfExchangeData(kind) if s then suuid = (s.uuid or -1) + 0 sneed = (s.needFragment or 0) + 0 scost = (s.costFragment or 0) + 0 end end) local function num(n) return string.format('%d', n) end local function drop() pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchTreasureCancelExchange, {uuid = suuid}) end) end if want == pay or have[pay] <= have[want] then if suuid > 0 then drop() return 'the seven are level (' .. have[want] .. ' each) — there is nothing worth asking for, so the standing offer was withdrawn' end return 'the seven are level (' .. have[want] .. ' each) — nothing worth asking for, nothing posted' end if suuid > 0 and sneed == want and scost == pay then return 'already standing, and it asks for the right thing: need=' .. num(want) .. ' pay=' .. num(pay) end local note = '' if suuid > 0 then drop() note = 'withdrew ' .. num(sneed) .. '<-' .. num(scost) .. ', ' end pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchTreasureCallExchange, {type = kind, needFragment = math.floor(want), costFragment = math.floor(pay)}) end) return note .. 'posted: we need ' .. num(want) .. ' (' .. have[want] .. ' held) and pay ' .. num(pay) .. ' (' .. have[pay] .. ' held)' end)() INTO stall
    LOG "our own offer: {stall}"
