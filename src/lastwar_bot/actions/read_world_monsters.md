# Read the monsters the client can see on the world map, with their kind and level.
# ru: Прочитать монстров, которых клиент видит на карте мира, — вид и уровень.
#
# A READ, and nothing else: it presses nothing, opens nothing and changes nothing.
#
# **This one cannot be a capture, and that is measured rather than assumed.** Every other
# thing on the map — bases, mines, secret tasks, ghost squads, alliance cities, treasures
# — arrives in `world.get.block` and is read off the wire by the passive sniffer. Monsters
# do not. Checked against incremental pans (141 new tiles), a full load of an unvisited
# district (1490 tiles, 1029 mines, every family at every level), `push.world.point.update`,
# a re-login including the 443 KB `init`, and a switch to a server not visited that day —
# roughly 2000 unique tiles, and **zero** objects above the 1..10 mine level range while
# levels 12..28 were on screen throughout (docs/research/protocol.md, «Monsters are not on
# the wire»). Monster placement is computed CLIENT-SIDE from map configuration; the server
# only validates and scores what is done to one. So the only place a monster list exists is
# the client's own memory, which is what this reads.
#
# It follows from that that this read is **as wide as the client's view**, not as wide as
# the map: a lap of the map (`scan_map.md`) fills the sniffer's tables for every other kind,
# and leaves this one holding whatever is drawn around the camera when it stops. Run it
# after a jump to the area you care about; the panel merges what each run finds into a list
# that keeps growing, exactly as it does for the tiles.
#
# Two sources, in this order, and a tile named by both is kept once:
#
#   * `invasion` — the zombie-invasion event's own two lists
#     (`ActivityMonsterInvasionDataManager.monsterInvasionData.selfMonsters` /
#     `aliMonsters`). These carry a config id, so the kind and the level are the game's
#     own answer. The lists are empty between waves, which is not a failure.
#   * `scene`    — the roaming monsters the client currently has DRAWN
#     (`WorldMonster…(Clone)` game objects, found through their own
#     `TouchObjectEventTrigger`, the same handle the no-click attack uses). Their tile
#     comes from the object's world position; their level from the «ур. N» label hanging
#     over them, when there is one.
#
# The answer lands in ONE variable, `monsters`, as records separated by « | »:
#
#     src=scene pid=535614 x=614 y=535 uuid=0 cfg=0 type=0 level=19 kind=WorldMonster01
#
#   * `src`   — which of the two sources above found it.
#   * `pid`   — the tile index; `x`/`y` are that index split, the coordinates on screen.
#   * `uuid`  — the monster's server uuid where one is known (the invasion list has it,
#               a drawn clone does not until it is selected), else 0.
#   * `cfg`   — its config id, else 0.
#   * `type`  — `lw_world_monster.type`: **7** is the zombie line (Invading Zombies /
#               Zombie Boss) and **8** is the Doom line («Роковая Элита»). 0 means
#               nobody could say — the same split `join_rally.md` sorts its banners by.
#   * `level` — the monster's level, and **`-1` when nobody could say**, which is not
#               the same as level zero and must not be drawn as one.
#   * `kind`  — the drawn object's own name with `(Clone)` taken off. It is the only
#               thing a roaming monster says about itself before it is selected, and it
#               is also the KEY: see below.
#
# ## The prefab name is the identity, and the config is the answer (#1519)
#
# A drawn monster used to come back as `type=0 level=0` — every one of them, for as long
# as this recipe has existed — because a clone carries no config id and the level label
# hanging over it is not always there to be read. Zero is the worst possible answer: it
# is a NUMBER, so the column showed it, and a person reading «уровень 0» over a level-10
# zombie is being lied to rather than left in the dark.
#
# The name is enough. `WorldMonster_General_invasion(Clone)` is the prefab the client
# built the monster from, and that string is a COLUMN of `lw_world_monster` —
# `pic_name`, which for config id 1030000 reads `world_monster_general_invasion`: the
# same thing bar the case and the underscores. So the name is normalised and looked up,
# and the level, the type and (where the prefab belongs to exactly one row) the config id
# come back as the game's own numbers.
#
# **Only where the rows AGREE.** A prefab can stand for a whole family: live,
# `world_monster_general_invasion` is three rows and every one of them is level 10, while
# `world_monster_boss_invasion` is thirty rows spanning levels 5 to 75. The first
# answers; the second answers `nil` and the reading falls back to the label over the
# monster, and to `-1` when there is no label either. A level guessed for something that
# could be 5 or 75 would be the same lie in a new place.
#
# The map is built once per session and parked in the game VM
# (`monster_prefab_lookup` in tools/lib/lua_actions.py); the census of every prefab and
# the levels behind it is docs/research/golden-zombies.md.
#
# A field the game will not answer is left at its «unknown» value rather than guessed:
# every read is wrapped, so a manager that is not loaded yet costs one zero and not the
# whole line.
#
# NOT YET CONFIRMED AGAINST A LIVE CLIENT (#1289). The two sources, the field names and
# the type/level lookup are each taken from work that was proven live — the invasion lists
# from the rally budget's own classifier, the clone handle from world-monsters.md
# Finding 10, `lw_world_monster` from #1281 — but this particular chunk has not been run
# beside a map with monsters on it. What it says about the `scene` source in particular
# (which label belongs to which clone) is the part to check first.

