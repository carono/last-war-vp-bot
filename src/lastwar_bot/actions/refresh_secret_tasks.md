# Refresh the day's own secret tasks by the price rule, sending each UR the moment it falls.
# ru: Обновление своих секретных заданий по правилу цен, с отправкой каждого выпавшего UR сразу.
#
# THE PLAYER'S OWN TASKS, not anybody else's. The other three abilities on this tab spend
# daily counters the server gives away — `steal_secret_task.md` robs a stranger's tile,
# `assist_secret_task.md` helps an alliancemate, `help_ally.md` answers building requests.
# This one spends a CURRENCY, and that is what every gate below is about.
#
# THE ORDER IS «SEND, THEN REFRESH», AND THAT CORRECTION COST A LIVE RUN (#1903). The
# first version refreshed to the end and sent everything afterwards. It refreshed three
# times, a UR fell out on the third — and the next seven presses did nothing at all,
# because A REFRESH RE-ROLLS EVERY TASK NOBODY HAS SENT. The thing that was paid for is
# exactly the thing the next refresh throws away.
#
# The game says the same in its own way, which is how the stall was diagnosed: while an
# idle UR is standing there the window HIDES «Обновить» (`refreshBtn` goes inactive and
# the «мега» pair takes its place). It is not a limit and not a cooldown — it is the
# client refusing to let a win be re-rolled. Send the UR and the button comes back.
#
# So each round is: send whatever the dispatch popup has selected, then refresh once, then
# look again. If a UR could NOT be sent — no heroes free, no march slot — the round STOPS
# rather than refreshing past it, and says why. Losing a UR is worse than losing a turn.
#
# HEROES RUN OUT, AND THAT IS ORDINARY. There are more tasks than there are heroes to man
# them, and the ones already out come back at a time the client knows to the millisecond.
# So a run that could not send everything does not wait and does not forget: it leaves the
# seconds to the nearest returning squad in `next_run_in`, and the schedule books this
# errand's next turn for exactly then (docs/dsl.md, the convention `tavern_free_pull.md`
# uses).
#
# THE PRICES WERE MEASURED, NOT ASSUMED, and two of the three were not what they were
# thought to be:
#   * an ordinary refresh costs ONE «Секретный приказ» — the item
#     `GetDispatchSetting('refresh_item')` names. The window's own button says so:
#     `refreshBtn` carries `<how many you have>/<what it costs>`. Only when the items run
#     out does the same press ask for DIAMONDS, at `GetTaskRefreshSetting()` each — which
#     is where the number 100 comes from.
#   * the MEGA refresh costs a handful of the same item — twenty against five non-UR
#     tasks on the reading this was written from, so about four apiece — and no getter
#     answers it. It is drawn in the dialog the button raises, so this recipe OPENS the
#     dialog, READS the price, and closes it unpressed when the rule says no.
#   * `GetTaskSuperRefreshSetting()` is not a price at all. It answers the same number as
#     `refresh_item` — an item id — and reading it as diamonds is how a plan ends up
#     spending 1 520 002 of them.
#
# WHICH TASKS COUNT. Only the IDLE ones («считать только свободные задания»): a task with
# a squad already out is skipped by the mega refresh, cannot be re-rolled, and has nothing
# for the dispatch to send. Quality is the config row's `color` — 5 is UR, 4 and 3 are
# below it, and anything ABOVE 5 counts as UR too, because a rarity nobody has seen yet
# must not read as «not UR» and be thrown away. The `cfgId` digits say nothing about it.
#
# IT PRESSES THE GAME'S OWN BUTTONS. `hero.dispatch.refresh` carries a `costType` whose
# values are written down nowhere we can read, so building the frame by hand is a guess
# between «spend a ticket» and «spend diamonds» — a guess the player pays for. And the
# dispatch popup arrives with a squad already chosen for every task AND its own «только
# UR» toggle already on, so «send the one the refresh just won» is the game's own answer
# rather than a hero-picker written here.
#
# THE CAMERA MOVES ON A SEND. The game's own handler closes the popup and takes the world
# view to the tasks' point. That is the button, not a choice this makes.

