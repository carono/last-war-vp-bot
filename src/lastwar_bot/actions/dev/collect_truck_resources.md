# Collect the resources from the truck parked on the base.
# ru: Собрать ресурсы с грузовика на базе.
#
# What the player does by hand: tap the truck standing on the base, press
# "collect", close the congratulation modal that lists the gifts. The recorded
# session (20260730_130004 «Сбор ресурсов с грузовика») shows all three steps are
# one and the same message with a different action number — a read, the collect,
# and one more read once the modal is gone. So no window is opened here and no
# modal has to be closed afterwards; this runs headless with the base on screen or
# not.
#
# The collect takes everything the truck holds in one press — base resources plus
# the bonus items — so it is a single TAP, never `xall`. There is no readiness
# check yet: pressing it when nothing is banked costs one refused call and the
# game's own tip, nothing worse.
#
# Still dev: written from the wire, not yet re-run in a live session.

TAP truck_reward_refresh    # ask the server what the truck is holding
TAP collect_truck_reward    # the "collect" press — takes the whole load
TAP truck_reward_refresh    # what closing the modal does: re-read the now-empty truck
