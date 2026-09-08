# Catch what the server actually answers, by message name, from the game's own Lua.
# ru: Поймать, что сервер на самом деле отвечает, по имени сообщения, прямо из Lua игры.
#
# NO SNIFFER (#2390). `SFSNetwork` is a plain Lua table holding three functions —
# `SendMessage`, `HandleMessage`, `GetMsgType` — so replacing `HandleMessage` with a
# closure that calls the old one reads every reply the client parses, by name, at the
# moment it arrives. That is one npcap listener fewer: a second capture over one
# interface starves the first, and a starved capture reads exactly like a deaf client.
#
# `docs/research/march-energy.md` says why this exists: it was written down there that a
# Lua wrapper «does not take — it is a C# static», and that was wrong. Two things decide
# whether one installs, and both are silent when got wrong (the statement answers `?`):
#
#   * FIXED PARAMETERS, never `...`. A vararg wrapper using `select('#', ...)` caught
#     nothing at all;
#   * NOTHING BUT PLAIN TABLES parked in `_G`. A dump helper stored as `_G.__x = function`
#     failed the same way; declared inside the closure it works.
#
# It unwraps itself at the end, so a run that finishes leaves the client as it found it.
# A run that is interrupted leaves the wrapper in place until the client restarts — it is
# a pass-through, so nothing breaks, and re-arming finds its own wrapper and adds no
# second one. That it is left at all is why this is a dev tool and not an ability.
#
#   like     the part of a message NAME to catch, lower case. Everything is far too much.
#   seconds  how long to listen.
# WHY NOTHING HERE LIVES ON `_G` (#2656). It all did, and on a live client that never
# worked: the build guards its own globals (`Global/GlobalProtect.lua` — an `__newindex`
# that REFUSES a new name and only logs «cannot be added/modified»). Every `_G.__lw_…`
# write was dropped, so the box was never created (the catch caught nothing, silently,
# inside its own `pcall`), the «already wrapped?» guard was never true, and the unwrap at
# the end had nothing to restore. Each run therefore stacked ANOTHER wrapper on
# `HandleMessage`, for the life of the client, each one calling the one below it — three
# runs on one afternoon is three frames added to every message the client receives, and
# enough of them is a stack overflow on the game's own dispatch. So the state hangs off
# one table on `DataCenter` (an ordinary field, not guarded), and re-arming recognises
# its own wrapper and does nothing.
ARGS like = stamina
ARGS seconds = 10

LUA (function() local B = DataCenter.__lw_wcatch if B == nil then B = {} DataCenter.__lw_wcatch = B end B.box = {} B.like = '{like}' if B.wrapper ~= nil and SFSNetwork.HandleMessage == B.wrapper then return end local old = SFSNetwork.HandleMessage if type(old) ~= 'function' then return end B.orig = old B.wrapper = function(a1, a2, a3, a4) pcall(function() local name = string.lower(tostring(a1 or '')) if string.find(name, B.like, 1, true) then local box = B.box local function d(v, lv) if type(v) ~= 'table' then return tostring(v) end if lv > 2 then return '{..}' end local p = {} local n = 0 for k, vv in pairs(v) do p[#p+1] = tostring(k) .. '=' .. d(vv, lv + 1) n = n + 1 if n > 25 then p[#p+1] = '..' break end end return '{' .. table.concat(p, ',') .. '}' end box[#box+1] = 'a1=' .. d(a1, 0) .. ' a2=' .. d(a2, 0) .. ' a3=' .. d(a3, 0) .. ' a4=' .. d(a4, 0) end end) return B.orig(a1, a2, a3, a4) end SFSNetwork.HandleMessage = B.wrapper end)()

LOG "listening for «{like}» for {seconds} s"
WAIT {seconds}

READ_LUA (function() local B = DataCenter.__lw_wcatch local box = (B and B.box) or {} if #box == 0 then return 'nothing caught' end return table.concat(box, ' || '):sub(1, 1800) end)() INTO caught
LOG "caught: {caught}"

READ_LUA (function() local B = DataCenter.__lw_wcatch if B == nil or B.wrapper == nil then return 'nothing to unwrap' end if SFSNetwork.HandleMessage ~= B.wrapper then return 'left in place — somebody wrapped on top of ours' end SFSNetwork.HandleMessage = B.orig B.wrapper = nil B.orig = nil return 'unwrapped' end)() INTO undone
LOG "{undone}"
