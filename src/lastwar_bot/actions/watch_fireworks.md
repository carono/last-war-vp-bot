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
# WHOSE FIREWORK IT IS — THE GATE IS A WHITELIST NOW (#2365). #1899 wrote it as a
# BLACKLIST: a box was skipped only when its `allianceUid` was there AND differed from
# ours, so a box that named NO alliance, or any box at all when our own alliance id
# could not be read, went straight to a press. The server refuses those
# (`zombieRush_tips_19, "not same alliance"`) and the client shows the player a popup
# for every one — which is what «постоянно получаю ошибку в клиенте» was. So the rule is
# turned round: **a press is made only for a box whose `allianceUid` EQUALS ours, both
# sides present.** Anything else is counted (`foreign`, `noAlliance`) and left alone.
#
# AND NOTHING IS ASKED FROM ANOTHER SERVER (#2365). `get.fireworks.info.list` answers
# `firework_tips_1013, "not in this server"` when the camera is on a cross-server map,
# and that refusal is a popup too. The hook now compares `LuaEntry.Player.serverId` with
# `WorldFavoDataManager.curServerId` and, when they differ, presses nothing and asks
# nothing — it only counts the announcement as `away`. It also asks the list ONLY when a
# firework of OUR OWN alliance is already known and had nothing pressable: an
# announcement about a firework the client does not track at all teaches this nothing and
# used to buy one refusal per push.
#
# THE HOOK CARRIES ITS VERSION, and that is the whole of «всё ещё» (#2365). The wrapper
# lives in the client's VM and outlives every panel restart: a fix committed to this file
# reached a running client only when somebody restarted the GAME, because the re-arm ran,
# found `on = true` and said «already on» — so a client that had been up since before the
# fix went on pressing with the old closure, invisibly, while the panel's own log showed
# nothing at all. The state now carries `ver`, the re-arm compares it, and an older watch
# is switched OFF (`B.on = false`, which turns its wrapper into a pass-through) before
# the new one is installed. Bump `VER` in the same edit as any change to the press.
#
# WHERE THE STATE LIVES, and why it is not a global. `_G` in this client carries a
# `__newindex` guard (`GlobalProtect.lua:54`): a refused assignment silently does not
# happen and the game writes the refusal into its own log — «Lua 全局变量 '…' 不可<新增/
# 修改>» (#1702, found by the golden-zombie chain, whose caches were being rebuilt on
# every call because of it). Measured live for THIS recipe on 2026-08-21: the guard is
# installed (`getmetatable(_G) ~= nil`) but our own name went through — a global set in
# one call was still readable in the next. So the refusal is selective, and that is
# precisely the problem: whether a watcher survives is then a property of the name it
# picked and of whatever the guard is checking that build.
#
# It matters more here than for a cache. The hook keeps its counters in a CLOSURE, so a
# refused flag does not stop it working — it stops the next lap FINDING it. The recipe
# would say «armed» rather than «already on» and wrap `HandleMessage` a second time,
# every three minutes, for as long as the re-arm trigger runs, while the reading showed
# zeroes throughout. So the state is a field of `DataCenter`: an existing table, which
# takes new fields quietly, and where this chain already reads everything else it knows.
#
# WHAT IT KEEPS, for read_fireworks_watch.md to read back: how many pushes arrived, how
# many presses went out, how many boxes the client has on record, and **the milliseconds
# between the push arriving and the press leaving** — the number this whole recipe exists
# to make small.
#
# Stop it with unwatch_fireworks.md. Re-playing this is free and idempotent: a hook that
# is already on says so and installs nothing. A client restart takes the VM and the hook
# with it, which is why the trigger `firework_watch` re-arms it on a slow clock.

