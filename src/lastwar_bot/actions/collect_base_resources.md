# Collect every ready resource from the base's production buildings.
#
# One tap = the base's own "Collect All". The base's resource generators are
# production lines (DataCenter.ProductLineManager); collecting one is
# SendCollect(uuid), and the game's Collect-All button just fires that for every
# ready building. This button does the same — it loops GetAllBuildUuids() and
# calls SendCollect on each. An already-empty building simply no-ops, so no
# readiness check and no window are needed.
#
# Verified live: sweeping all 38 production buildings dropped their pending
# storage from ~29k to ~6k (16 ready -> 0). Full write-up in
# docs/research/resource-collection.md.

TAP collect_base_resources
