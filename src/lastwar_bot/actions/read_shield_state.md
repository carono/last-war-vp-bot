# Read the base's protection: is a shield up, until when, and what the bag holds.
# ru: Прочитать защиту базы: стоит ли щит, до какого момента и что лежит в сумке.
#
# A READ, and nothing else: it presses nothing, opens nothing and sends nothing to the
# server. No window has to be open — the wall is a manager the client keeps loaded from
# login, so this answers in one call from any scene.
#
# The answer lands in ONE variable, `shield`, as `k=v` pairs on one line:
#
#     up=1 ends=1789178275822 have24=1 have12=2 now=1789175679176
#
#   * up     — 1 when the base is under protection right now (the game's own
#              `IsInShield()`), 0 when it is not.
#   * ends   — when the protection runs out, epoch milliseconds on the GAME's clock
#              (`tools/lib/game_clock.py`), 0 when there is none.
#   * have24 — how many 24-hour shields the bag holds, summed over its stacks.
#   * have12 — how many 12-hour ones, for a card that says what else is in reserve.
#   * now    — the same GAME clock, so a reader works out what is left without ever
#              mixing in this PC's clock, which is minutes away from it.

READ_LUA (function() local M=DataCenter.DefenceWallDataManager local up,ends=0,0 if M~=nil then pcall(function() if M:IsInShield() then up=1 end end) pcall(function() ends=math.floor((M:GetDefenceWallData().protectEndTime or 0)+0) end) end local function _c(id) local n=0 pcall(function() for _,v in pairs(DataCenter.ItemData.ItemInfos or {}) do if math.floor((v.itemId or 0)+0)==id then n=n+math.floor((v.count or 0)+0) end end end) return n end local now=0 pcall(function() now=math.floor(UITimeManager:GetInstance():GetServerTime()+0) end) return 'up='..up..' ends='..ends..' have24='.._c(200411)..' have12='.._c(200406)..' now='..now end)() INTO shield
