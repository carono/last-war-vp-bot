# Refresh the day's own secret tasks by the price rule, then send every squad at once.
# ru: Обновление своих секретных заданий по правилу цен и пакетная отправка отрядов.
#
# THE PLAYER'S OWN TASKS, not anybody else's. The other three abilities on this tab spend
# daily counters the server gives away — `steal_secret_task.md` robs a stranger's tile,
# `assist_secret_task.md` helps an alliancemate, `help_ally.md` answers building requests.
# This one spends a CURRENCY, and that is what every gate below is about.
#
# THE RULE, in the words it was given in: spend tickets while there are tickets; when
# they run out spend diamonds; and take the mega refresh when the tickets cover it, or
# cover it all but a small top-up in diamonds — otherwise go on with ordinary refreshes
# first and let the diamonds come after.
#
# THE PRICES WERE MEASURED, NOT ASSUMED (#1903), and two of the three were not what they
# were thought to be:
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
# a squad already out is skipped by the mega refresh, has nothing for the batch dispatch
# to send, and cannot be re-rolled. Quality is the config row's `color` — 5 is UR, and
# anything above it is treated as UR too, because a rarity nobody has seen yet must not
# read as «not UR» and be thrown away. The `cfgId` digits say nothing about either.
#
# IT PRESSES THE GAME'S OWN BUTTONS. `hero.dispatch.refresh` carries a `costType` whose
# values are written down nowhere we can read, so building the frame by hand is a guess
# between «spend a ticket» and «spend diamonds» — a guess the player pays for. The
# window's button already knows which the player can afford, and the batch dispatch's
# popup picks a squad for every task by itself, which is the one part a hand-built frame
# would have to invent.
#
# THE CAMERA MOVES AT THE END. The game's own handler for the batch dispatch closes the
# popup and takes the world view to the tasks' point. That is the button, not a choice
# this makes — pass `dispatch = 0` when the map must be left alone.

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

# Take the mega refresh at all (it is the one press that improves every idle task at
# once), and send the squads afterwards. Either may be turned off on its own.
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

# 4. Ordinary refreshes, tickets first and diamonds only inside the budget. `xall`
#    re-reads the rule between presses, so this stops the instant the idle non-UR tasks
#    reach the threshold, the tickets run out with no diamonds allowed, or the budget
#    will not cover one more.
TAP refresh_secret_task xall

# 5. Say where that got to, whether or not anything was pressed. A standing order that
#    reports nothing is indistinguishable from a broken one.
TAP scan_secret_post
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_nonur) or 0) INTO nonur
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_tickets) or 0) INTO tickets
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_goldleft) or 0) INTO gold_left
LOG "after refreshing: {nonur} idle non-UR left, {tickets} ticket(s), {gold_left} diamond(s) of the budget"

# 6. The mega refresh — the one press that lifts every idle non-UR task to UR at once.
#    Its price is only ever drawn, so the dialog is opened to be READ; what the rule
#    decides afterwards is whether it is confirmed or closed unpressed.
IF mega == 1
    IF nonur > 0
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

# 7. Send every idle task's squad in one press. The popup fills the squads itself; the
#    confirm is the `hero.dispatch.batch.start`, and the camera follows it to the point.
IF dispatch == 1
    TAP scan_secret_post
    READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_idle) or 0) INTO idle
    READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_ing) or 0) INTO marching
    READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_march) or 0) INTO marches
    IF idle > 0
        LOG "sending {idle} squad(s); {marching} of {marches} marches already out"
        TAP open_batch_dispatch
        TAP confirm_batch_dispatch
    ELSE
        LOG "nothing idle to send — {marching} of {marches} marches out"

# 8. One last look, so whoever pressed this — the window or the phone — is told the
#    state it LEFT rather than the one it started from. The panel draws its page off
#    these, which is how a press made from a phone still moves the numbers in the window.
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
LOG "secret post: idle={idle} non-UR={nonur} UR={ur} out={running} tickets={tickets} diamonds={diamonds} price={price} marches={marching}/{marches}"

# 9. Leave the screen as it was found.
TAP close_secret_post
