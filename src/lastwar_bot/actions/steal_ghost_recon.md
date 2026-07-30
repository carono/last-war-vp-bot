# Rob the queued ghost-recon squads — «Операция Призрак».
# ru: Обокрасть отряды «Операции Призрак», стоящие в очереди.
#
# NOT the same robbery as steal_secret_task.md. That one takes a hero dispatch
# («секретка») off a player's tile with `hero.dispatch.steal`; this one takes the
# weekly co-op event's squads with `ghost.recon.steal`. Different commands,
# different five-a-day budgets, different queues — so the two recipes never share
# a target. See docs/research/ghost-recon-steal.md.
#
# One press = one `ghost.recon.steal {uuid, ownerServer}`, the whole network side
# of the in-game «украсть» button on a ghost-recon tile
# (WorldPointBtnType.GhostreconTaskSteal). Headless: no tile tap, no popup, no
# march, no window open.
#
# THE EVENT RUNS ONE DAY A WEEK. Outside it `IsOpenDay()` is false, the client
# knows no squads at all, and every gate here reads zero — so this recipe is a
# deliberate no-op on the other six days rather than an error.
#
# TARGETS COME FROM OUTSIDE. `TAP` takes no arguments, so park them first:
#
#     C:\Python312\python.exe tools\ghost_recon_steal.py --list
#     C:\Python312\python.exe tools\ghost_recon_steal.py --all --queue-only
#
# `--all` keeps only what the client itself calls robbable: the squad has
# finished, a loot slot is free, it is somebody else's, I have not robbed it
# before, and its server is inside the event's reachable set
# (`dispatchStealRange`). That verdict is the game's own
# `GetPointStealType(...) == CanSteal`, not a guess of ours.

# 1. Nothing queued (or the event is closed) means nothing to do.
READ_LUA (function() return #(DataCenter.ActGhostreconManager.__lw_ghost_queue or {}) end)() INTO targets
IF targets == 0
    LOG "No ghost-recon squad queued — run tools/ghost_recon_steal.py first."

# 2. Spend the queue. `xall` re-reads min(queued, robberies left today) between
#    presses — and reads 0 outright while the event is closed.
TAP steal_ghost_recon xall

# 3. A success raises the event's loot window; close it so the next run is clean.
TAP dismiss_ghost_recon_reward
