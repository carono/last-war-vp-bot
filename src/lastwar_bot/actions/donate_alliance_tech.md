# Donate to the alliance's priority (recommended) technology.
#
# Every line is just "tap a button". The messy engine calls behind each button
# (open this window, click that cell, press Donate) live in the button library
# tools/lib/game_buttons.py — a recipe never has to name them.

TAP alliance_tech     # the "Alliance Tech" button (opens the tech list directly)
TAP recommended_tech  # the tech marked as priority
TAP donate_1000 xall  # press "Donate 1000" for every attempt currently banked
TAP close x3          # close the windows we opened
