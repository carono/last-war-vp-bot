# Listen for the moment a surprise box drops a shareable packet — «караулить пакет».
# ru: Караулить появление счастливого пакета из ящика с сюрпризом.
#
# WHY A HOOK AND NOT A POLL. The bonus falls out of DIFFERENT boxes — the person's own
# words — so there is no one press to hang the reading on, and the client keeps the
# packet in a table nobody is told about (`LuckyBuffManager.notSharedLuckyPacketList`).
# Asking the game every few minutes whether the table has grown is exactly the background
# question CLAUDE.md forbids, so this recipe listens where the change ARRIVES: a wrapper
# around the client's own `SFSNetwork.HandleMessage` that compares the size of the list
# before and after each message it delivers.
#
# WHAT IT IS FOR, AND WHAT IS STILL OPEN. #2397 found the packet, gave it away and could
# not name the command that had announced it: the drop happened before the panel was
# looking, and the client had loaded no push module for it
# (`Net.Msgs.…RedPacket…` held only `GetAllianceRedPacket` and `RedPacketsRvdId`). The
# candidates the defines offer are `push.prepare.red.packet` and
# `push.receive.assign.red.packet`, and a trigger built on a guess would either never
# fire or fire on the wrong thing. So this watch NAMES the command on the next drop —
# `heard=` in the reading — and the wire trigger is written once the name is known
# (docs/research/lucky-packet.md).
#
# It records and never presses. Giving the packet away drives three of the client's own
# windows, and opening windows inside a message handler is how a VM gets wedged
# (`docs/research/lua-reflection-hazards.md`); the press stays where a person or the
# schedule can see it — `actions/share_lucky_packet.md`.
#
# Re-playing this is free: a hook already on says so and installs nothing. A client
# restart takes the VM and the hook with it, which is why the trigger `lucky_watch`
# re-arms it on a slow clock — the same shape `firework_watch` uses, and for the same
# reason.
READ_LUA (function() local VER = 2397 local B = DataCenter.__lw_lucky if B and B.on and (tonumber(B.ver) or 0) == VER then return 'already on: drops=' .. tostring(B.drops) .. ' heard=[' .. table.concat(B.rows, '; ') .. ']' end local replaced = '' if B and B.on then B.on = false replaced = ' (an older watch, version ' .. tostring(B.ver or '?') .. ', was switched off first)' end B = {on = true, ver = VER, drops = 0, rows = {}} DataCenter.__lw_lucky = B local function size() local m = DataCenter.LuckyBuffManager if not m then return 0 end local inst = m.Instance or m local n = 0 for _ in pairs(inst.notSharedLuckyPacketList or {}) do n = n + 1 end return n end B.was = size() local hm = SFSNetwork.HandleMessage SFSNetwork.HandleMessage = function(cmd, msg, ...) local out = hm(cmd, msg, ...) if B.on then pcall(function() local now = size() if now > B.was then B.drops = B.drops + (now - B.was) if #B.rows < 20 then B.rows[#B.rows + 1] = tostring(cmd) .. ' +' .. (now - B.was) end end B.was = now end) end return out end return 'armed' .. replaced end)() INTO state
LOG "Караул за пакетом: {state}"
