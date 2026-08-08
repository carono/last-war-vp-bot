# Take a starred alliance task in the second it matures — «спринт по звезде».
# ru: Спринт по звезде: жать в момент готовности задания-звезды.
#
# The ordinary standing order is assist_secret_task.md: it re-reads the alliance's list,
# ranks it, holds a help back for a ripening star and spends the rest on URs. This is the
# other half of that rule — the part that actually COLLECTS the star it has been holding
# the help for.
#
# WHY IT EXISTS. Live acceptance of the star priority (#1292) measured the failure
# exactly: the day's only ripe star was gone from the list in UNDER TWO MINUTES, taken by
# alliancemates, and `star_ready` never read non-zero on a single poll. The reserve
# worked — a help was being kept — and the help was still not spent. A rule that waits
# for a star and then arrives late loses twice over: the star goes to somebody else and
# the URs it held the budget from go unspent as well.
#
# AND NOTHING NEEDS TO POLL FASTER TO FIX IT. The task carries its own `completionTime`,
# so the instant it matures is known to the millisecond the moment the five-minute poll
# first sees the task — live, three level-7 stars announced themselves 78, 79 and 233
# minutes ahead. The panel therefore SCHEDULES: it sleeps until a few seconds before the
# star is due and plays this recipe then. The ordinary period never changes, no extra
# reads happen while the star ripens, and the only fast pressing there is lasts seconds.
#
# PRESSING EARLY IS FREE, which is what lets the spam start before the countdown ends.
# `DispatchAssistMessage:HandleMessage` takes the `errorCode` branch on a refusal and
# raises a tip; `todayAssistNum` reaches the client only on the success branch, out of the
# server's own reply. So a press against a task that is not finished yet spends nothing —
# the same guarantee the robbery leans on (steal_secret_task.md) — and the loop can let
# the SERVER decide when «yes» begins instead of trusting our own idea of the clock.
#
# The whole ability is written up in docs/research/secret-task-assist.md.

# The lowest level worth one of the day's five, exactly as the ordinary order reads it.
# Blank/0 = any level. Only starred tasks are sprinted at: a UR is not worth a spam loop
# — thirty-four of them sat unhelped in one live reading — and the ordinary recipe spends
# those at its own pace.
ARGS level = 0

# How long the pressing may last, from arming. It bounds the case the clock cannot: a
# star that never matures — a mate who cancelled it, a countdown that was already wrong
# when we read it — would otherwise be pressed until the button's own cap every time.
ARGS window_sec = 20

# 1. Re-read the alliance's list. The same first step the ordinary order takes and for
#    the same reason: the local copy keeps tasks other people have already helped with,
#    and a press at one of those is answered with a tip instead of a help.
TAP refresh_alliance_secret_tasks

# 2. Park the rule and the window where the presses can read them — `TAP` takes no
#    arguments. The wait bound is irrelevant here (we are AT the star, not deciding
#    whether to wait for it), so it is parked as zero: every star that can still be
#    helped today is a legitimate target for a sprint.
LUA local M=DataCenter.ActDispatchTaskDataManager M.__lw_assist_level={level} M.__lw_assist_wait_ms=0 M.__lw_assist_window_ms={window_sec}*1000

# 3. One walk over the list, so every question below is about the same moment — and then
#    ARM IMMEDIATELY, before anything is read back for the log. Every `READ_LUA` is a
#    round trip, and the six below cost about three seconds together; arming behind them
#    would spend that out of the lead the panel scheduled. The arming makes its own
#    decision about the budget (it arms nothing when the day's five are gone), so nothing
#    below has to run first for it to be safe.
TAP scan_secret_task_stars
TAP arm_assist_sprint

READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local cap=tonumber(M:GetDispatchSetting('aid_count')) or 0 local used=tonumber(M:GetTodayAssistNum()) or 0 local left=cap-used if left<0 then left=0 end return left end)() INTO helps_left
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_star_ready) or 0) INTO star_ready
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_star_pending) or 0) INTO star_pending
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_star_eta_sec) or -1) INTO star_eta_sec
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_star_level) or 0) INTO star_level
READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager if M.__lw_assist_target then return 1 end return 0 end)() INTO armed

IF helps_left == 0
    LOG "no assists left today"
ELSE
    # 4. What the arming chose: the ready star if the countdown had already ended,
    #    otherwise the nearest one still running. Both are ordinary — the panel aims this
    #    recipe a few seconds early, so the star it came for usually has not matured yet.
    IF armed == 0
        # Nothing starred is in reach. Said out loud rather than passed over: a sprint
        # that pressed nothing and a sprint that lost a race look identical otherwise,
        # and telling them apart is the whole of #1227.
        LOG "star sprint: nothing starred to press ({star_ready} ready, {star_pending} ripening)"
    ELSE
        LOG "star sprint: ★{star_level} in {star_eta_sec} s — pressing until the server answers"
        # 5. THE SPRINT. `xall` re-reads the gate between presses and stops on the first
        #    of: the server confirming (`todayAssistNum` moved), the server saying the
        #    task is gone («уже решена с помощью других лиц» — that IS a lost race), the
        #    window closing, the budget running out, or the button's cap.
        TAP assist_secret_task_sprint xall
        # 6. Say what the server did, per target, and disarm.
        TAP finish_assist_sprint
        READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager return tonumber(M.__lw_assist_presses) or 0 end)() INTO presses
        READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local now=tonumber(M:GetTodayAssistNum()) or 0 local mark=tonumber(M.__lw_assist_mark) or now return now-mark end)() INTO taken
        IF taken > 0
            LOG "assist_star_taken — ★{star_level} helped after {presses} press(es)"
        ELSE
            LOG "assist_star_missed — ★{star_level} not taken after {presses} press(es)"
