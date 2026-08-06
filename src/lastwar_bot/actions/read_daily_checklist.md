# Read what the day still owes — every daily errand whose state the game will answer.
# ru: Прочитать, что ещё не сделано за сегодня — по каждому делу, о котором игра отвечает.
#
# A READ, and nothing else: it presses nothing, opens nothing, sends nothing and
# changes nothing, so it is safe to run beside anything and as often as anybody
# likes. It exists so that a checklist of daily errands is a READING of the game
# rather than a row of boxes somebody ticked by hand — a hand-ticked box says what
# the person remembers, and what the person remembers is exactly what a checklist is
# for not having to do.
#
# The whole answer is ONE line in ONE variable, `daily`, as `key=value` pairs
# separated by spaces:
#
#     base_ready=4 trucks_ready=1 donate_left=17 help_waiting=0 recruit_pending=0
#     gifts_pending=2 skills_ready=1 wounded=0 healed_ready=0 queues_help=3
#     decorations=0 steal_left=2 steal_cap=5 ghost_open=1 ghost_left=5 ghost_cap=5
#
# Every value is a whole number, and **`-` means the game would not answer** — a
# manager that is not loaded yet, a feature this account does not have. That is not
# the same as zero and must never be drawn as one: zero is «nothing left to do»,
# a dash is «nobody knows», and a checklist that shows the second as the first is
# lying about the one thing it is for.
#
# What each field is, and what it is worth:
#
#   base_ready       production buildings with at least one unit banked — the same
#                    `>= 1` the server itself accepts, so this is exactly how many
#                    `collect_base_resources` would harvest.
#   trucks_ready     supply trucks that have ARRIVED (the bubbles `collect_trucks`
#                    taps). One still on the road is not counted: it is not work yet.
#   donate_left      donation attempts still banked today for the alliance's
#                    priority tech. A daily quota — 0 means today's is spent.
#   help_waiting     alliancemates waiting for help, by either of the two readings
#                    (the client's list, and the red-point count a push bumps).
#   recruit_pending  survivors standing in the city queues waiting to be recruited.
#   gifts_pending    gift-bearing visitors standing in the same queues.
#   skills_ready     profession skills that are off cooldown and need no target.
#   wounded          hospital entries with wounded in them (0 = nobody hurt).
#   healed_ready     1 while a finished heal is waiting to be collected.
#   queues_help      working queues with no help request standing — the ones
#                    «попросить ускорить» would ask the alliance about.
#   decorations      upgrade STEPS banked as spare duplicates, not decorations.
#   steal_left       secret-task robberies left today, of `steal_cap` (5 live).
#   ghost_open       1 while «Операция Призрак» is running today. It is a ONE DAY A
#                    WEEK event: 0 means the whole feature is dark and the two
#                    numbers beside it mean nothing.
#   ghost_left       ghost-recon robberies left today, of `ghost_cap`.
#
# Every field is read inside its own `pcall`, so a manager that is missing costs one
# dash and not the whole line — the reading of thirteen things must not be all or
# nothing, because the one that fails is usually the feature the account has not
# unlocked.
#
# ONE round trip for all of it, on purpose. A VM call costs about 0.15 s and the
# work inside it is free (docs/research/alliance-tech-donate.md), so sixteen
# `READ_LUA` lines would be sixteen times the price of this one, and this one runs
# every few minutes while the panel is open.
#
# The expressions are the SAME ones the presses themselves are gated on
# (`tools/lib/lua_actions.py`), copied here rather than re-invented, and
# `tests/test_panel_checklist.py` fails if any of them stops matching. A count that
# said one thing to the checklist and another to the button would be worse than no
# count at all.
#
# Who reads it: the panel's «Чеклист» tab (`panel/tabs/checklist/`), which turns the
# line into a row per errand — done, still to do, or «состояние неизвестно» for a
# dash. Nothing else in the bot depends on the shape.

