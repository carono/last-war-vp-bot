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
# BEST-EFFORT ALL THE WAY DOWN, exactly like this recipe's neighbour
# `read_squad_state.md`: every reach is wrapped, a manager that is not loaded costs one
# empty record and not the line, and a squad whose heroes cannot be read reports no
# heroes rather than somebody else's.
#
# AND IT ASKS THE CONFIG AT MOST ONCE PER COLUMN, which is not fussiness — the first
# version tried five table names by eight column names for EVERY hero, and a lookup into
# a config table the client has not got is expensive: the read took longer than the
# ninety seconds an action is given and timed out, holding the game link for all of it
# (#2062). So: one table (`lw_hero`), the column remembered the moment one answers, and
# the whole probe abandoned after a single miss. A number below 1000 is a slot position
# and never a hero id — the formation's own list answers with those — so it is not looked
# up at all.

READ_LUA (function() local afd = DataCenter.ArmyFormationDataManager local inst = nil pcall(function() inst = LocalController.instance() end) local function num(v) local n = tonumber(v) if n == nil then return 0 end return math.floor(n) end local COLS = {"icon", "res_name", "resname", "head_icon", "hero_icon", "icon_name", "res", "pic_name"} local hitCol, tried = nil, false local function ask(id, col) local v = nil pcall(function() v = inst:getValue("lw_hero", id, col) end) if type(v) == "string" and v ~= "" then return v end return nil end local function stem(id) if inst == nil or id < 1000 then return "" end if hitCol ~= nil then return ask(id, hitCol) or "" end if tried then return "" end for _, col in ipairs(COLS) do local v = ask(id, col) if v ~= nil then hitCol = col return v end end tried = true return "" end local function idOf(h) if type(h) ~= "table" then return 0 end return num(h.heroId or h.HeroId or h.cfgId or h.id) end local function heroesOf(f) local tries = {} pcall(function() tries[#tries+1] = f:GetHeroList() end) pcall(function() tries[#tries+1] = f.heroList end) pcall(function() tries[#tries+1] = f.heroes end) pcall(function() tries[#tries+1] = f.heroInfoList end) for _, arr in ipairs(tries) do if type(arr) == "table" then local out = {} for _, h in pairs(arr) do local id = idOf(h) if id >= 1000 then out[#out+1] = id end end if #out > 0 then return out end end end return {} end local rows = {} pcall(function() for _, f in pairs(afd.ArmyFormationList) do rows[#rows+1] = f end end) table.sort(rows, function(a, b) return (tonumber(a.index) or 0) < (tonumber(b.index) or 0) end) local parts = {} for _, f in ipairs(rows) do local faces = {} for _, id in ipairs(heroesOf(f)) do local s = stem(id) s = tostring(s):gsub("[^%w_%-]", "") faces[#faces+1] = id .. ":" .. s end parts[#parts+1] = "squad=" .. num(f.index) .. " heroes=" .. table.concat(faces, ",") end return table.concat(parts, " | ") end)() INTO squad_heroes
