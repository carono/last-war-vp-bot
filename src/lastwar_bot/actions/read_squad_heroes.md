# Read which heroes are standing in each squad, and the picture the game draws them by.
# ru: Прочитать, какие герои стоят в каждом отряде, и картинку, которой их рисует игра.
#
# A READ, and nothing else: it presses nothing, opens nothing and changes nothing.
#
# WHAT IT IS FOR. Everywhere the panel asks «which squads may go» it used to draw four
# checkboxes numbered 1..4, and a number is not what a person recognises their own army
# by — they know it by the faces standing in it (#2062). So the picker draws the heroes,
# and this is the one read behind it.
#
# ONE READ, NEVER A POLL. A squad's composition changes when the PLAYER rearranges it,
# which is a thing that happens a few times a month and announces itself to nobody. So
# this runs on first need and then not again until somebody asks for it — the rule this
# repository works to (`CLAUDE.md`, «Read once, then LISTEN»). The panel's side of that
# is `panel/runtime/squad_picker.py`.
#
# The answer lands in ONE variable, `squad_heroes`, as one line of records separated by
# « | », one record per squad slot in the order the player sees:
#
#     squad=1 heroes=50006:Audie_Murphy,50009:Katyusha,50015:Tom
#
# Each hero is `id:stem`, where `stem` is the icon name out of the client's OWN config —
# `hero_icon_<stem>.png` in the extracted art (`tools/extract_hero_icons.py`). The stem
# is empty when the config would not name one, and then the panel falls back to the
# eyeball-confirmed table in `tools/lib/hero_icons_map.py` and, failing that, draws the
# squad's number. NOTHING IS GUESSED: a face nobody could name is no face at all, never
# a similar one (#2062).
#
# WHY THE STEM IS READ AND NOT LOOKED UP. The `heroId -> resName` table lives in a config
# datatable that is encrypted on disk (`docs/research/hero-icons.md`), which is why the
# repository's own table has ten ids in it and always will have. The RUNNING client has
# the table decrypted — it draws those faces every time the player opens the hero screen —
# and `LocalController.instance():getValue(...)` is the door #2051 opened onto it. Which
# table and which column hold the name is not written down anywhere, so the read TRIES
# the candidates once, keeps whichever answered, and reuses it for every hero after that.
#
# BEST-EFFORT ALL THE WAY DOWN, exactly like `read_squad_heroes`'s neighbour
# `read_squad_state.md`: every reach is wrapped, a manager that is not loaded costs one
# empty record and not the line, and a squad whose heroes cannot be read reports no
# heroes rather than somebody else's.

READ_LUA (function() local afd = DataCenter.ArmyFormationDataManager local inst = nil pcall(function() inst = LocalController.instance() end) local function num(v) local n = tonumber(v) if n == nil then return 0 end return math.floor(n) end local TABLES = {"lw_hero", "hero", "lw_hero_base", "lw_hero_info", "lw_hero_cfg"} local COLS = {"icon", "res_name", "resname", "head_icon", "hero_icon", "icon_name", "res", "pic_name"} local hitTable, hitCol = nil, nil local function ask(id, tb, col) local v = nil pcall(function() v = inst:getValue(tb, id, col) end) if type(v) == "string" and v ~= "" then return v end return nil end local function stem(id) if inst == nil or id <= 0 then return "" end if hitTable ~= nil then return ask(id, hitTable, hitCol) or "" end for _, tb in ipairs(TABLES) do for _, col in ipairs(COLS) do local v = ask(id, tb, col) if v ~= nil then hitTable, hitCol = tb, col return v end end end return "" end local function idOf(h) if type(h) == "table" then return num(h.heroId or h.HeroId or h.id or h.cfgId) end return num(h) end local function heroesOf(f, index) local tries = {} pcall(function() tries[#tries+1] = f:GetHeroList() end) pcall(function() tries[#tries+1] = f:GetHeroInfoList() end) pcall(function() tries[#tries+1] = f.heroList end) pcall(function() tries[#tries+1] = f.heroes end) pcall(function() tries[#tries+1] = f.heroInfoList end) pcall(function() tries[#tries+1] = f.armyList end) local H = nil pcall(function() H = DataCenter.HeroFormationDataManager or DataCenter.FormationDataManager end) if H ~= nil then pcall(function() tries[#tries+1] = H:GetFormationHeroList(index) end) pcall(function() tries[#tries+1] = H:GetHeroListByFormation(index) end) end for _, arr in ipairs(tries) do if type(arr) == "table" then local out = {} for _, h in pairs(arr) do local id = idOf(h) if id > 0 then out[#out+1] = id end end if #out > 0 then return out end end end return {} end local rows = {} pcall(function() for _, f in pairs(afd.ArmyFormationList) do rows[#rows+1] = f end end) table.sort(rows, function(a, b) return (tonumber(a.index) or 0) < (tonumber(b.index) or 0) end) local parts = {} for _, f in ipairs(rows) do local index = num(f.index) local faces = {} for _, id in ipairs(heroesOf(f, index)) do local s = stem(id) s = tostring(s):gsub("[^%w_%-]", "") faces[#faces+1] = id .. ":" .. s end parts[#parts+1] = "squad=" .. index .. " heroes=" .. table.concat(faces, ",") end return table.concat(parts, " | ") end)() INTO squad_heroes
