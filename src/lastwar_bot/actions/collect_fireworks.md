# Take every firework gift box that is still open to us — «собрать салюты».
# ru: Забрать все подарки с салютов — «собрать салюты».
#
# A player lights a firework over their own base and, while it burns, it drops gift
# boxes for everyone around. Each box is one `get.fireworks.gift {uuid, ownerUid,
# type}` — headless: no marker tap, no world-point popup, no camera move, no window.
# That is the whole network side of the in-game «получить» on a firework bubble
# (recorded 2026-08-20, `results/traces/20260820_150539_салют_trace.log`).
#
# WHO IS ASKED, AND WHY IT IS THE CLIENT AND NOT THE WIRE. The owner of a firework is
# `ownerUid`, an account id, and it deliberately does not cross the capture's pipe
# (`panel/runtime/firework_wire.py`). The client keeps the whole thing itself:
# `DataCenter.LWFireworkGiftManager.uid2FireworkGiftQueueMap` is owner -> a queue of the
# boxes that firework still has, and the manager answers the two questions that decide a
# press without asking the server anything:
#
#   * `IsHasAvailableBoxForMeByUid(uid)` — has THIS account still got a box to take from
#     that firework. This is the gate. A firework whose boxes are gone, or whose box we
#     have already had, answers false and costs one local call.
#   * `IsThisGiftUuidGot(uuid)` — whether this very box is already ours. The client keeps
#     the record in `giftUuid2TimeTable`, so a second run over the same firework presses
#     nothing.
#
# THE LIST IS REFRESHED FIRST. `get.fireworks.info.list` asks the server what is burning
# right now; the reply lands in the manager a beat later, which is what the WAIT is for.
# Without it a firework that started while the panel was busy is invisible to the queue
# map, and the run reports «nothing to take» over a sky full of them.
#
# GATES: there is no daily quota and no cooldown on taking a box — the limit is one box
# per firework per account, which is exactly what `IsHasAvailableBoxForMeByUid` answers.
# A run with nothing to take is a clean no-op and says so in numbers.
#
# The wire side, the managers and the field names are written up in
# docs/research/fireworks.md.

# Ask the server what is burning right now; the reply fills the client's own queue map.
LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.GetFireworksInfoList) end)
WAIT 1.5

# One pass over every firework the client knows about, pressing each box that is still
# ours to take. The whole loop is one VM round trip — a trip costs ~0.15 s and the loop
# inside it is free (docs/research/alliance-tech-donate.md), and a firework is taken in
# seconds by everybody who can see it.
READ_LUA (function() local G = DataCenter.LWFireworkGiftManager if not G then return 'no manager' end local owners, boxes, sent, already, unnamed = 0, 0, 0, 0, 0 local shape = '' local function giftId(e) if type(e) ~= 'table' then return nil end for _, k in ipairs({'uuid', 'giftUuid', 'fireworksUuid', 'id'}) do local v = e[k] if v ~= nil and tostring(v):match('^%d%d%d%d%d%d%d%d%d%d') then return v end end for _, v in pairs(e) do if type(v) ~= 'table' and type(v) ~= 'function' and tostring(v):match('^%d%d%d%d%d%d%d%d%d%d%d%d%d%d%d') then return v end end return nil end for uid, queue in pairs(G.uid2FireworkGiftQueueMap or {}) do owners = owners + 1 local mine = false pcall(function() mine = G:IsHasAvailableBoxForMeByUid(uid) end) if mine then local arr = {} pcall(function() arr = queue:ToArray() end) for _, e in ipairs(arr) do boxes = boxes + 1 if shape == '' and type(e) == 'table' then local ks = {} for k in pairs(e) do ks[#ks + 1] = tostring(k) end table.sort(ks) shape = table.concat(ks, ',') end local u = giftId(e) if u == nil then unnamed = unnamed + 1 else local got = false pcall(function() got = G:IsThisGiftUuidGot(u) end) if got then already = already + 1 else local kind = tonumber(e.type) or 0 local ok = pcall(function() SFSNetwork.SendMessage(MsgDefines.GetFireworksGift, u, tostring(uid), kind) end) if ok then sent = sent + 1 else unnamed = unnamed + 1 end end end end end end return 'fireworks=' .. owners .. ' boxes=' .. boxes .. ' taken=' .. sent .. ' already=' .. already .. ' unreadable=' .. unnamed .. ' fields=[' .. shape .. ']' end)() INTO report

# How many boxes this account has ever been given, as the CLIENT counts them — the one
# authority there is (`giftUuid2TimeTable`), read after the presses rather than kept by
# the panel. A press the server refused simply never appears here.
WAIT 1.5
READ_LUA (function() local G = DataCenter.LWFireworkGiftManager local n = 0 for _ in pairs((G and G.giftUuid2TimeTable) or {}) do n = n + 1 end return n end)() INTO got

LOG "Fireworks: {report}; boxes on record for this account: {got}"
