# Re-hear the tiles a list already holds, so their loot counts and their absence are true.
# ru: Переслушать тайлы, уже стоящие в списке, чтобы их счётчик краж и пропажа были правдой.
#
# THE CHECKING HALF OF A LAP, and a different errand from `scan_map.md` / the star round.
# A lap of the whole warzone FILLS a list: it walks 121 waypoints, hears twenty thousand
# tiles and finds whatever is out there. This walks only the squares the caller names,
# because the question is not «what is on this map» but «are the rows I am looking at
# still worth going to».
#
# WHY IT HAS TO BE THE MAP AT ALL (measured, #1484). «Сколько раз эту секретку уже
# ограбили» rides on the map tile and on nothing else: the per-tile answer a marker tap
# gets (`world.get.detail.new`) carries 45 fields and no stealer list, and the client's
# own alliance table covers MY alliance's tasks — which is none of a list built out of
# strangers' tiles. So a row that says «0/3, готово к сбору» about a tile emptied an hour
# ago can only be corrected by the map being driven over it again. Live, before this
# existed: 716 «состояние перечитано» lines in one profile's log, «обновлено» nought in
# every single one of them.
#
# NOTHING IS PRESSED AND NO WINDOW OPENS. The camera walks the waypoints and whatever
# passive capture is listening decodes what the server sends back — which is also the one
# thing this cannot do for itself: with the monitor down this is a camera walk that
# confirms nothing, so the panel refuses to start it rather than reporting a cheerful
# success (`panel/tabs/secret_tasks/tab.py`).
#
# ONE WARZONE PER RUN, and that is not a simplification. A capture indexes the warzone it
# is currently hearing and drops every tile of the one the client leaves the moment it
# leaves — measured: a lap of one warzone left 1434 tiles in the checkpoint and going
# home emptied it within four seconds. So a caller with rows on ten warzones plays this
# ten times and reads the checkpoint between the runs.

# The tiles to re-hear: `x,y` pairs separated by `;`, in the order they are walked.
ARGS points =
# How many of them, so an empty argument fails HERE with a sentence rather than inside
# the primitive. A `{name}` is substituted before the script is parsed, so the guard
# cannot be written against `points` itself — `IF` compares numbers.
ARGS count = 0
# WHICH warzone they are on. Compulsory: see the note above about what a capture keeps.
ARGS server = 0
# The last height at which the client still asks for secret-task tiles at all; one notch
# higher and bases keep arriving while the tasks stop, silently
# (docs/research/map-sweep-zoom.md).
ARGS zoom = 600
ARGS every = 0.05

IF count == 0
    FAIL "verify_secret_tasks was given no tiles — name them in `points`"
IF server == 0
    FAIL "verify_secret_tasks was given no warzone — name it in `server`"

# A walk from inside the base fetches no tiles and says so nowhere (#1335) — the same
# switch `scan_map.md` makes, for the same reason.
IF scene != world
    LOG "Putting the map up first — a walk from the base fetches no tiles."
    GAME WORLD
    WAIT scene == world WITHIN 30s

LOG "verify — re-hearing {count} tile(s) on warzone {server}"
VISIT_MAP POINTS {points} ZOOM {zoom} EVERY {every} SERVER {server}
LOG "verify_done — warzone {server} walked; what was heard is the capture's to say"
