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
# six fields separated by « ;; » with the NAME last:
#
#     14;;75443145;;0;;0;;1;;Еда
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
#   * perhour  — the production rate per hour, or 0 where the game reports none.
#   * base     — 1 when the base has at least one building producing this resource
#                (`ResourceManager:GetResourceOutBuildings`), 0 when it has not. The
#                panel puts the produced ones first; it does not decide which they are.
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
# Every read is wrapped, so a type whose row is missing costs one blank and not the whole
# reading, and a client that has not finished logging in answers an empty string rather
# than a page of zeros.

READ_LUA (function() local R=LuaEntry and LuaEntry.Resource local RM=DataCenter.ResourceManager local RT=DataCenter.ResourceTemplateManager if R==nil or RM==nil or RT==nil then return '' end local ids={} for k,_ in pairs(RT.resourceTemplateDic or {}) do local n=tonumber(k) if n~=nil then ids[#ids+1]=n end end table.sort(ids) local out={} for _,t in ipairs(ids) do local cnt,mx,ph,base,nm=0,0,0,0,'' pcall(function() cnt=math.floor((R:GetCntByResType(t) or 0)+0) end) pcall(function() mx=math.floor((R:GetMaxStorageByResType(t) or 0)+0) end) if mx>0 and mx<cnt then mx=0 end pcall(function() ph=math.floor((LWResourceLackUtil.GetResourceSpeedCountPerHour(t) or 0)+0) end) pcall(function() local b=RM:GetResourceOutBuildings(t) if type(b)=='table' then for _ in pairs(b) do base=1 break end end end) pcall(function() nm=tostring(RM:GetResourceNameByType(t) or ''):gsub('%s+',' ') end) if cnt>0 or base==1 then out[#out+1]={t,cnt,mx,ph,base,nm} end end local held={} for _,r in ipairs(out) do if r[2]>0 then held[r[6]]=true end end local rows={} for _,r in ipairs(out) do if r[2]>0 or not held[r[6]] then rows[#rows+1]=r[1]..';;'..r[2]..';;'..r[3]..';;'..r[4]..';;'..r[5]..';;'..r[6] end end return table.concat(rows,' #|# ') end)() INTO resources
LOG "resources: {resources}"