READ_LUA (function() local VER = 2365 local B = DataCenter.__lw_fww if B and B.on and (tonumber(B.ver) or 0) == VER then return 'already on: pushes=' .. B.pushes .. ' taken=' .. B.taken .. ' foreign=' .. (B.foreign or 0) end local replaced = '' if B and B.on then B.on = false replaced = ' (an older watch, version ' .. tostring(B.ver or 'pre-2365') .. ', was switched off first: pushes=' .. tostring(B.pushes) .. ' taken=' .. tostring(B.taken) .. ')' end B = {on = true, ver = VER, pushes = 0, presses = 0, taken = 0, failed = 0, foreign = 0, blind = 0, away = 0, lastMs = -1, bestMs = -1, err = '', rows = {}, asked = 0} DataCenter.__lw_fww = B local function press() local G = DataCenter.LWFireworkGiftManager if not G then return 0, 'no manager', 0 end local myAl = '' pcall(function() myAl = tostring(LuaEntry.Player.allianceId or '') end) if myAl == 'nil' then myAl = '' end local home, cur = 0, 0 pcall(function() home = math.floor((tonumber(tostring(LuaEntry.Player.serverId)) or 0) + 0) end) pcall(function() cur = math.floor((tonumber(tostring((DataCenter.WorldFavoDataManager and DataCenter.WorldFavoDataManager.curServerId) or 0)) or 0) + 0) end) if home > 0 and cur > 0 and cur ~= home then B.away = B.away + 1 return 0, '', 0 end if myAl == '' then return 0, '', 0 end local sent, why, ours = 0, '', 0 for uid, queue in pairs(G.uid2FireworkGiftQueueMap or {}) do local mine = false pcall(function() mine = G:IsHasAvailableBoxForMeByUid(uid) end) local arr = {} pcall(function() arr = queue:ToArray() end) local foreign, own = false, false for _, e in ipairs(arr) do if type(e) == 'table' and e.uuid ~= nil then local al = tostring(e.allianceUid or '') if al == 'nil' then al = '' end if al == '' then B.blind = B.blind + 1 elseif al ~= myAl then foreign = true else own = true local open = (e.isAvailable == true) or mine local got = false pcall(function() got = G:IsThisGiftUuidGot(e.uuid) end) if open and not got then local ok, oops = pcall(function() SFSNetwork.SendMessage(MsgDefines.GetFireworksGift, {uuid = e.uuid, ownerUid = tostring(e.ownerUid or uid), type = tonumber(e.type) or 0}) end) if ok then sent = sent + 1 else B.failed = B.failed + 1 if why == '' then why = tostring(oops) end end end end end end if own then ours = ours + 1 elseif foreign then B.foreign = B.foreign + 1 end end local worth = 0 if ours > 0 and sent == 0 then worth = 1 end return sent, why, worth end local hm = SFSNetwork.HandleMessage SFSNetwork.HandleMessage = function(cmd, msg, ...) local out = hm(cmd, msg, ...) if B.on and (cmd == 'push.get.fireworks.gift' or cmd == 'get.fireworks.info.list') then pcall(function() local t0 = os.clock() if cmd == 'push.get.fireworks.gift' then B.pushes = B.pushes + 1 end local sent, why, worth = press() local ms = math.floor((os.clock() - t0) * 1000) if sent > 0 then B.presses = B.presses + 1 B.taken = B.taken + sent B.lastMs = ms if B.bestMs < 0 or ms < B.bestMs then B.bestMs = ms end end if why ~= '' and B.err == '' then B.err = why end if #B.rows < 30 then local tile = 'nil' pcall(function() tile = tostring(msg.pointId or msg.point or '') end) B.rows[#B.rows + 1] = cmd .. ' tile=' .. tile .. ' sent=' .. sent .. (worth == 0 and ' skipped=1' or '') .. ' ms=' .. ms end if sent == 0 and worth == 1 and cmd == 'push.get.fireworks.gift' and (os.clock() - B.asked) > 3 then B.asked = os.clock() pcall(function() SFSNetwork.SendMessage(MsgDefines.GetFireworksInfoList) end) end end) end return out end return 'armed' .. replaced end)() INTO state
LOG "Fireworks watch: {state}"