# The number of idle non-UR tasks this is content to stop at. Above it, ordinary
# refreshes; at or below it, the mega refresh is considered.
ARGS keep = 3

# May diamonds be spent at all? 0 keeps the whole run inside the tickets: when they run
# out it stops and says so.
ARGS use_diamonds = 1

# The most diamonds ONE RUN may spend — on ordinary refreshes and on the mega's top-up
# together. Measured off the purse itself, so a dialog that was raised and cancelled
# costs nothing.
ARGS diamond_budget = 1200

# Take the mega refresh at all (the one press that lifts every idle non-UR task to UR),
# and, at the very end, send the tasks the rule was content to keep as well. Either may
# be turned off on its own; the UR rescue above is not optional, because it is what makes
# the refreshing worth paying for.
ARGS mega = 1
ARGS dispatch = 1

# 1. Park the rule where the presses can read it — `TAP` takes no arguments — and stamp
#    the purse the budget is measured from.
LUA local M=DataCenter.ActDispatchTaskDataManager M.__lw_ref_keep={keep} M.__lw_ref_gold={use_diamonds} M.__lw_ref_budget={diamond_budget} M.__lw_ref_mega_cost=-1 M.__lw_ref_mega_tasks=0 local g=0 pcall(function() g=tonumber(LuaEntry.Player.gold) or 0 end) M.__lw_ref_gold0=g

# 2. Open the command post. Every press below is a press inside this window.
TAP open_secret_post

# 3. One walk, so every question underneath is answered about the same moment.
TAP scan_secret_post
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_nonur) or 0) INTO nonur
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_ur) or 0) INTO ur
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_run) or 0) INTO running
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_tickets) or 0) INTO tickets
LOG "secret post: {nonur} idle non-UR, {ur} idle UR, {running} out on errands, {tickets} ticket(s) in hand"

