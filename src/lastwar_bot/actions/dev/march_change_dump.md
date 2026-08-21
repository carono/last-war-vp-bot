# What `SendChangeMarchToServer` and `OnChangeSingleMarch` touch — the re-target path.
# ru: Что трогают SendChangeMarchToServer и OnChangeSingleMarch — путь смены цели марша.
#
# The operator re-targets a squad that is standing in the field, with no pause, and a bare
# `SendCreateMarchMessage` at such a squad is refused in silence. `MarchUtil` turns out to
# have three names shaped like the answer — `OnChangeSingleMarch`, `SendChangeMarchToServer`
# and `OnChangeSingleFormation` — and this client still allows `string.dump`, so their
# constants can be read without opening a window: the client's Lua is not stripped, so the
# constant table names every field and every message id the function mentions.

READ_LUA (function() local function consts(f) if type(f) ~= 'function' then return '<not a function>' end local ok, d = pcall(string.dump, f) if not ok or d == nil then return '<dump refused>' end local got = {} for w in string.gmatch(d, '[%w%._]+') do if #w > 2 then got[#got + 1] = w end end local seen, out = {}, {} for _, w in ipairs(got) do if not seen[w] then seen[w] = true out[#out + 1] = w end end return table.concat(out, ' ') end local c = consts(MarchUtil.SendChangeMarchToServer) return string.sub(c, -700) end)() INTO send_change
LOG "SendChangeMarchToServer, the tail :: {send_change}"

READ_LUA (function() local function consts(f) if type(f) ~= 'function' then return '<not a function>' end local ok, d = pcall(string.dump, f) if not ok or d == nil then return '<dump refused>' end local got = {} for w in string.gmatch(d, '[%w%._]+') do if #w > 2 then got[#got + 1] = w end end local seen, out = {}, {} for _, w in ipairs(got) do if not seen[w] then seen[w] = true out[#out + 1] = w end end return table.concat(out, ' ') end return consts(MarchUtil.OnChangeSingleMarch) end)() INTO on_change
LOG "OnChangeSingleMarch :: {on_change}"

READ_LUA (function() local function consts(f) if type(f) ~= 'function' then return '<not a function>' end local ok, d = pcall(string.dump, f) if not ok or d == nil then return '<dump refused>' end local got = {} for w in string.gmatch(d, '[%w%._]+') do if #w > 2 then got[#got + 1] = w end end local seen, out = {}, {} for _, w in ipairs(got) do if not seen[w] then seen[w] = true out[#out + 1] = w end end return table.concat(out, ' ') end return consts(MarchUtil.OnChangeSingleFormation) end)() INTO on_change_formation
LOG "OnChangeSingleFormation :: {on_change_formation}"

READ_LUA (function() return 'WorldMarchChange=' .. tostring(MsgDefines.WorldMarchChange) end)() INTO msgid
LOG "the message id: {msgid}"