READ_LUA (function() local out={} local function put(k,f) local ok,v=pcall(f) if not ok or v==nil then out[#out+1]=k..'=-' return end local n=tonumber(v) if n~=nil then v=math.floor(n) end out[#out+1]=k..'='..tostring(v) end put('base_ready',function() return (function() local plm=DataCenter.ProductLineManager local n=0 for _,u in pairs(plm:GetAllBuildUuids() or {}) do local ok,stor=pcall(function() return plm:GetBuildingCurrStorage(u) end) if ok and (stor or 0)>=1 then n=n+1 end end return n end)() end) put('trucks_ready',function() return (function() local m=DataCenter.BuildBubbleManager local BT=_G.BuildBubbleType if not m or not BT then return 0 end local n=0 for _,v in pairs(m.allBuildBubble or {}) do local ty=v.param and v.param.buildBubbleType if ty==BT.TruckReward or ty==BT.TruckReady then n=n+1 end end return n end)() end) put('donate_left',function() return DataCenter.AllianceScienceDataManager:GetResDonateRestCount() end) put('help_waiting',function() return math.max((function() local n = 0 for _, it in ipairs(DataCenter.AllianceHelpDataManager:GetAllianceHelpList() or {}) do if not it.isSelf then n = n + 1 end end return n end)(), (DataCenter.AllianceHelpDataManager:GetHelpNum() or 0)) end) put('recruit_pending',function() return (function() local n = 0 local __M = DataCenter.CityVisitorManager for __q = 1, 2 do local __ok, __lst = pcall(__M.GetQueueAllVisitorData, __M, __q) if __ok and __lst then for _, e in ipairs(__lst) do local d, m = e and e.data, e and e.model if d and m and d.eventType == ((VisitorType and VisitorType.RECRUITMENT) or 3) and m.isArrival and not m.isFinish then n = n + 1 end end end end return n end)() end) put('gifts_pending',function() return (function() local n = 0 local __M = DataCenter.CityVisitorManager for __q = 1, 2 do local __ok, __lst = pcall(__M.GetQueueAllVisitorData, __M, __q) if __ok and __lst then for _, e in ipairs(__lst) do local d, m = e and e.data, e and e.model if d and m and d.eventType == ((VisitorType and VisitorType.GIFT) or 2) and m.isArrival and not m.isFinish then n = n + 1 end end end end return n end)() end) put('skills_ready',function() return #(function() local M=DataCenter.MasteryManager local d=M:GetData() if not d then return {} end local now=UITimeManager:GetInstance():GetServerTime() local fired=M.__lw_fired or {} local out={} for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do local sid=M:GetCurSkillIdByMasteryId(mid) local t=sid and M:GetSkillTemplate(sid) if t and t.active_skills and t:CheckUsePosition(MasterySkillUsePosType.SkillView) and M:GetMasteryGroupSkillState(mid)==MasterySkillState.Normal and (now-(fired[sid] or 0))>120000 then out[#out+1]=sid end end return out end)() end) put('wounded',function() return (function() local m = DataCenter and DataCenter.HospitalManager if not m or type(m.allHospital) ~= 'table' then return 0 end local n = 0 for _, h in pairs(m.allHospital) do if type(h)=='table' and type(h.dead)=='number' and h.dead > 0 then n = n + 1 end end return n end)() end) put('healed_ready',function() return (function() local q = DataCenter and DataCenter.QueueDataManager if not q or not NewQueueType or not NewQueueState then return 0 end local ok, queue = pcall(function() return q:GetQueueByType(NewQueueType.Hospital) end) if not ok or type(queue) ~= 'table' then return 0 end if queue.state == NewQueueState.Finish then return 1 end return 0 end)() end) put('queues_help',function() return (function() local q = DataCenter and DataCenter.QueueDataManager if not q or type(q.queueDic) ~= 'table' or not NewQueueState then return 0 end local n = 0 for _, v in pairs(q.queueDic) do if type(v)=='table' and v.state == NewQueueState.Work and v.isHelped ~= 1 then n = n + 1 end end return n end)() end) put('decorations',function() return (function() local bm=DataCenter.BuildManager local function scan(cb) for itemId in pairs(bm:GetAllDecoratorBuildingData() or {}) do local ok,d=pcall(function() return bm:GetMaxLvBuildDataByBuildId(itemId) end) if ok and d then local ok2,adv=pcall(function() return BuildingUtils.IsExistAdvanceUpgrade(itemId,d.level) end) if ok2 and adv then local ok3,cells=pcall(function() return BuildingUtils.GetDecorateUpLevelBuilds(d) end) local steps=0 if ok3 and type(cells)=='table' then for _,c in pairs(cells) do local n=tonumber(c.count) if n and n>0 then steps=steps+n end end end if cb(itemId,d,steps) then return true end end end end return false end  local n=0 scan(function(_,_,steps) n=n+steps end) return n end)() end) put('steal_left',function() return (function() local M=DataCenter.ActDispatchTaskDataManager local cap=tonumber(M:GetDispatchSetting('steal_count')) or 0 local used=tonumber(M:GetTodayStealNum()) or 0 local left=cap-used if left<0 then left=0 end return left end)() end) put('steal_cap',function() return (tonumber(DataCenter.ActDispatchTaskDataManager:GetDispatchSetting('steal_count')) or 0) end) put('ghost_open',function() return (DataCenter.ActGhostreconManager:IsOpenDay() and 1 or 0) end) put('ghost_left',function() return (function() local M=DataCenter.ActGhostreconManager local cfg=M:GetNowSettingCfg() local cap=tonumber(cfg and cfg.stealCount) or 0 local used=tonumber(M.stealTimes) or 0 local left=cap-used if left<0 then left=0 end return left end)() end) put('ghost_cap',function() return (function() local cfg=DataCenter.ActGhostreconManager:GetNowSettingCfg() return tonumber(cfg and cfg.stealCount) or 0 end)() end) return table.concat(out,' ') end)() INTO daily
