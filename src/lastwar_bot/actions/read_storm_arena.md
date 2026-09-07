# Read the state of the storm arena — the window, the attempts and the day's box.
# ru: Прочитать состояние «Арены Шторма» — окно события, попытки и дневной сундук.
#
# A READ: it presses nothing and spends nothing. It does send the game's own ask for the
# rank list, because without it there is nothing to read — the manager is empty until a
# screen asks, and a client that was never asked answers like a shut event.
#
# The whole answer is ONE line in ONE variable, `storm_arena`, as `key=value` pairs:
#
#     open=1 left=9 fought=1 need=5 chest=0 ready=1 score=1019 rank=110 until=571000 kof=1
#
#   open    1 while the event is running and a battle could be made right now
#   left    attempts the day still allows — the server's own count
#   fought  battles already made today — the server's own count, and the one the box
#           is paid on
#   need    how many battles the biggest daily box asks for (the game's own number)
#   chest   1 when that box has been taken today, 0 when it has not
#   ready   how many daily boxes could be taken right now
#   score   the arena score, and `rank` the place it buys
#   until   seconds left of the event
#   kof     1 while the event is in its three-team phase (the only one the errand can
#           fight — see docs/research/storm-arena.md)
#
# **A dash means the game would not answer** — the manager not loaded, a client still at
# the login screen, an account that has not unlocked the arena.
#
# The wire, the managers and the measurements are docs/research/storm-arena.md.

# --- an ear on the wire, installed once ------------------------------------------
# The battle and the refresh replies are parsed by the SCREENS, not by a manager, so a
# panel with no window open has nowhere to read them from. One guarded hook keeps the
# last of each; a second run reuses it rather than stacking another wrapper on top.
READ_LUA (function() local ok, res = pcall(function() local B = DataCenter.__lw_storm if B ~= nil and B.armed then return 1 end B = {armed = true} DataCenter.__lw_storm = B local hm = SFSNetwork.HandleMessage SFSNetwork.HandleMessage = function(cmd, msg, more) local s = string.lower(tostring(cmd or '')) if string.find(s, 'new.arena', 1, true) then B[s] = msg end return hm(cmd, msg, more) end return 1 end) if not ok then return 0 end return res end)() INTO storm_ear

IF storm_ear != 1
    FAIL "the storm arena's wire could not be listened to — the client is not answering"

# --- ask, then believe the answer -------------------------------------------------
LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.NewArenaRankList) end)

WAIT 2

READ_LUA (function() local ok, out = pcall(function() local dash = 'open=- left=- fought=- need=- chest=- ready=- score=- rank=- until=- kof=-' local m = DataCenter.NewPeakArenaManager if m == nil then return dash end local r = m.rankData if type(r) ~= 'table' then return dash end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local a = math.floor(((r.startTime or 0) + 0) / 1000) local z = math.floor(((r.endTime or 0) + 0) / 1000) local left = -1 pcall(function() left = math.floor((r.battleTimes or -1) + 0) end) local fought = -1 pcall(function() fought = math.floor((r.battleCount or -1) + 0) end) local need, chest, ready = -1, -1, -1 pcall(function() ready = 0 for _, row in pairs(r.dailyReward) do local n = math.floor((row.needCount or 0) + 0) local got = math.floor((row.rewarded or 0) + 0) if n > need then need = n chest = got end if got == 0 and fought >= n then ready = ready + 1 end end end) local can = false pcall(function() can = (m:CanChallenge() == true) end) local open = 0 if now > 0 and a > 0 and z > 0 and now >= a and now <= z and can and left > 0 then open = 1 end local kof = -1 pcall(function() if m:UseKofBattle() == true then kof = 1 else kof = 0 end end) local score = -1 pcall(function() score = math.floor((r.curScore or -1) + 0) end) local rank = -1 pcall(function() rank = math.floor((r.curRank or -1) + 0) end) local rest = -1 if now > 0 and z > now then rest = z - now end local function num(v) if v == nil or v < 0 then return '-' end return string.format('%d', v) end return 'open=' .. num(open) .. ' left=' .. num(left) .. ' fought=' .. num(fought) .. ' need=' .. num(need) .. ' chest=' .. num(chest) .. ' ready=' .. num(ready) .. ' score=' .. num(score) .. ' rank=' .. num(rank) .. ' until=' .. num(rest) .. ' kof=' .. num(kof) end) if not ok then return 'open=- left=- fought=- need=- chest=- ready=- score=- rank=- until=- kof=-' end return out end)() INTO storm_arena

LOG "storm arena: {storm_arena}"
