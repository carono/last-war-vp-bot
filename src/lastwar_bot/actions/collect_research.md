# Collect the studies that have finished in the science centres.
# ru: Собрать завершённые исследования в научных центрах.
#
# WHICH ONES. `uuid` empty is every centre whose study has finished; a uuid names one,
# which is what the row's own «Собрать» sends. Nothing else narrows it: the panel draws
# what `read_research_queues.md` read and passes back one of those uuids.
#
# WHAT COUNTS AS FINISHED is the same definition the build queue uses (#2641): the slot
# is in `Finish`, OR it is still in `Work` with its timer already run out — the client
# can be behind the server on that flip, and a study the server has not finished is
# refused by the server rather than guessed at here.
#
# THE SEND. `queue.finish` — `{uuid}`, the QUEUE's own uuid. A build queue has a claim of
# its own (`SendFreeBuildingUpgradeFinish`, `open_ready_buildings.md`); every other queue
# ends this way, and the message class names exactly one field
# (docs/research/research-queues.md). It is scheduled with `TimerManager:DelayInvoke`
# rather than called on the hijack thread — the same precaution the march send needs, and
# it costs nothing.
#
# WHAT PROVES IT. The server's own reply to `queue.finish`, counted by the ear this run
# raises before it sends; a reply carrying an `errorMsg` is counted as a refusal and the
# words are printed. The QUEUE is not the proof — the client's own copy of it lags, which
# is the whole lesson of #2641 — but a slot the server has answered for is freed here so
# the page is right at once instead of in a few minutes.
#
# WHAT IT SPENDS: nothing. No speed-ups, no diamonds, no daily quota. Closing a study
# EARLY is the other recipe (`speedup_research.md`) and it is a press a person makes.
#
# NO HOUR GATE, and that is deliberate rather than forgotten. A finished BUILDING is
# gated on the arms race's building hour because taking it pays points that only that
# hour buys (`open_ready_buildings.md`); a finished STUDY keeps until it is taken and the
# panel holds no opinion about when that should be — the day's own switch is where the
# person says so.

ARGS uuid =

# 1. What is waiting, before anything is claimed.
LUA DataCenter.__lw_sci_take = {want = '{uuid}', acks = 0, errs = {}}
READ_LUA (function() local Q = DataCenter.QueueDataManager if Q == nil or NewQueueType == nil or NewQueueState == nil then return 0 end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local p = DataCenter.__lw_sci_take local want = tostring(p.want or '') local n = 0 pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Science and v.state ~= NewQueueState.Free then local ends = math.floor(((v.endTime or 0) + 0) / 1000) if v.state == NewQueueState.Finish or (now > 0 and ends > 0 and ends <= now) then if want == '' or tostring(v.uuid) == want then n = n + 1 end end end end end) return n end)() INTO research_ready
LOG "studies waiting to be collected: {research_ready}"

IF research_ready == 0
    STOP "no study has finished — nothing to collect"

# 2. THE EAR, raised before the claims go out. It takes itself down after 60 seconds
#    even if the run dies, so a wrapper can never outlive the scenario that put it there.
LUA local p = DataCenter.__lw_sci_take local orig = SFSNetwork.HandleMessage local until_at = os.time() + 60 SFSNetwork.HandleMessage = function(...) local a = {...} pcall(function() local nm = '' for i = 1, 3 do if type(a[i]) == 'string' then nm = a[i] break end end if nm == 'queue.finish' then local bad = nil for i = 1, #a do local m = a[i] if type(m) == 'table' and m.errorMsg ~= nil then bad = tostring(m.errorMsg) end end if bad ~= nil then p.errs[#p.errs + 1] = bad else p.acks = p.acks + 1 end end end) if os.time() > until_at then SFSNetwork.HandleMessage = orig end return orig(...) end p.unhook = function() SFSNetwork.HandleMessage = orig end

# 3. Claim them, on the game's own thread.
READ_LUA (function() local Q = DataCenter.QueueDataManager if Q == nil then return 0 end local p = DataCenter.__lw_sci_take local want = tostring(p.want or '') local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local list = {} pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Science and v.state ~= NewQueueState.Free then local ends = math.floor(((v.endTime or 0) + 0) / 1000) if v.state == NewQueueState.Finish or (now > 0 and ends > 0 and ends <= now) then if want == '' or tostring(v.uuid) == want then list[#list + 1] = tostring(v.uuid) end end end end end) p.asked = list local tm = TimerManager:GetInstance() for _, u in ipairs(list) do tm:DelayInvoke(function() pcall(function() SFSNetwork.SendMessage(MsgDefines.QueueFinish, {uuid = u}, 0) end) end, 0) end return #list end)() INTO research_sent
LOG "claims sent: {research_sent}"

IF research_sent == 0
    STOP "that centre is not among the ones waiting — nothing was sent"

# 4. …and the answers.
READ_LUA (function() local p = DataCenter.__lw_sci_take or {} return math.floor(tonumber(p.acks) or 0) end)() INTO research_taken
WHILE research_taken < 1 LIMIT 15
    WAIT 1
    READ_LUA (function() local p = DataCenter.__lw_sci_take or {} return math.floor(tonumber(p.acks) or 0) end)() INTO research_taken

# …and a breath for the rest of a batch: the loop above ends on the FIRST answer, and
# «Собрать все» may have sent several.
WAIT 2
READ_LUA (function() local p = DataCenter.__lw_sci_take or {} return math.floor(tonumber(p.acks) or 0) end)() INTO research_taken

# 5. Down with the ear, and the client's own bookkeeping done for it: a slot the server
#    has answered for is FREE, whatever the client still believes.
READ_LUA (function() local p = DataCenter.__lw_sci_take or {} pcall(function() if type(p.unhook) == 'function' then p.unhook() end end) p.unhook = nil if math.floor(tonumber(p.acks) or 0) <= 0 then return 0 end local Q = DataCenter.QueueDataManager local freed = 0 local want = {} for _, u in ipairs(p.asked or {}) do want[tostring(u)] = true end pcall(function() for _, v in pairs(Q.queueDic or {}) do if type(v) == 'table' and v.type == NewQueueType.Science and want[tostring(v.uuid)] and v.state == NewQueueState.Finish then v.state = NewQueueState.Free v.endTime = 0 v.itemId = '' freed = freed + 1 end end end) return freed end)() INTO research_freed
READ_LUA (function() local p = DataCenter.__lw_sci_take or {} return table.concat(p.errs or {}, '; ') end)() INTO research_err

IF research_taken == 0
    LOG "nothing was handed over — {research_err}"
    FAIL "the claims went out and the game handed nothing over"

LOG "studies collected: {research_taken} of {research_sent} (slots freed: {research_freed}) {research_err}"
