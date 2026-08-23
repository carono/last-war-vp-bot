# Read the secret command post: how many of the day's own tasks are idle, and what a refresh would cost.
# ru: Чтение секретного командного пункта: сколько своих заданий свободно и чем платить за обновление.
#
# The reading half of `refresh_secret_tasks.md`, and nothing else: it opens no window,
# presses nothing and spends nothing. One walk over the player's own tasks plus the two
# purses that pay for a refresh — the «Секретные приказы» in the bag and the diamonds —
# so a panel can draw the page without asking the game anything itself.
#
# Quality is the config row's `color`; 5 is UR and anything above it counts as UR too.
# Only the IDLE tasks are counted: one with a squad already out cannot be re-rolled, is
# skipped by the mega refresh and has nothing for the batch dispatch to send.

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
