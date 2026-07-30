# Recruit every survivor waiting at the base.
# ru: Принять всех выживших, ждущих у ворот базы.

# Survivors walk up to the base and knock ("Собрать выжившего"); accepting one
# adds it as a worker. In game the flow is: tap the survivor, then tap the
# «Нанять»/agree button of the UIWorkerDetailRecruit window. On the wire that
# agree press is a single message, captured whole in trace 20260729_145441:
#
#     --> visitor.operate  {uid = <visitor uid>, operate = 1}
#
# so no window has to be opened — the button library reads the uid straight off
# the queued visitor. As with the other recipes, each line here is just "tap a
# button"; the real Lua lives in tools/lib/game_buttons.py (recruit_survivor),
# and the engine side is written up in docs/research/city-visitor-recruit.md.
#
# Detection & gate: visitors queue in DataCenter.CityVisitorManager; a survivor
# is a queue entry whose eventType == VisitorType.RECRUITMENT (3) and which has
# walked up to the base already (a queue entry exists before the visitor is
# spawned; the client leaves those alone too). The press is gated on there being
# at least one such visitor, so an empty queue costs no server round trip. `xall`
# recruits them one message at a time and re-reads the count, letting the
# server's push.user.visitor.change drain the queue instead of guessing a fixed
# number.
#
# Run it from the base, for the same reason as collect_visitor_gifts: a visitor is
# only ever walking up while the base is on screen, so from the world map nobody
# is "waiting" and the run is a quiet no-op.
#
# Proven live 2026-07-30 (task #1122), with a survivor actually knocking: one press,
# the survivor left (waiting 1 -> 0, visitor total 1 -> 0), its model disappeared
# from the base, and the gift visitor standing in the other queue was left alone.
#
# It took two fixes to get there, both of them a hardcoded value that read like a
# lookup. The kind was read off `visitorId`, a per-arrival counter, so the press
# picked "the third visitor of the session" whatever kind it was. And the queue was
# hardcoded to the first one, while the manager keeps two — survivors were queueing
# in the second, so the recipe could not see them at all and did nothing. Now it
# matches the kind across both queues.
#
# On a timer this must not count as done when it did nothing: survivors only walk up
# while the base is on screen, so off the base the run should FAIL and be retried
# (short retry_sec) rather than silently no-op and wait a whole interval. So the
# first thing it does is check the scene and bail if we are not in the city.

IF scene != city
    FAIL "not on the base (need the city scene) — retry later"

TAP recruit_survivor xall   # recruit until no survivor is left waiting
