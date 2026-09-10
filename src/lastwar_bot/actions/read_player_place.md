# Read where the player is in the client: the scene, the open window, the warzone.
# ru: Прочитать, где игрок в клиенте: сцена, открытое окно, варзона.
#
# A READ, and nothing else: it presses nothing, opens nothing and sends nothing to the
# server. One VM round trip, from any scene and with no window open.
#
# WHAT «WHERE» MEANS HERE (#2016, docs/research/player-place.md). Three separate things
# the client already knows, and none of them is guessed at:
#
#   * THE SCENE — `SceneUtils.GetIsInWorld()` / `GetIsInCity()` / `GetIsInPve()`. The
#     city is only reported when the main HUD (`UIMain`) is up as well, which is the same
#     rule the DSL's own `scene` condition keeps (`script_engine._scene_reading`): a
#     client still building the base reads `unknown` rather than «дома».
#   * THE OPEN WINDOW — `UIManager.Instance:GetStackTopWindow().Name`, the game's own id
#     of the screen on top, and `windowStack.length` for how many are stacked under it.
#     Empty when the player is looking at the scene itself: the stack really is empty
#     then (measured live — `length=0` on a world map with nothing open), and `UIMain`
#     never enters it because the HUD is a LAYER rather than a window.
#   * THE WARZONE — the one the camera is looking at
#     (`WorldFavoDataManager.curServerId`, the same field every coordinate jump reads)
#     and the account's own (`LuaEntry.Player.serverId`). They differ exactly when the
#     client is standing in somebody else's warzone, which is the one case where «текущий
#     сервер» has two honest answers.
#
# WHY NOT THE LIST OF OPEN WINDOWS. `IsWindowOpen` over the whole of `UIWindowNames` is
# 2231 calls and costs 1.0 ms inside the VM — measured, and cheap enough — but it answers
# in the table's own order, which is not the order they were opened in. A list that could
# not say which of two windows is in front would be the panel guessing, so the stack is
# asked instead: it IS the order, and its top is the screen the person is looking at.
#
# THE ANSWER lands in one variable, `player_place`, as five fields separated by « ;; »:
#
#     world;;UILWAlMain;;1;;935;;935
#
#   * scene       — `city`, `world`, `pve` or `unknown`.
#   * window      — the game's id of the window on top; empty when none is open.
#   * depth       — how many windows are stacked, 0 when none.
#   * server      — the warzone the camera is looking at.
#   * home        — the warzone this account belongs to.
#
# A CLIENT THAT HAS NOT LOGGED IN IS REFUSED BEFORE ANYTHING IS READ, exactly as the
# character card and the resource balance are: a client at the login screen answers every
# question cheerfully and wrongly (`tools/lib/game_clock.py`), and «в городе, сервер 0»
# is worse than no line at all. The check is the same round trip, so it is free.

READ_LUA (function() local nowms=0 pcall(function() nowms=UITimeManager.Instance:GetServerTime() end) nowms=math.floor((tonumber(tostring(nowms)) or 0)+0) if nowms < 1600000000000 then return '' end local mgr=nil pcall(function() mgr=UIManager.Instance end) if mgr==nil then return '' end local inw=false local inc=false local pve=false pcall(function() inw=SceneUtils.GetIsInWorld() and true or false end) pcall(function() inc=SceneUtils.GetIsInCity() and true or false end) pcall(function() pve=SceneUtils.GetIsInPve() and true or false end) local main=false pcall(function() main=mgr:IsWindowOpen('UIMain') and true or false end) local scene='unknown' if pve then scene='pve' elseif inw then scene='world' elseif inc and main then scene='city' end local top='' pcall(function() local w=mgr:GetStackTopWindow() if w~=nil then top=tostring(w.Name or ''):gsub('%s+','') end end) local depth=0 pcall(function() depth=math.floor((tonumber(tostring(mgr.windowStack.length)) or 0)+0) end) local home=0 pcall(function() home=math.floor((tonumber(tostring(LuaEntry.Player.serverId)) or 0)+0) end) local server=0 pcall(function() server=math.floor((tonumber(tostring((function() local WS=DataCenter.__lw_ws local __ok, __cur = pcall(function() return WS and WS.CurTilePos end) if not __ok or __cur == nil then local arr=CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i=0,arr.Length-1 do if arr[i] and arr[i]:GetType().Name=="WorldScene" then WS=arr[i] break end end DataCenter.__lw_ws=WS end local pm=nil pcall(function() pm=WS.PointManager end) local size=0 pcall(function() size=math.floor(WS.TileCount.x) end) local cx,cy=-1,-1 pcall(function() cx,cy=math.floor(WS.CurTilePos.x),math.floor(WS.CurTilePos.y) end) if pm~=nil and size>0 and cx>=0 and cy>=0 then local hist,seen={},0 for ty=cy-30,cy+30,3 do for tx=cx-30,cx+30,3 do if tx>=0 and ty>=0 and tx<size and ty<size then local ok,info=pcall(function() return pm:GetPointInfo(ty*size+1+tx) end) if ok and info~=nil then local s=0 pcall(function() s=math.floor((tonumber(tostring(info.serverId)) or 0)+0) end) if s>0 then hist[s]=(hist[s] or 0)+1 seen=seen+1 end end end end if seen>=12 then break end end local best,bn=0,0 for s,c in pairs(hist) do if c>bn then best,bn=s,c end end if best>0 then return best end end return (tonumber(tostring((DataCenter.WorldFavoDataManager and DataCenter.WorldFavoDataManager.curServerId) or (DataCenter.WarFlagDataManager and DataCenter.WarFlagDataManager.curServerId) or 0)) or 0) end)())) or 0)+0) end) if server<=0 then server=home end return scene..';;'..top..';;'..depth..';;'..server..';;'..home end)() INTO player_place
LOG "player place: {player_place}"
