# Help every alliancemate who has an open help request.
#
# Alliancemates ask for a speed-up on their builds / research; a single "Help All"
# press answers ALL of the pending requests at once. As with the other recipes,
# each line is just "tap a button" — the real Lua (DataCenter.AllianceHelpDataManager:
# OnHelpAll) lives in the button library tools/lib/game_buttons.py.
#
# No window is opened: OnHelpAll reads the help list and sends the al.help.all
# message straight from the data manager, so there is nothing to close afterwards.
#
# Daily limit: helping is UNLIMITED. Only the daily HELP POINTS are capped at 1000
# (GetAllianceHelpSliderData -> {todayHelpPoint, maxHelpCount}); reaching the cap
# does not stop you from helping — it just stops the points from growing.

TAP help_ally_all xall   # press "Help All" until no request is left pending
