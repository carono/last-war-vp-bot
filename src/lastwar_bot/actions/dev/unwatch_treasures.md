# Stop keeping treasure messages and put the client's two network doors back.
# ru: Перестать запоминать сообщения про сокровища и вернуть клиенту его функции.
#
# The end of watch_treasures.md. It takes the wrappers off `SFSNetwork.SendMessage` and
# `SFSNetwork.HandleMessage` rather than merely muting them, because a hook left on is a
# hook the next person has to know about — and the sniffer's tracer wraps the same two
# functions, so it would end up wrapping a wrapper.
#
# STOPPING IS NOT THROWING AWAY. What the ring already holds stays there and can still
# be read with read_treasure_watch.md; the last thing recorded is usually the interesting
# one. What does empty it is a client restart: the buffer lives in the game VM.

TAP treasure_watch_off

# Say what is left, so a caller can drain the tail rather than assume it is gone.
READ_LUA (function() local W = DataCenter.__lw_treasure_watch if not W then return 'on=0 wide=0 buf=0 seq=0 drop=0 cap=0' end return 'on=' .. tostring(W.on and 1 or 0) .. ' wide=' .. tostring(W.wide and 1 or 0) .. ' buf=' .. tostring(#(W.items or {})) .. ' seq=' .. tostring(W.seq or 0) .. ' drop=' .. tostring(W.drop or 0) .. ' cap=' .. tostring(W.cap or 0) end)() INTO watch
