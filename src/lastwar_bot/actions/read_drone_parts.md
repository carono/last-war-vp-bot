# Read what the bag holds of each drone-component chest — count, name and picture.
# ru: Прочитать, сколько сундуков компонентов дрона в сумке — по каждому виду, с картинкой.
#
# The counting half of `open_drone_parts.md`, and the reason it is its own recipe: a
# page that SHOWS the chests must be able to ask without opening any (CLAUDE.md — the
# panel reads through a scenario or not at all). One call for the whole list.
#
# THE NAMES ARE NOT THE SAME THING, and the confusion has cost a task already (#2617).
# «Сундук Компонента Дрона N ур.» — 630011…630013 — is what THIS file counts, and it is
# the duel's WEDNESDAY. «Сундук Чипа Навыка» — 540201…540401 — is Monday's, and it is
# `read_drone_chips.md`. Neither file touches the other's boxes.
#
# What comes back in `parts_rows`, one entry per id, joined by `` ;; ``:
#
#     630011|12|3|icon_item_630011|Сундук Компонента Дрона 1 ур.
#
# — the id, how many the bag holds, the game's own rarity colour, the icon file the
# item wears (never computed from the id: an item's picture may belong to another
# number) and the name in whatever language the client is in.

# WHICH BOXES. Comma-separated item ids, as the bag reads them.
ARGS ids = 630011,630012,630013

LUA DataCenter.__lw_use_ids = '{ids}'

READ_LUA (function() local raw = tostring(DataCenter.__lw_use_ids or '') local D, T = DataCenter.ItemData, DataCenter.ItemTemplateManager if T == nil then return '' end local want, order = {}, {} for piece in string.gmatch(raw, '[^,]+') do local n = math.floor(tonumber(piece) or 0) if n > 0 and not want[n] then want[n] = 0 order[#order + 1] = n end end if D ~= nil then pcall(function() for _, v in pairs(D.ItemInfos or {}) do local id = math.floor(tonumber(v.itemId) or 0) if want[id] ~= nil then want[id] = want[id] + math.floor(tonumber(v.count) or 0) end end end) end local out = {} for _, id in ipairs(order) do local name, icon, colour = '', '', 0 pcall(function() name = tostring(T:GetName(id) or '') end) pcall(function() local row = T:GetItemTemplate(id) icon = tostring(row.icon or '') colour = math.floor(tonumber(row.color or row.quality) or 0) end) out[#out + 1] = id .. '|' .. want[id] .. '|' .. colour .. '|' .. icon .. '|' .. name end return table.concat(out, ' ;; ') end)() INTO parts_rows
LOG "drone-component chests: {parts_rows}"
