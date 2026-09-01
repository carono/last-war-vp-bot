# Take the two VIP rewards the profile card offers: the daily chest and the daily gift.
# ru: Забрать две награды за VIP из карточки профиля: ежедневный сундук и ежедневный подарок.
#
# HEADLESS, and completely so: no window is opened, no marker is tapped, no camera is
# moved and no scene is required. Both presses are the client's own send, made from the
# base or from the world map alike, and the whole run is one VM round trip when there is
# nothing to take and three when there is.
#
# WHERE IT LIVES IN THE GAME. Opening the player's own profile card shows a VIP badge, and
# behind it two rewards come back every day the subscription is alive: a **chest** of VIP
# points and a **daily gift** of items. The bot takes both, and takes neither when the game
# says today's are already gone.
#
# WHAT ANSWERS THE QUESTION (docs/research/vip-rewards.md, #2091). `DataCenter.VIPManager`
# and the character's own VIP record on it, `VIPManager.vipinfo` — a `VIPDataInfo` filled
# at login and refreshed by the server's own `vip.info`. Every gate is a method of that
# object, so the whole reading is LOCAL: not one question goes on the wire for it.
#
#   * `IsVIPActive()`           — is the subscription running at all. Everything else is
#                                 meaningless when it is not, and the run says so instead
#                                 of pressing into the dark.
#   * `CanGetDailyFreeReward()` — is TODAY's gift still on offer.
#   * `CanGetDailyPoint()`      — is TODAY's points chest still on offer.
#   * `VIPManager:GetRedNum()`  — the badge the game itself would draw, reported beside the
#                                 gates so a run that pressed nothing can be told apart
#                                 from a run that could not see.
#
# THE DAY BOUNDARY IS THE GAME'S, and it is not computed here at all. Both gates are the
# server's own answer about today, so this recipe never asks what time it is, never
# consults the machine's clock and keeps no «last taken» of its own. There is nothing to
# drift and nothing to reset.
#
# THE PRESSES, and what they put on the wire — measured by wrapping `SFSNetwork.SendMessage`
# for the length of one call each (docs/research/vip-rewards.md §3):
#
#   * `VIPManager:ReceiveFreeReward()`       -> `vip.get.every.day.reward`, no payload.
#   * `VIPManager:RequestVipGetDailyPoint()` -> `vip.add.login.score`, no payload.
#
# A REFUSAL IS NOT A SUCCESS. The server answers a claim it accepts by pushing the record
# back (`UpdateVipInfo` — confirmed live with a hook on the manager's own handler) and
# answers one it refuses with silence. So the run does not report what it SENT: it presses,
# asks for the record again (`RequestLatestVipInfo()` -> `vip.info`), and reports what
# MOVED — the gate that shut, and the VIP score that grew. A gate still open afterwards is
# named in the log as refused.
#
# WHAT IS DELIBERATELY NOT PRESSED. The record also carries a ONE-OFF chest per VIP level
# ever reached (`GetPrivilegeRewardState(level)` -> 1 / 0 / -1, and `ReceivePrivilegeReward`
# behind it). It is a different reward from the two above — it does not come back daily —
# and on a live account every value of that ladder was refused by the server, so which of
# `1` and `0` means «still on offer» is not settled (docs/research/vip-rewards.md §5). The
# ladder is READ and written into the log, and nothing is pressed on it: a press nobody can
# gate is seven refused messages a run, and a log line costs nothing and is what will
# settle the question the first time a level goes unclaimed.
#
# NOT DETACHED. The whole run is under four seconds and nothing about it is a race, so it
# takes its ordinary turn in the queue.

