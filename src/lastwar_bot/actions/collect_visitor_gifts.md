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
# gift visitor is a queue entry whose eventType == VisitorType.GIFT (2) — versus
# RECRUITMENT (3) for a recruitable survivor — and which has walked up to the
# base already (a queue entry exists before the visitor is spawned; the client
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

TAP collect_visitor_gifts xall   # collect until no gift-bearing survivor is left
