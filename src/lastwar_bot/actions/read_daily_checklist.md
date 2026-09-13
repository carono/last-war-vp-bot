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
#   recruit_pending  survivors standing in the city queues waiting to be recruited,
#                    counted whether or not they have finished WALKING to the gate. The
#                    press is right to refuse one that has not arrived; a board that hid
#                    them said «0» over a queue of eight, because a visitor is re-created
#                    and walks the whole way again every time the client enters the base
#                    (#2843, and the press waits the walk out now).
#   gifts_pending    gift-bearing visitors standing in the same queues, same rule.
#   skills_ready     profession skills that are off cooldown and need no target.
#   winwin_open      1 when «Взаимовыгодное сотрудничество» is on this profession's
#                    tree AND the alliance has a War Leader with a base to aim at;
#                    0 when either is missing, a dash when the tree cannot be read.
#   winwin_left      1 when its charge is banked, 0 when it is on cooldown.
#   winwin_cap       1 — the skill banks one charge and never more.
#   winwin_next_min  minutes until the charge comes back, 0 when it is banked now.
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
#   trucks_send_left trade-truck dispatches still banked today, of
#                    `trucks_send_cap`. A DIFFERENT truck from `trucks_ready`:
#                    that one has arrived at the base and is waiting to be
#                    emptied, this one is the fleet the trade station sends out
#                    to another server. A daily quota — 0 means today's is spent.
#   trucks_send_cap  how many may go out today at all. Four to start with and
#                    more with the «Extra Truck» tech, so it is read rather than
#                    assumed.
#   explorer_keys    «Ключи исследователя» in the bag — what the chests in the
#                    mobile squad's window are opened with. A dash while the
#                    activity is not running on this account, which is not the
#                    same as «no keys».
#   explorer_chests  how many chests those keys will open right now (the price is
#                    the game's own, read rather than written down). A dash for
#                    the same reason as the line above.
#   mail_gifts       attachments still waiting in the Mail, over every tab — the
#                    same badge the tabs draw (`MailDataManager.group[<tab>]
#                    .unrewardCount`). Local to the client: nothing is asked of
#                    the server for it, and 0 means every gift has been taken.
#   trucks_idle      trucks that could go out RIGHT NOW: standing at the station
#                    and inside what is left of the allowance. «How many presses
#                    are available», not «how many trucks exist».
#   recover_tasks    day-pools of secret-task rewards nobody collected, still
#   recover_trucks   waiting behind the two «Вернуть» buttons — one row per server
#                    day, unclaimed ones only (`state == nil`). A dash on an
#                    account the feature is not open for, never a 0: «nothing to
#                    take» and «cannot take anything» must not look alike. Read off
#                    the list the client already holds; the claim itself asks the
#                    server for a fresh one (`collect_secret_tasks.md`,
#                    `send_trucks.md`).
#   tavern_free      free pulls the tavern is offering right now — one per hero
#                    banner the client is showing plus the survivors' one, each
#                    asked of its OWN `CanFreeRecruit()`. A dash when no banner
#                    answers at all, which is what a client that is not logged in
#                    looks like.
#   radar_free       room left on the radar board — its ceiling minus what is on
#                    it. A dash on an account whose radar is not there.
#   radar_helpable   errands on the board «Быстро выполнить» would set running —
#                    the help-an-alliancemate kind, the only one needing no march.
#   ministry_post    the id of the government post held right now, 0 for none. It
#                    is the reading «did the application go through» is answered
#                    with, and it is what says whether we are a minister now.
#   alstar_open      1 while «Звезда альянса» — the weekly ceremony — is running.
#                    A dash on an account whose client has never been told about
#                    one, which is not the same as «no ceremony this week».
#   alstar_stars     stars of the week on the ceremony board (fourteen live), or a
#                    dash while the board has not been fetched.
#   alstar_liked     how many of those stars carry a like of ours already. The
#                    likes are free and each star takes one.
#   alstar_chests    chests of the ceremony taken, of two: one for having liked,
#                    one for taking part.
#   algift_ord       alliance gifts of the ORDINARY chest still unclaimed, and
#   algift_prem      the same for the premium/privilege chest. Both are a dash
#                    until somebody has asked the server for the list at all — the
#                    client holds no gift records before that, and «0» over a
#                    never-asked list is the exact lie this reading exists to avoid.
#                    `collect_alliance_gifts` does the asking, and after it the
#                    server's own `push.alliance.reward.new` keeps the counts up to
#                    date, so nothing here ever asks (#2588).
#   hidden_open      1 while «Скрытые Сокровища» — the week's dig board — is
#                    running, 0 once the week has ended, a dash on a client that
#                    has never been told about the activity.
#   hidden_score     compasses earned this week, lifted to the highest reward step
#                    the server says was COLLECTED. The raw count does not move
#                    until the client is restarted, and the collected step is the
#                    server's own word that its target was reached (#2597).
#   hidden_goal      the week's own cap for those compasses — the game's number,
#                    not ours.
#   hidden_digs      how many digs the map fragments in the bag still allow: the
#                    smallest of the seven fragment counts, and nothing else.
#   arena_open       1 while the arena building has an event running — either the 3v3
#                    challenge or «Арена Шторма», which take turns in it. Read off the
#                    two managers' own windows, so no ask goes out for it.
#   arena_left       what the storm arena still owes today: the battles missing from
#                    the day's target PLUS the daily boxes the count has already
#                    reached and nobody has taken. Zero therefore means «five battles
#                    fought AND every box in», which is what «сделано» has to mean for
#                    a row somebody reads at a glance.
#   arena_cap        the biggest daily box's own number of battles — the game's five,
#                    never ours.
#
# **The two arena counts are a dash whenever the client has not been told them.** The
# storm arena's rank data comes and goes on the client, and this reading asks the game
# for NOTHING — so a board opened on a client that has not looked at the arena says
# «состояние неизвестно», which is the truth. Pressing «Выполнить» asks properly
# (`actions/read_storm_arena.md`) and the row follows a second later. The 3v3 half is a
# dash always: its day is counted in WINS, and the server tells nobody that number until
# a battle is fought (docs/research/arena-3v3.md §4).
#
# All three are a dash on an account where the trade station is still locked (it
# opens at base level 8), because a locked client answers «0 sent today» just
# like an idle one does — and drawn straight that is an errand the person could
# never finish.
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

