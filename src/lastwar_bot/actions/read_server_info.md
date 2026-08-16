# Read what the game knows about a warzone — when it opened and what day it is on.
# ru: Прочитать данные сервера: когда запущен, какой идёт день и что ещё известно.
#
# ANY server, not only the one the client is standing in, and WITHOUT a jump. The client
# asks the game server one question — `get.other.server.info` — and the answer is the
# warzone's opening moment in the game's own milliseconds; everything else in the line
# below is arithmetic the client already does for its own screens
# (docs/research/server-info.md).
#
#     ARGS server = 0       the warzone to ask about; 0 (the default) means the one the
#                         account plays in, whose opening moment the client already holds
#                         and which therefore costs no question at all.
#
# THE ANSWER IS ONE LINE in the variable `server_info`, `k=v` pairs:
#
#     server=<id> own=<0|1> open_ms=<epoch ms> day=<n> week=<n> now_ms=<epoch ms>
#     day_end_ms=<epoch ms> zone_star=<n> name=<text|-> max=<id|-> type=<n|->
#
#   server      the warzone this line is about.
#   own         1 when it is the account's own — then `name`, `max` and `type` are filled
#               in and `week` is meaningful; for anybody else's warzone the server tells
#               the client the opening moment and nothing else, so those read `-`.
#   open_ms     when the warzone opened, epoch milliseconds on the GAME's clock. The PC's
#               clock is not that clock (docs/research/game-clock.md), so a reader turning
#               this into a date judges it with `tools/lib/game_clock.py`.
#   day         which day the warzone is on TODAY — the client's own count
#               (`GetServerOpenDaysByTimeStamp`), so it agrees with what the game draws.
#               Day 1 is opening day.
#   week        the same count in whole weeks, and OWN warzone only — the client counts
#               it from its own opening moment and takes no argument.
#   now_ms      the game's clock at the moment of the read, so a caller can date `open_ms`
#               without trusting the machine it runs on.
#   day_end_ms  when this game-day turns over — the daily quotas' midnight, which is not
#               any midnight in particular (02:00 UTC on the warzone this was written on).
#   zone_star   the warzone's zone star, when the client happens to hold it; 0 otherwise.
#               It rides a different question and is not asked for here.
#
# WHY IT IS NOT INSTANT for a foreign warzone: the question goes to the game server and
# the answer comes back on the wire, so the recipe asks, waits, and re-reads up to four
# times. Measured live: the answer was there within a second. Once it has arrived the
# client keeps it, so asking the same warzone again is free.
#
# A CLIENT AT THE LOGIN SCREEN answers plausibly and wrongly about everything else
# (docs/research/game-clock.md), and here it simply has no opening moment at all — the
# recipe fails rather than reporting day 1 of 1970.

ARGS server = 0

READ_LUA (function() local sid=tonumber('{server}') or 0 local P=LuaEntry.Player local own=tonumber(P.serverId) or 0 if sid<=0 then sid=own end DataCenter.__lw_server_ask=sid if sid~=own then pcall(function() SFSNetwork.SendMessage(MsgDefines.GetOtherServerInfo,sid) end) end return sid end)() INTO asked_server
LOG "asking the game about warzone {asked_server}"

READ_LUA (function() local sid=tonumber(DataCenter.__lw_server_ask) or 0 local P=LuaEntry.Player local own=tonumber(P.serverId) or 0 local t=0 if sid==own then t=tonumber(P.openServerTime) or 0 else local d=P.otherServerOpenTimeDict t=(type(d)=='table' and tonumber(d[sid])) or 0 end return math.floor(t) end)() INTO open_ms

WHILE open_ms == 0 LIMIT 4
    WAIT 1
    READ_LUA (function() local sid=tonumber(DataCenter.__lw_server_ask) or 0 local P=LuaEntry.Player local own=tonumber(P.serverId) or 0 local t=0 if sid==own then t=tonumber(P.openServerTime) or 0 else local d=P.otherServerOpenTimeDict t=(type(d)=='table' and tonumber(d[sid])) or 0 end return math.floor(t) end)() INTO open_ms

IF open_ms == 0
    LOG "warzone {asked_server}: the client had no answer — either the server does not exist or this client is not in a session"
    FAIL "server info: no opening moment came back"

READ_LUA (function() local sid=tonumber(DataCenter.__lw_server_ask) or 0 local P=LuaEntry.Player local T=UITimeManager:GetInstance() local own=tonumber(P.serverId) or 0 local mine=(sid==own) local t=0 if mine then t=tonumber(P.openServerTime) or 0 else local d=P.otherServerOpenTimeDict t=(type(d)=='table' and tonumber(d[sid])) or 0 end t=math.floor(t) local function num(f,...) local ok,v=pcall(f,...) if not ok or v==nil then return '-' end local n=tonumber(v) if n==nil then return '-' end return tostring(math.floor(n)) end local star='-' pcall(function() local M=DataCenter.ServerStatusManager local i=M and M.globalServerInfo and M.globalServerInfo[sid] if i then star=tostring(math.floor(tonumber(i.zoneStar) or 0)) end end) local out={} out[#out+1]='server='..sid out[#out+1]='own='..(mine and 1 or 0) out[#out+1]='open_ms='..t out[#out+1]='day='..num(function() return T:GetServerOpenDaysByTimeStamp(t) end) out[#out+1]='week='..(mine and num(function() return T:GetOpenServerWeek() end) or '-') out[#out+1]='now_ms='..num(function() return T:GetServerTime() end) out[#out+1]='day_end_ms='..num(function() return T:GetTomorrowZero() end) out[#out+1]='zone_star='..star out[#out+1]='name='..(mine and tostring(P.serverName) or '-') out[#out+1]='max='..(mine and num(function() return P.serverMax end) or '-') out[#out+1]='type='..(mine and num(function() return P.serverType end) or '-') return table.concat(out,' ') end)() INTO server_info
LOG "warzone {server_info}"
