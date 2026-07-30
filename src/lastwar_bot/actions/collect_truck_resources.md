# Collect the resources from the truck parked on the base.
# ru: Собрать ресурсы с грузовика на базе.
#
# What the player does by hand (recording 20260730_130004 «Сбор ресурсов с
# грузовика»): tap the truck standing on the base, press "collect", then close the
# congratulation modal that lists the gifts. The collect itself is headless — the
# tap, the collect and the client's re-read are all one wire message with a
# different action number, so no window has to be opened to take the load.
#
# The collect takes everything the truck holds in one press — base resources plus
# the bonus items — so it is a single TAP, never `xall`. There is no readiness
# check yet: pressing it when nothing is banked costs one refused call and the
# game's own tip, nothing worse.
#
# The collect does leave UI on screen, though: the client raises a congratulation
# reward modal listing the gifts, and the truck's own menu stays open behind it. So
# after the collect this tidies up — dismiss the reward modal, then close the truck
# menu — leaving the base clean for whatever runs next.

TAP truck_reward_refresh    # ask the server what the truck is holding
TAP collect_truck_reward    # the "collect" press — takes the whole load
TAP dismiss_reward_popup    # close the congratulation modal listing the gifts
TAP dismiss_truck_menu      # close the truck's own menu left open behind it
