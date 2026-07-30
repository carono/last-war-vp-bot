# Collect every supply truck that has arrived at the base.
# ru: Забрать готовые грузовики с базы.
#
# A truck shows up on the base as a build bubble: BuildBubbleType.TruckTravelling
# while it is en route, TruckReward / TruckReady once it has arrived. This taps the
# ready bubbles via their OnClick handler — the literal reproduction of the
# "Сбор грузовика ресурсов" trace.
#
# Still dev: the enum values and bubble mechanism are confirmed live (a TruckReward
# and two TruckTravelling bubbles were observed), but OnClick has not yet been fired
# on a truck that was actually ready — verify when one is waiting, in case the ready
# bubble opens a window instead of collecting directly. See
# docs/research/resource-collection.md.

TAP collect_trucks
