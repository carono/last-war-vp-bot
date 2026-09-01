# Work the alert tower: hand in what the tasks ask, claim what is done, send the squad again.
# ru: Отработать вышку оповещения: сдать что просят задания, забрать готовое, снова отправить отряд.
#
# HEADLESS, from the base or from the world map alike: every press below is the client's
# own send. No window is opened, the tower building is never tapped and the camera does
# not move.
#
# WHAT ONE RUN DOES, in the order it does it (docs/research/alert-tower.md, #2084):
#
#   1. asks the game for the record — the run's state and every task the zone handed out
#      (`CALL read_alert_tower`, which is also where every reading in the log comes from);
#   2. **hands over what a task asks for** — the tasks that want an item («принести 500»)
#      are paid out of the bag, one handover per pass, and the pass repeats while there
#      are tasks it can still pay for. There is no ceiling of our own on this: the person
#      whose account it is decided that everything a task asks for may be given
#      («сдавать разрешено всё, что просит задание»), so the only gate is whether the bag
#      holds enough — a handover the bag cannot cover is not attempted;
#   3. **claims every finished task** — `status == 2` in the game's own `TaskState`, and
#      a claimed one leaves the list, which is how the claim is verified rather than
#      assumed;
#   4. **collects the march's loot** when the march has reached its last node;
#   5. **opens the surprise box** when one is waiting;
#   6. **sends the squad in again** when a start is left and nothing is walking — one
#      start is added a day and three at most are stored, so a start left unspent on a
#      finished run is a day of the ability thrown away;
#   7. reads the whole state back, so the page the person is looking at moves with what
#      just happened and nothing asks the game a second time.
#
# WHY A HANDOVER IS A LOOP AND NOT ONE SEND PER TASK. `num` — how far a task has got —
# is the SERVER's count: it moves when the server has taken the goods, not when the
# message left. So a task wanting two handovers cannot be paid twice in one breath
# without guessing, and this recipe never guesses about spending: it pays once, waits for
# the record, and asks again whether anything is still payable. Measured live on
# 2026-09-01: one `SendIdleGameEventGoods` on a task asking `900002;500` moved the bag by
# exactly 500 and the task from `status=1 num=0` to `status=2 num=1`.
#
# WHAT IS DELIBERATELY NOT PRESSED. Four tasks in the config name a squad
# (`battle_army`, event kind 2) and are fought rather than paid, and the boss on the main
# screen is challenged with `SendChallengeBossMessage`. Neither was on offer on the live
# account while this was written, so neither is sent: a press nobody has ever seen answered
# is a press that cannot be told from a refusal. Both are READ — the boss's strength stands
# beside the squad's in the log — and both are named in the research file as the next step.
#
# GATES: nothing here has a quota of its own except the daily start, which the game
# itself counts (`startGameLeftTime`), and a claim of a task the server has already given
# is answered by silence and costs nothing.

ARGS give_goods = 1
ARGS start_run = 1
ARGS take_box = 1

# ---- what the game says is there ----------------------------------------------------
CALL read_alert_tower

