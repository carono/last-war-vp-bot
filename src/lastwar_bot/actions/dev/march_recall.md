# Walk the hunt's squad home with the game's own recall — #1702.
# ru: Вернуть отряд охоты домой штатным игровым отзывом — задача #1702.
#
# `MarchUtil.OnBackHome` is a real function of this client (listed by
# `dev/march_api_probe.md`), and it is what the game's own «вернуть» does. This is the
# repair for a squad left on a march the server never gave an arrival time to.
#
# Scheduled on the main thread, like every other order this repository sends: a call made
# straight from the hijack thread returns `true` and is dropped (docs/research/world-
# monsters.md, Finding 17).

LUA (function() local p = DataCenter.__lw_gold or {} local f = p.formation if f == nil then pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if math.floor(tonumber(v.index) or -1) == 2 then f = v.uuid end end end) end if f == nil then CS.UnityEngine.Debug.LogError('ACT recall no-formation') return end TimerManager:GetInstance():DelayInvoke(function() local ok, err = pcall(function() MarchUtil.OnBackHome(f) end) CS.UnityEngine.Debug.LogError('ACT recall ok=' .. tostring(ok) .. ' err=' .. tostring(err)) end, 0.5) end)()
WAIT 6
READ_LUA (function() local out = {} pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do local i = math.floor(tonumber(v.index) or -1) out[#out+1] = 'squad' .. i .. ' state=' .. tostring(v.state) .. ' canMarch=' .. tostring(v.canMarch) end end) local n = -1 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms ~= nil then n = ms.Count end end) out[#out+1] = 'marches=' .. tostring(n) return table.concat(out, ' | ') end)() INTO after
LOG "after the recall: {after}"
