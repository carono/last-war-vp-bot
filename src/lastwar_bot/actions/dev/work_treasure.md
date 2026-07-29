# Work the map treasures — «сокровище на карте»: если ещё копается — копаем,
# если уже раскопано — собираем.
#
# UNPROVEN (in actions/dev/ on purpose). The sends and the dig-vs-dug rule are
# taken verbatim from one live capture (docs/research/world-treasures.md), but no
# treasure was on the map during the RE, so the dig->claim round-trip has NOT been
# fired end-to-end. Move to actions/ once it is confirmed against a live treasure.
#
# A world-map treasure (WorldPointType.TREASURE=21) is dug by alliance marches; while
# it is still being dug its point carries no operator uid, and once fully dug that
# field is filled with the finisher's uid. So per target there are two moves:
#   * still digging -> send a squad to dig it   (dig_treasure)
#   * already dug   -> claim the reward          (claim_treasure)
#
# TARGETS COME FROM OUTSIDE THIS RECIPE. `TAP` takes no arguments, so — exactly like
# steal_ghost_recon.md — the targets are parked in the game VM first, as a list on
# `DataCenter.__lw_treasure_queue`, each entry:
#     { pid=<tileIndex>, uuid=<long>, server=<int>, dug=<bool>, cross=<bool>,
#       formation=<squad uuid, optional> }
# `dug` is the operator-uid split above; `cross` is server ~= home. The finder is
# `tools/find_treasures.py --queue` (asks the server for the treasure list, parks what it
# finds); run it first — with nothing parked this recipe is a clean no-op. A shared dig
# squad for entries with no `formation` can be set once:
# `DataCenter.__lw_treasure_formation = <formation uuid>`.

# On the world map — the treasures live there.
GAME WORLD

# Nothing queued means nothing to do — say so instead of pressing blind.
READ_LUA (function() return #(DataCenter.__lw_treasure_queue or {}) end)() INTO targets
IF targets == 0
    LOG "No treasure queued — run the finder first (fills DataCenter.__lw_treasure_queue)."

# Walk the queue. For each head: dug -> claim, still digging -> dig. Each press pops
# the head, so the queue drains and `targets` counts down to zero.
WHILE targets > 0 LIMIT 20
    READ_LUA (function() local t=(DataCenter.__lw_treasure_queue or {})[1] if not t then return -1 end return t.dug and 1 or 0 end)() INTO dug
    IF dug > 0
        LOG "Сокровище раскопано — собираем."
        TAP claim_treasure
    ELSE
        LOG "Сокровище ещё копается — шлём отряд копать."
        TAP dig_treasure
    WAIT 1.5
    READ_LUA (function() return #(DataCenter.__lw_treasure_queue or {}) end)() INTO targets

# A successful claim raises the reward window — close it so the next run is clean.
TAP dismiss_treasure_reward
