# Take our own treasure-piece offer off the alliance board.
# ru: Снять наше предложение об обмене кусочками с доски альянса.
#
# The other half of `exchange_treasure_pieces.md`, split out because it is the one thing
# a person wants to do BY HAND: the errand keeps an offer standing at all times, and
# «not right now» has to be sayable without switching the errand off.
#
# Costs nothing either way — an offer escrows no piece (measured live, #1975) — so this
# is only ever about what the alliance sees on the board.
#
# `hero.dispatch.cancel.fragment.exchange` {uuid}, and the uuid is our own record's,
# read out of the client rather than passed in: an offer we do not have is a no-op that
# says so, and a uuid typed in from somewhere else would cancel somebody else's.

ARGS kind = 4

LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchTreasureGetSelfInfo, {type = {kind}}) end)
WAIT 2

READ_LUA (function() local kind = {kind} local M = DataCenter.SplinterExchangeManager local uuid, need, cost = -1, 0, 0 pcall(function() local s = M:GetSelfExchangeData(kind) if s then uuid = (s.uuid or -1) + 0 need = (s.needFragment or 0) + 0 cost = (s.costFragment or 0) + 0 end end) if uuid <= 0 then return 'there was nothing of ours on the board' end local ok = pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchTreasureCancelExchange, {uuid = uuid}) end) if not ok then return 'the withdrawal was refused by the client' end return 'withdrawn: we were asking for ' .. string.format('%d', need) .. ' and paying ' .. string.format('%d', cost) end)() INTO withdrawn
LOG "our own offer: {withdrawn}"
