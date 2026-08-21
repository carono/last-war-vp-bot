# What the game offers for RE-TARGETING a squad that is already standing in the field.
# ru: Что игра предлагает для смены цели у отряда, который уже стоит в поле.
#
# The operator does this by hand and reports no pause at all: «я НИКОГДА не бью от базы,
# ухожу далеко, атакую СРАЗУ С ПОЛЯ, и когда отряд заканчивает атаку, у меня уже намечена
# цель — другой зомби или шахта — и лага после атаки нет». A bare
# `MarchUtil.SendCreateMarchMessage` at a stationed squad is refused in silence (the purse
# does not move), so the game must reach it another way, and «зомби ИЛИ ШАХТА» says it is a
# general «change what this army is doing» rather than an attack special case.
#
# This is a READ. It names what exists — every field of `MarchUtil` and of the march data
# manager, plus whether the Lua sandbox still allows a function's constants to be read
# (`string.dump`, which the client's own tables were mapped with and which was closed for
# some routes in 2026-08). Nothing is pressed and nothing is sent.

READ_LUA (function() local out = {} local function names(t, label) local got = {} local ok = pcall(function() for k, v in pairs(t) do if type(k) == 'string' then got[#got + 1] = k .. (type(v) == 'function' and '()' or '') end end end) if not ok then return label .. '=<unreadable>' end table.sort(got) return label .. '[' .. tostring(#got) .. ']=' .. table.concat(got, ',') end local mu = nil pcall(function() mu = MarchUtil end) if mu ~= nil then out[#out + 1] = names(mu, 'MarchUtil') else out[#out + 1] = 'MarchUtil=nil' end return table.concat(out, ' | ') end)() INTO march_util
LOG "MarchUtil: {march_util}"

READ_LUA (function() local got = {} pcall(function() local m = DataCenter.WorldMarchDataManager for k, v in pairs(getmetatable(m) and getmetatable(m).__index or m) do if type(k) == 'string' then got[#got + 1] = k end end end) table.sort(got) return '[' .. tostring(#got) .. ']' .. table.concat(got, ',') end)() INTO march_mgr
LOG "WorldMarchDataManager: {march_mgr}"

READ_LUA (function() local ok, dump = pcall(function() return string.dump(function() return 1 end) end) if not ok or dump == nil then return 'string.dump=closed' end return 'string.dump=open len=' .. tostring(#dump) end)() INTO dumpable
LOG "sandbox: {dumpable}"

READ_LUA (function() local got = {} pcall(function() for k, v in pairs(MsgDefines) do if type(k) == 'string' and (string.find(string.lower(k), 'march') or string.find(string.lower(k), 'move') or string.find(string.lower(k), 'target')) then got[#got + 1] = k .. '=' .. tostring(v) end end end) table.sort(got) return '[' .. tostring(#got) .. ']' .. table.concat(got, ',') end)() INTO msgs
LOG "march-ish messages: {msgs}"