# 4. The cycle: rescue, then refresh, then look again. `go` is re-read at the bottom of
#    every round, so the loop ends the moment the rule is satisfied, the purses are empty
#    or a UR is stuck for want of a squad.
READ_LUA (function() local function _num(v) if v==nil then return 0 end local ok,n=pcall(function() return v+0 end) if ok and n~=nil then return n end ok,n=pcall(function() return tonumber(v) end) if ok and n~=nil then return n end return 0 end local M=DataCenter.ActDispatchTaskDataManager local idle,nonur,ur,run=0,0,0,0 local ok,tasks=pcall(function() return M:GetAllSingleTasks() end) if ok and type(tasks)=='table' then for _,v in pairs(tasks) do local col=0 pcall(function() col=_num(v.cfg:getValue('color')) end) local ct=_num(v.completionTime) if ct>0 then run=run+1 else idle=idle+1 if col>=5 then ur=ur+1 else nonur=nonur+1 end end end end local item=(function() local ok,v=pcall(function() return DataCenter.ActDispatchTaskDataManager:GetDispatchSetting('refresh_item') end) local n=0 if ok and v~=nil then pcall(function() n=v+0 end) end return n end)() local tickets=0 pcall(function() for _,s in pairs(DataCenter.ItemData.ItemInfos or {}) do if _num(s.itemId)==item then tickets=tickets+_num(s.count) end end end) local gold=0 pcall(function() gold=_num(LuaEntry.Player.gold) end) local price=0 pcall(function() price=_num(M:GetTaskRefreshSetting()) end) local superopen=0 pcall(function() if M:CheckSuperRefreshOpen() then superopen=1 end end) local free=0 pcall(function() free=_num(M:GetSingleTaskNormalCount()) end) local ing=0 pcall(function() ing=_num(M:GetSingleTaskIngCount()) end) local maxm=0 pcall(function() maxm=math.floor(_num(M:GetMaxMarch())) end) local now=0 pcall(function() now=math.floor(_num(UITimeManager:GetInstance():GetServerSeconds())) end) local nextfree=0 if ok and type(tasks)=='table' and now>0 then for _,v in pairs(tasks) do local ct=math.floor(_num(v.completionTime)/1000) if ct>now then local d=ct-now if nextfree==0 or d<nextfree then nextfree=d end end end end local budget=tonumber(M.__lw_ref_budget) or 0 local gold0=tonumber(M.__lw_ref_gold0) or gold local spent=gold0-gold if spent<0 then spent=0 end local goldleft=budget-spent if goldleft<0 then goldleft=0 end if (tonumber(M.__lw_ref_gold) or 0)==0 then goldleft=0 end local keep=tonumber(M.__lw_ref_keep) or 0 if ur>0 then return 1 end if nonur<=keep then return 0 end if tickets>0 then return 1 end if price>0 and goldleft>=price then return 1 end return 0 end)() INTO go
WHILE go == 1 LIMIT 24
    TAP open_secret_post
    TAP scan_secret_post
    READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_ur) or 0) INTO ur
    # 4a. Anything the game has selected goes out FIRST — with «только UR» on, that is
    #     precisely the task the last refresh won.
    IF ur > 0
        TAP open_batch_dispatch
        TAP read_batch_dispatch
        READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_picked) or 0) INTO picked
        IF picked > 0
            LOG "sending {picked} UR task(s) before touching the refresh"
            TAP confirm_batch_dispatch
        ELSE
            LOG "a UR is idle and the game selected nothing to send it with — no free hero or no march slot"
            TAP cancel_batch_dispatch
    # 4b. …and only then the refresh, and only if the rescue actually worked.
    TAP open_secret_post
    TAP scan_secret_post
    READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_ur) or 0) INTO ur
    IF ur > 0
        LOG "stopping: {ur} UR task(s) are still standing idle, and a refresh would throw them away"
        READ_LUA 0 INTO go
    ELSE
        TAP refresh_secret_task
        READ_LUA (function() local function _num(v) if v==nil then return 0 end local ok,n=pcall(function() return v+0 end) if ok and n~=nil then return n end ok,n=pcall(function() return tonumber(v) end) if ok and n~=nil then return n end return 0 end local M=DataCenter.ActDispatchTaskDataManager local idle,nonur,ur,run=0,0,0,0 local ok,tasks=pcall(function() return M:GetAllSingleTasks() end) if ok and type(tasks)=='table' then for _,v in pairs(tasks) do local col=0 pcall(function() col=_num(v.cfg:getValue('color')) end) local ct=_num(v.completionTime) if ct>0 then run=run+1 else idle=idle+1 if col>=5 then ur=ur+1 else nonur=nonur+1 end end end end local item=(function() local ok,v=pcall(function() return DataCenter.ActDispatchTaskDataManager:GetDispatchSetting('refresh_item') end) local n=0 if ok and v~=nil then pcall(function() n=v+0 end) end return n end)() local tickets=0 pcall(function() for _,s in pairs(DataCenter.ItemData.ItemInfos or {}) do if _num(s.itemId)==item then tickets=tickets+_num(s.count) end end end) local gold=0 pcall(function() gold=_num(LuaEntry.Player.gold) end) local price=0 pcall(function() price=_num(M:GetTaskRefreshSetting()) end) local superopen=0 pcall(function() if M:CheckSuperRefreshOpen() then superopen=1 end end) local free=0 pcall(function() free=_num(M:GetSingleTaskNormalCount()) end) local ing=0 pcall(function() ing=_num(M:GetSingleTaskIngCount()) end) local maxm=0 pcall(function() maxm=math.floor(_num(M:GetMaxMarch())) end) local now=0 pcall(function() now=math.floor(_num(UITimeManager:GetInstance():GetServerSeconds())) end) local nextfree=0 if ok and type(tasks)=='table' and now>0 then for _,v in pairs(tasks) do local ct=math.floor(_num(v.completionTime)/1000) if ct>now then local d=ct-now if nextfree==0 or d<nextfree then nextfree=d end end end end local budget=tonumber(M.__lw_ref_budget) or 0 local gold0=tonumber(M.__lw_ref_gold0) or gold local spent=gold0-gold if spent<0 then spent=0 end local goldleft=budget-spent if goldleft<0 then goldleft=0 end if (tonumber(M.__lw_ref_gold) or 0)==0 then goldleft=0 end local keep=tonumber(M.__lw_ref_keep) or 0 if ur>0 then return 1 end if nonur<=keep then return 0 end if tickets>0 then return 1 end if price>0 and goldleft>=price then return 1 end return 0 end)() INTO go

