# Read the alliance train: is one at the platform, has it a conductor, are we aboard.
# ru: Прочитать поезд альянса: стоит ли он у перрона, есть ли машинист, сели ли мы.
#
# A READ, and nothing else: it presses nothing, opens no window and sends nothing to the
# server. Safe to poll while the boarding recipe is running.
#
# The answer lands in ONE variable, `train`, as `key=value` pairs:
#
#     open=1 state=2 queued=0 carriage=-1 waiting=55 cars=4 seats=7 departs=8140 thanked=0 contracts=92
#
#   * `open`      — the event is running AND the station is neither closed nor locked.
#                   `-` when the client would not answer at all (not logged in yet).
#   * `state`     — what stands at the platform: `0` nothing, `1` a train with no
#                   conductor yet, `2` a conductor has been appointed, `3` passengers are
#                   aboard. Boarding is possible from `2` upwards; below it there is
#                   nobody driving and the game refuses.
#   * `queued`    — are WE in a carriage already (`1`) or not (`0`).
#   * `carriage`  — which carriage we are queued in, as the player sees it (1..4), or
#                   `-1` when we are in none.
#   * `waiting`   — how many alliancemates are queued across all the carriages.
#   * `cars`      — how many carriages a passenger may board (the conductor's own is not
#                   one of them), and `seats` how many the biggest one holds.
#   * `departs`   — seconds until the train leaves, off the GAME's clock and never the
#                   PC's (`tools/lib/game_clock.py`).
#   * `thanked`   — has the fare already been paid from this account today's train (`1`),
#                   whether by this panel or by the person playing.
#   * `contracts` — how many Trade Contracts are in the bag. The fare is paid in these,
#                   and this number is the ceiling the boarding recipe clamps to: what it
#                   cannot pay out of the bag it does NOT buy for diamonds.
#
# The boarding half is `board_alliance_train.md`; the protocol is
# docs/research/alliance-train.md.

READ_LUA (function() local M = DataCenter.LWAllyStationDataManager if M == nil then return 'open=-' end local function yes(f) local ok, v = pcall(f) if not ok then return nil end return v and 1 or 0 end local function n(v) local ok, r = pcall(function() return v + 0 end) if ok then return r end return nil end local opened, closed, locked = yes(function() return (M:IsTrainActivityOpen()) end), yes(function() return (M:IsTrainClosed()) end), yes(function() return (M:IsTrainFunctionLock()) end) local open = '-' if opened ~= nil then if opened == 1 and closed ~= 1 and locked ~= 1 then open = '1' else open = '0' end end local p = nil pcall(function() p = M:GetPlatform(1) end) local state, queued, carriage, waiting, departs = '-', '-', '-', '-', '-' if type(p) == 'table' then state = tostring(n(p.state) or -1) queued = (p.meInQueue == true) and '1' or '0' local me = '' pcall(function() me = tostring(LuaEntry.Player.uid) end) local total, mine = 0, -1 pcall(function() for car, list in pairs(p.lineUp or {}) do if type(list) == 'table' then for _, who in pairs(list) do total = total + 1 if type(who) == 'table' and me ~= '' and tostring(who.uid) == me then mine = (n(car) or 1) - 1 end end end end end) waiting = tostring(total) carriage = tostring(mine) local ends = n(p.readyEndTime) or 0 if ends > 0 then local now = 0 pcall(function() now = UITimeManager.Instance:GetServerTime() + 0 end) if now > 0 then departs = tostring(math.max(0, math.floor((ends - now) / 1000))) end end end local cars, seats = 0, 0 local t = nil pcall(function() t = M:GetTrainByPlatformId(1) end) pcall(function() for _, c in pairs(t.carriages or {}) do local id = n(c.carriageId) or 0 local s = n(c.seatNum) or 0 if id > 0 then cars = cars + 1 if s > seats then seats = s end end end end) local thanked = yes(function() return (M:AlreadyThumbsUp()) end) local contracts = 0 pcall(function() for _, s in pairs(DataCenter.ItemData.ItemInfos or {}) do if type(s) == 'table' and tostring(s.itemId) == '1520001' then contracts = contracts + ((n(s.count) or 0)) end end end) return 'open=' .. open .. ' state=' .. state .. ' queued=' .. queued .. ' carriage=' .. carriage .. ' waiting=' .. waiting .. ' cars=' .. tostring(cars) .. ' seats=' .. tostring(seats) .. ' departs=' .. departs .. ' thanked=' .. tostring(thanked == nil and '-' or thanked) .. ' contracts=' .. tostring(math.floor(contracts)) end)() INTO train
