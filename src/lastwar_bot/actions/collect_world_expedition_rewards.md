# Take both kinds of reward «Мировой поход» owes — the zone's own and the points tiers.
# ru: Забрать обе награды «Мирового похода» — за зону и за общие очки.
#
# HEADLESS and FREE. The event pays along two lists and neither is handed over by itself
# (`docs/research/world-expedition.md`):
#
#   * the ZONE's own reward — a tier per number of stages cleared in that zone, claimed
#     by naming the zone;
#   * the POINTS reward — a tier per TOTAL score of the round, claimed the same way with
#     `-1` in place of a zone.
#
# One ask claims every tier of that list the account has already earned, so a run costs
# at most five messages and nothing at all when there is nothing owed.
#
# THE SAFE IS THE THIRD LIST AND IS NOT ASKED FOR ON AN ORDINARY DAY: it only fills once
# a round has ended and is claimed during the settlement period, so it is asked for only
# after the round's own end time has passed.
#
# Nothing waiting is a SUCCESS, not a failure — the ordinary state of the event is «all
# claimed so far».

CALL read_world_expedition

IF rewards == 0
    LOG "Мировой поход: наград к получению нет"
ELSE
    READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter.LWSeasonTowerManager local S = DataCenter.__lw_ge or {} local asked = 0 for i = 1, 4 do if num(S['r' .. i]) == 1 then local sid = num(S['id' .. i]) if sid > 0 and pcall(function() M:ClaimReward(sid) end) then asked = asked + 1 end end end local group = false pcall(function() for _, row in pairs(M:GetGroupScoreRewards() or {}) do if num(row.received) == 0 then group = true break end end end) if group and pcall(function() M:ClaimReward(-1) end) then asked = asked + 1 end return asked end)() INTO ge_asked

    LOG "Мировой поход: запрошено наград — {ge_asked}"
    WAIT 3

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local S = DataCenter.__lw_ge or {} local M = DataCenter.LWSeasonTowerManager local now = 0 pcall(function() now = num(UITimeManager.Instance:GetServerTime()) end) if now == 0 then now = os.time() * 1000 end if num(S.ends) > 0 and now <= num(S.ends) * 1000 then return 0 end if num(S.safe) == 1 then return 0 end local ok = pcall(function() M:SendClaimSafeBoxRewardMessage() end) return ok and 1 or 0 end)() INTO ge_safe

IF ge_safe == 1
    LOG "Мировой поход: запрошена награда из сейфа — раунд завершён"

CALL read_world_expedition

LOG "Мировой поход: осталось наград — {rewards}"
