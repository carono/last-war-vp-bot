# Take the «Кодовое имя» chests — every achievement the event says is claimable.
# ru: Забрать призы «Кодового имени» — все награды, которые игра отдаёт.
#
# The fight is not the whole of this event. It pays out along a LADDER of damage
# achievements — «Нанести {1} урона {0} одной атакой», one rung per threshold — and
# nothing hands the chests over: they wait in the event's window until somebody claims
# them, which is why the day's errand plays this after its three attacks. The third
# attack is exactly the moment a new rung can have been beaten, and a rung beaten on
# Monday is still unclaimed on Saturday if nobody opened the screen (#2850 — the account
# it was written on had one waiting with its three attacks long since made).
#
# NO WINDOW IS OPENED. A person walks the event window and its «Задачи» tab; this asks
# the server for the ladder and sends the same claim the rung's own button is made of,
# once per rung that is waiting.
#
# It takes no arguments and it ends as a SUCCESS when there is nothing to take: an
# errand that failed over an empty ladder would sit out its retry hold and try again
# over a state only the next attack can change.
#
# It ends as a FAILURE only when the ladder was counted, the claims were sent and the
# server's own count did not move — which is the same sentence as everywhere else on
# this event: a stranded client answers every getter with yesterday's numbers and
# returns cleanly from every send (docs/research/server-link-status.md).
#
# The presses live in tools/lib/game_buttons.py (`codename_rewards_fetch`,
# `codename_claim_rewards`), the reading is actions/read_codename_event.md, and the
# reverse-engineering is docs/research/codename-event.md.

# --- 1. Ask for the ladder ---------------------------------------------------------
# The march get the attack sends does NOT bring it: a claim over a ladder nobody fetched
# presses nothing and reports success. `-1` is «the manager would not say» — an account
# that has not unlocked the event, or a client that has stopped answering.
TAP codename_rewards_fetch

READ_LUA ((function() local ok, t = pcall(function() return (DataCenter.ActBossDataManager.AchievementTaskData or {}) end) if not ok or type(t) ~= 'table' then return nil end local n = 0 local any = false for _, v in pairs(t) do any = true if tostring(v.state) == '1' then n = n + 1 end end if not any then return nil end return n end)() or -1) INTO cn_bonus

IF cn_bonus < 0
    FAIL "the event's achievement ladder could not be read — check the client is still talking to the server"

IF cn_bonus < 1
    LOG "«Кодовое имя»: there is nothing left to claim right now"

# --- 2. Claim every rung that is waiting -------------------------------------------
# The whole of the work is INSIDE this branch rather than behind an early `STOP`,
# because this recipe is CALLed: a `STOP` unwinds the caller with it, and the day's
# errand would then end on «nothing to claim» having said nothing about its attacks
# (tests/test_recipe_calls.py, #2390).
IF cn_bonus > 0
    LOG "«Кодовое имя»: {cn_bonus} chest(s) waiting"

    # One press for the whole ladder — the loop is inside the VM call, because a round
    # trip costs about 0.15 s and the ladder is fifty rungs long. There is no «получить
    # всё» on this event: each rung is its own send.
    TAP codename_claim_rewards

    # The claims are asynchronous — they return at once and the rungs move when the
    # replies land — so the count is ASKED again rather than read the instant it was
    # pressed.
    WAIT 2

    TAP codename_rewards_fetch

    READ_LUA ((function() local ok, t = pcall(function() return (DataCenter.ActBossDataManager.AchievementTaskData or {}) end) if not ok or type(t) ~= 'table' then return nil end local n = 0 local any = false for _, v in pairs(t) do any = true if tostring(v.state) == '1' then n = n + 1 end end if not any then return nil end return n end)() or -1) INTO cn_bonus

    WHILE cn_bonus > 0 LIMIT 8
        WAIT 1
        TAP codename_rewards_fetch
        READ_LUA ((function() local ok, t = pcall(function() return (DataCenter.ActBossDataManager.AchievementTaskData or {}) end) if not ok or type(t) ~= 'table' then return nil end local n = 0 local any = false for _, v in pairs(t) do any = true if tostring(v.state) == '1' then n = n + 1 end end if not any then return nil end return n end)() or -1) INTO cn_bonus

    IF cn_bonus > 0
        FAIL "the claims were sent and the event still owes chests — check the client is still talking to the server"

    LOG "The «Кодовое имя» chests are claimed"
