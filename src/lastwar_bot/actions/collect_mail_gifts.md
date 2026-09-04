# Take every gift the mail is still holding — the «собрать всё» of each tab.
# ru: Забрать подарки из почты — «собрать всё» по всем вкладкам.
#
# WHAT THE ABILITY IS (#2090). A mail tab draws a red badge when one of its letters
# still has an attachment nobody has taken, and the tab's own button takes the lot.
# There are nine tabs, the badge is per tab, and a letter's gift does not expire the
# moment it arrives — so a run that presses every tab with something in it collects
# whatever has accumulated since the last one.
#
# THE GATE IS THE CLIENT'S OWN BADGE, AND IT IS LOCAL. `DataCenter.MailDataManager`
# keeps `group[<tab>]` with `unrewardCount` — the very number the badge draws — beside
# `unreadCount` and the tab's total. A tab whose `unrewardCount` is 0 is not pressed at
# all: nothing is asked of the server for it. Measured live on 2026-09-01: nine tabs,
# `unrewardCount` 0/0/3/11/0/0/0/0/1, and `GetMailUnRewardCountByGroup(<tab>)` returns
# the same figure for anybody who would rather ask by method.
#
# A letter carries the same fact itself — `rewardStatus` is 0 while its gift is still
# there and 1 once it has been taken, and `mail:CanClaimReward()` says so in one call.
# The two agree: a tab reading `unrewardCount = 11` had exactly eleven letters at
# `rewardStatus = 0`. The letters are PAGED, though (a tab of 1 566 letters hands out
# twenty at a time), so the count on the tab is what this recipe gates on — the loaded
# page is a sample, not the list.
#
# THE PRESS IS `ReadAndRewardGroupMail(<tab>)`, the manager's own «собрать всё»: it is
# what the button behind the badge calls, it goes out as `mail.reward.batch` and it
# needs NO window open — measured headless on the tab that had one gift left, badge
# 1 -> 0 and the letter's `rewardStatus` 0 -> 1 within two seconds. As its name says it
# also marks that tab's letters read, exactly as pressing the button in the game does.
#
# WHY IT IS NOT A CLOCK. A gift announces itself: a letter arrives as `push.mail`, so
# the trigger `mail_gifts` listens for that and this recipe runs on the announcement
# (CLAUDE.md, «читаем один раз, дальше слушаем»). Nothing here polls, and a run with
# every badge at zero is one VM round trip that presses nothing and says so.
#
# The wire names, the manager's surface and what was measured are written up in
# docs/research/mail-gifts.md.

# One round trip for the whole sweep: a trip costs ~0.15 s and the loop inside it is
# free (docs/research/alliance-tech-donate.md). Returns HOW MANY tabs were pressed so
# the recipe can branch; the sentence for the log is parked and read back below.
# ONE CALL, NOT ONE PER QUESTION (#2404). A read is a thread hijack into the
# client at half a second a time whatever it asks, and the machine can make about
# 1.4 of them a second in total (`docs/research/link-contention.md`), so a run of
# readings one statement at a time is that many seconds of everybody's budget for
# answers the game could hand over together. What each one is, and why it is asked,
# is on the comments and LOG lines that follow.
READ_LUA (function() local __v0 = (function() local t0 = os.clock() local M = DataCenter.MailDataManager if not M then DataCenter.__lw_mail = 'no manager' return 0 end local tabs, gifts, pressed, failed = 0, 0, 0, 0 local err, hit = '', '' for gid, g in pairs(M.group or {}) do if type(g) == 'table' then tabs = tabs + 1 local n = tonumber(g.unrewardCount) or 0 if n <= 0 then local ok, m = pcall(function() return M:GetMailUnRewardCountByGroup(gid) end) if ok then n = tonumber(m) or 0 end end if n > 0 then gifts = gifts + n local ok, why = pcall(function() M:ReadAndRewardGroupMail(gid) end) if ok then pressed = pressed + 1 hit = hit .. (hit ~= '' and ',' or '') .. tostring(gid) .. ':' .. n else failed = failed + 1 if err == '' then err = tostring(why) end end end end end DataCenter.__lw_mail = 'tabs=' .. tabs .. ' gifts=' .. gifts .. ' pressed=' .. pressed .. ' failed=' .. failed .. (hit ~= '' and (' [' .. hit .. ']') or '') .. ' ms=' .. math.floor((os.clock() - t0) * 1000) .. (err ~= '' and (' err=' .. err) or '') return pressed end)() local __v1 = tostring(DataCenter.__lw_mail or '') return __v0, __v1 end)() INTO pressed, summary
LOG "Mail gifts: {summary}"

# What the SERVER made of it, and never the press itself: `unrewardCount` moves when the
# reply lands, so a badge still standing after this is a gift the server refused. Read
# only when something actually went out — a run that pressed nothing has nothing to
# confirm and no reason to spend the wait.
IF pressed > 0
    WAIT 1.5
    READ_LUA (function() local M = DataCenter.MailDataManager local left, rest = 0, '' for gid, g in pairs(M.group or {}) do local n = tonumber(g.unrewardCount) or 0 if n > 0 then left = left + n rest = rest .. (rest ~= '' and ',' or '') .. tostring(gid) .. ':' .. n end end return 'still waiting=' .. left .. (rest ~= '' and (' [' .. rest .. ']') or '') end)() INTO left
    LOG "Mail gifts: {left}"
    # Whatever the tabs paid out raises the ordinary reward modal; the ear closes it and
    # writes down what was given (#2027).
    CALL collect_reward_popups
