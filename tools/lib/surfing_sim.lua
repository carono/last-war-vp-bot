-- The offline JUDGE for the Street Run autopilot — one implementation, two hosts.
--
-- It steps a virtual avatar at 60 Hz over a field of obstacles, asks `_G.__SR_AI.planRoute`
-- (the very planner the live run uses) what to do, and collides against a *truth* model whose
-- sizes are deliberately independent of the planner's own safety padding: if the planner is
-- wrong about a body, the judge still kills it.
--
-- Hosts:
--   * tools/dev/surfing_simulate.py  — pushes this text into the GAME's Lua VM, so the judge
--     runs against the planner exactly as installed there;
--   * tools/dev/surfing_offline.py   — loads it into a local Lua (lupa) with no game at all,
--     which is ~200x faster and cannot freeze the client.
--
-- Both call the same functions below, so a verdict cannot drift between them.

local SIM = {}
_G.__SR_SIM = SIM

local floor, max = math.floor, math.max

-- The avatar's own motion. These are literals ON PURPOSE — they are the game's constants
-- (Const.LineChangeTime / player.jumpDurationValue / Const.SlideTime), not the planner's
-- opinion of them, so a mistuned cfg cannot make the judge agree with the planner by
-- construction.
SIM.switchTime = 0.16
SIM.jumpTime   = 0.72
SIM.slideTime  = 0.50
SIM.baseX      = 36
SIM.laneOffset = 4
SIM.speedCap   = 60

-- A driving truck is ONCOMING, and it does not set off until the runner is near it. Both
-- halves are measured, not assumed — the human recordings carry every mover's live position
-- frame by frame (results/street_run/human/run_002.txt):
--   * 751 frame-to-frame samples put it at exactly MINUS its declared move_speed. Not one
--     sample has a mover travelling with the runner. The judge used to drive them forward,
--     which over a chained run of several km left them hundreds of metres from where they
--     belong, standing as walls in track they never reach.
--   * a mover more than ~120 units ahead is still sitting on its spawn mark (the last frame
--     one is seen parked is at a gap of 122; below 120 they are essentially always moving).
SIM.moverTrigger = 120

local function laneOf(x)
  local l = floor((x - SIM.baseX) / SIM.laneOffset + 0.5) + 1
  if l < 0 then l = 0 elseif l > 2 then l = 2 end
  return l
end
SIM.laneOf = laneOf

