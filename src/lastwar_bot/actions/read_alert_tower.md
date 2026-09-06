# Read the alert tower: the training run in the forbidden zone, its tasks and its rewards.
# ru: Чтение вышки оповещения: тренировка в запретной зоне, её задания и награды.
#
# HEADLESS. Nothing is opened, nothing is tapped, no camera moves and no scene is
# required — the whole reading is two requests the client sends itself plus one VM round
# trip. The building «Вышка оповещения» is only where a PLAYER enters the thing; the bot
# never goes near it.
#
# WHAT THE ABILITY IS. The tower runs a training march into the forbidden zone: a squad
# walks a strip of 480 nodes over four hours, opens what it finds, and while it walks the
# zone hands out TASKS — «bring 500 of this», «pass 50 nodes», «win a fight». A finished
# task is a reward that has to be claimed; an unclaimed one just sits there. One run is
# started a day (the game stores up to three starts), and the run itself needs nobody
# watching it.
#
# WHERE IT LIVES (docs/research/alert-tower.md, #2084). `DataCenter.T11IdleGameDataManager`
# — the client's own record of the game, filled by two sends and nothing else:
#
#   * `SendGetIdleGameMainMessage()`   -> the run's own state: which level, how many
#                                         starts are left today, the boss on offer,
#                                         whether a surprise box is waiting.
#   * `SendIdleGameEventAllMessage()`  -> every task the zone has handed out.
#
# Both are ASKED HERE, once, because there is nothing to subscribe to before the client
# has the record at all: a panel that has never opened the tower answers `GetMainData()`
# with `nil` (measured live). Afterwards the server pushes changes on its own, so this
# recipe is a person's press or a first look and never a clock (`CLAUDE.md`).
#
# WHAT A TASK CARRIES. `{eventId, uuid, num, questId, rewardId, status}` and the goal is
# in the config beside it — `lw_idle_game_event[eventId]` names the kind and the quest,
# `quest[questId]` names the goal (`para2`) and, when the task is a HANDOVER, what it
# wants (`para3` = `itemId;count`). `status` is the game's own `TaskState`: `1` not done,
# `2` done and waiting to be claimed, `3` claimed — a claimed one leaves the list.
#
# WHAT IS READ AND WHY EACH ONE. The page shows what a person would open the tower to
# see, and nothing that would need a second question:
#
#   * `level`      — the stage the account is on (`currentLevel`).
#   * `ready`      — tasks finished and waiting to be claimed.
#   * `open`       — tasks still running.
#   * `goods`      — of those open ones, how many ask for something the bag ALREADY has
#                    enough of. That is the number `work_alert_tower` would hand over.
#   * `starts`     — starts left today. One is added a day, three at most are stored.
#   * `has_run`    — is there a march ON THE BOARD at all (`endTime > 0`). Together with
#                    `run_left` it tells the two states `run_left = 0` used to conflate:
#                    `has_run = 1, run_left = 0` is a march that has ARRIVED and is
#                    waiting to be finished; `has_run = 0` is an empty board with nothing
#                    to finish. Reading them as one is what made the routine report loot
#                    it had never taken (#2585).
#   * `run_left`   — seconds until the running march reaches its last node; `0` when
#                    nothing is running, which is also when a start is worth spending.
#   * `box`        — is a surprise box waiting to be opened.
#   * `boss`       — the boss's strength beside the squad's, so «can it be challenged»
#                    is answered by two numbers rather than by a guess.
#
# `next_run_in` is the game's own clock and not the panel's: the march's remaining time
# plus a minute, so the errand comes back when there is something to claim rather than on
# a period somebody typed.

# ---- ask the game for the record, once ---------------------------------------------
LUA pcall(function() DataCenter.T11IdleGameDataManager:SendGetIdleGameMainMessage() end) pcall(function() DataCenter.T11IdleGameDataManager:SendIdleGameEventAllMessage() end)
WAIT 2.5

