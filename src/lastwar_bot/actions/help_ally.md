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
# The press is gated on somebody actually waiting, so a quiet alliance costs no server
# round trip. That gate reads TWO numbers, not one: the client's help list (requests that
# are not mine) AND the red-point count. A request that arrived while the bot was running
# is only in the second — `push.al.help.new` bumps the counter and never touches the list
# — so the list alone made this recipe press zero times for exactly the requests it was
# meant to answer. See docs/research/alliance-help.md.
#
# This recipe is the on-demand version — you run it and it answers whatever is waiting
# right now. For the standing order there is the panel's «Авто-помощь союзникам»
# checkbox: it listens for `push.al.help.new` on the wire and fires this very same press
# the second a request arrives, so none of them sits unanswered
# (tools/alliance_help_monitor.py, docs/research/alliance-help.md).
#
# Daily limit: helping is UNLIMITED. Only the daily HELP POINTS are capped at 1000
# (GetAllianceHelpSliderData -> {todayHelpPoint, maxHelpCount}); reaching the cap
# does not stop you from helping — it just stops the points from growing.

TAP help_ally_all xall   # press "Help All" until no request is left pending
