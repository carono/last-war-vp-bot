# Read what the CLIENT is looking at right now: the camera, and the tiles around it.
# ru: Прочитать, на что клиент смотрит сейчас: камера и клетки вокруг неё.
#
# A READ, and nothing else: it presses nothing, opens nothing, moves no camera and sends
# nothing to the server. One VM round trip, and every value is already in the client's
# memory (#2018, docs/research/live-screen-view.md).
#
# WHAT «WHAT THE CLIENT SEES» IS. The world scene keeps a bounded window of tiles around
# the camera — measured live, a 41×41 box and an 81×81 box return the SAME 366 points, so
# the client simply does not hold more than that. This reads:
#
#   * `WorldScene.CurTilePos` — the camera's own tile. The coordinate #2016 looked for and
#     did not find on `WorldFavoDataManager.curPos`, which is nil.
#   * `WorldScene.Zoom` and `GetLodLevel()` — how high the camera is, and which detail
#     band that height falls in (docs/research/map-sweep-zoom.md).
#   * `WorldScene.PointManager` — every tile the client is holding in a box around the
#     camera, with `PointType` as the wire's own `f2`: 6 base, 7 mine, 11 stronghold,
#     17 ★ task, 25 alliance city, 29 ghost recon.
#   * `GetMonsterListInArea` — the monsters the client is holding there, as kind `m`.
#   * `WorldMarchDataManager:GetOwnerMarches()` — this account's own marches, as kind `w`.
#
# THE SCENE IS FOUND ONCE AND CACHED in `DataCenter.__lw_screen_ws`, the way every recipe
# here caches it: the scan costs 4–10 ms and the cached read costs nothing. A cache whose
# `CurTilePos` no longer answers is thrown away and scanned again — a `WorldScene` is
# replaced whenever the world is entered afresh.
#
# WHAT IT COSTS, measured live: 14–15 ms inside the VM for all of it, against 0.6–1.2 s
# for the round trip that carries it. The work is free; the trip is the whole price, which
# is why nothing in the panel may play this on a clock of its own
# (`CLAUDE.md`, «Читаем один раз, дальше слушаем»).
#
# THE ANSWER lands in `screen_view` as fields separated by « ;; »:
#
#     world;;935;;718;;390;;105.0;;1;;20;;6:718:390,7:700:381,m:702:377;;w:711:388
#
#   * scene   — `city`, `world`, `pve` or `unknown`. Only `world` carries a picture.
#   * server  — the warzone the camera is in.
#   * x, y    — the camera's tile.
#   * zoom    — the camera's height; `lod` is the band it falls in.
#   * radius  — the half-width of the box that was read, in tiles.
#   * objects — `type:x:y`, comma separated. `m` is a monster, the digits are `PointType`.
#   * marches — `w:x:y` for this account's own marches, comma separated.
#
# A CLIENT THAT HAS NOT LOGGED IN IS REFUSED BEFORE ANYTHING IS READ, the same gate every
# other reading here keeps: a client at the login screen answers cheerfully and wrongly
# (`tools/lib/game_clock.py`), and a picture drawn from that is worse than no picture.
#
# A CLIENT THAT IS NOT IN THE WORLD answers its scene and nothing else — `city;;…` with an
# empty object list. That is «there is no world view to draw», which the page says in
# words; it is not a failed read and must not be drawn as an empty map.

ARGS radius = 20
ARGS cap = 900

READ_LUA (function() local nowms=0 pcall(function() nowms=UITimeManager.Instance:GetServerTime() end) nowms=math.floor((tonumber(tostring(nowms)) or 0)+0) if nowms < 1600000000000 then return '' end local scene='unknown' local inw,inc,pve=false,false,false pcall(function() inw=SceneUtils.GetIsInWorld() and true or false end) pcall(function() inc=SceneUtils.GetIsInCity() and true or false end) pcall(function() pve=SceneUtils.GetIsInPve() and true or false end) local main=false pcall(function() main=UIManager.Instance:IsWindowOpen('UIMain') and true or false end) if pve then scene='pve' elseif inw then scene='world' elseif inc and main then scene='city' end local server=0 pcall(function() server=math.floor((tonumber(tostring((DataCenter.WorldFavoDataManager and DataCenter.WorldFavoDataManager.curServerId) or 0)) or 0)+0) end) if server<=0 then pcall(function() server=math.floor((tonumber(tostring(LuaEntry.Player.serverId)) or 0)+0) end) end if scene~='world' then return scene..';;'..server..';;;;;;;;;;;;;;' end local ws=DataCenter.__lw_screen_ws local alive=false pcall(function() alive=(ws~=nil) and (ws.CurTilePos~=nil) end) if not alive then ws=nil pcall(function() local arr=CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i=0,arr.Length-1 do local mb=arr[i] local n=nil pcall(function() n=mb:GetType().Name end) if n=='WorldScene' then ws=mb break end end end) DataCenter.__lw_screen_ws=ws end if ws==nil then return scene..';;'..server..';;;;;;;;;;;;;;' end local cx,cy,zoom,lod=nil,nil,0,0 pcall(function() cx,cy=math.floor(ws.CurTilePos.x+0),math.floor(ws.CurTilePos.y+0) end) pcall(function() zoom=tonumber(tostring(ws.Zoom)) or 0 end) pcall(function() lod=math.floor((tonumber(tostring(ws:GetLodLevel())) or 0)+0) end) if cx==nil then return scene..';;'..server..';;;;;;;;;;;;;;' end local r=math.floor((tonumber(tostring('{radius}')) or 20)+0) if r<1 then r=1 end if r>60 then r=60 end local cap=math.floor((tonumber(tostring('{cap}')) or 900)+0) local pm=nil pcall(function() pm=ws.PointManager end) local seen,n={},0 pcall(function() for x=cx-r,cx+r do for y=cy-r,cy+r do if n>=cap then break end local pid=SceneUtils.TilePosToIndex(CS.UnityEngine.Vector2Int(x,y)) if pm:HasPointInfo(pid) then local k=math.floor((tonumber(tostring(pm:GetPointInfo(pid).PointType)) or 0)+0) n=n+1 seen[n]=k..':'..x..':'..y end end end end) pcall(function() local res=CS.System.Collections.Generic.Dictionary(CS.System.Int64,CS.UnityEngine.Vector2Int)() ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(cx,cy),r*2,nil,res) local e=res:GetEnumerator() while e:MoveNext() do if n>=cap then break end local p=e.Current.Value n=n+1 seen[n]='m:'..math.floor(p.x+0)..':'..math.floor(p.y+0) end end) local marches={} pcall(function() local mm=DataCenter.WorldMarchDataManager:GetOwnerMarches() if mm~=nil then for i=0,(mm.Count-1) do local m=nil pcall(function() m=mm[i] end) if m~=nil then local mx,my=nil,nil pcall(function() mx,my=math.floor(m.curPos.x+0),math.floor(m.curPos.y+0) end) if mx==nil then pcall(function() mx,my=math.floor(m.targetPos.x+0),math.floor(m.targetPos.y+0) end) end if mx~=nil then marches[#marches+1]='w:'..mx..':'..my end end end end end) return scene..';;'..server..';;'..cx..';;'..cy..';;'..string.format('%.1f',zoom)..';;'..lod..';;'..r..';;'..table.concat(seen,',')..';;'..table.concat(marches,',') end)() INTO screen_view
LOG "screen view: {screen_view}"
