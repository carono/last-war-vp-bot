# Read what is in the bag: every item the client holds, with its count, rarity and icon.
# ru: Прочитать сумку: все предметы клиента — количество, редкость и иконка.
#
# A READ, and nothing else: it presses nothing, opens nothing, sends nothing to the
# server. No window has to be open — the bag is a manager the client keeps loaded from
# login, so this answers in one call from any scene.
#
# WHERE THE LIST COMES FROM. `DataCenter.ItemData.ItemInfos` — a table keyed by the
# item's own uuid, one entry per STACK, each carrying `itemId`, `count` and the config
# row it was made from. It is not a push and it is not a capture: the client already
# holds it, and `push.resource.item.update` (the «your balance changed» push the panel
# already listens for) only moves numbers inside it. The two managers the panel used to
# guess at — `ItemDataManager` and `BagDataManager` — do not exist in this client at
# all, which is why nothing was ever read (#1469).
#
# WHAT A RECORD SAYS. The game's bag shows ONE cell per item id with the total on it, so
# the stacks are summed here rather than in the panel: several uuids of the same id
# collapse into one record. Every field is the game's own answer —
# `ItemTemplateManager:GetName(id)` returns the name already in the player's language,
# so nothing here is ever translated by the panel (`CLAUDE.md`, «Not one word of the
# panel is written in the panel»).
#
# The answer lands in ONE variable, `items`, as records separated by « #|# », each of
# them six fields separated by « ;; » with the NAME last:
#
#     850113;;12;;5;;137;;icon_item_850409;;Shard of Some Hero
#
#   * id     — the item's config id (`itemId`).
#   * count  — how many, summed over every stack of that id.
#   * colour — the rarity, 1..6, the config row's `color`. It is what picks the frame
#              the game draws behind the picture (`GetToolBgByColor`), so the panel
#              composes the same two layers rather than inventing a border of its own.
#   * type   — the config row's `type`, the tab the game's own bag would file it under.
#   * icon   — the sprite name, `icon` on the config row. NOT derivable from the id: a
#              hero shard is filed under one id and wears another hero's picture.
#   * name   — the item's name, in the player's language, from the game's own table.
#
# A field the game will not answer is left at its «unknown» value rather than guessed:
# every read is wrapped, so an item whose row is missing costs one blank and not the
# whole reading. The description is deliberately NOT here — 371 items carry some 58 KB
# of it, and the bag grid does not show it; `read_inventory_item.md` fetches one on
# demand when somebody opens a cell.

READ_LUA (function() local D=DataCenter.ItemData local T=DataCenter.ItemTemplateManager if D==nil then return '' end local agg,order={},{} for _,v in pairs(D.ItemInfos or {}) do local id=nil pcall(function() id=tonumber(v.itemId) end) if id~=nil then local a=agg[id] if a==nil then a=0 order[#order+1]=id end agg[id]=a+(tonumber(v.count) or 0) end end local out={} for _,id in ipairs(order) do local nm,ic,co,ty='','',0,0 pcall(function() nm=tostring(T:GetName(id) or '') end) local tpl=nil pcall(function() tpl=T:GetItemTemplate(id) end) if tpl~=nil then pcall(function() ic=tostring(tpl.icon or '') end) pcall(function() co=tonumber(tpl.color) or 0 end) pcall(function() ty=tonumber(tpl.type) or 0 end) end out[#out+1]=id..';;'..agg[id]..';;'..co..';;'..ty..';;'..ic..';;'..nm end return table.concat(out,' #|# ') end)() INTO items
