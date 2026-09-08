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
# WHAT COUNTS AS FINISHED is the same definition that recipe uses (#2641): the slot is in
# `Finish`, OR it is still in `Work` with its timer already run out — the client can be
# minutes behind the server on that flip, and a building the server has not finished is
# refused by the server rather than guessed at here.
#
# THE SEND, AND THE ONE THAT ACTUALLY SENDS (#2641). `BuildManager:CheckSendBuildFinish`
# is a CHECK, not a send: calling it on a finished building put nothing on the wire at
# all, which is why every «Открыть» reported a failure and no building was ever taken.
# The sender is `BuildManager:SendFreeBuildingUpgradeFinish(uuid)`, and it is scheduled
# with `TimerManager:DelayInvoke` rather than called on the hijack thread — the same
# precaution the march send needs, and it costs nothing.
#
# WHAT PROVES IT. `free.building.upgrade.finish` comes back for each claim, and it says
# in the clearest possible way which it was:
#
#     {_id = …, _time = …, reward = {…}, buildInfo = {uuid = …, bId = …, lv = …, …}}
#     {errorCode = "E000000", errorMsg = "upgrade is not finish"}
#
# So the run listens for its own answer and counts the ones that carried a `buildInfo`.
# The QUEUE cannot be the proof, and that was the other half of the bug: the client does
# not apply what the server tells it about its own build queue (docs/research/
# ready-buildings.md §5), so a slot claimed and taken sits in `Finish` for minutes
# afterwards. The recipe therefore frees the slot itself once the server has said yes —
# the client's own bookkeeping, done for it, so the page is right at once.

# WHICH BUILDING. A uuid as `read_ready_buildings.md` printed it; empty means all of them.
ARGS uuid =

# 1. Is it the building hour? 120001 is «Строительство Города»; -1 is «the client would
#    not answer», which is not a licence to open anything.
READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager if M == nil then return -1 end local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return -1 end local now, ends = 0, 0 pcall(function() now = math.floor(tonumber(UITimeManager:GetInstance():GetServerSeconds()) or 0) end) pcall(function() ends = math.floor(tonumber(d.stage_end_time) or 0) end) if now == 0 or ends <= now then return -1 end return math.floor(tonumber(d.event_id) or 0) end)() INTO arms_event
LOG "the arms race is paying for kind {arms_event} right now"

IF arms_event != 120001
    STOP "not the building hour of the arms race — the finished buildings are left standing"

# 2. What is waiting, before anything is claimed.
LUA DataCenter.__lw_open_build = {want = '{uuid}', acks = {}, errs = {}}
READ_LUA (function() local Q = DataCenter.QueueDataManager if Q == nil or NewQueueType == nil or NewQueueState == nil then return 0 end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local n = 0 pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and (v.state == NewQueueState.Finish or (v.state == NewQueueState.Work and now > 0 and math.floor(((v.endTime or 0) + 0) / 1000) <= now)) then n = n + 1 end end end) return n end)() INTO ready_before
LOG "finished buildings waiting: {ready_before}"

IF ready_before == 0
    STOP "no building has finished — nothing to open"

# 3. THE EAR, raised before the claims go out. It takes itself down after 60 seconds
#    even if the run dies, so a wrapper can never outlive the scenario that put it there.
LUA local p = DataCenter.__lw_open_build local orig = SFSNetwork.HandleMessage local until_at = os.time() + 60 SFSNetwork.HandleMessage = function(...) local a = {...} pcall(function() local nm = '' for i = 1, 3 do if type(a[i]) == 'string' then nm = a[i] break end end if nm == 'free.building.upgrade.finish' then for i = 1, #a do local m = a[i] if type(m) == 'table' then if type(m.buildInfo) == 'table' and m.buildInfo.uuid ~= nil then p.acks[tostring(m.buildInfo.uuid)] = 1 elseif m.errorMsg ~= nil then p.errs[#p.errs + 1] = tostring(m.errorMsg) end end end end end) if os.time() > until_at then SFSNetwork.HandleMessage = orig end return orig(...) end p.unhook = function() SFSNetwork.HandleMessage = orig end

# 4. Claim them, on the game's own thread.
READ_LUA (function() local Q, M = DataCenter.QueueDataManager, DataCenter.BuildManager if Q == nil or M == nil then return 0 end local p = DataCenter.__lw_open_build local want = tostring(p.want or '') local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local list = {} pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and (v.state == NewQueueState.Finish or (v.state == NewQueueState.Work and now > 0 and math.floor(((v.endTime or 0) + 0) / 1000) <= now)) then local u = v.itemId if want == '' or tostring(u) == want then list[#list + 1] = u end end end end) p.asked = list local n = 0 local tm = TimerManager:GetInstance() for _, u in ipairs(list) do n = n + 1 tm:DelayInvoke(function() pcall(function() M:SendFreeBuildingUpgradeFinish(u) end) end, 0) end return n end)() INTO opened
LOG "claims sent: {opened}"

IF opened == 0
    STOP "that building is not among the ones waiting — nothing was sent"

# 5. …and the answers. `taken` counts the claims the SERVER said yes to.
READ_LUA (function() local p = DataCenter.__lw_open_build or {} local n = 0 for _, u in ipairs(p.asked or {}) do if (p.acks or {})[tostring(u)] == 1 then n = n + 1 end end return n end)() INTO taken
WHILE taken < 1 LIMIT 15
    WAIT 1
    READ_LUA (function() local p = DataCenter.__lw_open_build or {} local n = 0 for _, u in ipairs(p.asked or {}) do if (p.acks or {})[tostring(u)] == 1 then n = n + 1 end end return n end)() INTO taken

# …and a breath for the rest of a batch: the loop above ends on the FIRST yes, and
# «Открыть все» sends several. Two seconds is what the others need to land.
WAIT 2
READ_LUA (function() local p = DataCenter.__lw_open_build or {} local n = 0 for _, u in ipairs(p.asked or {}) do if (p.acks or {})[tostring(u)] == 1 then n = n + 1 end end return n end)() INTO taken

# 6. Down with the ear, and the client's own bookkeeping done for it: a slot the server
#    has handed over is FREE, whatever the client still believes.
READ_LUA (function() local p = DataCenter.__lw_open_build or {} pcall(function() if type(p.unhook) == 'function' then p.unhook() end end) p.unhook = nil local Q = DataCenter.QueueDataManager local freed = 0 pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Default and (p.acks or {})[tostring(v.itemId)] == 1 then v.state = NewQueueState.Free freed = freed + 1 end end end) return freed end)() INTO freed
READ_LUA (function() local p = DataCenter.__lw_open_build or {} return table.concat(p.errs or {}, '; ') end)() INTO open_err

IF taken == 0
    LOG "nothing was handed over — {open_err}"
    FAIL "the claims went out and the game handed nothing over"

LOG "buildings taken: {taken} of {opened} (slots freed: {freed}) {open_err}"
