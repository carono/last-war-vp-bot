# Claim the alliance gifts — ordinary and premium.
#
# Reproduces exactly what the player did in the "Подарки альянса" recording: open
# the alliance Gifts section, then press its two "collect all" buttons — ordinary
# gifts first, then premium/privilege gifts.
#
# Each line is just "tap a button"; the engine calls live in the button library
# tools/lib/game_buttons.py. Behind them: opening the window sends
# alliance.reward.list; each collect button is UILWAllianceGiftCtrl:OnGetAllBtnClick
# (type) and sends alliance.reward.allreceive {type} (type 1 = ordinary, 2 = premium).
# A tab with nothing to claim just no-ops, so pressing both is always safe.
#
# The two collect buttons are real UI clicks, so the window must be open first —
# that is why this recipe opens the section and closes it at the end (unlike the
# headless help_ally / collect_base_resources recipes).
#
# Source: results/traffic/20260728_172314_Подарки_альянса_traffic.jsonl.
# Live-confirmed in-game (premium gifts collected on OnGetAllBtnClick(2)); see
# docs/research/alliance-gift-collection.md.

TAP alliance_gifts          # open the "Подарки альянса" section
TAP collect_gifts_ordinary  # "collect all" on the ordinary-gifts tab (type 1)
TAP collect_gifts_premium   # "collect all" on the premium-gifts tab (type 2)
TAP close                   # close the gift window
