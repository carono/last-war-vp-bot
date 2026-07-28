# Rob every queued secret task — «кража секретки».
#
# For the OTHER robbery — the weekly co-op event «Операция Призрак», which rides
# `ghost.recon.steal` and has its own five-a-day budget — see
# steal_ghost_recon.md. The two look alike and share nothing.
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
# TARGETS COME FROM OUTSIDE THIS RECIPE. `TAP` takes no arguments, so a robbery
# cannot name its victim here — the targets are parked in the game VM first:
#
#     C:\Python312\python.exe tools\steal_secret_task.py --from-scan results\tasks.json --queue-only
#     C:\Python312\python.exe tools\steal_secret_task.py --coords 588,300 --server 534 --queue-only
#
# `--from-scan` reads a capture checkpoint (tools/secret_task_capture.py --json) and
# keeps only tiles that are raidable right now; `--coords` resolves one tile's uuid
# through the same `world.get.detail.new` request a marker tap fires. Run this recipe
# afterwards and it spends the queue, one robbery per press.
#
# THE VICTIM MUST BE IN REACH. A task on a far server is refused by the server with
# «Операция не удалась! Не в том же секторе, что и целевая зона боевых действий!»
# (tips 458632) — confirmed live against server 971 while the client sat on 534. The
# refusal costs nothing but a queue entry: `todayStealNum` does not move, so `xall`
# simply carries on to the next target.
#
# Verified live (task #1099): with three markers in view on server 534, robbing
# uuid 1397117352503547575 took todayStealNum 1 -> 2 and raised the loot window.

# 1. Nothing queued means nothing to do — say so instead of pressing blind.
READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager return #(M.__lw_steal_queue or {}) end)() INTO targets
IF targets == 0
    LOG "No secret task queued — run tools/steal_secret_task.py first."

# 2. Spend the queue. `xall` re-reads min(queued, robberies left today) between
#    presses, so it stops both when the queue runs dry and at the daily cap, and
#    never sends a robbery the client would refuse for budget reasons.
TAP steal_secret_task xall

# 3. Each success raises the loot window (UIDispatchTaskReward) — the same window
#    that offers the victim an emoji. Close it so the next run starts clean.
TAP dismiss_steal_reward
