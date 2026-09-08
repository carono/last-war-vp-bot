# Claim every finished daily quest, then every step of the daily-progress ladder.
# ru: Забрать выполненные ежедневные задания и открывшиеся ступени прогресса.
#
# «Ежедневные задания» is two claims that look like one screen: a LIST of quest rows
# («убей 5 зомби», «потрать выносливость»), each worth points, and a LADDER of five
# boxes that open as the day's points cross 40 / 80 / 120 / 160 / 200. Both are headless
# — no window is opened, no marker is tapped, nothing is clicked.
#
# WHAT IS SENT, AND HOW IT WAS LEARNT (#2076). Neither shape was guessed and neither
# was found by pressing: both messages were built with `NewEmpty`, handed an `sfsObj`
# that records every `PutX`, and asked to fill themselves from marked arguments
# (`dev/_t2076_wire.md`, the trick from docs/research/alliance-train.md):
#
#   daily.task.reward   -> PutUtfString taskId   — ONE quest row, id as a STRING
#   daily.quest.reward  -> PutInt        stage   — ONE ladder box, by its 1..5 INDEX
#   daily.quest.ls      -> no fields             — «tell me the list again»
#
# The stage is an INDEX and not a threshold: `GetBoxState(40)` answers 0 for every
# threshold, while `GetBoxState(1..3)` answered 2 on a day whose three lower boxes had
# been taken. A number nobody has reached yet raises inside the manager rather than
# answering (`DailyTaskManager.lua:194: attempt to compare number with nil`), which is
# why every reading here is inside a `pcall` and an unreadable box is «not yet», never
# «press it».
#
# THE GATE IS THE GAME'S OWN WORD, AND WE COUNT NOTHING. A quest row carries `state`:
#
#   0 — not finished          1 — finished, NOT claimed          2 — claimed
#
# so «what is there to take» is asked of the client and never derived from a tally the
# panel keeps. That also gives the run its verdict for free: **a row that is still
# `state == 1` after its claim was sent is a REFUSAL, not a success**. The whole of
# #1854 is that lesson — 553 runs reporting success while collecting nothing — so this
# recipe re-reads and says the number out loud rather than counting what it sent.
#
# The ladder is asked the same way, box by box (`GetBoxState`), rather than by a
# «claim everything» press: five separate answers say WHICH box arrived, and a run that
# gets four and is refused one says so.
#
# WHAT WAKES IT. `push.daily.quest` — the server's own announcement that the day's
# progress moved. That is the trigger this belongs on: read once, then listen, never a
# clock asking «is there anything yet» (CLAUDE.md).

