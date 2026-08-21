# Where does the client say the squad actually IS? A read, for #1702.
# ru: Где, по данным клиента, реально стоит отряд — только чтение.
#
# The pick measures from `p.anchor` — the tile the hunt last SENT to — and from the base
# when there is none. Neither is «where the squad is standing», and the operator watched
# the difference: a zombie beside the squad, a choice hundreds of tiles away.

READ_LUA (function() local out = {} pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do local i = math.floor(tonumber(v.index) or -1) local bits = {'squad' .. i} for _, f in ipairs({'state', 'canMarch', 'pointId', 'point', 'tileIndex', 'posX', 'posY', 'x', 'y', 'worldPos', 'marchUuid'}) do local val = nil pcall(function() val = v[f] end) if val ~= nil then bits[#bits+1] = f .. '=' .. tostring(val) end end out[#out+1] = table.concat(bits, ' ') end end) return table.concat(out, ' || ') end)() INTO formations
LOG "formations: {formations}"

READ_LUA (function() local out = {} local now = 0 pcall(function() now = tonumber(UITimeManager.Instance:GetServerTime()) or 0 end) pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms == nil then return end for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) if m ~= nil then local bits = {'m' .. i} for _, f in ipairs({'endTime', 'targetPointId', 'pointId', 'endPointId', 'startPointId', 'formationUuid', 'armyUuid', 'state'}) do local val = nil pcall(function() val = m[f] end) if val ~= nil then bits[#bits+1] = f .. '=' .. tostring(val) end end out[#out+1] = table.concat(bits, ' ') end end end) return table.concat(out, ' || ') end)() INTO marches
LOG "marches: {marches}"

READ_LUA (function() local p = DataCenter.__lw_gold or {} local a = p.anchor local h = p.home return 'anchor=' .. tostring(a and (a.x .. ',' .. a.y) or '-') .. ' home=' .. tostring(h and (h.x .. ',' .. h.y) or '-') .. ' registry=' .. tostring(#(p.targets or {})) end)() INTO parked
LOG "what the run holds: {parked}"

# …and what the SCENE is drawing for our own armies: the client hands no tile through
# the formation or the march, so the object on the map may be the only place it is.
READ_LUA (function() local out = {} local n = 0 pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local cn = nil pcall(function() cn = mb:GetType().Name end) if cn ~= nil and (string.find(cn, 'March') or string.find(cn, 'Army')) then local go, nm = nil, nil pcall(function() go = mb.gameObject nm = tostring(go.name) end) if nm ~= nil then n = n + 1 if #out < 8 then local tile = '?' pcall(function() local t = SceneUtils.WorldToTileIndex(go.transform.position) local tp = SceneUtils.IndexToTilePos(t) tile = tostring(tp.x) .. ',' .. tostring(tp.y) end) out[#out+1] = cn .. ':' .. nm .. '@' .. tile end end end end end) return 'objects=' .. tostring(n) .. ' [' .. table.concat(out, ' | ') .. ']' end)() INTO drawn
LOG "armies drawn: {drawn}"
