# Read whether «Вторжение зомби» is running, and when its next window falls.
# ru: Чтение: идёт ли «Вторжение зомби» и когда его следующее окно.
#
# HEADLESS and nearly free: nothing is opened and nothing is pressed. The record arrives
# with the activity at login and the server keeps it up to date, so a reading is one
# round trip against the client's own memory — with ONE exception, below.
#
# WHAT IT LEAVES BEHIND, for the hunt that gates on it and for the card that draws it:
#
#   invasion      — the whole reading as one line, which is what the panel keeps
#   inv_open      — 1 while the invasion is running, 0 when it is not
#   inv_ends      — when the running one is over, in server seconds (0 when unknown)
#   inv_next_at   — when the next one starts, in server seconds (0 when unknown)
#   inv_seen      — how many golden zombies the client knows about; -1 = could not ask
#
# WHAT SAYS IT IS RUNNING, and it is the game's own answer rather than a date:
#
#   * `ActivityMonsterInvasionDataManager.invasionId` — 0 when no invasion is on. Read
#     live with the event off (2026-09-08): `invasionId=0`, `GetActivityData()` null,
#     `GetInvasionActivityId()` null, and the client's own golden-zombie list empty.
#   * the ACTIVITY ROW behind it, when the manager names one: `GetInvasionActivityId()`
#     into `ActivityListDataManager:GetActivityDataById(id)`, which carries `startTime`
#     and `endTime` in milliseconds. That is where `inv_ends` comes from.
#
# WHEN THE NEXT ONE IS. The invasion is a SEASON DAY, not a date: the client's own
# `advanced_monster_invasion` table has one row per season (`season_condition` «6-6»)
# and each names the `season_day` it falls on — 57 for every season from the second on.
# The season's own day number comes from the game (`GetNowSeasonAndSeasonDay`) and the
# day boundary with it (`GetTomorrowZero`), so the moment is arithmetic over two live
# readings and no date is written down anywhere. A day already past answers 0, which
# the card draws as «—»: an estimate nobody can check is worse than saying nothing.
#
# THE ONE MESSAGE IT MAY SEND. When the manager holds nothing at all, the client is
# asked for the record (`ReqMonsterInvasionActInfoMsg`) and the reading is taken again
# two seconds later. A client that has never asked and one that asked and was told «no
# invasion» look identical otherwise, and the difference decides whether the hunt runs.
# Nothing is sent when the manager already holds an invasion.

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local function ask(f) local ok, v = pcall(f) if not ok then return nil end return v end local M = {open = 0, inv = 0, act = 0, starts = 0, ends = 0, season = 0, day = 0, next_day = 0, next_at = 0, seen = -1, asked = 0} DataCenter.__lw_invasion = M local im = DataCenter.ActivityMonsterInvasionDataManager if im == nil then return 'no invasion manager — the client would not answer' end M.inv = num(ask(function() return im.invasionId end)) local now = num(ask(function() return UITimeManager:GetInstance():GetServerSeconds() end)) if now <= 0 then now = os.time() end M.act = num(ask(function() return im:GetInvasionActivityId() end)) if M.act > 0 then local L = DataCenter.ActivityListDataManager local row = ask(function() return L:GetActivityDataById(M.act) end) if type(row) == 'table' then M.starts = math.floor(num(ask(function() return row.startTime end)) / 1000) M.ends = math.floor(num(ask(function() return row.endTime end)) / 1000) end end if M.inv ~= 0 then M.open = 1 end if M.starts > 0 and M.ends > 0 and now >= M.starts and now <= M.ends then M.open = 1 end local S = DataCenter.SeasonDataManager local season = num(ask(function() local a = S:GetNowSeasonAndSeasonDay() return a end)) local day = 0 pcall(function() local a, b = S:GetNowSeasonAndSeasonDay() season = num(a) day = num(b) end) M.season, M.day = season, day local zero = math.floor(num(ask(function() return UITimeManager:GetInstance():GetTomorrowZero() end)) / 1000) local inst = ask(function() return LocalController.instance() end) if inst ~= nil and season > 0 then for i = 1, 12 do local row = ask(function() return inst:getLine('advanced_monster_invasion', i) end) if row == nil then break end local cond = tostring(ask(function() return row:getValue('season_condition') end) or '') local lo, hi = string.match(cond, '^(%d+)%-(%d+)$') if lo ~= nil and season >= (lo + 0) and season <= (hi + 0) then M.next_day = num(ask(function() return row:getValue('season_day') end)) break end end end if M.next_day > day and day > 0 and zero > 0 then M.next_at = zero + (M.next_day - day - 1) * 86400 end local ws = DataCenter.__lw_gold_ws local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) DataCenter.__lw_gold_ws = ws end if ws ~= nil then M.seen = 0 pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() ids:Add(1030000, 1) ids:Add(1030001, 1) ids:Add(1030002, 1) local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(ws.CurTilePos, 2000, ids, res) M.seen = res.Count end) end if M.open == 0 and M.inv == 0 and M.act == 0 then M.asked = 1 pcall(function() im:ReqMonsterInvasionActInfoMsg() end) end return 'open=' .. M.open .. ' inv=' .. M.inv .. ' act=' .. M.act .. ' starts=' .. M.starts .. ' ends=' .. M.ends .. ' season=' .. M.season .. ' day=' .. M.day .. ' next_day=' .. M.next_day .. ' next_at=' .. M.next_at .. ' seen=' .. M.seen .. ' asked=' .. M.asked end)() INTO invasion

# THE SECOND LOOK, and only where the first one had nothing to look at. The server's
# answer to the ask above lands after this statement, never inside it (docs/dsl.md), so
# the wait is what makes the ask worth sending at all.
READ_LUA (function() local M = DataCenter.__lw_invasion or {} return math.floor(M.asked or 0) end)() INTO inv_asked
IF inv_asked == 1
    WAIT 2
    READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter.__lw_invasion or {} local im = DataCenter.ActivityMonsterInvasionDataManager if im == nil then return 'no invasion manager — the client would not answer' end local ok, v = pcall(function() return im.invasionId end) if ok then M.inv = num(v) end if M.inv ~= 0 then M.open = 1 end return 'open=' .. math.floor(M.open or 0) .. ' inv=' .. math.floor(M.inv or 0) .. ' act=' .. math.floor(M.act or 0) .. ' starts=' .. math.floor(M.starts or 0) .. ' ends=' .. math.floor(M.ends or 0) .. ' season=' .. math.floor(M.season or 0) .. ' day=' .. math.floor(M.day or 0) .. ' next_day=' .. math.floor(M.next_day or 0) .. ' next_at=' .. math.floor(M.next_at or 0) .. ' seen=' .. math.floor(M.seen or -1) .. ' asked=1' end)() INTO invasion

READ_LUA (function() local M = DataCenter.__lw_invasion or {} return math.floor(M.open or 0) end)() INTO inv_open
READ_LUA (function() local M = DataCenter.__lw_invasion or {} return math.floor(M.ends or 0) end)() INTO inv_ends
READ_LUA (function() local M = DataCenter.__lw_invasion or {} return math.floor(M.next_at or 0) end)() INTO inv_next_at
READ_LUA (function() local M = DataCenter.__lw_invasion or {} return math.floor(M.seen or -1) end)() INTO inv_seen

LOG "Вторжение зомби: {invasion}"
