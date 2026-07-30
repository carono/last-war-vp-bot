-- Street Run («Уличный забег» / Surfing) autopilot — runs INSIDE the game's Lua VM.
--
-- Why in-VM: driving the runner from Python costs a ~0.1 s round trip per decision (read
-- the scene, decide, press a key through the foreground input), which is 3 units of track
-- per tick and forces the dodge to be a one-step reflex. The runner logic, however,
-- exposes everything needed to play it properly:
--
--   * SurfingLogic.OnUpdate           — a per-frame hook (60 Hz, zero latency);
--   * logic:OnMoveLeft/Right/Up/Down  — the same calls the keyboard/swipe handler makes,
--                                       so no window focus and no key presses are needed;
--   * monsterMgr.showList/farmMonster — every obstacle with exact lane x and world z,
--                                       ~200 units (≈7 s) ahead;
--   * the monster templates           — collide_damage (what actually kills) and the
--                                       prefab (what can be hopped).
--
-- So the whole dodge lives here: every frame it rebuilds the obstacle field, plans a
-- collision-free ROUTE through the look-ahead (a small DP over (distance, lane) states)
-- and issues the first move of that route when it comes due. Planning the whole horizon
-- is what a one-step reflex cannot do: it walks into traps that are two moves deep — a
-- container dead ahead while the only clear lane is two lane-changes away, or a side lane
-- that is clear now and blocked 30 units later.
--
-- Installed by tools/street_run_ai.py, which also reads back the telemetry left in
-- `_G.__SR_AI.stat` / `.log`.

local AI = _G.__SR_AI
if not AI then AI = {} _G.__SR_AI = AI end

AI.version = 21
if AI.enabled == nil then AI.enabled = true end
AI.cfg = AI.cfg or {}
local cfg = AI.cfg
-- geometry / motion (live-read constants; see docs/research/street-run-parkour.md)
cfg.horizon      = cfg.horizon      or 200   -- units of track planned ahead
cfg.switchTime   = cfg.switchTime   or 0.16  -- Const.LineChangeTime
cfg.jumpTime     = cfg.jumpTime     or 0.72  -- player.jumpDurationValue
cfg.slideTime    = cfg.slideTime    or 0.50  -- Const.SlideTime
cfg.lineOffset   = cfg.lineOffset   or 4     -- Const.LineOffset (lane spacing in x)
cfg.baseX        = cfg.baseX        or 36    -- Const.ParkourSceneCenter (centre lane)
-- collision geometry. An obstacle's anchor z is NOT its centre: the subway carriages
-- measure 25-41 units and hang entirely BEHIND their anchor (live-measured, see
-- AI.bounds), so they must be modelled as [z - back, z + front], never as z ± half.
cfg.padSmall     = cfg.padSmall     or 1.0   -- default half-length of a small obstacle
cfg.carUnit      = cfg.carUnit      or 8.24  -- one carriage segment; "_N" suffix = N of them
cfg.moverBack    = cfg.moverBack    or 41.0  -- assumed length of an unmeasured driving truck
cfg.bridgeBack   = cfg.bridgeBack   or 34.0  -- where a bridge gate's near edge sits before z
cfg.roofGap      = cfg.roofGap      or 16.0  -- gap the roof carries across to the next carriage
if cfg.rampSolid == nil then cfg.rampSolid = false end  -- learned: are ramps really rideable?
cfg.padExtra     = cfg.padExtra     or 1.5   -- timing slack added at both ends
-- route costs
cfg.costSwitch   = cfg.costSwitch   or 1.0
cfg.costJump     = cfg.costJump     or 1.6
cfg.costSlide    = cfg.costSlide    or 1.6
-- Mild preference for the centre lane, per unit spent off it. Expressed as a FRACTION of a
-- lane change over the whole horizon, because a fixed per-unit figure silently grows with
-- the horizon: 0.006 was a 0.72 nudge at a 120-unit view and became a 1.2 penalty at 200 —
-- dearer than the lane change itself, which drowned out every other consideration.
cfg.outerShare   = cfg.outerShare   or 0.3   -- centre preference, in lane-changes per horizon
cfg.earlyBias    = cfg.earlyBias    or 0.004 -- per unit of delay before a move: act early
-- Coins are a TIE-BREAK, not a reason. Safety is already absolute — the search only ever
-- expands collision-free states, so nothing unsafe can be chosen at any price. What is left
-- is the choice between routes that are all safe, and there the greedier one wins. The value
-- is bounded so it stays a tie-break: a lane lined with coins for the whole 200-unit horizon
-- (one every 4 units, so 50 of them) is worth 0.50 against a lane change at 1.00, which means
-- coins can tip a decision that is otherwise close but can never buy a swerve on their own.
cfg.coinBonus    = cfg.coinBonus    or 0.01
-- Buffs are worth a detour: a shield eats one fatal hit, a jetpack/morph flies over the
-- track outright. Priced just under a lane change so the route grabs one when it is
-- one step away, and never at the cost of safety (the DP only ever considers safe routes).
-- A shield eats a fatal hit and a jetpack flies over the track outright, so those are worth
-- MORE than a lane change (1.0) — they buy safety rather than spend it, and priced under it
-- the route simply never went and fetched one. Two lanes away costs two changes and stays
-- out of reach, which is the intended limit: fetch what is one step away, no lunging.
cfg.buffBonus    = cfg.buffBonus    or 1.4   -- shield / jetpack / morph / ally
cfg.pickupBonus  = cfg.pickupBonus  or 0.25  -- magnet / double / box: a tie-break like coins
cfg.allowJump    = (cfg.allowJump ~= false)  -- hop barrels/fences; carriages never

