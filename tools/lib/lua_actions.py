r"""Single source of truth for the confirmed navigation Lua chunks.

Both the panel (via the warm daemon) and the standalone scripts build their in-game Lua
from here, so the recipes never drift. Each function returns a Lua string; run it through
any evaluator with a `.run(chunk, marker, settle)` method (LuaEval or the daemon client).

All recipes are the ones verified live this session — see docs/research/world-tiles.md and
docs/skills/sniff-capture.md §7.
"""
from __future__ import annotations

import os

from rally_kinds import KIND_OF_NAME

# Home/world server id fallback, from env LW_DEFAULT_SERVER (0 = unknown; the live
# curServerId is preferred at call time, this is only used when it is missing).
HOME_SERVER = int(os.environ.get("LW_DEFAULT_SERVER") or 0)


def _kind_table() -> str:
    """The species table as a Lua literal — `name key -> kind` (#1317).

    Built once from `rally_kinds.KIND_OF_NAME`, which was read out of the live config
    rather than written by hand, so a season that adds a boss is a data change here and
    a locale line in the panel, never a new branch in this chunk.
    """
    body = ",".join("['%s']='%s'" % (key, kind)
                    for key, kind in sorted(KIND_OF_NAME.items()))
    return "local KIND_OF_NAME = {%s} " % body


def scene_world() -> str:
    """City -> World (renders the world scene)."""
    return 'pcall(function() SceneUtils.ChangeToWorld() end) CS.UnityEngine.Debug.LogError("ACT scene=world")'


def scene_city() -> str:
    """World -> City (home base)."""
    return 'pcall(function() SceneUtils.ChangeToCity() end) CS.UnityEngine.Debug.LogError("ACT scene=city")'


def current_server_expr() -> str:
    """Lua EXPRESSION for the server the client is looking at (HOME_SERVER if it will not say).

    An expression rather than only a chunk, because the answer is worth more inside
    another chunk than as a round trip of its own: reading it first and then acting on
    it cost a whole extra call to the VM — measured at 570-1300 ms in front of every
    coordinate jump, which was the second the panel felt slower than the game (#1230).
    """
    # `tonumber(tostring(…))` because the id is read off a C# field and is passed on to
    # a call that wants a number: it was a Python `int()` of the logged text before this
    # was ever a Lua expression, and the coercion has to survive the move.
    return ('(tonumber(tostring('
            '(DataCenter.WorldFavoDataManager and DataCenter.WorldFavoDataManager.curServerId) or '
            '(DataCenter.WarFlagDataManager and DataCenter.WarFlagDataManager.curServerId) or %d)) or %d)'
            % (HOME_SERVER, HOME_SERVER))


def current_server() -> str:
    """Log `ACT curserver=<id>` — the viewed world server (falls back to HOME_SERVER)."""
    return ('CS.UnityEngine.Debug.LogError("ACT curserver="..tostring(%s))'
            % current_server_expr())


#: The camera height the in-game coordinate jump uses — the client's own `InitZoom`.
#: Every jump that is about ONE tile keeps it: it is the height at which a person can
#: read the tile they landed on.
JUMP_ZOOM = 105

#: The highest camera height at which the server still sends SECRET-TASK tiles, and the
#: number a map sweep wants (task #1265, docs/research/map-sweep-zoom.md). Tile loading
#: is gated on the client's LOD, whose ladder is 150 / 250 / 400 / 600 / 1200 / … — so
#: 600 is the top of LOD 4, and 601 is LOD 5, where `f2=17` tiles stop arriving
#: altogether while bases, mines and strongholds keep coming. Measured live: one jump
#: at 105 loaded 9 secret tasks, the same jump at 600 loaded 112.
SWEEP_ZOOM_MAX = 600

#: The highest camera height at which the map still arrives AT ALL — the top of LOD 5.
#: Secret-task and ghost-recon tiles are already gone here (that is what
#: `SWEEP_ZOOM_MAX` is for), but bases, mines, alliance cities and strongholds still
#: come, and they come over four times the ground per jump. One step higher — 1200, LOD
#: 6 — and `world.get.block` answers with no tiles at all: the client has switched to the
#: coarse big-map layer, which is a different message. So this is literally the last
#: height at which player bases can be collected (#1265).
#:
#: 1199 and not 1200 on purpose. The client stores the height as a float and hands back
#: a hair MORE than it was given (1200 reads as 1200.0001), and the LOD ladder compares
#: on `>=` — so asking for exactly 1200 lands in LOD 6 and fetches nothing.
BASE_ZOOM_MAX = 1199

#: How far apart two waypoints of a FAST lap are. One jump at `SWEEP_ZOOM_MAX` loads
#: ±48 tiles in its shortest direction, so 90 overlaps by a few tiles at every seam and
#: a 1000-tile server is an 11 × 11 grid.
FAST_STEP = 90

#: The three heights the panel offers, `id -> (camera height, sweep step)`, named by what
#: each is FOR rather than by its number: a person choosing between them is choosing what
#: they want to see, not a camera setting.
#:
#: The step of each is what a live lap measured, not what the geometry suggested. At
#: `tasks` a lap of step 90 finds every secret task a lap of step 45 finds (604 against
#: 603 — the difference is tiles expiring mid-run), so 90 is complete for what that level
#: is FOR. At `bases`, where the tiles are far denser, the count does keep climbing:
#: 4 502 bases at step 150, **4 818 at 100**, 4 945 at 70 — so 100 is where the curve
#: flattens against the clock (~5 s a lap against 13). A step belongs to its height and
#: is meaningless without it.
ZOOM_LEVELS: dict = {
    "tile": (JUMP_ZOOM, 24),
    "tasks": (SWEEP_ZOOM_MAX, FAST_STEP),
    "bases": (BASE_ZOOM_MAX, 100),
}

#: What a jump with no height asked for uses — the game's own, so that a coordinate
#: clicked in the log still lands where a person can read the tile.
DEFAULT_ZOOM_LEVEL = "tile"


#: The heights a LAP is worth walking at (#1272). «Тайл» is not among them and must not
#: come back: a lap at 105 needs a 24-tile step, which is 88 SECONDS of camera against 6
#: at 600 — and it finds nothing the 600 lap does not, because 600 is the ceiling at
#: which the client still asks for secret tasks at all (docs/research/map-sweep-zoom.md).
#:
#: It used to be offered because one control drove both the lap and every JUMP, so
#: anybody who wanted to land on a readable tile picked «тайл» and thereby signed up for
#: an 88-second sweep. Jumps do not take a height any more — they are always the tile
#: view, decided in one place (`GameLink.jump`) — so this control is about the lap and
#: nothing else.
SWEEP_LEVELS = ("tasks", "bases")


def zoom_level(name: "str | None") -> tuple:
    """``(height, step)`` of a named level, falling back to the tile view.

    An unknown name is answered rather than raised on: the name comes out of a saved
    profile, and a panel that will not draw because a settings file has an old word in
    it is worse than one that opens at the close view.
    """
    return ZOOM_LEVELS.get(name or "", ZOOM_LEVELS[DEFAULT_ZOOM_LEVEL])

#: Seconds between two waypoints of a fast lap. The client fires one `world.get.block`
#: per view change with no debounce, so the floor is not the camera — it is the wire.
#: Measured: 0.05 delivered 100/100 responses, and asking for 0.01 still delivered
#: 121/121 while the traffic took 2.9 s to drain, so anything below ~0.02 buys nothing.
FAST_INTERVAL = 0.05


def jump_to_coord(x: int, y: int, server: "int | None" = None,
                  zoom: "int | None" = None) -> str:
    """Jump to tile (x, y) on `server` — the game's OWN coordinate navigation.

    Reproduces exactly what the in-game "go to coordinate on server" flow does (open the
    magnifier, pick a target, jump), captured live with `tools/lua_trace.py` while the
    player used it by hand (Player.log):

        GoToUtil.GotoWorldPos(worldPos, 105, nil, nil, serverId)

    `worldPos` is the tile's world position `Vector3(x*2+1, 0, y*2+1)` (world = tile*2, the
    camera lands on the tile). This ONE call covers both cases: a foreign `server` loads and
    enters that server's world (`IsInOtherServer` -> true), the home `server` returns to /
    centres on it (`IsInOtherServer` -> false). No `UIMoveCity` teleport window, no
    authorize-list dance, no forced mid-switch window-close — so map input stays alive
    afterwards. Verified live: srv 300 -> inOther, srv 100 -> home, UIMoveCity never opens.

    Replaces the removed `GotoPos` camera crutch and the `JumpToServerByServerId` move-city
    hack (which popped `UIMoveCity`, force-closed it mid-switch, and left map taps dead).

    ``server=None`` means "the one being looked at", and the chunk asks the game for it
    ITSELF (`current_server_expr`). A coordinate without a server is the ordinary case —
    a link clicked in the log, a row in «Командный пункт» — and the panel used to answer
    it with a separate read before the jump: one more trip through the Lua VM, one more
    settle, and the game only started moving after both (#1230).

    ``zoom`` is the second argument of that call — the camera's height, which decides how
    much map the client asks the server for. It defaults to the game's own `JUMP_ZOOM`,
    so a jump that is about one tile is unchanged. A sweep looking for tiles passes
    `SWEEP_ZOOM_MAX` instead and covers roughly twelve times the ground per jump.

    **Set it BEFORE the jump when it matters.** `GotoWorldPos` tweens position and zoom
    together, so a jump that also zooms out spends its last frames over the target at a
    lower height — and picks up tiles the height being asked for would never have loaded.
    A sweep is unaffected because every waypoint uses the same number, but a measurement
    that changes it per jump is measuring the tween (#1265).
    """
    sid = str(int(server)) if server is not None else current_server_expr()
    height = int(JUMP_ZOOM if zoom is None else zoom)
    return ('local srv=%s pcall(function() GoToUtil.GotoWorldPos('
            'CS.UnityEngine.Vector3(%d*2+1,0,%d*2+1),%d,nil,nil,srv) end) '
            'CS.UnityEngine.Debug.LogError("ACT jump=%d,%d srv="..tostring(srv))'
            % (sid, x, y, height, x, y))


#: Lua that finds the live `WorldScene` MonoBehaviour and caches it in `_G.WS`. The
#: scene is not a Lua global — it is a C# component on the `World` GameObject — and it
#: is replaced whenever the world is re-entered, so the cache is validated rather than
#: trusted.
#:
#: THE VALUE IS CHECKED, NOT MERELY THE ACCESS (#1296). A destroyed Unity object does not
#: throw when a member is read off it — it answers `nil` — so a guard that only asked
#: whether the read succeeded kept a dead scene for ever, and everything hanging off it
#: (`PointManager`, `TileCount`, `CurTilePos`) was `nil` with nothing saying why. Caught
#: live: a treasure lap reported 121 waypoints scheduled and 0 read, because `WS` was a
#: WorldScene from a session that had ended. Reading `CurTilePos` and requiring a VALUE
#: costs the same one access and re-finds the live one instead.
FIND_WORLD_SCENE = (
    'local WS=_G.WS local __ok, __cur = pcall(function() return WS and WS.CurTilePos end) '
    'if not __ok or __cur == nil then '
    'local arr=CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) '
    'for i=0,arr.Length-1 do if arr[i] and arr[i]:GetType().Name=="WorldScene" then '
    'WS=arr[i] break end end _G.WS=WS end ')


#: THE CONFIG ROW EVERY COLUMN NUMBER IS READ OFF. Any row of `lw_world_monster` would
#: do — the metadata is the table's, not the row's — and this is the one the repository
#: already names elsewhere, so there is one number to change if the table ever moves.
MONSTER_META_CFG = 1030000

#: THE WORLD'S OWN MONSTER REGISTER, asked instead of looked at (#1523).
#:
#: `WorldScene:GetMonsterListInArea(centre, size, cfgIdWhitelist, out)` answers
#: `uuid -> tile` for every monster the client HOLDS whose config id is on the whitelist.
#: Three things about it were measured live rather than assumed, and each changes what a
#: caller must do:
#:
#: * **`size` and `centre` are not a window.** Asked at the camera, at the middle of the
#:   map and with a radius of 5 000, the same client answered the same 28 — so one call is
#:   «tell me everything», and walking the map with the QUESTION buys nothing.
#: * **it is fed by LOADING, not by drawing.** 36 before a lap, **178 after a FAST one**
#:   (8 seconds, the ★ lap's own pace), and still 178 ten seconds later. The slow monster
#:   lap — 147 seconds of standing at every stop — added not one row to it. So the cheap
#:   lap this repository has always had is exactly the right one in front of this question.
#: * **a lap at 1199 EMPTIES it.** After a high lap the same call answered **0**: that
#:   height loads the coarse big-map layer and the client lets the fine one go. A caller
#:   walking several heights asks at the bottom of the walk, never at the top.
#:
#: **The whitelist is compulsory and an empty one answers nothing** (world-monsters.md,
#: Finding 6), so the ids come out of `lw_world_monster` — 12 115 rows, walked in 31 ms
#: through `getTable(...).data`, grouped by `pic_name` into 107 prefabs and parked in
#: `DataCenter.__lw_mon_groups`. Two passes: the prefab says whether anything of that kind is on
#: the map at all (107 asks), and then each of ITS config ids is asked on its own, so that
#: every monster carries the row it came from — which is the only way the LEVEL is exact,
#: because a prefab's rows differ by nothing else (iron 1…35, bread 1…35).
#:
#: Measured end to end on a live warzone after an 8-second lap: **178 monsters, all 178
#: with a level, in 36 ms** of asking over 108 second-pass calls. Four prefabs answered —
#: iron 35, bread 31, coin 40, and 72 golden zombies at level 10.
#:
#: WHAT IT IS NOT. It is not every monster on the map: the plain roaming squads the client
#: draws as `WorldMonster*` clones are NOT in it, and those are what
#: `scan_map_monsters.md` collects the slow way. What this has and a clone never does is
#: **the uuid**, which is the one thing a march cannot be sent without.
MONSTER_REGISTER = """
(function()
  local WS = nil
  pcall(function()
    local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour))
    for i = 0, arr.Length - 1 do
      local mb = arr[i]
      local n = nil
      pcall(function() n = mb:GetType().Name end)
      if n == "WorldScene" then WS = mb break end
    end
  end)
  if WS == nil then return "" end
  local inst = LocalController.instance()
  local groups = DataCenter.__lw_mon_groups
  if groups == nil or groups.v ~= 1 then
    local built = {}
    pcall(function()
      local data = inst:getTable("lw_world_monster").data
      local md = inst:getLine("lw_world_monster", __CFG__):getMetaData()
      local function col(n) local c = md[n] if type(c) == "table" then c = c[1] end return tonumber(c) end
      local cpic, clv, cty = col("pic_name"), col("level"), col("type")
      if cpic == nil or data == nil then return end
      for id, row in pairs(data) do
        local ld = row
        if type(row) == "table" and row._lineData ~= nil then ld = row._lineData end
        if type(ld) == "table" then
          local pic = ld[cpic]
          if pic ~= nil and tostring(pic) ~= "" then
            local key = tostring(pic)
            local g = built[key]
            if g == nil then g = {ids = {}, lv = {}, ty = {}} built[key] = g end
            g.ids[#g.ids + 1] = id
            g.lv[tostring(id)] = tonumber(ld[clv])
            g.ty[tostring(id)] = tonumber(ld[cty])
          end
        end
      end
    end)
    groups = {v = 1, map = built}
    DataCenter.__lw_mon_groups = groups
  end
  local V2 = CS.UnityEngine.Vector2Int
  local function ask(ids)
    local d = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)()
    for i = 1, #ids do pcall(function() d:Add(tonumber(ids[i]), 1) end) end
    local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)()
    pcall(function() WS:GetMonsterListInArea(V2(__CX__, __CY__), __SIZE__, d, res) end)
    return res
  end
  local out, seen = {}, {}
  for key, g in pairs(groups.map) do
    local coarse = ask(g.ids)
    local any = 0
    pcall(function() any = coarse.Count end)
    if any > 0 then
      for i = 1, #g.ids do
        local id = g.ids[i]
        local one = ask({id})
        local lv = g.lv[tostring(id)] or 0
        local ty = g.ty[tostring(id)] or 0
        pcall(function()
          local it = one:GetEnumerator()
          while it:MoveNext() do
            local cur = it.Current
            local uuid = tostring(cur.Key)
            if seen[uuid] == nil then
              seen[uuid] = true
              local pid = -1
              pcall(function() pid = WS:TilePosToIndex(cur.Value) end)
              out[#out + 1] = "src=world pid=" .. tostring(pid)
                .. " x=" .. tostring(cur.Value.x) .. " y=" .. tostring(cur.Value.y)
                .. " uuid=" .. uuid .. " cfg=" .. tostring(id)
                .. " type=" .. tostring(ty) .. " level=" .. tostring(lv)
                .. " kind=" .. tostring(key)
            end
          end
        end)
      end
    end
  end
  return table.concat(out, " | ")
end)()
"""


def monster_register(centre: tuple = (500, 500), size: int = 2000) -> str:
    """The chunk above with its numbers in — what `SCAN_MONSTERS` runs.

    `centre` and `size` are arguments for completeness and are measured to make no
    difference (see above); they are here so a caller who finds a build where they DO can
    say so without editing Lua.
    """
    return (MONSTER_REGISTER
            .replace("__CX__", str(int(centre[0])))
            .replace("__CY__", str(int(centre[1])))
            .replace("__SIZE__", str(int(size)))
            .replace("__CFG__", str(int(MONSTER_META_CFG))))


#: THE MONSTER SAMPLER a lap runs at every waypoint (#1523), installed once per lap.
#:
#: WHY IT HAS TO BE INSIDE THE GAME. A monster is not on the wire at all — placement is
#: computed client-side (docs/research/world-monsters.md) — so the only copy of the list
#: is what the client has DRAWN, and it draws only around wherever the camera is
#: standing. Read from Python that is one round trip per view, and a lap is 121 views;
#: scheduled beside the lap's own waypoints it is a Lua closure that runs between two
#: camera moves and costs nothing anybody can measure.
#:
#: WHERE THE MONSTERS HANG, measured live rather than guessed: every drawn one is a child
#: of `World/dynamicObj` whose name begins with `WorldMonster`. That node held 151
#: children on a live map and walking all of them took **1 ms**; the FindObjectsOfType
#: scan the tab's own reader uses costs 10–12 ms, which is why the sampler walks the node
#: and the reader does not.
#:
#: **THE NODE IS LOOKED UP FRESH EVERY TIME, and that is not a detail.** Caching the
#: transform in a global and reusing it is what made the first measurement of this
#: nonsense: the handle goes stale when the scene churns, every later sample walked a
#: destroyed object, and a lap that was really collecting thirty monsters reported two.
#:
#: What it keeps is keyed by TILE (`SceneUtils.WorldToTileIndex`), so one monster seen
#: from two overlapping views is one row, and the value is the drawn object's own name
#: and the level off its tag — all a roaming monster says about itself before it is
#: selected.
MONSTER_SAMPLER = """
local DC = DataCenter.ActDispatchTaskDataManager
if DC.__lw_mon == nil then DC.__lw_mon = {} DC.__lw_mon_n = 0 DC.__lw_mon_s = 0 end
DC.__lw_sample = function()
  local dyn = nil
  pcall(function()
    local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.GameObject))
    for i = 0, arr.Length - 1 do
      local g = arr[i]
      local nm = nil
      pcall(function() nm = g.name end)
      if nm ~= nil and tostring(nm) == "dynamicObj" then dyn = g.transform break end
    end
  end)
  if dyn == nil then return end
  DC.__lw_mon_s = (tonumber(DC.__lw_mon_s) or 0) + 1
  pcall(function()
    for i = 0, dyn.childCount - 1 do
      local c = dyn:GetChild(i)
      local nm = tostring(c.name)
      if nm:find("WorldMonster") then
        local pid = nil
        pcall(function() pid = SceneUtils.WorldToTileIndex(c.position) end)
        if pid ~= nil then
          local key = tostring(pid)
          if DC.__lw_mon[key] == nil then
            local lvl = 0
            -- THE LEVEL TAG, off a NAMED path inside this very object — not another
            -- scan of the scene, and not the `UIWorldLabel` the page's own reader looks
            -- for. Read live: the number a person sees over a monster is a
            -- `SuperTextMesh` under `ModelLabel/LevelLabel/LevelText`, with the icon's
            -- own copy at `Icon/IconLabel/LevelLabel` for the ones drawn as a pin.
            pcall(function()
              local lab = c:Find("ModelLabel/LevelLabel/LevelText")
              if lab == nil then lab = c:Find("Icon/IconLabel/LevelLabel") end
              if lab ~= nil then
                local txt = lab:GetComponent("SuperTextMesh")
                if txt == nil then txt = lab:GetComponent("UIWorldLabel") end
                if txt ~= nil then lvl = tonumber(string.match(tostring(txt.text), "%d+")) or 0 end
              end
            end)
            DC.__lw_mon[key] = (nm:gsub("%(Clone%)", "")) .. "|" .. tostring(lvl)
            DC.__lw_mon_n = (tonumber(DC.__lw_mon_n) or 0) + 1
          end
        end
      end
    end
  end)
end
"""


def fast_map_sweep(zoom: "int | None" = None, step: "int | None" = None,
                   interval: "float | None" = None,
                   server: "int | None" = None, harvest: bool = False) -> str:
    """One lap of the WHOLE server map, scheduled inside the game — the fast swipe.

    A lap driven from Python is a lap of round trips: ~150 ms each way, so 121 waypoints
    is twenty seconds of socket and almost no game. This hands the entire waypoint list
    to the game's own `TimerManager:DelayInvoke` in ONE call. The game then walks it at
    `interval`, the view rect moves every time, and — because the client does not
    debounce map requests — a `world.get.block` goes out for each. The answers land in
    the ordinary passive capture the panel already runs.

    **This is the thing that was thought impossible.** The note under task #1053 said a
    scripted camera move emits no map traffic and only a human drag gesture does, so the
    sweep had to be somebody's wrist. That was true of the REMOVED `GotoPos` crutch and
    is not true of `GotoWorldPos`, which is the game's own coordinate jump: measured
    live, 121 scheduled jumps produced 121 requests and 121 responses, with no gesture,
    no focus and no pixels (#1265). Nothing needs to be imitated.

    The grid is built from the scene's OWN `TileCount`, so it is a lap of whatever server
    is being looked at rather than of a number written down here. Waypoints run
    serpentine — the camera never travels the long way between two neighbours.

    `zoom` picks WHAT the lap collects, and there are only two heights worth passing:
    `SWEEP_ZOOM_MAX` (secret tasks, ghost recon and everything else) or `BASE_ZOOM_MAX`
    (four times the ground, bases and mines, no tasks). Above the second one the client
    fetches nothing at all.

    Measured live on a 1000 × 1000 server, one lap at `SWEEP_ZOOM_MAX`: **2.6 s**, 121
    requests, 20 742 tiles, 597 distinct secret tasks and 189 ghost-recon tiles. The same
    lap at `BASE_ZOOM_MAX` needs 49 waypoints and finds 4 762 bases in 2.6 s.

    `server` NAMES the server the waypoints are walked on (#1280). Left out, the lap asks
    the client — `current_server_expr()`, which reads `WorldFavoDataManager.curServerId`
    and falls back to `HOME_SERVER` (0 unless the machine sets it). That answer is a
    cached manager field rather than the camera: «перехожу на другой сервер, жму обход —
    возвращает на предыдущий», live. So a caller that knows where the person actually is
    — the panel's «Сервер» box, filled by «↻ сервер» and by every jump — says so, and
    the guess stays only for callers that have nothing to say.
    """
    height = int(SWEEP_ZOOM_MAX if zoom is None else zoom)
    stride = max(1, int(FAST_STEP if step is None else step))
    gap = max(0.0, float(FAST_INTERVAL if interval is None else interval))
    where = str(int(server)) if server else current_server_expr()
    # THE SAMPLER IS INSTALLED IN FRONT OF THE WAYPOINTS, never inside one (#1523): it is
    # one assignment and the closures below only call it, so a lap of 121 views defines
    # the function once. `harvest` is off by default because the ★ lap is timed in
    # fractions of a second and must stay exactly what it was.
    sampler = (MONSTER_SAMPLER + "\n") if harvest else ""
    sample_call = ("  tm:DelayInvoke(function()\n"
                   "    if DC.__lw_sweep_run ~= run then return end\n"
                   "    DC.__lw_sample()\n"
                   "  end, (n - 1) * %f + %f)\n" % (gap, gap * 0.85)) if harvest else ""
    return (FIND_WORLD_SCENE + sampler + '''
local DC = DataCenter.ActDispatchTaskDataManager
-- EVERY WAYPOINT IS SCHEDULED AT ONCE, so a lap cannot be called back — the game's own
-- timer owns them from here (#1272). What it CAN be is disowned: each closure checks the
-- run token it was scheduled under, and `fast_map_sweep_stop` bumps it. A stopped lap
-- therefore costs the timers that are still pending exactly one comparison each.
DC.__lw_sweep_run = (tonumber(DC.__lw_sweep_run) or 0) + 1
local run = DC.__lw_sweep_run
local srv=%s
local size = 1000
pcall(function() size = WS.TileCount.x end)
local step, half = %d, math.floor(%d / 2)
local axis = {}
local v = half
while v < size do axis[#axis+1] = v v = v + step end
local V3, tm = CS.UnityEngine.Vector3, TimerManager:GetInstance()
local n = 0
for row = 1, #axis do
  local y = axis[row]
  for col = 1, #axis do
    -- Serpentine: every other row is walked backwards, so consecutive waypoints are
    -- neighbours and the camera never crosses the map between two of them.
    local x = axis[(row %% 2 == 1) and col or (#axis - col + 1)]
    n = n + 1
    tm:DelayInvoke(function()
      if DC.__lw_sweep_run ~= run then return end
      pcall(function() GoToUtil.GotoWorldPos(V3(x*2+1, 0, y*2+1), %d, 0, nil, srv) end)
    end, (n - 1) * %f)
%s  end
end
CS.UnityEngine.Debug.LogError("ACT sweep n="..n.." zoom=%d step=%d span="
  ..string.format("%%.1f", (n - 1) * %f).." size="..tostring(size))
''' % (where, stride, stride, height, gap, sample_call, height, stride, gap))


#: The Lua one :func:`fast_map_visit` fills in — the waypoint walk with the grid taken
#: out. Kept out of the function so the Lua reads as Lua: the six `%`-slots are the
#: warzone, the point list, the height, the interval, and the height and interval again
#: for the line the chunk prints about itself.
VISIT_CHUNK = '''
local DC = DataCenter.ActDispatchTaskDataManager
-- THE SAME RUN TOKEN THE FULL LAP USES, so one «Stop» stops either of them and two of
-- them can never be walking over each other.
DC.__lw_sweep_run = (tonumber(DC.__lw_sweep_run) or 0) + 1
local run = DC.__lw_sweep_run
local srv = %s
local pts = {%s}
local V3, tm = CS.UnityEngine.Vector3, TimerManager:GetInstance()
for n = 1, #pts do
  local p = pts[n]
  tm:DelayInvoke(function()
    if DC.__lw_sweep_run ~= run then return end
    pcall(function() GoToUtil.GotoWorldPos(V3(p[1]*2+1, 0, p[2]*2+1), %d, 0, nil, srv) end)
  end, (n - 1) * %f)
end
CS.UnityEngine.Debug.LogError("ACT visit n="..#pts.." zoom=%d span="
  ..string.format("%%.1f", (#pts - 1) * %f).." srv="..tostring(srv))
'''


def fast_map_visit(points, zoom: "int | None" = None,
                   interval: "float | None" = None,
                   server: "int | None" = None) -> str:
    """Walk the camera over a NAMED list of tiles, so a capture re-hears exactly those.

    :func:`fast_map_sweep` with the grid taken out. The lap it schedules is a lap of a
    whole warzone — 121 waypoints, 2.6 s, twenty thousand tiles — and that is the right
    shape for FILLING a list. It is the wrong shape for CHECKING one: the rows of the
    star list that are ready to rob sit in a few dozen of those 121 squares, and walking
    the other eighty is time the operator spends waiting to be told whether a tile they
    are looking at is still worth going to (#1484).

    So the caller hands in the tiles it wants re-heard and this schedules one jump per
    tile, through the same machinery and with the same guarantees: the game's own timer
    owns the waypoints, the client answers each view change with a `world.get.block`, the
    answers land in whatever passive capture is listening, and the run token
    :func:`fast_map_sweep_stop` bumps disowns whatever is still pending.

    **One warzone per call.** Every waypoint carries the same `server`, because a capture
    keys its index on the warzone it is currently hearing and drops the rest the moment
    the client leaves (`TaskIndex.on_server_left`) — measured live: a lap of one warzone
    left 1434 tiles in the checkpoint and going home emptied it within four seconds. A
    caller with tiles on ten warzones therefore makes ten calls and reads between them,
    which is exactly what `SecretTasksTab` does.

    `points` is an iterable of `(x, y)`; duplicates are the caller's to remove — one jump
    per entry is what is scheduled. The height is `SWEEP_ZOOM_MAX` unless named, for the
    reason `docs/research/map-sweep-zoom.md` gives: one notch above it the client goes on
    sending bases and stops sending tasks, silently.
    """
    height = int(SWEEP_ZOOM_MAX if zoom is None else zoom)
    gap = max(0.0, float(FAST_INTERVAL if interval is None else interval))
    where = str(int(server)) if server else current_server_expr()
    items = ",".join("{%d,%d}" % (int(x), int(y)) for x, y in points)
    return (VISIT_CHUNK % (where, items, height, gap, height, gap))


def fast_visit_seconds(count: int, interval: "float | None" = None) -> float:
    """How long a :func:`fast_map_visit` of `count` waypoints takes, so a caller can wait.

    The same arithmetic the Lua does, and the same shape as :func:`fast_sweep_seconds` —
    a caller sitting out a lap it scheduled inside the game should not have to re-derive
    the span from the interval.
    """
    gap = max(0.0, float(FAST_INTERVAL if interval is None else interval))
    return max(0, int(count) - 1) * gap


def fast_map_sweep_stop() -> str:
    """Disown every waypoint a lap still has pending — «Остановить» (#1272).

    The lap hands its whole waypoint list to the game's own timer in one call, so there
    is nothing to cancel and no handle to cancel it with. Bumping the run token is the
    interruption: each pending closure compares it before moving the camera and returns
    when it does not match. The camera stops at wherever it had got to.
    """
    return ("local DC = DataCenter.ActDispatchTaskDataManager "
            "DC.__lw_sweep_run = (tonumber(DC.__lw_sweep_run) or 0) + 1 "
            'CS.UnityEngine.Debug.LogError("ACT sweep_stopped run="'
            "..tostring(DC.__lw_sweep_run))")


def fast_sweep_seconds(step: "int | None" = None, interval: "float | None" = None,
                       size: int = 1000) -> float:
    """How long one `fast_map_sweep` lap takes, so a caller can wait it out.

    The waypoint count is the same arithmetic the Lua does; `size` is the server's tile
    count, which only matters for the estimate — the lap itself asks the scene.
    """
    stride = max(1, int(FAST_STEP if step is None else step))
    gap = max(0.0, float(FAST_INTERVAL if interval is None else interval))
    per_axis = len(range(stride // 2, size, stride))
    return (per_axis * per_axis - 1) * gap


def _pid(x: int, y: int) -> str:
    """Lua expression: tile index (pointId) for tile (x, y)."""
    return 'SceneUtils.TilePosToIndex(CS.UnityEngine.Vector2Int(%d,%d))' % (x, y)


def move_to_coord(x: int, y: int) -> str:
    """In-server move to tile (x, y) by its pointId — the game's OWN move-to-tile.

    `GoToUtil.MoveToWorldPoint(pid)` centres the camera on a tile on the CURRENT server and
    leaves the world/input state consistent. It takes no `serverId`, so it cannot switch
    servers — for a coordinate jump that may target another server use `jump_to_coord`
    (the game's own `GotoWorldPos` path). Kept as the same-server centring primitive
    (e.g. after a jump, before reading a tile). Verified live: camera centres on (x, y),
    UIManager stack stays empty.
    """
    return ('pcall(function() GoToUtil.MoveToWorldPoint(%s) end) '
            'CS.UnityEngine.Debug.LogError("ACT moveto=%d,%d")' % (_pid(x, y), x, y))


def click_world_point(x: int, y: int, ptype: int = 0, uuid: int = 0) -> str:
    """Perform the in-engine map CLICK on tile (x, y) — navigate AND select in one call.

    `GoToUtil.OnClickWorldPoint(pid, type, uuid)` is exactly what a real tap on the map
    triggers: it moves to the tile and opens its `UIWorldPoint` interaction popup with the
    detail loaded. Using it replaces the fragile "camera-jump + pydirectinput pixel tap"
    crutch (whose tap "doesn't land" / under-sends) — the click happens inside the game, so
    there is nothing to miss. Verified live: reopens UIWorldPoint for the target tile.

    `ptype` = MarchTargetType and `uuid` = the tile's server uuid, both from the tile's
    world.get.block data. Monsters need the real server uuid; own resource/base tiles
    accept uuid=0. When you only have coordinates (no tile data), prefer `move_to_coord`
    to centre the view, then read the tile, then click with its real (type, uuid).
    """
    return ('pcall(function() GoToUtil.OnClickWorldPoint(%s,%d,%s) end) '
            'CS.UnityEngine.Debug.LogError("ACT click=%d,%d type=%d")'
            % (_pid(x, y), ptype, uuid, x, y, ptype))


def goto_server(server: int, in_move_to_state: bool = False) -> str:
    """Switch to another server's world the way the in-game UI does — the CLEAN path.

    This is the sequence the engine actually runs on a manual server switch, captured with
    `tools/lua_trace.py --dedup` while the player switched servers by hand (Player.log):

        CrossServerUtil.OnCrossServer(serverId)        -- enter the cross-server context
        GoToUtil.GotoServerZone(serverId, false)       -- navigate to that server's zone

    Notably the manual switch used NEITHER `CrossServerUtil.JumpToServerByServerId` NOR
    `SetCrossEnableList` — those belonged to the removed move-city bulk-load hack that also
    popped the `UIMoveCity` teleport window. `GotoServerZone` is the clean entry: no
    teleport UI, no authorize-list dance. It bulk-loads for targets the client is already
    authorized to view — i.e. servers in an active cross-server event group (e.g. the
    yuntie/meteorite battle group the traced switch belonged to).

    This is a bare server switch (no coordinate). To jump straight to a tile on another
    server prefer `jump_to_coord` (`GotoWorldPos`), which is what the in-game coordinate
    jump actually calls and which also enters the server cleanly.

    `in_move_to_state` is `GotoServerZone`'s second arg (the traced call passed `false`).
    """
    sid = int(server)
    return (
        'pcall(function() CrossServerUtil.OnCrossServer(%d) end) '
        'pcall(function() GoToUtil.GotoServerZone(%d, %s) end) '
        'CS.UnityEngine.Debug.LogError("ACT gotoserver srv=%d reason="..'
        'tostring(select(2,pcall(function() return CrossServerUtil.GetCrossEnableReason(%d) end))))'
        % (sid, sid, "true" if in_move_to_state else "false", sid, sid))


def back_home() -> str:
    """Return from a foreign server to the home server."""
    return ('TimerManager:GetInstance():DelayInvoke(function() '
            'pcall(function() CrossServerUtil.BackToSrcServer() end) '
            'pcall(function() CrossServerUtil.OnBackSelfServer() end) '
            'CS.UnityEngine.Debug.LogError("ACT back done") end, 0.4) '
            'CS.UnityEngine.Debug.LogError("ACT back armed")')


# ---------------------------------------------------------------------------
# Chat send (DM / room). Reverse-engineered live from a PM trace to <Player9>
# (task #1085): text, inline emoji and stickers. See docs/research/chat-send.md.
#
# Every chat send funnels through ONE choke point in the client:
#     ChatManager2:__sendToRoom(roomId, msg, extra, reply, isProxy, post)
# which builds and fires both wire commands (`lw.user.push.chat.msg` + the
# `chat.stat` telemetry twin). `extra` is an optional msgExtra table (srcLang,
# post, atUids, ...) — every field is read defensively, so an empty `{}` sends a
# clean plain message. `reply`=nil, `isProxy`=0, `post`=nil are the text defaults
# captured on the wire.
#
# Room id shapes (docs/research/chat.md §2):
#   DM        custom_<peerUid>_<selfUid>_v2
#   World     country_<server>
#   National  custom_lang_<lang>_<server>
#   Alliance  alliance_<serverId>_<allianceId>
#
# Inline emoji are Private Use Area glyphs (U+E000-U+F8FF) sitting *inside* the
# msg string; emoji id -> PUA is `ChatEmojiTemplateManager:GetEmojiDataById(id).name`
# (a PUA hex stem, e.g. 101 -> "e006" -> U+E006). Resolve those to real chars in
# the caller and hand the finished string here, so this recipe stays a pure send.
#
# Stickers are NOT text — they ride their own manager entry:
#     ChatEmojiTemplateManager:TrySendSticker(roomId, stickerId)


def _lua_bytes(s: str) -> str:
    """A Lua expression rebuilding `s` byte-for-byte via string.char.

    Avoids all quoting/escaping hazards for Cyrillic / CJK / PUA-emoji text when the
    chunk is shipped to the daemon and compiled by xLua (Lua strings are byte arrays).
    """
    b = s.encode("utf-8")
    if not b:
        return '""'
    return "string.char(" + ",".join(str(x) for x in b) + ")"


def chat_send_text(room_id: str, msg: str) -> str:
    """Send `msg` (already-assembled text, may contain inline PUA emoji) to `room_id`."""
    return (
        'pcall(function() local CM=ChatManager2 local inst=CM.GetInstance(CM) '
        'CM.__sendToRoom(inst, %s, %s, {}, nil, 0, nil) end) '
        'CS.UnityEngine.Debug.LogError("ACT chat_sent")'
        % (_lua_bytes(room_id), _lua_bytes(msg))
    )


def chat_send_sticker(room_id: str, sticker_id: int) -> str:
    """Send sticker `sticker_id` to `room_id` via the emoji/sticker manager."""
    return (
        'pcall(function() local em=DataCenter.ChatEmojiTemplateManager '
        'em:TrySendSticker(%s, %d) end) '
        'CS.UnityEngine.Debug.LogError("ACT chat_sticker_sent")'
        % (_lua_bytes(room_id), int(sticker_id))
    )


# ---------------------------------------------------------------------------
# Coordinate ("point") share. Reverse-engineered live for task #1089 from a PM
# trace to <Player9> — see docs/research/chat-coord-share.md.
#
# A shared coordinate is NOT text: it is `post = 13` (PostType.Text_PointShare)
# plus an `attachmentId` JSON blob describing the map object. The base `msg` is
# the literal placeholder "?" — the client renders the bubble from attachmentId
# (ChatMessage:getMessageWithExtra()).
#
# It also does NOT ride `ChatManager2:__sendToRoom`: that path rebuilds `extra`
# and silently drops attachmentId (verified — the echo came back with an empty
# attachment and "this message type is not supported by your game version").
# Shares go out as their own command class, `Chat.NetMessage.ChatShareCommand`,
# dispatched on the chat connection:
#
#     ChatManager2:GetInstance().Net:SendSFSMessage(<cmd>, param)
#
# `ChatShareCommand:OnCreate(param)` reads, in order:
#     post, lang, msg, roomId, tradeName, itemIds, tradePoint, attachmentId,
#     chatType, langRoomLang, toUser, reportUid, cardUuid, planIndex, bossUid,
#     ossAddress, serverIdEx, introductionEx, freeEx
# — everything past `attachmentId` belongs to other share kinds and may be nil.
#
# The command differs per channel (ChatMsgDefines):
#     DM        chat.room.send   (ChatSharePerson)   + toUser = peer uid
#     World     chat.country     (ChatShareCountry)
#     National  chat.country     + langRoomLang = <lang>
#     Alliance  al.msg           (ChatShareAlliance)

POST_POINT_SHARE = 13          # PostType.Text_PointShare

CMD_SHARE_DM = "chat.room.send"
CMD_SHARE_COUNTRY = "chat.country"
CMD_SHARE_ALLIANCE = "al.msg"


def chat_share_cmd(room_id: str) -> str:
    """The share command for a room id (see the table above)."""
    if room_id.startswith("alliance_"):
        return CMD_SHARE_ALLIANCE
    if room_id.startswith("country_") or room_id.startswith("custom_lang_"):
        return CMD_SHARE_COUNTRY
    return CMD_SHARE_DM


def _lua_opt(key: str, value) -> str:
    """`key=<lua>` fragment, or '' when the value is unset (keeps the field nil)."""
    if value in (None, ""):
        return ""
    return "%s=%s, " % (key, _lua_bytes(str(value)))


def chat_share_point(room_id: str, attachment_json: str, post: int = POST_POINT_SHARE,
                     lang: str = "ru", to_user=None, lang_room=None, cmd=None) -> str:
    """Share a map coordinate (`attachment_json`) into `room_id`.

    `attachment_json` is the already-serialised attachmentId blob — the caller owns its
    shape, since it differs per object kind (bare point, mine, monster, secret task...).
    """
    return (
        'pcall(function() local CM=ChatManager2 local inst=CM.GetInstance(CM) '
        'inst.Net:SendSFSMessage(%s, {post=%d, lang=%s, msg="?", roomId=%s, '
        'attachmentId=%s, %s%schatType=0}) end) '
        'CS.UnityEngine.Debug.LogError("ACT chat_point_sent")'
        % (_lua_bytes(cmd or chat_share_cmd(room_id)), int(post), _lua_bytes(lang),
           _lua_bytes(room_id), _lua_bytes(attachment_json),
           _lua_opt("toUser", to_user), _lua_opt("langRoomLang", lang_room))
    )


# --------------------------------------------------------------------------
# Government / ministry — the server's kingdom positions ("министерство")
# --------------------------------------------------------------------------
# The President appoints eight posts; a player asks for one by submitting an
# application. On the wire that is a single command, `kingdom.position.apply`,
# whose only field `positionId` is serialised as a UtfString.
#
# POSITION IDS ARE STRINGS, EVERYWHERE. `GetCanApplyGovernmentList()` hands back
# `"10007"`, not `10007`, and the apply manager keys its own tables the same way, so
# `CheckCanApply(10007)` answers **false** while `CheckCanApply("10007")` answers the
# truth — a silent wrong answer, not an error. Passing a number to
# `SendKingdomPositionApply` is the louder half of the same rule: the client's
# serialiser then throws "attempt to get length of a number value"
# (SFSDataSerializer). Every chunk below quotes the id for exactly this reason.
#
# Ids and names were read live off `GovernmentTemplateManager:GetTemplateName(id)`.
# The template's `type` field splits them into two families that are NOT applied for
# on the same terms: `type == 0` is the ordinary ministry, `type == 1` are the zone-war
# commanders, which only the conqueror may ask for. `slug` is the name the DSL `TAP`
# catalogue uses (tools/lib/game_buttons.py generates one button per post).
# See docs/research/ministry.md.
MINISTRY_POSTS: dict[int, tuple[str, str, str]] = {
    # id: (slug, English gloss, the in-game Russian name)
    10002: ("vice_president", "Vice President", "Вице-президент"),
    10003: ("minister_strategy", "Minister of Strategy", "Министр стратегии"),
    10004: ("minister_defence", "Minister of Defence", "Министр обороны"),
    10005: ("minister_construction", "Minister of Construction", "Министр строительства"),
    10006: ("minister_science", "Minister of Science", "Министр науки"),
    10007: ("minister_interior", "Minister of the Interior", "Министр внутренних дел"),
    10008: ("commander_military", "Military Commander", "Военный командир"),
    10009: ("commander_admin", "Administrative Commander", "Административный командир"),
}

# slug -> id, for CLI arguments that name a post instead of numbering it.
MINISTRY_SLUGS: dict[str, int] = {slug: pid for pid, (slug, _, _) in MINISTRY_POSTS.items()}


def ministry_apply_cooldown_ms(position_id: int) -> str:
    """Lua *expression* -> milliseconds left on the apply cooldown for `position_id`.

    `0` when the post may be asked for now (and when the reading is unavailable, so an
    unknown client cannot lock the ability out). Roughly 1_800_000 straight after an
    application — the same half hour the resign lock runs for.

    This is the real pre-flight, and it is NOT the one the manager advertises.
    `GetOwnApplyCD` reads `ownApplyTimeList[id]` against a config value and the server
    clock; read live it answered `1_696_421` (~28 min) 45 s after an application, and a
    large negative number for posts never asked for. Sending anyway earns
    `errorCode E000000, errorMsg "in cd"` and a toast — the trap the collect-readiness
    gate exists for.

    The id is a STRING here for the usual reason, and this one is worth naming twice:
    `GetOwnApplyCD(10007)` answers a flat `0` — "go ahead" — while
    `GetOwnApplyCD('10007')` answers the truth.
    """
    return ("(function() local ok, cd = pcall(function() "
            "return DataCenter.OfficialApplyManager:GetOwnApplyCD('%d') end) "
            "if not ok or type(cd) ~= 'number' or cd < 0 then return 0 end "
            "return math.floor(cd) end)()" % int(position_id))


def _ministry_gate(position_id: int) -> str:
    """Lua expression: may an application for `position_id` be sent right now?

    Four conditions, and the client's own `CheckCanApply` is only the weakest of them.
    Read back, that method walks `GetCanApplyGovernmentList()` and answers whether the
    id is *in the list* — it is a "does this post exist" test, not a permission one,
    which is why it says `true` while a post is held, while the cooldown runs, and for
    the commander posts nobody may have. Everything it does not cover has to be here,
    because every miss is a request that leaves the client, is rejected, and puts a
    toast in the player's face:

    * `CheckCanApply(id)` — the post is one of the applicable ones at all.
    * the apply cooldown (`ministry_apply_cooldown_ms`) — `errorMsg "in cd"`.
    * a post already held — `errorMsg "has position"`, observed live holding 10005.
    * the conqueror check for `type == 1` posts (the zone-war commanders): the server
      answers `errorCode officer_apply_045`, `errorMsg "not conqueror <alliance uuid>"`.
      Observed live against the Administrative Commander post.

    The conqueror half is verified only in the negative (a non-conqueror is correctly
    blocked); no conqueror account was available to confirm it opens.
    """
    return (
        "(function() local M=DataCenter.OfficialApplyManager "
        "local G=DataCenter.GovernmentManager "
        "if not M:CheckCanApply('%d') then return false end "
        "if %s > 0 then return false end "
        "local ok, own = pcall(function() return M:GetOwnPositionId() end) "
        "if ok and (tonumber(own) or 0) > 0 then return false end "
        "local t=DataCenter.GovernmentTemplateManager:GetTemplate('%d') "
        "if t and t.type==1 then return G:IsConqueror(G.curDataServerId) and true or false end "
        "return true end)()" % (int(position_id), ministry_apply_cooldown_ms(position_id),
                                int(position_id))
    )


def ministry_apply(position_id: int) -> str:
    """Submit an application for kingdom position `position_id`.

    Headless — no window has to be open. The in-game "Подать заявку" button is
    `UIOfficialApplyCtrl:SendKingdomPositionApply(positionId)`, and that method never
    touches `self`, so the module table can stand in for the window controller.

    Gated by `_ministry_gate` — without it the application still leaves the client and
    comes back as a server-side rejection with a player-facing toast, the same trap as
    the resource-collect readiness gate.
    """
    return (
        "local M = DataCenter.OfficialApplyManager "
        "local id = '%d' "
        "if %s then "
        "M:SetViewPositionId(id) "
        "local C = require('UI.UIGovernment.OfficialApply.Controller.UIOfficialApplyCtrl') "
        "C.SendKingdomPositionApply(C, id) end" % (int(position_id), _ministry_gate(position_id))
    )


def ministry_can_apply(position_id: int) -> str:
    """Lua *expression* -> 1 when an application for `position_id` would be accepted.

    Numeric on purpose: it is what `TAP <post> xall` counts down and what a recipe reads
    with `READ_LUA … INTO <var>` to decide whether to bother applying at all. Mirrors
    `ministry_apply`'s gate exactly, so `xall` never reports a press that the chunk then
    silently declines to make.
    """
    return "(%s and 1 or 0)" % _ministry_gate(position_id)


def ministry_own_position() -> str:
    """Lua *expression* -> the id of the post you hold right now, `0` when none.

    The one reading that says whether an application went through: the server grants an
    accepted application straight away, so a round trip later the held post either is the
    one asked for or the request did not take. Proven both ways —
    `0` -> `10007` on the application recorded in docs/research/ministry.md, and unmoved
    at `10005` when the server answered `errorMsg "has position"`.

    It is also the reading that says an application must NOT be sent at all: the server
    refuses one from a player who already holds a post, and `CheckCanApply` does not
    cover that (it answers `true` while a post is held). Without the check the request
    leaves the client, is rejected, and the player gets a toast for it.

    Numeric, so a recipe can test it with the ordinary `IF post == 10007` conditions.
    """
    return ("(function() local ok, p = pcall(function() "
            "return DataCenter.OfficialApplyManager:GetOwnPositionId() end) "
            "if not ok or p == nil then p = DataCenter.GovernmentManager.self_positionId end "
            "return tonumber(p) or 0 end)()")


def ministry_queue_len(position_id: int) -> str:
    """Lua *expression* -> how many players are queued for `position_id`.

    The list is server-fed and NOT pushed: it only holds data after
    `ministry_fetch_queues()` has been run and the reply has landed (~1 s).
    """
    return ("(function() local n=0 "
            "for _ in pairs(DataCenter.OfficialApplyManager:GetApplyList('%d') or {}) do n=n+1 end "
            "return n end)()" % int(position_id))


def ministry_held_minutes(position_id: int) -> str:
    """Lua *expression* -> how many minutes the current holder of `position_id` has sat.

    -1 when the post is vacant (or its holder has not been loaded yet), so a recipe can
    tell "empty seat" from "just appointed".
    """
    return ("(function() local i=DataCenter.GovernmentManager:GetPositionInfoByPositionId('%d') "
            "if not i or not i.appointTime or i.appointTime==0 then return -1 end "
            "return (UITimeManager.Instance:GetSocketTime()-i.appointTime)/60000 end)()"
            % int(position_id))


def ministry_fetch_board() -> str:
    """Load the board: the kingdom's post holders, plus every applicant queue.

    Two requests, both fire-and-forget — read the result from a SEPARATE chunk after a
    settle (never loop-and-wait inside one chunk, it freezes the client):

      * `get.kingdom.positions <the loaded kingdom>` refreshes the holder table.
      * `kingdom.position.apply.list` per post fills the applicant queues, which are
        never pushed and stay empty until asked for.

    The kingdom asked about is `GovernmentManager.curDataServerId` — whichever one the
    client currently has loaded. No attempt is made to pin the board to "my own"
    kingdom: the logged-in account is not a constant (operators switch accounts), and
    the client may be showing a kingdom it was merely browsing. So the reader gets
    what is actually there rather than an assertion — every board row carries its
    holder's server, which makes whose ministry is on screen visible.
    """
    return ("local M = DataCenter.OfficialApplyManager "
            "local G = DataCenter.GovernmentManager "
            "pcall(function() SFSNetwork.SendMessage('get.kingdom.positions', G.curDataServerId) end) "
            "for _, id in pairs(M:GetCanApplyGovernmentList() or {}) do "
            "pcall(function() M:SendKingdomPositionApplyList(id) end) end "
            'CS.UnityEngine.Debug.LogError("ACT ministry_board_requested")')


# --------------------------------------------------------------------------
# Alliance tech — the "Donate 1000" button of the priority science
# --------------------------------------------------------------------------
# `UIAllianceScienceInfoCtrl:OnResDonateClick(scienceId, resType, resNum, btnPos,
# techPointPos)` is the whole donation. Read back with `string.dump`, its body is:
#
#     if LuaEntry.Resource:GetCntByResType(resType) < need then
#         UIUtil.ShowTipsId(...); LWResourceLackUtil.GotoResLack(...); return end
#     if DataCenter.AllianceScienceDataManager:GetResDonateRestCount() <= 0 then ... end
#     SFSNetwork.SendMessage(MsgDefines.AlScienceDonate, ...)   -- 'al.science.donate'
#
# — no `self` field is touched (the dump lists `self` as an unused parameter, and
# `btnPos`/`techPointPos` only anchor the reward-fly animation). So the press does NOT
# need the detail window, or any window: `require`-ing the controller module and calling
# the method with `nil` for self sends the donation from a closed base view. Confirmed
# live with `GetStackTopWindow() == nil`: attempts 14 -> 13.
#
# Both gates read state the server has not yet updated — a donation in flight lowers
# neither the resource count nor the attempt count until `al.science.donate` comes back —
# which is what makes BATCHING work: `n` presses inside ONE Lua call all pass the gate
# and all reach the server. Proven live: one chunk with n=5 took attempts 13 -> 8, and a
# second with n=8 emptied the quota, each in ~0.2 s. That is the whole point of
# `alliance_donate_batch`: a round trip to the VM costs ~0.15 s while the loop inside it
# is free, so a full 30-attempt quota is one call, not thirty.
#
# The freeze pitfall of docs/research/alliance-tech-donate.md still stands and is the
# reason the loop counts to a FIXED `n` instead of looping until the count drops: a
# `while rest > 0` in Lua would spin on a value that cannot change before the frame ends
# and hang the client. The caller reads the real count, presses exactly that many, and
# re-reads to confirm — the count is still the stop condition, just not per press.
_SCIENCE_CTRL = "UI.UIAlliance.UIAllianceScienceInfo.Controller.UIAllianceScienceInfoCtrl"


def alliance_donate_rest(use_gold: bool = False) -> str:
    """Lua *expression* -> donation attempts still banked today (resource, or diamond)."""
    getter = "GetGoldDonateRestCount" if use_gold else "GetResDonateRestCount"
    return "DataCenter.AllianceScienceDataManager:%s()" % getter


def alliance_donate_press(use_gold: bool = False) -> str:
    """One donation to the priority tech — headless, no window open."""
    return alliance_donate_batch(use_gold, times="1", quiet=True)


def alliance_donate_batch(use_gold: bool = False, times: str = "n",
                          quiet: bool = False) -> str:
    """Donate `times` times to the priority tech in ONE game-VM call.

    `times` defaults to the Lua local `n`, which the caller prepends
    (`local n = 7 ` .. this chunk). Unless `quiet`, the chunk reports how many
    presses it actually fired as `ACT fired=<k>` — `k` is below `n` only when the
    run went broke mid-batch.

    The resource check mirrors the controller's own gate, so a batch that would run
    out of resources stops instead of walking into `GotoResLack` (which pops the
    buy-resources window). Like every other counter here it lags the server by a
    round trip, so it catches "already broke", not "broke on this press".
    """
    method = "OnGoldDonateClick" if use_gold else "OnResDonateClick"
    args = "rec.scienceId, rec.goldNum, nil, nil" if use_gold \
        else "rec.scienceId, rec.res, rec.resNum, nil, nil"
    afford = "true" if use_gold else \
        "LuaEntry.Resource:GetCntByResType(rec.res) >= rec.resNum"
    report = "" if quiet else \
        ' CS.UnityEngine.Debug.LogError("ACT fired="..tostring(fired))'
    return (
        "local rec = DataCenter.AllianceScienceDataManager:GetCurRecommendScience() "
        "local ctrl = require('%s') "
        "local fired = 0 "
        "if rec then for _ = 1, %s do "
        "if not (%s) then break end "
        "ctrl.%s(nil, %s) "
        "fired = fired + 1 "
        "end end%s" % (_SCIENCE_CTRL, times, afford, method, args, report)
    )


# --------------------------------------------------------------------------
# Alliance help — the "Помочь всем" button
# --------------------------------------------------------------------------
# `DataCenter.AllianceHelpDataManager:OnHelpAll(otherHelpInfoList)` looks like the
# action and is not: its whole body is `self.otherHelpInfoList = ...` plus
# `self:SetHelpNum(...)`, and its only caller is `AlHelpAllMessage:HandleMessage`.
# It is the *reply applier*. Calling it directly empties the pending list on screen
# and sends nothing — the request vanishes, no alliancemate is helped. That was the
# bug in the first version of this recipe (trace 20260728_232122).
#
# The press is `UILWAlHelpCtrl:OnClickHelpAll`, whose one network line is
#
#     SFSNetwork.SendMessage(MsgDefines.AlHelpAll,   -- 'al.help.all'
#                            curTime, helpAllBtnPos, toPos, nil, true)
#
# and `AlHelpAllMessage:OnCreate` puts exactly ONE field into the SFSObject —
# `cmdBaseTime`. The trailing arguments are kept client-side as `_helpBtnPos` /
# `_flyToPos` / `_isOnlyDisperse` / `_isOnlyShowDiff` and only drive the reward-fly
# animation, so the send needs no window open: `Vector3.zero` twice stands in for the
# on-screen button, matching the real click's `nil, true` tail. Confirmed live —
# `--> al.help.all cmdBaseTime=…` followed by the server's `<-- al.help.all`, with the
# pending list dropping to zero.
#
# The controller gates the send on `can_help` (at least one entry that is not mine),
# and shows tip 390170 otherwise. `alliance_help_pending()` is that same predicate as
# a number — but it is only HALF of "somebody is waiting", and on its own it is the
# half that a headless bot almost never sees. `push.al.help.new` does not put the new
# request into `GetAllianceHelpList()`; its handler only does
# `SetHelpNum(GetHelpNum() + 1)`. The list is filled by the help window's own query and
# rewritten by the `al.help.all` reply, so with no window ever opened it holds nothing
# but my own requests, and a list-only gate declines every request that arrives while
# the bot is running (four live pushes, four refusals — task #1113).
# `alliance_help_waiting()` therefore takes the larger of the two signals, and that is
# what both the chunk gate and the button's `xall` counter use. The red-point count is
# reset by the server's reply (5 -> 0, observed on the wire), so it terminates the loop.
def alliance_help_pending() -> str:
    """Lua *expression* -> alliancemates waiting for help *in the client's list*.

    Non-self entries of `GetAllianceHelpList()`; my own open requests sit in the same
    list (`isSelf == true`) and are not helpable, so they are skipped. Blind to a
    request that has only just arrived — see `alliance_help_waiting()`.
    """
    return ("(function() local n = 0 "
            "for _, it in ipairs(DataCenter.AllianceHelpDataManager:GetAllianceHelpList() or {}) do "
            "if not it.isSelf then n = n + 1 end end "
            "return n end)()")


def alliance_help_red_point() -> str:
    """Lua *expression* -> the red-point count `push.al.help.new` increments."""
    return "(DataCenter.AllianceHelpDataManager:GetHelpNum() or 0)"


def alliance_help_waiting() -> str:
    """Lua *expression* -> how many alliancemates are waiting, by either reading."""
    return "math.max(%s, %s)" % (alliance_help_pending(), alliance_help_red_point())


def alliance_help_all() -> str:
    """Answer every pending alliance help request in one message (`al.help.all`)."""
    return "if %s > 0 then %s end" % (alliance_help_waiting(), alliance_help_send())


def alliance_help_send() -> str:
    """The bare `al.help.all` send, with **no** client-side gate in front of it.

    `alliance_help_all()` above is this plus the gate, which is what a `TAP` wants: it
    decides and sends in one game-VM call. A caller that has ALREADY decided must not go
    through it — the gate would re-run on the Python side's back and turn the press into
    a silent no-op (that is exactly how the auto-helper came to log "helped 6" with
    nothing on the wire). `tools/lib/alliance_help.py` reads both signals itself, prints
    which one saw the request, and sends this.
    """
    return ("local Z = CS.UnityEngine.Vector3.zero "
            "SFSNetwork.SendMessage(MsgDefines.AlHelpAll, "
            "math.floor(UITimeManager:GetInstance():GetServerTime()), Z, Z, nil, true)")


# --------------------------------------------------------------------------
# City visitor — the queue, and which field says what kind a visitor is
# --------------------------------------------------------------------------
# Visitors queue up outside the base in `DataCenter.CityVisitorManager`; a new
# arrival pushes `push.user.visitor.change`. Each queue entry is a wrapper
# `{data = <visitor>, model = <view>}` returned by `GetQueueAllVisitorData(<queue>)`,
# so every field below lives one level in, on `.data` / `.model`.
#
# There is more than ONE queue, and a kind does not get to pick which: the manager
# keeps two, `GetQueueAllVisitorData(1)` and `(2)` (0 and 3+ raise). Live, gift
# visitors sat in queue 1 while the waiting survivor sat in queue 2 — so anything
# that reads a single queue silently cannot see half the visitors, which is what
# `recruit_survivors` was doing. The client itself takes the queue as a parameter
# next to the kind (`GetReceiveAllGiftUidList(<eventType>, <queue>, <max>)`). Both
# queues are therefore scanned, each in its own pcall so a queue the manager does
# not keep is skipped rather than fatal.
#
# The kind is `data.eventType`, and *that* is what indexes the global `VisitorType`
# enum — MERCHANT=1, GIFT=2, RECRUITMENT=3, BATTLE=4, WORKER_LOTTERY=5, …
# The client agrees: `AddVisitor` compares `eventType` against
# `VisitorType.AllianceCongratulation`, and `GetReceiveAllGiftUidList` filters the
# queue on `data.eventType == <the VisitorType asked for>`.
#
# `data.visitorId` is NOT the kind — it is a plain per-arrival counter. A live
# queue read (task #1122) showed four visitors numbered 3, 4, 5, 6 that were all
# `eventType == 2` (GIFT), which is how the earlier `visitorId == VisitorType.X`
# test came to be wrong in both directions: the gift press matched nothing at all
# (no visitor is ever numbered 2 while queued), and the recruit press fired at
# whoever happened to be the *third* visitor of the session regardless of kind.
#
# A visitor is only pressable once it has walked up: `model.isArrival` is true and
# `model.isFinish` false. A queue entry can exist before that (the fourth visitor
# above had a bare model — not spawned yet) and the client leaves those alone.
_VISITOR_QUEUES = (1, 2)


def _visitor_scan(body: str) -> str:
    """Lua statements: run `body` for every entry of every visitor queue.

    `body` is spliced in with the loop variables `d` (the entry's `.data`) and `m`
    (its `.model`) in scope. Each queue is fetched in its own pcall: the manager
    answers for 1 and 2 and raises for the rest, and a client that keeps a different
    number of them should cost this a queue, not the whole reading.
    """
    return ("local __M = DataCenter.CityVisitorManager "
            "for __q = %d, %d do "
            "local __ok, __lst = pcall(__M.GetQueueAllVisitorData, __M, __q) "
            "if __ok and __lst then "
            "for _, e in ipairs(__lst) do local d, m = e and e.data, e and e.model "
            "%s end end end" % (_VISITOR_QUEUES[0], _VISITOR_QUEUES[1], body))


def _visitor_kind_ready(kind: str, fallback: int) -> str:
    """Lua condition snippet: `d` is a waiting visitor of `VisitorType.<kind>`.

    Expects the loop variables `d` (the entry's `.data`) and `m` (its `.model`) to
    be in scope; `fallback` is the enum value to use if the `VisitorType` global
    is missing.
    """
    return ("d and m and d.eventType == ((VisitorType and VisitorType.%s) or %d) "
            "and m.isArrival and not m.isFinish" % (kind, fallback))


# A gift-bearing visitor is not ONE kind, and the set grows with every season: the
# enum ships GIFT, SeasonDayGift, SURVIVOR_PACK_GiFT and SystemGift, and a season
# that adds another would leave a hardcoded list quietly collecting half of them.
# So the kinds are read off the game's own enum by NAME — every `VisitorType`
# whose name says "gift", however it is spelled (`SURVIVOR_PACK_GiFT` is the
# client's own capitalisation) — and the count and the press share the one set.
# The fallback is plain GIFT, so a VM that answers no enum at all still collects
# what the recipe has always collected.
_VISITOR_GIFT_SET = ("local __K = {} "
                     "if VisitorType then for __k, __v in pairs(VisitorType) do "
                     "if type(__v) == 'number' and tostring(__k):lower():find('gift', 1, true) "
                     "then __K[__v] = true end end end "
                     "if next(__K) == nil then __K[2] = true end ")

_VISITOR_GIFT_READY = ("d and m and __K[d.eventType] "
                       "and m.isArrival and not m.isFinish")


def _visitor_count(ready: str, prelude: str = "") -> str:
    """Lua *expression* -> how many waiting visitors match `ready` anywhere.

    `ready` is a condition over the loop variables `d` / `m`; `prelude` is spliced in
    ahead of the scan, for a condition that needs a table built first.
    """
    return ("(function() local n = 0 %s%s return n end)()"
            % (prelude, _visitor_scan("if %s then n = n + 1 end" % ready)))


def _visitor_operate_first(ready: str, prelude: str = "") -> str:
    """Send `visitor.operate {uid, operate = 1}` for the front matching waiting visitor.

    Gated on the matching count so a queue with nobody of that kind waiting never
    spends a server round trip. The send returns out of both loops, so exactly one
    visitor is pressed however many queues had a candidate.
    """
    return ("(function() %sif %s <= 0 then return end %s end)()"
            % (prelude, _visitor_count(ready, prelude),
               _visitor_scan("if %s then "
                             "SFSNetwork.SendMessage(MsgDefines.VisitorOperateMessage, d.uid, 1) "
                             "return end" % ready)))


# --------------------------------------------------------------------------
# City visitor — recruit a waiting survivor ("Собрать выжившего")
# --------------------------------------------------------------------------
# A waiting survivor is a queue entry of kind `VisitorType.RECRUITMENT` (3). The
# recruit press (the «Нанять»/agree button of UIWorkerDetailRecruit) sends ONE
# message, seen whole in trace 20260729_145441 «Собрать выжившего»:
#
#     SFSNetwork.SendMessage(MsgDefines.VisitorOperateMessage, uid, 1)
#       -- MsgDefines.VisitorOperateMessage == 'visitor.operate'
#       -- SFSObject: PutLong('uid', <visitor uid>) + PutInt('operate', 1)
#
# `operate = 1` is accept/recruit (the button was `agreeBtn`); no other operate
# value was observed. The message body is exactly {uid, operate}, so the send
# needs no window open — the uid is read straight off the queued visitor's data.
def visitor_recruit_pending() -> str:
    """Lua *expression* -> how many queued visitors are recruitable survivors."""
    return _visitor_count(_visitor_kind_ready("RECRUITMENT", 3))


def visitor_recruit_survivor() -> str:
    """Recruit the first waiting survivor visitor (`visitor.operate {uid, operate=1}`)."""
    return _visitor_operate_first(_visitor_kind_ready("RECRUITMENT", 3))


# --------------------------------------------------------------------------
# City visitor — collect a gift-bearing survivor ("Собрать подарки выжившего")
# --------------------------------------------------------------------------
# A *gift* visitor is the same CityVisitorManager queue mechanic as the recruit
# survivor above — only the kind differs, and there is more than one of them. The
# client's own enum calls four kinds a gift: GIFT (2), SeasonDayGift (10),
# SURVIVOR_PACK_GiFT (19) and SystemGift (30), read live off `VisitorType` on
# 2026-09-01 for #2083, when a season put new survivors at the same gate carrying
# the same kind of present. So the set is derived from the enum BY NAME rather
# than written down: a season that adds a fifth is collected the day it opens,
# and nothing has to be edited when one turns over. Tapping such a visitor and collecting its gift sends
# the identical one-shot message, captured whole in trace 20260729_151712
# «Собрать подарки выжившего»:
#
#     SFSNetwork.SendMessage(MsgDefines.VisitorOperateMessage, uid, 1)
#       -- visitor.operate  {uid = <visitor uid>, operate = 1}
#
# After the send the client flew a coin-box reward (`UIUtil.DoFly(7, 1,
# icon_coinbox, ...)`) and destroyed the UICityVisitor window — i.e. operate=1
# means "collect the gift" here just as it means "accept" for a recruit. Because
# the body is only {uid, operate}, no window need be open: the uid is read
# straight off the queued visitor's data, exactly like the recruit path.
#
# The count is cross-checked against the client's own batch-claim list,
# `GetReceiveAllGiftUidList(VisitorType.GIFT, 1, n)`: on a live queue of four gift
# visitors, one of them not yet arrived, both said 3.
def visitor_gift_pending() -> str:
    """Lua *expression* -> how many queued visitors are gift-bearing survivors."""
    return _visitor_count(_VISITOR_GIFT_READY, _VISITOR_GIFT_SET)


def visitor_gift_collect() -> str:
    """Collect the first gift-bearing survivor (`visitor.operate {uid, operate=1}`)."""
    return _visitor_operate_first(_VISITOR_GIFT_READY, _VISITOR_GIFT_SET)


# --------------------------------------------------------------------------
# Occupation ("profession") skills — the Mastery tree
# --------------------------------------------------------------------------
# In game these are «навыки профессии»: the active skills of the profession the
# player picked (`home_id` 101 = Инженер / Engineer, 102 = Военный лидер / Warlord).
# On the wire one press is a single command:
#
#     --> use.desert.talent.skill  {skillId = "10113"}
#     <-- use.desert.talent.skill  {skillId, type = 1018, todayTimes = 1,
#                                   recover = {lastTime, duration, num, max, type,
#                                              cdEndTime},
#                                   exeObj = {reward = [...], lucky, bTypes, ...}}
#
# `recover` is the charge counter: `num` charges banked out of `max`, refilling
# `duration` ms after `lastTime`. That reply is what puts the skill on cooldown —
# nothing client-side does, which is why the re-fire guard below exists.
#
# The owning manager is `DataCenter.MasteryManager`:
#
#   * `UseSkill(skillId, pointId, msgId, serverId)` — what the in-game useBtn calls
#     (LWUIMasterySkillUseInWorldCell:OnBtnClickFunc). It routes on where the skill
#     is cast from and, for a no-target skill, ends in the sender.
#   * `SendUseSkillMsg(skillTemp, param, msgId)` — THE SENDER (its constants carry
#     `SFSNetwork | SendMessage | MsgDefines | MasteryUseSkill`).
#   * `HandleUseSkill(msg)` — the reply applier (rewards, popups,
#     `SetSkillCdAndEffectTime`). Calling it sends nothing; it is not the press.
#
# Verified without spending a charge: with `SendUseSkillMsg` and
# `SFSNetwork.SendMessage` temporarily stubbed out, `MasteryManager:UseSkill(10113)`
# — no pointId, no serverId — arrived at
# `SendUseSkillMsg(skillTemp{id=10113}, param=nil, msgId='use.desert.talent.skill')`,
# byte-for-byte the send the human click produced in trace
# `20260729_010052_навыки_профессии` (`SFSNetwork.SendMessage <- use.desert.talent.skill,
# 10113, nil`). No confirmation dialog on the way. See
# docs/research/occupation-skills.md.

# `MasterySkillState` (a game global). Only `Normal` may be pressed.
MASTERY_STATE_NONE, MASTERY_STATE_NORMAL, MASTERY_STATE_LOCKED = 0, 1, 2
MASTERY_STATE_CD, MASTERY_STATE_COVERED = 3, 4
MASTERY_STATE_NOUSE, MASTERY_STATE_EFFECT = 5, 6
MASTERY_STATE_NAMES: dict[int, str] = {
    MASTERY_STATE_NONE: "none",
    MASTERY_STATE_NORMAL: "ready",
    MASTERY_STATE_LOCKED: "locked",
    MASTERY_STATE_CD: "cooldown",
    MASTERY_STATE_COVERED: "covered",     # superseded by a higher tier of the same node
    MASTERY_STATE_NOUSE: "no-use",
    MASTERY_STATE_EFFECT: "in-effect",
}

# How long a just-fired skill stays excluded from the "ready" list. The client only
# learns about the new cooldown when the server's reply lands (~0.2-8 s observed), so
# without this a second press in that window would fire the SAME skill twice. Anything
# longer than the round trip and shorter than a real cooldown (>= 23 h) works.
MASTERY_REFIRE_GUARD_MS = 120_000


def _occupation_ready_ids() -> str:
    """Lua *expression* -> array of skill ids that can be fired right now, headless.

    Three filters, all of them load-bearing:

    * `active_skills` — passive nodes have no press at all.
    * `CheckUsePosition(MasterySkillUsePosType.SkillView)` — the skill is cast from the
      skill panel and needs NO target. The others (`Building`, `Field`, …) send a march
      or want a map point, and firing them blind would aim at nothing; they are left to
      a future targeted recipe.
    * `GetMasteryGroupSkillState(masteryId) == Normal` — the client's own gate. `CD`,
      `Locked` and `Covered` all read as "not now", and pressing anyway earns a
      server-side rejection with a player-facing toast (the same trap as the
      resource-collect readiness gate).

    Plus the re-fire guard: ids stamped by `apply_next_occupation_skill()` less than
    `MASTERY_REFIRE_GUARD_MS` ago are dropped, so `xall` cannot double-fire one skill
    while its cooldown is still in flight. The stamps live on the manager table
    (`__lw_fired`) rather than in a global — this VM rejects some new globals.
    """
    return (
        "(function() local M=DataCenter.MasteryManager "
        "local d=M:GetData() if not d then return {} end "
        "local now=UITimeManager:GetInstance():GetServerTime() "
        "local fired=M.__lw_fired or {} local out={} "
        "for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do "
        "local sid=M:GetCurSkillIdByMasteryId(mid) "
        "local t=sid and M:GetSkillTemplate(sid) "
        "if t and t.active_skills "
        "and t:CheckUsePosition(MasterySkillUsePosType.SkillView) "
        "and M:GetMasteryGroupSkillState(mid)==MasterySkillState.Normal "
        "and (now-(fired[sid] or 0))>%d then out[#out+1]=sid end end "
        "return out end)()" % MASTERY_REFIRE_GUARD_MS
    )


def occupation_skills_ready_count() -> str:
    """Lua *expression* -> how many no-target profession skills are off cooldown.

    What `TAP use_profession_skill xall` counts down, and what a recipe reads with
    `READ_LUA … INTO n` to decide whether the panel is worth opening at all.
    """
    return "#%s" % _occupation_ready_ids()


def apply_next_occupation_skill() -> str:
    """Fire the first ready no-target profession skill (one press, one skill).

    One press per chunk on purpose: the charge only drops when the server answers, and
    a `while ready > 0 do press() end` inside a single chunk would spin the game's main
    thread and freeze the client. `xall` re-reads the count between presses instead.
    """
    return (
        "local M=DataCenter.MasteryManager "
        "local ids=%s local sid=ids[1] "
        "if sid then M.__lw_fired=M.__lw_fired or {} "
        "M.__lw_fired[sid]=UITimeManager:GetInstance():GetServerTime() "
        "pcall(function() M:UseSkill(sid) end) "
        'CS.UnityEngine.Debug.LogError("ACT occupation_skill_used "..tostring(sid)) end'
        % _occupation_ready_ids()
    )


def skill_cooldown_remaining(skill_id: int) -> str:
    """Lua *expression* -> milliseconds until `skill_id` can be fired again.

    `0` = a charge is banked right now. `-1` = the question does not apply — the id is
    not an active skill of this profession, or its node is `Locked` / `Covered` (a tier
    superseded by a higher one, which carries no charge data at all and would otherwise
    read as a confident, wrong "ready now").

    This is `GetSkillAvailableTime` — the epoch-ms the NEXT charge lands, which is the
    server's `recover.cdEndTime` — minus the server clock, never the local one: the two
    drift, and every timestamp in this subsystem is server time.

    Milliseconds because that is what the game stores; a recipe that wants minutes
    divides. Deliberately independent of the re-fire guard in
    `apply_next_occupation_skill()` — this answers "what does the GAME think", which is
    what a scheduler wants when deciding how long to sleep before coming back.
    """
    return (
        "(function() local M=DataCenter.MasteryManager "
        "local d=M:GetData() if not d then return -1 end "
        "for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do "
        "local sid=M:GetCurSkillIdByMasteryId(mid) "
        "if sid==%d then "
        "local t=M:GetSkillTemplate(sid) "
        "if not (t and t.active_skills) then return -1 end "
        "local st=M:GetMasteryGroupSkillState(mid) "
        "if st==MasterySkillState.Locked or st==MasterySkillState.Covered "
        "or st==MasterySkillState.None then return -1 end "
        "local avail=d:GetSkillAvailableTime(sid) or 0 "
        "if avail==0 then return 0 end "
        "local left=avail-UITimeManager:GetInstance():GetServerTime() "
        "if left<0 then left=0 end return left end end "
        "return -1 end)()" % int(skill_id)
    )


def skill_can_use(skill_id: int) -> str:
    """Lua *expression* -> 1 when `skill_id` is a no-target skill that may be fired now.

    Numeric so a recipe can gate on it, and so `TAP <one skill> xall` stops at one press.
    """
    return ("(function() for _,sid in ipairs(%s) do "
            "if sid==%d then return 1 end end return 0 end)()"
            % (_occupation_ready_ids(), int(skill_id)))


def apply_occupation_skill(skill_id: int) -> str:
    """Fire one specific profession skill by id, gated by `skill_can_use`.

    For pinning a routine to a named skill («Быстрое Производство» and nothing else).
    Ungated it would still leave the client and come back as a rejection toast.
    """
    return ("if %s==1 then local M=DataCenter.MasteryManager "
            "M.__lw_fired=M.__lw_fired or {} "
            "M.__lw_fired[%d]=UITimeManager:GetInstance():GetServerTime() "
            "pcall(function() M:UseSkill(%d) end) end"
            % (skill_can_use(skill_id), int(skill_id), int(skill_id)))


# -- Win-Win Cooperation: the one profession skill that is cast ON ANOTHER PLAYER ---
#
# «Взаимовыгодное сотрудничество» / "Win-Win Cooperation" — an Engineer node whose
# use-position is `Building` rather than `SkillView`, so it needs a target and cannot go
# through `apply_next_occupation_skill()`. The game's own words for what it does
# (`season_mastery_s3_text_2_1`): "Can only be used on the War Leader: reduces THEIR
# construction and tech research costs … Earn rewards." The reward is ours; the discount
# is theirs. It costs nothing but the charge.
#
# THE TARGET'S PROFESSION IS IN THE DATA, which was the open question. Every record the
# client keeps about another player carries `careerType` — the same number as one's own
# `home_id` (101 Engineer, 102 War Leader) — and `careerLv` beside it. It is on the
# world point detail a marker tap fetches AND on the alliance roster, and the roster is
# the useful one: `AllianceCareerManager:GetAllianceMemberListByCareer(102)` hands back
# every War Leader in the alliance already filtered, each record carrying the `pointId`
# and `serverId` the press wants. No request goes on the wire to ask — the client has it.
#
# So there is no server-side "find me a candidate" call to imitate: the camera flight a
# player sees when they pick this skill is the client walking its own roster.
WIN_WIN_SKILL_ID = 10417

#: The professions, as the game numbers them — one's own `home_id` and another player's
#: `careerType` are the same scale.
CAREER_ENGINEER, CAREER_WAR_LEADER = 101, 102


def _win_win_node() -> str:
    """Lua fragment: `node` = the mastery node whose current skill is Win-Win, or nil.

    Resolved off the tree rather than written down, for the reason
    :func:`_occupation_ready_ids` gives: the node a skill sits at depends on the
    profession and on how far the tree is levelled. An account that is a War Leader —
    or an Engineer who has not learnt this node — simply has no match, which the gate
    reports as `state=-1` rather than pretending the skill is on cooldown.
    """
    return ("local node=nil if d then "
            "for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do "
            "if M:GetCurSkillIdByMasteryId(mid)==%d then node=mid break end end end "
            % WIN_WIN_SKILL_ID)


def win_win_state() -> str:
    """Lua *expression* -> one line of `key=value` about Win-Win, read in one trip.

    `state` is the client's own `MasterySkillState` for the node — `1` Normal (a charge
    is banked), `3` CD, and **`-1` when this account has no such node at all**, which is
    the honest answer for a War Leader and for an Engineer who has not learnt it. `-2`
    is a client that cannot answer for the tree at all (the login screen, which answers
    everything and knows nothing).

    `cands` is how many War Leaders of the alliance the client can name a base tile for
    — the press has nothing to aim at below one. `next_ms` is the server's own countdown
    to the next charge (`GetSkillAvailableTime`, i.e. `recover.cdEndTime`), `0` when one
    is banked now. `since_fire` is how long ago this recipe last fired it, so a re-fire
    inside the guard window is visible instead of looking like a refusal.
    """
    return (
        "(function() local M=DataCenter.MasteryManager "
        "local d=nil pcall(function() d=M:GetData() end) "
        "if not d then return 'state=-2 charges=0 cands=0 next_ms=0 since_fire=0' end "
        "local now=UITimeManager:GetInstance():GetServerTime() "
        + _win_win_node() +
        "local st=-1 local ch=0 local nxt=0 "
        "if node then st=M:GetMasteryGroupSkillState(node) or 0 "
        "pcall(function() local c=d:GetSkillChargeData(%d) ch=(c and c.num) or 0 end) "
        "local avail=0 pcall(function() avail=d:GetSkillAvailableTime(%d) or 0 end) "
        "if avail>0 then nxt=avail-now if nxt<0 then nxt=0 end end end "
        "local n=0 pcall(function() "
        "for _,v in pairs(DataCenter.AllianceCareerManager"
        ":GetAllianceMemberListByCareer(%d) or {}) do "
        "if type(v)=='table' and (v.pointId or 0)>0 then n=n+1 end end end) "
        "local f=M.__lw_fired or {} "
        "return 'state='..tostring(st)..' charges='..tostring(ch)..' cands='..tostring(n)"
        "..' next_ms='..tostring(math.floor(nxt))"
        "..' since_fire='..tostring(math.floor(now-(f[%d] or 0))) end)()"
        % (WIN_WIN_SKILL_ID, WIN_WIN_SKILL_ID, CAREER_WAR_LEADER, WIN_WIN_SKILL_ID)
    )


def win_win_ready() -> str:
    """Lua *expression* -> `1` when the skill can be fired at somebody right now.

    Everything :func:`win_win_state` reports, folded into the one number a recipe gates
    on and the button counts down: the node exists, the client says `Normal`, at least
    one War Leader has a tile to aim at, and the re-fire guard has expired.
    """
    return (
        "(function() local M=DataCenter.MasteryManager "
        "local d=nil pcall(function() d=M:GetData() end) if not d then return 0 end "
        "local now=UITimeManager:GetInstance():GetServerTime() "
        + _win_win_node() +
        "if not node then return 0 end "
        "if M:GetMasteryGroupSkillState(node)~=MasterySkillState.Normal then return 0 end "
        "local f=M.__lw_fired or {} if (now-(f[%d] or 0))<=%d then return 0 end "
        "local n=0 pcall(function() "
        "for _,v in pairs(DataCenter.AllianceCareerManager"
        ":GetAllianceMemberListByCareer(%d) or {}) do "
        "if type(v)=='table' and (v.pointId or 0)>0 then n=n+1 end end end) "
        "if n<1 then return 0 end return 1 end)()"
        % (WIN_WIN_SKILL_ID, MASTERY_REFIRE_GUARD_MS, CAREER_WAR_LEADER)
    )


def apply_win_win() -> str:
    """Fire Win-Win at one War Leader of the alliance — one press, one target.

    **`UseSkill` is deliberately NOT the call, and the reason cost a whole round of
    debugging.** The obvious version — `MasteryManager:UseSkill(10417, pointId, nil,
    serverId)`, the in-game click's own entry point — reaches `SendUseSkillMsg` and then
    nothing happens: measured live, every `Building`-position skill sends **zero** bytes
    through that route while every `SkillView` one sends its message, so the send is
    handed to a later frame that the panel's thread never gives it (the same shape as
    `SendCreateMarchMessage` needing `DelayInvoke`). A press through `UseSkill` therefore
    reports success, spends nothing and changes nothing.

    `SendUseSkillMsg` itself is fine and sends synchronously — proven live, and then
    proven by spending a real charge: `state` 1 → 3, `num` 1/1 → 0/1, `cdEndTime` 0 → a
    stamp 23 h 29 m out. So the press is the sender, called directly, with exactly the
    param `UseSkill` builds: `{otherUid, serverId}` off the roster record, and
    `MsgDefines.MasteryUseSkill`. No march is involved on either route.

    THE FIRST DRY RUN "PROVED" THE BROKEN VERSION, and that is the lesson worth keeping:
    it stubbed `SendUseSkillMsg` and watched `UseSkill` reach it. What it could not see
    is that the REAL sender never runs. A stub that replaces the thing under test proves
    only that its caller was reached — stub the layer BELOW it (`SFSNetwork.SendMessage`)
    and the emptiness is obvious at once.

    WHICH War Leader is chosen deliberately rather than "the first one": somebody who is
    online will actually spend the discount inside the day it lasts, and among those the
    biggest base has the most building and research left to spend it on. Ties fall back
    to whatever the roster happens to hand over, which is fine — every candidate is a
    legal target and the reward is ours either way.

    The id is stamped on `__lw_fired` before the call, exactly as
    :func:`apply_next_occupation_skill` does and for the same reason: the charge only
    drops when the server's reply lands, so without the stamp a second tap inside that
    window would fire at a second player off one charge.
    """
    return (
        "local M=DataCenter.MasteryManager "
        "local d=nil pcall(function() d=M:GetData() end) "
        "local now=UITimeManager:GetInstance():GetServerTime() "
        + _win_win_node() +
        "local f=M.__lw_fired or {} "
        "if node and M:GetMasteryGroupSkillState(node)==MasterySkillState.Normal "
        "and (now-(f[%d] or 0))>%d then "
        "local pick=nil pcall(function() "
        "for _,v in pairs(DataCenter.AllianceCareerManager"
        ":GetAllianceMemberListByCareer(%d) or {}) do "
        "if type(v)=='table' and (v.pointId or 0)>0 then "
        "if pick==nil then pick=v "
        "elseif (v.online and true or false)~=(pick.online and true or false) then "
        "if v.online then pick=v end "
        "elseif (v.mainCityLv or 0)>(pick.mainCityLv or 0) then pick=v end end end end) "
        "if pick then M.__lw_fired=f M.__lw_fired[%d]=now "
        "local t=M:GetSkillTemplate(%d) "
        "pcall(function() M:SendUseSkillMsg(t, "
        "{otherUid=tostring(pick.uid), serverId=pick.serverId}, "
        "MsgDefines.MasteryUseSkill) end) "
        'CS.UnityEngine.Debug.LogError("ACT win_win_used point "..tostring(pick.pointId)) '
        'else CS.UnityEngine.Debug.LogError("ACT win_win_no_candidate") end '
        'else CS.UnityEngine.Debug.LogError("ACT win_win_not_ready") end'
        % (WIN_WIN_SKILL_ID, MASTERY_REFIRE_GUARD_MS, CAREER_WAR_LEADER,
           WIN_WIN_SKILL_ID, WIN_WIN_SKILL_ID)
    )


def occupation_skills_dump() -> str:
    """Reader chunk: one `ACT S …` line per active skill of the current profession.

    Fields: `sid` skill id, `mid` mastery node, `st` MasterySkillState, `pos` where it is
    cast from (`SkillView` = no target), `num`/`max` banked charges, `avail` epoch-ms the
    next charge lands (0 = now), `cd` the full cooldown in minutes, and `name`, hex-encoded
    because the display name is localised and the log channel is ASCII-only.
    """
    return (
        "local M=DataCenter.MasteryManager local d=M:GetData() "
        'local function hex(s) return (tostring(s):gsub(".", '
        'function(c) return string.format("%02x", string.byte(c)) end)) end '
        "local names={} for k,v in pairs(MasterySkillUsePosType) do names[v]=k end "
        'CS.UnityEngine.Debug.LogError("ACT now "..tostring(UITimeManager:GetInstance():GetServerTime())'
        '.." home "..tostring(d and d.home_id).." lv "..tostring(d and d.level)) '
        "if not d then return end "
        "for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do "
        "local sid=M:GetCurSkillIdByMasteryId(mid) "
        "local t=sid and M:GetSkillTemplate(sid) "
        "if t and t.active_skills then "
        "local pos='' for v=0,9 do if t:CheckUsePosition(v) then pos=(names[v] or tostring(v)) end end "
        "local c=d:GetSkillChargeData(sid) "
        'CS.UnityEngine.Debug.LogError(string.format('
        '"ACT S sid=%s mid=%s st=%s pos=%s num=%s max=%s avail=%s cd=%s name=%s", '
        "tostring(sid), tostring(mid), tostring(M:GetMasteryGroupSkillState(mid)), pos, "
        "tostring(c and c.num or 0), tostring(c and c.max or 0), "
        "tostring(d:GetSkillAvailableTime(sid) or 0), tostring(t.cd_time), "
        "hex(UIUtil:GetString(t.name)))) end end"
    )


# --------------------------------------------------------------------------
# Secret-task robbery — «кража секретки»
# --------------------------------------------------------------------------
# A secret task (hero dispatch) sitting on another player's tile can be robbed
# three times before its loot slots are full. On the wire one robbery is a
# single command with no coordinate in it at all:
#
#     --> hero.dispatch.steal   {uuid, targetServer}
#     <-- push.hero.dispatch.mission.steal {pointId, serverId, worldId, playerInfo}
#     <-- hero.dispatch.steal   {reward[], ownerInfo, recordUuid, todayStealNum, ...}
#
# The Lua side, pinned live against the VM for task #1099 (traces
# `20260729_013329_кража_серкетки` / `20260729_013404_Кража_секретки`; both
# traffic checkpoints came back with keepalives only, so the wire half is the
# 2026-07-19 capture written up in docs/research/protocol.md §7):
#
#   * `MsgDefines.DispatchSteal` = `hero.dispatch.steal`.
#   * `Net.Msgs.DispatchTask.DispatchStealMessage:OnCreate(uuid, targetServer)`
#     puts exactly two fields in the SFSObject — `PutLong uuid`,
#     `PutInt targetServer`. So the send needs NO window open and no map tap.
#   * The in-game press is `UIWorldPointBtn:onDispatchTaskClick(btnType)` with
#     `btnType == WorldPointBtnType.DispatchTaskSteal` (54 — the same 54 the
#     trace passes to `LoadPath.GetBuildBtnSpritePath`, i.e. the «украсть»
#     icon). Its whole network line is that one `SFSNetwork.SendMessage`.
#   * `DispatchStealMessage:HandleMessage` is the reply applier (rewards,
#     `ShowReward`, `UpdateTodayNum`, `UpdateSteal`) — calling it sends nothing.
#     Same trap as `AllianceHelpDataManager:OnHelpAll`; the press is the send.
#
# THE TARGET IS A `uuid`, NOT A COORDINATE. A caller holding only x/y resolves
# it first with `secret_task_request_detail()` + `secret_task_uuid_at()` (the
# `world.get.detail.new` round trip the client itself fires when a marker is
# tapped) — verified live: asking for a known alliance task's pointId returned
# the same uuid the dispatch record carries.
#
# See docs/research/secret-task-steal.md.

# `WorldPointType.HERO_DISPATCH` — the pointType `world.get.detail.new` wants
# for a secret-task marker (and the `f2 = 17` tiles the map scanner decodes).
SECRET_TASK_POINT_TYPE = 17

# `WorldPointBtnType.DispatchTaskSteal` — the popup button this recipe replaces.
# Not used by the send (the send is the message, not the button); kept because it
# is what identifies the traced click.
SECRET_TASK_STEAL_BTN = 54


def secret_task_steals_left() -> str:
    """Lua *expression* -> how many robberies the account may still make today.

    `GetDispatchSetting("steal_count")` is the daily cap (5 on the live account) and
    `GetTodayStealNum()` what has been spent; the server resets both. This is the ONE
    gate that is fully readable client-side, which is why every press below carries it
    and why it is the `count_lua` of the `steal_secret_task` button.

    The other conditions `onDispatchTaskClick` checks — the tile's own looter list
    (`stealList:Contains(selfUid)`, max three) and its `protect_times` window — hang off
    the world object of a tile that is currently rendered, so they are NOT answerable
    for an arbitrary uuid. Those stay the server's job: a robbery it refuses comes back
    as `hero.dispatch.steal` with an `errorCode` and the client pops the matching tip.
    """
    return ("(function() local M=DataCenter.ActDispatchTaskDataManager "
            "local cap=tonumber(M:GetDispatchSetting('steal_count')) or 0 "
            "local used=tonumber(M:GetTodayStealNum()) or 0 "
            "local left=cap-used if left<0 then left=0 end return left end)()")


def secret_task_request_detail(x: int, y: int, server: int) -> str:
    """Ask the server for the marker detail of tile (x, y) — the uuid lookup.

    This is the first of the two messages a manual robbery sends: tapping a secret-task
    marker fires `world.get.detail.new {point, serverId, 0, pointType = 17, uid = ""}`,
    and the reply is parsed into `WorldPointDetailManager`, keyed by pointId. Read the
    uuid out of it with `secret_task_uuid_at()` AFTER a settle — never in the same
    chunk, the reply has not landed yet.
    """
    return ('pcall(function() SFSNetwork.SendMessage("world.get.detail.new", %s, %d, 0, %d, "") end) '
            'CS.UnityEngine.Debug.LogError("ACT detail_requested %d,%d srv=%d")'
            % (_pid(x, y), int(server), SECRET_TASK_POINT_TYPE, x, y, int(server)))


def secret_task_uuid_at(x: int, y: int) -> str:
    """Lua *expression* -> the task uuid cached for tile (x, y), or 0.

    `0` means "not asked for yet, or the reply has not arrived" — not "no task there".
    The cache is per pointId and survives across chunks, so the usual shape is
    request -> wait -> read.
    """
    return ("(function() local d=DataCenter.WorldPointDetailManager:GetDetailByPointId(%s) "
            "return (d and d.uuid) or 0 end)()" % _pid(x, y))


def secret_task_owner_at(x: int, y: int) -> str:
    """Lua *expression* -> the uid of the player whose task sits on tile (x, y), or 0.

    From the same cached detail. Lets a caller refuse to rob its own or an
    alliancemate's task before spending one of the day's five attempts.
    """
    return ("(function() local d=DataCenter.WorldPointDetailManager:GetDetailByPointId(%s) "
            "return (d and d.uid) or 0 end)()" % _pid(x, y))


def secret_task_steal(uuid: int, server: int) -> str:
    """Rob the secret task `uuid` on `server` — one `hero.dispatch.steal`.

    Headless: no marker tap, no `UIWorldPoint` window, no camera move. Gated on the
    daily budget so a spent account does not put a doomed message on the wire (the
    server would answer with an errorCode and the client would raise a toast — the same
    trap as the resource-collect readiness gate).
    """
    return ('if %s > 0 then '
            'pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchSteal, %d, %d) end) '
            'CS.UnityEngine.Debug.LogError("ACT steal_sent uuid=%d srv=%d") end'
            % (secret_task_steals_left(), int(uuid), int(server), int(uuid), int(server)))


def secret_task_leave_message(record_uuid: int, msg_id: int, server: int) -> str:
    """Leave the robbed player one of the canned emoji («стикер вдогонку»).

    The optional second half of the flow: the reward window that opens after a
    successful robbery has an emoji strip, and picking one fires
    `MsgDefines.DispatchLeaveMessage` = `hero.dispatch.leave.message`
    ({`recordUuid`, `msgId`, `targetServer`}) — read off
    `UIDispatchTaskRewardView:OnStealMessageBtnClick`.

    `record_uuid` is the `recordUuid` from the robbery's own reply (NOT the task uuid),
    and `msg_id` one of the ids in `GetStealEmojiList()` (11 of them live). Pure
    flavour — it pays nothing and is not part of the loot.
    """
    return ('pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchLeaveMessage, %d, %d, %d) end) '
            'CS.UnityEngine.Debug.LogError("ACT steal_message_sent record=%d msg=%d")'
            % (int(record_uuid), int(msg_id), int(server), int(record_uuid), int(msg_id)))


# --- the target queue ------------------------------------------------------
# `TAP` takes no arguments, so a button cannot be told *which* task to rob. The
# targets are therefore parked in the game VM — on the dispatch manager's own
# table (`__lw_steal_queue`), because this VM rejects some new globals — and the
# button robs the first one and drops it. Filling the queue is the job of
# `tools/steal_secret_task.py`: it is the side that can scan the map, resolve a
# coordinate to a uuid across a round trip, and drop what is already looted out.
# The same split as the profession skills: one press = one action, `xall` walks
# the set, and the count is re-read between presses.

def secret_task_queue_set(targets) -> str:
    """Replace the steal queue with `targets` — an iterable of (uuid, server) pairs."""
    items = ",".join("{uuid=%d,server=%d}" % (int(u), int(s)) for u, s in targets)
    return ("local M=DataCenter.ActDispatchTaskDataManager M.__lw_steal_queue={%s} "
            % items + _STEAL_MARK
            + 'CS.UnityEngine.Debug.LogError("ACT steal_queue_set "'
              '..tostring(#M.__lw_steal_queue))')


# WHAT THE SERVER SAYS WHEN THE TILE IS GONE, and why the spam has to hear it (#1272).
#
# `DispatchStealMessage:HandleMessage` is `errorCode -> UIUtil.ShowTipsId(errCode)`, and
# the errorCode IS the message key — the same shape the assist's refusal came back as.
# Read out of the live client's own `dispatch_des*` family:
#
#   dispatch_des040  «Это задание выполнено, украсть его невозможно.»
#   dispatch_des041  «Невозможно выполнить: срок задачи истек.»
#   dispatch_des042  «Задание уже взято»
#   dispatch_des043  «Это задание больше не доступно»
#
# All four mean the same thing to us: THERE IS NOTHING THERE ANY MORE. And the family
# holds no «ещё не готово» at all, which is the other half of the finding — an early
# press is answered by silence rather than by a refusal, so «any tip at all» would have
# been a workable rule too. These four are named anyway: a tip we have not met should
# leave the loop pressing, not stop it.
#
# Without this the loop had exactly two stop conditions — the counter moving, and the
# button's cap. Live, that read as `TAP Rob a secret task xall -> 60 press(es)` on one
# tile: sixty questions to a server that had already answered the first one.
STEAL_GONE_TIPS = ("dispatch_des040", "dispatch_des041",
                   "dispatch_des042", "dispatch_des043")

#: Lua that records the tip a refusal raises, so a loop can read the server's answer.
#: Installed once, idempotent, and a pass-through — it takes nothing away from the game.
#:
#: It stamps the tip into a field PER SPAM (#1294): the robbery clears `__lw_steal_tip`
#: when it arms a tile and the star sprint clears `__lw_assist_tip` when it arms a task,
#: so neither can read the other's refusal and stop on it. One hook, two mailboxes —
#: `UIUtil.ShowTipsId` is the game's single tip door and wrapping it twice would leave a
#: shim behind on every re-install.
#:
#: The guard carries a VERSION. A client that has been up since before this change has
#: the one-mailbox hook installed and would never fill `__lw_assist_tip`, so the sprint
#: would read every refusal as silence and press out its whole cap. Bumping the key
#: re-installs over it; the old shim stays in the chain and keeps working.
_TIP_HOOK = (
    "if not M.__lw_tip_hooked_v2 then M.__lw_tip_hooked_v2 = true "
    "local orig = UIUtil.ShowTipsId "
    "UIUtil.ShowTipsId = function(id, ...) "
    "pcall(function() local D=DataCenter.ActDispatchTaskDataManager "
    "D.__lw_steal_tip = tostring(id) D.__lw_assist_tip = tostring(id) end) "
    "return orig(id, ...) end end ")

#: The old name, kept because it reads better where the robbery arms its mark.
_STEAL_TIP_HOOK = _TIP_HOOK

#: …and the expression that reads it back: 1 when the server has said the tile is gone.
_STEAL_GONE = ("(function() local M=DataCenter.ActDispatchTaskDataManager "
               "local t=tostring(M.__lw_steal_tip or '') "
               + " ".join("if t=='%s' then return 1 end" % k for k in STEAL_GONE_TIPS)
               + " return 0 end)()")


def secret_task_gone() -> str:
    """Lua *expression* -> 1 when the server has answered «there is nothing there».

    The third outcome, beside «taken» and «not yet». It is terminal: pressing again is
    asking a question already answered, and the row it belongs to is not a target any
    more — which is why the panel takes it off the list rather than leaving it to say
    «готово к сбору» about a tile somebody else has emptied.
    """
    return _STEAL_GONE


# THE ONLY HONEST «IT WORKED» THERE IS (#1272). A robbery is confirmed by the SERVER
# and by nothing else: `DispatchStealMessage:HandleMessage` takes the error branch on a
# refusal and, on success, hands `UpdateTodayNum` the server's own `todayStealNum` out
# of the reply. Nothing is incremented locally, so the counter moving is the reply
# landing — and a send that got a tip back leaves it exactly where it was.
#
# That is what lets the press be REPEATED. `__lw_steal_mark` is the counter as it stood
# when the head of the queue was armed; while it has not moved, the head has not been
# taken and pressing again is worth doing. It is stamped when the queue is set and
# re-stamped when the head is dropped, so it always belongs to the target being pressed.
_STEAL_MARK = ("M.__lw_steal_mark=tonumber(M:GetTodayStealNum()) or 0 "
               "M.__lw_steal_tip=nil " + _STEAL_TIP_HOOK)


def secret_task_taken() -> str:
    """Lua *expression* -> 1 when the server has confirmed a robbery of the armed head.

    The counter against the mark, and that is the whole test. A `steal_sent` line proves
    a frame left the client; only this proves the server took it.
    """
    return ("(function() local M=DataCenter.ActDispatchTaskDataManager "
            "local now=tonumber(M:GetTodayStealNum()) or 0 "
            "local mark=tonumber(M.__lw_steal_mark) "
            "if mark == nil then return 0 end "
            "if now ~= mark then return 1 end return 0 end)()")


def secret_task_queue_pop() -> str:
    """Drop the head of the queue and re-arm the mark on whatever is now in front.

    Called between targets rather than before a send (which is what
    `steal_next_secret_task` used to do): the head has to survive its own press so that
    the press can be REPEATED until the server answers. A head that was never taken is
    dropped here too — after the spam has spent its cap on it, that tile is gone, taken
    by somebody else, or out of reach, and every one of those means «the next one».

    IT SAYS WHAT HAPPENED, PER TARGET (#1272). `ACT steal_done uuid=<u> how=<…>` — one of
    `taken` (the counter moved: ours), `gone` (the server said there is nothing there:
    the row is not a target any anymore and the panel takes it off the list) or
    `unanswered` (the spam ran out its cap without either: the row stays, because nothing
    said it should not). The verdict is read BEFORE the mark is re-armed, or it would be
    the next target's.
    """
    return ("local M=DataCenter.ActDispatchTaskDataManager "
            "local q=M.__lw_steal_queue or {} local t=table.remove(q,1) "
            "local how='unanswered' "
            "if %s == 1 then how='gone' elseif %s == 1 then how='taken' end "
            "local tip=tostring(M.__lw_steal_tip or '') "
            'CS.UnityEngine.Debug.LogError("ACT steal_done uuid="..tostring(t and t.uuid or 0)'
            '.." how="..how.." tip="..tip) '
            % (secret_task_gone(), secret_task_taken())
            + _STEAL_MARK +
            'CS.UnityEngine.Debug.LogError("ACT steal_queue_pop left="..tostring(#q))')


def secret_task_queue_clear() -> str:
    """Empty the steal queue (a recipe should not inherit yesterday's targets)."""
    return ("local M=DataCenter.ActDispatchTaskDataManager M.__lw_steal_queue={} "
            'CS.UnityEngine.Debug.LogError("ACT steal_queue_cleared")')


def secret_task_queue_len() -> str:
    """Lua *expression* -> how many targets are still queued."""
    return ("(function() local M=DataCenter.ActDispatchTaskDataManager "
            "return #(M.__lw_steal_queue or {}) end)()")


def secret_task_steals_pending() -> str:
    """Lua *expression* -> is the head of the queue still worth pressing? (1 or 0)

    The button's `count_lua`, and it answers a different question since #1272. It used
    to be «how many targets are left», which made `xall` press each of them once; it is
    now «press the SAME one again», and `xall` becomes the spam loop the race needs:

      * there is a head to press,
      * the day's budget is not spent,
      * the server has not confirmed this one yet (`secret_task_taken`),
      * and it has not said the tile is GONE either (`secret_task_gone`) — «задание уже
        взято», «больше не доступно», «срок истёк». That answer is terminal: pressing
        again is asking a question the server has already answered, and it is what turned
        one live press into `xall -> 60 press(es)` against a tile that no longer existed.

    **A tile is pressed BEFORE it matures on purpose.** There is no penalty for it — the
    server answers «ещё не готово», the counter does not move and nothing is spent
    (`DispatchStealMessage:HandleMessage`) — and a raidable star is taken in the first
    instant it exists, so the only way to be first is to be already pressing. The clock
    is deliberately NOT part of this gate: the recipe is played inside the window, and
    what stops the loop is the server saying yes, not our own idea of when it should.
    """
    return ("(function() local q=%s local b=%s local t=%s local g=%s "
            "if q>0 and b>0 and t==0 and g==0 then return 1 end return 0 end)()"
            % (secret_task_queue_len(), secret_task_steals_left(),
               secret_task_taken(), secret_task_gone()))


def steal_next_secret_task() -> str:
    """Rob the head of the queue — and LEAVE IT THERE, so it can be pressed again.

    One press per chunk, as before: `todayStealNum` only moves when the server's reply
    lands, so a `while` inside one chunk would spin the game's main thread and press
    against a stale budget.

    THE HEAD IS NO LONGER DROPPED BEFORE THE SEND (#1272). It used to be, so that a
    refusal cost a queue entry rather than wedging `xall` on a doomed uuid for ever —
    and that made the press a one-shot, which loses every race that is decided in
    fractions of a second. Now the head survives its own press, `count_lua` stops the
    loop the moment the SERVER confirms (`secret_task_taken`), and `max_taps` bounds the
    spam on a tile that will never answer. `secret_task_queue_pop` is what moves on.
    """
    return ("local M=DataCenter.ActDispatchTaskDataManager "
            "local q=M.__lw_steal_queue or {} local t=q[1] "
            "if t and %s > 0 then "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchSteal, t.uuid, t.server) end) "
            'CS.UnityEngine.Debug.LogError("ACT steal_sent uuid="..tostring(t.uuid)'
            '.." srv="..tostring(t.server)) end' % secret_task_steals_left())


# --------------------------------------------------------------------------
# Re-reading the STATE of tiles already on the list — «Обновить состояние» (#1272)
# --------------------------------------------------------------------------
# A different question from every read above, and the one nothing could answer. The
# alliance table (`secret_task_all_alliance`) knows only MY alliance's tasks — live: 189
# of them, none starred, all at home — so it cannot say a word about the strangers' tiles
# the map capture found, which is the whole of the ★ list. The capture only re-sees a
# tile when the map is driven over it again. Between those, a row went on saying «готово
# к сбору» about a tile somebody had emptied minutes ago.
#
# The per-tile authority is the one a marker tap uses: `world.get.detail.new`, keyed by
# pointId, answered into `WorldPointDetailManager` and readable by pointId afterwards.
# Measured live: a real tile answers with a 45-field record carrying `uuid`, `uid`,
# `serverId` and `expireTime`; **a point with no task on it answers with no detail at
# all** — `GetDetailByPointId` stays nil.
#
# WHICH MAKES «NIL» AMBIGUOUS ON ITS OWN, and that is the trap this task has already
# been caught by once (#1272, `_answerable`): a reply that never arrived looks exactly
# like «there is nothing there». So the probe sends a CONTROL point along with the batch
# — a tile the client itself says exists — and the reader reports whether that one came
# back. Without the control answering, a nil says nothing and no row is dropped.
#
# AND THE CONTROL HAS TO BE A POINT THAT IS NOT ALREADY ANSWERED (#1476). The detail
# cache is not emptied between runs: `worldPointDetailList` holds every point the client
# has ever had a detail for — 104 of them on the live profile that reported this — so a
# control picked blindly off `allianceTask` is very often one whose answer has been
# sitting there since some earlier tap. It then reads `ok=1` whatever the link is doing,
# and every silent tile in the batch is scored as «the server says it is gone». That is
# not a theory: 709 «состояние перечитано» lines in one profile's log, over ten days,
# and «исчезло» was EQUAL to «проверено» in every single one of them while «обновлено»
# was never once above nought. Measured on the same client: of 125 of the account's OWN
# alliance tasks exactly 2 had a cached detail, and a fresh `world.get.detail.new` for
# the other three sampled added nothing in eight seconds — yet the control answered, so
# all three would have been deleted.
#
# So the control is picked as the first alliance task the cache has NO answer for. Then
# `ok=1` can only mean a reply arrived DURING THIS RUN, which is the only thing it was
# ever supposed to mean. When every alliance task already has one — nothing left to prove
# arrival with — the probe sends no control at all and the reader says `ok=0`, which is
# «I cannot tell» and takes no row off the list.
#
# What the detail does NOT carry is the loot count: `stealInfoList` is not in it, so
# «сколько раз уже ограбили» still comes from the alliance table for the tiles it covers
# and from the capture for the rest.

def secret_task_detail_probe(tiles, control=None) -> str:
    """Ask the server about each `(x, y, server)` tile — plus a control point.

    The tile index is computed in the VM (`SceneUtils.TilePosToIndex`), so nothing out
    here has to know how a coordinate is packed into a pointId. The list is parked in
    order; :func:`secret_task_detail_read` reports back BY THAT ORDER, which is what lets
    a caller line the answers up with its own rows without re-deriving anything.

    Fire and forget: the replies land on their own and are read after a settle, never in
    this chunk.
    """
    items = ",".join(
        "{x=%d,y=%d,s=%d}" % (int(x), int(y), int(srv)) for x, y, srv in tiles)
    # The control is picked in the VM when the caller does not name one: the client's own
    # alliance table is a list of tiles it is sure exist, and one of them answering is
    # what turns «no detail» from «I heard nothing» into «there is nothing there».
    #
    # …and it is the first one the DETAIL CACHE cannot already answer (#1476), because a
    # point that is already answered proves nothing about this run — see the note above.
    ctrl = (("{p=%d,s=%d}" % (int(control[0]), int(control[1]))) if control else
            "(function() local D=DataCenter.WorldPointDetailManager "
            "for _, v in pairs(DataCenter.ActDispatchTaskDataManager"
            ".allianceTask or {}) do "
            "local d = D:GetDetailByPointId(v.pointId) "
            "if not (d and (tonumber(d.uuid) or 0) > 0) then "
            "return {p=v.pointId, s=v.targetServer} end end "
            "return nil end)()")
    return ("local M=DataCenter.ActDispatchTaskDataManager "
            "M.__lw_detail_ask={} M.__lw_detail_ctrl=%s "
            "for _, it in ipairs({%s}) do "
            "local pid = SceneUtils.TilePosToIndex(CS.UnityEngine.Vector2Int(it.x, it.y)) "
            "M.__lw_detail_ask[#M.__lw_detail_ask+1] = {p=pid, s=it.s} "
            "pcall(function() SFSNetwork.SendMessage('world.get.detail.new', pid, it.s, 0, %d, '') end) "
            "end "
            "if M.__lw_detail_ctrl then pcall(function() "
            "SFSNetwork.SendMessage('world.get.detail.new', M.__lw_detail_ctrl.p, "
            "M.__lw_detail_ctrl.s, 0, %d, '') end) end "
            'CS.UnityEngine.Debug.LogError("ACT detail_asked "..tostring(#M.__lw_detail_ask))'
            % (ctrl, items, SECRET_TASK_POINT_TYPE, SECRET_TASK_POINT_TYPE))


def secret_task_detail_read() -> str:
    """Emit what came back: one `ACT DT …` per asked tile, in order, and the control.

    `DT i=<n> uuid=<u> expire=<ms>` — `uuid=0` means no detail at all, which is what a
    point with no task on it answers (measured live). `DT_CONTROL ok=<0|1>` is whether
    the tile we KNOW exists answered, and it is the difference between «there is nothing
    there» and «nothing came back»: without it a silent link reads as an empty map, which
    is how a list gets deleted for a fault of its own connection (#1272).
    """
    return ("local M=DataCenter.ActDispatchTaskDataManager "
            "local D=DataCenter.WorldPointDetailManager "
            "for i, it in ipairs(M.__lw_detail_ask or {}) do "
            "local d = D:GetDetailByPointId(it.p) "
            'CS.UnityEngine.Debug.LogError("ACT DT i="..tostring(i)'
            '.." uuid="..tostring((d and d.uuid) or 0)'
            '.." expire="..tostring((d and d.expireTime) or 0)) end '
            "local ok = 0 "
            "if M.__lw_detail_ctrl then "
            "local c = D:GetDetailByPointId(M.__lw_detail_ctrl.p) "
            "if c and (tonumber(c.uuid) or 0) > 0 then ok = 1 end end "
            'CS.UnityEngine.Debug.LogError("ACT DT_CONTROL ok="..tostring(ok))')


# The clock the client draws its OWN countdowns with, in milliseconds, as a Lua
# statement that leaves it in a local called `nowms`.
#
# `UITimeManager.Instance:GetServerTime()` is the one to ask, and it is not a
# guess: `ActDispatchTaskDataManager.RefreshCompleteTimer`, string-dumped out of
# the live VM, computes its countdown as `completionTime` minus a `curTime` taken
# from exactly this manager (task #1227). It is the server's clock kept as an
# offset from the device's — `self.serverDeltaTime` — so it does NOT move with the
# PC's own time.
#
# `ChatInterface.getServerTime()` is the fallback, the same clock in whole
# seconds. Measured together they agree to the second (…337743 ms vs …337 s), so
# the fallback costs precision and nothing else.
_SERVER_NOW_MS = (
    'local nowms = 0 '
    'pcall(function() nowms = UITimeManager.Instance:GetServerTime() end) '
    'nowms = math.floor(tonumber(nowms) or 0) '
    'if nowms <= 0 then nowms = (tonumber(ChatInterface.getServerTime()) or 0) * 1000 end ')


def game_server_time() -> str:
    """Emit the game's own clock, in milliseconds — `ACT NOWMS=<ms>`.

    This is the clock every timestamp the game hands out is stamped on, and it is
    the one the client's own countdowns are drawn against — so anything asking
    «how long until this tile is raidable» or «has the dispatch finished yet» has
    to be judged by it rather than by the PC's clock. The two are not the same:
    the machine this was written on ran eleven seconds SLOW against real UTC, and
    the operator was reading 25-30 s of that on the tab (task #1227).

    `tools/lib/game_clock.py` keeps the difference; this is the read.
    """
    return (_SERVER_NOW_MS
            + 'CS.UnityEngine.Debug.LogError("ACT NOWMS="..tostring(nowms))')


# --------------------------------------------------------------------------
# Helping an alliancemate's secret task — `hero.dispatch.assist`
# --------------------------------------------------------------------------
# A THIRD thing, and not the alliance «Помочь всем» (#1272). `al.help.all`
# answers building/research requests and is unlimited; this answers the alliance's
# own FINISHED hero-dispatch tasks, costs one of five a day, and is what the daily
# plan means by «помочь выполнить 5 секретных заданий ранга UR или Звезда».
#
#     --> hero.dispatch.assist   {uuid: long, targetServer: int}
#     <-- hero.dispatch.assist   {errorCode | reward[], …}
#
# Read out of the live client (docs/research/secret-task-assist.md):
#
#   * the press is `DispatchTaskItem:OnGoClick` — one
#     `SFSNetwork.SendMessage(MsgDefines.DispatchAssist, infos.uuid, infos.targetServer)`
#     behind a `GetTodayAssistNum() < GetDispatchSetting("aid_count")` gate;
#   * the message class puts exactly those two fields on the wire
#     (`DispatchAssistMessage:OnCreate` — `PutLong(uuid)`, `PutInt(targetServer)`),
#     so it is headless: no window, no marker tap, no camera move;
#   * a task is helpable while it is FINISHED and unrewarded, which is precisely
#     what `GetAllianceAssisTaskCount()` counts (72 = the finished tasks, live).
#
# THE LIST GOES STALE AND THAT IS THE WHOLE TRAP. The client only learns that a
# task has been helped by somebody else when a push tells it, and a headless bot
# has no window open to ask. Sending against a stale entry is answered with
# `dispatch_des028` — «Спасибо, но задача уже решена с помощью других лиц» — and
# `todayAssistNum` does not move, so it reads exactly like a bot that pressed
# nothing. Live, the first two attempts failed that way and the third, sent right
# after `GetAllAllianceTasksFromServer()`, took the counter 0 -> 1.

def secret_task_assists_left() -> str:
    """Lua *expression* -> helps the account may still send today.

    `GetDispatchSetting("aid_count")` is the daily cap (5 on the live account) and
    `GetTodayAssistNum()` what has been spent. The same shape as
    `secret_task_steals_left`, and a DIFFERENT budget: robbing and helping have a cap
    each, and spending one does not touch the other.
    """
    return ("(function() local M=DataCenter.ActDispatchTaskDataManager "
            "local cap=tonumber(M:GetDispatchSetting('aid_count')) or 0 "
            "local used=tonumber(M:GetTodayAssistNum()) or 0 "
            "local left=cap-used if left<0 then left=0 end return left end)()")


def secret_task_assist_refresh() -> str:
    """Ask the server for the alliance's task list again — `hero.dispatch.alliance.list`.

    The first half of every help, and not optional (see the block above): the local copy
    keeps tasks other people have already helped with, and the server refuses those with
    a tip rather than with anything the budget records. Fire-and-forget — the reply lands
    on its own thread, so a caller reads the list AFTER a settle, never in this chunk.
    """
    return ('pcall(function() DataCenter.ActDispatchTaskDataManager'
            ':GetAllAllianceTasksFromServer() end) '
            'CS.UnityEngine.Debug.LogError("ACT assist_list_requested")')


def secret_task_assist_rule(level_min: int, star_wait_min: int = 0) -> str:
    """Park the help rule in the VM: the lowest level, and how long a star is worth.

    `TAP` takes no arguments, so the rule cannot travel with the press — it is left on
    the dispatch manager's own table, the same place the robbery queue lives, because
    this VM rejects some new globals. The RANK half of the rule is not a setting: only
    the top two ranks are ever helped, and a star always outranks a UR
    (see :data:`_ASSIST_SCAN`).

    `star_wait_min` is the second half of the priority: the longest a ripening star may
    hold one of the day's five back. `0` means «hold for any star that can ripen at all
    today» — the bound then comes from the task's own expiry and the daily reset alone.
    """
    return ("local M=DataCenter.ActDispatchTaskDataManager M.__lw_assist_level=%d "
            "M.__lw_assist_wait_ms=%d "
            'CS.UnityEngine.Debug.LogError("ACT assist_rule level="..tostring(%d)'
            '.." star_wait_min="..tostring(%d))'
            % (int(level_min), int(star_wait_min) * 60000,
               int(level_min), int(star_wait_min)))


#: When the day the daily counters belong to rolls over, in ms past midnight UTC.
#:
#: 02:00 UTC, measured rather than assumed: 597 of 636 secret-task tiles in one capture
#: shared a single expiry of 01:59:59 UTC and the rest fell on adjacent days
#: (`docs/research/protocol.md`, «Expiry is a daily reset»), and the treasure activity's
#: own `expire` landed on the same boundary (`docs/research/world-treasures.md`). It is
#: what «до конца дня» means for a help that has to be spent before the five come back.
_DAY_RESET_MS = 2 * 3600 * 1000

#: One walk over `allianceTask`, leaving the whole decision in locals (#1292).
#:
#: What it leaves behind, all judged on the GAME's clock and on the task's own config row
#: (`lw_dispatch_tasks` through `v.cfg` — never the cfgId's digits, #1267):
#:
#:   * `sready` / `uready` — helpable NOW: finished, unrewarded, unexpired, at or above
#:     the parked level. A star counts as a star even when it is also `color = 5`;
#:   * `bstar` / `bur` — the best of each, highest level first;
#:   * `spend` — starred tasks still COUNTING DOWN that can still be helped today, with
#:     `seta` the wait to the nearest of them, `slvl` its level and `bnext` the task
#:     itself. Each one holds back one of the day's helps;
#:   * `slate` — starred tasks that cannot make it: they ripen after their own
#:     `actEndTime`, after the daily reset, or after the parked wait bound. Waiting for
#:     one of those spends nothing and gains nothing, so they are counted and said out
#:     loud rather than silently waited on;
#:   * `left` — helps still in today's budget;
#:   * `best` — what a press would take: a ready star always, and a ready UR only while
#:     there are more helps left than there are stars worth waiting for.
#:
#: THE PRIORITY IS THE POINT. «Звезда в приоритете, UR только если звёзд нет» (#1292):
#: the old rank was `lvl*2+spec`, so a level-7 UR beat a level-6 star and the star was
#: gone by the time it mattered. A star is rare — one alliance task in two hundred
#: carried `is_special = 1` against 34 finished URs (#1272) — which is exactly why the
#: budget waits for one rather than racing it, and exactly why the wait needs a floor
#: under it: 34 URs sitting unspent all day is the other way to waste the five.
_ASSIST_SCAN = (
    "local M=DataCenter.ActDispatchTaskDataManager "
    + _SERVER_NOW_MS +
    "local now=nowms local low=tonumber(M.__lw_assist_level) or 0 "
    "local wait=tonumber(M.__lw_assist_wait_ms) or 0 "
    "local left=" + secret_task_assists_left() + " "
    # The next boundary the daily counters roll over on, on the game's own clock.
    + ("local dayend=(math.floor((now-%d)/86400000)+1)*86400000+%d "
       % (_DAY_RESET_MS, _DAY_RESET_MS)) +
    "local sready,uready,spend,seta,slvl,slate=0,0,0,-1,0,0 "
    "local bstar,bsrank,bur,burank,bnext=nil,-1,nil,-1,nil "
    "for _,v in pairs(M.allianceTask or {}) do "
    "local done=tonumber(v.completionTime) or 0 "
    "local rewarded=tonumber(v.rewarded) or 0 "
    "local exp=tonumber(v.actEndTime) or 0 "
    "local lvl,spec,colour=0,0,0 "
    "pcall(function() lvl=tonumber(v.cfg:getValue('level')) or 0 "
    "spec=tonumber(v.cfg:getValue('is_special')) or 0 "
    "colour=tonumber(v.cfg:getValue('color')) or 0 end) "
    "if done>0 and rewarded==0 and (exp==0 or now<exp) and lvl>=low then "
    "if done<=now then "
    "if spec==1 then sready=sready+1 "
    "if lvl>bsrank then bstar,bsrank=v,lvl end "
    "elseif colour>=5 then uready=uready+1 "
    "if lvl>burank then bur,burank=v,lvl end end "
    "elseif spec==1 then "
    "local lim=dayend if exp>0 and exp<lim then lim=exp end "
    "if done<lim and (wait<=0 or done-now<=wait) then spend=spend+1 "
    "if seta<0 or done-now<seta then seta=done-now slvl=lvl bnext=v end "
    "else slate=slate+1 end "
    "end end end "
    "local best=bstar if best==nil and left-spend>0 then best=bur end ")


def secret_task_assist_scan() -> str:
    """Walk the alliance list once and park the reading the recipe branches on.

    A snapshot rather than seven separate reads: the recipe asks six questions of it
    («is a star ready», «is one coming», «how long», «what level», «has one run out of
    day», «is there a UR at all») and they must all be answers to the SAME walk — a star
    that ripens between two reads would otherwise be waited for and helped in the same
    breath, or neither.

    Each answer is parked as a PLAIN NUMBER of its own on the dispatch manager — the
    same table the level and the robbery queue already live on — so the recipe reads one
    with `(tonumber(…__lw_star_left) or 0)` and a scan that never ran reads as zero
    rather than as a nil index that would fail the run. `__lw_star_eta` is in MINUTES,
    rounded up, and `-1` when there is no star to wait for: «готова через 0 минут» about
    a star forty seconds away is the kind of countdown #1227 was about.

    `__lw_star_eta_sec` IS THE SAME WAIT IN SECONDS, and it is what the sprint is
    scheduled off (#1294). A star matures at a moment the client already knows to the
    millisecond — `completionTime` is on the task — so nothing has to poll to DISCOVER
    readiness; the only question is being there when it arrives. Rounded DOWN, so the
    schedule lands a shade early rather than a shade late, and `-1` for «no star coming»
    exactly as the minutes are.

    Says what it saw on the way past — `ACT assist_scan star_ready=… ur_ready=…
    star_pending=… star_eta_min=… star_eta_sec=… star_lvl=… star_late=… left=…` — so the
    decision below it can be read back out of a log without re-asking the game.
    """
    return ("pcall(function() " + _ASSIST_SCAN +
            "local etamin=-1 if seta>=0 then etamin=math.ceil(seta/60000) end "
            "local etasec=-1 if seta>=0 then etasec=math.floor(seta/1000) end "
            # What is actually being HELD, which is not the same as how many stars are
            # coming: three ripening stars hold nothing at all out of a spent budget,
            # and a recipe that says «придерживаю 3 из 0» is reporting arithmetic
            # rather than the day (#1292, seen live).
            "local hold=spend if hold>left then hold=left end "
            "M.__lw_star_ready=sready M.__lw_star_ur=uready M.__lw_star_pending=spend "
            "M.__lw_star_eta=etamin M.__lw_star_level=slvl M.__lw_star_late=slate "
            "M.__lw_star_left=left M.__lw_star_hold=hold M.__lw_star_eta_sec=etasec "
            'CS.UnityEngine.Debug.LogError("ACT assist_scan star_ready="..tostring(sready)'
            '.." ur_ready="..tostring(uready).." star_pending="..tostring(spend)'
            '.." star_eta_min="..tostring(etamin).." star_eta_sec="..tostring(etasec)'
            '.." star_lvl="..tostring(slvl)'
            '.." star_late="..tostring(slate).." left="..tostring(left)'
            '.." hold="..tostring(hold)) end)')


def secret_task_star_field(name: str) -> str:
    """Lua *expression* -> one number :func:`secret_task_assist_scan` parked.

    `ready` / `ur` / `pending` / `eta` / `eta_sec` / `level` / `late` / `left` / `hold`.
    Zero when nothing has been scanned yet, which is the honest answer for a recipe that
    has not looked: no star ready, no star coming, nothing to hold back.
    """
    return ("(tonumber(DataCenter.ActDispatchTaskDataManager.__lw_star_%s) or 0)" % name)


def secret_task_assists_pending() -> str:
    """Lua *expression* -> presses `assist_secret_task` can still make.

    The button's `count_lua`, re-read by `xall` between presses, and where the priority
    is actually SPENT rather than merely described:

        ready stars, up to the budget
      + ready URs, but only into what is left AFTER one help is set aside for every
        star still ripening today

    So five helps and two ripening stars buy three URs now and keep two in hand; five
    helps and five ripening stars buy nothing at all and say so. A star that cannot
    ripen in time was never counted into `spend`, so it holds nothing back.
    """
    return ("(function() %s "
            "local n=sready if n>left then n=left end "
            "local room=left-n-spend "
            "if room>0 then local u=uready if u>room then u=room end n=n+u end "
            "return n end)()" % _ASSIST_SCAN)


def assist_next_secret_task() -> str:
    """Help the best matching alliance task — one press, one `hero.dispatch.assist`.

    `best` is a ready star when there is one and a ready UR only when the reserve allows
    it (:data:`_ASSIST_SCAN`), so the press cannot spend on a UR what the count above is
    holding for a star.

    The chosen task is dropped from the LOCAL list before the send
    (`DeleteAllianceTasks`, which is what the reply's own handler does on success). That
    is what keeps `xall` moving: a refusal («уже решена с помощью других лиц») leaves the
    budget untouched, so a press that did not drop its target would pick the same doomed
    uuid on every round until the loop's cap. It costs nothing to drop — the next
    `hero.dispatch.alliance.list` brings back whatever is still real.
    """
    return (_ASSIST_SCAN +
            "if best and left > 0 then local u,s=best.uuid,best.targetServer "
            "pcall(function() M:DeleteAllianceTasks(u) end) "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchAssist, u, s) end) "
            'CS.UnityEngine.Debug.LogError("ACT assist_sent uuid="..tostring(u)'
            '.." srv="..tostring(s)) end')


# --------------------------------------------------------------------------
# The star sprint — being there in the second the star matures (#1294)
# --------------------------------------------------------------------------
# WHAT WAS MEASURED. Live acceptance of #1292 caught the whole problem in one reading:
# the day's only ripe star was gone from the alliance list in UNDER TWO MINUTES, taken by
# alliancemates, and `star_ready` never once read non-zero. The reserve had done its job
# — a help was being held — and the help was still not spent, because a look every five
# minutes cannot land inside a two-minute window. Waiting for a star and then arriving
# late loses twice: the URs went unspent too.
#
# THE CLOCK IS ALREADY IN THE CLIENT'S HAND, and that is what makes this cheap. A task
# carries `completionTime`, so the moment it matures is known to the millisecond as soon
# as the ordinary five-minute poll has seen it — live, three level-7 stars announced
# themselves 78, 79 and 233 minutes ahead. Nothing has to poll faster to DISCOVER
# readiness. What is needed is to be pressing when it arrives, which is one scheduled
# wake-up and a few seconds of spam — not a shorter period all day.
#
# SO IT IS THE ROBBERY'S SHAPE, aimed at a moment instead of at a tile (#1272): arm the
# target a couple of seconds early, press as fast as the channel allows, and stop on the
# SERVER — the daily counter moving, or a tip that says the task is not there any more.
#
# PRESSING EARLY IS FREE, on the same evidence the robbery rests on.
# `DispatchAssistMessage:HandleMessage` takes the `errorCode` branch on a refusal and
# raises a tip; `todayAssistNum` is only ever set from the SUCCESS branch, out of the
# server's own reply (docs/research/secret-task-assist.md). A press against a task that
# has not finished yet therefore spends nothing — exactly as a robbery a second too early
# does — so the loop may start before the countdown ends and let the server decide when
# «yes» begins.

#: Tips that mean «this task cannot be helped any more» — terminal for the sprint.
#:
#: `dispatch_des028` is the one that cost two of the day's five before it was understood
#: («Спасибо, но задача уже решена с помощью других лиц»), and it is the exact answer a
#: LOST race gives: somebody else got there first. `dispatch_des041` is the task's own
#: expiry. Anything else the server says leaves the loop pressing, for the reason the
#: robbery's list gives: a tip we have not met before must not be read as a refusal.
ASSIST_GONE_TIPS = ("dispatch_des028", "dispatch_des041")

#: 1 when the server has said the armed task is not helpable any more.
_ASSIST_GONE = ("(function() local M=DataCenter.ActDispatchTaskDataManager "
                "local t=tostring(M.__lw_assist_tip or '') "
                + " ".join("if t=='%s' then return 1 end" % k for k in ASSIST_GONE_TIPS)
                + " return 0 end)()")


def secret_task_assist_gone() -> str:
    """Lua *expression* -> 1 when the server has refused the armed task terminally."""
    return _ASSIST_GONE


def secret_task_assist_taken() -> str:
    """Lua *expression* -> 1 when the server has confirmed a help of the armed task.

    `todayAssistNum` against the mark stamped when the target was armed, and that is the
    whole test — the counter reaches the client only on the reply's success branch, so a
    `assist_sprint_sent` line proves a frame left and nothing more.
    """
    return ("(function() local M=DataCenter.ActDispatchTaskDataManager "
            "local now=tonumber(M:GetTodayAssistNum()) or 0 "
            "local mark=tonumber(M.__lw_assist_mark) "
            "if mark == nil then return 0 end "
            "if now ~= mark then return 1 end return 0 end)()")


def secret_task_assist_sprint_arm() -> str:
    """Choose the star to sprint at, stamp the baseline, and open the window.

    The target is the ready star if the scan found one and otherwise the NEAREST RIPENING
    one — the sprint is played a couple of seconds early on purpose, so at arming time the
    star it is aimed at usually has not matured yet. Only a star: a UR is not worth a spam
    loop (thirty-four of them sat unhelped in one live reading) and the ordinary recipe
    spends those at its own pace.

    Parks `__lw_assist_target` (uuid + server, and the level for the log), the counter
    mark the presses are judged against, a fresh tip mailbox and the deadline the loop
    stops at. Says `ACT assist_armed lvl=… eta_sec=… window=…`, or `ACT assist_armed
    none` when the scan found no star at all — a sprint with nothing to press must say so
    rather than look like a silent success.

    How wide the window is comes off `__lw_assist_window_ms`, parked by the recipe from
    its own `ARGS` a line earlier, because a `TAP` carries no arguments. Twenty seconds
    when nothing has parked one.
    """
    return (_ASSIST_SCAN +
            "local t=bstar or bnext "
            "M.__lw_assist_tip=nil "
            "M.__lw_assist_mark=tonumber(M:GetTodayAssistNum()) or 0 "
            "M.__lw_assist_presses=0 "
            "local win=tonumber(M.__lw_assist_window_ms) or 20000 "
            "M.__lw_assist_deadline=now+win "
            "if t==nil or left<=0 then M.__lw_assist_target=nil "
            'CS.UnityEngine.Debug.LogError("ACT assist_armed none left="..tostring(left)) '
            "else local eta=0 local d=tonumber(t.completionTime) or 0 "
            "if d>now then eta=math.floor((d-now)/1000) end "
            "local lvl=0 pcall(function() lvl=tonumber(t.cfg:getValue('level')) or 0 end) "
            "M.__lw_assist_target={uuid=t.uuid,server=t.targetServer,level=lvl} "
            'CS.UnityEngine.Debug.LogError("ACT assist_armed lvl="..tostring(lvl)'
            '.." eta_sec="..tostring(eta).." window="..tostring(math.floor(win/1000))'
            '.." left="..tostring(left)) end ' + _TIP_HOOK)


def secret_task_assist_sprint_pending() -> str:
    """Lua *expression* -> is the armed star still worth pressing again? (1 or 0)

    The sprint's `count_lua`, and the same four questions the robbery's asks: there is a
    target, the day's budget is not spent, the server has not confirmed this one, and it
    has not said the task is gone. Plus the one the robbery does not need — the window,
    because a star that never matures (a mate who cancelled, a clock that was wrong)
    would otherwise be pressed until the button's cap every single time.
    """
    return ("(function() local M=DataCenter.ActDispatchTaskDataManager "
            "if M.__lw_assist_target==nil then return 0 end "
            + _SERVER_NOW_MS +
            "local dl=tonumber(M.__lw_assist_deadline) or 0 "
            "if dl>0 and nowms>dl then return 0 end "
            "local b=%s local t=%s local g=%s "
            "if b>0 and t==0 and g==0 then return 1 end return 0 end)()"
            % (secret_task_assists_left(), secret_task_assist_taken(),
               secret_task_assist_gone()))


def secret_task_assist_sprint_press() -> str:
    """Press the armed star once — one `hero.dispatch.assist`, and LEAVE IT ARMED.

    The opposite of :func:`assist_next_secret_task`, which drops its target from the local
    list before sending so that `xall` moves on. Here the target has to survive its own
    press, because pressing it AGAIN is the entire point: the loop ends when the server
    answers, not when the client has asked once.
    """
    return ("local M=DataCenter.ActDispatchTaskDataManager "
            "local t=M.__lw_assist_target "
            "if t and %s > 0 then "
            "M.__lw_assist_presses=(tonumber(M.__lw_assist_presses) or 0)+1 "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.DispatchAssist, "
            "t.uuid, t.server) end) "
            'CS.UnityEngine.Debug.LogError("ACT assist_sprint_sent n="'
            '..tostring(M.__lw_assist_presses)) end' % secret_task_assists_left())


def secret_task_assist_sprint_verdict() -> str:
    """Say what the sprint did, disarm, and leave the numbers a measurement needs.

    `ACT assist_sprint_done how=<taken|gone|unanswered> lvl=<n> presses=<n> tip=<id>` —
    the same three outcomes the robbery reports per target, for the same reason: «took
    it», «somebody else did» and «the server never answered» are three different days and
    they look identical in a log that only says the spam ended.

    `presses` is the measurement the task asked for (#1294): how many attempts a taken
    star costs, and how many a lost one burns.
    """
    return ("local M=DataCenter.ActDispatchTaskDataManager "
            "local t=M.__lw_assist_target local how='unanswered' "
            "if %s == 1 then how='taken' elseif %s == 1 then how='gone' end "
            "local lvl=0 if t then lvl=tonumber(t.level) or 0 end "
            'CS.UnityEngine.Debug.LogError("ACT assist_sprint_done how="..how'
            '.." lvl="..tostring(lvl)'
            '.." presses="..tostring(tonumber(M.__lw_assist_presses) or 0)'
            '.." tip="..tostring(M.__lw_assist_tip or "")) '
            "M.__lw_assist_target=nil"
            % (secret_task_assist_taken(), secret_task_assist_gone()))


def dispatch_task_cfg_rank(cfg_ids) -> str:
    """Emit `ACT CFG cfg=<id> lvl=<n> spec=<0|1>` for each secret-task TEMPLATE id.

    The game's own `lw_dispatch_tasks` row, asked for a bare cfgId — with no live task
    record to hang it off. Every other reader in this repo reaches `level` /
    `is_special` through `v.cfg`, the row already attached to an entry in `allianceTask`
    / `singleTask`, so a tile that came off a PCAP had nothing to ask and fell back to
    the digits — which call a `60009903` template «level 99, starred» where the game
    calls it «level 7, not starred» (#1267). That fallback is fine for a decoder with no
    client in the room; it is not fine for the thing that spends one of five raids a day
    (#1188), and the panel and the tool both have a client.

    `LocalController.instance` is a FUNCTION and not a field — `instance:getLine(…)`
    raises «attempt to index a function value». The path was read out of the bytecode of
    `ActDispatchTaskDataManager:UpdateOneAllianceTask` (`string.dump`, then its string
    constants in order), which is the method that attaches `cfg` to a task in the first
    place; it is written up in docs/research/secret-task-steal.md §6c.

    A template the client has no row for emits `lvl=0 spec=0`, which `proto.task_rank`
    already reads as «the config said nothing» and answers from the digits — so an
    unknown id degrades to exactly the behaviour there was before, never to a silent
    «not starred».
    """
    ids = ",".join(str(int(c)) for c in cfg_ids)
    return (
        'pcall(function() '
        'for _, cfg in ipairs({%s}) do '
        'local lvl, spec = 0, 0 '
        'pcall(function() '
        'local row = LocalController.instance():getLine(TableName.LwDispatchTask, cfg) '
        'lvl = tonumber(row:getValue("level")) or 0 '
        'spec = tonumber(row:getValue("is_special")) or 0 end) '
        'CS.UnityEngine.Debug.LogError("ACT CFG cfg="..tostring(cfg)'
        '.." lvl="..tostring(lvl).." spec="..tostring(spec)) '
        'end end)' % ids)


#: The last line both alliance reads print — the sentinel that ends the wait for
#: them (#1272). They are the panel's most frequent reads and a flat settle was what
#: they cost: 1.1 s per ready-row poll and per «Обновить состояние», with the daemon's
#: lock held for all of it, so every other call queued behind a read that had already
#: answered. `early` cannot help here — a hundred `Debug.LogError` lines do not always
#: land inside the quiet window it guesses by, so cutting the wait short truncated the
#: list. A last line of its own removes the guess (`lua_eval.collect`).
VT_END = "VT_END"


def secret_task_raidable_alliance() -> str:
    """Emit every alliance secret task that is raidable *right now*, straight from the VM.

    The client already keeps a parsed, always-current copy of the alliance's hero
    dispatch tasks in `ActDispatchTaskDataManager.allianceTask` (see
    project_secret_task_list) — the same list a member's shared secret task lands in
    the instant the push arrives. Reading it needs no pcap and no map panning, so a
    tile is knowable the moment the game knows it rather than whenever the sweep next
    pans over it. That is what lets the auto-loot react in a second or two instead of
    waiting out a capture tick.

    Only the tasks that pass the raid gate are emitted — dispatch finished
    (`completionTime` set and not in the future), not expired (`actEndTime` ahead), and
    a free loot slot (`#stealInfoList < 3`) — so the output is the handful of currently
    lootable tiles, not the whole 100+ row table. Each line carries what a steal target
    needs: `uuid`, `cfgId` (level + star split off it in Python), `srv` (targetServer),
    the tile `x`/`y` for the label, and the loot count. The per-tile conditions the
    server owns (my own past loots, the protect window, sector range) stay its call, the
    same as every other route into `hero.dispatch.steal`.

    Marker-tagged `ACT VT …` lines, one per raidable task; parsed by
    `steal_secret_task._vm_raidable_tasks`.
    """
    return (
        'pcall(function() '
        'local m = DataCenter.ActDispatchTaskDataManager '
        + _SERVER_NOW_MS +
        'local now = nowms local n = 0 '
        'CS.UnityEngine.Debug.LogError("ACT NOWMS="..tostring(nowms)) '
        'for _, v in pairs(m.allianceTask or {}) do '
        'local done = tonumber(v.completionTime) or 0 '
        'local exp = tonumber(v.actEndTime) or 0 '
        'local steals = #(v.stealInfoList or {}) '
        'if done > 0 and done <= now and (exp == 0 or now < exp) and steals < 3 then '
        'n = n + 1 '
        'local x, y = 0, 0 '
        'pcall(function() local tp = SceneUtils.IndexToTilePos(v.pointId) x, y = tp.x, tp.y end) '
        # The task's OWN config row — `lw_dispatch_tasks`, by column name, exactly
        # as `dispatch_tasks._DUMP_LUA` reads it. Without these two the parser has
        # only the cfgId's digits, which call a level-7 tile «level 99» (#1267).
        'local lvl, spec = 0, 0 '
        'pcall(function() lvl = tonumber(v.cfg:getValue("level")) or 0 '
        'spec = tonumber(v.cfg:getValue("is_special")) or 0 end) '
        'CS.UnityEngine.Debug.LogError("ACT VT uuid="..tostring(v.uuid)'
        '.." cfg="..tostring(v.cfgId).." srv="..tostring(v.targetServer)'
        '.." x="..tostring(x).." y="..tostring(y).." steals="..tostring(steals)'
        '.." lvl="..tostring(lvl).." spec="..tostring(spec)'
        '.." done="..tostring(done).." exp="..tostring(exp)) '
        'end end '
        'CS.UnityEngine.Debug.LogError("ACT %s n="..tostring(n)) end)'
        % VT_END)


def secret_task_all_alliance() -> str:
    """Emit every *live* alliance secret task, whether its dispatch is done yet or not.

    A wider read than `secret_task_raidable_alliance`: the raid gate here keeps the
    tile on the map (not expired, `actEndTime` ahead) and a loot slot free
    (`#stealInfoList < 3`), but does NOT require the dispatch to have finished
    (`completionTime <= now`). So the output also carries the tasks still counting down
    to raidability — what the «Secret Tasks» tab needs to show a per-tile timer «готово
    через …» and then flip a row to raidable the moment its clock runs out.

    Same `ACT VT …` line shape as the raidable read, so both parse through
    `steal_secret_task._parse_vt_lines`; `completionTime` (`done`) tells the two states
    apart on the Python side. `completionTime` must be set (`> 0`) — a tile with no
    finish time has no countdown to draw.

    IT ENDS BY SAYING SO — `ACT VT_END n=<lines>` (#1272). The read is the panel's most
    frequent one (every ready-row poll, every «Обновить состояние») and it used to be paid
    for with a flat 1.1 s settle, because there was no way to know the answer was
    complete: a hundred `Debug.LogError` lines do not always land inside the 20 ms quiet
    window `early` guesses by, so cutting the wait short truncated the list. A last line
    of its own removes the guess — see :data:`VT_END` and `lua_eval.collect`.
    """
    return (
        'pcall(function() '
        'local m = DataCenter.ActDispatchTaskDataManager '
        + _SERVER_NOW_MS +
        'local now = nowms local n = 0 '
        'CS.UnityEngine.Debug.LogError("ACT NOWMS="..tostring(nowms)) '
        'for _, v in pairs(m.allianceTask or {}) do '
        'local done = tonumber(v.completionTime) or 0 '
        'local exp = tonumber(v.actEndTime) or 0 '
        'local steals = #(v.stealInfoList or {}) '
        'if done > 0 and (exp == 0 or now < exp) and steals < 3 then '
        'n = n + 1 '
        'local x, y = 0, 0 '
        'pcall(function() local tp = SceneUtils.IndexToTilePos(v.pointId) x, y = tp.x, tp.y end) '
        # The task's OWN config row — `lw_dispatch_tasks`, by column name, exactly
        # as `dispatch_tasks._DUMP_LUA` reads it. Without these two the parser has
        # only the cfgId's digits, which call a level-7 tile «level 99» (#1267).
        'local lvl, spec = 0, 0 '
        'pcall(function() lvl = tonumber(v.cfg:getValue("level")) or 0 '
        'spec = tonumber(v.cfg:getValue("is_special")) or 0 end) '
        'CS.UnityEngine.Debug.LogError("ACT VT uuid="..tostring(v.uuid)'
        '.." cfg="..tostring(v.cfgId).." srv="..tostring(v.targetServer)'
        '.." x="..tostring(x).." y="..tostring(y).." steals="..tostring(steals)'
        '.." lvl="..tostring(lvl).." spec="..tostring(spec)'
        '.." done="..tostring(done).." exp="..tostring(exp)) '
        'end end '
        'CS.UnityEngine.Debug.LogError("ACT %s n="..tostring(n)) end)'
        % VT_END)


# --------------------------------------------------------------------------
# Ghost recon robbery — «Операция Призрак» / ghost.recon.steal
# --------------------------------------------------------------------------
# A DIFFERENT feature from the secret-task robbery above, despite the similar
# shape. «Секретка» is the hero dispatch that sits on a player's own tile and
# rides `hero.dispatch.*`; «Операция Призрак» is the weekly co-op event whose
# squads sit on `f2 = 29` tiles and ride `ghost.recon.*`. Both can be robbed,
# the commands are different, and the two daily budgets are counted separately.
# See docs/research/ghost-recon-steal.md and secret-task-steal.md.
#
# The wire side was captured in task #1005 (`results/ghost1005/steal.json`):
#
#     --> ghost.recon.steal  {uuid, ownerServer}
#     <-- ghost.recon.steal  {reward[], recordUuid, stealTimes, ownerInfo,
#                             cfgId, ownerUid, ownerServer, uuid}
#
# The Lua side was pinned live for this task:
#
#   * `MsgDefines.GhostReconSteal` = `ghost.recon.steal`, and
#     `GhostReconStealMessage:OnCreate(uuid, ownerServer)` puts exactly two
#     fields in the SFSObject — `PutLong uuid`, `PutInt ownerServer`.
#   * The press lives in the giant map-button dispatcher
#     `UIWorldPointBtn:OnBtnClick`, in the branch for
#     `WorldPointBtnType.GhostreconTaskSteal` (96); its constants read
#     `… GhostReconSteal | ownerServer …`, i.e. that one SendMessage.
#   * `GhostReconStealMessage:HandleMessage` is the reply applier
#     (`RewardManager:AddRewardsAndRes`, `ActGhostreconManager:GhostReconStealHandler`,
#     `UIUtil.ShowTipsId` on an errorCode). Calling it sends nothing.
#
# The owning manager is `DataCenter.ActGhostreconManager`: `taskList` (the
# squads the client knows, each with `uuid`, `cfgId`, `ownerId`, `ownerServer`,
# `targetServer`, `pointId`, `completionTime`, `actEndTime` and a `stealList` of
# past thieves), `stealTimes` (spent today), `GetNowSettingCfg().stealCount`
# (the daily cap, 5), `dispatchStealRange` (the set of servers that may be
# robbed at all) and `IsOpenDay()`.

# `GhostreconPointStealType`, the game's own verdict on one tile.
GHOST_STEAL_PREVIEW, GHOST_STEAL_CAN = 1, 2
GHOST_STEAL_UNSTEAL, GHOST_STEAL_UNSHOW = 3, 4
GHOST_STEAL_NAMES: dict[int, str] = {
    GHOST_STEAL_PREVIEW: "preview",     # visible, not robbable yet
    GHOST_STEAL_CAN: "can-steal",
    GHOST_STEAL_UNSTEAL: "no-steal",    # budget spent / already robbed by me
    GHOST_STEAL_UNSHOW: "not-shown",    # still running, or no template
}

# `WorldPointBtnType.GhostreconTaskSteal` — the map button this replaces. Not
# used by the send (the send is the message); kept because it names the click.
GHOST_RECON_STEAL_BTN = 96


def ghost_recon_is_open() -> str:
    """Lua *expression* -> 1 while the ghost-recon event is running today.

    `IsOpenDay()` compares the server clock against `openTime` for the same server
    day. Outside the event the whole feature is dark: `taskList` is empty, no tile
    carries a steal button, and a robbery would be refused — so every press below
    checks this first rather than putting a doomed message on the wire.
    """
    return "(DataCenter.ActGhostreconManager:IsOpenDay() and 1 or 0)"


def ghost_recon_steals_left() -> str:
    """Lua *expression* -> ghost-recon robberies still available today.

    `GetNowSettingCfg().stealCount` is the daily cap (5 on the live config) and
    `stealTimes` what has been spent. Counted separately from the secret-task
    budget in `secret_task_steals_left()` — the two features share nothing but
    the idea.
    """
    return ("(function() local M=DataCenter.ActGhostreconManager "
            "local cfg=M:GetNowSettingCfg() "
            "local cap=tonumber(cfg and cfg.stealCount) or 0 "
            "local used=tonumber(M.stealTimes) or 0 "
            "local left=cap-used if left<0 then left=0 end return left end)()")


#: `WorldPointType` of a ghost-recon squad's tile — what `world.get.detail.new` has to
#: be told to answer about one (`f2 = 29` on the wire, docs/research/protocol.md).
GHOST_RECON_POINT_TYPE = 29


def _ghost_task_by_uuid() -> str:
    """Lua chunk fragment: `find(uuid)` -> the task record, or nil.

    Looks in `taskList` (the squads the client actually has data for) — the alliance
    list is deliberately not searched: `ActGhostreconAllianceTaskInfo` carries neither
    `completionTime` nor `stealList`, so it cannot answer whether a tile is robbable.
    """
    return ("local function find(u) "
            "for _,t in ipairs(DataCenter.ActGhostreconManager.taskList or {}) do "
            "if tostring(t.uuid)==tostring(u) then return t end end return nil end ")


# The client's own verdict, `ActGhostreconManager:GetPointStealType(cfgId,
# completionTime, stealList)`, is the right gate for the TIMING half — it knows the
# template, the protect window and whether the squad has finished. It is called
# below with an EMPTY looter list on purpose:
#
#   passing a non-empty `stealList` throws inside the game
#   (`ActGhostreconManager.lua:570: attempt to index a nil value (field 'player')`
#   — the client reads `LuaEntry.player`, lowercase, which does not exist in this
#   VM; `LuaEntry.Player` does).
#
# Verified live: `GetPointStealType(60302, <finished>, {})` -> 2 (CanSteal),
# `GetPointStealType(60302, <still running>, {})` -> 4 (UnShow), and any non-empty
# list -> that error. So the looter half is counted here instead, from the record's
# own `stealList` against the template's `stealMaxtimes` (3 on cfg 60302), which is
# the same arithmetic the crashing branch was doing.
def ghost_recon_steal_state(uuid: int) -> str:
    """Lua *expression* -> `GhostreconPointStealType` for `uuid` (0 = unknown task).

    Numeric so a caller can tell *why* a target was skipped: 2 is robbable, 1 is
    visible but not yet, 3 is "not for me" (budget spent / already robbed), 4 is
    still running. 0 means the client has no record of that uuid at all — ask the
    server for the lists first (`ghost_recon_refresh()`).
    """
    return ("(function() %s local t=find(%d) if not t then return 0 end "
            "local M=DataCenter.ActGhostreconManager "
            "local ok,st=pcall(function() "
            "return M:GetPointStealType(t.cfgId, t.completionTime, {}) end) "
            "if not ok then return 0 end return st end)()"
            % (_ghost_task_by_uuid(), int(uuid)))


def ghost_recon_can_steal(uuid: int) -> str:
    """Lua *expression* -> 1 when `uuid` may be robbed right now.

    Four conditions, and every one of them is the client's own:

    * the event is open today;
    * the game's verdict for the tile is `CanSteal` (finished, past its protect
      window, template known);
    * the squad is somebody else's — robbing my own is not a thing;
    * the tile has a free loot slot and I am not already in its `stealList`
      (counted here rather than by the game, see the note above);
    * the owner's server is inside `dispatchStealRange`, the event's reachable set.

    All of it is advisory in the same way the secret-task gate is: the server has the
    last word and answers a refused robbery with an errorCode plus a toast.
    """
    return (
        "(function() if %s==0 then return 0 end "
        "%s local t=find(%d) if not t then return 0 end "
        "local M=DataCenter.ActGhostreconManager "
        "local me=tostring(LuaEntry.Player.uid) "
        "if tostring(t.ownerId)==me then return 0 end "
        "local tpl=M:GetTaskTemplate(t.cfgId) if not tpl then return 0 end "
        "local n=0 for _,s in ipairs(t.stealList or {}) do n=n+1 "
        "if tostring(s.uid)==me then return 0 end end "
        "if n>=(tonumber(tpl.stealMaxtimes) or 3) then return 0 end "
        "local srv=t.ownerServer or t.targetServer "
        "if srv and (M.dispatchStealRange or {})[srv]~=true then return 0 end "
        "local ok,st=pcall(function() "
        "return M:GetPointStealType(t.cfgId, t.completionTime, {}) end) "
        "if not ok or st~=GhostreconPointStealType.CanSteal then return 0 end "
        "if %s<=0 then return 0 end return 1 end)()"
        % (ghost_recon_is_open(), _ghost_task_by_uuid(), int(uuid),
           ghost_recon_steals_left())
    )


def daily_steal_budgets() -> str:
    """Lua *expression* -> both robbery budgets in one string, straight from the game.

    `secret=<left>/<cap> ghost=<left>/<cap> open=<0|1>` — TWO budgets, and the whole
    reason this reads them together is that they are separate and were being mistaken
    for one: on 2026-08-27 the account had `secret=0/5` while `ghost=5/5` (#2010). One
    round trip rather than two, so a card can say both without paying twice.

    Every number is the SERVER's, never a tally of presses the panel has made: the
    secret-task pair is `GetDispatchSetting('steal_count')` against `GetTodayStealNum()`,
    the ghost pair is `GetNowSettingCfg().stealCount` against `stealTimes`, and a steal
    only moves either of them when the reply lands. A count of our own sends would be a
    second set of books, and the first disagreement with the game would be a lie in our
    favour — which is exactly what a person reading «осталось 3» would act on.

    A manager the client has not loaded reads as `-` rather than 0: «not asked» and
    «none left» are different facts, and a 0 would stop a watcher that has every right
    to run.
    """
    return ("(function() "
            "local function pair(f) local ok,v=pcall(f) "
            "if not ok or v==nil then return '-' end return tostring(v) end "
            "local S=DataCenter.ActDispatchTaskDataManager "
            "local G=DataCenter.ActGhostreconManager "
            "local s_cap=pair(function() return math.floor(tonumber("
            "S:GetDispatchSetting('steal_count')) or 0) end) "
            "local s_used=pair(function() return math.floor(tonumber("
            "S:GetTodayStealNum()) or 0) end) "
            "local g_cap=pair(function() local cfg=G:GetNowSettingCfg() "
            "return math.floor(tonumber(cfg and cfg.stealCount) or 0) end) "
            "local g_used=pair(function() return math.floor(tonumber(G.stealTimes) or 0) "
            "end) "
            "local open=pair(function() return G:IsOpenDay() and 1 or 0 end) "
            "local function left(cap,used) if cap=='-' or used=='-' then return '-' end "
            "local n=tonumber(cap)-tonumber(used) if n<0 then n=0 end return tostring(n) "
            "end "
            "return 'secret='..left(s_cap,s_used)..'/'..s_cap"
            "..' ghost='..left(g_cap,g_used)..'/'..g_cap"
            "..' open='..open end)()")


def ghost_recon_refresh() -> str:
    """Ask the server for both ghost-recon task lists (own/known + alliance).

    Fire-and-forget: read the result from a SEPARATE chunk after a settle, never by
    looping inside this one. Without it a fresh client has an empty `taskList` and
    every target reads as unknown.
    """
    return ("pcall(function() SFSNetwork.SendMessage(MsgDefines.GhostreconGetTaskList) end) "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.GhostReconGetAllianceTaskList) end) "
            'CS.UnityEngine.Debug.LogError("ACT ghost_lists_requested")')


def ghost_recon_targets_dump() -> str:
    """Reader chunk: one `ACT G …` line per ghost-recon squad the client knows.

    Fields: `uuid`, `cfg` template id, `owner` uid, `srv` the owner's server, `tsrv`
    the server the squad is sent to, `x`/`y` (from `pointId`), `done` completion
    epoch-ms, `ends` the EVENT's own end, `exp` the task's expiry (the end of the event
    day, and the only one of the two anybody can count down to), `looted` how many of
    the template's slots are spent, `state` the game's `GhostreconPointStealType`, `raw` the task's OWN state
    (0 empty slot / 2 running / 3 done — `GHOST_STATE_*`), `mine` when the squad is my
    own, `al` the owning alliance's id, and `name` — the owner's nickname, hex-encoded
    because a nickname may hold spaces and any script at all.

    **The level, the rarity and the star come from the event's OWN config row**, not
    from the cfgId's digits: `lvl` / `colour` / `spec` are `GetTaskTemplate(cfgId)`'s
    `level` / `color` / `special`, and `slots` is its `stealMaxtimes`. The digits are
    only a fallback on the Python side, for a template the client has not loaded. That
    is the lesson #1244 cost on the other robbery, where home-made arithmetic invented
    both a star and a «level 99» (task #1251).

    `raw` and `state` are different questions and both are wanted: an EMPTY dispatch
    slot of mine has no squad, no tile and no coordinate, yet `GetPointStealType` still
    answers 2 for it. A reader that shows one as a target shows «✅ готово» on a slot
    nobody has filled (#1251).

    The owner's NAME is not on the task either — it is in the squad's own member list,
    against the member whose uid is the owner's. That is the only place the client
    keeps it, and it is what a list of «who of my alliance is running what» is for.

    A robbery needs `uuid` + `ownerServer`, both of which are printed, so this is the
    list a queue is built from.
    """
    return (
        "local M=DataCenter.ActGhostreconManager "
        "local me=tostring(LuaEntry.Player.uid) "
        "local function hex(s) return (tostring(s):gsub('.',function(c) "
        "return string.format('%%02x',c:byte()) end)) end "
        'CS.UnityEngine.Debug.LogError("ACT ghost open="..tostring(M:IsOpenDay())'
        '.." left="..tostring(%s).." known="..tostring(#(M.taskList or {}))) '
        "for _,t in ipairs(M.taskList or {}) do "
        "local x,y=0,0 pcall(function() local tp=SceneUtils.IndexToTilePos(t.pointId) "
        "x,y=tp.x,tp.y end) "
        "local n=0 for _,s in ipairs(t.stealList or {}) do n=n+1 end "
        "local ok,st=pcall(function() "
        "return M:GetPointStealType(t.cfgId, t.completionTime, {}) end) "
        "local lvl,colour,spec,slots=0,0,0,0 "
        "pcall(function() local c=M:GetTaskTemplate(t.cfgId) "
        "lvl=tonumber(c.level) or 0 colour=tonumber(c.color) or 0 "
        "spec=c.special and 1 or 0 slots=tonumber(c.stealMaxtimes) or 0 end) "
        "local who='' pcall(function() for _,mem in ipairs(t.memberList or {}) do "
        "local mi=mem.memberInfo or mem "
        "if tostring(mi.uid)==tostring(t.ownerId) then who=tostring(mi.name or '') end "
        "end end) "
        'CS.UnityEngine.Debug.LogError("ACT G uuid="..tostring(t.uuid)'
        '.." cfg="..tostring(t.cfgId).." owner="..tostring(t.ownerId)'
        '.." srv="..tostring(t.ownerServer or t.targetServer)'
        '.." tsrv="..tostring(t.targetServer)'
        '.." x="..tostring(x).." y="..tostring(y)'
        '.." done="..tostring(t.completionTime).." ends="..tostring(t.actEndTime)'
        '.." exp="..tostring(t.taskExpireTime)'
        '.." looted="..tostring(n).." state="..tostring(ok and st or 0)'
        '.." raw="..tostring(t.state)'
        '.." lvl="..tostring(lvl).." colour="..tostring(colour)'
        '.." spec="..tostring(spec).." slots="..tostring(slots)'
        '.." al="..tostring(t.allianceId).." name="..hex(who)'
        '.." mine="..tostring(tostring(t.ownerId)==me)) end'
        % ghost_recon_steals_left()
    )


def ghost_recon_templates_dump() -> str:
    """Reader chunk: one `ACT TPL …` line per ghost-recon template the client holds.

    The event's own config table, keyed by cfgId: `lvl` the level the game shows,
    `colour` the rarity it paints, `spec` whether it draws a star, `slots` how many
    robberies a tile allows and `dur` how long a squad stays out. Seventeen rows live.

    This is what lets a tile read off the MAP say the same things as one read out of
    the client's own list (#1251): the tile carries a cfgId and nothing else, and
    splitting that id into a level is the arithmetic that invented «level 99» on the
    other robbery. One read, cached by the caller for as long as the client runs — a
    config table does not change under a running client.
    """
    return (
        "local M=DataCenter.ActGhostreconManager "
        "for id,c in pairs(M.templates or {}) do "
        'CS.UnityEngine.Debug.LogError("ACT TPL cfg="..tostring(id)'
        '.." lvl="..tostring(c.level).." colour="..tostring(c.color)'
        '.." spec="..tostring(c.special and 1 or 0)'
        '.." slots="..tostring(c.stealMaxtimes).." dur="..tostring(c.time)) end'
    )


def ghost_recon_alliance_request() -> str:
    """Ask the server for the alliance's ghost-recon list — ONCE, to seed an empty one.

    The list normally needs no asking: the client keeps it and
    `push.ghost.recon.alliance.single` moves it, which is why the panel reads local
    state (:func:`ghost_recon_alliance_dump`) and polls nothing. But a client that has
    not had the event's window opened this session has never been sent the list at all,
    and an empty table is then indistinguishable from «the alliance has nothing out».
    The game's own window does exactly this in its `OnEnable`; this is that one message
    and nothing else (#1251).

    Fire-and-forget: read the result from a SEPARATE chunk after a settle.
    """
    return ("pcall(function() "
            "SFSNetwork.SendMessage(MsgDefines.GhostReconGetAllianceTaskList) end) "
            'CS.UnityEngine.Debug.LogError("ACT ghost_alliance_requested")')


def ghost_recon_alliance_dump() -> str:
    """Reader chunk: one `ACT A …` line per ghost-recon squad the ALLIANCE has out.

    A different manager from :func:`ghost_recon_targets_dump` and a different question.
    `ActGhostreconManager.taskList` is what THIS account is involved in — my own three
    slots and whatever else the client happens to have been told about. The window the
    player actually reads («Операция Призрак» → задания альянса) draws
    `ActGhostreconAllianceManager.allianceTaskList`, which is the whole alliance's, all
    of it at once — twelve rows live where the other list carried four (#1251).

    **Nothing here asks the server.** The list is already in the client and a push
    (`push.ghost.recon.alliance.single`) keeps it that way; the window's own
    `OnEnable` re-requests it, this does not.

    Fields: `uuid`, `cfg` template id, `owner` uid, `name` the leader's nickname
    (hex-encoded — it may hold spaces), `srv` the server the squad was sent to, `x`/`y`
    (from `pointId`), `start` when the squad set out, `state` the game's
    `GhostreconPointStealType`, `members` how many are on it — and the template's own
    `lvl` / `colour` / `spec` / `slots` / `dur`.

    **The clock is `start + dur`, not a field.** This record has no completion time at
    all; the event's config row carries how long a squad is out (`time`), so when it is
    back is arithmetic over two READ values rather than a guess. What is genuinely not
    in this list is how many times the tile has been robbed — there is no `stealList`
    on it — so a reader must leave that empty rather than invent it.
    """
    return (
        "local A=DataCenter.ActGhostreconAllianceManager "
        "local M=DataCenter.ActGhostreconManager "
        "local function hex(s) return (tostring(s):gsub('.',function(c) "
        "return string.format('%02x',c:byte()) end)) end "
        'CS.UnityEngine.Debug.LogError("ACT ghost_alliance n="'
        "..tostring(#(A.allianceTaskList or {}))) "
        "for _,t in ipairs(A.allianceTaskList or {}) do "
        "local x,y=0,0 pcall(function() local tp=SceneUtils.IndexToTilePos(t.pointId) "
        "x,y=tp.x,tp.y end) "
        "local lvl,colour,spec,slots,dur=0,0,0,0,0 "
        "pcall(function() local c=M:GetTaskTemplate(t.cfgId) "
        "lvl=tonumber(c.level) or 0 colour=tonumber(c.color) or 0 "
        "spec=c.special and 1 or 0 slots=tonumber(c.stealMaxtimes) or 0 "
        "dur=tonumber(c.time) or 0 end) "
        "local ok,st=pcall(function() "
        "return M:GetPointStealType(t.cfgId, t.teamStartTime+dur, {}) end) "
        "local who='' pcall(function() "
        "who=tostring(((t.leaderMemberInfo or {}).memberInfo or {}).name or '') end) "
        "local n=0 for _ in pairs(t.memberList or {}) do n=n+1 end "
        'CS.UnityEngine.Debug.LogError("ACT A uuid="..tostring(t.uuid)'
        '.." cfg="..tostring(t.cfgId).." owner="..tostring(t.ownerId)'
        '.." srv="..tostring(t.targetServer)'
        '.." x="..tostring(x).." y="..tostring(y)'
        '.." start="..tostring(t.teamStartTime)'
        '.." lvl="..tostring(lvl).." colour="..tostring(colour)'
        '.." spec="..tostring(spec).." slots="..tostring(slots).." dur="..tostring(dur)'
        '.." state="..tostring(ok and st or 0).." members="..tostring(n)'
        '.." name="..hex(who)) end'
    )


def ghost_recon_steal(uuid: int, owner_server: int) -> str:
    """Rob ghost-recon squad `uuid` on `owner_server` — one `ghost.recon.steal`.

    Headless: no tile tap, no popup, no march. Gated on the day's budget and on the
    event being open, so a spent or closed day never puts a doomed message on the
    wire. The per-tile conditions are `ghost_recon_can_steal()`'s job — this one
    takes a target the caller has already vetted (or is deliberately re-trying).
    """
    return ('if %s > 0 and %s > 0 then '
            'pcall(function() SFSNetwork.SendMessage(MsgDefines.GhostReconSteal, %d, %d) end) '
            'CS.UnityEngine.Debug.LogError("ACT ghost_steal_sent uuid=%d srv=%d") end'
            % (ghost_recon_is_open(), ghost_recon_steals_left(),
               int(uuid), int(owner_server), int(uuid), int(owner_server)))


def ghost_recon_leave_message(record_uuid: int, msg_id: int, owner_server: int) -> str:
    """Leave the robbed squad's owner one of the canned messages.

    `ghost.recon.leave.message {msgId, recordUuid, ownerServer}` — the follow-up
    captured in #1005, keyed by the `recordUuid` the robbery's reply carries (NOT the
    task uuid). Pure flavour; it pays nothing.
    """
    return ('pcall(function() SFSNetwork.SendMessage(MsgDefines.GhostReconLeaveMessage, '
            '%d, %d, %d) end) '
            'CS.UnityEngine.Debug.LogError("ACT ghost_message_sent record=%d msg=%d")'
            % (int(msg_id), int(record_uuid), int(owner_server),
               int(record_uuid), int(msg_id)))


# --- the ghost-recon target queue -----------------------------------------
# Same reason as the secret-task queue: `TAP` takes no arguments, so the targets
# are parked on the manager's own table and the button robs them one per press.
# A separate table from `__lw_steal_queue` so the two features can never rob each
# other's targets with the wrong command.

def ghost_recon_queue_set(targets) -> str:
    """Replace the ghost-recon queue with `targets` — (uuid, owner_server) pairs."""
    items = ",".join("{uuid=%d,server=%d}" % (int(u), int(s)) for u, s in targets)
    return ("local M=DataCenter.ActGhostreconManager M.__lw_ghost_queue={%s} "
            'CS.UnityEngine.Debug.LogError("ACT ghost_queue_set "..tostring(#M.__lw_ghost_queue))'
            % items)


def ghost_recon_queue_clear() -> str:
    """Empty the ghost-recon queue."""
    return ("local M=DataCenter.ActGhostreconManager M.__lw_ghost_queue={} "
            'CS.UnityEngine.Debug.LogError("ACT ghost_queue_cleared")')


def ghost_recon_queue_len() -> str:
    """Lua *expression* -> how many ghost-recon targets are queued."""
    return ("(function() return #(DataCenter.ActGhostreconManager.__lw_ghost_queue or {}) end)()")


def ghost_recon_steals_pending() -> str:
    """Lua *expression* -> presses `steal_ghost_recon` can still make.

    `min(queued, robberies left today)`, and 0 whenever the event is closed — the
    button's `count_lua`, so `xall` stops at the queue, at the cap, or at the end of
    the event, whichever comes first.
    """
    return ("(function() if %s==0 then return 0 end "
            "local q=%s local b=%s if q<b then return q end return b end)()"
            % (ghost_recon_is_open(), ghost_recon_queue_len(), ghost_recon_steals_left()))


def ghost_recon_request_detail() -> str:
    """Ask the server about every QUEUED ghost tile — one `world.get.detail.new` each.

    THE SAME ROUND TRIP A FINGER MAKES when it taps that tile, and no server jump: the
    message carries the tile's own `serverId`, so a squad standing on another warzone is
    asked about from here (#2010). The reply lands in `WorldPointDetailManager`, keyed by
    pointId, exactly as the secret-task robbery's coordinate lookup does.

    ONE PER TARGET WE ARE ABOUT TO TRY, and never a sweep of the list: the queue holds at
    most the day's remaining robberies, the list itself is kept current by the sniffer's
    events, and a periodic re-read of everything is the background activity the operator
    has forbidden.

    Sent for the whole queue in one chunk so the replies travel while the presses are
    still being gated; read them after a settle, never in the same chunk.

    BY THE TILE'S OWN `pointId`, never by one rebuilt from x/y (#2010). The wire carries
    it on every ghost tile, and the two do not agree: measured live, the tile at (195, 88)
    is `88195` on the wire and `SceneUtils.TilePosToIndex` answers `88196` — one square
    over, and the server duly said nothing about it. The rebuilt id stays as the fallback
    for a caller that has no `pid` to give.
    """
    return ("local M=DataCenter.ActGhostreconManager "
            "local n=0 "
            "for _,t in ipairs(M.__lw_ghost_queue or {}) do "
            "local pid=tonumber(t.pid or 0) or 0 "
            "if pid<=0 and t.x and t.y then pid=SceneUtils.TilePosToIndex("
            "CS.UnityEngine.Vector2Int(t.x, t.y)) end "
            "if pid>0 then "
            "pcall(function() SFSNetwork.SendMessage('world.get.detail.new', "
            "pid, t.server, 0, %d, '') end) n=n+1 end end "
            'CS.UnityEngine.Debug.LogError("ACT ghost_detail_asked n="..tostring(n))'
            % GHOST_RECON_POINT_TYPE)


def steal_next_ghost_recon() -> str:
    """Rob the first queued ghost-recon target — IF THE GAME SAYS IT MAY BE ROBBED.

    The target is popped BEFORE anything else, so a refusal costs one queue entry rather
    than wedging `xall` on the same doomed uuid. One press per chunk: the budget only
    moves when the server's reply lands.

    THE GAME'S OWN VERDICT, ASKED PER TARGET, AT THE MOMENT OF THE PRESS (#2010). It used
    to send at whatever was queued, and the whole of what gated it was the event day and
    the daily budget — so a tile the panel believed ready by its own clock was fired at,
    the server refused it, and `stealTimes` never moved: measured over four runs and
    twenty presses, not one confirmation. The verdict has two forms and the tile decides
    which:

    * a squad the CLIENT knows (`taskList`) is judged by `GetPointStealType(...) ==
      CanSteal`, plus the three things that gate cannot see — it is not mine, its looter
      list is not full, and its warzone is inside `dispatchStealRange`;
    * a tile only the MAP has seen has no entry there, so the authority is the detail
      just asked for (:func:`ghost_recon_request_detail`). Its `taskInfo` is the squad
      itself — measured live: `uuid`, `cfgId`, `completionTime`, `stealList`, `ownerId`
      and, the field that matters most, `ownerServer` — so the same three checks are made
      against it and `GetPointStealType` is asked with the tile's OWN looter list rather
      than an empty one.

      **AND THE SEND FOLLOWS THE DETAIL'S `ownerServer`, not the map's.** They are two
      different numbers and the robbery wants the owner's: a tile standing on 935 was
      dispatched by a player of 996, and `ghost.recon.steal {uuid, ownerServer}` addressed
      at 935 is a message about a squad that is not there.

    Anything the game does not confirm is SKIPPED, silently and without a send — the
    day's five are spent only on what it called available. The skip says so on the
    stream (`ghost_steal_skipped`) so a run that takes nothing can be read.
    """
    return ("local M=DataCenter.ActGhostreconManager "
            "local q=M.__lw_ghost_queue or {} local t=table.remove(q,1) "
            "if not t then return end "
            "if %s <= 0 or %s <= 0 then return end "
            "%s"
            "local me=tostring(LuaEntry.Player.uid) "
            "local ok=false local why='no_verdict' "
            "local task=find(t.uuid) "
            "if task then "
            "if tostring(task.ownerId)==me then why='mine' else "
            "local n=0 for _,s in ipairs(task.stealList or {}) do n=n+1 "
            "if tostring(s.uid)==me then n=99 end end "
            "local tpl=M:GetTaskTemplate(task.cfgId) "
            "local cap=(tpl and tonumber(tpl.stealMaxtimes)) or 3 "
            "local srv=task.ownerServer or task.targetServer "
            "if n>=cap then why='looted_out' "
            "elseif srv and (M.dispatchStealRange or {})[srv]~=true then why='out_of_range' "
            "else local okv,st=pcall(function() "
            "return M:GetPointStealType(task.cfgId, task.completionTime, {}) end) "
            "if okv and st==GhostreconPointStealType.CanSteal then ok=true "
            "else why='state_'..tostring(okv and st or 'err') end end end "
            "else "
            "local pid=tonumber(t.pid or 0) or 0 "
            "if pid<=0 and t.x and t.y then pid=SceneUtils.TilePosToIndex("
            "CS.UnityEngine.Vector2Int(t.x, t.y)) end "
            "local okd,d=pcall(function() "
            "return DataCenter.WorldPointDetailManager:GetDetailByPointId(pid) end) "
            "local ti=(okd and d) and d.taskInfo or nil "
            "if not ti then why='no_detail' "
            "elseif tostring(ti.uuid)~=tostring(t.uuid) then why='gone' "
            "elseif tostring(ti.ownerId)==me then why='mine' "
            "else "
            "local n=0 for _,sl in ipairs(ti.stealList or {}) do n=n+1 "
            "if tostring(sl.uid)==me then n=99 end end "
            "local tpl=M:GetTaskTemplate(ti.cfgId) "
            "local cap=(tpl and tonumber(tpl.stealMaxtimes)) or 3 "
            "local srv=ti.ownerServer or t.server "
            "if n>=cap then why='looted_out' "
            "elseif srv and (M.dispatchStealRange or {})[srv]~=true then why='out_of_range' "
            "else local okv,st=pcall(function() return M:GetPointStealType("
            "ti.cfgId, ti.completionTime, ti.stealList or {}) end) "
            "if okv and st==GhostreconPointStealType.CanSteal then ok=true "
            "t.server=srv "
            "else why='state_'..tostring(okv and st or 'err') end end end end "
            "if not ok then "
            'CS.UnityEngine.Debug.LogError("ACT ghost_steal_skipped uuid="'
            '..tostring(t.uuid).." why="..why) return end '
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.GhostReconSteal, "
            "t.uuid, t.server) end) "
            'CS.UnityEngine.Debug.LogError("ACT ghost_steal_sent uuid="..tostring(t.uuid)'
            '.." srv="..tostring(t.server))'
            % (ghost_recon_is_open(), ghost_recon_steals_left(), _ghost_task_by_uuid()))


# ---------------------------------------------------------------------------
# World-map treasures ("сокровища на карте") — dig march + claim.
# ---------------------------------------------------------------------------
# Reverse-engineered from a live capture (task #1107, docs/research/world-treasures.md).
# A treasure is a `world.get.block` / `push.world.point.update` tile with
# `WorldPointType.TREASURE == 21`; the alliance marches onto it to dig, and the
# finisher claims the reward. Two network moves, both taken verbatim from the trace
# and from the already-working attack / ghost-recon primitives:
#
#   * DIG  = MarchUtil.SendCreateMarchMessage(formation, MarchTargetType.DETECT_TREASURE,
#            pid, uuid, 1, 1, false, serverId, nil) — the SAME launch primitive as
#            attack/scout/collect (see attack.py / world-monsters.md Finding 17), only the
#            MarchTargetType changes: DETECT_TREASURE (50) same-server, CROSS_DETECT_TREASURE
#            (182) for a treasure on another server. Scheduled on the main thread via
#            TimerManager:DelayInvoke because a cold SendCreateMarchMessage from the hijack
#            thread is created but dropped by the server (attack.py).
#   * CLAIM = SFSNetwork.SendMessage(MsgDefines.DetectEventClaimTreasure, uuid, targetServer)
#            — the exact call the in-game "раскопать/забрать" finish fires (trace:
#            SFSObject PutLong "uuid" + PutInt "targetServer"). A pure network send, so it
#            needs no main-thread scheduling — identical shape to ghost-recon steal.
#
# NOT PROVEN LIVE YET: no treasure was on the map during the analysis
# (ActDetectTreasureDataManager.treasures_num == 0), so neither call has been fired
# end-to-end. The server gates both on the per-day dig/claim limit
# (ActDetectTreasureDataManager:CheckTreasureReachDailyLimit).

MARCH_DETECT_TREASURE = 50         # MarchTargetType.DETECT_TREASURE (same server)
MARCH_CROSS_DETECT_TREASURE = 182  # MarchTargetType.CROSS_DETECT_TREASURE (other server)


def dig_treasure_march(pid, uuid, server, formation, cross: bool = False) -> str:
    """Send a squad to dig the treasure at tile `pid` (uuid/server from its point data).

    `formation` is a squad formation UUID (as in attack.py / rally_join.py). `cross=True`
    uses MarchTargetType.CROSS_DETECT_TREASURE for a treasure sitting on another server;
    same-server digs use DETECT_TREASURE. All ids are passed as bare Lua numeric literals
    (Lua 5.3 int64), so a 19-digit uuid survives intact.
    """
    target = "CROSS_DETECT_TREASURE" if cross else "DETECT_TREASURE"
    return (
        'TimerManager:GetInstance():DelayInvoke(function() '
        'local ok,err=pcall(function() '
        'MarchUtil.SendCreateMarchMessage(%s, MarchTargetType.%s, %s, %s, 1, 1, false, %s, nil) '
        'end) '
        'CS.UnityEngine.Debug.LogError("ACT dig_treasure_sent ok="..tostring(ok).." err="..tostring(err)) '
        'end, 0.5) '
        'CS.UnityEngine.Debug.LogError("ACT dig_treasure_armed pid=%s target=%s")'
        % (formation, target, pid, uuid, server, pid, target)
    )


def claim_treasure(uuid, server) -> str:
    """Claim (take) a dug treasure by its `uuid` on `server` — the finisher's send.

    `SFSNetwork.SendMessage(MsgDefines.DetectEventClaimTreasure, uuid, targetServer)`,
    exactly what the in-game finish button fires; the message builder packs uuid->PutLong,
    server->PutInt. Headless, no window, no scheduling (pure network send).
    """
    return (
        'pcall(function() SFSNetwork.SendMessage(MsgDefines.DetectEventClaimTreasure, %s, %s) end) '
        'CS.UnityEngine.Debug.LogError("ACT claim_treasure_sent uuid=%s srv=%s")'
        % (uuid, server, uuid, server)
    )


# --- Treasure work queue (find -> dig-if-digging / claim-if-dug) -------------
# The recipe layer. Targets are parked OUTSIDE (a finder), exactly like ghost recon,
# because a DSL `TAP` takes no arguments. The finder fills a list on the VM:
#
#     DataCenter.__lw_treasure_queue = {
#       { pid=<tileIndex>, uuid=<long>, server=<int>,
#         dug=<bool>,       -- is it already dug? (wire point field 7 / operator uid present)
#         cross=<bool>,     -- treasure sits on another server? (server ~= home)
#         formation=<uuid>, -- squad to send to dig it (optional)
#       }, ...
#     }
#
# `dug` is the "копается vs раскопано" split proven from the capture
# (docs/research/world-treasures.md): while the treasure is still being dug the point
# carries NO operator uid (wire f11.7 absent); once fully dug that field is filled with
# the finisher's uid. The finder sets `dug` from that. `work_next_treasure` then does
# the right thing per target — dig it if still digging, claim it if dug.
#
# A shared default squad for the dig, when a queue entry has no `formation`:
#     DataCenter.__lw_treasure_formation = <formation uuid>


def treasure_queue_len() -> str:
    """Lua *expression* -> how many treasures are queued (0 when the finder found none)."""
    return "(function() return #(DataCenter.__lw_treasure_queue or {}) end)()"


def treasure_head_state() -> str:
    """Lua *expression* -> head target state: 1 dug (claim), 0 digging (dig), -1 empty."""
    return ("(function() local q=DataCenter.__lw_treasure_queue or {} local t=q[1] "
            "if not t then return -1 end return t.dug and 1 or 0 end)()")


def dig_head_treasure() -> str:
    """Pop the head treasure and send a squad to DIG it (still-being-dug target).

    The head is removed first (like `steal_next_ghost_recon`) so a refused march costs one
    queue entry rather than wedging `xall` on the same target — the finder re-adds it next
    scan while it is still digging. Scheduled on the main thread (a cold
    `SendCreateMarchMessage` from the hijack thread is created but dropped). Squad =
    `entry.formation`, else the shared `DataCenter.__lw_treasure_formation`; with neither it
    is popped and logged, not retried.
    """
    return (
        "local q=DataCenter.__lw_treasure_queue or {} local t=table.remove(q,1) "
        "if t then local fm=t.formation or DataCenter.__lw_treasure_formation "
        "if fm then TimerManager:GetInstance():DelayInvoke(function() "
        "pcall(function() MarchUtil.SendCreateMarchMessage(fm, "
        "t.cross and MarchTargetType.CROSS_DETECT_TREASURE or MarchTargetType.DETECT_TREASURE, "
        "t.pid, t.uuid, 1, 1, false, t.server, nil) end) "
        'CS.UnityEngine.Debug.LogError("ACT treasure_dig pid="..tostring(t.pid).." srv="..tostring(t.server)) '
        'end, 0.5) '
        'else CS.UnityEngine.Debug.LogError("ACT treasure_dig_skip no formation (set DataCenter.__lw_treasure_formation)") end '
        "end"
    )


def claim_head_treasure() -> str:
    """Pop the head treasure and CLAIM it (already-dug target) — the finisher's send.

    Direct network send (no scheduling needed), same shape as `steal_next_ghost_recon`.
    """
    return (
        "local q=DataCenter.__lw_treasure_queue or {} local t=table.remove(q,1) "
        "if t then pcall(function() SFSNetwork.SendMessage(MsgDefines.DetectEventClaimTreasure, t.uuid, t.server) end) "
        'CS.UnityEngine.Debug.LogError("ACT treasure_claim uuid="..tostring(t.uuid).." srv="..tostring(t.server)) end'
    )


def treasure_queue_dump() -> str:
    """Reader chunk: one `ACT TQ …` line per parked treasure, with its map position.

    `park_treasures` already logs what it parked, but only as it parks — a caller that
    wants to SHOW the queue (the panel's «Скрытые сокровища» list) needs to be able to
    re-read it, and needs the tile position a `pid` stands for. Fields: `i` the queue
    slot (1-based, what `dig_head_treasure`/`claim_head_treasure` spend in order), `pid`,
    `uuid`, `srv`, `dug` (already dug → claim, else dig) and `x`/`y` off
    `SceneUtils.IndexToTilePos`, the same conversion every other tile read uses.

    Emits nothing but the lines — reading the queue never changes it.
    """
    return (
        "local q=DataCenter.__lw_treasure_queue or {} "
        'CS.UnityEngine.Debug.LogError("ACT treasure_queue "..tostring(#q)) '
        "for i,t in ipairs(q) do "
        "local x,y=0,0 pcall(function() local tp=SceneUtils.IndexToTilePos(t.pid) "
        "x,y=tp.x,tp.y end) "
        'CS.UnityEngine.Debug.LogError("ACT TQ i="..tostring(i).." pid="..tostring(t.pid)'
        '.." uuid="..tostring(t.uuid).." srv="..tostring(t.server)'
        '.." dug="..tostring(t.dug and 1 or 0).." x="..tostring(x).." y="..tostring(y)) end'
    )


def treasure_formation_set(formation) -> str:
    """Park the squad `dig_head_treasure` should march with (`__lw_treasure_formation`).

    A queue entry may carry its own `formation`; this is the shared fallback, set once
    so a dig started from a list (the panel) does not have to rewrite every entry.

    `formation` goes in as a bare Lua literal, like every other uuid in this module —
    they are 19-digit numbers and Lua 5.3 integers hold them exactly.
    """
    return ("DataCenter.__lw_treasure_formation=%s "
            'CS.UnityEngine.Debug.LogError("ACT treasure_formation="..tostring('
            "DataCenter.__lw_treasure_formation))" % int(formation))


# --- The finder: is there a treasure right now? -----------------------------
# `DataCenter.ActDetectTreasureDataManager` is a pure reply cache, verified live via
# `string.dump` (task #1116): `GetArrData` only reads `self.dataDict[activityId]`, and
# only `OnGetArrDataMsg` ever writes it (it also sets `treasures_num`). So the client
# knows about a treasure exactly when a `activity.detect.list` reply has arrived —
# nothing polls on its own, and the dict stays empty for a whole session when the
# alliance's detect event dropped nothing.
#
# `treasure_refresh_request` re-asks the server (the message needs an activityId — sent
# with none it dies in the serializer: "bad argument #2 to 'pack'"). The ids to ask for
# are the manager's own `dailyGot` keys, which are the treasure cfg groups the account
# tracks a per-day count for.


def treasure_refresh_request(activity_ids) -> str:
    """Ask the server to (re-)send the detect-treasure list for each activity id.

    Fire-and-forget: the reply lands in `OnGetArrDataMsg`, so read the manager back a
    couple of seconds later (`treasure_state`).
    """
    ids = ",".join(str(int(i)) for i in activity_ids)
    return (
        "for _,id in ipairs({%s}) do "
        "local ok,err=pcall(function() SFSNetwork.SendMessage(MsgDefines.ActivityDetectList, id) end) "
        'CS.UnityEngine.Debug.LogError("ACT treasure_ask id="..tostring(id).." ok="..tostring(ok).." err="..tostring(err)) '
        "end" % ids
    )


def treasure_state() -> str:
    """Log the manager's treasure state — the "is there anything to dig?" read.

    Emits, all prefixed `ACT`:
      * `treasures_num=<n>`      — the count from the last list reply
      * `treasure_daily <cfgId>=<n>` — per-group takes already used today
      * `treasure_rec ...`       — one line per record found in `dataDict`, as raw
        `key=value` pairs
    The record lines are dumped raw on purpose: no treasure has ever been in the dict
    while looking (it was empty in both the #1107 RE and the #1116 check), so the exact
    field names are unconfirmed — the first live treasure prints its own shape here.
    """
    return (
        "local m=DataCenter.ActDetectTreasureDataManager "
        'CS.UnityEngine.Debug.LogError("ACT treasures_num="..tostring(m and m.treasures_num)) '
        "if m then "
        "for k,v in pairs(m.dailyGot or {}) do "
        'CS.UnityEngine.Debug.LogError("ACT treasure_daily "..tostring(k).."="..tostring(v)) end '
        "local function dump(t,depth,path) "
        "local flat,nested={},{} "
        "for k,v in pairs(t) do if type(v)=='table' then nested[#nested+1]={k,v} "
        "elseif type(v)~='function' then flat[#flat+1]=tostring(k)..'='..tostring(v) end end "
        "if #flat>0 then CS.UnityEngine.Debug.LogError('ACT treasure_rec '..path..' '..table.concat(flat,' ')) end "
        "if depth<3 then for _,kv in ipairs(nested) do dump(kv[2],depth+1,path..'.'..tostring(kv[1])) end end "
        "end "
        "local n=0 for k,v in pairs(m.dataDict or {}) do n=n+1 "
        "if type(v)=='table' then dump(v,1,tostring(k)) end end "
        'CS.UnityEngine.Debug.LogError("ACT treasure_dict_count="..tostring(n)) '
        "end"
    )


def park_treasures(home_server: int = 0) -> str:
    """Fill `DataCenter.__lw_treasure_queue` from the manager, for `work_treasure.md`.

    Walks `dataDict` for records carrying a point id and a uuid, and parks one queue
    entry each: `{pid, uuid, server, dug, cross}`. `dug` comes from the operator-uid
    field (present once the tile is fully dug — the split proven on the wire in
    docs/research/world-treasures.md); `cross` from the treasure's server differing
    from `home_server`. Field names are probed against several spellings because the
    record shape has never been seen populated — see `treasure_state`.

    Logs `ACT treasure_parked <n>` and one `ACT treasure_target ...` line per entry.
    """
    return (
        "local m=DataCenter.ActDetectTreasureDataManager local q={} "
        "local function pick(t,...) for _,k in ipairs({...}) do local v=t[k] "
        "if v~=nil and v~='' and v~=0 then return v end end return nil end "
        "local function take(rec) "
        "local pid=pick(rec,'pointId','point_id','pid','index','tileIndex') "
        "local uuid=pick(rec,'uuid','treasureUuid','treasure_uuid','id') "
        "if not pid or not uuid then return end "
        "local srv=pick(rec,'targetServer','serverId','srcServer','server') or %d "
        "local op=pick(rec,'operatorUid','operator','operatorId','uid','userId') "
        "q[#q+1]={pid=pid,uuid=uuid,server=srv,dug=(op~=nil),cross=(tonumber(srv)~=%d)} "
        "CS.UnityEngine.Debug.LogError('ACT treasure_target pid='..tostring(pid)..' uuid='..tostring(uuid)"
        "..' srv='..tostring(srv)..' dug='..tostring(op~=nil)) end "
        "local function walk(t,depth) "
        "local isrec=false for _,k in ipairs({'pointId','point_id','pid','uuid'}) do "
        "if t[k]~=nil then isrec=true end end "
        "if isrec then take(t) return end "
        "if depth<3 then for _,v in pairs(t) do if type(v)=='table' then walk(v,depth+1) end end end end "
        "if m then for _,v in pairs(m.dataDict or {}) do if type(v)=='table' then walk(v,1) end end end "
        "DataCenter.__lw_treasure_queue=q "
        "CS.UnityEngine.Debug.LogError('ACT treasure_parked '..tostring(#q))"
        % (int(home_server), int(home_server))
    )


# --- The watcher: every treasure message the client sees, kept until read ---
# What it is for. A treasure is a RACE and a rarity at once — the chest is out for
# minutes, the alliance digs it together, and the whole exchange is over before anybody
# can start a sniffer. So the messages have to be caught by something that was already
# listening, and kept until a person gets round to reading them. That is this: a hook on
# the client's own two network doors, writing into a ring buffer that lives in the game
# VM, drained by whoever asks.
#
# WHY THE BUFFER IS IN THE GAME AND NOT IN THE PANEL. The panel is restarted, switched
# profiles, minimised and closed; the client is not. A buffer on the panel's side loses
# exactly the messages that arrive while nobody is looking, which is every message worth
# having. In the VM it survives a panel restart and costs a table.
#
# WHAT IT HOOKS. `SFSNetwork.SendMessage(cmd, ...)` and `SFSNetwork.HandleMessage(cmd,
# obj, ...)` — both plain dot-functions taking the command name first, confirmed in the
# 2026-08-07 «сбор сокровища» trace where every send and every push goes through them
# (docs/research/world-treasures.md). Hooking the pair catches the whole ability without
# knowing which manager fires it: the dig march goes out through `MarchUtil.
# SendCreateMarchMessage`, which itself calls `SFSNetwork.SendMessage`.
#
# NOT AT THE SAME TIME AS THE TRACER. `lua_trace` wraps ~6500 functions including these
# two. Running both means each unwraps the other's wrapper on the way out, and the loser
# is whichever restored last. Record with ONE of them.
#
# THE FILTER, and why it is names rather than a manager. `wide` off keeps anything whose
# command carries `treasure` or `detect`, plus a `world.march.*` SEND whose target type
# is a treasure march (50 same-server / 182 cross-server). That is the three things a
# person watching wants — the chest appearing, the squad going out, the chest being
# taken — and nothing else. `wide` on keeps every message the client sends or handles,
# for the session where the question is «what did I miss».

#: How many messages the ring holds before the oldest is dropped. Each entry is a
#: command name and a flattened field list, so a few hundred is kilobytes.
TREASURE_WATCH_CAP = 400

#: Target types of a march that is digging a treasure (`MarchTargetType`), the two the
#: filter lets through from `world.march.*`: same server, and cross-server.
TREASURE_MARCH_TARGETS = (50, 182)

# The shared helpers the install chunk defines as locals and the closures capture. Kept
# as one string so the install is readable; `W` is the buffer table, looked up fresh so
# a re-install with a different `wide`/`cap` takes effect without re-wrapping.
_WATCH_HELPERS = r"""
local W = DataCenter.__lw_treasure_watch
local function nowms() local ms=0
  pcall(function() ms=UITimeManager.Instance:GetServerTime() end)
  ms = math.floor(tonumber(ms) or 0)
  if ms <= 0 then ms = (tonumber(ChatInterface.getServerTime()) or 0) * 1000 end
  return ms end
local function short(v)
  local s = tostring(v)
  if #s > 160 then s = s:sub(1,160) .. "..." end
  return s end
local function keep(dir, cmd, a1, a2)
  if not W.on then return false end
  if type(cmd) ~= "string" then return false end
  if W.wide then return true end
  if cmd:find("treasure", 1, true) or cmd:find("detect", 1, true) then return true end
  if dir == "out" and cmd:find("world.march.", 1, true) then
    for _, want in ipairs(W.marches or {}) do
      if tonumber(a1) == want or tonumber(a2) == want then return true end
    end
  end
  return false end
-- READ A MESSAGE BODY WHICHEVER SHAPE IT IS. An outgoing message is an SFSObject and
-- answers `SFSObject.GetKeys`; an INCOMING one, by the time `HandleMessage` gets it, is
-- a plain Lua table and answers nothing at all — `GetKeys` returns empty, so every push
-- the ring recorded came out with `f=""` and the harvest below could never read a uuid.
-- Found live on 2026-08-08 with a probe on a real `push.detect.treasure.claim`:
-- `KEYS[] PAIRS[operator=table uuid=…]` (#1296). So both are tried, SFSObject first.
local function getdata(obj, k)
  local v
  local ok = pcall(function() v = SFSObject.GetData(obj, k) end)
  if ok and v ~= nil then return v end
  ok = pcall(function() v = obj[k] end)
  if ok then return v end
  return nil end
local function fields(obj)
  local out = {}
  local keys = nil
  pcall(function()
    local ks = SFSObject.GetKeys(obj)
    if ks ~= nil and #ks > 0 then keys = ks end
  end)
  if keys ~= nil then
    for i, k in ipairs(keys) do
      if i > 24 then break end
      local v = getdata(obj, k)
      if type(v) == "table" then v = "{...}" end
      out[#out+1] = tostring(k) .. "=" .. short(v)
    end
  else
    pcall(function()
      local seen = 0
      for k, v in pairs(obj) do
        seen = seen + 1
        if seen > 24 then break end
        if type(v) == "table" then v = "{...}" end
        out[#out+1] = tostring(k) .. "=" .. short(v)
      end
    end)
  end
  return table.concat(out, " ") end
local function args(...)
  local out = {}
  local n = select("#", ...)
  if n > 8 then n = 8 end
  for i = 1, n do
    local v = select(i, ...)
    if type(v) == "table" then v = "{...}" end
    out[#out+1] = "a" .. i .. "=" .. short(v)
  end
  return table.concat(out, " ") end
local function push(dir, cmd, info)
  W.seq = (W.seq or 0) + 1
  W.items[#W.items+1] = {i=W.seq, t=nowms(), d=dir, c=tostring(cmd), f=info}
  while #W.items > (W.cap or 400) do
    table.remove(W.items, 1)
    W.drop = (W.drop or 0) + 1
  end end
local function jint(s, k)
  return tonumber(s:match('"' .. k .. '"%s*:%s*(%-?%d+)')) end
-- …and the same field when the client quotes it. `treasureId` is a NUMBER written as a
-- string in the share blob ("treasureId":"25193"), and it is the chest's TYPE — the one
-- thing a day-limit refusal is actually about (#2092), so it is read wherever it travels.
local function jnum(s, k)
  return tonumber(s:match('"' .. k .. '"%s*:%s*"?(%-?%d+)"?')) end
local function harvest(cmd, obj)
  local A = DataCenter.__lw_treasure_auto
  if not A or not A.on then return end
  if type(cmd) ~= "string" then return end
  if not cmd:find("treasure", 1, true) then return end
  -- A REFUSED CLAIM IS NOT SILENT AFTER ALL (#1296, caught on a live map). The reply to
  -- `detect.event.claim.treasure` comes back under the same name, and when the server
  -- says no it carries `errorCode` and `errorMsg` — the first one seen was
  -- `801354 player not in same alliance`. It names no chest, so it cannot be pinned on a
  -- target; what it CAN do is turn «nothing happened» into the server's own sentence, so
  -- the run says why instead of retrying four times into the dark.
  if cmd == "detect.event.claim.treasure" then
    local code = getdata(obj, "errorCode")
    if code ~= nil and tostring(code) ~= "0" then
      A.last_error = tostring(code) .. " " .. tostring(getdata(obj, "errorMsg") or "")
      A.last_error_at = nowms()
      -- …AND IT IS PINNED ON A CHEST AFTER ALL (#1318). The reply names none, which is why
      -- this used to be a floating sentence in a log — but the claim that provoked it has a
      -- name, and the watch writes down which chest it claimed last (`A.claim_uuid`). That
      -- is enough for the two codes that are verdicts: «claim repeat» is a chest this
      -- account already has, and «not in same alliance» is one it never had. Both end a
      -- retry loop that would otherwise run until the chest expired.
      --
      -- Only while the claim is FRESH: a code arriving a minute later belongs to whatever
      -- was claimed since, and pinning it on the wrong chest would write off a good one.
      --
      -- AND IT IS KEPT AS TEXT (#1898). `tonumber` was here, and two of the four codes
      -- this reply can carry are not numbers — `E100123 treasure is null` and
      -- `detect_dig_err_01 treasure not complete` both became `nil` and were dropped
      -- without a word, which is how a client came to send 25 claims over 287 s at a
      -- chest the server had said was not there on the first one.
      local key = A.claim_uuid
      if key ~= nil and (tonumber(A.claim_at) or 0) > 0
         and nowms() - A.claim_at < 15000 then
        for _, t in ipairs(A.targets or {}) do
          if tostring(t.uuid) == tostring(key) then t.err = tostring(code) end
        end
      end
    end
  end
  if cmd:find("claim", 1, true) then
    -- The alliance's own feed of the dig: one of these per member who has finished
    -- their part. It is NOT «somebody else took it» — every digger claims their own
    -- gift — so it is read as «this chest is dug and payable», never as a loss.
    local u = getdata(obj, "uuid")
    if u == nil then return end
    local key = tostring(u)
    -- A CHEST THE GAME HAS ALREADY SAID IS FINISHED IS NOT NEWS (#1898). The dig feed
    -- carries one message per member who finishes their part, so a chest this account has
    -- been paid for — or one the server has said is not there at all — goes on being
    -- announced after there is anything left to do about it. The ledger is what the three
    -- doors share; without it the queue re-opens a spent chest the moment the prune drops
    -- it, and the errand goes back to claiming into the dark.
    -- …and NOT by returning early: the same message is the beat every OTHER live chest
    -- is answered on, so the tick at the bottom still runs.
    local spent = ((A.spent or {})[key] ~= nil)
    local known = false
    for _, t in ipairs(A.targets or {}) do
      if tostring(t.uuid) == key and not t.done then known = true
        if not t.dug then t.dug, t.dug_by = nowms(), "push" end
        -- THE STATUS BRANCH, DECIDED THE SECOND IT IS HEARD (#1886): a chest that is dug
        -- and has no squad of ours out is CLAIMED, never marched at. A chest whose squad
        -- is on the road keeps the rule #1296 bought and waits for its own legs.
        if t.sent == nil and t.plan == nil then t.plan = "claim" end
      end
    end
    -- A CHEST NOBODY SHARED IS STILL A CHEST (#1296, learned on the first live one).
    -- The alliance dug a treasure for twenty minutes and not one `world.treasure.share.
    -- chat` crossed the wire — the share is a thing a PLAYER does, and often nobody
    -- does it. This broadcast, on the other hand, arrives once per member who finishes,
    -- and it carries the two things a CLAIM needs: the uuid and (from us) the server.
    -- It cannot carry a march — there is no tile in it — so the target is parked
    -- `claim_only`, and the step claims it without ever pretending a squad was sent.
    -- That is exactly the path that took a live chest on 2026-08-08 by hand.
    A.seen = A.seen or {}
    if not known and not spent and not A.seen[key] then
      A.seen[key] = nowms()
      A.targets = A.targets or {}
        local cfg = tonumber(getdata(obj, "treasureId"))
                  or tonumber(getdata(obj, "cfgId")) or 0
      A.targets[#A.targets+1] = {uuid = u, pid = 0, x = 0, y = 0, server = 0,
                                 at = nowms(), dug = nowms(), dug_by = "push",
                                 claim_only = true, plan = "claim", src = "dig-feed",
                                 cfg = cfg}
      A.news = (A.news or 0) + 1
    end
    -- …AND IT IS ANSWERED IN THE SAME FRAME IT ARRIVED. The watch would get to this chest
    -- within a fifth of a second and the panel within ten, and neither is «мгновенно»
    -- when the claim could leave on the message that opened it. So the tick is run right
    -- here, inside the hook: heard and claimed are one instant, and everything the claim
    -- needs was already on the table.
    pcall(function() if A.tick ~= nil then A.tick() end end)
    return
  end
  -- The announcement. A chest shared into alliance chat travels as an ordinary chat
  -- post whose `attachmentId` is a JSON blob; which key it arrives under is not
  -- guaranteed, so every string field is looked at and the one that carries a
  -- `shareType` with a `uuid` wins. Nothing else in the message is read.
  local blob
  local function look(v)
    if type(v) == "string" and v:find("shareType", 1, true)
       and v:find("uuid", 1, true) then blob = v end end
  local keys = nil
  pcall(function()
    local ks = SFSObject.GetKeys(obj)
    if ks ~= nil and #ks > 0 then keys = ks end end)
  if keys ~= nil then
    for _, k in ipairs(keys) do look(getdata(obj, k)) end
  else
    pcall(function() for _, v in pairs(obj) do look(v) end end)
  end
  if blob == nil then return end
  local uuid, x, y = jint(blob, "uuid"), jint(blob, "x"), jint(blob, "y")
  if uuid == nil or x == nil or y == nil then return end
  local key = tostring(uuid)
  A.seen = A.seen or {}
  -- …and the same ledger here: a share is posted by a PERSON, often minutes after the
  -- chest was taken (#1898).
  if A.seen[key] or (A.spent or {})[key] ~= nil then return end
  A.seen[key] = nowms()
  local pid = 0
  pcall(function()
    pid = SceneUtils.TilePosToIndex(CS.UnityEngine.Vector2Int(x, y)) end)
  local sid = jint(blob, "sid")
  A.targets = A.targets or {}
  A.targets[#A.targets+1] = {uuid=uuid, pid=pid, x=x, y=y,
                             server=sid or 0, at=nowms(), src="chat",
                             cfg=jnum(blob, "treasureId") or 0}
  A.news = (A.news or 0) + 1
end
"""


def treasure_watch_install(cap: int = TREASURE_WATCH_CAP) -> str:
    """Start (or re-arm) the watcher, and say what it is now — `ACT treasure_watch …`.

    Idempotent by construction: the two doors are wrapped once and the wrappers read
    `W.wide` / `W.cap` out of the buffer table on every call, so pressing this again
    with a different `DataCenter.__lw_treasure_watch_wide` changes what is kept without
    a second layer of wrapping. Nothing already in the ring is thrown away.

    The whole hook body is inside `pcall`, and a hook that throws must never break the
    client's networking: the original is called outside the guard, so a bug here costs
    a missing log line and not a dropped message.

    TWO CONSUMERS SHARE THE ONE HOOK (#1296). The ring buffer above is the debug page's;
    the auto-treasure errand needs the same two doors to hear a chest being announced,
    and a SECOND pair of wrappers on the same functions is how an unwrap loses a hook.
    So `harvest` runs from the same wrapper, gated on its own switch
    (`DataCenter.__lw_treasure_auto.on`) rather than on `W.on` — the auto errand listens
    with the ring off, and the ring records with the auto errand off.
    """
    return (
        "local D = DataCenter "
        "if not D.__lw_treasure_watch then D.__lw_treasure_watch = "
        "{seq=0, drop=0, items={}, on=false} end "
        "D.__lw_treasure_watch.cap = " + str(int(cap)) + " "
        "D.__lw_treasure_watch.wide = D.__lw_treasure_watch_wide and true or false "
        "D.__lw_treasure_watch.marches = {"
        + ",".join(str(int(t)) for t in TREASURE_MARCH_TARGETS) + "} "
        + _WATCH_HELPERS +
        "if not W.hooked then "
        "W.origSend = SFSNetwork.SendMessage "
        "W.origRecv = SFSNetwork.HandleMessage "
        "SFSNetwork.SendMessage = function(cmd, ...) "
        "local okk, want = pcall(keep, 'out', cmd, (select(1, ...)), (select(2, ...))) "
        "if okk and want then local oka, info = pcall(args, ...) "
        "if oka then pcall(push, 'out', cmd, info) end end "
        "return W.origSend(cmd, ...) end "
        "SFSNetwork.HandleMessage = function(cmd, obj, ...) "
        "local okk, want = pcall(keep, 'in', cmd, nil) "
        "if okk and want then local okf, info = pcall(fields, obj) "
        "if okf then pcall(push, 'in', cmd, info) end end "
        "pcall(harvest, cmd, obj) "
        "return W.origRecv(cmd, obj, ...) end "
        "W.hooked = true end "
        "W.on = true "
        'CS.UnityEngine.Debug.LogError("ACT treasure_watch on=1 wide="'
        '..tostring(W.wide and 1 or 0).." cap="..tostring(W.cap)'
        '.." buf="..tostring(#W.items))'
    )


def treasure_watch_stop() -> str:
    """Stop keeping messages, and put the client's two doors back as they were.

    The wrappers are removed rather than left recording into a buffer nobody drains: a
    hook that stays on is a hook the next person has to remember about, and the tracer
    would then wrap a wrapper. What is already in the ring survives — stopping is not
    the same as throwing away, and the last thing recorded is usually the interesting
    one.

    THE DOORS ARE ONLY PUT BACK WHEN NOBODY ELSE IS LISTENING (#1296). The auto-treasure
    errand hears a chest through this same pair of wrappers, so unhooking while its
    switch is on would leave it deaf with nothing on screen to say so. Then the ring is
    merely muted (`on = false`) and the reply says `hooked=1`, which is the honest
    answer: the recording stopped, the hook did not.
    """
    return (
        "local W = DataCenter.__lw_treasure_watch "
        "local A = DataCenter.__lw_treasure_auto "
        "local auto = (A ~= nil and A.on) and true or false "
        "if W then W.on = false "
        "if W.hooked and not auto then "
        "if W.origSend then SFSNetwork.SendMessage = W.origSend end "
        "if W.origRecv then SFSNetwork.HandleMessage = W.origRecv end "
        "W.hooked = false end end "
        'CS.UnityEngine.Debug.LogError("ACT treasure_watch on=0 hooked="'
        "..tostring(((W or {}).hooked) and 1 or 0)"
        '.." auto="..tostring(auto and 1 or 0)'
        '.." buf="..tostring(#((W or {}).items or {})))'
    )


def treasure_watch_drain(limit: int = 25, budget: int = 6000) -> str:
    """Lua *expression* -> a JSON object of the oldest messages, REMOVING them.

    Shaped for `READ_LUA … INTO feed`: one value, one line, no newline in it. The reader
    gets ``{"on":0|1,"wide":0|1,"n":<taken>,"more":<still queued>,"drop":<dropped since
    the last drain>,"seq":<total ever>,"items":[{"i","t","d","c","f"}…]}`` — `t` is the
    GAME's clock in milliseconds (`docs/research/game-clock.md`; the PC's lies), `d` is
    `in`/`out`, `c` the command and `f` its fields flattened to `k=v` pairs.

    TWO CAPS, because the answer travels as one log line. `limit` is how many entries at
    most, `budget` how many characters at most — whichever is reached first stops the
    drain and the rest is reported as `more`, so a caller loops until `more` is zero
    instead of losing the tail to a truncated line. `drop` is reported once and cleared:
    it is the ring's own confession that it overflowed, and it must not be counted twice.
    """
    return (
        "(function() "
        "local W = DataCenter.__lw_treasure_watch "
        'if not W then return \'{"on":0,"wide":0,"n":0,"more":0,"drop":0,"seq":0,"items":[]}\' end '
        "local function q(s) s = tostring(s or '') "
        "if #s > 400 then s = s:sub(1,400) .. '...' end "
        "s = s:gsub('\\\\', '\\\\\\\\'):gsub('\"', '\\\\\"'):gsub('%c', ' ') "
        "return '\"' .. s .. '\"' end "
        "local items = W.items or {} "
        "local parts, used = {}, 0 "
        "while #parts < " + str(int(limit)) + " and #items > 0 and used < "
        + str(int(budget)) + " do "
        "local it = table.remove(items, 1) "
        "local one = '{\"i\":' .. tostring(it.i or 0) .. ',\"t\":' .. tostring(it.t or 0) "
        ".. ',\"d\":' .. q(it.d) .. ',\"c\":' .. q(it.c) .. ',\"f\":' .. q(it.f) .. '}' "
        "used = used + #one "
        "parts[#parts+1] = one end "
        "local drop = W.drop or 0 W.drop = 0 "
        "return '{\"on\":' .. tostring(W.on and 1 or 0) "
        ".. ',\"wide\":' .. tostring(W.wide and 1 or 0) "
        ".. ',\"n\":' .. tostring(#parts) "
        ".. ',\"more\":' .. tostring(#items) "
        ".. ',\"drop\":' .. tostring(drop) "
        ".. ',\"seq\":' .. tostring(W.seq or 0) "
        ".. ',\"items\":[' .. table.concat(parts, ',') .. ']}' "
        "end)()"
    )


def treasure_watch_state() -> str:
    """Lua *expression* -> `on=<0|1> wide=<0|1> buf=<n> seq=<n> drop=<n> cap=<n>`.

    A look that changes nothing — what the drain would say, without spending the ring.
    Used to answer «is it listening?» after a client restart, which wipes the buffer
    along with the rest of the VM and is the one thing a person cannot tell by waiting.
    """
    return (
        "(function() local W = DataCenter.__lw_treasure_watch "
        "if not W then return 'on=0 wide=0 buf=0 seq=0 drop=0 cap=0' end "
        "return 'on=' .. tostring(W.on and 1 or 0) "
        ".. ' wide=' .. tostring(W.wide and 1 or 0) "
        ".. ' buf=' .. tostring(#(W.items or {})) "
        ".. ' seq=' .. tostring(W.seq or 0) "
        ".. ' drop=' .. tostring(W.drop or 0) "
        ".. ' cap=' .. tostring(W.cap or 0) end)()"
    )


# --- The auto errand: a chest announced -> a squad out -> the gift taken ------
# The three moments of the ability, driven by the client's own announcement instead of
# by a sweep of the map (#1296, docs/research/world-treasures.md).
#
# WHY IT IS NOT A MAP SWEEP. A chest is out for minutes and the alliance digs it
# together; a poll of the world would have to re-ask the map every few seconds to catch
# one, which costs a `world.get.block` round trip per look and still arrives late. The
# client is already told the moment a chest is shared into alliance chat — the trace of
# 2026-08-08 has the whole exchange in four messages — so the ear goes where the news
# already lands: the hook above, and a Lua table the errand reads. The «poll» this ships
# with reads that LOCAL table, one expression through the daemon, and never touches the
# network.
#
# WHY IT CANNOT BE A WIRE TRIGGER. The announcement is a chat post, and the chat
# broadcast rides a TLS websocket this repository cannot sniff
# (`docs/research/chat-system.md`): the 2026-08-08 capture has the message in the Lua
# trace and NOT on the wire beside it. So `panel/triggers.py`'s ordinary wire listener
# is deaf to it by construction, and the poll is not a shortcut — it is the only door.
#
# THE STATE, all of it in the game VM so a panel restart loses nothing:
#
#     DataCenter.__lw_treasure_auto = {
#       on      = true,                 -- the harvest switch (see treasure_watch_install)
#       seen    = { ["<uuid>"] = <ms> },-- announcements already turned into a target
#       news    = <n>,                  -- how many the hook has added, ever
#       targets = { { uuid, pid, x, y, server, at,   -- the announcement
#                     sent, squad,                  -- the march that went out
#                     dug,                          -- push.detect.treasure.claim seen
#                     claimed, done, why } },
#     }
#
# Each target walks new -> sent -> (dug) -> claimed -> done, and every step is written
# down where the next run can read it, because a run may be interrupted at any point:
# the errand is idempotent by state, not by luck.

#: How long after the march goes out the claim may be tried even though no
#: `push.detect.treasure.claim` was heard for that chest. The push is the honest gate
#: and this is the fallback: the alliance's feed may have arrived while the client was
#: reconnecting, and a chest that is dug and never claimed is the whole reward lost.
TREASURE_ARRIVE_GRACE_SEC = 240

#: How long a target is worked before it is written off. A chest that is neither claimed
#: nor dug by then is gone from the map — the point expires — and keeping it would mean
#: sending squads at an empty tile for ever.
TREASURE_TARGET_TTL_SEC = 1800

#: How long between two claims on the same chest, in milliseconds, by try number — and
#: there is no longer a cap on the tries (#1318). «Продолжать попытки, пока сокровище не
#: будет взято или не исчезнет»: the four-try cap wrote a chest off while it was still on
#: the map, which is the whole reward lost for a reason that mends itself in seconds. So a
#: chest is now worked until it is PAID (the reward window, or the server's own «claim
#: repeat») or until it is gone (its own `expireTime`, or the ttl), and the ramp is what
#: keeps that from being a flood: the first retries are fast because the interesting case
#: is a claim that raced the server by a fraction of a second, and the tail is slow because
#: a chest that has refused eight times is refusing for a reason a ninth send will not fix.
TREASURE_CLAIM_RAMP_MS = (500, 1000, 2000, 4000, 8000, 15000)

#: How long between two claims on the same chest once the ramp above is spent.
TREASURE_CLAIM_RETRY_SEC = 15

#: How long after a claim the reward window still counts as ITS reward. A refused claim
#: says nothing at all — measured live on 2026-08-08 against a uuid that cannot exist: no
#: message tip, no window, no error, and the reply comes back under the same command name
#: with no readable fields. So «did it pay?» has exactly one observable answer, the
#: `UIGiftPackageRewardGet` the client raises on a successful claim, and it is only read
#: as ours while it is this fresh — any window later than that could be any other reward.
TREASURE_PAID_WINDOW_SEC = 20

#: How long a march is given to APPEAR before its absence is believed. A squad whose
#: march the server has not confirmed yet still reads free — measured live on 2026-08-08:
#: the send went out at 21:01:50, the report five seconds later said `free=3 busy=0`, and
#: `GetOwnerFormationMarch` answered nil for a march that was on its way. So «no march» in
#: the first seconds after a send means «not answered yet», never «over», and a claim let
#: through by that reading is refused in the silence a refusal comes in. Twenty seconds is
#: comfortably longer than a server ever took to answer here, and shorter than the retry —
#: so it costs a chest nothing.
TREASURE_MARCH_SETTLE_SEC = 20

#: …and what that silence means once it has lasted (#1318). A march that never appears is
#: not a march that is over — it is a send the client DROPPED, which it does without a word
#: for a formation already committed (`docs/research/world-treasures.md`). Before this, the
#: settle above turned exactly that case into «the squad has been and come back», and the
#: claim went out into a road nobody had walked: «отправка отряда работает через раз» is
#: this, seen from the player's chair. So a send with no march behind it is re-sent instead,
#: and a chest that has swallowed this many sends is written off with a word that says so.
TREASURE_RESEND_TRIES = 3

#: HOW MANY CLAIMS A CHEST THAT IS ALREADY DUG GETS BEFORE A SQUAD IS SPENT ON IT (#1886).
#: `ownerUid` used to be a hint that opened the claim without closing the march, because
#: «a gate needs a success recording» and there was none. There is one now, and it cost a
#: hundred seconds: on 2026-08-23 a chest of this alliance's own was seen already dug the
#: second the client reached the map, four marches were sent at it and NONE of them ever
#: appeared (`march-unanswered` — the game drops a dig march at a chest whose dig is over),
#: and the blind claim the resend ladder finally reached was PAID on its first try —
#: `lag=99974ms`. So a dug chest is claimed first and marched at only if the server refuses
#: this many times, which costs the other case about the length of the ramp below.
TREASURE_CLAIM_FIRST_TRIES = 3

#: `MarchStatus.TREASURE_DIGGING` (`docs/research/squad-state.md`). A march in this state
#: carries the dig's OWN deadline in `endTime` — the moment the chest finishes being dug —
#: which is the whole of the timing this errand is built on: the claim is scheduled AT that
#: millisecond rather than discovered by a panel that happens to look afterwards.
TREASURE_DIG_STATUS = 19

#: `MarchStatus.BACK_HOME` — the squad's dig is over and it is walking home. The fallback
#: reading of «our part is done» for a client that never showed the digging state.
TREASURE_HOME_STATUS = 4

#: How early a known dig deadline is pinned with a one-shot of the game's own timer, in
#: milliseconds. The watch below already runs every fifth of a second while a chest is
#: live; this is what turns «within 200 ms» into «in the frame the dig ends», and it is
#: only armed for a deadline that is actually near, so a chest an hour out costs nothing.
TREASURE_DUE_ARM_MS = 5000

#: The server's own answers to a claim, and FIVE of them are VERDICTS rather than noise
#: (#1318, #1898, #1965). `801348 claim repeat` means this account has already had this chest —
#: which is a paid chest seen from the other side, and the one honest end to a retry loop
#: when the reward window was missed. `801354 player not in same alliance` means the chest
#: was never ours to take. `E100123 treasure is null` is the server saying the chest does
#: not exist any more: taken, expired, or gone from the map. `detect_dig_err_01 treasure
#: not complete` is the opposite verdict — the chest is there and the dig is NOT over, so
#: whatever stamped it «dug» was wrong. Anything else is a refusal worth retrying.
#:
#: THEY ARE STRINGS, AND THAT IS THE WHOLE OF #1898. Two of the four do not parse as
#: numbers, and the code that read them did `tonumber(code)` — so `E100123` arrived as
#: `nil` and was dropped in silence, and one live client sent 25 claims over 287 s at a
#: chest the server had already said was not there, every single reply saying so. A code
#: is compared as text from here on, whatever shape it has.
#:
#: THE FIFTH IS A DAY, NOT A CHEST (#1965). `activity_sports_uitips_015 day times limit N`
#: is the day's allowance of REWARDS being used up, and it says nothing at all about the
#: tile it was sent for: the chest is still there, still diggable, and nothing this errand
#: sends will be paid for it until the day resets. It is therefore neither a `gone` nor a
#: retry — the chest is HELD, and the hold ends at the game's own reset stamp.
TREASURE_ERR_CLAIM_REPEAT = "801348"
TREASURE_ERR_NOT_IN_ALLIANCE = "801354"
TREASURE_ERR_TREASURE_NULL = "E100123"
TREASURE_ERR_NOT_COMPLETE = "detect_dig_err_01"
TREASURE_ERR_DAY_LIMIT = "activity_sports_uitips_015"

#: THE ALLOWANCE IS PER TREASURE GROUP, AND THAT IS A MEASUREMENT (#1965, read live off
#: `ActDetectTreasureDataManager` on 2026-08-25 while the refusals were arriving):
#: `dailyGot` held two counters, `602 = 10` and `39 = 9`, and the client's own gate
#: answered `CheckTreasureReachDailyLimit(602) = true` with `(39) = false` in the same
#: read. So it is not one purse for the account and it is not a property of a tile —
#: stopping the whole errand on the first refusal would write off a group that still had
#: room, and writing the chest off for good would lose it after the reset.
#:
#: The two halves that follow from that are both in `_TREASURE_TICK`: the chest that was
#: refused is held until the reset (its group is full, whichever one it is), and the whole
#: errand stands down only when EVERY counter the client keeps says full.
#:
#: AND THE HOLD IS THE TYPE'S, NOT THE CHEST'S (#2092). Holding the one chest that was
#: refused left every other chest of the same kind to be marched at and refused in its own
#: turn — the errand going on catching a type that cannot pay, which is what was reported.
#: `A.day_bad` shuts the KIND (the chest's own cfg id, carried from all three doors) until
#: the reset, filled by the server's refusal and by the client's own
#: `CheckTreasureReachDailyLimit(<cfgId>)`, and stamped with `activity_detect_dig_times_
#: expire` so the stamp moving opens every type at once.
#:
#: THE SERVER'S REFUSAL IS THE WORKING HALF, measured 2026-09-01: `dailyGot` is keyed by a
#: GROUP id (a small number) while a chest carries a `25193`-shaped cfg id, and
#: `TreasureTemplateManager` is not reachable as a global, so nothing maps one to the
#: other. The gate is still asked with the chest's cfg — one guarded local call, no message
#: leaves — because a build whose gate accepts one would shut the type before the first
#: refusal is paid for. Wire the mapping in here if it is ever found.
#:
#: The reset is the game's own and is never computed here: the same manager carries
#: `activity_detect_dig_times_expire`, read live as `1787709600000` = 2026-08-26 02:00 UTC,
#: the ordinary daily boundary. A client that cannot be asked (no manager yet) falls back
#: to a short hold rather than to a guess about somebody's midnight.
TREASURE_DAY_LIMIT_ASK_MS = 5000
TREASURE_DAY_LIMIT_BLIND_MS = 3600 * 1000

#: How often the in-game watch looks while a chest is live, and while none is, in seconds.
#: The busy period is what the acceptance criterion rests on — «ВСЕ сокровища всегда забраны
#: в первую секунду» — and it costs one `GetOwnerFormationMarch` per chest out.
TREASURE_REAP_FAST_SEC = 0.2
TREASURE_REAP_IDLE_SEC = 2.0

#: How long the watch keeps looping with nothing to work before it stops itself. It is a
#: self-rescheduling timer inside somebody's game client, so it must have an end: the
#: panel's own poll re-arms it on the next tick, and a panel that has been closed leaves
#: nothing running a quarter of an hour later.
TREASURE_REAP_STOP_SEC = 900

#: `WorldPointType.TREASURE` — the same number the wire calls `f2` and the pcap scanner
#: filters on (docs/research/world-treasures.md).
TREASURE_POINT_TYPE = 21

#: The box the watch reads around the camera, and how often — the SECOND ear (#1318).
#: Half the width of the press the panel makes (`TREASURE_LOOK_BOX`) because this one runs
#: inside the game between panel ticks: 41 × 41 tiles is about four milliseconds, against
#: the thirty-odd of the full one. It never moves the camera and never asks the server.
TREASURE_REAP_LOOK_BOX = 20
TREASURE_REAP_LOOK_SEC = 3


def treasure_auto_arm(squads=(1, 2, 3, 4),
                      grace_sec: int = TREASURE_ARRIVE_GRACE_SEC,
                      ttl_sec: int = TREASURE_TARGET_TTL_SEC) -> str:
    """Switch the harvest on and park what the errand is allowed to spend.

    `squads` is which squad slots may be sent, in the order they may be spent — the
    1/2/3/4 the player sees in the dispatch panel, same meaning as the rally's.

    Idempotent, and deliberately does NOT clear the targets: an arm is what a restarted
    panel does on its first tick, and throwing the queue away there would lose a chest
    that was announced while nothing was watching.
    """
    slots = ",".join(str(int(s)) for s in squads) or "1,2,3,4"
    return (
        "local D = DataCenter "
        "if not D.__lw_treasure_auto then D.__lw_treasure_auto = "
        "{seen={}, targets={}, news=0} end "
        "local A = D.__lw_treasure_auto "
        "A.on = true "
        "A.squads = {" + slots + "} "
        "A.grace = " + str(int(grace_sec)) + " "
        "A.ttl = " + str(int(ttl_sec)) + " "
        'CS.UnityEngine.Debug.LogError("ACT treasure_auto on=1 squads="'
        '..tostring(#A.squads).." queued="..tostring(#(A.targets or {}))'
        '.." news="..tostring(A.news or 0))'
    )


def treasure_auto_arm_parked() -> str:
    """The same arm, reading its settings out of what the recipe parked first.

    A `TAP` carries no arguments (`docs/dsl.md`), so the values a recipe was given travel
    the way the rally's squads travel: parked on the VM ahead of the press and read here.

      * `DataCenter.__lw_treasure_squads` — the slots that may be spent, a Lua list;
      * `DataCenter.__lw_treasure_grace`  — seconds after the march before a claim may be
                                            tried without having heard the dig;
      * `DataCenter.__lw_treasure_ttl`    — seconds a chest is worked before it is written
                                            off as gone from the map.

    Each falls back to the built-in default when nothing was parked, so the button is
    pressable on its own from the Scenarios page.
    """
    return (
        # The claim half is parked here, on every arm — the definition IS the deployment
        # (#1318). A client running since before an edit to this file would otherwise go on
        # claiming by last week's rules with nothing on screen to say so.
        _TREASURE_TICK +
        "local D = DataCenter "
        "if not D.__lw_treasure_auto then D.__lw_treasure_auto = "
        "{seen={}, targets={}, news=0} end "
        "local A = D.__lw_treasure_auto "
        "A.on = true "
        "local s = D.__lw_treasure_squads "
        "if type(s) ~= 'table' or #s == 0 then s = {1,2,3,4} end "
        "A.squads = s "
        "A.grace = tonumber(D.__lw_treasure_grace) or "
        + str(int(TREASURE_ARRIVE_GRACE_SEC)) + " "
        "A.ttl = tonumber(D.__lw_treasure_ttl) or "
        + str(int(TREASURE_TARGET_TTL_SEC)) + " "
        'CS.UnityEngine.Debug.LogError("ACT treasure_auto on=1 squads="'
        '..tostring(#A.squads).." grace="..tostring(A.grace)'
        '.." queued="..tostring(#(A.targets or {}))'
        '.." news="..tostring(A.news or 0))'
    )


def treasure_auto_disarm() -> str:
    """Switch the harvest off; the queue and the hook are left as they are.

    Off means «stop turning announcements into targets», not «forget what you know»: a
    target already halfway through — a squad out, the gift not taken — is still worth
    finishing by hand, and the debug page can still read the queue.
    """
    return (
        "local A = DataCenter.__lw_treasure_auto "
        "if A then A.on = false end "
        'CS.UnityEngine.Debug.LogError("ACT treasure_auto on=0 queued="'
        "..tostring(#((A or {}).targets or {})))"
    )


def treasure_auto_check() -> str:
    """Lua *expression* -> true when the auto errand has something to do right now.

    What the poll trigger asks every few seconds. It reads LOCAL state only — no send,
    no map, no window — so the cost is one daemon round trip (~0.15 s with the daemon
    free) and nothing the game can notice.

    True in two cases, and only the first is the obvious one:

      * **an unfinished target** — a chest is queued and its next step is owed;
      * **no ear at all** — a client restart wipes the VM and with it the hook, and a
        poll that only ever asked about targets would then wait for ever for a chest it
        could not hear. So «nobody is listening» is itself work, and the errand's first
        step is to arm.

    IT USED TO BE THREE, AND THE THIRD ONE TOOK THE CLIENT AWAY FROM EVERYTHING ELSE
    (#2390). «The client is in the WORLD» was reason enough to run, every tick — on the
    grounds that looking is one box of the point manager and costs a hundredth of a
    second. What actually ran was the WHOLE errand, and measured against a golden-zombie
    hunt, which keeps the client in the world for as long as it lasts: **53 runs in 44
    minutes, 1096 s of the client — 42 % of the wall clock — every one of them ending
    «nothing was sent this run»**, with the day's own allowance already full. The chain
    it was starving got four and a half minutes into its first target in that time.

    The operator's decision, in their words: **«клады должны только по пушам
    определяться, там нечему отбирать управление»**. So the errand is what it says on the
    tin — an answer to something HEARD. The ear is the in-client hook on the chat share
    (#1277), because the announcement rides a TLS websocket this repository cannot decode
    and a wire listener is deaf to it by construction
    (`docs/research/world-treasures.md`); what this poll does is read the panel's own
    table in the VM, which is a local read of about 0.15 s and never a run.

    **What that closes is the «simply found» door**: a chest nobody announced is no
    longer looked for on a tick. It is still found by anything that plays the errand for
    another reason — a person's press, a chest heard, the dig feed — and putting the lap
    back means a clock with a period somebody chose out loud, not a poll that fires every
    ten seconds.
    """
    return (
        "(function() "
        "local D = DataCenter "
        "local W = D.__lw_treasure_watch "
        "local A = D.__lw_treasure_auto "
        "if A == nil then return true end "
        # …AND A CHEST THE DAY'S ALLOWANCE IS HOLDING IS NOT WORK (#1965). It is unfinished
        # and will stay unfinished until the reset, so counting it as a reason to run turns
        # the poll into a clock that wakes the errand every few seconds to do nothing. The
        # hold is measured against the game's own stamp, so the day turning over makes the
        # same chest work again with nothing pressed.
        "local until_ms = tonumber(A.day_until) or 0 "
        "local stop = (A.day_full and until_ms > 0) and true or false "
        # A DAY THAT IS SPENT DOES NOT EVEN GET THE ARM (#2390). The two truths below —
        # «the errand is off» and «nothing is listening» — exist so a client restart is
        # noticed; they are not worth the client when there is nothing left to hear TODAY.
        # Measured live: with the allowance full and the queue empty, the errand still ran
        # every 40–90 s, because the arm it performs rewrites this very table and the next
        # poll caught it half-written and read «nobody is listening». So the day is asked
        # FIRST, against the game's own clock, and it re-opens by itself when the stamp
        # passes — no press, no restart.
        "local now = 0 "
        "pcall(function() "
        "now = math.floor(tonumber(UITimeManager.Instance:GetServerTime()) or 0) end) "
        "local shut = (stop and (now <= 0 or now < until_ms)) and true or false "
        "if not shut then "
        "if not A.on then return true end "
        "if W == nil or not W.hooked then return true end end "
        "for _, t in ipairs(A.targets or {}) do if not t.done then "
        # …and neither is a chest whose TYPE the day is full of, whatever its own stamp
        # says: the watch may not have beaten since it was heard (#2092).
        "local cfg = tonumber(t.cfg) or 0 "
        "local bad = (cfg > 0 and until_ms > 0 "
        "and (A.day_bad or {})[tostring(cfg)] ~= nil) and true or false "
        "local held = stop or bad or ((tonumber(t.hold_until) or 0) > 0 "
        "and until_ms > 0 and (tonumber(A.tick_at) or 0) < tonumber(t.hold_until)) "
        "if not held then return true end end end "
        # …AND NOTHING ELSE IS WORK (#2390). Being on the map used to answer «yes» here,
        # which turned an errand into a clock that took the client every ten seconds to
        # find out there was nothing to do — 42 % of the client over a measured 44
        # minutes, against a day whose allowance was already spent. A chest that was
        # never announced is not heard, and this says so.
        "return false end)()"
    )


#: The claim half of the errand, as ONE Lua function parked on the VM (#1318).
#:
#: WHY IT IS A FUNCTION AND NOT A CHUNK. Everything else in this file is a chunk the panel
#: sends when it wants something done, which means it happens when the PANEL looks — and
#: the panel looks every ten seconds, with a twenty-second cooldown behind it. Measured
#: against the criterion the player set («в первую секунду»), that is the whole bug: a
#: chest whose dig finished a tenth of a second after a tick waits out the rest of the tick
#: AND the cooldown before anybody asks. Nothing in the chunk was slow; the QUESTION was
#: being asked late.
#:
#: So the question moved into the client. `A.tick` is defined here, called by the game's
#: own timer every fifth of a second while a chest is live, called again by a one-shot
#: pinned to the exact millisecond a dig ends, and called by the panel's step at the end of
#: every press. All three run the same code and the state they walk is the same table, so
#: two of them landing together costs one extra `GetOwnerFormationMarch` and nothing else.
_TREASURE_TICK = '''
local D = DataCenter
if not D.__lw_treasure_auto then D.__lw_treasure_auto = {seen={}, targets={}, news=0} end
D.__lw_treasure_auto.tick = function()
  local A = DataCenter.__lw_treasure_auto
  if A == nil then return end
  local P = LuaEntry.Player
  -- THE GAME'S CLOCK, never this machine's (docs/research/game-clock.md). Every deadline
  -- compared below — the dig's own `endTime`, the chest's `expireTime` — is stamped by the
  -- server, so a PC running two minutes fast would claim two minutes early, for ever.
  local now = 0
  pcall(function()
    now = math.floor(tonumber(UITimeManager.Instance:GetServerTime()) or 0) end)
  if now <= 0 then pcall(function()
    now = math.floor((tonumber(ChatInterface.getServerTime()) or 0) * 1000) end) end
  if now <= 0 then A.tick_why = "no-clock" return end
  A.tick_at = now
  A.ticks = (tonumber(A.ticks) or 0) + 1
  -- THE DAY'S ALLOWANCE, ASKED OF THE CLIENT RATHER THAN INFERRED FROM A REFUSAL (#1965).
  -- `activity_sports_uitips_015 day times limit N` is the server saying the day's REWARDS
  -- are used up, and the client keeps the same books: `dailyGot` is one counter per
  -- treasure group and `CheckTreasureReachDailyLimit` is the game's own verdict on each.
  -- Read live while the refusals were arriving, the two counters disagreed — `602` full
  -- and `39` not — which is why this is not one flag for the account.
  --
  -- It is a LOCAL read: no message leaves, nothing on screen moves, and it is repeated at
  -- most every few seconds however often the watch beats.
  if (tonumber(A.day_at) or 0) <= 0
     or now - (tonumber(A.day_at) or 0) >= %(day_ask)d
     or (tonumber(A.day_ask_now) or 0) == 1 then
    A.day_at, A.day_ask_now = now, 0
    local dm = DataCenter.ActDetectTreasureDataManager
    if dm == nil then
      A.day_full, A.day_groups, A.day_reset = false, "", 0
    else
      pcall(function() A.day_reset = tonumber(dm.activity_detect_dig_times_expire) or 0 end)
      local full, seen, words = true, 0, {}
      pcall(function()
        for g, got in pairs(dm.dailyGot or {}) do
          seen = seen + 1
          local reached = false
          pcall(function()
            reached = dm:CheckTreasureReachDailyLimit(g) and true or false end)
          words[#words+1] = tostring(g) .. "=" .. tostring(got)
            .. (reached and "/full" or "")
          if not reached then full = false end
        end
      end)
      -- A CLIENT THAT COUNTS NOTHING IS NOT A CLIENT THAT IS FULL. `dailyGot` is filled by
      -- a reply, so a freshly started one tracks no group at all — reading that as «the
      -- day is spent» would stand the errand down on a client that had not been asked.
      if seen == 0 then full = false end
      A.day_full, A.day_groups = full, table.concat(words, ",")
      -- …AND THE SAME QUESTION PER TYPE, WHICH IS THE ONE THE ERRAND ACTS ON (#2092).
      -- The allowance is a counter per treasure TYPE, so «the day's limit» is never a
      -- fact about a chest: the moment one chest of a type is refused, every other chest
      -- of that type — the ones on the list and the ones nobody has heard of yet — is
      -- worth nothing until the reset. `A.day_bad` is that exclusion, keyed by the type's
      -- own cfg id, and it is filled from two places: the client's own gate, asked here
      -- for every type on the list, and the server's refusal, which is the authority and
      -- is kept whatever the client's copy of the books says.
      -- THE EXCLUSION BELONGS TO A DAY, AND THE DAY IS THE GAME'S. `activity_detect_dig_
      -- times_expire` is the boundary this very counter resets at, so the stamp MOVING is
      -- the reset happening — and every type shut against the old stamp is open again,
      -- with nothing pressed and no clock of this machine's consulted.
      local stamp = tonumber(A.day_reset) or 0
      if (tonumber(A.day_bad_stamp) or 0) ~= stamp then
        A.day_bad, A.day_bad_stamp = {}, stamp
      end
      local bad = {}
      for k, v in pairs(A.day_bad or {}) do if v == "server" then bad[k] = "server" end end
      local types = {}
      for _, t in ipairs(A.targets or {}) do
        local c = tonumber(t.cfg) or 0
        if c > 0 and not t.done then types[c] = true end
      end
      for c in pairs(types) do
        local reached = false
        pcall(function()
          reached = dm:CheckTreasureReachDailyLimit(c) and true or false end)
        if reached then bad[tostring(c)] = bad[tostring(c)] or "client" end
      end
      A.day_bad = bad
    end
    -- …and the reset the hold ends at. The game's own stamp where there is one; a short
    -- blind hold where there is not, so a client that cannot be asked retries in an hour
    -- instead of guessing at somebody's midnight.
    if (tonumber(A.day_reset) or 0) <= 0 then
      A.day_blind = now + %(day_blind)d
    else
      A.day_blind = nil
    end
  end
  local day_until = (tonumber(A.day_reset) or 0)
  if day_until <= 0 then day_until = tonumber(A.day_blind) or 0 end
  if day_until > 0 and now >= day_until then
    -- THE RESET HAPPENED AND NOTHING HAD TO BE PRESSED (#1965). Every hold is measured
    -- against the game's own stamp, so the day turning over lifts all of them at once —
    -- no restart, no hand on the panel, and the next beat works the queue it was holding.
    day_until = 0
    A.day_full = false
    -- …and the types with them: the exclusion is the day's, so it ends when the day does.
    A.day_bad = {}
  end
  A.day_until = day_until
  local wm = DataCenter.WorldMarchDataManager
  local home_srv = tonumber(P.serverId) or 0
  local ttl = (tonumber(A.ttl) or %(ttl)d) * 1000
  local grace = (tonumber(A.grace) or %(grace)d) * 1000
  local ramp = {%(ramp)s}
  -- The one observable proof that a claim was PAID: the window the client raises on a
  -- successful one. A refused claim is silent (docs/research/world-treasures.md).
  local reward = false
  pcall(function() reward = UIManager.Instance:IsWindowOpen(
    UIWindowNames.UIGiftPackageRewardGet) and true or false end)
  local live, claimed, paid, expired, waiting, resent, gone = 0, 0, 0, 0, 0, 0, 0
  -- Chests standing still because the day's reward allowance is spent, counted apart from
  -- the ones merely waiting on a squad: the two look identical in a queue and one of them
  -- will not move however long anybody waits (#1965).
  local held = 0
  -- THE THIRD WATCHER OF THE DIG, and the only one that needs nobody to say anything
  -- (#1886). The wire has exactly one hearable dig signal — `push.detect.treasure.claim`,
  -- one per member who finishes — and the map stream that would be the other one is
  -- decoded on the C# side and never reaches `SFSNetwork.HandleMessage`, so no Lua hook
  -- can hear a tile flip. What Lua CAN do is read the tile the client already holds: the
  -- point info for a chest we are tracking carries the finisher (`ownerUid`) the moment
  -- the dig is over. One `GetPointInfo` per tracked chest, five times a second, on tiles
  -- the client has loaded anyway — so a dig nobody broadcast is still caught inside a
  -- fifth of a second instead of at the panel's next look.
  --
  -- It is a BACKSTOP and not the gate, and the limit is worth knowing: the point manager
  -- only answers for tiles the client is currently holding, so a chest the camera has
  -- walked away from reads `nil` and nothing is stamped. Costing nothing when it cannot
  -- answer is the whole reason it may run on every beat.
  local pm = nil
  pcall(function() pm = _G.WS and _G.WS.PointManager end)
  if pm ~= nil then
    for _, t in ipairs(A.targets or {}) do
      if not t.done and t.dug == nil and (tonumber(t.pid) or 0) > 0 then
        local who = nil
        pcall(function()
          local info = pm:GetPointInfo(tonumber(t.pid))
          if info ~= nil then who = tostring(info.ownerUid or "") end end)
        if who ~= nil and who ~= "" and who ~= "0" then
          t.dug, t.dug_by = now, "tile"
        end
      end
    end
  end
  for _, t in ipairs(A.targets or {}) do
   if not t.done then
    -- 1. WHAT THE SERVER SAID ABOUT THIS CHEST. The reply to a claim carries an
    -- `errorCode`, and the hook pins it on whichever target claimed last (`A.claim_uuid`),
    -- so two of the codes are verdicts rather than a line in a log: «claim repeat» is a
    -- chest this account already has, and «not in same alliance» is a chest it never had.
    -- Anything else is a refusal that may mend itself, and the retry ramp keeps trying.
    local code = (t.err ~= nil) and tostring(t.err) or nil
    t.err = nil
    if code == "%(err_repeat)s" then
      t.done, t.why, t.done_at, t.paid = true, "already-had-it", now, now
    elseif code == "%(err_foreign)s" then
      t.done, t.why, t.done_at = true, "foreign", now
    elseif code == "%(err_null)s" then
      -- THE CHEST IS NOT THERE ANY MORE, said by the only thing that can know (#1898).
      -- Taken, expired, or gone from the map — the server does not say which and it does
      -- not matter: nothing this errand can send will ever be paid for it, so it leaves
      -- the work here rather than on the far end of a thirty-minute ttl.
      t.done, t.why, t.done_at = true, "gone", now
    elseif code == "%(err_daylimit)s" then
      -- THE DAY, NOT THE CHEST (#1965). The reward allowance for this chest's group is
      -- spent, and the chest itself is untouched by that: it is still on the map, still
      -- diggable, and worth exactly nothing to this account until the day resets. So it
      -- is neither struck off nor retried — it is HELD, and the hold ends at the game's
      -- own reset stamp, which means it comes back by itself.
      t.hold_until = day_until
      t.hold_why = "day-limit"
      t.claimed, t.tries = nil, 0
      -- AND THE TYPE WITH IT (#2092). Holding the one chest that was refused left every
      -- other chest of the same type on the list — and every one heard afterwards — to be
      -- marched at and claimed until it was refused in its own turn, which is the whole of
      -- «нужно исключить из слушателя этот тип сокровища до следующего сброса». The
      -- refusal is the server's, so it outranks the client's own counters and is kept
      -- across every re-read of them until the reset stamp passes.
      local c = tonumber(t.cfg) or 0
      if c > 0 then
        A.day_bad = A.day_bad or {}
        A.day_bad[tostring(c)] = "server"
      end
      A.limit_at, A.limit_last = now, tostring(code)
      A.limit_all = (tonumber(A.limit_all) or 0) + 1
      -- …and ask the client again on the next beat rather than in five seconds: its own
      -- counters are what decide whether the WHOLE errand stands down, and the refusal
      -- that just arrived is the moment they changed.
      A.day_ask_now = 1
    elseif code == "%(err_undug)s" then
      -- THE OPPOSITE VERDICT: the chest is there and the dig is NOT over, so whatever
      -- stamped it «dug» was wrong. Take the stamp off and put it back on the march path
      -- if no squad of ours is out — the claim-first branch (#1886) is a guess made off
      -- `ownerUid`, and this is the server correcting it.
      t.dug, t.dug_by = nil, nil
      t.undug = (tonumber(t.undug) or 0) + 1
      if t.sent == nil and not t.claim_only then
        t.plan, t.tries, t.claimed = "march", 0, nil
      end
    end
    -- 2. PAID — the reward window, while it is fresh enough to be OURS.
    if not t.done and t.claimed ~= nil and reward
       and now - (tonumber(t.claimed) or 0) <= %(paid_win)d then
      t.done, t.why, t.paid, t.done_at = true, "paid", now, now
    end
    -- 3. GONE — the chest's own deadline first, the errand's guess second.
    if not t.done and (((tonumber(t.at) or 0) > 0 and now - (tonumber(t.at) or 0) > ttl)
       or ((tonumber(t.expire) or 0) > 0 and now > tonumber(t.expire))) then
      t.done, t.why, t.done_at = true, "expired", now
    end
    if t.done then
      t.state = tostring(t.why)
      -- THE LEDGER ALL THREE DOORS READ (#1898). A finished chest stays in `targets` for
      -- a ttl and no longer, and the doors that queue one — the dig feed, the chat share
      -- and the look — would each hand it back afterwards as news. This is the one place
      -- that remembers a uuid is spent, and it outlives the prune.
      -- …for a VERDICT only. «expired» is this errand's own guess that a chest has been
      -- on the list too long, and a guess must stay re-openable: if the map still draws
      -- the chest, the look is right and the guess was wrong.
      if t.why ~= "expired" then
        A.spent = A.spent or {}
        A.spent[tostring(t.uuid)] = tostring(t.why)
      end
      if t.why == "paid" or t.why == "already-had-it" then
        paid = paid + 1
        A.paid_all = (tonumber(A.paid_all) or 0) + 1
        -- THE NUMBER THE ACCEPTANCE CRITERION IS READ OFF. `ready_at` is the moment the
        -- chest BECAME takeable — the dig's own deadline where the game gave one — and
        -- `claim_at` is when the first claim for it left. Their difference is the answer
        -- to «в первую секунду?» in milliseconds, per chest, and it is kept as the last
        -- one and as the worst one so a good average cannot hide a bad chest.
        if (tonumber(t.ready_at) or 0) > 0 and (tonumber(t.claim_at) or 0) > 0 then
          t.lag = t.claim_at - t.ready_at
          A.lag_ms = t.lag
          if t.lag > (tonumber(A.lag_worst) or -1) then A.lag_worst = t.lag end
        end
      elseif t.why == "expired" then expired = expired + 1
      -- WRITTEN OFF BECAUSE THE GAME SAID SO, counted apart from a chest that merely ran
      -- out of time here. The two look the same in a queue and mean opposite things: one
      -- is the errand giving up, the other is the errand being told.
      elseif t.why == "gone" or t.why == "tile-gone" or t.why == "foreign" then
        gone = gone + 1
        A.gone_all = (tonumber(A.gone_all) or 0) + 1
        A.gone_last = tostring(t.why) .. " @[" .. tostring(t.x) .. ","
          .. tostring(t.y) .. "]"
        A.gone_last_at = now
      end
    else
      live = live + 1
      -- 4. WHERE OUR OWN SQUAD IS. The march object is the only thing that can say, and
      -- what it says has three shapes: it is walking there, it is DIGGING (and then its
      -- `endTime` is the moment the dig ends — the whole point of this watch), or it is on
      -- its way home, which means our part is done.
      local m = nil
      local lost = false
      if t.squad_uuid ~= nil then pcall(function()
        m = wm:GetOwnerFormationMarch(P.uid, t.squad_uuid, P.allianceId) end) end
      if m ~= nil then
        t.march_seen = true
        local sn = tonumber(m.status)
        local ss = "" pcall(function() ss = tostring(m.status) end)
        local et = nil pcall(function() et = tonumber(m.endTime) end)
        if sn == %(dig_status)d or ss:find("TREASURE_DIGGING", 1, true) ~= nil then
          t.digging = true
          if et ~= nil and et > 0 then t.due = et end
        elseif sn == %(home_status)d or ss:find("BACK_HOME", 1, true) ~= nil then
          if t.back_at == nil then t.back_at = now end
        elseif et ~= nil and et > 0 then
          t.arrive = et
        end
      elseif t.sent ~= nil then
        if t.march_seen then
          -- A march that WAS there and is not: the squad has been and gone.
          if t.gone_at == nil then t.gone_at = now end
        else
        -- HOW MANY TIMES WE ACTUALLY LOOKED, not just how long it has been. The clock
        -- alone is not enough to call a send lost: a client the watch is not running on is
        -- only looked at when the panel presses, and a chest twelve tiles from the base
        -- could be marched, dug and walked home between two of those presses — which would
        -- read as «the march never appeared» and send a second squad at a chest that had
        -- already been dug. Three sightings of an empty road, and only then.
        t.looks = (tonumber(t.looks) or 0) + 1
        if (tonumber(t.looks) or 0) >= 3
           and now - (tonumber(t.sent) or 0) >= %(settle)d then
          -- …and a march that was NEVER there is a send the client dropped without a
          -- word. Re-send it; do not read the silence as a squad that has been.
          t.sent, t.squad, t.squad_uuid = nil, nil, nil
          t.due, t.digging, t.armed, t.arrive, t.looks = nil, nil, nil, nil, nil
          t.resends = (tonumber(t.resends) or 0) + 1
          resent = resent + 1
          lost = true
          if t.resends > %(resends)d then
            -- EVERY SEND SWALLOWED, and the chest is NOT written off — it is claimed
            -- blind. Two things look like this from here: a client dropping our marches,
            -- and a march this reading simply cannot see. The second one would cost the
            -- whole gift for a chest that was already dug, so the last word is left to the
            -- server: the claim goes out, and «claim repeat» / «not in same alliance» /
            -- silence are three different answers, all of them better than a guess.
            t.claim_only, t.blind = true, true
          end
        end
        end
      end
      if not t.done then
       -- 5. IS IT TAKEABLE, AND SINCE WHEN? The anchor matters as much as the answer: a
       -- claim is measured against the moment the chest became takeable, not against the
       -- tick that noticed.
       local ready, anchor = false, nil
       -- A HOLD THE GAME'S OWN CLOCK LETS GO OF (#1965). Every hold is measured against
       -- the reset stamp the manager carries, so the day turning over takes the hold off
       -- without anybody pressing anything — and a client that stopped being able to
       -- answer at all (`day_until == 0`) is given the chest back rather than kept from it
       -- for ever by a stamp nobody can check.
       if (tonumber(t.hold_until) or 0) > 0
          and (day_until <= 0 or now >= (tonumber(t.hold_until) or 0)) then
         t.hold_until, t.hold_why = nil, nil
       end
       -- …and the stand-down that is NOT about one chest. The allowance is counted per
       -- treasure group, so one refusal proves one group is full and nothing more; when
       -- every counter the client keeps says full there is no chest anywhere on the map
       -- this account can be paid for, and the honest thing is to send nothing until the
       -- day resets.
       -- A TYPE THE DAY IS FULL OF IS EXCLUDED WHOLE (#2092): the chest that was
       -- refused, its neighbours on the list, and the ones the ears bring in afterwards.
       -- Nothing here is counted on this side — the type is excluded because the server
       -- refused it or the client's own gate says the counter is spent, and it comes back
       -- when the game's own reset stamp passes.
       local tc = tonumber(t.cfg) or 0
       if day_until > 0 and tc > 0 and (A.day_bad or {})[tostring(tc)] ~= nil then
         t.hold_until, t.hold_why = day_until, "day-limit-type"
         t.claimed, t.tries = nil, 0
       end
       local day_stop = (A.day_full and day_until > 0) and true or false
       if (tonumber(t.hold_until) or 0) > 0 or day_stop then
         t.state = "day-limit"
         held = held + 1
         waiting = waiting + 1
       elseif lost then
         t.state = "march-lost:resend" .. tostring(t.resends)
         waiting = waiting + 1
       else
        if t.claim_only and t.sent == nil then
          ready, anchor = true, (tonumber(t.dug) or tonumber(t.at) or now)
        elseif t.sent == nil and t.dug ~= nil and t.plan ~= "march" then
          -- A CHEST THAT ARRIVES ALREADY DUG IS CLAIMED BEFORE ANY SQUAD IS SPENT ON IT
          -- (#1886). The other order was deliberate and is now disproved by a recording:
          -- the march is refused in silence when the dig is already over, the errand
          -- reads that silence as a dropped send and re-sends it, and the chest is only
          -- taken when the resend ladder runs out and claims blind — a hundred seconds
          -- for a claim the server pays on its first try. The march is still there, one
          -- ramp later, for the case this reading is wrong (`cf_done` below).
          t.plan = "claim"
          ready, anchor = true, (tonumber(t.dug) or tonumber(t.at) or now)
        elseif t.sent ~= nil then
          if (tonumber(t.due) or 0) > 0 and now >= tonumber(t.due) then
            ready, anchor = true, tonumber(t.due)
          elseif t.back_at ~= nil then ready, anchor = true, t.back_at
          elseif t.gone_at ~= nil then ready, anchor = true, t.gone_at
          elseif t.dug ~= nil and m == nil and t.march_seen
                 and now - (tonumber(t.sent) or 0) >= grace then
            ready, anchor = true, now
          end
        end
        if ready and t.ready_at == nil then t.ready_at = anchor or now end
        -- …AND THE CLAIM-FIRST IS A TRY, NOT A VERDICT. `ownerUid` says «this chest has
        -- been worked», not «this account may have it», so a chest that swallows this
        -- many claims in silence is handed back to the march path with a clean ramp — the
        -- old order, one ramp late, for a chest this reading was wrong about.
        if ready and t.plan == "claim" and t.sent == nil and not t.claim_only
           and (tonumber(t.tries) or 0) >= %(cf_tries)d then
          t.plan, t.tries, t.claimed = "march", 0, nil
          ready = false
        end
        if ready then
          local n = tonumber(t.tries) or 0
          -- The gap AFTER n tries, so the first retry is the ramp's first step and not its
          -- second. A chest is only ever cooling once it has been claimed at least once.
          local wait = ramp[math.max(1, n)] or ramp[#ramp]
          if t.claimed ~= nil and now - (tonumber(t.claimed) or 0) < wait then
            waiting = waiting + 1
            -- …unless the claim went out THIS millisecond, which is what a press looks
            -- like from the second pass it makes: the word «claim1» is what happened, and
            -- «waiting» would describe the same instant as if nothing had.
            if t.claimed ~= now then t.state = "claimed-waiting" .. tostring(n) end
          else
            t.tries = n + 1
            local srv = ((tonumber(t.server) or 0) ~= 0) and tonumber(t.server) or home_srv
            -- WHICH CHEST THE NEXT `errorCode` BELONGS TO. The reply names no chest, so
            -- the only honest way to read it is to know which one was claimed last.
            A.claim_uuid = tostring(t.uuid)
            A.claim_at = now
            local ok, err = pcall(function()
              SFSNetwork.SendMessage(MsgDefines.DetectEventClaimTreasure, t.uuid, srv) end)
            if ok then
              t.claimed = now
              claimed = claimed + 1
              A.claims_all = (tonumber(A.claims_all) or 0) + 1
              if t.claim_at == nil then
                t.claim_at = now
                t.lag = now - (tonumber(t.ready_at) or now)
                A.lag_ms = t.lag
                -- …AND THE NUMBER THE PLAYER ACTUALLY ASKED FOR (#1886): «услышали —
                -- собрали», end to end. `lag` measures from the chest becoming takeable,
                -- which is the errand's own half; this measures from the second the
                -- client learned of the chest at all, which is the sentence the player
                -- said. On a chest heard already dug the two are the same number.
                t.hear = now - (tonumber(t.at) or now)
                A.hear_ms = t.hear
                if t.hear > (tonumber(A.hear_worst) or -1) then A.hear_worst = t.hear end
                if t.lag > (tonumber(A.lag_worst) or -1) then A.lag_worst = t.lag end
              end
              t.state = "claim" .. tostring(t.tries)
            else
              t.state = "claim-threw:" .. tostring(err)
            end
          end
        else
          waiting = waiting + 1
          if t.blind then t.state = "march-never-left:claiming"
          elseif t.sent == nil then t.state = "to-send"
          elseif t.digging then
            t.state = "digging-" .. tostring(math.max(0, math.floor(
              ((tonumber(t.due) or now) - now) / 1000))) .. "s"
          elseif not t.march_seen then t.state = "march-unanswered"
          -- OUR OWN LEGS, said apart from anybody else's (#1296). «The alliance has dug it
          -- and our squad is still on the road» is the state that hid a hundred seconds of
          -- burnt claims inside the word «digging»; it has its own word for that reason.
          elseif t.dug ~= nil then t.state = "dug-still-marching"
          else t.state = "marching" end
        end
        -- 6. THE MILLISECOND ITSELF. A dig deadline that is near is pinned with a one-shot
        -- of the game's own timer, so the claim leaves in the frame the dig ends instead of
        -- on whichever fifth of a second comes next. Armed once per deadline.
        if (tonumber(t.due) or 0) > 0 and not ready then
          local dt = tonumber(t.due) - now
          if dt > 0 and dt <= %(arm_ms)d and t.armed ~= t.due then
            t.armed = t.due
            pcall(function() TimerManager:GetInstance():DelayInvoke(function()
              local AA = DataCenter.__lw_treasure_auto
              if AA ~= nil and AA.tick ~= nil then pcall(AA.tick) end
            end, dt / 1000) end)
          end
        end
       end
      end
    end
   end
  end
  A.t_live, A.t_claimed, A.t_paid = live, claimed, paid
  A.t_expired, A.t_waiting, A.t_resent = expired, waiting, resent
  A.t_gone, A.t_held = gone, held
  -- …AND THE SAME NUMBERS ADDED UP FOR WHOEVER IS HOLDING A PRESS. A step asks this
  -- function twice — once to resolve the queue before it spends a squad on it, once to
  -- claim what became takeable — and the second pass would otherwise report zero of what
  -- the first one did. The step zeroes these on its way in; the game's own timer never
  -- touches them.
  A.s_claimed = (tonumber(A.s_claimed) or 0) + claimed
  A.s_paid = (tonumber(A.s_paid) or 0) + paid
  A.s_expired = (tonumber(A.s_expired) or 0) + expired
  A.s_resent = (tonumber(A.s_resent) or 0) + resent
  A.s_gone = (tonumber(A.s_gone) or 0) + gone
  A.claim_sent = claimed
end
''' % {"ttl": int(TREASURE_TARGET_TTL_SEC), "grace": int(TREASURE_ARRIVE_GRACE_SEC),
       "ramp": ", ".join(str(int(ms)) for ms in TREASURE_CLAIM_RAMP_MS),
       "paid_win": int(TREASURE_PAID_WINDOW_SEC) * 1000,
       "err_repeat": TREASURE_ERR_CLAIM_REPEAT,
       "err_foreign": TREASURE_ERR_NOT_IN_ALLIANCE,
       "err_null": TREASURE_ERR_TREASURE_NULL,
       "err_undug": TREASURE_ERR_NOT_COMPLETE,
       "err_daylimit": TREASURE_ERR_DAY_LIMIT,
       "day_ask": int(TREASURE_DAY_LIMIT_ASK_MS),
       "day_blind": int(TREASURE_DAY_LIMIT_BLIND_MS),
       "dig_status": int(TREASURE_DIG_STATUS), "home_status": int(TREASURE_HOME_STATUS),
       "settle": int(TREASURE_MARCH_SETTLE_SEC) * 1000,
       "resends": int(TREASURE_RESEND_TRIES), "arm_ms": int(TREASURE_DUE_ARM_MS),
       "cf_tries": int(TREASURE_CLAIM_FIRST_TRIES)}


def treasure_tick_define() -> str:
    """Park (or replace) `A.tick` — the claim half of the errand, as game-side code.

    Idempotent and deliberately re-run on every arm and every step: the definition IS the
    deployment. A client that has been running since before an edit to this file would
    otherwise keep claiming with last week's rules, and there is nothing on screen to say
    so.
    """
    return _TREASURE_TICK


def treasure_reaper_install() -> str:
    """Start the game-side watch that takes a chest the moment its dig ends (#1318).

    «Таймер работать с наивысшим приоритетом, отслеживать время завершения раскопки и в ту
    же микросекунду забирать сокровище, и продолжать попытки, пока сокровище не будет взято
    или не исчезнет.» This is that timer, and it lives where the deadline lives.

    WHAT IT ACTUALLY WAITS FOR. A dig march carries `MarchStatus.TREASURE_DIGGING` and,
    with it, an `endTime` — the server's own millisecond for when the digging finishes
    (`docs/research/squad-state.md`). So the watch does not guess and does not poll the
    server: it reads our own march, learns the deadline the first time the squad starts
    digging, and pins a one-shot of the game's timer to it. Between deadlines it looks
    every fifth of a second, which is what catches the chests whose deadline never arrives
    in a readable form — a claim-only target heard through the alliance's dig feed, a march
    that ends by going home.

    THREE THINGS IT DOES BESIDES CLAIMING, all of them cheap:

      * **it watches for a send that never happened.** A march the client dropped in
        silence used to be read as a march that was over, and the claim went out into an
        empty road (`TREASURE_RESEND_TRIES`);
      * **it reads the box the camera is in**, every few seconds, out of the client's own
        point manager — the second of the two ears the panel is asked to keep open. It
        never moves the camera, never changes the zoom and never asks the server, and in
        the city it does nothing at all;
      * **it stops itself.** This is a self-rescheduling timer inside somebody's game, so
        it ends after `TREASURE_REAP_STOP_SEC` with nothing to work. The panel's poll
        re-arms it on the next tick; a panel that has been closed leaves nothing behind.

    Re-arming is safe and is how a code change is deployed: the run token is bumped, every
    loop scheduled under the old one returns on its next wake, and exactly one loop is left
    running. The queue itself is never touched.
    """
    return _TREASURE_TICK + _TREASURE_REAP_LOOP


def treasure_reaper_start() -> str:
    """The same watch, for a caller that has just parked `A.tick` itself.

    The arm below defines the tick — it is the recipe's first press, so the definition is
    always the current one — and the button that composes the two would otherwise carry
    nine kilobytes of the same Lua twice.
    """
    return _TREASURE_REAP_LOOP


_TREASURE_REAP_LOOP = '''
local A = DataCenter.__lw_treasure_auto
if A == nil then A = {seen={}, targets={}, news=0} DataCenter.__lw_treasure_auto = A end
A.reap = (tonumber(A.reap) or 0) + 1
local token = A.reap
A.reap_on = true
A.reap_started = A.tick_at or 0
-- THE SECOND EAR: what the client can see from where it already stands. Not a lap — the
-- whole-server walk was deleted for costing 48 s of camera and finding other people's
-- chests (#1296) — one box around the camera, read out of the point manager the client
-- fills for itself. It runs off `_G.WS` and never goes looking for the scene: finding it
-- costs a `FindObjectsOfType` over every MonoBehaviour in the game, which is the panel's
-- own press to pay, not a background timer's.
local function look()
  local A = DataCenter.__lw_treasure_auto
  local now = tonumber(A.tick_at) or 0
  if now <= 0 then return end
  if (tonumber(A.look_at) or 0) > 0 and now - A.look_at < %(look_sec)d then return end
  A.look_at = now
  local inworld = false
  pcall(function() inworld = SceneUtils.GetIsInWorld() and true or false end)
  if not inworld then A.look_why = "city" return end
  local scene = _G.WS
  local pm = nil
  pcall(function() pm = scene and scene.PointManager end)
  if pm == nil then A.look_why = "no-point-manager" return end
  local cx, cy = -1, -1
  pcall(function() cx, cy = scene.CurTilePos.x, scene.CurTilePos.y end)
  cx, cy = math.floor(tonumber(cx) or -1), math.floor(tonumber(cy) or -1)
  if cx < 0 or cy < 0 then A.look_why = "no-camera-tile" return end
  local size = 1000
  pcall(function() size = scene.TileCount.x end)
  local srv = tonumber(LuaEntry.Player.serverId) or 0
  local mine = tostring(LuaEntry.Player.allianceId or "")
  local box = %(look_box)d
  local x0, x1 = math.max(0, cx - box), math.min(size - 1, cx + box)
  local y0, y1 = math.max(0, cy - box), math.min(size - 1, cy + box)
  local found, ours, foreign = 0, 0, 0
  for ty = y0, y1 do
    local base = ty * size + 1
    for tx = x0, x1 do
      local info = nil
      pcall(function() info = pm:GetPointInfo(base + tx) end)
      if info ~= nil then
        local pt = nil
        pcall(function() pt = tonumber(info.PointType) end)
        if pt == %(point_type)d then
          local uuid = nil
          pcall(function() uuid = info.uuid end)
          if uuid ~= nil and tostring(uuid) ~= "0" then
            found = found + 1
            local ally = "" pcall(function() ally = tostring(info.allianceId or "") end)
            -- A CHEST BELONGS TO AN ALLIANCE and the game refuses everybody else's
            -- (errorCode 801354). Eighteen of the first nineteen ever seen were foreign.
            if mine ~= "" and ally ~= "" and ally ~= mine then foreign = foreign + 1
            else
              ours = ours + 1
              local key = tostring(uuid)
              local seen_here = nil
              for _, t in ipairs(A.targets or {}) do
                if tostring(t.uuid) == key then seen_here = t end end
              if seen_here ~= nil then
                -- The door that has the TILE upgrades a target that arrived without one.
                if (tonumber(seen_here.pid) or 0) == 0 then
                  seen_here.pid, seen_here.x, seen_here.y = base + tx, tx, ty
                  seen_here.claim_only = false
                  seen_here.src = tostring(seen_here.src or "?") .. "+eye"
                end
                if (tonumber(seen_here.cfg) or 0) == 0 then
                  pcall(function() seen_here.cfg = tonumber(info.cfgId)
                    or tonumber(info.treasureId) or 0 end)
                end
              else
                local who = "" pcall(function() who = tostring(info.ownerUid or "") end)
                local exp = 0 pcall(function() exp = tonumber(info.expireTime) or 0 end)
                A.seen = A.seen or {}
                A.seen[key] = A.seen[key] or now
                A.targets = A.targets or {}
                local cfg = 0
                pcall(function() cfg = tonumber(info.cfgId)
                  or tonumber(info.treasureId) or 0 end)
                A.targets[#A.targets+1] = {uuid = uuid, pid = base + tx, x = tx, y = ty,
                  server = tonumber(info.serverId) or srv, at = now, src = "eye",
                  expire = exp, cfg = cfg,
                  dug = ((who ~= "" and who ~= "0") and now or nil)}
                A.news = (tonumber(A.news) or 0) + 1
              end
            end
          end
        end
      end
    end
  end
  A.look_why = "looked"
  A.look_found, A.look_ours, A.look_foreign = found, ours, foreign
end
local tm = TimerManager:GetInstance()
local function loop()
  local A = DataCenter.__lw_treasure_auto
  if A == nil or A.reap ~= token or not A.reap_on then return end
  if A.tick ~= nil then pcall(A.tick) end
  pcall(look)
  local busy = (tonumber(A.t_live) or 0) > 0
  local now = tonumber(A.tick_at) or 0
  if busy or (tonumber(A.reap_busy_at) or 0) == 0 then A.reap_busy_at = now end
  -- A TIMER IN SOMEBODY ELSE'S GAME HAS TO END. Nothing to work for a quarter of an hour
  -- and the loop stops; the panel's poll arms it again the moment it next looks.
  if now > 0 and not busy and now - (tonumber(A.reap_busy_at) or now) > %(stop_ms)d then
    A.reap_on = false
    CS.UnityEngine.Debug.LogError("ACT treasure_reaper idle-stop ticks="
      .. tostring(A.ticks or 0))
    return
  end
  tm:DelayInvoke(loop, busy and %(fast)s or %(idle)s)
end
tm:DelayInvoke(loop, %(fast)s)
CS.UnityEngine.Debug.LogError("ACT treasure_reaper on=1 run=" .. tostring(token)
  .. " queued=" .. tostring(#(A.targets or {})))
''' % {"look_sec": int(TREASURE_REAP_LOOK_SEC) * 1000,
       "look_box": int(TREASURE_REAP_LOOK_BOX), "point_type": int(TREASURE_POINT_TYPE),
       "stop_ms": int(TREASURE_REAP_STOP_SEC) * 1000,
       "fast": repr(float(TREASURE_REAP_FAST_SEC)),
       "idle": repr(float(TREASURE_REAP_IDLE_SEC))}


def treasure_reaper_stop() -> str:
    """Stop the game-side watch; the queue and the ear are left exactly as they are.

    Bumping the run token is the whole of it — a loop already scheduled cannot be cancelled,
    so it is disowned instead and returns on its next wake (the same way a map lap is
    stopped). What the watch knew stays on the VM: a chest halfway through is still worth
    finishing, by the panel's press or by the next arm.
    """
    return (
        "local A = DataCenter.__lw_treasure_auto "
        "if A ~= nil then A.reap = (tonumber(A.reap) or 0) + 1 A.reap_on = false end "
        'CS.UnityEngine.Debug.LogError("ACT treasure_reaper on=0 ticks="'
        "..tostring((A or {}).ticks or 0))"
    )


def treasure_reaper_state() -> str:
    """Lua *expression* -> what the watch is doing, and the number the criterion needs.

    ``on=<0|1> ticks=<n> live=<n> claims=<n> paid=<n> lag=<ms> worst=<ms> hear=<ms>
    eye=<why>`` —
    `lag` is the milliseconds between a chest becoming takeable and the first claim for it
    leaving, which is «в первую секунду» said as a number rather than as an impression,
    and `worst` is the worst one this client has seen so an average cannot hide a bad chest.
    `-1` for either means no chest has been taken yet.
    """
    return (
        "(function() local A = DataCenter.__lw_treasure_auto "
        "if A == nil then return 'on=0 ticks=0 live=0 claims=0 paid=0 "
        "lag=-1 worst=-1 gone=0 eye=never' end "
        "return 'on=' .. tostring((A.reap_on and A.reap_on ~= 0) and 1 or 0) "
        ".. ' ticks=' .. tostring(A.ticks or 0) "
        ".. ' live=' .. tostring(A.t_live or 0) "
        ".. ' claims=' .. tostring(A.claims_all or 0) "
        ".. ' paid=' .. tostring(A.paid_all or 0) "
        ".. ' lag=' .. tostring(A.lag_ms or -1) "
        ".. ' worst=' .. tostring(A.lag_worst or -1) "
        # «услышали — собрали», the whole distance, which is the sentence the player used
        # and the one `lag` alone cannot answer (#1886).
        ".. ' hear=' .. tostring(A.hear_ms or -1) "
        # …and how many chests were struck out because the GAME said they are not there
        # (#1898). A watch that claims and is never paid looks identical to one that is
        # working, and the difference is this number.
        ".. ' gone=' .. tostring(A.gone_all or 0) "
        ".. ' eye=' .. tostring(A.look_why or 'never') end)()"
    )


def treasure_auto_step() -> str:
    """Work every queued chest one step, in ONE chunk — and say what it did.

    A CHEST IS A RACE, so this is one call and not eight. The rally join was measured at
    5.48 s across its readings and 0.19 s once they became local variables inside a
    single chunk (#1281); a treasure has the same shape — it is out for minutes and the
    alliance is digging it — so the sieve, the pairing, the send and the claim all happen
    here, and the recipe only reads the sentence back.

    What one step is, per target:

      * **new** — pick the nearest free squad and march it onto the tile. Same
        `MarchUtil.SendCreateMarchMessage` the game's own dig ends at, type 50 for a
        chest on this server and 182 for one on another (`docs/research/
        world-treasures.md`), called STRAIGHT rather than behind
        `TimerManager:DelayInvoke` — the rally join proved the direct send works from the
        daemon's thread, and a send behind a timer cannot say whether it threw.
      * **already dug** — nothing is marched at it at all until the claim has been
        refused (#1886). `A.tick` claims it on the beat it is queued; the squad is the
        fallback, not the first move.
      * **anything else** — `A.tick`, and not this chunk (#1318). Waiting for a dig to end
        and claiming the moment it does is a question of MILLISECONDS, and a chunk the
        panel sends is asked every ten seconds at best. So the claim half lives in the game
        (`_TREASURE_TICK`), is driven by the game's own timer, and is called from here as
        the last thing this press does — a press is never slower than the watch, and the
        watch never waits for a press.

    A REFUSED CLAIM IS SILENT, and the whole shape above exists because of it. Measured
    live on 2026-08-08 against a uuid that cannot exist: **no message tip, no window, no
    thrown error**, and the reply arrives under the same command name carrying no readable
    fields. So «the send returned cleanly» proves nothing, and the first version of this
    chunk — which treated it as payment — wrote a chest off while the alliance was still
    digging it, in exactly the case the grace was added for: a squad still walking when the
    clock ran out. Two corrections came out of that, and neither is optional:

      * the grace waits for the CLOCK **and** for the march to be over
        (`GetOwnerFormationMarch` on the squad that was sent — the target keeps that
        squad's uuid for this reason). A chest 300 tiles out lives longer than any grace
        worth having;
      * a claim is proven by the `UIGiftPackageRewardGet` the client raises on a paid one,
        read only while it is fresh; a chest whose tries all ran out is written off as
        `claim-unconfirmed`, never as `claimed`.

    AND THE DIG FEED DOES NOT OVERRULE OUR OWN MARCH — the second correction, measured on
    the first chest this account ever had of its own (#1296). `t.dug` used to skip the
    march test entirely, on the reading that a dug chest is claimable. It is not: a chest
    the ALLIANCE has dug is not a chest THIS account has dug, and the claim is refused
    until our squad has done its part. Live, on a chest twelve tiles from home: the march
    went out at 20:55:41 and the first claim at 20:55:43, two seconds later, with the squad
    barely out of the base — all four tries spent inside 124 s, every one refused in
    silence, and the chest written off. So `not marching` now gates the feed exactly as it
    gates the clock, and a chest waiting on our own legs says `dug-still-marching` rather
    than hiding inside `digging`.

    A SPENT CHEST STAYS IN THE LIST, which is the other half of that bug. The prune used
    to drop every finished target, and `treasure_scan_harvest` looks for duplicates among
    the targets it can see — so the lap five minutes later re-queued the chest it had just
    written off, sent a SECOND squad at it and burned four more claims, round and round for
    as long as the chest was on the map. Finished targets are now kept until their ttl
    runs out: skipped by the step (`live` takes only what is not `done`), recognised by the
    harvest, and counted apart in the report as `spent=` so `queued=` still means work.

    «NEAREST» IS HONEST ABOUT ITS OWN LIMIT, and this is worth reading before trusting
    the word. A squad has no position of its own — read live off
    `ArmyFormationDataManager`, a formation carries its army, its slot and its heroes and
    NO tile — and a squad that is free is by definition standing in the base. So every
    free squad is the same distance from the chest, and «the nearest squad» can only be
    honestly resolved as «the nearest CHEST first, with the lowest free slot», which is
    what this does: targets are ordered by their distance from the base, and the report
    names the distance it went by. A squad already marching is never counted as nearer,
    because it is not free.

    THE PER-DAY LIMIT IS THE SERVER'S. `CheckTreasureReachDailyLimit` gates both the dig
    and the claim, and a refusal comes back as the server's own answer rather than as a
    thrown error — so a send that goes out and pays nothing is reported as sent, and the
    day's allowance is not something this chunk pretends to know.
    """
    return (
        "local A = DataCenter.__lw_treasure_auto "
        "if A == nil then A = {seen={}, targets={}, news=0} "
        "DataCenter.__lw_treasure_auto = A end "
        "local P = LuaEntry.Player "
        "local now = 0 pcall(function() "
        "now = math.floor(tonumber(UITimeManager.Instance:GetServerTime()) or 0) end) "
        "if now <= 0 then pcall(function() "
        "now = math.floor((tonumber(ChatInterface.getServerTime()) or 0) * 1000) end) end "
        "local grace = (tonumber(A.grace) or " + str(int(TREASURE_ARRIVE_GRACE_SEC))
        + ") * 1000 "
        "local ttl = (tonumber(A.ttl) or " + str(int(TREASURE_TARGET_TTL_SEC))
        + ") * 1000 "
        "local home_srv = tonumber(P.serverId) or 0 "
        # The base's own tile — where a free squad stands, and what the ordering of the
        # chests is measured from.
        "local hx, hy = 0, 0 "
        "pcall(function() local tp = SceneUtils.IndexToTilePos(tonumber(P.world_main_pos)) "
        "hx, hy = tonumber(tp.x) or 0, tonumber(tp.y) or 0 end) "
        # The squads that could go: in the allowed slots, with an army, not marching.
        "local allow = {} "
        "for _, s in ipairs(A.squads or {1,2,3,4}) do allow[tonumber(s) or -1] = true end "
        "local afd = DataCenter.ArmyFormationDataManager "
        "local wm = DataCenter.WorldMarchDataManager "
        "local free, empties, busy, dry = {}, {}, 0, 0 "
        "for _, f in pairs(afd.ArmyFormationList) do "
        "local idx = -1 pcall(function() idx = tonumber(f.index) or -1 end) "
        "if allow[idx] then "
        "local n = 0 pcall(function() n = tonumber(f.totalSoldierNum) or 0 end) "
        "local out = false "
        "pcall(function() out = (wm:GetOwnerFormationMarch("
        "P.uid, f.uuid, P.allianceId) ~= nil) end) "
        "if out then busy = busy + 1 elseif n <= 0 then dry = dry + 1 "
        "empties[#empties+1] = f.uuid "
        "else free[#free+1] = {slot=idx, uuid=f.uuid, n=n} end end end "
        "table.sort(free, function(a, b) return a.slot < b.slot end) "
        # A SQUAD THAT READS EMPTY IS USUALLY A SQUAD NOBODY HAS ASKED ABOUT (#1285, and
        # measured again here: the same three squads read 3123/2631/2565 and then 0/0/0
        # twenty minutes later, with the army untouched in the game). The client's
        # counter is a reply cache; one request puts the real number back in ~0.4 s with
        # nothing on screen. So a run that has a chest and no squad to send ASKS, marks
        # that it asked, and lets the recipe come round again — refusing on a number
        # nobody has fetched is refusing on nothing.
        "A.asked = false "
        "if #free == 0 and #empties > 0 then "
        "for _, u in ipairs(empties) do pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.GetFormationSoldier, u) end) end "
        "A.asked = true end "
        # The chests, nearest first — the only place the word «nearest» can be earned
        # (see the docstring).
        # HOW FAR EVERY CHEST IS, AND WHICH DOOR IT CAME THROUGH — measured before anything
        # is decided, because the words below are written on chests the tick may finish.
        "for _, t in ipairs(A.targets or {}) do if not t.done then "
        "t.d = math.max(math.abs((tonumber(t.x) or 0) - hx), "
        "math.abs((tonumber(t.y) or 0) - hy)) "
        # WHICH DOOR THIS CHEST CAME THROUGH, and how long ago — because «a chest was
        # worked» is half an answer: the three doors fail in different ways (nobody shared
        # it / the dig feed carries no tile / nobody has looked that way yet), and a log
        # that does not say which one let this chest in cannot tell a working door from a
        # lucky one.
        "t.tag = tostring(t.src or '?') "
        "if (tonumber(t.at) or 0) > 0 and now > 0 then "
        "t.tag = t.tag .. '/' .. tostring(math.floor((now - t.at) / 1000)) .. 's' end "
        "end end "
        # THE WATCH RUNS FIRST, and this is not a nicety: a chest whose minutes on the map
        # are over is written off by the tick, and a step that built its list before asking
        # would send a squad at a tile that expired a minute ago.
        "A.s_claimed, A.s_paid, A.s_expired, A.s_resent, A.s_gone = 0, 0, 0, 0, 0 "
        "if A.tick ~= nil then pcall(A.tick) end "
        "local live = {} "
        "for _, t in ipairs(A.targets or {}) do if not t.done then "
        "live[#live+1] = t end end "
        "table.sort(live, function(a, b) return (a.d or 0) < (b.d or 0) end) "
        # WHAT THE SEND HALF OWNS, and what it stopped owning (#1318). Everything about a
        # chest that has ALREADY got a squad — is the dig over, is it takeable, has the
        # server paid — is `A.tick`, because those questions have to be asked in
        # milliseconds and this chunk is asked in tens of seconds. What is left here is the
        # pairing: which chest, which squad, and the march itself.
        "local sent, notes, mine = 0, {}, {} "
        "local fi = 1 "
        "for _, t in ipairs(live) do "
        # A chest with a squad out, or one that only ever had a uuid to claim, is the
        # watch's business — this loop leaves it alone and the note comes off the word the
        # watch wrote on it.
        # …and so is a chest the watch is claiming BEFORE it marches (#1886): a dug chest
        # gets the ramp first, and a squad only if the server refuses it.
        "if t.sent ~= nil or t.claim_only or t.plan == 'claim' then "
        # …AND A CHEST THE DAY'S ALLOWANCE HAS REFUSED GETS NO SQUAD EITHER (#1965). The
        # reward is the whole errand: marching at a chest that cannot be paid for spends a
        # squad, a walk and a dig for nothing. `hold_until` is this chest's own group being
        # full; `day_full` is every counter the client keeps saying so, which stands the
        # send half down altogether until the day resets.
        # …and a chest of a TYPE the day is full of gets none either (#2092), whether or
        # not the watch has stamped its hold yet: the exclusion is the type's, so a chest
        # heard a moment ago is as unpayable as the one that was refused.
        "elseif (tonumber(t.hold_until) or 0) > 0 or A.day_full "
        "or ((tonumber(t.cfg) or 0) > 0 and (tonumber(A.day_until) or 0) > 0 "
        "and (A.day_bad or {})[tostring(tonumber(t.cfg))] ~= nil) then "
        "mine[#mine+1] = {t, 'day-limit'} "
        "else "
        # New: the nearest free squad goes out. `fi` walks the free list so two chests
        # in the same minute never get the same squad.
        "local f = free[fi] "
        "if f == nil then mine[#mine+1] = {t, 'no-free-squad'} "
        # THE CAMERA DOES NOT HAVE TO BE ON THE CHEST — checked, because for a while it
        # looked as though it did (#1296). A send with the camera elsewhere once produced
        # nothing on the wire, and a send with the camera on the tile produced the message
        # at once; the difference turned out to be the SQUAD, not the view. Measured again
        # with the camera parked 500 tiles away and every squad genuinely free, the march
        # went out exactly as before. What the client does drop in silence is a march for a
        # formation that is already committed — and a squad whose march the server has not
        # confirmed yet still reads free here, which is what the first reading caught. The
        # watch is what notices afterwards that this send left no march at all, and sends
        # again rather than claiming into an empty road.
        "else fi = fi + 1 "
        "local srv = tonumber(t.server) or home_srv "
        "local target = (srv ~= 0 and srv ~= home_srv) and "
        + str(int(MARCH_CROSS_DETECT_TREASURE)) + " or "
        + str(int(MARCH_DETECT_TREASURE)) + " "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(f.uuid, target, t.pid, t.uuid, 1, 1, false, "
        "srv, nil) end) "
        # The squad's UUID rides with the target, not just its slot: the «is it still
        # walking?» test the watch makes asks about THIS squad's march, and a slot number
        # cannot.
        "if ok then t.sent, t.squad, t.squad_uuid = now, f.slot, f.uuid sent = sent + 1 "
        "t.march_seen, t.due, t.armed, t.gone_at, t.back_at = nil, nil, nil, nil, nil "
        "mine[#mine+1] = {t, 'squad' .. tostring(f.slot)} "
        "else mine[#mine+1] = {t, 'march-threw:' .. tostring(err)} end "
        "end end end "
        # …AND THEN THE CLAIM HALF, AT ONCE. The same function the game's own timer calls,
        # run here so a press is never slower than the watch it shares its state with — and
        # so a client whose watch has idled out still claims on a press.
        "if A.tick ~= nil then pcall(A.tick) end "
        # …and the send half keeps its own words. The watch writes a word on every live
        # chest, and a chest this press has just marched at — or could find no squad for —
        # would otherwise be described by what it looks like a fifth of a second later
        # («marching», «to-send») rather than by what this press DID about it.
        "for _, r in ipairs(mine) do r[1].state = r[2] end "
        # A FINISHED CHEST IS REMEMBERED, NOT FORGOTTEN — and the difference is a second
        # march (#1296). The prune used to drop every `done` target, and the lap that came
        # round five minutes later looked for a duplicate among the LIVE targets only: the
        # chest it had just written off was `new` again, got a fresh squad sent at it and
        # burned another four claims, for as long as it stayed on the map. So a spent chest
        # stays in the list until its ttl runs out — the step skips it (`live` takes only
        # what is not done) and the harvest recognises it (`already-queued`).
        "local keep, alive = {}, 0 "
        "for _, t in ipairs(A.targets or {}) do "
        "if not t.done then keep[#keep+1] = t alive = alive + 1 "
        "elseif now > 0 and now - (tonumber(t.done_at) or 0) < ttl then "
        "keep[#keep+1] = t end end "
        "A.targets = keep "
        "local spent = #keep - alive "
        # The notes are written LAST, off the word the watch left on each chest, so the
        # line says where every one of them actually stands rather than where it stood
        # before the claim half ran.
        "for _, t in ipairs(A.targets or {}) do "
        "if t.d ~= nil and (not t.done or t.done_at == now) then "
        "notes[#notes+1] = 'x' .. tostring(t.d) .. '/' .. tostring(t.tag) "
        ".. ':' .. tostring(t.state or '?') "
        ".. ((tonumber(t.lag) ~= nil) and ('/lag' .. tostring(t.lag) .. 'ms') or '') "
        "end end "
        "A.report = 'sent=' .. tostring(sent) "
        ".. ' claimed=' .. tostring(A.s_claimed or 0) "
        ".. ' paid=' .. tostring(A.s_paid or 0) "
        ".. ' waiting=' .. tostring(A.t_waiting or 0) "
        ".. ' expired=' .. tostring(A.s_expired or 0) "
        ".. ' queued=' .. tostring(alive) "
        # What is being held only so it is not started over. Said when there is any, so a
        # queue that reads 0 and a list that is not empty are never the same line.
        ".. (spent > 0 and (' spent=' .. tostring(spent)) or '') "
        # A SEND THAT LEFT NO MARCH, said out loud (#1318). This is «отправка отряда
        # работает через раз» in one word: the client dropped the march and the watch is
        # sending it again, which used to be invisible because the silence read as a squad
        # that had been and come back.
        ".. ((tonumber(A.s_resent) or 0) > 0 "
        "and (' resent=' .. tostring(A.s_resent)) or '') "
        # A TARGET STRUCK OUT BECAUSE THE GAME SAID IT IS NOT THERE, said in words rather
        # than left as a chest that quietly stopped being mentioned (#1898). Silence is how
        # this bug lasted: the server answered «treasure is null» twenty-five times and the
        # only trace was one floating `server-said=` that named no chest.
        ".. ((tonumber(A.s_gone) or 0) > 0 "
        "and (' gone=' .. tostring(A.s_gone)) or '') "
        # THE DAY'S ALLOWANCE, SAID OUT LOUD (#1965). A refusal used to leave nothing but a
        # floating `server-said=` and a queue that went on retrying — the same silence
        # #1898 was about, one code later. `held=` is how many chests are standing still
        # for it, `day=` is the client's own counters, and the words are there so a person
        # reading the log is told rather than left to work it out from a stalled queue.
        ".. ((tonumber(A.t_held) or 0) > 0 "
        "and (' held=' .. tostring(A.t_held)) or '') "
        ".. ((A.day_full and (tonumber(A.day_until) or 0) > 0) "
        "and ' day-limit=[дневной лимит наград исчерпан — до сброса суток за кладами не "
        "хожу]' or '') "
        ".. (((A.day_groups or '') ~= '' and (tonumber(A.t_held) or 0) > 0) "
        "and (' day=[' .. tostring(A.day_groups) .. ']') or '') "
        # THE TYPES THAT ARE SHUT, said out loud (#2092). `held=` counts chests and a
        # person reading it cannot tell one unlucky chest from a whole kind of chest the
        # day has closed; this names the kinds, and how each of them was closed — the
        # server refusing a claim, or the client's own counter being spent.
        ".. ((function() local w = {} "
        "for c, how in pairs(A.day_bad or {}) do "
        "w[#w+1] = tostring(c) .. '/' .. tostring(how) end "
        "if #w == 0 or (tonumber(A.day_until) or 0) <= 0 then return '' end "
        "table.sort(w) "
        "return ' day-types=[' .. table.concat(w, ',') "
        ".. ' — эти типы сокровищ исключены до сброса суток]' end)()) "
        ".. ((A.gone_last and now > 0 and (tonumber(A.gone_last_at) or 0) > 0 "
        "and now - A.gone_last_at < 60000) "
        "and (' dropped=[' .. tostring(A.gone_last) "
        ".. ' — the chest is not there any more, taking it off the list]') or '') "
        ".. ' free=' .. tostring(#free) .. ' busy=' .. tostring(busy) "
        ".. ' empty=' .. tostring(dry) "
        ".. (A.asked and ' asked-for-army' or '') "
        ".. ' news=' .. tostring(A.news or 0) "
        # THE NUMBER THE PLAYER ASKED FOR, on every line. `lag` is how long the last chest
        # taken had to wait between becoming takeable and its first claim leaving, and
        # `worst` is the worst this client has ever managed. «В первую секунду» is a
        # measurement, so it is reported as one.
        ".. ((tonumber(A.lag_ms) ~= nil) and (' lag=' .. tostring(A.lag_ms) .. 'ms') or '') "
        ".. ((tonumber(A.lag_worst) ~= nil) "
        "and (' worst=' .. tostring(A.lag_worst) .. 'ms') or '') "        # …AND THE SAME DISTANCE MEASURED FROM THE EAR (#1886): «услышали — собрали».
        ".. ((tonumber(A.hear_ms) ~= nil) "
        "and (' heard-to-claim=' .. tostring(A.hear_ms) .. 'ms') or '') "
        ".. ' watch=' .. tostring((A.reap_on and 1) or 0) "
        # …and what the SERVER last said no to, if it said anything. A claim it refuses
        # answers with an `errorCode`, and a run that claimed and was refused otherwise
        # reads as a run that did nothing at all.
        ".. ((A.last_error and now > 0 and (tonumber(A.last_error_at) or 0) > 0 "
        "and now - A.last_error_at < 60000) "
        "and (' server-said=[' .. tostring(A.last_error) .. ']') or '') "
        ".. ' [' .. table.concat(notes, ' ') .. ']' "
        "A.did = sent + (tonumber(A.s_claimed) or 0) "
        'CS.UnityEngine.Debug.LogError("ACT treasure_auto_step " .. A.report)'
    )


def treasure_queue_one_parked() -> str:
    """Put ONE named chest into the errand's queue — the press a single row makes (#1318).

    A row on «Командный пункт» knows exactly which chest it is drawn for, and until now
    each of its two buttons drove the game by hand: «Копать» assembled a march, «Забрать»
    sent one claim and reported the send as the result. A send that returns cleanly proves
    nothing (`docs/research/world-treasures.md`), which is precisely why the player found
    the button unreliable — it said «взято» and nothing arrived.

    So a row now parks its chest here and the ERRAND takes it: the same queue, the same
    squad pairing, the same watch that claims at the dig's deadline and keeps trying until
    the chest is paid or gone. The recipe is `actions/take_treasure.md`; a `TAP` carries no
    arguments, so what it was given travels on the VM as
    `DataCenter.__lw_treasure_one = {uuid=…, server=…, pid=…, x=…, y=…}` — the same hand-off
    the rally's join uses for its squads.

    A chest already in the queue is UPGRADED rather than duplicated: a target heard through
    the dig feed carries a uuid and no tile, and a row that has one fills it in — which is
    the difference between «claim it and hope» and «march on it». A chest already spent is
    started over on purpose: this is somebody pressing the button, and the press means «try
    it again» in the one case a person can see something the errand cannot.
    """
    return (
        "local D = DataCenter "
        "if not D.__lw_treasure_auto then D.__lw_treasure_auto = "
        "{seen={}, targets={}, news=0} end "
        "local A = D.__lw_treasure_auto "
        "local one = D.__lw_treasure_one or {} "
        "local uuid = one.uuid "
        "local now = 0 pcall(function() "
        "now = math.floor(tonumber(UITimeManager.Instance:GetServerTime()) or 0) end) "
        "if now <= 0 then pcall(function() "
        "now = math.floor((tonumber(ChatInterface.getServerTime()) or 0) * 1000) end) end "
        "if uuid == nil or tostring(uuid) == '0' then "
        'CS.UnityEngine.Debug.LogError("ACT treasure_one none") return end '
        "local key = tostring(uuid) "
        "local pid = tonumber(one.pid) or 0 "
        "local found = nil "
        "for _, t in ipairs(A.targets or {}) do "
        "if tostring(t.uuid) == key then found = t end end "
        "local what = 'new' "
        "if found ~= nil then what = 'again' "
        "found.done, found.why, found.state = nil, nil, nil "
        "found.tries, found.claimed, found.err = 0, nil, nil "
        "found.at = now "
        "if pid > 0 and (tonumber(found.pid) or 0) == 0 then "
        "found.pid, found.x, found.y = pid, tonumber(one.x) or 0, tonumber(one.y) or 0 "
        "found.claim_only = false what = 'upgraded' end "
        "if (tonumber(one.server) or 0) ~= 0 then found.server = tonumber(one.server) end "
        "else "
        "A.seen = A.seen or {} A.seen[key] = A.seen[key] or now "
        "A.targets = A.targets or {} "
        "A.targets[#A.targets+1] = {uuid = uuid, pid = pid, "
        "x = tonumber(one.x) or 0, y = tonumber(one.y) or 0, "
        "server = tonumber(one.server) or 0, at = now, src = 'row', "
        "claim_only = (pid == 0)} "
        "A.news = (tonumber(A.news) or 0) + 1 end "
        'CS.UnityEngine.Debug.LogError("ACT treasure_one " .. what .. " queued="'
        "..tostring((function() local n = 0 "
        "for _, t in ipairs(A.targets or {}) do if not t.done then n = n + 1 end end "
        "return n end)()))"
    )


def treasure_auto_report() -> str:
    """Lua *expression* -> the sentence the last step wrote, or a word saying it never ran."""
    return ("(DataCenter.__lw_treasure_auto and DataCenter.__lw_treasure_auto.report "
            "or 'the step left no report — the press did not run')")


def treasure_auto_did() -> str:
    """Lua *expression* -> how many sends the last step made (a march or a claim)."""
    return ("(function() local A = DataCenter.__lw_treasure_auto "
            "if A == nil then return 0 end return tonumber(A.did) or 0 end)()")


def treasure_auto_dump() -> str:
    """Lua *expression* -> one line per queued chest: where it is and what stage it is at.

    A reading, for the log and for the debug page. Positions and uuids are the account's
    own and belong on screen, never in this repository (CLAUDE.md).
    """
    return (
        "(function() local A = DataCenter.__lw_treasure_auto "
        "if A == nil then return 'the auto errand has never been armed' end "
        "local out = {} "
        "for i, t in ipairs(A.targets or {}) do "
        "local st = 'new' "
        "if t.claimed then st = 'claimed' elseif t.dug then st = 'dug' "
        "elseif t.sent then st = 'digging' end "
        "out[#out+1] = tostring(i) .. ') @[' .. tostring(t.x) .. ',' .. tostring(t.y) "
        ".. '|' .. tostring(t.server) .. '] ' .. st "
        ".. (t.squad and (' squad' .. tostring(t.squad)) or '') end "
        "if #out == 0 then return 'no chest is queued (on=' "
        ".. tostring(A.on and 1 or 0) .. ', heard=' .. tostring(A.news or 0) .. ')' end "
        "return table.concat(out, ' ; ') end)()"
    )


# --- The third door: a sweep of the MAP itself -------------------------------
# «Скрытые сокровища не собираются, если они просто на карте, даже если карту обновлять,
# проверяется не то, должно сканироваться карта на предмет сокровищ, а не только
# слушаться пуш шаринга.» The two doors above are both somebody TELLING the client about
# a chest — the alliance chat share, which a player may simply never send, and the dig
# broadcast, which carries a uuid and no tile. Neither of them looks at the map, so a
# chest that is merely LYING there is invisible to both.
#
# WHAT «ОБНОВИТЬ» ASKS, AND WHY IT IS NOT THIS. The refresh on «Командный пункт» sends
# `activity.detect.list` and reads `ActDetectTreasureDataManager` — the account's own
# detect-event list, i.e. the chests THIS alliance's event placed. A chest another
# alliance put out, or one this client was never told about, is not in that reply no
# matter how often it is asked for. That is the «проверяется не то» exactly.
#
# AND THE MAP IS NOT READABLE OFF THE LUA WIRE. Measured live on 2026-08-08: with the
# watcher in `wide` mode (it keeps every command), three jumps at height 600 produced no
# `world.get.block` in the ring at all — only ordinary pushes. The map stream is decoded
# on the C# side and never reaches `SFSNetwork.HandleMessage`, so no hook in Lua can hear
# it and the pcap scanners (`tools/dev/treasure_capture.py`) exist for that reason.
#
# WHAT IS READABLE is the client's OWN point manager, which is what the zoom research
# measured the map with (docs/research/map-sweep-zoom.md §2):
#
#     WS.PointManager:GetPointInfo(pid)   -- nil when the client does not know that tile
#     info.PointType == 21               -- WorldPointType.TREASURE, the wire's `f2`
#     info.uuid, info.serverId           -- read live off a neighbouring kind:
#                                        -- HeroDispatchMissionPointInfo answers
#                                        -- uuid=<19 digits> serverId=<n> cfgId=<n>
#
# …and its one limit is the whole design here: **it only holds what is in view**. Jump
# away and the old tiles go back to unknown. So the scrape has to ride the sweep, one box
# per waypoint, which is what this does — the waypoint list goes to the game's own timer
# exactly as `fast_map_sweep` schedules it, and a second timer a moment behind each jump
# reads the box that jump loaded.
#
# Measured on the live client (1000 × 1000 server, height 600, step 90): a 121 × 121 box
# is **0.040 s** inside the VM, and the tile index needs no call at all —
# `pid = y * size + x + 1` was checked against `SceneUtils.TilePosToIndex` at four
# coordinates and agrees. The whole lap is that box times the waypoint count, spread over
# the lap rather than spent in one place.

#: How long after a waypoint's jump its box is read, and how long the camera then stands
#: still — the two numbers that decide what a lap comes home with, and both are measured.
#:
#: A jump asks the server for its tiles and the point manager fills in ONE step: read live
#: at two spots, the box was empty at 0.05 / 0.10 / 0.15 s and complete at 0.20–0.30 s
#: (1250 and 319 tiles respectively), and no later reading added a single one. So the lag
#: is a shade past the fill and the pause is a shade past the lag.
#:
#: **This is why a treasure lap is not the 6.5 s the plain sweep is.** `fast_map_sweep`
#: moves the camera every 0.05 s because a pcap listener catches the replies whenever they
#: land; a lap that READS the client has to be standing where it is looking. Measured: at
#: 0.05 s a whole lap of 121 waypoints knew 2599 tiles in total — twenty a stop, against
#: the 500–1250 a stop holds when it is given its quarter of a second.
TREASURE_SCAN_LAG = 0.30

#: …and the pause between two waypoints. 121 waypoints at this is about 48 s of camera,
#: which is the honest price of reading the map out of the client rather than off a wire.
TREASURE_SCAN_STEP_SEC = 0.40


#: How often the map is worth re-reading. A chest is out for MINUTES and the alliance
#: digs it together, so the useful cadence is minutes — five of them here. The errand's
#: own tick is ten seconds and hears the two announcement doors in that second; the lap
#: is the door for a chest nobody announced, and it costs a camera that walks the whole
#: server, so it is deliberately the slowest of the three.
TREASURE_SCAN_EVERY_SEC = 300


def treasure_scan_sweep(zoom: "int | None" = None, step: "int | None" = None,
                        interval: "float | None" = None,
                        server: "int | None" = None,
                        lag: float = TREASURE_SCAN_LAG) -> str:
    """One lap of the whole map that READS it — every `PointType 21` tile it passes.

    The lap itself is `fast_map_sweep`'s: the waypoints are handed to the game's own
    `TimerManager` in one call and walked inside the game, so nothing here is a round trip
    per stop. What is added is a second timer per waypoint, `lag` behind the jump, which
    reads the box that jump loaded out of `WorldScene.PointManager` and keeps the chests —
    and a PAUSE, because a camera that has already left is a box that reads empty
    (:data:`TREASURE_SCAN_LAG`).

    The findings land in `DataCenter.__lw_treasure_scan.found`, keyed by uuid so a chest
    seen from two overlapping boxes is one finding. Nothing is sent, nothing is claimed
    and no window opens: the lap moves the camera and reads memory.

    A lap can be disowned exactly as the plain sweep can — both share
    `DataCenter.ActDispatchTaskDataManager.__lw_sweep_run`, so `fast_map_sweep_stop()`
    stops this one too, and the scrapes check the same token before touching anything.

    EVERY NUMBER CAN BE PARKED, because a `TAP` carries no arguments (`docs/dsl.md`) and
    this is meant to be pressed by a recipe: `DataCenter.__lw_treasure_scan_cfg`
    (`{zoom, step, every, lag, server}`) is read first and the arguments here are the
    fallback for each one, so the same button works pressed bare.
    """
    height = int(SWEEP_ZOOM_MAX if zoom is None else zoom)
    stride = max(1, int(FAST_STEP if step is None else step))
    gap = max(0.0, float(TREASURE_SCAN_STEP_SEC if interval is None else interval))
    where = str(int(server)) if server else current_server_expr()
    return (FIND_WORLD_SCENE + '''
local DC = DataCenter.ActDispatchTaskDataManager
local S = {found = {}, n = 0, done = 0, tiles = 0, known = 0, chests = 0,
           errs = 0, blind = 0}
DataCenter.__lw_treasure_scan = S
DC.__lw_sweep_run = (tonumber(DC.__lw_sweep_run) or 0) + 1
local run = DC.__lw_sweep_run
S.run = run
local cfg = DataCenter.__lw_treasure_scan_cfg or {}
local srv = tonumber(cfg.server) or 0
if srv == 0 then srv = %s end
local size = 1000
pcall(function() size = WS.TileCount.x end)
S.server = srv
local height = tonumber(cfg.zoom) or %d
local step = math.max(1, math.floor(tonumber(cfg.step) or %d))
local gap = math.max(0, tonumber(cfg.every) or %f)
local lag = math.max(0, tonumber(cfg.lag) or %f)
local half = math.floor(step / 2)
-- The box each waypoint reads. Half a step covers the strip between two neighbouring
-- waypoints exactly; the margin is for the map's edge rows, where the axis stops short
-- of the border.
local box = half + 8
local axis = {}
local v = half
while v < size do axis[#axis+1] = v v = v + step end
local V3, tm = CS.UnityEngine.Vector3, TimerManager:GetInstance()
-- One member at a time and each read guarded: a point info is a C# object whose class
-- differs per kind, so a field the treasure class does not have would throw where a
-- missing value is wanted instead.
local function get(o, k)
  local ok, v = pcall(function() return o[k] end)
  if ok then return v end
  return nil
end
local function scrape(cx, cy)
  if DC.__lw_sweep_run ~= run then return end
  -- THE SCENE IS LOOKED UP AGAIN, not held. A WorldScene is replaced whenever the world
  -- is re-entered and a destroyed one answers `nil` to everything without throwing, so a
  -- lap that captured it at the start would read an empty map in silence — which is
  -- exactly what happened the first time this ran live (121 waypoints scheduled, 0 read).
  local scene = _G.WS
  local pm = scene and scene.PointManager
  if pm == nil then S.blind = (S.blind or 0) + 1 return end
  local x0, x1 = math.max(0, cx - box), math.min(size - 1, cx + box)
  local y0, y1 = math.max(0, cy - box), math.min(size - 1, cy + box)
  for ty = y0, y1 do
    local base = ty * size + 1
    for tx = x0, x1 do
      local ok, info = pcall(function() return pm:GetPointInfo(base + tx) end)
      if ok then
        S.tiles = S.tiles + 1
        -- HOW MANY OF THOSE THE CLIENT ACTUALLY KNEW, which is the difference between «no
        -- chest on the map» and «the lap ran over a client nobody was answering». `tiles`
        -- is only how many ids were asked about — it is the same number on a dead link.
        if info ~= nil then S.known = S.known + 1 end
        if info ~= nil and (tonumber(get(info, "PointType")) or -1) == %d then
          local uuid = get(info, "uuid")
          if uuid ~= nil and tostring(uuid) ~= "0" then
            local key = tostring(uuid)
            if S.found[key] == nil then
              S.chests = S.chests + 1
              -- `TreasurePointInfo`, read off the first chests ever scanned live
              -- (2026-08-08): `uuid`, `serverId`, `allianceId`, `allianceAbbr`,
              -- `expireTime`, `ownerUid`. Two of those matter here.
              --
              -- `ownerUid` is the wire's `f11.7` — the finisher — and it is READ AS A
              -- HINT rather than as a verdict, which is the difference that matters.
              -- Measured on the first live lap: 19 chests out of 19 carried it, and the
              -- one of them this account could reason about (its own alliance's) answered
              -- a claim with `errorCode 801348 — claim repeat`. So it does look like «this
              -- chest has been worked», but no chest has ever been caught WITHOUT it, and
              -- a gate needs a success recording (`CLAUDE.md`).
              --
              -- Read as a hint it cannot do harm, and since #1886 it is read FIRST: a
              -- chest marked dug is claimed before a squad is spent on it, and marched at
              -- only when the server has refused that claim `TREASURE_CLAIM_FIRST_TRIES`
              -- times (see `_TREASURE_TICK`). The order was the other way round until a
              -- recording settled it: a dug chest cost 100 s of dropped marches and was
              -- then paid on the first blind claim. Being wrong this way costs the length
              -- of the claim ramp; being wrong the other way costs a hundred seconds, and
              -- writing the chest off as unworkable would cost the chest.
              --
              -- `expireTime` is the chest's OWN deadline, in the game's milliseconds. It
              -- beats any age the errand could keep: a chest is worked until the map
              -- takes it away, and the map says when that is.
              local who = tostring(get(info, "ownerUid") or "")
              S.found[key] = {uuid = uuid, pid = base + tx, x = tx, y = ty,
                              server = tonumber(get(info, "serverId")) or srv,
                              expire = tonumber(get(info, "expireTime")) or 0,
                              owner = who,
                              cfg = tonumber(get(info, "cfgId"))
                                    or tonumber(get(info, "treasureId")) or 0,
                              alliance = tostring(get(info, "allianceId") or ""),
                              dug = (who ~= "" and who ~= "0")}
            end
          end
        end
      else
        S.errs = S.errs + 1
      end
    end
  end
  S.done = S.done + 1
end
local n = 0
for row = 1, #axis do
  local y = axis[row]
  for col = 1, #axis do
    local x = axis[(row %% 2 == 1) and col or (#axis - col + 1)]
    n = n + 1
    local at = (n - 1) * gap
    tm:DelayInvoke(function()
      if DC.__lw_sweep_run ~= run then return end
      pcall(function() GoToUtil.GotoWorldPos(V3(x*2+1, 0, y*2+1), height, 0, nil, srv) end)
    end, at)
    tm:DelayInvoke(function() pcall(scrape, x, y) end, at + lag)
  end
end
S.n = n
S.span = (n - 1) * gap + lag
CS.UnityEngine.Debug.LogError("ACT treasure_scan n="..n.." zoom="..height.." step="..step
  .." box="..box.." span="..string.format("%%.1f", S.span).." size="..tostring(size)
  .." srv="..tostring(srv))
''' % (where, height, stride, gap, float(lag), TREASURE_POINT_TYPE))


#: How far around the camera a look reads, in tiles. Not a view rect — the point manager
#: holds what the client has been ANSWERED about, which is a good deal more than the glass
#: shows and costs nothing extra to walk. A 121 × 121 box is the same size as one waypoint
#: of the old lap, measured at 0.03–0.04 s inside the VM.
TREASURE_LOOK_BOX = 60


def treasure_look_around() -> str:
    """Read the chests in what the client is ALREADY looking at. Moves nothing.

    THE LAP IS GONE AND THIS IS WHAT REPLACED IT (#1296). Walking the whole server every
    few minutes was measured and was not worth its camera: two full laps found 19 and 21
    chests, and **ours was zero both times** — a chest of one's own alliance is placed in
    the hive, not out on the open map, so 48 s of camera every five minutes bought a
    census of other people's treasure. What is worth keeping is the READING, which was
    never the expensive half: the client's own `WorldScene.PointManager` holds every tile
    it has been answered about, so a chest we drive past is a chest we can see for free.

    So this is the same scrape as the lap's, with the jumps taken out: one box around
    where the camera happens to be, whenever the errand ticks and the client is in the
    world. It never jumps, never changes the zoom and never touches the server — a person
    playing on the map notices nothing at all, which is the whole point of hanging it on
    an ordinary tick.

    Its findings land in `DataCenter.__lw_treasure_scan.found` exactly as the lap's did, so
    :func:`treasure_scan_harvest` reads it unchanged — and a chest seen twice stays one.
    `n`/`done` are 1: one box, read once.

    The manual lap (`actions/scan_treasures.md`) is still there for somebody who WANTS a
    census, and is off unless pressed.
    """
    return (FIND_WORLD_SCENE + '''
local S = {found = {}, n = 1, done = 0, tiles = 0, known = 0, chests = 0,
           errs = 0, blind = 0, span = 0, look = true}
DataCenter.__lw_treasure_scan = S
local world = false
pcall(function() world = SceneUtils.GetIsInWorld() and true or false end)
if not world then
  S.why = "not-in-world"
  CS.UnityEngine.Debug.LogError("ACT treasure_look not-in-world")
  return
end
local scene = _G.WS
local pm = scene and scene.PointManager
if pm == nil then
  S.blind, S.why = 1, "no-point-manager"
  CS.UnityEngine.Debug.LogError("ACT treasure_look no-point-manager")
  return
end
local size = 1000
pcall(function() size = scene.TileCount.x end)
-- WHERE THE CAMERA ALREADY IS. Not chosen, not moved to — read.
local cx, cy = -1, -1
pcall(function() cx, cy = scene.CurTilePos.x, scene.CurTilePos.y end)
cx, cy = math.floor(tonumber(cx) or -1), math.floor(tonumber(cy) or -1)
if cx < 0 or cy < 0 then
  S.why = "no-camera-tile"
  CS.UnityEngine.Debug.LogError("ACT treasure_look no-camera-tile")
  return
end
S.at_x, S.at_y = cx, cy
local srv = 0
pcall(function() srv = tonumber(LuaEntry.Player.serverId) or 0 end)
S.server = srv
local box = %d
local function get(o, k)
  local ok, v = pcall(function() return o[k] end)
  if ok then return v end
  return nil
end
local x0, x1 = math.max(0, cx - box), math.min(size - 1, cx + box)
local y0, y1 = math.max(0, cy - box), math.min(size - 1, cy + box)
-- WHICH OF THE CHESTS WE ARE WORKING THIS BOX CAN SPEAK FOR (#1898). A tile the client
-- holds and that carries no treasure is the map saying the chest is not there — the
-- second, wire-free half of «цели больше нет». It is only trustworthy for a tile the
-- point manager ANSWERED about: an unloaded tile answers `nil` too, and reading that as
-- «gone» would throw away a live chest the camera merely walked away from. So the answer
-- is recorded per pid, and only for the handful of pids this errand is tracking.
local want, A0 = {}, DataCenter.__lw_treasure_auto
if A0 ~= nil then
  for _, t in ipairs(A0.targets or {}) do
    if not t.done and (tonumber(t.pid) or 0) > 0 then want[tonumber(t.pid)] = true end
  end
end
S.checked = {}
for ty = y0, y1 do
  local base = ty * size + 1
  for tx = x0, x1 do
    local ok, info = pcall(function() return pm:GetPointInfo(base + tx) end)
    if ok then
      S.tiles = S.tiles + 1
      if info ~= nil then S.known = S.known + 1
        if want[base + tx] then S.checked[base + tx] = true end
      end
      if info ~= nil and (tonumber(get(info, "PointType")) or -1) == %d then
        local uuid = get(info, "uuid")
        if uuid ~= nil and tostring(uuid) ~= "0" then
          local key = tostring(uuid)
          if S.found[key] == nil then
            S.chests = S.chests + 1
            local who = tostring(get(info, "ownerUid") or "")
            S.found[key] = {uuid = uuid, pid = base + tx, x = tx, y = ty,
                            server = tonumber(get(info, "serverId")) or srv,
                            expire = tonumber(get(info, "expireTime")) or 0,
                            owner = who,
                            cfg = tonumber(get(info, "cfgId"))
                                  or tonumber(get(info, "treasureId")) or 0,
                            alliance = tostring(get(info, "allianceId") or ""),
                            dug = (who ~= "" and who ~= "0")}
          end
        end
      end
    else
      S.errs = S.errs + 1
    end
  end
end
S.done, S.why = 1, "looked"
CS.UnityEngine.Debug.LogError("ACT treasure_look at=" .. tostring(cx) .. "," .. tostring(cy)
  .. " tiles=" .. tostring(S.tiles) .. " known=" .. tostring(S.known)
  .. " chests=" .. tostring(S.chests))
''' % (int(TREASURE_LOOK_BOX), TREASURE_POINT_TYPE))


def treasure_scan_state() -> str:
    """Lua *expression* -> how far the lap has got and what it has found so far.

    ``done=<n>/<n> chests=<n> tiles=<n> span=<s> errs=<n>`` — a reading, so a recipe can
    say whether it waited long enough instead of assuming it did. `done` short of `n`
    means the lap is still walking (or was stopped); `tiles` is how many point ids were
    looked at, which is the difference between «no chest on the map» and «the point
    manager answered nothing at all».
    """
    return (
        "(function() local S = DataCenter.__lw_treasure_scan "
        "if S == nil then return 'no lap has been run' end "
        "local c = 0 for _ in pairs(S.found or {}) do c = c + 1 end "
        "return 'done=' .. tostring(S.done or 0) .. '/' .. tostring(S.n or 0) "
        ".. ' chests=' .. tostring(c) "
        ".. ' tiles=' .. tostring(S.tiles or 0) "
        ".. ' known=' .. tostring(S.known or 0) "
        ".. ' blind=' .. tostring(S.blind or 0) "
        ".. ' span=' .. string.format('%.1f', tonumber(S.span) or 0) "
        ".. ' errs=' .. tostring(S.errs or 0) end)()"
    )


def treasure_scan_harvest() -> str:
    """Turn what the lap found into targets of the auto errand — the third door.

    THREE DOORS, ONE LIST. A chest that arrives twice is one target and keeps whichever
    half of the truth each door has: the dig feed brings a uuid and no tile (`claim_only`),
    and this brings the tile — so a target already queued without one is UPGRADED here
    rather than duplicated, and stops being claim-only the moment a squad can be sent to
    it. `A.seen` is not consulted for that: it remembers uuids the hook has already turned
    into targets, and a chest still on the map is worth marching at whether or not the
    hook heard of it first.

    A CHEST BELONGS TO AN ALLIANCE, and this is where the lap earns its keep. The first
    live lap found nineteen chests on the map and the account could take none of them:
    the claims came back `errorCode 801354 — player not in same alliance`. A detect-event
    treasure is placed by ONE alliance's event and dug by ITS members, so a chest whose
    `allianceId` is not this player's is not a chest this player has, however plainly it
    is drawn on the map. They are counted as `foreign=` and never queued — a march at one
    spends a squad on a tile the server will not pay for.

    **AND THE THREE NUMBERS ARE SAID SEPARATELY, ALWAYS.** «Found 19» on its own is a
    promise of nineteen gifts, and eighteen of those nineteen are somebody else's chest
    that this account cannot touch — so the report leads with `found=` / `ours=` /
    `foreign=` and never with a single total. A number that does not distinguish two
    states is worse than no number: it reads as good news and is not.

    Nothing is sent from here. The step that follows is the one that marches and claims.
    """
    return (
        "local S = DataCenter.__lw_treasure_scan "
        "local D = DataCenter "
        "if not D.__lw_treasure_auto then D.__lw_treasure_auto = "
        "{seen={}, targets={}, news=0} end "
        "local A = D.__lw_treasure_auto "
        "local now = 0 pcall(function() "
        "now = math.floor(tonumber(UITimeManager.Instance:GetServerTime()) or 0) end) "
        "if now <= 0 then pcall(function() "
        "now = math.floor((tonumber(ChatInterface.getServerTime()) or 0) * 1000) end) end "
        "local mine = '' "
        "pcall(function() mine = tostring(LuaEntry.Player.allianceId or '') end) "
        "local fresh, grown, known, foreign, spent = 0, 0, 0, 0, 0 "
        "for key, f in pairs((S or {}).found or {}) do "
        "if mine ~= '' and tostring(f.alliance or '') ~= '' "
        "and tostring(f.alliance) ~= mine then foreign = foreign + 1 "
        # A CHEST THIS ERRAND HAS ALREADY FINISHED WITH IS NOT A FINDING (#1898). The look
        # reads the ground, and the ground goes on drawing a chest this account has been
        # paid for. Without the ledger the third door hands it back as news the moment the
        # prune drops it from the list, and a paid chest is claimed all over again.
        "elseif (A.spent or {})[key] ~= nil then spent = spent + 1 "
        "else "
        "local seen_here = nil "
        "for _, t in ipairs(A.targets or {}) do "
        "if tostring(t.uuid) == key then seen_here = t end end "
        "if seen_here ~= nil then "
        # The tile is the thing this door has and the others may not. A target parked by
        # the dig feed carries a uuid and zeros; filling those in is what turns it from
        # «claim it and hope» into «march on it».
        "if (tonumber(seen_here.pid) or 0) == 0 then "
        "seen_here.pid, seen_here.x, seen_here.y = f.pid, f.x, f.y "
        "seen_here.server = tonumber(f.server) or seen_here.server "
        "seen_here.claim_only = false "
        "seen_here.src = tostring(seen_here.src or '?') .. '+scan' "
        "grown = grown + 1 "
        "else known = known + 1 end "
        "if (tonumber(seen_here.cfg) or 0) == 0 then "
        "seen_here.cfg = tonumber(f.cfg) or 0 end "
        "else "
        "A.seen = A.seen or {} A.seen[key] = A.seen[key] or now "
        "A.targets = A.targets or {} "
        # THE STATUS THE CHEST WAS IN WHEN IT WAS FOUND, written down as the plan
        # (#1886): a chest the tile says is already dug is claimed and never marched at;
        # one that is still being dug gets a squad. The branch is taken here, once, rather
        # than rediscovered by whoever looks next.
        "A.targets[#A.targets+1] = {uuid = f.uuid, pid = f.pid, x = f.x, y = f.y, "
        "server = tonumber(f.server) or 0, at = now, src = 'scan', "
        "expire = tonumber(f.expire) or 0, cfg = tonumber(f.cfg) or 0, "
        "plan = (f.dug and 'claim' or 'march'), "
        "dug_by = (f.dug and 'tile' or nil), "
        "dug = (f.dug and now or nil)} "
        "A.news = (A.news or 0) + 1 "
        "fresh = fresh + 1 end end end "
        # A CHEST THE MAP CAN SPEAK FOR AND DOES NOT MENTION IS GONE (#1898). The wire
        # says it best — `E100123 treasure is null` — but only in answer to a claim, and a
        # chest waiting for a squad is never claimed. This is the same fact read off the
        # ground: the look marked every tracked tile the point manager ANSWERED about, and
        # a tracked chest whose tile answered and holds no treasure is not there any more.
        # An unloaded tile is not an answer and says nothing, which is the whole reason the
        # look records which tiles it got.
        "local vanished = 0 "
        "local checked = (S or {}).checked or {} "
        "local found = (S or {}).found or {} "
        "for _, t in ipairs(A.targets or {}) do "
        "if not t.done and (tonumber(t.pid) or 0) > 0 "
        "and checked[tonumber(t.pid)] and found[tostring(t.uuid)] == nil "
        # …unless a claim of ours is still in the air. The server's own answer is the
        # better verdict and it is seconds away; a tile that vanished because the chest was
        # just paid for would otherwise be filed as a loss.
        "and (now == 0 or now - (tonumber(t.claimed) or 0) > 5000) then "
        "t.done, t.why, t.done_at = true, 'tile-gone', now "
        "t.state = 'tile-gone' "
        "A.spent = A.spent or {} A.spent[tostring(t.uuid)] = 'tile-gone' "
        "A.gone_all = (tonumber(A.gone_all) or 0) + 1 "
        "A.gone_last = 'tile-gone @[' .. tostring(t.x) .. ',' .. tostring(t.y) .. ']' "
        "A.gone_last_at = now "
        "A.s_gone = (tonumber(A.s_gone) or 0) + 1 "
        "vanished = vanished + 1 end end "
        "local looked = tonumber((S or {}).tiles) or 0 "
        # …and a chest already finished with still COUNTS as one of ours on the ground:
        # `found=` is what the box holds, not what is left to do about it.
        "local ours = fresh + grown + known + spent "
        "A.scan_at = now "
        # The three numbers, kept as numbers as well as said in a sentence — the panel
        # draws them apart from each other and must not have to parse a line to do it.
        "A.scan_found = ours + foreign "
        "A.scan_ours = ours "
        "A.scan_foreign = foreign "
        "A.scan_report = 'found=' .. tostring(ours + foreign) "
        ".. ' ours=' .. tostring(ours) .. ' foreign=' .. tostring(foreign) "
        ".. ' (new=' .. tostring(fresh) .. ' upgraded=' .. tostring(grown) "
        ".. ' already-queued=' .. tostring(known) "
        ".. (spent > 0 and (' done-with=' .. tostring(spent)) or '') "
        # …and what the ground itself struck out this look, in its own word.
        ".. (vanished > 0 and (' vanished=' .. tostring(vanished)) or '') .. ')' "
        ".. ' waypoints=' .. tostring((S or {}).done or 0) "
        ".. '/' .. tostring((S or {}).n or 0) "
        ".. ' tiles=' .. tostring(looked) "
        ".. ' known=' .. tostring(tonumber((S or {}).known) or 0) "
        # The chests still to be worked — NOT the length of the list, which also holds the
        # ones already spent and kept only so the next lap does not start them over.
        ".. ' queued=' .. tostring((function() local n = 0 "
        "for _, t in ipairs(A.targets or {}) do if not t.done then n = n + 1 end end "
        "return n end)()) "
        'CS.UnityEngine.Debug.LogError("ACT treasure_scan_harvest " .. A.scan_report)'
    )


def treasure_scan_report() -> str:
    """Lua *expression* -> the sentence the last harvest wrote."""
    return ("(DataCenter.__lw_treasure_auto and "
            "DataCenter.__lw_treasure_auto.scan_report "
            "or 'no lap has been harvested')")


def treasure_scan_counts() -> str:
    """Lua *expression* -> `found=<n> ours=<n> foreign=<n> queued=<n> ago=<s>`.

    THE SPLIT IS THE POINT. A lap of a live map found nineteen chests and eighteen of
    them belonged to other alliances, which the server refuses outright — so a screen or
    a log line saying «19 found» promises nineteen gifts and delivers one. This is what
    the panel draws, and it draws the three numbers apart.

    `ago` is seconds since the last lap on the GAME's clock, or `-1` when none has been
    walked in this client — the same distinction: «none found» and «never looked» are
    different answers and must not share a zero.
    """
    return (
        "(function() local A = DataCenter.__lw_treasure_auto "
        "if A == nil or (tonumber(A.scan_at) or 0) <= 0 then "
        "return 'found=0 ours=0 foreign=0 queued=0 ago=-1' end "
        "local now = 0 pcall(function() "
        "now = math.floor(tonumber(UITimeManager.Instance:GetServerTime()) or 0) end) "
        "local ago = -1 "
        "if now > 0 then ago = math.floor((now - A.scan_at) / 1000) end "
        "return 'found=' .. tostring(tonumber(A.scan_found) or 0) "
        ".. ' ours=' .. tostring(tonumber(A.scan_ours) or 0) "
        ".. ' foreign=' .. tostring(tonumber(A.scan_foreign) or 0) "
        ".. ' queued=' .. tostring(#(A.targets or {})) "
        ".. ' ago=' .. tostring(ago) end)()"
    )


def treasure_scan_ask(every_sec: int = TREASURE_SCAN_EVERY_SEC) -> str:
    """Decide whether a lap is worth walking right now, and park the answer.

    `DataCenter.__lw_treasure_scan_due` becomes `1` or `0`, which is what the recipe
    reads: a `TAP` returns nothing, and the rule belongs here rather than copied into a
    recipe where it would drift from this one.

    Three questions, all local and all cheap, because this is asked on the errand's own
    tick and a lap that cannot help must not cost one:

      * is the client in the WORLD? The point manager belongs to the world scene, and a
        lap started from the city would move the camera out from under whoever is
        looking at their base;
      * has `every_sec` passed since the last lap? A chest is out for minutes, so the
        map is worth re-reading in minutes and not in seconds;
      * is the client answering at all? Without the game's own clock there is no telling
        one lap from the next, and a lap walked on a client that is loading is a camera
        thrown across a map nobody is connected to.

    A queue that already has chests in it is NOT a reason to skip: a chest placed a
    minute ago is exactly what the lap is for, and the errand works several at once.

    The period is `DataCenter.__lw_treasure_scan_cfg.every` when the recipe parked one,
    and `every_sec` otherwise. **Deciding it is due STAMPS the clock**, so a tick that
    asks twice does not walk two laps — and a lap that then fails to start still costs
    the period rather than being retried every ten seconds.
    """
    return (
        "local D = DataCenter "
        "local cfg = D.__lw_treasure_scan_cfg or {} "
        "local every = math.max(0, tonumber(cfg.every_sec) or "
        + str(int(every_sec)) + ") "
        "local world = false "
        "pcall(function() world = SceneUtils.GetIsInWorld() and true or false end) "
        "local now = 0 pcall(function() "
        "now = math.floor(tonumber(UITimeManager.Instance:GetServerTime()) or 0) end) "
        "local A = D.__lw_treasure_auto "
        "local last = tonumber(A and A.scan_at) or 0 "
        "local why = 'due' "
        "local due = 1 "
        "if not world then due, why = 0, 'not-in-world' "
        "elseif now <= 0 then due, why = 0, 'no-game-clock' "
        "elseif every <= 0 then due, why = 0, 'switched-off' "
        "elseif last > 0 and now - last < every * 1000 then due, why = 0, "
        "'last-lap-' .. tostring(math.floor((now - last) / 1000)) .. 's-ago' end "
        "if due == 1 and A ~= nil then A.scan_at = now end "
        "D.__lw_treasure_scan_due = due "
        'CS.UnityEngine.Debug.LogError("ACT treasure_scan_due " .. tostring(due) '
        '.. " " .. why .. " every=" .. tostring(every))'
    )


# --------------------------------------------------------------------------
# Hospital — heal wounded soldiers ("Лечение юнитов")
# --------------------------------------------------------------------------
# The base hospital (`LWUIHospital`, view `LWUIHospitalView`) heals wounded soldiers.
# One press of its cure button sends ONE message — the wire shape captured in
# `20260729_152749` / `20260729_152841`, the caller side read off the live VM
# (docs/research/hospital-heal.md):
#
#     SFSNetwork.SendMessage(MsgDefines.HospitalCure, {      -- "hospital.cure"
#         armyArray = { {armyId = <string>, count = <int>}, ... },
#         gold      = 0,           -- gold spent on the heal (0 = the free heal)
#     })
#
# The message class `HospitalCureMessage` renames the per-entry `count` to `healNum`
# on the wire (`PutUtfString(armyId, tostring(one.armyId))` + `PutInt(healNum, …)`),
# which is why the trace shows `healNum` and the caller passes `count`. `gold` is NOT
# optional (the serialiser packs it as an int; a missing one aborts the send with
# "bad argument #2 to 'pack'"), and `worldType` the class fills in itself.
#
# Do NOT add `goldForTime` / `goldForResource` / `itemIds`: they belong to the
# pay-to-finish branch, and passing them even as 0/"" makes `OnCreate` skip `armyArray`
# altogether, so the server answers errorCode E000000 and nothing heals. The recorded
# human press (20260729_182527, no dedup) puts exactly armyArray + gold + worldType.
#
# The wounded list is `DataCenter.HospitalManager.allHospital`, keyed by armyId. A row
# carries exactly three server fields (`HospitalInfo`: armyId, heal, dead):
#
#     allHospital[3014] = {armyId = 3014, dead = 365, heal = 0}
#       -- dead : wounded of that type waiting in the hospital — the pool to heal
#       -- heal : how many of them are already in treatment
#
# (`curCount`, if present, is NOT from the server: the window stamps its own suggested
# amount onto the row — the slice of the wounded that fits the player's chosen cure
# time. Reading it as the wounded count gives a number that is only there after the
# window has been opened, which is why the heal is built from `dead`.)
#
# so the whole thing runs headless — no window is opened.
def _hospital_army_literal(entries) -> str:
    """Render `[(armyId, count), ...]` as the Lua `armyArray` table literal.

    armyId is forced to a string (UtfString on the wire), the count to an int.
    """
    parts = []
    for army_id, count in entries:
        parts.append('{armyId="%s",count=%d}' % (str(army_id), int(count)))
    return "{" + ",".join(parts) + "}"


# `SFSNetwork.SendMessage("hospital.cure", param)` cannot build `armyArray` on its own.
# `HospitalCureMessage:OnCreate` silently declines to build it from a param handed to it
# that way — the message goes out with only `gold` + `worldType`, and the server answers
# `errorCode E000000` (verified live many times, with every spelling of the entry fields,
# on a clean VM, with and without the hospital window open).
#
# So the message is completed on its way OUT, one step short of the wire. `SendMessage`
# serialises with `msg:ToBinary()`, so the class's `ToBinary` is borrowed for exactly one
# call — long enough to put the `armyArray` the caller wants onto `msg.sfsObj` — and put
# back before the original runs.
#
# THE OLD ROUTE IS GONE, and not because it was wrong (#1702). It used to read
# `GetMsgType` and the transport out of `SFSNetwork.SendMessage`'s upvalues with
# `debug.getupvalue` and call `Network:SendLuaMessage` itself. The client has since shut
# its Lua sandbox: `debug.getupvalue` answers «this API is disabled for security» and
# `string.dump` «lua_dump is disabled», so nothing can be read out of a function any more.
# `SFSNetwork` exposes three names — `GetMsgType`, `HandleMessage`, `SendMessage` — and
# the hook below needs only the first and the last. Nothing else in the repository may
# reach for the closed pair either: what breaks is silent, since the message is simply
# never assembled and the press reports success.
#
# Proven live 2026-08-20 on this route: 692 wounded across two soldier types went to
# treatment in one press, `dead` 692 -> 0 and `heal` 0 -> 692.
_HOSPITAL_TRANSPORT = (
    "local __cure = function(army) "
    "if #army == 0 then error('no wounded soldiers') end "
    "local cls = SFSNetwork.GetMsgType('hospital.cure') "
    "if type(cls) ~= 'table' then error('hospital: message class not found') end "
    "local orig = cls.ToBinary "
    "local injected = false "
    "rawset(cls, 'ToBinary', function(self, ...) "
    "rawset(cls, 'ToBinary', nil) "
    "local arr = SFSArray.New() "
    "for _, e in ipairs(army) do "
    "local o = SFSObject.New() "
    "o:PutUtfString('armyId', tostring(e[1])) "
    "o:PutInt('healNum', math.floor(e[2])) "
    "arr:AddSFSObject(o) end "
    "self.sfsObj:PutSFSArray('armyArray', arr) "
    "injected = true "
    "return orig(self, ...) end) "
    "local ok, err = pcall(function() "
    "SFSNetwork.SendMessage('hospital.cure', { gold = 0 }) end) "
    "rawset(cls, 'ToBinary', nil) "
    "if not ok then error(tostring(err)) end "
    "if not injected then error('hospital: the send never serialised the message') end "
    "return #army end "
)


def hospital_cure(entries) -> str:
    """Heal the given soldier types in one `hospital.cure`.

    `entries` is an iterable of `(armyId, count)` pairs — the faithful, parameterised
    reproduction of the in-game press, for when the caller already knows which types to
    heal and how many of each. `gold` goes out as 0: the free heal.
    """
    entries = list(entries)
    army = "{" + ",".join('{"%s",%d}' % (str(a), int(c)) for a, c in entries) + "}"
    return ('local ok,err = pcall(function() %s __cure(%s) end) '
            'CS.UnityEngine.Debug.LogError("ACT hospital_cure entries=%d ok="..tostring(ok)'
            '..(ok and "" or (" err="..tostring(err))))'
            % (_HOSPITAL_TRANSPORT, army, len(entries)))


def hospital_wounded_count() -> str:
    """Lua *expression* -> how many soldier types currently have wounded to heal.

    Counts `DataCenter.HospitalManager.allHospital` rows with a positive `dead` — the
    same rows the hospital window lists. Returns 0 when the manager is not loaded yet,
    so the gate reads as a safe "nothing to heal" rather than an error.
    """
    return ("(function() "
            "local m = DataCenter and DataCenter.HospitalManager "
            "if not m or type(m.allHospital) ~= 'table' then return 0 end "
            "local n = 0 "
            "for _, h in pairs(m.allHospital) do "
            "if type(h)=='table' and type(h.dead)=='number' and h.dead > 0 then n = n + 1 end end "
            "return n end)()")


def hospital_wounded_total() -> str:
    """Lua *expression* -> how many wounded soldiers are lying in the hospital.

    The SUM of `dead` across the rows `hospital_wounded_count()` merely counts, which
    is the number a person reads ("681 раненых") rather than the three or four soldier
    types they are spread over. A gate wants the count — one press heals every type at
    once — so this one is for display only.
    """
    return ("(function() "
            "local m = DataCenter and DataCenter.HospitalManager "
            "if not m or type(m.allHospital) ~= 'table' then return 0 end "
            "local n = 0 "
            "for _, h in pairs(m.allHospital) do "
            "if type(h)=='table' and type(h.dead)=='number' and h.dead > 0 then n = n + h.dead end end "
            "return n end)()")


def hospital_heal_all() -> str:
    """Heal EVERY wounded soldier type in one `hospital.cure`.

    Builds the armyArray from `DataCenter.HospitalManager.allHospital` — one entry per
    type with `dead > 0`, healing the whole batch of each. That is more than the window
    pre-fills (it suggests only as many as fit the player's chosen cure time), and it is
    what "heal them all" means. Sends nothing (a logged no-op) when nothing is wounded.

    """
    return (
        "local ok,err = pcall(function() "
        + _HOSPITAL_TRANSPORT +
        "local m = DataCenter and DataCenter.HospitalManager "
        "if not m or type(m.allHospital) ~= 'table' then error('HospitalManager not loaded') end "
        # A ROW IS NOT A LUA TABLE (#1702). `allHospital` is keyed by army id and its
        # values are the client's own objects: `type(h)` answers `userdata`, `h.dead`
        # needs `tonumber`, and the old test — `type(h)=='table' and
        # type(h.dead)=='number'` — quietly matched nothing at all. The press then
        # sent an EMPTY army, the transport raised «no wounded soldiers» into its own
        # pcall, and the run reported a press that had healed no one: live, 698
        # wounded stayed 698 with the log saying the button had been pressed.
        "local army = {} "
        "for key, h in pairs(m.allHospital) do "
        "local id, dead = nil, nil "
        "pcall(function() id = h.armyId end) "
        "if id == nil then id = key end "
        "pcall(function() dead = math.floor(tonumber(h.dead) or 0) end) "
        "if id ~= nil and dead ~= nil and dead > 0 then "
        "army[#army+1] = {tostring(id), dead} end end "
        "__cure(army) "
        'CS.UnityEngine.Debug.LogError("ACT hospital_heal_all types="..#army) '
        "end) "
        'if not ok then CS.UnityEngine.Debug.LogError("ACT hospital_heal_all skip: "..tostring(err)) end'
    )


def hospital_collect() -> str:
    """Collect the healed soldiers — the game's own "receive" press, headless.

    The window's receive button is `HospitalManager:CheckSendFinish(buildUuid)`, which
    does all of the gating itself: it only sends `queue.finish` when the hospital queue
    has actually reached the Finish state, and it refuses (with the game's own tip) when
    the soldiers would overflow the barracks. So this is safe to press at any time — a
    heal still running costs one no-op call.
    """
    return (
        "local ok,err = pcall(function() "
        "local m = DataCenter and DataCenter.HospitalManager "
        "if not m or not m.CheckSendFinish then error('HospitalManager not loaded') end "
        "m:CheckSendFinish(m:GetCurHospitalBuildUuid()) "
        'CS.UnityEngine.Debug.LogError("ACT hospital_collect pressed") '
        "end) "
        'if not ok then CS.UnityEngine.Debug.LogError("ACT hospital_collect skip: "..tostring(err)) end'
    )


def hospital_healed_ready() -> str:
    """Lua *expression* -> 1 when a finished heal is waiting to be collected, else 0.

    The hospital queue (`NewQueueType.Hospital`) reaches `NewQueueState.Finish` (3) when
    its timer runs out; until then collecting is a no-op, so this is what gates the
    `collect_healed` press.
    """
    return ("(function() "
            "local q = DataCenter and DataCenter.QueueDataManager "
            "if not q or not NewQueueType or not NewQueueState then return 0 end "
            "local ok, queue = pcall(function() return q:GetQueueByType(NewQueueType.Hospital) end) "
            "if not ok or type(queue) ~= 'table' then return 0 end "
            "if queue.state == NewQueueState.Finish then return 1 end "
            "return 0 end)()")


def hospital_wounded_probe() -> str:
    """Dump the hospital's own wounded list — one line per soldier type.

    Prints `DataCenter.HospitalManager.allHospital` (armyId, dead, heal) plus the
    hospital queue's state and how many building queues are free, which together are
    everything the heal and the collect press depend on. Handy to confirm before/after a
    heal that the counts actually moved, and to tell a rejected heal from a busy base.
    """
    return (
        "local L=function(s) CS.UnityEngine.Debug.LogError('HOSP '..tostring(s)) end "
        "pcall(function() "
        "local m = DataCenter and DataCenter.HospitalManager "
        "if not m or type(m.allHospital) ~= 'table' then L('HospitalManager not loaded') return end "
        "local rows = {} "
        "for id, h in pairs(m.allHospital) do "
        "rows[#rows+1] = tostring(id)..': dead='..tostring(h.dead)..' heal='..tostring(h.heal) end "
        "table.sort(rows) "
        "for _, r in ipairs(rows) do L(r) end "
        "local q = DataCenter.QueueDataManager:GetQueueByType(NewQueueType.Hospital) "
        "L('queue state='..tostring(q and q.state)..' endTime='..tostring(q and q.endTime)"
        "..' helpNum='..tostring(q and q.helpNum)) "
        "L('free build queues='..tostring(%s)) "
        "end)" % free_build_queues()
    )


def hospital_heal_portion() -> str:
    """Send at most `DataCenter.__lw_heal_portion` wounded soldiers for treatment.

    The whole of what :func:`hospital_heal_all` does, with a CEILING on it — the number a
    person typed («лечить по столько за раз»). Zero, the default, means «every one of
    them» and the two are then the same press.

    WHY A CEILING IS WORTH HAVING. A heal is one queue and one timer: sending every
    wounded soldier in the base starts a treatment that can run for hours, and nothing
    else can be healed until it ends. A portion sends as much as the player wants to wait
    for, and the watch (:func:`hospital_watch_install`) sends the next one the moment the
    queue frees, so the same wounded are cleared in slices instead of one long block.

    THE ORDER IS THE HIGHEST SOLDIER FIRST. `allHospital` is keyed by the soldier
    template id and a bigger id is a better soldier, so a portion spends itself on what
    the player would pick first. What the ceiling cannot split it does not split: a type
    is filled up to whatever is left of the portion and the next type gets the remainder.

    Leaves `DataCenter.__lw_heal` for :func:`hospital_heal_report` — what was asked for,
    what was sent, over how many types, and the error when the send raised.
    """
    return (
        "local want = math.floor(tonumber(DataCenter.__lw_heal_portion) or 0) "
        "local ok,err = pcall(function() "
        + _HOSPITAL_TRANSPORT +
        "local m = DataCenter and DataCenter.HospitalManager "
        "if not m or type(m.allHospital) ~= 'table' then error('HospitalManager not loaded') end "
        # A ROW IS NOT A LUA TABLE — the same `userdata` trap `hospital_heal_all`
        # documents: read every field through `pcall` + `tonumber`, never `type(h)`.
        "local rows = {} "
        "for key, h in pairs(m.allHospital) do "
        "local id, dead = nil, nil "
        "pcall(function() id = h.armyId end) "
        "if id == nil then id = key end "
        "pcall(function() dead = math.floor(tonumber(h.dead) or 0) end) "
        "if id ~= nil and dead ~= nil and dead > 0 then "
        "rows[#rows+1] = {tostring(id), dead, math.floor(tonumber(id) or 0)} end end "
        "table.sort(rows, function(a, b) return a[3] > b[3] end) "
        "local army, sent = {}, 0 "
        "for _, r in ipairs(rows) do "
        "local take = r[2] "
        "if want > 0 then take = math.min(take, want - sent) end "
        "if take > 0 then army[#army+1] = {r[1], take} sent = sent + take end end "
        "DataCenter.__lw_heal = {want = want, sent = sent, types = #army, err = ''} "
        "__cure(army) "
        'CS.UnityEngine.Debug.LogError("ACT hospital_heal_portion want="..tostring(want)'
        '.." sent="..tostring(sent).." types="..tostring(#army)) '
        "end) "
        "if not ok then "
        "DataCenter.__lw_heal = DataCenter.__lw_heal or {} "
        "DataCenter.__lw_heal.err = tostring(err) "
        "DataCenter.__lw_heal.sent = 0 "
        'CS.UnityEngine.Debug.LogError("ACT hospital_heal_portion skip: "..tostring(err)) end'
    )


#: THE HOSPITAL WINDOW'S OWN CONTROLLER, which is where the price of a heal is worked out
#: (#2085). `HospitalManager` has no cost method at all — the window computes what it
#: shows — and the person's answer to «how much does it cost» was that the game already
#: says so: «При лечении указывается нужное количество ресурсов».
#:
#: It is `UI.LWUIHospital.Controller.LWUIHospitalCtrl:GetHealCostResourceCount(count)`,
#: and the useful discovery is that **it needs no window**: measured live on 2026-09-01
#: with the module not loaded at all, `require` + `New` + the call answered the same
#: numbers as the open window did (`loaded=false require=true new=true cost1000=625`).
#: So the price is a headless reading like every other one here, and nothing flashes on
#: the player's screen to get it.
#:
#: The instance is kept on the VM rather than built per call: it is the window's
#: controller and building one is not free, and the price does not depend on it.
_HEAL_COST_CTRL = (
    "(function() "
    "local D = DataCenter "
    "local inst = D.__lw_heal_ctrl "
    "if inst == nil then "
    "local path = 'UI.LWUIHospital.Controller.LWUIHospitalCtrl' "
    "local C = package.loaded[path] "
    "if C == nil then pcall(function() C = require(path) end) end "
    "if type(C) ~= 'table' then return nil end "
    "pcall(function() inst = C.New(C) end) "
    "if inst == nil then pcall(function() inst = C:New() end) end "
    "D.__lw_heal_ctrl = inst end "
    "return inst end)()"
)


def hospital_heal_cost(count_expr: str) -> str:
    """Lua *expression* -> what the hospital window's controller answers for `count_expr`.

    **This is NOT the bill, and a first version of this file said it was.** Measured live
    on 2026-09-02 it answers `ceil(0.625 * n)` — the same rate with 1 724 wounded, with
    120 and with none, and the same rate on a second account — so it cannot be the price
    of healing soldiers whose own config price differs by tier. What the heal really costs
    is :func:`hospital_heal_bill`; this number is kept, and printed beside that one, so
    that a person with the hospital window open can settle in one sentence which of the
    two the screen shows (docs/research/hospital-heal.md §9a).
    """
    return ("(function() local inst = %s "
            "if inst == nil then return -1 end "
            "local n = math.floor(tonumber(%s) or 0) "
            "if n <= 0 then return 0 end "
            "local r = nil "
            "local ok = pcall(function() r = inst:GetHealCostResourceCount(n) end) "
            "if not ok or r == nil then return -1 end "
            "return math.floor(tonumber(r) or -1) end)()"
            % (_HEAL_COST_CTRL, count_expr))


def hospital_heal_report() -> str:
    """Lua *expression* -> one line about the last portion heal, for the log."""
    return (
        "(function() local h = DataCenter.__lw_heal or {} "
        "return 'asked=' .. tostring(math.floor(tonumber(h.want) or 0)) .. "
        "' sent=' .. tostring(math.floor(tonumber(h.sent) or 0)) .. "
        "' types=' .. tostring(math.floor(tonumber(h.types) or 0)) .. "
        "((h.err ~= nil and h.err ~= '') and (' refused=' .. tostring(h.err)) or '') end)()"
    )


#: WHAT A HEAL COSTS, AND WHICH OF THE GAME'S OWN NUMBERS SAYS SO (#2085).
#:
#: WHICH resources is the game's answer, per soldier type and beyond doubt:
#: `lw_soldier.rescue_consume` is an explicit `id;amount|id;amount` list — `1;577|14;577`
#: for the tier-9 soldier, `1;702.7|14;702.7` for the tier-10 — whose ids are rows of
#: `aps_resources`, and `CommonUtil.GetResourceNameByType(id)` names them in the player's
#: own language («Металл», «Еда»). That is the same pair the hospital window draws
#: (`oreNeedResourceCell` / `cerealNeedResourceCell`). Balances come from
#: `CommonUtil.GetOwnCountByCommonCostType(1, id)`, verified against the base's own
#: numbers, where the `1` is «a base resource» as against `2`, «a resource ITEM».
#:
#: HOW MUCH is that list times the soldiers going, and the two other candidates were
#: measured and REJECTED rather than assumed (2026-09-02, live):
#:
#: * `LWUIHospitalCtrl:GetHealCostResourceCount(n)` answers `ceil(0.625 * n)` — the same
#:   rate with 1 724 wounded, with 120 and with none at all, and the same rate on a
#:   second account. A bill that does not move when the wounded change from tier 9 to
#:   tier 10 is not this bill. It is printed beside ours in the log all the same, so a
#:   person who has the window open can say in one sentence which of the two it shows.
#: * `HospitalManager:GetSoldierCureValueLocal()` is a CONSTANT (55 059.81 here) — the
#:   same number with 120 wounded and with zero. An earlier revision of this file took it
#:   for «the game's own bill, discounts included» and prorated by it; that was wrong and
#:   is retracted.
#:
#: So what is not yet settled is whether the player's own research DISCOUNTS the config
#: price. If it does, this reads a little high — and the direction matters, because a
#: shortfall read high opens a pack that was not needed. That is why nothing opens unless
#: the run was told to, and why the question is being put to the person rather than
#: guessed at (docs/research/hospital-heal.md §9).
#:
#: **A bill that could not be read is -1, never 0**, and the bag is not opened on one:
#: «I could not look» and «it is free» are different answers, and only the first of them
#: is safe to act on.
def hospital_heal_bill() -> str:
    """Park `DataCenter.__lw_heal_bill` — what the portion will cost, and what is short.

    One entry per resource the wounded actually charge: `{id, name, need, own, lack}`.
    `need` and `lack` are -1 when the game could not be asked, which is what stops
    :func:`hospital_open_res_packs` from opening anything.
    """
    return (
        "local want = math.floor(tonumber(DataCenter.__lw_heal_portion) or 0) "
        "local B = {res = {}, sent = 0, all = 0, val = -1, why = ''} "
        "local ok, err = pcall(function() "
        "local m = DataCenter and DataCenter.HospitalManager "
        "if not m or type(m.allHospital) ~= 'table' then error('HospitalManager not loaded') end "
        # A ROW IS NOT A LUA TABLE — every field through `pcall`, the same trap the heal
        # itself documents.
        "local rows = {} "
        "for key, h in pairs(m.allHospital) do "
        "local id, dead = nil, nil "
        "pcall(function() id = h.armyId end) "
        "if id == nil then id = key end "
        "pcall(function() dead = math.floor(tonumber(h.dead) or 0) end) "
        "if id ~= nil and dead ~= nil and dead > 0 then "
        "rows[#rows+1] = {math.floor(tonumber(id) or 0), dead} end end "
        # The portion spends itself exactly as the heal does — highest soldier first —
        # so the bill is for the soldiers that are actually going.
        "table.sort(rows, function(a, b) return a[1] > b[1] end) "
        "local sent, all, take_of = 0, 0, {} "
        "for _, r in ipairs(rows) do all = all + r[2] "
        "local take = r[2] "
        "if want > 0 then take = math.min(take, want - sent) end "
        "if take < 0 then take = 0 end "
        "take_of[#take_of+1] = {r[1], take, r[2]} sent = sent + take end "
        "B.sent, B.all = sent, all "
        "local I = LocalController.instance() "
        "local raw_p, raw_a = {}, {} "
        "for _, t in ipairs(take_of) do local s = nil "
        "pcall(function() s = tostring(I:getValue('lw_soldier', t[1], 'rescue_consume', nil)) end) "
        "if s ~= nil and s ~= '' and s ~= 'nil' then "
        "for pair in string.gmatch(s, '[^|]+') do "
        "local rid, amt = string.match(pair, '(%d+);([%d%.]+)') "
        "if rid ~= nil then rid = math.floor(tonumber(rid) or 0) amt = tonumber(amt) or 0 "
        "raw_p[rid] = (raw_p[rid] or 0) + amt * t[2] "
        "raw_a[rid] = (raw_a[rid] or 0) + amt * t[3] end end end end "
        # The game's own bill for everything lying in the hospital, discounts included.
        "local fn = -1 "
        "pcall(function() fn = math.ceil(tonumber(" + _HEAL_COST_CTRL + ":GetHealCostResourceCount(sent)) or -1) end) "
        "B.fn = fn "
        "for rid, rawp in pairs(raw_p) do "
        "local need = -1 "
        "if rawp > 0 then need = math.ceil(rawp) end "
        "local own = -1 "
        "pcall(function() own = math.floor(tonumber("
        "CommonUtil.GetOwnCountByCommonCostType(1, rid)) or -1) end) "
        "local nm = '' pcall(function() nm = tostring(CommonUtil.GetResourceNameByType(rid)) end) "
        "local lack = -1 "
        "if need >= 0 and own >= 0 then lack = math.max(0, need - own) end "
        "B.res[#B.res+1] = {id = rid, need = need, own = own, lack = lack, name = nm} end "
        "end) "
        "if not ok then B.why = tostring(err) end "
        "DataCenter.__lw_heal_bill = B "
        'CS.UnityEngine.Debug.LogError("ACT hospital_heal_bill sent="..tostring(B.sent)'
        '.." why="..tostring(B.why))'
    )


def hospital_bill_report() -> str:
    """Lua *expression* -> the bill in one line for the log, resource by resource."""
    return (
        "(function() local B = DataCenter.__lw_heal_bill or {} "
        "if B.why ~= nil and B.why ~= '' then return 'unknown ' .. tostring(B.why) end "
        "local out = {} "
        "for _, r in ipairs(B.res or {}) do "
        "out[#out+1] = tostring(r.name or r.id) .. ' need=' .. tostring(r.need) .. "
        "' own=' .. tostring(r.own) .. ' short=' .. tostring(r.lack) end "
        "if #out == 0 then return 'nothing to pay for' end "
        "return 'soldiers=' .. tostring(math.floor(tonumber(B.sent) or 0)) .. ' of ' .. "
        "tostring(math.floor(tonumber(B.all) or 0)) .. ' :: ' .. table.concat(out, ' | ') .. "
        "' | the window controller would say ' .. tostring(math.floor(tonumber(B.fn) or -1)) end)()"
    )


#: THE ONLY KIND OF ITEM THIS MAY EVER OPEN — a resource pack, `goods.type == 3`. The
#: plan comes from the game, but the game is answering «what would cover this», not «what
#: may a bot spend», and a plan naming anything else is refused rather than trusted.
_RES_PACK_TYPE = 3


def hospital_open_res_packs() -> str:
    """Open exactly the resource packs the GAME says would cover the heal's shortfall.

    The client works this out for itself — `LWResourceLackUtil:GetResItemsToSupplementDatas(
    resource, lack)` answers with a list of `{itemId, count}`, which is the same list the
    game shows a player when a purchase is short. So nothing here decides which pack gives
    which resource (a question this repository could not answer for a day: `goods.para1`
    resolves in none of the 744 config tables) — the game decides, and this spends the
    plan and nothing beyond it.

    THREE GATES, and each of them refuses rather than guesses:

    * the run has to have been ASKED (`DataCenter.__lw_heal_chests == 1`);
    * the bill has to have been READ (a `lack` of -1 is «I could not look», not «short»);
    * every item in the plan has to be a resource pack (:data:`_RES_PACK_TYPE`).

    Leaves `DataCenter.__lw_heal_packs` — one row per pack, with how many were asked for
    and how many actually left the bag, so the log says what was spent rather than that
    a press happened.
    """
    return (
        "local P = {rows = {}, why = ''} "
        "local ok, err = pcall(function() "
        "if math.floor(tonumber(DataCenter.__lw_heal_chests) or 0) ~= 1 then error('not asked') end "
        "local B = DataCenter.__lw_heal_bill "
        "if type(B) ~= 'table' or type(B.res) ~= 'table' then error('no bill') end "
        "if B.why ~= nil and B.why ~= '' then error('bill: ' .. tostring(B.why)) end "
        "local L, D, T = LWResourceLackUtil, DataCenter.ItemData, DataCenter.ItemTemplateManager "
        "if L == nil then error('no lack util') end "
        "if D == nil then error('no bag') end "
        "for _, r in ipairs(B.res) do local lack = math.floor(tonumber(r.lack) or -1) "
        "if lack > 0 then local plan = nil "
        "pcall(function() plan = L:GetResItemsToSupplementDatas(r.id, lack) end) "
        "if type(plan) ~= 'table' or #plan == 0 then "
        "P.rows[#P.rows+1] = {name = r.name, lack = lack, want = 0, used = 0, why = 'no-packs'} "
        "else for _, e in ipairs(plan) do "
        "local id = math.floor(tonumber(e.itemId) or 0) "
        "local n = math.floor(tonumber(e.count) or 0) "
        "local kind = -1 "
        "pcall(function() kind = math.floor(tonumber(T:GetItemTemplate(id).type) or -1) end) "
        "if id > 0 and n > 0 and kind == %(pack)d then "
        "local stacks, used = {}, 0 "
        "pcall(function() for _, v in pairs(D.ItemInfos or {}) do "
        "if math.floor(tonumber(v.itemId) or 0) == id then "
        "stacks[#stacks+1] = {uuid = v.uuid, n = math.floor(tonumber(v.count) or 0)} end end end) "
        "for _, st in ipairs(stacks) do local left = n - used "
        "if left > 0 and st.n > 0 then local k = math.min(left, st.n) "
        "local go = pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.ItemUse, {uuid = st.uuid, num = k}) end) "
        "if go then used = used + k end end end "
        "P.rows[#P.rows+1] = {name = r.name, lack = lack, item = id, want = n, used = used, "
        "why = (used < n) and 'ran-out' or ''} "
        "else P.rows[#P.rows+1] = {name = r.name, lack = lack, item = id, want = n, used = 0, "
        "why = 'not-a-pack'} end end end end end "
        "end) "
        "if not ok then P.why = tostring(err) end "
        "DataCenter.__lw_heal_packs = P "
        'CS.UnityEngine.Debug.LogError("ACT hospital_open_res_packs rows="..tostring(#P.rows)'
        '.." why="..tostring(P.why))'
        % {"pack": _RES_PACK_TYPE}
    )


def hospital_packs_report() -> str:
    """Lua *expression* -> what was opened out of the bag, for the log."""
    return (
        "(function() local P = DataCenter.__lw_heal_packs or {} "
        "if P.why ~= nil and P.why ~= '' then return 'opened nothing: ' .. tostring(P.why) end "
        "local out = {} "
        "for _, r in ipairs(P.rows or {}) do "
        "out[#out+1] = tostring(r.name or '?') .. ' short=' .. tostring(r.lack) .. "
        "' item=' .. tostring(r.item or '-') .. ' asked=' .. tostring(r.want) .. "
        "' opened=' .. tostring(r.used) .. "
        "((r.why ~= nil and r.why ~= '') and (' ' .. tostring(r.why)) or '') end "
        "if #out == 0 then return 'nothing was short' end "
        "return table.concat(out, ' | ') end)()"
    )



#: How long after a hook fires the watch actually looks, in seconds. Never zero: every
#: door below is wrapped around a method the CLIENT is in the middle of — `OnQueueEnd`
#: runs while the queue is being retired, `HospitalCureHandle` while the reply is being
#: applied — and sending a message from inside one of those is asking the client to
#: re-enter its own handler. A fifth of a second later it is out of them and the state
#: the watch reads is the settled one.
HEAL_WATCH_SETTLE_SEC = 0.25

#: The belt to the hooks' brace: how long after the heal's own `endTime` the alarm goes
#: off. The queue reaches `Finish` on the client's own clock, and a second of slack costs
#: nothing and saves a collect that would otherwise wait for the next hook.
HEAL_WATCH_ALARM_SLACK_SEC = 1.0

#: How long the watch goes on re-arming its alarm with nothing to do before it stops.
#: A timer in somebody else's game has to end (the same rule the treasure reaper keeps):
#: the recipe arms it again on its next run, so an idled-out watch costs one heal's delay
#: and never a wedged client.
HEAL_WATCH_IDLE_STOP_SEC = 3600


#: THE WATCH — «собираем, как завершается, по хуку» (#2085).
#:
#: WHY IT IS NOT A POLL. A heal ends on a timer the client is already keeping, and the
#: client says so itself: `HospitalManager:OnQueueEnd` is the call it makes when the
#: hospital queue retires, `HospitalCureHandle` the one it makes when the server answers
#: a cure, and `UpdateHospitalDeadInfo` the one it makes when soldiers are hurt. Three
#: doors, each wrapped once, each merely scheduling the same `step` a quarter of a second
#: later — so the collect leaves in the moment the game itself learnt the heal was over,
#: and NOTHING is asked of the server in between (`CLAUDE.md`, «Read once, then LISTEN»).
#:
#: The alarm is the belt to that brace: the queue's `endTime` is a stamp the server gave
#: us, so the exact millisecond the heal finishes is known in advance and one `DelayInvoke`
#: is pinned to it. It is not a period and it is not a poll — it is one wake-up at a time
#: that is already known, and it is re-pinned only when a heal is running.
#:
#: WHAT ONE STEP DOES, in the order of the in-game routine:
#:   1. a finished heal is collected (`CheckSendFinish` — its own gate);
#:   2. an idle hospital with wounded in it is sent the next portion;
#:   3. a working queue with no request standing is put in front of the alliance.
#: Exactly the three presses `actions/heal_units.md` plays, run by the game rather than
#: by the panel — so a panel that is busy elsewhere, or shut, loses nothing.
_HEAL_WATCH = '''
local D = DataCenter
D.__lw_heal_watch = D.__lw_heal_watch or {ticks = 0, collected = 0, healed = 0,
                                          helped = 0, run = 0, why = "", last = ""}
local W = D.__lw_heal_watch
W.run = (tonumber(W.run) or 0) + 1
W.on = true
W.at = 0
local token = W.run
local tm = TimerManager:GetInstance()

local function now_ms()
  local t = 0
  pcall(function() t = math.floor(tonumber(UITimeManager.Instance:GetServerTime()) or 0) end)
  if t <= 0 then pcall(function()
    t = math.floor((tonumber(ChatInterface.getServerTime()) or 0) * 1000) end) end
  return t
end

W.step = function(why)
  local A = DataCenter.__lw_heal_watch
  if A == nil or not A.on or A.run ~= token then return end
  A.pending = false
  local m = DataCenter and DataCenter.HospitalManager
  local q = DataCenter and DataCenter.QueueDataManager
  if m == nil or q == nil then A.last = "no-manager" return end
  A.ticks = (tonumber(A.ticks) or 0) + 1
  A.why = tostring(why or "?")
  A.at = now_ms()
  local queue = nil
  pcall(function() queue = q:GetQueueByType(NewQueueType.Hospital) end)
  local state, ends, helped, uuid, qtype = -1, 0, 1, nil, 3
  if queue ~= nil then
    pcall(function() state = math.floor(tonumber(queue.state) or -1) end)
    pcall(function() ends = math.floor(tonumber(queue.endTime) or 0) end)
    pcall(function() helped = math.floor(tonumber(queue.isHelped) or 1) end)
    pcall(function() uuid = queue.uuid end)
    pcall(function() qtype = math.floor(tonumber(queue.type) or 3) end)
  end
  A.state, A.ends = state, ends

  -- 1. THE COLLECT. `CheckSendFinish` is the window's own receive button and holds its
  -- own gates (the queue really finished, the barracks have room), so this is a no-op
  -- at any other moment.
  if state == NewQueueState.Finish then
    local ok = pcall(function() m:CheckSendFinish(m:GetCurHospitalBuildUuid()) end)
    A.collected = (tonumber(A.collected) or 0) + (ok and 1 or 0)
    A.last = ok and "collected" or "collect-refused"
    A.busy_at = A.at
    -- The server's answer frees the queue and comes back through the cure/queue doors,
    -- which wake this again: nothing else is done in the same breath, because the
    -- hospital will not take a heal until the collect has landed (errorCode 130069).
    return
  end

  -- 2. THE NEXT PORTION, when the hospital is standing idle with wounded in it.
  if state ~= NewQueueState.Work and state ~= NewQueueState.Finish then
    local wounded = 0
    pcall(function()
      for _, h in pairs(m.allHospital or {}) do
        local d = 0
        pcall(function() d = math.floor(tonumber(h.dead) or 0) end)
        wounded = wounded + d
      end end)
    A.wounded = wounded
    if wounded > 0 then
      pcall(function() DataCenter.__lw_heal = nil end)
      pcall(function() %(heal)s end)
      -- The chunk swallows its own failure and writes it down, so what was SENT is the
      -- only honest answer: a refusal leaves `sent` at zero and `err` in the report.
      local sent, why = 0, ""
      pcall(function()
        local h = DataCenter.__lw_heal or {}
        sent = math.floor(tonumber(h.sent) or 0)
        why = tostring(h.err or "")
      end)
      A.healed = (tonumber(A.healed) or 0) + sent
      A.last = (sent > 0) and ("healed " .. tostring(sent))
               or ("heal-refused " .. (why ~= "" and why or "?"))
      A.busy_at = A.at
      -- The reply comes back through `HospitalCureHandle`, which wakes this again to
      -- ask for help over a queue that is by then working.
      return
    end
  end

  -- 3. THE ALLIANCE. Only while the queue is actually working and only when no request
  -- is standing — `isHelped` is the game's own book on that, so a repeat costs nothing.
  local ask = (math.floor(tonumber(DataCenter.__lw_heal_help) or 1) == 1)
  if state == NewQueueState.Work and helped ~= 1 and uuid ~= nil and ask then
    local ok = pcall(function()
      SFSNetwork.SendMessage(MsgDefines.AllianceCallHelp, uuid, 1, qtype, '1') end)
    A.helped = (tonumber(A.helped) or 0) + (ok and 1 or 0)
    if ok then A.last = "asked-for-help" A.busy_at = A.at end
  end
  if state == NewQueueState.Work then A.busy_at = A.at end
end

-- THE ALARM. One wake-up, at a moment the SERVER named — never a period.
local function alarm()
  local A = DataCenter.__lw_heal_watch
  if A == nil or not A.on or A.run ~= token then return end
  pcall(A.step, "alarm")
  local ends = math.floor(tonumber(A.ends) or 0)
  local at = math.floor(tonumber(A.at) or 0)
  local left = (ends > 0 and at > 0) and ((ends - at) / 1000) or -1
  if left > 0 then
    tm:DelayInvoke(alarm, left + %(slack)s)
    return
  end
  -- Nothing is running. Wake once more in a while so that a heal started by the PLAYER
  -- in the game is still collected, and stop for good when even that finds nothing:
  -- the recipe arms this again on its next run.
  if at > 0 and (tonumber(A.busy_at) or 0) > 0
     and (at - (tonumber(A.busy_at) or at)) / 1000 > %(idle)s then
    A.on = false
    CS.UnityEngine.Debug.LogError("ACT heal_watch idle-stop ticks=" .. tostring(A.ticks or 0))
    return
  end
  tm:DelayInvoke(alarm, %(recheck)s)
end

-- THE DOORS. Wrapped on the manager INSTANCE (`rawset`), so the class is left alone and
-- a second arm finds the wrapper already there — `W.hooked` is what makes this
-- idempotent, exactly as the treasure watch's pair of wrappers is.
local function wake(why)
  local A = DataCenter.__lw_heal_watch
  if A == nil or not A.on or A.pending then return end
  A.pending = true
  tm:DelayInvoke(function() pcall(A.step, why) end, %(settle)s)
end

if not W.hooked then
  local m = DataCenter and DataCenter.HospitalManager
  if m ~= nil then
    W.hooked = true
    for _, name in ipairs({"OnQueueEnd", "HospitalCureHandle", "UpdateHospitalDeadInfo"}) do
      local orig = m[name]
      if type(orig) == "function" then
        rawset(m, name, function(self, ...)
          local r = orig(self, ...)
          pcall(wake, name)
          return r
        end)
      end
    end
  end
end

tm:DelayInvoke(alarm, %(settle)s)
CS.UnityEngine.Debug.LogError("ACT heal_watch on=1 run=" .. tostring(token)
  .. " hooked=" .. tostring(W.hooked and 1 or 0))
'''


def hospital_watch_install() -> str:
    """Arm the game-side watch: collect, heal the next portion, ask for help — by hook.

    Idempotent. The three doors are wrapped once however often this is played, and a
    fresh arm bumps a run token so an alarm left over from a previous one disowns itself
    on its next wake (the same way the treasure reaper is stopped).

    Reads its two knobs off the VM, where the recipe parks them:
    `DataCenter.__lw_heal_portion` (how many soldiers a heal may send, 0 = all) and
    `DataCenter.__lw_heal_help` (whether the alliance is asked at all).
    """
    return (_HEAL_WATCH % {
        "heal": hospital_heal_portion(),
        "settle": repr(float(HEAL_WATCH_SETTLE_SEC)),
        "slack": repr(float(HEAL_WATCH_ALARM_SLACK_SEC)),
        "idle": repr(float(HEAL_WATCH_IDLE_STOP_SEC)),
        "recheck": repr(float(HEAL_WATCH_IDLE_STOP_SEC / 6.0)),
    })


def hospital_watch_stop() -> str:
    """Stop the game-side watch. The wrappers stay; the switch and the token are what move.

    A `DelayInvoke` already scheduled cannot be cancelled, so it is disowned rather than
    cancelled — it wakes, sees a token that is not its own, and returns. The doors are
    left wrapped on purpose: unwrapping a method that something else may have wrapped
    since is how a hook is lost, and a wrapper over a watch that is off costs one `pcall`
    that returns immediately.
    """
    return (
        "local W = DataCenter.__lw_heal_watch "
        "if W ~= nil then W.on = false W.run = (tonumber(W.run) or 0) + 1 end "
        'CS.UnityEngine.Debug.LogError("ACT heal_watch on=0 ticks="'
        "..tostring((W or {}).ticks or 0))"
    )


def hospital_watch_state() -> str:
    """Lua *expression* -> what the watch has been doing, in one line for the log."""
    return (
        "(function() local W = DataCenter.__lw_heal_watch "
        "if W == nil then return 'on=0 hooked=0 ticks=0 collected=0 healed=0 helped=0' end "
        "return 'on=' .. tostring(W.on and 1 or 0) .. "
        "' hooked=' .. tostring(W.hooked and 1 or 0) .. "
        "' ticks=' .. tostring(math.floor(tonumber(W.ticks) or 0)) .. "
        "' collected=' .. tostring(math.floor(tonumber(W.collected) or 0)) .. "
        "' healed=' .. tostring(math.floor(tonumber(W.healed) or 0)) .. "
        "' helped=' .. tostring(math.floor(tonumber(W.helped) or 0)) .. "
        "' state=' .. tostring(math.floor(tonumber(W.state) or -1)) .. "
        "' wounded=' .. tostring(math.floor(tonumber(W.wounded) or 0)) .. "
        "' woke=' .. tostring(W.why or '-') .. "
        "' last=' .. tostring(W.last or '-') end)()"
    )


# --------------------------------------------------------------------------
# Ask the alliance to speed a queue up ("Запрос помощи")
# --------------------------------------------------------------------------
# A press of its own, positional arguments — NOT a param table
# (recording 20260729_182527, docs/research/hospital-heal.md §4):
#
#     SFSNetwork.SendMessage(MsgDefines.AllianceCallHelp, uuid, 1, qType, "1")
#       -> PutLong(uuid, <queue uuid>)  PutInt(type, 1)
#          PutInt(qType, <queue type>)  PutUtfString(itemId, "1")
#
# `itemId` MUST be a string: passing the number 1 dies in the serialiser with
# "attempt to get length of a number value" before the message leaves the client. The
# trace cannot tell the two apart — it prints both as `1`.
#
# `qType` is the queue's own `type` (3 = Hospital), so the same message asks for help on
# any queue. `isHelped` on the queue is the state: 0 = no request standing, 1 = asked.
# Gating on it keeps a repeat run from re-asking, and it is what flips after a successful
# send (proven live: hospital queue isHelped 0 -> 1, allies answered within seconds).
def alliance_call_help_all() -> str:
    """Ask the alliance to speed up every working queue that has no request standing."""
    return (
        "local ok,err = pcall(function() "
        "local q = DataCenter and DataCenter.QueueDataManager "
        "if not q or type(q.queueDic) ~= 'table' or not NewQueueState then "
        "error('QueueDataManager not loaded') end "
        "local n = 0 "
        "for _, v in pairs(q.queueDic) do "
        "if type(v)=='table' and v.state == NewQueueState.Work and v.isHelped ~= 1 then "
        "SFSNetwork.SendMessage(MsgDefines.AllianceCallHelp, v.uuid, 1, v.type, '1') "
        "n = n + 1 end end "
        'CS.UnityEngine.Debug.LogError("ACT alliance_call_help_all asked="..n) '
        "end) "
        'if not ok then CS.UnityEngine.Debug.LogError("ACT alliance_call_help_all skip: "..tostring(err)) end'
    )


def queues_needing_help() -> str:
    """Lua *expression* -> how many working queues have no help request standing."""
    return ("(function() "
            "local q = DataCenter and DataCenter.QueueDataManager "
            "if not q or type(q.queueDic) ~= 'table' or not NewQueueState then return 0 end "
            "local n = 0 "
            "for _, v in pairs(q.queueDic) do "
            "if type(v)=='table' and v.state == NewQueueState.Work and v.isHelped ~= 1 then "
            "n = n + 1 end end "
            "return n end)()")


def free_build_queues() -> str:
    """Lua *expression* -> how many building queues (`NewQueueType.Default`) are idle.

    Diagnostic only. A heal does NOT need one: a recorded human press went through with
    all four Default queues working, which retired the earlier «Очередь на строительство
    заполнена» theory (docs/research/hospital-heal.md §5).
    """
    return ("(function() "
            "local q = DataCenter and DataCenter.QueueDataManager "
            "if not q or type(q.queueDic) ~= 'table' or not NewQueueType or not NewQueueState then return 0 end "
            "local n = 0 "
            "for _, v in pairs(q.queueDic) do "
            "if type(v)=='table' and v.type == NewQueueType.Default and v.state == NewQueueState.Free then "
            "n = n + 1 end end "
            "return n end)()")


# --------------------------------------------------------------------------
# Alliance rally: join the live ones, one squad each
# --------------------------------------------------------------------------
# «Присоединиться к ралли». The engine side is `tools/rally_join.py` and
# `docs/research/rally-join.md`; this is the same thing as a pressable button so a
# recipe (and therefore a timer) can do it.
#
#   * a rally is a world march with `teamUuid ~= 0`; its LEADER is the march whose
#     `uuid == teamUuid - 1`, and that leader carries the join parameters
#     (`teamUuid`, `targetPos`, `serverId`);
#   * joining is `MarchUtil.SendCreateMarchMessage(formationUuid, 6, targetPos,
#     teamUuid, 1, 1, false, server, nil)`, scheduled on the main thread;
#   * WHICH squad goes is the first argument: the formation whose `index` is the
#     slot the player sees (1/2/3), read live off
#     `DataCenter.ArmyFormationDataManager.ArmyFormationList`;
#   * the send silently no-ops while every formation is COLD (`totalSoldierNum`
#     0). `MarchUtil.OnClickStartMarch` warms them but opens the dispatch panel,
#     so it is followed by `GoToUtil.CloseAllWindows()` — the game's own close,
#     not `DestroyAllWindow` (that one kills the HUD). Already warm -> no UI at all.
#
# One press = one squad -> one rally, so a recipe says `TAP join_rally xall` and
# the squads parked in `DataCenter.__lw_rally_squads` are spent one per rally.
# Two things are excluded from the candidates, which is what makes "squads 2 and 3
# join TWO DIFFERENT rallies" true rather than hopeful:
#   * rallies the player already has a march in (`GetOwnerMarches`), and
#   * rallies joined by an earlier press in this same run
#     (`DataCenter.__lw_rally_joined`) — the server's own reply takes seconds to
#     arrive, so waiting for it would let the next press pick the same rally again.

# Shared prelude: `squads` (the parked queue, default 1/2/3), and `rallies` — the
# joinable ones, ordered by team uuid so the pick is stable between two calls.
_RALLY_PRELUDE = (
    "local wm=DataCenter.WorldMarchDataManager "
    "local function g(mo,k) local ok,v=pcall(function() return mo[k] end) "
    "if ok then return v end return nil end "
    # A dictionary enumerator yields KeyValuePairs, a list one yields the item —
    # take .Value when there is one.
    "local function cur(e) local mo=e.Current local ok,v=pcall(function() return mo.Value end) "
    "if ok and v~=nil then return v end return mo end "
    "local taken=DataCenter.__lw_rally_joined or {} "
    "local om=wm:GetOwnerMarches() "
    "if om then local e=om:GetEnumerator() while e:MoveNext() do local mo=cur(e) "
    "local t=g(mo,'teamUuid') if t~=nil and tostring(t)~='0' then taken[tostring(t)]=true end "
    "end end "
    "local rallies={} local col=wm:GetAllMarches() "
    "if col then local e=col:GetEnumerator() while e:MoveNext() do local mo=cur(e) "
    "local team=g(mo,'teamUuid') local ts=tostring(team) "
    "if team~=nil and ts~='0' and ts~='nil' and not taken[ts] then "
    "local lead=false pcall(function() lead=(tostring(g(mo,'uuid'))==tostring(team-1)) end) "
    # TWO PLACES, AND THEY ARE NOT THE SAME PLACE. `point` is where the rally is GOING
    # — the monster — and it is what a listing should show. `joinpoint` is where a
    # JOINER marches: the troops gather at the base of whoever raised the banner and
    # set off from there together, so a join ends at the leader's own tile (`startPos`,
    # `homePos` behind it). Every member march of every rally read live says the same:
    # its `targetPos` is the leader's tile and its `homePos` is the member's own base.
    #
    # Sending the monster made the client fly the camera to the monster and the server
    # refuse the march as «invalid end point» — the destination was real, it just was
    # not a place a joining squad may be sent to. The player spotted it from the camera:
    # joining by hand moves the view to the PLAYER doing the rallying, the bot's press
    # moved it to the monster.
    "if lead then rallies[#rallies+1]={team=team,point=g(mo,'targetPos'),"
    "joinpoint=(g(mo,'startPos') or g(mo,'homePos') or g(mo,'targetPos')),"
    "server=(g(mo,'serverId') or g(mo,'targetServer'))} end "
    "end end end "
    "table.sort(rallies,function(a,b) return tostring(a.team)<tostring(b.team) end) "
    "local squads=DataCenter.__lw_rally_squads or {1,2,3} "
)


# OURS, NOT EVERY BANNER ON THE MAP. `GetAllMarches()` returns every march the client
# can see, and a rally belonging to another alliance cannot be joined at all — the
# server refuses it, which is the «invalid end point» the player was shown and which
# cost this ability weeks of looking in the wrong place (#1237). The marches carry
# `allianceName`; the PLAYER does not, and no alliance manager on the client will hand
# it over — so it is learned from any march of our own on the map (`ownerUid == P.uid`)
# and remembered, because there are minutes when we have none out and the answer must
# not go with them.
#
# Learned and not configured, deliberately: an alliance name typed into a setting is one
# more thing to be wrong after a merge or a rename, and it would be an account's own
# identifier living in a file (`CLAUDE.md`).
_RALLY_MINE = (
    "local P = LuaEntry.Player "
    "if col then local e2 = col:GetEnumerator() while e2:MoveNext() do local m2 = cur(e2) "
    "local u, an = nil, nil "
    "pcall(function() u = tostring(m2.ownerUid) an = tostring(m2.allianceName) end) "
    "if u == tostring(P.uid) and an ~= nil and an ~= '' and an ~= 'nil' then "
    "DataCenter.__lw_my_alliance = an end end end "
    "local mine = DataCenter.__lw_my_alliance "
)

#: The prelude the JOIN side uses: every rally out, narrowed to this alliance's. Kept
#: apart from `_RALLY_PRELUDE` because the monitor's listing wants what is on the map,
#: the whole map — «who is rallying right now» is a different question from «what may I
#: join». Falls open when the alliance could not be learned: a gate that cannot see must
#: not refuse (the same rule the squad sieve follows), and a press at a rally we cannot
#: join costs one refusal rather than a missed one.
_RALLY_PRELUDE_MINE = (
    _RALLY_PRELUDE + _RALLY_MINE +
    "local ours = {} "
    "if col and mine then local e3 = col:GetEnumerator() while e3:MoveNext() do "
    "local m3 = cur(e3) local t3, n3 = nil, nil "
    "pcall(function() t3 = m3.teamUuid n3 = tostring(m3.allianceName) end) "
    "if t3 ~= nil and tostring(t3) ~= '0' and n3 == mine then ours[tostring(t3)] = true end "
    "end end "
    "if mine ~= nil then local kept = {} "
    "for _, r in ipairs(rallies) do if ours[tostring(r.team)] then kept[#kept+1] = r end end "
    "rallies = kept end "
    # On the JOIN side `point` IS the gathering tile: everything downstream of this
    # prelude sends a squad, and a squad marches to the leader's base (see `joinpoint`
    # in `_RALLY_PRELUDE`). The listing side keeps the two apart and shows the monster.
    "for _, r in ipairs(rallies) do if r.joinpoint ~= nil then r.point = r.joinpoint end end "
)


def rally_squads_set(squads) -> str:
    """Park the squad slots a run may spend, and forget the previous run's joins."""
    slots = ",".join(str(int(s)) for s in squads)
    return ("DataCenter.__lw_rally_squads={%s} DataCenter.__lw_rally_joined={} "
            'CS.UnityEngine.Debug.LogError("ACT rally_squads_set {%s}")' % (slots, slots))


def rally_joins_pending() -> str:
    """Lua *expression* -> presses `join_rally` can still make.

    `min(squads still parked, rallies not already joined)` — so `xall` stops both
    when the squads run out and when there is no fresh rally left, and is a clean
    no-op when the map is quiet.
    """
    return ("(function() %s "
            "if #squads<#rallies then return #squads end return #rallies end)()"
            % _RALLY_PRELUDE)


def rally_joinable_count() -> str:
    """Lua *expression* -> how many rallies are out that this account is not in.

    The press's own gate is `min(squads, rallies)`; this is the rallies half on its
    own, so a recipe can tell «there was nothing to join» from «there was, and the
    join did not happen». Those are the two endings that used to look identical, and
    the second one is a fault while the first is an ordinary quiet minute.
    """
    return "(function() %s return #rallies end)()" % _RALLY_PRELUDE_MINE


def rally_day_count() -> str:
    """Lua *expression* -> `"<done> <max>"` — the day's rallies, as the GAME counts them.

    `DataCenter.MonsterManager` keeps the account's own daily rally-boss counter and the
    threshold beside it — `daily_kill_boss` / `kill_boss_max_num`, reached through
    `GetKillBossNum()` and `GetMaxKillBossNum()` (docs/research/rally-join.md, «The game
    keeps the count itself»). It is per ACCOUNT, kept by the server and reset on the
    server's own day, which is why nothing here counts anything and no PC clock is
    consulted.

    It counts a rally that FINISHED and paid, so it lags the joins in flight by however
    many squads are out — measured live at 275 against 320 joins the panel had recorded
    over the same day. That is the honest limit of it and it is the number the ceiling is
    judged against all the same, because it is the only one the game keeps
    (`rally_join_all`, #1317).

    `"-1 -1"` when the manager cannot be reached — «unreadable», never «none today».
    """
    return ("(function() local a, b = -1, -1 "
            "pcall(function() local MM = DataCenter.MonsterManager "
            "a = MM:GetKillBossNum() b = MM:GetMaxKillBossNum() end) "
            "return tostring(math.floor(tonumber(a) or -1)) .. ' ' .. "
            "tostring(math.floor(tonumber(b) or -1)) end)()")


def server_day_end() -> str:
    """Lua *expression* -> the ms at which the SERVER's day turns, or 0.

    `UITimeManager:GetInstance():GetTomorrowZero()` — the client's own answer, and the
    only honest one: the boundary is 02:00 UTC on the warzone this was measured on
    (#1188) and there is nothing that says every warzone shares it. Anything a daily
    budget of ours resets on is judged against this rather than against a date the PC
    works out for itself (#1317).
    """
    return ("(function() local v = 0 "
            "pcall(function() v = UITimeManager:GetInstance():GetTomorrowZero() end) "
            "return math.floor(tonumber(v) or 0) end)()")


def rally_joined_count() -> str:
    """Lua *expression* -> how many of OUR squads are standing in a rally right now.

    Read before the press and again after it, and the difference is the only honest
    answer to «did that do anything». The press cannot answer it for itself: the send
    is scheduled onto the game's own timer and returns before the server has replied,
    so a press that «worked» and a press that vanished return exactly the same thing
    (docs/research/rally-join.md).
    """
    return ("(function() local P=LuaEntry.Player "
            "local wm=DataCenter.WorldMarchDataManager "
            "local afd=DataCenter.ArmyFormationDataManager local n=0 "
            "for _,f in pairs(afd.ArmyFormationList) do pcall(function() "
            "local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) "
            "if m~=nil and tostring(m.teamUuid)~=\"0\" then n=n+1 end end) end "
            "return n end)()")


def rally_join_all() -> str:
    """Join EVERY rally that can be joined right now — sieve, pair and send, in ONE chunk.

    THE WHOLE ABILITY IN A SINGLE CALL, and the reason is a measurement rather than a
    taste for short code. A call into the game VM cost **1.3 s at best and 10–19 s under
    the panel's ordinary background load** on the live client (task #1281,
    `tools/dev/rally_latency.py`; the client itself was at 59 fps, so none of it is the
    game's). The recipe this replaces took EIGHT readings before it sent anything —
    measured at 100 s to the send, twice over — and a banner during an event is gone in
    a fraction of that. Everything that used to be a reading is now a local variable:

      * which rallies are out that belong to this alliance and we are not already in
        (`_RALLY_PRELUDE_MINE`);
      * which of the parked squads are standing at home, idle, and have soldiers;
      * the pairing, one squad per rally, in the order both arrived;
      * the send itself, the same `SendCreateMarchMessage` the game's own squad screen
        ends at (`rally_join_send` — the type is the SECOND argument, #1277);
      * and the count of our squads standing in rallies BEFORE any of it, so the recipe
        can prove afterwards that the map moved.

    THE DOORS ARE HERE TOO, for the same reason: a check in front of this chunk is a
    second call on the one path measured in fractions of a second. The day's ceiling
    against the game's own counter (`__lw_rally_cap` → `-4`), the per-kind budgets and
    the kind filter the panel parks, and the SOLDIER FLOOR — `__lw_rally_min_soldiers`,
    how many soldiers must be standing in the base before a banner is worth a squad at
    all (`-5`, #1317). The pool it is judged against is the one the sieve already reads.

    EVERY SQUAD AND EVERY RALLY LEFT BEHIND IS NAMED. `DataCenter.__lw_rally_report` is
    a sentence the recipe reads back and logs: how many were sent, how many rallies were
    out, and one word per squad that was passed over — `out` (marching, gathering,
    already in a rally), `empty` (no soldiers), `no-formation` (the game knows no squad
    in that slot) — plus the server's own refusal for a send that threw. «Тихо не
    поехали» is what this exists to make impossible.

    NOTHING IS OPENED ON SCREEN BY THIS CHUNK, and on the path that catches a banner
    nothing is opened at all. The march itself never needed a window — that is the whole
    finding, and it is the same one «Кодовое имя» rests on (#1259): five screens a person
    walks converge on one send, and the target is addressed by uuid.

    The one thing a window still does is FILL AN EMPTY SQUAD from the base's pool, and
    the client refuses a squad with no soldiers before a byte leaves. That is not the
    march, so it is not on the march's path: this chunk reports such a squad as `empty`
    and sets `__lw_rally_todo = -1`, and the recipe decides — after the fast send has
    already gone out for every squad that had an army — whether to spend the four extra
    calls opening the game's own screen for the ones that had not.

    A JOIN IS MARKED THE MOMENT IT IS SENT (`__lw_rally_joined`), because the server
    takes seconds to answer and two squads landing on one banner is worse than a slow
    join. The marks are PRUNED first against the rallies actually on the map, so a
    banner that came down and a banner we failed to join both stop being marked — a mark
    that outlived its rally is how «joined once, never again» would look.
    """
    return (
        # The marks first, and only the ones whose rally is still out. Before the
        # prelude, which reads this table to decide what is already ours.
        "local wm0 = DataCenter.WorldMarchDataManager "
        "local live = {} local c0 = wm0 and wm0:GetAllMarches() "
        "if c0 then local e0 = c0:GetEnumerator() while e0:MoveNext() do local m0 = e0.Current "
        "local ok0, v0 = pcall(function() return m0.Value end) if ok0 and v0 ~= nil then m0 = v0 end "
        "local ok1, t0 = pcall(function() return m0.teamUuid end) "
        "if ok1 and t0 ~= nil then live[tostring(t0)] = true end end end "
        # A MARK MUST NOT OUTLIVE THE SQUAD IT STANDS FOR (#1281). It exists to bridge the
        # seconds between a send and the server confirming it, so that two squads are not
        # spent on one banner. Keeping it for as long as the BANNER lives is too long: a
        # squad comes home, the rally is still standing and could be joined again, and the
        # run says «no rally we are not already in» — which by then is false. Seen live:
        # `seen=6 ours=6 already_in=0 rallies=0`, six banners of ours, a march of ours in
        # none of them, and every one of them held shut by a mark.
        #
        # So a mark AGES. It is dropped when the banner is gone (as before), and also once
        # it has survived two runs with no march of ours in that team — by which point the
        # server has long since answered and the mark is standing for nothing.
        "local om0 = wm0 and wm0:GetOwnerMarches() local ours_in = {} "
        "if om0 then local e7 = om0:GetEnumerator() while e7:MoveNext() do local m7 = e7.Current "
        "local ok7, v7 = pcall(function() return m7.Value end) if ok7 and v7 ~= nil then m7 = v7 end "
        "local ok8, t7 = pcall(function() return m7.teamUuid end) "
        "if ok8 and t7 ~= nil then ours_in[tostring(t7)] = true end end end "
        "local keep = {} "
        "for k, age in pairs(DataCenter.__lw_rally_joined or {}) do "
        "if live[k] then "
        "if ours_in[k] then keep[k] = 0 "
        "else local a = (tonumber(age) or 0) + 1 if a < 2 then keep[k] = a end end end end "
        "DataCenter.__lw_rally_joined = keep "
        # HOW MANY SQUADS THIS BANNER HAS ALREADY SWALLOWED (#1281). `__lw_rally_shut`
        # empties every run on purpose — a refusal is only terminal while the banner
        # stands, and a squad that came home deserves a second look. What it cannot see
        # is a banner asked again and again across runs: measured over three and a half
        # hours, one banner took FOURTEEN squads and let none of them in, and eighteen
        # banners between them ate 108 of the 137 sends that reached nothing.
        #
        # A retry is still worth having — 9 of the 114 banners we got into took more than
        # one send, all of them landing on the second or third, 6 to 11 seconds later. So
        # the count is kept per banner for as long as the banner is on the map and the
        # third failure is the last: it keeps 8 of those 9 and saves 51 sends that could
        # not have worked. The count is cleared the moment a march of ours stands in that
        # team, so a banner we are IN is never charged for the tries it took.
        "local tries = {} "
        "for k, n in pairs(DataCenter.__lw_rally_tries or {}) do "
        "if live[k] and not ours_in[k] then tries[k] = tonumber(n) or 0 end end "
        "DataCenter.__lw_rally_tries = tries " +
        _RALLY_PRELUDE_MINE +
        # What the run will be judged against: our squads standing in a rally right now.
        "local before = 0 "
        "local afd = DataCenter.ArmyFormationDataManager "
        "for _, f in pairs(afd.ArmyFormationList) do pcall(function() "
        "local m = wm:GetOwnerFormationMarch(P.uid, f.uuid, P.allianceId) "
        "if m ~= nil and tostring(m.teamUuid) ~= '0' then before = before + 1 end end) end "
        "DataCenter.__lw_rally_before = before "
        # HOW MANY SOLDIERS THE PLAYER OWNS AT ALL — the difference between «this squad
        # has not been topped up» and «there are not enough troops in the base to fill
        # any squad» (#1281). One reading, ahead of the sieve, so both words below cost
        # nothing extra. `0` when it cannot be read, and then the sieve says the milder
        # of the two rather than inventing a wall.
        "local pool = 0 "
        "pcall(function() pool = tonumber("
        "DataCenter.SoldierDataManager:GetPlayerSoldiersTotalNum()) or 0 end) "
        # The sieve, with a word for every squad it drops. A squad whose state cannot be
        # read at all is KEPT: a gate that cannot see must not refuse (#1237).
        "local home, skipped, unchecked = {}, {}, {} "
        "for _, s in ipairs(squads) do "
        "local f = nil "
        "for _, v in pairs(afd.ArmyFormationList) do "
        "local ok, idx = pcall(function() return v.index end) "
        "if ok and tonumber(idx) ~= nil and tonumber(idx) == tonumber(s) then f = v end end "
        "if f == nil then skipped[#skipped+1] = tostring(s)..':no-formation' "
        "else "
        "local st = tonumber(f.state) "
        "local ok, idle = pcall(function() return f:IsFree() end) "
        "local free = true if ok and idle ~= nil then free = (idle and true or false) end "
        # FILL IT, THEN MEASURE IT — the order the player asked for, and the game's own
        # filler is what does both (#1281). `ArmyFormation:ConscriptSoldier()` is the
        # method the squad screen runs: it draws from `SoldierDataManager:GetInsideSoldiers()`
        # up to what the squad's heroes can carry, and on the way it WRITES the ceiling
        # into `heroTotalSoldierCapacity`. Nothing in it sends: read off its own
        # constants, it touches the soldier pool, the hero table and its own fields and
        # no message at all.
        #
        # That call is why the check works headless. Without it the ceiling is simply
        # absent — measured live on three squads, `GetAllHeroSoldierCapacity()` answered
        # 0 before and 3123 / 2631 / 2565 immediately after, and the game's own dispatch
        # screen had shown «3,123/3,123 units» for the first of them
        # (docs/research/world-monsters.md, finding 10). Until this line the gate could
        # only ever see a ceiling on a client whose dispatch screen had been rendered by
        # hand.
        "pcall(function() f:ConscriptSoldier() end) "
        # A SQUAD BELOW ITS OWN CEILING IS NOT SENT, and the ceiling is the one the
        # squad's heroes can carry rather than whatever happens to be standing in it.
        # `totalSoldierNum` is what is in it now, and it reads 0 until the army has been
        # asked for, which is why nothing may be decided from it before the recipe's
        # `formation.get.soldier` has run (#1285) — the fill above works from the pool,
        # not from the squad, so it does not stand in for that request.
        #
        # A ceiling that cannot be read does not refuse: an unreadable gate must not
        # shut, the same rule the state check above follows.
        "local n = 0 pcall(function() n = tonumber(f.totalSoldierNum) or 0 end) "
        "local cap = 0 pcall(function() cap = math.floor(tonumber(f:GetAllHeroSoldierCapacity()) or 0) end) "
        "if st ~= nil and not (st == 0 and free) then skipped[#skipped+1] = tostring(s)..':out' "
        "elseif n <= 0 then skipped[#skipped+1] = tostring(s)..':empty' "
        # THE TWO REASONS ARE NOT THE SAME REASON, and that is the whole point of
        # splitting them. «Not topped up» is a minute's work for the player; «there are
        # not enough soldiers in the base to fill one squad» is a wall, and an auto-join
        # that goes quiet against a wall must SAY which wall. Measured on the live
        # account the day this was written: three squads holding 1725/1724/1725 against
        # ceilings of 3123/2631/2565, out of 1727 soldiers owned in total — so not one
        # squad could be filled, and a single unnamed «passed over» would have read as an
        # ordinary quiet evening for as long as the barracks stayed that size.
        "elseif cap > 0 and n < cap then "
        "if pool > 0 and pool < cap then "
        "skipped[#skipped+1] = tostring(s)..':short-of-troops('..n..'/'..cap..', base has '..pool..')' "
        "else skipped[#skipped+1] = tostring(s)..':not-full('..n..'/'..cap..')' end "
        "else home[#home+1] = {slot = s, uuid = f.uuid} "
        # A SQUAD THAT WENT WITHOUT THE CEILING BEING CHECKED SAYS SO (#1281). The
        # ceiling is `heroTotalSoldierCapacity`, and a headless client leaves it nil
        # until the game's own dispatch screen has been rendered once — the same
        # recompute that flips `canMarch` (docs/research/world-monsters.md, finding 10).
        # An unreadable gate must not refuse, so the squad goes; what it must not do is
        # go SILENTLY, or «the full-squad check does nothing» looks exactly like «every
        # squad was full».
        "if not (cap > 0) then unchecked[#unchecked+1] = tostring(s) end end end end "
        # THE DENOMINATOR, counted rather than guessed (#1281). «Six banners» is not six
        # chances: the list the client keeps holds every team on the map — other
        # alliances', and the ones we are already standing in. Without the split, «two
        # were missed» cannot be said or denied, which is exactly what the summary had to
        # admit. One more pass over the collection already in hand, so it costs nothing.
        # WHAT KIND OF RALLY EACH ONE IS, and it is a real question rather than a
        # placeholder (#1281). The budget has had three keys since it was written —
        # `monster`, `zombie_invasion` (uncapped on purpose), `alliance_drill` — and no
        # classifier at all: the reading that was supposed to tell them apart assigned
        # the SAME key to every rally, so an invasion boss, which the event does not
        # ration, spent the ordinary monsters' twenty a day.
        #
        # The march itself cannot answer: every leader on the map reads `monsterId=0`,
        # `monsterType=0`, `type=ASSEMBLY_MARCH`. What CAN is the event's own list of
        # monsters (`ActivityMonsterInvasionDataManager.monsterInvasionData`, fields
        # `selfMonsters` / `aliMonsters`), so a rally whose target is in it is an
        # invasion boss and everything else is an ordinary monster.
        #
        # Indexed by uuid AND by tile, because the element shape could not be read from a
        # live event — the lists are empty between waves — and a key that is not there
        # simply never matches. `inv_ok` says whether the lists could be read at all,
        # which is the difference between «this is not an invasion boss» and «nobody
        # could tell», and the report says which.
        "local inv_set, inv_ok = {}, false "
        "pcall(function() local im = DataCenter.ActivityMonsterInvasionDataManager "
        "local d = im and im.monsterInvasionData "
        "if d ~= nil then inv_ok = true "
        "for _, nm in ipairs({'selfMonsters', 'aliMonsters'}) do "
        "local lst = nil pcall(function() lst = d[nm] end) "
        "if type(lst) == 'table' then for kk, mon in pairs(lst) do "
        "inv_set[tostring(kk)] = true "
        "pcall(function() if mon.uuid ~= nil then inv_set[tostring(mon.uuid)] = true end end) "
        "pcall(function() if mon.pointId ~= nil then inv_set['p'..tostring(mon.pointId)] = true end end) "
        "pcall(function() if mon.point ~= nil then inv_set['p'..tostring(mon.point)] = true end end) "
        "end end end end end) "
        # WHAT EACH BANNER IS GOING FOR, off the wire. The push carries
        # `targetContentId` — the monster's config id — and the client's own march record
        # drops it (25 of the push's 33 fields survive into `GetAllMarches()`, not this
        # one), so the panel hears it and parks it here as `team:contentId,…` (#1281).
        # `lw_world_monster` turns it into a type and a level: 7 is the zombie line
        # (Invading Zombies / Zombie Boss), 8 is the Doom line (Роковая Элита).
        "local target_of_team = {} "
        # HOW MANY OF THEM THERE WERE, remembered before anything is looked up (#1323).
        # An empty map is not «this banner is new», it is «this profile cannot name a
        # single banner», and the two produce the same `monster` in the count while
        # meaning opposite things.
        "local tgt_n = 0 "
        "pcall(function() for pair in string.gmatch(tostring("
        "DataCenter.__lw_rally_targets or ''), '[^,]+') do "
        "local team, cid = string.match(pair, '(%d+):(%d+)') "
        "if team ~= nil then target_of_team[team] = tonumber(cid) tgt_n = tgt_n + 1 end end end) "
        "local LCI = nil pcall(function() LCI = LocalController.instance() end) "
        + _kind_table() +
        # AN UNKNOWN ROW ANSWERS WITH AN EMPTY STRING, NOT NIL — measured live: asking
        # `lw_world_monster` for an id it has never heard of came back `type=''`, and a
        # first version of the branch below turned that into the key `monster_type_`
        # with nothing after it. Empty is «no answer», and «no answer» has to be the
        # unheard-of case rather than a species with a blank name (#1281).
        # THE SPECIES IS ITS `name` KEY, NOT ITS `type` (#1317). Read out of the live
        # config: «Роковая Элита» (`300602`) sits under three different types across
        # seasons, and type 8 is not it at all — that is the Doom WALKER line
        # (`monster_boss_name_001`, «Разрушитель»), which is what the old `doom_elite`
        # key had been counting. `activity` is what marks an event's monsters, and 107 is
        # the General's Trial, whose two species are the ones the player names as «простые
        # и элитные»: `2010220` Vanguard Instructors and `challenge_zombie_001` Elite
        # Instructor.
        "local function monster_of(cid) "
        "if LCI == nil or cid == nil then return nil, nil, nil, nil end "
        "local ty, lv, nm, act = nil, nil, nil, nil "
        "pcall(function() ty = LCI:getValue('lw_world_monster', cid, 'type', nil) end) "
        "pcall(function() lv = LCI:getValue('lw_world_monster', cid, 'level', nil) end) "
        "pcall(function() nm = LCI:getValue('lw_world_monster', cid, 'name', nil) end) "
        "pcall(function() act = LCI:getValue('lw_world_monster', cid, 'activity', nil) end) "
        "if ty ~= nil and tostring(ty) == '' then ty = nil end "
        "if lv ~= nil and tostring(lv) == '' then lv = nil end "
        "if nm ~= nil and tostring(nm) == '' then nm = nil end "
        "if act ~= nil and tostring(act) == '' then act = nil end "
        "return ty, lv, nm, act end "
        # THE ALLIANCE EXERCISE NAMES ITS OWN BOSS, and that is the only exact way to know
        # one: the drill's boss is not a species on the map but a uuid the manager carries
        # (`AllyDrillDataManager.actInfo.data.bossUuid` / `bossPointId`, read live for
        # #1317 while a drill was running).
        "local drill_uuid, drill_point = nil, nil "
        "pcall(function() local d = DataCenter.AllyDrillDataManager.actInfo.data "
        "drill_uuid = d and d.bossUuid drill_point = d and d.bossPointId end) "
        # THE INVASION EVENT STILL ANSWERS FIRST: its own monster lists are the only thing
        # that marks a banner as one the event does not ration, and that is a different
        # question from what species is standing on the tile.
        "local function kind_of(r) "
        "local cid = target_of_team[tostring(r.team)] "
        "local ty, lv, nm, act = monster_of(cid) "
        "r.level = lv r.mtype = ty "
        "if drill_uuid ~= nil and r.target ~= nil "
        "and tostring(r.target) == tostring(drill_uuid) then return 'alliance_drill', true end "
        "if drill_point ~= nil and r.point ~= nil "
        "and tostring(r.point) == tostring(drill_point) then return 'alliance_drill', true end "
        "if inv_ok then "
        "local tu = r.target "
        "if tu ~= nil and inv_set[tostring(tu)] then return 'zombie_invasion', true end "
        "if r.point ~= nil and inv_set['p'..tostring(r.point)] then return 'zombie_invasion', true end end "
        # …then the event a species belongs to, and then the species itself — which is the
        # split the player reads off the screen.
        "if nm ~= nil then local hit = KIND_OF_NAME[tostring(nm)] "
        "if hit ~= nil then return hit, true end end "
        "if act ~= nil and tostring(act) == '107' then return 'general_trial', true end "
        "if ty ~= nil and tonumber(ty) ~= nil then "
        "if tonumber(ty) == 8 then return 'doom_walker', true end "
        "if tonumber(ty) == 7 then return 'zombie_boss', true end "
        # A ROW THE NAME TABLE CANNOT NAME IS NOT A KIND OF ITS OWN (#1323). This used to
        # answer `monster_type_<n>`, and that key is in nobody's vocabulary: the panel's
        # caps file is seeded from `rally_kinds.KIND_ORDER`, so such a key has no cap, is
        # never handed a budget, is never shown on the tab and never appears in
        # `over_budget` — while the tally counts joins under it all day. The key a join is
        # COUNTED under and the key the door looks a budget up by have to be one key or
        # the door is open by construction. So an unnamed row is the fallback kind, the
        # type is kept for the report (`r.unnamed`), and nothing is spent from a budget
        # nobody could set.
        "r.unnamed = tonumber(ty) "
        "return 'monster', false end "
        # NOT HEARD OF, and said so rather than assumed. A banner raised before the panel
        # started listening has no push behind it, so its kind is genuinely unknown; it is
        # counted as an ordinary monster because something must be counted, and the report
        # says how many were counted that way.
        "return 'monster', false end "
        # HOW MANY SEATS THE BANNER HAS, and how many are taken. The wire says the size
        # (`assemblyMarchMax`, measured live at 5) and the client's own march list says
        # the occupancy — every member march of a rally is in it, which is how the count
        # stays right without waiting for another push. The panel parks the sizes here
        # as `team:max,…` exactly as it parks the targets (#1281).
        # AND HOW FULL IT WAS WHEN WE LAST HEARD IT (#1281). The occupancy used to be
        # counted in the client alone, on the argument that its march list is current at
        # the moment of the send while a push is as old as the last one we heard. The
        # wire says otherwise: over three and a half hours, 21 squads were sent at a
        # banner the wire had last announced as 5 of 5 and NOT ONE of them reached it,
        # while the client's own count of those same banners still showed a seat. Both
        # numbers are floors of the truth — a march the other side has not told us about
        # is missing from ours, and a member who joined since the last push is missing
        # from theirs — so the sieve believes the LARGER, and only a banner both agree is
        # open stays a candidate.
        "local max_of, wire_taken = {}, {} "
        "pcall(function() for pair in string.gmatch(tostring("
        "DataCenter.__lw_rally_slots or ''), '[^,]+') do "
        "local team, tk, mx = string.match(pair, '(%d+):(%d+)/(%d+)') "
        "if team == nil then team, mx = string.match(pair, '(%d+):(%d+)') end "
        "if team ~= nil then max_of[team] = tonumber(mx) "
        "if tk ~= nil then wire_taken[team] = tonumber(tk) end end end end) "
        # Banners this run has already been refused by — the recipe writes them here when
        # a send produced no march, and they are not offered again inside the same run.
        "local blocked = {} "
        "pcall(function() for k in pairs(DataCenter.__lw_rally_shut or {}) do "
        "blocked[tostring(k)] = true end end) "
        "local seen_t, our_t, end_of, target_of, count_of = {}, {}, {}, {}, {} "
        "if col then local e9 = col:GetEnumerator() while e9:MoveNext() do local m9 = cur(e9) "
        "local t9 = g(m9, 'teamUuid') local ts9 = tostring(t9) "
        "if t9 ~= nil and ts9 ~= '0' and ts9 ~= 'nil' then seen_t[ts9] = true "
        "count_of[ts9] = (count_of[ts9] or 0) + 1 "
        "local u9 = g(m9, 'uuid') local lead9 = false "
        "pcall(function() lead9 = (tostring(u9) == tostring(t9 - 1)) end) "
        "if lead9 then end_of[ts9] = tonumber(g(m9, 'endTime')) or 0 "
        "target_of[ts9] = g(m9, 'targetUuid') end "
        "local n9 = tostring(g(m9, 'allianceName')) "
        "if mine ~= nil and n9 == mine then our_t[ts9] = true end end end end "
        # THE BANNERS THE CLIENT HAS NOT HEARD OF YET (#1301), and they are the whole of
        # the delay a person sees. Everything above this line reads `GetAllMarches()`,
        # and that table is a MEDIAN OF 10 s behind the push that announced the banner
        # (p25 8.1 s, p75 19.1 s, max 62 s, over 31 banners) — in 23 of 26 late cases it
        # only learned about the banner once somebody ELSE had joined it. The trigger
        # itself is instant: 0.005 s from the wire to the fire, 0.3 s from there to the
        # send. So a run woken by a push spent its 0.3 s, found nothing, and truthfully
        # reported `rallies=0` — measured end to end at 16:19:49.682 push → 16:19:50.175
        # send → `sent=0 rallies=0 seen=0`, and the same banner joined at 16:19:58 the
        # moment a refresh push made the client notice it.
        #
        # The push carries everything the send needs from the first byte, so the panel
        # parks it here as `team:tile/server,…` (`rallytab.point_map`) and a banner the
        # wire has announced becomes a candidate with the address off the wire. It is
        # ONLY ever an addition: a team the client already lists is skipped here and
        # stays the client's, and one we already have a march in (`taken`) or have been
        # refused by this run (`blocked`) is skipped as it would be anywhere else.
        #
        # THEY GO IN FRONT, because that is the point: a banner the client has not caught
        # up with is by definition the freshest one on the map, and the ones already in
        # its table have had at least one run to be taken.
        #
        # NOT PUT THROUGH THE ALLIANCE SIEVE, and it does not need to be: these arrive on
        # `push.alliance.march.*`, which is this alliance's own stream. The sieve above
        # exists because `GetAllMarches()` returns both sides of a war; the wire does not.
        #
        # A uuid THAT DOES NOT SURVIVE THE ROUND TRIP IS DROPPED. A teamUuid is 19 digits;
        # an integer Lua holds exactly and a double does not, and a send aimed at a
        # rounded uuid reaches nothing while reporting cleanly — the failure this ability
        # already spent weeks in (#1237). `tostring(tonumber(t)) == t` is the whole test:
        # it holds on an integer VM and fails on the scientific notation a float gives
        # back, so the candidate is simply left to the client rather than sent into the
        # void.
        "local from_wire = {} "
        "pcall(function() local ahead = {} "
        "for pair in string.gmatch(tostring("
        "DataCenter.__lw_rally_points or ''), '[^,]+') do "
        "local team, pt, sv = string.match(pair, '(%d+):(%d+)/(%d+)') "
        "if team ~= nil and not seen_t[team] and not taken[team] and not blocked[team] then "
        "local tn = tonumber(team) local pn, sn = tonumber(pt), tonumber(sv) "
        "if tn ~= nil and tostring(tn) == team and pn ~= nil and sn ~= nil then "
        "ahead[#ahead+1] = {team = tn, point = pn, server = sn} "
        "from_wire[#from_wire+1] = team end end end "
        "if #ahead > 0 then for _, r in ipairs(rallies) do ahead[#ahead+1] = r end "
        "rallies = ahead end end) "
        # A RALLY THAT HAS ALREADY ARRIVED IS NOT A RALLY TO JOIN (#1281). The client
        # keeps a resolved banner in its march table — same teamUuid, same
        # `type=ASSEMBLY_MARCH`, `status` still saying MOVING — so nothing in the shape
        # of the entry says it is over. `endTime` does, and it is the only field that
        # does: nine «banners» on the map at 18:52 and every one of them had arrived,
        # the oldest thirty-two minutes earlier. Squads were being sent at all of them,
        # the server dropped every send without a word on screen, and the run reported
        # «sent=3 … joined=0» — fifteen sends and no march in one quarter of an hour.
        #
        # This is also the correction to a claim made earlier in this task: «six joinable
        # banners held shut by a mark» were six banners that had already been fought.
        # Ageing the marks did not free them, it removed the accidental guard that was
        # keeping squads off them.
        "local now_ms = 0 "
        "pcall(function() now_ms = UITimeManager:GetInstance():GetServerTime() end) "
        "local arrived = {} "
        "if now_ms > 0 then local still = {} "
        "for _, r in ipairs(rallies) do local et = end_of[tostring(r.team)] "
        "if et == nil or et <= 0 or et > now_ms then still[#still+1] = r "
        "else arrived[#arrived+1] = tostring(r.team) end end "
        "rallies = still end "
        # A BANNER STILL GATHERING CAN STILL BE SHUT (#1281). The player watched the
        # Marshal event and named it: the list of active rallies is full of banners that
        # have not left yet and have no seat left in them, and every squad we owned was
        # being thrown at one. `endTime` cannot see that — it says the banner is still
        # standing, which is true. Seats can: nine banners measured on the wire during
        # that event and every one of them read 5 of 5.
        #
        # A banner whose size we never heard is NOT filtered — an unheard size is not a
        # full banner, and the refusal path below is what catches those.
        "local full = {} "
        "local still2 = {} "
        "for _, r in ipairs(rallies) do local ts = tostring(r.team) "
        "local mx, taken = max_of[ts], count_of[ts] or 0 "
        "local wt = wire_taken[ts] "
        "local src = 'client' "
        "if wt ~= nil and wt > taken then taken = wt src = 'wire' end "
        "local spent = tonumber(tries[ts] or 0) or 0 "
        "if blocked[ts] then full[#full+1] = ts..':refused-full' "
        "elseif spent >= 3 then full[#full+1] = ts..':swallowed('..spent..' squads, none arrived)' "
        "elseif mx ~= nil and mx > 0 and taken >= mx then "
        "full[#full+1] = ts..':banner-full('..taken..'/'..mx..' by '..src..')' "
        "else still2[#still2+1] = r end end "
        "rallies = still2 "
        "local function _n(t) local k = 0 for _ in pairs(t) do k = k + 1 end return k end "
        # COUNTED FROM OUR OWN MARCHES, not from the marks. `taken` also carries the
        # teams this run has just SENT to, and a mark outlives the squad that came home —
        # so counting it answered «already_in=6» on an account with three squads, which is
        # a number that cannot be true. The honest reading is a march of ours standing in
        # that team right now, which is the same thing `before` is counted from.
        "local seen_n, our_n, in_n = _n(seen_t), _n(our_t), 0 "
        "local om2 = wm:GetOwnerMarches() "
        "if om2 then local e8 = om2:GetEnumerator() while e8:MoveNext() do local m8 = cur(e8) "
        "local t8 = g(m8, 'teamUuid') local ts8 = tostring(t8) "
        "if t8 ~= nil and ts8 ~= '0' and seen_t[ts8] then in_n = in_n + 1 end end end "
        # Pair and send. One squad per rally, both in the order they arrived. EVERY BANNER
        # IS NAMED — the one it went to, and the one it did not and why — so «not a banner
        # missed» can be checked one at a time instead of as a total (#1281).
        # THE DAY'S CEILING, AND IT IS THE GAME'S OWN NUMBER (#1317). `daily_kill_boss`
        # is what the client counts rally bosses with — one per rally that finished and
        # paid today, kept by the server and reset on the SERVER's day, so it needs no
        # tally of ours and no PC clock.
        #
        # It was a READING here until #1317 and it is a door again, which is a reversal
        # worth spelling out. #1281 took the door out for a good reason — the panel's own
        # tally was twelve ahead of the game's and had been refusing banners the account
        # was entitled to since 19:42 — and drew the wrong conclusion from a true fact:
        # past twenty the game stops PAYING, it does not stop the joining. The player has
        # since said what that costs: «лимит Роковой Элиты стоит 20, а бот целый день
        # цепляется к стягам» — a squad in an unpaid rally is a squad away from home for
        # nothing, all evening. So the door is back, with the tally taken out of it: the
        # count is the game's (`GetKillBossNum`), the ceiling is the person's
        # (`__lw_rally_cap`, 0 = no ceiling), and nothing here is written down.
        #
        # A GATE THAT CANNOT SEE DOES NOT REFUSE: an unreadable `kb` joins as before.
        "local kb, kbmax, kbleft = nil, nil, nil "
        "pcall(function() local MM = DataCenter.MonsterManager "
        "kb = MM:GetKillBossNum() kbmax = MM:GetMaxKillBossNum() "
        "kbleft = MM:GetRestKillBossNum() end) "
        "local cap = tonumber(DataCenter.__lw_rally_cap) or 0 "
        "local capped = (cap > 0 and tonumber(kb) ~= nil and tonumber(kb) >= cap) "
        # …AND THE SOLDIERS IN THE BASE, WHICH IS A DOOR OVER THE WHOLE RUN (#1317).
        #
        # «Сделай число в панели, и будем сравнивать кол солдат в казарме с указанным,
        # если меньше, автостяги останавливаем.» One number typed by the person, one
        # reading off the game, and nothing goes out while the reading is the smaller —
        # no shares, no sums of the squads' ceilings, no arithmetic about how many squads
        # it would fill.
        #
        # THE READING IS `pool` — `SoldierDataManager:GetPlayerSoldiersTotalNum()`, the
        # soldiers standing IN THE BASE, which the sieve above was already asking for.
        # It is the pool the game's own squad filler draws from: it falls when a march
        # leaves and rises when one returns, so soldiers out with a squad are not in it.
        # The report names it (`in_base=`) rather than leaving «казарма» to be guessed at.
        #
        # A GATE THAT CANNOT SEE DOES NOT REFUSE: `pool` is 0 when the reading failed, and
        # then this door stands open exactly as it did before it existed.
        "local minpool = tonumber(DataCenter.__lw_rally_min_soldiers) or 0 "
        "local short_pool = (minpool > 0 and pool > 0 and pool < minpool) "
        # …AND HOW LONG THE SQUAD WOULD BE IN THE AIR (#2425).
        #
        # «Когда приходит пуш свободного стяга, нужно проверять расстояние до того, кто
        # организует стягивание; если поход занимает более 5 секунд, к такому стягу не
        # присоединяемся.» A squad sent to the far side of the map is a squad that misses
        # every near banner while it flies, and the banners are many and frequent.
        #
        # PRICED THE WAY THE GAME PRICES IT, and both halves are the game's own answer:
        # `SceneUtils.TileDistanceToMyHome(point, server)` is the distance from the base
        # — where a squad the sieve keeps is standing — to the tile the joiners gather
        # on, and `MarchUtil.CalcMarchSpeedByConfig(JOIN_RALLY, formationUuid)` is that
        # squad's own speed in tiles a second (`docs/research/golden-zombies.md` §4b
        # measured that unit against the server's own `endTime`, two seconds apart over a
        # 271 s march). Nothing is invented here and nothing is read that was not already
        # to hand: it is arithmetic on two calls the chunk makes for itself.
        #
        # THE SPEED IS THE SQUAD'S, so it is asked per formation and cached for the run —
        # the bonuses behind it (`GetFormationSpeedAddByIndex`) are per squad, and the
        # banner is judged against the squad that would actually go to it.
        #
        # A GATE THAT CANNOT SEE DOES NOT REFUSE: an unreadable distance or speed comes
        # back `-1` and the banner is taken exactly as it was before this existed.
        "local maxfly = tonumber(DataCenter.__lw_rally_max_fly) or 0 "
        "local spd_of = {} "
        "local function fly_secs(r, q) "
        "if r == nil or q == nil or r.point == nil then return -1 end "
        "local key = tostring(q.uuid) local sp = spd_of[key] "
        "if sp == nil then sp = 0 pcall(function() "
        "sp = tonumber(MarchUtil.CalcMarchSpeedByConfig(6, q.uuid, nil, nil)) or 0 end) "
        "spd_of[key] = sp end "
        "if sp <= 0 then return -1 end "
        "local d = -1 pcall(function() "
        "d = tonumber(SceneUtils.TileDistanceToMyHome(r.point, r.server)) or -1 end) "
        "if d < 0 then return -1 end return d / sp end "
        # …AND THE CEILING PER KIND (#1317). `kind:left,…`, parked by the panel, which is
        # the only thing that can count them: the client keeps ONE daily rally counter and
        # no per-species number anywhere — every manager was walked for #1317 and there is
        # none. So the panel's tally is the source, the person's number is the cap, and
        # what happens HERE is the decision: a banner of a kind with nothing left is
        # passed over and named, and each send spends one from the kind it went to, so two
        # banners of the same kind in one press cannot both take the last one.
        #
        # A kind with NO entry is unlimited, exactly as `0` means in the panel's file.
        "local kind_left = {} "
        "pcall(function() for pair in string.gmatch(tostring("
        "DataCenter.__lw_rally_kind_left or ''), '[^,]+') do "
        "local k, n = string.match(pair, '([%w_]+):(%-?%d+)') "
        "if k ~= nil then kind_left[k] = tonumber(n) end end end) "
        # …AND THE DOOR IS MADE CHECKABLE FROM THE RUN'S OWN LINE (#1322). The budget that
        # was in force is remembered before a single send spends from it, and the report
        # names it for every kind this run actually looked at. A door that refuses nothing
        # and a door that was never handed a number read exactly alike in the log —
        # `kind_capped=` simply never appeared — and for a whole day that was the
        # difference between a cap of 20 and thirty joins of «Элитные инструкторы».
        "local kind_left0, kind_n = {}, 0 "
        "for k, v in pairs(kind_left) do kind_left0[k] = v kind_n = kind_n + 1 end "
        "local kind_seen = {} "
        # …AND THE KINDS THE PERSON SIMPLY DOES NOT WANT (#1317). A filter, not a budget:
        # nothing is counted, so nothing can drift — «цепляться к этим, к тем не
        # цепляться» is answerable exactly, because the kind of a banner is known here
        # BEFORE a squad leaves. `kind_skip` is a plain list of kinds, and a banner of one
        # is passed over and named `kind-off`.
        "local kind_off = {} "
        "pcall(function() for k in string.gmatch(tostring("
        "DataCenter.__lw_rally_kind_skip or ''), '[^,]+') do kind_off[k] = true end end) "
        "local kind_blocked = {} "
        "local kind_dropped = {} "
        "local sent, errs, went, left_over, kinds, went_kind = 0, {}, {}, {}, {}, {} "
        "local far = {} "
        "local sent_teams = {} "
        "local unknown_kind = 0 "
        "local pairs_n = #home if #rallies < pairs_n then pairs_n = #rallies end "
        "local qi = 0 "
        "for i = 1, #rallies do local r = rallies[i] "
        "r.target = target_of[tostring(r.team)] "
        "local kind, known = kind_of(r) "
        "if not known then unknown_kind = unknown_kind + 1 end "
        "kind_seen[kind] = true "
        # The day is spent: every banner is NAMED as passed over for that reason rather
        # than silently skipped, so «nothing went out» never reads as «no rally was out».
        "if capped then left_over[#left_over+1] = tostring(r.team)..':day-capped' "
        # …the base has not got the soldiers the person asked for, and every banner is
        # NAMED as passed over for that reason: a quiet evening and a base being refilled
        # are different sentences (#1317).
        "elseif short_pool then left_over[#left_over+1] = "
        "tostring(r.team)..':low-on-soldiers('..pool..'/'..minpool..')' "
        # …a kind the person has switched off, which is a different sentence again: it is
        # not «today is spent», it is «not this kind at all» (#1317).
        "elseif kind_off[kind] then "
        "kind_dropped[kind] = (kind_dropped[kind] or 0) + 1 "
        "left_over[#left_over+1] = tostring(r.team)..':kind-off('..kind..')' "
        # …and so is a banner whose KIND is spent, with the kind in the word: «нечего
        # слать» and «этого вида на сегодня хватит» are different answers (#1317).
        "elseif kind_left[kind] ~= nil and kind_left[kind] >= 0 and kind_left[kind] <= 0 then "
        "kind_blocked[kind] = (kind_blocked[kind] or 0) + 1 "
        "left_over[#left_over+1] = tostring(r.team)..':kind-capped('..kind..')' "
        "elseif qi >= #home then left_over[#left_over+1] = tostring(r.team)..(#home == 0 and ':no-squad' or ':squads-spent') "
        # TOO FAR TO BE WORTH A SQUAD (#2425). Judged against the squad that would be
        # sent — the next one in the queue — and it does NOT spend it: a banner passed
        # over here leaves the squad for the banner behind it, which is the whole point.
        "else local q = home[qi + 1] local ft = fly_secs(r, q) "
        "if maxfly > 0 and ft >= 0 and ft > maxfly then "
        "far[#far+1] = tostring(r.team)..':'..string.format('%.1f', ft)..'s' "
        "left_over[#left_over+1] = tostring(r.team)..':too-far('"
        "..string.format('%.1f', ft)..'s > '..tostring(maxfly)..'s)' "
        "else qi = qi + 1 "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(q.uuid, 6, r.point, r.team, 1, 1, false, r.server, nil) end) "
        "if ok then sent = sent + 1 keep[tostring(r.team)] = 0 "        # age 0: freshly sent
        # One off the kind's budget, HERE and not in the panel afterwards: two banners of
        # one kind in a single press would otherwise both be measured against the same
        # «one left» (#1317).
        "if kind_left[kind] ~= nil and kind_left[kind] > 0 then "
        "kind_left[kind] = kind_left[kind] - 1 end "
        "tries[tostring(r.team)] = (tonumber(tries[tostring(r.team)] or 0) or 0) + 1 "
        "sent_teams[#sent_teams+1] = tostring(r.team) "
        # …WITH HOW LONG THE FLIGHT WAS PRICED AT (#2425), so the number the door judges
        # can be read back against the server's own arrival time on any banner that went.
        "went[#went+1] = tostring(r.team)..'/s'..tostring(q.slot)"
        "..((ft >= 0) and ('/'..string.format('%.1f', ft)..'s') or '') "
        "kinds[#kinds+1] = kind "
        "went_kind[#went_kind+1] = tostring(r.team)..'='..kind"
        "..((r.level ~= nil) and (' lv'..tostring(r.level)) or '')"
        # …and the type of a row the name table could not name, which is the one thing
        # lost by counting it as the fallback kind rather than as `monster_type_<n>`
        # (#1323). Said here, where a person can read it, instead of in a key nothing
        # can cap.
        "..((r.unnamed ~= nil) and (' type'..tostring(r.unnamed)..' unnamed') or '') "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_all send squad="..tostring(q.slot)'
        '.." team="..tostring(r.team).." point="..tostring(r.point).." server="..tostring(r.server)) '
        "else errs[#errs+1] = tostring(q.slot)..':'..tostring(err) "
        "left_over[#left_over+1] = tostring(r.team)..':refused' end end end end "
        "DataCenter.__lw_rally_joined = keep "
        "DataCenter.__lw_rally_sent = sent "
        "DataCenter.__lw_rally_kinds = table.concat(kinds, ',') "
        # WHERE THIS PASS SENT, so the recipe can take those banners out and go to the
        # next ones when the server answers «Rally participant full» (game key 390857).
        "DataCenter.__lw_rally_sent_teams = table.concat(sent_teams, ',') "
        # WHAT THE RECIPE DOES NEXT, decided here so it costs no reading of its own.
        # `sent` when anything went; `-1` when nothing did and the only thing in the way
        # was an EMPTY squad with a rally standing there for it — the one case the
        # headless send cannot cover, because the client refuses a squad with no soldiers
        # before a byte leaves and only the game's own screen fills one from the base's
        # pool; `0` when there is nothing to be done at all.
        "local empty, under, walled = 0, 0, 0 "
        "for _, s in ipairs(skipped) do "
        "if string.find(s, ':empty', 1, true) then empty = empty + 1 end "
        "if string.find(s, ':not-full(', 1, true) then under = under + 1 end "
        "if string.find(s, ':short-of-troops(', 1, true) then walled = walled + 1 end end "
        "DataCenter.__lw_rally_todo = sent "
        "if sent == 0 and empty > 0 and #rallies > 0 then DataCenter.__lw_rally_todo = -1 end "
        # `-2` and `-3` — «a banner is standing and every squad that could go is under
        # strength» (#1281), told apart because the answer is different. `-2` is a squad
        # the player can top up; `-3` is a base that has not got the soldiers to fill one
        # squad, which is a wall rather than a chore and must never read as an ordinary
        # quiet minute. Both rank BELOW `-1`: `-1` is answered by ASKING the game for the
        # army and trying again, and a run with one unasked squad should try that first —
        # under-strength is only reported when there is nothing left to try.
        "if sent == 0 and empty == 0 and (walled > 0 or under > 0) and #rallies > 0 then "
        "DataCenter.__lw_rally_todo = (walled > 0) and -3 or -2 end "
        # `-4` — the day's ceiling is reached (#1317). It OUTRANKS every other verdict:
        # a squad standing empty on a day the person has already spent is not a reason to
        # fetch an army, and the recipe stops on this before it reaches its `todo < 0`
        # branch. Only ever set when the game answered with a number of its own.
        # `-5` — the base is under the soldier floor the person set (#1317). It ranks
        # above the under-strength verdicts for the same reason `-4` does: nothing about
        # a squad is the news, the BASE is, and fetching an army for a squad that may not
        # be spent anyway is a call spent on a run that is already refused.
        "if short_pool then DataCenter.__lw_rally_todo = -5 end "
        # …and the day's ceiling outranks even that: «сегодня всё» is the more final of
        # the two, and a base that fills up later still has nothing to join today.
        "if capped then DataCenter.__lw_rally_todo = -4 end "
        "local report = 'sent='..sent..' rallies='..#rallies..' free='..#home "
        # The split that makes «rallies=1» readable: of every team on the map, how many
        # are this alliance's and how many we are already standing in. `joinable` is the
        # denominator «not one missed» is measured against; the rest are not chances.
        "report = report..' seen='..seen_n..' ours='..our_n..' already_in='..in_n "
        # …and how many of the candidates the client could not have offered. A run whose
        # every send went to a wire-only banner reads `seen=0 rallies=2` otherwise, which
        # is a pair of numbers that cannot both be true (#1301).
        "if #from_wire > 0 then report = report..' from_wire=['"
        "..table.concat(from_wire, ' ')"
        "..'] (heard on the wire, not yet in the march table the client keeps)' end "
        # THE EVENT'S OWN NUMBER, beside ours. The invasion rations attacks itself
        # (`attackNum`), and our per-day cap is a different thing with a different unit —
        # so both are shown and neither is substituted for the other, and a person
        # reading «nothing was sent» can see whose ceiling it was (#1281).
        "local inv_n = nil "
        "pcall(function() inv_n = DataCenter.ActivityMonsterInvasionDataManager"
        ".monsterInvasionData.attackNum end) "
        "if inv_n ~= nil then report = report..' game_attackNum='..tostring(inv_n) end "
        "if #went > 0 then report = report..' to=['..table.concat(went, ' ')..']' end "
        "if #went_kind > 0 then report = report..' going_for=['..table.concat(went_kind, ' ')..']' end "
        "if kb ~= nil then report = report..' trophies='..tostring(kb)..'/'..tostring(kbmax) "
        "if kbleft ~= nil and tonumber(kbleft) ~= nil and tonumber(kbleft) <= 0 then "
        "report = report..' -- past the trophy threshold: the game pays nothing more today' end end "
        # THE DOOR SAYS SO IN THE RUN'S OWN SENTENCE (#1317), with both numbers: the
        # game's count and the ceiling it was judged against. `cap=0` is «no ceiling» and
        # says nothing at all, exactly as it did before the door existed.
        "if cap > 0 then report = report..' cap='..tostring(kb)..'/'..cap "
        "if capped then report = report..' -- the ceiling for today is reached, so nothing "
        "was sent' end end "
        # …AND THE SOLDIER FLOOR, WITH BOTH NUMBERS AND THE NAME OF THE READING, whether
        # or not it shut anything (#1317). `in_base` is the soldiers standing in the base
        # (`GetPlayerSoldiersTotalNum`, the pool the squad filler draws from) — named
        # here because «казарма» could be read as more than one number, and a door that
        # does not say what it compared cannot be argued with.
        "if minpool > 0 then report = report..' in_base='..pool..'/'..minpool "
        "if short_pool then report = report..' -- fewer soldiers in the base "
        "(GetPlayerSoldiersTotalNum) than the floor set in «Автостяг», so nothing "
        "was sent' "
        "elseif not (pool > 0) then report = report..' (the number of soldiers in the "
        "base could not be read — the floor did not refuse anything)' end end "
        # THE BUDGET THIS RUN WAS ACTUALLY HANDED, for every kind it saw (#1322). `kind:N`
        # is what that kind had left when the press started, `none` is a kind the panel
        # named no ceiling for, and `(the panel handed no per-kind budget at all)` is the
        # sentence that would have told us in one line why nothing was ever capped. Said
        # whether or not anything was held back, because the whole failure was a door that
        # stayed silent while it stood open: `kind_capped=` never appeared, and neither
        # does it on an evening when every kind is well inside its allowance.
        "local kbud = {} "
        "for k in pairs(kind_seen) do local v = kind_left0[k] "
        "kbud[#kbud+1] = k..':'..((v == nil) and 'none' or tostring(v)) end "
        "table.sort(kbud) "
        "if #kbud > 0 then report = report..' kind_budget=['..table.concat(kbud, ' ')..']' "
        "if kind_n == 0 then report = report..' (the panel handed no per-kind budget at all)' end end "
        # …and which KINDS held a banner back, with how many each (#1317). Said even when
        # something else went out, because «two of the four were the wrong kind today» is
        # exactly the sentence a person needs to change a number with.
        "local kb_parts = {} "
        "for k, n in pairs(kind_blocked) do kb_parts[#kb_parts+1] = k..'x'..n end "
        "table.sort(kb_parts) "
        "if #kb_parts > 0 then report = report..' kind_capped=['..table.concat(kb_parts, ' ')"
        "..'] (this kind has had its allowance for today)' end "
        # …and the kinds that were passed over because nobody wants them. Named the same
        # way and kept apart from the budget, so «я это выключил» never reads as «на
        # сегодня хватит» (#1317).
        "local ko_parts = {} "
        "for k, n in pairs(kind_dropped) do ko_parts[#ko_parts+1] = k..'x'..n end "
        "table.sort(ko_parts) "
        "if #ko_parts > 0 then report = report..' kind_off=['..table.concat(ko_parts, ' ')"
        "..'] (this kind is switched off in «Автостяг»)' end "
        # WHAT COULD NOT BE NAMED, AND WHY — and the «why» is the whole of #1323. The
        # sentence here used to blame the event list, which is one of three reasons and
        # not the common one: a banner's KIND is `targetContentId`, that field is on the
        # push and in no reading the client keeps (docs/research/rally-join.md), and the
        # panel parks it per banner. A profile whose targets arrive empty therefore
        # classifies every banner as the fallback `monster`, spends one bucket's budget
        # all day and leaves every kind the person actually capped at zero — which reads
        # in the log exactly like an evening of ordinary monsters. So the count of parked
        # targets is said beside the count of banners nothing could name.
        "if unknown_kind > 0 then report = report..' unclassified='..unknown_kind "
        "if tgt_n == 0 then report = report..' (no banner targets were parked at all, so "
        "the kind of every banner fell back to \"monster\" — a per-kind budget cannot "
        "bite here, whatever the panel handed over)' "
        "else report = report..' (no target for this banner, or the event lists could "
        "not be read — counted as \"monster\", said rather than assumed)' end end "
        # …AND THE BANNERS THAT WERE TOO FAR TO BE WORTH A SQUAD, WITH THEIR PRICE (#2425).
        # Named whether or not anything else went out, because «стягов не было» and «до
        # них было далеко лететь» are different evenings and the number is the one thing
        # that makes the threshold choosable.
        "if #far > 0 then report = report..' too_far=['..table.concat(far, ' ')"
        "..'] (over the flight ceiling of '..tostring(maxfly)..'s set in «Автостяг»)' end "
        "if #arrived > 0 then report = report..' arrived=['..table.concat(arrived, ' ')..']' end "
        "if #full > 0 then report = report..' no_seat=['..table.concat(full, ' ')..']' end "
        "if #left_over > 0 then report = report..' passed=['..table.concat(left_over, ' ')..']' end "
        "if #skipped > 0 then report = report..' left=['..table.concat(skipped, ' ')..']' end "
        "if #unchecked > 0 then report = report..' ceiling-unknown=['..table.concat(unchecked, ' ')"
        "..'] (the game has not filled in how many soldiers fit — sent without the full-squad check)' end "
        "if #errs > 0 then report = report..' refused=['..table.concat(errs, ' ')..']' end "
        "if #rallies == 0 then report = report..' -- no rally of this alliance is out that we are not already in' "
        "elseif #home == 0 then report = report..' -- not one of the chosen squads can be sent' "
        "elseif sent < #rallies then report = report..' -- more rallies than squads to spend' end "
        "DataCenter.__lw_rally_report = report "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_all "..report)'
    )


# --------------------------------------------------------------------------
# Alliance rally: JOIN one THROUGH THE GAME'S OWN SCREENS
# --------------------------------------------------------------------------
# The direct send does not work and it is not for want of trying: the message the bot
# builds matches the player's argument for argument (docs/research/rally-join.md), and
# the server still creates no march — until #1238 found that both were being aimed at the
# monster instead of the tile the joiners gather on. `rally_join_send` is the join with no
# screen at all; what is below it is the FALLBACK, and it earns its keep by filling a
# squad that has no soldiers in it. It walks the windows the way `create_rally.md` drives
# the raise, waiting for STATES rather than sleeping:
#
#     OnClickStartMarch -> UIFormationSelectListV2 -> pick the squad -> OnCheckTime
#
# Read off a trace of a HAND-MADE join: `OnClickStartMarch(6, point, team, -1, 1, 7,
# server, 0, 10)` is what opens that screen — note the `10`, which the old fire-and-
# forget warm-up passed as `0` — and the screen is the SAME one the create side already
# picks a squad on, so the last two steps are the create side's, spelled for the join.
#
# THE SCREEN IS NOT CLOSED BY ANY OF THIS. The old press opened it and shut it again in
# the same breath, which is why the send that followed had nothing behind it — the same
# lesson #1172 paid for on the create side: the popup a button lives on must stay up
# until the button has been pressed. The screen closes itself when the launch succeeds.
_RALLY_JOIN_PARAMS = "local p = DataCenter.__lw_rally_join or {} "


def rally_join_arm() -> str:
    """Pick the rally to join and the squad to send, and park both. Presses nothing.

    First rally the account is not already in; of the sieved squads, **the first one that
    can actually be sent** — that is, one with soldiers in it. The sieve upstream only
    asks whether a squad is at home and idle, and a squad can be both of those and still
    be empty; taking it anyway is what sends an otherwise headless join through the
    windows, because an empty squad is the one case the send cannot cover (#1238).

    Falls back to the first sieved squad when none has soldiers — then the screen path
    below fills it, which is what the screen is for. So the choice never REFUSES a join,
    it only prefers the one that needs nothing opened.

    Parked because `TAP` carries no arguments and every step below reads it back.
    """
    return (
        _RALLY_PRELUDE_MINE +
        "local r = rallies[1] "
        "local afd = DataCenter.ArmyFormationDataManager "
        # index -> formation uuid + how many soldiers are standing in it, read once
        "local uuid_of, soldiers_of = {}, {} "
        "for _, v in pairs(afd.ArmyFormationList) do "
        "local ok, idx = pcall(function() return v.index end) "
        "if ok and idx ~= nil then local key = tostring(idx) "
        "pcall(function() uuid_of[key] = v.uuid end) "
        "local n = 0 pcall(function() n = tonumber(v.totalSoldierNum) or 0 end) "
        "soldiers_of[key] = n end end "
        "local slot = nil "
        "for _, s in ipairs(squads) do "
        "if slot == nil and (soldiers_of[tostring(s)] or 0) > 0 then slot = s end end "
        "if slot == nil then slot = squads[1] end "
        "if slot == nil or r == nil then DataCenter.__lw_rally_join = nil "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_arm none squads="..#squads'
        '.." rallies="..#rallies) return end '
        "local fu = uuid_of[tostring(slot)] "
        "if fu == nil then DataCenter.__lw_rally_join = nil "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_arm noformation squad="..tostring(slot)) '
        "return end "
        "DataCenter.__lw_rally_join = {squad = slot, formation = fu, point = r.point, "
        "team = r.team, server = r.server} "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_arm squad="..tostring(slot)'
        '.." soldiers="..tostring(soldiers_of[tostring(slot)])'
        '.." team="..tostring(r.team).." point="..tostring(r.point))'
    )


def rally_join_armed() -> str:
    """Lua *expression* -> 1 when there is a rally to join and a squad to join it with."""
    return ("(function() local p = DataCenter.__lw_rally_join "
            "if p == nil or p.formation == nil then return 0 end return 1 end)()")


def rally_join_soldiers() -> str:
    """Lua *expression* -> soldiers standing in the armed squad, or -1 if unreadable.

    The one thing the squad screen does that the send cannot do for itself: a squad with
    heroes and NO soldiers is refused by the client before a byte leaves — the send's own
    constants are `hasSolider` and `GameDialogDefine.ADD_SOLDIER`, and what the player is
    shown is the «add soldiers» tip rather than an error.

    Nothing here can put soldiers in an empty squad, so a run that reads 0 has nothing to
    send with: either the screen fills the squad from the base's pool, or — when the pool
    is empty too, which is what an evening of rallies leaves behind — the answer is the
    hospital and not this ability.
    """
    return ("(function() local p = DataCenter.__lw_rally_join "
            "if p == nil or p.formation == nil then return -1 end "
            "local afd = DataCenter.ArmyFormationDataManager local n = -1 "
            "for _, f in pairs(afd.ArmyFormationList) do "
            "local ok, u = pcall(function() return f.uuid end) "
            "if ok and tostring(u) == tostring(p.formation) then "
            "pcall(function() n = tonumber(f.totalSoldierNum) or -1 end) end end "
            "return n end)()")


def rally_join_send() -> str:
    """Join the armed rally with NO screen: build the march message and send it.

    This is the same call the game itself ends up making — the squad screen's launch
    walks `OnCheckTime` -> `OnCreateClick` -> `TryStartMarch` -> this — and its Lua reads
    nothing off any window: the payload comes from `GetFormationStartPos` and
    `ArmyFormationDataManager:GetOneArmyInfoByUuid`, i.e. from the squad itself.

    What made the direct send look impossible for weeks was the END POINT, not the path:
    it was aimed at the monster the rally is going to attack instead of the tile the
    joiners gather on (#1237, and `joinpoint` in `_RALLY_PRELUDE`). Every other
    explanation chased — the thirteenth argument, the hero arrays, the message body —
    sat downstream of that.

    Called straight, not through `TimerManager:DelayInvoke` as the old press was: the
    screen's own launch runs synchronously from this same daemon thread and works, and a
    send hidden behind a timer cannot say whether it threw — which is half of what a run
    needs to know when nothing appears on the map.
    """
    return (
        _RALLY_JOIN_PARAMS +
        "if p.formation == nil then error('no rally armed for this run') end "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(p.formation, 6, p.point, p.team, 1, 1, false, "
        "p.server, nil) end) "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_send squad="..tostring(p.squad)'
        '.." team="..tostring(p.team).." point="..tostring(p.point)'
        '.." server="..tostring(p.server).." ok="..tostring(ok).." err="..tostring(err))'
    )


def rally_join_in() -> str:
    """Lua *expression* -> 1 when one of our marches is already standing in the armed rally.

    Asked between the screenless send and the fallback that opens the screens, because a
    send that landed a moment late must not cost a SECOND squad: the ability spends one
    squad per rally and the whole point of the fallback is the case where nothing was
    spent at all.
    """
    return (
        "(function() local p = DataCenter.__lw_rally_join if p == nil then return 0 end "
        "local P = LuaEntry.Player local wm = DataCenter.WorldMarchDataManager "
        "local col = wm:GetAllMarches() if col == nil then return 0 end "
        "local e = col:GetEnumerator() while e:MoveNext() do local mo = e.Current "
        "local ok, v = pcall(function() return mo.Value end) if ok and v ~= nil then mo = v end "
        "local t, u = nil, nil pcall(function() t = mo.teamUuid u = mo.ownerUid end) "
        "if t ~= nil and tostring(t) == tostring(p.team) "
        "and tostring(u) == tostring(P.uid) then return 1 end end "
        "return 0 end)()")


def squads_fill_empty() -> str:
    """Ask the server for the army of every parked squad the client shows as empty.

    THE EMPTY SQUAD WAS NEVER EMPTY — the client simply had not asked (#1285). A squad
    reads `totalSoldierNum = 0` with `soldiers = {}` in a session where nothing has
    needed the number yet, and everything downstream treats that as «no army»: the send
    refuses it before a byte leaves (`hasSolider`, `GameDialogDefine.ADD_SOLDIER`), the
    join sieve reports it as `empty`, and the run ends having spent nothing.

    One message fixes it and no window is opened::

        SFSNetwork.SendMessage(MsgDefines.GetFormationSoldier, formationUuid)
                               -- «formation.get.soldier»

    Measured live on a client whose three squads all read 0 while the base held
    thousands of soldiers: **0 -> a full squad in 0.37 s**, that time including the two
    VM round trips around it. The reply lands in `RefreshFormationSoldier`, which fills
    `formation.soldiers` (posIndex -> {soldierId = count, supply}) and the total the
    gates read. So this is a FETCH, not a recruitment: it makes the client agree with
    the server about an army the server already had.

    None of the client's own fillers can do it. `AutoInitFormationData`,
    `AutoAddSoldierByForm`, `AutoAddSoldier` (both `useForm`) and `FetchFormationSoldier`
    were each pressed on a live empty squad and each returned cleanly having changed
    nothing (0 -> 0). They all draw on `ArmyManager:GetArmyFreeList()`, which walks
    `ArmyManager.allArmy` — and that table is EMPTY on a client that has not been sent
    `army.info`. Asking for `army.info` by hand does not fill it either.

    A SQUAD THAT IS STILL 0 AFTER THIS IS GENUINELY EMPTY, and that is the reading the
    caller wants: `squads_filled_count()` counts the ones that came back with an army,
    and a run that asked and got nothing may say «the squad is empty» and mean it.

    Which squads it asks for is parked in `DataCenter.__lw_fill_squads` (the slots the
    player sees, 1/2/3/4); with nothing parked it asks for every squad the game knows.
    `TAP` carries no arguments of its own, which is why it is parked rather than passed.
    """
    return (
        "local afd = DataCenter.ArmyFormationDataManager "
        "local want = nil local list = DataCenter.__lw_fill_squads "
        "if type(list) == 'table' and #list > 0 then want = {} "
        "for _, s in ipairs(list) do want[tostring(s)] = true end end "
        "local asked, held, names, refused = 0, 0, {}, {} "
        "for _, f in pairs(afd.ArmyFormationList) do "
        "local idx, uuid, num = nil, nil, 0 "
        "pcall(function() idx = f.index uuid = f.uuid "
        "num = tonumber(f.totalSoldierNum) or 0 end) "
        "if idx ~= nil and (want == nil or want[tostring(idx)]) then "
        "if num > 0 then held = held + 1 else "
        "local ok, err = pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.GetFormationSoldier, uuid) end) "
        "if ok then asked = asked + 1 names[#names + 1] = tostring(idx) "
        "else refused[#refused + 1] = tostring(idx) .. ':' .. tostring(err) end "
        "end end end "
        "DataCenter.__lw_fill_asked = asked "
        "DataCenter.__lw_fill_wanted = names "
        "DataCenter.__lw_fill_report = 'asked=' .. tostring(asked) "
        ".. ' already-loaded=' .. tostring(held) "
        ".. ((#names > 0) and (' squads=[' .. table.concat(names, ' ') .. ']') or '') "
        ".. ((#refused > 0) and (' refused=[' .. table.concat(refused, ' ') .. ']') or '') "
        'CS.UnityEngine.Debug.LogError("ACT squads_fill_empty "'
        "..DataCenter.__lw_fill_report)"
    )


def squads_filled_count() -> str:
    """Lua *expression* -> how many of the squads just asked for now hold an army.

    Counted over `DataCenter.__lw_fill_wanted` — the slots `squads_fill_empty` actually
    sent a request for — so a squad that was already loaded is not counted as a success
    this press did not earn, and a squad the server answered for with nothing stays at
    zero and is the honest «this one really is empty».

    **-1 means nothing was asked for** — every chosen squad already held its army, or the
    press did not run. A third answer rather than a zero, because the recipe polls on
    `filled == 0` and a run with nothing to wait for must not spend the poll: this is
    CALLed from `join_rally.md` with a banner standing on the map.

    NOT ONE BRACE IN IT, and that is a constraint rather than a style: `actions/
    fill_empty_squads.md` inlines this same text in a `READ_LUA`, and the DSL reads `{…}`
    inside a line as one of the run's own arguments. A Lua table constructor in a recipe
    is an argument the recipe never declared, so the set-of-wanted-slots this would
    naturally be written with is a nested loop instead — over at most four squads.
    """
    return (
        "(function() local names = DataCenter.__lw_fill_wanted "
        "if type(names) ~= 'table' or #names == 0 then return -1 end "
        "local afd = DataCenter.ArmyFormationDataManager local n = 0 "
        "for _, f in pairs(afd.ArmyFormationList) do "
        "local idx, num = nil, 0 "
        "pcall(function() idx = f.index num = tonumber(f.totalSoldierNum) or 0 end) "
        "if idx ~= nil and num > 0 then "
        "for _, s in ipairs(names) do "
        "if tostring(s) == tostring(idx) then n = n + 1 end end end end "
        "return n end)()"
    )


def join_next_rally() -> str:
    """Send the next parked squad to the next rally it is not already in.

    One press per chunk: the squad is dropped from the queue and the rally marked
    as taken BEFORE the send, so a refused join costs one squad rather than wedging
    `xall` on the same rally forever.

    Superseded by `rally_join_send` + the fallback in `actions/join_rally.md`, which
    ask the map whether the send achieved anything instead of assuming it did. Kept
    because `tools/rally_join.py` drives the same shape from a shell, and corrected
    to `joinpoint` with it: this one spent months aiming at the monster.
    """
    return (
        _RALLY_PRELUDE +
        "local slot=squads[1] local r=rallies[1] "
        "if slot==nil or r==nil then "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_skip squads="..#squads.." rallies="..#rallies) '
        "return end "
        "local formation=nil local warm=false "
        "local afd=DataCenter.ArmyFormationDataManager "
        "for _,v in pairs(afd.ArmyFormationList) do "
        "local ok,idx=pcall(function() return v.index end) "
        "if ok and tostring(idx)==tostring(slot) then pcall(function() formation=v.uuid end) end "
        "local ok2,n=pcall(function() return v.totalSoldierNum end) "
        "if ok2 and (n or 0)>0 then warm=true end end "
        "table.remove(squads,1) DataCenter.__lw_rally_squads=squads "
        "if formation==nil then "
        'CS.UnityEngine.Debug.LogError("ACT rally_join_skip no formation for squad "..tostring(slot)) '
        "return end "
        "local taken2=DataCenter.__lw_rally_joined or {} taken2[tostring(r.team)]=true "
        "DataCenter.__lw_rally_joined=taken2 "
        # Where the JOINER goes — the leader's own tile — and not where the rally is
        # going. See `joinpoint` in `_RALLY_PRELUDE`.
        "local jp = r.joinpoint or r.point "
        "if not warm then "
        "pcall(function() MarchUtil.OnClickStartMarch(6,jp,r.team,-1,1,7,r.server,0,0) end) "
        "pcall(function() GoToUtil.CloseAllWindows() end) end "
        "TimerManager:GetInstance():DelayInvoke(function() pcall(function() "
        "MarchUtil.SendCreateMarchMessage(formation,6,jp,r.team,1,1,false,r.server,nil) "
        "end) end,0.5) "
        'CS.UnityEngine.Debug.LogError("ACT rally_join squad="..tostring(slot)'
        '.." team="..tostring(r.team).." point="..tostring(jp)'
        '.." server="..tostring(r.server).." warmed="..tostring(not warm))'
    )


# --------------------------------------------------------------------------
# Alliance rally: RAISE one («Стягивание»)
# --------------------------------------------------------------------------
# The CREATE side — the other half of the join above. `tools/rally_create.py`
# drives it from Python and `docs/research/rally-create.md` is the write-up; these
# are the same four presses as pressable buttons, so a recipe (and therefore the
# Scenarios tab and a timer) can raise a banner.
#
# It is a FLOW, not a single send, and each press needs the window the previous one
# opened to actually be there:
#
#     «лупа» (UISearch) -> the target's popup (UIWorldPoint)
#         -> the squad screen (UIFormationSelectListV2 / …New) -> launch
#
# So the presses stay four separate buttons with the polls between them written in
# the recipe (`WHILE` + `WAIT` + `READ_LUA`), never a Lua loop waiting on the server
# inside one chunk — that is the client freeze docs/dsl.md warns about.
#
# WHAT to rally is parked first, the same trick the join side uses for its squads:
# `TAP` carries no arguments, so `actions/create_rally.md` writes the run's target
# into `DataCenter.__lw_rally_create` and every press below reads it back.
#
#     DataCenter.__lw_rally_create = {
#         squad     = 1,          -- the slot the player sees (1/2/3/4)
#         level     = 35,         -- 1..200, clamped by the search press
#         kind      = "boss",     -- "boss" = Роковая Элита, "monster" = field monster
#         formation = <uuid>,     -- the squad's formation, resolved when parked
#     }
#
# `formation` is resolved at park time, BEFORE anything is opened, so a squad that
# does not exist stops the recipe instead of leaving a monster popup hanging open on
# the map (the same order rally_create.create_on_level keeps).

# The parked run, and the «лупа» tab its kind maps to. The tab numbers are the
# UISearchType enum read live: 5 = Boss (the Fatal Elite, `find.monster.boss`),
# 1 = Monster (ordinary field monsters, `find.monster`) — docs/research/rally-elite-search.md.
_RALLY_CREATE_PARAMS = "local p = DataCenter.__lw_rally_create or {} "
_RALLY_SEARCH_TAB = "local st = 5 if tostring(p.kind) == 'monster' then st = 1 end "

# The two windows the squad screen can be, depending on the `formation_v2_switch` config.
_FORMATION_WIN = (
    "local function _isformation(w) return w ~= nil and "
    "(w.Name == 'UIFormationSelectListV2' or w.Name == 'UIFormationSelectListNew') end "
)


def rally_create_arm() -> str:
    """Finish the parked run: resolve the squad's formation and note the rally count.

    The recipe parks the three plain values it was given (`squad`, `level`, `kind`);
    this fills in the two the game has to be asked for, BEFORE anything is opened:

    * `formation` — the uuid of the squad slot the player sees. Formations live in
      `ArmyFormationDataManager.ArmyFormationList` keyed by uuid, each carrying an
      `index` = that slot number, and the formation uuid is the first argument of the
      send the launch button eventually makes. A slot with no formation leaves this
      nil, which is the recipe's cue to stop before a target popup is left hanging
      open on the map.
    * `before` — how many rallies of ours are already out, so the raise can be
      *measured* afterwards rather than assumed from a press that returned cleanly.
    """
    return (
        "local p = DataCenter.__lw_rally_create or {} "
        "local afd = DataCenter.ArmyFormationDataManager "
        "for _, v in pairs(afd.ArmyFormationList) do "
        "local ok, idx = pcall(function() return v.index end) "
        "if ok and tostring(idx) == tostring(p.squad) then "
        "pcall(function() p.formation = v.uuid end) end end "
        "p.before = %s "
        "DataCenter.__lw_rally_create = p "
        'CS.UnityEngine.Debug.LogError("ACT rally_arm squad="..tostring(p.squad)'
        '.." level="..tostring(p.level).." kind="..tostring(p.kind)'
        '.." formation="..tostring(p.formation).." rallies="..tostring(p.before))'
        % own_rally_count()
    )


def rally_armed() -> str:
    """Lua *expression* -> 1 when the parked run has a squad the game knows."""
    return ("(((DataCenter.__lw_rally_create or {}).formation ~= nil) and 1 or 0)")


def rally_raised() -> str:
    """Lua *expression* -> rallies of ours gained since `rally_create_arm()` ran.

    1 once the banner is standing. Reading the DIFFERENCE rather than the count is
    what makes this work with rallies already out — a player leading one elsewhere
    starts from a non-zero count.
    """
    return "(%s - ((DataCenter.__lw_rally_create or {}).before or 0))" % own_rally_count()


def rally_search_open() -> str:
    """Open the world-map search («лупа») — the window the level is typed into."""
    return "UIManager.Instance:OpenWindow(UIWindowNames.UISearch)"


def rally_search_fire() -> str:
    """Set the parked level on the parked tab and press the magnifier.

    `OnSearchClick(type, subType)` reads the level back through
    `GetCurNumBySearchType` and fires the server request; subType 0 is the default
    sub-tab (a nil one trips the game's own recorder). The answer is not waited for
    here — the server flies the camera in and opens the target's popup by itself
    (`OnSearchEnd` -> `GoToUtil.MoveToWorldMarchAndOpen`), which the recipe polls for.

    The level is clamped to 1..200, the range both tabs accept; a level the server
    has nothing for simply comes back empty, like any other miss.
    """
    return (
        _RALLY_CREATE_PARAMS + _RALLY_SEARCH_TAB +
        "local lvl = tonumber(p.level) or 1 "
        "if lvl < 1 then lvl = 1 end if lvl > 200 then lvl = 200 end "
        "local w = UIManager.Instance:GetStackTopWindow() "
        "if not w or w.Name ~= 'UISearch' then "
        "error('the search window is not open (top is '..tostring(w and w.Name)..')') end "
        "w.Ctrl:SetCurNumBySearchType(st, lvl, 0) "
        "w.Ctrl:OnSearchClick(st, 0) "
        'CS.UnityEngine.Debug.LogError("ACT rally_search level="..lvl.." type="..st)'
    )


def rally_target_state() -> str:
    """Lua *expression* -> what the search brought up: 1 ralliable, -1 not, 0 nothing yet.

    The reliable test is the popup's own action button, not `canAttack`: a rally
    target carries exactly one and it names itself `RallyBoss`, while a soloable
    monster names itself `AttackMonster` and nothing turns that into a rally.

    `0` also covers "the window is up but its monster data has not landed yet" — the
    data arrives a beat after the window — so the recipe polls this until it moves.
    """
    return (
        "(function() local w = UIManager.Instance:GetStackTopWindow() "
        "if not w or w.Name ~= 'UIWorldPoint' then return 0 end "
        "local c = w.Ctrl local lvl = nil "
        "pcall(function() lvl = c:GetMonsterData(c.uuid).level end) "
        "if lvl == nil then return 0 end "
        "local b = '?' pcall(function() b = tostring(c:GetPointBtnEnumName(w.View.btnList[1])) end) "
        "if b == 'RallyBoss' then return 1 end return -1 end)()"
    )


def rally_banner_press() -> str:
    """Press «Стягивание» on the open target popup.

    Exactly the two arguments the button's own handler passes —
    `OnClickStartMarch(RALLY_FOR_BOSS, pointId, uuid)` — and the game fills the rest
    (server, wait time, auto-return) in on the squad screen it opens. THE POPUP MUST
    STILL BE ON TOP: closing it first is what made the target "hide" with nothing
    pressed.
    """
    return (
        "local w = UIManager.Instance:GetStackTopWindow() "
        "if not w or w.Name ~= 'UIWorldPoint' then "
        "error('the target popup is not open (top is '..tostring(w and w.Name)..')') end "
        "MarchUtil.OnClickStartMarch(MarchTargetType.RALLY_FOR_BOSS, w.Ctrl.pointId, w.Ctrl.uuid) "
        'CS.UnityEngine.Debug.LogError("ACT rally_banner point="..tostring(w.Ctrl.pointId)'
        '.." uuid="..tostring(w.Ctrl.uuid))'
    )


def rally_panel_ready() -> str:
    """Lua *expression* -> 1 once the squad screen the rally press opens is on top."""
    return ("(function() " + _FORMATION_WIN +
            "if _isformation(UIManager.Instance:GetStackTopWindow()) then return 1 end "
            "return 0 end)()")


def rally_squad_pick() -> str:
    """Pick the parked squad on the open squad screen.

    `View:OnSelectClick` is the tap (it repaints the cells and the cost),
    `Ctrl:SetSelectFormationUuid` is what the tap ultimately records; both are done
    so the screen and the send agree. Nothing is sent here — the launch is a press of
    its own, and the recipe only makes it once the pick has been read back.
    """
    return (
        _FORMATION_WIN + _RALLY_CREATE_PARAMS +
        "local w = UIManager.Instance:GetStackTopWindow() "
        "if not _isformation(w) then "
        "error('the squad screen is not open (top is '..tostring(w and w.Name)..')') end "
        "if p.formation == nil then error('no squad parked for this run') end "
        "pcall(function() w.View:OnSelectClick(p.formation) end) "
        "w.Ctrl:SetSelectFormationUuid(p.formation) "
        'CS.UnityEngine.Debug.LogError("ACT rally_squad sel="..tostring(w.Ctrl.selectFormationUuid))'
    )


def rally_squad_picked() -> str:
    """Lua *expression* -> 1 when the open squad screen really holds the parked squad."""
    return (
        "(function() " + _FORMATION_WIN + _RALLY_CREATE_PARAMS +
        "local w = UIManager.Instance:GetStackTopWindow() "
        "if not _isformation(w) then return 0 end "
        "if p.formation ~= nil and tostring(w.Ctrl.selectFormationUuid) == tostring(p.formation) "
        "then return 1 end return 0 end)()"
    )


def rally_launch() -> str:
    """Press the squad screen's launch button.

    `Ctrl:OnCheckTime(formationUuid, destroyTimeIndex)` is what its View calls: the
    game's own pre-checks (rally cap, wait-time and transport warnings) and then
    `OnCreateClick` -> `SendCreateMarchMessage`. The screen closes itself on success.
    """
    return (
        _FORMATION_WIN + _RALLY_CREATE_PARAMS +
        "local w = UIManager.Instance:GetStackTopWindow() "
        "if not _isformation(w) then "
        "error('the squad screen is not open (top is '..tostring(w and w.Name)..')') end "
        "w.Ctrl:OnCheckTime(p.formation, nil) "
        'CS.UnityEngine.Debug.LogError("ACT rally_launch formation="..tostring(p.formation))'
    )


def own_rally_count() -> str:
    """Lua *expression* -> how many of the player's own marches are part of a rally.

    A raised banner adds one. That increase is the only thing that proves a rally
    went out: a plain march count moves for unrelated reasons, and
    `IsHaveMarchInWorld()` is already true whenever anything at all is out.
    """
    return (
        "(function() local wm = DataCenter.WorldMarchDataManager "
        "local om = wm:GetOwnerMarches() local n = 0 "
        "if om then local e = om:GetEnumerator() while e:MoveNext() do "
        "local mo = e.Current.Value if mo == nil then mo = e.Current end "
        "local ok, t = pcall(function() return mo.teamUuid end) "
        "if ok and t ~= nil and tostring(t) ~= '0' and tostring(t) ~= 'nil' then n = n + 1 end "
        "end end return n end)()"
    )


# --------------------------------------------------------------------------
# The resource truck standing on the base ("Сбор ресурсов с грузовика")
# --------------------------------------------------------------------------
# Recording `20260730_130004_Сбор_ресурсов_с_грузовика` — the player tapped the
# truck parked on the base, pressed "collect", then closed the congratulation
# modal. The whole flow is ONE command sent three times with a different
# `action`, and the trace (filter=SFS, dedup=false) spells it out:
#
#     SFSNetwork.SendMessage <- lw.pve.idle.reward, 0     -- tap: read what is banked
#       -> SFSObject.PutInt(action, 0)
#     SFSNetwork.SendMessage <- lw.pve.idle.reward, 1     -- "collect": take it
#       -> push.resource.item.update                      -- the resources land
#     SFSNetwork.SendMessage <- lw.pve.idle.reward, 0     -- modal closed: re-read
#
# So the payload is a single int (`{"action":N}` on the wire) and there is no
# uuid, no world position and no bubble to hunt for — `action=1` *is* the
# collect, headless, with nothing open. The captured reply to `action=1` carries
# the whole banked pile in one go (`reward:[{type:1,…},{type:20,…},{type:31,…},
# {type:27,…}]` plus the `dominator*` bonus lists and a fresh
# `lastIdleRewardTimeStamp`), which is why this is a single press and not `xall`:
# one claim empties the accumulator.
#
# Note this is NOT the `BuildBubbleType.TruckReward` bubble press behind the
# older `collect_trucks` button. That one was derived from a *deduped* trace
# (`20260728_171442`, `dedup=True`), so it never showed a wire command at all;
# this recording is the first one that does, and the command it shows is the
# base's idle-reward accumulator.
#
# There is no readiness gate here yet: the client-side counter that says how much
# is banked is only known from the `action=0` reply, which a single Lua chunk
# cannot read back. A claim on an empty accumulator therefore costs one refused
# call (the server's own tip), the same shape as the hospital collect press.

_TRUCK_REWARD_MSG = "lw.pve.idle.reward"


def truck_reward_refresh() -> str:
    """Ask the server what the base's resource truck is currently holding.

    `lw.pve.idle.reward` with `action=0` — the read the client fires both when the
    truck is tapped and again after the reward modal is closed. Sends nothing else
    and changes nothing; it just makes the client's own numbers current.
    """
    return (
        "local ok,err = pcall(function() "
        "SFSNetwork.SendMessage('%s', 0) "
        'CS.UnityEngine.Debug.LogError("ACT truck_reward_refresh sent") '
        "end) "
        'if not ok then CS.UnityEngine.Debug.LogError("ACT truck_reward_refresh skip: "..tostring(err)) end'
        % _TRUCK_REWARD_MSG
    )


def truck_reward_collect() -> str:
    """Collect the resource truck parked on the base — the "collect" press itself.

    `lw.pve.idle.reward` with `action=1`, exactly what the recorded press sent. One
    call takes everything the accumulator holds (base resources plus the bonus
    lists), so pressing it twice in a row has nothing left to take — do not loop it.
    Nothing needs to be open: no window, no bubble, no camera position.
    """
    return (
        "local ok,err = pcall(function() "
        "SFSNetwork.SendMessage('%s', 1) "
        'CS.UnityEngine.Debug.LogError("ACT truck_reward_collect sent") '
        "end) "
        'if not ok then CS.UnityEngine.Debug.LogError("ACT truck_reward_collect skip: "..tostring(err)) end'
        % _TRUCK_REWARD_MSG
    )


def base_collect_ready_count() -> str:
    """Lua *expression* -> how many base buildings have something banked to collect.

    THE SAME PREDICATE THE PRESS USES, deliberately: `collect_base_resources` sweeps
    every production line whose `GetBuildingCurrStorage(uuid)` is at least 1, because
    that is precisely what the server accepts (below 1 it answers 602026 «still in
    production» and the client pops a toast per building — task #1087). Counting by
    any other rule would give a checklist that says «4 ready» where the press finds
    none, and the two would drift apart the first time either changed.

    A read: it collects nothing and sends nothing.
    """
    return ("(function() local plm=DataCenter.ProductLineManager local n=0 "
            "for _,u in pairs(plm:GetAllBuildUuids() or {}) do "
            "local ok,stor=pcall(function() return plm:GetBuildingCurrStorage(u) end) "
            "if ok and (stor or 0)>=1 then n=n+1 end end return n end)()")


def trucks_ready_count() -> str:
    """Lua *expression* -> how many supply trucks have arrived and are waiting.

    The bubbles `collect_trucks` taps, counted rather than pressed:
    `BuildBubbleType.TruckReward` / `TruckReady`. A truck still on the road wears
    `TruckTravelling` and is not counted — it is not work the person can do yet.
    """
    return ("(function() local m=DataCenter.BuildBubbleManager local BT=_G.BuildBubbleType "
            "if not m or not BT then return 0 end local n=0 "
            "for _,v in pairs(m.allBuildBubble or {}) do "
            "local ty=v.param and v.param.buildBubbleType "
            "if ty==BT.TruckReward or ty==BT.TruckReady then n=n+1 end end "
            "return n end)()")


# --------------------------------------------------------------------------
# Sending trade trucks out ("Отправка грузовиков")
# --------------------------------------------------------------------------
# A DIFFERENT truck from the two above. `trucks_ready_count` counts the supply
# trucks that have ARRIVED at the base and `truck_reward_*` empties the idle
# accumulator parked on it; these three read the TRADE STATION — the fleet the
# player dispatches to another server and other players rob on the way
# (`UILWTruckSuperDeparture`, docs/research/ui-open.md).
#
# `DataCenter.LWMyStationDataManager` owns all of it, and the three numbers a
# person actually wants are already computed there rather than derivable from the
# fleet list (read live, #1249):
#
#   GetDepartureCount()      how many went out today
#   GetMaxDailyCount()       today's allowance — the BASE four plus whatever the
#                            «Extra Truck» tech adds, so never a constant
#   GetRealReadyCount()      how many could go out RIGHT NOW: trucks standing at
#                            the station in `TruckStationState.Ready`, capped by
#                            what is left of the allowance
#
# Every one of them is nil-guarded on `IsTruckFunctionLock()` FIRST, and that
# guard is the whole point: the trade station is locked until the base reaches
# level 8, and a locked client still answers `GetDepartureCount() == 0`. Drawn
# straight, that reads as «nothing sent yet today» on an account that cannot send
# anything at all — a to-do the person can never tick off. Returning nil instead
# makes the reading say `-`, which the checklist draws as «state unknown»
# (`panel/tabs/checklist/model.py`: a feature this account has not unlocked is
# exactly one of the things a dash is for).
#
# There is NO press here yet. Dispatching is `train.send` / `train.batch.send`
# with an escorting squad per truck and a rarity refresh in front of it; until
# that is a scenario, the panel reads these and offers no button (#1249).
#
# Every call is wrapped in its own parentheses before `tonumber`: these three
# return TWO values, and `tonumber(a, b)` reads the second as a base, which fails
# with «string expected, got number» rather than with a wrong count.

_TRUCK_STATION = ("local M=DataCenter and DataCenter.LWMyStationDataManager "
                  "if not M or M:IsTruckFunctionLock() then return nil end ")


def truck_dispatch_left() -> str:
    """Lua *expression* -> trade-truck dispatches still banked today, or nil.

    The quota's remaining half, the same shape every other daily allowance on the
    board is read in (`secret_task_steals_left`): allowance minus what has gone,
    floored at zero so a cap that shrinks mid-day cannot show a negative.
    """
    return ("(function() " + _TRUCK_STATION +
            "local cap=tonumber((M:GetMaxDailyCount())) or 0 "
            "local used=tonumber((M:GetDepartureCount())) or 0 "
            "local left=cap-used if left<0 then left=0 end return left end)()")


def truck_dispatch_cap() -> str:
    """Lua *expression* -> how many trade trucks may go out today at all, or nil.

    Four to start with and more with the «Extra Truck» tech, which is why it is
    read rather than written down: the number differs per account and grows.
    """
    return ("(function() " + _TRUCK_STATION +
            "return tonumber((M:GetMaxDailyCount())) or 0 end)()")


def truck_dispatch_ready() -> str:
    """Lua *expression* -> trade trucks that could be dispatched right now, or nil.

    The client's own `GetRealReadyCount`: trucks standing at the station in
    `TruckStationState.Ready`, capped by what is left of today's allowance. So it
    is «how many presses are available», not «how many trucks exist» — a fleet of
    four with one dispatch left answers 1.
    """
    return ("(function() " + _TRUCK_STATION +
            "return tonumber((M:GetRealReadyCount())) or 0 end)()")


def secret_task_steal_cap() -> str:
    """Lua *expression* -> the daily robbery cap (5 on the live account).

    Split out from :func:`secret_task_steals_left` so a reading can show «2 из 5» and
    not just «3 left»: a quota is only readable as spent-of-allowed, and the allowed
    half is a server setting that has changed before.
    """
    return ("(tonumber(DataCenter.ActDispatchTaskDataManager:"
            "GetDispatchSetting('steal_count')) or 0)")


def ghost_recon_steal_cap() -> str:
    """Lua *expression* -> the ghost-recon daily robbery cap. See the note above."""
    return ("(function() local cfg=DataCenter.ActGhostreconManager:GetNowSettingCfg() "
            "return tonumber(cfg and cfg.stealCount) or 0 end)()")


# --- Base decorations: the handbook's upgrade press --------------------------
# Session `20260730_142543_Повышение_украшений` recorded the press itself; the rest
# of this was read out of the live Lua VM afterwards, because the first recipe built
# from the wire alone did nothing in game (task #1125).
#
# The wire, from the trace (the tracer ran with `filter="SFS"`, so ONLY SFS calls were
# recorded — the building/handbook/cell taps are simply not in the file, and their
# absence there proves nothing about them):
#
#     SFSNetwork.SendMessage <- decorator.progress.upgrade, <buildUuid>, 1
#       SFSObject.PutLong  buildUuid, <buildUuid>
#       SFSObject.PutInt   num, 1
#
# The two parameters are NOT free-form:
#
#   * `buildUuid` is the decoration GROUP's representative building, the one
#     `BuildManager:GetMaxLvBuildDataByBuildId(itemId)` returns. Fed that itemId
#     (103401000) it hands back exactly the uuid in the recording. Any other building
#     of the same decoration is the wrong target — sending one is accepted by the
#     client and changes nothing (proven live).
#   * `num` is a COUNT of progress steps to buy, not a slot index: the real press,
#     `UIDecorationAdvanceUpgrade:OnLevelUpClick`, sends `curCanUpgradeNum`, which is
#     1 for a single tap and more for a long press.
#
# The first gate is `BuildingUtils.IsExistAdvanceUpgrade(itemId, level)` — the decoration
# has an "advance upgrade" step at its current level. Without it the server refuses the
# send outright: `errorCode = building_center_tips4`,
# `errorMsg = "building no extra_lvup_para"` (captured live off the reply).
#
# The second gate is the material, and it is a SPARE DUPLICATE of the decoration, not a
# currency. `BuildingUtils.GetDecorateUpLevelBuilds(buildData)` returns the feed cells the
# window renders, one per level that can be fed in:
#
#     {itemId = 103404001, count = 2, needScore = 484, nextScore = 486, levelTemplate, buildData}
#
# `count` is how many steps are buyable right now — the spare copies held, capped by what
# is still missing to the next star threshold (`math.min` inside the reader). It is exactly
# the `curCanUpgradeNum` the real press sends. One spare copy = one progress point.
#
# `BuildManager:IsCanUpgradeDecoration(itemId, level, buildData)` is NOT this gate, and an
# earlier revision of this block wrongly used it. It returns `hasCount, upgradeNeedCount`
# in *glue value* (`equal_glue_value` off the level template) and prices the ordinary
# decoration LEVEL upgrade — 29160 for level 6 -> 7 — against holdings of ~110. Read as a
# material gate it is never satisfiable, so the button never pressed. Proven wrong by the
# 20260730_162054 recording: the player upgraded 103402000 by hand while that pair read
# 110 / 29160, and the window's own readout was the spare count (green `1/100` before the
# press, red `0/99` after) with the star bar moving 386 -> 387 of 486.
#
# So one press is: pick a decoration group that passes both gates, resolve its uuid from
# the itemId, send `{buildUuid, num}`. No window is opened; the handbook the player walked
# through is UI only.
#
# Proven live on 2026-07-30 by this button, one step at a time, on decoration 103404000
# (level 6, two spares banked): the star score went 484/486 -> 485/486 and the spare count
# 2 -> 1, so the press moved real progress and the game charged for it. The uuid it sent is
# the one `GetMaxLvBuildDataByBuildId` resolves — the same identity both hand recordings
# put on the wire for their own groups.
#
# **`num > 1` in one send, proven live on 2026-08-20 (task #1560).** §7 of the research
# note had this as the one thing not yet shown: the panel's own long press reads the same
# `curCanUpgradeNum` this button computes, and nothing in the trace said a bigger number
# in the SAME message would not just be refused down to 1. It is not refused: decoration
# 103502000 read `needScore=52 cnt=2` (two spares banked, two points short of the next
# star), one message carried `num=2`, and the very next read came back `needScore=54
# cnt=0` — the score crossed the whole gap in the one round trip that used to take two
# presses. So `upgrade_all_decorations_now` below sends each ready group its WHOLE
# available count in ONE message rather than stepping it by ones — the wire already
# supported this, the recipe just never asked for more than 1.

_DECOR_UPGRADE_MSG_KEY = "MsgDefines.DecoratorProgressUpgradeMessage"

# Walks the decoration groups and hands each one that has an upgrade step to `cb` as
# `(itemId, buildData, steps)`, where `steps` is how many progress steps the banked spare
# duplicates would buy right now (0 = nothing to feed). Shared by the count, the press and
# the dump so the three can never disagree about what "ready" means.
_DECOR_SCAN = (
    "local bm=DataCenter.BuildManager "
    "local function scan(cb) "
    "for itemId in pairs(bm:GetAllDecoratorBuildingData() or {}) do "
    "local ok,d=pcall(function() return bm:GetMaxLvBuildDataByBuildId(itemId) end) "
    "if ok and d then "
    "local ok2,adv=pcall(function() return BuildingUtils.IsExistAdvanceUpgrade(itemId,d.level) end) "
    "if ok2 and adv then "
    "local ok3,cells=pcall(function() return BuildingUtils.GetDecorateUpLevelBuilds(d) end) "
    "local steps=0 "
    "if ok3 and type(cells)=='table' then "
    "for _,c in pairs(cells) do local n=tonumber(c.count) if n and n>0 then steps=steps+n end end end "
    "if cb(itemId,d,steps) then return true end end end end return false end "
)


def decoration_upgrade_ready_count() -> str:
    """Lua *expression* -> how many progress steps are affordable across all decorations.

    This is a count of STEPS, not of decorations: a group holding two spare duplicates
    contributes two, so `TAP upgrade_decoration xall` spends every one of them. Zero is
    the normal reading — a spare copy of a decoration is a rare thing to be holding.
    """
    return ("(function() %s local n=0 "
            "scan(function(_,_,steps) n=n+steps end) "
            "return n end)()" % _DECOR_SCAN)


def upgrade_next_decoration(count: int = 1) -> str:
    """Upgrade the first decoration that is ready — the whole press, self-contained.

    Finds the group itself (no target has to be parked first), resolves the uuid the
    game would use and sends `count` progress steps. With nothing ready it logs why
    and sends nothing, so running it on a schedule costs one VM call and no refusals.

    One step per press by default: the reply refreshes the group, so the next press
    re-reads what is left instead of trusting a stale count.
    """
    return (
        "%s local fired=false "
        "scan(function(itemId,d,steps) "
        "if steps>0 then "
        "local num=math.min(%d,steps) "
        "pcall(function() SFSNetwork.SendMessage(%s, d.uuid, num) end) "
        'CS.UnityEngine.Debug.LogError("ACT decor_upgrade item="..tostring(itemId)..'
        '" uuid="..tostring(d.uuid).." lv="..tostring(d.level)..'
        '" num="..tostring(num).." of "..tostring(steps)) '
        "fired=true return true end end) "
        'if not fired then CS.UnityEngine.Debug.LogError("ACT decor_upgrade_skip nothing ready") end'
        % (_DECOR_SCAN, int(count), _DECOR_UPGRADE_MSG_KEY)
    )


def upgrade_all_decorations_now() -> str:
    """Lua *expression* -> spend EVERY banked spare in ONE game-VM call, and report it.

    One message per ready group, each carrying that group's WHOLE available count —
    not one step at a time. A round trip to the VM costs ~0.15 s and the loop inside it
    is free (the same reasoning `alliance_donate_batch` spends a whole quota on), so a
    base with a dozen ready groups is one call instead of a dozen presses.

    This is safe to fire at every group in the SAME pass because each group gets
    exactly ONE send: nothing here re-reads a group's cell after sending to it, so
    there is no risk of a second send inside this call pricing itself off a count the
    first send has already spent but the client has not yet heard back about (the
    trap `alliance_donate_batch`'s own comment names, avoided here by never sending
    twice to the same group). A group whose spares outrun the immediate next star
    threshold spends only what that threshold prices — `count` is already capped to
    it (§4 of docs/research/decoration-upgrade.md) — and whatever is left over is
    picked up on the NEXT run once the game exposes the following star's cell.

    Returns one string: a summary line, a semicolon-separated line per group that was
    actually sent (`item: before->after/goal (+steps)`), and, when any exist, a short
    tail naming the groups this pass could not touch and why (no spare banked).
    """
    return (
        "(function() %s local checked,ready,total=0,0,0 local sent_lines,why={},{} "
        "scan(function(itemId,d,steps) checked=checked+1 "
        "local score,goal='?','?' "
        "pcall(function() local cells=BuildingUtils.GetDecorateUpLevelBuilds(d) "
        "for _,c in pairs(cells or {}) do goal=c.nextScore "
        "if tonumber(c.count) and tonumber(c.count)>0 then score=c.needScore end end end) "
        "if steps>0 then ready=ready+1 total=total+steps "
        "pcall(function() SFSNetwork.SendMessage(%s, d.uuid, steps) end) "
        "sent_lines[#sent_lines+1]=tostring(itemId)..': '..tostring(score)..'->'"
        "..tostring((tonumber(score) or 0)+steps)..'/'..tostring(goal)..' (+'..tostring(steps)..')' "
        "else why[#why+1]=tostring(itemId)..' (goal '..tostring(goal)..')' end end) "
        "local out='checked '..tostring(checked)..', '..tostring(ready)"
        "..' upgraded now, '..tostring(total)..' step(s) sent total' "
        "if #sent_lines>0 then out=out..' :: '..table.concat(sent_lines,'; ') end "
        "if #why>0 then out=out..' :: no spare banked for: '..table.concat(why,', ') end "
        "return out end)()"
        % (_DECOR_SCAN, _DECOR_UPGRADE_MSG_KEY)
    )


def decoration_upgrade(item_id: int, count: int = 1) -> str:
    """Upgrade one named decoration group by its `item_id` — the targeted press.

    The uuid is resolved in game (`GetMaxLvBuildDataByBuildId`), never hard-coded: it
    belongs to the account and changes when the group's top building does.
    """
    return (
        "local bm=DataCenter.BuildManager "
        "local ok,d=pcall(function() return bm:GetMaxLvBuildDataByBuildId(%d) end) "
        "if ok and d then "
        "pcall(function() SFSNetwork.SendMessage(%s, d.uuid, %d) end) "
        'CS.UnityEngine.Debug.LogError("ACT decor_upgrade item=%d uuid="..tostring(d.uuid).." num=%d") '
        'else CS.UnityEngine.Debug.LogError("ACT decor_upgrade_skip item=%d not on the base") end'
        % (int(item_id), _DECOR_UPGRADE_MSG_KEY, int(count), int(item_id), int(count), int(item_id))
    )


def decoration_state_dump() -> str:
    """Log every decoration that has an upgrade step, with the steps its spares would buy.

    This is the "why is nothing happening?" reading: a line per group with how many steps
    its spares would buy and a READY marker on the ones a press would actually take.

    The star score is printed only for a group that has something to feed. With no spare
    banked the reader's `needScore` degenerates to `nextScore`, which would read as "this
    one is maxed out" when it only means "nothing to feed here" — so that line says
    `no-spares` and the threshold instead of a score it cannot know.
    """
    return (
        "%s local n,ready=0,0 "
        "scan(function(itemId,d,steps) n=n+1 "
        "if steps>0 then ready=ready+1 end "
        "local score,goal='?','?' "
        "pcall(function() local cells=BuildingUtils.GetDecorateUpLevelBuilds(d) "
        "for _,c in pairs(cells or {}) do goal=c.nextScore "
        "if tonumber(c.count) and tonumber(c.count)>0 then score=c.needScore end end end) "
        'CS.UnityEngine.Debug.LogError("ACT decor item="..tostring(itemId)..'
        '" uuid="..tostring(d.uuid).." lv="..tostring(d.level)..'
        '" score="..(steps>0 and (tostring(score).."/"..tostring(goal)) '
        'or ("no-spares (goal "..tostring(goal)..")"))..'
        '" steps="..tostring(steps)..(steps>0 and "  READY" or "")) end) '
        'CS.UnityEngine.Debug.LogError("ACT decor_groups="..tostring(n).." ready="..tostring(ready))'
        % _DECOR_SCAN
    )


def decorations_window() -> str:
    """Open the base's decoration window — the manual path, for looking at it."""
    return ("pcall(function() UIManager.Instance:OpenWindow(UIWindowNames.UIDecorationMain) end) "
            'CS.UnityEngine.Debug.LogError("ACT decorations_window opened")')


# --------------------------------------------------------------------------
# The account's characters, and switching the client to one of them
# --------------------------------------------------------------------------
# The list is what the server answers to `account.login.new` — one entry per
# character, parsed into `DataCenter.AccountManager.rolesList`. Where it comes
# from, and why the client's login cache is NOT it, is docs/research/account-list.md.
#
# Switching used to reproduce the LOGIN SCREEN's cell handler
# (`UIAccountListCell.OnBtnSelectClick`), which builds its message out of
# `AccountManager.param` — a table only that screen fills. From inside a session it
# therefore sent `az.account.login` with an empty `userName` and the server answered
# `120618 email format error` (captured, #1190). It reported "sent" and switched
# nothing.
#
# The game's own route is the CHARACTER screen's cell: `UIRolesCell:OnBtnClick`
# opens `UIWindowNames.UIRoleLogin` for the picked role, and that window's
# «войти» press is `UIRoleLoginView:OnClickLogin`, whose whole body (read out of the
# live VM with `string.dump`) is:
#
#     CS.AccountCredentialManager.ClearAll()
#     CS.AccountCredentialManager.SetServerNetInfo(param.ip, param.port, param.zone)
#     CS.AccountCredentialManager.SetLoginKey(param.loginKey)
#     CS.AccountCredentialManager.SetUID(param.gameUid)
#     CS.AccountCredentialManager.Save()
#     CS.AIHelp.AIHelpProxy.Logout()
#     EventManager:GetInstance():Broadcast(EventId.SwitchAccount)
#     SFSNetwork.SendMessage(MsgDefines.UserCleanPost)
#
# — i.e. write the picked character's credentials over the saved ones, then tell the
# server the session is done with. Every field it needs (`ip`, `port`, `zone`,
# `loginKey`, `gameUid`) is in the role record the server sent; nothing is invented
# and no window has to be opened. `ip` is a pipe-separated list of hosts and `port` a
# string — both are passed on exactly as the game passes them.
#
# That is NOT the whole press, and the missing half cost a live run that did nothing:
# the relog is done by the REPLY to `user.clean.post`. Its handler
# (`Net.Msgs.Account.UserCleanPostMessage:HandleMessage`) is one call —
# `CS.SwitchAccountCheckGameVersionTools.ReloadGameByCheckLauncherVersion()` — and
# that is what actually drops the session and logs back in with what was just saved.
# Sent from inside a session by hand, that reply never came: the handler was hooked
# and watched for 14 s across three sends and never fired, while the client sat on the
# old character. So the press makes the same call itself, right after the send.
#
# Proven live (#1192, 2026-08-02): 100 -> 200 and back, in-process — the game keeps
# its pid, so the Lua daemon survives the relog and the panel needs no reattach. The
# client comes back on the new character's base about ten seconds later.

#: Where the recipe parks the server id to switch to (`TAP` carries no arguments).
_SWITCH_VAR = "DataCenter.__lw_switch_account"

#: Walk `rolesList` and hand each real character to `fn`. The screen prepends an
#: `isEmpty` placeholder (its "add a character" slot) which is not a character.
_ROLES_SCAN = (
    "local function scan(fn) "
    "local roles = DataCenter.AccountManager.rolesList "
    "if type(roles) ~= 'table' then return end "
    "for _, v in pairs(roles) do "
    "if type(v) == 'table' and not v.isEmpty then fn(v) end end end "
)


def account_roles_request() -> str:
    """Ask the server for this account's characters — headless, opens no window.

    `account.login.new` carries only the device id, and the reply lands
    asynchronously as `push.account.login.new`, which fills
    `DataCenter.AccountManager.rolesList`. Poll :func:`account_roles_count` after it
    rather than expecting the list to be there when this returns.
    """
    return (
        "local ok,err = pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.AccountLoginNew) "
        'CS.UnityEngine.Debug.LogError("ACT account_roles_request sent") '
        "end) "
        'if not ok then CS.UnityEngine.Debug.LogError("ACT account_roles_request skip: "..tostring(err)) end'
    )


def account_roles_count() -> str:
    """Expression: how many characters the server has named so far (0 before it answers)."""
    return ("(function() local n = 0 %s scan(function() n = n + 1 end) return n end)()"
            % _ROLES_SCAN)


def account_switch_target() -> str:
    """Expression: can the parked server id be switched to right now?

    ``1`` the character is there and is not the one in play, ``0`` no character of
    this account is on that server, ``-1`` that character is already in play. The
    recipe turns each into its own refusal, so "nothing happened" is never the answer.
    """
    return (
        "(function() local sid = tostring(%s or 0) local hit = 0 %s "
        "scan(function(v) if tostring(v.id) == sid then hit = 1 end end) "
        "if hit == 0 then return 0 end "
        "local cur = 0 pcall(function() cur = LuaEntry.Player.serverId end) "
        "if tostring(cur) == sid then return -1 end return 1 end)()"
        % (_SWITCH_VAR, _ROLES_SCAN)
    )


def account_switch_press() -> str:
    """Switch the live client to the character parked in ``__lw_switch_account``.

    The «войти» press of the game's own `UIRoleLogin` window plus the relog its reply
    would have triggered, run without opening anything (see the block comment above).
    Saves that character's credentials over the current ones, tells the server the
    session is done, and reloads the client — which comes back on the new character
    about ten seconds later, in the same process.

    Fire-and-forget: the reconnect cannot be observed from inside the same chunk, so
    the recipe checks afterwards that `LuaEntry.Player.serverId` moved.
    """
    return (
        "local ok,err = pcall(function() "
        "local sid = tostring(%s or 0) local role %s "
        "scan(function(v) if tostring(v.id) == sid then role = v end end) "
        "if role == nil then "
        'CS.UnityEngine.Debug.LogError("ACT account_switch skip: no character on "..sid) return end '
        "local A = CS.AccountCredentialManager "
        "A.ClearAll() "
        "A.SetServerNetInfo(role.ip, role.port, role.zone) "
        "A.SetLoginKey(role.loginKey) "
        "A.SetUID(role.gameUid) "
        "A.Save() "
        "pcall(function() CS.AIHelp.AIHelpProxy.Logout() end) "
        "EventManager:GetInstance():Broadcast(EventId.SwitchAccount) "
        "SFSNetwork.SendMessage(MsgDefines.UserCleanPost) "
        'CS.UnityEngine.Debug.LogError("ACT account_switch sent server="..sid) '
        # The relog itself — what the reply to `user.clean.post` does in the game, and
        # what nothing does when the message is sent by hand. Last, so a client that
        # goes down mid-call has already saved the credentials it will come back with.
        "CS.SwitchAccountCheckGameVersionTools.ReloadGameByCheckLauncherVersion() "
        "end) "
        'if not ok then CS.UnityEngine.Debug.LogError("ACT account_switch skip: "..tostring(err)) end'
        % (_SWITCH_VAR, _ROLES_SCAN)
    )


def account_switch_arm(serverid) -> str:
    """Park the server id the next :func:`account_switch_press` should switch to."""
    return "%s = %d" % (_SWITCH_VAR, int(serverid))


def jump_landing() -> str:
    """Log `ACT landing=<viewed>,<home>,<in_other>` — the three facts a jump landed by.

    **`curServerId` ALONE CANNOT SAY WHETHER A CROSS-SERVER JUMP ARRIVED (#2593).** Live,
    after one, the client has named a THIRD warzone — neither the one left nor the one
    entered (docs/research/secret-tasks-tab.md), so a press that waited for that field to
    equal its target reported «перехода не было» about a jump that had worked. The wire
    says the move itself takes ~1.6 s (docs/research/protocol.md), and the confirm was
    still red after nineteen.

    So the judge is `CrossServerUtil.IsInOtherServer()`, which is what
    :func:`jump_to_coord`'s own live check used: a foreign warzone turns it true, the home
    one turns it false, and the account's own `serverId` stays put through both. The
    viewed number is kept as the thing to SHOW, never as the thing to decide by.
    """
    return ('local cur=%s local home="" local other=false '
            'pcall(function() home = tostring(LuaEntry.Player.serverId) end) '
            'pcall(function() other = CrossServerUtil.IsInOtherServer() end) '
            'CS.UnityEngine.Debug.LogError("ACT landing="..tostring(cur)..","'
            '..tostring(home)..","..tostring(other))'
            % current_server_expr())


def account_current_server() -> str:
    """Expression: the server of the character in play (0 while the client is reconnecting).

    `WorldFavoDataManager.curServerId` is empty on a freshly logged-in client, so the
    player's own record is asked first and that is only the fallback.
    """
    return ("(function() local cur = 0 "
            "pcall(function() cur = LuaEntry.Player.serverId end) "
            "if not cur or tonumber(cur) == nil or tonumber(cur) == 0 then "
            "pcall(function() cur = DataCenter.WorldFavoDataManager.curServerId end) end "
            "return tonumber(cur) or 0 end)()")


def account_roles_dump() -> str:
    """Log one `ACT R …` line per character, with everything the server said about it.

    Text fields are hex-encoded because the log line is read back through a marker
    that is not binary-safe and nicknames are not ASCII. `tools/account_switch.py`
    parses these lines; the panel's «Аккаунты» tab draws them.
    """
    return (
        "local function hex(s) return (tostring(s):gsub('.', function(c) "
        "return string.format('%%02x', c:byte()) end)) end "
        "local function L(s) CS.UnityEngine.Debug.LogError('ACT '..s) end "
        "pcall(function() "
        "L('cur='..tostring(%s)) %s "
        "scan(function(v) L('R serverid='..tostring(v.id)"
        "..' gameUid='..tostring(v.gameUid)"
        "..' level='..tostring(v.gameUserLevel or 0)"
        "..' power='..tostring(v.power or 0)"
        "..' picVer='..tostring(v.picVer or 0)"
        "..' nick='..hex(tostring(v.gameUserName or ''))"
        "..' zone='..hex(tostring(v.zone or ''))"
        "..' alliance='..hex(tostring(v.alAbbr or ''))"
        "..' uuid='..hex(tostring(v.uuid or ''))"
        "..' pic='..hex(tostring(v.pic or ''))) end) end)"
        % (account_current_server(), _ROLES_SCAN)
    )


# --------------------------------------------------------------------------
# «Кодовое имя» — the world-boss event (`Codename`, the game's own key 100086)
# --------------------------------------------------------------------------
# The event puts one boss on the world map for a few hours at a time («Кодовое имя
# 87/39/64», one per pair of weekdays) and asks for three attacks on it. Attempts
# themselves are UNLIMITED — the game's own rules say so and the client agrees
# (`attackMaxNum = -1`) — so the thing the day owes is not an allowance being spent
# but a count being reached: three attacks earn the reward, and the biggest single
# hit is what the daily ranking is made of.
#
# Everything below reads or presses `DataCenter.ActBossDataManager`, which is where
# the client keeps the whole event:
#
#   IsBossAvailable()      is the boss attackable RIGHT NOW: a stage with a start
#                          and an end, checked against the server's clock. The event
#                          runs Monday to Saturday and the stage covers the whole day
#                          (23 hours from the server's midnight), so outside it means
#                          Sunday, not «between windows». The four times in
#                          `bossRefreshTimeSvr` are when the boss RESPAWNS during the
#                          day, not four separate windows.
#
#                          IT ANSWERS «no» ON A CLIENT THAT HAS NOT ASKED. The stage
#                          list it reads (`stageTimeList`) arrives only in the reply to
#                          `user.get.act.boss.march`, which the game itself sends when
#                          it opens the event's own screen. A panel that never asked
#                          reads a nil list and draws «событие не идёт» over a running
#                          event — which is exactly what happened until #1259. Every
#                          reading of this manager therefore sends `codename_fetch()`
#                          first and waits for `codename_loaded()`.
#   actBossTransTimes      attacks made in the current window. The server owns it:
#                          it is refreshed by `UserGetActBossMarch` and announced as
#                          `OnActBossAttackTimesRefresh`, so it counts an attack sent
#                          from anywhere — this panel, the phone, the person playing.
#   rewardMaxTimes         how many attacks earn the reward. Three, from the config,
#                          read rather than written down here.
#   maxDamage              the biggest single hit, which is the number the ranking
#                          uses and the number the person wants to see.
#   GetActBossDataList()   the boss instances themselves: uuid, monsterId, startPos
#                          and the window they live in.
#
# The reverse-engineering is docs/research/codename-event.md.
_CODENAME_MGR = "DataCenter.ActBossDataManager"
_CODENAME_PARAMS = "local p = DataCenter.__lw_codename or {} "


def codename_fetch() -> str:
    """Ask the server for the event's bosses and its stage — the game's own get.

    `user.get.act.boss.march` is what the client sends for itself (`RefreshTransTime`)
    and what the reply handler `RefreshActBossDataList` fills BOTH `stageTimeList` and
    `actBossDataList` from. Nothing is changed by it: it is a read of the server's
    state, and the game fires it whenever it opens the event's screen.

    It has to be sent by us because nothing else will. `RefreshTransTime` returns early
    on a client whose stage list is still nil — the very state a panel-driven client is
    always in — so the manager would sit empty for the whole session and every reading
    beside it would be last session's or none. Send this, wait for `codename_loaded()`,
    then read.
    """
    return ('pcall(function() SFSNetwork.SendMessage(MsgDefines.UserGetActBossMarch) end) '
            'CS.UnityEngine.Debug.LogError("ACT codename_fetch sent")')


def codename_loaded() -> str:
    """Lua *expression* -> 1 once the fetch's reply has landed, else 0.

    The stage list is the thing the reply brings and the thing `IsBossAvailable()`
    reads, so its arrival is what «the answer is now worth reading» means. It stays 0
    on a day the event does not run — there is no stage to send — which is why every
    caller waits for it with a LIMIT rather than until it turns 1.
    """
    return ("((type(%s.stageTimeList) == 'table') and 1 or 0)" % _CODENAME_MGR)


def codename_open() -> str:
    """Lua *expression* -> 1 while the boss can be attacked right now, else 0.

    Ask `codename_fetch()` first and wait for `codename_loaded()`, or this answers «no»
    on a running event — the stage list it reads arrives only in that reply.

    The gate the whole feature hangs off: outside a window there is no boss on the
    map, and every count beside it is last window's. Drawn as «событие не идёт»
    rather than as a zero, because those are different answers.
    """
    return ("(function() local ok, v = pcall(function() return %s:IsBossAvailable() end) "
            "if not ok then return nil end return (v and 1 or 0) end)()" % _CODENAME_MGR)


def codename_attacks_made() -> str:
    """Lua *expression* -> attacks made on the boss in the current window."""
    return ("(function() local ok, v = pcall(function() return %s.actBossTransTimes end) "
            "if not ok then return nil end return math.floor(tonumber(v) or 0) end)()"
            % _CODENAME_MGR)


def codename_attacks_needed() -> str:
    """Lua *expression* -> how many attacks earn the reward (three, from the config)."""
    return ("(function() local ok, v = pcall(function() return %s.rewardMaxTimes end) "
            "if not ok then return nil end return math.floor(tonumber(v) or 0) end)()"
            % _CODENAME_MGR)


def codename_attacks_left() -> str:
    """Lua *expression* -> how many of the day's attacks are still owed, or nil.

    `needed - made`, floored at zero, and nil when either half could not be read — the
    same three-way answer every other reading here gives, because «none left» and
    «nobody knows» are different states and a caller that conflates them either skips a
    day's reward or marches at a client that cannot answer.

    One copy of the arithmetic, spelled here rather than in each caller: the «События»
    board draws it, `read_codename_event.md` reports it and `attack_codename_daily.md`
    loops on it, and a board that said two while the loop believed three would be worse
    than no number at all.
    """
    return ("(function() local a = %s local n = %s if a == nil or n == nil then "
            "return nil end local l = n - a if l < 0 then l = 0 end return l end)()"
            % (codename_attacks_made(), codename_attacks_needed()))


def codename_max_damage() -> str:
    """Lua *expression* -> the biggest single hit landed on the boss.

    What the daily ranking is made of, per the event's own rules: only the highest
    damage dealt in ONE attack counts.
    """
    return ("(function() local ok, v = pcall(function() return %s.maxDamage end) "
            "if not ok then return nil end return math.floor(tonumber(v) or 0) end)()"
            % _CODENAME_MGR)


def codename_targets() -> str:
    """Lua *expression* -> how many boss instances the client has on the map."""
    return ("(function() local ok, l = pcall(function() return %s:GetActBossDataList() end) "
            "if not ok or type(l) ~= 'table' then return nil end "
            "local n = 0 for _ in pairs(l) do n = n + 1 end return n end)()" % _CODENAME_MGR)


def codename_seconds_left() -> str:
    """Lua *expression* -> seconds left in the open window, or nil when none is open."""
    return ("(function() local ok, st = pcall(function() return %s:GetAttackStageData() end) "
            "if not ok or type(st) ~= 'table' then return nil end "
            "local e = tonumber(st.endTime) if e == nil then return nil end "
            "local now = tonumber(UITimeManager:GetInstance():GetServerTime()) or 0 "
            "local left = e - now if left < 0 then left = 0 end "
            "return math.floor(left) end)()" % _CODENAME_MGR)


def codename_arm() -> str:
    """Set the attack run up: pick the boss, pick a free squad, note the count.

    All three before anything is opened, for the reason `rally_create_arm` does the
    same: a run that finds out at the last press that there was no squad has already
    flown the camera across the map and left a popup open on it.

    * `uuid` / `point` / `server` — the boss. Taken from `GetActBossDataList()`, whose
      entries carry the uuid the march is addressed to and a `startPos` the map index
      is made of. `startPos` is read through every shape it is known to take (a
      table with `x`/`y`, a pair, a ready-made index), because the list is empty
      outside a window and there was no live one to look at when this was written.
    * `formation` — the FIRST squad standing in the base. «Свободный отряд» is what
      the button says and what it means: a squad already marching, gathering or
      standing in somebody else's rally cannot be sent, and the game only says so at
      the last press.
    * `before` — attacks made so far, so the attack can be MEASURED afterwards rather
      than assumed from a press that returned cleanly.
    """
    return (
        _CODENAME_PARAMS +
        "p.uuid, p.point, p.server, p.formation = nil, nil, nil, nil "
        "pcall(function() "
        "local lst = %(mgr)s:GetActBossDataList() "
        "for _, b in pairs(lst or {}) do "
        "if p.uuid == nil then "
        "p.uuid = b.uuid "
        "pcall(function() p.server = tonumber(b.serverId) or tonumber(b.srcServer) end) "
        "local sp = b.startPos "
        "if type(sp) == 'table' then "
        "local x, y = tonumber(sp.x), tonumber(sp.y) "
        "if x ~= nil and y ~= nil then p.point = math.floor(y) * 1000 + math.floor(x) "
        "else p.point = tonumber(sp[1]) end "
        "else p.point = tonumber(sp) end "
        "end end end) "
        "pcall(function() "
        "local best = nil "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "local idx = tonumber(v.index) "
        "local st = tonumber(v.state) "
        "local ok, idle = pcall(function() return v:IsFree() end) "
        "local free = true if ok and idle ~= nil then free = (idle and true or false) end "
        "if idx ~= nil and st == 0 and free and (best == nil or idx < best.idx) then "
        "best = {idx = idx, uuid = v.uuid} end end "
        "if best ~= nil then p.formation, p.squad = best.uuid, best.idx end end) "
        "p.before = %(made)s "
        "DataCenter.__lw_codename = p "
        'CS.UnityEngine.Debug.LogError("ACT codename_arm boss="..tostring(p.uuid)'
        '.." point="..tostring(p.point).." squad="..tostring(p.squad)'
        '.." formation="..tostring(p.formation).." attacks="..tostring(p.before))'
        % {"mgr": _CODENAME_MGR, "made": codename_attacks_made()}
    )


def codename_armed() -> str:
    """Lua *expression* -> what the arm found: 1 all set, 0 no boss, -1 no free squad."""
    return (
        "(function() " + _CODENAME_PARAMS +
        "if p.uuid == nil or p.point == nil then return 0 end "
        "if p.formation == nil then return -1 end return 1 end)()"
    )


def codename_send() -> str:
    """Send the squad at the boss — the whole attack, in one call, with no window.

    This is the LAST thing the squad screen does when a person taps «Марш», with the
    arguments it passes, read off the wire while the player made one attack by hand
    (#1259) and then reproduced byte for byte:

        SendCreateMarchMessage(formation, DIRECT_ATTACK_ACT_BOSS, point, uuid,
                               timeIndex = 1, autoBackHome = 1, needSoldier = false,
                               targetServerId = server, destroyTimeIndex = nil)

    so nothing between the event's «Атака» and that call has to be walked at all: no
    camera flight, no tile waiting to be streamed in, no popup, no squad screen. The
    boss is addressed by uuid, and the server builds the path itself — the message that
    leaves carries `start;target` as a pair it works out from the formation.

    `CROSS_DIRECT_ATTACK_ACT_BOSS` when the boss stands on another server; the arm parks
    its `serverId` so this can tell.

    Scheduled on the main thread through `TimerManager:DelayInvoke`, for the reason
    every other launch in this file is (`attack.py`): a cold send from the hijack
    thread returns `true` and is dropped by the server.
    """
    return (
        _CODENAME_PARAMS +
        "if p.formation == nil or p.uuid == nil then error('nothing armed for this run') end "
        "local kind = MarchTargetType.DIRECT_ATTACK_ACT_BOSS "
        "local home = nil pcall(function() home = tonumber(LuaEntry.Player:GetSelfServerId()) end) "
        "if p.server ~= nil and home ~= nil and tonumber(p.server) ~= home then "
        "kind = MarchTargetType.CROSS_DIRECT_ATTACK_ACT_BOSS end "
        "TimerManager:GetInstance():DelayInvoke(function() "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(p.formation, kind, p.point, p.uuid, "
        "1, 1, false, p.server, nil) end) "
        'CS.UnityEngine.Debug.LogError("ACT codename_send ok="..tostring(ok).." err="..tostring(err)) '
        "end, 0.4) "
        'CS.UnityEngine.Debug.LogError("ACT codename_send scheduled squad="..tostring(p.squad)'
        '.." boss="..tostring(p.uuid).." kind="..tostring(kind))'
    )


def codename_sent() -> str:
    """Lua *expression* -> attacks gained since the arm ran. 1 once one has gone out.

    The DIFFERENCE, not the count: a window the person has already attacked in starts
    from a non-zero number, and the server owns the counter, so this is the one thing
    that proves an attack was really launched rather than merely pressed.
    """
    return ("((%s or 0) - ((DataCenter.__lw_codename or {}).before or 0))"
            % codename_attacks_made())


#: The windows the «Кодовое имя» attack leaves behind, and the ONLY ones the ear below
#: is allowed to shut (#2604). Both are raised by the game itself when a hit lands —
#: `UIBossDamageTip` carries «Текущий урон» over a single «Подтвердить», and
#: `LWUIWorldBossDamageTipView` is its newer sibling — so neither is a window a person
#: opens on purpose, which is what makes closing one safe. The event's other screens
#: («История Боев» `LWUIWorldBossRecord`, the rank, the reward, the task list) are
#: deliberately NOT here: a person reads those, and a panel that shut them would be
#: taking the game away from whoever is playing it.
CODENAME_SHUT_WINDOWS = ("UIBossDamageTip", "LWUIWorldBossDamageTipView")

#: How long after an attack a record window still counts as OURS, in minutes. The modal
#: does not arrive with the send: the squad flies to the boss first and the client only
#: raises it when the hit is resolved, which is minutes later and cannot be waited for
#: inside the recipe. So the ear holds a deadline instead of a flag, long enough for the
#: slowest march and short enough that an evening of hand-play is never touched.
CODENAME_SHUT_MINUTES = 30


def codename_shut_install(minutes: int = CODENAME_SHUT_MINUTES) -> str:
    """Lua *chunk* — shut the record modal the game raises after our own hit (#2604).

    An EAR, never a poll: it wraps `UIManager.Instance:OpenWindow` — the same instance
    `rawset` the reward ear uses (`reward_watch_install`, docs/research/reward-popups.md)
    — so nothing is asked of the game between the attack and the window, and the client
    tells us itself the moment one opens. The wrapper chains onto whatever is already on
    the instance and is re-armed by every attack, so the two ears survive each other in
    either order.

    Three things decide whether a window is shut, and all three have to hold:

    1. the name is one of :data:`CODENAME_SHUT_WINDOWS` — an explicit pair, never a
       substring, and never the screens a person reads;
    2. our own attack armed the ear less than ``minutes`` ago. Outside that span the
       modal belongs to somebody playing by hand and is left alone;
    3. the window answers `Ctrl:CloseSelf` — never `DestroyAllWindow`, which takes the
       HUD with it and does not give it back.

    The close is scheduled through `TimerManager:DelayInvoke` rather than made inside the
    client's own `OpenWindow`, for the same reason #2603 delayed the lucky gift's: a
    window closed halfway through opening is a window the client is still building.
    """
    names = " ".join(f"W['{name}']=true" for name in CODENAME_SHUT_WINDOWS)
    return (
        "pcall(function() "
        "local D=DataCenter local B=D.__lw_cnshut "
        "if B==nil or B.rows==nil then B={rows={},closed=0,seen=0} D.__lw_cnshut=B end "
        f"local W={{}} {names} B.allow=W "
        # The client answers to both spellings of its clock depending on where it is
        # asked from, and a wrong one here would make the deadline meaningless — so both
        # are tried, and a clock that answers neither falls back to the machine's.
        "local function now() local t=0 "
        "pcall(function() t=UITimeManager:GetInstance():GetServerTime() end) "
        "if (tonumber(tostring(t)) or 0)<=0 then "
        "pcall(function() t=UITimeManager.Instance:GetServerTime() end) end "
        "local n=math.floor((tonumber(tostring(t)) or 0)+0) "
        "if n<=0 then n=math.floor(os.time()*1000) end return n end "
        f"B.till=now()+{int(minutes)}*60*1000 "
        "local mgr=UIManager.Instance "
        "local cur=rawget(mgr,'OpenWindow') "
        "if type(cur)~='function' then local mt=getmetatable(mgr) "
        "local cls=mt and rawget(mt,'__index') cur=cls and cls.OpenWindow end "
        "if type(cur)~='function' then B.err='no OpenWindow' return end "
        "if B.wrapper~=nil and cur==B.wrapper then B.on=true return end "
        "B.orig=cur "
        # `table.pack`/`unpack`, exactly as the reward ear: this sits in front of EVERY
        # window the client opens and may not change what the caller gets back.
        "local pk=table.pack or function(...) return {n=select('#',...),...} end "
        "local up=table.unpack or unpack "
        "B.wrapper=function(self,name,...) local res=pk(B.orig(self,name,...)) "
        "pcall(function() local b=D.__lw_cnshut if b==nil then return end "
        "local s=tostring(name) if not b.allow[s] then return end "
        "b.seen=b.seen+1 "
        "if b.till==nil or now()>b.till then "
        "b.rows[#b.rows+1]='left|'..s while #b.rows>20 do table.remove(b.rows,1) end return end "
        "TimerManager:GetInstance():DelayInvoke(function() pcall(function() "
        "local w=UIManager.Instance:GetWindow(s) "
        "if w and w.Ctrl and w.Ctrl.CloseSelf then w.Ctrl:CloseSelf() "
        "b.closed=b.closed+1 b.rows[#b.rows+1]='closed|'..s "
        "else b.rows[#b.rows+1]='stuck|'..s end "
        "while #b.rows>20 do table.remove(b.rows,1) end end) end,0.6) end) "
        "return up(res,1,res.n) end "
        "rawset(mgr,'OpenWindow',B.wrapper) B.on=true end)"
    )


def codename_shut_report() -> str:
    """Lua *expression* -> what the ear has done, in one line for the log."""
    return (
        "(function() local B=DataCenter.__lw_cnshut "
        "if B==nil then return 'караул не встал' end "
        "if not B.on then return 'караул не встал: '..tostring(B.err) end "
        "return 'караул на окне рекорда: видел '..tostring(B.seen)"
        "..', закрыл '..tostring(B.closed)"
        "..(#(B.rows or {})>0 and (' ['..table.concat(B.rows,' ')..']') or '') end)()"
    )


# ---------------------------------------------------------------------------
# «Кристальный босс» — the daily boss with three attacks (#2077)
# ---------------------------------------------------------------------------
# The game's own name, out of the client's own tables: key `red_world_boss_title1` —
# **Crystal Boss** in English, **«Кристальный босс»** in Russian. The client calls it
# the RED boss everywhere in code (`DataCenter.CrystalBossDataManager`, `red.boss.*`
# on the wire) and the crystal one everywhere a person can see it; both names are the
# game's, and the panel uses the one the player reads.
#
# It is «Кодовое имя» with a different manager and a different march type — the person
# asked for it in those words, and the reverse-engineering agreed. One boss stands on
# the world map for a window that covers the server day, THREE attacks a day are paid
# for, and the server owns the count. Read once, act, then ask again:
#
#   RequestMarchData()     sends `red.boss.get.march`, the client's own get. It is the
#                          reading's first step for the same reason `codename_fetch`
#                          is: a manager nobody asked answers with the state it booted
#                          with, and this one boots with no boss and no counter.
#   GetRemainAttackCount() attacks LEFT today. The server's own number, so it counts an
#                          attack made from anywhere — this panel, the phone, or the
#                          person playing. It is the gate and the proof both.
#   GetMaxAttackCount()    how many the day pays for. Three at the time of writing,
#                          read rather than written down.
#   GetCurrentBoss()       the boss itself: `uuid`, `startPos` (a ready-made map index),
#                          `serverId`, and the health it has left.
#
# The attack is ONE call, exactly as it is for «Кодовое имя», with the march type the
# client keeps for this boss: `MarchTargetType.DIRECT_ATTACK_RED_BOSS` (194), and
# `CROSS_DIRECT_ATTACK_RED_BOSS` (196) when the boss stands on another server.
#
# The reverse-engineering is docs/research/crystal-boss.md.
_CRYSTAL_MGR = "DataCenter.CrystalBossDataManager"
_CRYSTAL_PARAMS = "local p = DataCenter.__lw_crystal or {} "


def crystal_fetch() -> str:
    """Ask the server for the boss and the day's attack count — the client's own get.

    `RequestMarchData()` sends `red.boss.get.march` and nothing else (measured on a live
    client: `RequestPanelData()` sends that one plus the progress and the achievement
    gets, which this feature never reads). The reply is what fills the march state, the
    boss dictionary and the attack counter, so every reading below is worth reading only
    after it has landed.
    """
    return ('pcall(function() %s:RequestMarchData() end) '
            'CS.UnityEngine.Debug.LogError("ACT crystal_fetch sent")' % _CRYSTAL_MGR)


def crystal_loaded() -> str:
    """Lua *expression* -> 1 once the fetch's reply has landed, else 0.

    The march state is what the reply brings — the activity, the stage and the state it
    is in — so its arrival is «the answers beside it are this session's». It stays 0 on
    a client that is not talking to the server, which is why every caller waits for it
    with a LIMIT rather than until it turns 1.
    """
    return ("(function() local ok, st = pcall(function() return %s:GetMarchState() end) "
            "if not ok or type(st) ~= 'table' then return 0 end "
            "if st.activityId == nil then return 0 end return 1 end)()" % _CRYSTAL_MGR)


def crystal_open() -> str:
    """Lua *expression* -> 1 while the boss can be attacked at all right now, else 0.

    All three of the client's own gates, because they answer different questions: the
    activity is switched on (`IsOpen`), the day's window is running (`IsActivityTimeOpen`)
    and there is a boss standing in it (`IsBossAvailable`). A day with no window is
    «событие не идёт» rather than «нет атак» — different states, drawn differently, and
    the errand ends the first as a success.
    """
    return ("(function() local ok, v = pcall(function() "
            "return (%(m)s:IsOpen() and %(m)s:IsActivityTimeOpen() "
            "and %(m)s:IsBossAvailable()) end) "
            "if not ok then return nil end return (v and 1 or 0) end)()"
            % {"m": _CRYSTAL_MGR})


def crystal_attacks_left() -> str:
    """Lua *expression* -> attacks the day still owes, or nil when nobody could say.

    THE SERVER'S OWN NUMBER, and the only one worth gating on: it counts the attacks
    made from anywhere, so a day the person has already played by hand costs this panel
    nothing. nil is «the counter could not be read», which is not zero — a client that
    has stopped answering must not look like a day already finished.
    """
    return ("(function() local ok, v = pcall(function() "
            "return %s:GetRemainAttackCount() end) "
            "if not ok or v == nil then return nil end "
            "local n = math.floor((v or 0) + 0) if n < 0 then n = 0 end return n end)()"
            % _CRYSTAL_MGR)


def crystal_attacks_max() -> str:
    """Lua *expression* -> how many attacks the day pays for (three, from the config)."""
    return ("(function() local ok, v = pcall(function() "
            "return %s:GetMaxAttackCount() end) "
            "if not ok or v == nil then return nil end "
            "return math.floor((v or 0) + 0) end)()" % _CRYSTAL_MGR)


def crystal_attacks_made() -> str:
    """Lua *expression* -> attacks already made today: the day's number minus what is left.

    Derived rather than read, because the client keeps no counter of its own for it —
    `transInfo.attackTimes` is a different thing entirely (it belongs to the crystal
    TRANSPORT, and it read 0 on a day whose three attacks had all been made).
    """
    return ("(function() local l = %s local n = %s "
            "if l == nil or n == nil then return nil end "
            "local m = n - l if m < 0 then m = 0 end return m end)()"
            % (crystal_attacks_left(), crystal_attacks_max()))


def crystal_can_attack() -> str:
    """Lua *expression* -> 1 while the client itself says an attack may be sent."""
    return ("(function() local ok, v = pcall(function() return %s:CanAttackBoss() end) "
            "if not ok then return nil end return (v and 1 or 0) end)()" % _CRYSTAL_MGR)


def crystal_targets() -> str:
    """Lua *expression* -> how many boss instances the client has on the map."""
    return ("(function() local ok, n = pcall(function() "
            "return %s:GetBossDataCount() end) "
            "if not ok or n == nil then return nil end "
            "return math.floor((n or 0) + 0) end)()" % _CRYSTAL_MGR)


def crystal_seconds_left() -> str:
    """Lua *expression* -> seconds left in the open window, or nil when none is open.

    The stage's `endTime` is in MILLISECONDS here — the same unit the server clock is
    read in — so the difference is divided before it is handed back. Codename's stage
    speaks seconds; the two are not the same manager and neither number is guessed.
    """
    return ("(function() local ok, st = pcall(function() "
            "return %s:GetAttackStageData() end) "
            "if not ok or type(st) ~= 'table' then return nil end "
            "local e = st.endTime if e == nil then return nil end "
            "e = e + 0 "
            "local now = (UITimeManager:GetInstance():GetServerTime() or 0) + 0 "
            "local left = (e - now) / 1000 if left < 0 then left = 0 end "
            "return math.floor(left) end)()" % _CRYSTAL_MGR)


def crystal_boss_health() -> str:
    """Lua *expression* -> the boss's health as a percentage of what it started with."""
    return ("(function() local ok, b = pcall(function() "
            "return %s:GetCurrentBoss() end) "
            "if not ok or type(b) ~= 'table' then return nil end "
            "local h, full = b.armyHealth, b.armyInitHealth "
            "if h == nil or full == nil then return nil end "
            "h, full = h + 0, full + 0 if full <= 0 then return nil end "
            "return math.floor(h * 100 / full) end)()" % _CRYSTAL_MGR)


def crystal_arm() -> str:
    """Set the attack up: the boss, a squad standing in the base, and the count before.

    All three before anything is sent, for the reason `codename_arm` does the same: a
    run that finds out at the send that there was no squad has already told the server
    it was coming.

    * `uuid` / `point` / `server` — out of `GetCurrentBoss()`. `startPos` is a ready-made
      map index on this manager (854849 on the live boss), and it is read through the
      shapes a position is known to take anyway, because a manager is not a promise.
    * `formation` — the FIRST squad standing in the base. A squad already marching,
      gathering, in a rally or wiped cannot be sent, and the game only says so at the
      last press.
    * `before` — attacks LEFT before the send, so the attack can be measured afterwards
      rather than assumed from a press that returned cleanly.
    """
    return (
        _CRYSTAL_PARAMS +
        "p.uuid, p.point, p.server, p.formation, p.squad = nil, nil, nil, nil, nil "
        "pcall(function() "
        "local b = %(mgr)s:GetCurrentBoss() "
        "if type(b) == 'table' then "
        "p.uuid = b.uuid "
        "pcall(function() if b.serverId ~= nil then p.server = b.serverId + 0 end end) "
        "local sp = b.startPos "
        "if type(sp) == 'table' then "
        "local x, y = sp.x, sp.y "
        "if x ~= nil and y ~= nil then p.point = math.floor(y + 0) * 1000 + math.floor(x + 0) "
        "elseif sp[1] ~= nil then p.point = sp[1] + 0 end "
        "elseif sp ~= nil then p.point = sp + 0 end "
        "end end) "
        "pcall(function() "
        "local best = nil "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "local idx = v.index and (v.index + 0) or nil "
        "local st = v.state and (v.state + 0) or nil "
        "local ok, idle = pcall(function() return v:IsFree() end) "
        "local free = true if ok and idle ~= nil then free = (idle and true or false) end "
        "if idx ~= nil and st == 0 and free and (best == nil or idx < best.idx) then "
        "best = {idx = idx, uuid = v.uuid} end end "
        "if best ~= nil then p.formation, p.squad = best.uuid, best.idx end end) "
        "p.before = %(left)s "
        "DataCenter.__lw_crystal = p "
        'CS.UnityEngine.Debug.LogError("ACT crystal_arm boss="..tostring(p.uuid)'
        '.." point="..tostring(p.point).." squad="..tostring(p.squad)'
        '.." formation="..tostring(p.formation).." left="..tostring(p.before))'
        % {"mgr": _CRYSTAL_MGR, "left": crystal_attacks_left()}
    )


def crystal_armed() -> str:
    """Lua *expression* -> what the arm found: 1 all set, 0 no boss, -1 no free squad."""
    return (
        "(function() " + _CRYSTAL_PARAMS +
        "if p.uuid == nil or p.point == nil then return 0 end "
        "if p.formation == nil then return -1 end return 1 end)()"
    )


def crystal_send() -> str:
    """Send the squad at the crystal boss — one call, no window, no camera flight.

    The same shape the «Кодовое имя» attack was read off the wire in (#1259), with this
    boss's own march type out of the client's own table:

        SendCreateMarchMessage(formation, DIRECT_ATTACK_RED_BOSS, point, uuid,
                               timeIndex = 1, autoBackHome = 1, needSoldier = false,
                               targetServerId = server, destroyTimeIndex = nil)

    `CROSS_DIRECT_ATTACK_RED_BOSS` when the boss stands on another server; the arm parks
    the boss's `serverId` so this can tell. Scheduled on the main thread through
    `TimerManager:DelayInvoke`, because a send from the hijack thread returns `true` and
    is dropped by the server.
    """
    return (
        _CRYSTAL_PARAMS +
        "if p.formation == nil or p.uuid == nil then error('nothing armed for this run') end "
        "local kind = MarchTargetType.DIRECT_ATTACK_RED_BOSS "
        "local home = nil pcall(function() home = LuaEntry.Player:GetSelfServerId() + 0 end) "
        "if p.server ~= nil and home ~= nil and (p.server + 0) ~= home then "
        "kind = MarchTargetType.CROSS_DIRECT_ATTACK_RED_BOSS end "
        "TimerManager:GetInstance():DelayInvoke(function() "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(p.formation, kind, p.point, p.uuid, "
        "1, 1, false, p.server, nil) end) "
        'CS.UnityEngine.Debug.LogError("ACT crystal_send ok="..tostring(ok).." err="..tostring(err)) '
        "end, 0.4) "
        'CS.UnityEngine.Debug.LogError("ACT crystal_send scheduled squad="..tostring(p.squad)'
        '.." boss="..tostring(p.uuid).." kind="..tostring(kind))'
    )


def crystal_sent() -> str:
    """Lua *expression* -> attacks spent since the arm ran. 1 once one has gone out.

    The DIFFERENCE between the count the arm noted and the count now, and it counts DOWN
    because this manager reports what is LEFT. The server owns the number, so this is
    the one thing that proves an attack was launched rather than merely pressed.

    **-1 is «the counter could not be read»**, and it is spelled out rather than folded
    into a zero: a client that has stopped answering would otherwise hand back the whole
    of `before` and read as an attack that went out.
    """
    return ("(function() local cur = %s "
            "if cur == nil then return -1 end "
            "return ((DataCenter.__lw_crystal or {}).before or 0) - cur end)()"
            % crystal_attacks_left())



# ---------------------------------------------------------------------------
# «Вход с другого устройства» — the kick, as the CLIENT shows it
# ---------------------------------------------------------------------------
# The game is single-session: logging the account in elsewhere kicks this client and
# puts a modal on it. CAUGHT LIVE on 2026-08-06 with the player kicking it on purpose
# while this polled twice a second — the whole recording, and the two guesses it
# disproved, is docs/research/session-kick.md.
#
# THE WINDOW IS `UICommonMessageTip`, and it is NOT `UIDisconnect` or
# `UICrossDisconnect` — those two exist, and stayed shut. Its `View.tipText` carries the
# message, word for word:
#
#     Внимание
#     В ваш аккаунт был выполнен вход с другого устройства     (the game's key E100083)
#
# AND IT IS INVISIBLE TO THE WINDOW STACK. The window sets `DontPushWindowStack`, so
# `GetStackTopWindow()` answers nil and `WindowStack` is empty with the modal plainly on
# screen. That is exactly how the earlier reading concluded «a kick leaves no trace in
# the client» — wrong accessor as well as wrong moment. `IsWindowOpen` is the only one
# that sees it.
#
# `UICommonMessageTip` is a GENERIC dialog and is not, by itself, proof of a kick — the
# client uses it for anything. While the question was asked ONLY on a lost link the pair
# was conclusive enough (a merely stranded client shows no window at all, watched live
# twice): lost link + a message tip with text = kicked.
#
# THAT PAIR IS NOT THE QUESTION ANY MORE (#1270). A kick can sit behind a link that reads
# `online` — one established socket out of six — so the flag is now asked on every poll
# and in front of every send, and on a healthy client «some dialog is open» would be a
# false kick, whose cure is a restart. So the expression hands back the TEXT and
# `tools/lib/game_kick.py` decides, by comparing it with the game's own wording for key
# `E100083` out of the client's own language tables. One reading, and the strength of
# the evidence is judged where the sentences are.

#: The client's OWN window for «this server is closed» — the game's name for the state,
#: found in its window table (`docs/research/ui-open-data/ui_window_names.json`) and
#: confirmed on a live client on 2026-08-26: `UIWindowNames.UIServerMaintenanceTip`
#: resolves, and `windowsConfig` has no entry for it while it has never been shown —
#: the class is built with the window, exactly as every other UI class here is.
#:
#: WHY IT IS BETTER THAN THE SENTENCE. A window name is the same in every language and
#: costs a flag rather than a comparison against nineteen locale tables. The text is
#: kept beside it because nobody has yet SEEN this window open: the state is rare, the
#: one recorded window (#1549) was watched from outside the client, and «the name exists»
#: is not «this is what the server opens». So both are read, in one round trip, and
#: whichever answers decides — with the reading written down when it fires
#: (`panel/runtime/status.py`), so the first real maintenance turns the guess into a
#: recording.
MAINTENANCE_WINDOW = "UIServerMaintenanceTip"


def maintenance_look() -> str:
    """Lua *expression* -> one line about the closed-door windows and the message tip.

    ``maint=0|1 login=0|1 disc=0|1 cross=0|1 tip=<the dialog's text>`` — the tip LAST,
    because it is the only field that can contain spaces.

    Four windows and one text in a single round trip (~90 ms), because the two
    questions the panel asks of a client it can drive — «has the account been taken»
    and «is the server shut» — are answered out of the same window table, and asking
    twice is a second trip for nothing.

    Answers `''` for anything it cannot read, so it can only ever ADD a reason.
    """
    return ("(function() local ok, v = pcall(function() "
            "local m = UIManager.Instance "
            "local function open(n) local o = false "
            "pcall(function() o = m:IsWindowOpen(n) end) return o and '1' or '0' end "
            "local t = '' "
            "if m:IsWindowOpen('UICommonMessageTip') then "
            "local w = m:GetWindow('UICommonMessageTip') "
            "local x = w and w.View and w.View.tipText "
            "t = x == nil and '' or tostring(x) end "
            "return 'maint=' .. open('%s') .. ' login=' .. open('UILogin') "
            ".. ' disc=' .. open('UIDisconnect') .. ' cross=' .. open('UICrossDisconnect') "
            ".. ' tip=' .. t end) "
            "if not ok then return '' end return v end)()" % MAINTENANCE_WINDOW)


def kick_tip() -> str:
    """Lua *expression* -> the text of the open message dialog, or '' if none is open.

    Both halves matter. `IsWindowOpen` first, because `GetWindow` hands back a window
    that has been CLOSED with its last text still on it — a stale sentence read off a
    shut dialog would be a kick that ended minutes ago. And the text rather than a flag,
    because the dialog is generic: the words are the only thing that tells a kick from
    every other message the client puts up (`tools/lib/game_kick.py`).

    Answers '' for anything it cannot read, so it can only ever ADD a reason, never
    remove one.
    """
    return ("(function() local ok, v = pcall(function() "
            "local m = UIManager.Instance "
            "if not m:IsWindowOpen('UICommonMessageTip') then return '' end "
            "local w = m:GetWindow('UICommonMessageTip') "
            "local t = w and w.View and w.View.tipText "
            "return t == nil and '' or tostring(t) end) "
            "if not ok then return '' end return v end)()")


# ---------------------------------------------------------------------------
# The keyboard macros: send the squad the game is ALREADY asking for (#1283)
# ---------------------------------------------------------------------------
# A person clicks a target on the map — a monster, a mine, another player's base,
# anything — presses the popup's action, and the game puts up the squad-selection
# screen. Everything the march needs is on that screen by then, and #1283 read it off
# a live client rather than guessing:
#
#     UIFormationSelectListV2  (or …New, depending on the `formation_v2_switch` config)
#         Ctrl.targetType      -- MarchTargetType: 7 rally, 11 attack a base, 1 a
#                                 monster, 2 gather, 6 join a rally, …
#         Ctrl.targetPoint     -- the target's tile index
#         Ctrl.targetUuid      -- the target's server uuid, which is what addresses it
#         Ctrl.targetServerId  -- whose server it stands on
#         Ctrl.timeIndex       -- the wait slot (a rally's countdown; 1 for a plain march)
#         Ctrl.autoBackHome    -- come back by itself
#         Ctrl.selectFormationUuid -- the squad the screen has highlighted
#
# The class is readable WITHOUT the window being open —
# `UIManager.Instance.windowsConfig[UIWindowNames.UIFormationSelectListV2].Ctrl` is the
# class table — which is how those names were found: `string.dump` on its `InitData`
# and `OnCreateClick` ([[project_lua_string_dump_decompile]]).
#
# Two different sends, on purpose:
#
#   * keys 1..4 press the screen's OWN launch button, `Ctrl:OnCheckTime(formation, nil)`
#     -> `OnCreateClick` -> `SendCreateMarchMessage`. The macro replaces the mouse and
#     nothing else, so every pre-check the game makes for that target type — stamina,
#     power warnings, the rally cap, the transport warning — still happens, and the
#     screen closes itself exactly as it does under a finger. This is the same press
#     `rally_launch` makes;
#   * CapsLock has no screen to press, so it sends `SendCreateMarchMessage` itself with
#     the arguments the last launch went out with, the way `codename_send` does.
#
# Both are parked in the game VM rather than in the panel: `TAP` carries no arguments,
# and the memory has to outlive the scenario that filled it.
#
#     DataCenter.__lw_macro      = {squad, formation, type, point, target, server,
#                                   timeIndex, back, need, before}
#     DataCenter.__lw_macro_last = the same, as the last launch actually sent it
#
# docs/research/march-hotkeys.md is the write-up.

#: How long a send waits before it leaves. It has to leave from the GAME's own thread —
#: one made on the hijack thread is created and dropped — so it is handed to the game's
#: timer, and this is the delay that buys. A third of a second was the first number tried
#: and it was never measured; on a key press it is a quarter of the whole budget, so it is
#: one tick now. What matters is the thread, not the wait (#1328).
_SEND_TICK = "0.05"

_MACRO = "local p = DataCenter.__lw_macro or {} "
_MACRO_LAST = "local m = DataCenter.__lw_macro_last or {} "

#: The two windows the squad screen can be — the same pair `_FORMATION_WIN` names for
#: the rally flow, found wherever it sits rather than only on top: a confirmation the
#: game puts over it must not read as "the person never opened one".
_MACRO_FIND = (
    "local function _findscreen() "
    "local m = UIManager.Instance "
    "local top = m:GetStackTopWindow() "
    "if top ~= nil and (top.Name == 'UIFormationSelectListV2' "
    "or top.Name == 'UIFormationSelectListNew') then return top end "
    "local found = nil "
    "for _, n in ipairs({'UIFormationSelectListV2', 'UIFormationSelectListNew'}) do "
    "pcall(function() if found == nil and m:IsWindowOpen(n) then found = m:GetWindow(n) end end) "
    "end return found end "
)


#: The click watcher (#1328). Two halves, both parked in the game's VM:
#:
#:   * `DataCenter.__lw_pick_read(ctrl)` — turn ONE world-point popup controller into a
#:     pin: the tile, the uuid, whose server it stands on, what kind of point it is, and
#:     — the part that decides everything — WHICH march the macro would send at it;
#:   * a wrapper around `UIWorldPointCtrl:InitData`, the method the popup fills itself in
#:     with. The class table is `UIManager.Instance.windowsConfig[UIWindowNames
#:     .UIWorldPoint].Ctrl` and every instance indexes into it, so wrapping it once
#:     catches every click there is — a finger on the map, `GoToUtil.OnClickWorldPoint`,
#:     a jump out of the magnifier — without the panel polling anything.
#:
#: THE KIND IS READ, NEVER GUESSED. `WorldPointUIType` and `MarchTargetType` are the
#: game's own enums, asked for BY NAME, so a season that renumbers them changes nothing
#: here. Four kinds are supported and the rest are refused by name in the log:
#:
#:     Monster / Boss  -> ATTACK_MONSTER, and only when the point's own monster detail
#:                        says `canAttack == 1`. `0` is a rally-only target, which is
#:                        raised through its own screen and never by this macro — the
#:                        same refusal `macro_repeat` has made since #1283;
#:     City            -> ATTACK_CITY, unless the base is the player's own;
#:     CollectPoint    -> COLLECT (a resource tile addresses by tile, `uuid` is 0);
#:     CollectArmy     -> ATTACK_ARMY_COLLECT (somebody else's squad, mid-gather).
#:
#: `GetMonsterData` MUST be passed the uuid — called bare it answers a one-field stub
#: with `canAttack = 0` and every monster reads as rally-only (world-monsters.md,
#: Finding 8). It is called here, at pin time, because the popup's controller is the only
#: thing that can answer it and it is gone by the time a key is pressed.
#: Bumped whenever the WRAPPER's own body changes, so an arming replaces the one a
#: long-running client already carries instead of quietly leaving it in place. The reader
#: needs no version — it is re-assigned every time.
_PICK_VER = 3

_PICK_READ = (
    "DataCenter.__lw_pick_read = function(s) "
    "local U = WorldPointUIType or {} local M = MarchTargetType or {} "
    "local p = {} "
    "pcall(function() p.point = tonumber(s.pointId) end) "
    "pcall(function() p.target = s.uuid end) "
    "pcall(function() p.kind = tonumber(s.type) end) "
    "pcall(function() p.server = tonumber(s.serverId) end) "
    "pcall(function() p.at = tonumber(UITimeManager:GetInstance():GetServerSeconds()) end) "
    "pcall(function() p.home = tonumber(LuaEntry.Player.serverId) end) "
    "pcall(function() p.who = tostring(LuaEntry.Player.uid) end) "
    "p.mine = 0 "
    "pcall(function() if tostring(s.ownerUid) == tostring(LuaEntry.Player.uid) "
    "then p.mine = 1 end end) "
    # WHO OPENED THIS POPUP — the person, or the panel? The bot opens world-point popups
    # of its own all day (a rally hunt, a treasure sweep, a jump to coordinates), and a
    # WHO OPENED THIS POPUP CANNOT BE ASKED, and two live sessions were spent finding that
    # out. The idea was that a scripted open would leave a `[string "…"]` frame on the
    # stack while a finger would not, so an errand's sightseeing could be told from a
    # person's click. It cannot: `InitData` does not run inside the opener at all. The
    # stack at a real one, read live, has no `GoToUtil` in it —
    #
    #     1:[string "chunk"]  2:[C]  3:[string "chunk"]   <- this watcher, always
    #     4:…/UI/UIWorldPoint/View/UIWorldPointView.lua
    #     5,7,8:…/Framework/UI/UIManager.lua
    #
    # — because the point's detail is fetched from the server and the window is filled in
    # when the REPLY lands, by which time whoever asked has long returned. So the test read
    # «scripted» off its own two frames and answered that to everything, a finger included,
    # and since a scripted open was not kept the pin froze on whatever got in first: the
    # person clicked elsewhere all day and the key kept marching on the original target.
    #
    # So EVERY open is recorded and the PRESS decides. That is the safe way round: a pin
    # that always mirrors the last point opened can be refused by kind, while a pin that
    # sometimes refuses to move is a squad marching at a target nobody chose any more.
    # What the errands open — a secret task, a treasure, a ghost tile, a rally-only elite —
    # is refused by the press in its own words; what a person clicks is marched on.
    "p.can = -1 "
    "for n, v in pairs(U) do if tonumber(v) == p.kind then p.kindname = tostring(n) end end "
    "if p.kind ~= nil and (p.kind == U.Monster or p.kind == U.Boss) then "
    # A monster whose detail cannot be read at all is a monster that needs a banner, not
    # an unknown kind of point: `0` before the call, so a failed read refuses with the
    # sentence that fits rather than with «the macro does not march on that».
    "p.can = 0 "
    "pcall(function() local md = s:GetMonsterData(s.uuid) "
    "p.can = tonumber(md and md.canAttack) or 0 end) "
    "if p.can == 1 then p.mtt = tonumber(M.ATTACK_MONSTER) end "
    "elseif p.kind ~= nil and p.kind == U.City then "
    "if p.mine == 0 then p.mtt = tonumber(M.ATTACK_CITY) end "
    "elseif p.kind ~= nil and p.kind == U.CollectPoint then "
    "p.mtt = tonumber(M.COLLECT) "
    "elseif p.kind ~= nil and p.kind == U.CollectArmy then "
    "p.mtt = tonumber(M.ATTACK_ARMY_COLLECT) end "
    "if p.point ~= nil then local _y = math.floor(p.point / 1000) "
    "p.desc = tostring(p.kindname) .. ' @[' .. tostring(p.point - _y * 1000) "
    ".. ',' .. tostring(_y) .. '|' .. tostring(p.server or p.home) .. ']' end "
    # THE READER KEEPS THE PIN, and not the wrapper, for a reason that only shows up on a
    # client that is already running: a wrapper is installed ONCE and stays, so a fix that
    # lives in the wrapper never reaches a client wrapped by yesterday's panel — and
    # re-wrapping would only put the old body underneath the new one, still overwriting.
    # The reader is re-assigned by every arming, so this is where a correction can land.
    "if p.point ~= nil then DataCenter.__lw_macro_pick = p end "
    "return p end "
)

#: Wrap `InitData` once and leave it wrapped. The original is kept on the class under a
#: name of ours, which is also the flag that says it has been done — a second arming is
#: a no-op rather than a wrapper around a wrapper. The reader above is re-assigned every
#: time regardless, so a client that was armed by an older panel picks up a fixed one.
#:
#: The original runs FIRST and unprotected: `InitData` is what fills the popup in, and a
#: popup that opened blank because a macro was listening would be a far worse bug than
#: any this file fixes. Everything of ours is inside `pcall`, and its return values are
#: handed back untouched.
_PICK_ARM = _PICK_READ + (
    "pcall(function() "
    "local cfg = UIManager.Instance.windowsConfig[UIWindowNames.UIWorldPoint] "
    "local cls = cfg and cfg.Ctrl "
    "if cls == nil then return end "
    # A WRAPPER IS UPGRADABLE, and it has to be: a client runs for days and the panel is
    # restarted several times a day, so «installed once, for ever» meant a client kept
    # yesterday's wrapper whatever the code said — and wrapping the wrapper only leaves
    # the old body underneath, still doing the old thing. The version is the flag: a
    # different one puts the GAME's own method back first, then wraps that.
    "if rawget(cls, '__lw_pick_orig') ~= nil then "
    "if rawget(cls, '__lw_pick_ver') == %(ver)d then return end "
    "cls.InitData = cls.__lw_pick_orig cls.__lw_pick_orig = nil end "
    "local orig = cls.InitData "
    "if type(orig) ~= 'function' then return end "
    "cls.__lw_pick_orig = orig cls.__lw_pick_ver = %(ver)d "
    "cls.InitData = function(s, ...) "
    "local r = table.pack(orig(s, ...)) "
    # A SCRIPTED OPEN IS NOT RECORDED AT ALL, and the first live session is why (#1328).
    # It used to be recorded and refused at press time, which read fine in a test and was
    # useless in a game: the panel opens world-point popups every few seconds (a treasure
    # sweep, a secret-task scan, a rally hunt), so a person's click survived about ten
    # seconds before an errand overwrote it and every key from then on answered «эту точку
    # открыла панель». One press worked and nothing after it. The pin now belongs to the
    # person: only a click writes it, and an errand's sightseeing goes past unrecorded.
    "pcall(function() DataCenter.__lw_pick_read(s) end) "
    "return table.unpack(r, 1, r.n) end "
    "end) "
) % {"ver": _PICK_VER}

#: The popup itself, wherever it sits — the same shape `_MACRO_FIND` uses for the squad
#: screen, and for the same reason: a confirmation the game puts over it must not read
#: as «there is nothing open».
_PICK_FIND = (
    "local function _findpopup() "
    "local m = UIManager.Instance "
    "local top = m:GetStackTopWindow() "
    "if top ~= nil and top.Name == 'UIWorldPoint' then return top end "
    "local found = nil "
    "pcall(function() if m:IsWindowOpen('UIWorldPoint') then "
    "found = m:GetWindow('UIWorldPoint') end end) "
    "return found end "
)


def macro_pick_arm() -> str:
    """Lua *statement* -> arm the click watcher, and say nothing if it already is.

    Cheap enough to run in front of every key press, which is where it runs: `macro_send`
    starts with it, so a client that restarted between two presses is watched again
    without anybody noticing. See :data:`_PICK_ARM` for what it wraps and why.
    """
    return _PICK_ARM


def macro_pick_result() -> str:
    """Lua *expression* -> the pinned target's kind, as the game names it, `?` if none."""
    return "tostring((DataCenter.__lw_macro_pick or {}).kindname or '?')"


def macro_pick_desc() -> str:
    """Lua *expression* -> what the last press aimed at, in words. `-` when it aimed at
    the open squad screen instead, because that target was never a pin."""
    return "tostring((DataCenter.__lw_macro or {}).desc or '-')"


def own_march_count() -> str:
    """Lua *expression* -> how many marches of ours are out right now, -1 if unreadable.

    The proof a macro really sent something. A press that returned cleanly proves the
    call ran; this is the number the SERVER moves, and it moves for a march of any kind
    — an attack, a gather, a rally — which is exactly the range of targets a macro is
    pointed at. `own_rally_count()` above counts the subset that is part of a rally.
    """
    return (
        "(function() local ok, n = pcall(function() "
        "local om = DataCenter.WorldMarchDataManager:GetOwnerMarches() local c = 0 "
        "if om then local e = om:GetEnumerator() while e:MoveNext() do c = c + 1 end end "
        "return c end) if not ok then return -1 end return n end)()"
    )


def macro_send() -> str:
    """Send the chosen squad at whatever the person last chose, in ONE call (#1290/#1328).

    Two ways to a target, tried in that order inside one chunk:

    1. **The squad screen, if one is open** — the #1283 path, unchanged. Everything the
       march needs is on that screen, the launch is the game's own `Ctrl:OnCheckTime`, and
       the macro replaces the MOUSE and nothing else.
    2. **The target the person CLICKED, if no screen is open** (#1328). The click watcher
       (:data:`_PICK_ARM`) pinned it the moment the map tap opened its popup, so the send
       goes out with no window at all — the shape `macro_repeat` has been proving since
       #1283. If nothing is pinned but the popup is still open, it is read on the spot:
       that covers the very first press after a client restart, when the watcher was
       armed a moment too late to have seen the click.

    The order is deliberate. A person who has opened the squad screen went that way on
    purpose, and the screen's own target is both fresher and more complete (a rally's wait
    slot is a field of the screen, not of the tile).

    WHAT IT DECIDED lands in `DataCenter.__lw_macro.result`, which the recipe reads back
    (`macro_result`) to say WHICH of the two, or WHICH refusal:

    ``1`` the open screen's launch was pressed · ``2`` the pinned target was marched on
    directly · ``0`` no screen and nothing clicked · ``-1`` the game has no squad with
    that number · ``-2`` the screen is open and its target could not be read · ``-3`` the
    screen's own launch raised · ``-4`` the pin is older than the run allows · ``-5`` the
    macro does not march on that kind of point · ``-6`` the pinned monster is rally-only ·
    ``-7`` the player is not on the world map any more · ``-8`` the pin belongs to another
    account or another home server.

    (There was a ``-9`` — «the panel opened this, not you» — and it is gone: which of the
    two opened a popup is not a question the client can answer, see :data:`_PICK_READ`.
    Nothing reuses the number, so a log line from an older panel still reads true.)

    The pin is NOT consumed by a successful send, on purpose: three keys in a row put
    three squads on one target, which is what a person clicking a boss wants. What ends it
    is time, the scene, and the account — never the panel's own bookkeeping.

    NOTHING ASKS THE SCREEN WHETHER THE MARCH NEEDS SOLDIERS. `NeedTakeArmy` called bare
    answers `true`, the send then goes out with `needSoldier = true`, and the server
    accepts the call and creates no march — an afternoon of #1283 went into that. The
    direct send passes `false` for the same reason, as every proven send here does.
    """
    return (
        _MACRO + _MACRO_FIND + _PICK_FIND + _PICK_ARM +
        "p.type, p.point, p.target, p.server = nil, nil, nil, nil "
        "p.timeIndex, p.back, p.formation, p.err = nil, nil, nil, nil "
        "p.desc, p.age, p.kind, p.prev, p.say = nil, nil, nil, nil, nil "
        "p.result = 0 "
        "(function() "
        "local w = _findscreen() "
        "p.screen = (w ~= nil) and 1 or 0 "
        "if w ~= nil then "
        "local c = w.Ctrl "
        "pcall(function() p.type = tonumber(c.targetType) end) "
        "pcall(function() p.point = tonumber(c.targetPoint) end) "
        "pcall(function() p.target = c.targetUuid end) "
        "pcall(function() p.server = tonumber(c.targetServerId) end) "
        "pcall(function() p.timeIndex = tonumber(c.timeIndex) end) "
        "pcall(function() p.back = tonumber(c.autoBackHome) end) "
        "pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if tonumber(v.index) == tonumber(p.squad) then p.formation = v.uuid end end end) "
        "if p.target == nil or p.type == nil then p.result = -2 return end "
        "if p.formation == nil then p.result = -1 return end "
        "p.before = %(count)s "
        "DataCenter.__lw_macro_last = {squad = p.squad, formation = p.formation, "
        "type = p.type, point = p.point, target = p.target, server = p.server, "
        "timeIndex = p.timeIndex, back = p.back, before = p.before} "
        "pcall(function() w.View:OnSelectClick(p.formation) end) "
        "pcall(function() w.Ctrl:SetSelectFormationUuid(p.formation) end) "
        "local ok, err = pcall(function() w.Ctrl:OnCheckTime(p.formation, nil) end) "
        "if not ok then p.result = -3 p.err = tostring(err) return end "
        "p.result = 1 return end "
        # --- no screen: the target the person's own click pinned ---------------
        "local q = DataCenter.__lw_macro_pick "
        "if q == nil or q.point == nil then "
        "local pop = _findpopup() "
        # A popup standing open at the moment of the key press is the strongest evidence
        # of what is chosen there is — and the reader keeps it, so the next press has it
        # too.
        "if pop ~= nil then pcall(function() "
        "q = DataCenter.__lw_pick_read(pop.Ctrl) end) end end "
        "if q == nil or q.point == nil then p.result = 0 return end "
        "p.desc, p.kind = q.desc, q.kindname "
        "local now = 0 "
        "pcall(function() now = tonumber(UITimeManager:GetInstance():GetServerSeconds()) or 0 end) "
        "p.age = (q.at ~= nil and now > 0) and (now - q.at) or 0 "
        "local inworld = false "
        "pcall(function() inworld = SceneUtils.GetIsInWorld() and true or false end) "
        "local who = '' pcall(function() who = tostring(LuaEntry.Player.uid) end) "
        "local home = 0 pcall(function() home = tonumber(LuaEntry.Player.serverId) or 0 end) "
        "if (q.who ~= nil and q.who ~= who) or (q.home ~= nil and tonumber(q.home) ~= home) "
        "then p.result = -8 return end "
        "if not inworld then p.result = -7 return end "
        "if p.age > (tonumber(p.stale) or 180) then p.result = -4 return end "
        "if q.can == 0 then p.result = -6 return end "
        "if q.mtt == nil then p.result = -5 return end "
        "pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if tonumber(v.index) == tonumber(p.squad) then p.formation = v.uuid end end end) "
        "if p.formation == nil then p.result = -1 return end "
        "p.type, p.point, p.target = q.mtt, q.point, q.target or 0 "
        "p.server, p.timeIndex, p.back = q.server or home, 1, 1 "
        "p.before = %(count)s "
        # WHAT THE LAST PRESS ACHIEVED, read here rather than waited for there. The recipe
        # used to stand and count marches for up to seven seconds after a send, holding
        # the game claim — and every key pressed in that window was refused with «занят»,
        # which is «the macro works once» from the other side (#1328, seen live). So the
        # verdict on a send arrives with the NEXT press, off the count the previous one
        # wrote down, and costs nothing.
        "local _L = DataCenter.__lw_macro_last "
        "if _L ~= nil and _L.pin == 1 and _L.before ~= nil then "
        "p.prev = p.before - _L.before end "
        "DataCenter.__lw_macro_last = {squad = p.squad, formation = p.formation, "
        "type = p.type, point = p.point, target = p.target, server = p.server, "
        "timeIndex = p.timeIndex, back = p.back, before = p.before, pin = 1} "
        "p.say = tostring(p.desc) "
        "if p.prev ~= nil then p.say = p.say .. ' (previous press: ' .. "
        "(p.prev >= 1 and 'a march went out' or 'no march appeared') .. ')' end "
        # THE SEND CARRIES ITS OWN COPY, and that is not tidiness. `p` IS
        # `DataCenter.__lw_macro`, one table shared by every press, and the send is late
        # by a tick on purpose (a cold one, made on the hijack thread, is created and
        # dropped — it has to leave from the game's own). Three keys in a row on one boss —
        # the thing this recipe is FOR — would otherwise have the second press overwrite
        # the squad the first one was about to march with.
        "local _f, _t, _pt, _tg, _sv = p.formation, p.type, p.point, p.target, p.server "
        "TimerManager:GetInstance():DelayInvoke(function() "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(_f, _t, _pt, _tg, 1, 1, false, _sv, nil) end) "
        'CS.UnityEngine.Debug.LogError("ACT macro_send pinned ok="..tostring(ok)'
        '.." err="..tostring(err)) '
        "end, %(tick)s) "
        "pcall(function() local pop = _findpopup() "
        "if pop ~= nil and pop.Ctrl and pop.Ctrl.CloseSelf then pop.Ctrl:CloseSelf() end end) "
        "p.result = 2 "
        "end)() "
        "DataCenter.__lw_macro = p "
        'CS.UnityEngine.Debug.LogError("ACT macro_send squad="..tostring(p.squad)'
        '.." result="..tostring(p.result).." screen="..tostring(p.screen)'
        '.." type="..tostring(p.type).." point="..tostring(p.point)'
        '.." target="..tostring(p.target).." server="..tostring(p.server)'
        '.." kind="..tostring(p.kind).." age="..tostring(p.age)'
        '.." formation="..tostring(p.formation).." marches="..tostring(p.before)'
        '.." err="..tostring(p.err))'
        % {"count": own_march_count(), "tick": _SEND_TICK}
    )


def macro_result() -> str:
    """Lua *expression* -> what :func:`macro_send` decided. See it for the five values."""
    return "(tonumber((DataCenter.__lw_macro or {}).result) or 0)"


def macro_sent() -> str:
    """Lua *expression* -> marches gained since `macro_send()` ran. 1 once one is out."""
    return "((%s) - ((DataCenter.__lw_macro or {}).before or 0))" % own_march_count()


def macro_repeat_ready() -> str:
    """Lua *expression* -> whether the last macro march can be sent again as it stands.

    ``1`` yes · ``0`` nothing has been sent by a macro yet · ``-1`` the last one was a
    RALLY, and a rally is not repeatable this way.

    The same three answers :func:`macro_repeat` now parks in `result` — this is the
    reading with nothing sent, kept for a caller that wants to ASK (a tab showing what
    CapsLock would do). CapsLock itself does not ask first any more (#1290): asking cost
    a whole round trip in front of a key press, and the refusal has to be made inside the
    send's own chunk regardless.

    The rally case is not squeamishness. A banner is raised through the squad screen's
    own launch, which fills in a wait slot and a disband time the screen owns; the plain
    `SendCreateMarchMessage` this key makes has never been proven for a rally type, and
    the one time #1283 tried it live the client went down mid-run. Nothing pins that
    crash on the send — but «unproven» plus «the client restarted while it ran» is not a
    thing to keep pointing at somebody's account, and re-raising a banner is not what
    «повторить последний марш» is for anyway.

    `MarchUtil.IsRallyMarch` is the GAME's own answer to «is this a rally type», which
    is better than a list of numbers copied out of an enum that grows every season.
    """
    return (
        "(function() " + _MACRO_LAST +
        "if m.formation == nil or m.target == nil or m.type == nil then return 0 end "
        "local rally = false "
        "pcall(function() rally = MarchUtil.IsRallyMarch(m.type) and true or false end) "
        "if rally then return -1 end "
        "return 1 end)()"
    )


def macro_repeat() -> str:
    """Send the last macro march again — same squad, same target, and no window at all.

    The whole point of the key: the screen is not opened, the camera is not moved and
    the target is not clicked. It is the send `macro_send` ends at, made directly with
    the arguments that went out last time — the shape `codename_send` proved: the target
    is addressed by uuid, so the server works the path out for itself.

    Scheduled through `TimerManager:DelayInvoke` for the reason every launch in this
    file is: a cold send is created and dropped.

    IT DECIDES FOR ITSELF, AND PARKS THE ANSWER (#1290). The recipe used to ask
    `macro_repeat_ready` first and only then press — a round trip in front of a key
    press, for a question this chunk has to answer again anyway. So the gate is here,
    and `result` says which of the three happened:

    ``1`` the send is scheduled · ``0`` nothing has been sent by a macro yet ·
    ``-1`` the last one was a RALLY.

    The rally refusal is not squeamishness. A banner is raised through the squad screen's
    own launch, which fills in a wait slot and a disband time the screen owns; the plain
    `SendCreateMarchMessage` this key makes has never been proven for a rally type, and
    the one time #1283 tried it live the client went down mid-run. `MarchUtil.IsRallyMarch`
    is the GAME's own answer, so a rally type added next season is covered without
    anybody copying an enum.
    """
    return (
        _MACRO_LAST +
        "m.result = 0 "
        "(function() "
        "if m.formation == nil or m.target == nil or m.type == nil then return end "
        "local rally = false "
        "pcall(function() rally = MarchUtil.IsRallyMarch(m.type) and true or false end) "
        "if rally then m.result = -1 return end "
        # WHAT THE LAST REPEAT ACHIEVED, read here rather than waited for there — the same
        # deferral the clicked path makes, and for the same measured reason (#1328). The
        # recipe used to stand and count marches for three and a half seconds after this
        # send, holding the game claim: measured live, `TAP=+0.08 … end=+3.42`, of which
        # everything past `+0.2` was the poll. That is the whole of the «CapsLock reacts
        # after three seconds» the person felt, and the next press waited behind it too.
        "local _was = m.before "
        "m.before = %(count)s "
        "if _was ~= nil then m.prev = m.before - _was end "
        "TimerManager:GetInstance():DelayInvoke(function() "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(m.formation, m.type, m.point, m.target, "
        "m.timeIndex or 1, m.back or 1, false, m.server, nil) end) "
        'CS.UnityEngine.Debug.LogError("ACT macro_repeat ok="..tostring(ok).." err="..tostring(err)) '
        "end, %(tick)s) "
        "m.result = 1 "
        "end)() "
        "m.say = tostring(m.squad) "
        "if m.prev ~= nil then m.say = m.say .. ' (previous press: ' .. "
        "(m.prev >= 1 and 'a march went out' or 'no march appeared') .. ')' end "
        "DataCenter.__lw_macro_last = m "
        'CS.UnityEngine.Debug.LogError("ACT macro_repeat scheduled squad="..tostring(m.squad)'
        '.." result="..tostring(m.result).." type="..tostring(m.type)'
        '.." target="..tostring(m.target).." marches="..tostring(m.before))'
        % {"count": own_march_count(), "tick": _SEND_TICK}
    )


def macro_repeat_result() -> str:
    """Lua *expression* -> what :func:`macro_repeat` decided. See it for the three values."""
    return "(tonumber((DataCenter.__lw_macro_last or {}).result) or 0)"


def macro_repeat_say() -> str:
    """Lua *expression* -> the squad CapsLock just sent, and how the previous one went.

    The verdict on a repeat arrives with the NEXT press rather than being waited for: a
    run holds the game claim, and the three and a half seconds this used to spend counting
    marches were three and a half seconds of «занят» for the key behind it (#1328).
    """
    return "tostring((DataCenter.__lw_macro_last or {}).say or '-')"


def macro_repeat_sent() -> str:
    """Lua *expression* -> marches gained since `macro_repeat()` scheduled its send.

    Kept for a caller that wants to ASK — the recipe does not, any more (see
    :func:`macro_repeat_say`)."""
    return ("((%s) - ((DataCenter.__lw_macro_last or {}).before or 0))"
            % own_march_count())


def macro_last_squad() -> str:
    """Lua *expression* -> the squad number of the last macro march, 0 if there is none."""
    return "(tonumber((DataCenter.__lw_macro_last or {}).squad) or 0)"


# ---------------------------------------------------------------------------
# «Найм» — the recruit banners: heroes and survivors, x1 / x10 / x100
# ---------------------------------------------------------------------------
# Two messages, both read off a live trace of the player pulling by hand (run
# 20260813_103441, «найм героев») and then confirmed field by field in the VM:
#
#     --> lottery.hero.card    {id (string), isTen (int), useFree (int)}  + the cost item
#     --> lottery.worker.card  {useFree (int), isTen (int), officerId (int)}
#
# `isTen` IS NOT A FLAG. The trace only ever carried 0 and 1 — a single pull and a ten —
# so a x100 button had nothing to send. The client's own enum answers it:
# `UIHeroMultiRecruitType = { Ten = 1, OneHundred = 2 }`, and the view picks the value
# with it (`UIHeroRecruitView.ExecuteMultiRecruitAction`, read with `string.dump`). So
# the field is a SIZE — 0 single, 1 ten, 2 hundred — and the hundred is derived from the
# game's own table rather than guessed off two samples.
#
# THE FREE PULL IS THE GAME'S ANSWER, never a count kept here. Both banners have one and
# they are not the same shape: a hero banner refreshes its free pull daily
# (`LotteryInfo:IsSupportFreeRecruit()` / `:CanFreeRecruit()`, `dailyFreeNextFreshTime`),
# and the survivors' one runs on a timer of its own
# (`WorkerLotteryInfo:CanFreeRecruit()`, `nextFreeTime`). Both gates are CALLED rather
# than reimplemented: the client compares its own clock its own way, and a copy of that
# arithmetic here is one build away from disagreeing with what the person sees.
#
# The reverse-engineering, the fields and what each one meant live, is
# docs/research/recruit-draw.md.

#: How a count maps onto the wire's `isTen` — the client's own `UIHeroMultiRecruitType`.
RECRUIT_SIZES = {1: 0, 10: 1, 100: 2}

#: The two banners this ability knows, as the scenario spells them.
RECRUIT_KINDS = ("hero", "worker")

# The Lua that finds the hero banner to pull on. `DataCenter.__lw_recruit_lottery` names
# one when the caller picked it; otherwise the first of the client's own current recruit
# ids that actually resolves — the list carries ids whose banner has not been loaded, and
# those answer `nil` rather than an empty banner.
_RECRUIT_HERO_INFO = (
    "local function heroInfo() "
    "local M = DataCenter.LotteryDataManager "
    "local want = tostring(DataCenter.__lw_recruit_lottery or '') "
    "if want ~= '' then "
    "local ok, v = pcall(function() return M:GetLotteryDataById(want) end) "
    "if ok and v ~= nil then return v, want end "
    "ok, v = pcall(function() return M:GetLotteryDataById(tonumber(want)) end) "
    "if ok and v ~= nil then return v, want end "
    "return nil, want end "
    "for _, id in pairs(M.curRecruitIdList or {}) do "
    "local ok, v = pcall(function() return M:GetLotteryDataById(id) end) "
    "if ok and v ~= nil then return v, tostring(id) end end "
    "return nil, '' end "
)

# …and the survivors' one, which the client keeps as a single banner: the config row in
# `LotteryDataManager` (the officer id the message carries) and the account's own data
# (`WorkerLotteryDataManager`) with the free timer on it.
_RECRUIT_WORKER_INFO = (
    "local function workerInfo() "
    "local M = DataCenter.LotteryDataManager "
    "local cfg, wl = nil, nil "
    "pcall(function() cfg = M:GetOnlyWorkerLotteryData() end) "
    "pcall(function() wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) "
    "return wl, cfg end "
)

# A cost is a pair {itemId, itemNum}: `GetCostItems()` holds the single and the ten,
# `recruit100CostInfo` the hundred. Everything is wrapped, so a banner that is missing a
# hundred costs one zero rather than the whole reading.
_RECRUIT_COST = (
    # THE TICKET ID IS A STRING AND STAYS ONE. The client keeps `itemId` as text and the
    # message puts it on the wire with `PutUtfString`, so a `tonumber()` on the way past
    # — the obvious tidy-up — makes the client's own serializer throw «attempt to get
    # length of a number value» and NOTHING leaves. Caught on the first live pull; the
    # same value read back as a string sent cleanly. `GetItemById` takes it either way.
    "local function costOf(info, size) "
    "local id, num = '', 0 "
    "pcall(function() "
    "if size == 2 then local c = info:GetHundredCost() "
    "if c ~= nil then id = c.itemId num = tonumber(c.itemNum) or 0 end "
    "else local list = info:GetCostItems() or {} local c = list[size + 1] "
    "if c ~= nil then id = c.itemId num = tonumber(c.itemNum) or 0 end end "
    "end) return id, num end "
    "local function have(itemId) local n = 0 "
    "pcall(function() local it = DataCenter.ItemData:GetItemById(itemId) "
    "n = tonumber(it and it.count) or 0 end) return n end "
)

# The free pull, asked of the game and normalised. `free` is the client's own answer,
# `next` is when it comes back — in epoch SECONDS whichever unit the banner keeps it in
# (the hero one counts seconds, the survivors' one milliseconds).
_RECRUIT_FREE = (
    "local function secs(v) local n = tonumber(v) or 0 "
    "if n > 100000000000 then n = n / 1000 end return math.floor(n) end "
)


def recruit_state() -> str:
    """Lua *expression* -> one line saying what both banners can do right now.

    ``now=<server seconds> | hero id=… support=1 free=0 next=… item=… have=… c1=1
    c10=10 c100=100 total=… limit=… | worker id=… support=1 free=1 next=0 item=…
    have=… c1=1 c10=10 c100=100``

    * ``support`` — has this banner a free pull at all (a hero banner may not);
    * ``free``    — is it available THIS MOMENT, the client's own gate;
    * ``next``    — when it comes back, epoch seconds; ``0`` when it is available now;
    * ``item`` / ``have`` — the ticket the pulls are paid in and how many are held;
    * ``c1`` / ``c10`` / ``c100`` — what one, ten and a hundred cost in that ticket;
    * ``total`` / ``limit`` — pulls made on the hero banner and its ceiling, ``0`` when
      the banner does not keep one.

    A banner the client cannot answer for is left out of the line entirely, which is how
    «the client is not logged in» tells itself apart from «no free pull today».
    """
    return (
        "(function() "
        + _RECRUIT_HERO_INFO + _RECRUIT_WORKER_INFO + _RECRUIT_COST + _RECRUIT_FREE +
        "local out = {} "
        "local now = 0 pcall(function() now = math.floor(tonumber("
        "UITimeManager:GetInstance():GetServerSeconds()) or 0) end) "
        "out[#out+1] = 'now='..now "
        "local hi, hid = heroInfo() "
        "if hi ~= nil then "
        "local sup, free = 0, 0 "
        "pcall(function() sup = hi:IsSupportFreeRecruit() and 1 or 0 end) "
        "pcall(function() free = hi:CanFreeRecruit() and 1 or 0 end) "
        "local nxt = 0 if free == 0 and sup == 1 then nxt = secs(hi.dailyFreeNextFreshTime) end "
        "local id1, n1 = costOf(hi, 0) local _, n10 = costOf(hi, 1) local _, n100 = costOf(hi, 2) "
        "local total, limit = 0, 0 "
        "pcall(function() total = math.floor(tonumber(hi.totalLottery) or 0) end) "
        "pcall(function() limit = math.floor(tonumber(hi.totalLotteryLimit) or 0) end) "
        "out[#out+1] = 'hero id='..hid..' support='..sup..' free='..free..' next='..nxt"
        "..' item='..id1..' have='..have(id1)..' c1='..n1..' c10='..n10..' c100='..n100"
        "..' total='..total..' limit='..limit end "
        "local wl, wcfg = workerInfo() "
        "if wl ~= nil then "
        "local free = 0 pcall(function() free = wl:CanFreeRecruit() and 1 or 0 end) "
        "local nxt = 0 if free == 0 then nxt = secs(wl.nextFreeTime) end "
        "local id1, n1 = costOf(wl, 0) local _, n10 = costOf(wl, 1) "
        "local n100 = 0 "
        "pcall(function() local c = wcfg and wcfg.recruit100CostInfo "
        "if c ~= nil then n100 = tonumber(c.itemNum) or 0 end end) "
        "local wid = 0 pcall(function() wid = math.floor(tonumber(wcfg and wcfg.id) or 0) end) "
        "out[#out+1] = 'worker id='..wid..' support=1 free='..free..' next='..nxt"
        "..' item='..id1..' have='..have(id1)..' c1='..n1..' c10='..n10..' c100='..n100 end "
        "return table.concat(out, ' | ') end)()"
    )


def tavern_free_pulls() -> str:
    """Lua *expression* -> how many free pulls the tavern is offering RIGHT NOW.

    Every hero banner the client is currently showing carries a free pull on a clock of
    its own, and the survivors' banner carries one more (docs/research/recruit-draw.md
    §3), so the answer is how many banners answer yes to their OWN `CanFreeRecruit()` —
    the client's gate, called and never re-implemented, exactly as
    `actions/tavern_free_pull.md` calls it before each pull it takes.

    `nil` — a dash, never a zero — when no banner answers at all. A client that is not
    logged in says «no free pull» to every question with a perfectly straight face
    (#1227), and drawn as a zero that reads as «сегодня всё забрано».
    """
    return ("(function() local M = DataCenter.LotteryDataManager "
            "if M == nil then return nil end "
            "local seen, free = 0, 0 "
            "pcall(function() for _, id in pairs(M.curRecruitIdList or {}) do "
            "local v = nil "
            "pcall(function() v = M:GetLotteryDataById(id) end) "
            "if v == nil then pcall(function() "
            "v = M:GetLotteryDataById(tostring(id)) end) end "
            "if v ~= nil then seen = seen + 1 "
            "local ok = false "
            "pcall(function() ok = v:CanFreeRecruit() and true or false end) "
            "if ok then free = free + 1 end end end end) "
            "local wl = nil pcall(function() "
            "wl = DataCenter.WorkerLotteryDataManager:GetWorkerLotteryData() end) "
            "if wl ~= nil then seen = seen + 1 "
            "local ok = false "
            "pcall(function() ok = wl:CanFreeRecruit() and true or false end) "
            "if ok then free = free + 1 end end "
            "if seen == 0 then return nil end return free end)()")


def recruit_draw() -> str:
    """Pull on the banner parked in ``DataCenter.__lw_recruit_*`` — one message, no window.

    The caller parks three things first (``recruit_draw.md`` does it in one `LUA` line,
    the way `join_rally.md` parks its squads — a `TAP` carries no arguments of its own):

    * ``__lw_recruit_kind``    — ``hero`` or ``worker``;
    * ``__lw_recruit_count``   — ``1``, ``10`` or ``100``;
    * ``__lw_recruit_free``    — ``auto`` (spend the free pull when there is one and the
      count is 1), ``no`` (never), ``only`` (send NOTHING unless the pull is free);
    * ``__lw_recruit_lottery`` — which hero banner, empty for the one the client shows.

    **Every refusal is loud** (`docs/skills/sniff.md` §8.0a): the ticket count is checked
    against the game's own cost before anything leaves, and a pull that cannot be paid
    for writes why into ``__lw_recruit_report`` and sends nothing, rather than being
    refused by the server in a tip nobody reads.
    """
    return (
        _RECRUIT_HERO_INFO + _RECRUIT_WORKER_INFO + _RECRUIT_COST +
        "DataCenter.__lw_recruit_sent = 0 "
        "DataCenter.__lw_recruit_report = '' "
        "DataCenter.__lw_recruit_before = nil "
        "local kind = tostring(DataCenter.__lw_recruit_kind or 'hero') "
        "local count = math.floor(tonumber(DataCenter.__lw_recruit_count) or 1) "
        "local want = tostring(DataCenter.__lw_recruit_free or 'auto') "
        "local sizes = {[1] = 0, [10] = 1, [100] = 2} "
        "local size = sizes[count] "
        "if size == nil then "
        "DataCenter.__lw_recruit_report = 'count='..count..' is not 1, 10 or 100 — nothing sent' "
        "return end "
        "local info, cfg, id = nil, nil, '' "
        "if kind == 'worker' then info, cfg = workerInfo() "
        "if cfg ~= nil then pcall(function() id = tostring(math.floor(tonumber(cfg.id) or 0)) end) end "
        "else info, id = heroInfo() end "
        "if info == nil then "
        "DataCenter.__lw_recruit_report = 'kind='..kind..' — the client has no such banner "
        "loaded (not logged in, or the recruit screen has never been opened) — nothing sent' "
        "return end "
        "local free = 0 pcall(function() free = info:CanFreeRecruit() and 1 or 0 end) "
        "local useFree = 0 "
        "if want ~= 'no' and free == 1 and count == 1 then useFree = 1 end "
        "if want == 'only' and useFree == 0 then "
        "DataCenter.__lw_recruit_report = 'kind='..kind..' count='..count..' — the free pull is "
        "not available and «only free» was asked for — nothing sent' "
        "return end "
        "local itemId, itemNum = costOf(info, size) "
        "if kind == 'worker' and size == 2 then "
        "pcall(function() local c = cfg and cfg.recruit100CostInfo "
        "if c ~= nil then itemId = c.itemId itemNum = tonumber(c.itemNum) or 0 end end) end "
        "local held = have(itemId) "
        "if useFree == 0 and (itemNum <= 0 or held < itemNum) then "
        "DataCenter.__lw_recruit_report = 'kind='..kind..' count='..count..' cost='..itemNum"
        "..' of item '..itemId..' have='..held..' — not enough tickets, nothing sent' "
        "return end "
        # WHAT THE PULL IS MEASURED AGAINST, taken before the send: the tickets held
        # with the free pull's own gate under them. A pull that is refused by the
        # server returns just as cleanly as one it takes, so the recipe waits for THIS
        # number to move and calls the run failed when it never does.
        "local free_before = 0 pcall(function() free_before = info:CanFreeRecruit() and 1 or 0 end) "
        "DataCenter.__lw_recruit_before = have(itemId) * 2 + free_before "
        "local ok, err = pcall(function() "
        "if kind == 'worker' then "
        "SFSNetwork.SendMessage(MsgDefines.LotteryWorkerCard, useFree, size, math.floor(tonumber(id) or 0)) "
        "else "
        "SFSNetwork.SendMessage(MsgDefines.LotteryHeroCard, id, size, useFree, itemId) end end) "
        "if ok then DataCenter.__lw_recruit_sent = 1 end "
        "DataCenter.__lw_recruit_report = 'kind='..kind..' banner='..id..' count='..count"
        "..' isTen='..size..' useFree='..useFree..' cost='..(useFree == 1 and 0 or itemNum)"
        "..' item='..itemId..' have='..held..' sent='..tostring(ok)..' err='..tostring(err) "
        'CS.UnityEngine.Debug.LogError("ACT recruit_draw "..DataCenter.__lw_recruit_report)'
    )


def recruit_report() -> str:
    """Lua *expression* -> what :func:`recruit_draw` did, in its own words."""
    return ("(DataCenter.__lw_recruit_report or "
            "'the pull left no report — the press did not run')")


def recruit_sent() -> str:
    """Lua *expression* -> ``1`` when a pull actually left, ``0`` when it was refused."""
    return "(tonumber(DataCenter.__lw_recruit_sent) or 0)"


def recruit_verify() -> str:
    """Lua *expression* -> a number that MOVES when a pull really happened.

    Two things can pay for a pull and only one of them is tickets, so the proof has to
    cover both: the ticket count halves the number and the free pull's own gate is the
    unit under it. A paid pull drops the tickets, a free one flips
    ``CanFreeRecruit()`` from 1 to 0 — either way this value is different afterwards,
    and a press the server ignored leaves it exactly where it was.

    It is NOT the button's `verify_lua`, and that is deliberate: a press that decided on
    purpose to send nothing — no free pull with «only free» asked for, not enough
    tickets — moves nothing either, and a button-level check reports that as «pressed
    and nothing moved» over a refusal the recipe has already explained in words. So the
    recipe reads :func:`recruit_sent` first and only then waits on this.
    """
    return (
        "(function() "
        + _RECRUIT_HERO_INFO + _RECRUIT_WORKER_INFO + _RECRUIT_COST +
        "local kind = tostring(DataCenter.__lw_recruit_kind or 'hero') "
        "local info = nil "
        "if kind == 'worker' then info = (workerInfo()) else info = (heroInfo()) end "
        "if info == nil then return -1 end "
        "local itemId = 0 pcall(function() itemId = (costOf(info, 0)) end) "
        "local free = 0 pcall(function() free = info:CanFreeRecruit() and 1 or 0 end) "
        "return have(itemId) * 2 + free end)()"
    )


def recruit_moved() -> str:
    """Lua *expression* -> ``1`` once the game has caught up with a pull that was sent.

    The difference against the reading :func:`recruit_draw` took before the send. `0`
    while the server has not answered yet, so a recipe polls it for a second or two —
    and a `0` that never becomes `1` is the one honest way to say «it went out and
    nothing came of it».
    """
    return ("((DataCenter.__lw_recruit_before ~= nil and "
            "(%s) ~= DataCenter.__lw_recruit_before) and 1 or 0)" % recruit_verify())


# ---------------------------------------------------------------------------
# Радар — the detect-event board (#1414)
# ---------------------------------------------------------------------------
# The radar hands out a board of small errands ("detect events"): kill a Doom Legion
# camp, gather a mine, run an errand for an ally. Each one is a `DetectEventInfo` with
# its own `uuid`; a finished one pays out, an unfinished one has to be carried out.
#
# Every press below is one message, and every one of them is taken verbatim off the
# recording `results/traces/20260815_080129_радар_trace.log` (#1414) — the payload
# shapes are the `SFSObject.Put*` lines beside each `SFSNetwork.SendMessage`:
#
#   get.detect.info                 {openWnd: bool}          — read the board
#   receive.detect.event.reward     {uuid: long}             — claim ONE finished errand
#   detect.event.help.start         {uuid: long, eventType}  — begin carrying one out
#   detect.event.help.end           {uuid: long, eventType}  — report it finished
#   detect.event.put.point.in.world {uuid: long}             — drop its target on the map
#
# «Получить все» IS the per-errand claim. The in-game button is a client-side loop:
# the recording shows `arrayV2.iterator` and then eleven separate
# `receive.detect.event.reward` sends in a row, one per finished errand, matching the
# red badge of 11. There is no "claim all" command, so the recipe's `xall` reproduces
# exactly what the button does — which is also why a single errand can be claimed on
# its own with the same primitive.

# The `eventType` the recording carried on both help messages. It is a property of the
# errand, not a constant of the feature, so `radar_help_start`/`radar_help_end` take it
# — this is only the fallback for a caller that has not read one off the board.
RADAR_HELP_EVENT_TYPE = 18


def radar_fetch_board() -> str:
    """Ask the server for the radar board — `get.detect.info`.

    The reply is what fills the client's own list, so this is the read that has to
    happen before anything below can name a `uuid`. Give it a settle (~0.8 s) and read
    the board afterwards, never in the same chunk.

    **No argument, on purpose.** The recording's own refresh is
    `SFSNetwork.SendMessage("get.detect.info", nil)` and the message class writes
    `openWnd = true` into the payload by itself — the flag is the server's copy of «a
    window asked», not an instruction to open one, and passing it from here would only
    be a second spelling of what the message already does. Nothing on screen moves.
    """
    return ('pcall(function() SFSNetwork.SendMessage(MsgDefines.DetectInfoGet) end) '
            'CS.UnityEngine.Debug.LogError("ACT radar_board_requested")')


# The board's own readings. Every one of them is the client's own accessor rather than a
# walk of `events` written here: `RadarCenterDataManager` counts by
# `DetectEventState`, and a copy of that test in this file would be a second opinion
# about what «finished» means the day the enum grows a value.
#
#   DetectEventState = {NOT_FINISH = 0, FINISHED = 1, REWARDED = 2, NOT_IN_WORLD = 3}
#
# Read live off the client on 2026-08-17 (#1470), together with the manager's method
# list; the whole board is written up in `docs/research/radar.md`.


def radar_finished_count() -> str:
    """How many errands are FINISHED and waiting to be claimed — the red badge.

    `GetFinishedDetectEventNum` counts `state == DETECT_EVENT_STATE_FINISHED`, which is
    exactly the set the in-game «Получить все» iterates. This is the `count_lua` of the
    claim button, so `TAP radar_claim xall` spends precisely the badge.
    """
    return ("(function() local M = DataCenter.RadarCenterDataManager "
            "if not M then return 0 end "
            "local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) "
            "return (ok and tonumber(n)) or 0 end)()")


def radar_board_count() -> str:
    """How many errands are on the board right now, finished or not."""
    return ("(function() local M = DataCenter.RadarCenterDataManager "
            "if not M then return 0 end "
            "local ok, n = pcall(function() return M:GetDetectEventCount() end) "
            "return (ok and tonumber(n)) or 0 end)()")


def radar_board_max() -> str:
    """How many errands the board holds at most — `detectInfo.eventNum`.

    The ceiling matters because it is a STOP, not a spill: a full board stops handing
    out new errands, so hoarding finished ones for the duel day pays only while there
    is room left. `docs/research/radar.md` has the arithmetic.
    """
    return ("(function() local M = DataCenter.RadarCenterDataManager "
            "if not M then return 0 end "
            "local ok, n = pcall(function() return M:GetMaxDetectNum() end) "
            "return (ok and tonumber(n)) or 0 end)()")


def radar_free_slots() -> str:
    """Room left on the board — the ceiling minus what is on it. Never below zero."""
    return ("(function() local a = %s local b = %s "
            "local d = a - b if d < 0 then d = 0 end return d end)()"
            % (radar_board_max(), radar_board_count()))


def radar_helpable_count() -> str:
    """How many errands «Быстро выполнить» would set running.

    An errand is eligible when it is a HELPER one (`DetectEventType.HELPER = 18` — the
    «help an alliancemate» kind, the only kind that needs no march), it is not finished
    yet, and it is not frozen. That is the set the in-game button fired on: three at
    once in the recording, all three `eventType = 18`.
    """
    return ("(function() local M = DataCenter.RadarCenterDataManager "
            "if not M then return 0 end "
            "local n = 0 "
            "for _, e in pairs(rawget(M, 'events') or {}) do "
            "local t = rawget(e, 'template') "
            "if rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH "
            "and t and rawget(t, 'type') == DetectEventType.HELPER "
            "and not rawget(e, 'isFrozen') then n = n + 1 end end "
            "return n end)()")


def radar_game_weekday() -> str:
    """Which weekday the GAME is on — 1 = Monday … 7 = Sunday, 0 when it cannot be asked.

    Not the PC's. The game's day turns at the server's own midnight (02:00 UTC on the
    warzone this was measured on, `docs/research/ghost-recon-steal.md`), so a machine in
    any timezone west of it spends hours calling the game's Tuesday «Monday» — and the
    whole point of asking is to decide whether TODAY is the day the radar's errands
    score. The client's own `GetTomorrowZero()` is the next such midnight; a day earlier
    is the start of the one now running, and its UTC weekday is the label the duel week
    uses.

    Lua's `os.date` numbers the week from Sunday, so it is turned round here rather than
    at three call sites.
    """
    return ("(function() local ok, ms = pcall(function() "
            "return UITimeManager:GetInstance():GetTomorrowZero() end) "
            "if not ok or not tonumber(ms) then return 0 end "
            "local start = math.floor(tonumber(ms) / 1000) - 86400 "
            "local w = tonumber(os.date('!%w', start)) "
            "if w == nil then return 0 end "
            "if w == 0 then return 7 end return w end)()")


def radar_claim_press() -> str:
    """Claim the FIRST finished errand — one `receive.detect.event.reward`.

    The in-game «Получить все» is a client-side loop, not a command: the recording shows
    `arrayV2.iterator` and then eleven separate sends in a row, one per finished errand,
    matching the red badge of 11. So claiming all and claiming one are the same press,
    which is what `xall` spends.

    It sends the message rather than calling `ClaimDetectEventRewardByEventData`,
    because that method is the WINDOW's version of the press: it asks the resource
    manager whether the bag is full, may pop a confirm dialog for a rescue errand whose
    soldiers would not fit (`radar_army_01`), and queues a fly-to animation. The
    message underneath it is the whole of the transaction, and a headless press must
    not be able to leave a modal standing.

    That does mean the client-side «your barracks are full» warning is skipped: a rescue
    errand claimed with no room pays what the server decides to pay. The warning is
    advice to a person, not a rule of the server.
    """
    return ("(function() local M = DataCenter.RadarCenterDataManager "
            "if not M then return end "
            "for _, e in pairs(rawget(M, 'events') or {}) do "
            "if rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_FINISHED then "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.DetectEventRewardReceive, "
            "rawget(e, 'uuid')) end) "
            "CS.UnityEngine.Debug.LogError(\"ACT radar_claim_sent uuid=\" .. "
            "tostring(rawget(e, 'uuid'))) return end end end)()")


def radar_claim_batch(times: str = "n") -> str:
    """Claim up to `times` finished errands in ONE game-VM call.

    `times` defaults to the Lua local `n`, which the caller prepends. A claim is a plain
    fire-and-forget send — nothing inside the batch waits on the server — so the whole
    badge empties in one round trip instead of one per errand, and the caller's re-read
    of :func:`radar_finished_count` afterwards remains the stop condition.

    Reports what it really sent as `ACT fired=<k>`.
    """
    return ("local M = DataCenter.RadarCenterDataManager "
            "local fired = 0 "
            "if M then for _, e in pairs(rawget(M, 'events') or {}) do "
            "if fired >= %s then break end "
            "if rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_FINISHED then "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.DetectEventRewardReceive, "
            "rawget(e, 'uuid')) end) fired = fired + 1 end end end "
            'CS.UnityEngine.Debug.LogError("ACT fired=" .. tostring(fired))' % times)


def radar_help_start_all() -> str:
    """Set every eligible «help an alliancemate» errand running, in one call.

    This is the in-game «Быстро выполнить» (`BtnCompleteOnClick`): one
    `detect.event.help.start {uuid, eventType}` per eligible errand — three at once in
    the recording. Each one then takes `Mathf.Min(3000, <distance> * 100)` milliseconds,
    so **three seconds covers the longest of them**, and the finish has to be reported
    separately (:func:`radar_help_end_all`).

    The uuids it started are parked on `DataCenter.__lw_radar_helping`, so the finish
    reports exactly what this began and never an errand somebody else's press owns.
    """
    return ("local M = DataCenter.RadarCenterDataManager "
            "local started = {} "
            "if M then for _, e in pairs(rawget(M, 'events') or {}) do "
            "local t = rawget(e, 'template') "
            "if rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH "
            "and t and rawget(t, 'type') == DetectEventType.HELPER "
            "and not rawget(e, 'isFrozen') then "
            "local u = rawget(e, 'uuid') "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.DetectEventHelpStart, u, "
            "DetectEventType.HELPER) end) "
            "started[#started + 1] = u end end end "
            "DataCenter.__lw_radar_helping = started "
            'CS.UnityEngine.Debug.LogError("ACT radar_help_started=" .. tostring(#started))')


def radar_help_end_all() -> str:
    """Report every errand :func:`radar_help_start_all` began as finished.

    One `detect.event.help.end {uuid, eventType}` per parked uuid. **The client only
    sends this itself while the radar window is open** — the recording's three finishes
    fire the instant the window's own progress slider reaches 1.0 — so a headless run
    has to send them, or the errands sit half-done until somebody opens the board.

    Sending one before its timer has elapsed is the server's decision to refuse, not
    ours to make; the caller's job is to wait the three seconds first.
    """
    return ("local u = DataCenter.__lw_radar_helping or {} "
            "local sent = 0 "
            "for _, uuid in ipairs(u) do "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.DetectEventHelpEnd, uuid, "
            "DetectEventType.HELPER) end) sent = sent + 1 end "
            "DataCenter.__lw_radar_helping = {} "
            'CS.UnityEngine.Debug.LogError("ACT radar_help_ended=" .. tostring(sent))')


def radar_claim(uuid: str) -> str:
    """Claim ONE finished radar errand — `receive.detect.event.reward {uuid}`.

    This is the whole of the in-game «Получить» on a single card, and eleven of these
    in a row are the whole of «Получить все» (see the section comment). Nothing else is
    sent: no window is opened, no card is tapped.
    """
    return ('pcall(function() SFSNetwork.SendMessage("receive.detect.event.reward", %s) end) '
            'CS.UnityEngine.Debug.LogError("ACT radar_claim_sent uuid=%s")'
            % (uuid, uuid))


def radar_help_start(uuid: str, event_type: int = RADAR_HELP_EVENT_TYPE) -> str:
    """Set an errand running — `detect.event.help.start {uuid, eventType}`.

    The in-game «Быстро выполнить» (`BtnCompleteOnClick`) fires one of these per
    eligible errand — three at once in the recording — and each one takes time: the
    client computes `Mathf.Min(3000, <distance from the home tile>)` right before the
    send, so the wait is the travel distance, capped. The finish is reported separately
    with :func:`radar_help_end`.
    """
    return ('pcall(function() SFSNetwork.SendMessage("detect.event.help.start", %s, %d) end) '
            'CS.UnityEngine.Debug.LogError("ACT radar_help_start uuid=%s type=%d")'
            % (uuid, int(event_type), uuid, int(event_type)))


def radar_help_end(uuid: str, event_type: int = RADAR_HELP_EVENT_TYPE) -> str:
    """Report an errand finished — `detect.event.help.end {uuid, eventType}`.

    The client sends this itself when its own timer runs out, so a recipe that started
    one with :func:`radar_help_start` must either wait for the client to do it or send
    it once the errand's timer has actually elapsed. Sending it early is the server's
    decision to refuse, not ours to make.
    """
    return ('pcall(function() SFSNetwork.SendMessage("detect.event.help.end", %s, %d) end) '
            'CS.UnityEngine.Debug.LogError("ACT radar_help_end uuid=%s type=%d")'
            % (uuid, int(event_type), uuid, int(event_type)))


def radar_put_point(uuid: str) -> str:
    """Drop an errand's target onto the world map — `detect.event.put.point.in.world`.

    The in-game «Перейти» (`Detect_Event_Info_Goto_Btn`). The server answers by placing
    the tile and broadcasting event 2454 with the same uuid; the client then knows the
    point index and moves there (`GoToUtil.MoveToWorldPointAndOpen(<point>, nil, uuid,
    <server>)`). Only after that does an ordinary march start — attacking the camp or
    gathering the mine is `MarchUtil.OnClickStartMarch`, the same call every other
    target uses, and none of it is part of this message.
    """
    return ('pcall(function() SFSNetwork.SendMessage("detect.event.put.point.in.world", %s) end) '
            'CS.UnityEngine.Debug.LogError("ACT radar_point_requested uuid=%s")'
            % (uuid, uuid))


# ---------------------------------------------------------------------------
# Радар — the errands that need a march (#1470)
# ---------------------------------------------------------------------------
# The other half of the board. A `HELPER` errand is two messages and three seconds; every
# other kind is a TILE ON THE MAP with a squad sent at it, and the sequence the game plays
# is three steps rather than one:
#
#   1. `detect.event.put.point.in.world {uuid}` — an errand sits at `state = 3`
#      (`DETECT_EVENT_STATE_NOT_IN_WORLD`) until this is sent; the server then places its
#      tile and the errand becomes `state = 0`. This is the in-game «Перейти», minus the
#      camera flight that follows it.
#   2. a march — `MarchUtil.SendCreateMarchMessage(formation, <target type>, pointId, uuid,
#      1, 1, false, server, nil)`, the same call `dig_treasure_march` makes.
#   3. nothing. The errand ripens when the squad arrives and does its work, and then it is
#      the ordinary claim (`radar_claim_press`). There is no third message to send.
#
# **THE TARGET TYPE IS NEVER GUESSED.** `MarchTargetType` has 190-odd members and picking
# the wrong one sends somebody's squad at something they did not ask for. So only pairs the
# client itself names are shipped, and an errand of any other kind is SKIPPED WITH ITS KIND
# IN THE LOG rather than marched hopefully:
#
#   | DetectEventType            | MarchTargetType   | where the pair comes from            |
#   |----------------------------|-------------------|--------------------------------------|
#   | `TREASURE` = 19            | `DETECT_TREASURE` | live-proven by `auto_treasure`        |
#   | `DetectEventPickGarbage`=6 | `PICK_GARBAGE`    | `MarchUtil.OnCollectGarbage` names it |
#   | `GATHER_RESOURCE` = 16     | `SAMPLE`          | `MarchUtil.OnCollectSimple` names it  |
#
# Each of those two `MarchUtil` functions mentions exactly ONE `MarchTargetType` constant in
# its bytecode and no other, which is as close to a definition as a stripped-of-nothing Lua
# dump gets. Everything else — the monster camps, the rescues, the fake players, the
# wandering bosses, the seasonal digs — is left for a run that can prove its pair.
#
# The dedup and the busy gate are the same one table. An errand this recipe has marched is
# stamped on `DataCenter.__lw_radar_marched[<uuid>]`, so a second run does not send a second
# squad at a tile that already has ours, and an errand that could not be marched — no free
# squad — is simply not stamped and comes round again. Nothing is dropped silently: every
# press says what it did and what it could not do, which is the #1416 lesson.

#: `DetectEventType` -> `MarchTargetType`, as a Lua table literal. Written as names rather
#: than numbers on purpose: a number here would be this build's answer, and the client's own
#: enums are the authority every other reading in this file goes to.
RADAR_MARCH_TYPES = (
    "{[DetectEventType.GATHER_RESOURCE] = MarchTargetType.COLLECT, "
    "[DetectEventType.DetectEventPickGarbage] = MarchTargetType.PICK_GARBAGE, "
    "[DetectEventType.FAKE_PLAYER] = MarchTargetType.ATTACK_CITY, "
    "[DetectEventType.TREASURE] = MarchTargetType.DETECT_TREASURE}"
)

#: The kinds whose TILE carries a uuid of its own. Everything else is marched at with
#: `uuid = 0`, which is what a resource tile really has — `tools/dev/gather.py` reads
#: `uuid = 0` straight off the popup of a mine the player clicked, and the march that
#: goes out with it is the one that works. Passing the ERRAND's uuid instead was one of
#: the two reasons the first attempts sent nothing.
RADAR_MARCH_UUID_KINDS = ("{[DetectEventType.TREASURE] = true, "
                          "[DetectEventType.FAKE_PLAYER] = true}")

#: The walk every reading and press below shares: the errands that are NOT the help kind,
#: not finished, not frozen, and not already marched by us. Returns a Lua array of
#: `{uuid, kind, pid, target}` where `target` is nil for a kind with no proven pair.
_RADAR_MARCH_LIST = (
    "local M = DataCenter.RadarCenterDataManager "
    "local map = %s "
    "local done = DataCenter.__lw_radar_marched or {} "
    "local list = {} "
    "if M then for _, e in pairs(rawget(M, 'events') or {}) do "
    "local t = rawget(e, 'template') "
    "local kind = t and rawget(t, 'type') "
    "local u = rawget(e, 'uuid') "
    "if kind ~= nil and kind ~= DetectEventType.HELPER "
    "and rawget(e, 'state') ~= DetectEventState.DETECT_EVENT_STATE_FINISHED "
    "and rawget(e, 'state') ~= DetectEventState.DETECT_EVENT_STATE_REWARDED "
    "and not rawget(e, 'isFrozen') and not done[tostring(u)] then "
    "list[#list + 1] = {uuid = u, kind = kind, pid = rawget(e, 'pointId'), "
    "state = rawget(e, 'state'), target = map[kind]} end end end "
) % RADAR_MARCH_TYPES


def radar_place_points() -> str:
    """Put every out-of-world errand onto the map — the in-game «Перейти», minus the camera.

    An errand at `state = 3` (`DETECT_EVENT_STATE_NOT_IN_WORLD`) has no tile yet and cannot
    be marched at; one `detect.event.put.point.in.world {uuid}` each is what places it. The
    server answers by placing the tile and broadcasting the errand's new state, so this
    needs a settle before anything reads the board again.

    Only the kinds with a proven march type are placed. Placing one this recipe would then
    refuse to march would put a tile on the player's map for nothing.
    """
    return (_RADAR_MARCH_LIST +
            "local sent = 0 "
            "for _, r in ipairs(list) do "
            "if r.target ~= nil and r.state == DetectEventState.DETECT_EVENT_STATE_NOT_IN_WORLD then "
            "pcall(function() SFSNetwork.SendMessage(MsgDefines.DetectEventPutPointInWorld, "
            "r.uuid) end) sent = sent + 1 end end "
            'CS.UnityEngine.Debug.LogError("ACT radar_points_placed=" .. tostring(sent))')


def radar_marchable_count() -> str:
    """How many errands this recipe could march at right now — a proven kind, on the map,
    not already ours. The `count_lua` of the march button, so `xall` spends exactly them."""
    return ("(function() " + _RADAR_MARCH_LIST +
            "local n = 0 "
            "for _, r in ipairs(list) do "
            "if r.target ~= nil and r.state == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH "
            "then n = n + 1 end end "
            "return n end)()")


def radar_unmarchable_kinds() -> str:
    """The kinds on the board this recipe will NOT march, as `<kind>x<count>` — so a run
    that skipped work says WHICH work rather than «some».

    A string, not a number: it goes into a `LOG` line, and the point of it is to be the
    next task's input. A kind that keeps showing up here is the pair worth proving.
    """
    return ("(function() " + _RADAR_MARCH_LIST +
            "local tally = {} "
            "for _, r in ipairs(list) do "
            "if r.target == nil then local k = tostring(r.kind) "
            "tally[k] = (tally[k] or 0) + 1 end end "
            "local out = {} "
            "for k, v in pairs(tally) do out[#out + 1] = k .. 'x' .. tostring(v) end "
            "table.sort(out) "
            "if #out == 0 then return 'none' end "
            "return table.concat(out, ' ') end)()")


def radar_squads_arm() -> str:
    """Park the squads this run may send, ONCE, before any of them is spent.

    The picker used to re-read `totalSoldierNum` and `GetOwnerFormationMarch` on every
    press, and both readings move under it: the soldier count is a client-side cache that
    goes back to zero (#1285), and a march is not known to the client until the server has
    answered, which is longer than the gap between two presses. A run that had three squads
    standing at home therefore sent one march and then said «no free squad» eleven times.

    So the squads are chosen ONCE — loaded, and not already out — and parked as a queue the
    press pops from, exactly the way the treasures and the rally park theirs. The server
    stays the authority for the next run; within one run, the queue is.
    """
    return ("local afd = DataCenter.ArmyFormationDataManager "
            "local q = {} "
            "if afd then for _, v in pairs(afd.ArmyFormationList or {}) do "
            "local ok, sol = pcall(function() return tonumber(v.totalSoldierNum) or 0 end) "
            "if ok and sol > 0 then "
            "local out = nil "
            "pcall(function() out = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch(v.uuid) end) "
            "if out == nil then q[#q + 1] = {uuid = v.uuid, index = v.index} end end end end "
            "DataCenter.__lw_radar_squad_queue = q "
            'CS.UnityEngine.Debug.LogError("ACT radar_squads_armed=" .. tostring(#q))')


def radar_squads_ready() -> str:
    """Lua *expression* -> how many parked squads are still unspent."""
    return "(function() return #(DataCenter.__lw_radar_squad_queue or {}) end)()"


def radar_free_squads() -> str:
    """How many squads this run can still send — what `radar_squads_arm` parked and the
    presses have not yet popped. See that function for why it is a queue and not a re-read.
    """
    return radar_squads_ready()


def radar_march_press() -> str:
    """Send ONE free squad at ONE marchable errand — the whole of the march half's press.

    Nothing is opened and no camera moves: `SendCreateMarchMessage` is the layer under the
    game's own `OnCollectSimple` / `OnCollectGarbage`, below the squad-picker window those
    open (`MarchUtil.OnClickStartMarch` ends in `OpenFormationSelectUI`, which is why it is
    not what this calls).

    It stamps the errand on `DataCenter.__lw_radar_marched` BEFORE reporting, so a repeat
    press moves on to the next errand rather than piling a second squad onto this one. A
    press with nothing to send, or with no free squad, says which of the two it was and
    stamps nothing — the errand comes round again on the next run.

    **The SQUAD is stamped too, and that is a bug this recipe already had.** The first live
    run sent four marches and every one of them named squad 1: `GetOwnerFormationMarch`
    does not know a march until the server has answered, which is longer than the gap
    between two presses, so the picker chose the same formation over and over. The
    server's answer is still the authority — the stamp only stops a press racing its own
    predecessor within one run, and `radar_marched_forget` clears both tables together.
    """
    return (_RADAR_MARCH_LIST +
            "local pick = nil "
            "for _, r in ipairs(list) do "
            "if r.target ~= nil and r.state == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH "
            "and pick == nil then pick = r end end "
            "if pick == nil then "
            'CS.UnityEngine.Debug.LogError("ACT radar_march_none why=nothing-to-march") '
            "return end "
            "local q = DataCenter.__lw_radar_squad_queue or {} "
            "local squad = table.remove(q, 1) "
            "if squad == nil then "
            'CS.UnityEngine.Debug.LogError("ACT radar_march_none why=no-free-squad") '
            "return end "
            "local srv = 0 "
            "pcall(function() srv = tonumber(LuaEntry.Player.serverId) or 0 end) "
            "local carries = " + RADAR_MARCH_UUID_KINDS + " "
            "local tgt = carries[pick.kind] and pick.uuid or 0 "
            # Stamped BEFORE the send rather than after it: the send now happens a frame
            # later (below), so an `if ok then` around the stamp would run before the call
            # it is meant to describe. The stamp's job is «this press has taken this
            # errand and this squad», which is true the moment the press decides.
            "DataCenter.__lw_radar_marched = DataCenter.__lw_radar_marched or {} "
            "DataCenter.__lw_radar_marched[tostring(pick.uuid)] = true "
            # ON THE MAIN THREAD, and this is the whole reason the first attempts sent
            # nothing at all. A `SendCreateMarchMessage` issued from the hijack thread is
            # BUILT and then DROPPED — no error, no march — which is why every send in
            # this file that works goes through `TimerManager:DelayInvoke`
            # (`dig_treasure_march`, `dig_head_treasure`, `tools/dev/gather.py`). Measured
            # again on 2026-08-17: the identical call direct returned `ok=true` three times
            # and left `GetOwnerMarches()` at zero; scheduled, one press put a squad on the
            # map.
            "TimerManager:GetInstance():DelayInvoke(function() "
            "local ok, err = pcall(function() "
            "MarchUtil.SendCreateMarchMessage(squad.uuid, pick.target, pick.pid, tgt, "
            "1, 1, false, srv, nil) end) "
            'CS.UnityEngine.Debug.LogError("ACT radar_march_sent ok=" .. tostring(ok) '
            '.. " kind=" .. tostring(pick.kind) .. " target=" .. tostring(pick.target) '
            '.. " pid=" .. tostring(pick.pid) .. " uuid=" .. tostring(tgt) '
            '.. " squad=" .. tostring(squad.index) .. " err=" .. tostring(err)) '
            "end, 0.5) "
            'CS.UnityEngine.Debug.LogError("ACT radar_march_armed kind=" .. tostring(pick.kind) '
            '.. " pid=" .. tostring(pick.pid) .. " squad=" .. tostring(squad.index))')


def radar_marched_forget() -> str:
    """Forget which errands this recipe has marched.

    The stamp exists to stop a second squad going at a tile that already has ours, and an
    errand that has been claimed is gone from the board anyway — so the table only ever
    grows with uuids the server has already retired. Clearing it is what a person does after
    a squad came home with nothing and the errand is to be tried again.
    """
    return ('DataCenter.__lw_radar_marched = {} '
            'DataCenter.__lw_radar_squads_used = {} '
            'CS.UnityEngine.Debug.LogError("ACT radar_marched_forgotten")')


# ---------------------------------------------------------------------------
# Радар — the level table, which is where the two numbers actually come from (#1470)
# ---------------------------------------------------------------------------
# The board's capacity and the day's allowance are NOT constants and NOT the same number,
# and both were guessed wrong once before the table turned up. `detect_level` — 20 rows,
# one per radar level, read live off `LocalController` — settles it:
#
#   detect_show_num   how many errands the board holds AT ONCE  — the capacity
#   detect_max_num    how many it will hand out in a DAY        — the allowance
#   refresh           "<seconds>;<count>" — the drip that refills the allowance
#
# On the account this was read from, level 16: `detect_show_num = 12`,
# `detect_max_num = 40` — which is exactly the 12 the board sat at all afternoon and the 40
# `detectInfo.eventNum` started the day on. `eventNum` is therefore the allowance COUNTING
# DOWN, and `GetMaxDetectNum()` (which returns it) is a badly named remainder rather than
# any kind of maximum.
#
# **Level 1 gives 5 and 25.** So a second player's radar has different numbers for both,
# which is why neither may be written down here: the level is read per profile
# (`GetDetectInfoLevel`) and the row is looked up under it.

def radar_nothing_to_do() -> str:
    """Lua *expression* -> 1 when there is nothing on the board worth a trip to it.

    THE DAY'S RULES, AND THE FIRST OF THEM (#2390). The operator's, in their words: «лимит
    выполненных достигнут — к радару не ходим». Before this, a board with nothing left in
    it still cost the whole journey — the world scene, the squads refilled, the board read
    three times, the points placed — and only at the claim did the cycle discover the day
    had nothing left to hand out and stop. Measured live on 2026-09-03: `quota=40 left=0
    board=12 ripe=12 helpable=0 free_places=0`, a board on which not one of those steps
    could have changed anything.

    Three readings, all out of the client's own copy, no request and no window:

    * `detectInfo.eventNum` — what is LEFT of the day's allowance. Zero means a claim
      frees a place the game cannot refill, so making room buys nothing;
    * how many ally errands can be helped — the ones that need no march at all;
    * how many errands on the board still want a squad.

    All three zero and there is nothing a trip could do. It says nothing about the DUEL
    day: on that one the ripe errands are the whole point, and the caller goes whatever
    this answers.
    """
    return ("(function() local left = %(left)s "
            "if left > 0 then return 0 end "
            "if %(help)s > 0 then return 0 end "
            "if %(march)s > 0 then return 0 end "
            "return 1 end)()"
            % {"left": radar_board_max(), "help": radar_helpable_count(),
               "march": radar_marchable_count()})


def radar_level() -> str:
    """The profile's own radar level — 0 when it cannot be read."""
    return ("(function() local M = DataCenter.RadarCenterDataManager "
            "if not M then return 0 end "
            "local ok, v = pcall(function() return M:GetDetectInfoLevel() end) "
            "return (ok and tonumber(v)) or 0 end)()")


def _radar_level_field(field: str) -> str:
    """A column of this profile's `detect_level` row, 0 when anything is unreadable.

    The column NAMES are read off the row's own metadata rather than assumed at a numeric
    index: a config table that grows a column shifts every index after it, and this file
    has no business remembering which build had what where.
    """
    return ("(function() local M = DataCenter.RadarCenterDataManager "
            "if not M then return 0 end "
            "local lvl = 0 "
            "pcall(function() lvl = tonumber(M:GetDetectInfoLevel()) or 0 end) "
            "if lvl < 1 then return 0 end "
            "local inst = LocalController.instance() "
            "pcall(function() inst:getTable('detect_level') end) "
            "local row = nil "
            "pcall(function() row = inst:getLine('detect_level', lvl) end) "
            "if type(row) ~= 'table' then return 0 end "
            "local md = nil pcall(function() md = row:getMetaData() end) "
            "if type(md) ~= 'table' then return 0 end "
            # `md` is keyed by COLUMN NAME and each entry's `[1]` is the numeric
            # index `_lineData` uses — the other way round from the obvious reading,
            # and reading it the obvious way returned 0 for everything with nothing
            # saying why.
            "local col = nil "
            "pcall(function() local e = md['%s'] col = e and e[1] end) "
            "if col == nil then return 0 end "
            "local ld = rawget(row, '_lineData') or {} "
            "return tonumber(ld[col]) or tonumber(ld[tostring(col)]) "
            "or tonumber(ld[tonumber(col) or -1]) or 0 end)()" % field)


def radar_next_refresh() -> str:
    """Lua *expression* -> the stamp the radar refills itself at, in server ms.

    `detectInfo.nextRefreshTime`, read out of the client's own copy: no request, no
    window, nothing the server hears. Live on 2026-09-03 it read ~3.6 h ahead with
    `eventNum = 0` beside it — the day's allowance drawn to the last errand and the board
    waiting for its own clock, which is the state this reading exists to recognise.

    0 when the client cannot answer, and a 0 is deliberately treated as «work» by the gate
    below: a board nobody can read is not a board somebody may skip.
    """
    return ("(function() local M = DataCenter.RadarCenterDataManager "
            "if not M then return 0 end "
            "local di = nil pcall(function() di = M.detectInfo end) "
            "if di == nil then pcall(function() di = M:GetDetectInfo() end) end "
            "if di == nil then return 0 end "
            "return math.floor(tonumber(rawget(di, 'nextRefreshTime')) or 0) end)()")


def radar_window_done() -> str:
    """Lua *expression* -> 1 when this refresh window has already been worked.

    THE WHOLE POINT OF THE ERRAND'S PACING (#2390), and it is the operator's own rule:
    «Радар обновляется раз в 4 часа, один раз выполнили задания и все, ждем обновления».
    The board hands out its allowance and then refills at `nextRefreshTime`, so the useful
    unit of work is ONE PASS PER REFRESH — not a clock. Measured before this existed: the
    errand held the client 1344 s over 44 minutes, 51 % of the wall clock, while a chain
    that yields to everything crawled.

    The stamp of the window a cycle finished in is parked by :func:`radar_window_mark`, so
    a run that was cut short — the client crashed, the lease went — leaves nothing behind
    and the next tick works the window again. There is no push behind the refresh
    (`docs/research/radar.md`: nothing on the wire announces it), so the shape is «read the
    game's own stamp and be quiet until it moves».
    """
    return ("(function() local now = %s "
            "if now <= 0 then return 0 end "
            "local seen = tonumber(DataCenter.__lw_radar_done_for) or 0 "
            "if seen == now then return 1 end return 0 end)()" % radar_next_refresh())


def radar_window_mark() -> str:
    """Park the refresh stamp this cycle has just worked, so the next tick is quiet."""
    return ("DataCenter.__lw_radar_done_for = %s "
            'CS.UnityEngine.Debug.LogError("ACT radar_window_mark at="'
            "..tostring(DataCenter.__lw_radar_done_for))" % radar_next_refresh())


def radar_capacity() -> str:
    """How many errands this profile's board holds at once — `detect_show_num`.

    The number `keep_free` is measured against. Read per profile, never written down: a
    level-1 radar holds 5 and a level-16 one holds 12.
    """
    return _radar_level_field("detect_show_num")


def radar_day_quota() -> str:
    """How many errands this profile's radar hands out in a whole day — `detect_max_num`.

    The TOTAL. What is LEFT of it is `detectInfo.eventNum` (:func:`radar_board_max`, whose
    name lies), and the difference between the two is how much of the day has been drawn.
    """
    return _radar_level_field("detect_max_num")


def radar_free_places() -> str:
    """Room on the board — the capacity minus what is on it. Never below zero.

    This is the reading the hoard is steered by, and it replaces the subtraction that used
    to be done against `GetMaxDetectNum()` — two unrelated quantities, which is how a log
    line came to read «12 of 2 slots used».
    """
    return ("(function() local cap = %s local now = %s "
            "local d = cap - now if d < 0 then d = 0 end return d end)()"
            % (radar_capacity(), radar_board_count()))


# ---------------------------------------------------------------------------
# Golden zombies («золотые зомби») — scan the map, then a chain of solo marches
# ---------------------------------------------------------------------------
# Task #1519. The «golden zombie» the player means is the invasion event's own small
# monster, and it is told apart by ONE number and never by its picture: config id
# **1030000** in the client's `lw_world_monster` table. Read live off the running
# client on 2026-08-19:
#
#     id=1030000  level=10  type=7  special=9  size=1  recommend_power=670000
#     expire=720  is_stop=1  speed=0.75  worldmap_icon=zyf_daditu_guaiwu_huang0
#
# `type=7` is the zombie line, `special=9` is `WorldMonsterSpecialType.MonsterInvasion`,
# and `huang` in the icon name is the yellow one on the gold piles. Nothing here is read
# from a sprite: the whitelist below is the config id, so a re-skin of the model changes
# nothing and a monster that merely LOOKS golden is not attacked.
#
# ## The energy, and why it is asked rather than counted
#
# One solo attack costs whatever the game says it costs:
#
#     MarchUtil.GetCostStaminaByTargetType(MarchTargetType.ATTACK_MONSTER) -> 10
#
# and the purse is `LuaEntry.Player.stamina` (120 on a full account, so twelve attacks).
# Both are read every lap of the chain — never decremented by us — for the same reason
# the panel keeps no counters: a person attacking on the screen in front of them spends
# from the same purse, and a number we kept would be confidently wrong within a minute.
#
# ## The chain, and why it is not a fan out of the base
#
# The next target is the nearest one to WHERE THE SQUAD IS, not to home. That is the
# whole ability: `back_home = 0` on the intermediate marches leaves the squad standing
# on the tile it just cleared, so the following march starts from there. A run that
# picked «nearest to base» every time would walk the same ground three times over.
#
# The first pick has no previous kill to measure from, so it uses the game's own
# `SceneUtils.TileDistanceToMyHome(pointIndex, serverId)` — the distance from the
# player's base, which is where the squad is standing before the first send. Every pick
# after it is a plain distance from the last target's tile.
#
# ## The send
#
# `MarchUtil.SendCreateMarchMessage(formation, ATTACK_MONSTER, pid, uuid, 1, backHome,
# false, serverId, nil)` — the same primitive every other launch in this file uses, and
# the same rule: **scheduled through `TimerManager:GetInstance():DelayInvoke`.** A cold
# send from the hijack thread returns `true` and is dropped by the server
# (docs/research/world-monsters.md, Finding 17). `CROSS_ATTACK_MONSTER` when the target
# sits on another warzone.
#
# ## Two ways to find one, in this order
#
#   1. `WorldScene:GetMonsterListInArea(centre, size, {1030000: 1}, out)` — the invasion
#      enumerator. It answers `uuid -> tile` for every golden zombie in the area, which
#      is everything the send needs, with no window opened and nothing tapped. Golden
#      zombies are invasion monsters, so this is their enumerator and not a stretch of
#      one (Finding 10: it is invasion-ONLY, which is exactly the case here).
#   2. the drawn clones — `WorldMonster…invasion(Clone)` game objects around the camera.
#      A clone knows its tile and NOT its uuid (the uuid is the server's answer), so a
#      target found this way is completed by one `TouchObjectEventTrigger:OnClick()`
#      that opens the point popup, has its uuid read off it and is closed again with
#      `Ctrl:CloseSelf()` — never `DestroyAllWindow()`, which destroys the HUD for good.
#
# NOT PROVEN AGAINST A LIVE GOLDEN ZOMBIE (#1519): the account's invasion was between
# waves while this was written (`GetInvasionSummonProgress() = 0`, zero monsters of any
# config in a 600-tile radius), so the config read, the energy read, the cost read and
# the enumerator's plumbing were verified live and the kill itself was not.

#: THE BAG'S STAMINA ITEMS — the game's own item ids, and what each one is worth (#1702).
#: These are config ids, identical on every account and every machine, exactly like the
#: golden zombie's own :data:`GOLDEN_ZOMBIE_CFG`. The values are the game's: 400401 is the
#: fifty, 400402 is the ten. An id the bag holds that is not named here is left alone —
#: guessing what an item does from its name is how a panel spends somebody's event token.
STAMINA_ITEMS = ((400401, 50), (400402, 10))


#: WHICH KINDS OF ITEM THE BAG WILL USE (#1702). The client exposes no «can this be
#: used» flag at all — the row it keeps carries `id`, `icon`, `type` and `type2` and
#: nothing else, `CheckUseStateTool` answers `true` for a hero shard as readily as for a
#: stamina potion, and there is no `lw_item` config table to ask. So the kinds are listed,
#: and the list was read off the player's own bag by name: speed-ups, resource packs and
#: potions, and every flavour of chest. Everything else — shards, tokens, fragments,
#: coupons — shows no button at all.
#:
#: **A kind that is not here is not offered, ever.** Spending somebody's item because a
#: guess said it was consumable is not a bug that can be apologised for afterwards.
USABLE_ITEM_TYPES = (2, 3, 5, 59, 109, 150)


#: THE BAG'S OWN TABS, in the game's own order (#1702). The client spells them itself —
#: `UIBagTab` reads `Special = 1, Resource = 2, SpeedUp = 3, Hero = 4, Equip = 5,
#: Gift = 6` — so the SET and the ORDER are the game's, not ours.
#:
#: What the client does NOT hand over is which tab an item falls into: the row it keeps
#: carries a `type` and nothing about the bag's own filing. So the types are mapped here,
#: read off the player's own bag by name — a speed-up is a speed-up, an «Осколок» is a
#: hero piece, a «Сундук» is a gift. **A type nobody has classified falls into the game's
#: own first tab, `Special`**, which is where the game itself puts what it cannot file.
BAG_TABS = (1, 2, 3, 4, 5, 6)
BAG_TAB_SPECIAL = 1
BAG_TAB_OF_TYPE = {
    2: 3,                                     # speed-ups
    3: 2,                                     # resource packs, potions, diamonds
    5: 6, 59: 6, 109: 6, 150: 6,              # chests and boxes
    99: 4, 137: 4, 141: 4, 142: 4,            # hero shards and fragments
    103: 5, 132: 5, 143: 5,                   # equipment and its pieces
}


def item_tab_expr(id_expr: str = "id") -> str:
    """Lua *expression* -> which of the bag's own tabs an item belongs to (1..6)."""
    pairs = " ".join("m[%d] = %d" % (kind, tab) for kind, tab in sorted(BAG_TAB_OF_TYPE.items()))
    return (
        "((function(i) local k = -1 "
        "pcall(function() k = math.floor(tonumber("
        "DataCenter.ItemTemplateManager:GetItemTemplate(i).type) or -1) end) "
        "local m = {} %(pairs)s "
        "return m[k] or %(special)d end)(%(id)s))"
        % {"pairs": pairs, "special": BAG_TAB_SPECIAL, "id": id_expr}
    )


def use_bag_item() -> str:
    """Use `DataCenter.__lw_use_num` of item `DataCenter.__lw_use_id`, stack by stack.

    The general form of what `use_stamina_items` does for energy: the bag keeps one entry
    per STACK, so a hundred of something may be several, and each is spent no further than
    it goes. The send is `item.use` with a TABLE — `{uuid = <the stack's own uuid>,
    num = n}` — which is the only shape of five tried live that this client will serialise
    (docs/research/inventory.md).

    It never spends more than was asked for and never more than the bag holds, and it
    refuses outright for a kind that is not in :data:`USABLE_ITEM_TYPES`.
    """
    return (
        "local id = math.floor(tonumber(DataCenter.__lw_use_id) or 0) "
        "local want = math.floor(tonumber(DataCenter.__lw_use_num) or 0) "
        "local D, T = DataCenter.ItemData, DataCenter.ItemTemplateManager "
        "local used, why = 0, '' "
        "local kind = -1 "
        "pcall(function() kind = math.floor(tonumber(T:GetItemTemplate(id).type) or -1) end) "
        "local ok_kind = false "
        "for _, k in ipairs({%(kinds)s}) do if k == kind then ok_kind = true end end "
        "if id <= 0 or want <= 0 then why = 'nothing-asked' "
        "elseif not ok_kind then why = 'not-usable' "
        "elseif D == nil then why = 'no-bag' else "
        "local stacks = {} "
        "pcall(function() for _, v in pairs(D.ItemInfos or {}) do "
        "if math.floor(tonumber(v.itemId) or 0) == id then "
        "stacks[#stacks + 1] = {uuid = v.uuid, n = math.floor(tonumber(v.count) or 0)} "
        "end end end) "
        "for _, st in ipairs(stacks) do local left = want - used "
        "if left > 0 and st.n > 0 then local n = math.min(left, st.n) "
        "local sent = pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.ItemUse, {uuid = st.uuid, num = n}) end) "
        "if sent then used = used + n end end end "
        "if used == 0 and why == '' then why = 'none-in-bag' end end "
        "DataCenter.__lw_use = {id = id, want = want, used = used, kind = kind, why = why} "
        'CS.UnityEngine.Debug.LogError("ACT use_item id="..tostring(id).." want="..tostring(want)'
        '.." used="..tostring(used).." kind="..tostring(kind).." why="..tostring(why))'
        % {"kinds": ", ".join(str(k) for k in USABLE_ITEM_TYPES)}
    )


def use_bag_ids() -> str:
    """Open EVERY stack of every item id listed in `DataCenter.__lw_use_ids`, in one call.

    The general form of :func:`use_bag_item` for an ability whose answer is «all of
    them»: the duel's Monday pays for opening a KIND of box, an account holds several
    levels of it, and each level is several stacks. Done one press at a time that is a
    thread hijack per stack — half a second each, and the machine makes about 1.4 of them
    a second in total (docs/research/link-contention.md) — so the loop lives inside the
    one call, exactly as the alliance donation's thirty attempts do.

    The ids are parked as a comma-separated string, because `TAP` carries no arguments;
    the send is the same `item.use` table one stack at a time, and a kind the bag will
    not use is refused per id rather than failing the run.

    It leaves `DataCenter.__lw_use_all` = ``{ids, kinds, used, stacks, why}`` behind,
    with `used` the total count spent and `why` naming the ids it refused.
    """
    return (
        "local raw = tostring(DataCenter.__lw_use_ids or '') "
        "local D, T = DataCenter.ItemData, DataCenter.ItemTemplateManager "
        "local ids, used, stacks, bad, per = {}, 0, 0, {}, {} "
        # `[^,]+` and not `[^,%s]+`: this string is %-formatted below, so a Lua
        # character class of `%s` would be eaten as a format spec. `tonumber` ignores
        # the spaces anyway.
        "for piece in string.gmatch(raw, '[^,]+') do "
        "local n = math.floor(tonumber(piece) or 0) if n > 0 then ids[#ids + 1] = n end end "
        "local why = '' "
        "if #ids == 0 then why = 'nothing-asked' "
        "elseif D == nil then why = 'no-bag' else "
        "for _, id in ipairs(ids) do "
        "local kind = -1 "
        "pcall(function() kind = math.floor(tonumber(T:GetItemTemplate(id).type) or -1) end) "
        "local ok_kind = false "
        "for _, k in ipairs({%(kinds)s}) do if k == kind then ok_kind = true end end "
        "if not ok_kind then bad[#bad + 1] = id .. ':' .. kind else "
        "local mine = {} "
        "pcall(function() for _, v in pairs(D.ItemInfos or {}) do "
        "if math.floor(tonumber(v.itemId) or 0) == id then "
        "mine[#mine + 1] = {uuid = v.uuid, n = math.floor(tonumber(v.count) or 0)} "
        "end end end) "
        "for _, st in ipairs(mine) do if st.n > 0 then "
        "local sent = pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.ItemUse, {uuid = st.uuid, num = st.n}) end) "
        "if sent then used = used + st.n stacks = stacks + 1 "
        # PER ID, because the panel keeps a tally per GRADE (#2617): a run that opened
        # 31 R and 3 SSR is two different facts, and «44» is neither of them.
        "per[id] = (per[id] or 0) + st.n end end end end end "
        "if used == 0 and why == '' then why = 'none-in-bag' end end "
        "if #bad > 0 then why = why .. (why == '' and '' or ' ') .. 'not-usable=' "
        ".. table.concat(bad, '/') end "
        "local pairs_txt = {} "
        "for id, n in pairs(per) do pairs_txt[#pairs_txt + 1] = id .. ':' .. n end "
        "DataCenter.__lw_use_all = {ids = raw, used = used, stacks = stacks, why = why, "
        "per = table.concat(pairs_txt, ',')} "
        'CS.UnityEngine.Debug.LogError("ACT use_bag_ids ids="..tostring(raw)'
        '.." used="..tostring(used).." stacks="..tostring(stacks).." why="..tostring(why))'
        % {"kinds": ", ".join(str(k) for k in USABLE_ITEM_TYPES)}
    )


def bag_use_all_report() -> str:
    """Lua *expression* -> one line about the last «open all of these» call."""
    return (
        "(function() local u = DataCenter.__lw_use_all or {} "
        "return 'ids=' .. tostring(u.ids or '-') .. "
        "' used=' .. tostring(math.floor(tonumber(u.used) or 0)) .. "
        "' stacks=' .. tostring(math.floor(tonumber(u.stacks) or 0)) .. "
        "' why=' .. tostring((u.why ~= nil and u.why ~= '') and u.why or '-') end)()"
    )


def bag_use_all_per_id() -> str:
    """Lua *expression* -> «540201:31,540401:3» — what the last «open all» spent, by id."""
    return ("(function() local u = DataCenter.__lw_use_all or {} "
            "local s = tostring(u.per or '') "
            "if s == '' then return '-' end return s end)()")


def bag_use_all_used() -> str:
    """Lua *expression* -> how many items the last «open all of these» call spent."""
    return ("(function() local u = DataCenter.__lw_use_all or {} "
            "return math.floor(tonumber(u.used) or 0) end)()")


def bag_count_of_ids() -> str:
    """Lua *expression* -> how many of `DataCenter.__lw_use_ids` the bag holds in total."""
    return (
        "(function() local raw = tostring(DataCenter.__lw_use_ids or '') "
        "local D = DataCenter.ItemData if D == nil then return 0 end "
        "local want = {} "
        "for piece in string.gmatch(raw, '[^,]+') do "
        "local n = math.floor(tonumber(piece) or 0) if n > 0 then want[n] = true end end "
        "local total = 0 "
        "pcall(function() for _, v in pairs(D.ItemInfos or {}) do "
        "if want[math.floor(tonumber(v.itemId) or 0)] then "
        "total = total + math.floor(tonumber(v.count) or 0) end end end) "
        "return total end)()"
    )


def bag_item_rows() -> str:
    """Lua *expression* -> one line per item id in `DataCenter.__lw_use_ids`.

    ``id|count|colour|icon|name``, joined by `` ;; ``. The NAME and the ICON are the
    game's own — `GetName` does the locale lookup for whatever language the client is in,
    and the icon is the row's own file name, never computed from the id (an item wears a
    picture belonging to a different number, docs/research/inventory.md).

    One call for the whole list, because a read is a thread hijack whatever it asks.
    """
    return (
        "(function() local raw = tostring(DataCenter.__lw_use_ids or '') "
        "local D, T = DataCenter.ItemData, DataCenter.ItemTemplateManager "
        "if T == nil then return '' end "
        "local want, order = {}, {} "
        "for piece in string.gmatch(raw, '[^,]+') do "
        "local n = math.floor(tonumber(piece) or 0) "
        "if n > 0 and not want[n] then want[n] = 0 order[#order + 1] = n end end "
        "if D ~= nil then pcall(function() for _, v in pairs(D.ItemInfos or {}) do "
        "local id = math.floor(tonumber(v.itemId) or 0) "
        "if want[id] ~= nil then want[id] = want[id] + math.floor(tonumber(v.count) or 0) "
        "end end end) end "
        "local out = {} "
        "for _, id in ipairs(order) do "
        "local name, icon, colour = '', '', 0 "
        "pcall(function() name = tostring(T:GetName(id) or '') end) "
        "pcall(function() local row = T:GetItemTemplate(id) "
        "icon = tostring(row.icon or '') "
        "colour = math.floor(tonumber(row.color or row.quality) or 0) end) "
        "out[#out + 1] = id .. '|' .. want[id] .. '|' .. colour .. '|' .. icon "
        ".. '|' .. name end "
        "return table.concat(out, ' ;; ') end)()"
    )


#: THE DRONE, AS THE CLIENT SPELLS IT (#2617). The game calls it a «tactical weapon» in
#: its own code and «UAV» on the wire (`push.uav.effects`, `push.uav.skillchip.changes`),
#: which is why nothing in `DataCenter` is named after a drone at all. One per account,
#: id 1000, read off `TacticalWeaponManager`.
DRONE_WEAPON_ID = 1000


#: HOW MUCH OF A COST ITEM THE ACCOUNT HOLDS — and it is NOT the bag (#2617, measured).
#: The drone's two prices are 7037 (components) and 7038 (gears), and neither is a stack
#: in `ItemData.ItemInfos`: a live account showed 0 of both there while the client's own
#: gate said it could pay, because they are RESOURCES —
#: `ResourceItemDataManager` — and a resource is a running total, not a stack. Reading
#: the wrong store is how a recipe reports «not enough» over a purse of 71 976 670.
_RES_COUNTS_LUA = (
    "local function _lw_res_counts() local out = {} "
    "local R = DataCenter and DataCenter.ResourceItemDataManager "
    "if R ~= nil then pcall(function() for k, v in pairs(R.itemList or {}) do "
    "local id = 0 local n = 0 "
    "if type(v) == 'table' then "
    "id = math.floor(tonumber(v.itemId or v.id or k) or 0) "
    "n = math.floor(tonumber(v.count or v.num or v.value or v.number) or 0) end "
    "if id > 0 then out[id] = (out[id] or 0) + n end end end) end "
    # …and the bag on top of it, for a cost item that IS a stack.
    "local D = DataCenter and DataCenter.ItemData "
    "if D ~= nil then pcall(function() for _, v in pairs(D.ItemInfos or {}) do "
    "local id = math.floor(tonumber(v.itemId) or 0) "
    "if id > 0 then out[id] = (out[id] or 0) + math.floor(tonumber(v.count) or 0) end "
    "end end) end return out end "
)


def _drone_info_lua(var: str = "info") -> str:
    """Lua *statements* -> park the account's drone in a local of that name (or nil).

    Two ways round, because the manager answers one of them on any given call: the
    getter, and the table it keeps. Probed live — see docs/research/drone-upgrade.md.
    """
    return (
        "local %(var)s = nil "
        "local M = DataCenter and DataCenter.TacticalWeaponManager "
        "if M ~= nil then "
        "pcall(function() %(var)s = M:GetTacticalWeaponInfo(%(id)d) end) "
        "if type(%(var)s) ~= 'table' then "
        "pcall(function() for _, v in pairs(M.tacticalWeaponInfos or {}) do "
        "%(var)s = v end end) end end "
        % {"var": var, "id": DRONE_WEAPON_ID}
    )


def drone_state() -> str:
    """Lua *expression* -> one line about the drone: level, cap, cost and what is held.

    Everything the gate needs in ONE reading, because a read is a thread hijack and the
    machine makes about 1.4 of them a second (docs/research/link-contention.md).
    """
    return (
        "(function() " + _RES_COUNTS_LUA + _drone_info_lua() +
        "if type(info) ~= 'table' then return 'lv=0 max=0 can=0 why=no-drone' end "
        "local row = info.levelTemplate "
        "if type(row) ~= 'table' then pcall(function() row = info:GetLevelTemplate() end) end "
        "local cost = {} "
        "if type(row) == 'table' and type(row.cost_resItem) == 'table' then "
        "for _, c in pairs(row.cost_resItem) do "
        "if type(c) == 'table' then cost[#cost + 1] = {id = math.floor(tonumber(c.id) or 0), "
        "n = math.floor(tonumber(c.value) or 0)} end end end "
        "local have = _lw_res_counts() "
        "local bits = {} "
        "for _, c in ipairs(cost) do "
        "bits[#bits + 1] = c.id .. ':' .. (have[c.id] or 0) .. '/' .. c.n end "
        "local function ask(name) local v = nil "
        "local ok = pcall(function() v = info[name](info) end) "
        "if not ok then return -1 end if v == true then return 1 end "
        "if v == false then return 0 end return math.floor(tonumber(v) or -1) end "
        "return 'lv=' .. tostring(math.floor(tonumber(info.level) or 0)) .. "
        "' max=' .. tostring(math.floor(tonumber(info.maxLevel) or 0)) .. "
        "' capped=' .. tostring(ask('IsReachLevelLimit')) .. "
        "' topped=' .. tostring(ask('IsReachMaxLevel')) .. "
        "' pays=' .. tostring(ask('HasResItemToUpgrade')) .. "
        "' cost=' .. table.concat(bits, ',') end)()"
    )


def drone_level() -> str:
    """Lua *expression* -> the drone's level right now, or 0. The proof a press worked."""
    return ("(function() " + _drone_info_lua() +
            "if type(info) ~= 'table' then return 0 end "
            "return math.floor(tonumber(info.level) or 0) end)()")


def drone_upgrades_left() -> str:
    """Lua *expression* -> how many levels the account can buy RIGHT NOW.

    What `xall` counts down: the smallest of «what each cost item buys», nothing at all
    when the client says the level is capped by the building or by the drone's own
    ceiling, and never more than the levels parked in `DataCenter.__lw_drone_max`
    (0 = as many as the bag pays for).
    """
    return (
        "(function() " + _RES_COUNTS_LUA + _drone_info_lua() +
        "if type(info) ~= 'table' then return 0 end "
        "local function ask(name) local v = nil "
        "local ok = pcall(function() v = info[name](info) end) "
        "return ok and v == true end "
        "if ask('IsReachMaxLevel') or ask('IsReachLevelLimit') then return 0 end "
        "local row = info.levelTemplate "
        "if type(row) ~= 'table' then pcall(function() row = info:GetLevelTemplate() end) end "
        "if type(row) ~= 'table' or type(row.cost_resItem) ~= 'table' then return 0 end "
        "local have = _lw_res_counts() "
        "local can = -1 "
        "for _, c in pairs(row.cost_resItem) do if type(c) == 'table' then "
        "local id, n = math.floor(tonumber(c.id) or 0), math.floor(tonumber(c.value) or 0) "
        "if n > 0 then local buys = math.floor((have[id] or 0) / n) "
        "if can < 0 or buys < can then can = buys end end end end "
        "if can < 0 then can = 0 end "
        "local cap = math.floor(tonumber(DataCenter.__lw_drone_max) or 0) "
        "if cap > 0 and can > cap then can = cap end "
        "return can end)()"
    )


def drone_level_up() -> str:
    """Press «upgrade the drone» once — one `weapon.up.lv` for the account's own drone.

    The send is `MsgDefines.TacticalWeaponLevelUpMessage`; what it carries is
    docs/research/drone-upgrade.md, proven live rather than guessed. Nothing here gates
    the ability: the recipe reads :func:`drone_upgrades_left` and presses that many
    times, so a press that arrives with nothing to pay with is refused by the server
    exactly as the game's own button would be.
    """
    return (
        _drone_info_lua() +
        "local before = 0 "
        "if type(info) == 'table' then before = math.floor(tonumber(info.level) or 0) end "
        "local sent = pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.TacticalWeaponLevelUpMessage, "
        "{id = %(id)d}) end) "
        "DataCenter.__lw_drone = {sent = sent and 1 or 0, level = before} "
        'CS.UnityEngine.Debug.LogError("ACT drone_up sent="..tostring(sent)'
        '.." level="..tostring(before))'
        % {"id": DRONE_WEAPON_ID}
    )


def bag_use_report() -> str:
    """Lua *expression* -> one line about the last item use, for the log and the panel."""
    return (
        "(function() local u = DataCenter.__lw_use or {} "
        "return 'id=' .. tostring(math.floor(tonumber(u.id) or 0)) .. "
        "' want=' .. tostring(math.floor(tonumber(u.want) or 0)) .. "
        "' used=' .. tostring(math.floor(tonumber(u.used) or 0)) .. "
        "' kind=' .. tostring(math.floor(tonumber(u.kind) or -1)) .. "
        "' why=' .. tostring(u.why or '-') end)()"
    )


def item_usable_expr(id_expr: str = "id") -> str:
    """Lua *expression* -> 1 when an item of that id is one the bag will use."""
    return (
        "((function(i) local k = -1 "
        "pcall(function() k = math.floor(tonumber("
        "DataCenter.ItemTemplateManager:GetItemTemplate(i).type) or -1) end) "
        "for _, t in ipairs({%(kinds)s}) do if t == k then return 1 end end "
        "return 0 end)(%(id)s))"
        % {"kinds": ", ".join(str(k) for k in USABLE_ITEM_TYPES), "id": id_expr}
    )


def use_stamina_items() -> str:
    """Spend stamina items out of the bag until `DataCenter.__lw_stam_want` is bought.

    **The send is `item.use` with a TABLE** — `{uuid = <the stack's own uuid>, num = n}`,
    the shape a live recording of the fireworks caught (docs/research/fireworks.md) and
    the only one of five tried that the client would serialise: a positional
    `(uuid, num)` returns cleanly and does nothing, and a table with `count` instead of
    `num` throws inside the serialiser. Verified live: one ten-point item, purse 135 → 145.

    The big denominations go first, and a stack is spent no further than it goes — the
    bag keeps one entry per STACK, so a hundred fifties may be several. What it cannot
    make up exactly it stops short of rather than overshooting: the caller asked for a
    number, and spending one more item than that is spending somebody's inventory.
    """
    return (
        "local want = math.floor(tonumber(DataCenter.__lw_stam_want) or 0) "
        "local D = DataCenter.ItemData "
        "local spent, used = 0, {} "
        "local before = %(energy)s "
        "if D ~= nil and want > 0 then "
        "for _, pair in ipairs({%(items)s}) do "
        "local id, worth = pair[1], pair[2] "
        "local stacks = {} "
        "pcall(function() for _, v in pairs(D.ItemInfos or {}) do "
        "if math.floor(tonumber(v.itemId) or 0) == id then "
        "stacks[#stacks + 1] = {uuid = v.uuid, n = math.floor(tonumber(v.count) or 0)} "
        "end end end) "
        "for _, st in ipairs(stacks) do "
        "local room = math.floor((want - spent) / worth) "
        "if room > 0 then local n = math.min(room, st.n) "
        "if n > 0 then "
        "local ok = pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.ItemUse, {uuid = st.uuid, num = n}) end) "
        "if ok then spent = spent + n * worth "
        "used[#used + 1] = tostring(id) .. 'x' .. tostring(n) end end end end end end "
        "DataCenter.__lw_stam = {want = want, spent = spent, before = before, "
        "used = table.concat(used, ',')} "
        'CS.UnityEngine.Debug.LogError("ACT use_stamina want="..tostring(want)'
        '.." spent="..tostring(spent).." used="..tostring(table.concat(used, ",")))'
        % {"energy": golden_energy(),
           "items": ", ".join("{%d, %d}" % (i, v) for i, v in STAMINA_ITEMS)}
    )


def free_stamina_ready() -> str:
    """Lua *expression* -> 1 when the day's FREE energy has not been taken yet.

    The game keeps two fields about it on the player — `lastClaimFreeStaminaTime`, the
    stamp of the last claim, and `todayFreeStamina`. The stamp is the one trusted here,
    measured against the SERVER's own midnight (`GetTomorrowZero()` less a day), because a
    count called «today» is only as good as whoever resets it and a stamp says when.

    Read out of the client's own copy: no request, no window, nothing the server hears.
    """
    return ("(function() local p = nil "
            "pcall(function() p = LuaEntry.Player end) "
            "if p == nil then return -1 end "
            "local at = tonumber(rawget(p, 'lastClaimFreeStaminaTime')) or 0 "
            "local zero = 0 "
            "pcall(function() zero = math.floor(tonumber("
            "UITimeManager:GetInstance():GetTomorrowZero()) or 0) end) "
            "if zero <= 0 then return -1 end "
            "local day = zero - 86400000 "
            "if at >= day then return 0 end "
            "return 1 end)()")


def claim_free_stamina() -> str:
    """Take the day's FREE energy — `user.claim.daily.stamina`, one send, no window.

    FIRST OF THE THREE, and the order is the operator's own (#2390): «сначала бесплатные,
    потом за 300 алмазов и только в конце из запасов». The bag comes LAST because what is
    in it does not come back by itself, while the free claim and the cheap refill are
    renewed every server day — spending the reserve while a free one is standing there is
    the one order that cannot be undone.

    The purse before the send is parked so the caller can say what it gave.
    """
    return (
        "DataCenter.__lw_freestam = {before = %(energy)s, sent = false} "
        "local ok = pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.ClaimDailyStamina, {}) end) "
        "DataCenter.__lw_freestam.sent = ok "
        'CS.UnityEngine.Debug.LogError("ACT claim_free_stamina sent="..tostring(ok)'
        '.." before="..tostring(DataCenter.__lw_freestam.before))'
        % {"energy": golden_energy()}
    )


def free_stamina_report() -> str:
    """Lua *expression* -> what the free claim gave, for the log."""
    return (
        "(function() local f = DataCenter.__lw_freestam or {} "
        "local before = math.floor(tonumber(f.before) or 0) "
        "local now = math.floor(tonumber(%(energy)s) or 0) "
        "return 'sent=' .. tostring(f.sent == true) .. "
        "' before=' .. tostring(before) .. ' now=' .. tostring(now) .. "
        "' gained=' .. tostring(now - before) end)()"
        % {"energy": golden_energy()}
    )


def stamina_refill_bought_today() -> str:
    """Lua *expression* -> how many diamond refills of energy were bought today.

    `-1` when the client cannot say. The player carries two fields — `playerStaminaGoldNum`
    (the count) and `playerStaminaGoldTime` (the stamp of the last one) — and the stamp is
    what makes the count trustworthy: a count called «today» is only as good as whoever
    resets it, so a stamp older than the SERVER's own midnight is read as zero however the
    count reads. The same rule `free_stamina_ready` keeps, and for the same reason.
    """
    return ("(function() local p = nil "
            "pcall(function() p = LuaEntry.Player end) "
            "if p == nil then return -1 end "
            "local n = tonumber(rawget(p, 'playerStaminaGoldNum')) "
            "if n == nil then return -1 end "
            "local at = tonumber(rawget(p, 'playerStaminaGoldTime')) or 0 "
            "local zero = 0 "
            "pcall(function() zero = math.floor(tonumber("
            "UITimeManager:GetInstance():GetTomorrowZero()) or 0) end) "
            "if zero <= 0 then return -1 end "
            "if at < (zero - 86400000) then return 0 end "
            "return math.floor(n) end)()")


def player_gems() -> str:
    """Lua *expression* -> the diamond purse (`LuaEntry.Player.gold`), or `-1`.

    Diamonds are what the game calls `gold` on the player; the yellow bricks are
    `goldBrickInfos` and are a different currency entirely. Read out of the client's own
    copy — no request, no window.
    """
    return ("(function() local v = nil "
            "pcall(function() v = tonumber(LuaEntry.Player.gold) end) "
            "if v == nil then return -1 end "
            "return math.floor(v) end)()")


def buy_stamina_refill() -> str:
    """Buy the day's refill of march energy for diamonds — one send, no window.

    SECOND OF THE THREE (#2390): after the day's free claim and before the bag. **The
    price cannot be read anywhere in the client** — not a config table, not a Lua
    function, and not the board's own reply, which carries the purse and the stamps and
    nothing about a cost (`docs/research/march-energy.md`). So the caller gates on the
    COUNT of refills already bought today, which by the operator's description of the
    ladder identifies the cheap one, and prices the purchase AFTERWARDS out of the
    diamond purse.

    Both purses are parked before the send so the report can say what it cost.
    """
    return (
        "DataCenter.__lw_stambuy = {gems = %(gems)s, energy = %(energy)s, sent = false} "
        "local ok = pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.UserRecoverPlayerStamina, {}) end) "
        "DataCenter.__lw_stambuy.sent = ok "
        'CS.UnityEngine.Debug.LogError("ACT buy_stamina_refill sent="..tostring(ok)'
        '.." gems="..tostring(DataCenter.__lw_stambuy.gems))'
        % {"gems": player_gems(), "energy": golden_energy()}
    )


def stamina_refill_report() -> str:
    """Lua *expression* -> what the refill cost and what it gave, for the log.

    `paid` is the diamond purse before less the purse now — the only way this bot has of
    learning a price it cannot ask for. A negative one means something else credited
    diamonds in the same second and the number is worthless; the recipe treats that as
    «unknown» rather than as «free».
    """
    return (
        "(function() local b = DataCenter.__lw_stambuy or {} "
        "local gems0 = math.floor(tonumber(b.gems) or -1) "
        "local gems1 = math.floor(tonumber(%(gems)s) or -1) "
        "local e0 = math.floor(tonumber(b.energy) or 0) "
        "local e1 = math.floor(tonumber(%(energy)s) or 0) "
        "local paid = -1 "
        "if gems0 >= 0 and gems1 >= 0 then paid = gems0 - gems1 end "
        "return 'sent=' .. tostring(b.sent == true) .. "
        "' gems_before=' .. tostring(gems0) .. ' gems_now=' .. tostring(gems1) .. "
        "' paid=' .. tostring(paid) .. "
        "' energy_before=' .. tostring(e0) .. ' energy_now=' .. tostring(e1) .. "
        "' gained=' .. tostring(e1 - e0) end)()"
        % {"gems": player_gems(), "energy": golden_energy()}
    )


def stamina_refill_paid() -> str:
    """Lua *expression* -> the diamonds the last refill cost, or `-1` when unknowable."""
    return (
        "(function() local b = DataCenter.__lw_stambuy or {} "
        "local gems0 = math.floor(tonumber(b.gems) or -1) "
        "local gems1 = math.floor(tonumber(%(gems)s) or -1) "
        "if gems0 < 0 or gems1 < 0 then return -1 end "
        "local paid = gems0 - gems1 "
        "if paid < 0 then return -1 end "
        "return paid end)()"
        % {"gems": player_gems()}
    )


def stamina_report() -> str:
    """Lua *expression* -> one line about the last stamina purchase, for the log."""
    return (
        "(function() local p = DataCenter.__lw_stam or {} "
        "return 'want=' .. tostring(math.floor(tonumber(p.want) or 0)) .. "
        "' bought=' .. tostring(math.floor(tonumber(p.spent) or 0)) .. "
        "' items=' .. tostring(p.used or '-') .. "
        "' before=' .. tostring(math.floor(tonumber(p.before) or 0)) .. "
        "' now=' .. tostring(%(energy)s) end)()"
        % {"energy": golden_energy()}
    )


def stamina_stock() -> str:
    """Lua *expression* -> what the bag holds of each stamina item, and what it is worth."""
    return (
        "(function() local D = DataCenter.ItemData local T = DataCenter.ItemTemplateManager "
        "local out = {} "
        "for _, pair in ipairs({%(items)s}) do local id, worth = pair[1], pair[2] "
        "local n = 0 "
        "pcall(function() for _, v in pairs(D.ItemInfos or {}) do "
        "if math.floor(tonumber(v.itemId) or 0) == id then "
        "n = n + math.floor(tonumber(v.count) or 0) end end end) "
        "local nm = '' pcall(function() nm = tostring(T:GetName(id) or '') end) "
        "out[#out + 1] = tostring(id) .. ':' .. tostring(n) .. 'x' .. tostring(worth) .. "
        "'=' .. tostring(n * worth) .. ' (' .. nm:gsub('%%s+', ' ') .. ')' end "
        "return table.concat(out, ' | ') .. ' | stamina=' .. tostring(%(energy)s) end)()"
        % {"items": ", ".join("{%d, %d}" % (i, v) for i, v in STAMINA_ITEMS),
           "energy": golden_energy()}
    )


#: The config id of the golden / invading zombie. The one number that identifies it.
GOLDEN_ZOMBIE_CFG = 1030000

#: How close to landing a march has to be before the wait switches from three-second
#: beats to one-second ones (#1702). Four seconds: long enough that an ordinary hop of a
#: chain — two tiles, about three seconds — is watched closely from the start, short
#: enough that a march across the map is not.
GOLDEN_ETA_NEAR_MS = 4000

#: How far the origin has to move before the camera is flown to it again (#1702). The
#: client keeps a district loaded around where it is looking, and a chain's kills are a
#: handful of tiles apart — measured live, two tiles — so a flight per kill buys nothing
#: and costs the settle that follows it. Eight tiles is comfortably inside one district
#: and comfortably smaller than the hop that would leave it.
GOLDEN_LOOK_AGAIN = 8

#: How near the camera a target has to be before its ABSENCE means anything (#1702).
#: The client draws — and answers about — a window of roughly sixty tiles around wherever
#: it is looking. Inside that window "the enumerator did not return it" is a fact about
#: the map; outside it, it is a fact about what nobody has looked at. That distinction is
#: THE_LIST_RULE (#1272) applied to monsters: a row leaves the registry only when the map
#: SAID it is gone.
GOLDEN_SEEN_REACH = 60

#: The shape of the REFRESH — a short ring of camera stops around the origin (#1702).
#: A stop is a camera move and an enumerator read, and the gap is what the client's region
#: loader needs to draw what it has been sent. Measured live, and this is the measurement
#: the whole design rests on: **a lap of the map leaves the client holding the district it
#: ENDED in and nothing else.** Standing 488 tiles away, `GetMonsterListInArea` answered
#: `0` golden zombies within 300 tiles of the base; thirteen stops later it answered `17`,
#: the nearest of them **14 tiles** from the front door. The ground was never empty — it
#: was never loaded. One wide look at the lap's own height does not fix it either (tried:
#: the first pick still came out 488 tiles away). Only dwell does.
GOLDEN_REFRESH_RING = 80
GOLDEN_REFRESH_STOPS = 6
GOLDEN_REFRESH_GAP = 1.1

#: How many PROVEN disappearances are worth an expensive refresh of the registry (#1702).
#: The operator's own number — «только если 2–5 монстров пропали, значит нужно обновить»
#: — because the camera sits on the kills and the picture is nearly always current; a
#: refresh after every kill buys a redraw nobody needed. Three is the middle of that
#: band, and the recipe's `refresh_after` overrides it per run.
GOLDEN_REFRESH_AFTER = 3

#: Fallback cost of one solo attack, when the game will not price it. The live answer
#: on 2026-08-19 was 10; this is only what keeps the gate honest if the call fails.
GOLDEN_ATTACK_COST = 10

#: HOW MANY RE-AIMS IN A ROW MAY FAIL TO PRODUCE A MARCH before the run stops trying to
#: re-aim at all and sends the ordinary way out of the base (#2390).
#:
#: Measured live: a chain re-aimed a march that no longer existed for **nine minutes and
#: zero attacks**. The squad was standing at home, `GetOwnerMarches` held nothing, and the
#: run went on ordering `world.march.change` at the uuid it had been holding since its last
#: send — because that uuid was remembered and never checked again. Every lap answered
#: `reaimed=1`, every lap's proof answered `launched=0`, and the blame landed on the
#: ZOMBIE: the target was written off, another was picked, and the ghost march was re-aimed
#: at that one instead.
#:
#: Two, because one is the ordinary case the optimism was bought for — the client drops the
#: march object the instant a fight resolves — and a second one in a row is the client
#: saying it has no march, twice, which is a fact rather than a race.
GOLDEN_REAIM_MISSES = 2

#: Where the run's own state is parked in the game VM, so it survives between presses
#: (`TAP` carries no arguments) and a panel restart.
_GOLD = "DataCenter.__lw_gold"

_GOLD_P = "local p = %s or {} " % _GOLD

#: WHERE THE TWO CHAINS AGREE NOT TO TREAD ON EACH OTHER (#1702). Two squads hunt at once
#: (`tools/lib/golden_twin.py`), each with its own state table, and the one thing they
#: must not do is march at the same zombie: the second order is refused in silence and
#: the lap is wasted. So a send writes the tile down here and a pick skips a tile the
#: OTHER run has written — one table, deliberately spelled without the `__lw_gold`
#: prefix, because that prefix is what the twin renames.
#:
#: A claim carries the squad that made it and the moment it was made, and it goes stale:
#: a run that dies mid-march would otherwise lock its last target out of the map for the
#: rest of the night.
GOLDEN_CLAIM_SEC = 300

#: `_goldfree(p, pid)` -> true when no OTHER run is on that tile. In scope everywhere,
#: because it goes into the prelude every golden expression already opens with.
_GOLD_CLAIMS = (
    "local _zc = DataCenter.__lw_zclaims "
    "if type(_zc) ~= 'table' then _zc = {} DataCenter.__lw_zclaims = _zc end "
    "local function _goldnow() local t = nil "
    "pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) "
    "if t == nil then t = os.time() * 1000 end return t end "
    "local function _goldfree(p, pid) "
    "local c = _zc[tostring(pid)] "
    "if c == nil then return true end "
    "if tostring(c.sq) == tostring(p.squad) then return true end "
    "return (_goldnow() - (tonumber(c.at) or 0)) > (%d * 1000) end "
    "local function _goldclaim(p, pid) "
    "_zc[tostring(pid)] = {sq = p.squad, at = _goldnow()} end "
    % GOLDEN_CLAIM_SEC
)

_GOLD_P = _GOLD_P + _GOLD_CLAIMS

#: «МОЖЕТ ЛИ ЭТОТ ОТРЯД ПРИНЯТЬ ПРИКАЗ» — the game's own answer, and never `canMarch`
#: (#1702). Given a formation, this Lua function is `true` only when the squad is in the
#: base (`ArmyFormationState.Free`, 0) and the game's own `IsFree()` agrees.
#:
#: `canMarch` was read here for a while and it is a RED HERRING: it is recomputed by the
#: real dispatch render (`UIFormationSelectListV2`) and by nothing else, so a headless
#: session sees whatever it was left at. Measured live, one press apart, on a squad
#: standing at home with a full army::
#:
#:     squad=2 state=0 free=1 soldiers=2631 status=- march=- team=0    (read_squad_state)
#:     squad2 state=0 canMarch=false soldiers=2631                     (the old gate)
#:
#: The whole rest of this repository already knew — `create_rally.md`,
#: `read_squad_state.md` and the rally limits all ask `state == 0` with `IsFree()`. The
#: golden family was the one place that did not, and the operator read the result of it
#: as «в логи пишется, что ОТРЯД ЗАНЯТ, но это НЕ ТАК».
_SQUAD_FREE = (
    "(function(f) local st = math.floor(tonumber(f.state) or -1) "
    "if st ~= 0 then return false end "
    "local ok, idle = pcall(function() return f:IsFree() end) "
    "if ok and idle ~= nil then return (idle and true or false) end return true end)"
)


#: THE REGISTRY LOSES A ROW ONLY WHERE THE MAP WAS READ (#1702) — the secret tasks' rule,
#: word for word (#1272). `present` is what THIS scan's enumerator returned; a queued
#: target missing from it is dropped only when both halves of "we looked" hold:
#:
#:   * it is inside the drawn window around the camera (:data:`GOLDEN_SEEN_REACH`), and
#:   * the client says it holds that tile's district (`HasPointInfo`).
#:
#: Anything else — a far target, a district the client never fetched, an oracle that will
#: not answer — is "we did not look there", and the row stays. A row that stays costs one
#: wasted send at worst; a row wrongly dropped is a zombie the chain can never come back
#: to, because nothing re-adds what the scan cannot see.
_GOLD_REAP = (
    "local function _goldreap(p, ws, present, cx, cy) "
    "local kept, gone = {}, 0 "
    "for _, t in ipairs(p.targets or {}) do "
    "local keep = true "
    "if not present[tostring(t.pid)] then "
    "local dx = (tonumber(t.x) or -1e9) - cx local dy = (tonumber(t.y) or -1e9) - cy "
    "local near = (dx * dx + dy * dy) <= REACH * REACH "
    "local known = nil "
    "pcall(function() known = ws:HasPointInfo(t.pid) end) "
    "if near and known == true then keep = false end end "
    "if keep then kept[#kept + 1] = t else gone = gone + 1 end end "
    "p.targets = kept "
    "if gone > 0 then "
    "p.vanished = (tonumber(p.vanished) or 0) + gone "
    "p.since_refresh = (tonumber(p.since_refresh) or 0) + gone end "
    "return gone end "
).replace("REACH", str(GOLDEN_SEEN_REACH))


def golden_energy() -> str:
    """Lua *expression* -> the player's energy right now, as a whole number.

    `LuaEntry.Player.stamina` is the purse the game spends on a monster march; the
    method form is asked second because it is the one that exists on older builds.
    """
    return ("(function() local v = nil "
            "pcall(function() v = tonumber(LuaEntry.Player.stamina) end) "
            "if v == nil then pcall(function() v = tonumber(LuaEntry.Player:GetCurStamina()) end) end "
            "return math.floor(v or 0) end)()")


def golden_attack_cost() -> str:
    """Lua *expression* -> what ONE solo attack costs in energy, the game's own answer."""
    return ("(function() local v = nil "
            "pcall(function() v = tonumber(MarchUtil.GetCostStaminaByTargetType("
            "MarchTargetType.ATTACK_MONSTER)) end) "
            "if v == nil or v <= 0 then return %d end return math.floor(v) end)()"
            % GOLDEN_ATTACK_COST)


#: Find the `WorldScene` MonoBehaviour and cache it. The world's controller is the only
#: thing that can enumerate monsters, and it exists only in the world scene.
_GOLD_WS = (
    "local ws = DataCenter.__lw_gold_ws "
    "local alive = false "
    "pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) "
    "if not alive then ws = nil "
    "pcall(function() local arr = CS.UnityEngine.Object.FindObjectsOfType("
    "typeof(CS.UnityEngine.MonoBehaviour)) "
    "for i = 0, arr.Length - 1 do local mb = arr[i] local n = nil "
    "pcall(function() n = mb:GetType().Name end) "
    "if n == 'WorldScene' then ws = mb break end end end) "
    "DataCenter.__lw_gold_ws = ws end "
)


#: WHERE THE BASE IS, worked out from the game's own distance oracle (#1702).
#:
#: There is no call that hands the player's own tile over — `SceneUtils` carries exactly
#: one home-flavoured function, and it answers a DISTANCE. That is enough: a distance
#: field with a single minimum is solved by three readings and one small refine.
#:
#: `d(P) = |P - H|` is plain Euclid (measured live: 64 tiles east of home reads 64.0), so
#: with `C` the camera tile and two samples a step away on each axis,
#:
#:     u = (d0² - d1² + a²) / 2a        v = (d0² - d2² + b²) / 2b        H = C + (u, v)
#:
#: and the 7x7 sweep around the guess covers the rounding. `nil` when the oracle will not
#: answer — a caller then falls back to asking it per target, which is what the recipe
#: did before this existed.
_GOLD_HOME = (
    "local function _goldhome(ws, srv) "
    "if ws == nil then return nil end "
    "local function _d(x, y) if x < 0 or y < 0 then return nil end local v = nil "
    "pcall(function() local pid = ws:TilePosToIndex(CS.UnityEngine.Vector2Int(x, y)) "
    "v = tonumber(SceneUtils.TileDistanceToMyHome(pid, srv)) end) return v end "
    "local cam = ws.CurTilePos local cx, cy = cam.x, cam.y "
    "local step = 64 "
    "local d0 = _d(cx, cy) if d0 == nil then return nil end "
    "local ax, ay = step, step "
    "local d1 = _d(cx + ax, cy) if d1 == nil then ax = -step d1 = _d(cx + ax, cy) end "
    "local d2 = _d(cx, cy + ay) if d2 == nil then ay = -step d2 = _d(cx, cy + ay) end "
    "if d1 == nil or d2 == nil then return nil end "
    "local u = (d0 * d0 - d1 * d1 + ax * ax) / (2 * ax) "
    "local v = (d0 * d0 - d2 * d2 + ay * ay) / (2 * ay) "
    "local hx, hy = math.floor(cx + u + 0.5), math.floor(cy + v + 0.5) "
    # THE SWEEP IS A DESCENT, and it has to be (#1702). The oracle answers whole tiles, so
    # at five hundred tiles out the two squared readings the guess is built from carry a
    # rounding error worth several tiles — live, the guess missed and a fixed ±3 sweep
    # found nothing, which left the run with no base tile at all and every pick falling
    # back to asking the oracle per target. Coarse first, then fine, from wherever the
    # camera happens to be.
    "local best, bd = {x = hx, y = hy}, _d(hx, hy) "
    "for _, step in ipairs({8, 4, 2, 1}) do "
    "for dx = -3, 3 do for dy = -3, 3 do "
    "local nx, ny = best.x + dx * step, best.y + dy * step "
    "local dd = _d(nx, ny) "
    "if dd ~= nil and (bd == nil or dd < bd) then bd = dd best = {x = nx, y = ny} end "
    "end end end "
    "if best == nil or bd == nil or bd > 1.5 then return nil end "
    "pcall(function() best.pid = ws:TilePosToIndex("
    "CS.UnityEngine.Vector2Int(best.x, best.y)) end) "
    "return best end "
)


def golden_arm() -> str:
    """Set the run up: which squad, where home is, what an attack costs, what energy there is.

    Reads and parks, presses nothing. The squad is addressed by its SLOT — the 1/2/3/4
    the player sees and the panel offers — because a slot is what a person can choose;
    the formation uuid it resolves to is what the send needs, and it is looked up here
    rather than typed anywhere (docs/research/rally-squad-identity.md).

    **It does NOT work out where home is, and that is the second lesson of #1519.** The
    world scene opens on the player's own base, so «the tile under the camera» looks like
    a free answer — and it is one only if the scene was just entered. A client the panel
    keeps on the map has its camera wherever the last lap of `scan_map` left it, and the
    run that took that for home measured every distance from a corner of the world. The
    game answers the question properly: `SceneUtils.TileDistanceToMyHome(pid, serverId)`
    reads 0 at the base and 492 at a tile 492 away, and `golden_pick` uses it for the
    first pick.

    A squad reading zero soldiers is reported as empty and NOT sent: on this client that
    usually means «the army was never fetched», which `fill_empty_squads.md` fixes in
    about a third of a second — so the recipe calls that first and this arm is what
    decides whether it worked.
    """
    return (
        _GOLD_WS + _GOLD_HOME +
        # WHAT SURVIVES A RE-ARM (#1702). Arming builds the run from nothing, and the
        # two facts it must not throw away are WHERE THE BASE IS (a solve that needs
        # the camera near home) and WHERE THE SQUAD WAS LEFT. The operator watched the
        # second one bite: «найти ближайшего» arms first, so every press forgot that
        # the squad was standing in the field and measured from the house instead —
        # a pick hundreds of tiles away with zombies beside the squad.
        "local _keep = DataCenter.__lw_gold or {} "
        "local p = {} "
        "p.anchor = _keep.anchor "
        "p.last_sent = _keep.last_sent "
        "p.cfg = %(cfg)d "
        "p.squad = math.floor(tonumber(%(gold)s_squad) or 1) "
        "p.radius = math.floor(tonumber(%(gold)s_radius) or 2000) "
        "p.reach = math.floor(tonumber(%(gold)s_reach) or 0) "
        "p.cluster = math.floor(tonumber(%(gold)s_cluster) or 0) "
        "p.reach_near = p.reach "
        "p.breather_limit = math.floor(tonumber(%(gold)s_breathers) or 0) "
        "p.reach_far = math.floor(tonumber(%(gold)s_reach_far) or 0) "
        "p.dry = 0 "
        "p.breathers = 0 p.stalled = nil "
        "p.back = math.floor(tonumber(%(gold)s_back) or 0) "
        "p.limit = math.floor(tonumber(%(gold)s_limit) or 0) "
        "p.targets = {} p.used = {} p.attacks = 0 p.spent = 0 p.found = 0 "
        "p.vanished = 0 p.since_refresh = 0 p.refreshes = 0 "
        "pcall(function() p.server = math.floor(tonumber(LuaEntry.Player:GetSelfServerId()) or 0) end) "
        "p.anchor = nil "
        "p.ring_now = nil "
        "p.home = _goldhome(ws, p.server) "
        "if p.home ~= nil then DataCenter.__lw_gold_home = p.home "
        "elseif DataCenter.__lw_gold_home ~= nil then p.home = DataCenter.__lw_gold_home end "
        "p.cost = %(cost)s "
        "p.energy = %(energy)s "
        "pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if math.floor(tonumber(v.index) or -1) == p.squad then "
        "p.formation = v.uuid p.soldiers = math.floor(tonumber(v.totalSoldierNum) or 0) "
        "p.state = math.floor(tonumber(v.state) or 0) end end end) "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_arm squad="..tostring(p.squad)'
        '.." formation="..tostring(p.formation).." soldiers="..tostring(p.soldiers)'
        '.." energy="..tostring(p.energy).." cost="..tostring(p.cost)'
        '.." server="..tostring(p.server)'
        '.." home="..tostring(p.home and p.home.x)..","..tostring(p.home and p.home.y))'
        % {"cfg": GOLDEN_ZOMBIE_CFG, "gold": _GOLD,
           "cost": golden_attack_cost(), "energy": golden_energy()}
    )

def golden_armed() -> str:
    """Lua *expression* -> 1 all set, 0 no such squad, -1 the squad has no soldiers."""
    return ("(function() " + _GOLD_P +
            "if p.formation == nil then return 0 end "
            "if (tonumber(p.soldiers) or 0) <= 0 then return -1 end "
            "return 1 end)()")


def _golden_prefab_helpers() -> str:
    """Lua *statements* -> `_goldpic()` and `_goldids()`, on top of the prefab map.

    WHAT a golden zombie looks like on the map is asked of the config rather than spelled
    out here: `pic_name` of the golden row is the prefab the client builds the clone from,
    and every config row sharing that prefab is a golden zombie too — three of them, live.

    `world_monster_boss_invasion` is a DIFFERENT prefab and a level 5..75 boss, which is
    exactly what the first version of this — «the clone's name contains `invasion`» —
    would have marched a squad at.
    """
    return (
        "local function _goldpic() local v = nil pcall(function() "
        "v = LocalController.instance():getValue('lw_world_monster', "
        "%(cfg)d, 'pic_name', nil) end) return _norm(v) end "
        "local function _goldids() local e = _monmap()[_goldpic()] "
        "if e ~= nil and e.ids ~= nil and #e.ids > 0 then return e.ids end "
        "return {%(cfg)d} end "
        % {"cfg": GOLDEN_ZOMBIE_CFG}
    )


def golden_scan() -> str:
    """Read the map around the camera: add what is new, and REAP what the map says is gone.

    Two sources, merged and de-duplicated by uuid (and by tile for the ones that have no
    uuid yet). Nothing is opened, nothing is tapped and nothing already attacked this run
    comes back: a tile in `used` is skipped on the way in.

    **The queue used to only ever grow, and that is what changed (#1702).** One brisk lap
    of the map gives the whole registry; from the first march onwards the chain works off
    that registry AND off the map, because the zombies in it are being killed — by us and
    by everybody else — and a row that has died is a march thrown at a corpse. So every
    scan also reaps: a queued target the enumerator did not return is dropped **only**
    where the map was actually read (:data:`_GOLD_REAP`), which is the secret tasks'
    THE_LIST_RULE (#1272) with the camera's drawn window as the proof.

    The reaping is skipped entirely when the enumerator itself failed — an empty answer
    from a read that did not happen is "we did not look", not "they are all dead".

    Run it as often as the camera moves. `gone=` in its own log line is what feeds the
    refresh threshold (:func:`golden_needs_refresh`).
    """
    return (
        monster_prefab_lookup() + _golden_prefab_helpers() +
        _GOLD_P + _GOLD_REAP +
        "if p.targets == nil then p.targets = {} end "
        "if p.used == nil then p.used = {} end " +
        _GOLD_WS +
        "if ws == nil then "
        'CS.UnityEngine.Debug.LogError("ACT golden_scan skipped=not-in-world") return end '
        "local seen = {} "
        "for _, t in ipairs(p.targets) do seen[tostring(t.pid)] = true end "
        # WHAT THIS READ ACTUALLY SAW, as opposed to what the queue already held: `seen`
        # is the de-duplicator and cannot answer "is it still there", because everything
        # queued is in it before the read begins.
        "local present = {} "
        "local added = 0 "
        # -- 1. the invasion enumerator: uuid -> tile, everything the send needs
        "local read_ok = pcall(function() "
        "local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() "
        "for _, id in ipairs(_goldids()) do pcall(function() ids:Add(id, 1) end) end "
        "local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, "
        "CS.UnityEngine.Vector2Int)() "
        "ws:GetMonsterListInArea(ws.CurTilePos, p.radius, ids, res) "
        "local e = res:GetEnumerator() "
        "while e:MoveNext() do "
        "local uuid, tile = e.Current.Key, e.Current.Value "
        "local pid = nil pcall(function() pid = ws:TilePosToIndex(tile) end) "
        "if pid ~= nil then present[tostring(pid)] = true "
        "if not seen[tostring(pid)] and not p.used[tostring(uuid)] then "
        "seen[tostring(pid)] = true added = added + 1 "
        "p.targets[#p.targets + 1] = {pid = pid, uuid = uuid, key = tostring(uuid), "
        "x = math.floor(tile.x + 0.5), y = math.floor(tile.y + 0.5), "
        "src = 'area', at = os.time()} end end end end) "
        # -- 2. the drawn clones: a tile, and a handle that can fetch the uuid later
        "pcall(function() "
        "local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour)) "
        "for i = 0, arr.Length - 1 do local mb = arr[i] local cn = nil "
        "pcall(function() cn = mb:GetType().Name end) "
        "if cn == 'TouchObjectEventTrigger' then "
        "local go, root, guard = mb.gameObject, nil, 0 "
        "while go ~= nil and guard < 8 do local nm = nil pcall(function() nm = go.name end) "
        "if nm ~= nil and string.find(nm, 'WorldMonster') then root = go break end "
        "local nxt = nil pcall(function() if go.transform.parent ~= nil then "
        "nxt = go.transform.parent.gameObject end end) go = nxt guard = guard + 1 end "
        "if root ~= nil then local nm = tostring(root.name) "
        "if _norm(nm) == _goldpic() then "
        "local pid = nil pcall(function() "
        "pid = SceneUtils.WorldToTileIndex(root.transform.position) end) "
        "if pid ~= nil then present[tostring(pid)] = true "
        "if not seen[tostring(pid)] then "
        "local tp = nil pcall(function() tp = SceneUtils.IndexToTilePos(pid) end) "
        "seen[tostring(pid)] = true added = added + 1 "
        "p.targets[#p.targets + 1] = {pid = pid, uuid = 0, trig = mb, "
        "x = (tp and tp.x or -1), y = (tp and tp.y or -1), src = 'clone'} end end end "
        "end end end end) "
        # -- 3. …and only now, with a read that answered, take out what is gone
        "local gone = 0 "
        "if read_ok then "
        "local cam = ws.CurTilePos "
        "gone = _goldreap(p, ws, present, cam.x, cam.y) end "
        "p.found = #p.targets "
        "p.ids = _goldids() "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_scan added="..tostring(added)'
        '.." gone="..tostring(gone)'
        '.." since_refresh="..tostring(math.floor(tonumber(p.since_refresh) or 0))'
        '.." queued="..tostring(p.found))'
        % {"gold": _GOLD}
    )


def golden_refresh() -> str:
    """Walk a short ring of camera stops around the origin, reading the map at each one.

    The expensive half of keeping the registry honest, and it runs on a THRESHOLD rather
    than on a clock (:data:`GOLDEN_REFRESH_AFTER`): the camera already sits on the kills,
    so an ordinary scan after each one is a current picture almost all the time. It is
    when several targets in a row turn out to be gone that the ground is stale enough to
    be worth paying for.

    **Why stops and not one look.** The client answers about what it has LOADED, and it
    loads what the camera dwells on. A lap of the map moves every 0.05 s — far faster than
    the region loader — so the lap gives the far picture and leaves the near ground blank:
    live, `0` golden zombies within 300 tiles of the base, and the first pick 488 tiles
    away, on a map that had 17 of them within 300 and one at 14. A single wide look at the
    lap's own height changes nothing. Thirteen stops turned the 0 into 17.

    So this is the old ring sweep, cut down and re-aimed: :data:`GOLDEN_REFRESH_STOPS`
    stops on one ring of :data:`GOLDEN_REFRESH_RING` tiles plus the origin itself, walked
    on the game's own timer, the enumerator read and merged at every stop. Around the
    ORIGIN of the next pick — the base before the first march, the last kill after it —
    and never around the base for its own sake.

    It is also the run's opening move, once, which is what replaced eighteen stops before
    every first pick with seven.
    """
    return (
        _GOLD_P + _GOLD_WS + _GOLD_OWN_MARCH +
        "if ws == nil then "
        'CS.UnityEngine.Debug.LogError("ACT golden_refresh skipped=not-in-world") return end '
        "local o = _origin(p) "
        "if o == nil then o = {x = ws.CurTilePos.x, y = ws.CurTilePos.y} end "
        "if p.targets == nil then p.targets = {} end "
        "if p.used == nil then p.used = {} end "
        "p.since_refresh = 0 "
        "p.refreshes = (tonumber(p.refreshes) or 0) + 1 "
        "p.refresh_done = 0 "
        "%(gold)s = p "
        "local ids = p.ids or {%(cfg)d} "
        "local ring = math.floor(tonumber(p.ring_now) or %(ring)d) "
        "if ring < 1 then ring = %(ring)d end "
        # -- one stop: move the camera, then read the enumerator around that point
        "local function stop(x, y) "
        "local g = %(gold)s "
        "pcall(function() local pid = ws:TilePosToIndex(CS.UnityEngine.Vector2Int(x, y)) "
        "GoToUtil.MoveToWorldPoint(pid) end) "
        "pcall(function() "
        "local w = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() "
        "for _, id in ipairs(ids) do pcall(function() w:Add(id, 1) end) end "
        "local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, "
        "CS.UnityEngine.Vector2Int)() "
        "ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(x, y), ring, w, res) "
        "local seen = {} "
        "for _, t in ipairs(g.targets) do seen[tostring(t.pid)] = true end "
        "local e = res:GetEnumerator() "
        "while e:MoveNext() do local uuid, tile = e.Current.Key, e.Current.Value "
        "local pid = nil pcall(function() pid = ws:TilePosToIndex(tile) end) "
        "if pid ~= nil and not seen[tostring(pid)] and not g.used[tostring(pid)] then "
        "seen[tostring(pid)] = true "
        "g.targets[#g.targets + 1] = {pid = pid, uuid = uuid, key = tostring(uuid), "
        "x = math.floor(tile.x + 0.5), y = math.floor(tile.y + 0.5), "
        "src = 'refresh'} end end end) "
        "g.found = #g.targets "
        "%(gold)s = g end "
        # -- the ring itself, scheduled on the game's own timer
        "local tm = TimerManager:GetInstance() "
        "local n = 0 "
        "for k = 0, %(stops)d - 1 do "
        "local a = (2 * math.pi * k) / %(stops)d "
        "local x = math.floor(o.x + ring * math.cos(a) + 0.5) "
        "local y = math.floor(o.y + ring * math.sin(a) + 0.5) "
        "if x >= 0 and y >= 0 then n = n + 1 "
        "tm:DelayInvoke(function() stop(x, y) end, n * %(gap)f) end end "
        # …and the origin last, so the camera ends where the pick is measured from
        "tm:DelayInvoke(function() stop(o.x, o.y) "
        "local g = %(gold)s g.refresh_done = 1 g.looked = {x = o.x, y = o.y} "
        "%(gold)s = g end, (n + 1) * %(gap)f) "
        'CS.UnityEngine.Debug.LogError("ACT golden_refresh at="..tostring(o.x)..","..tostring(o.y)'
        '.." stops="..tostring(n + 1).." n="..tostring(p.refreshes))'
        % {"gold": _GOLD, "cfg": GOLDEN_ZOMBIE_CFG,
           "stops": GOLDEN_REFRESH_STOPS, "ring": GOLDEN_REFRESH_RING,
           "gap": GOLDEN_REFRESH_GAP}
    )


#: How far a FIRST pick may be before the ring is widened rather than marched (#1702).
#: The opening ring covers about twice :data:`GOLDEN_REFRESH_RING` — its own radius plus
#: what the enumerator reads at each stop — so a pick beyond that is «the near ground was
#: never loaded» as often as «there is nothing near». Live, over 76 opening picks the
#: median was 47 tiles and the tail reached 569; at the attack speed the game quotes,
#: 569 tiles is over ten minutes of marching and another ring is nine seconds.
GOLDEN_FIRST_FAR = 160

#: …and how wide the ring may grow before the answer is believed. Four doublings from 80
#: is most of a warzone, and a run that has walked that much and still has nothing near it
#: is a run whose invasion really is somewhere else.
GOLDEN_RING_MAX = 640


def golden_widen_ring() -> str:
    """Double the refresh ring for the rest of this run, up to :data:`GOLDEN_RING_MAX`.

    Not a preference and not a setting: a within-run answer to a first pick that came out
    farther than the ring could see. The next :func:`golden_refresh` walks the wider ring
    and reads the enumerator at the same width, so the stops themselves cost what they
    always cost — the ring is bigger, not slower.
    """
    return (
        _GOLD_P +
        "local now = math.floor(tonumber(p.ring_now) or " + str(GOLDEN_REFRESH_RING) + ") "
        "local want = now * 2 "
        "if want > " + str(GOLDEN_RING_MAX) + " then want = " + str(GOLDEN_RING_MAX) + " end "
        "p.ring_now = want "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_widen ring="..tostring(want))'
        % {"gold": _GOLD}
    )


def golden_best_dist() -> str:
    """Lua *expression* -> how far the nearest QUEUED target is from the pick's origin.

    `-1` when the queue is empty. The origin is the same one the pick uses — the anchor
    if the chain has sent anything, the base before that — so this is «how long the next
    march would be», asked before it is ordered and without choosing anything.
    """
    return (
        "(function() " + _GOLD_P + _GOLD_OWN_MARCH +
        "local ox, oy = nil, nil "
        "local o = _origin(p) "
        "if o ~= nil then ox, oy = o.x, o.y end "
        "local best = nil "
        "for _, t in ipairs(p.targets or {}) do "
        "if not (p.used or {})[tostring(t.pid)] and _goldfree(p, t.pid) then "
        "local d = nil "
        "if ox ~= nil then local dx, dy = (t.x - ox), (t.y - oy) "
        "d = math.sqrt(dx * dx + dy * dy) "
        "else pcall(function() "
        "d = tonumber(SceneUtils.TileDistanceToMyHome(t.pid, p.server)) end) end "
        "if d ~= nil and (best == nil or d < best) then best = d end end end "
        "if best == nil then return -1 end "
        "return math.floor(best + 0.5) end)()"
    )


def golden_refresh_done() -> str:
    """Lua *expression* -> 1 once the refresh ring has finished walking."""
    return ("(function() " + _GOLD_P +
            "return (math.floor(tonumber(p.refresh_done) or 0) == 1) and 1 or 0 end)()")


def golden_refresh_seconds() -> float:
    """How long the refresh ring takes, for the caller that has to wait it out."""
    return (GOLDEN_REFRESH_STOPS + 2) * GOLDEN_REFRESH_GAP


def golden_needs_refresh() -> str:
    """Lua *expression* -> 1 when enough targets have been proven gone to redraw the ground.

    The threshold is the run's own `refresh_after` when it set one, and
    :data:`GOLDEN_REFRESH_AFTER` otherwise. Zero or less switches the refresh off
    entirely, which is what a run that wants nothing but the opening lap passes.
    """
    return ("(function() " + _GOLD_P +
            "local n = math.floor(tonumber(p.since_refresh) or 0) "
            "local lim = math.floor(tonumber(%(gold)s_refresh_after) or %(def)d) "
            "if lim <= 0 then return 0 end "
            "return (n >= lim) and 1 or 0 end)()"
            % {"gold": _GOLD, "def": GOLDEN_REFRESH_AFTER})


def golden_vanished() -> str:
    """Lua *expression* -> how many queued targets the map has proven gone this run."""
    return ("(function() " + _GOLD_P +
            "return math.floor(tonumber(p.vanished) or 0) end)()")


def golden_queued() -> str:
    """Lua *expression* -> how many golden zombies are queued and not yet attacked."""
    return ("(function() " + _GOLD_P +
            "local n = 0 for _, t in ipairs(p.targets or {}) do "
            "if not (p.used or {})[tostring(t.pid)] then n = n + 1 end end return n end)()")


def golden_found() -> str:
    """Lua *expression* -> how many golden zombies the registry holds right now.

    It used to mean «how many this run has seen at all», because the queue only ever grew
    and the two were the same number. They are not any more (#1702): a scan reaps what the
    map has disowned, so this rises with what is found and falls with what has died.
    :func:`golden_vanished` is the other half — how many the map has taken out.
    """
    return "(function() " + _GOLD_P + "return math.floor(tonumber(p.found) or 0) end)()"


def golden_pick() -> str:
    """Choose the nearest golden zombie to WHERE THE SQUAD IS, and park it as the target.

    The anchor is the last tile a squad was sent to this run; before the first send there
    is none, and the game's own `SceneUtils.TileDistanceToMyHome(pid, serverId)` answers
    from the base instead — which is where the squad is standing. Live it reads 0 at the
    base tile and 492 at a tile 492 tiles away, with or without the server id.

    Distance after that is a plain tile distance from the anchor. It has to be: the
    home-distance call knows only one origin, and the entire point of the ability is that
    the second target is measured from the first and not from the house.

    **THE ORIGIN IS A TILE, AND THE FIRST ONE IS THE BASE'S** (#1702). `golden_arm` works
    the base tile out of the oracle (:data:`_GOLD_HOME`), so the first pick and every one
    after it are the same arithmetic on the same kind of number — a plain tile distance
    from a tile. Asking the oracle per target is kept as the fallback for a client that
    would not give the base up, and a target the oracle cannot price either is passed over
    rather than picked: `1e9` used to be the answer for ALL of them at once, and a queue
    of equals is picked in whatever order the enumerator happened to fill it.

    **A first pick 500 tiles away is not always a bug** — the invasion clusters in its own
    region of the map, so a base far from it pays that walk once. What IS a bug, and is
    what #1702 fixed, is a far pick made while near ones exist: `GetMonsterListInArea`
    answers out of what the CLIENT has loaded, and a lap of `scan_map` leaves the camera
    at the far end of the server with the tiles around the base long since evicted. So the
    recipe puts the camera back on the origin and re-scans before every pick.
    """
    return (
        _GOLD_P + _GOLD_OWN_MARCH +
        "p.cur = nil "
        "local ox, oy, from = nil, nil, 'oracle' "
        "local o0, o0name = _origin(p) "
        "if o0 ~= nil then ox, oy, from = o0.x, o0.y, o0name end "
        # THE SQUAD WORKS A CROWD, NOT A MAP (#2390). The invasion moves, and with the
        # zombies near the base dead the nearest one left is 24 tiles away with nobody
        # beside it — measured live, `queued: 1` with 215 energy in the purse. A chain
        # is only worth anything where the next zombie is a few tiles from the last, so
        # the queue is cut into squares of `cluster` tiles, the fullest one is chosen,
        # and every pick after that is made INSIDE it until it is empty. The march to
        # the first of them is the ride over, and it is paid once instead of per kill.
        # `cluster = 0` turns it off and the pick is the plain nearest again.
        "local step = math.floor(tonumber(p.cluster) or 0) "
        "local function _incell(c, t) "
        "return c ~= nil and t.x >= c.x0 and t.x < (c.x0 + c.step) "
        "and t.y >= c.y0 and t.y < (c.y0 + c.step) end "
        "local function _cellsleft(p, c) "
        "local n = 0 "
        "for _, t in ipairs(p.targets or {}) do "
        "if not (p.used or {})[tostring(t.pid)] and _goldfree(p, t.pid) "
        "and _incell(c, t) then n = n + 1 end end return n end "
        "if step > 0 then "
        "if p.crowd ~= nil and _cellsleft(p, p.crowd) < 1 then p.crowd = nil end "
        "if p.crowd == nil then "
        "local cells = {} "
        "for _, t in ipairs(p.targets or {}) do "
        "if not (p.used or {})[tostring(t.pid)] and _goldfree(p, t.pid) then "
        "local kx = math.floor(t.x / step) * step "
        "local ky = math.floor(t.y / step) * step "
        "local key = tostring(kx) .. ':' .. tostring(ky) "
        "local cell = cells[key] "
        "if cell == nil then cell = {x0 = kx, y0 = ky, step = step, n = 0} "
        "cells[key] = cell end "
        "cell.n = cell.n + 1 end end "
        "local pickc, pickn, pickd = nil, 0, nil "
        "for _, cell in pairs(cells) do "
        "local cx, cy = cell.x0 + step / 2, cell.y0 + step / 2 "
        "local d = nil "
        "if ox ~= nil then local dx, dy = (cx - ox), (cy - oy) "
        "d = math.sqrt(dx * dx + dy * dy) end "
        "if cell.n > pickn or (cell.n == pickn and d ~= nil and pickd ~= nil "
        "and d < pickd) then pickc, pickn, pickd = cell, cell.n, d end end "
        "if pickc ~= nil then p.crowd = pickc p.crowd.n = pickn "
        "p.crowd.dist = pickd and math.floor(pickd + 0.5) or -1 end end end "
        "local best, bestd = nil, nil "
        "for _, t in ipairs(p.targets or {}) do "
        "if not (p.used or {})[tostring(t.pid)] and _goldfree(p, t.pid) "
        "and (step <= 0 or p.crowd == nil or _incell(p.crowd, t)) then "
        "local d = nil "
        "if ox ~= nil then local dx, dy = (t.x - ox), (t.y - oy) "
        "d = math.sqrt(dx * dx + dy * dy) "
        "else pcall(function() d = tonumber("
        "SceneUtils.TileDistanceToMyHome(t.pid, p.server)) end) end "
        # …AND NOT ONE THE SQUAD WOULD WALK ALL MORNING TO (#1702). With the zombies
        # near the base killed, the queue is whatever the sweep saw at the far end of
        # the warzone: measured live, picks 580 to 615 tiles out, which is a march of
        # minutes for one kill and reads as a hung chain. `reach` is that limit in
        # tiles; 0 keeps the old behaviour of walking anywhere.
        "local reach = math.floor(tonumber(p.reach) or 0) "
        "if step > 0 and p.crowd ~= nil and _incell(p.crowd, t) then reach = 0 end "
        "if d ~= nil and reach > 0 and d > reach then d = nil end "
        "if d ~= nil and (bestd == nil or d < bestd) then best, bestd = t, d end end end "
        "if best ~= nil then p.cur = best p.curdist = math.floor(bestd + 0.5) "
        "p.curfrom = from end "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_pick pid="..tostring(p.cur and p.cur.pid)'
        '.." uuid="..tostring(p.cur and p.cur.uuid).." dist="..tostring(p.curdist)'
        '.." from="..tostring(from).." at="..tostring(ox)..","..tostring(oy))'
        % {"gold": _GOLD}
    )


def golden_look_from() -> str:
    """Put the camera where the next pick is measured FROM — the last kill, or the base.

    Nothing is pressed and nothing is sent: the camera is the only thing that makes the
    client ask the server for a district's tiles, and `GetMonsterListInArea` can only
    answer out of what the client holds. That is the whole of #1702: after a lap of
    `scan_map` the camera stands at the far end of the server, the tiles around the base
    have been evicted, and «the nearest golden zombie» is chosen from a list that has no
    near ones in it at all — a five-minute march with a dozen zombies sitting beside the
    house.

    So it runs before every scan of the chain: the base for the first pick, the tile of
    the last kill for the rest — the same origin `golden_pick` measures from.

    **It moves the camera only when the origin has actually MOVED** (#1702, the lag
    measurement). A kill two tiles from the last one is inside the district the client
    already holds, and a camera flight it does not need costs the flight AND the settle
    the caller waits afterwards — measured, 3.5 s of a 13-second gap between two kills two
    tiles apart. So the tile last looked at is remembered and anything within
    :data:`GOLDEN_LOOK_AGAIN` tiles of it is left alone; `p.looked_moved` says which
    happened, and the recipe only pays the settle when it was a real move.
    """
    return (
        _GOLD_P + _GOLD_WS + _GOLD_OWN_MARCH +
        "p.looked_moved = 0 "
        "local at = _origin(p) "
        "if at == nil then %(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_look_from skipped=no-origin") return end '
        "local seen = p.looked "
        "if seen ~= nil then local dx, dy = (at.x - seen.x), (at.y - seen.y) "
        "if math.sqrt(dx * dx + dy * dy) <= %(near)d then %(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_look_from skipped=near at="'
        '..tostring(at.x)..","..tostring(at.y)) return end end '
        "local pid = at.pid "
        "if pid == nil and ws ~= nil then pcall(function() "
        "pid = ws:TilePosToIndex(CS.UnityEngine.Vector2Int(at.x, at.y)) end) end "
        "if pid == nil then %(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_look_from skipped=no-tile") return end '
        "local ok, err = pcall(function() GoToUtil.MoveToWorldPoint(pid) end) "
        "if ok then p.looked = {x = at.x, y = at.y} p.looked_moved = 1 end "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_look_from ok="..tostring(ok)'
        '.." err="..tostring(err).." at="..tostring(at.x)..","..tostring(at.y)'
        '.." origin="..tostring(p.anchor ~= nil and "anchor" or "home"))'
        % {"gold": _GOLD, "near": GOLDEN_LOOK_AGAIN}
    )


def golden_looked_moved() -> str:
    """Lua *expression* -> 1 when the last look really moved the camera, else 0.

    What the recipe waits on: streaming a district in takes a moment, and NOT streaming
    one takes none.
    """
    return ("(function() " + _GOLD_P +
            "return (math.floor(tonumber(p.looked_moved) or 0) == 1) and 1 or 0 end)()")


def golden_pick_where() -> str:
    """Lua *expression* -> the chosen zombie's tile in the panel's own coordinate token.

    `#<server> X:<x> Y:<y>` — the one spelling of a world coordinate in this repository
    (`tools/lib/coords.py`), which the log view turns into something a person can click
    to fly there (#1702, and the operator asked for exactly that). Empty string when
    nothing is chosen, so a caller can tell «none» from a tile at 0,0.
    """
    return ("(function() " + _GOLD_P +
            "local c = p.cur if c == nil then return '' end "
            "local srv = math.floor(tonumber(c.server or p.server) or 0) "
            "local core = 'X:' .. tostring(math.floor(tonumber(c.x) or 0)) "
            ".. ' Y:' .. tostring(math.floor(tonumber(c.y) or 0)) "
            "if srv > 0 then return '#' .. tostring(srv) .. ' ' .. core end "
            "return core end)()")


def golden_pick_report() -> str:
    """Lua *expression* -> one line about the armed target, for the log (#1702).

    What a person watching a chain needs to see, and could not until now: WHERE the
    target is, how far it is FROM THE ORIGIN the pick used, which origin that was — the
    base for the first kill, the last kill afterwards — and, as the check on both, how far
    the same tile is from the base. On the first lap the two distances agree; on every lap
    after it the home one grows while the near one stays small, which is the chain doing
    exactly what it is for.
    """
    return (
        "(function() " + _GOLD_P + _GOLD_OWN_MARCH +
        "local c = p.cur if c == nil then return 'none' end "
        "local o = _origin(p) "
        "local hd = nil "
        "pcall(function() hd = tonumber(SceneUtils.TileDistanceToMyHome(c.pid, p.server)) end) "
        "return 'at=' .. tostring(c.x) .. ',' .. tostring(c.y) .. "
        "' dist=' .. tostring(math.floor(tonumber(p.curdist) or 0)) .. "
        "' from=' .. tostring(p.curfrom or '-') .. "
        "' origin=' .. tostring(o and o.x) .. ',' .. tostring(o and o.y) .. "
        "' home_dist=' .. tostring(hd and math.floor(hd + 0.5)) .. "
        # WHY THE ORIGIN IS WHERE IT IS (#1702) — one word, every lap.
        "' stand=' .. _stand(p) .. "
        "' src=' .. tostring(c.src or '-') .. "
        "' crowd=' .. (p.crowd and (tostring(p.crowd.x0) .. ',' .. tostring(p.crowd.y0) "
        ".. '+' .. tostring(p.crowd.step) .. 'x' .. tostring(p.crowd.n) "
        ".. '@' .. tostring(p.crowd.dist)) or '-') .. "
        "' queued=' .. tostring(#(p.targets or {})) .. "
        "' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) end)()"
    )


def golden_picked() -> str:
    """Lua *expression* -> 1 a target is armed, 0 the queue is empty."""
    return "(function() " + _GOLD_P + "return (p.cur ~= nil) and 1 or 0 end)()"


def golden_needs_uuid() -> str:
    """Lua *expression* -> 1 when the armed target still has to be asked about.

    A target found by the invasion enumerator arrives with its uuid; one found as a drawn
    clone does not, because the uuid is the SERVER's answer and the client never stores
    it. `uuid = 0` is refused by the send, so that one has to be touched first.
    """
    return ("(function() " + _GOLD_P +
            "if p.cur == nil then return 0 end "
            "return ((tonumber(p.cur.uuid) or 0) == 0) and 1 or 0 end)()")


def golden_touch() -> str:
    """Open the armed target's own point popup, so the server hands over its uuid.

    `TouchObjectEventTrigger:OnClick()` is the genuine tap-resolution path with no tap —
    it fetches the point detail and opens `UIWorldPoint` for that exact monster
    (docs/research/world-monsters.md, Finding 17). A no-op when the uuid is already
    known, which is the ordinary case.
    """
    return (
        _GOLD_P +
        "if p.cur == nil or (tonumber(p.cur.uuid) or 0) ~= 0 then "
        'CS.UnityEngine.Debug.LogError("ACT golden_touch skipped=have-uuid") return end '
        "if p.cur.trig == nil then "
        'CS.UnityEngine.Debug.LogError("ACT golden_touch skipped=no-handle") return end '
        "local ok, err = pcall(function() p.cur.trig:OnClick() end) "
        'CS.UnityEngine.Debug.LogError("ACT golden_touch ok="..tostring(ok).." err="..tostring(err))'
    )


def golden_grab() -> str:
    """Take the uuid off the open popup and close it again — the popup ONLY.

    `Ctrl:CloseSelf()`, never `UIManager:DestroyAllWindow()`: the latter destroys the
    persistent HUD and nothing brings it back (Finding 16). A popup that turns out to be
    something other than a golden zombie is dropped from the queue rather than attacked.
    """
    return (
        _GOLD_P +
        "if p.cur == nil or (tonumber(p.cur.uuid) or 0) ~= 0 then return end "
        "local w = nil pcall(function() w = UIManager.Instance:GetStackTopWindow() end) "
        "local c = nil pcall(function() if w ~= nil and tostring(w.Name) == 'UIWorldPoint' "
        "then c = w.Ctrl end end) "
        "if c == nil then "
        "p.used[tostring(p.cur.pid)] = true p.cur = nil %(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_grab miss=no-popup") return end '
        "local uuid, pid, srv = nil, nil, nil "
        "pcall(function() uuid = c.uuid pid = c.pointId srv = c.serverId end) "
        "local lvl = nil "
        "pcall(function() local md = c:GetMonsterData(c.uuid) if md ~= nil then "
        "lvl = tonumber(md.level) end end) "
        "pcall(function() c:CloseSelf() end) "
        "if uuid == nil or (tonumber(uuid) or 0) == 0 then "
        "p.used[tostring(p.cur.pid)] = true p.cur = nil %(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_grab miss=no-uuid") return end '
        "p.cur.uuid = uuid "
        "if pid ~= nil then p.cur.pid = pid end "
        "if srv ~= nil then p.cur.server = math.floor(tonumber(srv) or 0) end "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_grab uuid="..tostring(uuid)'
        '.." pid="..tostring(p.cur.pid).." level="..tostring(lvl))'
        % {"gold": _GOLD}
    )


#: RE-READ THE TARGET'S uuid FROM THE GAME, right before it is used (#1702). A monster's
#: uuid is a C# `Int64` handed over by the enumerator, and the queue keeps a REFERENCE to
#: it: minutes later `tostring()` on one answers «<invalid c# object>» — measured live,
#: with the second target of a chain. Sending that is sending nothing, which is exactly
#: what «the send never became a march» was, and why the first target of a run always
#: worked and the next one never did. It cannot be kept as a Lua number either — nineteen
#: digits is past what one holds exactly — so the queue keeps the TEXT of it and the live
#: object is fetched again, from a two-tile enumerator call, at the moment of the send.
_GOLD_FRESH_UUID = (
    "local function _freshuuid(ws, p, t) "
    "if ws == nil or t == nil then return nil end "
    "local want = tostring(t.key or t.uuid or 0) "
    "local found = nil "
    "pcall(function() "
    "local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() "
    "for _, id in ipairs(p.ids or {" + str(1030000) + "}) do pcall(function() ids:Add(id, 1) end) end "
    "local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, "
    "CS.UnityEngine.Vector2Int)() "
    "ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 2, ids, res) "
    "local e = res:GetEnumerator() "
    "while e:MoveNext() do local k = e.Current.Key "
    "if tostring(k) == want then found = k end end end) "
    "return found end "
)


def golden_send() -> str:
    """Send the chosen squad at the armed golden zombie — one call, no window.

    `back = 0` on the ordinary lap of the chain, so the squad STAYS on the tile it just
    cleared and the next pick is measured from there. The caller raises it to 1 for the
    last march of the run, which is what brings the squad home.

    **AND `0` IS TRUE IN LUA, WHICH IS WHY THE SQUAD WALKED HOME ANYWAY (#2390).**
    `autoBackHome` is a C# bool, and xLua converts a Lua value to one with
    `lua_toboolean` — where every number, `0` included, is true. So the whole chain sent
    `back = 0` meaning «stay» and the game heard «come home», and every kill cost the
    flight out AND the flight back. Measured live on a 79-tile target: 84 s out, 91 s
    home, 13 s of our own reading and pressing — a 188-second lap of which 175 s was
    travel and half of that travel was bought by this one conversion. The flag is a
    genuine Lua boolean now (`home = (back ~= 0)`), with the old numeric form kept as a
    fallback in case a build wants the number after all.

    **THERE ARE TWO DOORS, and which one is right is decided by where the squad is
    (#1702).** `SendCreateMarchMessage` creates a march FROM THE BASE and the server
    refuses it, in silence and without touching the purse, at an army that has already
    landed. The squad standing on the tile it just cleared needs the call the dispatch
    screen uses instead::

        MarchUtil.SendChangeMarchToServer(marchUuid, targetType, targetPoint,
                                          targetUuid, backHome, targetServerId,
                                          destroyTimeIndex)

    Seven arguments — `debug.getinfo` says `nparams=7` — and its constants name the
    message it sends, `world.march.change`, with every field of the payload. It builds
    the march info, the world id and the card list itself. Live on 2026-08-22 at a squad
    reading `status=STATION: 0 end=0`: purse 1871 -> 1861 and the march turned MOVING
    onto the new tile, with no step homewards. That is the whole point of the chain: the
    next hop is the distance between two zombies, not twice the distance to the base.

    Scheduled through `TimerManager:GetInstance():DelayInvoke` either way, like every
    other launch in this file: a cold send from the hijack thread returns `true` and is
    dropped by the server (docs/research/world-monsters.md, Finding 17).
    """
    return (
        _GOLD_P + _GOLD_WS + _GOLD_FRESH_UUID + _GOLD_OWN_MARCH +
        "if p.cur == nil or p.formation == nil then error('nothing armed for this run') end "
        "local t = p.cur "
        "local srv = math.floor(tonumber(t.server or p.server) or 0) "
        "local kind = MarchTargetType.ATTACK_MONSTER "
        "if p.server ~= nil and srv ~= 0 and srv ~= p.server then "
        "kind = MarchTargetType.CROSS_ATTACK_MONSTER end "
        "local back = math.floor(tonumber(%(gold)s_back) or p.back or 0) "
        "local home = (back ~= 0) "
        "local f, pid = p.formation, t.pid "
        # THE uuid IS FETCHED AGAIN HERE (#1702) — see :data:`_GOLD_FRESH_UUID`. The
        # one in the queue is a reference that may have died since the scan.
        "local uuid = _freshuuid(ws, p, t) "
        # NO LIVE uuid MEANS NO ZOMBIE (#1702). The game has just been asked about the
        # very tile, so an answer of «nothing there» is the map having moved on — and a
        # send at a dead reference is a wasted order and ten seconds of waiting for a
        # march that cannot come. The target is written off as gone instead.
        "if uuid == nil then p.used[tostring(t.pid)] = true "
        "p.dropped = (tonumber(p.dropped) or 0) + 1 p.cur = nil "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_send dropped=stale pid="..tostring(t.pid)) '
        "return end "
        # WHICH DOOR (#1702). A march of ours that has ARRIVED is re-targeted where it
        # stands; anything else is a fresh march out of the base.
        "local own = _ownmarch(p) "
        "local mu = _reaim(own, p) "
        "if mu ~= nil then "
        "TimerManager:GetInstance():DelayInvoke(function() "
        "local ok, err = pcall(function() "
        "MarchUtil.SendChangeMarchToServer(mu, kind, pid, uuid, home, srv, 0) end) "
        "if not ok then pcall(function() "
        "MarchUtil.SendChangeMarchToServer(mu, kind, pid, uuid, back, srv, 0) end) end "
        'CS.UnityEngine.Debug.LogError("ACT golden_send redeploy ok="..tostring(ok)'
        '.." err="..tostring(err)) '
        "end, 0.5) "
        "else "
        "TimerManager:GetInstance():DelayInvoke(function() "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(f, kind, pid, uuid, 1, home, false, srv, nil) end) "
        "if not ok then pcall(function() "
        "MarchUtil.SendCreateMarchMessage(f, kind, pid, uuid, 1, back, false, srv, nil) end) end "
        'CS.UnityEngine.Debug.LogError("ACT golden_send ok="..tostring(ok).." err="..tostring(err)) '
        "end, 0.5) end "
        "p.redeploy = (mu ~= nil) and 1 or 0 "
        "if mu ~= nil then p.own_march = tostring(mu) "
        "p.redeploys = (tonumber(p.redeploys) or 0) + 1 "
        "else p.fallbacks = (tonumber(p.fallbacks) or 0) + 1 end "
        "p.used[tostring(t.pid)] = true "
        "_goldclaim(p, t.pid) "
        "p.anchor = {x = t.x, y = t.y, pid = t.pid} "
        "p.last_sent = {x = t.x, y = t.y, pid = t.pid} "
        "p.pending = {pid = pid, uuid = uuid, key = tostring(uuid), x = t.x, y = t.y} "
        # WHAT THE LAST ORDER HIT, SET ASIDE BEFORE IT IS OVERWRITTEN (#2390). The chain
        # sends before it judges now — the re-aim window is seconds wide — so the zombie
        # of the order that has just finished has to survive this line to be looked at.
        # A QUEUE rather than a slot, because a lap whose flight is too short to look
        # in must not lose the kill: measured live, judging and choosing together cost
        # 14-40 s against hops of 20-30 s, and the reading that says so is
        # `eta_left = -29` — the march had landed half a minute before the chain came
        # back to wait for it. What is not looked at this lap is looked at the next.
        "if p.hit ~= nil then p.judgeq = p.judgeq or {} "
        "table.insert(p.judgeq, p.hit) end "
        "p.judge = p.hit "
        "p.hit = p.pending "
        "_goldclaim(p, t.pid) "
        # THE MARCHES THAT EXIST BEFORE THE SEND (#1702). The proof that a send reached
        # the server is a march of ours that was not there a moment ago, so the «before»
        # set is taken here — and the one that appears against it is this attack, which
        # is also the march whose clock the wait should be on.
        "p.march_before = {} "
        "pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() "
        "if ms == nil then return end "
        "for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) "
        "if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) "
        "if u ~= nil then p.march_before[u] = true end end end end) "
        "p.before = %(energy)s "
        "p.cur = nil "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_send scheduled pid="..tostring(pid)'
        '.." uuid="..tostring(uuid).." back="..tostring(back)'
        '.." redeploy="..tostring(p.redeploy).." attack="..tostring(p.attacks))'
        % {"gold": _GOLD, "energy": golden_energy()}
    )


def golden_flight_left() -> str:
    """Lua *expression* -> seconds until THIS run's own march lands, ``-1`` when unknown.

    How much room the lap has before the window opens (#2390). The chain's own work after
    an order — judging the last kill, choosing the next zombie — costs 14 s on a quiet
    panel and upwards of 40 s on a busy one, while a hop of five tiles is over in twenty:
    measured live, the chain came back to wait for a march that had landed 29 seconds
    earlier (`eta_left = -29`), and by then there was nothing left to re-aim. So the lap
    asks how long it has and only looks at the last kill when the looking fits.

    The server's own arrival stamp for the order this run sent (`p.eta_ms`), and never a
    clock of ours.
    """
    return ("(function() " + _GOLD_P +
            "local due = tonumber(p.eta_ms) "
            "if due == nil or due <= 0 then return -1 end "
            "local now = nil "
            "pcall(function() now = tonumber(UITimeManager.Instance:GetServerTime()) end) "
            "if now == nil then now = os.time() * 1000 end "
            "return math.floor((due - now) / 1000) end)()")


def golden_reaim_now() -> str:
    """Lua *expression* -> 1 when the squad was RE-AIMED where it stands, else 0.

    CHECK AND ORDER IN ONE BREATH, and here that is not tidiness — it is the whole
    ability (#2390). The window in which a march can be re-aimed is a few seconds wide:
    measured off the operator's own hand-driven chain on the wire, the next
    `world.march.change` left between 0.08 s and 3.4 s after the previous leg landed. The
    chain used to spend that window on questions — «is the march re-aimable», «is the
    squad free», «is this the last march» — each one a round trip to the game VM at
    0.2 s plus the player's own logging, and measured live it was **ten seconds** from
    the landing to the order, by which time the march had gone and the send made a new
    one out of the base (`redeploys=0 fallbacks=5` over five laps).

    So this asks and orders inside a single call, and answers what happened:

    * ``1``  — the run's own march was re-aimed at the chosen zombie where it stood;
    * ``0``  — there is nothing to re-aim (no march of ours, or it carries somebody's
      banner). The caller then sends the ordinary way, out of the base, and the report
      counts it as a `fallback`;
    * ``-3`` — nothing is chosen, so there was nothing to send at;
    * ``-4`` — the client can no longer name that zombie: it is gone, and the target is
      written off rather than marched at.

    Everything the ordinary send parks for the lap that follows is parked here too — the
    anchor, the pending target, the zombie set aside for judging, the marches that
    existed before the order — so `golden_launched`, `golden_confirm` and
    `golden_judge_the_kill` read exactly what they always read.
    """
    return (
        "(function() " + _GOLD_P + _GOLD_WS + _GOLD_FRESH_UUID + _GOLD_OWN_MARCH +
        "if p.cur == nil or p.formation == nil then return -3 end "
        "local t = p.cur "
        "local srv = math.floor(tonumber(t.server or p.server) or 0) "
        "local kind = MarchTargetType.ATTACK_MONSTER "
        "if p.server ~= nil and srv ~= 0 and srv ~= p.server then "
        "kind = MarchTargetType.CROSS_ATTACK_MONSTER end "
        # THE uuid IS THE ONE THE SEND KEPT, AND IT IS NOT ASKED FOR AGAIN (#2390).
        # Reading the march back after the fight is what kept failing: 16 readings
        # out of 22 answered `stand=nomarch`, because the client drops the march
        # object the moment the fight resolves. The operator plays it the other way
        # round — «маршрут могу поменять в моменте», the march being a live thing for
        # the whole flight — and the wire agrees: one of the five re-aims in the
        # capture left 0.45 s BEFORE its leg was due to land. So the order goes out
        # at the uuid this run has been holding since it sent it, with no question
        # asked in between; whether the server took it is settled afterwards by the
        # ordinary proof (`golden_launched`), and a re-aim that did not land is
        # answered by the ordinary march out of the base.
        # …AND THE MARCH HAS TO BE THERE (#2390). The uuid was taken on trust for as
        # long as the run held one, which is right for the beat after a landing and
        # wrong for ever: once the squad is home the client holds no march at all,
        # and an order at a uuid nobody has is answered by nothing. So the game is
        # asked whether the march EXISTS — `_reaim` answers with the uuid only for a
        # banner-free march of ours — and when it does not, the remembered uuid is
        # dropped and the caller sends the ordinary way, out of the base, which the
        # report counts as a `fallback`.
        "local own = _ownmarch(p) "
        "local mu = _reaim(own, p) "
        "if mu == nil then "
        "if p.own_march ~= nil then p.own_march = nil "
        "p.reaim_drops = (tonumber(p.reaim_drops) or 0) + 1 end "
        "p.reaim_miss = 0 p.redeploy = 0 "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_reaim none — no march of ours; '
        'sending out of the base instead, drops="..tostring(p.reaim_drops)) '
        "return 0 end "
        "local uuid = _freshuuid(ws, p, t) "
        "if uuid == nil then p.used[tostring(t.pid)] = true "
        "p.dropped = (tonumber(p.dropped) or 0) + 1 p.cur = nil "
        "%(gold)s = p return -4 end "
        # THE LAST MARCH STILL COMES HOME (#2390). The ordinary send asks the recipe for
        # that; here the question is answered inside the same call, because a second
        # round trip is the very thing this function exists to remove.
        "local home = false "
        "local left = %(energy)s "
        "local cost = math.floor(tonumber(p.cost) or %(fallback)d) "
        "if cost <= 0 then cost = %(fallback)d end "
        "if left < cost * 2 then home = true end "
        "local lim = math.floor(tonumber(p.limit) or 0) "
        "if lim > 0 and (tonumber(p.attacks) or 0) + 1 >= lim then home = true end "
        "local pid = t.pid "
        "TimerManager:GetInstance():DelayInvoke(function() "
        "local ok, err = pcall(function() "
        "MarchUtil.SendChangeMarchToServer(mu, kind, pid, uuid, home, srv, 0) end) "
        'CS.UnityEngine.Debug.LogError("ACT golden_reaim ok="..tostring(ok)'
        '.." err="..tostring(err).." pid="..tostring(pid)) '
        # A TENTH, NOT A HALF (#2390). Every send in this file hops to the main
        # thread, and the ordinary attack does it at 0.1 s. The re-aim was
        # sitting at 0.5, which is four tenths given away inside a window
        # measured at 0.08-3.4 s wide.
        "end, 0.1) "
        "p.own_march = tostring(mu) "
        "p.redeploy = 1 "
        "p.redeploys = (tonumber(p.redeploys) or 0) + 1 "
        "p.used[tostring(t.pid)] = true "
        "_goldclaim(p, t.pid) "
        "p.anchor = {x = t.x, y = t.y, pid = t.pid} "
        "p.last_sent = {x = t.x, y = t.y, pid = t.pid} "
        "p.pending = {pid = pid, uuid = uuid, key = tostring(uuid), x = t.x, y = t.y} "
        "if p.hit ~= nil then p.judgeq = p.judgeq or {} "
        "table.insert(p.judgeq, p.hit) end "
        "p.judge = p.hit "
        "p.hit = p.pending "
        "p.march_before = {} "
        "pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() "
        "if ms == nil then return end "
        "for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) "
        "if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) "
        "if u ~= nil then p.march_before[u] = true end end end end) "
        "p.before = %(energy)s "
        "p.cur = nil "
        "%(gold)s = p "
        "return 1 end)()"
        % {"gold": _GOLD, "energy": golden_energy(), "fallback": GOLDEN_ATTACK_COST}
    )



def golden_land_or_reaim() -> str:
    """Lua *expression* -> ``-1`` while the march is still flying, else `golden_reaim_now`.

    THE BEAT THAT FINDS THE LANDING IS THE BEAT THAT SENDS THE ORDER (#2390). The wait
    used to read «has our march landed» on a four-tenths beat and then, in a SECOND
    statement, ask for the re-aim. Between those two statements sits a whole turn of the
    player — 0.2 s at the VM and about a second and a half by the time it has been logged
    — and the window a march can be re-aimed in was measured off the operator's own
    hand-driven chain at 0.08-3.4 s. So the turn between them was most of the window.

    Here they are one call. While the server's arrival stamp for this run's own order
    (`p.eta_ms`) is still in the future the answer is `-1` and the caller beats again; on
    the first beat that finds it past, the re-aim goes out inside the same round trip and
    the answer is whatever `golden_reaim_now` answers (1 re-aimed, 0 nothing to re-aim,
    -3 nothing chosen, -4 the zombie is gone).

    Nothing parked means nothing to wait for — the first lap of a run — and that falls
    straight through to the re-aim, which answers `0` and sends the ordinary way.
    """
    return ("(function() " + _GOLD_P +
            "local due = tonumber(p.eta_ms) "
            "if due ~= nil and due > 0 then "
            "local now = nil "
            "pcall(function() now = tonumber(UITimeManager.Instance:GetServerTime()) end) "
            "if now == nil then "
            "pcall(function() now = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end "
            "if now == nil then now = os.time() * 1000 end "
            "if now < due then return -1 end end "
            "return " + golden_reaim_now() + " end)()")


def golden_confirm() -> str:
    """Count the attack — but only once the GAME holds a march of ours.

    The send is not the attack. `SendCreateMarchMessage` returns cleanly whether or not
    the server honoured it (docs/research/world-monsters.md, Findings 13 and 16), so a
    run that counted its own presses would report five attacks over an evening in which
    nothing left the base. This is pressed after the march has been seen in
    `WorldMarchDataManager`, and it is the only thing that moves the tally.
    """
    return (
        _GOLD_P +
        "if p.pending == nil then "
        'CS.UnityEngine.Debug.LogError("ACT golden_confirm skipped=nothing-pending") return end '
        "p.attacks = (tonumber(p.attacks) or 0) + 1 "
        "p.misses = 0 p.reaim_miss = 0 "
        "local lap_now = nil "
        "pcall(function() lap_now = (tonumber(UITimeManager.Instance:GetServerTime()) or 0) / 1000 end) "
        "if lap_now ~= nil and lap_now > 0 then "
        "local was = tonumber(p.lap_at) "
        "if was ~= nil and lap_now > was then "
        "p.lap_sum = (tonumber(p.lap_sum) or 0) + (lap_now - was) "
        "p.lap_n = (tonumber(p.lap_n) or 0) + 1 "
        "p.lap_last = lap_now - was end "
        "p.lap_at = lap_now end "
        # WHAT THE SERVER TOOK, not what it quoted (#1702): live, a 10-energy attack was
        # charged 8. The quote is the fallback for the case where the purse could not be
        # read at all.
        "local charged = nil "
        "local before = tonumber(p.before) "
        "if before ~= nil then charged = before - %(energy)s end "
        "if charged == nil or charged <= 0 then charged = tonumber(p.cost) or 0 end "
        "p.spent = (tonumber(p.spent) or 0) + charged "
        "local pid = p.pending.pid "
        # THE TARGET MOVES TO THE KILL WATCH (#1702): the march proves the attack went,
        # and the zombie vanishing proves it is over — two facts, counted separately.
        "p.hit = p.pending "
        "p.pending = nil "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_confirm pid="..tostring(pid)'
        '.." attacks="..tostring(p.attacks).." spent="..tostring(p.spent)'
        '.." charged="..tostring(charged))'
        % {"gold": _GOLD, "energy": golden_energy()}
    )


def golden_launched() -> str:
    """Lua *expression* -> 1 once a march of OURS exists that did not exist before the send.

    **THE PROOF THAT AN ATTACK IS UNDER WAY** (#1702), and it is the operator's own model:
    a march appearing in the game's list is the send having reached the server, and it is
    a fact about the ORDER rather than about anything we paid for it.

    What it replaces is «the purse went down by what the attack cost», which was wrong
    twice over. The server does not always charge the quoted price — live, a 10-energy
    attack was taken at 8 — and the purse does not only go DOWN: a player who tops their
    energy up mid-chain (56 → 102, live) makes an unmoved purse look like a send nobody
    received, and the chain stopped over three marches that had all gone out.

    **THE SQUAD GOING BUSY IS THE SAME PROOF, and it had to be added (#1702.)** The march
    list is the client's, and the client lists a march when it gets round to it; a send
    that WAS accepted but whose march had not been listed yet read as a refusal, the chain
    wrote the target off and ordered the squad somewhere else — and the game re-routed a
    squad that was already walking. That is the operator's «меняет маршрут, когда уже идёт
    на зомби», and it is a bug in the proof, not in the send.

    So either half is enough: OUR OWN SQUAD carrying a march it was not carrying before,
    or the game answering that the squad is no longer free. The chain never sends unless
    the squad IS free (:func:`golden_squad_free`), so «busy now» can only be the order we
    just gave.

    **IT ASKS THE FORMATION, NOT THE ACCOUNT (#1702).** The march list is every squad's,
    so an auto-join raising a SECOND squad inside the four seconds the panel waits used to
    confirm an order that had been refused. `GetOwnerFormationMarch` answers for our
    formation alone, and a march standing in a banner (`teamUuid ~= 0`) is not the order
    we gave — from outside the two look alike, both carrying `endTime = 0`.

    **A REDEPLOY MAKES NO NEW MARCH, so it is proved differently (#1702).**
    `SendChangeMarchToServer` re-targets the march the squad already has: the uuid does
    not change, the status turns from STATION to MOVING and `targetPos` becomes the tile
    we asked for. So «a march that was not there before» can never come true for one, and
    the proof is that the run's own march now points at the very tile of the send. The
    squad-went-busy half cannot answer either: it was already busy, standing there.

    `1` when nothing is pending, so a caller polling this after a skipped send is not left
    waiting for a march nobody ordered.
    """
    return (
        "(function() " + _GOLD_P + _GOLD_OWN_MARCH +
        "if p.pending == nil then return 1 end "
        "if math.floor(tonumber(p.redeploy) or 0) == 1 then "
        "local m = _ownmarch(p) "
        "if m == nil then return 0 end "
        "local tp = nil pcall(function() tp = tostring(m.targetPos) end) "
        "if tp ~= nil and tp == tostring(p.pending.pid) then return 1 end "
        "return 0 end "
        "local seen = p.march_before or {} "
        "local mine = nil "
        "pcall(function() local P = LuaEntry.Player "
        "mine = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch("
        "P.uid, p.formation, P.allianceId) end) "
        "if mine ~= nil then local u, team = nil, '0' "
        "pcall(function() u = tostring(mine.uuid) end) "
        "pcall(function() team = tostring(mine.teamUuid) end) "
        "if u ~= nil and not seen[u] and (team == '0' or team == 'nil') then "
        # THE UUID IS KEPT (#1702). This is the one moment the run can be certain which
        # march is its own, and `_ownmarch` needs it later: when the squad has landed and
        # `GetOwnerFormationMarch` answers nil, the march is asked for by name.
        "p.own_march = u " + _GOLD + " = p "
        "return 1 end end "
        "local fresh = nil "
        "pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() "
        "if ms == nil then return end "
        "local want = math.floor(tonumber(p.squad) or -1) "
        "for i = 0, (ms.Count - 1) do local x = nil pcall(function() x = ms[i] end) "
        "if x ~= nil then local u, team, slot = nil, '0', -1 "
        "pcall(function() u = tostring(x.uuid) end) "
        "pcall(function() team = tostring(x.teamUuid) end) "
        "pcall(function() slot = math.floor(tonumber(x.armyInfo.f4) or -1) end) "
        "if u ~= nil and not seen[u] and (team == '0' or team == 'nil') "
        "and (want < 0 or slot == want) then fresh = u end end end end) "
        "if fresh ~= nil then p.own_march = fresh " + _GOLD + " = p "
        "return 1 end "
        "local busy = false "
        "pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if tostring(v.uuid) == tostring(p.formation) then "
        "busy = not " + _SQUAD_FREE + "(v) end end end) "
        "return busy and 1 or 0 end)()"
    )


def golden_gone() -> str:
    """Lua *expression* -> 1 when the zombie this run last hit is no longer on the map.

    **THE PROOF THAT THE ATTACK IS OVER** (#1702). The march says the order went out; the
    monster vanishing says the fight happened. It is asked around the target's own tile,
    with the golden config ids as the whitelist, so a different monster standing nearby
    cannot answer for it.

    `1` when there is nothing to look for. A zombie somebody ELSE killed first answers `1`
    too, and that is right: the question is «is it still there to be fought», not «was it
    ours». The caller treats a `0` that never clears as «moving on», never as a failure —
    a monster that outlives the wait costs the chain nothing but the wait.
    """
    return (
        "(function() " + _GOLD_P +
        # THE TARGET BEING JUDGED IS THE ONE SET ASIDE BY THE SEND (#2390). The chain
        # orders the next zombie the moment the squad lands, and only then looks at what
        # it hit — so `p.hit` by that time is the NEW target, still alive and about to be
        # attacked. `p.judge` is the previous one, parked by `golden_send`; with nothing
        # parked there is nothing to judge and the answer is «gone», which counts no kill
        # (`golden_note_kill` refuses an empty slot for the same reason).
        "local t = (p.judgeq or {})[1] or p.judge "
        "if t == nil then return 1 end " +
        _GOLD_WS +
        "if ws == nil then return 1 end "
        "local want = tostring(t.key or t.uuid or 0) "
        "local there = false "
        "pcall(function() "
        "local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() "
        "for _, id in ipairs(p.ids or {%(cfg)d}) do pcall(function() ids:Add(id, 1) end) end "
        "local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, "
        "CS.UnityEngine.Vector2Int)() "
        "ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 3, ids, res) "
        "local e = res:GetEnumerator() "
        "while e:MoveNext() do if tostring(e.Current.Key) == want then there = true end end end) "
        "return there and 0 or 1 end)()"
        % {"cfg": GOLDEN_ZOMBIE_CFG}
    )


def golden_note_kill() -> str:
    """Count the zombie that has gone, and stop looking for it.

    Kept apart from the attack tally on purpose (#1702): a march that went out and a
    zombie that fell are two different facts, and a run that sent three orders and saw two
    of the three vanish should say exactly that rather than round either number to the
    other.
    """
    return (
        _GOLD_P +
        "local t = (p.judgeq or {})[1] or p.judge "
        "if t == nil then return end "
        "p.kills = (tonumber(p.kills) or 0) + 1 "
        "local uuid = t.uuid "
        "if p.judgeq ~= nil and p.judgeq[1] ~= nil then table.remove(p.judgeq, 1) end "
        "p.judge = nil "
        "p.dry = 0 "
        "local near = math.floor(tonumber(p.reach_near) or 0) "
        "if near > 0 then p.reach = near end "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_note_kill uuid="..tostring(uuid)'
        '.." kills="..tostring(p.kills))'
        % {"gold": _GOLD}
    )


def golden_drop_kill() -> str:
    """Stop waiting for a zombie that will not go — somebody else's kill, or a long fight.

    Not a failure and never counted: the chain moves on, and the run's report shows one
    more attack than kills, which is the honest shape of what happened.
    """
    return (
        _GOLD_P +
        "local t = (p.judgeq or {})[1] or p.judge "
        "if t == nil then return end "
        "local uuid = t.uuid "
        "if p.judgeq ~= nil and p.judgeq[1] ~= nil then table.remove(p.judgeq, 1) end "
        "p.judge = nil "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_drop_kill uuid="..tostring(uuid))'
        % {"gold": _GOLD}
    )


def golden_here() -> str:
    """Lua *expression* -> 1 when the armed target is still on the map, 0 when it is gone.

    The last gate before a send, and it obeys THE_LIST_RULE like everything else that can
    take a row out (#1702, #1272): `0` means **the map said the zombie is not there**, and
    an unread district can never say that. So three answers collapse into «still there» —
    nothing armed, a read that failed, and a tile whose district the client does not hold
    (`HasPointInfo`) — and only a district the client HAS, answering without this zombie
    in it, returns `0`.

    It used to be asked with the camera flown onto the target, and that flight is gone:
    the queue is reaped by every scan now, so a target that survived to be armed has
    already been checked against the map wherever the map was readable. What is left here
    is the cheap local confirmation, and it must not turn "I cannot see that far" into a
    dropped zombie — that is a row the chain could never get back.
    """
    return (
        "(function() " + _GOLD_P +
        "local t = p.cur "
        "if t == nil then return 1 end " +
        _GOLD_WS +
        "if ws == nil then return 1 end "
        "local want = tostring(t.key or t.uuid or 0) "
        "local there = false "
        "local ok = pcall(function() "
        "local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() "
        "for _, id in ipairs(p.ids or {%(cfg)d}) do pcall(function() ids:Add(id, 1) end) end "
        "local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, "
        "CS.UnityEngine.Vector2Int)() "
        "ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 3, ids, res) "
        "local e = res:GetEnumerator() "
        "while e:MoveNext() do if tostring(e.Current.Key) == want then there = true end end end) "
        "if there then return 1 end "
        "if not ok then return 1 end "
        "local known = nil "
        "pcall(function() known = ws:HasPointInfo(t.pid) end) "
        "if known ~= true then return 1 end "
        "return 0 end)()"
        % {"cfg": GOLDEN_ZOMBIE_CFG}
    )


def golden_target_live() -> str:
    """Lua *expression* -> 1 when the client can still hand over the armed target's uuid.

    **The STRICT question, and it is strict on purpose (#1702).** `golden_here` is
    deliberately lenient — an unread district can never say «gone», because a row wrongly
    dropped is a zombie the registry can never get back. This one is the opposite trade,
    and it is asked of ONE target that a march is about to be spent on: if the client
    cannot name that uuid at that tile right now, the order would be sent at nothing.

    It is the same check `golden_send` makes a moment later (`dropped=stale`), moved to
    where it is cheap. Measured live: of fifteen laps of a run, **nine ended in
    `dropped=stale`** — a whole lap each, spent choosing a target the client had already
    forgotten. Asked here, the chain simply picks again and sends in the same lap.
    """
    return (
        "(function() " + _GOLD_P + _GOLD_WS + _GOLD_FRESH_UUID +
        "if ws == nil then return 1 end "
            # OFF-CAMERA IS NOT DEAD (#1702). The client answers only for tiles it
            # is HOLDING, so a candidate in the invasion's own corner reads «not
            # there» whether it is alive or not — live, 144 rows dropped in a row
            # while the operator watched dozens of the same zombies on screen. A far
            # candidate is taken on trust here and proved by the send, which flies to
            # it before it orders anything.
            "local t0 = p.cur "
            "if t0 ~= nil then local cx, cy = nil, nil "
            "pcall(function() cx, cy = ws.CurTilePos.x, ws.CurTilePos.y end) "
            "if cx ~= nil then local dx, dy = (t0.x - cx), (t0.y - cy) "
            "if math.sqrt(dx * dx + dy * dy) > 40 then return 1 end end end "
        "local t = p.cur "
        "if t == nil then return 0 end "
        "return (_freshuuid(ws, p, t) ~= nil) and 1 or 0 end)()"
    )


def golden_drop_target() -> str:
    """Take the armed target off the queue without sending anything at it.

    For a zombie that is not there any more (:func:`golden_here`). It is NOT a miss — no
    order was given, nothing was refused, and the run has no reason to think the game has
    stopped listening — so the miss streak is left alone and the chain simply picks again.
    """
    return (
        _GOLD_P +
        "if p.cur == nil then return end "
        "local pid, uuid = p.cur.pid, p.cur.uuid "
        "p.used[tostring(pid)] = true "
        "p.dropped = (tonumber(p.dropped) or 0) + 1 "
        # A DROP IS A PROVEN DISAPPEARANCE, and it counts as one (#1702). The client was
        # asked about this exact uuid at this exact tile and had no answer — that is the
        # map speaking, not an absence of looking, so it feeds the same counter the
        # reaping does and the ground gets redrawn once enough of them pile up. Live, a
        # lap dropped six stale rows in a row and sent nothing, because nothing was
        # telling the threshold that the picture had gone bad.
        "p.vanished = (tonumber(p.vanished) or 0) + 1 "
        "p.since_refresh = (tonumber(p.since_refresh) or 0) + 1 "
        "p.cur = nil "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_drop_target pid="..tostring(pid)'
        '.." uuid="..tostring(uuid).." dropped="..tostring(p.dropped))'
        % {"gold": _GOLD}
    )


def golden_unstick() -> str:
    """Walk the squad home, because where it is standing it will not take orders (#1702).

    **The operator's own finding, and it is a rule of the game rather than a bug of
    ours:** a squad standing on DIRTY GROUND — the fouled tiles the invasion leaves —
    accepts neither an attack nor a move. From outside it looks exactly like every other
    silent refusal: the send returns cleanly and no march appears.

    So a refusal at a target the client says is still there, with an army in the squad, is
    answered by taking the squad OFF the ground it is on instead of by counting another
    refusal. `MarchUtil.OnBackHome` is the game's own «recall» and is tried in both the
    shapes this client has been seen to take; the chain then measures from the base again,
    which is where the squad is going.

    It is counted apart from the misses — `p.unstuck` — and it CLEARS the miss streak,
    because a squad that could not move is not a client that has gone deaf.
    """
    return (
        _GOLD_P +
        "local f = p.formation "
        "local ok = false "
        "local sent = false "
        "local want = p.march_uuid "
        "local tgt = nil if p.pending ~= nil then tgt = p.pending.uuid end "
        "pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() "
        "if ms == nil then return end "
        "for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) "
        "if m ~= nil then local u, e, t = nil, nil, nil "
        "pcall(function() t = tostring(m.targetUuid) end) "
        "pcall(function() u = m.uuid end) pcall(function() e = tonumber(m.endTime) end) "
        # …INCLUDING A MARCH WITH NO CLOCK (#1702). `endTime = 0` is the phantom: the
        # client drew a march the server never confirmed, and it is exactly the one
        # that has to come back. Filtering it out is how one survived a recall.
        # OURS, AND ONLY OURS (#1702). A rally march of the player's own has no
        # arrival clock either, and recalling it would take the account out of its
        # alliance's rally. So a march is recalled when it is the one this hunt
        # parked, when it aims at the zombie we are attacking, or when it has a
        # clock of its own — never merely because it is clockless.
        "local mine = (want ~= nil and u == tostring(want)) "
        "or (tgt ~= nil and t ~= nil and t == tostring(tgt)) "
        "or (e ~= nil and e > 0) "
        "if u ~= nil and mine then "
        "TimerManager:GetInstance():DelayInvoke(function() "
        "pcall(function() MarchUtil.OnBackHome(u) end) end, 0.5) sent = true end end end end) "
        "ok = sent "
        "if not sent and f ~= nil then "
        "ok = pcall(function() MarchUtil.OnBackHome(f) end) end "
        "p.unstuck = (tonumber(p.unstuck) or 0) + 1 "
        "p.misses = 0 "
        # THE PARKED CLOCK GOES WITH IT (#1702). `eta_ms` is what the chain waits on, and
        # a recall makes the march it belonged to meaningless — left standing, the wait
        # that triggered the recall triggers it again on the next lap, for ever.
        "p.eta_ms = nil "
        # …AND THE NEXT RIDE IS SKIPPED, ONCE (#1702). Every distance the chain works out
        # is measured from `anchor or home`, and a recalled squad is at neither: it is
        # wherever it happened to be when the order was cancelled, walking. The planner
        # then prices both the direct march and the ride off the wrong origin, and live
        # that is a ride quoted at 40 seconds that took more than two hundred. The
        # comparison is meaningless until the squad is somewhere the chain knows about,
        # so the next send is a plain attack march and the ride resumes after it.
        "p.skip_ride = 1 "
        # THE TARGET SURVIVES A RECALL (#1702). The chain re-picks every lap, so
        # clearing it there changed nothing; for a hand press it changed everything —
        # «я его развернул и второй раз не смог отправить» was «Вернуть отряд»
        # throwing away the zombie the person had just fixed. The ORDER is forgotten,
        # the CHOICE is not.
        "p.pending = nil p.hit = nil p.judge = nil p.judgeq = {} p.crowd = nil "
        "if p.home ~= nil then p.anchor = nil end "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_unstick ok="..tostring(ok)'
        '.." unstuck="..tostring(p.unstuck))'
        % {"gold": _GOLD}
    )


#: How long a march the chain is willing to WAIT OUT before deciding the squad is not on
#: a hunt at all (#1702). A hop between two golden zombies is seconds; the longest ride
#: the planner will take is `approach_sec` (60 by default) plus the last few tiles. A
#: clock three minutes out is therefore never this chain's march — it is a mine being
#: gathered, a rally, a treasure run, something the person sent by hand. Measured live:
#: 109 minutes, and the hunt sat in front of it.
GOLDEN_WAIT_CEILING = 180


def golden_eta_left() -> str:
    """Lua *expression* -> seconds until the parked march lands; -1 when nothing is parked.

    The same clock every wait in the chain uses — the server's own `endTime` for the
    newest march of ours — but as a NUMBER rather than as a yes/no, so a caller can tell
    «nearly there» from «this is not our march at all» (:data:`GOLDEN_WAIT_CEILING`).

    **AND ONLY FOR A MARCH THIS HUNT DID NOT ORDER (#1702).** The ceiling exists to stop
    the chain waiting out a mine being gathered or a rally somebody else's press sent the
    squad into. Applied to the hunt's OWN march it would do the exact opposite — cancel
    an order in flight, which is the very «меняет маршрут, когда уже идёт» this task is
    about. `p.pending` is set the moment the chain sends, so a parked order of ours
    answers `-1` here and is waited out on its own clock like any other.

    To be exact about what was and was not observed: a ride the planner quoted at 40
    seconds really did fly for 213, and the recall that followed was the RIDE'S FUSE
    doing its job at the mine, not this ceiling. The ceiling never saw that march, because
    a ride is waited out inside the send. The guard is here because nothing stopped it
    seeing the next one, and a rule that can cancel the hunt's own attack is not a rule
    worth leaving to luck.
    """
    return ("(function() " + _GOLD_P +
            "if p.pending ~= nil then return -1 end "
            "local due = tonumber(p.eta_ms) "
            "if due == nil then return -1 end "
            "local now = nil "
            "pcall(function() now = tonumber(UITimeManager.Instance:GetServerTime()) end) "
            "if now == nil then pcall(function() "
            "now = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end "
            "if now == nil then now = os.time() * 1000 end "
            "return math.floor((due - now) / 1000) end)()")


def golden_squad_free() -> str:
    """Lua *expression* -> 1 the squad can be given an order, 0 it cannot, -1 unreadable.

    **The invariant the whole chain now hangs on (#1702): never give an order to a squad
    the game says cannot take one.** Breaking it is how both of the operator's worst
    complaints happen.

    * «Залипание на шахте». The ride is a GATHER order, and a squad that lands on a mine
      starts working it — measured live, `canMarch = false` with the march's own
      `endTime` **109 minutes** away. Every attack sent into that window is refused in
      silence, and the old chain spent ten seconds proving it, wrote the target off, and
      tried the next one, for as long as the run lasted.
    * «Меняет маршрут на ходу». A send that IS accepted but whose march the client has
      not listed yet reads as a refusal, so the chain wrote the target off and ordered
      the squad somewhere else — and the game re-routed a squad that was already walking.

    **«NO ARMY» IS NOT «BUSY», and reading them as one is a bug this very reading nearly
    shipped (#1702).** Measured live on an account whose client had just restarted:
    `squad3 state=0 free=1 soldiers=0` — a squad standing AT HOME, perfectly free, whose
    army the client has simply never fetched. A gate that treats that as «busy» waits two
    minutes and stops the hunt on a good squad.

    **AND THE «BUSY» HALF ASKS THE GAME, NOT `canMarch` (#1702).** See :data:`_SQUAD_FREE`:
    the flag is recomputed by the real dispatch render and by nothing else, so a headless
    session read `canMarch = false` over a squad standing at home with 2 631 soldiers and
    the panel said «отряд занят» about a squad the player could see was not.

    So there are four answers, and the caller is expected to act on the difference:

    ``1``   the squad can be given an order right now.
    ``0``   the game says it cannot: it is marching, gathering, or standing on dirty
            ground. Waiting is the right thing.
    ``-2``  the client is holding no army for it. Nothing is wrong with the squad —
            `fill_empty_squads.md` puts the soldiers back in about a third of a second,
            and the reading is then worth taking again (#1285).
    ``-1``  the squad cannot be found at all. Neither a yes nor a no; ask again.
    """
    return (
        "(function() " + _GOLD_P +
        "if p.formation == nil then return -1 end "
        "local seen, can, n = false, nil, 0 "
        "pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if tostring(v.uuid) == tostring(p.formation) then seen = true "
        "can = " + _SQUAD_FREE + "(v) "
        "n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) "
        "if not seen or can == nil then return -1 end "
        "if n <= 0 then return -2 end "
        "if can then return 1 end "
        "return 0 end)()"
    )


#: `MarchStatus.STATION` — a march that has ARRIVED and is standing there
#: (docs/research/squad-state.md). It has no arrival time left to wait for, so a chain
#: that waits for the squad's `state` to clear waits for ever.
GOLDEN_MARCH_STATION = 0

#: `MarchStatus.COLLECTING` — a march that has arrived at a resource node and is WORKING
#: it. The squad is standing exactly as `STATION` is, and the clock on it is the ore's,
#: not a journey's: measured live, a squad that landed on a level-9 mine read
#: `COLLECTING: 3` with `endTime` five and a half hours out.
GOLDEN_MARCH_COLLECTING = 3


#: THE RUN'S OWN MARCH, AND WHETHER IT HAS LANDED (#1702). Both halves of the redeploy:
#: a squad standing on the tile it cleared still carries a march, and that march is what
#: `MarchUtil.SendChangeMarchToServer` re-targets.
#:
#: The march is asked for twice because `GetOwnerFormationMarch` is not reliable on its
#: own — its signature is `(ownerUid, formationUuid, allianceUid)` and it has been seen
#: answering `nil` over an account that genuinely held marches. So the uuid of the march
#: this run last put out is kept in the state (`p.own_march`, set by
#: :func:`golden_launched`) and asked for by name when the first question comes back
#: empty. Never a scan of the account's marches: with the pair driver two squads of the
#: same account are out at once, and «the only march there is» is then another squad's.
#:
#: LANDED means the squad is STANDING rather than travelling, and is not in a banner —
#: walking a squad out of somebody's rally to hit a zombie is not this recipe's decision
#: to make. Two readings say «standing», and both were proved live on 2026-08-22:
#:
#: * `MarchStatus.STATION` with no arrival time left — a squad on the tile it cleared.
#:   Re-aimed at a zombie 23 tiles off: purse 1871 -> 1861, status STATION -> MOVING.
#: * `MarchStatus.COLLECTING` — a squad WORKING A MINE, which is what the operator
#:   re-targets by hand every day. Rode onto a free mine (`COLLECTING: 3`, `endTime` 5.6
#:   hours out), then aimed the same march at another: **same march uuid, target
#:   425441 -> 420470, COLLECTING -> MOVING**, no walk home and no new march. That is
#:   «залипание на шахте» answered as well.
#:
#: A GATHERING march counts only when it is the RUN'S OWN (`p.own_march`). The hunt's
#: ride puts a squad on a node itself and may take it off again; a squad the PLAYER sent
#: to gather is theirs, and yanking it off the ore to hit a zombie is not a decision this
#: recipe gets to make either. A march still MOVING is never touched: re-aiming one is
#: «меняет маршрут, когда уже идёт на зомби», a bug this file has already paid for.
#: …AND THE ORIGIN OF THE NEXT MARCH FOLLOWS FROM IT (#1702). The anchor is the last
#: tile the run sent a squad to; whether it is where the NEXT march starts depends on
#: whether the squad is still standing there. Measured live on 2026-08-22, over six kills
#: of one chain: it was not — every march the server priced after a kill was priced from
#: the BASE (`eta 76 s` for a hop of 14 tiles whose target was 60 from home, `89 s` for
#: one of 10 whose target was 70, `149 s` for one of 48 at 119). A squad that has killed
#: is normally home again by the time the next order can be given.
#:
#: Measuring from an anchor the squad has left is worse than useless: it chases the
#: neighbours of the last corpse and pays the distance from the base for each, so the
#: chain drifts outwards — 46, 51, 60, 70, 78, 84, 119 tiles from home over six kills.
#:
#: So the origin is ASKED, never assumed: the anchor while the squad genuinely still has
#: a landed march to be re-aimed (the redeploy of :func:`golden_send` will be used and
#: the hop is the hop), and the base otherwise.
_GOLD_OWN_MARCH = (
    "local function _ownmarch(p) "
    "if p.formation == nil then return nil end "
    "local m = nil "
    "pcall(function() local P = LuaEntry.Player "
    "m = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch("
    "P.uid, p.formation, P.allianceId) end) "
    "if m ~= nil then return m end "
    "if p.own_march ~= nil then "
    "pcall(function() m = DataCenter.WorldMarchDataManager:GetMarch(p.own_march) end) "
    "if m ~= nil then return m end end "
    # …AND THE SQUAD'S OWN SLOT, which is the identity that always holds (#1702). The
    # formation question answers nil often enough to be useless on its own, and
    # `p.own_march` is only written when the launch proof SEES the new march — which it
    # does not when the proof came from «the squad went busy» instead. Without this
    # third question a chain reads «no march at all» over a squad standing in the field,
    # and every reading built on it (the origin, the redeploy) silently falls back to
    # the base. A march carries the slot it was sent with in `armyInfo.f4`
    # (docs/research/rally-join.md), and a slot is what `p.squad` is.
    "local want = math.floor(tonumber(p.squad) or -1) "
    "if want < 0 then return nil end "
    "pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() "
    "if ms == nil then return end "
    "for i = 0, (ms.Count - 1) do local x = nil pcall(function() x = ms[i] end) "
    "if x ~= nil then local slot = nil "
    "pcall(function() slot = math.floor(tonumber(x.armyInfo.f4) or -1) end) "
    "if slot == want then m = x end end end end) "
    "return m end "
    "local function _landed(m, p) "
    "if m == nil then return false end "
    "local team = nil pcall(function() team = tostring(m.teamUuid) end) "
    "if team ~= nil and team ~= '0' and team ~= 'nil' then return false end "
    "local st, due = nil, nil "
    "pcall(function() st = tonumber(string.match(tostring(m.status), '(%d+)%s*$')) end) "
    "pcall(function() due = tonumber(m.endTime) end) "
    "if st == " + str(GOLDEN_MARCH_STATION) + " and (due == nil or due <= 0) then "
    "return true end "
    "if st == " + str(GOLDEN_MARCH_COLLECTING) + " and p ~= nil "
    "and p.own_march ~= nil then local u = nil "
    "pcall(function() u = tostring(m.uuid) end) "
    "return u ~= nil and u == tostring(p.own_march) end "
    "return false end "
    # RE-AIMABLE IS WIDER THAN LANDED, AND THE CAPTURE SAYS SO (#2390). `_landed`
    # answers «standing still with no clock», which is the reading a mine gives; a march
    # that has just finished a zombie fight is already walking home and answers no. The
    # operator's own hand-driven chain was recorded on the wire: five `world.march.change`
    # in a row over ONE march uuid, sent between 0.1 s and 3.4 s after each arrival, the
    # `path` of every one of them starting at the tile the squad was standing on. So a
    # march THIS RUN put out, carrying nobody's banner, is re-aimable whatever its status
    # says — that is the whole window the chain lives in, and the old gate closed it.
    "local function _reaim(m, p) "
    "if m == nil or p == nil then return nil end "
    "local team = nil pcall(function() team = tostring(m.teamUuid) end) "
    "if team ~= nil and team ~= '0' and team ~= 'nil' then return nil end "
    "local u = nil pcall(function() u = tostring(m.uuid) end) "
    "if u == nil or u == 'nil' then return nil end "
    "if p.own_march ~= nil and u == tostring(p.own_march) then return m.uuid end "
    "if _landed(m, p) then return m.uuid end "
    "return nil end "
    "local function _stand(p) "
    "local m = _ownmarch(p) "
    "if m == nil then return 'nomarch' end "
    "local team = nil pcall(function() team = tostring(m.teamUuid) end) "
    "if team ~= nil and team ~= '0' and team ~= 'nil' then return 'banner' end "
    "local st, due = nil, nil "
    "pcall(function() st = tonumber(string.match(tostring(m.status), '(%d+)%s*$')) end) "
    "pcall(function() due = tonumber(m.endTime) end) "
    "if st == " + str(GOLDEN_MARCH_STATION) + " then "
    "if due == nil or due <= 0 then return 'station' end return 'station+clock' end "
    "if st == " + str(GOLDEN_MARCH_COLLECTING) + " then "
    "if p.own_march == nil then return 'mine-notours' end "
    "local u = nil pcall(function() u = tostring(m.uuid) end) "
    "if u == tostring(p.own_march) then return 'mine' end return 'mine-notours' end "
    "return 'status' .. tostring(st) end "
    # WHERE THE NEXT PICK IS MEASURED FROM, AND «WHERE» INCLUDES «WILL BE» (#2390). The
    # chain chooses its next target while the current march is still in the air, so an
    # origin that only answers for a squad standing still would measure every pick from
    # the base and walk the hunt back and forth across the map. A march of OURS that
    # carries nobody's banner is going to the anchor — it is the only place this chain
    # ever sends the squad — so the anchor is the origin whether it has landed or not.
    # (The march object's own destination field was asked for first and is not reachable:
    # reflection over it answers nothing under xLua, so the anchor the send parked is the
    # honest source.)
    "local function _origin(p) "
    "if p.anchor ~= nil then "
    "local m = _ownmarch(p) "
    "if _landed(m, p) then return p.anchor, 'anchor' end "
    "if m ~= nil then "
    "local team = nil pcall(function() team = tostring(m.teamUuid) end) "
    "if team == nil or team == '0' or team == 'nil' then "
    "return p.anchor, 'flying' end end end "
    "if p.home ~= nil then return p.home, 'home' end "
    "return p.anchor, 'anchor' end "
)


def golden_parked() -> str:
    """Lua *expression* -> 1 when the squad is out and NOTHING WILL FREE IT BY ITSELF.

    The other half of «the hunt sat there doing nothing», and it is not the ceiling
    (:data:`GOLDEN_WAIT_CEILING`) — that one answers a march with a long clock. This one
    answers a march with NO clock. Measured live on the chosen squad (#1702)::

        squad=2 state=1 free=0 soldiers=2631 status=STATION march=NORMAL team=0
                point=494542 arrive=0

    `state = 1` is «out», so :data:`_SQUAD_FREE` says no order can be given; `arrive = 0`
    means there is no landing to wait for, because the squad has already landed and is
    STANDING there. The wait brick then spent its whole allowance — ten minutes, 300
    beats — on a squad that would have read exactly the same in an hour, and the run
    ended with `attacks=0`.

    So a parked squad is RECALLED rather than waited on, the same press that takes one off
    dirty ground. Two things are deliberately NOT parked:

    * a march standing in a banner (`teamUuid ~= 0`) — that is the alliance rally the
      auto-join walked off with, it ends by itself in minutes, and recalling it would
      quit somebody's rally on their behalf;
    * a march that still has an arrival time — that one is travelling, and the ceiling
      above is the reading that decides whether it is ours to wait for.

    A squad the game says is FREE answers 0 here whatever else is true of it: this is a
    reason to recall, not a description of the ground.
    """
    return (
        "(function() " + _GOLD_P +
        "if p.formation == nil then return 0 end "
        "local seen, can = false, nil "
        "pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if tostring(v.uuid) == tostring(p.formation) then seen = true "
        "can = " + _SQUAD_FREE + "(v) end end end) "
        "if not seen or can == nil or can then return 0 end "
        "local m = nil "
        "pcall(function() local P = LuaEntry.Player "
        "m = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch("
        "P.uid, p.formation, P.allianceId) end) "
        # NO MARCH AT ALL, and the squad still will not take an order: dirty ground, or a
        # send the client swallowed. Nothing is going to change that on its own either.
        "if m == nil then return 1 end "
        "local team = nil pcall(function() team = tostring(m.teamUuid) end) "
        "if team ~= nil and team ~= '0' then return 0 end "
        # …AND A LANDED MARCH IS NO LONGER A REASON TO RECALL (#1702). It was, for as
        # long as the only send this repository had could not redeploy one. The squad
        # standing on the tile it cleared is given its next order WHERE IT STANDS now
        # (:func:`golden_send`), so recalling it would throw away exactly the saving the
        # chain is built on. What still parks a squad is a march that is not there at
        # all — dirty ground, or a send the client swallowed.
        "return 0 end)()"
    )


def golden_can_order() -> str:
    """Lua *expression* -> may this squad be given an attack RIGHT NOW. 1 / 0 / -1 / -2.

    **AND «STANDING WHERE IT KILLED» IS NOT ONE OF THE YESES — measured, twice, live
    (#1702).** The hope was worth testing, because the arithmetic said it was where the
    whole cost is. With two squads hunting on the test account, a kill split like this:

        free -> order away     median   5 s
        order -> free again    median  64 s and 115 s

    Five seconds is our own overhead — judge, pick, uuid check, send, all of it. The rest
    is the squad not coming back, and it is not the march: a squad that had just killed
    read `state=1 status=STATION team=0 point=467403 arrive=0`, STANDING on the tile it
    cleared, which is what `back = 0` asks for so the next hop is three tiles instead of
    a march from the base.

    So this reading was widened to accept a landed, banner-free march — and the game
    refused the orders. Two sends went out at a stationed squad at 01:27:51 and 01:28:01
    and **the purse did not move**: 1941 before, 1941 three minutes later. A bare
    `SendCreateMarchMessage` cannot redeploy an army that has arrived, exactly as it
    cannot move one off a resource node (docs/research/golden-zombies.md §4b). The
    player's own tap does it through the dispatch screen, which is a different call and
    is not found yet.

    **AND THEN THE DOOR WAS FOUND, so this says yes to it after all (#1702).** The
    refusal above was real and the reading of it was wrong: `SendCreateMarchMessage` is
    the call that creates a march FROM THE BASE, and a landed army needs the one the
    dispatch screen uses — `MarchUtil.SendChangeMarchToServer`, seven arguments, message
    `world.march.change`. Live on 2026-08-22, at a squad reading
    `state=1 status=STATION: 0 pos=440462 end=0`: purse 1871 -> 1861, and the march
    turned MOVING with its target on the new zombie, 23 tiles away, without a step
    homewards. It is the same lesson this file keeps paying for — a refusal that the
    person playing by hand cannot reproduce is a bug in the sender, not a rule of the
    game.

    So: free by the ordinary rule, OR out with a march of its own that has ARRIVED, has
    no arrival time left, and is not standing in a banner. A rally is left out on
    purpose — walking a squad out of somebody's banner is not this recipe's decision.
    `-2` still means «the client is holding no army», which has its own cure.
    """
    return (
        "(function() " + _GOLD_P + _GOLD_OWN_MARCH +
        "if p.formation == nil then return -1 end "
        "local seen, can, n = false, nil, 0 "
        "pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if tostring(v.uuid) == tostring(p.formation) then seen = true "
        "can = " + _SQUAD_FREE + "(v) "
        "n = math.floor(tonumber(v.totalSoldierNum) or 0) end end end) "
        "if not seen or can == nil then return -1 end "
        "if n <= 0 then return -2 end "
        "if can then return 1 end "
        "if _landed(_ownmarch(p), p) then return 1 end "
        "return 0 end)()"
    )


def golden_no_ride() -> str:
    """Switch the fast approach off for the REST of this run, and say why (#1702).

    One ride that ends in a gather parks the squad for an hour or more, so the chain does
    not get to make that mistake twice: the first time a ride lands and the squad comes
    back «cannot march», the ride is disowned for the run and the remaining kills are
    plain attack marches. The setting the person chose is untouched — this is a
    within-run fuse, not a preference.
    """
    return (
        _GOLD_P +
        "p.no_ride = 1 "
        "p.rides_dropped = (tonumber(p.rides_dropped) or 0) + 1 "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_no_ride dropped="..tostring(p.rides_dropped))'
        % {"gold": _GOLD}
    )


def golden_riding_off() -> str:
    """Lua *expression* -> 1 when this run has disowned the ride (:func:`golden_no_ride`)."""
    return ("(function() " + _GOLD_P +
            "return (math.floor(tonumber(p.no_ride) or 0) == 1) and 1 or 0 end)()")


def golden_stuck() -> str:
    """Lua *expression* -> 1 when the squad looks stuck where it stands, else 0.

    Asked after a send that produced no march. Two readings have to agree: the squad
    holds an army (so the server is not refusing an empty formation) and the game says it
    is not free (:data:`_SQUAD_FREE` — `state` plus `IsFree()`), which is what a squad on
    dirty ground reads. Both are the client's own answers about OUR formation, not a
    guess about the ground.
    """
    return (
        "(function() " + _GOLD_P +
        "if p.formation == nil then return 0 end "
        "local n, can = 0, true "
        "pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if tostring(v.uuid) == tostring(p.formation) then "
        "n = math.floor(tonumber(v.totalSoldierNum) or 0) "
        "can = " + _SQUAD_FREE + "(v) end end end) "
        "return ((n > 0) and (can == false)) and 1 or 0 end)()"
    )


def golden_note_miss() -> str:
    """A send that produced no march of ours: write it off and let the chain try another.

    **Not a failure of the run** (#1702). The commonest reason is the honest one: the
    zombie was already dead — the client's list is a snapshot and another player got there
    first — and the server simply refuses an order at a monster that is not there. Trying
    the next target is exactly right, and stopping the whole chain over it is what the
    strict version did.

    What it must NOT do is spin: a client that has gone deaf refuses everything, and a run
    that answers that by picking another target for ever is a busy loop against a dead
    link. So the misses are counted and the caller stops at the second one in a row.
    """
    return (
        _GOLD_P +
        "p.misses = (tonumber(p.misses) or 0) + 1 "
        "if math.floor(tonumber(p.redeploy) or 0) == 1 then "
        "p.reaim_miss = (tonumber(p.reaim_miss) or 0) + 1 "
        "if p.reaim_miss >= %(reaims)d then "
        "p.own_march = nil p.reaim_miss = 0 "
        "p.reaim_resets = (tonumber(p.reaim_resets) or 0) + 1 "
        'CS.UnityEngine.Debug.LogError("ACT golden_reaim_reset after=%(reaims)d'
        'total="..tostring(p.reaim_resets)) '
        "end end "
        "p.redeploy = 0 "
        "local uuid = p.pending and p.pending.uuid "
        "p.pending = nil p.hit = nil p.judge = nil p.judgeq = {} p.crowd = nil "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_note_miss uuid="..tostring(uuid)'
        '.." misses="..tostring(p.misses)'
        '.." reaim_miss="..tostring(p.reaim_miss))'
        % {"gold": _GOLD, "reaims": GOLDEN_REAIM_MISSES}
    )


def golden_misses() -> str:
    """Lua *expression* -> how many sends in a row produced no march."""
    return ("(function() " + _GOLD_P +
            "return math.floor(tonumber(p.misses) or 0) end)()")


def golden_reaimable() -> str:
    """Lua *expression* -> 1 while the run's own march can still be RE-AIMED, else 0.

    The window the chain lives in. A march this run put out — banner-free, whatever its
    status — takes `world.march.change` where it stands, so there is no reason to wait
    for it to disappear and no reason to walk the squad home. When it answers 0 the march
    is gone and the next order has to be a new one out of the base, which the send does
    by itself and counts as `fallbacks`.
    """
    return ("(function() " + _GOLD_P + _GOLD_OWN_MARCH +
            "local m = _ownmarch(p) "
            "return (_reaim(m, p) ~= nil) and 1 or 0 end)()")


def golden_marching() -> str:
    """Lua *expression* -> 1 while the run's own squad is out marching, else 0.

    The squad's own `state` on `ArmyFormationDataManager.ArmyFormationList`, and not the
    world's march list: another squad of the same account may be gathering somewhere and
    has nothing to do with this chain. Measured live on 2026-08-19 — a squad standing in
    the base reads `state = 0` and one that has just been sent reads `1`.

    `WorldMarchDataManager:GetOwnerFormationMarch` looks like the right question and is
    not usable here: its real signature is `(ownerUid, formationUuid, allianceUid)` and it
    answers `nil` for every argument we could give it, including the formation's own
    `ownerUid`, while the account genuinely held four marches.
    """
    return ("(function() " + _GOLD_P +
            "if p.formation == nil then return 0 end local st = nil "
            "pcall(function() "
            "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
            "if tostring(v.uuid) == tostring(p.formation) then "
            "st = math.floor(tonumber(v.state) or 0) end end end) "
            "return ((st or 0) == 1) and 1 or 0 end)()")


def golden_can_go() -> str:
    """Lua *expression* -> 1 while there is energy, a target and room in the day's limit.

    The energy is ASKED every lap, never subtracted by us: the same purse is spent by a
    person playing on the screen at the time, and a number we kept would go wrong within
    a minute of them touching anything.
    """
    return (
        "(function() " + _GOLD_P +
        "local left = %(energy)s "
        "local cost = math.floor(tonumber(p.cost) or %(fallback)d) "
        "if cost <= 0 then cost = %(fallback)d end "
        "if left < cost then return 0 end "
        "local lim = math.floor(tonumber(p.limit) or 0) "
        "if lim > 0 and (tonumber(p.attacks) or 0) >= lim then return 0 end "
        "return (%(queued)s > 0) and 1 or 0 end)()"
        % {"energy": golden_energy(), "fallback": GOLDEN_ATTACK_COST,
           "queued": golden_queued()}
    )


def golden_last_march() -> str:
    """Lua *expression* -> 1 when the march about to go out is the last this run can make.

    The one that has to bring the squad HOME: everything before it deliberately leaves it
    standing on the map so the chain is short, and a squad left out there when the run
    ends is a squad somebody else can hit.
    """
    return (
        "(function() " + _GOLD_P +
        "local left = %(energy)s "
        "local cost = math.floor(tonumber(p.cost) or %(fallback)d) "
        "if cost <= 0 then cost = %(fallback)d end "
        "if left < cost * 2 then return 1 end "
        "local lim = math.floor(tonumber(p.limit) or 0) "
        "if lim > 0 and (tonumber(p.attacks) or 0) + 1 >= lim then return 1 end "
        "return (%(queued)s <= 1) and 1 or 0 end)()"
        % {"energy": golden_energy(), "fallback": GOLDEN_ATTACK_COST,
           "queued": golden_queued()}
    )


def golden_attacks() -> str:
    """Lua *expression* -> how many marches this run has sent."""
    return "(function() " + _GOLD_P + "return math.floor(tonumber(p.attacks) or 0) end)()"


def golden_spent() -> str:
    """Lua *expression* -> how much energy this run has spent, at the game's own price."""
    return "(function() " + _GOLD_P + "return math.floor(tonumber(p.spent) or 0) end)()"


def golden_report() -> str:
    """Lua *expression* -> one line of `key=value` the panel parses and files away.

    The run's whole tally in one round trip: what was found, what was sent, what it cost
    and what is left. The panel stores it (`panel.db`) and draws it; it counts nothing
    itself.
    """
    return (
        "(function() " + _GOLD_P +
        "return 'found=' .. tostring(math.floor(tonumber(p.found) or 0)) .. "
        "' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) .. "
        "' kills=' .. tostring(math.floor(tonumber(p.kills) or 0)) .. "
        "' dropped=' .. tostring(math.floor(tonumber(p.dropped) or 0)) .. "
        "' vanished=' .. tostring(math.floor(tonumber(p.vanished) or 0)) .. "
        "' refreshes=' .. tostring(math.floor(tonumber(p.refreshes) or 0)) .. "
        "' unstuck=' .. tostring(math.floor(tonumber(p.unstuck) or 0)) .. "
        # HOW MANY ORDERS WERE GIVEN WHERE THE SQUAD STOOD (#1702). The difference
        # between this and `attacks` is the number of kills that cost a walk home, which
        # is the only number that says whether the redeploy is actually being reached.
        "' redeploys=' .. tostring(math.floor(tonumber(p.redeploys) or 0)) .. "
        "' fallbacks=' .. tostring(math.floor(tonumber(p.fallbacks) or 0)) .. "
        "' reaim_drops=' .. tostring(math.floor(tonumber(p.reaim_drops) or 0)) .. "
        "' reaim_resets=' .. tostring(math.floor(tonumber(p.reaim_resets) or 0)) .. "
        "' spent=' .. tostring(math.floor(tonumber(p.spent) or 0)) .. "
        "' cost=' .. tostring(math.floor(tonumber(p.cost) or 0)) .. "
        "' energy=' .. tostring(%(energy)s) .. "
        "' queued=' .. tostring(%(queued)s) .. "
        "' squad=' .. tostring(math.floor(tonumber(p.squad) or 0)) .. "
        "' lap=' .. tostring(math.floor((tonumber(p.lap_n) or 0) > 0 and ((tonumber(p.lap_sum) or 0) / (tonumber(p.lap_n) or 1)) or 0)) .. "
        "' laplast=' .. tostring(math.floor(tonumber(p.lap_last) or 0)) end)()"
        % {"energy": golden_energy(), "queued": golden_queued()}
    )


def golden_survey() -> str:
    """Lua *expression* -> one line of `key=value`: the board the panel draws, in one ask.

    A READ and nothing else — it arms nothing, queues nothing and touches no state the
    run keeps, so the panel may poll it while a run is in flight without disturbing it.

    ``seen`` is how many golden zombies the CLIENT currently knows about, which is as
    wide as what it has loaded and not as wide as the map: it was 11 straight after
    entering the world and 135 after one lap of the server (#1519). ``-1`` means the
    question could not be asked at all — the base is on screen, and the world's own
    controller does not exist there.
    """
    return (
        "(function() local energy = %(energy)s local cost = %(cost)s "
        "local seen = -1 "
        "%(ws)s"
        "if ws ~= nil then seen = 0 pcall(function() "
        "local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, CS.System.Int32)() "
        "ids:Add(%(cfg)d, 1) "
        "local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, "
        "CS.UnityEngine.Vector2Int)() "
        "ws:GetMonsterListInArea(ws.CurTilePos, 2000, ids, res) "
        "seen = res.Count end) end "
        "local can = 0 if cost > 0 then can = math.floor(energy / cost) end "
        "local f = nil pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if f == nil then f = v.uuid end end end) "
        "local function sp(k) local v = nil "
        "pcall(function() v = MarchUtil.CalcMarchSpeedByConfig(k, f, nil, nil) end) "
        "return tonumber(v) or 0 end "
        "local sa, sc = sp(MarchTargetType.ATTACK_MONSTER), sp(MarchTargetType.COLLECT) "
        "local ratio = 0 if sa > 0 then ratio = sc / sa end "
        "return 'energy=' .. tostring(energy) .. ' cost=' .. tostring(cost) .. "
        "' attacks=' .. tostring(can) .. ' seen=' .. tostring(seen) .. "
        "' atk=' .. tostring(math.floor(sa * 1000 + 0.5)) .. "
        "' col=' .. tostring(math.floor(sc * 1000 + 0.5)) .. "
        "' ratio=' .. tostring(math.floor(ratio * 100 + 0.5)) end)()"
        % {"energy": golden_energy(), "cost": golden_attack_cost(),
           "ws": _GOLD_WS, "cfg": GOLDEN_ZOMBIE_CFG}
    )


# ---------------------------------------------------------------------------
# What a drawn monster IS — the prefab name, looked up in the game's own config
# ---------------------------------------------------------------------------
# Task #1519, and it is the same lesson the secret tasks taught (#1281): **the digits in
# a thing's identifier lie, and the real answer is a row in the client's config.** A
# roaming monster the client has DRAWN says nothing about itself before it is selected —
# no uuid, no config id, no level — except the name of the prefab it was made from:
#
#     WorldMonster_General_invasion(Clone)
#
# and that name is a column of `lw_world_monster`. Read live on 2026-08-19:
#
#     cfg 1030000  pic_name = world_monster_general_invasion  level = 10  type = 7  special = 9
#
# — the same string as the clone's, bar the case and the underscores. So a prefab name
# normalised (lower-cased, everything but letters and digits dropped) is a key into the
# config, and the level comes back as the game's own number instead of the 0 that the
# «уровень» column had been showing for every scene-read monster.
#
# **A prefab is not always ONE monster, and the difference decides what may be said.**
# Census of every `pic_name` in the table, live:
#
#     world_monster_general_invasion   3 rows, all level 10, type 7   <- the golden zombie
#     world_monster_boss_invasion     30 rows, levels 5..75, type 7   <- its boss
#     world_monster_boss_iron         35 rows, levels 1..35, type 1
#     …
#
# So the rule is unanimity: a prefab whose rows AGREE on a field answers it, and one
# whose rows disagree answers `nil` and the reading falls back to the level label drawn
# over the monster. A number invented for a boss that could be level 5 or level 75 is
# worse than no number at all, which is the whole reason the column was wrong in the
# first place.

#: Bump this whenever :func:`monster_prefab_lookup` changes what it builds.
#:
#: **A panel restart does NOT clear the game's Lua globals** — that is the mirror image
#: of the rule in `CLAUDE.md`. The panel was restarted onto a fixed map builder twice
#: and went on reading the EMPTY map the broken one had parked in `_G`, because the game
#: VM had not gone anywhere; the fix looked like it had failed when it had never run
#: (#1519). Anything cached in the VM therefore carries the version of the code that
#: built it, and is rebuilt when they disagree.
MON_MAP_VERSION = 4


def monster_prefab_lookup() -> str:
    """Lua *statements* defining `_norm(s)` and `_monmap()` — the prefab -> config map.

    Built once and parked in `DataCenter.__lw_mon_prefab`: the table has 12 115 rows and walking
    it per read would be paid on every poll. Two ways in, and the second exists because
    the first depends on the shape of `LocalController:getTable`:

      1. the whole table at once — `getTable('lw_world_monster')` hands back
         `{index = <column name -> column id>, data = <id -> row>}`, which is plain Lua
         and costs no per-row call into the engine;
      2. failing that, the golden zombie's own row through `getValue`, which is the call
         this repository has used since #1281 and is certain of. It is three lookups, so
         the one prefab named here always resolves even if the table cannot be walked.

    Each entry is `{ids = {…}, level = <n or nil>, type = <n or nil>, special = <n or
    nil>, n = <rows> }`, where a field is `nil` when the rows behind that prefab disagree.
    """
    return (
        "local function _norm(s) "
        "return (string.gsub(string.lower(tostring(s or '')), '[^%%w]', '')) end "
        "local function _monmap() "
        "local c = DataCenter.__lw_mon_prefab "
        "if c ~= nil and c.v == %(ver)d then return c.map end "
        "local m = {} local walked, why = 0, '' "
        "local okwalk, err = pcall(function() "
        "local inst = LocalController.instance() "
        "local data = inst:getTable('lw_world_monster').data "
        "local md = inst:getLine('lw_world_monster', %(cfg)d):getMetaData() "
        "local function _col(n) local c = md[n] "
        "if type(c) == 'table' then c = c[1] end return tonumber(c) end "
        "local cpic, clv, cty, csp = _col('pic_name'), _col('level'), "
        "_col('type'), _col('special') "
        "if cpic == nil or data == nil then return end "
        "for id, row in pairs(data) do "
        "local ld = row "
        "if type(row) == 'table' and row._lineData ~= nil then ld = row._lineData end "
        "if type(ld) == 'table' then local pic = ld[cpic] "
        "if pic ~= nil and tostring(pic) ~= '' then "
        "local key = _norm(pic) local e = m[key] "
        "local lv, ty, sp = tonumber(ld[clv]), tonumber(ld[cty]), tonumber(ld[csp]) "
        "if e == nil then m[key] = {ids = {id}, n = 1, level = lv, type = ty, special = sp} "
        "else e.n = e.n + 1 "
        "if #e.ids < 32 then e.ids[#e.ids + 1] = id end "
        "if e.level ~= lv then e.level = nil end "
        "if e.type ~= ty then e.type = nil end "
        "if e.special ~= sp then e.special = nil end end end "
        "walked = walked + 1 end end end) "
        "if not okwalk then why = tostring(err) end "
        "DataCenter.__lw_mon_diag = {walked = walked, why = why} "
        # …and the one prefab this repository names by hand, so it resolves whatever the
        # table's shape turns out to be on the next build of the game.
        "pcall(function() "
        "local inst = LocalController.instance() "
        "local function v(f) return tonumber(inst:getValue('lw_world_monster', %(cfg)d, f, nil)) end "
        "local pic = inst:getValue('lw_world_monster', %(cfg)d, 'pic_name', nil) "
        "if pic ~= nil and tostring(pic) ~= '' then local key = _norm(pic) "
        "if m[key] == nil then m[key] = {ids = {%(cfg)d}, n = 1, level = v('level'), "
        "type = v('type'), special = v('special')} end end end) "
        "DataCenter.__lw_mon_prefab = {v = %(ver)d, map = m} return m end "
        % {"cfg": GOLDEN_ZOMBIE_CFG, "ver": MON_MAP_VERSION}
    )


def monster_prefab_probe() -> str:
    """Lua *expression* -> one `key=value` line about the prefab map, for a person to read.

    What it says: how many prefabs the map holds, and what it makes of the golden
    zombie's own — the config ids behind it, its level and its type. `n=0` means the map
    could not be built at all, which is the one answer worth acting on.
    """
    return (
        "(function() " + monster_prefab_lookup() +
        "local m = _monmap() local n = 0 for _ in pairs(m) do n = n + 1 end "
        "local pic = nil pcall(function() "
        "pic = LocalController.instance():getValue('lw_world_monster', %(cfg)d, 'pic_name', nil) end) "
        "local e = m[_norm(pic)] "
        "local ids = '' if e ~= nil then for _, id in ipairs(e.ids) do ids = ids .. id .. ',' end end "
        "local d = DataCenter.__lw_mon_diag or {} "
        "return 'prefabs=' .. n .. ' walked=' .. tostring(d.walked) .. "
        "' why=' .. tostring(d.why) .. ' golden_pic=' .. tostring(pic) .. "
        "' rows=' .. tostring(e and e.n) .. ' ids=' .. ids .. "
        "' level=' .. tostring(e and e.level) .. ' type=' .. tostring(e and e.type) .. "
        "' special=' .. tostring(e and e.special) end)()"
        % {"cfg": GOLDEN_ZOMBIE_CFG}
    )


# ---------------------------------------------------------------------------
# The fast approach — ride to the target on a GATHER order, then attack
# ---------------------------------------------------------------------------
# The operator's own idea, and the game's own numbers back it. `MarchUtil` prices a march
# per ORDER, not per distance:
#
#     MarchUtil.CalcMarchSpeedByConfig(targetType, formationUuid, nil, nil)
#
# and on a live account, same formation, same call:
#
#     ATTACK_MONSTER (1)     0.765          <- what a kill costs to reach
#     ATTACK_CITY   (11)     0.815
#     COLLECT        (2)     1.930          <- 2.52x faster
#     DETECT_TREASURE (50)   1.930
#
# So the long haul out to a golden zombie — they live in their own region, several
# hundred tiles from anybody's base — can be ridden on a GATHER order to a mine beside
# the target, and only the last few tiles paid at attack speed. Two separate bonuses back
# that up rather than one: `GetFormationSpeedAddByIndex` and `GetFormationCollectSpeedAdd`
# are different numbers on the same squad.
#
# **The plan is only taken when the arithmetic says it wins**, and never on a hop where
# the extra stop costs more than it saves:
#
#     direct  = dist(squad -> target) / speed_attack
#     two-leg = dist(squad -> mine) / speed_collect + dist(mine -> target) / speed_attack
#
# and the approach is used when `direct` is over the caller's threshold AND `two-leg` is
# actually shorter. Speed is read as tiles per second: 0.765 against a 492-tile haul is
# eleven minutes, which is the order of what a live run measured.
#
# **What the mine is for is the RIDE, not the ore.** The squad is sent with
# `MarchTargetType.COLLECT` at a resource tile the client already knows about —
# `WorldScene.PointManager:GetPointInfo(pid)` answers `ResPointInfo` with
# `pointType = 7` for a mine and `BuildPointInfo` / `6` for somebody's base — and the
# attack goes out once it has arrived.
#
# THE RISK, SAID PLAINLY. A squad that has arrived at a mine is GATHERING, and issuing
# the attack from there is the same move the chain's second kill already needs: a march
# sent from where the squad stands rather than from home. That is not proven live yet
# (docs/research/golden-zombies.md), and this feature inherits it exactly. What IS known:
# the ride itself costs no energy — `GetCostStaminaByTargetType(COLLECT)` is 0 against 10
# for an attack — so a plan that turns out to be impossible wastes travel time and not a
# single point of the day's purse. The recipe still proves every attack by the energy the
# server takes, so an attack that cannot be issued from the field ends the run saying so.

#: `MarchTargetType.COLLECT` — the gather order, and the fast one.
MARCH_COLLECT = 2

#: `WorldPointType.WorldResource` — what `GetPointInfo` calls a mine (`f2 = 7` on the
#: wire, `docs/research/world-tiles.md`).
POINT_MINE = 7


def golden_speeds() -> str:
    """Lua *expression* -> `attack=<n> collect=<n> ratio=<n>`, the game's own numbers.

    A READ: it prices the two orders for the run's own squad and presses nothing. The
    ratio is what says whether the approach is worth having at all on this account —
    the bonuses behind the two are separate, so a player who has levelled one and not
    the other will see a different number from the 2.52 measured on 2026-08-19.
    """
    return (
        "(function() " + _GOLD_P +
        "local f = p.formation "
        "if f == nil then pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if f == nil then f = v.uuid end end end) end "
        "local function s(t) local v = nil "
        "pcall(function() v = MarchUtil.CalcMarchSpeedByConfig(t, f, nil, nil) end) "
        "return tonumber(v) or 0 end "
        "local a, c = s(MarchTargetType.ATTACK_MONSTER), s(MarchTargetType.COLLECT) "
        "local r = 0 if a > 0 then r = c / a end "
        "return 'attack=' .. string.format('%.3f', a) .. "
        "' collect=' .. string.format('%.3f', c) .. "
        "' ratio=' .. string.format('%.2f', r) .. "
        "' cost_collect=' .. tostring(MarchUtil.GetCostStaminaByTargetType("
        "MarchTargetType.COLLECT)) end)()"
    )


#: How the squad's distance to a tile is worked out, wherever it happens to be. The
#: anchor is the last tile it was sent to this run; before the first send there is none
#: and the game answers from the base instead. Same rule as `golden_pick`, so the two
#: cannot drift into disagreeing about which target is nearer.
#:
#: **AND THE ORIGIN IS THE ANCHOR AGAIN, because the redeploy call was found (#1702).**
#: This measured HOME for a while, and the reasoning was sound at the time: 21 laps said
#: the cost of a kill tracked `2 * home_dist / 0.765` and ignored the anchor entirely,
#: because a landed army could not be given a new order and every kill was a round trip.
#: That was true of the send we had — `SendCreateMarchMessage` — and not of the game.
#: `MarchUtil.SendChangeMarchToServer` re-targets a squad standing where it killed, live,
#: with the purse taken and the march turning from STATION to MOVING without a step
#: homewards. So the nearest target to the LAST KILL is the cheap one again, and the base
#: only answers before the first send.
_GOLD_DIST = (
    "local function _dist(pid, x, y) "
    "local o = _origin(p) "
    "if o ~= nil then local dx, dy = (x - o.x), (y - o.y) "
    "return math.sqrt(dx * dx + dy * dy) end "
    "local d = nil "
    "pcall(function() d = tonumber(SceneUtils.TileDistanceToMyHome(pid, p.server)) end) "
    "return d or 1e9 end "
)


def golden_look() -> str:
    """Put the camera on the armed target, so the client streams the tiles around it in.

    Nothing is pressed and nothing is sent: the camera is the only thing that makes the
    client ask the server for a district's tiles, and `HasPointInfo` can only answer for
    tiles it has. Live, a plan for a target 700 seconds away came back `no-mine` for
    exactly that reason — the mines were on the wire and in the panel's own map, and the
    CLIENT had never loaded that corner (#1519).

    `GoToUtil.MoveToWorldPoint(pointId)` is the tile-accurate mover — the world-position
    calls take world units and land the camera at half the tile asked for
    (docs/research/world-monsters.md, Finding 9).
    """
    return (
        _GOLD_P +
        "local t = p.cur "
        "if t == nil then "
        'CS.UnityEngine.Debug.LogError("ACT golden_look skipped=no-target") return end '
        "local ok, err = pcall(function() GoToUtil.GotoWorldPos(t.x, t.y, 600, tonumber(p.server) or 0) end) pcall(function() GoToUtil.MoveToWorldPoint(t.pid) end) "
        'CS.UnityEngine.Debug.LogError("ACT golden_look ok="..tostring(ok).." err="..tostring(err)'
        '.." at="..tostring(t.x)..","..tostring(t.y))'
    )


def golden_approach_arm() -> str:
    """Work out whether to ride to the armed target on a gather order, and where to stop.

    Reads and parks; sends nothing. It prices both orders, measures the direct haul, and
    only then goes looking for a mine — a short hop never pays for the extra stop and is
    dropped before a single tile is scanned.

    The mine is chosen to minimise the WHOLE journey, not to be nearest the target: a
    mine one tile from the zombie is no good if it is on the far side of the map. Only a
    plan that beats the direct march is kept, and `p.approach` stays nil otherwise.
    """
    return (
        _GOLD_P + _GOLD_OWN_MARCH + _GOLD_DIST +
        "p.approach = nil p.why = '' "
"if math.floor(tonumber(p.skip_ride) or 0) == 1 then p.skip_ride = 0 "
"p.why = 'after-recall' "
"%(gold)s = p "
'CS.UnityEngine.Debug.LogError("ACT golden_approach skipped=after-recall") return end '
"if math.floor(tonumber(p.no_ride) or 0) == 1 then p.why = 'no-ride' "
"%(gold)s = p "
'CS.UnityEngine.Debug.LogError("ACT golden_approach skipped=no-ride") return end '
        "local t = p.cur "
        "if t == nil then "
        'CS.UnityEngine.Debug.LogError("ACT golden_approach skipped=no-target") return end '
        "local function sp(k) local v = nil "
        "pcall(function() v = MarchUtil.CalcMarchSpeedByConfig(k, p.formation, nil, nil) end) "
        "return tonumber(v) or 0 end "
        "local sa, sc = sp(MarchTargetType.ATTACK_MONSTER), sp(MarchTargetType.COLLECT) "
        "p.speed_atk, p.speed_col = sa, sc "
        "if sa <= 0 or sc <= sa then p.why = 'no-gain' %(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_approach skipped=no-gain atk="..tostring(sa)'
        '.." col="..tostring(sc)) return end '
        "local far = _dist(t.pid, t.x, t.y) "
        "local direct = far / sa "
        "p.direct_sec = math.floor(direct) "
        "local limit = tonumber(%(gold)s_approach_sec) or 60 "
        "if direct <= limit then p.why = 'short' %(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_approach skipped=short sec="..tostring(math.floor(direct))) '
        "return end "
        # -- the mines the client already knows about, in a ring around the target
        "local ws = DataCenter.__lw_gold_ws "
        "local alive = false pcall(function() alive = (ws ~= nil) and (ws.CurTilePos ~= nil) end) "
        "if not alive then p.why = 'not-in-world' %(gold)s = p return end "
        "local reach = math.floor(tonumber(%(gold)s_approach_reach) or 12) "
        "local best, bestsec = nil, direct "
        "local looked, mines = 0, 0 "
        "pcall(function() local pm = ws.PointManager "
        "for dx = -reach, reach do for dy = -reach, reach do "
        "local mx, my = t.x + dx, t.y + dy "
        "if mx >= 0 and my >= 0 then "
        "local pid = nil "
        "pcall(function() pid = ws:TilePosToIndex(CS.UnityEngine.Vector2Int(mx, my)) end) "
        "if pid ~= nil then looked = looked + 1 "
        "local has = false pcall(function() has = ws:HasPointInfo(pid) end) "
        "if has then local pi = nil pcall(function() pi = pm:GetPointInfo(pid) end) "
        "local kind, cls = nil, '' "
        "pcall(function() local pt = pi.pointType kind = tonumber(pt) "
        "if kind == nil then kind = tonumber(string.match(tostring(pt), '(%%d+)%%s*$')) end end) "
        "pcall(function() cls = tostring(pi:GetType().Name) end) "
        "if kind == %(mine)d or cls == 'ResPointInfo' then mines = mines + 1 "
        "local ride = _dist(pid, mx, my) / sc "
        "local hop = math.sqrt(dx * dx + dy * dy) / sa "
        "if (ride + hop) < bestsec then best = {pid = pid, x = mx, y = my} "
        "bestsec = ride + hop end end end end end end end end) "
        "if best == nil then p.why = 'no-mine' else "
        "p.approach = best p.approach_sec = math.floor(bestsec) p.why = 'planned' end "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_approach why="..tostring(p.why)'
        '.." direct="..tostring(math.floor(direct)).." via="..tostring(math.floor(bestsec))'
        '.." mines="..tostring(mines).." looked="..tostring(looked)'
        '.." at="..tostring(best and best.x)..","..tostring(best and best.y))'
        % {"gold": _GOLD, "mine": POINT_MINE}
    )


def golden_needs_district() -> str:
    """Lua *expression* -> 1 when a ride is worth looking for a mine for, else 0.

    The planner bails on the arithmetic — «short», «no-gain», «no-ride», «after-recall» —
    without touching the map, and only reaches the mine hunt when the haul is long enough
    to be worth one. `no-mine` therefore means «the sums say ride, and the client has not
    been shown that corner of the map»: exactly the case where flying the camera there and
    asking again is worth its three seconds.

    Measured (#1702): the flight ran on EVERY lap of a run with the ride switched on —
    twelve times in one run — and cost 2 s of button settle plus a second of waiting plus
    a scan, on hops of four and six tiles that the planner then dismissed as «short».
    """
    return ("(function() " + _GOLD_P +
            "return (tostring(p.why or '') == 'no-mine') and 1 or 0 end)()")


def golden_approach_planned() -> str:
    """Lua *expression* -> 1 when a ride has been planned for the armed target, else 0."""
    return ("(function() " + _GOLD_P +
            "return (p.approach ~= nil) and 1 or 0 end)()")


def golden_approach_send() -> str:
    """Send the squad at the mine on a GATHER order — the ride, not the ore.

    The same `SendCreateMarchMessage` every launch in this file uses, with
    `MarchTargetType.COLLECT` and `autoBackHome = 0` so the squad STAYS beside the target
    when it lands. Scheduled on the main thread, for the reason all of them are.

    The ride is free: `GetCostStaminaByTargetType(COLLECT)` is 0, so a plan that turns out
    to be impossible costs travel time and no energy.
    """
    return (
        _GOLD_P +
        "local a = p.approach "
        "if a == nil or p.formation == nil then error('nothing to ride to') end "
        "local srv = math.floor(tonumber(p.server) or 0) "
        "local f, pid = p.formation, a.pid "
        "TimerManager:GetInstance():DelayInvoke(function() "
        "local ok, err = pcall(function() "
        "MarchUtil.SendCreateMarchMessage(f, MarchTargetType.COLLECT, pid, 0, 1, 0, "
        "false, srv, nil) end) "
        'CS.UnityEngine.Debug.LogError("ACT golden_ride ok="..tostring(ok).." err="..tostring(err)) '
        "end, 0.5) "
        "p.rode = (tonumber(p.rode) or 0) + 1 "
        "p.anchor = {x = a.x, y = a.y, pid = a.pid} "
        # THE MARCHES THAT EXIST BEFORE THE RIDE (#1702), exactly as the attack send parks
        # them: the ride's own march is the one that appears against this set, and it is
        # the clock the wait afterwards must be on. Without it the wait falls back to «the
        # latest march we hold», which on the first lap of a run is another squad's rally.
        "p.march_before = {} "
        "pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() "
        "if ms == nil then return end "
        "for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) "
        "if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) "
        "if u ~= nil then p.march_before[u] = true end end end end) "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_ride scheduled pid="..tostring(pid)'
        '.." at="..tostring(a.x)..","..tostring(a.y).." saved="'
        '..tostring((tonumber(p.direct_sec) or 0) - (tonumber(p.approach_sec) or 0)).."s")'
        % {"gold": _GOLD}
    )


def golden_rode() -> str:
    """Lua *expression* -> how many rides this run has taken."""
    return "(function() " + _GOLD_P + "return math.floor(tonumber(p.rode) or 0) end)()"


def golden_approach_report() -> str:
    """Lua *expression* -> one line about the last plan, for the log and the panel."""
    return (
        "(function() " + _GOLD_P +
        "return 'why=' .. tostring(p.why or '-') .. "
        "' direct=' .. tostring(math.floor(tonumber(p.direct_sec) or 0)) .. "
        "' via=' .. tostring(math.floor(tonumber(p.approach_sec) or 0)) .. "
        "' rode=' .. tostring(math.floor(tonumber(p.rode) or 0)) .. "
        "' atk=' .. string.format('%.3f', tonumber(p.speed_atk) or 0) .. "
        "' col=' .. string.format('%.3f', tonumber(p.speed_col) or 0) end)()"
    )


#: The SERVER's clock in milliseconds, which is what a march's `endTime` is stamped in.
#: The PC's own clock is not it (docs/research/game-clock.md), so it is only the fallback
#: of last resort — a few seconds out either way is harmless for a wait, and being an
#: hour out is not.
_GAME_NOW_MS = (
    "(function() local t = nil "
    "pcall(function() t = tonumber(UITimeManager.Instance:GetServerTime()) end) "
    "if t == nil then pcall(function() "
    "t = tonumber(UITimeManager:GetInstance():GetServerTime()) end) end "
    "if t == nil then t = os.time() * 1000 end return t end)()"
)


def golden_note_eta() -> str:
    """Park when the march that has just gone out is due to land.

    **The squad's `state` cannot answer «has it arrived».** Measured live: a ride of 271
    seconds left the formation reading `state = 1` for 485 seconds and counting, because
    a squad that has landed at a mine is GATHERING and the client makes no distinction
    between «on the road» and «at work». A chain that waits for `state` to clear waits
    for ever.

    The march's own clock does answer. The newest of our marches is the one just created —
    it is the one that lands last — and its `endTime` is the server's own arrival stamp,
    within two seconds of what the speed function predicts. Where the list cannot be read
    the prediction is parked instead, so the wait is bounded either way.
    """
    return (
        _GOLD_P +
        "local latest, fresh, fresh_uuid = nil, nil, nil "
        "local seen = p.march_before or {} "
        "pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() "
        "if ms == nil then return end "
        "for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) "
        "if m ~= nil then local e, u = nil, nil "
        "pcall(function() e = tonumber(m.endTime) end) "
        "pcall(function() u = tostring(m.uuid) end) "
        "if e ~= nil and e > 0 then "
        "if u ~= nil and not seen[u] and (fresh == nil or e > fresh) then fresh = e fresh_uuid = u end "
        "if latest == nil or e > latest then latest = e end end end end end) "
        # THE MARCH THIS SEND MADE, when it can be told apart (#1702). «The latest of all
        # our marches» is another squad's rally or radar errand as often as not, and
        # waiting for that one is minutes of a chain spent standing still.
        "if fresh ~= nil then latest = fresh end "
        "p.march_uuid = fresh_uuid "
        "if latest == nil then "
        "local guess = tonumber(p.approach_sec) or 60 "
        "latest = (%(now)s) + math.floor(guess * 1000) end "
        "p.eta_ms = latest "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_eta in="'
        '..tostring(math.floor((latest - (%(now)s)) / 1000)).."s")'
        % {"gold": _GOLD, "now": _GAME_NOW_MS}
    )


def golden_march_in_flight() -> str:
    """Lua *expression* -> 1 while the march this hunt ordered is still on the map.

    **`canMarch` DOES NOT ANSWER THIS, and that is the whole reason this exists (#1702).**
    Measured live with the dev brick `dev/golden_squad_state.md` run against a squad that
    had just been sent at a zombie::

        squad2 state=1 canMarch=true soldiers=2631
        marches=1 [left=71s uuid=1000000000000000001 form=?]

    A march of ours in flight, and the formation still saying it may march — the flag is
    stale in both directions, which is why nothing gates on it any more. `golden_squad_free`
    reads `state` and `IsFree()` now; this asks the parked march uuid, which is exact.

    The march's own uuid answers it exactly: `golden_note_eta` parks the uuid of the
    march the send created, and this is 1 for as long as that uuid is still in our own
    march list. Nothing parked — the first lap, or a send that never became a march — is
    `0`, because there is nothing of ours to wait for.
    """
    return ("(function() " + _GOLD_P +
            "local want = p.march_uuid "
            "if want == nil then return 0 end "
            "local alive = 0 "
            "pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() "
            "if ms == nil then return end "
            "for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) "
            "if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) "
            "if u ~= nil and u == tostring(want) then alive = 1 end end end end) "
            "return alive end)()")


def golden_seen_live() -> str:
    """Lua *expression* -> how many golden zombies the client can name RIGHT NOW.

    Not the registry, which is what earlier sweeps saw: this asks the client about the
    ground it currently holds. The difference is the whole of «не работает от слова
    совсем» (#1702) — measured live on 2026-08-21, the queue held 83 rows and this
    answered **0**, because the invasion wave was not up and every row was a ghost of a
    zombie somebody had killed while we were elsewhere.
    """
    return ("(function() " + _GOLD_P + _GOLD_WS +
            "if ws == nil then return -1 end "
            "local n = 0 "
            "pcall(function() "
            "local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, "
            "CS.System.Int32)() "
            "for _, id in ipairs(p.ids or {%(cfg)d}) do pcall(function() ids:Add(id, 1) end) end "
            "local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, "
            "CS.UnityEngine.Vector2Int)() "
            "ws:GetMonsterListInArea(ws.CurTilePos, math.floor(tonumber(p.radius) or 2000), "
            "ids, res) "
            "local e = res:GetEnumerator() while e:MoveNext() do n = n + 1 end end) "
            "return n end)()" % {"cfg": 1030000})


def golden_forget_queue() -> str:
    """Throw the registry away — every row in it is a ghost, and rows cost picks.

    Only ever pressed when the client has just said it can see NONE (`golden_seen_live`).
    Keeping them would make the next lap spend its twelve picks proving one by one what
    one reading already said (#1702).
    """
    return (_GOLD_P + "p.targets = {} p.cur = nil p.pending = nil %(gold)s = p "
            'CS.UnityEngine.Debug.LogError("ACT golden_forget_queue")' % {"gold": _GOLD})


def golden_phantom_marches() -> str:
    """Lua *expression* -> how many of OUR OWN orders have no arrival time.

    `endTime = 0` beside a real `startTime` is a march the client drew and the server
    never confirmed — the squad painted mid-move, refusing every order after it, which
    is what «отряд застрял в текстурах» looks like in the data (#1702).

    **AND IT IS NOT THE ONLY MARCH WITHOUT A CLOCK, which is why this is narrow.**
    Measured live minutes after the first version shipped: a rally march of the player's
    own — `endTime = 0`, `targetUuid` pointing at the rally — sat in the same list. A
    blanket «recall everything with no clock» would have pulled the account out of its
    own alliance rallies. So only a march this hunt ordered counts: the uuid the send
    parked, or one aimed at the very zombie we are attacking.
    """
    return ("(function() " + _GOLD_P +
            "local want = p.march_uuid "
            "local tgt = nil if p.pending ~= nil then tgt = p.pending.uuid end "
            "if want == nil and tgt == nil then return 0 end "
            "local n = 0 "
            "pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() "
            "if ms == nil then return end "
            "for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) "
            "if m ~= nil then local e, u, t = nil, nil, nil "
            "pcall(function() e = tonumber(m.endTime) end) "
            "pcall(function() u = tostring(m.uuid) end) "
            "pcall(function() t = tostring(m.targetUuid) end) "
            "local ours = (want ~= nil and u == tostring(want)) "
            "or (tgt ~= nil and t ~= nil and t == tostring(tgt)) "
            "if ours and (e == nil or e <= 0) then n = n + 1 end end end end) "
            "return n end)()")


def golden_send_now() -> str:
    """Check and ORDER in one breath, so nothing sits between the two (#1702).

    The press used to ask five questions, get an answer, and only then send — and every
    one of those was a tenth of a second in which the world could change. Here the squad
    is resolved, the previous order forgotten, the target read and the march scheduled
    inside a single call, and the answer says what happened:

    * ``1``   — the order was scheduled at the fixed zombie;
    * ``0``   — the squad is out or refusing orders;
    * ``-1``  — no such squad on this account;
    * ``-2``  — the client holds no army for it (curable: ask, then press again);
    * ``-3``  — nothing is fixed;
    * ``-4``  — the client can no longer name that zombie: it is gone, and the order is
      NOT sent, because a march at a corpse is the one thing this whole task is about.

    The send itself is still `MarchUtil.SendCreateMarchMessage` on the main thread
    through `DelayInvoke` — a cold call from the hijack thread is dropped by the server
    (docs/research/world-monsters.md, Finding 17) — and `back = 1`, so a single press
    brings the squad home when it is done.
    """
    return (
        "(function() " + _GOLD_P + _GOLD_WS + _GOLD_FRESH_UUID +
        "p.squad = math.floor(tonumber(%(gold)s_squad) or p.squad or 1) "
        "p.formation = nil p.soldiers = 0 "
        "local can = nil "
        "pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if math.floor(tonumber(v.index) or -1) == p.squad then "
        "p.formation = v.uuid p.soldiers = math.floor(tonumber(v.totalSoldierNum) or 0) "
        "can = %(free)s(v) end end end) "
        # …the previous ORDER is forgotten, the CHOICE is kept: «отправил, развернул,
        # отправить снова» has to work.
        "p.pending = nil p.hit = nil p.judge = nil p.judgeq = {} p.crowd = nil p.march_uuid = nil p.misses = 0 "
        "if p.cur ~= nil and p.used ~= nil then p.used[tostring(p.cur.pid)] = nil end "
        "%(gold)s = p "
        "if p.formation == nil then return -1 end "
        "if p.cur == nil then return -3 end "
        # «NO ARMY» IS ASKED FIRST (#1702). A squad the client holds no soldiers for is
        # `state = 0` and `IsFree() = true` — free by every reading the game has — so
        # acting on «free» before counting the soldiers sends an EMPTY formation at a
        # zombie, which the server refuses in silence. The count is the only thing that
        # tells «the client has not fetched the army» from «the squad is idle».
        "if math.floor(tonumber(p.soldiers) or 0) <= 0 then return -2 end "
        "if not can then return 0 end "
        "local t = p.cur "
        "local uuid = _freshuuid(ws, p, t) "
        # …AND THE ROW GOES WITH IT (#1702). A zombie the client cannot name is one
        # somebody else has killed; leaving it in the registry means the next «найти»
        # offers the same empty tile, which is precisely what the operator hit.
        "if uuid == nil then "
        "local keep = {} "
        "for _, q in ipairs(p.targets or {}) do "
        "if tostring(q.pid) ~= tostring(t.pid) then keep[#keep + 1] = q end end "
        "p.targets = keep p.cur = nil DataCenter.__lw_gold = p "
        "return -4 end "
        "local srv = math.floor(tonumber(t.server or p.server) or 0) "
        "local kind = MarchTargetType.ATTACK_MONSTER "
        "if p.server ~= nil and srv ~= 0 and srv ~= p.server then "
        "kind = MarchTargetType.CROSS_ATTACK_MONSTER end "
        "local f, pid = p.formation, t.pid "
        "p.march_before = {} "
        "pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() "
        "if ms == nil then return end "
        "for i = 0, (ms.Count - 1) do local m = nil pcall(function() m = ms[i] end) "
        "if m ~= nil then local u = nil pcall(function() u = tostring(m.uuid) end) "
        "if u ~= nil then p.march_before[u] = true end end end end) "
        "p.pending = {pid = pid, uuid = uuid, key = tostring(uuid), x = t.x, y = t.y} "
        "p.hit = p.pending "
        "p.anchor = {x = t.x, y = t.y, pid = t.pid} "
        "p.last_sent = {x = t.x, y = t.y, pid = t.pid} "
        "p.attacks = p.attacks or 0 "
        "%(gold)s = p "
        "TimerManager:GetInstance():DelayInvoke(function() "
        "pcall(function() "
        "MarchUtil.SendCreateMarchMessage(f, kind, pid, uuid, 1, 1, false, srv, nil) end) "
        "end, 0.1) "
        "return 1 end)()"
        % {"gold": _GOLD, "free": _SQUAD_FREE})


def golden_ready_to_send() -> str:
    """Everything the attack press must know before it orders, in ONE call.

    Points the run at the squad the panel chose, forgets the previous ORDER while keeping
    the target, and answers whether an order may go at all:

    * ``1``   — a target is fixed and the squad can march;
    * ``0``   — the squad is out or otherwise refusing orders;
    * ``-1``  — this account has no such squad;
    * ``-2``  — the client is holding no army for it (that one has a cure);
    * ``-3``  — nothing is fixed; «найти ближайшего» has not been pressed.

    Numbers rather than words because the DSL's `IF` compares numbers and state words
    and nothing else — a condition on a quoted string is «unknown condition», which is
    how the first version of this died one line into a live press (#1702).

    Five round trips became one (#1702): «мгновенно» is mostly a matter of not asking
    the same VM five questions it could have answered in a single breath.
    """
    return (
        "(function() " + _GOLD_P +
        "p.squad = math.floor(tonumber(%(gold)s_squad) or p.squad or 1) "
        "p.formation = nil p.soldiers = 0 "
        "local state = nil local can = nil "
        "pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if math.floor(tonumber(v.index) or -1) == p.squad then "
        "p.formation = v.uuid p.soldiers = math.floor(tonumber(v.totalSoldierNum) or 0) "
        "state = math.floor(tonumber(v.state) or 0) can = %(free)s(v) end end end) "
        "p.pending = nil p.hit = nil p.judge = nil p.judgeq = {} p.crowd = nil p.march_uuid = nil p.misses = 0 "
        "if p.cur ~= nil and p.used ~= nil then p.used[tostring(p.cur.pid)] = nil end "
        "%(gold)s = p "
        "if p.formation == nil then return -2 end "
        "if p.cur == nil then return -3 end "
        "if math.floor(tonumber(p.soldiers) or 0) <= 0 then return -2 end "
        "if can then return 1 end "
        "return 0 end)()"
        % {"gold": _GOLD, "free": _SQUAD_FREE})


def golden_find_now() -> str:
    """Everything «Найти ближайшего» does, in ONE call, and it says what it found.

    A round trip to the game's VM costs about a tenth of a second, and the button was
    making fourteen of them — arm, armed?, origin, scan, look, moved?, scan, count,
    pick, picked?, where, report — with a fixed second of settling in the middle. Inside
    the VM the same work is free (`docs/research/alliance-tech.md`: a whole quota in one
    call), so it is one call now, and the only thing left costing real time is the
    camera when the squad is out and the client has to be shown that ground.

    Returns the report line the log prints, or `none:<n>` when nothing could be chosen —
    `n` being how many zombies the client can name from here, which is the difference
    between «the wave is out» and «they are all far away».
    """
    return (
        "(function() " + _GOLD_P + _GOLD_WS +
        "if ws == nil then return -1 end "
        # …the squad, its formation, and the origin — the same rules as the recipe had,
        # in the order they depend on each other.
        "p.squad = math.floor(tonumber(%(gold)s_squad) or p.squad or 1) "
        "p.formation = nil p.soldiers = 0 "
        "local out = 0 "
        "pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if math.floor(tonumber(v.index) or -1) == p.squad then "
        "p.formation = v.uuid p.soldiers = math.floor(tonumber(v.totalSoldierNum) or 0) "
        "if math.floor(tonumber(v.state) or 0) ~= 0 then out = 1 end end end end) "
        "if p.formation == nil then return 'nosquad' end "
        "if out == 1 then if p.anchor == nil then p.anchor = p.last_sent end "
        "else p.anchor = nil end "
        "if p.home == nil then p.home = DataCenter.__lw_gold_home end "
        "p.radius = math.floor(tonumber(%(gold)s_radius) or 2000) "
        "p.reach = 0 "
        "if p.targets == nil then p.targets = {} end "
        "if p.used == nil then p.used = {} end "
        "%(gold)s = p "
        "return out end)()"
        % {"gold": _GOLD})


def golden_confirm_current() -> str:
    """Ask the game about the CHOSEN zombie's own tile. 1 alive, 0 gone, -1 cannot tell.

    **The answer comes from the AREA LIST around that tile, and the three cases are told
    apart by what else is in it** (#1702). Measured with the camera parked exactly on a
    candidate:

        tile=874,895 holds=false camera=874,895 area_n=1

    `HasPointInfo` is false for a monster tile — point info is for resource nodes, bases
    and the like — so the obvious «does the client hold this ground» question cannot be
    asked that way, and the camera's own position does not answer it either (`CurTilePos`
    lags a jump). The list does: ask about a small box around the tile and

    * the zombie's own uuid is in it            → it is there, `1`;
    * something else is, but not it             → the client is holding that ground and
      the zombie is not on it, so it is gone, `0` — struck out, which is the only case
      THE_LIST_RULE (#1272) allows;
    * the box comes back empty                  → nothing is loaded there at all, `-1`,
      and the row is left exactly as it was.
    """
    return (
        "(function() " + _GOLD_P + _GOLD_WS +
        "local t = p.cur "
        "if t == nil or ws == nil then return -1 end "
        "local n, mine = 0, false "
        "local asked = pcall(function() "
        "local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, "
        "CS.System.Int32)() "
        "for _, id in ipairs(p.ids or {%(cfg)d}) do pcall(function() ids:Add(id, 1) end) end "
        "local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, "
        "CS.UnityEngine.Vector2Int)() "
        "ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 3, ids, res) "
        "local e = res:GetEnumerator() "
        "while e:MoveNext() do n = n + 1 "
        "if tostring(e.Current.Key) == tostring(t.key or t.uuid or 0) then mine = true end end end) "
        "if not asked then return -1 end "
        "if mine then t.at = os.time() t.seen = 1 %(gold)s = p return 1 end "
        # …AND «EMPTY BOX» IS TWO DIFFERENT THINGS (#1702). A three-tile box comes
        # back empty both when the district is not loaded and when it IS loaded and
        # simply has no zombie left on it. Asked wide — sixty tiles — the answer
        # separates them: anything at all in that circle means the client is holding
        # this part of the world, so the small box being empty is a death.
        "if n <= 0 then "
        "local wide = 0 "
        "pcall(function() "
        "local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, "
        "CS.System.Int32)() "
        "for _, id in ipairs(p.ids or {1030000}) do pcall(function() ids:Add(id, 1) end) end "
        "local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, "
        "CS.UnityEngine.Vector2Int)() "
        "ws:GetMonsterListInArea(CS.UnityEngine.Vector2Int(t.x, t.y), 60, ids, res) "
        "local e2 = res:GetEnumerator() while e2:MoveNext() do wide = wide + 1 end end) "
        "if wide <= 0 then return -1 end end "
        "local keep = {} "
        "for _, q in ipairs(p.targets or {}) do "
        "if tostring(q.pid) ~= tostring(t.pid) then keep[#keep + 1] = q end end "
        "p.targets = keep p.cur = nil p.reaped = (tonumber(p.reaped) or 0) + 1 "
        "%(gold)s = p "
        "return 0 end)()"
        % {"gold": _GOLD, "cfg": 1030000})


def golden_age_line() -> str:
    """Lua *expression* -> how old the chosen row is, and whether it was ever confirmed.

    «Реестр часовой давности это кладбище» — the invasion is farmed out in minutes, so
    a row's age is most of what says whether to believe it (#1702).
    """
    return ("(function() " + _GOLD_P +
            "local t = p.cur if t == nil then return 'no target' end "
            "local age = -1 "
            "if t.at ~= nil then age = math.floor(os.time() - tonumber(t.at)) end "
            "return 'age=' .. tostring(age) .. 's seen=' "
            ".. tostring(t.seen == 1) end)()")


def golden_pick_and_report() -> str:
    """Choose the nearest zombie the CLIENT STILL KNOWS, dropping the dead as it goes.

    One call: the arithmetic, the liveness check, the reaping of rows that no longer
    exist, the tile and the report line. Five round trips became one when this was
    written (#1702) — and the liveness check went missing with them, which the operator
    found within a day: «указал на пустое место… не хотел никак обновлять реестр».
    The same tile came back six presses in a row, because nothing ever struck it out.

    So each candidate is asked about before it is offered, nearest first, and a row the
    client cannot name is REMOVED from the registry and the next one tried — up to a
    dozen, which is enough to walk past a farmed-out corner without spending a second on
    it. A far candidate is taken on trust exactly as before: the client answers only for
    ground it is holding, so «not there» from forty tiles away means «not loaded», not
    «not alive» (the send re-checks it from close up).

    Comes back as `noneseen` (the client can see none at all), `nonenear` (it can see
    some, but none of them are in the registry any more) or `<tile>|<report>`.
    """
    return (
        "(function() " + _GOLD_P + _GOLD_WS + _GOLD_FRESH_UUID + _GOLD_OWN_MARCH +
        "if ws == nil then return 'noneseen' end "
        "p.cur = nil "
        "local ox, oy, from = nil, nil, 'oracle' "
        "local o0, o0name = _origin(p) "
        "if o0 ~= nil then ox, oy, from = o0.x, o0.y, o0name end "
        "local dropped = 0 "
        "local best, bestd = nil, nil "
        "for _try = 1, 12 do "
        "best, bestd = nil, nil "
        "for _, t in ipairs(p.targets or {}) do "
        "if not (p.used or {})[tostring(t.pid)] and _goldfree(p, t.pid) then "
        "local d = nil "
        "if ox ~= nil then local dx, dy = (t.x - ox), (t.y - oy) "
        "d = math.sqrt(dx * dx + dy * dy) "
        "else pcall(function() d = tonumber("
        "SceneUtils.TileDistanceToMyHome(t.pid, p.server)) end) end "
        "if d ~= nil and (bestd == nil or d < bestd) then best, bestd = t, d end end end "
        "if best == nil then break end "
        # …ASKED ABOUT BEFORE IT IS OFFERED. Far candidates are taken on trust: the
        # client answers only for the ground it holds, and «not there» from a district
        # it has evicted says nothing about the zombie.
        "local near = true "
        "pcall(function() local cx, cy = ws.CurTilePos.x, ws.CurTilePos.y "
        "local dx, dy = (best.x - cx), (best.y - cy) "
        "near = (math.sqrt(dx * dx + dy * dy) <= 40) end) "
        "if (not near) or _freshuuid(ws, p, best) ~= nil then break end "
        # …and a row the client cannot name is struck out, not shown again.
        "local keep = {} "
        "for _, t in ipairs(p.targets or {}) do "
        "if tostring(t.pid) ~= tostring(best.pid) then keep[#keep + 1] = t end end "
        "p.targets = keep dropped = dropped + 1 best = nil end "
        "if best == nil then "
        "local n = 0 "
        "pcall(function() "
        "local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32, "
        "CS.System.Int32)() "
        "for _, id in ipairs(p.ids or {%(cfg)d}) do pcall(function() ids:Add(id, 1) end) end "
        "local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, "
        "CS.UnityEngine.Vector2Int)() "
        "ws:GetMonsterListInArea(ws.CurTilePos, math.floor(tonumber(p.radius) or 2000), "
        "ids, res) "
        "local e = res:GetEnumerator() while e:MoveNext() do n = n + 1 end end) "
        "%(gold)s = p "
        "if n > 0 then return 'nonenear' end return 'noneseen' end "
        "p.cur = best p.curdist = math.floor(bestd + 0.5) p.curfrom = from "
        "%(gold)s = p "
        "local srv = math.floor(tonumber(best.server or p.server) or 0) "
        "local tile = 'X:' .. tostring(math.floor(best.x)) .. ' Y:' .. tostring(math.floor(best.y)) "
        "if srv > 0 then tile = '#' .. tostring(srv) .. ' ' .. tile end "
        "local hd = nil pcall(function() "
        "hd = tonumber(SceneUtils.TileDistanceToMyHome(best.pid, p.server)) end) "
        "local queued = 0 for _, t in ipairs(p.targets or {}) do "
        "if not (p.used or {})[tostring(t.pid)] then queued = queued + 1 end end "
        "return tile .. '|at=' .. tostring(best.x) .. ',' .. tostring(best.y) "
        ".. ' dist=' .. tostring(p.curdist) .. ' from=' .. from "
        ".. ' origin=' .. tostring(ox) .. ',' .. tostring(oy) "
        ".. ' home_dist=' .. tostring(hd and math.floor(hd + 0.5)) "
        ".. ' queued=' .. tostring(queued) .. ' dropped=' .. tostring(dropped) "
        # WHY THE ORIGIN CAME OUT AS IT DID (#1702). One word, on every lap, printed
        # where the pick is already being logged: `station`/`mine` mean the next order
        # is a redeploy, `nomarch` means the squad is home and the march starts there.
        # Without it «the redeploy never fires» is a guess about four different causes.
        ".. ' stand=' .. _stand(p) end)()"
        % {"gold": _GOLD, "cfg": 1030000})


def golden_clear_order() -> str:
    """Forget the LAST order, keeping the target — so the same zombie can be sent at again.

    «Отправил, развернул отряд, отправить снова» has to work (#1702). What stood in the
    way was the run's memory of the previous order: the march uuid it parked, the pending
    order it was proving, and — the one that actually blocks — the tile written into
    `used`, which is how the chain remembers not to walk back round its own kills. For a
    hand press none of that is wanted: the person is looking at the zombie and pressing
    attack again.

    The target itself is untouched, so this is «try that again», not «choose again».
    """
    return (_GOLD_P +
            "p.pending = nil p.hit = nil p.judge = nil p.judgeq = {} p.crowd = nil p.march_uuid = nil p.misses = 0 "
            "if p.cur ~= nil and p.used ~= nil then p.used[tostring(p.cur.pid)] = nil end "
            "%(gold)s = p "
            'CS.UnityEngine.Debug.LogError("ACT golden_clear_order")' % {"gold": _GOLD})


def golden_use_squad() -> str:
    """Point the run at the squad the PANEL has chosen, keeping the parked target.

    `golden_arm` builds the run's state from nothing, which is right at the start of a
    hunt and wrong for «Атаковать выбранного»: arming there would throw away the very
    zombie the person had just fixed with «Найти ближайшего» (#1702). This writes the
    slot and its formation and touches nothing else, so the squad can be changed on the
    tab between finding a target and attacking it — which is exactly what the operator
    asked for.

    Says what it resolved, because «which squad went» is the first question afterwards.
    """
    return (
        _GOLD_P +
        "p.squad = math.floor(tonumber(%(gold)s_squad) or p.squad or 1) "
        "p.formation = nil p.soldiers = 0 "
        "pcall(function() "
        "for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do "
        "if math.floor(tonumber(v.index) or -1) == p.squad then "
        "p.formation = v.uuid p.soldiers = math.floor(tonumber(v.totalSoldierNum) or 0) "
        "end end end) "
        "%(gold)s = p "
        'CS.UnityEngine.Debug.LogError("ACT golden_use_squad squad="..tostring(p.squad)'
        '.." formation="..tostring(p.formation).." soldiers="..tostring(p.soldiers))'
        % {"gold": _GOLD})


def golden_order_line() -> str:
    """Lua *expression* -> one line saying exactly what is about to be sent.

    The operator asked to see it: which squad, which formation, which tile, and which
    call. Printed BEFORE the order goes, so a refusal afterwards is read against what
    was actually asked for rather than against what somebody assumed (#1702).
    """
    return ("(function() " + _GOLD_P +
            "local c = p.cur "
            "local where = 'none' "
            "if c ~= nil then local srv = math.floor(tonumber(c.server or p.server) or 0) "
            "where = '#' .. tostring(srv) .. ' X:' .. tostring(math.floor(tonumber(c.x) or 0)) "
            ".. ' Y:' .. tostring(math.floor(tonumber(c.y) or 0)) "
            ".. ' pid=' .. tostring(c.pid) end "
            "return 'squad=' .. tostring(p.squad) "
            ".. ' formation=' .. tostring(p.formation) "
            ".. ' soldiers=' .. tostring(math.floor(tonumber(p.soldiers) or 0)) "
            ".. ' target=' .. where "
            ".. ' call=SendCreateMarchMessage/ATTACK_MONSTER' end)()")


def golden_forget_target() -> str:
    """Let the chosen zombie go — the parked target and nothing else (#1702).

    The registry is left alone: forgetting WHICH one was chosen is not forgetting that
    the map has zombies on it. After this «Атаковать выбранного» has nothing to send at
    and says so, which is the whole point of the button — a person who has changed their
    mind should not have to press «attack» to find out that the panel had not.
    """
    return (_GOLD_P + "p.cur = nil p.pending = nil p.hit = nil %(gold)s = p "
            'CS.UnityEngine.Debug.LogError("ACT golden_forget_target")' % {"gold": _GOLD})


def golden_stall_mark() -> str:
    """Say that this lap could not get an order out — WITHOUT ending the run (#1702).

    A streak of sends that never became marches used to end the hunt outright, and
    measured over a whole morning that is the ONE thing that ended almost every run:
    19 kills in 38 minutes and then «several sends in a row went nowhere», with 7 505
    energy still in the purse. What it actually means is that the corner the squad is
    standing in has been farmed out — a fact about the map five minutes from now, not
    about the client — so the chain marks it and the caller decides.
    """
    return (_GOLD_P + "p.stalled = 1 %(gold)s = p "
            'CS.UnityEngine.Debug.LogError("ACT golden_stall_mark misses="'
            '..tostring(math.floor(tonumber(p.misses) or 0)))' % {"gold": _GOLD})


def golden_stalled() -> str:
    """Lua *expression* -> 1 when the last lap could not get an order out."""
    return ("(function() " + _GOLD_P +
            "return (p.stalled == 1) and 1 or 0 end)()")


def golden_breathe() -> str:
    """Take the stall back and count the pause — the chain is going to look again.

    Everything a stall leaves behind is cleared: the miss streak, the half-armed target,
    the order that was never taken. What is NOT cleared is the list of targets already
    used, so a breather does not send the hunt back round tiles it has already cleared.
    """
    return (_GOLD_P +
            "p.stalled = nil p.misses = 0 p.cur = nil p.pending = nil "
            "p.breathers = (tonumber(p.breathers) or 0) + 1 "
            "p.dry = (tonumber(p.dry) or 0) + 1 "
            "if (tonumber(p.dry) or 0) >= 3 then "
            "local far = math.floor(tonumber(p.reach_far) or 0) "
            "if far > 0 then p.reach = far end end "
            "%(gold)s = p "
            'CS.UnityEngine.Debug.LogError("ACT golden_breathe n="'
            '..tostring(math.floor(tonumber(p.breathers) or 0)))' % {"gold": _GOLD})


def golden_breathers_left() -> str:
    """Lua *expression* -> how many pauses this run may still take.

    A bound rather than a licence: a client that has genuinely gone deaf refuses every
    order for ever, and a hunt that waits for ever in front of one is the bug this whole
    task started from. Thirty pauses of a minute and a half is a couple of hours of
    hunting; past that something is wrong that waiting will not mend.
    """
    return ("(function() " + _GOLD_P +
            "local lim = math.floor(tonumber(p.breather_limit) or 0) "
            "if lim <= 0 then return 0 end "
            "local used = math.floor(tonumber(p.breathers) or 0) "
            "local left = lim - used if left < 0 then left = 0 end "
            "return left end)()")


def golden_arrived() -> str:
    """Lua *expression* -> 1 once the parked march is due to have landed, else 0.

    `1` when nothing is parked, so a caller that polls this after a step which sent
    nothing is not left waiting on a clock nobody wound.
    """
    return ("(function() " + _GOLD_P +
            "local due = tonumber(p.eta_ms) if due == nil then return 1 end "
            "return ((%s) >= due) and 1 or 0 end)()" % _GAME_NOW_MS)


# --------------------------------------------------------------------------
# The secret command post: refreshing the day's own tasks, and sending the
# squads out in one press (#1903)
# --------------------------------------------------------------------------
# THREE ABILITIES OVER ONE WINDOW, and the prices are the reason they are here rather
# than headless. Measured live before a line of this was written:
#
#   * an ordinary refresh costs ONE «Секретный приказ» — item `refresh_item`
#     (`GetDispatchSetting`), and the window's own button says so: `refreshBtn` carries
#     `item/itemCount = "<have>/<cost>"`. When the items run out the same press asks for
#     DIAMONDS instead, at `GetTaskRefreshSetting()` each.
#   * the mega refresh costs a HANDFUL of the same item — twenty of them against five
#     non-UR tasks on the reading this was written from — and the number is not in any
#     getter: it is drawn in the confirm dialog the button raises
#     (`UIDispatchTaskRefreshConfirm`, `item_1/clickBtn/NumText`). So the cost is READ
#     from the dialog and the dialog is closed unpressed when the rule says no.
#   * `GetTaskSuperRefreshSetting()` is NOT a price. It answers the same number as
#     `GetDispatchSetting('refresh_item')` — an item id — and reading it as diamonds is
#     how a plan ends up spending 1 520 002 of them.
#
# AND THAT IS WHY THESE PRESS THE GAME'S OWN BUTTONS. `hero.dispatch.refresh` carries a
# `costType` whose values are not written down anywhere we can read, so building the
# frame by hand is a guess between «spend a ticket» and «spend diamonds» — a guess the
# player pays for. The window's button already knows which the player can afford, raises
# the diamond dialog only when the tickets are gone, and picks the heroes for the batch
# dispatch (`UIDispatchTaskSuperPopup` fills every task's squad by itself). Pressing it
# is the cheap, honest version of all three.

#: `tonumber` IS NOT SAFE ON THIS CLIENT, and finding that out cost an afternoon
#: (#1903). The game's Lua hardens it: `tonumber(v)` where `v` is already a number
#: RAISES — «bad argument #1 to 'tonumber' (string expected, got number)» — measured on
#: `GetTaskRefreshSetting()`, which answers a plain `100` of type `number` and blows up
#: the moment it is handed to `tonumber`. Inside a `pcall`, which is where every read in
#: this file lives, that failure is SILENT: the local keeps its default and the recipe
#: reports «price 0», i.e. «free», about a press that costs diamonds.
#:
#: So every number that comes back from the game goes through this instead: arithmetic
#: first (`v + 0`, which works on both), `tonumber` only as the fallback for a genuine
#: string, and zero when neither answers.
_NUM = ("local function _num(v) if v==nil then return 0 end "
        "local ok,n=pcall(function() return v+0 end) if ok and n~=nil then return n end "
        "ok,n=pcall(function() return tonumber(v) end) if ok and n~=nil then return n end "
        "return 0 end ")

#: WHAT THE MEGA REFRESH REALLY COSTS, per idle non-UR task it would improve (#1903).
#: Measured three times on two accounts — 20 orders for five tasks, 12 for three, and a
#: third mega that wanted 12 for three while the bag held 2 and the game silently took
#: the missing ten in diamonds. The dialog's item row shows what will come out of the
#: BAG, not what the refresh costs, so this is what the gate is judged on.
MEGA_ITEMS_PER_TASK = 4

#: The window every press below lives in.
_POST_WIN = "UIWindowNames.UIDispatchTaskMain"

#: Fetch a window's root GameObject. `w.gameObject` answers on a window that has
#: finished loading and `nil` on one that has not — the view underneath it answers
#: either way, and a probe that skipped the fallback read «no go» about a window that
#: was plainly on screen.
_UI_ROOT = (
    "local function _root(n) local w=UIManager.Instance:GetWindow(n) "
    "if not w then return nil end local go=nil "
    "pcall(function() go=w.gameObject end) "
    "if go==nil then pcall(function() go=w.View.gameObject end) end "
    "return go end ")

#: Press a button by the NAME of its own transform, anywhere under a root. Inactive
#: nodes included on purpose: the «мега» pair lives in a panel that is only shown after
#: another press, and invoking the handler works whether or not it is on screen.
_UI_PRESS = (
    "local function _press(root,name) if root==nil then return false end "
    "local trs=root:GetComponentsInChildren(typeof(CS.UnityEngine.RectTransform),true) "
    "for i=0,trs.Length-1 do if tostring(trs[i].name)==name then "
    "local b=trs[i]:GetComponent(typeof(CS.UnityEngine.UI.Button)) "
    "if b~=nil then b.onClick:Invoke() return true end end end return false end ")

#: The first text under a root whose path matches, with the whitespace squeezed out.
_UI_TEXT = (
    "local function _text(root,want) if root==nil then return nil end "
    "local cs={} local a=root:GetComponentsInChildren(typeof(CS.TMPro.TextMeshProUGUI),true) "
    "for i=0,a.Length-1 do cs[#cs+1]=a[i] end "
    "local b=root:GetComponentsInChildren(typeof(CS.UnityEngine.UI.Text),true) "
    "for i=0,b.Length-1 do cs[#cs+1]=b[i] end "
    "for _,c in ipairs(cs) do local p='' local tr=c.transform local d=0 "
    "while tr and d<4 do p=tr.name..'/'..p tr=tr.parent d=d+1 end "
    "if p:find(want,1,true) then local t=tostring(c.text) "
    "if t~='' then return (t:gsub('%s+','')) end end end return nil end ")

#: The item an ordinary refresh is paid for in — asked of the game, never spelled out.
_REFRESH_ITEM = ("(function() local ok,v=pcall(function() "
                 "return DataCenter.ActDispatchTaskDataManager:GetDispatchSetting('refresh_item') end) "
                 "local n=0 if ok and v~=nil then pcall(function() n=v+0 end) end "
                 "return n end)()")

#: One walk over the player's OWN tasks plus the two purses that pay for a refresh.
#:
#: `color` is the quality, off the task's config row rather than off its `cfgId` — the
#: digits of the id lie about the level and say nothing about the rarity. UR reads as 5
#: on the live client, and anything ABOVE it is treated as UR too: a rarity nobody has
#: seen yet must not read as «not UR» and get re-rolled away.
#:
#: A task with a `completionTime` is out on its errand. Those are the ones the mega
#: refresh skips and the ones the batch dispatch has nothing to send, so every count
#: here is about the IDLE ones — which is also how the person reading the panel counts
#: them («считать только свободные задания»).
_POST_SCAN = (
    _NUM +
    "local M=DataCenter.ActDispatchTaskDataManager "
    "local idle,nonur,ur,run,done=0,0,0,0,0 "
    "local srvnow=0 pcall(function() srvnow=math.floor(_num(UITimeManager:GetInstance():GetServerSeconds())) end) "
    "local ok,tasks=pcall(function() return M:GetAllSingleTasks() end) "
    "if ok and type(tasks)=='table' then for _,v in pairs(tasks) do "
    "local col=0 pcall(function() col=_num(v.cfg:getValue('color')) end) "
    "local ct=_num(v.completionTime) "
    "if ct>0 then if math.floor(ct/1000)<=srvnow and srvnow>0 then done=done+1 "
    "else run=run+1 end else idle=idle+1 "
    "if col>=5 then ur=ur+1 else nonur=nonur+1 end end end end "
    "local item=" + _REFRESH_ITEM + " local tickets=0 "
    "pcall(function() for _,s in pairs(DataCenter.ItemData.ItemInfos or {}) do "
    "if _num(s.itemId)==item then tickets=tickets+_num(s.count) end end end) "
    "local gold=0 pcall(function() gold=_num(LuaEntry.Player.gold) end) "
    "local price=0 pcall(function() price=_num(M:GetTaskRefreshSetting()) end) "
    "local superopen=0 pcall(function() if M:CheckSuperRefreshOpen() then superopen=1 end end) "
    "local free=0 pcall(function() free=_num(M:GetSingleTaskNormalCount()) end) "
    "local ing=0 pcall(function() ing=_num(M:GetSingleTaskIngCount()) end) "
    "local maxm=0 pcall(function() maxm=math.floor(_num(M:GetMaxMarch())) end) "
    "local now=srvnow "
    "local nextfree=0 "
    "if ok and type(tasks)=='table' and now>0 then for _,v in pairs(tasks) do "
    "local ct=math.floor(_num(v.completionTime)/1000) "
    "if ct>now then local d=ct-now if nextfree==0 or d<nextfree then nextfree=d end end end end ")

#: How many diamonds this run is still allowed to spend: the budget it was armed with,
#: less what the purse has actually gone down by. Read off the PURSE rather than counted
#: in the recipe, because a press that raised a dialog and was cancelled spends nothing
#: and a tally kept by hand would have charged for it anyway.
_GOLD_LEFT = (
    "local budget=tonumber(M.__lw_ref_budget) or 0 "
    "local gold0=tonumber(M.__lw_ref_gold0) or gold "
    "local spent=gold0-gold if spent<0 then spent=0 end "
    "local goldleft=budget-spent if goldleft<0 then goldleft=0 end "
    "if (tonumber(M.__lw_ref_gold) or 0)==0 then goldleft=0 end ")


def secret_post_arm(keep: int = 3, use_gold: int = 1, budget: int = 1200) -> str:
    """Park the rule the presses below read, and stamp the purse the budget is measured from.

    `TAP` takes no arguments, so the three numbers a person can change — the non-UR
    threshold, whether diamonds may be spent at all, and how many of them — travel here
    and the presses read them back. The purse is stamped at the same moment: everything
    the run is allowed to spend is «what the wallet has gone down by since this line»,
    which costs nothing to keep true and cannot over-charge for a dialog that was
    cancelled.
    """
    return ("pcall(function() " + _NUM + "local M=DataCenter.ActDispatchTaskDataManager "
            "M.__lw_ref_keep=" + str(int(keep)) + " "
            "M.__lw_ref_gold=" + str(int(use_gold)) + " "
            "M.__lw_ref_budget=" + str(int(budget)) + " "
            "M.__lw_ref_mega_cost=-1 M.__lw_ref_mega_tasks=0 "
            "local g=0 pcall(function() g=_num(LuaEntry.Player.gold) end) "
            "M.__lw_ref_gold0=g end)")


def secret_post_scan() -> str:
    """Walk the own-task list once and park every number the recipe branches on.

    A snapshot rather than nine separate reads, for the reason
    :func:`secret_task_assist_scan` gives: a task that finishes between two of them
    would otherwise be counted as idle by one question and as running by the next.
    """
    return ("pcall(function() " + _POST_SCAN + _GOLD_LEFT +
            "M.__lw_ref_idle=idle M.__lw_ref_nonur=nonur M.__lw_ref_ur=ur "
            "M.__lw_ref_run=run M.__lw_ref_tickets=tickets M.__lw_ref_goldnow=gold "
            "M.__lw_ref_price=price M.__lw_ref_super=superopen M.__lw_ref_free=free "
            "M.__lw_ref_ing=ing M.__lw_ref_march=maxm M.__lw_ref_goldleft=goldleft "
            "M.__lw_ref_nextfree=nextfree M.__lw_ref_done=done "
            'CS.UnityEngine.Debug.LogError("ACT post_scan idle="..tostring(idle)'
            '.." nonur="..tostring(nonur).." ur="..tostring(ur).." run="..tostring(run)'
            '.." tickets="..tostring(tickets).." price="..tostring(price)'
            '.." goldleft="..tostring(goldleft).." march="..tostring(ing).."/"..tostring(maxm)'
            '.." done="..tostring(done).." nextfree="..tostring(nextfree)) end)')


def secret_post_open() -> str:
    """Open «Секретный командный пункт» — the window all three presses live in.

    IDEMPOTENT SINCE #2606, and that is the whole of it: `OpenWindow` on a window that
    is already up re-runs the open, so a refresh cycle asking for it once a ticket made
    the post visibly re-appear on every press — «модалка обновляется, как будто каждый
    раз открываем вкладку». Asking whether it is open first costs one call and leaves
    the screen still; the window ends in exactly the same state either way, so no gate
    and no press below changes.
    """
    return ("pcall(function() local mgr=UIManager.Instance "
            "local ok,open=pcall(function() return mgr:IsWindowOpen(" + _POST_WIN + ") end) "
            "if ok and open then return end "
            "mgr:OpenWindow(" + _POST_WIN + ") end)")


def secret_post_close() -> str:
    """Close the command post, and any dialog of its own still standing."""
    return ("pcall(function() local mgr=UIManager.Instance "
            "for _,n in ipairs({UIWindowNames.UIDispatchTaskRefreshConfirm, "
            "UIWindowNames.UIDispatchTaskSuperPopup, " + _POST_WIN + "}) do "
            "local ok,open=pcall(function() return mgr:IsWindowOpen(n) end) "
            "if ok and open then local w=mgr:GetWindow(n) "
            "if w and w.Ctrl and w.Ctrl.CloseSelf then pcall(function() w.Ctrl:CloseSelf() end) end "
            "end end end)")


def secret_post_refreshes_left() -> str:
    """Lua *expression* -> 1 while an ordinary refresh is still owed, else 0.

    The button's `count_lua`, re-read by `xall` between presses, and the whole of the
    rule's first half in one place:

      * nothing at all while the idle non-UR tasks are already down to the threshold;
      * a ticket pays for the next one whenever there is a ticket;
      * otherwise diamonds, and only while the run is allowed to spend them AND the
        budget still covers one at the game's own price.

    One rather than a count, exactly like the robbery's: a refresh re-rolls the idle
    tasks and how many come back non-UR is the server's business, so «how many more
    presses» cannot be known in advance and each press is decided on what the last one
    actually did.
    """
    return ("(function() " + _POST_SCAN + _GOLD_LEFT +
            "local keep=tonumber(M.__lw_ref_keep) or 0 "
            "if ur>0 then return 0 end "
            "if nonur<=keep then return 0 end "
            "if tickets>0 then return 1 end "
            "if price>0 and goldleft>=price then return 1 end "
            "return 0 end)()")


def secret_post_refresh_press() -> str:
    """Press the window's own «Обновить» — and answer the dialog the LAST press raised.

    Two jobs in one chunk because `xall` cannot interleave two buttons: when the tickets
    run out the game does not refresh, it raises a cost dialog, and the answer to that
    dialog is the next thing that has to happen. So a press that finds one standing
    settles it first — confirmed while the rule still allows diamonds, cancelled the
    moment it does not — and presses «Обновить» only on a clear screen.

    Nothing here decides what is SPENT: the game's own button pays with a ticket while
    there is one and asks about diamonds when there is not, which is the whole reason
    this is a press rather than a `hero.dispatch.refresh` built by hand.
    """
    return ("pcall(function() " + _UI_ROOT + _UI_PRESS + _POST_SCAN + _GOLD_LEFT +
            "local mgr=UIManager.Instance "
            "for _,n in ipairs({UIWindowNames.UICommonConfirm, UIWindowNames.CommonTipConfirm}) do "
            "local ok,open=pcall(function() return mgr:IsWindowOpen(n) end) "
            "if ok and open then local r=_root(n) "
            "local allow=(goldleft>=price and price>0) "
            "local hit=false "
            "if allow then hit=_press(r,'ConfirmBtn') or _press(r,'confirmBtn') or _press(r,'BtnConfirm') end "
            "if not hit then local w=mgr:GetWindow(n) "
            "if w and w.Ctrl and w.Ctrl.CloseSelf then pcall(function() w.Ctrl:CloseSelf() end) end end "
            'CS.UnityEngine.Debug.LogError("ACT post_cost dialog=1 paid="..tostring(hit and 1 or 0)) '
            "return end end "
            "local root=_root(" + _POST_WIN + ") "
            "local hit=_press(root,'refreshBtn') "
            'CS.UnityEngine.Debug.LogError("ACT post_refresh pressed="..tostring(hit and 1 or 0)'
            '.." nonur="..tostring(nonur).." tickets="..tostring(tickets)) end)')


def secret_post_mega_open() -> str:
    """Press «Мега Обновление» — which raises its confirm dialog and sends NOTHING.

    The dialog is where the send lives (`hero.dispatch.refresh` with `isSuper`), so this
    is the safe half: it is how the price is found out at all, and the recipe decides
    afterwards whether to confirm it or close it unpressed.
    """
    return ("pcall(function() " + _UI_ROOT + _UI_PRESS +
            "local hit=_press(_root(" + _POST_WIN + "),'superRefreshBtn') "
            'CS.UnityEngine.Debug.LogError("ACT post_mega_open pressed="..tostring(hit and 1 or 0)) end)')
def secret_post_mega_read() -> str:
    """Read what the mega refresh would cost, and whether the rule lets it be paid.

    Both numbers are DRAWN and not stored: the cost is the item count under the dialog's
    own cost row and the task count is the number inside its sentence. That is the whole
    reason this step exists — no getter on the dispatch manager answers either, and the
    one that looks as though it does (`GetTaskSuperRefreshSetting`) answers an item id.

    The VERDICT is parked beside them rather than left to the recipe: the rule is
    arithmetic over two purses, and a recipe asking three more questions to do it itself
    would be answering about a moment that had already passed.

    Parks `-1` for the cost when the dialog is not up, so a recipe that reads it without
    having opened one does not read «free» — and an unread cost is never affordable.
    """
    return ("pcall(function() " + _UI_ROOT + _UI_TEXT + _POST_SCAN + _GOLD_LEFT +
            "local r=_root(UIWindowNames.UIDispatchTaskRefreshConfirm) "
            "local cost=-1 local tasks=0 "
            "if r~=nil then local n=_text(r,'NumText') "
            "if n~=nil then cost=tonumber((n:gsub('[^%d]',''))) or -1 end "
            "local tip=_text(r,'TipText') "
            "if tip~=nil then local d=tip:match('<b>(%d+)</b>') or tip:match('(%d+)') "
            "tasks=tonumber(d) or 0 end end "
            # THE DIALOG'S ITEM ROW IS NOT THE PRICE, and finding that out cost a
            # thousand diamonds (#1903, live on a second account). With twelve orders
            # wanted and two in the bag, the row read `2` — what will be TAKEN FROM THE
            # BAG — and the game topped the missing ten up with diamonds by itself:
            # tickets 2 -> 0 and the purse 32 921 -> 31 921, exactly ten at the ordinary
            # hundred. Nothing in the recipe had allowed a diamond.
            #
            # So the reading is kept (it is what the dialog says) and the GATE is judged
            # on the larger of it and what the price is known to scale to — four orders
            # per idle non-UR task, measured three times: 20 for five, 12 for three, and
            # the twelve this run paid for three. A gate that trusts the smaller number
            # is a gate that spends a purse it was told not to touch.
            "local want=cost local scale=nonur*" + str(MEGA_ITEMS_PER_TASK) + " "
            "if tasks>0 then scale=tasks*" + str(MEGA_ITEMS_PER_TASK) + " end "
            "if scale>want then want=scale end "
            # THE CEILING IS ON THE WHOLE PRICE, NOT ON WHAT IS LEFT OF THE GRIND, and a
            # MIXED payment is the ordinary case rather than a mistake: orders as far as
            # they go, diamonds for the rest. The operator's rule in their own words —
            # «1200 — это нормальный прайс; если мега с билетами требует 1200 или меньше,
            # можно смело соглашаться». So the run's own diamond meter (`goldleft`, which
            # the ordinary refreshes spend against) does NOT narrow this decision: a mega
            # that fits under the cap is taken even late in a run.
            "local cap=tonumber(M.__lw_ref_budget) or 0 "
            "if (tonumber(M.__lw_ref_gold) or 0)==0 then cap=0 end "
            "local need=0 local okpay=0 "
            "if cost>=0 then if tickets>=want then okpay=1 "
            "elseif price>0 then need=(want-tickets)*price "
            "if need<=cap then okpay=1 end end end "
            "M.__lw_ref_mega_cost=cost M.__lw_ref_mega_want=want M.__lw_ref_mega_tasks=tasks "
            "M.__lw_ref_mega_ok=okpay M.__lw_ref_mega_gold=need "
            "M.__lw_ref_mega_cap=cap M.__lw_ref_mega_gold0=gold "
            'CS.UnityEngine.Debug.LogError("ACT post_mega_cost cost="..tostring(cost)'
            '.." want="..tostring(want).." tasks="..tostring(tasks)'
            '.." ok="..tostring(okpay).." gold="..tostring(need)'
            '.." cap="..tostring(cap)) end)')


def secret_post_mega_confirm() -> str:
    """Press the confirm dialog's «Подтвердить» — this is the press that spends."""
    return ("pcall(function() " + _UI_ROOT + _UI_PRESS +
            "local hit=_press(_root(UIWindowNames.UIDispatchTaskRefreshConfirm),'ConfirmBtn') "
            'CS.UnityEngine.Debug.LogError("ACT post_mega_done pressed="..tostring(hit and 1 or 0)) end)')


def secret_post_mega_cancel() -> str:
    """Close the confirm dialog unpressed — the answer when the rule says no."""
    return ("pcall(function() local mgr=UIManager.Instance "
            "local n=UIWindowNames.UIDispatchTaskRefreshConfirm "
            "local ok,open=pcall(function() return mgr:IsWindowOpen(n) end) "
            "if ok and open then local w=mgr:GetWindow(n) "
            "if w and w.Ctrl and w.Ctrl.CloseSelf then pcall(function() w.Ctrl:CloseSelf() end) end end "
            "DataCenter.ActDispatchTaskDataManager.__lw_ref_mega_cost=-1 end)")


def secret_post_dispatch_open() -> str:
    """Press «Мега развертывание» — the popup that fills every idle task's squad.

    Nothing is sent yet: the popup picks the heroes (measured live — it arrives with a
    squad already on every task) and its own confirm is what fires
    `hero.dispatch.batch.start`. Choosing the heroes is exactly the part a hand-built
    frame would have to invent, which is why the batch dispatch is a press too.
    """
    return ("pcall(function() " + _UI_ROOT + _UI_PRESS +
            "local hit=_press(_root(" + _POST_WIN + "),'superDispatchBtn') "
            'CS.UnityEngine.Debug.LogError("ACT post_send_open pressed="..tostring(hit and 1 or 0)) end)')


def secret_post_dispatch_confirm() -> str:
    """Confirm the batch dispatch — but only after reading what is about to go (#2022).

    THE VERDICT IS ASKED AT THE MOMENT OF THE PRESS, and it is asked HERE rather than in
    the recipe. That is the shape the ghost robbery arrived at (#2010,
    :func:`ghost_recon_steal_press`): a press that decides for itself cannot be sent
    wrong by a caller that forgot a gate, and a run that took nothing can be read off the
    stream afterwards. The recipe still asks its own questions first — it wants to close
    the popup politely and say why — but the guard does not depend on it having done so.

    What is refused, when `__lw_ref_onlyur_want` is 1 (the rule «только UR», on by
    default):

    * `no_popup` — the popup is not there, or its view cannot be walked. An unreadable
      popup is never confirmed: «отправить, наверное, правильное» is exactly the
      failure this exists to stop.
    * `filter_off` — the game's own «только UR» toggle reads OFF. Whatever the caller
      believes it set, this is what the game says now.
    * `rarity_unreadable` — a SELECTED row whose rarity could not be read at all. Said
      apart from `cheap_selected` because the two want opposite fixes: one is the game
      offering something the rule does not want, the other is this code not recognising
      the field it reads.
    * `cheap_selected` — a selected row below UR. `color` 5 is UR and anything above it
      counts as UR too; the `cfgId` digits say nothing about rarity and are not looked
      at (the level and the star live in the config as well, and are logged beside it).
    * `more_than_ur` — more rows selected than there are idle UR tasks standing. The
      cross-check that needs no field name at all: whatever a row turns out to be
      called, there cannot be more UR sent than there are UR. Skipped when nothing has
      scanned the post yet, because «no reading» is not «zero».

    And whatever happens, the rows are NAMED first — index, rarity, level, star — so a
    run says what it sent rather than how many. That is the other half of #2010's
    lesson: the blind runs became diagnosable the moment the press started saying its
    verdicts out loud.

    The camera follows a real send: the game's own handler closes the popup and moves
    the world view onto the tasks' point. Nothing here can prevent that — it is what the
    button does — so a recipe that runs this says so out loud.
    """
    return ("pcall(function() " + _UI_ROOT + _UI_PRESS + _NUM +
            "local M=DataCenter.ActDispatchTaskDataManager "
            "local want=tonumber(M.__lw_ref_onlyur_want) if want==nil then want=1 end "
            "local function refuse(why) M.__lw_ref_sent=-1 "
            'CS.UnityEngine.Debug.LogError("ACT post_send_refused why="..tostring(why)) end '
            "local w=UIManager.Instance:GetWindow(UIWindowNames.UIDispatchTaskSuperPopup) "
            "if w==nil or type(w.View)~='table' then refuse('no_popup') return end "
            "local v=w.View "
            "local onlyur=0 local t=v.toggleOnlySelectUR "
            "if t~=nil then local u=t.unity_uitoggle "
            "if u~=nil then pcall(function() if u.isOn then onlyur=1 end end) end end "
            "if onlyur==0 then pcall(function() if v.isOnlySelectUR then onlyur=1 end end) end "
            "local rows,picked,cheap,unread=0,0,0,0 local said={} "
            "for _,d in pairs(v.datas or {}) do rows=rows+1 "
            "if d.selected then picked=picked+1 "
            "local cfg=nil pcall(function() cfg=d.taskInfo.cfg end) "
            "if cfg==nil then pcall(function() cfg=d.cfg end) end "
            "local col,lvl,star=-1,-1,0 "
            "if cfg~=nil then pcall(function() col=_num(cfg:getValue('color')) end) "
            "pcall(function() lvl=_num(cfg:getValue('level')) end) "
            "pcall(function() star=_num(cfg:getValue('is_special')) end) end "
            "if col<0 then unread=unread+1 end "
            "if col<5 then cheap=cheap+1 end "
            "said[#said+1]='#'..tostring(rows)..'/col'..tostring(col)"
            "..'/lvl'..tostring(lvl)..(star>0 and '/star' or '') "
            "end end "
            # NAMED BEFORE JUDGED, so a refusal and a send are read the same way.
            'CS.UnityEngine.Debug.LogError("ACT post_send_rows rows="..tostring(rows)'
            '.." picked="..tostring(picked).." only_ur="..tostring(onlyur)'
            '.." cheap="..tostring(cheap).." unread="..tostring(unread)'
            '.." want_only_ur="..tostring(want)'
            '.." rows_selected=["..table.concat(said,",").."]") '
            "if picked<=0 then refuse('nothing_selected') return end "
            "if want==1 then "
            "if onlyur==0 then refuse('filter_off') return end "
            "if unread>0 then refuse('rarity_unreadable') return end "
            "if cheap>0 then refuse('cheap_selected') return end "
            # «No reading» is not «zero»: a post nobody has scanned has no `__lw_ref_ur`
            # at all, and refusing on that would be refusing on ignorance.
            "local idleur=tonumber(M.__lw_ref_ur) "
            "if idleur~=nil and picked>idleur then refuse('more_than_ur') return end "
            "end "
            "local r=_root(UIWindowNames.UIDispatchTaskSuperPopup) "
            "local hit=_press(r,'ConfirmBtn') or _press(r,'confirmBtn') "
            "M.__lw_ref_sent=(hit and picked or 0) "
            'CS.UnityEngine.Debug.LogError("ACT post_send_done pressed="..tostring(hit and 1 or 0)'
            '.." sent="..tostring(hit and picked or 0)'
            '.." rows_selected=["..table.concat(said,",").."]") end)')


def secret_post_batch_read() -> str:
    """Look into «Мега развертывание» before confirming it: what would actually go.

    The popup arrives with a squad already chosen for every idle task AND with its own
    «только UR» toggle already on (`View.isOnlySelectUR`), so on the reading this was
    written from five rows were offered and exactly ONE was `selected` — the idle UR.
    That is the game's own answer to «send the thing the refresh just won», and it is
    why this ability never needs to pick heroes itself.

    THIS IS A VERIFICATION AND NOT ONLY A COUNT (#2022). The toggle is the game's, and
    this ability's own last step used to untick it whenever the «send the leftovers»
    switch was on — which was the default. The press right after sends every SELECTED
    row, and unticking is what selects them all, so the cheap tasks went out with the
    UR ones. Whether the untick also survived to the NEXT popup is an open question,
    named in `docs/research/secret-task-refresh.md`; nothing here assumes either answer.
    So this parks four numbers rather than two:

      * `rows` / `picked` — how many the popup holds and how many are selected;
      * `onlyur` — 1 when the game's own toggle is really on, read rather than assumed;
      * `cheap` — how many of the SELECTED rows are below UR, judged on the row's own
        config `color` exactly as the scan judges an idle task;
      * `unread` — how many of those rows had no readable colour at all. They are
        counted CHEAP as well, because the only mistake that costs a day of marches is
        sending one — but they are counted APART so the refusal that follows says «this
        popup's rows could not be read» rather than «the game selected cheap tasks».
        The two want opposite fixes, and one number for both hides which it is.

    …and a fifth that says whether any of the four mean anything: `read_ok`. It is
    cleared before the walk and set only after a live popup has actually been read, so
    a read that died leaves 0 rather than the previous run's «all clear». The recipe
    treats a 0 exactly as it treats a refusal — nothing is sent, and it says why.

    Zero selected is not an error — it is «there is nothing here the rule wants sent»,
    and the recipe closes the popup instead of confirming it. A non-zero `cheap`, or an
    `onlyur` of 0, is the recipe's cue to refuse the send outright — and the PRESS
    refuses on its own account as well (:func:`secret_post_dispatch_confirm`), so the
    guard does not rest on the recipe having asked.
    """
    return (
            # CLEARED FIRST, IN A PCALL OF ITS OWN, and that is not tidiness (#2022). The
            # numbers below live on the manager between calls, so a read that DIES —
            # popup gone, view not a table, the manager itself unreachable — would leave
            # the previous run's «all clear» standing and the next gate would pass on a
            # reading nobody took. The stamp says «this answer was taken just now»; a 0
            # is «I could not look», which the recipe treats exactly like a refusal.
            "pcall(function() DataCenter.ActDispatchTaskDataManager.__lw_ref_read_ok=0 end) "
            "pcall(function() local M=DataCenter.ActDispatchTaskDataManager " + _NUM +
            "local w=UIManager.Instance:GetWindow(UIWindowNames.UIDispatchTaskSuperPopup) "
            "local rows,picked,cheap,unread=0,0,0,0 local onlyur=0 local seen=0 "
            "if w~=nil and type(w.View)=='table' then seen=1 "
            "local v=w.View "
            # The toggle is read from the Toggle behind it when there is one — that is
            # the thing a click moves — and from the view's own flag otherwise. Either
            # of them saying «on» is enough; neither being readable reads as OFF, so an
            # unreadable popup refuses the send rather than trusting it.
            "local t=v.toggleOnlySelectUR "
            "if t~=nil then local u=t.unity_uitoggle "
            "if u~=nil then pcall(function() if u.isOn then onlyur=1 end end) end end "
            "if onlyur==0 then pcall(function() if v.isOnlySelectUR then onlyur=1 end end) end "
            "for _,d in pairs(v.datas or {}) do rows=rows+1 "
            "if d.selected then picked=picked+1 "
            # A row's rarity, from the same place the scan reads it: the task's own
            # config `color`, where 5 is UR and anything above it counts as UR too. A
            # row whose colour cannot be read at all is counted as CHEAP — the safe
            # side of the only mistake that costs marches.
            "local col=-1 "
            "pcall(function() col=_num(d.taskInfo.cfg:getValue('color')) end) "
            "if col<0 then pcall(function() col=_num(d.cfg:getValue('color')) end) end "
            "if col<0 then unread=unread+1 end "
            "if col<5 then cheap=cheap+1 end end end end "
            "M.__lw_ref_rows=rows M.__lw_ref_picked=picked M.__lw_ref_unread=unread "
            "M.__lw_ref_onlyur=onlyur M.__lw_ref_cheap=cheap M.__lw_ref_read_ok=seen "
            'CS.UnityEngine.Debug.LogError("ACT post_send_rows rows="..tostring(rows)'
            '.." picked="..tostring(picked).." only_ur="..tostring(onlyur)'
            '.." cheap="..tostring(cheap).." unread="..tostring(unread)'
            '.." read_ok="..tostring(seen)) end)')


def secret_post_batch_only_ur() -> str:
    """Put «только UR» back ON, and say whether it had to be put back (#2022).

    The counterpart of :func:`secret_post_batch_all`. The operator watched a run untick
    the toggle and then send cheap tasks together with the UR ones — «отправлены не
    только UR задания, но и дешевые» — and the untick is this ability's own (#2022).

    Whether it also SURVIVES to the next popup is not known: the one recorded live
    reading says a popup opens with the filter on. Rather than settle that question by
    guessing, the run turns the toggle back on at EVERY popup it opens, before reading
    what would be sent — which is right under either answer and costs one call.

    Parks `__lw_ref_onlyur_fixed` = 1 when the toggle was found OFF and had to be
    restored. That is the standing measurement of «who unticks it»: now that nothing
    here does, a run that keeps reporting 1 is being unticked by something else, and
    that is when the research doc gets rewritten.
    """
    return ("pcall(function() local M=DataCenter.ActDispatchTaskDataManager "
            "M.__lw_ref_onlyur_fixed=0 "
            "local w=UIManager.Instance:GetWindow(UIWindowNames.UIDispatchTaskSuperPopup) "
            "if w==nil or type(w.View)~='table' then return end "
            "local v=w.View local was=0 "
            "local t=v.toggleOnlySelectUR local u=nil "
            "if t~=nil then u=t.unity_uitoggle end "
            "if u~=nil then pcall(function() if u.isOn then was=1 end end) "
            # Setting `isOn` is what a click does: the game's own handler re-filters the
            # rows off it, so nothing here has to know which of them are UR.
            "if was==0 then pcall(function() u.isOn=true end) end "
            "else pcall(function() if v.isOnlySelectUR then was=1 end end) "
            "if was==0 then pcall(function() v.isOnlySelectUR=true end) end end "
            "if was==0 then M.__lw_ref_onlyur_fixed=1 end "
            'CS.UnityEngine.Debug.LogError("ACT post_send_only_ur was="..tostring(was)) end)')


def secret_post_batch_all() -> str:
    """Untick «только UR» so the popup offers every idle task, not just the UR ones.

    The last step of a run, and only when the person asked for it: the tasks left over
    after the refreshing are the ones the rule was content to keep, and sending them is
    what turns them into rewards instead of leaving squads idle. The toggle is the
    game's own — flipping it is what re-selects the rows, so nothing here has to know
    which they are.
    """
    return ("pcall(function() "
            "local w=UIManager.Instance:GetWindow(UIWindowNames.UIDispatchTaskSuperPopup) "
            "if w==nil or type(w.View)~='table' then return end "
            "local t=w.View.toggleOnlySelectUR if t==nil then return end "
            "local u=t.unity_uitoggle if u==nil then return end "
            "if u.isOn then u.isOn=false end "
            'CS.UnityEngine.Debug.LogError("ACT post_send_all only_ur=0") end)')


def secret_post_batch_cancel() -> str:
    """Close the dispatch popup unpressed — the answer when nothing in it may be sent."""
    return ("pcall(function() local mgr=UIManager.Instance "
            "local n=UIWindowNames.UIDispatchTaskSuperPopup "
            "local ok,open=pcall(function() return mgr:IsWindowOpen(n) end) "
            "if ok and open then local w=mgr:GetWindow(n) "
            "if w and w.Ctrl and w.Ctrl.CloseSelf then pcall(function() w.Ctrl:CloseSelf() end) end "
            "end end)")


def secret_post_round_due() -> str:
    """Lua *expression* -> 1 while the alternating cycle still has a round to do.

    The cycle is «send, then refresh» and not «refresh, then send» — the correction the
    first live run earned (#1903). A refresh re-rolls every task nobody has sent, so a UR
    that a refresh has just produced is destroyed by the NEXT refresh unless a squad goes
    out on it first. The game agrees loudly: while an idle UR stands there it hides
    «Обновить» altogether, which is why seven presses in a row moved nothing.

    So a round is due when there is a UR to rescue, or when the rule still owes an
    ordinary refresh and something can pay for it.
    """
    return ("(function() " + _POST_SCAN + _GOLD_LEFT +
            "local keep=tonumber(M.__lw_ref_keep) or 0 "
            "if ur>0 then return 1 end "
            "if nonur<=keep then return 0 end "
            "if tickets>0 then return 1 end "
            "if price>0 and goldleft>=price then return 1 end "
            "return 0 end)()")


# --------------------------------------------------------------------------
# The boxes a secret task pays out in (#1903)
# --------------------------------------------------------------------------
#: «Загадочный ящик с припасами» — the box the day's own secret tasks hand out. A GAME
#: config id, identical on every account and every machine, exactly like
#: :data:`STAMINA_ITEMS` and the golden zombie's own id: nothing about one computer is
#: written down here (`CLAUDE.md`). It is item `type` 5, which is already in
#: :data:`USABLE_ITEM_TYPES`, so the bag will open it.
#:
#: One kind and not a family: the task rows in the game's own window list «Загадочный
#: ящик с припасами» beside the hero experience and the ore, and the resource chests in
#: the bag (`SR/SSR/UR сундук с …`, type 109) are what comes OUT of it rather than what a
#: task pays in.
SECRET_TASK_BOX = 710005


def bag_snapshot() -> str:
    """Park what the bag holds right now, id by id, so the next look can say what CHANGED.

    «What fell out of the boxes» has no other answer: the reward window is a picture, the
    server sends no itemised receipt the panel can read, and the bag is simply a table
    that is larger afterwards. So the honest report is a DIFFERENCE, and this is its first
    half.
    """
    return ("pcall(function() local m={} "
            "for _,s in pairs(DataCenter.ItemData.ItemInfos or {}) do "
            "local id=0 pcall(function() id=s.itemId+0 end) "
            "local c=0 pcall(function() c=s.count+0 end) "
            "if id>0 then m[id]=(m[id] or 0)+c end end "
            "DataCenter.__lw_bag_was=m end)")


def bag_gains(limit: int = 12) -> str:
    """Lua *expression* -> what the bag gained since :func:`bag_snapshot`, in words.

    Names come from the game's own table (`ItemTemplateManager:GetName`), so the line is
    already in the player's language and nothing here translates anything. Losses are
    reported too — the boxes themselves go down, and a report that showed only the gains
    would be hiding the price of its own success.
    """
    return ("(function() local was=DataCenter.__lw_bag_was "
            "if type(was)~='table' then return 'nothing was noted down first' end "
            "local now={} "
            "for _,s in pairs(DataCenter.ItemData.ItemInfos or {}) do "
            "local id=0 pcall(function() id=s.itemId+0 end) "
            "local c=0 pcall(function() c=s.count+0 end) "
            "if id>0 then now[id]=(now[id] or 0)+c end end "
            "local seen={} for id in pairs(was) do seen[id]=true end "
            "for id in pairs(now) do seen[id]=true end "
            "local rows={} "
            "for id in pairs(seen) do local d=(now[id] or 0)-(was[id] or 0) "
            "if d~=0 then local nm='' "
            "pcall(function() nm=tostring(DataCenter.ItemTemplateManager:GetName(id)) end) "
            "if nm=='' then nm='#'..tostring(id) end "
            "rows[#rows+1]={d=d,s=(d>0 and '+' or '')..tostring(d)..' '..nm} end end "
            "if #rows==0 then return 'nothing changed' end "
            "table.sort(rows,function(a,b) return math.abs(a.d)>math.abs(b.d) end) "
            "local out={} for i=1,math.min(#rows," + str(int(limit)) + ") do out[#out+1]=rows[i].s end "
            "if #rows>" + str(int(limit)) + " then out[#out+1]='…and '..tostring(#rows-" +
            str(int(limit)) + ")..' more' end "
            "return table.concat(out,', ') end)()")


def bag_holds(id_expr: str) -> str:
    """Lua *expression* -> how many of one item the bag holds, summed over its stacks."""
    return ("(function() local id=" + str(id_expr) + " local n=0 "
            "for _,s in pairs(DataCenter.ItemData.ItemInfos or {}) do "
            "local i=0 pcall(function() i=s.itemId+0 end) "
            "if i==id then local c=0 pcall(function() c=s.count+0 end) n=n+c end end "
            "return n end)()")


def secret_task_rewards_left() -> str:
    """Lua *expression* -> how many finished tasks are still waiting to be claimed."""
    return ("(function() local n=0 "
            "pcall(function() n=DataCenter.ActDispatchTaskDataManager"
            ":GetSingleTaskRewardableCount()+0 end) return n end)()")


def secret_task_claim_all() -> str:
    """Claim every finished task's reward in one press — the manager's own «забрать всё».

    `TryRewardAll()` is the game's own button behind «Получить», and it is what sends
    `hero.dispatch.batch.reward`. Measured live: six finished tasks, `rewardable` 6 -> 0,
    every one of them `rewarded = 1` afterwards and the march slots free.

    Claiming is income, never a cost — nothing here is gated on a budget.
    """
    return ("pcall(function() local M=DataCenter.ActDispatchTaskDataManager "
            "local before=0 pcall(function() before=M:GetSingleTaskRewardableCount()+0 end) "
            "if before>0 then pcall(function() M:TryRewardAll() end) end "
            'CS.UnityEngine.Debug.LogError("ACT post_claim was="..tostring(before)) end)')


def secret_post_mega_spent() -> str:
    """Lua *expression* -> the diamonds the mega refresh actually took.

    A press is not believed on its own word (#1282, and #1903 in diamonds): the purse is
    stamped when the price is read and read again after the confirm, so what was really
    paid is said out loud instead of inferred from a dialog that turned out to be
    describing something else.
    """
    return ("(function() local M=DataCenter.ActDispatchTaskDataManager "
            "local was=tonumber(M.__lw_ref_mega_gold0) "
            "if was==nil then return 0 end local now=0 "
            "pcall(function() now=LuaEntry.Player.gold+0 end) "
            "local d=was-now if d<0 then d=0 end return d end)()")


# ---------------------------------------------------------------------------
# The trade station's fleet: rotate a truck's rarity, then send it out (#1908)
# ---------------------------------------------------------------------------
# The THIRD truck in this file, and the only one that spends anything. The other
# two are income: `trucks_ready_count` counts the supply trucks that have arrived
# at the base and `truck_reward_*` empties the idle accumulator parked on it.
# These press the TRADE STATION — the fleet a commander dispatches to another
# server, other players rob on the way, and the initiator empties on arrival.
#
# EVERYTHING HERE IS THE GAME'S OWN «Супер режим» WINDOW, and that is a decision
# rather than a convenience. `UILWTruckSuperDeparture` holds both halves of the
# ability — a Refresh tab that lifts several trucks' rarity in one send, and a
# Departure tab that sends several trucks with their escorts in one more — and
# both halves live in the VIEW rather than in the data manager
# (`UILWTruckSuperDeparture.View`, measured live on three accounts, #1908):
#
#   canSelectRefreshTruckIndexMap    which trucks the refresh may touch at all —
#                                    and it already excludes one that is at the
#                                    top rarity, which is a gate nothing here has
#                                    to reinvent
#   canSelectDepartureTruckIndexMap  …and which may be sent
#   recordSelectRefreshTruckIndexMap the selection itself, index -> true
#   recordSelectDepartureTruckIndexMap
#   selectRefreshReindeerCart        the «all the way to the sleigh» toggle
#   isUnlockReindeerCart             whether this account has that toggle at all
#   CalcRefreshTruckCost()           …which SETS refreshSelectTruckNeedTicketCount
#   refreshSelectTruckNeedTicketCount  the price of the current selection, in
#                                    Trade Contracts
#   ownTicketCount                   how many are in the bag
#   oneTicket2DiamondNum             what one costs in diamonds when the bag is
#                                    short — the game tops a short bag up itself
#   OnBtnRefreshOrDepartureClick()   the ONE button, whichever tab is up
#   OnTabItemClick(n)                1 = Refresh, 2 = Departure
#
# THE PRICE WAS MEASURED, ONE TRUCK AT A TIME, and it is flat: three contracts to
# bring ANY truck to UR — a level-1 truck and a level-4 truck cost the same — and
# six to bring it to the Reindeer Sleigh Ride. Three trucks to the sleigh is
# therefore 18 contracts, and none of that is written down here: the selection is
# made, `CalcRefreshTruckCost()` is called, and the number the game answers is what
# the gate is judged on. A price read off a table is a price that was true once.
#
# RARITY IS TWO FIELDS, NOT ONE. `quality` runs 1..5 — 5 is UR — and the sleigh is
# `quality == 10` with `isSpecialURQuality == true` beside it. So «is this truck
# already good enough» is asked as: at the UR target, anything from 5 up; at the
# sleigh target, only the special flag. Anything ABOVE 5 that is not the sleigh
# counts as UR too, for the reason the secret tasks give: a rarity nobody has seen
# yet must not read as «not good enough» and be re-rolled away.
#
# WHAT IS NOT HERE. An account whose trade station has no super mode would rotate
# one truck at a time (`train.change`, `LWMyStationDataManager:TryChangeTrain`) —
# and there is no such account to measure against: all three that were open when
# this was written have the super window and the sleigh unlocked. So the scan reads
# the fact and the scenario says so rather than guessing at a frame that spends
# contracts; see docs/research/truck-dispatch.md.

#: The window both halves of the ability live in.
_TRUCK_WIN = "UIWindowNames.UILWTruckSuperDeparture"

#: …and the second confirm it raises when a press would throw away something good.
_TRUCK_CONFIRM = "UIWindowNames.UILWTruckSuperDepartureRefreshSecondConfirm"

#: The station manager, and the view of the window in front of it. Both are asked
#: for every step, because a window the person closed under the panel's feet is an
#: ordinary thing and must read as «not open» rather than raise.
_TRUCK_M = ("local M=DataCenter and DataCenter.LWMyStationDataManager ")

_TRUCK_VIEW = (
    "local function _tview() local ok,w=pcall(function() "
    "return UIManager.Instance:GetWindow(" + _TRUCK_WIN + ") end) "
    "if not ok or w==nil then return nil end local v=nil "
    "pcall(function() v=w.View end) return v end ")

#: Is this truck already at or above what the run is aiming for? `target` is 10 for
#: the Reindeer Sleigh Ride and 5 for UR — the game's own `quality` numbers, so the
#: setting travels as the thing it names.
_TRUCK_ENOUGH = (
    "local function _enough(t,target) if t==nil then return true end "
    "local sp=false pcall(function() sp=(t.isSpecialURQuality==true) end) "
    "if sp then return true end "
    "if target>=10 then return false end "
    "return _num(t.quality)>=5 end ")

#: The item a rotation is paid for in — asked of the game, never spelled out.
_TRUCK_ITEM = ("(function() local ok,v=pcall(function() "
               "return DataCenter.LWMyStationDataManager:GET_CHANGE_TRAIN_ITEM_ID() end) "
               "local n=0 if ok and v~=nil then pcall(function() n=v+0 end) end "
               "return n end)()")


def truck_station_stamp() -> str:
    """Stamp the two purses the run is measured from, and clear the last run's verdicts.

    The three knobs a person can change — what rarity the run aims for, whether diamonds
    may top a short bag of contracts up, and how many of them may go — are set by the
    scenario's own `LUA` line just above this, because `TAP` takes no arguments and the
    values come out of `ARGS`. This deliberately does NOT touch them: it only writes down
    what the wallet and the bag held at the start, so «what did that cost» can be answered
    by subtraction rather than by trusting a press's own word.

    A budget of 0 means NO CEILING, and that is the operator's instruction for this
    ability in their own words — «в супер режиме всегда обновляем до требуемого уровня НЕ
    ТОРГУЯСЬ». The secret tasks' ceiling of 1200 is a rule about a different screen and a
    different currency; carrying it over here would be inventing a limit nobody asked for.
    """
    return ("pcall(function() " + _NUM + _TRUCK_M +
            "if not M then return end "
            "if M.__lw_trk_target==nil then M.__lw_trk_target=10 end "
            "if M.__lw_trk_gold==nil then M.__lw_trk_gold=1 end "
            "if M.__lw_trk_budget==nil then M.__lw_trk_budget=0 end "
            "if M.__lw_trk_one==nil then M.__lw_trk_one=0 end "
            "M.__lw_trk_cost=-1 M.__lw_trk_want=0 M.__lw_trk_ok=0 M.__lw_trk_need=0 "
            "M.__lw_trk_picked=0 "
            "local g=0 pcall(function() g=_num(LuaEntry.Player.gold) end) "
            "M.__lw_trk_gold0=g "
            "local item=" + _TRUCK_ITEM + " local tick=0 "
            "pcall(function() for _,s in pairs(DataCenter.ItemData.ItemInfos or {}) do "
            "if _num(s.itemId)==item then tick=tick+_num(s.count) end end end) "
            "M.__lw_trk_tick0=tick "
            'CS.UnityEngine.Debug.LogError("ACT trk_arm target="..tostring(M.__lw_trk_target)'
            '.." gold="..tostring(M.__lw_trk_gold).." budget="..tostring(M.__lw_trk_budget)'
            '.." tickets="..tostring(tick)) end)')


def truck_station_open() -> str:
    """Open «Супер режим» — the window both halves of the ability live in."""
    return ("pcall(function() UIManager.Instance:OpenWindow(" + _TRUCK_WIN + ") end)")


def truck_station_close() -> str:
    """Close the window, and the second confirm if one is still standing."""
    return ("pcall(function() local mgr=UIManager.Instance "
            "for _,n in ipairs({" + _TRUCK_CONFIRM + ", " + _TRUCK_WIN + "}) do "
            "local ok,open=pcall(function() return mgr:IsWindowOpen(n) end) "
            "if ok and open then local w=mgr:GetWindow(n) "
            "if w and w.Ctrl and w.Ctrl.CloseSelf then "
            "pcall(function() w.Ctrl:CloseSelf() end) end end end end)")


def truck_station_scan() -> str:
    """Walk the fleet once and park every number the recipe branches on.

    A snapshot rather than a dozen separate reads, for the reason every other scan in
    this file gives: a truck that arrives between two of them would be counted as idle
    by one question and as travelling by the next.

    The station's lock is asked FIRST and parked as its own flag, because a locked
    station answers `0` dispatched exactly like an idle one — drawn straight that reads
    as «nothing sent yet today» on an account that cannot send anything at all.
    """
    return ("pcall(function() " + _NUM + _TRUCK_M + _TRUCK_VIEW + _TRUCK_ENOUGH +
            "if not M then return end "
            "local lock=1 pcall(function() if not M:IsTruckFunctionLock() then lock=0 end end) "
            "local sent=0 pcall(function() sent=_num((M:GetDepartureCount())) end) "
            "local cap=0 pcall(function() cap=_num((M:GetMaxDailyCount())) end) "
            "local ready=0 pcall(function() ready=_num((M:GetRealReadyCount())) end) "
            "local item=" + _TRUCK_ITEM + " local tick=0 "
            "pcall(function() for _,s in pairs(DataCenter.ItemData.ItemInfos or {}) do "
            "if _num(s.itemId)==item then tick=tick+_num(s.count) end end end) "
            "local gold=0 pcall(function() gold=_num(LuaEntry.Player.gold) end) "
            "local target=_num(M.__lw_trk_target) if target<=0 then target=10 end "
            "local v=_tview() local win=(v~=nil) and 1 or 0 "
            "local sleigh=0 local rate=0 local own=tick "
            "if v~=nil then pcall(function() if v.isUnlockReindeerCart==true then sleigh=1 end end) "
            "pcall(function() rate=_num(v.oneTicket2DiamondNum) end) "
            "pcall(function() own=_num(v.ownTicketCount) end) end "
            # How many trucks are already where the run wants them, and how many it
            # would still like to improve. The two are counted off DIFFERENT lists on
            # purpose:
            #
            #   * `good` and `fleet` come from the station manager, which holds every
            #     truck the account owns whether it is standing or on the road. Counting
            #     them off the window instead made the closing line say «0 at the target»
            #     about three sleighs that had just been dispatched — the window rebuilds
            #     its rows around what can be acted on, and a truck in flight cannot;
            #   * `poor` comes from the window, because it is «how many presses are
            #     there», and a truck the refresh may not touch is not one of them.
            "local poor,good,fleet,home,road=0,0,0,0,0 "
            # A truck that has come home with a load is `TruckStationState.Reward`,
            # asked of the manager rather than derived from `arriveTs`: the client
            # owns the difference between «the clock says it has landed» and «the
            # server has said so», and only the second one can be collected.
            "pcall(function() for _,t in pairs(M:GetMyTrainList() or {}) do "
            "fleet=fleet+1 if _enough(t,target) then good=good+1 end "
            "local st=-1 pcall(function() st=_num((M:GetTruckStationStateByTrainData(t))) end) "
            "if st==4 then home=home+1 elseif st==3 then road=road+1 end end end) "
            "pcall(function() for i=1,8 do local d=v and v.truckShowDataList[i] "
            "local t=d and d.truckData "
            "if t~=nil and not _enough(t,target) and v.canSelectRefreshTruckIndexMap "
            "and v.canSelectRefreshTruckIndexMap[i] then poor=poor+1 end end end) "
            "M.__lw_trk_lock=lock M.__lw_trk_sent=sent M.__lw_trk_cap=cap "
            "M.__lw_trk_ready=ready M.__lw_trk_tick=tick M.__lw_trk_goldnow=gold "
            "M.__lw_trk_win=win M.__lw_trk_sleigh=sleigh M.__lw_trk_rate=rate "
            "M.__lw_trk_own=own M.__lw_trk_poor=poor M.__lw_trk_good=good "
            "M.__lw_trk_fleet=fleet M.__lw_trk_home=home M.__lw_trk_road=road "
            'CS.UnityEngine.Debug.LogError("ACT trk_scan lock="..tostring(lock)'
            '.." sent="..tostring(sent).."/"..tostring(cap).." ready="..tostring(ready)'
            '.." tickets="..tostring(tick).." poor="..tostring(poor).." good="..tostring(good)'
            '.." window="..tostring(win).." sleigh="..tostring(sleigh)'
            '.." home="..tostring(home).." road="..tostring(road)) end)')


def truck_refresh_select() -> str:
    """Tick exactly the trucks that are below the target, and read what that costs.

    Not «select all»: the window's own button ticks every truck it MAY touch, and at
    the UR target that includes a truck which is already UR — a press would re-roll a
    win and pay for the privilege. So the selection is built here, one index at a time,
    out of the trucks the game says are selectable AND that :data:`_TRUCK_ENOUGH` says
    are not good enough yet.

    The price is the game's own: the selection is set, `CalcRefreshTruckCost()` is
    called, and `refreshSelectTruckNeedTicketCount` is what it answers. Parked beside it
    is the verdict — contracts alone if the bag covers it, otherwise the diamonds the
    game would silently top the shortfall up with, judged against the ceiling the run
    was armed with (0 = none, which is this ability's default).
    """
    return ("pcall(function() " + _NUM + _TRUCK_M + _TRUCK_VIEW + _TRUCK_ENOUGH +
            "if not M then return end local v=_tview() "
            "M.__lw_trk_cost=-1 M.__lw_trk_want=0 M.__lw_trk_ok=0 M.__lw_trk_need=0 "
            "if v==nil then return end "
            "local target=_num(M.__lw_trk_target) if target<=0 then target=10 end "
            # The sleigh is a tech of its own. An account without it cannot be asked
            # for one, so the run quietly aims at UR instead and says so in the scan.
            "local sleigh=false pcall(function() sleigh=(v.isUnlockReindeerCart==true) end) "
            "if target>=10 and not sleigh then target=5 end "
            "M.__lw_trk_aim=target "
            "pcall(function() v:OnTabItemClick(1) end) "
            "pcall(function() v.selectRefreshReindeerCart=(target>=10) end) "
            "local map=v.recordSelectRefreshTruckIndexMap "
            "if type(map)~='table' then return end "
            "for k in pairs(map) do map[k]=nil end "
            "local want=0 "
            "pcall(function() for i=1,8 do local d=v.truckShowDataList[i] "
            "local t=d and d.truckData "
            "if t~=nil and v.canSelectRefreshTruckIndexMap "
            "and v.canSelectRefreshTruckIndexMap[i] and not _enough(t,target) then "
            "map[i]=true want=want+1 end end end) "
            "local cost=0 "
            "pcall(function() v:CalcRefreshTruckCost() end) "
            "pcall(function() cost=_num(v.refreshSelectTruckNeedTicketCount) end) "
            "local own=0 pcall(function() own=_num(v.ownTicketCount) end) "
            "local rate=0 pcall(function() rate=_num(v.oneTicket2DiamondNum) end) "
            "local budget=_num(M.__lw_trk_budget) "
            "local allow=(_num(M.__lw_trk_gold)~=0) "
            "local need=0 local ok=0 "
            "if want>0 then if own>=cost then ok=1 "
            "elseif allow and rate>0 then need=(cost-own)*rate "
            "if budget<=0 or need<=budget then ok=1 end end end "
            "M.__lw_trk_cost=cost M.__lw_trk_want=want M.__lw_trk_ok=ok "
            "M.__lw_trk_need=need M.__lw_trk_own=own M.__lw_trk_rate=rate "
            'CS.UnityEngine.Debug.LogError("ACT trk_select want="..tostring(want)'
            '.." aim="..tostring(target).." cost="..tostring(cost).." own="..tostring(own)'
            '.." need="..tostring(need).." ok="..tostring(ok)) end)')


def truck_refresh_press() -> str:
    """Press the window's own button on the Refresh tab — the press that starts the spend.

    The game's button rather than a `train.batch.change` built here, for the reason the
    secret tasks give about theirs: what a rotation costs and which purse it comes out
    of is the client's decision, and a frame written by hand is a guess between «spend a
    contract» and «spend diamonds» that the player pays for.

    It does not always finish the job. Measured live: with three trucks ticked the click
    raised `UILWTruckSuperDepartureRefreshSecondConfirm` and sent NOTHING — the run's
    first attempt reported success against an unchanged bag of 358 contracts. So the
    answer to that dialog is a step of its own (:func:`truck_refresh_confirm`), because a
    dialog needs a frame to appear in and nothing inside one Lua chunk can wait for it.
    """
    return ("pcall(function() " + _TRUCK_VIEW +
            "local v=_tview() if v==nil then return end "
            "pcall(function() v:OnBtnRefreshOrDepartureClick() end) "
            'CS.UnityEngine.Debug.LogError("ACT trk_refresh pressed=1") end)')


def truck_refresh_confirm() -> str:
    """Answer the second confirm, if the press raised one — this is what actually sends.

    The dialog's own confirm is `TrySendRefreshMsg` on the view behind it, and calling
    that is what took 18 contracts out of a bag of 358 and turned three trucks into
    sleighs on the run this was written from. It is reached through the VIEW rather than
    by hunting a button called `ConfirmBtn` under the dialog's root: the first version did
    hunt for one, found nothing under any of the four usual names, and reported a
    successful rotation that had not happened.

    Guarded on the dialog being open, so a press that went straight through cannot be
    sent a second time.
    """
    return ("pcall(function() " + _TRUCK_VIEW +
            "local mgr=UIManager.Instance "
            "local ok,open=pcall(function() return mgr:IsWindowOpen(" + _TRUCK_CONFIRM + ") end) "
            "local sent=0 "
            "if ok and open then local v=_tview() "
            "if v~=nil then pcall(function() v:TrySendRefreshMsg() end) sent=1 end "
            "local w=mgr:GetWindow(" + _TRUCK_CONFIRM + ") "
            "if w and w.Ctrl and w.Ctrl.CloseSelf then "
            "pcall(function() w.Ctrl:CloseSelf() end) end end "
            'CS.UnityEngine.Debug.LogError("ACT trk_confirm sent="..tostring(sent)) end)')


def truck_send_select() -> str:
    """Tick the trucks that are to go out, best first, and never more than the day allows.

    «Send what there is room for» is the whole of it. The window says which trucks MAY
    be sent; the day's allowance says how many presses are left, and the two are not the
    same number — a fleet of three standing at a station with one dispatch banked sends
    ONE. When the allowance is the smaller of the two, the trucks are ranked by rarity
    and the best go: a sleigh held back for tomorrow is a sleigh somebody re-rolls away.
    """
    return ("pcall(function() " + _NUM + _TRUCK_M + _TRUCK_VIEW +
            "if not M then return end local v=_tview() "
            "M.__lw_trk_picked=0 if v==nil then return end "
            "pcall(function() v:OnTabItemClick(2) end) "
            "local map=v.recordSelectDepartureTruckIndexMap "
            "if type(map)~='table' then return end "
            "for k in pairs(map) do map[k]=nil end "
            "local rows={} "
            "pcall(function() for i=1,8 do local d=v.truckShowDataList[i] "
            "local t=d and d.truckData "
            "if t~=nil and v.canSelectDepartureTruckIndexMap "
            "and v.canSelectDepartureTruckIndexMap[i] then "
            "rows[#rows+1]={i=i,q=_num(t.quality)} end end end) "
            "table.sort(rows,function(a,b) if a.q==b.q then return a.i<b.i end return a.q>b.q end) "
            "local sent=0 pcall(function() sent=_num((M:GetDepartureCount())) end) "
            "local cap=0 pcall(function() cap=_num((M:GetMaxDailyCount())) end) "
            "local left=cap-sent if left<0 then left=0 end "
            "local picked=0 "
            # «По одному за раз»: the rows are already ranked by rarity, so a cap of
            # one sends the BEST truck standing and leaves the rest for the turns
            # this errand books itself as each one comes home. The escorting squad is
            # still the window's own — with a single truck ticked it puts up the first
            # formation, which is the strongest one the person has arranged.
            "local one=_num(M.__lw_trk_one) if one~=0 and left>1 then left=1 end "
            "for _,r in ipairs(rows) do if picked>=left then break end "
            "map[r.i]=true picked=picked+1 end "
            "M.__lw_trk_picked=picked M.__lw_trk_left=left M.__lw_trk_standing=#rows "
            'CS.UnityEngine.Debug.LogError("ACT trk_pick picked="..tostring(picked)'
            '.." standing="..tostring(#rows).." left="..tostring(left)) end)')


def truck_send_press() -> str:
    """Send the ticked trucks — the view's own `TrySendDepartureMsg`, and not the button.

    The Refresh tab and the Departure tab share one button, and driven from Lua the two
    behave differently: on the Refresh tab `OnBtnRefreshOrDepartureClick` raises the
    second confirm, and on the Departure tab it does nothing whatsoever. That is not a
    guess — a whole run pressed it against three trucks standing at a station with five
    dispatches banked and left the counter at 0/5; the same selection sent all three the
    moment `TrySendDepartureMsg` was called. (The handler presumably wants the button it
    was wired to, which a call from outside has not got.)

    So this is the sender the button ends at, called directly, and the click is not made
    at all — a click that MIGHT work followed by a send that certainly does is two
    dispatches out of a five-a-day allowance the first time the click starts working.

    The escorting squads are still the window's own: it arrives with five heroes against
    every truck, which is the part a hand-built `train.send` would have to invent.
    """
    return ("pcall(function() " + _TRUCK_VIEW +
            "local v=_tview() if v==nil then return end "
            "pcall(function() v:TrySendDepartureMsg() end) "
            'CS.UnityEngine.Debug.LogError("ACT trk_send sent=1") end)')


def truck_collect_arrived() -> str:
    """Empty every truck that has come home — the window's own batch collect.

    A truck the trade station sent out comes back three to four hours later carrying
    what it earned, and until somebody takes that load the truck is not standing at the
    station either: it is `TruckStationState.Reward`, which is neither `Ready` (it cannot
    be sent) nor `Travelling` (it is not going anywhere). So the collect is not a tidying
    step at the end of the day — it is what turns an arrival back into a dispatch, and
    the day's allowance is spent by trucks that were collected in time and wasted by ones
    that were not.

    `TryBatchCollectReward()` is the one press, measured live: it takes no arguments and
    empties the lot (`train.batch.reward`). Its per-truck sibling `TryCollectReward` wants
    a uuid — called bare it raises inside the serialiser — and one press for the fleet is
    one round trip instead of four.

    The arrived count is parked before the press so the recipe can say what it took, and
    the press is not made at all when nothing is home: a batch of nothing is a frame the
    server is asked to think about for no reason.
    """
    return ("pcall(function() " + _NUM + _TRUCK_M +
            "if not M then return end "
            "local home=0 "
            "pcall(function() for _,t in pairs(M:GetMyTrainList() or {}) do "
            "local st=-1 pcall(function() st=_num((M:GetTruckStationStateByTrainData(t))) end) "
            "if st==4 then home=home+1 end end end) "
            "M.__lw_trk_home=home M.__lw_trk_took=0 "
            "if home>0 then local ok=pcall(function() M:TryBatchCollectReward() end) "
            "if ok then M.__lw_trk_took=home end end "
            'CS.UnityEngine.Debug.LogError("ACT trk_collect home="..tostring(home)'
            '.." took="..tostring(M.__lw_trk_took)) end)')


def truck_gold_spent() -> str:
    """Lua *expression* -> how many diamonds the purse has gone down by since the arm.

    A press is not believed on its own word — the purse is. The game tops a short bag of
    contracts up with diamonds by itself and says so nowhere a recipe can read, which is
    how a mega refresh once cost a thousand diamonds nobody had allowed (#1903).
    """
    return ("(function() local M=DataCenter.LWMyStationDataManager "
            "local was=tonumber(M.__lw_trk_gold0) if was==nil then return 0 end "
            "local now=0 pcall(function() now=LuaEntry.Player.gold+0 end) "
            "local d=was-now if d<0 then d=0 end return d end)()")


def truck_tickets_spent() -> str:
    """Lua *expression* -> how many Trade Contracts have left the bag since the arm."""
    return ("(function() " + _NUM + "local M=DataCenter.LWMyStationDataManager "
            "local was=tonumber(M.__lw_trk_tick0) if was==nil then return 0 end "
            "local item=" + _TRUCK_ITEM + " local now=0 "
            "pcall(function() for _,s in pairs(DataCenter.ItemData.ItemInfos or {}) do "
            "if _num(s.itemId)==item then now=now+_num(s.count) end end end) "
            "local d=was-now if d<0 then d=0 end return d end)()")


# ---------------------------------------------------------------------------
# robbing somebody else's trade truck (#2591)
# ---------------------------------------------------------------------------
#
# A DIFFERENT SCREEN FROM THE ONE ABOVE. Everything up to here is our OWN fleet — the
# «Супер режим» window, the rotation, the dispatch. This is the other tab of the same
# event: the board of trucks other players have on the road, and the press that robs one.
# The game caps it at four a day (`MAX_DAILY_LOOT_COUNT`) and counts what has gone with
# `GetRobCount()`.
#
# THE PRESS IS BUILT BY HAND, and the two hours it took to learn why are worth four lines
# (measured live, #2591):
#
#   * `LWMyStationDataManager:TryAttackTrain(trainData, …)` throws inside the serialiser —
#     `bad argument #2 to 'pack' (number expected, got table)`. Whatever the client calls
#     it with, it is not a train's own data table;
#   * `FormationToSFSObject(formation)` hands back an array of 33 entries whose `heroUuid`
#     sits under the LONG tag holding a STRING, and the packer refuses it the same way. It
#     is not the `heroInfo` the message wants;
#   * `trainData.uuid` is a STRING on the board — `%d` will format it and `PutLong` will
#     not take it, which is exactly the kind of failure that looks like a server refusal;
#   * so the array is built here: one `SFSObject` per hero standing in the squad, with the
#     hero's uuid as a number and its slot as an int.
#
# The four fields the message really writes were read off `AttackTrainMessage:OnCreate`
# with a recording proxy in place of `sfsObj` (the trick `docs/research/alliance-train.md`
# describes): `PutLong uuid`, `PutSFSArray heroInfo`, `PutInt serverId`, `PutInt squadNo`,
# taken from arguments 1, 2, 3 and 5. Argument 4 is written nowhere and goes out as 0.
#
# WHAT «WEAKER THAN US» IS MEASURED AGAINST. The client cannot price its own squad:
# `GetFormationPowerByUuid` answers 0 for every formation and there is no `*BattlePower`
# method anywhere in `DataCenter`. Two readings exist, and this file prefers them in this
# order:
#
#   1. **the server's own number**, off one of OUR trucks on the road — a dispatched truck
#      carries the `power` of the squad escorting it, in the same units as the `power` the
#      board prints against somebody else's truck. Apples to apples, and the only reading
#      that is;
#   2. **the heroes' own numbers added up**, when no truck of ours is out. It reads LOWER
#      than the server's (39.8M against 60.1M for the same squad, measured), so a rule
#      written against it comes out STRICTER than the person asked for — which is the safe
#      direction for a press that loses troops when it is wrong.
#
# Which of the two answered is parked as well, so the recipe can say it out loud rather
# than quietly comparing two different scales.

#: The board of other players' trucks. Tab 2 is «цели»; tab 1 is our own fleet.
_ROB_WIN = "UIWindowNames.UILWTrainList"

_ROB_BOARD = (
    "local function _rboard() local ok,w=pcall(function() "
    "return UIManager.Instance:GetWindow(" + _ROB_WIN + ") end) "
    "if not ok or w==nil then return nil end local l=nil "
    "pcall(function() l=w.View:GetTrainsByTab(2) end) return l end ")

#: Every knob the recipe parked, with the defaults a run that parked nothing still works
#: under. `black` is a comma-fenced list of owner ids — `,id,id,` — so a plain substring
#: search cannot match half an id.
_ROB_RULE = (
    "local function _rrule(M) local lvl=_num(M.__lw_rob_lvl) if lvl<=0 then lvl=31 end "
    "local q=_num(M.__lw_rob_q) local margin=_num(M.__lw_rob_margin) "
    "local squad=_num(M.__lw_rob_squad) if squad<=0 then squad=1 end "
    "local black=','..tostring(M.__lw_rob_black or '')..',' "
    "return lvl,q,margin,squad,black end ")

#: What the run is allowed to compare a guard's power against. Returns the number and
#: where it came from: 1 = the server's own, 0 = the heroes added up, -1 = nothing.
_ROB_OURS = (
    "local function _rours(M,squad) local best=0 "
    "pcall(function() for _,t in pairs(M:GetMyTrainList() or {}) do "
    "if _num(t.squadNo)==squad then local p=_num(t.power) if p>best then best=p end end end end) "
    "if best>0 then return best,1 end local sum=0 "
    "pcall(function() local f=M:GetAttackFormationByIndex(squad) "
    "for uuid,_ in pairs(f.heroes or {}) do "
    "local h=DataCenter.HeroDataManager:GetHeroByUuid(uuid) "
    "if type(h)=='table' then sum=sum+_num(h.power) end end end) "
    "if sum>0 then return sum,0 end return 0,-1 end ")

#: Does one truck on the board pass every part of the rule.
_ROB_FITS = (
    "local function _rfits(t,lvl,q,margin,black,ours) "
    "if t==nil or ours<=0 then return false end "
    "if _num(t.ownerLv)<lvl then return false end "
    "if q>0 then local sp=false pcall(function() sp=(t.isSpecialURQuality==true) end) "
    "if _num(t.quality)<q and not (q>=10 and sp) then return false end end "
    "if black:find(','..tostring(t.ownerId)..',',1,true) then return false end "
    "if _num(t.power)>ours*(100-margin)/100 then return false end "
    "return true end ")


def truck_rob_open() -> str:
    """Open the board of other players' trucks."""
    return ("pcall(function() UIManager.Instance:OpenWindow(" + _ROB_WIN + ") end)")


def truck_rob_close() -> str:
    """Close it again, leaving the screen as it was found."""
    return ("pcall(function() local mgr=UIManager.Instance "
            "local ok,open=pcall(function() return mgr:IsWindowOpen(" + _ROB_WIN + ") end) "
            "if ok and open then local w=mgr:GetWindow(" + _ROB_WIN + ") "
            "if w and w.Ctrl and w.Ctrl.CloseSelf then "
            "pcall(function() w.Ctrl:CloseSelf() end) end end end)")


def truck_rob_scan() -> str:
    """Read the board, the day's counter and our own strength in one go.

    One snapshot rather than a dozen questions, for the reason every other scan in this
    file gives: a truck that leaves the board between two of them would be counted twice.
    """
    return ("pcall(function() " + _NUM + _TRUCK_M + _ROB_BOARD + _ROB_RULE + _ROB_OURS +
            _ROB_FITS +
            "if not M then return end "
            "local lvl,q,margin,squad,black=_rrule(M) "
            "local ours,src=_rours(M,squad) "
            "M.__lw_rob_ours=ours M.__lw_rob_src=src "
            "local done=0 pcall(function() done=_num((M:GetRobCount())) end) "
            "local cap=0 pcall(function() cap=_num(M.MAX_DAILY_LOOT_COUNT) end) "
            "if cap<=0 then cap=4 end "
            "local usedup=0 pcall(function() if M:IsTruckRobCountUsedUp() then usedup=1 end end) "
            "local l=_rboard() local win=(l~=nil) and 1 or 0 "
            "local n,fit,best=0,0,0 "
            "if l~=nil then pcall(function() for _,d in pairs(l) do local t=d.trainData or d "
            "n=n+1 if _rfits(t,lvl,q,margin,black,ours) then fit=fit+1 "
            "local p=_num(t.power) if p>best then best=p end end end end) end "
            "M.__lw_rob_win=win M.__lw_rob_n=n M.__lw_rob_fit=fit M.__lw_rob_best=best "
            "M.__lw_rob_done=done M.__lw_rob_cap=cap M.__lw_rob_used=usedup "
            'CS.UnityEngine.Debug.LogError("ACT rob_scan window="..tostring(win)'
            '.." board="..tostring(n).." fit="..tostring(fit).." done="..tostring(done)'
            '.."/"..tostring(cap).." ours="..tostring(ours).." src="..tostring(src)) end)')


def truck_rob_refresh() -> str:
    """Ask the SERVER for a new board of targets, and count the rotation.

    `train.list` is what the window's own refresh button sends, and it really does
    replace the rows: measured live, all fifteen `uuid`s came back different. Re-opening
    the window would do the same thing and cost the six seconds the window takes, so the
    message goes on its own.

    The count of rotations that found nothing lives here beside it, because the recipe has
    no arithmetic of its own — `__lw_rob_spins` is set to the person's ceiling once and
    walked down by `truck_rob_spend_spin` below.
    """
    return ("pcall(function() SFSNetwork.SendMessage('train.list', true) "
            'CS.UnityEngine.Debug.LogError("ACT rob_refresh asked") end)')


def truck_rob_press() -> str:
    """Rob the safest truck the rule still allows, and park who it was.

    SAFEST, not richest: within the rarity the rule asks for, the one with the weakest
    guard goes first. What a robbery is worth is decided by the truck's rarity and how
    far along its road it is, never by how hard its escort hits back — so a stronger
    guard buys nothing and costs troops when the reading was optimistic.
    """
    return ("pcall(function() " + _NUM + _TRUCK_M + _ROB_BOARD + _ROB_RULE + _ROB_OURS +
            _ROB_FITS +
            "if not M then return end "
            "M.__lw_rob_hit=0 M.__lw_rob_owner='' M.__lw_rob_lv=0 M.__lw_rob_pw=0 "
            "M.__lw_rob_qual=0 M.__lw_rob_err='' "
            "local lvl,q,margin,squad,black=_rrule(M) "
            "local ours=_num(M.__lw_rob_ours) "
            "if ours<=0 then M.__lw_rob_err='no reading of our own strength' return end "
            "local l=_rboard() "
            "if l==nil then M.__lw_rob_err='the board is not open' return end "
            "local pick=nil "
            "pcall(function() for _,d in pairs(l) do local t=d.trainData or d "
            "if _rfits(t,lvl,q,margin,black,ours) then "
            "if pick==nil then pick=t "
            "elseif _num(t.quality)>_num(pick.quality) then pick=t "
            "elseif _num(t.quality)==_num(pick.quality) "
            "and _num(t.power)<_num(pick.power) then pick=t end end end end) "
            "if pick==nil then M.__lw_rob_err='nothing on the board passes the rule' return end "
            "M.__lw_rob_owner=tostring(pick.ownerId) M.__lw_rob_lv=_num(pick.ownerLv) "
            "M.__lw_rob_pw=_num(pick.power) M.__lw_rob_qual=_num(pick.quality) "
            "local f=nil pcall(function() f=M:GetAttackFormationByIndex(squad) end) "
            "if f==nil then M.__lw_rob_err='squad '..squad..' is not there' return end "
            "local arr=SFSArray.New() local heroes=0 "
            "pcall(function() for uuid,slot in pairs(f.heroes or {}) do "
            "local o=SFSObject.New() o:PutLong('heroUuid',uuid+0) o:PutInt('index',slot+0) "
            "arr:AddSFSObject(o) heroes=heroes+1 end end) "
            "if heroes==0 then M.__lw_rob_err='squad '..squad..' has no heroes in it' return end "
            "local ok,err=pcall(function() SFSNetwork.SendMessage(MsgDefines.AttackTrain, "
            "pick.uuid+0, arr, pick.serverId+0, 0, _num(f.squadNo)) end) "
            "if not ok then M.__lw_rob_err=tostring(err) return end "
            "M.__lw_rob_hit=1 "
            'CS.UnityEngine.Debug.LogError("ACT rob_press owner="..tostring(M.__lw_rob_owner)'
            '.." lv="..tostring(M.__lw_rob_lv).." power="..tostring(M.__lw_rob_pw)'
            '.." quality="..tostring(M.__lw_rob_qual).." heroes="..tostring(heroes)) end)')


def truck_rob_blacklist_add() -> str:
    """Lua *expression* -> the blacklist with the last target's owner added to it.

    Comma-fenced, and the same owner is never written twice — the recipe hands the answer
    straight to `REMEMBER`, so what comes back is what the next run reads.
    """
    return ("(function() local M=DataCenter.LWMyStationDataManager "
            "local black=tostring(M.__lw_rob_black or '') "
            "local who=tostring(M.__lw_rob_owner or '') "
            "if who=='' then return black end "
            "if (','..black..','):find(','..who..',',1,true) then return black end "
            "if black=='' then black=who else black=black..','..who end "
            "M.__lw_rob_black=black return black end)()")


# ---------------------------------------------------------------------------
# the reward popups: an ear inside the client, not a round of questions (#2027)
# ---------------------------------------------------------------------------
#
# WHAT THIS IS FOR. Half the abilities of this bot end in a modal: a help given to an
# alliancemate's secret task, a gift collected, a truck brought home. The panel presses
# headless, so nobody asked for that window — it lands on top of the client anyway. The
# old answer was a press of its own after each collect (`dismiss_reward_popup` in
# `game_buttons.py`): a sweep of every open window whose name carries `Reward`/`GetGift`.
# It works, and it is a PRESS — it happens only where a recipe remembered to put it, it
# says nothing about what was IN the window, and a popup raised by something the panel
# did not start sits there until the next recipe runs.
#
# So this is an EAR instead, which is what «читаем один раз, дальше слушаем» asks for
# (`CLAUDE.md`). Two of the client's own Lua methods are wrapped ONCE per client:
#
#   * `DataCenter.RewardManager`'s show-methods — the client's own «here is what you were
#     given». They carry the reward list, so this is where WHAT is read.
#   * `UIManager.Instance.OpenWindow` — where the popup arrives, and where it is closed
#     with `Ctrl:CloseSelf()` (never `DestroyAllWindow`, which takes the HUD with it).
#
# Both write into a small ring on `DataCenter.__lw_rewards`, and NOTHING asks the game
# anything: the wrappers run inside calls the client was making anyway. The panel drains
# the ring the next time it is talking to the VM (`actions/collect_reward_popups.md`).
#
# WHY WRAPPING WORKS HERE. Both objects are Lua tables with a class behind a metatable —
# measured live (#2027): `UIManager.Instance` is a table whose metatable's `__index`
# carries `OpenWindow`, and `DataCenter.RewardManager` the same with `ShowCommonReward`
# and its siblings. A `rawset` on the INSTANCE shadows the class for that instance alone,
# so nothing else in the client sees a changed class — the same form #1420 used on
# `UIWorldPointCtrl:InitData` and #1990 on the resource writers.
#
# The ear dies with the client, which is correct: a fresh client has no wrappers and the
# recipe puts them back. It is idempotent — a second install finds `__lw_rewards.on`.
#
# ---------------------------------------------------------------------------
# THREE GUARDS, AND THE ORDER THEY ARE IN MATTERS
# ---------------------------------------------------------------------------
#
# «Close whatever popped up» is the one change here that can break something expensive:
# a mini-game holds its own window for the whole match (#2021), a march holds the squad
# screen, a purchase holds its dialog. Shutting one of those from a wrapper would look
# exactly like the game closing it, and the recipe waiting on it would fail for no
# readable reason. So a window is closed only when ALL THREE hold:
#
#   1. **The name is in :data:`REWARD_WINDOWS`** — an explicit list, never a substring
#      match. A reward-shaped window that is NOT in the list is recorded as `unknown`
#      and LEFT ALONE, which is how the list grows: by evidence a person can read on the
#      «Награды» page, not by a guess made inside a wrapper.
#   2. **A reward show fired in the last :data:`REWARD_WINDOW_MS`** — the game itself
#      said «here is what you were given» microseconds ago. A window that opens outside
#      that span is somebody's press, not a reward.
#   3. **Nothing has claimed a hold.** A recipe that keeps a window of its own for the
#      length of its run sets `DataCenter.__lw_rewards.hold`, and while it is set the ear
#      records (`held`) and closes nothing at all. It is a belt beside the braces: the
#      screens in question are not in the list either, and the two mistakes that would
#      have to happen together are «somebody adds a name» and «somebody removes a flag».
#
# WHY CLOSE AT ALL, EVEN OVER OUR OWN WORK. A reward popup is an acknowledgement of
# something the SERVER has already granted — closing it takes nothing back. What it does
# do is sit on top of the client, where it blocks the vision steps (`FIND`/`CLICK`) and
# any press that goes through the window stack. So the popup is the thing in the way, and
# the hold above is what protects the one case where the window is the work.

#: The windows this ear may close, by NAME. Every one of them exists in the client's own
#: `UIWindowNames` table (pinned by `tests/test_reward_popups.py` against
#: `docs/research/ui-open-data/ui_window_names.json`), and every one is a reward
#: acknowledgement: a list of what was just granted, with nothing to decide on it.
#:
#: **Grow it only with evidence.** An `unknown|<name>` row on the «Награды» page is what
#: says a window belongs here — the ear records those and never closes them.
REWARD_WINDOWS = (
    # Proven live: the modal an alliance-gift collect raises (#1188 era,
    # docs/research/alliance-gift-collection.md).
    "UIGiftPackageRewardGet",
    # The secret-task family — the complaint this task started from: a help given to an
    # alliancemate's task raises one of these headless.
    "UIDispatchTaskReward",
    # The abilities that already end in a reward list of their own.
    "UILWTruckRewardGet", "UIGhostreconReward", "UIGhostreconGetBoxReward",
    "UIDispatchTreasureReward", "UIDispatchTreasureGetBoxReward", "UICollectReward",
    # The generic «here is what you got» tips the client reuses across features.
    "UICommonRewardTip", "UIRewardShow", "UIRewardTip", "UIRewardContentTip",
    "UIGetRewardView", "UICommonBoxRewardShow", "UILWCommonBoxShowRewardTip",
    "UIMultiRewardPop", "UILWGetGiftView",
)

#: The show-methods on `RewardManager` that mean «the player has just been given this».
#: Read off the live class (#2027); a name that is not on it is skipped rather than
#: guessed at, so a client that renames one loses that row and nothing else.
REWARD_SHOWS = (
    "ShowCommonReward", "ShowSingleReward", "ShowGiftReward", "ShowTwoLinesRewards",
    "SequenceShowReward", "ShowCommonHeroReward", "ShowGiftBoxOpenReward",
    "ShowDailyTaskReward", "ShowGeift", "ShowDetectEventCombineReward",
)

#: How long after a reward show a window opening still counts as THAT reward's popup, in
#: milliseconds of the game's own clock. Generous enough for a window that waits for its
#: atlas, short enough that the next thing a person opens by hand falls outside it.
REWARD_WINDOW_MS = 3000

#: How many rows the ring holds before it counts losses instead. A drain empties it and
#: the recipes that earn things drain as they go, so this is a ceiling on a client
#: nobody has played anything through — not a working size.
REWARD_RING = 80


def reward_watch_install() -> str:
    """Lua *chunk* — put the ear in, once. Idempotent, and silent when already in.

    Everything is `pcall`-guarded twice over: this runs on the client's own Lua thread
    INSIDE the game's call to `OpenWindow`, and a wrapper that raises would take the
    window with it.
    """
    shows = ",".join(f"'{name}'" for name in REWARD_SHOWS)
    allow = " ".join(f"W['{name}']=true" for name in REWARD_WINDOWS)
    return (
        "pcall(function() "
        "local D=DataCenter local B=D.__lw_rewards "
        "if B and B.on then return end "
        "B={rows={},lost=0,closed=0,seen=0} D.__lw_rewards=B "
        f"local W={{}} {allow} B.allow=W "
        "local function now() local t=0 "
        "pcall(function() t=UITimeManager.Instance:GetServerTime() end) "
        "return math.floor((tonumber(tostring(t)) or 0)+0) end "
        "local function add(kind,what) B.seen=B.seen+1 "
        f"if #B.rows>={REWARD_RING} then B.lost=B.lost+1 return end "
        "B.rows[#B.rows+1]=tostring(now())..'|'..kind..'|'..tostring(what) end "
        # What was in the reward list. The client's reward rows carry an id and a count
        # under several names depending on which show was called, so each is tried in
        # turn and a row that answers none of them is counted and not named.
        "local function items(v) if type(v)~='table' then return '' end "
        "local out={} local n=0 "
        "for _,it in pairs(v) do if type(it)=='table' then "
        "local id=it.id or it.rewardId or it.itemId or it.rewardType or it.type "
        "local num=it.num or it.count or it.value or it.amount or it.number "
        "if id~=nil then n=n+1 if n<=12 then "
        "out[#out+1]=tostring(id)..'x'..tostring(num or 1) end end end end "
        "if n>12 then out[#out+1]='+'..tostring(n-12) end "
        "return table.concat(out,',') end "
        # -- the reward shows: WHAT was given ---------------------------------
        "local rm=D.RewardManager local rmt=getmetatable(rm) "
        "local rcls=rmt and rawget(rmt,'__index') "
        "if type(rcls)=='table' then "
        f"for _,m in ipairs({{{shows}}}) do local f=rcls[m] "
        "if type(f)=='function' then rawset(rm,m,function(self,...) "
        "local a={...} "
        # THE WISH, asked at every call and never at the install (#2408). The switch
        # on «Триггеры» writes `__lw_rewards_off` through `reward_watch_mute`, and it
        # is a global of its own rather than a field of the ring below: a recipe that
        # earns something re-installs the ear as it goes, and a wish kept in the ring
        # would be rebuilt away by the next collect.
        "pcall(function() if D.__lw_rewards_off then return end local got='' "
        "for i=1,#a do local s=items(a[i]) if s~='' then got=s break end end "
        "B.expect=now() add('reward',m..'|'..got) end) "
        "return f(self,...) end) end end end "
        # -- the window: the three guards, then CloseSelf ---------------------
        "local mgr=UIManager.Instance local mmt=getmetatable(mgr) "
        "local mcls=mmt and rawget(mmt,'__index') "
        "local orig=mcls and mcls.OpenWindow "
        # `table.pack`/`unpack` rather than `{...}`: a window that returns nil in the
        # middle of its results would be truncated by the table constructor, and this
        # wrapper sits in front of EVERY window the client opens — it may not change
        # what the caller gets back by so much as an argument. `unpack` is the 5.1
        # spelling, kept as a fallback so the ear cannot break windows on a client
        # built against an older Lua.
        "local pk=table.pack or function(...) return {n=select('#',...),...} end "
        "local up=table.unpack or unpack "
        "if type(orig)=='function' then rawset(mgr,'OpenWindow',function(self,name,...) "
        "local res=pk(orig(self,name,...)) "
        "pcall(function() if D.__lw_rewards_off then return end local s=tostring(name) "
        # guard 2: the game said «here is a reward» a moment ago. Everything else that
        # opens is somebody's press and is not this ear's business at all.
        f"if not (B.expect and (now()-B.expect)<{REWARD_WINDOW_MS}) then return end "
        # guard 3: a recipe is holding a window of its own — record and touch nothing.
        # The hold carries a DEADLINE rather than a flag, so a recipe that ends without
        # lifting it (a crash, a stop, a mini-game armed and left to play itself) cannot
        # deafen the ear until the client restarts.
        "if B.hold and now()<B.hold then add('held',s) return end "
        # guard 1: the name, explicitly. An unknown one is REPORTED, never closed.
        "if not W[s] then add('unknown',s) return end "
        "local w=self:GetWindow(name) "
        "if w and w.Ctrl and w.Ctrl.CloseSelf then "
        "local ok=pcall(function() w.Ctrl:CloseSelf() end) "
        "if ok then B.closed=B.closed+1 add('closed',s) else add('popup',s) end "
        "else add('popup',s) end end) "
        "return up(res,1,res.n) end) end "
        "B.on=true end)")


def reward_watch_hold(minutes: float = 30.0) -> str:
    """Lua *chunk* — «I am holding a window of my own for this long; close nothing».

    For a recipe whose window IS the work: the mini-game holds its screen for the whole
    match (#2021), a march holds the squad screen. The names of those screens are not in
    :data:`REWARD_WINDOWS` either — this is the second lock on the same door, and it is
    the one that does not depend on a list staying right.

    It carries a DEADLINE, in minutes of the game's own clock, and never a bare flag. A
    recipe that arms something and returns — which is exactly what the mini-game does —
    has nobody left to lift a flag afterwards, and a hold nobody lifts is an ear that
    hears nothing for the rest of the client's life. `minutes=0` lifts it at once.

    Safe to set twice, safe to lift when it was never set, and gone with the client.
    """
    span = max(0.0, float(minutes)) * 60_000
    return ("pcall(function() local B=DataCenter.__lw_rewards if B==nil then return end "
            "local t=0 pcall(function() t=UITimeManager.Instance:GetServerTime() end) "
            "t=math.floor((tonumber(tostring(t)) or 0)+0) "
            f"B.hold=(({span:.0f})>0) and (t+{span:.0f}) or nil end)")


def reward_watch_mute(on: bool) -> str:
    """Lua *chunk* — «hear the reward popups» / «close nothing, say nothing» (#2408).

    THE SWITCH THE CARD ON «Триггеры» MOVES. The wish is a global of its own,
    `DataCenter.__lw_rewards_off`, and deliberately not a field of the ear's own ring:
    a recipe that earns something puts the ear back as it goes
    (`actions/collect_reward_popups.md`), and a wish kept inside the ring would be
    rebuilt away by the next collect — a switch that flips itself back on.

    `on=True` clears the wish, `on=False` sets it. Safe on a client that has never had
    the ear in: the flag is read by the wrappers when they run and by nothing else.
    """
    return ("pcall(function() DataCenter.__lw_rewards_off = %s end)"
            % ("nil" if on else "true"))


# --- Explorer treasure: the chests in the mobile squad's window (#2381) ---------------
#
# The keys («Ключ исследователя», item 771001) are paid out by our OWN secret tasks, and
# `ExplorerTreasureManager` holds the whole of it: `GetTreasureHaveItemNum` is the purse,
# `GetTreasureOpenNeedItemNum` the price of one chest (5), `IsOpen` whether the activity
# runs at all, and `GetGuaranteedTimes` / `GetGuaranteedNeedTimes` the run towards the
# guaranteed reward. The send is `hero.dispatch.explorer.treasure.open` and it takes NO
# parameter — the message class's own `OnCreate(self)` reads nothing, so one send is one
# chest (docs/research/explorer-treasure.md).

def explorer_treasure_state() -> str:
    """Lua *expression* — the whole reading as one `key=value` string.

    Read-only, opens nothing, sends nothing. `have` is the purse, `need` the price,
    `chests` how many the purse buys right now.
    """
    return (
        "(function() local M = DataCenter and DataCenter.ExplorerTreasureManager "
        "if M == nil then return 'open=0 why=no-manager' end "
        "local function num(fn) local v = 0 "
        "pcall(function() v = math.floor((M[fn](M) or 0) + 0) end) return v end "
        "local open = false pcall(function() open = M:IsOpen() and true or false end) "
        "local have, need = num('GetTreasureHaveItemNum'), num('GetTreasureOpenNeedItemNum') "
        "if need <= 0 then need = math.floor(tonumber(M.treasureNeedNum) or 0) end "
        "local chests = (need > 0) and math.floor(have / need) or 0 "
        "local item = num('GetTreasureItemId') "
        "return 'open=' .. (open and 1 or 0) .. ' have=' .. have .. ' need=' .. need "
        ".. ' chests=' .. chests .. ' guar=' .. num('GetGuaranteedTimes') "
        ".. ' guar_need=' .. num('GetGuaranteedNeedTimes') .. ' item=' .. item end)()"
    )


def explorer_treasure_left() -> str:
    """Lua *expression* — how many chests the keys still buy, minus what is kept back.

    `DataCenter.__lw_explorer_keep` is the floor a recipe parks: keys never spent, so a
    person saving up for the guaranteed reward is not emptied by a scheduled run.
    """
    return (
        "(function() local M = DataCenter and DataCenter.ExplorerTreasureManager "
        "if M == nil then return 0 end "
        "local open = false pcall(function() open = M:IsOpen() and true or false end) "
        "if not open then return 0 end "
        "local have, need = 0, 0 "
        "pcall(function() have = math.floor((M:GetTreasureHaveItemNum() or 0) + 0) end) "
        "pcall(function() need = math.floor((M:GetTreasureOpenNeedItemNum() or 0) + 0) end) "
        "if need <= 0 then need = math.floor(tonumber(M.treasureNeedNum) or 0) end "
        "if need <= 0 then return 0 end "
        "local keep = math.floor(tonumber(DataCenter.__lw_explorer_keep) or 0) "
        "local spendable = have - keep "
        "if spendable < 0 then spendable = 0 end "
        "return math.floor(spendable / need) end)()"
    )


def explorer_treasure_open() -> str:
    """Open ONE explorer chest — the game's own «Открыть», with the price gate in front.

    Everything that could make the send pointless is answered before it goes out: no
    manager, the activity not running, no price to read, or a purse that would drop below
    `DataCenter.__lw_explorer_keep`. The refusals are named in the marker line rather than
    swallowed, so a run that opened nothing says WHY.
    """
    return (
        "local M = DataCenter and DataCenter.ExplorerTreasureManager "
        "local sent, why, have, need = 0, '', 0, 0 "
        "if M == nil then why = 'no-manager' else "
        "local open = false pcall(function() open = M:IsOpen() and true or false end) "
        "pcall(function() have = math.floor((M:GetTreasureHaveItemNum() or 0) + 0) end) "
        "pcall(function() need = math.floor((M:GetTreasureOpenNeedItemNum() or 0) + 0) end) "
        "if need <= 0 then need = math.floor(tonumber(M.treasureNeedNum) or 0) end "
        "local keep = math.floor(tonumber(DataCenter.__lw_explorer_keep) or 0) "
        "if not open then why = 'closed' "
        "elseif need <= 0 then why = 'no-price' "
        "elseif have - keep < need then why = 'no-keys' "
        "else local ok = pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.ExplorerTreasureOpen) end) "
        "if ok then sent = 1 else why = 'send-failed' end end end "
        "DataCenter.__lw_explorer = {sent = sent, why = why, have = have, need = need} "
        'CS.UnityEngine.Debug.LogError("ACT explorer_open sent=" .. tostring(sent) '
        '.. " have=" .. tostring(have) .. " need=" .. tostring(need) '
        '.. " why=" .. tostring(why))'
    )


# --- «Скрытые Сокровища» — the weekly compass board (#2382) ----------------------
#
# The event the game calls `Treasure_map_S3` and shows on the tab beside the explorer
# chests: every dig of a treasure map pays a random handful of COMPASSES, and a week's
# worth of them unlocks ten reward tiers, the last of which is the week's whole point.
#
# Three things, and each of them is the client's own answer rather than a number typed
# here (`CLAUDE.md`, «Nothing about one machine is written into the code»):
#
#   * the dig — `hero.dispatch.dig.treasure`, whose ONE argument is the fragment set the
#     event runs on (`ActDispatchTreasureManager.digExchangeType`). Sent positionally:
#     the message class reads nothing off a parameter table, and a table argument leaves
#     the client silent — measured live, the send simply never left;
#   * the score — the compasses in the bag, which is what
#     `DigTreasureBoxRewardManager:GetBoxRewardItemCount()` answers, against
#     `GetMaxNum()` for the week's cap;
#   * the tiers — `GetTreasureBoxRewardList()`, one row per milestone with `target` and
#     `isReward`; `SendGetBoxRewardMessage` takes everything that has been earned and
#     spends none of the score, which was worth one live claim to settle.
#
# THE SCORE DOES NOT MOVE WHILE THE CLIENT RUNS, and that is the one thing a caller must
# know. Measured on 2026-09-02: three digs, the fragments decremented on the wire the
# same second (`push.item.del`), and the compass count read 0 for the six seconds after
# each dig — then 750 the moment the client was restarted. So a loop that waits for the
# score to reach the goal never ends. What is dug is therefore PLANNED once, off the
# score the client is holding, and counted down; the score itself is a reading that
# catches up between sessions.
# The whole measurement is `docs/research/hidden-treasures.md`.


def hidden_treasures_read() -> str:
    """Everything the page shows, in one round trip: score, digs, tiers, the week.

    A reading only — nothing is sent and nothing is spent. Every id comes off the
    client: the activity is `DigTreasureBoxRewardManager:GetActId()`, the fragment set
    is `ActDispatchTreasureManager.digExchangeType`, and the week's two ends are the
    activity's own row in `ActivityListDataManager`.
    """
    return (
        "(function() "
        "local B = DataCenter and DataCenter.DigTreasureBoxRewardManager "
        "local A = DataCenter and DataCenter.ActDispatchTreasureManager "
        "if B == nil or A == nil then return 'open=0 why=no-manager' end "
        "local score, goal, digs, act = 0, 0, 0, 0 "
        "pcall(function() score = math.floor((B:GetBoxRewardItemCount() or 0) + 0) end) "
        "pcall(function() goal = math.floor((B:GetMaxNum() or 0) + 0) end) "
        "pcall(function() digs = math.floor((A:GetCanDigCount() or 0) + 0) end) "
        "pcall(function() act = math.floor((B:GetActId() or 0) + 0) end) "
        # TWO PASSES, and the reason is the lag: a step that has been COLLECTED is the
        # server's own word that its target was reached, and it survives a compass count
        # that has not caught up yet (see the module note). So the highest collected
        # target is a FLOOR under the score, and it is worked out before «which step is
        # waiting» is decided — otherwise a step below the true score would be reported
        # as the next one to reach rather than as one already earned.
        "local tiers, taken, ready, next_at, earned = 0, 0, 0, 0, 0 "
        "local rows = {} "
        "pcall(function() for _, row in ipairs(B:GetTreasureBoxRewardList() or {}) do "
        "tiers = tiers + 1 "
        "local target = math.floor((tonumber(tostring(row.target)) or 0) + 0) "
        "local got = math.floor((tonumber(tostring(row.isReward)) or 0) + 0) "
        "rows[#rows + 1] = {target, got} "
        "if got ~= 0 then taken = taken + 1 "
        "if target > earned then earned = target end end end end) "
        "if earned > score then score = earned end "
        "for _, r in ipairs(rows) do if r[2] == 0 then "
        "if r[1] <= score then ready = ready + 1 "
        "elseif next_at == 0 or r[1] < next_at then next_at = r[1] end end end "
        "local opens, closes, now = 0, 0, 0 "
        "pcall(function() now = math.floor((UITimeManager:GetInstance()"
        ":GetServerSeconds() or 0) + 0) end) "
        "pcall(function() for _, a in pairs(DataCenter.ActivityListDataManager"
        ".activityList or {}) do "
        "if math.floor((tonumber(tostring(a.activityId)) or 0) + 0) == act then "
        "opens = math.floor(((tonumber(tostring(a.startTime)) or 0) / 1000) + 0) "
        "closes = math.floor(((tonumber(tostring(a.endTime)) or 0) / 1000) + 0) "
        "end end end) "
        "local live = (closes == 0 or (now > 0 and now < closes)) and 1 or 0 "
        "return 'open=' .. live .. ' score=' .. score .. ' goal=' .. goal "
        ".. ' digs=' .. digs .. ' tiers=' .. tiers .. ' taken=' .. taken "
        ".. ' ready=' .. ready .. ' next=' .. next_at .. ' earned=' .. earned "
        ".. ' act=' .. act "
        ".. ' opens=' .. opens .. ' closes=' .. closes .. ' now=' .. now "
        "end)()"
    )


def hidden_treasures_plan() -> str:
    """Decide, ONCE, how many digs this run may make, and park the number.

    Read the section above for why this is planned rather than looped on the score: the
    compass count does not move while the client runs, so a press that re-derived «am I
    there yet» from it would dig for ever. The plan is the smallest of three honest
    bounds — the digs the fragments allow, the ceiling the caller set, and what the
    distance to the goal is worth at the event's own AVERAGE pay (`__lw_hidden_pay`).
    """
    return (
        "local A = DataCenter and DataCenter.ActDispatchTreasureManager "
        "local B = DataCenter and DataCenter.DigTreasureBoxRewardManager "
        "local digs, score, goal, why = 0, 0, 0, '' "
        "if A == nil or B == nil then why = 'no-manager' else "
        "pcall(function() digs = math.floor((A:GetCanDigCount() or 0) + 0) end) "
        "pcall(function() score = math.floor((B:GetBoxRewardItemCount() or 0) + 0) end) "
        "pcall(function() goal = math.floor((B:GetMaxNum() or 0) + 0) end) "
        # The floor under a lagging score: the highest reward step the SERVER says has
        # been collected. Without it a second run on the same day plans off the compass
        # count the client froze at, and digs a whole goal's worth of fragments away for
        # nothing — measured on 2026-09-02, when 17 digs took every step and the count
        # still read 750.
        "local earned = 0 "
        "pcall(function() for _, row in ipairs(B:GetTreasureBoxRewardList() or {}) do "
        "local got = math.floor((tonumber(tostring(row.isReward)) or 0) + 0) "
        "local target = math.floor((tonumber(tostring(row.target)) or 0) + 0) "
        "if got ~= 0 and target > earned then earned = target end end end) "
        "if earned > score then score = earned end end "
        "local want = math.floor(tonumber(DataCenter.__lw_hidden_goal) or 0) "
        "if want > 0 and (goal <= 0 or want < goal) then goal = want end "
        "local pay = math.floor(tonumber(DataCenter.__lw_hidden_pay) or 0) "
        "if pay <= 0 then pay = 300 end "
        "local cap = math.floor(tonumber(DataCenter.__lw_hidden_cap) or 0) "
        "local short = goal - score "
        "local plan = 0 "
        "local closes, now = 0, 0 "
        "pcall(function() now = math.floor((UITimeManager:GetInstance()"
        ":GetServerSeconds() or 0) + 0) end) "
        "local act = 0 pcall(function() act = math.floor((B:GetActId() or 0) + 0) end) "
        "pcall(function() for _, a in pairs(DataCenter.ActivityListDataManager"
        ".activityList or {}) do "
        "if math.floor((tonumber(tostring(a.activityId)) or 0) + 0) == act then "
        "closes = math.floor(((tonumber(tostring(a.endTime)) or 0) / 1000) + 0) "
        "end end end) "
        "if why == '' then "
        "if closes > 0 and now > 0 and now >= closes then why = 'week-over' "
        "elseif short <= 0 then why = 'goal-reached' "
        "elseif digs <= 0 then why = 'no-fragments' "
        "else plan = math.ceil(short / pay) "
        "if plan > digs then plan = digs end "
        "if cap > 0 and plan > cap then plan = cap end end end "
        "DataCenter.__lw_hidden_left = plan "
        "DataCenter.__lw_hidden = {plan = plan, digs = digs, score = score, "
        "goal = goal, why = why, done = 0} "
        'CS.UnityEngine.Debug.LogError("ACT hidden_plan plan=" .. tostring(plan) '
        '.. " digs=" .. tostring(digs) .. " score=" .. tostring(score) '
        '.. " goal=" .. tostring(goal) .. " why=" .. tostring(why))'
    )


def hidden_treasures_left() -> str:
    """How many digs the parked plan still has — what `TAP … xall` counts down."""
    return "(math.floor(tonumber(DataCenter.__lw_hidden_left) or 0))"


def hidden_treasures_dig() -> str:
    """Dig ONE treasure map: `hero.dispatch.dig.treasure <set>`.

    The set is the client's own `digExchangeType`, sent positionally — a parameter table
    is accepted by the API and produces no send at all.
    """
    return (
        "local A = DataCenter and DataCenter.ActDispatchTreasureManager "
        "local sent, why, set = 0, '', 0 "
        "local left = math.floor(tonumber(DataCenter.__lw_hidden_left) or 0) "
        "if A == nil then why = 'no-manager' "
        "elseif left <= 0 then why = 'plan-spent' else "
        "pcall(function() set = math.floor((tonumber(tostring(A.digExchangeType)) "
        "or 0) + 0) end) "
        "local digs = 0 "
        "pcall(function() digs = math.floor((A:GetCanDigCount() or 0) + 0) end) "
        "if set <= 0 then why = 'no-set' "
        "elseif digs <= 0 then why = 'no-fragments' "
        "else local ok = pcall(function() "
        "SFSNetwork.SendMessage(MsgDefines.DispatchDigTreasure, set) end) "
        "if ok then sent = 1 DataCenter.__lw_hidden_left = left - 1 "
        "else why = 'send-failed' end end end "
        "local S = DataCenter.__lw_hidden or {} "
        "S.done = math.floor(tonumber(S.done) or 0) + sent S.why = why "
        "DataCenter.__lw_hidden = S "
        'CS.UnityEngine.Debug.LogError("ACT hidden_dig sent=" .. tostring(sent) '
        '.. " left=" .. tostring(DataCenter.__lw_hidden_left) '
        '.. " why=" .. tostring(why))'
    )


def hidden_treasures_claim() -> str:
    """Take every tier the week has already earned — the «подтверждение» of a dig.

    One send does the lot: measured live, claiming with the board standing at 750
    compasses turned BOTH the 300 and the 600 tier to «taken» and left the score where
    it was, so the milestones are not paid for out of the count.
    """
    return (
        "local B = DataCenter and DataCenter.DigTreasureBoxRewardManager "
        "local sent, why = 0, '' "
        "if B == nil then why = 'no-manager' else "
        "local ok = pcall(function() B:SendGetBoxRewardMessage(1) end) "
        "if ok then sent = 1 else why = 'send-failed' end end "
        'CS.UnityEngine.Debug.LogError("ACT hidden_claim sent=" .. tostring(sent) '
        '.. " why=" .. tostring(why))'
    )


def hidden_treasures_ask() -> str:
    """Ask the server for the board — the tiers come back, nothing is spent."""
    return (
        "local B = DataCenter and DataCenter.DigTreasureBoxRewardManager "
        "local sent = 0 "
        "if B ~= nil then "
        "local ok = pcall(function() B:SendMainBoxRewardUIMessage() end) "
        "if ok then sent = 1 end end "
        'CS.UnityEngine.Debug.LogError("ACT hidden_ask sent=" .. tostring(sent))'
    )


def hidden_treasures_digs() -> str:
    """How many digs the fragments still allow — the proof a dig really left.

    The compass count cannot serve as one (it does not move until the client is
    restarted), but the fragments do: the server takes one of each of the seven the
    same second, so this number falling is what says the press was not swallowed.
    """
    return (
        "(function() local A = DataCenter and DataCenter.ActDispatchTreasureManager "
        "if A == nil then return 0 end local n = 0 "
        "pcall(function() n = math.floor((A:GetCanDigCount() or 0) + 0) end) "
        "return n end)()"
    )


def hidden_treasures_note() -> str:
    """Work the whole reading out and PARK it, so a recipe can say it in one short line.

    The Lua belongs here rather than pasted into a scenario (`CLAUDE.md`): the recipe
    presses this and then reads `DataCenter.__lw_hidden_board`.
    """
    return ("DataCenter.__lw_hidden_board = " + hidden_treasures_read() + " "
            'CS.UnityEngine.Debug.LogError("ACT hidden_board " '
            ".. tostring(DataCenter.__lw_hidden_board))")


def hidden_treasures_board() -> str:
    """The parked reading, or an empty string when nothing has been read yet."""
    return "(DataCenter.__lw_hidden_board or '')"


# ---------------------------------------------------------------------------
# «Вернуть» — the rewards a secret task or a trade truck never delivered (#2605)
# ---------------------------------------------------------------------------
#
# Both windows — the command post's hero dispatch and the trade station's departure —
# carry a button called «Вернуть». Behind it is ONE manager,
# `DataCenter.DispatchRecoverManager`, holding two lists of the same shape: a row per
# server day, with everything that day's tasks or trucks earned and nobody took. The
# server keeps them for a few days and then they are gone.
#
# Measured live on two accounts (#2605):
#
# * `dispatchRecoverList` / `trainRecoverList` — the pools, keyed by `customId`, which is
#   the day's own stamp. A row with `state == nil` has NOT been claimed; a claimed one
#   comes back with `state = 1`, which is how a press is judged rather than by the send
#   returning without an error.
# * `ClaimDispatchRecoverReward(customId)` / `ClaimTrainRecoverReward(customId)` — one
#   pool per send. Recorded with the sending layer stubbed (#2598): the frame is
#   `SFSNetwork.SendMessage('dispatch.recover.reward', customId)`, exactly one field wide,
#   and its train twin the same.
# * `GetDispatchRecoverCostStr()` / `GetTrainRecoverCostStr()` answer **0** — claiming a
#   pool is free. It is income that was already earned and never collected, so there is no
#   budget gate here and nothing to refuse.
# * `IsDispatchRecoverOpen()` / `IsTrainRecoverOpen()` say whether the account has the
#   feature at all, and a closed one is answered `nil` rather than `0` so a page draws
#   «unknown» instead of «nothing to take».

_RECOVER_M = ("local M=DataCenter and DataCenter.DispatchRecoverManager ")

#: The two halves, as the manager spells them. `kind` is the recipe's word for one.
_RECOVER_KINDS = {
    "tasks": ("dispatchRecoverList", "IsDispatchRecoverOpen",
              "ClaimDispatchRecoverReward"),
    "trucks": ("trainRecoverList", "IsTrainRecoverOpen",
               "ClaimTrainRecoverReward"),
}


def _recover_parts(kind: str) -> tuple:
    try:
        return _RECOVER_KINDS[kind]
    except KeyError:                        # pragma: no cover — a typo in a caller
        raise ValueError("recover kind must be 'tasks' or 'trucks', not %r" % (kind,))


def recover_pools_ask() -> str:
    """Ask the server for both «Вернуть» lists — what the window sends when it opens.

    A request, not a poll: it is made inside a run that is about to claim, never on a
    clock. The client holds the lists from login and they go stale as days turn over, so
    a run that is about to press asks once first.
    """
    return ("pcall(function() " + _RECOVER_M +
            "if not M then return end "
            "pcall(function() M:RequestRecoverListsBySwitch() end) "
            "pcall(function() M:RequestDispatchRecoverList() end) "
            "pcall(function() M:RequestTrainRecoverList() end) end)")


def recover_pools_left(kind: str) -> str:
    """Lua *expression* -> how many pools of `kind` are still unclaimed.

    `nil` when the account has not got the feature — «unknown», which a page draws as a
    dash. Never `0`, which would read as «nothing to take» on an account that cannot take
    anything at all (the same trap the locked trade station set, `truck-dispatch.md`).
    """
    field, is_open, _ = _recover_parts(kind)
    return ("(function() " + _RECOVER_M +
            "if not M then return nil end local open=false "
            "pcall(function() open=M:" + is_open + "() and true or false end) "
            "if not open then return nil end local n=0 "
            "for _,row in pairs(M." + field + " or {}) do "
            "if row.state==nil then n=n+1 end end return n end)()")


def recover_claim_all(kind: str) -> str:
    """Claim every unclaimed pool of `kind` — one send each, and free.

    One send per pool because the game has no batch for it: `Claim…RecoverReward` takes a
    single `customId`. They go out together and the reply that flips `state` arrives on
    its own; what was SENT is parked, and the recipe re-reads the list afterwards to say
    what actually moved — a send is never taken for a claim (#2585).
    """
    field, is_open, claim = _recover_parts(kind)
    tag = "rec_" + kind
    return ("pcall(function() " + _RECOVER_M +
            "if not M then return end local open=false "
            "pcall(function() open=M:" + is_open + "() and true or false end) "
            "local before,sent=0,0 "
            "if open then for _,row in pairs(M." + field + " or {}) do "
            "if row.state==nil then before=before+1 "
            "if pcall(function() M:" + claim + "(row.customId) end) then sent=sent+1 end "
            "end end end "
            "M.__lw_rec_" + kind + "_before=before M.__lw_rec_" + kind + "_sent=sent "
            'CS.UnityEngine.Debug.LogError("ACT ' + tag + ' before="..tostring(before)'
            '.." sent="..tostring(sent)) end)')


def recover_pools_sent(kind: str) -> str:
    """Lua *expression* -> how many claims the last press put on the wire."""
    _recover_parts(kind)
    return ("(function() " + _RECOVER_M +
            "if not M then return 0 end "
            "return tonumber(M.__lw_rec_" + kind + "_sent) or 0 end)()")
