# Switch the reward-popup ear on or off.
# ru: Включить или выключить слушатель наградных окон.
#
# WHAT THE SWITCH ON «Триггеры» PLAYS (#2408). The ability itself is
# `actions/collect_reward_popups.md` — an ear inside the client that closes the «вот что
# вам дали» modals and writes down what was in them. It had no card of its own because it
# is in no catalogue: nothing on «Триггеры» could say whether it was on, and nothing
# could turn it off.
#
# The wish is one global in the client, `DataCenter.__lw_rewards_off`, and it is
# deliberately NOT a field of the ear's own ring: every recipe that earns something puts
# the ear back as it goes, so a wish stored in the ring would be rebuilt away by the next
# collect — a switch that flips itself back on.
#
# Switching it on also installs the ear, so the card's box and the client agree the moment
# the box is ticked rather than at the next collect.

ARGS on = 1

IF on > 0
    TAP hear_reward_popups
    TAP watch_reward_popups
    LOG "reward_popups_switch: on"
ELSE
    TAP mute_reward_popups
    LOG "reward_popups_switch: off"
