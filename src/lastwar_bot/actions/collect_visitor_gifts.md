# Collect every gift a survivor brought to the base.

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
# Detection & gate: visitors queue in DataCenter.CityVisitorManager; a gift
# visitor is a queue entry with visitorId == VisitorType.GIFT (2) — versus
# RECRUITMENT (3) for a recruitable survivor. The press is gated on there being
# at least one such visitor, so an empty queue costs no server round trip.
# `xall` collects them one message at a time and re-reads the count, letting the
# server's push.user.visitor.change drain the queue instead of guessing a number.
#
# Not yet proven live: the send is reconstructed from trace 20260729_151712
# (SendMessage(visitor.operate, uid, 1) → coin-box DoFly → UICityVisitor closed).
# The companion traffic capture was empty (0 B), so only the trace attests it.

TAP collect_visitor_gifts xall   # collect until no gift-bearing survivor is left
