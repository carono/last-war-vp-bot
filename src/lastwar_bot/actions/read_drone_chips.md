# Read what the bag holds of each drone chip chest — count, name and picture.
# ru: Прочитать, сколько сундуков чипов дрона в сумке — по каждому виду, с картинкой.
#
# The counting half of `open_drone_chips.md`, and the reason it is its own recipe: a
# page that SHOWS the chests must be able to ask without opening any (CLAUDE.md — the
# panel reads through a scenario or not at all). One call for the whole list.
#
# What comes back in `chips_rows`, one entry per id, joined by `` ;; ``:
#
#     540201|31|3|icon_item_540201|Сундук Чипа Навыка R
#
# — the id, how many the bag holds, the game's own rarity colour, the icon file the
# item wears (never computed from the id: an item's picture may belong to another
# number) and the name in whatever language the client is in.

# WHICH BOXES. Comma-separated item ids, as the bag reads them.
ARGS ids = 540201,540301,540401

LUA DataCenter.__lw_use_ids = '{ids}'

READ_LUA (function() local raw = tostring(DataCenter.__lw_use_ids or '') local D, T = DataCenter.ItemData, DataCenter.ItemTemplateManager if T == nil then return '' end local want, order = {}, {} for piece in string.gmatch(raw, '[^,]+') do local n = math.floor(tonumber(piece) or 0) if n > 0 and not want[n] then want[n] = 0 order[#order + 1] = n end end if D ~= nil then pcall(function() for _, v in pairs(D.ItemInfos or {}) do local id = math.floor(tonumber(v.itemId) or 0) if want[id] ~= nil then want[id] = want[id] + math.floor(tonumber(v.count) or 0) end end end) end local out = {} for _, id in ipairs(order) do local name, icon, colour = '', '', 0 pcall(function() name = tostring(T:GetName(id) or '') end) pcall(function() local row = T:GetItemTemplate(id) icon = tostring(row.icon or '') colour = math.floor(tonumber(row.color or row.quality) or 0) end) out[#out + 1] = id .. '|' .. want[id] .. '|' .. colour .. '|' .. icon .. '|' .. name end return table.concat(out, ' ;; ') end)() INTO chips_rows
LOG "chip chests: {chips_rows}"
