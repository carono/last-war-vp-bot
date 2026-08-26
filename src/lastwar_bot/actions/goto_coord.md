# Walk the camera to one tile — what pressing a coordinate does, wherever it is shown.
# ru: Перевести камеру на клетку — то, что делает нажатие на координату, где бы она ни была.
#
# THE ABILITY BEHIND A LINK (#1982). The person's rule: «любые координаты должны быть
# кликабельны и приводить к переходу на них в игре». A press is a press, so it plays a
# recipe like every other one — the front-end passes what it read off the text and
# nothing else (`CLAUDE.md`, «Everything is a scenario»).
#
# NOTHING IS SPENT. This walks the client's own camera: no march, no troops, no daily
# allowance, and the server is asked only for the tiles that come into view. That is why
# the press asks no question first — a jump is undoable by jumping back.
#
# THE SERVER IS THE WHOLE DIFFICULTY, and it is why there are two branches. `JUMP x, y`
# stays on the warzone the client is looking at, resolved inside the chunk; `JUMP x, y, s`
# ENTERS warzone `s` (`GoToUtil.GotoWorldPos` — the real cross-server jump, #1272). A
# zero would be neither: it is a warzone that does not exist, and it used to be the
# fallback that sent the camera nowhere. So zero means «wherever we are».

ARGS x = 0
ARGS y = 0
ARGS server = 0

IF server > 0
    LOG "jumping to #{server} X:{x} Y:{y}"
    JUMP {x}, {y}, {server}
ELSE
    LOG "jumping to X:{x} Y:{y} on the warzone the client is on"
    JUMP {x}, {y}
