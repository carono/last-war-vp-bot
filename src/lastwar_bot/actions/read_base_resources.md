# Read the base's resource stock: every resource the game counts, with its own name.
# ru: Прочитать запас ресурсов базы: всё, что игра считает, её же именами.
#
# A READ, and nothing else: it presses nothing, opens nothing and sends nothing to the
# server. No window has to be open and no scene is required — the client keeps the
# balance loaded from login, so this answers in one VM round trip from the base or from
# the world map alike.
#
# WHERE THE NUMBERS COME FROM (#1990, docs/research/base-resources.md). `LuaEntry.Resource`
# is the client's own resource object — the thing the HUD along the top of the screen is
# drawn from — and it answers per RESOURCE TYPE rather than per field name:
#
#   * `GetCntByResType(type)`          — how much of it the player holds.
#   * `GetMaxStorageByResType(type)`   — the cap, where the resource has one.
#   * `GetResAddSpeedByResType(type)`  — the per-second trickle, where it has one.
#   * `LWResourceLackUtil.GetResourceSpeedCountPerHour(type)` — the per-hour rate.
#
# Asking BY TYPE is the whole point. The flat fields on that object are the engine's
# legacy names and they no longer line up with what the game shows: the field spelled
# `wood` is drawn as «Золотые монеты» and the one spelled `money` as «Еда». Reading a
# field and labelling it in the panel would therefore print a confident lie, so nothing
# here is named by us at all — `ResourceManager:GetResourceNameByType(type)` returns the
# name already in the player's own language, out of the game's own table (`CLAUDE.md`,
# «Not one word of the panel is written in the panel»).
#
# WHICH TYPES. The game's own resource table, `ResourceTemplateManager.resourceTemplateDic`
# — every type the client knows about, in ascending order. A row is reported when the
# player holds some of it OR the base has a building that produces it; the rest are
# resources this account has never met and would be a column of zeros.
#
# THE ANSWER lands in one variable, `resources`, as records separated by « #|# », each
# seven fields separated by « ;; » with the NAME last:
#
#     14;;75443145;;0;;0;;1;;26400;;Еда
#
#   * type     — the game's resource type id.
#   * count    — how much is held.
#   * max      — the cap, or 0 where the game reports none. NOT invented: most of the
#                base resources genuinely have no cap and answer 0, and only the
#                season-scoped ones (water, electricity) come back with one.
#
#                A CAP BELOW THE STOCK IS NOT THIS RESOURCE'S CAP, and is reported as
#                none. `GetMaxStorageByResType(1)` answers 200 while the account holds
#                71 832 543 of type 1: the 200 is the season's own metal allowance,
#                which the accessor reaches for because the two share a type. «71 832 543
#                из 200» is not a fact about anything, so the number is dropped rather
#                than shown.
#   * perhour  — the production rate per hour, or 0 where the game reports none — which,
#                on this build, is EVERY base resource. `GetResourceSpeedCountPerHour`
#                answers 0 for gold, food, metal and oil alike; the only per-hour figures
#                the client keeps are the season trickle resources'. The base's buildings
#                do state a per-TICK amount (`GetBuildProduceNum`), but the tick length is
#                nowhere in the client — it was established at 5 s only by watching the
#                storage climb — so turning it into «в час» would be the panel's
#                arithmetic wearing the game's authority. It is left at 0 and the card
#                shows nothing. See `pending` below for the number that IS stated.
#   * base     — 1 when the base has at least one building producing this resource
#                (`ResourceManager:GetResourceOutBuildings`), 0 when it has not. The
#                panel puts the produced ones first; it does not decide which they are.
#   * pending  — how much of it is standing UNCOLLECTED in the base's production
#                buildings right now: the game's own `GetBuildingCurrStorage` for every
#                building, summed by the resource that building makes
#                (`GetProductRes` answers `{[type] = per-tick}`). This is the number that
#                makes «сколько сейчас» actionable — it is what one press of «Сбор
#                ресурсов» would add — and it is STATED, not derived.
#
#                Note `GetProductRes`, not `GetResType`: the latter does not answer for a
#                build uuid while the client is out on the world map, which is what made
#                an earlier version of this reading report nothing at all.
#   * name     — the resource's name in the player's language, from the game's table.
#
# TWO TYPES CAN CARRY THE SAME NAME, and one of them is dead. The client still has the
# engine's original type 0 in its table, and the row behind it now reads «Золотые монеты»
# — the same name as type 2, which is the one the player actually holds. Drawn side by
# side that is indistinguishable from a bug («золото: 0» above «золото: 712 198 273»), so
# a row whose count is zero is dropped when another reported row wears the same name and
# is not. Nothing is renamed and nothing is merged: the row that survives is the one the
# game itself is counting.
#
# …AND WHAT THE BASE'S LINES PAY IN BESIDES RESOURCES (#2744). The person's words: «Ещё
# с базы мы собираем компоненты дрона, шестерёнки и медали для обезьяны». None of those
# is a resource type: a drone part and a screw are resource ITEMS
# (`ResourceItemDataManager.itemList`), a chest is a bag stack (`ItemData.ItemInfos`), and
# `LuaEntry.Resource` knows nothing about either. So they are read from their own stores
# and reported in a SECOND SECTION of the same answer, after « #||# », five fields each:
#
#     7038;;415;;12;;icon_feijilingjian;;Запчасти дрона
#
#   * id       — the game's item id.
#   * count    — how much is held, summed over the stacks where a bag item has several.
#   * pending  — how much is standing uncollected in the lines that pay it, the same
#                `GetBuildingCurrStorage` the resources' `pending` is summed from.
#   * icon     — the sprite the game's own config names for it, no path and no suffix.
#   * name     — the item's name in the player's language, from the game's table.
#
# WHICH ITEMS. Not «everything in the bag» — the ones the base's own production lines
# pay: `GetProductResItem(uuid)` and `GetProductGoods(uuid)` over `GetAllBuildUuids`. On
# a live base that is seven, and every one of them is something a press of «Сбор
# ресурсов» brings in. Anything else in the bag came from somewhere else and is not this
# reading's business.
#
# ONE ROUND TRIP, TWO STORES: the section rides on the reading that was already being
# taken. A second play for the same press would spend the exclusive link twice for one
# question.
#
# A CLIENT THAT HAS NOT LOGGED IN IS REFUSED BEFORE ANYTHING IS READ. The first thing the
# chunk does is ask the game what time it is: a client sitting at the login screen has no
# server clock and hands out its own uptime instead, and it answers every OTHER question
# just as cheerfully and just as wrongly — no tasks, server -1, five robberies unspent
# (`tools/lib/game_clock.py`). So an implausible clock ends the reading with an empty
# string, and the panel keeps the rows it had rather than drawing a base with nothing in
# it. The check is free: it is the same round trip.
#
# Every read is wrapped, so a type whose row is missing costs one blank and not the whole
# reading.