# 1. Claim every finished-but-unclaimed row, one message each, in one VM round trip —
#    a trip costs ~0.15 s and the loop inside it is free. A day with nothing finished
#    costs exactly this one read and the run is over four lines later: `push.daily.quest`
#    fires whenever the day's progress MOVES, which is most of the time somebody is
#    playing, so the no-op path must be cheap enough to be run for nothing.
# ONE CALL, NOT ONE PER QUESTION (#2404). A read is a thread hijack into the
# client at half a second a time whatever it asks, and the machine can make about
# 1.4 of them a second in total (`docs/research/link-contention.md`), so a run of
# readings one statement at a time is that many seconds of everybody's budget for
# answers the game could hand over together. What each one is, and why it is asked,
# is on the comments and LOG lines that follow.
READ_LUA (function() local __v0 = (function() local M = DataCenter and DataCenter.DailyTaskManager if M == nil then DataCenter.__lw_dq = 'no DailyTaskManager — is the client logged in?' DataCenter.__lw_dq_n = 0 return 0 end local ready, sent, failed, err, ids = 0, 0, 0, '', {} for _, r in pairs(M.dailyQuestTasks or {}) do if type(r) == 'table' and r.state == 1 then ready = ready + 1 local ok, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.DailyTaskReward, tostring(r.id)) end) if ok then sent = sent + 1 ids[#ids+1] = tostring(r.id) else failed = failed + 1 if err == '' then err = tostring(why) end end end end DataCenter.__lw_dq = 'finished ' .. ready .. ', claim sent ' .. sent .. (failed > 0 and (', REFUSED BY THE CLIENT ' .. failed .. ' (' .. err .. ')') or '') .. (sent > 0 and (' [' .. table.concat(ids, ' ') .. ']') or '') DataCenter.__lw_dq_n = sent return sent end)() local __v1 = tostring(DataCenter.__lw_dq or '') return __v0, __v1 end)() INTO quests_sent, quests_said
LOG "Daily quests: {quests_said}"

# 2. Only a run that actually claimed something waits for the answers — and then says
#    what LANDED. A row still sitting at state 1 was refused, which is the one thing a
#    run that counted its own presses could never notice (#1854: 553 runs of a recipe
#    reporting success while collecting nothing).
IF quests_sent > 0
    WAIT 2
    READ_LUA (function() local M = DataCenter and DataCenter.DailyTaskManager if M == nil then return 'no manager' end local left, done, open = 0, 0, 0 for _, r in pairs(M.dailyQuestTasks or {}) do if type(r) == 'table' then if r.state == 1 then left = left + 1 elseif r.state == 2 then done = done + 1 else open = open + 1 end end end local cur = -1 pcall(function() cur = M:GetCurValue() + 0 end) return 'claimed today ' .. done .. ', still unclaimed ' .. left .. ', unfinished ' .. open .. ', points ' .. cur .. (left > 0 and ' — THE SERVER REFUSED THE UNCLAIMED ONES' or '') end)() INTO quests_after
    LOG "Daily quests: {quests_after}"

# 3. The ladder, one box at a time. `GetBoxState` is the game's own answer about a box;
#    the point total is only used to skip a box nobody has reached yet, so a state this
#    recipe has never met still ends up in the log instead of inside a guess. Read after
#    the claims above on purpose — the points those rows are worth are what opens the
#    next box.
# ONE CALL, NOT ONE PER QUESTION (#2404). A read is a thread hijack into the
# client at half a second a time whatever it asks, and the machine can make about
# 1.4 of them a second in total (`docs/research/link-contention.md`), so a run of
# readings one statement at a time is that many seconds of everybody's budget for
# answers the game could hand over together. What each one is, and why it is asked,
# is on the comments and LOG lines that follow.
READ_LUA (function() local __v0 = (function() local M = DataCenter and DataCenter.DailyTaskManager if M == nil then DataCenter.__lw_dq_box = 'no manager' return 0 end local cur = -1 pcall(function() cur = M:GetCurValue() + 0 end) local steps = M.dailyBoxActive or {} local sent, taken, held, failed, err, seen = 0, 0, 0, 0, '', {} for i = 1, 20 do local need = steps[i] if need == nil then break end local want = -1 pcall(function() want = need + 0 end) local st = nil pcall(function() st = M:GetBoxState(i) end) seen[#seen+1] = i .. '@' .. want .. ':' .. tostring(st) if st == 2 then taken = taken + 1 elseif want >= 0 and cur >= want then local ok, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.DailyQuestReward, i) end) if ok then sent = sent + 1 else failed = failed + 1 if err == '' then err = tostring(why) end end else held = held + 1 end end DataCenter.__lw_dq_box = 'points ' .. cur .. ', already taken ' .. taken .. ', claim sent ' .. sent .. ', not reached ' .. held .. (failed > 0 and (', REFUSED BY THE CLIENT ' .. failed .. ' (' .. err .. ')') or '') .. ' [' .. table.concat(seen, ' ') .. ']' return sent end)() local __v1 = tostring(DataCenter.__lw_dq_box or '') local __v2 = __v0 + (DataCenter.__lw_dq_n or 0) return __v0, __v1, __v2 end)() INTO boxes_sent, boxes_said, granted
LOG "Daily ladder: {boxes_said}"

# 4. …and the ladder's own verdict, read back the same way, for the same reason: a box
#    that was sent and is not `2` afterwards was refused, whatever the press said.
IF boxes_sent > 0
    WAIT 2
    READ_LUA (function() local M = DataCenter and DataCenter.DailyTaskManager if M == nil then return 'no manager' end local cur = -1 pcall(function() cur = M:GetCurValue() + 0 end) local all = false pcall(function() all = M:IsAllBoxRewardReceived() end) local out, taken, waiting = {}, 0, 0 local steps = M.dailyBoxActive or {} for i = 1, 20 do local need = steps[i] if need == nil then break end local st = nil pcall(function() st = M:GetBoxState(i) end) out[#out+1] = i .. ':' .. tostring(st) if st == 2 then taken = taken + 1 elseif st ~= nil then waiting = waiting + 1 end end return 'points ' .. cur .. ', boxes taken ' .. taken .. ', still open ' .. waiting .. ', ladder finished ' .. tostring(all) .. ' [' .. table.concat(out, ' ') .. ']' end)() INTO boxes_after
    LOG "Daily ladder: {boxes_after}"

# 5. …and the windows the claims raised (#2642). Both claims are headless, but the
#    client answers a granted reward with a modal of its own — «вот что вам дали» — and
#    it lands on top of whatever is on screen and stays there. So a run that actually
#    took something puts the ear back in and shuts what is up: `collect_reward_popups`
#    closes a reward window the moment it opens (and writes down what was in it), while
#    the sweep clears one that was already standing when the ear went in.
#
#    Only on the run that claimed: this recipe is played from `push.daily.quest`, which
#    lands whenever the day's progress moves, and a run that took nothing must stay the
#    one cheap read it is. `granted` is the two claim counts added together inside the
#    read above, because a condition here can only test one variable against a number.
#
#    The quest count reaches that sum through a Lua global the first read parks
#    (`DataCenter.__lw_dq_n`) and NOT as a substituted placeholder: a brace-name is
#    filled in when the file is PARSED, so a value the run has only just read arrives
#    as the literal text and the whole read comes back nil (docs/dsl.md, `PARK`). Measured
#    live — the first version failed with «variable 'boxes_sent' = None».
IF granted > 0
    TAP dismiss_reward_popup
    CALL collect_reward_popups
