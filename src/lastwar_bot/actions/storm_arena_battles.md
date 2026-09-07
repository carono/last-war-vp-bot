# Fight the storm arena five times and take the day's box.
# ru: Пять боёв на «Арене Шторма» и дневной сундук.
#
# «Арена Шторма» stands in the same building as the 3v3 challenge and replaces it when
# that one ends. The server offers FIVE opponents; the person picks one and fights it
# with the arena's own three-team line-up. What the day's box is paid on is the NUMBER OF
# BATTLES, not the wins — so this errand fights until the count is in, whatever the
# results were, and then takes every daily box the count has reached.
#
# **The opponent is the weakest one outside our own alliance.** «Weakest» is the row's
# own `power`, which is the line-up's power rather than the base's — that is what decides
# the fight. «Ours» is the alliance id the game gives for this account, compared with the
# one on the opponent's row; no alliance is named anywhere in this file. A list with
# nobody but our own people on it is re-rolled while the game gives re-rolls away, and
# never once they cost diamonds.
#
# **The counts are the SERVER's.** `battleCount` is how many battles the day has had and
# `battleTimes` how many attempts are left; both ride on the rank list and on every
# battle reply, and both are re-read after each round rather than counted here.
#
# **The line-up is the person's own, and it is never built by hand.** The battle carries
# our three teams, and the only trustworthy source for them is the game itself: the
# pre-battle preview answers with `ownerInfo.formationArr`, which is parsed back into the
# arena's own formation class and packed by the client's own packer. A hand-built array
# is refused (`docs/research/storm-arena.md` §3).
#
# It ends as a SUCCESS and fights nothing when there is nothing to do: the event is not
# running, the day's attempts are spent, the battles are already made and the boxes
# taken, or the event is in a phase this errand cannot fight. A failure there would sit
# out the retry hold and try again all day for a state that will not change.
#
# It ends as a FAILURE when a battle could not be made at all — no opponent came back,
# the send was refused, the client stopped answering. Every one of those mends itself in
# minutes, so the clock keeps its place and the next run does only what is STILL owed.
#
# The wire, the managers and the measurements are docs/research/storm-arena.md; the
# reading behind the counts is actions/read_storm_arena.md.

SHARE
ARGS battles = 5

# --- what the day has already had ---------------------------------------------
# The reading is its own recipe and this plays it: it installs the one guarded ear on the
# wire, asks the server for the rank list, and says the line a person reads. Everything
# below is read out of what that ask brought back, so the server is asked once.
CALL read_storm_arena

# `-1` is «the counts could not be read», which is not «nothing to do»: a client that has
# stopped answering would otherwise look exactly like a finished day.
READ_LUA (function() local ok, out = pcall(function() local m = DataCenter.NewPeakArenaManager if m == nil then return -1 end local r = m.rankData if type(r) ~= 'table' then return -1 end local B = DataCenter.__lw_storm if type(B) ~= 'table' then return -1 end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local a = math.floor(((r.startTime or 0) + 0) / 1000) local z = math.floor(((r.endTime or 0) + 0) / 1000) if now <= 0 or a <= 0 or z <= 0 then return -1 end B.open = 0 if now >= a and now <= z then B.open = 1 end local left = math.floor((r.battleTimes or -1) + 0) local fought = math.floor((r.battleCount or -1) + 0) if left < 0 or fought < 0 then return -1 end B.left = left B.fought = fought B.kof = 0 pcall(function() if m:UseKofBattle() == true then B.kof = 1 end end) B.made = 0 B.won = 0 B.lost = 0 B.strikes = 0 B.boxes = 0 return 1 end) if not ok then return -1 end return out end)() INTO storm_read

IF storm_read < 0
    FAIL "the storm arena's counters could not be read — check the client is still talking to the server"

READ_LUA (function() local B = DataCenter.__lw_storm return math.floor((B.open or 0) + 0) end)() INTO storm_open

IF storm_open != 1
    LOG "the storm arena is not running right now"
    STOP "the event is shut"

READ_LUA (function() local B = DataCenter.__lw_storm return math.floor((B.kof or 0) + 0) end)() INTO storm_kof

IF storm_kof != 1
    LOG "the storm arena is not in its three-team phase — this errand can only fight that one"
    STOP "the phase is not one this errand fights"

