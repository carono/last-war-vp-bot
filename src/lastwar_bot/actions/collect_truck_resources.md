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
# THE UI IT LEAVES BEHIND, AND WHY ONE SWEEP IS NOT ENOUGH (#2642). The client raises
# a congratulation reward modal listing the gifts, and the truck's own menu stays open
# behind it. The sweep at the end (`dismiss_reward_popup`) closes what is standing at
# the moment it runs — and the modal is raised by the SERVER's answer, which may land
# after it. That is the window the person kept finding on screen. So the ear goes in
# FIRST: `watch_reward_popups` wraps the client's own reward-show and window-open calls,
# so a modal that arrives late is shut the instant it opens, by the client itself, with
# nothing asked of the game (docs/research/reward-popups.md). The sweep stays as the
# belt beside those braces, and the drain at the end says what was in the window.

TAP watch_reward_popups     # the ear FIRST: a modal that lands late is shut on arrival
TAP truck_reward_refresh    # ask the server what the truck is holding
TAP collect_truck_reward    # the "collect" press — takes the whole load
WAIT 1.5                    # let the server's answer — and its modal — arrive
TAP dismiss_reward_popup    # close the congratulation modal listing the gifts
TAP dismiss_truck_menu      # close the truck's own menu left open behind it
CALL collect_reward_popups  # bring back what the ear heard, and put it back in