AI.stat = AI.stat or {}
AI.log = AI.log or {}
AI.trace = AI.trace or {}
AI.err = nil

local floor, ceil, min, max = math.floor, math.ceil, math.min, math.max

local function logmsg(s)
  CS.UnityEngine.Debug.LogError("SRAI " .. tostring(s))
end
AI.logmsg = logmsg

-- --------------------------------------------------------------------------
-- obstacle classification, from the monster templates (definitive)
-- --------------------------------------------------------------------------
-- collide_damage > 0 is what kills (the player has maxBlood = 1, so any hit is fatal);
-- everything else — coins, buffs, energy — is harmless and only worth collecting.
local function templateOf(mid)
  local tm = DataCenter.SurfingMonsterTemplateManager
  local temps = tm and tm.monsterTemps
  return temps and temps[mid] or nil
end

-- kindOverride lets a caller state the truth about a template the client has not loaded —
-- used by the offline simulator (tools/dev/surfing_simulate.py) so a dry run classifies
-- obstacles exactly as a live run would.
AI.kindOverride = AI.kindOverride or {}

local kindCache = {}
local function kindOf(mid)
  local ov = AI.kindOverride[mid]
  if ov ~= nil then return ov end
  local k = kindCache[mid]
  if k ~= nil then return k end
  local t = templateOf(mid)
  if not t then
    -- unknown template: assume a solid obstacle no action clears (dodge, never hop)
    k = {solid = true, jump = false, slide = false, back = cfg.padSmall,
         front = cfg.padSmall, lanes = 1, speed = 0}
  elseif (t.collide_damage or 0) <= 0 then
    -- harmless: coins score, everything else is a buff worth a small detour
    local mt = t.monster_type or 0
    local strong = (mt == 5) or (mt == 7) or (mt == 8) or (mt == 9)   -- jetpack/shield/ally/morph
    k = {solid = false, jump = false, back = 0, front = 0, lanes = 1, speed = 0,
         buff = (mt ~= 0) and (strong and cfg.buffBonus or cfg.pickupBonus) or nil}
  else
    local a = string.lower(tostring(t.asset or ""))
    -- What clears an obstacle (confirmed by the player): barrels are hopped; the HIGH
    -- fences cannot be jumped at all — they are ducked under; so are the bridge openings.
    -- Carriages and trucks can only be gone around.
    local jumpable = (string.find(a, "mutong", 1, true) ~= nil)
        or (string.find(a, "dizhalan", 1, true) ~= nil)
    local slideable = (string.find(a, "zhalan", 1, true) ~= nil)
        or (string.find(a, "qiao", 1, true) ~= nil)
    -- Carriage pieces are named ..._N and are N segments long, hanging behind the anchor.
    -- The "xiepo" (slope) variants carry a RAMP: those are driven up and ridden along the
    -- roof, so they are entered head-on and are lethal only from the SIDE. The plain
    -- carriages have no ramp and are a wall from every direction. Both facts are from the
    -- player watching a run: three carriages abreast at 741/742/745 with ramps on the
    -- middle and right ones, and the run died by swerving LEFT off the middle ramp into the
    -- rampless carriage. `sideOnly` is that distinction — run into it, never swerve into it.
    local back, front, lanes, ramp, carriage = cfg.padSmall, cfg.padSmall, 1, false, false
    if string.find(a, "chexiang", 1, true) or string.find(a, "truck", 1, true) then
      local n = tonumber(string.match(a, "_(%d+)%.prefab$") or "1") or 1
      back, front = cfg.carUnit * n, 0.2
      -- The driving trucks have never been measured — the "_N" length is a guess read off
      -- the prefab name, and it is the only number in this model nothing confirms. It is
      -- also the prime suspect for the largest group of deaths: nothing known in the lane,
      -- a truck in frame, and the gap to it larger than the guess (1220.1 m against a truck
      -- at 1258 = 38 units, versus the 24.7 the name implies). Until one is measured live,
      -- assume the longest body in the game rather than the shortest reading of the name.
      if (t.move_speed or 0) > 0 then back = max(back, cfg.moverBack) end
      if (t.move_speed or 0) == 0 then
        carriage = true
        ramp = (not cfg.rampSolid) and string.find(a, "xiepo", 1, true) ~= nil
      end
    elseif string.find(a, "qiao", 1, true) then
      -- Bridge pieces span the whole road (a collider 20-64 units wide, so no lane change
      -- answers them) and a live run died on the LEADING EDGE of one, 748.2 m against a
      -- body starting at 745.6 — not somewhere inside it. So the lethal part is the gate at
      -- the near edge, not the 36 units of deck behind it: model a thin full-width bar
      -- there, which a slide can duck.
      back, front, lanes = cfg.bridgeBack, -cfg.bridgeBack + 2.5, 3
    end
    -- move_speed > 0 means the thing drives along the track: at 20 the player overtakes
    -- it slowly, at 40 it runs away — either way it blocks its lane for far longer than a
    -- static obstacle does, which a static model gets badly wrong.
    k = {solid = true, jump = jumpable, slide = slideable, back = back, front = front,
         lanes = lanes, ramp = ramp, carriage = carriage, speed = t.move_speed or 0}
  end
  kindCache[mid] = k
  return k
