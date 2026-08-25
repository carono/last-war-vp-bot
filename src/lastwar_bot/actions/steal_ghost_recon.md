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
# TARGETS. `TAP` takes no arguments, but this recipe does — a CALLER may name the
# squads and the recipe parks them itself (#1976, the same shape steal_secret_task.md
# took in #1272):
#
#     run_action("steal_ghost_recon", variables={"queue": "{uuid=1,server=534}"})
#
# With no `queue` it spends whatever is already parked, which is what the tool leaves
# behind:
#
#     C:\Python312\python.exe tools\ghost_recon_steal.py --list
#     C:\Python312\python.exe tools\ghost_recon_steal.py --all --queue-only
#
# The panel does NOT spawn that tool any more. It used to, and the reason it stopped is
# the one written in `CLAUDE.md`: a spawned child costs five seconds before the first
# press, and the whole of what it was doing here was parking a list the panel had
# already chosen (`GhostReconPane.rob_candidates`).
#
# `--all` keeps only what the client itself calls robbable: the squad has
# finished, a loot slot is free, it is somebody else's, I have not robbed it
# before, and its server is inside the event's reachable set
# (`dispatchStealRange`). That verdict is the game's own
# `GetPointStealType(...) == CanSteal`, not a guess of ours.

# The targets, when the caller names them: Lua table bodies, comma separated —
# `{uuid=1,server=534},{uuid=2,server=534}`. Empty means «spend what is parked».
ARGS queue =

# 1. Park what the caller named, and stamp the run's own baseline. `{queue}` is
#    substituted before the script is parsed, so an empty argument leaves an empty table
#    and step 2 says so — it must NOT wipe a queue the tool parked a moment ago.
#    `__lw_ghost_run` is what step 4 judges the run by.
LUA local M=DataCenter.ActGhostreconManager local q={ {queue} } if #q > 0 then M.__lw_ghost_queue=q end M.__lw_ghost_run=tonumber(M.stealTimes) or 0

# 2. Nothing queued (or the event is closed) means nothing to do.
READ_LUA (function() return #(DataCenter.ActGhostreconManager.__lw_ghost_queue or {}) end)() INTO targets
IF targets == 0
    LOG "No ghost-recon squad queued — name them in `queue`, or run tools/ghost_recon_steal.py first."

# 3. Spend the queue. `xall` re-reads min(queued, robberies left today) between
#    presses — and reads 0 outright while the event is closed.
TAP steal_ghost_recon xall

# 4. A success raises the event's loot window; close it so the next run is clean.
TAP dismiss_ghost_recon_reward

# 5. Say what the SERVER did. `stealTimes` is the account's spent count and only the
#    reply moves it, so this is the one honest «it worked» — a `ghost_steal_sent` line
#    above proves a frame left the client and nothing more.
READ_LUA (function() local M=DataCenter.ActGhostreconManager local now=tonumber(M.stealTimes) or 0 local was=tonumber(M.__lw_ghost_run) or now return now-was end)() INTO taken
IF taken > 0
    LOG "ghost_taken — the server confirmed a robbery"
READ_LUA (function() local M=DataCenter.ActGhostreconManager local cfg=M:GetNowSettingCfg() local cap=tonumber(cfg and cfg.stealCount) or 0 local used=tonumber(M.stealTimes) or 0 local left=cap-used if left<0 then left=0 end return left end)() INTO left
IF left == 0
    LOG "ghost_steals_spent — the day's robberies are gone"
