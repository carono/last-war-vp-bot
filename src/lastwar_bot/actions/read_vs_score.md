# Read the alliance duel's score: mine, my alliance's, and the side we are playing.
# ru: Прочитать счёт дуэли: мои очки, очки альянса и счёт противостояния.
#
# A READ, and nothing else: it presses nothing, opens nothing and spends nothing.
#
# WHERE THE DUEL KEEPS ITS SCORE. `DataCenter.GetDuelScoreManager.duelInfos[2]` is the
# alliance duel («VS»); `duelInfos[1]` is the arms race and is not this. Its `scoreData`
# carries three different things and they are easy to confuse:
#
# * `curScore` — THE PLAYER'S OWN score for the duel, the number the personal reward
#   ladder is paid against. `target` is that ladder, the game's own `|`-joined list of
#   milestones.
# * `vsAllianceInfo` — one entry per SIDE, with `alName`, `abbr`, `allianceId`, `alScore`
#   (that side's score) and `win` (days won so far).
# * `minDayScore` / `minWeekScore` — what an alliance has to reach for the event to pay.
#
# WHICH SIDE IS OURS IS DERIVED, NEVER GUESSED (docs/research/vs-rankings.md): there is
# no «this is you» field, `targetAllianceId` names the OPPONENT, so the other of the two
# entries is ours. With no opponent named the sides come back empty rather than picked at
# random — an empty column is honest, a guessed one looks answered.
#
# What comes back in `vs_score`, one `key=value` per space:
#
#     mine=1234567 target=40000,150000,540000 minday=200000 minweek=600000
#     us=AL1|1000000|1 them=AL2|900000|0
#
# — `us` and `them` are `<abbr>|<score>|<days won>`. A field the game has not filled in
# comes back empty rather than as a zero: «nobody knows» and «none» are different answers
# and the page draws them differently.
#
# Who reads it: the «VS» tab, once when the client gets into the game and again on the
# duel's own push. Nothing here decides anything and nothing here is written down.

READ_LUA (function() local M = DataCenter.GetDuelScoreManager if M == nil then return '' end local sd = nil pcall(function() sd = M.duelInfos[2].scoreData end) if sd == nil then return '' end local out = {} local mine = -1 pcall(function() mine = math.floor((sd.curScore or -1) + 0) end) out[#out+1] = 'mine=' .. tostring(mine) local tg = '' pcall(function() tg = tostring(sd.target or '') end) tg = string.gsub(tg, '|', ',') out[#out+1] = 'target=' .. tg local md, mw = -1, -1 pcall(function() md = math.floor((sd.minDayScore or -1) + 0) end) pcall(function() mw = math.floor((sd.minWeekScore or -1) + 0) end) out[#out+1] = 'minday=' .. tostring(md) out[#out+1] = 'minweek=' .. tostring(mw) local foe = '' pcall(function() foe = tostring(sd.targetAllianceId or '') end) local us, them = '', '' pcall(function() for _, s in pairs(sd.vsAllianceInfo or {}) do local id = tostring(s.allianceId or '') local abbr = tostring(s.abbr or '') local score = math.floor((s.alScore or 0) + 0) local win = math.floor((s.win or 0) + 0) local row = abbr .. '|' .. tostring(score) .. '|' .. tostring(win) if foe ~= '' and id == foe then them = row elseif foe ~= '' then us = row end end end) out[#out+1] = 'us=' .. us out[#out+1] = 'them=' .. them return table.concat(out, ' ') end)() INTO vs_score

LOG "duel score: {vs_score}"
