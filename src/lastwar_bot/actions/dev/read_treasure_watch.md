# Read the treasure messages the watcher has been keeping, and empty what was read.
# ru: Прочитать накопленные сообщения игры про сокровища и очистить прочитанное.
#
# The other half of watch_treasures.md. It presses nothing, sends nothing and changes
# nothing in the game — but it is not a plain read either: what it hands back it REMOVES
# from the ring, so two readers would each get half the feed. One reader at a time.
#
# THE ANSWER IS ONE JSON OBJECT in the variable `feed`, because a `READ_LUA` carries one
# value and that value travels as one line of the client's log:
#
#     {"on":1,"wide":0,"n":4,"more":0,"drop":0,"seq":128,"items":[
#        {"i":125,"t":1785322473766,"d":"in","c":"world.treasure.share.chat",
#         "f":"uuid=1000000000000000001 x=571 y=456"}, … ]}
#
#   on     is the hook still installed? 0 after a client restart — the VM is fresh and
#          everything the watcher knew is gone with it. Re-arm rather than wonder.
#   wide   is it keeping every message, or only the treasure ones?
#   n      how many entries this drain returned; `items` has exactly that many.
#   more   how many are still queued. **Not zero means call again**, right away: the
#          drain stops at 25 entries or ~6000 characters, whichever comes first,
#          because a log line cut in half loses the whole drain rather than one entry.
#   drop   how many the ring dropped since the last drain — its own confession that it
#          overflowed. Reported once and cleared, so counting it twice would read as
#          twice the loss.
#   seq    how many messages it has kept in total, ever. A number that does not move
#          between drains means the client is saying nothing, not that the read failed.
#
# Each entry: `i` the sequence number, `t` the GAME's clock in milliseconds (the PC's
# lies — docs/research/game-clock.md), `d` the direction (`out` the client sent it, `in`
# the client received it), `c` the command, `f` its fields flattened to `k=v` pairs — a
# send has no names to read so its arguments are numbered `a1 a2 …`, a push carries the
# server's own field names. A nested object is named `{...}` and not walked: one level is
# what a feed line can hold.
#
# The values are the ACCOUNT's — uuids, servers, coordinates, names. They belong on
# screen and in a saved feed file; never in this repository (CLAUDE.md).
#
# Who plays it: the «Сокровища» debug page (`panel/tabs/treasure_debug/`), on a timer
# while the watch is on, so the ring is drained long before it can overflow.

READ_LUA (function() local W = DataCenter.__lw_treasure_watch if not W then return '{"on":0,"wide":0,"n":0,"more":0,"drop":0,"seq":0,"items":[]}' end local function q(s) s = tostring(s or '') if #s > 400 then s = s:sub(1,400) .. '...' end s = s:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('%c', ' ') return '"' .. s .. '"' end local items = W.items or {} local parts, used = {}, 0 while #parts < 25 and #items > 0 and used < 6000 do local it = table.remove(items, 1) local one = '{"i":' .. tostring(it.i or 0) .. ',"t":' .. tostring(it.t or 0) .. ',"d":' .. q(it.d) .. ',"c":' .. q(it.c) .. ',"f":' .. q(it.f) .. '}' used = used + #one parts[#parts+1] = one end local drop = W.drop or 0 W.drop = 0 return '{"on":' .. tostring(W.on and 1 or 0) .. ',"wide":' .. tostring(W.wide and 1 or 0) .. ',"n":' .. tostring(#parts) .. ',"more":' .. tostring(#items) .. ',"drop":' .. tostring(drop) .. ',"seq":' .. tostring(W.seq or 0) .. ',"items":[' .. table.concat(parts, ',') .. ']}' end)() INTO feed