# --- how many battles are owed --------------------------------------------------
# ONE CALL, NOT ONE PER QUESTION (#2404): a read is a thread hijack into the client at
# half a second a time whatever it asks, so the two answers travel together.
READ_LUA (function() local __v0 = (function() local B = DataCenter.__lw_storm local want = {battles} - math.floor((B.fought or 0) + 0) if want < 0 then want = 0 end local left = math.floor((B.left or 0) + 0) if want > left then want = left end B.todo = want return want end)() local __v1 = (function() local B = DataCenter.__lw_storm return 'fought today ' .. math.floor((B.fought or 0) + 0) .. ' of {battles}, attempts left ' .. math.floor((B.left or 0) + 0) end)() return __v0, __v1 end)() INTO storm_todo, storm_state

LOG "storm arena: {storm_state} — {storm_todo} battle(s) to fight"

# --- the list of opponents ------------------------------------------------------
# `isRefresh = 0` asks for the list the server already holds and costs nothing; the
# re-roll below is the one that has a price, and it is only ever taken while that price
# is zero.
LUA pcall(function() local B = DataCenter.__lw_storm B['new.arena.refresh'] = nil SFSNetwork.SendMessage(MsgDefines.NewArenaRefresh, 0) end)

WAIT 3

# --- fight, re-asking the counts after every battle -------------------------------
# The LIMIT is a safety rail rather than the rule: the loop leaves when the SERVER says
# the battles are in or the attempts are gone.
WHILE storm_todo > 0 LIMIT 10
    READ_LUA (function() local ok, out = pcall(function() local B = DataCenter.__lw_storm local last = B['new.arena.kof.battle'] local list = nil if type(last) == 'table' and type(last.battleList) == 'table' then list = last.battleList else local r = B['new.arena.refresh'] if type(r) == 'table' then list = r.battleList end end if type(list) ~= 'table' then return 'no opponent list came back' end B['new.arena.kof.battle'] = nil local mine = '' pcall(function() mine = tostring(LuaEntry.Player.allianceId or '') end) local pick, pp, seen, ours = nil, nil, 0, 0 for _, v in pairs(list) do seen = seen + 1 local a = '' pcall(function() a = tostring(v.playerInfo.allianceId or '') end) if mine ~= '' and a == mine then ours = ours + 1 else local p = math.floor((v.power or 0) + 0) if pick == nil or p < pp then pick = tostring(v.uid) pp = p end end end B.pick = pick B.pickPower = pp if pick == nil then local r = B['new.arena.refresh'] local free = 0 pcall(function() local price = tostring(r.refresh_price or '') local n = math.floor((r.refreshCount or 0) + 0) local count = 0 for part in string.gmatch(price, '[^|]+') do count = count + 1 if count == n + 1 then if (part + 0) == 0 then free = 1 end break end end end) if free == 1 then B.skip = 1 B['new.arena.refresh'] = nil pcall(function() SFSNetwork.SendMessage(MsgDefines.NewArenaRefresh, 1) end) return 'all ' .. seen .. ' candidates are our own alliance — asked for a free re-roll' end return 'all ' .. seen .. ' candidates are our own alliance, and a re-roll would cost diamonds' end B['new.arena.kof.battle.preview'] = nil pcall(function() SFSNetwork.SendMessage(MsgDefines.NewArenaKofBattlePreviewMessage, pick) end) return 'offered ' .. seen .. ', ours ' .. ours .. ', taking the weakest at power ' .. tostring(pp) end) if not ok then return 'the opponent could not be chosen: ' .. tostring(out) end return out end)() INTO storm_pick
    LOG "{storm_pick}"
    WAIT 4
    READ_LUA (function() local ok, out = pcall(function() local B = DataCenter.__lw_storm if math.floor((B.skip or 0) + 0) == 1 then B.skip = 0 return 'the list was re-rolled — looking again' end if B.pick == nil then B.strikes = math.floor((B.strikes or 0) + 0) + 1 return 'nobody to fight this round' end local pv = B['new.arena.kof.battle.preview'] if type(pv) ~= 'table' or type(pv.ownerInfo) ~= 'table' then B.strikes = math.floor((B.strikes or 0) + 0) + 1 return 'the pre-battle look came back empty' end local raw = pv.ownerInfo.formationArr local cls = require('DataCenter.LW3V3ArenaManager.ArenaArmyFormationInfo') local teams = {} for i = 1, 3 do local one = cls:New() one:ParseData(raw[i]) teams[#teams+1] = one end local packed = DataCenter.LW3V3Manager:FormationToSFS(teams) B['new.arena.kof.battle'] = nil SFSNetwork.SendMessage(MsgDefines.NewArenaKofBattleMessage, B.pick, packed) return 'sent' end) if not ok then local B = DataCenter.__lw_storm B.strikes = math.floor((B.strikes or 0) + 0) + 1 return 'the battle was refused by the client: ' .. tostring(out) end return out end)() INTO storm_sent
    WAIT 6
    READ_LUA (function() local ok, out = pcall(function() local B = DataCenter.__lw_storm local r = B['new.arena.kof.battle'] if type(r) ~= 'table' then if B.pick == nil then return 'no battle was made this round' end B.strikes = math.floor((B.strikes or 0) + 0) + 1 return 'the server said nothing about the battle' end if r.errorCode ~= nil then B.strikes = math.floor((B.strikes or 0) + 0) + 1 return 'the server refused the battle (' .. tostring(r.errorCode) .. ' ' .. tostring(r.errorMsg) .. ')' end B.strikes = 0 B.made = math.floor((B.made or 0) + 0) + 1 local win = (r.isWin == true) or (math.floor((r.isWin or 0) + 0) == 1) if win then B.won = math.floor((B.won or 0) + 0) + 1 else B.lost = math.floor((B.lost or 0) + 0) + 1 end local left = -1 if type(r.battleTimes) == 'number' then left = math.floor(r.battleTimes + 0) end if left >= 0 then B.left = left B.fought = math.floor((B.fought or 0) + 0) + 1 end local score = math.floor((r.ownerNewScore or 0) + 0) local rank = math.floor((r.curRank or 0) + 0) return 'battle ' .. math.floor(B.made) .. ': ' .. (win and 'WON' or 'lost') .. ', fought today ' .. math.floor(B.fought) .. ' of {battles}, attempts left ' .. math.floor(B.left) .. ', score ' .. score .. ' (rank ' .. rank .. ')' end) if not ok then return 'the battle result could not be read: ' .. tostring(out) end return out end)() INTO storm_round
    LOG "{storm_round}"
    READ_LUA (function() local B = DataCenter.__lw_storm if math.floor((B.strikes or 0) + 0) >= 2 then B.todo = 0 return 0 end local want = {battles} - math.floor((B.fought or 0) + 0) if want < 0 then want = 0 end local left = math.floor((B.left or 0) + 0) if want > left then want = left end B.todo = want return want end)() INTO storm_todo

# --- the day's boxes ------------------------------------------------------------
# A box is asked for by its PLACE in the day's ladder — the first, the second, the third
# — and never by the number of battles it wants. The two look alike for the first box
# (one battle, first place) and part company after it: measured on 2026-09-07, asking for
# «5» left the five-battle box unclaimed while asking for «3» took it. Only boxes the day
# has actually reached are asked for, and only ones it has not already taken.
LUA pcall(function() local B = DataCenter.__lw_storm local m = DataCenter.NewPeakArenaManager local r = m.rankData local fought = math.floor((B.fought or 0) + 0) for i, row in pairs(r.dailyReward) do local need = math.floor((row.needCount or 0) + 0) local got = math.floor((row.rewarded or 0) + 0) if got == 0 and need > 0 and fought >= need then pcall(function() SFSNetwork.SendMessage(MsgDefines.NewArenaReward, math.floor(i + 0)) end) end end end)

WAIT 4

# The rank list is asked again so the box is counted on what the SERVER says it gave,
# never on the fact that a message left.
LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.NewArenaRankList) end)

WAIT 3

READ_LUA (function() local ok, out = pcall(function() local B = DataCenter.__lw_storm local m = DataCenter.NewPeakArenaManager local r = m.rankData local taken, waiting, need, chest = 0, 0, -1, -1 pcall(function() local fought = math.floor((r.battleCount or 0) + 0) for _, row in pairs(r.dailyReward) do local n = math.floor((row.needCount or 0) + 0) local got = math.floor((row.rewarded or 0) + 0) if got == 1 then taken = taken + 1 elseif fought >= n then waiting = waiting + 1 end if n > need then need = n chest = got end end end) B.boxes = taken return 'fought ' .. math.floor((B.made or 0) + 0) .. ' this run, won ' .. math.floor((B.won or 0) + 0) .. ', lost ' .. math.floor((B.lost or 0) + 0) .. ', today ' .. math.floor((r.battleCount or 0) + 0) .. ' of {battles}, attempts left ' .. math.floor((r.battleTimes or 0) + 0) .. ', boxes taken ' .. taken .. ' (still owed ' .. waiting .. '), the ' .. need .. '-battle box ' .. ((chest == 1) and 'is in' or 'is not') end) if not ok then return 'the day could not be totted up: ' .. tostring(out) end return out end)() INTO storm_report

LOG "storm arena: {storm_report}"

READ_LUA (function() local B = DataCenter.__lw_storm return math.floor((B.strikes or 0) + 0) end)() INTO storm_strikes

IF storm_strikes > 1
    FAIL "the storm arena refused two battles in a row — the clock will try again"
