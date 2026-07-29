# Join the alliance rallies that are out, one squad each.
#
# `squads` is which squad slots may be spent, in order — the 1/2/3 the player sees
# in the dispatch panel. Each squad goes to a DIFFERENT rally: `squads = [1]` joins
# only the first rally with squad 1, `squads = [2, 3]` joins two rallies, one with
# squad 2 and one with squad 3. With fewer rallies out than squads, the leftover
# squads simply stay home.
#
#   run join_rally                       -- all three squads, one rally each
#   run join_rally {"squads": [2, 3]}    -- only squads 2 and 3
#
# A rally is an alliance march the bot can read straight off the game (no map
# panning, no pcap): the leader's march carries the rally id, its target tile and
# server, which is everything a join needs. Rallies the player is already in are
# skipped, and so is a rally an earlier press in this same run has just joined —
# the server takes seconds to confirm, and waiting for it would let two squads land
# on the same rally.
#
# Nothing is opened on screen as long as one squad is already loaded. If every
# squad is cold the join would be a silent no-op, so the press loads them the way
# the game does and closes the panel it opens.
#
# The engine calls live in tools/lib/game_buttons.py ("join_rally") and
# tools/lib/lua_actions.py; the reverse-engineering is in
# docs/research/rally-join.md.
#
# UNPROVEN as a recipe: the calls behind it are the ones tools/rally_join.py joins
# with, but this file has not been run against a live rally yet.

ARGS squads = [1, 2, 3]

LUA DataCenter.__lw_rally_squads = { {squads} } DataCenter.__lw_rally_joined = {}
TAP join_rally xall   # one press per squad, each to a rally of its own
