# Help the alliance finish its best secret tasks — «помощь секретке».
# ru: Помощь соратникам с секретными заданиями («помочь выполнить»).
#
# NOT the alliance «Помочь всем» (help_ally.md). That one answers building and research
# requests, rides `al.help.all` and is unlimited; this one answers an alliancemate's
# FINISHED hero-dispatch task, rides `hero.dispatch.assist` and costs one of five a day
# (`GetDispatchSetting("aid_count")`). It is what the daily plan means by «помочь
# выполнить 5 секретных заданий ранга UR или Звезда», and the counter resets daily, so
# an unspent help is income thrown away — the same reason occupation_skills.md exists.
#
# Nor is it the robbery (steal_secret_task.md): that spends a different budget on
# strangers' tiles. Helping pays the helper AND the owner, and it is the alliance's own
# list it works over, so there is no home-server prohibition here to speak of.
#
# One press = one `hero.dispatch.assist {uuid, targetServer}`, headless: no window, no
# marker tap, no camera move. The engine calls live in tools/lib/game_buttons.py; the API
# is written up in docs/research/secret-task-assist.md.
#
# THE LIST GOES STALE, AND THAT IS THE WHOLE TRAP. The client only hears that a task has
# been helped by somebody else through a push it has to be listening for; a bot with no
# window open keeps entries the server has long since closed. Sending at one of those is
# answered with «Спасибо, но задача уже решена с помощью других лиц» and the budget does
# NOT move — which reads exactly like a bot that pressed nothing at all. Live, two
# attempts failed that way and the third, sent right after the re-read below, took
# `todayAssistNum` 0 -> 1 and the task vanished from the list.
#
# Verified live (task #1272): with the day's five untouched, one help landed on a
# finished alliance task on the home server and the counter moved.

# The lowest level worth one of the day's five. Blank/0 = any level. The RANK is not an
# argument: only UR and starred tasks are ever helped, because that is what the daily
# plan pays for.
ARGS level = 0

# 1. Re-read the alliance's tasks. Everything below is judged on what comes back.
TAP refresh_alliance_secret_tasks

# 2. Park the rule where the press can read it — `TAP` takes no arguments.
LUA local M=DataCenter.ActDispatchTaskDataManager M.__lw_assist_level={level}

# 3. Say why nothing happened, when nothing does. A silent standing order is
#    indistinguishable from a broken one.
READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local cap=tonumber(M:GetDispatchSetting('aid_count')) or 0 local used=tonumber(M:GetTodayAssistNum()) or 0 local left=cap-used if left<0 then left=0 end return left end)() INTO helps_left
IF helps_left == 0
    LOG "no assists left today"

# 4. Spend what there is. `xall` re-reads min(matching tasks, helps left) between
#    presses, so it stops both when the list runs out and at the daily cap.
TAP assist_secret_task xall
