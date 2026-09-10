# Walk one sector and count what the CLIENT got, so our own tally can be subtracted.
# ru: Обход одного сектора и счёт того, что получил КЛИЕНТ, чтобы вычесть наш счёт.
#
# WHY IT EXISTS. Everything the panel knows about the map arrives through a passive pcap
# child, and a child that misses frames looks exactly like ground with nothing on it. So
# «ничего не утекает мимо нас» could only ever be an opinion: there was one count, ours,
# and nothing to compare it with.
#
# This is the second count. The client keeps its own store of every tile it has been
# answered about (`WorldScene.PointManager`), so the same box of ground can be counted
# twice at the same moment — once by the client and once by us — and the difference is
# the loss, per kind, in numbers.
#
# WHAT IT DOES NOT DO: press anything, spend anything, or send one byte beyond the camera
# jumps the walk itself makes. It is a READ with a walk in front of it.
#
# HOW TO READ THE ANSWER. `AUDIT_MAP` says what the CLIENT holds — `BuildPointInfo` a
# base, `ResPointInfo` a mine, `AllyCityPointInfo` an alliance city, and so on, because
# the kind is the class name of what the point store returns. The panel's own side is the
# capture's census (`##KINDS##`, `f2` counts) and the intake ledger; whoever presses this
# reads the two together.

# Which warzone the sector is on. Naming none is a bug in the caller, not a lap of
# wherever the camera happens to be: an empty warzone slot handed to the game's own jump
# loads the HOME world (#2727).
ARGS server = 0
# The sector's centre, in that warzone's own coordinates.
ARGS x = 500
ARGS y = 500
# Half the side of the box the client is counted over, in tiles. 40 is 81x81 = 6561
# lookups, about a fifth of a second, and comfortably inside what one stop at the
# task-carrying height loads.
ARGS box = 40
# The camera height. 600 is the last one at which secret-task and ghost-recon tiles still
# arrive; above it the map keeps sending bases and mines and stops sending tasks
# (docs/research/map-sweep-zoom.md), which would read as «no tasks here» about ground
# that is full of them.
ARGS zoom = 600

IF server == 0
    FAIL "audit_map_intake was called with no warzone — name the one the sector is on."

IF scene != world
    LOG "Putting the map up first — a sector read from the base counts nothing."
    GAME WORLD
    WAIT scene == world WITHIN 30s

LOG "Walking the sector at @[{x},{y}|{server}]."
VISIT_MAP POINTS {x},{y} ZOOM {zoom} EVERY 0.05 SERVER {server}

# THE BOX IS THE GROUND WE WALKED, NOT WHEREVER THE CAMERA ENDED UP (#2740). A walk and
# a read are two calls, and a neighbour taking the game link between them moves the
# camera: the first control run walked to one waypoint and counted a box around another,
# and only the camera on the answer line gave it away. The answer reports both.
AUDIT_MAP BOX {box} AT {x},{y} INTO client
LOG "The client holds, around @[{x},{y}|{server}]: {client}"
