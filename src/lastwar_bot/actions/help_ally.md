# Help every alliancemate who has an open help request.
#
# Alliancemates ask for a speed-up on their builds / research; a single "Help All"
# press answers ALL of the pending requests at once. As with the other recipes,
# each line is just "tap a button" — the real Lua (one al.help.all message, built
# the way UILWAlHelpCtrl:OnClickHelpAll builds it) lives in the button library
# tools/lib/game_buttons.py.
#
# NB — `TAP help_ally_all` is NOT a screen tap on a button inside the alliance
# window. It is a headless Lua send. It reproduces the ALWAYS-VISIBLE main-screen
# help element (the bottom-bar `HelpBubbleTip`, hosted by
# UI.LWMainUI.Component.UIMainBottom.MainAllianceBubbles) — that bubble and the
# window's "Help All" button both fire the one and only al.help.all up-message
# (Net.Msgs.Alliance.AlHelpAllMessage; there is no other alliance help-all
# command), which this recipe sends directly. So EVERY window can be closed and
# the help still goes out. Verified live: with the alliance window never opened,
# GetAllianceHelpList() still reads the pending requests (it is push-populated by
# push.al.help.new), and the al.help.all send lands. See docs/research/alliance-help.md.
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
