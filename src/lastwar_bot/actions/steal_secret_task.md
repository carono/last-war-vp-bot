# Rob every queued secret task — «кража секретки».
# ru: Обокрасть все секретки из очереди («кража секретки»).
#
# For the OTHER robbery — the weekly co-op event «Операция Призрак», which rides
# `ghost.recon.steal` and has its own five-a-day budget — see steal_ghost_recon.md.
# The two look alike and share nothing.
#
# A finished hero-dispatch task ("секретка") on another player's tile can be robbed
# three times before its loot slots are full, and the account gets five robberies a
# day (`GetDispatchSetting("steal_count")`). The counter resets daily and nothing
# carries over, so an unspent robbery is simply income thrown away — the same reason
# occupation_skills.md exists.
#
# One press = one `hero.dispatch.steal {uuid, targetServer}`, the whole network side
# of the in-game «украсть» button (WorldPointBtnType.DispatchTaskSteal). It is
# headless: no marker tap, no UIWorldPoint popup, no camera move, no window open.
# The engine calls live in tools/lib/game_buttons.py; the API is written up in
# docs/research/secret-task-steal.md.
#
# THIS IS A RACE, AND THE RECIPE IS SHAPED BY IT (#1272). A raidable star is taken in
# the first instant it exists — «счёт идёт на доли секунды, много желающих уже
# кликают» — so a target is not pressed once and dropped. It is pressed AGAIN AND
# AGAIN, as fast as the channel allows (~7 presses a second; one round trip through
# the warm daemon is 80-135 ms), starting a couple of seconds BEFORE the tile matures
# and stopping the moment the server says yes.
#
# PRESSING EARLY IS FREE. The server answers «ещё не готово», the daily counter does
# not move and nothing is spent — the counter is the SERVER's number and only reaches
# the client on the success branch of the reply (`DispatchStealMessage:HandleMessage`).
# So the only honest «it worked» is that counter moving, and that is exactly what the
# button's own gate watches (`secret_task_taken`): a `steal_sent` line proves a frame
# left the client and nothing more.
#
# TARGETS. `TAP` takes no arguments, so the queue is parked in the game VM first —
# but a CALLER may name them, which is what the panel's «Автолут ★» does:
#
#     run_action("steal_secret_task", variables={"queue": "{uuid=…,server=…}"})
#
# With no `queue` the recipe spends whatever is already parked, which is what the
# tool leaves behind:
#
#     C:\Python312\python.exe tools\steal_secret_task.py --from-scan results\tasks.json --queue-only
#     C:\Python312\python.exe tools\steal_secret_task.py --coords 588,300 --server 534 --queue-only
#
# `--from-scan` reads a capture checkpoint (tools/secret_task_capture.py --json) and
# keeps only tiles that are raidable right now; `--coords` resolves one tile's uuid
# through the same `world.get.detail.new` request a marker tap fires. Those two need a
# map scan and a round trip to resolve a coordinate, which is why the tool still
# exists — and why it is NOT in the panel's hot path any more: spawning it costs five
# seconds, and five seconds is the whole race.
#
# THE VICTIM MUST BE IN REACH. A task on a far server is refused by the server with
# «Операция не удалась! Не в том же секторе, что и целевая зона боевых действий!»
# (tips 458632) — confirmed live against server 971 while the client sat on 534. The
# refusal costs nothing but time: `todayStealNum` does not move, so the spam simply
# runs out its cap on that tile and the recipe moves to the next one.
#
# Verified live (task #1099): with three markers in view on server 534, robbing
# uuid 1397117352503547575 took todayStealNum 1 -> 2 and raised the loot window.

# The targets, when the caller names them: Lua table bodies, comma separated —
# `{uuid=1,server=534},{uuid=2,server=534}`. Empty means «spend what is parked».
ARGS queue =

# 1. Park what the caller named, and stamp the run's own baseline. `{queue}` is
#    substituted before the script is parsed, so an empty argument leaves an empty table
#    and step 2 says so. `__lw_steal_run` is what step 5 judges the whole run by; the
#    per-target `__lw_steal_mark` beside it is what the press loop stops on.
LUA local M=DataCenter.ActDispatchTaskDataManager local q={ {queue} } if #q > 0 then M.__lw_steal_queue=q M.__lw_steal_mark=tonumber(M:GetTodayStealNum()) or 0 end M.__lw_steal_run=tonumber(M:GetTodayStealNum()) or 0

# 2. Nothing queued means nothing to do — say so instead of pressing blind.
READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager return #(M.__lw_steal_queue or {}) end)() INTO targets
IF targets == 0
    LOG "No secret task queued — name them in `queue`, or run tools/steal_secret_task.py first."

# 3. Spend the queue, one target at a time. `xall` is the SPAM: it re-reads the
#    button's gate and presses again while the server has not confirmed this target,
#    stopping on the confirmation, on a spent daily budget, or on the button's own cap
#    (~9 seconds of pressing). Then the head is dropped — taken or hopeless, either way
#    the next one is what matters — and the mark re-armed on whatever is now in front.
WHILE targets > 0 LIMIT 6
    TAP steal_secret_task xall
    TAP drop_steal_target
    READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager return #(M.__lw_steal_queue or {}) end)() INTO targets

# 4. Each success raises the loot window (UIDispatchTaskReward) — the same window
#    that offers the victim an emoji. Close it so the next run starts clean.
TAP dismiss_steal_reward

# 5. Say what the SERVER did, in words a caller can steer by. `steal_taken` and
#    `steals_spent` are read back by the panel's «Автолут ★»
#    (panel/tabs/secret_tasks/autoloot.py) — reword them there in the same breath or the
#    standing order stops noticing its own successes and stops pausing on a spent day.
#
#    The counter is the whole test: a `steal_sent` line above proves a frame left the
#    client, and only this proves the server took it.
READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local now=tonumber(M:GetTodayStealNum()) or 0 local was=tonumber(M.__lw_steal_run) or now return now-was end)() INTO taken
IF taken > 0
    LOG "steal_taken — the server confirmed a robbery"
READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local cap=tonumber(M:GetDispatchSetting('steal_count')) or 0 local used=tonumber(M:GetTodayStealNum()) or 0 local left=cap-used if left<0 then left=0 end return left end)() INTO left
IF left == 0
    LOG "steals_spent — the day's robberies are gone"
