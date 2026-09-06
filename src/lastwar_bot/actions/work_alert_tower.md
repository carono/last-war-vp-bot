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
#   2. **closes a march that has arrived** — `SendIdleGameEndMessage`, which is what pays
#      the run out and what settles its nodes, so it goes FIRST: a task the march finished
#      only turns `status = 2` once the run is closed. It used to be
#      `SendRewardReceiveMessage`, which puts nothing on the wire at all, so for five days
#      the log said «забрана добыча» over a march that was still standing on the board
#      unpaid (#2585);
#   3. **hands over what a task asks for** — the tasks that want an item («принести 500»)
#      are paid out of the bag, one handover per pass, and the pass repeats while there
#      are tasks it can still pay for. There is no ceiling of our own on this: the person
#      whose account it is decided that everything a task asks for may be given
#      («сдавать разрешено всё, что просит задание»), so the only gate is whether the bag
#      holds enough — a handover the bag cannot cover is not attempted;
#   4. **claims every finished task** — `status == 2` in the game's own `TaskState`, and
#      a claimed one leaves the list, which is how the claim is verified rather than
#      assumed;
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

# ---- 1. close the arrived march — the step that actually pays (#2585) ----------------
#
# FIRST, deliberately: closing the run is what settles its nodes, so a task the march
# finished is only `status = 2` after this. Claiming before it meant a reward waited a
# whole half-hour for the next turn of the errand.
#
# WHAT WAS WRONG HERE FOR FIVE DAYS. This used to be one line —
# `SendRewardReceiveMessage()` — followed by «забрана добыча закончившегося забега»,
# printed whether or not anything had been taken. Measured live on 2026-09-06 with an ear
# on both directions of the wire: that call puts **NOTHING on the socket at all** (the
# same probe caught `idle.game.main` going out a second earlier, so the ear was working),
# and the server therefore never answered. The march that had walked its 480 nodes was
# left standing on the board, its reward unpaid, its tasks frozen — `num` on the two open
# ones had not moved since 2026-09-01 — while every half hour the log said the loot had
# been collected.
#
# What finishes a run is `SendIdleGameEndMessage()` — `idle.game.end` on the wire, taken
# by the server without an error, after which `passNode` and `endTime` reset to `0`. So
# THAT is what is sent, and «closed» is claimed only when the board has actually cleared.
# The bag is photographed before the send and again after, so the line says in numbers
# what arrived rather than what was attempted.
#
# `has_run` is why the two states are told apart at all: `run_left = 0` is true both of a
# march that has arrived and of an empty board, and pressing on the empty one is the
# nothing-press this whole section existed to stop.
IF has_run == 1
    IF run_left == 0
        READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local function snap() local out = {} pcall(function() for _, it in pairs(DataCenter.ItemData.ItemInfos or {}) do local id, c = 0, 0 pcall(function() id = num(it.itemId or it.templateId or it.id) end) pcall(function() c = num(it.count) end) if id > 0 then out[id] = (out[id] or 0) + c end end end) return out end DataCenter.__lw_at_bag = snap() local ok, why = pcall(function() M:SendIdleGameEndMessage() end) DataCenter.__lw_at_end = ok and '' or tostring(why) return ok and 1 or 0 end)() INTO end_sent
        WAIT 3.5
        READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local function snap() local out = {} pcall(function() for _, it in pairs(DataCenter.ItemData.ItemInfos or {}) do local id, c = 0, 0 pcall(function() id = num(it.itemId or it.templateId or it.id) end) pcall(function() c = num(it.count) end) if id > 0 then out[id] = (out[id] or 0) + c end end end) return out end local function gained() local was = DataCenter.__lw_at_bag or {} local now = snap() local rows = {} for id, c in pairs(now) do local d = c - (was[id] or 0) if d > 0 then rows[#rows + 1] = id .. '+' .. d end end for id, c in pairs(was) do if now[id] == nil then rows[#rows + 1] = id .. '-' .. c end end table.sort(rows) if #rows == 0 then return 'в сумку ничего не пришло' end return 'в сумке: ' .. table.concat(rows, ' ') end local i = nil pcall(function() i = M:GetIdleInfoData() end) local ends = num(i and i.endTime) local nodes = num(i and i.passNode) local why = tostring(DataCenter.__lw_at_end or '') if why ~= '' then return 'клиент отказал: ' .. why end if ends > 0 or nodes > 0 then return 'сервер НЕ закрыл забег (endTime=' .. ends .. ' узлов=' .. nodes .. ')' end return 'подтверждено, ' .. gained() end)() INTO end_text
        LOG "Вышка оповещения, забег закрыт: {end_text}"

# ---- 2. hand over what the tasks ask for --------------------------------------------
IF give_goods == 1
    WHILE goods > 0 LIMIT 4
        READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local inst = nil pcall(function() inst = LocalController.instance() end) local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local function cell(tbl, id, key) local out = nil pcall(function() local row = inst:getLine(tbl, id) local md = row:getMetaData() local c = md[key] if type(c) == 'table' then c = c[1] end out = (rawget(row, '_lineData') or {})[c] end) if out == nil then return '' end return tostring(out) end local function held(id) local n = 0 pcall(function() local it = DataCenter.ItemData:GetItemById(id) n = num(it and it.count) end) return n end local sent, short, failed = 0, 0, 0 local err = '' local paid = {} pcall(function() for _, e in pairs(M:GetGameEventList() or {}) do if num(e.status) == 1 then local para3 = cell('quest', e.questId, 'para3') local need, can = {}, true for part in string.gmatch(para3, '[^|]+') do local id, want = string.match(part, '(%d+)%s*;%s*(%d+)') if id ~= nil then need[#need+1] = {id = tonumber(id), num = tonumber(want)} end end if #need > 0 then for _, w in ipairs(need) do if held(w.id) < w.num then can = false end end if can then local ok, why = pcall(function() M:SendIdleGameEventGoods(e.uuid) end) if ok then sent = sent + 1 paid[#paid+1] = num(e.eventId) .. ':' .. need[1].id .. 'x' .. need[1].num else failed = failed + 1 if err == '' then err = tostring(why) end end else short = short + 1 end end end end end) DataCenter.__lw_at_goods = 'отправлено сдач=' .. sent .. ' не хватает=' .. short .. ' отказано=' .. failed .. (err ~= '' and (' err=' .. err) or '') .. (#paid > 0 and (' [' .. table.concat(paid, ' ') .. ']') or '') return sent end)() INTO handed
        READ_LUA tostring(DataCenter.__lw_at_goods or '') INTO handed_text
        LOG "Вышка оповещения, сдача: {handed_text}"
        WAIT 2.5
        READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local inst = nil pcall(function() inst = LocalController.instance() end) local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local function cell(tbl, id, key) local out = nil pcall(function() local row = inst:getLine(tbl, id) local md = row:getMetaData() local c = md[key] if type(c) == 'table' then c = c[1] end out = (rawget(row, '_lineData') or {})[c] end) if out == nil then return '' end return tostring(out) end local function held(id) local n = 0 pcall(function() local it = DataCenter.ItemData:GetItemById(id) n = num(it and it.count) end) return n end local left = 0 pcall(function() for _, e in pairs(M:GetGameEventList() or {}) do if num(e.status) == 1 then local para3 = cell('quest', e.questId, 'para3') local can, any = true, false for part in string.gmatch(para3, '[^|]+') do local id, want = string.match(part, '(%d+)%s*;%s*(%d+)') if id ~= nil then any = true if held(tonumber(id)) < tonumber(want) then can = false end end end if any and can then left = left + 1 end end end end) return left end)() INTO goods

# ---- 3. claim every finished task ----------------------------------------------------
READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local sent, failed = 0, 0 local err = '' pcall(function() for _, e in pairs(M:GetGameEventList() or {}) do if num(e.status) == 2 then local ok, why = pcall(function() M:SendIdleGameEventReceiveMessage(e.uuid) end) if ok then sent = sent + 1 else failed = failed + 1 if err == '' then err = tostring(why) end end end end end) DataCenter.__lw_at_take = 'забрано=' .. sent .. ' отказано=' .. failed .. (err ~= '' and (' err=' .. err) or '') return sent end)() INTO claimed
WAIT 2.0
READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local ready = 0 pcall(function() for _, e in pairs(M:GetGameEventList() or {}) do if num(e.status) == 2 then ready = ready + 1 end end end) return tostring(DataCenter.__lw_at_take or '') .. ' осталось готовых=' .. ready end)() INTO claimed_text
LOG "Вышка оповещения, награды заданий: {claimed_text}"

