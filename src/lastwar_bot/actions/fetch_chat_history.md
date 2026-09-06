# Ask the SERVER for chat older than the client holds, for one room.
# ru: Попросить у сервера историю чата старше той, что держит клиент, — для одной комнаты.
#
# WHY THIS IS A SEPARATE RECIPE FROM `read_chat_history.md`. That one reads the copy the
# client already made and asks the server NOTHING, which is what a first read must be.
# This one is the other half the person asked for (#2064): «Опрос сервера при прокрутке
# тоже сделай, если у нас нет сообщений» — when the store and the client are both spent
# and a thumb is still travelling upwards, there is nowhere left to look but the server.
#
# WHAT IT PRESSES. `ChatManager2.Instance.Ctrl:ChatRoomRequestHistoryMsg(roomId, sort)`,
# measured live 2026-08-29 on `country_935`: `sort = 0` is BACKWARDS and brings 100
# messages per call (47 → 148 → 248 held, `GetFirstMsgServerTime` walking back from
# 1787963199672 to 1787949750850); `sort = 1` adds nothing at all, which is what the
# forward direction has to say when the client is already at «now». So this asks with 0
# and only with 0.
#
# WHY IT IS SAFE TO CALL IT REPEATEDLY. The cursor is the CLIENT's — each call asks for
# what lies before the oldest message it holds — so a second call fetches the slice
# before the first and never the same one twice. The room's own `GetIsChatHistoryEnd()`
# is the server's «that is all there was», remembered by the client per room; the request
# is not even sent once it stands.
#
# WHEN TO PLAY IT. On a PERSON's scroll, after the panel's own store has run out — never
# on a clock, and never speculatively. It is the one place in the chat where the panel
# talks to the server, and it costs a round trip every time.
#
# WHAT IT LEAVES BEHIND
#   history_end   1 when the server has said this room has nothing older, else 0
#   held_before /
#   held_after    how many messages the client held for this room before and after the
#                 ask — their difference is what the server actually sent, and 0 is
#                 either the end or a request it did not answer inside the wait
#   chat          the same JSON array `READ_CHAT` always answers with — the newest
#                 `limit` of EVERY room the client holds, the freshly fetched ones
#                 among them, oldest first
#
# SHARE — THE CHAT MUST NEVER BE THE REASON THE FARM WAITED (#2594). This recipe
# asks the server and waits for the reply, with no window open, so it keeps the
# client only for the moments it is actually talking to the game: between two
# statements, and between the polls of its own WAIT, it hands the link back to
# whoever is waiting. The person's rule, in their words: «Чат должен всегда работать
# в отдельном потоке и его действия ничего не должны блокировать».
SHARE
ARGS room =
ARGS limit = 400
READ_LUA (function() local I = package.loaded["Chat.ChatInterface"] local mgr = I and I.getRoomMgr and I.getRoomMgr() local d = mgr and mgr.roomDatas and mgr.roomDatas["{room}"] if not d then return -1 end return #(d:GetMsgs()) end)() INTO held_before
IF held_before < 0
    LOG "the client is not sitting in room {room} — nothing to ask the server about"
    STOP
LUA local M = package.loaded["Chat.ChatManager2"] local I = package.loaded["Chat.ChatInterface"] local d = I.getRoomMgr().roomDatas["{room}"] local over = d:GetIsChatHistoryEnd() if not over then M.Instance.Ctrl:ChatRoomRequestHistoryMsg("{room}", 0) end
WAIT 3
READ_LUA (function() local I = package.loaded["Chat.ChatInterface"] local d = I.getRoomMgr().roomDatas["{room}"] return #(d:GetMsgs()) end)() INTO held_after
READ_LUA (function() local I = package.loaded["Chat.ChatInterface"] local d = I.getRoomMgr().roomDatas["{room}"] local over = d:GetIsChatHistoryEnd() if over then return 1 end return 0 end)() INTO history_end
LOG "the server was asked for room {room}: the client held {held_before} and holds {held_after} now, end={history_end}"
READ_CHAT LIMIT {limit} INTO chat
