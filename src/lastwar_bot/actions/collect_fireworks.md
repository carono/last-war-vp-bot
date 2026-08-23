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
# WHOSE FIREWORK IT IS — THE WHOLE OF #1899. The announcement carries no alliance at
# all (`push.get.fireworks.gift` = configId, pointId and the TAKER's uid and nickname),
# so the panel is woken by every firework anybody in sight lights, and a listener that
# cannot tell them apart goes to the game for each one. The box itself can tell: a box
# in `uid2FireworkGiftQueueMap` carries `allianceUid`, and `LuaEntry.Player.allianceId`
# is our own — measured live on 2026-08-23, five fireworks known to the client, every
# one of them another alliance's and none of them matching ours. Both readings are
# LOCAL: the gate costs no request.
#
# So a firework whose boxes name another alliance is skipped whole — not pressed, not
# refreshed, not waited on — and the run says so in words. Nothing was ever collectable
# there: the server refuses such a box with `zombieRush_tips_19, "not same alliance"`
# (docs/research/fireworks.md §4). What this replaces is a run that pressed nothing,
# then paid `get.fireworks.info.list` plus 1.5 s, then another second reading the record
# back — on every announcement of every alliance's firework in view.
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
READ_LUA (function() local t0 = os.clock() local G = DataCenter.LWFireworkGiftManager if not G then DataCenter.__lw_fw = 'no manager' DataCenter.__lw_fw_ask = 1 DataCenter.__lw_fw_sent = 0 return 0 end local myAl = '' pcall(function() myAl = tostring(LuaEntry.Player.allianceId or '') end) local owners, boxes, sent, already, shut, failed, foreign, ours, unknown = 0, 0, 0, 0, 0, 0, 0, 0, 0 local err = '' local shape = '' for uid, queue in pairs(G.uid2FireworkGiftQueueMap or {}) do owners = owners + 1 local mine = false pcall(function() mine = G:IsHasAvailableBoxForMeByUid(uid) end) local arr = {} pcall(function() arr = queue:ToArray() end) local alien, own, seen = false, false, false for _, e in ipairs(arr) do if type(e) == 'table' then boxes = boxes + 1 seen = true if shape == '' then local ks = {} for k in pairs(e) do ks[#ks + 1] = tostring(k) end table.sort(ks) shape = table.concat(ks, ',') end local al = tostring(e.allianceUid or '') if myAl ~= '' and al ~= '' and al ~= myAl then alien = true else if myAl ~= '' and al == myAl then own = true end local u = e.uuid local open = (e.isAvailable == true) or mine local got = false if u ~= nil then pcall(function() got = G:IsThisGiftUuidGot(u) end) end if u == nil or not open then shut = shut + 1 elseif got then already = already + 1 else local ok, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.GetFireworksGift, {uuid = u, ownerUid = tostring(e.ownerUid or uid), type = tonumber(e.type) or 0}) end) if ok then sent = sent + 1 else failed = failed + 1 if err == '' then err = tostring(why) end end end end end end if alien then foreign = foreign + 1 elseif own then ours = ours + 1 elseif seen then unknown = unknown + 1 end end local ask = 0 if sent == 0 and (owners == 0 or unknown > 0 or myAl == '') then ask = 1 end DataCenter.__lw_fw_ask = ask DataCenter.__lw_fw_sent = sent DataCenter.__lw_fw = 'fireworks=' .. owners .. ' ours=' .. ours .. ' foreign=' .. foreign .. ' unknown=' .. unknown .. ' boxes=' .. boxes .. ' taken=' .. sent .. ' already=' .. already .. ' shut=' .. shut .. ' failed=' .. failed .. ' ms=' .. math.floor((os.clock() - t0) * 1000) .. (err ~= '' and (' err=' .. err) or '') .. ' fields=[' .. shape .. ']' .. ((sent == 0 and ask == 0 and foreign > 0 and ours == 0) and " — another alliance's firework, skipping" or '') return sent end)() INTO taken
READ_LUA tostring(DataCenter.__lw_fw or '') INTO first
LOG "Fireworks: {first}"

# Second pass, and only when the first has NOTHING LEFT TO LEARN FROM (#1899). Asking
# `get.fireworks.info.list` and waiting a second and a half for the reply is the slow
# path, and it is worth paying only when the client's own book might be missing a
# firework: nothing known at all, a firework whose boxes name no alliance, or an account
# whose own alliance id could not be read. A sky the client already knows and that is
# **another alliance's** teaches this run nothing — the server refuses such a box with
# `zombieRush_tips_19, "not same alliance"` — so the recipe does not go to the game for
# it at all, and the line above says so in words.
READ_LUA (tonumber(DataCenter.__lw_fw_ask) or 1) INTO ask
IF ask == 1
    LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.GetFireworksInfoList) end)
    WAIT 1.5
    READ_LUA (function() local G = DataCenter.LWFireworkGiftManager if not G then return 'no manager' end local myAl = '' pcall(function() myAl = tostring(LuaEntry.Player.allianceId or '') end) local seen, sent, failed, foreign = 0, 0, 0, 0 local err = '' for uid, queue in pairs(G.uid2FireworkGiftQueueMap or {}) do local mine = false pcall(function() mine = G:IsHasAvailableBoxForMeByUid(uid) end) local arr = {} pcall(function() arr = queue:ToArray() end) for _, e in ipairs(arr) do if type(e) == 'table' then seen = seen + 1 local al = tostring(e.allianceUid or '') if myAl ~= '' and al ~= '' and al ~= myAl then foreign = foreign + 1 else local u = e.uuid local open = (e.isAvailable == true) or mine local got = false if u ~= nil then pcall(function() got = G:IsThisGiftUuidGot(u) end) end if u ~= nil and open and not got then local ok, why = pcall(function() SFSNetwork.SendMessage(MsgDefines.GetFireworksGift, {uuid = u, ownerUid = tostring(e.ownerUid or uid), type = tonumber(e.type) or 0}) end) if ok then sent = sent + 1 else failed = failed + 1 if err == '' then err = tostring(why) end end end end end end end DataCenter.__lw_fw_sent = (tonumber(DataCenter.__lw_fw_sent) or 0) + sent return 'boxes=' .. seen .. ' foreign=' .. foreign .. ' taken=' .. sent .. ' failed=' .. failed .. (err ~= '' and (' err=' .. err) or '') end)() INTO second
    LOG "Fireworks (after refresh): {second}"

# How many boxes this account has ever been given, as the CLIENT counts them — the one
# authority there is (`giftUuid2TimeTable`), read after the presses rather than kept by
# the panel. A press the server refused simply never appears here. Read only when
# something actually went out: a run that pressed nothing has nothing new to count, and
# the second of waiting is a second of a race it is not in.
READ_LUA (tonumber(DataCenter.__lw_fw_sent) or 0) INTO pressed
IF pressed > 0
    WAIT 1.0
    READ_LUA (function() local G = DataCenter.LWFireworkGiftManager local n = 0 for _ in pairs((G and G.giftUuid2TimeTable) or {}) do n = n + 1 end return n end)() INTO got
    LOG "Fireworks: boxes on record for this account: {got}"
