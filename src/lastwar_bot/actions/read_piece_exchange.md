# Read the alliance's treasure-piece board: what we hold, what is offered, what we ask.
# ru: Прочитать доску обмена кусочками: что у нас есть, что предлагают, что просим мы.
#
# A READ, and nothing else — it presses nothing and trades nothing. Two asks go out
# first (`hero.dispatch.get.alliance.exchange.info` and
# `hero.dispatch.get.exchange.info`, both one field: `type`), because the client's
# board is empty until it has been asked for; everything after that is local.
#
# WHAT COMES BACK, in one variable, so the panel parses one string:
#
#     set=4 | digs=12 | have=771011:12,771012:20,… | mine=771011>771012 | offers=…
#
#   * `digs`  — the smallest of the seven counts, which IS the number of digs left: a
#               dig spends one of each. It is the number the whole ability serves.
#   * `have`  — piece id and how many, in the set's own order.
#   * `mine`  — our own standing offer as «what we need > what we pay», or `-` when we
#               have none up. Posting one costs nothing (measured, #1975), so `-` here
#               means an opportunity going by rather than a saving.
#   * `offers`— one record per alliance offer, `uuid;name;give;get;verdict`, where GIVE
#               and GET are already turned round into OUR side of the trade (a record's
#               `needFragment` is what its owner is short of, so it is what we would
#               hand over) and `verdict` is `1` when the standing rule would take it and
#               `0` when it would not. The rule lives here as well as in
#               `exchange_treasure_pieces.md` on purpose: a board that showed offers
#               without saying which of them the errand will act on is a board that has
#               to be re-derived by eye every time it is read.
#
# The verdict is «только добор минимума», the operator's own ruling (#1975): take an
# offer only when what it PAYS is the scarcest piece we hold and what it ASKS is at
# least `gap` above that floor. Same `gap` argument, same default, so the two never
# disagree about the same board.

ARGS kind = 4
ARGS gap = 1

LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchTreasureGetALInfo, {type = {kind}}) end) pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchTreasureGetSelfInfo, {type = {kind}}) end)
WAIT 2

READ_LUA (function() local kind = {kind} local gap = {gap} local M = DataCenter.SplinterExchangeManager local info = M and M.exchangeInfoList and M.exchangeInfoList[kind] if info == nil then return 'set=' .. kind .. ' | digs=-1 | have= | mine=- | offers=' end local num = function(n) return string.format('%d', n) end local ids = info.fragGoodsIdList or {} local have, order = {}, {} for _, id in ipairs(ids) do have[id + 0] = 0 order[#order+1] = id + 0 end pcall(function() for _, it in pairs(DataCenter.ItemData.ItemInfos or {}) do local id = it.itemId if id ~= nil and have[id + 0] ~= nil then have[id + 0] = have[id + 0] + ((it.count or 0) + 0) end end end) local floor = nil for _, id in ipairs(order) do if floor == nil or have[id] < floor then floor = have[id] end end floor = floor or 0 local h = {} for _, id in ipairs(order) do h[#h+1] = num(id) .. ':' .. have[id] end local mine, owner = '-', '' pcall(function() local s = M:GetSelfExchangeData(kind) if s and ((s.uuid or -1) + 0) > 0 then mine = num((s.needFragment or 0) + 0) .. '>' .. num((s.costFragment or 0) + 0) owner = tostring(s.ownerId or '') end end) local list = {} pcall(function() list = M:GetAlExchangeDataList(kind) or {} end) local rows = {} for _, r in pairs(list) do local give = (r.needFragment or 0) + 0 local get = (r.costFragment or 0) + 0 if not (owner ~= '' and tostring(r.ownerId or '') == owner) then local good = 0 if have[give] ~= nil and have[get] ~= nil and have[get] == floor and have[give] >= floor + gap then good = 1 end local nm = tostring(r.name or ''):gsub('[;|]', ' ') rows[#rows+1] = tostring(r.uuid) .. ';' .. nm .. ';' .. num(give) .. ';' .. num(get) .. ';' .. good end end return 'set=' .. kind .. ' | digs=' .. floor .. ' | have=' .. table.concat(h, ',') .. ' | mine=' .. mine .. ' | offers=' .. table.concat(rows, '|') end)() INTO board
LOG "the board: {board}"
