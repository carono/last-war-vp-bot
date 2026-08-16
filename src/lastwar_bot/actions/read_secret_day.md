# Read what the game itself can say about the star-secret-task day.
# ru: Прочитать, что игра сама говорит про день звёздных секреток.
#
# The game runs a day on which star (`is_special`) secret tasks are handed out in
# numbers, and a day after it on which they still come but far more rarely. It never
# says so anywhere a client can read: the config tables carry the star-task COUNTS by
# base level and season, the pools of task templates and the events screen, and not one
# of the 742 of them holds a per-day, per-warzone plan (docs/research/secret-task-day.md).
#
# What the client CAN be asked is what it is holding right now — the alliance's dispatch
# table, which is the same list the ★ page reads — and the game's own clock. That is
# evidence rather than a verdict: how many of the tasks in front of it are starred, on
# which warzone, and which game-day it is. The panel writes it into its book of
# observations and derives the cycle from those (`panel/runtime/secret_day.py`); nothing
# here decides what today is.
#
#     ARGS server = 0     which warzone the caller is asking about; 0 (the default)
#                         means the account's own. A foreign warzone is reported as
#                         `own=0` and carries no counts — the client is told the
#                         dispatch table of the alliance it is in and of no other, and
#                         saying anything else would be inventing it.
#
# TWO LINES COME BACK, in the variables `secret_clock` and `secret_counts` (and
# `secret_servers`, which is how many warzones the second line names — the DSL compares
# numbers, so «did anything come back at all» is asked as a count):
#
#     secret_clock   own=<id> asked=<id> now_ms=<epoch ms> day_end_ms=<epoch ms>
#     secret_counts  <server>=<stars>/<tasks> <server>=<stars>/<tasks> …
#
#   own          the warzone the account plays in, as the client knows it.
#   asked        the warzone the caller asked about, after 0 has been resolved to `own`.
#   now_ms       the GAME's clock (docs/research/game-clock.md) — the machine's is not it.
#   day_end_ms   when this game-day turns over; the day boundary every observation is
#                counted against, so a reading taken at 01:00 lands on the right day.
#   <server>=…   per warzone, how many of the alliance's LIVE dispatch tasks standing on
#                it are starred, out of how many there are. Live = not expired, which is
#                what «сейчас на карте» means; a task whose window has closed says
#                nothing about today.
#
# A CLIENT AT THE LOGIN SCREEN answers plausibly and wrongly about all of it
# (docs/research/game-clock.md): server -1, an empty table, a clock that is the process's
# uptime. So the recipe fails rather than handing the panel a day-zero observation.

ARGS server = 0

READ_LUA (function() local P=LuaEntry.Player local T=UITimeManager:GetInstance() local own=tonumber(P.serverId) or 0 local asked=tonumber('{server}') or 0 if asked<=0 then asked=own end local function num(f) local ok,v=pcall(f) if not ok or tonumber(v)==nil then return 0 end return math.floor(tonumber(v)) end return 'own='..own..' asked='..asked..' now_ms='..num(function() return T:GetServerTime() end)..' day_end_ms='..num(function() return T:GetTomorrowZero() end) end)() INTO secret_clock
LOG "clock: {secret_clock}"

READ_LUA (function() local P=LuaEntry.Player local own=tonumber(P.serverId) or 0 if own<=0 then return '' end local T=UITimeManager:GetInstance() local now=0 pcall(function() now=math.floor(tonumber(T:GetServerTime()) or 0) end) local m=DataCenter.ActDispatchTaskDataManager local tot,star={},{} local n=0 for _,v in pairs((m and m.allianceTask) or {}) do local exp=tonumber(v.actEndTime) or 0 if exp==0 or now<exp then local srv=math.floor(tonumber(v.targetServer) or own) local spec=0 pcall(function() spec=tonumber(v.cfg:getValue('is_special')) or 0 end) tot[srv]=(tot[srv] or 0)+1 star[srv]=(star[srv] or 0)+((spec==1) and 1 or 0) n=n+1 end end if n==0 then return '' end local ids={} for k in pairs(tot) do ids[#ids+1]=k end table.sort(ids) local out={} for _,k in ipairs(ids) do out[#out+1]=k..'='..star[k]..'/'..tot[k] end return table.concat(out,' ') end)() INTO secret_counts
LOG "counts: {secret_counts}"

READ_LUA (function() local s='{secret_counts}' local n=0 for _ in s:gmatch('%S+') do n=n+1 end return n end)() INTO secret_servers

IF secret_servers == 0
    LOG "the client is holding no live dispatch task at all — either the alliance has none out, or this client is not in a session"
    FAIL "secret day: nothing to count"