# The whole answer is one line in one variable — no LOG line after it, because the panel
# polls this and the interpreter already traces what it read.
READ_LUA (function() local function _norm(s) return (string.gsub(string.lower(tostring(s or '')), '[^%w]', '')) end local function _monmap() local c = _G.__LW_MON_PREFAB if c ~= nil and c.v == 4 then return c.map end local m = {} local walked, why = 0, '' local okwalk, err = pcall(function() local inst = LocalController.instance() local data = inst:getTable('lw_world_monster').data local md = inst:getLine('lw_world_monster', 1030000):getMetaData() local function _col(n) local c = md[n] if type(c) == 'table' then c = c[1] end return tonumber(c) end local cpic, clv, cty, csp = _col('pic_name'), _col('level'), _col('type'), _col('special') if cpic == nil or data == nil then return end for id, row in pairs(data) do local ld = row if type(row) == 'table' and row._lineData ~= nil then ld = row._lineData end if type(ld) == 'table' then local pic = ld[cpic] if pic ~= nil and tostring(pic) ~= '' then local key = _norm(pic) local e = m[key] local lv, ty, sp = tonumber(ld[clv]), tonumber(ld[cty]), tonumber(ld[csp]) if e == nil then m[key] = {ids = {id}, n = 1, level = lv, type = ty, special = sp} else e.n = e.n + 1 if #e.ids < 32 then e.ids[#e.ids + 1] = id end if e.level ~= lv then e.level = nil end if e.type ~= ty then e.type = nil end if e.special ~= sp then e.special = nil end end end walked = walked + 1 end end end) if not okwalk then why = tostring(err) end _G.__LW_MON_DIAG = {walked = walked, why = why} pcall(function() local inst = LocalController.instance() local function v(f) return tonumber(inst:getValue('lw_world_monster', 1030000, f, nil)) end local pic = inst:getValue('lw_world_monster', 1030000, 'pic_name', nil) if pic ~= nil and tostring(pic) ~= '' then local key = _norm(pic) if m[key] == nil then m[key] = {ids = {1030000}, n = 1, level = v('level'), type = v('type'), special = v('special')} end end end) _G.__LW_MON_PREFAB = {v = 4, map = m} return m end local out={} local LCI=nil pcall(function() LCI=LocalController.instance() end) local map=_monmap() local function mon(cid) if LCI==nil or cid==nil then return nil,nil end local ty,lv pcall(function() ty=LCI:getValue('lw_world_monster',cid,'type',nil) end) pcall(function() lv=LCI:getValue('lw_world_monster',cid,'level',nil) end) if ty~=nil and tostring(ty)=='' then ty=nil end if lv~=nil and tostring(lv)=='' then lv=nil end return tonumber(ty),tonumber(lv) end local function tile(pid) local x,y=-1,-1 pcall(function() local tp=SceneUtils.IndexToTilePos(pid) x,y=tp.x,tp.y end) return x,y end local seen={} local function add(src,pid,uuid,cid,lvl,kind,ty0) if pid==nil then return end local key=tostring(pid) if seen[key] then return end seen[key]=true local x,y=tile(pid) local ty,lv=mon(cid) if lv==nil then lv=lvl end if ty==nil then ty=ty0 end out[#out+1]="src="..src.." pid="..tostring(pid).." x="..tostring(x).." y="..tostring(y).." uuid="..tostring(uuid or 0).." cfg="..tostring(cid or 0).." type="..tostring(ty or 0).." level="..tostring(lv or -1).." kind="..tostring(kind or "-") end pcall(function() local im=DataCenter.ActivityMonsterInvasionDataManager local d=im and im.monsterInvasionData if d==nil then return end for _,nm in ipairs({'selfMonsters','aliMonsters'}) do local lst=nil pcall(function() lst=d[nm] end) if type(lst)=='table' then for k,m in pairs(lst) do local pid,uuid,cid=nil,nil,nil pcall(function() pid=m.pointId or m.point end) pcall(function() uuid=m.uuid end) pcall(function() cid=m.cfgId or m.monsterId or m.contentId end) if pid==nil and tonumber(k)~=nil then pid=tonumber(k) end add('invasion',pid,uuid,cid,nil,'invasion',nil) end end end end) local mons,labels={},{} pcall(function() local arr=CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i=0,arr.Length-1 do local mb=arr[i] local cn=nil pcall(function() cn=mb:GetType().Name end) if cn=='TouchObjectEventTrigger' or cn=='UIWorldLabel' then local p=nil pcall(function() p=mb.gameObject end) local root,guard=nil,0 while p~=nil and guard<8 do local pn=nil pcall(function() pn=p.name end) if pn~=nil and string.find(pn,'WorldMonster') then root=p break end local nxt=nil pcall(function() if p.transform.parent~=nil then nxt=p.transform.parent.gameObject end end) p=nxt guard=guard+1 end if root~=nil then local key=nil pcall(function() key=tostring(root:GetInstanceID()) end) if key~=nil then if cn=='UIWorldLabel' then local txt=nil pcall(function() txt=mb.text end) if txt==nil then pcall(function() txt=mb.Text end) end if txt~=nil then labels[key]=tostring(txt) end else mons[key]=root end end end end end end) for key,root in pairs(mons) do local pid=nil pcall(function() pid=SceneUtils.WorldToTileIndex(root.transform.position) end) local kind='-' pcall(function() kind=tostring(root.name):gsub('%(Clone%)',''):gsub('%s+','_') end) local e=map[_norm(kind)] local cid=nil if e~=nil and e.n==1 then cid=e.ids[1] end local lvl=e and e.level or nil if lvl==nil then local t=labels[key] if t~=nil then lvl=tonumber(string.match(t,'%d+')) end end add('scene',pid,0,cid,lvl,kind,e and e.type or nil) end return table.concat(out,' | ') end)() INTO monsters