READ_LUA (function() local out={} local function put(k,f) local ok,v=pcall(f) if not ok or v==nil then out[#out+1]=k..'=-' return end local n=tonumber(v) if n~=nil then v=math.floor(n) end out[#out+1]=k..'='..tostring(v) end put('base_ready',function() return (function() local plm=DataCenter.ProductLineManager local n=0 for _,u in pairs(plm:GetAllBuildUuids() or {}) do local ok,stor=pcall(function() return plm:GetBuildingCurrStorage(u) end) if ok and (stor or 0)>=1 then n=n+1 end end return n end)() end) put('trucks_ready',function() return (function() local m=DataCenter.BuildBubbleManager local BT=_G.BuildBubbleType if not m or not BT then return 0 end local n=0 for _,v in pairs(m.allBuildBubble or {}) do local ty=v.param and v.param.buildBubbleType if ty==BT.TruckReward or ty==BT.TruckReady then n=n+1 end end return n end)() end) put('donate_left',function() return DataCenter.AllianceScienceDataManager:GetResDonateRestCount() end) put('help_waiting',function() return math.max((function() local n = 0 for _, it in ipairs(DataCenter.AllianceHelpDataManager:GetAllianceHelpList() or {}) do if not it.isSelf then n = n + 1 end end return n end)(), (DataCenter.AllianceHelpDataManager:GetHelpNum() or 0)) end) put('recruit_pending',function() return (function() local n = 0 local __M = DataCenter.CityVisitorManager for __q = 1, 2 do local __ok, __lst = pcall(__M.GetQueueAllVisitorData, __M, __q) if __ok and __lst then for _, e in ipairs(__lst) do local d, m = e and e.data, e and e.model if d and m and d.eventType == ((VisitorType and VisitorType.RECRUITMENT) or 3) and not m.isFinish then n = n + 1 end end end end return n end)() end) put('gifts_pending',function() return (function() local n = 0 local __K = {} if VisitorType then for __k, __v in pairs(VisitorType) do if type(__v) == 'number' and tostring(__k):lower():find('gift', 1, true) then __K[__v] = true end end end if next(__K) == nil then __K[2] = true end local __M = DataCenter.CityVisitorManager for __q = 1, 2 do local __ok, __lst = pcall(__M.GetQueueAllVisitorData, __M, __q) if __ok and __lst then for _, e in ipairs(__lst) do local d, m = e and e.data, e and e.model if d and m and __K[d.eventType] and not m.isFinish then n = n + 1 end end end end return n end)() end) put('skills_ready',function() return #(function() local M=DataCenter.MasteryManager local d=M:GetData() if not d then return {} end local now=UITimeManager:GetInstance():GetServerTime() local fired=M.__lw_fired or {} local out={} for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do local sid=M:GetCurSkillIdByMasteryId(mid) local t=sid and M:GetSkillTemplate(sid) if t and t.active_skills and t:CheckUsePosition(MasterySkillUsePosType.SkillView) and M:GetMasteryGroupSkillState(mid)==MasterySkillState.Normal and (now-(fired[sid] or 0))>120000 then out[#out+1]=sid end end return out end)() end) put('winwin_open',function() return (function() local M=DataCenter.MasteryManager local d=nil pcall(function() d=M:GetData() end) if not d then return nil end local node=nil for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do if M:GetCurSkillIdByMasteryId(mid)==10417 then node=mid break end end if not node then return 0 end local n=0 pcall(function() for _,v in pairs(DataCenter.AllianceCareerManager:GetAllianceMemberListByCareer(102) or {}) do if type(v)=='table' and (v.pointId or 0)>0 then n=n+1 end end end) if n<1 then return 0 end return 1 end)() end) put('winwin_left',function() return (function() local M=DataCenter.MasteryManager local d=nil pcall(function() d=M:GetData() end) if not d then return nil end local node=nil for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do if M:GetCurSkillIdByMasteryId(mid)==10417 then node=mid break end end if not node then return nil end if M:GetMasteryGroupSkillState(node)==MasterySkillState.Normal then return 1 end return 0 end)() end) put('winwin_cap',function() return (function() local M=DataCenter.MasteryManager local d=nil pcall(function() d=M:GetData() end) if not d then return nil end local node=nil for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do if M:GetCurSkillIdByMasteryId(mid)==10417 then node=mid break end end if not node then return nil end return 1 end)() end) put('winwin_next_min',function() return (function() local M=DataCenter.MasteryManager local d=nil pcall(function() d=M:GetData() end) if not d then return nil end local node=nil for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do if M:GetCurSkillIdByMasteryId(mid)==10417 then node=mid break end end if not node then return nil end local avail=0 pcall(function() avail=d:GetSkillAvailableTime(10417) or 0 end) if avail<=0 then return 0 end local left=avail-UITimeManager:GetInstance():GetServerTime() if left<0 then left=0 end return math.floor(left/60000) end)() end) put('wounded',function() return (function() local m = DataCenter and DataCenter.HospitalManager if not m or type(m.allHospital) ~= 'table' then return 0 end local n = 0 for _, h in pairs(m.allHospital) do if type(h)=='table' and type(h.dead)=='number' and h.dead > 0 then n = n + 1 end end return n end)() end) put('healed_ready',function() return (function() local q = DataCenter and DataCenter.QueueDataManager if not q or not NewQueueType or not NewQueueState then return 0 end local ok, queue = pcall(function() return q:GetQueueByType(NewQueueType.Hospital) end) if not ok or type(queue) ~= 'table' then return 0 end if queue.state == NewQueueState.Finish then return 1 end return 0 end)() end) put('queues_help',function() return (function() local q = DataCenter and DataCenter.QueueDataManager if not q or type(q.queueDic) ~= 'table' or not NewQueueState then return 0 end local n = 0 for _, v in pairs(q.queueDic) do if type(v)=='table' and v.state == NewQueueState.Work and v.isHelped ~= 1 then n = n + 1 end end return n end)() end) put('decorations',function() return (function() local bm=DataCenter.BuildManager local function scan(cb) for itemId in pairs(bm:GetAllDecoratorBuildingData() or {}) do local ok,d=pcall(function() return bm:GetMaxLvBuildDataByBuildId(itemId) end) if ok and d then local ok2,adv=pcall(function() return BuildingUtils.IsExistAdvanceUpgrade(itemId,d.level) end) if ok2 and adv then local ok3,cells=pcall(function() return BuildingUtils.GetDecorateUpLevelBuilds(d) end) local steps=0 if ok3 and type(cells)=='table' then for _,c in pairs(cells) do local n=tonumber(c.count) if n and n>0 then steps=steps+n end end end if cb(itemId,d,steps) then return true end end end end return false end  local n=0 scan(function(_,_,steps) n=n+steps end) return n end)() end) put('steal_left',function() return (function() local M=DataCenter.ActDispatchTaskDataManager local cap=tonumber(M:GetDispatchSetting('steal_count')) or 0 local used=tonumber(M:GetTodayStealNum()) or 0 local left=cap-used if left<0 then left=0 end return left end)() end) put('steal_cap',function() return (tonumber(DataCenter.ActDispatchTaskDataManager:GetDispatchSetting('steal_count')) or 0) end) put('ghost_open',function() return (DataCenter.ActGhostreconManager:IsOpenDay() and 1 or 0) end) put('ghost_left',function() return (function() local M=DataCenter.ActGhostreconManager local cfg=M:GetNowSettingCfg() local cap=tonumber(cfg and cfg.stealCount) or 0 local used=tonumber(M.stealTimes) or 0 local left=cap-used if left<0 then left=0 end return left end)() end) put('ghost_cap',function() return (function() local cfg=DataCenter.ActGhostreconManager:GetNowSettingCfg() return tonumber(cfg and cfg.stealCount) or 0 end)() end) put('trucks_send_left',function() return (function() local M=DataCenter and DataCenter.LWMyStationDataManager if not M or M:IsTruckFunctionLock() then return nil end local cap=tonumber((M:GetMaxDailyCount())) or 0 local used=tonumber((M:GetDepartureCount())) or 0 local left=cap-used if left<0 then left=0 end return left end)() end) put('trucks_send_cap',function() return (function() local M=DataCenter and DataCenter.LWMyStationDataManager if not M or M:IsTruckFunctionLock() then return nil end return tonumber((M:GetMaxDailyCount())) or 0 end)() end) put('trucks_idle',function() return (function() local M=DataCenter and DataCenter.LWMyStationDataManager if not M or M:IsTruckFunctionLock() then return nil end return tonumber((M:GetRealReadyCount())) or 0 end)() end) put('recover_tasks',function() return (function() local M=DataCenter and DataCenter.DispatchRecoverManager if not M then return nil end local open=false pcall(function() open=M:IsDispatchRecoverOpen() and true or false end) if not open then return nil end local n=0 for _,row in pairs(M.dispatchRecoverList or {}) do if row.state==nil then n=n+1 end end return n end)() end) put('recover_trucks',function() return (function() local M=DataCenter and DataCenter.DispatchRecoverManager if not M then return nil end local open=false pcall(function() open=M:IsTrainRecoverOpen() and true or false end) if not open then return nil end local n=0 for _,row in pairs(M.trainRecoverList or {}) do if row.state==nil then n=n+1 end end return n end)() end) put('mail_gifts',function() return (function() local M=DataCenter and DataCenter.MailDataManager if not M or type(M.group)~='table' then return nil end local n=0 for gid,g in pairs(M.group) do if type(g)=='table' then local c=tonumber(g.unrewardCount) or 0 if c<=0 then local ok,m=pcall(function() return M:GetMailUnRewardCountByGroup(gid) end) if ok then c=tonumber(m) or 0 end end if c>0 then n=n+c end end end return n end)() end) put('explorer_keys',function() return (function() local M=DataCenter and DataCenter.ExplorerTreasureManager if M==nil then return nil end local open=false pcall(function() open=M:IsOpen() and true or false end) if not open then return nil end local have=0 pcall(function() have=math.floor((M:GetTreasureHaveItemNum() or 0)+0) end) return have end)() end) put('explorer_chests',function() return (function() local M=DataCenter and DataCenter.ExplorerTreasureManager if M==nil then return nil end local open=false pcall(function() open=M:IsOpen() and true or false end) if not open then return nil end local have,need=0,0 pcall(function() have=math.floor((M:GetTreasureHaveItemNum() or 0)+0) end) pcall(function() need=math.floor((M:GetTreasureOpenNeedItemNum() or 0)+0) end) if need<=0 then need=math.floor(tonumber(M.treasureNeedNum) or 0) end if need<=0 then return nil end return math.floor(have/need) end)() end) put('tavern_free',function() return (function() local M = DataCenter.LotteryDataManager if M == nil then return nil end local seen, free = 0, 0 pcall(function() for _, id in pairs(M.curRecruitIdList or {}) do local v = nil pcall(function() v = M:GetLotteryDataById(id) end) if v == nil then pcall(function() v = M:GetLotteryDataById(tostring(id)) end) end if v ~= nil then seen = seen + 1 local ok = false pcall(function() ok = v:CanFreeRecruit() and true or false end) if ok then free = free + 1 end end end end) local wl = nil pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) if wl ~= nil then seen = seen + 1 local ok = false pcall(function() ok = wl:CanFreeRecruit() and true or false end) if ok then free = free + 1 end end if seen == 0 then return nil end return free end)() end) put('radar_free',function() return (function() local M=DataCenter and DataCenter.RadarCenterDataManager if not M then return nil end return (function() local a = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetMaxDetectNum() end) return (ok and tonumber(n)) or 0 end)() local b = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() local d = a - b if d < 0 then d = 0 end return d end)() end)() end) put('radar_helpable',function() return (function() local M=DataCenter and DataCenter.RadarCenterDataManager if not M then return nil end return (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local n = 0 for _, e in pairs(rawget(M, 'events') or {}) do local t = rawget(e, 'template') if rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH and t and rawget(t, 'type') == DetectEventType.HELPER and not rawget(e, 'isFrozen') then n = n + 1 end end return n end)() end)() end) put('ministry_post',function() return (function() local ok, p = pcall(function() return DataCenter.OfficialApplyManager:GetOwnPositionId() end) if not ok or p == nil then p = DataCenter.GovernmentManager.self_positionId end return tonumber(p) or 0 end)() end) put('alstar_open',function() local M=DataCenter and DataCenter.AllianceStarManager if M==nil then return nil end return (M.hasCeremony and 1 or 0) end) put('alstar_stars',function() local M=DataCenter and DataCenter.AllianceStarManager if M==nil or type(M.ceremonyThumbs)~='table' then return nil end local n=0 for _,l in pairs(M.ceremonyThumbs) do for _,v in pairs(l or {}) do if v.isStar then n=n+1 end end end if n==0 then return nil end return n end) put('alstar_liked',function() local M=DataCenter and DataCenter.AllianceStarManager if M==nil or type(M.ceremonyThumbs)~='table' then return nil end local n,seen=0,0 for _,l in pairs(M.ceremonyThumbs) do for _,v in pairs(l or {}) do if v.isStar then seen=seen+1 if type(v.selfThumbs)=='table' and next(v.selfThumbs)~=nil then n=n+1 end end end end if seen==0 then return nil end return n end) put('alstar_chests',function() local M=DataCenter and DataCenter.AllianceStarManager if M==nil or type(M.ceremonyFullData)~='table' then return nil end local n=0 local ok,e=pcall(function() return M:GetEmojiThumbsRewardInfo() end) local liked=0 for _,l in pairs(M.ceremonyThumbs or {}) do for _,v in pairs(l or {}) do if v.isStar and type(v.selfThumbs)=='table' and next(v.selfThumbs)~=nil then liked=liked+1 end end end if ok and type(e)=='table' then if (tonumber(e.claimedIndex) or 0)>0 then n=n+1 end elseif liked>0 then n=n+1 end if M.ceremonyFullData.participateReceive then n=n+1 end return n end) put('algift_ord',function() local M=DataCenter and DataCenter.AllianceGiftDataManager if M==nil then return nil end local seen,n=0,0 for _,t in ipairs({1,2}) do local ok,l=pcall(function() return M:GetGiftInfoList(t) end) if ok and type(l)=='table' then for _,g in pairs(l) do seen=seen+1 if t==1 and (tonumber(g.receiveState) or -1)==0 then n=n+1 end end end end if seen==0 then return nil end return n end) put('algift_prem',function() local M=DataCenter and DataCenter.AllianceGiftDataManager if M==nil then return nil end local seen,n=0,0 for _,t in ipairs({1,2}) do local ok,l=pcall(function() return M:GetGiftInfoList(t) end) if ok and type(l)=='table' then for _,g in pairs(l) do seen=seen+1 if t==2 and (tonumber(g.receiveState) or -1)==0 then n=n+1 end end end end if seen==0 then return nil end return n end) put('hidden_open',function() local B=DataCenter and DataCenter.DigTreasureBoxRewardManager if B==nil then return nil end local act=0 pcall(function() act=math.floor((B:GetActId() or 0)+0) end) local now,closes=0,0 pcall(function() now=math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0)+0) end) pcall(function() for _,a in pairs(DataCenter.ActivityListDataManager.activityList or {}) do if math.floor((tonumber(tostring(a.activityId)) or 0)+0)==act then closes=math.floor(((tonumber(tostring(a.endTime)) or 0)/1000)+0) end end end) if closes==0 or (now>0 and now<closes) then return 1 end return 0 end) put('hidden_score',function() local B=DataCenter and DataCenter.DigTreasureBoxRewardManager if B==nil then return nil end local score=0 pcall(function() score=math.floor((B:GetBoxRewardItemCount() or 0)+0) end) local earned=0 pcall(function() for _,row in ipairs(B:GetTreasureBoxRewardList() or {}) do local t=math.floor((tonumber(tostring(row.target)) or 0)+0) local g=math.floor((tonumber(tostring(row.isReward)) or 0)+0) if g~=0 and t>earned then earned=t end end end) if earned>score then score=earned end return score end) put('hidden_goal',function() local B=DataCenter and DataCenter.DigTreasureBoxRewardManager if B==nil then return nil end local n=0 pcall(function() n=math.floor((B:GetMaxNum() or 0)+0) end) if n<=0 then return nil end return n end) put('hidden_digs',function() local A=DataCenter and DataCenter.ActDispatchTreasureManager if A==nil then return nil end local n=0 pcall(function() n=math.floor((A:GetCanDigCount() or 0)+0) end) return n end) put('arena_open',function() local now=0 pcall(function() now=math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0)+0) end) if now<=0 then return nil end local seen=false local function win(a,z) a=math.floor((a or 0)/1000) z=math.floor((z or 0)/1000) if a<=0 or z<=0 then return false end seen=true return now>=a and now<=z end local three=false pcall(function() local m=DataCenter.LW3V3ArenaManager three=win(m.startTime,m.endTime) end) local storm=false pcall(function() local m=DataCenter.NewPeakArenaManager storm=win(m.info.startTime,m.info.endTime) end) if not seen then return nil end if three or storm then return 1 end return 0 end) put('arena_left',function() local m=DataCenter and DataCenter.NewPeakArenaManager if m==nil then return nil end local r=m.rankData if type(r)~='table' then return nil end local fought=math.floor((r.battleCount or -1)+0) if fought<0 then return nil end local need,owed=0,0 local ok=pcall(function() for _,row in pairs(r.dailyReward) do local n=math.floor((row.needCount or 0)+0) local got=math.floor((row.rewarded or 0)+0) if n>need then need=n end if got==0 and fought>=n then owed=owed+1 end end end) if not ok or need<=0 then return nil end local left=need-fought if left<0 then left=0 end return left+owed end) put('arena_cap',function() local m=DataCenter and DataCenter.NewPeakArenaManager if m==nil then return nil end local r=m.rankData if type(r)~='table' then return nil end local need=0 local ok=pcall(function() for _,row in pairs(r.dailyReward) do local n=math.floor((row.needCount or 0)+0) if n>need then need=n end end end) if not ok or need<=0 then return nil end return need end) return table.concat(out,' ') end)() INTO daily
