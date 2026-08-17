# Radar: send squads at the errands that cannot be done on the spot.
# ru: Радар: отправить отряды на задания, которые нельзя выполнить на месте.
#
# The other half of the board. `do_radar_tasks.md` does the two things that are messages
# and nothing else — the «help an alliancemate» errands and the claim. Everything left is a
# TILE ON THE MAP with a squad sent at it, and that is this recipe.
#
# Three steps, and the third one is not a step:
#
#   1. **put the errand on the map.** An errand sits at `state = 3`
#      (`NOT_IN_WORLD`) with no tile until `detect.event.put.point.in.world` is sent. This
#      is the in-game «Перейти» minus the camera flight that follows it.
#   2. **march a free squad at it** — `MarchUtil.SendCreateMarchMessage`, the layer under
#      the game's own `OnCollectSimple` / `OnCollectGarbage` and BELOW the squad-picker
#      window they open. Nothing appears on screen.
#   3. **nothing.** The errand ripens by itself when the squad arrives and does its work,
#      and then it is the ordinary claim — which `do_radar_tasks.md` already does, on its
#      own clock. There is no arrival to wait for here and no third message to send, so
#      this recipe does not sit holding the client for a march's travel time.
#
# ## The target type is never guessed
#
# `MarchTargetType` has 190-odd members and the wrong one sends somebody's squad at
# something they did not ask for. So only pairs the client itself names are shipped:
#
#   * `TREASURE` → `DETECT_TREASURE` — live-proven by `auto_treasure.md`;
#   * `DetectEventPickGarbage` → `PICK_GARBAGE` — `MarchUtil.OnCollectGarbage` mentions
#     that one constant in its bytecode and no other;
#   * `GATHER_RESOURCE` → `SAMPLE` — same, for `MarchUtil.OnCollectSimple`.
#
# **An errand of any other kind is SKIPPED WITH ITS KIND IN THE LOG.** The monster camps,
# the rescues, the fake players, the wandering bosses and the seasonal digs are all left
# for a run that can prove their pair, and the closing line names them by number so the
# next task knows which pair is worth proving. A skipped errand is not lost: it stays on
# the board and can be claimed or marched by hand.
#
# ## The squad gate, and why nothing is dropped
#
# A squad may be sent when it has soldiers in it AND is not already out — a formation with
# no soldiers produces a march the server silently drops (which is what «отправка работает
# через раз» on the treasures turned out to be), and one already on the map cannot go
# twice. Both halves are read from the client: `totalSoldierNum`, and
# `WorldMarchDataManager:GetOwnerFormationMarch`.
#
# With no free squad the press sends nothing and SAYS SO (`radar_march_none
# why=no-free-squad`) — it does not stamp the errand, so the errand comes round again on
# the next run rather than being silently consumed. That is the #1416 rule: an errand this
# recipe could not do is an errand that is still waiting, and the log has to be able to
# prove it.
#
# An errand this recipe HAS marched is stamped on `DataCenter.__lw_radar_marched`, in the
# game VM, so it survives a panel restart and a profile switch the way the treasure queue
# does — no second squad at a tile that already has ours. `forget` clears it, for the case
# where a squad came home with nothing and the errand should be tried again.
#
# The board, the enums and the measurements are in `docs/research/radar.md`.

ARGS place = 1
ARGS forget = 0

IF forget == 0
    LOG "radar-march: keeping the record of what has already been marched"
ELSE
    TAP radar_forget_marched

# The board first: an errand's state and its tile both come from the server.
TAP radar_read_board

IF place == 0
    LOG "radar-march: not putting anything new on the map (place = 0)"
ELSE
    TAP radar_place_points
    WAIT 1.5
    TAP radar_read_board