# 5. Say where that got to, whether or not anything was pressed.
TAP scan_secret_post
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_nonur) or 0) INTO nonur
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_ur) or 0) INTO ur
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_tickets) or 0) INTO tickets
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_goldleft) or 0) INTO gold_left
LOG "after refreshing: {nonur} idle non-UR left, {ur} idle UR, {tickets} ticket(s), {gold_left} diamond(s) of the budget"

# 6. The mega refresh — the one press that lifts every idle non-UR task to UR at once.
#    Its price is only ever drawn, so the dialog is opened to be READ; the rule decides
#    afterwards whether it is confirmed or closed unpressed. Never while a UR is standing
#    idle: what it produces would be waiting for a squad beside one that already is.
IF mega == 1
    IF ur == 0
        IF nonur > 0
            TAP open_secret_post
            TAP open_mega_refresh
            TAP read_mega_refresh_cost
            READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_mega_cost) or -1) INTO mega_cost
            READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_mega_tasks) or 0) INTO mega_tasks
            READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_mega_ok) or 0) INTO mega_ok
            READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_mega_gold) or 0) INTO mega_gold
            IF mega_ok == 1
                LOG "mega refresh: {mega_cost} ticket(s) for {mega_tasks} task(s), {mega_gold} diamond(s) on top — taking it"
                TAP confirm_mega_refresh
            ELSE
                LOG "mega refresh: {mega_cost} ticket(s) for {mega_tasks} task(s) needs {mega_gold} diamond(s) — outside the rule, left alone"
                TAP cancel_mega_refresh

# 7. Send what is standing: the URs the mega has just made, and — if the person asked for
#    it — the tasks the rule was content to keep as well. The popup fills every squad
#    itself; its confirm is the `hero.dispatch.batch.start`.
TAP open_secret_post
TAP scan_secret_post
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_idle) or 0) INTO idle
IF idle > 0
    TAP open_batch_dispatch
    IF dispatch == 1
        TAP select_all_batch_dispatch
    TAP read_batch_dispatch
    READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_rows) or 0) INTO rows
    READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_picked) or 0) INTO picked
    IF picked > 0
        LOG "sending {picked} of the {rows} idle task(s)"
        TAP confirm_batch_dispatch
    ELSE
        LOG "nothing of the {rows} idle task(s) can be sent — no free hero or no march slot"
        TAP cancel_batch_dispatch

# 8. One last look, so whoever pressed this — the window or the phone — is told the state
#    it LEFT rather than the one it started from. The panel draws its page off these,
#    which is how a press made from a phone still moves the numbers in the window.
TAP scan_secret_post
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_idle) or 0) INTO idle
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_nonur) or 0) INTO nonur
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_ur) or 0) INTO ur
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_run) or 0) INTO running
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_tickets) or 0) INTO tickets
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_goldnow) or 0) INTO diamonds
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_price) or 0) INTO price
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_ing) or 0) INTO marching
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_march) or 0) INTO marches
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_nextfree) or 0) INTO next_free
LOG "secret post: idle={idle} non-UR={nonur} UR={ur} out={running} tickets={tickets} diamonds={diamonds} price={price} marches={marching}/{marches} next-free={next_free}s"

# 9. What is left unsent is not abandoned. The nearest squad's own finish time — which the
#    client knows to the millisecond — becomes this errand's next turn, plus a minute so
#    the hero is really back. Nothing left over, or nothing out: `0`, and the timer's own
#    period stands.
READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local idle=tonumber(M.__lw_ref_idle) or 0 if idle<=0 then return 0 end local free=tonumber(M.__lw_ref_nextfree) or 0 if free<=0 then return 0 end return free+60 end)() INTO next_run_in
IF idle > 0
    LOG "{idle} task(s) still waiting for a squad — coming back in {next_run_in} s, when the nearest one is home"

# 10. Leave the screen as it was found.
TAP close_secret_post
