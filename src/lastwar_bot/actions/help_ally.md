# Help every alliancemate who has an open help request.
#
# Alliancemates ask for a speed-up on their builds / research; a single "Help All"
# press answers ALL of the pending requests at once. As with the other recipes,
# each line is just "tap a button" — the real Lua (one al.help.all message, built
# the way UILWAlHelpCtrl:OnClickHelpAll builds it) lives in the button library
# tools/lib/game_buttons.py.
#
# No window is opened: the message carries a single field (cmdBaseTime) and the
# reply refreshes the list by itself, so there is nothing to close afterwards.
# The press is gated on there being at least one request that is not my own —
# the same check the in-game button makes before it sends — so a quiet alliance
# costs no server round trip.
#
# Daily limit: helping is UNLIMITED. Only the daily HELP POINTS are capped at 1000
# (GetAllianceHelpSliderData -> {todayHelpPoint, maxHelpCount}); reaching the cap
# does not stop you from helping — it just stops the points from growing.

TAP help_ally_all xall   # press "Help All" until no request is left pending
