# The same question, narrowed: what NAMES the client has for moving an army that has landed.
# ru: Тот же вопрос уже: как клиент называет смену задания уже приземлившемуся отряду.
#
# The first probe answered «MarchUtil has 84 fields» and truncated. This one filters:
# anything whose name looks like a re-target, a continue, a next order, or the message
# ids that carry one. It also reads the dispatch screen's own controller, which is where
# the player's tap goes — and `string.dump` came back OPEN on this client, so a function's
# constants can be read without opening a window.

READ_LUA (function() local got = {} pcall(function() for k, v in pairs(MarchUtil) do local l = string.lower(k) if string.find(l, 'change') or string.find(l, 'again') or string.find(l, 'next') or string.find(l, 'continue') or string.find(l, 'retarget') or string.find(l, 'move') or string.find(l, 'click') or string.find(l, 'send') or string.find(l, 'start') or string.find(l, 'back') then got[#got + 1] = k end end end) table.sort(got) return '[' .. tostring(#got) .. ']' .. table.concat(got, ',') end)() INTO mu_hits
LOG "MarchUtil, the re-target shaped names: {mu_hits}"

READ_LUA (function() local got = {} pcall(function() for k, v in pairs(MsgDefines) do if type(v) == 'string' and (string.find(v, 'march') or string.find(v, 'move')) then got[#got + 1] = k .. '=' .. v end end end) table.sort(got) return '[' .. tostring(#got) .. ']' .. table.concat(got, ' ') end)() INTO msg_hits
LOG "messages whose id mentions a march or a move: {msg_hits}"

READ_LUA (function() local ok, out = pcall(function() local c = UIManager.Instance.windowsConfig[UIWindowNames.UIFormationSelectListV2].Ctrl local got = {} for k, v in pairs(c) do if type(v) == 'function' then got[#got + 1] = k end end table.sort(got) return '[' .. tostring(#got) .. ']' .. table.concat(got, ',') end) if not ok then return 'ctrl=<' .. tostring(out) .. '>' end return out end)() INTO ctrl
LOG "the dispatch screen's controller: {ctrl}"