READ_LUA (function() local M = DataCenter.RadarCenterDataManager local map = {[DetectEventType.TREASURE] = MarchTargetType.DETECT_TREASURE, [DetectEventType.DetectEventPickGarbage] = MarchTargetType.PICK_GARBAGE, [DetectEventType.GATHER_RESOURCE] = MarchTargetType.SAMPLE} local done = DataCenter.__lw_radar_marched or {} local n = 0 if M then for _, e in pairs(rawget(M, 'events') or {}) do local t = rawget(e, 'template') local kind = t and rawget(t, 'type') if kind ~= nil and kind ~= DetectEventType.HELPER and map[kind] ~= nil and rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH and not rawget(e, 'isFrozen') and not done[tostring(rawget(e, 'uuid'))] then n = n + 1 end end end return n end)() INTO marchable
READ_LUA (function() local afd = DataCenter.ArmyFormationDataManager if not afd then return 0 end local n = 0 for _, v in pairs(afd.ArmyFormationList or {}) do local ok, sol = pcall(function() return tonumber(v.totalSoldierNum) or 0 end) if ok and sol > 0 then local out = nil pcall(function() out = WorldMarchDataManager:GetOwnerFormationMarch(v.uuid) end) if out == nil then n = n + 1 end end end return n end)() INTO squads
READ_LUA (function() local M = DataCenter.RadarCenterDataManager local map = {[DetectEventType.TREASURE] = true, [DetectEventType.DetectEventPickGarbage] = true, [DetectEventType.GATHER_RESOURCE] = true} local tally = {} if M then for _, e in pairs(rawget(M, 'events') or {}) do local t = rawget(e, 'template') local kind = t and rawget(t, 'type') if kind ~= nil and kind ~= DetectEventType.HELPER and not map[kind] and rawget(e, 'state') ~= DetectEventState.DETECT_EVENT_STATE_FINISHED and rawget(e, 'state') ~= DetectEventState.DETECT_EVENT_STATE_REWARDED then local k = tostring(kind) tally[k] = (tally[k] or 0) + 1 end end end local out = {} for k, v in pairs(tally) do out[#out + 1] = k .. 'x' .. tostring(v) end table.sort(out) if #out == 0 then return 'none' end return table.concat(out, ' ') end)() INTO skipped

LOG "radar-march: {marchable} errand(s) ready to be marched at, {squads} free squad(s); kinds this cannot march yet: {skipped}"

IF squads == 0
    LOG "radar-march: every squad is out or empty — the errands stay on the board and wait"
    STOP

IF marchable == 0
    LOG "radar-march: nothing of a kind this can march is on the map; skipped kinds are named above"
    STOP

# One squad per press, as many times as there is something to send and somebody to send.
# `xall` re-reads the count, so it stops on whichever runs out first — the errands or the
# squads — and the press says which.
TAP radar_march xall

READ_LUA (function() local M = DataCenter.RadarCenterDataManager local map = {[DetectEventType.TREASURE] = MarchTargetType.DETECT_TREASURE, [DetectEventType.DetectEventPickGarbage] = MarchTargetType.PICK_GARBAGE, [DetectEventType.GATHER_RESOURCE] = MarchTargetType.SAMPLE} local done = DataCenter.__lw_radar_marched or {} local n = 0 if M then for _, e in pairs(rawget(M, 'events') or {}) do local t = rawget(e, 'template') local kind = t and rawget(t, 'type') if kind ~= nil and kind ~= DetectEventType.HELPER and map[kind] ~= nil and rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH and not rawget(e, 'isFrozen') and not done[tostring(rawget(e, 'uuid'))] then n = n + 1 end end end return n end)() INTO marchable
READ_LUA (function() local afd = DataCenter.ArmyFormationDataManager if not afd then return 0 end local n = 0 for _, v in pairs(afd.ArmyFormationList or {}) do local ok, sol = pcall(function() return tonumber(v.totalSoldierNum) or 0 end) if ok and sol > 0 then local out = nil pcall(function() out = WorldMarchDataManager:GetOwnerFormationMarch(v.uuid) end) if out == nil then n = n + 1 end end end return n end)() INTO squads
READ_LUA (function() local ok, n = pcall(function() local c = 0 for _ in pairs(DataCenter.__lw_radar_marched or {}) do c = c + 1 end return c end) return (ok and n) or 0 end)() INTO marched

LOG "radar-march: done — {marched} errand(s) have our squads on them, {marchable} still waiting, {squads} free squad(s) left"
