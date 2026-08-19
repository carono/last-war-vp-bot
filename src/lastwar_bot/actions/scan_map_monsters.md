# Walk the map for MONSTERS, sampling what the client draws at every stop.
# ru: Обойти карту за МОНСТРАМИ, снимая на каждой остановке то, что нарисовал клиент.
#
# A lap of its own, and it has to be one, because monsters are the one thing on this map
# that is not on the wire. Every other kind — bases, mines, secret tasks, ghost squads —
# arrives in `world.get.block` and is decoded by a passive sniffer, so `scan_map.md` can
# throw the camera across the whole server in two and a half seconds and the answers land
# by themselves. A monster is computed CLIENT-SIDE (docs/research/world-monsters.md); the
# only copy of it is the object the client has DRAWN around wherever the camera is
# standing, and nobody is listening for those. They have to be picked up, stop by stop.
#
# **WHY THE PACE IS A SETTING AND NOT A CONSTANT** (#1523, all measured live on a
# 1000×1000 warzone, 121 waypoints at height 600, counting distinct monster tiles):
#
#     every 0.05 s  ->     22 monsters   (the ★ lap's pace: the camera has moved on
#                                          before the client has drawn anything)
#     every 0.30 s  ->     27
#     every 0.60 s  ->     33
#     every 1.20 s  ->    972              <- the cliff, and it is a cliff, not a slope
#     every 2.50 s  ->  1 059              (twice the clock for another 9%)
#
# **THE CURVE IS A CLIFF AND NOT A SLOPE, which is the whole finding.** Somewhere around
# a second the client's region loader starts keeping up, and the same lap over the same
# ground goes from thirty monsters to a thousand. Everything below it is a lap that looks
# like it worked and collects almost nothing — which is exactly what «монстров тысячи, а
# в гриде десятки» was. Above it the curve flattens at once: 2.5 s costs twice the clock
# for another nine per cent.
#
# So the default is **1.2 s — about 970 monsters in 147 s of camera** — and the operator
# owns the knob: below it is a cheap shallow lap, above it is minutes for single-digit
# percentages.
#
# **AND THE HEIGHT IS NOT ONE ANSWER EITHER.** How many monsters are drawn at once
# depends on it — measured at one view: 105 → 12, 300 → 24, 600 → 25, 1199 → 20 — while
# the ground one view covers grows with it, so a high lap needs fewer stops and a low one
# sees more per stop. Neither dominates, which is exactly why the caller passes both and
# a page that wants the map covered twice plays this twice.
#
# What it leaves behind is the game's own table, keyed by tile, which
# `read_world_monsters.md` drains. Nothing here writes to the panel: this lap FILLS, that
# read COLLECTS, and either may be run without the other.

ARGS server = 0
ARGS zoom = 600
ARGS step = 90
# Seconds the camera stands at each stop. Below ~0.3 the client draws nothing new and the
# lap is a fast way of collecting almost nothing; see the table above.
ARGS every = 1.2

IF scene != world
    LOG "Putting the map up first — a lap from the base draws no monsters."
    GAME WORLD
    WAIT scene == world WITHIN 30s

SWEEP_MAP ZOOM {zoom} STEP {step} EVERY {every} SERVER {server} HARVEST

# What the lap picked up, in the SAME record shape `read_world_monsters.md` answers with,
# so the panel has one parser and not two. Drained rather than copied: the table is the
# handover between the lap and this read, and a second read must not report the same lap
# twice as if the map had been walked again.
#
# A harvested row carries `src=lap`, its tile, the drawn object's own name and the level
# off its tag — never a uuid and never a config id, because a drawn clone has neither
# until it is selected.
READ_LUA (function() local DC=DataCenter.ActDispatchTaskDataManager local t=DC.__lw_mon if type(t)~='table' then return '' end local out={} for pid,v in pairs(t) do local nm,lv=tostring(v):match('^(.-)|(%d+)$') if nm==nil then nm=tostring(v) lv='0' end local x,y=-1,-1 pcall(function() local tp=SceneUtils.IndexToTilePos(tonumber(pid)) x,y=tp.x,tp.y end) out[#out+1]="src=lap pid="..tostring(pid).." x="..tostring(x).." y="..tostring(y).." uuid=0 cfg=0 type=0 level="..tostring(lv).." kind="..tostring(nm) end DC.__lw_mon={} DC.__lw_mon_n=0 DC.__lw_mon_s=0 return table.concat(out,' | ') end)() INTO monsters

LOG "One monster lap is done."
