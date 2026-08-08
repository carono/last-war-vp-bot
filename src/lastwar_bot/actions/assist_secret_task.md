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
# THE STAR COMES FIRST, AND WAITING FOR ONE IS PART OF THE RULE (#1292). A star is
# rare — live, one alliance task in two hundred carried one against thirty-four finished
# URs — so a budget that takes whatever is ready spends its five on URs by lunchtime and
# has nothing left when the star of the day finally matures. So: a ready star is helped
# before any UR whatever their levels, and every star still counting down HOLDS ONE HELP
# BACK. The rest of the budget goes on URs meanwhile — the star reserves one help each,
# not the whole five.
#
# AND THE WAIT HAS A FLOOR UNDER IT. A star is only worth holding a help for while it can
# still be helped TODAY: it must finish before its own `actEndTime`, before the daily
# reset the budget rides on (02:00 UTC), and inside `star_wait_min`. One that cannot make
# all three is counted, said out loud and left — the budget goes to the URs rather than
# to a star that will still be counting down when the five come back.
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
# plan pays for, and the star always outranks the UR.
ARGS level = 0

# The longest a star still counting down may hold one of the day's helps back. 0 = as
# long as it takes, which the task's own expiry and the daily reset still bound.
ARGS star_wait_min = 240

# 1. Re-read the alliance's tasks. Everything below is judged on what comes back.
TAP refresh_alliance_secret_tasks

# 2. Park the rule where the press can read it — `TAP` takes no arguments.
LUA local M=DataCenter.ActDispatchTaskDataManager M.__lw_assist_level={level} M.__lw_assist_wait_ms={star_wait_min}*60000

# 3. One walk over the list, so every question below is answered about the same moment.
#    The scan parks its answers on the dispatch manager; these read them back.
TAP scan_secret_task_stars
# …except the budget, which is asked of the manager directly. It is the one reading here
# that does not come off the alliance list, and a scan that failed silently must not be
# able to report «no assists left today» about a day with five in hand.
READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local cap=tonumber(M:GetDispatchSetting('aid_count')) or 0 local used=tonumber(M:GetTodayAssistNum()) or 0 local left=cap-used if left<0 then left=0 end return left end)() INTO helps_left
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_star_ready) or 0) INTO star_ready
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_star_pending) or 0) INTO star_pending
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_star_late) or 0) INTO star_late
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_star_level) or 0) INTO star_level
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_star_ur) or 0) INTO ur_ready
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_star_eta) or -1) INTO star_eta_min
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_star_hold) or 0) INTO star_hold

# 4. Say why nothing happened, when nothing does. A silent standing order is
#    indistinguishable from a broken one.
#
#    THE PRIORITY IS ONLY SPOKEN OF WHILE THERE IS A BUDGET TO SPEND (#1292, seen live).
#    A spent day has nothing to hold and nothing to choose between: «придерживаю 2 из 0»
#    is arithmetic reported as if it were a decision, and the person reading it has to
#    work out for themselves that the real answer is the line above.
IF helps_left == 0
    LOG "no assists left today"
ELSE
    # 5. …and say which way the priority fell, every time. Every one of these lines is a
    #    decision about the day's five, and a budget spent without a reason given is the
    #    thing #1227 was. `star_hold` rather than `star_pending`: what is HELD is capped
    #    by what is left, however many stars are on their way.
    IF star_ready > 0
        LOG "star first: {star_ready} starred task(s) ready, {ur_ready} UR waiting its turn"
    ELSE
        IF star_pending > 0
            LOG "waiting for star {star_level} (ready in {star_eta_min} min) — holding {star_hold} of {helps_left} help(s) back"
        ELSE
            LOG "no star ripening today — taking UR ({ur_ready} ready)"

    # 6. …and never wait in silence for one that cannot make it.
    IF star_late > 0
        LOG "{star_late} star(s) cannot ripen before the day resets — not waiting for those"

# 7. Spend what the rule allows. `xall` re-reads between presses: ready stars first, then
#    URs into whatever is left AFTER one help per ripening star. It stops when the list
#    runs out, when the budget does, and when the only thing left is the reserve.
TAP assist_secret_task xall
