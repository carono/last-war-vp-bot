# Read the shareable lucky packet a surprise box dropped — «есть ли чем поделиться».
# ru: Прочитать счастливый пакет, выпавший из ящика с сюрпризом.
#
# A surprise box sometimes drops a BIG BONUS: a red packet of free diamonds the player
# may give away in chat, once, inside an hour. The client keeps it in
# `DataCenter.LuckyBuffManager.notSharedLuckyPacketList` — a map of packet uuid to
# `{configId, uid, expireTime, count}` — and `shortestTimePacketUUid` names the one that
# runs out first. Both readings are LOCAL: the whole of this recipe is one round trip to
# the VM and asks the server for nothing.
#
# `expireTime` is the game's own millisecond stamp and the deadline is an hour from the
# drop, so the minutes left are the only number a person wants. A packet that has already
# run out is still in the list until the client sweeps it, so it is counted separately —
# «есть один, но он мёртвый» and «нет ни одного» are different answers.
#
# The packet is given away in the ALLIANCE chat (the chooser offers that room and no
# other, measured live #2397), so an account outside an alliance has nowhere to put it;
# that is read here too rather than discovered halfway through the press.
READ_LUA (function() local m = DataCenter.LuckyBuffManager if not m then return 'have=0 live=0 min=-1 alliance=0 err=no-manager' end local inst = m.Instance or m local now = 0 pcall(function() now = UITimeManager:GetInstance():GetServerTime() end) if now == nil or now == 0 then now = os.time() * 1000 end local have, live, soonest = 0, 0, nil for _, e in pairs(inst.notSharedLuckyPacketList or {}) do if type(e) == 'table' then have = have + 1 local t = tonumber(e.expireTime) or 0 if t > now then live = live + 1 if soonest == nil or t < soonest then soonest = t end end end end local mins = -1 if soonest then mins = math.floor((soonest - now) / 60000) end local al = 0 pcall(function() local a = tostring(LuaEntry.Player.allianceId or '') if a ~= '' and a ~= 'nil' and a ~= '0' then al = 1 end end) return 'have=' .. have .. ' live=' .. live .. ' min=' .. mins .. ' alliance=' .. al end)() INTO lucky
LOG "Счастливый пакет: {lucky}"

