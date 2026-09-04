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
# a pass-through, so nothing breaks, but that is why this is a dev tool and not an ability.
#
#   like     the part of a message NAME to catch, lower case. Everything is far too much.
#   seconds  how long to listen.
ARGS like = stamina
ARGS seconds = 10

LUA _G.__lw_catch = {} if _G.__lw_catch_old == nil then local old = SFSNetwork.HandleMessage if type(old) == 'function' then _G.__lw_catch_old = old SFSNetwork.HandleMessage = function(a1, a2, a3, a4) pcall(function() local name = string.lower(tostring(a1 or '')) if string.find(name, '{like}', 1, true) then local box = _G.__lw_catch local function d(v, lv) if type(v) ~= 'table' then return tostring(v) end if lv > 2 then return '{..}' end local p = {} local n = 0 for k, vv in pairs(v) do p[#p+1] = tostring(k) .. '=' .. d(vv, lv + 1) n = n + 1 if n > 25 then p[#p+1] = '..' break end end return '{' .. table.concat(p, ',') .. '}' end box[#box+1] = 'a1=' .. d(a1, 0) .. ' a2=' .. d(a2, 0) .. ' a3=' .. d(a3, 0) .. ' a4=' .. d(a4, 0) end end) return old(a1, a2, a3, a4) end end end

LOG "listening for «{like}» for {seconds} s"
WAIT {seconds}

READ_LUA (function() local box = _G.__lw_catch or {} if #box == 0 then return 'nothing caught' end return table.concat(box, ' || '):sub(1, 1800) end)() INTO caught
LOG "caught: {caught}"

READ_LUA (function() if _G.__lw_catch_old ~= nil then SFSNetwork.HandleMessage = _G.__lw_catch_old _G.__lw_catch_old = nil return 'unwrapped' end return 'nothing to unwrap' end)() INTO undone
LOG "{undone}"
