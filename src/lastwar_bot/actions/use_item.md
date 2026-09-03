# Use an item from the bag — this item, this many.
# ru: Применить предмет из сумки — этот, столько-то штук.
#
# The general form of `use_stamina.md`: it takes the item's own config id and a count,
# and spends that many out of the bag. The bag keeps one entry per STACK, so a hundred
# of something may be several entries, and each is spent no further than it goes.
#
# **The send is `item.use` with a table** — `{uuid = <the stack's own uuid>, num = n}`.
# That is the shape a live recording of the fireworks caught, and the only one of five
# tried that this client will serialise (docs/research/inventory.md).
#
# **A kind of item the bag will not use is refused before anything leaves.** The client
# exposes no «can this be used» flag — the row it keeps carries an id, an icon and two
# type numbers, and `CheckUseStateTool` answers `true` for a hero shard as readily as for
# a potion — so the kinds are listed in `tools/lib/lua_actions.py`
# (`USABLE_ITEM_TYPES`): speed-ups, resource packs and potions, and chests. Anything else
# is answered `not-usable` and nothing is spent. A guess that spends somebody's shard is
# not a mistake that can be taken back.
#
# What it reports, in `use_report`:
#
#     id=400401 want=20 used=20 kind=3 why=-
#
# ## Arguments
#
#   item    the item's own config id, as the bag reads it.
#   count   how many to use. More than the bag holds spends what there is and says so.

ARGS item = 0
ARGS count = 1

LUA DataCenter.__lw_use_id = {item}
LUA DataCenter.__lw_use_num = {count}

TAP use_item
WAIT 2

READ_LUA (function() local u = DataCenter.__lw_use or {} return 'id=' .. tostring(math.floor(tonumber(u.id) or 0)) .. ' want=' .. tostring(math.floor(tonumber(u.want) or 0)) .. ' used=' .. tostring(math.floor(tonumber(u.used) or 0)) .. ' kind=' .. tostring(math.floor(tonumber(u.kind) or -1)) .. ' why=' .. tostring(u.why or '-') end)() INTO use_report
LOG "used: {use_report}"

READ_LUA (function() local u = DataCenter.__lw_use or {} return math.floor(tonumber(u.used) or 0) end)() INTO used

IF used == 0
    FAIL "nothing was used — {use_report}"

# …AND IF WHAT WAS OPENED WAS A CHEST, LOOK FOR THE PACKET IT MAY HAVE DROPPED (#2397).
# A surprise box sometimes gives the player a red packet of free diamonds to hand to the
# alliance, and only for an hour. The drop is announced by nothing anybody has named, so
# the person's decision was to check at the two moments that cost nothing: HERE — the run
# that opened the box — and every half hour (the `lucky_share` errand).
#
# WHAT COUNTS AS «OPENING A BOX» is the item's own kind, as the game files it:
# `USABLE_ITEM_TYPES` calls 5, 59, 109 and 150 chests and boxes (2 and 3 are speed-ups and
# resource packs, which never drop a packet). So a speed-up costs this recipe nothing at
# all, and a chest costs one local reading.
#
# The check is LAST on purpose and the give-away is a sub-recipe with its own gate: it
# neither stops nor fails this run when there is nothing to share.
READ_LUA (function() local u = DataCenter.__lw_use or {} local k = math.floor(tonumber(u.kind) or -1) if k == 5 or k == 59 or k == 109 or k == 150 then return 1 end return 0 end)() INTO was_chest
IF was_chest == 1
    CALL share_lucky_packet