READ_LUA (function() local nowms=0 pcall(function() nowms=UITimeManager.Instance:GetServerTime() end) nowms=math.floor(tonumber(nowms) or 0) if nowms < 1600000000000 then return '' end local R=LuaEntry and LuaEntry.Resource local RM=DataCenter.ResourceManager local RT=DataCenter.ResourceTemplateManager if R==nil or RM==nil or RT==nil then return '' end local pend={} local P=DataCenter.ProductLineManager if P~=nil then pcall(function() for _,u in pairs(P:GetAllBuildUuids() or {}) do local r=P:GetProductRes(u) if type(r)=='table' then local s=0 pcall(function() s=math.floor((P:GetBuildingCurrStorage(u) or 0)+0) end) for k,_ in pairs(r) do local n=tonumber(k) if n~=nil then pend[n]=(pend[n] or 0)+s end end end end end) end local ids={} for k,_ in pairs(RT.resourceTemplateDic or {}) do local n=tonumber(k) if n~=nil then ids[#ids+1]=n end end table.sort(ids) local out={} for _,t in ipairs(ids) do local cnt,mx,ph,base,nm,pd=0,0,0,0,'',(pend[t] or 0) pcall(function() cnt=math.floor((R:GetCntByResType(t) or 0)+0) end) pcall(function() mx=math.floor((R:GetMaxStorageByResType(t) or 0)+0) end) if mx>0 and mx<cnt then mx=0 end pcall(function() ph=math.floor((LWResourceLackUtil.GetResourceSpeedCountPerHour(t) or 0)+0) end) pcall(function() local b=RM:GetResourceOutBuildings(t) if type(b)=='table' then for _ in pairs(b) do base=1 break end end end) pcall(function() nm=tostring(RM:GetResourceNameByType(t) or ''):gsub('%s+',' ') end) if cnt>0 or base==1 or pd>0 then out[#out+1]={t,cnt,mx,ph,base,pd,nm} end end local held={} for _,r in ipairs(out) do if r[2]>0 then held[r[7]]=true end end local rows={} for _,r in ipairs(out) do if r[2]>0 or not held[r[7]] then rows[#rows+1]=r[1]..';;'..r[2]..';;'..r[3]..';;'..r[4]..';;'..r[5]..';;'..r[6]..';;'..r[7] end end local IT={} local PL=DataCenter.ProductLineManager local RI=DataCenter.ResourceItemDataManager local TM=DataCenter.ItemTemplateManager local BAG=DataCenter.ItemData if PL~=nil then pcall(function() for _,u in pairs(PL:GetAllBuildUuids() or {}) do local st=0 pcall(function() st=math.floor((PL:GetBuildingCurrStorage(u) or 0)+0) end) pcall(function() local q=PL:GetProductResItem(u) if type(q)=='table' then for k,_ in pairs(q) do local n=tonumber(k) if n~=nil then local e=IT[n] or {kind='res',pend=0} e.pend=e.pend+st IT[n]=e end end end end) pcall(function() local q=PL:GetProductGoods(u) if type(q)=='table' then for k,_ in pairs(q) do local n=tonumber(k) if n~=nil then local e=IT[n] or {kind='bag',pend=0} e.pend=e.pend+st IT[n]=e end end end end) end end) end local iids={} for k,_ in pairs(IT) do iids[#iids+1]=k end table.sort(iids) local irows={} for _,id in ipairs(iids) do local e=IT[id] local cnt=0 if e.kind=='res' then if RI~=nil then pcall(function() for _,v in pairs(RI.itemList or {}) do if type(v)=='table' and (tonumber(v.itemId) or -1)==id then cnt=cnt+math.floor((v.number or 0)+0) end end end) end else if BAG~=nil then pcall(function() for _,st in pairs(BAG.ItemInfos or {}) do if type(st)=='table' and (tonumber(st.itemId) or -1)==id then cnt=cnt+math.floor((st.count or st.num or 0)+0) end end end) end end local nm,ic='','' if TM~=nil then pcall(function() nm=tostring(TM:GetName(id) or ''):gsub('%s+',' ') end) pcall(function() local t=TM:GetItemTemplate(id) if type(t)=='table' then ic=tostring(t.pic or t.icon or '') end end) end if nm=='' and RI~=nil then pcall(function() nm=tostring(RI:GetName(id) or ''):gsub('%s+',' ') end) end if ic=='' and RI~=nil then pcall(function() ic=tostring(RI:GetIconPath(id) or ''):match('([^/]+)$') or '' end) end irows[#irows+1]=id..';;'..cnt..';;'..math.floor(e.pend)..';;'..ic..';;'..nm end return table.concat(rows,' #|# ')..' #||# '..table.concat(irows,' #|# ') end)() INTO resources
LOG "resources: {resources}"