# ---- 4. the surprise box ---------------------------------------------------------------
IF take_box == 1
    IF box == 1
        LUA pcall(function() DataCenter.T11IdleGameDataManager:SendOpenSurpriseBoxMessage() end)
        WAIT 2.5
        READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local m = nil pcall(function() m = M:GetMainData() end) if num(m and m.surpriseBoxGainTime) > 0 then return 'сервер НЕ открыл коробку' end return 'подтверждено' end)() INTO box_text
        LOG "Вышка оповещения, коробка-сюрприз: {box_text}"

# ---- 5. send the squad in again --------------------------------------------------------
IF start_run == 1
    IF starts > 0
        IF run_left == 0
            LUA pcall(function() DataCenter.T11IdleGameDataManager:SendStartIdleGameMessage() end)
            WAIT 3.0
            READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local i, m = nil, nil pcall(function() i = M:GetIdleInfoData() end) pcall(function() m = M:GetMainData() end) local ends = num(i and i.endTime) local starts = num(m and m.startGameLeftTime) if ends <= 0 then return 'сервер НЕ принял отправку, стартов осталось ' .. starts end return 'подтверждено, стартов осталось ' .. starts end)() INTO start_text
            LOG "Вышка оповещения, отряд отправлен в запретную зону: {start_text}"

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
