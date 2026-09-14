# The day's «Мировой поход»: fill the lineups, press auto-challenge in every open zone, take both rewards.
# ru: Дневной «Мировой поход»: собрать отряды, нажать авто-испытание во всех открытых зонах, забрать обе награды.
#
# The errand a clock plays once a day, and the whole of the event in one run:
#
#   1. a lineup — the account's own first squad — is put into every open zone that has
#      none, which is how a zone that unlocked today gets played on the day it unlocked;
#   2. «авто-испытание» is pressed in every open zone. It rations nothing: no attempts,
#      no stamina, no item, so a day costs the account nothing but the pressing;
#   3. both reward lists are claimed — the zone's own tiers and the points tiers.
#
# A ROUND IS FOURTEEN DAYS and opens its four zones on days 1, 3, 5 and 7; when it ends
# everything resets and the next one begins. A zone that is not open yet is skipped and
# nothing is retried over it — it will be there tomorrow.
#
# LOSING IS THE ORDINARY END OF A DAY. The auto challenge climbs until the lineup is
# beaten, and «упёрлись в сильного соперника» is the answer rather than a fault: the run
# ends well, the clock keeps its place, and tomorrow's press tries the same wall again
# with whatever the account has grown since. Nothing here ever stops trying because a day
# cleared nothing.
#
#     ARGS squad = 1      which of the player's squads the lineup is taken from
#
# The reading behind the card is `read_world_expedition.md`; the reverse engineering is
# `docs/research/world-expedition.md`.

ARGS squad = 1

CALL read_world_expedition

IF open == 0
    LOG "Мировой поход: раунд не идёт — сегодня делать нечего"
    STOP

IF live == 0
    LOG "Мировой поход: ни одна зона ещё не открыта"
    STOP

CALL world_expedition_lineup
CALL world_expedition_sweep
CALL collect_world_expedition_rewards