# ---- what the game says is waiting -------------------------------------------------
# One round trip: the login gate, the subscription gate, both daily gates and the one-off
# ladder for the log. Returns HOW MANY presses are due so the recipe can skip the rest; the
# sentence for the log is parked and read back below.
READ_LUA (function() local t0 = os.clock() local now = 0 pcall(function() now = UITimeManager.Instance:GetServerTime() end) now = math.floor((tonumber(now) or 0) + 0) DataCenter.__lw_vip_gift = 0 DataCenter.__lw_vip_chest = 0 DataCenter.__lw_vip_score = 0 if now < 1600000000000 then DataCenter.__lw_vip = 'the client is still at the login screen — nothing read, nothing pressed' return 0 end local M = DataCenter and DataCenter.VIPManager local I = M and M.vipinfo if I == nil then DataCenter.__lw_vip = 'this client has no VIP record' return 0 end local active = false pcall(function() active = (I:IsVIPActive() == true) end) local level = 0 pcall(function() level = math.floor((tonumber(I.level) or 0) + 0) end) local score = 0 pcall(function() score = math.floor((tonumber(I.score) or 0) + 0) end) local gift = false pcall(function() gift = (I:CanGetDailyFreeReward() == true) end) local chest = false pcall(function() chest = (I:CanGetDailyPoint() == true) end) local red = 0 pcall(function() red = math.floor((tonumber(M:GetRedNum()) or 0) + 0) end) local top = level pcall(function() local T = DataCenter.VIPTemplateManager if T ~= nil then top = math.floor((tonumber(T.maxLevel) or level) + 0) end end) if top < level then top = level end local ladder = {} for lv = 1, top do local st pcall(function() st = I:GetPrivilegeRewardState(lv) end) ladder[#ladder + 1] = lv .. ':' .. math.floor((tonumber(st) or -9) + 0) end if active then DataCenter.__lw_vip_gift = gift and 1 or 0 DataCenter.__lw_vip_chest = chest and 1 or 0 end DataCenter.__lw_vip_score = score local due = (tonumber(DataCenter.__lw_vip_gift) or 0) + (tonumber(DataCenter.__lw_vip_chest) or 0) DataCenter.__lw_vip = 'vip=' .. (active and ('on lv' .. level) or 'off') .. ' gift=' .. tostring(gift) .. ' chest=' .. tostring(chest) .. ' due=' .. due .. ' points=' .. score .. ' red=' .. red .. ' one-off ladder=[' .. table.concat(ladder, ' ') .. '] ms=' .. math.floor((os.clock() - t0) * 1000) return due end)() INTO vip_due
READ_LUA tostring(DataCenter.__lw_vip or '') INTO vip_state
LOG "VIP: {vip_state}"

# ---- press what is due, then let the SERVER say what moved -------------------------
IF vip_due > 0
    LUA (function() local M = DataCenter.VIPManager local out = {} if (tonumber(DataCenter.__lw_vip_gift) or 0) == 1 then local ok, why = pcall(function() M:ReceiveFreeReward() end) out[#out + 1] = 'gift=' .. (ok and 'sent' or ('FAILED ' .. tostring(why))) end if (tonumber(DataCenter.__lw_vip_chest) or 0) == 1 then local ok, why = pcall(function() M:RequestVipGetDailyPoint() end) out[#out + 1] = 'chest=' .. (ok and 'sent' or ('FAILED ' .. tostring(why))) end DataCenter.__lw_vip_sent = table.concat(out, ' ') end)()
    WAIT 1.5
    LUA pcall(function() DataCenter.VIPManager:RequestLatestVipInfo() end)
    WAIT 2.0
    READ_LUA (function() local M = DataCenter.VIPManager local I = M.vipinfo local gift_left, chest_left = false, false pcall(function() gift_left = (I:CanGetDailyFreeReward() == true) end) pcall(function() chest_left = (I:CanGetDailyPoint() == true) end) local score = 0 pcall(function() score = math.floor((tonumber(I.score) or 0) + 0) end) local was = math.floor((tonumber(DataCenter.__lw_vip_score) or 0) + 0) local said = 'sent[' .. tostring(DataCenter.__lw_vip_sent or '') .. ']' if (tonumber(DataCenter.__lw_vip_gift) or 0) == 1 then said = said .. ' gift=' .. (gift_left and 'REFUSED — still on offer' or 'taken') else said = said .. ' gift=nothing was on offer' end if (tonumber(DataCenter.__lw_vip_chest) or 0) == 1 then said = said .. ' chest=' .. (chest_left and 'REFUSED — still on offer' or 'taken') else said = said .. ' chest=nothing was on offer' end return said .. ' points ' .. was .. ' -> ' .. score .. ' (+' .. (score - was) .. ')' end)() INTO vip_result
    LOG "VIP: {vip_result}"
