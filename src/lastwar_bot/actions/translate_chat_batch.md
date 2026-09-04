# Translate SEVERAL chat messages with the game's own translator, in one round trip.
# ru: Перевести несколько сообщений чата встроенным переводчиком игры за один заход.
#
# WHY A BATCH EXISTS AT ALL (#2418). The person asked for messages to be translated as
# they arrive: «пусть на все новые сообщения … сразу переводить». One message at a time
# is `translate_chat_message.md`, and it costs the game link a call, a three-second wait
# and three readings — near enough four seconds, whether it translates one message or
# would have translated twenty. Measured on this account's own chat: 1.5 messages a
# minute over a quiet hour, 8.2 over the busiest hour and 22.4 in the busiest ten
# minutes. At four seconds each the busy hour alone would spend half the link on
# translation, and the busy ten minutes would want more link than there is.
#
# So the asks are issued together and the answers read together: N translations cost one
# wait, not N. The panel decides WHEN to flush and how many to send (`chat.py`); this
# recipe does what it is handed.
#
# THERE IS NO LANGUAGE ON A MESSAGE — measured, not assumed. The message object has an
# `originalLang` field and the server never fills it: 40 of 40 empty in a live alliance
# room, and still empty on a message the game had just translated (`translateState = 2`,
# `translatedLang = ru`). `isShowTranslateBtn()` is the game's own «may this be
# translated» and it answered true for 39 of those 40, so it is a permission and not a
# language. Whoever turns this on is choosing to translate everything the game will
# translate, including what is already in their own language.
#
# THE ANSWERS TRAVEL AS HEX, joined without whitespace, because a reading is split on
# spaces and a translation may hold any byte.
#
# WHAT IT LEAVES BEHIND
#   tr_done    `seq=hex,seq=hex,…` — one pair per message that came back translated,
#              or `none` when nothing did
#   tr_lang    the language the client translated INTO (its own setting)
ARGS room =
ARGS seqs =
LUA (function() local I = package.loaded["Chat.ChatInterface"] local mgr = I and I.getRoomMgr and I.getRoomMgr() local d = mgr and mgr.roomDatas and mgr.roomDatas["{room}"] _G.__LW_TRB = {} if not d then return end local want = {} for s in ("{seqs}"):gmatch("[^,]+") do want[s] = true end local M = package.loaded["Chat.ChatManager2"] for _, m in ipairs(d:GetMsgs() or {}) do local id = tostring(m.seqId) if want[id] then local ok, show = pcall(function() return m:isShowTranslateBtn() end) if not ok or show ~= false then _G.__LW_TRB[id] = m pcall(function() M.Instance.Ctrl:OnChatTranslate(m) end) end end end end)()
WAIT 3
READ_LUA (function() local out = {} for id, m in pairs(_G.__LW_TRB or {}) do local ok, t = pcall(function() return m:getTranslationMsg() end) if ok and type(t) == "string" and t ~= "" then out[#out+1] = id .. "=" .. (t:gsub(".", function(c) return string.format("%02x", c:byte()) end)) end end if #out == 0 then return "none" end return table.concat(out, ",") end)() INTO tr_done
READ_LUA (function() local I = package.loaded["Chat.ChatInterface"] local ok, a = pcall(function() return I.GetChatTranslateLanguageAbbr() end) if ok and type(a) == "string" then return a end return "" end)() INTO tr_lang
LOG "the game translated a batch of {room} into {tr_lang}"
