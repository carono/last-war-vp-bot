# Translate ONE chat message with the game's own translator.
# ru: Перевести одно сообщение чата встроенным переводчиком игры.
#
# THE GAME ALREADY TRANSLATES, so nothing here goes to an outside service. The person's
# words (#2418): «В чате есть функция перевода, изучи её, сделай эту возможность». The
# client keeps the answer ON the message — `translateState`, `getTranslationMsg()`,
# `translatedLang` — and the button in the game is one call:
# `ChatManager2.Instance.Ctrl:OnChatTranslate(message)`.
#
# WHAT WAS MEASURED (live, 2026-09-04, an alliance room): before the call
# `translateState = 0` on every message the client held; three seconds after it the
# picked message read `state = 2` with a 39-character translation and
# `translatedLang = ru` — the language `ChatInterface.GetChatTranslateLanguageAbbr()`
# names, which is the player's OWN chat-translation setting rather than anything this
# panel chooses. `isShowTranslateBtn()` is the game's own «may this be translated», and
# a message it refuses is refused here too.
#
# THE ANSWER TRAVELS AS HEX, the same way the room names do: a translation may hold any
# byte, a space or a newline among them, and the recipe's readings are whitespace-split.
#
# WHAT IT LEAVES BEHIND
#   tr_state   the game's own state: 2 = translated, 0 = never asked, anything else is
#              the client still working or an error it reported
#   tr_text    the translation, hex-encoded utf-8 — empty when there is none
#   tr_lang    the language the client translated INTO (its own setting)
#
# SHARE — THE CHAT MUST NEVER BE THE REASON THE FARM WAITED (#2594). This recipe
# asks the client's own translator and waits for it, with no window open, so it keeps the
# client only for the moments it is actually talking to the game: between two
# statements, and between the polls of its own WAIT, it hands the link back to
# whoever is waiting. The person's rule, in their words: «Чат должен всегда работать
# в отдельном потоке и его действия ничего не должны блокировать».
SHARE
ARGS room =
ARGS seq =
LUA (function() local I = package.loaded["Chat.ChatInterface"] local mgr = I and I.getRoomMgr and I.getRoomMgr() local d = mgr and mgr.roomDatas and mgr.roomDatas["{room}"] DataCenter.__lw_tr = nil if not d then return end for _, m in ipairs(d:GetMsgs() or {}) do if tostring(m.seqId) == "{seq}" then DataCenter.__lw_tr = m end end local m = DataCenter.__lw_tr if not m then return end local ok, show = pcall(function() return m:isShowTranslateBtn() end) if ok and show == false then return end local M = package.loaded["Chat.ChatManager2"] pcall(function() M.Instance.Ctrl:OnChatTranslate(m) end) end)()
WAIT 3
READ_LUA (function() local m = DataCenter.__lw_tr if not m then return 0 end return tonumber(m.translateState) or 0 end)() INTO tr_state
READ_LUA (function() local m = DataCenter.__lw_tr if not m then return "" end local ok, t = pcall(function() return m:getTranslationMsg() end) if not ok or type(t) ~= "string" then return "" end return (t:gsub(".", function(c) return string.format("%02x", c:byte()) end)) end)() INTO tr_text
READ_LUA (function() local m = DataCenter.__lw_tr local l = m and m.translatedLang if type(l) ~= "string" or l == "" then local I = package.loaded["Chat.ChatInterface"] local ok, a = pcall(function() return I.GetChatTranslateLanguageAbbr() end) if ok and type(a) == "string" then return a end return "" end return l end)() INTO tr_lang
LOG "the game translated one message of {room}: state={tr_state}, into {tr_lang}"
