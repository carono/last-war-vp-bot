# Measure how fast this computer takes the map, and say which sweep speed it can hold.
# ru: Замерить, как быстро этот компьютер принимает карту, и назвать деление скорости.
#
# WHY IT EXISTS (#2705). The sweep's pace is a scale of twenty and the person asked for a
# way to find their own number rather than guess it: «добавь бенчмарк для обхода,
# автоопределение скорости, пусть экран перейдет на какую то область с монстрами, засекает
# и записывает данные, когда с провода перестанут приходить данные с карты, фиксируем и
# указываем оптимальную скорость обхода». The right pace is not a taste — it is how long
# THIS machine needs to take one view's worth of answers, and the only honest way to learn
# that is to time it.
#
# WHAT IT DOES, and it is nothing but camera moves:
#
#   1. goes AWAY from the target first, so the area is genuinely unloaded — measuring a
#      view the client already holds measures nothing at all;
#   2. jumps to the target and starts the clock;
#   3. samples what the client HOLDS around it, ten times a second, until the number
#      stops climbing. That is the stream of map answers arriving and then stopping,
#      counted rather than waited out on a timer.
#
# NOTHING IS SPENT, NOTHING IS PRESSED and no window opens. It names no warzone either
# (`scan_map.md`, #2705): the measurement is of the warzone the person is standing in.
#
# WHERE IT MEASURES. `x`/`y` name the tile, and the caller is expected to pass one it
# knows has something on it — the panel passes a monster off its own register, which is
# what «область с монстрами» means in practice. A tile nobody named falls back to the
# MIDDLE of the map, and the answer says which of the two it was, because a measurement
# over empty ground is a fast machine and a lie.
#
# WHAT IT LEAVES BEHIND
#   bench_ms       milliseconds from the jump to the LAST tile that arrived
#   bench_tiles    how many tiles the client ended up holding around the target
#   bench_samples  how many readings the window managed
#   bench_where    `x,y from` — the tile, and whether it was named or fallen back to

ARGS x = 0
ARGS y = 0
ARGS zoom = 600

# How long the window watches, and how often. Ten a second for six seconds: a lap
# waypoint that needs longer than that is not a pace anybody would set.
ARGS samples = 60
ARGS every = 0.1

IF scene != world
    LOG "Putting the map up first — a measurement from the base measures nothing."
    GAME WORLD
    WAIT scene == world WITHIN 30s

READ_LUA (function() local WS=DataCenter.__lw_ws local ok,cur=pcall(function() return WS and WS.CurTilePos end) if not ok or cur==nil then local arr=CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) for i=0,arr.Length-1 do if arr[i] and arr[i]:GetType().Name=="WorldScene" then WS=arr[i] break end end DataCenter.__lw_ws=WS end local size=1000 pcall(function() size=WS.TileCount.x end) local tx,ty={x}+0,{y}+0 local from="named" if tx<1 or ty<1 or tx>=size or ty>=size then tx=math.floor(size/2) ty=math.floor(size/2) from="centre" end local B={rows={},t0=0,tx=tx,ty=ty,from=from,before=0} DataCenter.__lw_mapbench=B local V3,tm=CS.UnityEngine.Vector3,TimerManager:GetInstance() local function count() local n=0 for x=tx-90,tx+90,3 do if x>=0 and x<size then for y=ty-90,ty+90,3 do if y>=0 and y<size then local pid=SceneUtils.TilePosToIndex(CS.UnityEngine.Vector2Int(x,y)) if WS.PointManager:HasPointInfo(pid) then n=n+1 end end end end end return n end local ax=(tx>size/2) and 60 or (size-60) local ay=(ty>size/2) and 60 or (size-60) pcall(function() GoToUtil.GotoWorldPos(V3(ax*2+1,0,ay*2+1),{zoom},0,nil,nil) end) tm:DelayInvoke(function() B.before=count() pcall(function() GoToUtil.GotoWorldPos(V3(tx*2+1,0,ty*2+1),{zoom},0,nil,nil) end) B.t0=CS.UnityEngine.Time.realtimeSinceStartup end,1.5) for k=1,{samples} do tm:DelayInvoke(function() if B.t0==0 then return end local ok2,n=pcall(count) B.rows[#B.rows+1]={math.floor((CS.UnityEngine.Time.realtimeSinceStartup-B.t0)*1000),(ok2 and n or -1)} end,1.5+k*{every}) end return tostring(tx)..","..tostring(ty).." "..from end)() INTO bench_target
LOG "map_bench — measuring at {bench_target}, watching for {samples} readings"

WAIT 9

READ_LUA (function() local B=DataCenter.__lw_mapbench or {} local rows=B.rows or {} if #rows==0 then return 0,0,0,"nothing" end local prev=B.before or 0 local last=0 local best=prev for i=1,#rows do local ms,n=rows[i][1],rows[i][2] if n>prev then last=ms prev=n end if n>best then best=n end end return last,best-(B.before or 0),#rows,(tostring(B.tx)..","..tostring(B.ty).." "..tostring(B.from)) end)() INTO bench_ms, bench_tiles, bench_samples, bench_where
LOG "map_bench_done — {bench_tiles} tile(s) at {bench_where}, the stream stopped {bench_ms} ms after the jump ({bench_samples} readings)"