# ---- one round trip: everything above, parked for the cheap reads below -------------
READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local inst = nil pcall(function() inst = LocalController.instance() end) local function cell(tbl, id, key) local out = nil pcall(function() local row = inst:getLine(tbl, id) local md = row:getMetaData() local c = md[key] if type(c) == 'table' then c = c[1] end out = (rawget(row, '_lineData') or {})[c] end) if out == nil then return '' end return tostring(out) end local function held(id) local n = 0 pcall(function() local it = DataCenter.ItemData:GetItemById(id) n = num(it and it.count) end) return n end local function wants(questId) local out = {} local para3 = cell('quest', questId, 'para3') for part in string.gmatch(para3, '[^|]+') do local id, need = string.match(part, '(%d+)%s*;%s*(%d+)') if id ~= nil then out[#out+1] = {id = tonumber(id), num = tonumber(need)} end end return out end local m = nil pcall(function() m = M:GetMainData() end) local i = nil pcall(function() i = M:GetIdleInfoData() end) local now = 0 pcall(function() now = num(UITimeManager.Instance:GetServerTime()) end) if now == 0 then now = os.time() * 1000 end local ready, open, goods, poor = 0, 0, 0, 0 pcall(function() for _, e in pairs(M:GetGameEventList() or {}) do local st = num(e.status) if st == 2 then ready = ready + 1 elseif st == 1 then open = open + 1 local need = wants(e.questId) if #need > 0 then local can = true for _, w in ipairs(need) do if held(w.id) < w.num then can = false end end if can then goods = goods + 1 else poor = poor + 1 end end end end end) local left = 0 if i ~= nil then local ends = num(i.endTime) if ends > 0 then left = math.floor((ends - now) / 1000) if left < 0 then left = 0 end end end local pool = 0 pcall(function() for _ in pairs(i.rewardPool or {}) do pool = pool + 1 end end) local boss, mine = 0, 0 pcall(function() boss = num(cell('lw_idle_game_boss', num(m.bossId), 'boss_power')) end) pcall(function() mine = num(i.challengePower) end) local t = {level = num(m and m.currentLevel), starts = num(m and m.startGameLeftTime), box = (num(m and m.surpriseBoxGainTime) > 0) and 1 or 0, ready = ready, open = open, goods = goods, poor = poor, pool = pool, left = left, boss = boss, power = mine, nodes = num(i and i.passNode), run = (i ~= nil and num(i.endTime) > 0) and 1 or 0, known = (m ~= nil) and 1 or 0} t.text = 'level=' .. t.level .. ' run=' .. t.run .. ' ready=' .. ready .. ' open=' .. open .. ' goods=' .. goods .. ' short=' .. poor .. ' starts=' .. t.starts .. ' run_left=' .. left .. 's box=' .. t.box .. ' loot=' .. pool .. ' boss=' .. boss .. ' power=' .. mine DataCenter.__lw_at = t return t.text end)() INTO tower
LOG "Вышка оповещения: {tower}"

# ---- the readings the panel draws, one cheap field each -----------------------------
READ_LUA (math.floor((DataCenter.__lw_at or {}).known or 0)) INTO known
READ_LUA (math.floor((DataCenter.__lw_at or {}).level or 0)) INTO level
READ_LUA (math.floor((DataCenter.__lw_at or {}).ready or 0)) INTO ready
READ_LUA (math.floor((DataCenter.__lw_at or {}).open or 0)) INTO open
READ_LUA (math.floor((DataCenter.__lw_at or {}).goods or 0)) INTO goods
READ_LUA (math.floor((DataCenter.__lw_at or {}).starts or 0)) INTO starts
READ_LUA (math.floor((DataCenter.__lw_at or {}).left or 0)) INTO run_left
READ_LUA (math.floor((DataCenter.__lw_at or {}).run or 0)) INTO has_run
READ_LUA (math.floor((DataCenter.__lw_at or {}).box or 0)) INTO box
READ_LUA (math.floor((DataCenter.__lw_at or {}).boss or 0)) INTO boss_power
READ_LUA (math.floor((DataCenter.__lw_at or {}).power or 0)) INTO squad_power

# The game's own clock decides when this errand is worth another turn: a march that is
# still walking has nothing to claim, so come back a minute after it ends. Nothing
# running and nothing to claim is half an hour — the daily start refills on the server's
# day boundary and there is no event to wait for.
READ_LUA (function() local t = DataCenter.__lw_at or {} local left = math.floor(t.left or 0) if left > 0 then return left + 60 end return 1800 end)() INTO next_run_in
