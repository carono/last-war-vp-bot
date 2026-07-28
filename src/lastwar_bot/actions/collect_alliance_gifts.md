# Claim every alliance gift (ordinary + premium).
#
# The alliance "Gifts" screen (Подарки альянса) collects the boxes alliancemates
# and the alliance itself have banked for you. It has two "collect all" buttons —
# ordinary gifts (type 1) and premium / privilege gifts (type 2). This recipe
# presses both in one go.
#
# As with the other recipes, each line is just "tap a button"; the real Lua
# (DataCenter.AllianceGiftDataManager:SetAllGiftReceiveByType) lives in the button
# library tools/lib/game_buttons.py.
#
# No window is opened: the claim is sent straight from the data manager (the
# recorded flow's "open section" tap only loaded the list; the two collect taps
# each send alliance.reward.allreceive {type}). So there is nothing to close.
#
# Source: results/traffic/20260728_172314_Подарки_альянса_traffic.jsonl.
# See docs/research/alliance-gift-collection.md for the wire/Lua mapping and the
# verification caveat (the record had nothing pending, so the claim was gated).

TAP collect_alliance_gifts xall   # sweep both gift tabs until nothing is left to claim
