# Collect every ready resource from the base's production buildings.
#
# One tap sweeps all producing city buildings and fires the game's own harvest
# call (BuildingUtils.CityCollectionByItemId) once per resource type — the server
# hands over whatever is ready and ignores the rest. This is the exact call the
# game makes when you tap a ready resource building by hand.
#
# Mechanism captured from the "Сбор ресурсов" trace
# (results/traces/20260728_171425_Сбор_ресурсов_trace.log, line
# `BuildingUtils.CityCollectionByItemId <- 10201000, <pos>, <pos>`). Verified live:
# the sweep targets ~11 resource-building kinds and runs clean. Full write-up in
# docs/research/resource-collection.md.

TAP collect_base_resources
