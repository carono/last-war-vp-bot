# Take every firework gift box that is still open to us — «собрать салюты».
# ru: Забрать все подарки с салютов — «собрать салюты».
#
# A player lights a firework over their own base and, while it burns, it drops gift
# boxes for everyone around. Each box is one `get.fireworks.gift {uuid, ownerUid,
# type}` — headless: no marker tap, no world-point popup, no camera move, no window.
# That is the whole network side of the in-game «получить» on a firework bubble.
#
# THE PRESS IS ONE TABLE, AND THAT IS THE WHOLE OF #1854. The first version of this
# recipe wrote the three fields as three positional arguments, and the client refused
# every one of them before a byte left the machine:
#
#   GetFireworksGiftMessage.lua:13: attempt to index a number value (local 'param')
#
# — measured live on 2026-08-20 by sending both shapes at the same box. The failure was
# inside the recipe's own `pcall`, so it was counted as «unreadable» and the run went on
# to report success: 553 runs in one profile's log, `taken=0` in every single one, and
# not one box ever collected. **The message takes a TABLE**, exactly as the client's own
# send does, and a press that throws is now reported as `failed=` with the error rather
# than hidden among the ids this recipe could not read.
#
# WHY THERE IS NO WAIT BEFORE THE PRESS. Everybody who can see a firework is taking from
# it, so a box is gone in seconds — the ability is a race and every wait is a loss. The
# push that starts this run (`push.get.fireworks.gift`, the trigger `firework_collect`)
# is the client HAVING ALREADY handled somebody else's box: by the time the panel is
# woken the queue map is fresh, so the first thing this recipe does is press. Asking
# `get.fireworks.info.list` and waiting a second and a half for the reply — which is what
# it used to open with — spent the race before entering it. The refresh is still here,
# but it is the SECOND pass and it only runs when the first found nothing.
#
# WHO IS ASKED, AND WHY IT IS THE CLIENT AND NOT THE WIRE. The owner of a firework is
# `ownerUid`, an account id, and it deliberately does not cross the capture's pipe
# (`panel/runtime/firework_wire.py`). The client keeps the whole thing itself:
# `DataCenter.LWFireworkGiftManager.uid2FireworkGiftQueueMap` is owner -> a queue of the
# boxes that firework still has, and a box carries its own answer:
#
#   * `isAvailable` — on the box itself: is there still one here for us. Measured
#     `false` on every box of a firework that had been picked clean (`num=12/15`,
#     `num=10/15` — that count is the WHOLE firework's, not ours).
#   * `IsHasAvailableBoxForMeByUid(uid)` — the same question asked of the firework as a
#     whole. Local, no request.
#   * `IsThisGiftUuidGot(uuid)` — whether this very box is already ours
#     (`giftUuid2TimeTable`), so a second run over the same firework presses nothing.
#
# GATES: there is no daily quota and no cooldown on taking a box — the limit is one box
# per firework per account. A run with nothing to take is a clean no-op and says so in
# numbers.
#
# NOT DETACHED, DELIBERATELY. `DETACH` claims the client at `claims.DETACHED`, *below*
# an ordinary background errand (docs/dsl.md) — exactly the wrong end of the queue for
# something decided in seconds. What keeps this from waiting its turn is the trigger's
# «сразу, без очереди» (`immediate`), and the run itself is short enough — one VM round
# trip when there is something to take — that nothing needs protecting from its length.
#
# The wire side, the managers and the field names are written up in
# docs/research/fireworks.md.

# First pass: press whatever the client already knows about, at once. The whole loop is
# one VM round trip — a trip costs ~0.15 s and the loop inside it is free
# (docs/research/alliance-tech-donate.md). Returns the NUMBER taken so the recipe can
# branch on it; the sentence for the log is parked and read back below.
READ_LUA (function() local t0 = os.clock() local G = DataCenter.LWFireworkGiftManager if not G then DataCenter.__lw_fw = 'no manager' return 0 end local owners, boxes, sent, already, shut, failed = 0, 0, 0, 0, 0, 0 local err = '' local shape = '' for uid, queue in pairs(G.uid2FireworkGiftQueueMap or {}) do owners = owners + 1 local mine = false pcall(function() mine = G:IsHasAvailableBoxForMeByUid(uid) end) local arr = {} pcall(function() arr = queue:ToArray() end) for _, e in ipairs(arr) do if type(e) == 'table' then boxes = boxes + 1 if shape == '' then local ks = {} for k in pairs(e) do ks[#ks + 1] = tostring(k) end table.sort(ks) shape = table.concat(ks, ',') end local u = e.uuid local open = (e.isAvailable == true) or mine local got = false if u ~= nil then pcall(function() got = G:IsThisGiftUuidGot(u) end) end if u == nil or not open then shut = shut + 1 elseif got then already = already + 1 else local ok, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.GetFireworksGift, {uuid = u, ownerUid = tostring(e.ownerUid or uid), type = tonumber(e.type) or 0}) end) if ok then sent = sent + 1 else failed = failed + 1 if err == '' then err = tostring(why) end end end end end end DataCenter.__lw_fw = 'fireworks=' .. owners .. ' boxes=' .. boxes .. ' taken=' .. sent .. ' already=' .. already .. ' shut=' .. shut .. ' failed=' .. failed .. ' ms=' .. math.floor((os.clock() - t0) * 1000) .. (err ~= '' and (' err=' .. err) or '') .. ' fields=[' .. shape .. ']' return sent end)() INTO taken
READ_LUA tostring(DataCenter.__lw_fw or '') INTO first
LOG "Fireworks: {first}"

# Second pass, and only when the first found nothing to take: ask the server what is
# burning right now. This is the slow path on purpose — a firework that started while
# the panel was busy is invisible to the queue map until the list comes back, and a run
# that has already pressed has no reason to pay the second and a half.
IF taken == 0
    LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.GetFireworksInfoList) end)
    WAIT 1.5
    READ_LUA (function() local G = DataCenter.LWFireworkGiftManager if not G then return 'no manager' end local seen, sent, failed = 0, 0, 0 local err = '' for uid, queue in pairs(G.uid2FireworkGiftQueueMap or {}) do local mine = false pcall(function() mine = G:IsHasAvailableBoxForMeByUid(uid) end) local arr = {} pcall(function() arr = queue:ToArray() end) for _, e in ipairs(arr) do if type(e) == 'table' then seen = seen + 1 local u = e.uuid local open = (e.isAvailable == true) or mine local got = false if u ~= nil then pcall(function() got = G:IsThisGiftUuidGot(u) end) end if u ~= nil and open and not got then local ok, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.GetFireworksGift, {uuid = u, ownerUid = tostring(e.ownerUid or uid), type = tonumber(e.type) or 0}) end) if ok then sent = sent + 1 else failed = failed + 1 if err == '' then err = tostring(why) end end end end end end return 'boxes=' .. seen .. ' taken=' .. sent .. ' failed=' .. failed .. (err ~= '' and (' err=' .. err) or '') end)() INTO second
    LOG "Fireworks (after refresh): {second}"

# How many boxes this account has ever been given, as the CLIENT counts them — the one
# authority there is (`giftUuid2TimeTable`), read after the presses rather than kept by
# the panel. A press the server refused simply never appears here.
WAIT 1.0
READ_LUA (function() local G = DataCenter.LWFireworkGiftManager local n = 0 for _ in pairs((G and G.giftUuid2TimeTable) or {}) do n = n + 1 end return n end)() INTO got
LOG "Fireworks: boxes on record for this account: {got}"
