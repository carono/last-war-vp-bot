# Can the client tell us its own connection is ready? — a read, for #1702.
# ru: Может ли клиент сам сказать, что соединение готово — только чтение, задача #1702.
#
# The client logs «Send msg when conn not ready» when something is sent into a link the
# server has already hung up on, and a march sent then leaves a squad on a march with no
# arrival time — which is what «отряд застрял в текстурах» looks like from the outside.
# The panel's own gate reads SOCKETS from outside the process; this asks whether the game
# will say it from inside, which is the reading a send can be gated on.

READ_LUA (function() local out = {} local function try(name, fn) local ok, v = pcall(fn) out[#out+1] = name .. '=' .. (ok and tostring(v) or 'no') end try('NetworkManager', function() return NetworkManager ~= nil end) try('NM.IsConnected', function() return NetworkManager.Instance:IsConnected() end) try('NM.isConnected', function() return NetworkManager.Instance.isConnected end) try('NM.connected', function() return NetworkManager.Instance.connected end) try('NM.IsReady', function() return NetworkManager.Instance:IsReady() end) try('ChatManager2.err', function() local CM = ChatManager2 local inst = CM.GetInstance and CM.GetInstance(CM) or CM return inst:IsConnectionError() end) local names = {} pcall(function() for k, v in pairs(NetworkManager) do local lk = string.lower(tostring(k)) if string.find(lk, 'conn') or string.find(lk, 'ready') or string.find(lk, 'state') then names[#names+1] = tostring(k) end end end) table.sort(names) out[#out+1] = 'NetworkManager members: ' .. table.concat(names, ',') return table.concat(out, ' | ') end)() INTO net
LOG "net readiness: {net}"
