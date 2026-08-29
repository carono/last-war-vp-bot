# Read the chat history the client is already holding — every room, newest first.
# ru: Прочитать историю чата, которую клиент уже держит, — по всем комнатам.
#
# WHERE IT COMES FROM. The client keeps its own copy of every room it is sitting in:
# `Chat.ChatInterface.getRoomMgr().roomDatas[<room>].msgs`, filled by the very parse the
# chat listener hooks (`tools/chat_reader.py`). Reading it asks the SERVER nothing — it
# is the copy the client made when the messages arrived, which is exactly what «read
# once, then LISTEN» wants a FIRST read to be. Measured live: 7 rooms, 291 messages
# held, every one of them with a uid, a seqId and its own serverTime.
#
# WHAT IT DELIBERATELY DOES NOT DO. `ChatController.ChatRoomRequestHistoryMsg` would
# fetch DEEPER than what is held — that is a question to the server, and it is not asked
# here. What the client has is what this answers with; everything after it arrives on
# its own, through the listener.
#
# WHEN TO PLAY IT. Once, when a person opens the chat tab or presses «Загрузить
# историю» — never on a clock. The messages it brings back are folded into the same
# per-character store the listener writes to, on the same identity, so playing it twice
# adds nothing the second time.
#
# WHAT IT LEAVES BEHIND
#   chat    a JSON array of records, oldest first — `ts` (the message's own serverTime,
#           never the parse time), `room_id`, `chat_type`, `seq_id`, `sender_uid`,
#           `sender_name`, `msg`, and the avatar fields the tab draws a face from.
#
# `limit` is per ROOM: the newest that many of each. A room the client holds nothing for
# (every private conversation nobody has opened this session) is skipped rather than
# counted as empty — it is not «no history», it is history the client has not asked for.
ARGS limit = 40
READ_CHAT LIMIT {limit} INTO chat
