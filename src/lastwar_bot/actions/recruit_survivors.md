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
# is a queue entry with visitorId == VisitorType.RECRUITMENT (3). The press is
# gated on there being at least one such visitor, so an empty queue costs no
# server round trip. `xall` recruits them one message at a time and re-reads the
# count, letting the server's push.user.visitor.change drain the queue instead
# of guessing a fixed number.
#
# Proven live 2026-07-29: pending 1 -> 0, total visitors 5 -> 4 after one send.

TAP recruit_survivor xall   # recruit until no survivor is left waiting
