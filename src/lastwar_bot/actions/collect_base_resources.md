# Collect every ready resource from the base's production buildings.
# ru: Сбор ресурсов со всех готовых производств базы.
#
# One tap = the base's own "Collect All". The base's resource generators are
# production lines (DataCenter.ProductLineManager); collecting one is
# SendCollect(uuid), and the game's Collect-All button just fires that for every
# ready building. This button does the same — it loops GetAllBuildUuids() and
# calls SendCollect on the buildings that have at least one unit banked
# (GetBuildingCurrStorage >= 1). No window has to be open.
#
# The readiness gate is not cosmetic: collecting a building that is still
# producing is rejected by the server (errorCode 602026, "In production, please
# be patient.") and the client pops one toast per rejection.
#
# Verified live: sweeping all 38 production buildings dropped their pending
# storage from ~29k to ~6k (16 ready -> 0); after the gate landed, 36 collects
# went out and 36 succeeded with zero rejections. Full write-up in
# docs/research/resource-collection.md.

# WHAT THE SWEEP IS ABOUT TO BRING IN, read BEFORE a single building is collected
# (#2747). The day's card «Сбор ресурсов» is built by DIFFING balances, and a balance
# says only that a number moved: a chest opened, an arms-race prize, a quest reward and
# this harvest are indistinguishable once they have landed. Attributing them by TIME
# alone is what put 34 «Запчастей дрона» on a card whose base makes about seven a day —
# the burst chain that keeps a harvest's own cascade together also swallowed two
# twenty-part prizes that arrived a minute after it.
#
# So the harvest states its OWN SIZE, and the panel credits the base up to that and no
# further. `GetBuildingCurrStorage` is the same number `read_base_resources.md` reports
# as `pending`; taken here it is exact rather than however stale the last reading was.
# Measured live: the reading of 23:55 said 219 screws were standing and the harvest a
# minute later paid exactly 219.
#
# One VM round trip before the sweep, and it presses nothing. `type=amount` for a
# resource, `i<id>=amount` for an item, « #|# » between them, empty when the client
# cannot answer — and an empty answer costs nothing but the older, looser attribution.

READ_LUA (function() local P=DataCenter.ProductLineManager if P==nil then return '' end local res,itm={},{} pcall(function() for _,u in pairs(P:GetAllBuildUuids() or {}) do local s=0 pcall(function() s=math.floor((P:GetBuildingCurrStorage(u) or 0)+0) end) if s>0 then pcall(function() local r=P:GetProductRes(u) if type(r)=='table' then for k,_ in pairs(r) do local n=tonumber(k) if n~=nil then res[n]=(res[n] or 0)+s end end end end) pcall(function() local q=P:GetProductResItem(u) if type(q)=='table' then for k,_ in pairs(q) do local n=tonumber(k) if n~=nil then itm[n]=(itm[n] or 0)+s end end end end) pcall(function() local q=P:GetProductGoods(u) if type(q)=='table' then for k,_ in pairs(q) do local n=tonumber(k) if n~=nil then itm[n]=(itm[n] or 0)+s end end end end) end end end) local out={} for k,v in pairs(res) do out[#out+1]=k..'='..math.floor(v) end for k,v in pairs(itm) do out[#out+1]='i'..k..'='..math.floor(v) end return table.concat(out,' #|# ') end)() INTO harvest_pending
LOG "the sweep is about to collect: {harvest_pending}"
TAP collect_base_resources