end
AI.kindOf = kindOf

-- The classification is derived from cfg, so anything that retunes cfg (the learner in
-- tools/lib/surfing_stats.py) has to drop the cache or the old verdicts survive.
function AI.resetKinds()
  kindCache = {}
end

local function laneOfX(x)
  local l = floor((x - cfg.baseX) / cfg.lineOffset + 0.5) + 1   -- 0 = left, 1 = centre, 2 = right
  if l < 0 then l = 0 elseif l > 2 then l = 2 end
  return l
end

-- --------------------------------------------------------------------------
-- the route planner: a DP over (bucket along z, lane)
-- --------------------------------------------------------------------------
-- Buckets are 1 unit of track. From each state the avatar may run on one bucket, start a
-- lane change (which sweeps through BOTH lanes for switchTime seconds) or hop (clearing
-- low obstacles only). A state is only reachable through free track, so any route the DP
-- returns is collision-free under this model; it then maximises the distance reached and,
-- among routes that survive the whole horizon, takes the cheapest one.
local function planRoute(pz, lane0, speed, obstacles, flying)
  local H = cfg.horizon
  local outerBias = cfg.outerShare * cfg.costSwitch / cfg.horizon
  local SW = max(1, ceil(cfg.switchTime * speed))
  local JL = max(2, ceil(cfg.jumpTime * speed))
  local SLD = max(2, ceil(cfg.slideTime * speed))

  -- occupancy per lane: solid = kills a runner; noJump / noSlide = still kills while
  -- airborne / while sliding; reward = coins and buffs, priced as a negative cost
  local solid, noJump, noSlide, reward, side = {}, {}, {}, {}, {}
  for l = 0, 2 do solid[l] = {} noJump[l] = {} noSlide[l] = {} reward[l] = {} side[l] = {} end
  -- Carriages are ridden, not dodged. A "xiepo" piece carries a ramp: the runner drives
  -- up it and then runs along the roof, and the roof carries on over the plain carriages
  -- that follow in the same lane. So a carriage body is only a wall when NOTHING leads up
  -- onto it — which is exactly the layout that killed a run: three carriages abreast with
  -- ramps on two of them, and the rampless one taken by a lane change off the ramp.
  -- Per lane, walk the carriage bodies in order and carry the roof forward across a small
  -- gap; what is on the roof is safe to run into head-on and fatal to swerve into.
  local cars = {[0] = {}, [1] = {}, [2] = {}}
  for i = 1, #obstacles do
    local o = obstacles[i]
    local k = kindOf(o.mid)
    if k.carriage then
      local l = laneOfX(o.x)
      local t = cars[l]
      t[#t + 1] = {z0 = o.z - (o.back or k.back), z1 = o.z + (o.front or k.front), ramp = k.ramp}
    end
  end
  local gaps = {}
  for l = 0, 2 do
    local t = cars[l]
    table.sort(t, function(p, q) return p.z0 < q.z0 end)
    local roofUntil = nil
    for i = 1, #t do
      local c = t[i]
      if c.ramp or (roofUntil and c.z0 - roofUntil <= cfg.roofGap) then
        -- carrying on along the roof: the hole between this carriage and the last one is a
        -- drop to the road and must be HOPPED, not run across (told by the player after a
        -- run rode a truck and fell off its far end)
        if roofUntil and c.z0 > roofUntil then
          gaps[#gaps + 1] = {l = l, z0 = roofUntil, z1 = c.z0}
        end
        c.roof = true
        roofUntil = c.z1
      else
        roofUntil = nil
      end
    end
  end

  for i = 1, #obstacles do
    local o = obstacles[i]
    local k = kindOf(o.mid)
    local l = laneOfX(o.x)
    if k.solid then
      local back = (o.back or k.back) + cfg.padExtra
      local front = (o.front or k.front) + cfg.padExtra
      local l0, l1 = l, l
      if (o.lanes or k.lanes or 1) >= 3 then l0, l1 = 0, 2 end
      -- is this body one the runner can be on top of?
      local sideOnly = false
      if k.carriage then
        if k.ramp then
          sideOnly = true
        else
          local z0 = o.z - (o.back or k.back)
          for _, c in ipairs(cars[l]) do
            if math.abs(c.z0 - z0) < 0.01 and c.roof then sideOnly = true break end
          end
        end
      end
      local v = max(o.speed or 0, k.speed or 0)
      if v > 0 then
        local drift = v / speed - 1
        local rel0 = o.z - pz
        for j = 0, H do
          local rel = rel0 + j * drift
          if rel > -front and rel < back then
            for ll = l0, l1 do
              if sideOnly then side[ll][j] = true else solid[ll][j] = true end
              if not k.jump then noJump[ll][j] = true end
              if not k.slide then noSlide[ll][j] = true end
            end
          end
        end
      else
        local aj = ceil(o.z - back - pz)
        local bj = floor(o.z + front - pz)
        if bj >= 0 and aj <= H then
          for j = max(0, aj), min(H, bj) do
            for ll = l0, l1 do
              if sideOnly then side[ll][j] = true else solid[ll][j] = true end
              if not k.jump then noJump[ll][j] = true end
              if not k.slide then noSlide[ll][j] = true end
            end
          end
        end
      end
    else
      local j = floor(o.z - pz)
      if j >= 0 and j <= H then
        local w = k.buff or cfg.coinBonus
        if (reward[l][j] or 0) < w then reward[l][j] = w end
      end
    end
  end

  for i = 1, #gaps do
    local g = gaps[i]
    local aj = ceil(g.z0 - pz)
    local bj = floor(g.z1 - pz)
    for j = max(0, aj), min(H, bj) do
      solid[g.l][j] = true      -- a hole in the roof: fatal to run into...
      noSlide[g.l][j] = true    -- ...not something a duck helps with...
      -- and deliberately NOT noJump: hopping the gap is exactly how it is crossed
    end
  end

  -- what a stretch of one lane is worth in pickups, so the tie-break is the same whether the
  -- route runs the stretch, changes lane across it or flies over it
  local function rewardOf(l, a, b)
    local sum = 0
    for j = max(0, a), min(H, b) do sum = sum + (reward[l][j] or 0) end
    return sum
  end

  local function freeRun(l, a, b)         -- every bucket in [a,b] clear of solids
    for j = max(0, a), min(H, b) do
      if solid[l][j] then return false end
    end
    return true
  end
  local function freeEnter(l, a, b)      -- as above, plus nothing that kills a side entry
    for j = max(0, a), min(H, b) do
      if solid[l][j] or side[l][j] then return false end
    end
    return true
  end
  local function freeFor(blocked, l, a, b)   -- clear for an action (airborne / sliding)
    for j = max(0, a), min(H, b) do
      if blocked[l][j] then return false end
    end
    return true
  end

  -- Whether a hop/duck started at bucket `i` and lasting `len` buckets actually gets past
  -- something. A jump is an arc, not a box: the avatar is only off the ground in the middle
  -- of it, so the takeoff and landing stretches still collide with everything, and only the
  -- middle stretch clears. Requiring the obstacle to fall inside that middle stretch is what
  -- times the hop — without it the route hops the instant it is legal and comes down right
  -- in front of the barrel (seen live: a run that died at 88.8 m having jumped at 64.6 m).
  -- The last condition also rules out hops that clear nothing, which only make the avatar
  -- busy while a real obstacle closes in.
  local function clears(blocked, l, i, len)
    local lead = max(1, floor(len * 0.15))
    local tail = max(1, floor(len * 0.15))
    local a, b = i + lead + 1, i + len - tail
    if b <= a then return false end
    if not freeRun(l, i + 1, i + lead) then return false end
    if not freeRun(l, i + len - tail + 1, i + len) then return false end
    if not freeFor(blocked, l, a, b) then return false end
    local useful = false
    for j = max(0, a), min(H, b) do
      if solid[l][j] then useful = true break end
    end
    return useful
  end

  -- DP state arrays, flat: idx = i * 3 + lane
  local cost, fact, faz = {}, {}, {}
  local function relax(i, l, c, a, az)
    if i > H then i = H end
    local idx = i * 3 + l
    local cur = cost[idx]
    if cur == nil or c < cur - 1e-9 then
      cost[idx] = c fact[idx] = a faz[idx] = az
    end
  end
  cost[0 * 3 + lane0] = 0
  fact[0 * 3 + lane0] = 0
  faz[0 * 3 + lane0] = -1

  local bestI, bestC, bestIdx = 0, 0, 0 * 3 + lane0
  for i = 0, H do
    for l = 0, 2 do
      local idx = i * 3 + l
      local c = cost[idx]
      if c ~= nil then
        if i > bestI or (i == bestI and c < bestC) then
          bestI, bestC, bestIdx = i, c, idx
        end
        if i < H then
          local a0, z0 = fact[idx], faz[idx]
          local outer = (l == 1) and 0 or outerBias
          -- 1. run on
          if not solid[l][i + 1] then
            relax(i + 1, l, c + outer - (reward[l][i + 1] or 0), a0, z0)
          end
          -- 2. lane change (the sweep must be free in both lanes). The bucket the avatar
          --    is already standing in is not re-checked for its own lane — reaching this
          --    state means it was survived; the lane being entered is checked in full.
          for d = -1, 1, 2 do
            local t = l + d
            if t >= 0 and t <= 2 and freeRun(l, i + 1, i + SW) and freeEnter(t, i, i + SW) then
              local a, az = a0, z0
              if a == 0 then a = (d < 0) and 1 or 2 az = i end
              relax(i + SW, t, c + cfg.costSwitch + cfg.earlyBias * i + outer * SW
                    - rewardOf(t, i + 1, i + SW), a, az)
            end
          end
          -- 3. hop — clears barrels and fences; a jump into a carriage is still fatal
          if cfg.allowJump and clears(noJump, l, i, JL) then
            local a, az = a0, z0
            if a == 0 then a = 3 az = i end
            relax(i + JL, l, c + cfg.costJump + cfg.earlyBias * i + outer * JL
                  - rewardOf(l, i + 1, i + JL), a, az)
          end
          -- 4. slide — the other way past a fence, and the only way through a bridge gate
          --    that spans every lane
          if clears(noSlide, l, i, SLD) then
            local a, az = a0, z0
            if a == 0 then a = 4 az = i end
            relax(i + SLD, l, c + cfg.costSlide + cfg.earlyBias * i + outer * SLD
                  - rewardOf(l, i + 1, i + SLD), a, az)
          end
        end
      end
    end
  end
  return bestI, fact[bestIdx] or 0, faz[bestIdx] or -1
end
AI.planRoute = planRoute

-- --------------------------------------------------------------------------
-- reading the live obstacle field
-- --------------------------------------------------------------------------
local function gather(mm, pz, out)
  local n = 0
  local lim = pz + cfg.horizon + 20
  for _, mon in pairs(mm.showList or {}) do
    if type(mon) == "table" then
      -- `dataZ` is where the thing was PLACED. For the driving trucks that is the spawn
      -- point and never moves, so planning against it aims at a ghost: the truck the run
      -- swerved into was, by dataZ, nowhere near. Movers must be read at their live
      -- position; the parked pieces keep dataZ, which is exact for them.
      local sp = mon.move_speed or 0
      local z = mon.dataZ or mon.z or 0
      if sp > 0 then
        local live = nil
        pcall(function() live = mon:GetPosition().z end)
        if live == nil and type(mon.curWorldPos) == "table" then live = mon.curWorldPos[3] end
        if live then z = live end
      end
      if z > pz - 50 and z < lim then
        n = n + 1
        local mid = mon.monsterId or 0
        local e = AI.extent[mid]
        out[n] = {x = mon.x or cfg.baseX, z = z, mid = mid, speed = sp,
                  back = e and e.back, front = e and e.front, lanes = e and e.lanes}
      end
    end
  end
  -- farmMonster holds what has been placed but not yet spawned into the scene: it extends
  -- the look-ahead well past the render window.
  for _, f in pairs(mm.farmMonster or {}) do
    if type(f) == "table" then
      local z = f.z or f.dataZ or 0
      if z > pz - 10 and z < lim then
        local mid = 0
        local b = f.born
        if type(b) == "table" and type(b.monster) == "table" then mid = b.monster[1] or 0 end
        n = n + 1
        out[n] = {x = f.x or cfg.baseX, z = z, mid = mid}
      end
    end
  end
  for i = #out, n + 1, -1 do out[i] = nil end
  return n
end

-- --------------------------------------------------------------------------
-- collider measurement
-- --------------------------------------------------------------------------
-- How long an obstacle actually is along the track decides whether a gap is real; guessing
-- it makes the planner either reckless or so timid it declares a passable stretch a wall.
-- The first time each prefab is seen its collider bounds are read off the live object and
-- kept in AI.bounds (relative to the obstacle's own z), for tools/dev to harvest.
AI.bounds = AI.bounds or {}
AI.extent = AI.extent or {}
local COL_TYPE = nil

local function measure(mon)
  local mid = mon.monsterId
  if not mid or AI.extent[mid] then return end
  local ok = pcall(function()
    local go = mon.gameObject
    if COL_TYPE == nil then COL_TYPE = typeof(CS.UnityEngine.Collider) end
    local col = go:GetComponentInChildren(COL_TYPE)
    if col == nil then AI.extent[mid] = false return end
    local b = col.bounds
    local z = mon.dataZ or mon.z or 0
    local back, front = z - (b.center.z - b.size.z / 2), (b.center.z + b.size.z / 2) - z
    local lanes = (b.size.x > 6) and 3 or 1
    AI.extent[mid] = {back = back, front = front, lanes = lanes}
    -- height matters as much as length: the hop tops out at 3.24 (jumpVo 16.5, gravity
    -- -42), so whether a fence can be cleared is a question of sy, not of its name.
    -- dontCollide is the game's own list of what the obstacle ignores.
    local dc = ""
    if type(mon.dontCollide) == "table" then
      for k2, v2 in pairs(mon.dontCollide) do dc = dc .. tostring(k2) .. ":" .. tostring(v2) .. "," end
    end
    AI.bounds[go.name] = string.format("back=%.2f front=%.2f sx=%.2f dx=%.2f sy=%.2f y0=%.2f dc=%s",
      back, front, b.size.x, b.center.x - (mon.x or cfg.baseX), b.size.y,
      b.center.y - b.size.y / 2, dc == "" and "-" or dc)
  end)
  if not ok then AI.bounds["_error"] = "measure failed" end
end

-- --------------------------------------------------------------------------
-- the per-frame tick
-- --------------------------------------------------------------------------
local obsBuf = {}

local function tick(logic)
  if not AI.enabled then return end
  local p = logic.player
  if not p then return end
  local st = AI.stat
  local mm = logic.monsterMgr
  if not mm then return end

  local pos = p:GetPosition()
  local pz = pos.z
  local speed = 30
  local okS, sp = pcall(function() return logic:GetMoveSpeed() end)
  if okS and sp and sp > 0 then speed = sp end

  -- Death is the only thing that tells the route where it was wrong, so the moment the
  -- avatar dies the surroundings are frozen into AI.death: what killed it, in which lane,
  -- and everything within reach at that instant. Without this the loop is guesswork.
  -- The check runs BEFORE the running-state gate: the run leaves state 3 the same frame
  -- it dies, so gating on it first would miss every death.
  local dying = (p.curBlood or 0) <= 0 or logic.state ~= 3
  if dying then
    if not st.dead and st.frames and st.frames > 0 then
      st.dead = true
      st.deathz = pz
      st.deathspeed = speed
      st.deathlane = laneOfX(pos.x)
      -- Height and lane offset say what the obstacle list cannot: y well above 0 means the
      -- avatar was up on a carriage roof, and an x between lanes means it died mid-change.
      st.deathy = pos.y
      st.deathx = pos.x
      st.deathanim = tostring(p.curAnimName)
      -- anything else alive in the scene (the runner has a chasing hunter NPC)
      local u = {}
      pcall(function()
        for _, un in pairs(logic.unitMgr and logic.unitMgr.units or {}) do
          if type(un) == "table" and un ~= p then
            local nm = tostring(un.__cname or un.name or "?")
            local uz = 0
            pcall(function() uz = un:GetPosition().z end)
            u[#u + 1] = string.format("%s@%.0f", nm, uz)
          end
        end
      end)
      st.deathunits = table.concat(u, ",")
      local d = {}
      for _, mon in pairs(mm.showList or {}) do
        if type(mon) == "table" then
          local z = mon.dataZ or mon.z or 0
          if (mon.move_speed or 0) > 0 then
            pcall(function() z = mon:GetPosition().z end)
          end
          if z > pz - 25 and z < pz + 130 then
            local nm = "?"
            pcall(function() nm = mon.gameObject.name end)
            d[#d + 1] = string.format("%s|%.1f|%s|%s|%s", tostring(mon.x), z,
                tostring(mon.monsterId), tostring(mon.move_speed), nm)
          end
        end
      end
      AI.death = d
    end
    st.state = logic.state
    return
  end
  st.state = logic.state
  st.dead = false

  -- lane: while a change is in flight, plan from the lane being ENTERED (targetX is stale
  -- once the change has finished, so it is only trusted while the timer runs)
  local changing = (p.lineChangeTimer or 0) > 0
  local lane = laneOfX((changing and p.targetX) or pos.x)

  st.z = pz
  st.lane = lane
  st.speed = speed
  st.frames = (st.frames or 0) + 1
  if pz > (st.maxz or 0) then st.maxz = pz end

  -- do not stack commands: one lane change at a time, and never mid-hop
  local busy = changing
  if not busy then
    local okJ, jumping = pcall(function() return p:IsJumping() end)
    local okS2, sliding = pcall(function() return p:IsSliding() end)
    busy = ((okJ and jumping) or (okS2 and sliding)) or false
  end

  -- a few prefabs measured every 20 frames: already-known ones cost a table lookup, so
  -- every kind on the track gets recorded within a run without loading the frame
  if (st.frames % 20) == 0 then
    local c = 0
    for _, mon in pairs(mm.showList or {}) do
      local mz = mon.dataZ or 0
      if type(mon) == "table" and (mon.move_speed or 0) > 0 then
        pcall(function() mz = mon:GetPosition().z end)
      end
      if type(mon) == "table" and mz > pz and mz < pz + 60 then
        measure(mon)
        c = c + 1
        if c >= 6 then break end
      end
    end
  end

  local flying = false
  local okF, fly = pcall(function() return p:IsFlying() end)
  if okF and fly then flying = true end
  st.flying = flying

  local n = gather(mm, pz, obsBuf)
  local reach, act, az = planRoute(pz, lane, speed, obsBuf, flying)
  st.reach = reach
  st.act = act
  st.actz = az
  st.obs = n

  -- a rolling trace of the last few seconds: the run's own account of what it saw and
  -- decided, which is what a death has to be read against
  local T = AI.trace
  if (st.frames % 3) == 0 then
    T[#T + 1] = string.format("%.1f|%d|%d|%d|%d|%d", pz, lane, act, reach, n, busy and 1 or 0)
    if #T > 300 then table.remove(T, 1) end
  end

  if busy or act == 0 or az ~= 0 then return end
  if act == 1 then logic:OnMoveLeft()
  elseif act == 2 then logic:OnMoveRight()
  elseif act == 3 then logic:OnMoveUp()
  elseif act == 4 then logic:OnMoveDown() end
  st.moves = (st.moves or 0) + 1
  local L = AI.log
  L[#L + 1] = string.format("%.1f|%d|%d|%d|%d", pz, lane, act, reach, n)
  if #L > 400 then table.remove(L, 1) end
end

-- --------------------------------------------------------------------------
-- installation: wrap OnUpdate once, keep the original behaviour intact
-- --------------------------------------------------------------------------
local SL = require("DataCenter.LWBattle.Logic.Surfing.SurfingLogic")

if SL.__srai_orig == nil then
  SL.__srai_orig = SL.OnUpdate
end
SL.OnUpdate = function(self, ...)
  local r = SL.__srai_orig(self, ...)
  _G.__SR_LOGIC = self
  local ok, err = pcall(tick, self)
  if not ok then
    if AI.err ~= tostring(err) then
      AI.err = tostring(err)
      logmsg("tick-error " .. AI.err)
    end
  end
  return r
end

-- also capture the instance the moment a run starts, so a probe can read it before the
-- first frame of the runner
if SL.__srai_start == nil then
  SL.__srai_start = SL.OnStart
  SL.OnStart = function(self, ...)
    _G.__SR_LOGIC = self
    AI.stat = {frames = 0, moves = 0, maxz = 0}
    AI.log = {}
    return SL.__srai_start(self, ...)
  end
end

logmsg("installed v" .. AI.version)
