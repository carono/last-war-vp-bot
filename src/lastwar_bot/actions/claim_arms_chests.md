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
# the row rather than counted from the loop.
#
# ## A DAY CHEST IS ASKED FOR ONLY WHEN THE GAME SAYS IT IS OWED (#2709)
#
# What used to be written here — that a day row carries no target, so the boxes are
# offered by index and «a server that disagrees simply refuses; nothing is lost either
# way» — was wrong about the cost. Something IS lost: the client answers a refused claim
# with its own toast (tip `120228`, raised by the `activity.hero.day.reward` handler),
# and this recipe runs at the start of every arms-race turn. Two unearned boxes therefore
# put two «недостаточно» toasts on the player's screen every run, which is the message
# the person reported as «час юнитов не работает, пишет что недостаточно ресурсов»
# (#2709) — a complaint about a phase that had sent nothing at all.
#
# The manager answers the question itself: `GetDailyBoxState(data, i)` — `i` counted
# from ONE, the row's position, not its zero-based `index` — returns `ActivityBoxState`,
# which is `Close = 1`, `CanOpen = 2`, `Open = 3`. Only `CanOpen` is claimed. When the
# call cannot be made at all the fallback is the day's own progress: `claimStatus` holds
# one key per phase of the day and a non-zero value once that phase counts as finished,
# so box `index` is owed when more phases than that are done.
#
# The research is docs/research/arms-race.md; the reading is actions/read_arms_race.md.

CALL read_arms_race

READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 'no reading' end local act = math.floor((d.activityId or 0) + 0) if act <= 0 then return 'the game would not name the activity — nothing claimed' end local sc = math.floor((d.sc or 0) + 0) local score_sent, score_owed, day_sent, failed = 0, 0, 0, 0 local err = '' for _, b in pairs(d.score_rewards or {}) do if type(b) == 'table' then local got = math.floor((b.receive or 0) + 0) local target = math.floor((b.target or 0) + 0) local idx = math.floor((b.index or 0) + 0) if got == 0 and target > 0 and sc >= target then score_owed = score_owed + 1 local ok, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.ActivityHeroScoreReward, act, idx) end) if ok then score_sent = score_sent + 1 else failed = failed + 1 if err == '' then err = tostring(why) end end end end end local done = 0 local pre = tostring(math.floor((d.curDay or 0) + 0)) .. '_' for k, v in pairs(d.claimStatus or {}) do if tostring(k):sub(1, #pre) == pre and math.floor((v or 0) + 0) ~= 0 then done = done + 1 end end local can_open = 2 pcall(function() can_open = math.floor((ActivityBoxState.CanOpen or 2) + 0) end) local day_shut = 0 for i, b in pairs(d.day_rewards or {}) do if type(b) == 'table' then local got = math.floor((b.receive or 0) + 0) local idx = math.floor((b.index or 0) + 0) if got == 0 then local state = 0 pcall(function() state = math.floor((M:GetDailyBoxState(d, i) or 0) + 0) end) local owed = false if state > 0 then owed = (state == can_open) else owed = (done > idx) end if owed then local ok, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.ActivityHeroDayReward, act, idx) end) if ok then day_sent = day_sent + 1 else failed = failed + 1 if err == '' then err = tostring(why) end end else day_shut = day_shut + 1 end end end end return 'score=' .. sc .. ' phase_chests_owed=' .. score_owed .. ' phase_claimed=' .. score_sent .. ' phases_done_today=' .. done .. ' day_claimed=' .. day_sent .. ' day_not_earned=' .. day_shut .. ' failed=' .. failed .. (err ~= '' and (' err=' .. err) or '') end)() INTO arms_chests

WAIT 2

# What the server made of it. A row still saying `receive == 0` after a claim is a row
# the server refused, and that is worth seeing rather than assuming.
READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 'no reading' end local sc = math.floor((d.sc or 0) + 0) local held, owed = 0, 0 for _, b in pairs(d.score_rewards or {}) do if type(b) == 'table' then local got = math.floor((b.receive or 0) + 0) local target = math.floor((b.target or 0) + 0) if got == 1 then held = held + 1 elseif target > 0 and sc >= target then owed = owed + 1 end end end local dheld = 0 for _, b in pairs(d.day_rewards or {}) do if type(b) == 'table' and math.floor((b.receive or 0) + 0) == 1 then dheld = dheld + 1 end end return 'phase_taken=' .. held .. ' still_owed=' .. owed .. ' day_taken=' .. dheld end)() INTO arms_chests_after

LOG "arms chests: {arms_chests} :: {arms_chests_after}"
