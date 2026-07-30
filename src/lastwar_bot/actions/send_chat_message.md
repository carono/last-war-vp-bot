# Send a chat message (text / emoji / sticker / coordinates) to a player DM or a channel.
# ru: Отправить сообщение в чат (текст / эмодзи / стикер / координаты) — в ЛС или в канал.
#
# Unlike the other recipes, a chat send is PARAMETERISED (who + what), so it is not
# a fixed "tap a button" script — it is driven by the tool that carries the payload:
#
#     C:\Python312\python.exe tools\chat_send.py --to <peerUid> --text "Тест"
#     C:\Python312\python.exe tools\chat_send.py --to <peerUid> --text "hi {e:101}{e:106}"
#     C:\Python312\python.exe tools\chat_send.py --to <peerUid> --sticker 35
#     C:\Python312\python.exe tools\chat_send.py --to <peerUid> --coords "567,471"
#     C:\Python312\python.exe tools\chat_send.py --to <peerUid> --my-base
#     C:\Python312\python.exe tools\chat_send.py --room country_935 --text "hello world"
#     C:\Python312\python.exe tools\chat_send.py --to <peerUid> --text "hi" --dry-run
#     C:\Python312\python.exe tools\chat_send.py --list-emoji     # ids for {e:<id>}
#     C:\Python312\python.exe tools\chat_send.py --list-sticker   # sticker ids
#
# --to <uid>   builds the DM room custom_<peerUid>_<selfUid>_v2 (self uid is read
#              live from the game). --room targets any channel directly:
#                World     country_<server>
#                National  custom_lang_<lang>_<server>
#                Alliance  alliance_<serverId>_<allianceId>
#
# Emoji are inline: reference them in --text with {e:<id>} tokens; the tool resolves
# each id to its Private Use Area glyph before sending. Stickers are a separate
# manager call, so pass them with --sticker (not inside --text).
#
# Coordinates are NOT text: --coords "X,Y" shares a map pin (--coord-server /
# --coord-label / --coord-type tune it) and --my-base shares the player's own base
# the way the chat "share my position" button does. Accepted coordinate spellings are
# whatever tools/lib/coords.py parses ("X:567 Y:471", "@[567,471|935]", "(567,471)").
#
# Everything runs inside the game's own Lua VM through the warm daemon (no pixels,
# no foreground input). Text / emoji funnel through ChatManager2:__sendToRoom,
# stickers through ChatEmojiTemplateManager:TrySendSticker, and coordinates through
# ChatManager2.Net:SendSFSMessage("chat.room.send", ...) — __sendToRoom drops the
# attachment. The shared recipes live in tools/lib/lua_actions.py (chat_send_text /
# chat_send_sticker / chat_share_point); the reverse-engineering is written up in
# docs/research/chat-send.md and docs/research/chat-coord-share.md.
#
# Outgoing chat cannot be unsent — use --dry-run to preview the resolved room id and
# payload first.
