# Collect every ready resource from the base's production buildings.
#
# One tap = the base's own "Collect All". The base's resource generators are
# production lines (DataCenter.ProductLineManager); collecting one is
# SendCollect(uuid), and the game's Collect-All button just fires that for every
# ready building. This button does the same — it loops GetAllBuildUuids() and
# calls SendCollect on the buildings that have at least one unit banked
# (GetBuildingCurrStorage >= 1). No window has to be open.
#
# The readiness gate is not cosmetic: collecting a building that is still
# producing is rejected by the server (errorCode 602026, "In production, please
# be patient.") and the client pops one toast per rejection.
#
# Verified live: sweeping all 38 production buildings dropped their pending
# storage from ~29k to ~6k (16 ready -> 0); after the gate landed, 36 collects
# went out and 36 succeeded with zero rejections. Full write-up in
# docs/research/resource-collection.md.

TAP collect_base_resources