# ---- 1. hand over what the tasks ask for --------------------------------------------
IF give_goods == 1
    WHILE goods > 0 LIMIT 4
        READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local inst = nil pcall(function() inst = LocalController.instance() end) local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local function cell(tbl, id, key) local out = nil pcall(function() local row = inst:getLine(tbl, id) local md = row:getMetaData() local c = md[key] if type(c) == 'table' then c = c[1] end out = (rawget(row, '_lineData') or {})[c] end) if out == nil then return '' end return tostring(out) end local function held(id) local n = 0 pcall(function() local it = DataCenter.ItemData:GetItemById(id) n = num(it and it.count) end) return n end local sent, short, failed = 0, 0, 0 local err = '' local paid = {} pcall(function() for _, e in pairs(M:GetGameEventList() or {}) do if num(e.status) == 1 then local para3 = cell('quest', e.questId, 'para3') local need, can = {}, true for part in string.gmatch(para3, '[^|]+') do local id, want = string.match(part, '(%d+)%s*;%s*(%d+)') if id ~= nil then need[#need+1] = {id = tonumber(id), num = tonumber(want)} end end if #need > 0 then for _, w in ipairs(need) do if held(w.id) < w.num then can = false end end if can then local ok, why = pcall(function() M:SendIdleGameEventGoods(e.uuid) end) if ok then sent = sent + 1 paid[#paid+1] = num(e.eventId) .. ':' .. need[1].id .. 'x' .. need[1].num else failed = failed + 1 if err == '' then err = tostring(why) end end else short = short + 1 end end end end end) DataCenter.__lw_at_goods = 'сдано=' .. sent .. ' не хватает=' .. short .. ' отказано=' .. failed .. (err ~= '' and (' err=' .. err) or '') .. (#paid > 0 and (' [' .. table.concat(paid, ' ') .. ']') or '') return sent end)() INTO handed
        READ_LUA tostring(DataCenter.__lw_at_goods or '') INTO handed_text
        LOG "Вышка оповещения, сдача: {handed_text}"
        WAIT 2.5
        READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local inst = nil pcall(function() inst = LocalController.instance() end) local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local function cell(tbl, id, key) local out = nil pcall(function() local row = inst:getLine(tbl, id) local md = row:getMetaData() local c = md[key] if type(c) == 'table' then c = c[1] end out = (rawget(row, '_lineData') or {})[c] end) if out == nil then return '' end return tostring(out) end local function held(id) local n = 0 pcall(function() local it = DataCenter.ItemData:GetItemById(id) n = num(it and it.count) end) return n end local left = 0 pcall(function() for _, e in pairs(M:GetGameEventList() or {}) do if num(e.status) == 1 then local para3 = cell('quest', e.questId, 'para3') local can, any = true, false for part in string.gmatch(para3, '[^|]+') do local id, want = string.match(part, '(%d+)%s*;%s*(%d+)') if id ~= nil then any = true if held(tonumber(id)) < tonumber(want) then can = false end end end if any and can then left = left + 1 end end end end) return left end)() INTO goods

# ---- 2. claim every finished task ----------------------------------------------------
READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local sent, failed = 0, 0 local err = '' pcall(function() for _, e in pairs(M:GetGameEventList() or {}) do if num(e.status) == 2 then local ok, why = pcall(function() M:SendIdleGameEventReceiveMessage(e.uuid) end) if ok then sent = sent + 1 else failed = failed + 1 if err == '' then err = tostring(why) end end end end end) DataCenter.__lw_at_take = 'забрано=' .. sent .. ' отказано=' .. failed .. (err ~= '' and (' err=' .. err) or '') return sent end)() INTO claimed
READ_LUA tostring(DataCenter.__lw_at_take or '') INTO claimed_text
LOG "Вышка оповещения, награды заданий: {claimed_text}"
IF claimed > 0
    WAIT 2.0

# ---- 3. the march's own loot, when the march is over ----------------------------------
IF run_left == 0
    LUA pcall(function() DataCenter.T11IdleGameDataManager:SendRewardReceiveMessage() end)
    LOG "Вышка оповещения: забрана добыча закончившегося забега"
    WAIT 1.5

# ---- 4. the surprise box ---------------------------------------------------------------
IF take_box == 1
    IF box == 1
        LUA pcall(function() DataCenter.T11IdleGameDataManager:SendOpenSurpriseBoxMessage() end)
        LOG "Вышка оповещения: открыта коробка-сюрприз"
        WAIT 1.5

# ---- 5. send the squad in again --------------------------------------------------------
IF start_run == 1
    IF starts > 0
        IF run_left == 0
            LUA pcall(function() DataCenter.T11IdleGameDataManager:SendStartIdleGameMessage() end)
            LOG "Вышка оповещения: отряд отправлен в запретную зону"
            WAIT 3.0

# ---- 6. read the whole thing back, so the page moves with what just happened ------------
#
# The reading is the same recipe the panel plays on its own, called for its `READ_LUA …
# INTO` and nothing else, so the page ends up holding what the game says NOW rather than
# what this run believes it did. Its own log line inside the call carries the numbers the
# CALLER started with — a sub-recipe's `{name}` is filled at call time (docs/dsl.md) — so
# the fresh state is said here, by the caller, where the placeholder is filled as the line
# is written.
CALL read_alert_tower
READ_LUA tostring((DataCenter.__lw_at or {}).text or '') INTO tower_after
LOG "Вышка оповещения после отработки: {tower_after}"
