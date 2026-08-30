# «Гонка вооружений» — забрать все положенные сундуки: и за очки фазы, и за день.
# ru: «Гонка вооружений» — забрать все положенные сундуки: и за очки фазы, и за день.
#
# It takes and never spends. A box is claimed only when the SERVER's own row says it is
# owed — `receive == 0` and the score already past the row's `target` — so a run over an
# account that has claimed everything by hand sends nothing at all and says so.
#
# The two ladders are separate and both are walked:
#
#   score_rewards[i] = {index, receive, target, value}         the phase's own chest
#   day_rewards[i]   = {index, receive, resourceItemId, ...}   the day's chest
#
# `index` is the number the send names and it is ZERO-based, which is why it is read off
# the row rather than counted from the loop. What the row will not say is whether a day
# chest is OWED — it carries no target — so those are offered by index and a server that
# disagrees simply refuses; nothing is lost either way.
#
# The research is docs/research/arms-race.md; the reading is actions/read_arms_race.md.

CALL read_arms_race

READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 'no reading' end local act = math.floor((d.activityId or 0) + 0) if act <= 0 then return 'the game would not name the activity — nothing claimed' end local sc = math.floor((d.sc or 0) + 0) local score_sent, score_owed, day_sent, failed = 0, 0, 0, 0 local err = '' for _, b in pairs(d.score_rewards or {}) do if type(b) == 'table' then local got = math.floor((b.receive or 0) + 0) local target = math.floor((b.target or 0) + 0) local idx = math.floor((b.index or 0) + 0) if got == 0 and target > 0 and sc >= target then score_owed = score_owed + 1 local ok, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.ActivityHeroScoreReward, act, idx) end) if ok then score_sent = score_sent + 1 else failed = failed + 1 if err == '' then err = tostring(why) end end end end end for _, b in pairs(d.day_rewards or {}) do if type(b) == 'table' then local got = math.floor((b.receive or 0) + 0) local idx = math.floor((b.index or 0) + 0) if got == 0 then local ok, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.ActivityHeroDayReward, act, idx) end) if ok then day_sent = day_sent + 1 else failed = failed + 1 if err == '' then err = tostring(why) end end end end end return 'score=' .. sc .. ' phase_chests_owed=' .. score_owed .. ' phase_claimed=' .. score_sent .. ' day_offered=' .. day_sent .. ' failed=' .. failed .. (err ~= '' and (' err=' .. err) or '') end)() INTO arms_chests

WAIT 2

# What the server made of it. A row still saying `receive == 0` after a claim is a row
# the server refused, and that is worth seeing rather than assuming.
READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 'no reading' end local sc = math.floor((d.sc or 0) + 0) local held, owed = 0, 0 for _, b in pairs(d.score_rewards or {}) do if type(b) == 'table' then local got = math.floor((b.receive or 0) + 0) local target = math.floor((b.target or 0) + 0) if got == 1 then held = held + 1 elseif target > 0 and sc >= target then owed = owed + 1 end end end local dheld = 0 for _, b in pairs(d.day_rewards or {}) do if type(b) == 'table' and math.floor((b.receive or 0) + 0) == 1 then dheld = dheld + 1 end end return 'phase_taken=' .. held .. ' still_owed=' .. owed .. ' day_taken=' .. dheld end)() INTO arms_chests_after

LOG "arms chests: {arms_chests} :: {arms_chests_after}"
