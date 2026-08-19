# Ask the world's own monster register without touching the camera or the scene.
# ru: Спросить реестр монстров мира, не трогая камеру и не меняя сцену.
#
# THE SAME QUESTION `list_world_monsters.md` ASKS, WITH THE WALK TAKEN OUT — and that is
# the whole ability, because the walk is what makes the other one unrepeatable.
#
# What #1549 measured on a live client says why this file has to exist:
#
#   * the register is fed by **LOADING**, not by drawing, and a person panning the map by
#     hand loads exactly as the panel's own lap does. Over a hand-driven session it held
#     **176, 177, 321** monsters at three different moments — the map was never the
#     problem;
#   * the panel's monster page held **1** row in the same window, because nothing asks the
#     register unless a person presses one of three buttons, and a row that nobody
#     re-confirms ages out after fifteen minutes (`world.SIGHTING_TTL_SEC`);
#   * the asking itself is **36 ms**. `list_world_monsters.md` puts an eight-second camera
#     lap in front of it, which is right for a press and impossible on a clock: a poll
#     that throws the map about every twenty seconds takes the map away from the person
#     walking it.
#
# So this asks and nothing else. The person's own walking is the lap.
#
# **AND IT NEVER PUTS THE MAP UP.** `list_world_monsters.md` opens with `GAME WORLD`,
# which is right for a press — somebody who asked for monsters wants the map — and wrong
# for a poll, which would drag a person out of their base every twenty seconds. Here the
# scene is a GATE: on the map it asks, and off it the recipe answers nothing at all.
#
# The two answers are deliberately different, and the panel tells them apart:
#
#   * `monsters` set (even to an empty string) — the register was asked. An empty string
#     is «the map holds none», which is a fact.
#   * `monsters` never set — the client is not on the map, so there was nothing to ask.
#     Not an empty map, and the page says so rather than looking broken.

IF scene == world
    SCAN_MONSTERS INTO monsters
ELSE
    LOG "Not on the world map — the register is the world's own, and the base has none."
