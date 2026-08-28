# The day's secret tasks, from end to end: claim what ripened, open the boxes, refresh, send.
# ru: Секретные задания за день: собрать созревшее, вскрыть ящики, обновить и отправить.
#
# ONE ERRAND AND NOT TWO, and the reason is a clock rather than a preference. Everything
# this ability waits for happens at the SAME moment — a running task's own
# `completionTime`. When it arrives, three things become true together:
#
#   * the task is finished and its reward is claimable;
#   * **its march slot is still held until the reward is taken** — that is the fact that
#     makes lateness expensive, measured live: six finished tasks sat on six of the nine
#     marches with nothing running at all;
#   * and the heroes that were out on it are home, so an idle task can finally be sent.
#
# A separate «collector» row would wake at exactly the same instants as this one, take
# the same game claim, and race it over the same list. So the day's errand wakes at the
# nearest finish, does all four things in the one order that makes sense, and books its
# own next turn — the schedule's `next_run_in`, the convention `tavern_free_pull.md` uses.
# The row's period is only the FALLBACK: «раз в сутки» is where a day with nothing running
# starts from, not how often this runs.
#
# THE ORDER IS THE POINT:
#
#   1. **claim** — a finished task holds a march until its reward is taken, so nothing
#      else has room until this is done;
#   2. **open the boxes** — before the refreshing, on the operator's instruction, and it
#      is not only tidiness: the boxes pay out «Секретные приказы», so opening them
#      first makes the refreshing cheaper. Live, 1 200 boxes returned twelve of them;
#   3. **refresh by the price rule** — orders first, diamonds under the one ceiling, each
#      UR sent the instant it falls (`refresh_secret_tasks.md` holds all of that);
#   4. **send whatever there are heroes for**, and say what there were not.
#
# WHY IT COMES BACK. There are more tasks than heroes and a task runs for hours, so one
# visit cannot finish a day: what is left unsent waits for a squad, and what is out will
# want claiming. Both are the same clock, and the run leaves it in `next_run_in`.

# Every knob belongs to the ability it is passed to; a `CALL` hands the caller's variables
# down, so these are the same names `refresh_secret_tasks.md` and `collect_secret_tasks.md`
# declare, and changing one here changes it for the whole day's run.
ARGS keep = 3
ARGS use_diamonds = 1
ARGS diamond_cap = 1200
ARGS mega = 1
ARGS dispatch = 1
# Only UR tasks are ever sent, and the popup is READ to prove it before every confirm
# (#2022). `refresh_secret_tasks.md` holds the whole of the guard.
ARGS only_ur = 1
ARGS boxes = 0
ARGS batch = 100

# 1-2. Claim what has ripened and open the boxes it paid out in.
CALL collect_secret_tasks

# 3-4. Then the price rule, the UR rescues and the sending.
CALL refresh_secret_tasks

# 5. Book the next turn on the GAME's clock, not on the row's period. The nearest running
#    task's finish is the moment the next reward may be claimed AND the moment the next
#    heroes are home — one number for both, plus half a minute so the server has really
#    turned it over. Nothing running: `0`, and the daily anchor stands.
READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local free=tonumber(M.__lw_ref_nextfree) or 0 if free<=0 then return 0 end return free+30 end)() INTO next_run_in
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_run) or 0) INTO running
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_idle) or 0) INTO idle
IF next_run_in > 0
    LOG "the day's secret tasks: {running} out, {idle} still idle — back in {next_run_in} s, when the first of them finishes"
ELSE
    LOG "the day's secret tasks: nothing is out ({idle} idle) — nothing to wait for, the row's own period stands"
