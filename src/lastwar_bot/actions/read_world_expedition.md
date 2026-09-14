# Read «Мировой поход»: which of the four zones are open, how far each one got, what is owed.
# ru: Чтение «Мирового похода»: какие из четырёх зон открыты, как далеко прошли, что не забрано.
#
# HEADLESS. No window is opened and nothing is tapped: the client keeps the whole event in
# `DataCenter.LWSeasonTowerManager`, filled by `season.tower.info` at login and kept up to
# date by the server's own pushes, so one VM round trip answers everything
# (`docs/research/world-expedition.md`).
#
# WHAT IT LEAVES BEHIND, for the errand that plays the event and for the card that draws it:
#
#   expedition  — the whole reading as one line, which is what the panel keeps
#   open        — 1 while a round is running, 0 when it is not
#   live        — how many zones are open right now (they unlock on days 1, 3, 5 and 7)
#   unset       — how many open zones still have no lineup in them
#   rewards     — how many claims are waiting (a zone's own, plus the points tier)
#   ends        — when the round is over, in seconds; a round lasts fourteen days
#   next_zone   — when the next zone unlocks, in seconds, or 0 when they all have
#
# The per-zone fields are `oN` (open), `fN` (stages cleared), `hN` (lineup set) and `rN`
# (a claim waiting), N being 1..4 in the game's own order.

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local S = {known = 0, open = 0, zones = 0, live = 0, unset = 0, rewards = 0, score = 0, next_score = 0, starts = 0, ends = 0, next_zone = 0, safe = 0} for i = 1, 4 do S['o' .. i] = 0 S['f' .. i] = 0 S['h' .. i] = 0 S['r' .. i] = 0 S['id' .. i] = 0 end DataCenter.__lw_ge = S local M = DataCenter.LWSeasonTowerManager if type(M) ~= 'table' then return 0 end S.known = 1 local now = 0 pcall(function() now = num(UITimeManager.Instance:GetServerTime()) end) if now == 0 then now = os.time() * 1000 end S.starts = math.floor(num(M.startTime) / 1000) S.ends = math.floor(num(M.endTime) / 1000) S.score = num(M.score) S.next_score = num(M.nextScore) if num(M.startTime) > 0 and num(M.endTime) > now then S.open = 1 end pcall(function() if M:IsHasClaimSafeBoxReward() == true then S.safe = 1 end end) local list = M.stageList or {} local nxt = 0 for i = 1, 4 do local st = list[i] if type(st) == 'table' then S.zones = S.zones + 1 S['id' .. i] = num(st.stageId) S['f' .. i] = num(st.floor) local at = num(st.openTime) if at > 0 and at <= now then S['o' .. i] = 1 S.live = S.live + 1 local n = 0 pcall(function() local f = M:GetFormation(num(st.stageId)) for _ in pairs(f.heroes or {}) do n = n + 1 end end) if n > 0 then S['h' .. i] = 1 else S.unset = S.unset + 1 end pcall(function() if M:HasRewardToClaim(i) == true then S['r' .. i] = 1 S.rewards = S.rewards + 1 end end) elseif at > 0 and (nxt == 0 or at < nxt) then nxt = at end end end S.next_zone = math.floor(nxt / 1000) pcall(function() for _, row in pairs(M:GetGroupScoreRewards() or {}) do if num(row.received) == 0 then S.rewards = S.rewards + 1 break end end end) return S.open end)() INTO open

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local S = DataCenter.__lw_ge or {} local out = {} for _, k in ipairs({'known', 'open', 'zones', 'live', 'unset', 'rewards', 'score', 'next_score', 'starts', 'ends', 'next_zone', 'safe'}) do out[#out + 1] = k .. '=' .. num(S[k]) end for i = 1, 4 do for _, p in ipairs({'o', 'f', 'h', 'r'}) do out[#out + 1] = p .. i .. '=' .. num(S[p .. i]) end end return table.concat(out, ' ') end)() INTO expedition

READ_LUA (function() local S = DataCenter.__lw_ge or {} return math.floor(S.live or 0) end)() INTO live
READ_LUA (function() local S = DataCenter.__lw_ge or {} return math.floor(S.unset or 0) end)() INTO unset
READ_LUA (function() local S = DataCenter.__lw_ge or {} return math.floor(S.rewards or 0) end)() INTO rewards
READ_LUA (function() local S = DataCenter.__lw_ge or {} return math.floor(S.ends or 0) end)() INTO ends

LOG "Мировой поход: {expedition}"
