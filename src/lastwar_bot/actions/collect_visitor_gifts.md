# Collect every gift a survivor brought to the base.
# ru: Забрать подарки, принесённые выжившими.

# Some survivors walk up to the base carrying gifts ("Собрать подарки
# выжившего"); tapping one and collecting flies a reward (a coin box in trace
# 20260729_151712). On the wire the collect press is a single message, the same
# one a recruit sends — only the visitor kind differs:
#
#     --> visitor.operate  {uid = <visitor uid>, operate = 1}
#
# so no window has to be opened — the button library reads the uid straight off
# the queued visitor. As with the other recipes, each line here is just "tap a
# button"; the real Lua lives in tools/lib/game_buttons.py (collect_visitor_gifts),
# and the engine side is written up in docs/research/city-visitor-recruit.md.
#
# Detection & gate: visitors queue in DataCenter.CityVisitorManager — in two
# queues, both of which are searched, because a kind is not tied to one of them. A
# gift visitor is a queue entry whose eventType is one the game itself calls a
# gift — versus RECRUITMENT for a recruitable survivor — and which has walked up
# to the base already (a queue entry exists before the visitor is spawned; the client
# leaves those alone too). The press is gated on there being at least one such
# visitor, so an empty queue costs no server round trip. `xall` collects them one
# message at a time and re-reads the count, letting the server's
# push.user.visitor.change drain the queue instead of guessing a number.
#
# Run it from the base. Visitors are only ever walking up while the base is on
# screen: leaving it deletes their models, entering it starts them again, and the
# spawn is on a timer of its own. From the world map, then, nothing is "arrived"
# and this is a quiet no-op — nothing is lost, the gifts keep waiting, but the run
# does nothing until the base is back on screen.
#
# Proven live 2026-07-30 (task #1122): a queue of four gift visitors, one of them
# not yet arrived, collected 3 -> 0 in three sends; the visitor count went 3 -> 0
# server-side and the unarrived one stayed queued. Until then the recipe pressed
# nothing at all: the kind was read off `visitorId`, which is a per-arrival
# counter, not the VisitorType.
#
# Which kinds those are is asked of the client rather than listed here. A season
# brings its own survivors to the same gate with the same present, so the kinds are
# every entry of the game's own `VisitorType` enum whose NAME says "gift" — four of
# them live on 2026-09-01 (#2083): the ordinary one, the season's daily one, the
# survivor-pack one and the system one. A written-down list would have collected the
# old ones and walked past the season's, saying nothing about it; this way a season
# that adds a fifth is collected the day it opens.
#
# Visitors only walk up while the base is on screen, so a run made from the map is a
# no-op — and it used to be written as `FAIL`, which #2070 measured: the radar and the
# treasure errands leave the client on the WORLD map and nothing puts it back, so this
# row failed 69 times in one day and collected nothing. The scene is not a precondition
# somebody else owes us, it is one call. So the run RETURNS to the base and only gives
# up when the client will not go.

IF scene != city
    GAME CITY
    WAIT scene == city WITHIN 30s

TAP collect_visitor_gifts xall   # collect until no gift-bearing survivor is left
