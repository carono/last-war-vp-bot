# Take the «Кристальный босс» chests — every reward the event says is claimable.
# ru: Забрать бонусы кристального босса — все награды, которые игра отдаёт.
#
# The fight is not the whole of this event. It pays out along TWO lists of its own, and
# the game names both itself: «Weekly Damage Rewards» — one chest per segment of the
# week's damage record, reset weekly — and «Achievement Rewards», one per achievement
# the account has finished. Neither is handed over by winning. They sit in the event's
# window until somebody claims them, which is why the day's errand plays this after its
# three attacks: the third attack is exactly the moment the week's damage record can
# have moved, and a chest earned on Monday is still uncollected on Saturday if nobody
# opened the screen (#2638 — the account it was written on had 55 waiting).
#
# NO WINDOW IS OPENED. A person walks the event window, its rewards tab and its
# «Получить всё»; this asks the server for the two lists and presses the same two calls
# the button is made of.
#
# It takes no arguments and it ends as a SUCCESS when there is nothing to take: an
# errand that failed over an empty list would sit out its retry hold and try again over
# a state that only the next attack can change.
#
# It ends as a FAILURE only when the chests were counted, the claim was sent and the
# server's own count did not move — which is the same sentence as everywhere else on
# this event: a stranded client answers every getter with yesterday's numbers and
# returns cleanly from every send (docs/research/server-link-status.md).
#
# The presses live in tools/lib/game_buttons.py (`crystal_rewards_fetch`,
# `crystal_claim_all`), the reading is actions/read_crystal_boss.md, and the
# reverse-engineering is docs/research/crystal-boss.md.

# --- 1. Ask for the two lists -----------------------------------------------------
# The manager holds no reward list until something asks for one, exactly as it holds no
# boss: a claim over a list nobody fetched presses nothing and reports success.
TAP crystal_rewards_fetch

READ_LUA ((function() local w = nil local a = nil local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetClaimableCount() end) if ok and v ~= nil then w = math.floor(v + 0) end ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetAchievementClaimableCount() end) if ok and v ~= nil then a = math.floor(v + 0) end if w == nil and a == nil then return nil end return (w or 0) + (a or 0) end)() or -1) INTO cr_bonus

IF cr_bonus < 0
    FAIL "the event's reward lists could not be read — check the client is still talking to the server"

IF cr_bonus < 1
    LOG "«Кристальный босс»: there is nothing to claim right now"
    STOP "no chest is waiting"

LOG "«Кристальный босс»: {cr_bonus} chest(s) waiting"

# --- 2. Claim, and let the SERVER say the chests arrived --------------------------
# Two calls, and the one called `ClaimAllRewards()` is deliberately not among them: on
# a live client with 55 chests waiting it returned cleanly and claimed nothing at all.
TAP crystal_claim_all

# The claim is asynchronous — the manager says so itself — so the count is re-asked
# rather than read the instant it was pressed.
WAIT 2

TAP crystal_rewards_fetch

READ_LUA ((function() local w = nil local a = nil local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetClaimableCount() end) if ok and v ~= nil then w = math.floor(v + 0) end ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetAchievementClaimableCount() end) if ok and v ~= nil then a = math.floor(v + 0) end if w == nil and a == nil then return nil end return (w or 0) + (a or 0) end)() or -1) INTO cr_bonus

WHILE cr_bonus > 0 LIMIT 8
    WAIT 1
    TAP crystal_rewards_fetch
    READ_LUA ((function() local w = nil local a = nil local ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetClaimableCount() end) if ok and v ~= nil then w = math.floor(v + 0) end ok, v = pcall(function() return DataCenter.CrystalBossDataManager:GetAchievementClaimableCount() end) if ok and v ~= nil then a = math.floor(v + 0) end if w == nil and a == nil then return nil end return (w or 0) + (a or 0) end)() or -1) INTO cr_bonus

IF cr_bonus > 0
    FAIL "the claim was sent and the event still owes chests — check the client is still talking to the server"

LOG "The «Кристальный босс» chests are claimed"
