# Take a firework's gift box the instant the game hears about one — «караулить салюты».
# ru: Забирать подарок с салюта в момент объявления — «караулить салюты».
#
# WHY THIS EXISTS, AND WHY IT IS NOT A TIMER. A firework burns for a couple of minutes
# and everybody who can see it is taking from it, so a box is decided in seconds. The
# panel can hear the announcement — `push.get.fireworks.gift`, the trigger
# `firework_collect` — but hearing it costs the whole chain: the capture's child process
# decodes the frame, writes a line, the hub reads it, the schedule accepts an errand, a
# worker claims the client, and only then does a Lua round trip go out. This recipe
# removes every link of that chain by putting the press where the announcement ARRIVES:
# a wrapper around the client's own `SFSNetwork.HandleMessage`, which presses inside the
# same call that delivered the push.
#
# It is the shape `actions/dev/watch_treasures.md` already uses — a hook parked in the
# game VM, read back by a second recipe — with one difference that matters: this one
# ACTS. A client with it on takes gift boxes on its own, which is the point.
#
# WHAT THE ANNOUNCEMENT ACTUALLY CARRIES (measured live 2026-08-20, and it settles the
# question docs/research/fireworks.md §6 left open):
#
#     push.get.fireworks.gift {configId, pointId, uid, name, pic, picVer,
#                              headSkinId, headSkinET, isDouble}
#
# — `pointId` is the SQUARE the firework stands over and `configId` is which firework it
# is. There is **no box uuid and no ownerUid in it**: the push says «somebody took a box
# from the firework on that square», naming the taker rather than the prize. So the press
# cannot be built from the push, and the client's own book is the only source there is:
# `LWFireworkGiftManager.uid2FireworkGiftQueueMap` — which the client has already updated
# by the time the wrapper is reached, because it handles the push before it returns.
#
# THE PRESS IS ONE TABLE — `{uuid, ownerUid, type}`. Three positional arguments throw
# inside the client (`attempt to index a number value (local 'param')`), which is how
# 553 collector runs reported success and took nothing (#1854).
#
# THE GATE IS THE BOX. `isAvailable` on the box, `IsHasAvailableBoxForMeByUid(uid)` on the
# firework, `IsThisGiftUuidGot(uuid)` on what is already ours. And the server has one of
# its own that no local reading shows: a box refused with
# `errorCode = zombieRush_tips_19, errorMsg = "not same alliance"` — measured live —
# so a firework outside the alliance is heard and not taken, whatever the queue says.
#
# WHAT IT KEEPS, for read_fireworks_watch.md to read back: how many pushes arrived, how
# many presses went out, how many boxes the client has on record, and **the milliseconds
# between the push arriving and the press leaving** — the number this whole recipe exists
# to make small.
#
# Stop it with unwatch_fireworks.md. Re-playing this is free and idempotent: a hook that
# is already on says so and installs nothing. A client restart takes the VM and the hook
# with it, which is why the trigger `firework_watch` re-arms it on a slow clock.

READ_LUA (function() local B = _G.__LW_FWW if B and B.on then return 'already on: pushes=' .. B.pushes .. ' taken=' .. B.taken end B = {on = true, pushes = 0, presses = 0, taken = 0, failed = 0, lastMs = -1, bestMs = -1, err = '', rows = {}, asked = 0} _G.__LW_FWW = B local function press() local G = DataCenter.LWFireworkGiftManager if not G then return 0, 'no manager' end local sent, why = 0, '' for uid, queue in pairs(G.uid2FireworkGiftQueueMap or {}) do local mine = false pcall(function() mine = G:IsHasAvailableBoxForMeByUid(uid) end) local arr = {} pcall(function() arr = queue:ToArray() end) for _, e in ipairs(arr) do if type(e) == 'table' and e.uuid ~= nil then local open = (e.isAvailable == true) or mine local got = false pcall(function() got = G:IsThisGiftUuidGot(e.uuid) end) if open and not got then local ok, oops = pcall(function() SFSNetwork.SendMessage(MsgDefines.GetFireworksGift, {uuid = e.uuid, ownerUid = tostring(e.ownerUid or uid), type = tonumber(e.type) or 0}) end) if ok then sent = sent + 1 else B.failed = B.failed + 1 if why == '' then why = tostring(oops) end end end end end end return sent, why end local hm = SFSNetwork.HandleMessage SFSNetwork.HandleMessage = function(cmd, msg, ...) local out = hm(cmd, msg, ...) if B.on and (cmd == 'push.get.fireworks.gift' or cmd == 'get.fireworks.info.list') then pcall(function() local t0 = os.clock() if cmd == 'push.get.fireworks.gift' then B.pushes = B.pushes + 1 end local sent, why = press() local ms = math.floor((os.clock() - t0) * 1000) if sent > 0 then B.presses = B.presses + 1 B.taken = B.taken + sent B.lastMs = ms if B.bestMs < 0 or ms < B.bestMs then B.bestMs = ms end end if why ~= '' and B.err == '' then B.err = why end if #B.rows < 30 then local tile = 'nil' pcall(function() tile = tostring(msg.pointId or msg.point or '') end) B.rows[#B.rows + 1] = cmd .. ' tile=' .. tile .. ' sent=' .. sent .. ' ms=' .. ms end if sent == 0 and cmd == 'push.get.fireworks.gift' and (os.clock() - B.asked) > 3 then B.asked = os.clock() pcall(function() SFSNetwork.SendMessage(MsgDefines.GetFireworksInfoList) end) end end) end return out end return 'armed' end)() INTO state
LOG "Fireworks watch: {state}"
