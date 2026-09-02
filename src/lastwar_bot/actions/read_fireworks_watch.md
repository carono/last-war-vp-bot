# What the firework watcher has heard and taken — «что поймал караул салютов».
# ru: Что услышал и забрал караул салютов.
#
# The reading half of watch_fireworks.md. It presses nothing and sends nothing; what it
# hands back it also CLEARS from the ring, so two readers would each get half of it.
#
# The answer is one line, because a `READ_LUA` carries one value:
#
#     on=1 pushes=14 presses=1 taken=1 failed=0 lastMs=3 bestMs=3 onRecord=29 rows=[…]
#
#   on        is the hook still installed? `0` after a client restart — the VM is fresh
#             and everything the watcher knew went with it. Re-arm rather than wonder.
#   pushes    announcements heard since it was armed.
#   presses   times it had something to take; `taken` is how many boxes went out.
#   foreign   announcements that were ANOTHER alliance's firework: heard, never pressed
#             at, and never asked about (#1899).
#   noAlliance boxes whose `allianceUid` the client does not carry. They are NOT pressed
#             either (#2365): a press is made only for a box that names OUR alliance, so
#             a box that names none is skipped rather than tried and refused.
#   away      announcements that arrived while the camera was on ANOTHER server. Nothing
#             is pressed and nothing is asked there: `get.fireworks.info.list` answers
#             `firework_tips_1013, "not in this server"` and the client shows the player
#             a popup for it (#2365).
#   lastMs    **milliseconds from the push arriving to the press leaving** — the number
#             the whole ability is measured by. `bestMs` is the smallest one seen.
#   onRecord  how many boxes this account has ever been given, as the CLIENT counts them
#             (`giftUuid2TimeTable`) — the one authority, never a tally the panel keeps.

READ_LUA (function() local B = DataCenter.__lw_fww local G = DataCenter.LWFireworkGiftManager local got = 0 for _ in pairs((G and G.giftUuid2TimeTable) or {}) do got = got + 1 end if not B then return 'on=0 pushes=0 presses=0 taken=0 failed=0 foreign=0 noAlliance=0 away=0 lastMs=-1 bestMs=-1 onRecord=' .. got .. ' rows=[]' end local rows = table.concat(B.rows, '; ') B.rows = {} return 'on=' .. (B.on and 1 or 0) .. ' pushes=' .. B.pushes .. ' presses=' .. B.presses .. ' taken=' .. B.taken .. ' failed=' .. B.failed .. ' foreign=' .. (B.foreign or 0) .. ' noAlliance=' .. (B.blind or 0) .. ' away=' .. (B.away or 0) .. ' lastMs=' .. B.lastMs .. ' bestMs=' .. B.bestMs .. ' onRecord=' .. got .. (B.err ~= '' and (' err=' .. B.err) or '') .. ' rows=[' .. rows .. ']' end)() INTO watch
LOG "Fireworks watch: {watch}"