-- One run over one obstacle field.
--   obs   — {{x=, z=, mid=, speed=}, ...} (z is the anchor; `speed` drives it along the track)
--   hole  — {{lane, z0, z1}, ...} seams between chained carriage roofs: a drop, fatal unless airborne
--   roof  — {{lane, z0, z1}, ...} rideable roof spans: while over one, ground obstacles cannot hit
--   accel — units/sec gained per unit of track (0 = the fixed-speed per-band replay)
-- Returns: distance reached, the killing obstacle (nil if it survived), moves issued.
function SIM.once(obs, hole, roof, lane0, speed0, accel, zmax)
  local AI = _G.__SR_AI
  local dt = 1 / 60
  local function spdAt(z)
    local s = speed0 + z * accel
    if s > SIM.speedCap then s = SIM.speedCap end
    return s
  end
  local pz, lane = 0, lane0
  local swT, swFrom, swTo, jT, slT = 0, lane0, lane0, 0, 0
  local dead, frame, t, moves = nil, 0, 0, 0
  local live, window = {}, {}
  for i = 1, #obs do
    live[i] = {x = obs[i].x, z = obs[i].z, mid = obs[i].mid, speed = obs[i].speed}
  end
  -- level 2: is the avatar over a rideable carriage roof in lane `ln` at distance `z`?
  local function onRoofAt(z, ln)
    for i = 1, #roof do
      local r = roof[i]
      if r[1] == ln and z >= r[2] and z <= r[3] then return true end
    end
    return false
  end
  local speed = spdAt(0)
  local airRoof = false     -- took off from a roof: still at roof height until it lands
  -- Flight. Some stretches of track have every lane blocked at once — three oncoming trucks
  -- abreast — and the only way over them is the aeroplane buff. A judge without it declares a
  -- perfectly ordinary route impassable, which is exactly what it used to do.
  local fly, taken = 0, {}
  while pz < zmax and not dead do
    frame = frame + 1
    t = t + dt
    if fly > 0 then fly = fly - dt end
    speed = spdAt(pz)
    for i = 1, #live do
      local o = live[i]
      if o.speed > 0 then
        -- parked on its spawn mark until the runner closes to `moverTrigger`, then oncoming
        if not o.t0 and obs[i].z - pz <= SIM.moverTrigger then o.t0 = t end
        if o.t0 then o.z = obs[i].z - o.speed * (t - o.t0) end
      end
    end
    -- Hopping a seam means leaving one roof and coming down on the next, and for that whole
    -- arc the avatar is at ROOF height — it is not on the road, and the carriage it is about
    -- to land on is a floor, not a wall. Reading the level at the current z alone made the
    -- landing register as ramming the next carriage head-on, so a correctly planned seam hop
    -- still "died" the moment it crossed into the roof it was aimed at.
    local onRoof = onRoofAt(pz, lane) or (jT > 0 and airRoof)
    local z0, z1 = pz, pz + speed * dt
    -- picked up on the way through: a buff is collected by running over it in its lane
    for i = 1, #live do
      local o = live[i]
      local k = AI.kindOverride[o.mid]
      if k and (k.fly or 0) > 0 and not taken[i]
         and o.z >= z0 and o.z < z1 and (k.lanes >= 3 or laneOf(o.x) == lane) then
        taken[i], fly = true, k.fly
      end
    end
    if frame % 2 == 1 and swT <= 0 and jT <= 0 and slT <= 0 then
      local n = 0
      for i = 1, #live do
        local o = live[i]
        if o.z > pz - 10 and o.z < pz + 320 then n = n + 1 window[n] = o end
      end
      for i = #window, n + 1, -1 do window[i] = nil end
      local reach, act, az = AI.planRoute(pz, lane, speed, window, fly > 0, onRoof)
      -- A death report names the killer but never says what the planner believed on the way in.
      -- `SIM.watch` is that missing half: set it and every planning frame is handed over, so a
      -- mistimed hop can be read off the decisions instead of guessed at from the corpse.
      if SIM.watch then
        SIM.watch(pz, lane, speed, act, az, reach, onRoof and 1 or 0, jT > 0 and 1 or 0,
                  slT > 0 and 1 or 0, swT > 0 and 1 or 0)
      end
      if az == 0 and act ~= 0 then
        if act == 1 and lane > 0 then
          swT, swFrom, swTo, lane = SIM.switchTime, lane, lane - 1, lane - 1 moves = moves + 1
        elseif act == 2 and lane < 2 then
          swT, swFrom, swTo, lane = SIM.switchTime, lane, lane + 1, lane + 1 moves = moves + 1
        elseif act == 3 then jT = SIM.jumpTime airRoof = onRoof moves = moves + 1
        elseif act == 4 then slT = SIM.slideTime moves = moves + 1 end
      end
    end
    -- riding a roof: the carriages are floor and ground obstacles are below — no ground
    -- collision. In the air on the aeroplane buff: nothing on the ground reaches at all.
    -- On the ground: the usual solid collisions (carriages are walls, etc.).
    if not onRoof and fly <= 0 then
      for i = 1, #live do
        local o = live[i]
        local k = AI.kindOverride[o.mid]
        if k and k.solid then
          if z1 > o.z - k.back and z0 < o.z + k.front then
            local ol = laneOf(o.x)
            local hit
            if k.lanes >= 3 then hit = true
            elseif swT > 0 then
              -- A lane change hands the runner over at the midpoint; it does NOT stand in both
              -- lanes for the whole 0.16 s. The old rule said it did, and that is not a
              -- geometry the game can have: the measured colliders are 3.48 wide (bounds.json)
              -- against a lane pitch of 4, so there is x between two of them that belongs to
              -- neither. Charging the runner for both lanes over the entire manoeuvre made a
              -- 5.1 m change need a 5.1 m hole in BOTH lanes at once, and on run_002 the gaps
              -- between oncoming trucks are 5 and 6 m — so an exhaustive search of the whole
              -- route stalled at 482 m of 11880 and the stretch was written up as impassable.
              -- It is not: with the handover the same search reaches 5469 m.
              hit = (ol == ((swT > SIM.switchTime * 0.5) and swFrom or swTo))
            else hit = (ol == lane) end
            if k.sideOnly and swT <= 0 then hit = false end   -- ridden head-on, fatal only sideways
            if hit and not (jT > 0 and k.jump) and not (slT > 0 and k.slide) then dead = o end
          end
        end
      end
    end
    -- a seam between two carriage roofs: a drop, lethal unless the avatar is airborne over it
    if not dead and jT <= 0 and fly <= 0 then
      for i = 1, #hole do
        local h = hole[i]
        if h[1] == lane and z1 > h[2] and z0 < h[3] then
          dead = {z = h[2], mid = -1, x = SIM.baseX + SIM.laneOffset * (h[1] - 1), seam = true}
        end
      end
    end
    if swT > 0 then swT = swT - dt end
    if jT > 0 then jT = jT - dt end
    if slT > 0 then slT = slT - dt end
    pz = z1
  end
  return pz, dead, moves
end

-- Replay a list of fields (one per band, or a single chained track) from one start lane.
-- Returns: survivors, fields tried, total distance, and a per-death record.
function SIM.score(bands, holes, roofs, lane0, speed0, accel, zmax)
  local passed, total, dist, deaths = 0, 0, 0, {}
  for bi = 1, #bands do
    local z, dead, moves = SIM.once(bands[bi], holes[bi], roofs[bi], lane0, speed0, accel, zmax)
    total = total + 1
    dist = dist + z
    if dead == nil then
      passed = passed + 1
    else
      deaths[#deaths + 1] = {i = bi, z = z, mid = dead.mid, x = dead.x, obz = dead.z,
                             seam = dead.seam and 1 or 0, moves = moves}
    end
  end
  return passed, total, dist, deaths
end

-- deliberately no trailing `return`: the in-VM host concatenates its own driver after this
-- text, and in Lua a `return` must end its block — a trailing one turns the join into a
-- syntax error. `_G.__SR_SIM` above is how both hosts reach the judge.
