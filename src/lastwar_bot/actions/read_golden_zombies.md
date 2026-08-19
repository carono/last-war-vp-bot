# Read what the golden-zombie chain has to work with: energy, its price, and how many are known.
# ru: Прочитать, с чем работает охота на золотых зомби: энергия, её цена и сколько зомби известно.
#
# A READ, and nothing else: it presses nothing, opens nothing, moves no camera and
# changes no state the attacking run keeps — so the panel may poll it while a chain is in
# flight, and it does.
#
# The answer lands in ONE variable, `golden`, as `key=value` pairs:
#
#     energy=55 cost=10 attacks=5 seen=135
#
#   * `energy`  — `LuaEntry.Player.stamina`, the purse a monster march is paid from.
#   * `cost`    — what the game charges for one solo attack right now
#                 (`MarchUtil.GetCostStaminaByTargetType`); 10 on 2026-08-19.
#   * `attacks` — how many attacks the purse still buys. Energy divided by price, and
#                 nothing else: the day has no separate quota on these.
#   * `atk`     — what the game prices an ATTACK march at, in THOUSANDTHS of a tile per
#                 second (765 live, i.e. 0.765). Whole numbers because the parser of
#                 this line keeps only digits.
#   * `col`     — the same for a GATHER march (1930 live) …
#   * `ratio`   — … and the one over the other, which is what says whether the fast
#                 approach is worth anything on this account: the march bonus and the
#                 gathering bonus are separate, so a player who has levelled one and not
#                 the other sees a different number. In hundredths: 252 live, i.e. 2.52.
#   * `seen`    — how many golden zombies (config id 1030000) the CLIENT knows about.
#                 That is as wide as what it has loaded, not as wide as the map: 11
#                 straight after entering the world, 135 after one lap of the server
#                 (`scan_map.md`). **`-1` means the question could not be asked** — the
#                 base is on screen and the world's own controller only exists on the
#                 map. Never drawn as «none»: «nobody asked» and «none there» are
#                 different answers.
#
# The attacking half is `attack_golden_zombies.md`; what is proven live and what is not
# is docs/research/golden-zombies.md.

READ_LUA (function() local energy = (function() local v = nil pcall(function() v = tonumber(LuaEntry.Player.stamina) end) if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end return math.floor(v or 0) end)() local cost = (function() local v = nil pcall(function() v = tonumber(MarchUtil.GetCostStaminaByTargetType(MarchTargetType.ATTACK_MONSTER)) end) if v == nil or v <= 0 then return 10 end return math.floor(v) end)() local seen = -1 local ws = _G.__LW_GOLD_WS local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) if not alive then ws = nil pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil pcall(function() n = mb:GetType().Name end) if n == 'WorldScene' then ws = mb break end end end) _G.__LW_GOLD_WS = ws end if ws ~= nil then seen = 0 pcall(function() local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() ids:Add(1030000, 1) local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(ws.CurTilePos, 2000, ids, res) seen = res.Count end) end local can = 0 if cost > 0 then can = math.floor(energy / cost) end local f = nil pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if f == nil then f = v.uuid end end end) local function sp(k) local v = nil pcall(function() v = MarchUtil.CalcMarchSpeedByConfig(k, f, nil, nil) end) return tonumber(v) or 0 end local sa, sc = sp(MarchTargetType.ATTACK_MONSTER), sp(MarchTargetType.COLLECT) local ratio = 0 if sa > 0 then ratio = sc / sa end return 'energy=' .. tostring(energy) .. ' cost=' .. tostring(cost) .. ' attacks=' .. tostring(can) .. ' seen=' .. tostring(seen) .. ' atk=' .. tostring(math.floor(sa * 1000 + 0.5)) .. ' col=' .. tostring(math.floor(sc * 1000 + 0.5)) .. ' ratio=' .. tostring(math.floor(ratio * 100 + 0.5)) end)() INTO golden
