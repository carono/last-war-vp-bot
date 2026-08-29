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
#     squad=1 heroes=40007:Elsa,50009:Katyusha,50015:Tom
#
# Each hero is `id:stem`, where `stem` is the icon name — `hero_icon_<stem>.png` in the
# extracted art (`tools/extract_hero_icons.py`). NOTHING IS GUESSED: a hero the client
# would not name is left out rather than drawn as somebody who looks like him (#2062).
#
# HOW THE TWO HALVES MEET, which took three live reads to settle and is written down so
# that nobody pays for them again:
#
#   * A FORMATION DOES NOT HOLD HERO IDS. `ArmyFormationDataManager.ArmyFormationList`
#     gives one entry per squad, and its `heroList` / `heroes` answer with POSITIONS
#     (1..5), not with heroes. What does hold the link is `localIndexToHeroDic` —
#     `{position -> hero uuid}`, with `remoteIndexToHeroDic` beside it saying the same.
#   * THE ROSTER TURNS A UUID INTO A HERO. `DataCenter.HeroDataManager:GetAllHeroList()`
#     returns every hero the player owns, each with its `uuid` and its `heroId`. That is
#     the whole of the join: uuid off the formation, id off the roster.
#   * THE PORTRAIT'S NAME IS IN THE CONFIG, TWO HOPS AWAY, and the running client has it
#     decrypted (`LocalController.instance():getValue`). `lw_hero[id].appearance` is the
#     look a hero wears, and `lw_hero_appearance[appearance].half_icon_path` is literally
#     `hero_icon_<stem>` — the name of the extracted file. `queue_icon_path` says the same
#     and is tried after it. So the encrypted on-disk table
#     (`docs/research/hero-icons.md`) is not needed at all, and the panel's own
#     eyeball-confirmed table of ten ids is only the fallback for a client that would not
#     answer. A hero's `bigName` is NOT the stem — it is the display name
#     (`hero_show_name_Murphy` against a file called `hero_icon_Audie_Murphy`), which is
#     why it is read nowhere here.
#
# TWO LOOKUPS PER HERO, EACH REMEMBERED. The stem is cached per hero id inside the one
# call, so a squad of five costs at most ten config reads and a repeated hero costs none.
# That is what keeps this inside the ninety seconds an action is given — the version that
# guessed at columns for every hero timed out and held the game link for all of it.
#
# BEST-EFFORT ALL THE WAY DOWN, exactly like this recipe's neighbour
# `read_squad_state.md`: every reach is wrapped, a manager that is not loaded costs one
# empty record and not the line, and a squad whose heroes cannot be read reports no
# heroes rather than somebody else's.

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if not ok or n == nil then return 0 end return math.floor(n) end local inst = nil pcall(function() inst = LocalController.instance() end) local stems = {} local function stem(id) if stems[id] ~= nil then return stems[id] end local out = "" if inst ~= nil then local app = 0 pcall(function() app = num(inst:getValue("lw_hero", id, "appearance")) end) if app == 0 then app = id end for _, col in ipairs({"half_icon_path", "queue_icon_path"}) do if out == "" then pcall(function() local v = inst:getValue("lw_hero_appearance", app, col) if type(v) == "string" then out = v end end) end end end out = tostring(out):gsub("[^%w_%-]", "") stems[id] = out return out end local byUuid = {} local hm = nil pcall(function() hm = DataCenter.HeroDataManager end) if hm ~= nil then local list = nil for _, call in ipairs({"GetAllHeroList", "GetHeroList", "GetAllHero"}) do if list == nil then pcall(function() local v = hm[call](hm) if type(v) == "table" then list = v end end) end end if type(list) == "table" then for _, h in pairs(list) do if type(h) == "table" then pcall(function() local u = tostring(h.uuid) local id = num(h.heroId) if id == 0 then id = num(h.modelId) end if u ~= "" and id > 0 then byUuid[u] = id end end) end end end end local afd = nil pcall(function() afd = DataCenter.ArmyFormationDataManager end) local rows = {} pcall(function() for _, f in pairs(afd.ArmyFormationList) do rows[#rows+1] = f end end) table.sort(rows, function(a, b) return num(a.index) < num(b.index) end) local parts = {} for _, f in ipairs(rows) do local dic = nil pcall(function() if type(f.localIndexToHeroDic) == "table" then dic = f.localIndexToHeroDic end end) if dic == nil then pcall(function() if type(f.remoteIndexToHeroDic) == "table" then dic = f.remoteIndexToHeroDic end end) end local faces = {} if dic ~= nil then local slots = num(f.slots) if slots < 1 then slots = 5 end for pos = 1, slots do pcall(function() local u = dic[pos] if u ~= nil then local id = byUuid[tostring(u)] if id ~= nil then faces[#faces+1] = id .. ":" .. stem(id) end end end) end end parts[#parts+1] = "squad=" .. num(f.index) .. " heroes=" .. table.concat(faces, ",") end return table.concat(parts, " | ") end)() INTO squad_heroes
