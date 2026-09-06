# Send a chat message (text / emoji / sticker / coordinates) to a player DM or a channel.
# ru: Отправить сообщение в чат (текст / эмодзи / стикер / координаты) — в ЛС или в канал.
#
# The ability, in one file. It used to be a TOOL the chat tab spawned, which is why the
# phone had the chat's reading and no box to answer in (`CLAUDE.md`, «A press travels
# only when the ability is a scenario»); `CHAT_SEND` is the primitive that let it become
# a recipe, and `tools/chat_send.py` stayed on as the command line around the same code.
#
# WHAT IT IS GIVEN
#   room    the room to send into, outright:
#             World     country_<server>
#             National  custom_lang_<lang>_<server>
#             Alliance  alliance_<serverId>_<allianceId>
#             DM        custom_<peerUid>_<selfUid>_v2
#   to      a peer's uid instead — the DM room is built around it, with the sender's
#           own uid read live from the game
#   text    the message. Inline emoji are `{e:<id>}` tokens inside it and are resolved
#           to their glyphs before the send (`tools/chat_send.py --list-emoji` prints
#           the ids). A sticker is NOT text — the game will not carry one alongside a
#           message, so it travels in `sticker`.
#   sticker a sticker id, sent as its own message (`--list-sticker`)
#   coords  a coordinate to share as a tappable map pin — "600,400", "X:600 Y:400",
#           "@[600,400|100]" all read. A pin is not the text "600,400": the game
#           renders it into a bubble the receiver can tap.
#   server  the warzone of that coordinate, when the coordinate does not name one
#           (default: the sender's own)
#   label   the caption on the shared pin
#
# Text, a sticker and a pin may travel together — each is its own message, in that
# order. `CHAT_SENT` is left behind as 1 when the game confirmed every part of it.
#
# OUTGOING CHAT CANNOT BE UNSENT. The room is decided by the caller, on purpose: the
# panel shows which room the box is answering into before a word is typed.
#
# Everything runs inside the game's own Lua VM — no pixels, no foreground input. Text
# and emoji funnel through ChatManager2:__sendToRoom, stickers through
# ChatEmojiTemplateManager:TrySendSticker, and a pin through the chat connection's own
# share command (__sendToRoom drops the attachment). The reverse-engineering is written
# up in docs/research/chat-send.md and docs/research/chat-coord-share.md.
#
# SHARE — THE CHAT MUST NEVER BE THE REASON THE FARM WAITED (#2594). This recipe
# hands the message to the client's own sender, with no window open, so it keeps the
# client only for the moments it is actually talking to the game: between two
# statements, and between the polls of its own WAIT, it hands the link back to
# whoever is waiting. The person's rule, in their words: «Чат должен всегда работать
# в отдельном потоке и его действия ничего не должны блокировать».
SHARE
ARGS room =
ARGS to =
ARGS text =
ARGS sticker =
ARGS coords =
ARGS server =
ARGS label =
CHAT_SEND ROOM room TO to TEXT text STICKER sticker COORDS coords SERVER server LABEL label
