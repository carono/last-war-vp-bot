# The rooms the client is sitting in — every channel, group and thread it holds.
# ru: Комнаты, в которых сидит клиент, — все каналы, группы и переписки.
#
# WHY IT EXISTS. The panel used to know six chat tabs and nothing else, so a player's
# own custom group — the client holds it like any other room — had nowhere to be drawn
# and its forty messages were tipped into «Другие» beside the cross-server and season
# channels (#2418). The list of rooms is the CLIENT's, never a table in the code.
#
# WHERE IT COMES FROM. `Chat.ChatInterface.getRoomMgr().roomDatas` — the client's own
# per-room state, the same map `read_chat_history` reads the messages out of. Nothing is
# asked of the server, so this is what «read once, then LISTEN» wants a first read to be:
# play it when somebody opens the chat, never on a clock.
#
# WHAT IT LEAVES BEHIND
#   rooms   the rooms, `;;` between them: `<id>\t<name in hex>\t<messages held>`. The
#           reading travels as ONE line — a newline between rooms is cut off at the
#           first of them, measured — and the name is hex
#           because a group is named by a person and may hold any byte at all; the
#           caller decodes it. A room the client has no name for leaves that field empty.
READ_LUA (function() local I = package.loaded["Chat.ChatInterface"] if type(I) ~= "table" then return "" end local ok, mgr = pcall(function() return I.getRoomMgr() end) if not ok or type(mgr) ~= "table" then return "" end local function hex(s) if type(s) ~= "string" or s == "" then return "" end return (s:gsub(".", function(c) return string.format("%02x", string.byte(c)) end)) end local out = {} for key, rd in pairs(mgr.roomDatas or {}) do local msgs, name = 0, "" if type(rd) == "table" then if type(rd.msgs) == "table" then msgs = #rd.msgs end for _, f in ipairs({"roomName", "name", "title", "groupName"}) do local v = rd[f] if type(v) == "string" and v ~= "" then name = v break end end end out[#out+1] = tostring(key) .. "\t" .. hex(name) .. "\t" .. msgs end return table.concat(out, ";;") end)() INTO rooms
