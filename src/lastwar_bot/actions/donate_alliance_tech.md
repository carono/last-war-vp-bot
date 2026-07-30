# Donate to the alliance's priority (recommended) technology.
# ru: Донат в приоритетную (рекомендованную) технологию альянса.
#
# One line, because the donate press needs no window open: the controller method
# behind "Donate 1000" touches no window state, so it is called straight on the
# module and the player's view is left exactly as it was found. `xall` reads how
# many attempts are banked, spends all of them in a single call into the game (a
# round trip costs ~0.15 s and the loop inside it is free, so a full quota is one
# call) and re-reads the count to confirm the server took them.
#
# The messy engine calls live in the button library tools/lib/game_buttons.py and
# the Lua in tools/lib/lua_actions.py — a recipe never has to name them. The
# reverse-engineering is written up in docs/research/alliance-tech-donate.md.

TAP donate_1000 xall  # press "Donate 1000" for every attempt currently banked
