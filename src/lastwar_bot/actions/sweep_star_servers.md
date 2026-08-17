# Walk a few warzones having their star-secret-task day, so the ★ list keeps filling.
# ru: Обойти несколько зон с днём звёздных секреток, чтобы список ★ пополнялся.
#
# THIS RECIPE STEALS NOTHING. It fills the list — «Автолут ★» robs out of it, and it robs
# each tile in the instant the server calls it ripe. That division is the whole point,
# and it comes from a measurement (#1479): a lap of a fresh warzone brought **91 star
# tiles of which 86 were still maturing and 0-5 were raidable that second**. So one lap
# of one warzone is nearly worthless, and what pays is coming back through the day with
# a full list already standing.
#
# WHAT ONE RUN DOES, in order:
#
#   1. asks the client how many of the day's five robberies are left, and STOPS when
#      there are none — a lap that cannot end in a robbery is a lap for nothing;
#   2. puts the map up, because a lap from inside the base collects no tiles at all and
#      says so nowhere (#1335, `scan_map.md`);
#   3. picks 5-10 warzones (`PICK_STAR_SERVERS`): having their star day today, standing
#      in a season phase this account may rob in (#1471), never home (#1188), and not one
#      of the ones today's earlier laps already walked (#1479);
#   4. walks each of them once at the secret-task height, through `sweep_one_star_server`.
#
# WHAT IT NEEDS RUNNING BESIDE IT. A lap produces traffic and decodes nothing: the ★
# page's own sniffer is what turns it into rows. With the monitor off this run is a
# camera walk that fills nothing, which is why the panel refuses to start the errand
# while its capture is down rather than reporting a cheerful success
# (`panel/tabs/secret_tasks/star_round.py`).
#
# WHY IT IS NOT SET TO RUN OFTEN. Four hours is the operator's period, and it is the
# ripening that decides it: a task found at the start of a lap is raidable hours later,
# so the useful cadence is «be back before the ones I saw mature», not «be back at once».

# How many warzones one lap walks. Held between 5 and 10 by the model
# (`tools/lib/star_round.py`) whatever is written here, so a hand-edited timer cannot ask
# for one warzone or for two hundred.
ARGS count = 6

# 1. THE GATE: the day's robberies. `steal_count` is the account's allowance and
#    `GetTodayStealNum` is what the SERVER says has been spent of it — never a tally the
#    panel keeps, and never the PC's idea of what day it is: the counter resets on the
#    game's own boundary and the number below is that boundary's answer.
READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local cap=tonumber(M:GetDispatchSetting('steal_count')) or 0 local used=tonumber(M:GetTodayStealNum()) or 0 local left=cap-used if left<0 then left=0 end return left end)() INTO steals_left
READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager return tonumber(M:GetTodayStealNum()) or 0 end)() INTO steals_done
LOG "steal_budget — {steals_done} robbed today, {steals_left} left of the day's allowance"
IF steals_left == 0
    STOP "the day's robberies are already spent — nothing a lap could feed"

# 2. The map, or the lap collects nothing. Same switch `scan_map.md` makes, for the same
#    reason: a lap ENDS on the world anyway, so putting it up is only earlier and honest.
IF scene != world
    LOG "Putting the map up first — a lap from the base fetches no tiles."
    GAME WORLD
    WAIT scene == world WITHIN 30s

# 3. WHICH WARZONES. Nothing is asked of the game here but «which warzone is home»: the
#    slice is the season plan already on disk and the star day is this profile's own book
#    of observations (#1467).
PICK_STAR_SERVERS COUNT {count}
LOG "star_round — home {STAR_HOME}, {STAR_REACH} warzone(s) in reach, {STAR_POOL} having their star day, {STAR_WALKED} walked earlier today, this lap: {STAR_SERVERS}"
IF STAR_PICKED == 0
    STOP "no warzone in reach is having its star day today — nothing to walk"

# 4. …and walk them. One warzone per `CALL`, because the number travels as `{STAR_SERVER}`
#    and a `{name}` is filled when the sub-recipe is parsed — which is at the CALL, once
#    per lap of this loop. LIMIT is the model's own ceiling, so a queue can never outrun it.
WHILE STAR_LEFT > 0 LIMIT 10
    NEXT_STAR_SERVER
    CALL sweep_one_star_server

LOG "star_round_done — {STAR_PICKED} warzone(s) walked ({STAR_CHOSEN}), {steals_done} robbed today, {steals_left} still to spend"
