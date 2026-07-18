# Find secret tasks (hero dispatch) worth raiding.
#
# Unlike every other action here, this one does not read the screen. Secret
# tasks arrive as exact numbers in the game's own `world.get.block` traffic —
# level, coordinates and the list of players who already looted the task —
# so SCAN_SECRET_MISSIONS decodes them off the wire instead of guessing at
# pixels. See docs/research/protocol.md §7 for the field mapping.
#
# Requirements:
#   - Wireshark installed (the scan drives its `dumpcap` capture engine).
#   - **The map must be moving while the scan runs.** The game only sends
#     `world.get.block` as the map scrolls; a stationary map sends nothing
#     and the scan will correctly report zero tasks.
#
# Filters (all optional, any order):
#   LEVEL n       task level, read from cfgId
#   STAR          only starred tasks — PROVISIONAL, see tools/lastwar_proto.py
#   CAN_LOOT      at least one of the three loot slots still free
#   FREE_SLOTS n  stricter: at least n of the three free (3 = untouched)
#   WITHIN ns     how long to listen; returns early on the first match

# 1. The map has to be on screen for the game to request map blocks at all.
IF screen != world
    CALL go_to_world
    WAIT screen == world WITHIN 10s

# 2. Listen while the map scrolls. Level 7, starred, still lootable —
#    adjust the filters to taste.
SCAN_SECRET_MISSIONS LEVEL 7 STAR CAN_LOOT WITHIN 30s

# 3. Branch on what came back. Coordinates for each match are printed to the
#    run log; marching to them needs a navigate-to-coordinates primitive that
#    does not exist yet.
IF missions.count == 0
    LOG "No matching secret task in view — scroll the map and scan again."
ELSE
    LOG "Found raidable secret tasks; see the log lines above for coordinates."
