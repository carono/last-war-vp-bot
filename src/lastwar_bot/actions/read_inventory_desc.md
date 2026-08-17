# Read the description text of named items, in the player's own language.
# ru: Прочитать описания названных предметов — на языке самого игрока.
#
# A READ, and nothing else. The companion of `read_inventory.md`, split off it for one
# measured reason: a live bag holds 371 items whose names come to 16 KB and whose
# DESCRIPTIONS come to 58 KB, and the bag is re-read every time the game says the
# balance moved. A description never changes, though — it is a line in the client's own
# table — so it is asked for ONCE per item and kept in the profile's database.
#
# So the caller passes only the ids it does not know yet:
#
#     ARGS ids = 850113,400204,701000
#
# An empty list is not an error — it answers with nothing, which is what a panel whose
# cache is already complete should cost.
#
# The answer lands in `descs`, records separated by « #|# », two fields separated by
# « ;; » with the TEXT last:
#
#     850113;;Use it to raise a survivor's stars and make them stronger!
#
# An id the client cannot describe is left out entirely rather than sent as a blank, so
# the caller can tell «no description» from «not asked».

ARGS ids =

READ_LUA (function() local T=DataCenter.ItemTemplateManager if T==nil then return '' end local out={} for one in string.gmatch('{ids}', '[^,%s]+') do local id=tonumber(one) if id~=nil then local ds='' pcall(function() ds=tostring(T:GetDes(id) or '') end) if ds~='' then out[#out+1]=id..';;'..ds end end end return table.concat(out,' #|# ') end)() INTO descs
