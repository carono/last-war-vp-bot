# Attack the «Кодовое имя» boss once, with a squad standing in the base.
# ru: Одна атака по боссу события «Кодовое имя» отрядом, стоящим в базе.
#
# The event puts one boss on the world map and asks for THREE attacks on it; attempts
# themselves are not rationed («кол-во попыток в день не ограничено» — the game's own
# rules), and only the biggest single hit counts for the daily ranking. This recipe is
# ONE attack: run it three times for the day's credit, or as often as there is a squad
# free for a better hit.
#
# It takes no arguments. «A free squad» is not a choice the person should have to make
# three times a day: the run finds the first squad standing in the base and sends that
# one. A squad already marching, gathering, standing in a rally or wiped cannot be sent
# at all, and there is nothing to choose between the ones that can.
#
# NO WINDOW IS OPENED AND THE CAMERA IS NOT MOVED, and that is not a shortcut — it is
# what the game itself turns out to do. A person walks five screens for this: the event
# window, its «Атака» (which sends nothing, it only flies the camera to the boss), the
# boss on the map, «Атака» in its popup, then the squad screen. All five end at ONE
# call, and #1259 read that call off the wire while the player made an attack by hand:
#
#     world.march.formation.new  <-  SendCreateMarchMessage(formation, 33, point, uuid,
#                                    1, 1, false, server, nil)
#
# The boss is addressed by its uuid, so none of the walk is load-bearing: there is no
# tile to wait for the client to stream in, and the server works the path out itself.
# The recipe sends exactly that, and the count it proves itself by then moves.
#
# Three steps, and each waits for the game to be in the next state rather than sleeping
# a guessed amount:
#
#   1. ASK. The event's manager is EMPTY until something asks the server for the day's
#      boss, and it answers «no boss, event shut» until then — read_codename_event.md
#      has the whole trap. Every later step reads what this brings back;
#   2. arm — the boss out of the event's own list, and the first squad standing in the
#      base, both before anything is sent;
#   3. send, and let the SERVER say whether an attack went out.
#
# Nothing is claimed from a press that returned cleanly. The run ends as a FAILURE,
# naming the step, when the event is not running (Sunday), when the boss is not in the
# list yet, when no squad is standing in the base, and when everything was sent and the
# count did not move. A timer therefore keeps its place and tries again instead of
# counting an attack that never went out.
#
# **A count that does not move can also mean the client is no longer talking to the
# server** — a stranded client goes on answering every getter with yesterday's numbers
# and returning `true` from every send (docs/research/server-link-status.md). That is
# not a state this recipe can read, and it cost #1259 an afternoon of blaming the
# server for a refusal it never made; the panel's status strip is what says it, and it
# is worth a glance before believing the failure below.
#
# The presses live in tools/lib/game_buttons.py (`codename_*`) and their engine calls in
# tools/lib/lua_actions.py; the reverse-engineering is docs/research/codename-event.md.
# The panel plays this from «События» and from the «Кодовое имя» block on «Чеклист».

# --- 1. Ask, then believe the answer ----------------------------------------------
# First, before anything is read or sent. Without it the gate below refuses on every day
# of the week, which is exactly what it did until #1259.
TAP codename_fetch

READ_LUA ((type(DataCenter.ActBossDataManager.stageTimeList) == 'table') and 1 or 0) INTO cn_loaded

WHILE cn_loaded == 0 LIMIT 4
    WAIT 0.6
    READ_LUA ((type(DataCenter.ActBossDataManager.stageTimeList) == 'table') and 1 or 0) INTO cn_loaded

READ_LUA (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager:IsBossAvailable() end) if not ok then return nil end return (v and 1 or 0) end)() INTO cn_open

IF cn_open != 1
    FAIL "«Кодовое имя» is not running — the event takes Sunday off"

# --- 2. Which boss, and which squad -----------------------------------------------
# Both before anything is sent: a run that finds out at the send that there was no squad
# has already told the server it was coming.
TAP codename_arm

READ_LUA (function() local p = DataCenter.__lw_codename or {} if p.uuid == nil or p.point == nil then return 0 end if p.formation == nil then return -1 end return 1 end)() INTO armed

IF armed == 0
    FAIL "the event is running but its boss is not in the list yet — try again in a moment"
IF armed < 0
    FAIL "no squad is standing in the base — every one of them is already out"

# --- 3. Send, and let the game say whether an attack went out ---------------------
# The proof is the SERVER's own attack count moving, not the send returning cleanly:
# the count is what the reward is paid against and what the board draws.
#
# EACH POLL ASKS AGAIN, and that is the whole reason this loop works. The count is the
# server's, and the client does not learn the new one on its own — no push arrived in
# the ten seconds this waited before the ask was put in, and the run failed reporting
# «the count did not move» over an attack that had already gone out and could be seen in
# the game. Asking is how the client itself finds out; a poll that only re-reads is
# polling a number nothing is updating.
TAP codename_send

TAP codename_fetch

READ_LUA (((function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.actBossTransTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() or 0) - ((DataCenter.__lw_codename or {}).before or 0)) INTO sent

# Twelve, not six: the server took eight seconds to own up to the first attack proven
# this way, which is six asks — a limit that only just cleared it is a run that reports
# a false failure the first time the server is busy.
WHILE sent < 1 LIMIT 12
    TAP codename_fetch
    READ_LUA (((function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.actBossTransTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() or 0) - ((DataCenter.__lw_codename or {}).before or 0)) INTO sent

IF sent < 1
    FAIL "the squad was sent and the attack count did not move — check the client is still talking to the server"

LOG "A squad is on its way to the «Кодовое имя» boss"
