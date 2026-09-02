# Dig hidden treasures until the week's compasses are earned, then take what they unlocked.
# ru: Копать «Скрытые Сокровища» до недельной цели по компасам и забрать открытые награды.
#
#   run dig_hidden_treasures                       -- the game's own goal, its own pace
#   run dig_hidden_treasures {"cap": 5}            -- at most five digs this run
#   run dig_hidden_treasures {"goal": 3000}        -- stop at a goal of one's own
#
# WHAT THE ABILITY IS. «Скрытые Сокровища» (the game's `Treasure_map_S3`) is the tab
# beside the explorer chests: a dig of a treasure map pays a random handful of COMPASSES,
# and the week's total unlocks ten reward steps — 300, 600, 1000, 1500, 2000, 2600, 3300,
# 4000, 5000 and the last one at 6000, which is the week's whole point. A dig spends one
# of each of the seven map fragments, so «how many digs are in hand» is the smallest of
# the seven counts and nothing else.
#
# THE PAY IS RANDOM AND MEASURED, not guessed: the event's own reward table pays
# 150/180/240 six times in ten, 350/450/600 three, and 600/700/900 the last one — an
# average near 320, which is why the goal is about twenty digs. `pay` is that average and
# it is what the plan divides by; lower it and the run digs more than it needs, raise it
# and it stops short and finishes on the next run.
#
# WHY THIS IS PLANNED ONCE RATHER THAN LOOPED ON THE SCORE. The compasses a dig pays do
# NOT reach the client's own count while it is running — measured on 2026-09-02: three
# digs, the seven fragments decremented on the wire the same second, and the compass count
# read 0 for six seconds after each of them, then 750 the moment the client was restarted.
# A loop that waited for the score to reach the goal would therefore dig for ever. So the
# run works out ONCE how many digs the distance is worth, parks that number, and counts it
# down; the score catches up between sessions and the next run plans off the true one.
#
# …AND THE LAG HAD ONE MORE BITE IN IT, which cost a whole goal's worth of fragments before
# it was found: a SECOND run in the same session plans off the same frozen count and digs
# the whole distance again. So the plan puts a floor under the score — the highest reward
# step the server says has been COLLECTED. A collected step is the server's own word that
# its target was reached, and it arrives fresh with the board while the compass count does
# not. Measured on 2026-09-02: 17 digs took every one of the ten steps and the count still
# read 750; the floor reads that as 6000 and the next run digs nothing.
#
# THE REWARDS ARE TAKEN AT THE END, ALWAYS — even by a run that dug nothing. A step that
# has been earned and not collected is a reward standing on the board, and one send takes
# every step the week has already reached; measured live, claiming at 750 compasses turned
# both the 300 and the 600 step to «taken» and left the score exactly where it was, so the
# steps are not paid for out of the count.
#
# The protocol, the measurements and what is still unproven: `docs/research/hidden-treasures.md`.

# The week's goal. 0 — the default — means «whatever the game says», which is the board's
# own cap; a smaller number stops earlier, a larger one is ignored (the cap is the cap).
ARGS goal = 0

# The most digs this ONE run may make. 0 is «as many as the plan asks for».
ARGS cap = 0

# What one dig is worth on average, in compasses. It decides how many digs the distance to
# the goal is planned as, and nothing else.
ARGS pay = 320

# What this run may spend, parked where the presses can read it — a `TAP` takes no
# arguments of its own.
LUA DataCenter.__lw_hidden_goal = {goal} DataCenter.__lw_hidden_cap = {cap} DataCenter.__lw_hidden_pay = {pay}

# The board first: the tier flags are the server's answer, and a run that claimed on a
# stale one would be asking for a step somebody has already taken.
TAP ask_hidden_treasures
TAP read_hidden_treasures
READ_LUA (DataCenter.__lw_hidden_board or 'nothing has been read') INTO board
LOG "hidden treasures before: {board}"

# How many digs this run may make, decided once off the reading above.
TAP plan_hidden_treasures
READ_LUA (math.floor(tonumber((DataCenter.__lw_hidden or {}).plan) or 0)) INTO plan
READ_LUA tostring((DataCenter.__lw_hidden or {}).why or '') INTO why

IF plan == 0
    LOG "nothing to dig — {why}: goal-reached is the week already earned, no-fragments is an empty bag of map pieces, week-over is the event closed. The rewards already earned are taken anyway."
    TAP claim_hidden_treasures
    STOP

LOG "digging {plan} treasure(s) this run"

# The whole plan, one press each, counted down inside the game. A press past the plan
# does nothing and says so; the fragments falling are what proves each one left.
TAP dig_hidden_treasure xall

# EVERY STEP THE WEEK HAS EARNED, whatever this run dug. One send takes the lot and
# spends none of the score.
TAP claim_hidden_treasures

TAP ask_hidden_treasures
TAP read_hidden_treasures
READ_LUA (DataCenter.__lw_hidden_board or 'nothing has been read') INTO board
READ_LUA (math.floor(tonumber((DataCenter.__lw_hidden or {}).done) or 0)) INTO dug
LOG "hidden treasures after: dug={dug} · {board} — the score does not move until the client is restarted, so an unchanged score= here is the reading lagging and not a dig that paid nothing"
