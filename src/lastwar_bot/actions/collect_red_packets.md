# Take a share of every red packet the chat is still holding — «забрать чужие пакеты».
# ru: Забрать свою долю из всех красных пакетов, которые ещё висят в чате.
#
# The press a person makes by hand, and what the ear (`watch_red_packets.md`) does by
# itself when an announcement arrives. It is the same gate and the same send — the ear
# parks the whole of it on its own table (`DataCenter.__lw_rpw.take`, and never on a
# global — the build refuses those, #2656), and this recipe arms the ear and then
# offers it the messages the CLIENT IS ALREADY HOLDING.
#
# NOTHING IS ASKED OF THE SERVER. `Chat.ChatInterface.getRoomMgr().roomDatas[<room>].msgs`
# is the client's own copy of the last few dozen messages of every room it sits in,
# filled by the same parse the ear hooks (docs/research/chat-lua-readout.md). Asking
# `get.alliance.red.packet` would be a question to the server for a thing the client can
# already answer, and asking it on a clock is what `CLAUDE.md` forbids outright.
#
# A packet the ear has already pressed at is skipped by uuid, so pressing this button
# twice in a row sends nothing the second time: the server refuses a second open with a
# popup the person then has to close, which is the mistake #2365 paid for on fireworks.
CALL watch_red_packets
READ_LUA (function() local B = DataCenter.__lw_rpw local take = B and B.take if type(take) ~= 'function' then return 'ear not armed — nothing swept' end local before = {heard = B.heard, taken = B.taken, skipped = B.skipped, failed = B.failed} local I = package.loaded['Chat.ChatInterface'] local ok, mgr = pcall(function() return I.getRoomMgr() end) if not ok or type(mgr) ~= 'table' then return 'клиент не держит комнат чата' end local seen = 0 for _, rd in pairs(mgr.roomDatas or {}) do if type(rd) == 'table' and type(rd.msgs) == 'table' then for _, m in ipairs(rd.msgs) do local p = nil pcall(function() p = tonumber(m.post) end) if p == 611 then seen = seen + 1 pcall(take, m) end end end end return 'в чате пакетов: ' .. seen .. ', забрано сейчас: ' .. (B.taken - before.taken) .. ', пропущено: ' .. (B.skipped - before.skipped) .. ', не смог: ' .. (B.failed - before.failed) end)() INTO swept
LOG "Красные пакеты в чате: {swept}"
CALL read_red_packet_watch
