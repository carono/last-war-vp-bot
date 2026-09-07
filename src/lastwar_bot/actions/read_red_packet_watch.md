# What the chat ear has heard and taken — «что поймал караул красных пакетов».
# ru: Что услышал и забрал караул чужих красных пакетов в чате.
#
# The reading half of `watch_red_packets.md`. It presses nothing and sends nothing, and
# it asks the SERVER nothing: both halves of the answer are already in the client.
#
# The answer is one line, because a `READ_LUA` carries one value:
#
#     on=1 heard=3 taken=2 skipped=1 failed=0 liked=2 likeFailed=0 closed=2 likesLeft=8
#     lastMs=4 bestMs=3 today=2 max=10 rows=[…]
#
#   on      is the hook still installed? `0` after a client restart — the VM is fresh
#           and everything the ear knew went with it. The trigger `red_packet_watch`
#           re-arms it; this reading is how a person sees that it needs to.
#   heard   red-packet announcements parsed since the ear was armed.
#   taken   presses that left. `skipped` is the gates saying no — quota, expired,
#           another server, an unknown room, or a packet already pressed at.
#   liked   gifts thanked for — the like the person presses by hand, proven by the
#           client's own day count dropping (`likesLeft`, ten a day) and not by a
#           send that did not raise. `likeFailed` is a like that left no mark.
#   closed  windows the ear shut behind itself over the chat.
#   lastMs  milliseconds from the announcement arriving to the press leaving. The
#           number the whole ability is measured by, exactly as the fireworks watch.
#   today   packets this account has taken today, as the CLIENT counts them
#           (`GetRedPacketGetNum` / `GetRedPacketGetMaxNum` — 10 a day, measured live).
#           The one authority there is; the panel keeps no tally of its own.
#   rows    the last twenty words the ear said to itself, and it CLEARS them, so two
#           readers would each get half. No uuid and no nickname is ever in them.
READ_LUA (function() local M = DataCenter.RedPacketManager local inst = M and (M.Instance or M) local today, max = -1, -1 pcall(function() today = math.floor((inst:GetRedPacketGetNum() or 0) + 0) end) pcall(function() max = math.floor((inst:GetRedPacketGetMaxNum() or 0) + 0) end) local thanks = -1 pcall(function() thanks = math.floor((InteractiveUtil.GetCanThumbsUpCount(61) or 0) + 0) end) local B = DataCenter.__lw_rpw if B == nil then return 'on=0 heard=0 taken=0 skipped=0 failed=0 liked=0 likeFailed=0 closed=0 likesLeft=' .. thanks .. ' lastMs=-1 bestMs=-1 today=' .. today .. ' max=' .. max .. ' rows=[]' end local rows = table.concat(B.rows or {}, '; ') B.rows = {} return 'on=' .. (B.on and 1 or 0) .. ' heard=' .. B.heard .. ' taken=' .. B.taken .. ' skipped=' .. B.skipped .. ' failed=' .. B.failed .. ' liked=' .. (B.liked or 0) .. ' likeFailed=' .. (B.likeFailed or 0) .. ' closed=' .. (B.closed or 0) .. ' likesLeft=' .. thanks .. ' lastMs=' .. B.lastMs .. ' bestMs=' .. B.bestMs .. ' today=' .. today .. ' max=' .. max .. (B.err ~= '' and (' err=' .. B.err) or '') .. ' rows=[' .. rows .. ']' end)() INTO watch
LOG "Караул красных пакетов: {watch}"
