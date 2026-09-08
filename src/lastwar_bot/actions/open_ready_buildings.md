# Open the buildings that have finished — but only during the arms race's building hour.
# ru: Открыть достроенные здания — только в час стройки «Гонки вооружений».
#
# THE GATE IS THE POINT OF THIS RECIPE, and it is why the panel has no button that opens
# a building without playing this file. A finished building keeps until somebody takes
# it, and taking it pays «Строительство Города» points — so a building opened in any
# other hour of the day is points thrown away. The person's words (#2632): «открываем
# только в час стройки гонки вооружений».
#
# The phase is asked of the event itself (`ActivityPersonalArmsDataManager`): the current
# record's `event_id` is one of the five kinds, `120001` is city building, and the record
# is only current while its `stage_end_time` is still ahead of the server's own clock. A
# client that cannot answer stops rather than guessing — a run that opens everything
# because a manager was not loaded is exactly the mistake this gate exists to prevent.
#
# WHICH ONES. `uuid` empty is every finished building; a uuid names one, which is what
# the row's own «Открыть» sends. Nothing else narrows it: the panel draws what
# `read_ready_buildings.md` read and passes back one of those uuids.
#
# THE SEND GOES THROUGH THE GAME'S OWN TIMER. `BuildManager:CheckSendBuildFinish(uuid)`
# is the client's own claim (its parameters are `uuid, isDelaySend, info`, read off the
# live function), and it is scheduled with `TimerManager:DelayInvoke` rather than called
# on the hijack thread — the same precaution the march send needs, and it costs nothing.
#
# WHAT IT REPORTS. `opened` is how many claims went out, `ready_left` how many are still
# waiting afterwards. A run that sent claims and changed nothing FAILS: a send the server
# drops returns as cleanly as one it takes.
#
# WHAT IT SPENDS: nothing. The building is already built and paid for.

# WHICH BUILDING. A uuid as `read_ready_buildings.md` printed it; empty means all of them.
ARGS uuid =

# 1. Is it the building hour? 120001 is «Строительство Города»; -1 is «the client would
#    not answer», which is not a licence to open anything.
READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager if M == nil then return -1 end local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return -1 end local now, ends = 0, 0 pcall(function() now = math.floor(tonumber(UITimeManager:GetInstance():GetServerSeconds()) or 0) end) pcall(function() ends = math.floor(tonumber(d.stage_end_time) or 0) end) if now == 0 or ends <= now then return -1 end return math.floor(tonumber(d.event_id) or 0) end)() INTO arms_event
LOG "the arms race is paying for kind {arms_event} right now"

IF arms_event != 120001
    STOP "not the building hour of the arms race — the finished buildings are left standing"

# 2. What is waiting, before anything is claimed.
LUA DataCenter.__lw_open_build = '{uuid}'
READ_LUA (function() local Q = DataCenter.QueueDataManager if Q == nil or NewQueueType == nil or NewQueueState == nil then return 0 end local n = 0 pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and v.state == NewQueueState.Finish then n = n + 1 end end end) return n end)() INTO ready_before
LOG "finished buildings waiting: {ready_before}"

IF ready_before == 0
    STOP "no building has finished — nothing to open"

# 3. Claim them, on the game's own thread.
READ_LUA (function() local Q, M = DataCenter.QueueDataManager, DataCenter.BuildManager if Q == nil or M == nil then return 0 end local want = tostring(DataCenter.__lw_open_build or '') local list = {} pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and v.state == NewQueueState.Finish then local u = v.itemId if want == '' or tostring(u) == want then list[#list + 1] = u end end end end) local n = 0 local tm = TimerManager:GetInstance() for _, u in ipairs(list) do n = n + 1 tm:DelayInvoke(function() pcall(function() M:CheckSendBuildFinish(u) end) end, 0) end return n end)() INTO opened
LOG "claims sent: {opened}"

IF opened == 0
    STOP "that building is not among the ones waiting — nothing was sent"

WAIT 2

# 4. …and whether the game took them. The queue slot goes back to Free when it did.
READ_LUA (function() local Q = DataCenter.QueueDataManager if Q == nil or NewQueueType == nil or NewQueueState == nil then return 0 end local n = 0 pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and v.state == NewQueueState.Finish then n = n + 1 end end end) return n end)() INTO ready_left
LOG "still waiting: {ready_left}"

IF ready_left == ready_before
    FAIL "the claims went out and nothing moved — the game did not take them"
