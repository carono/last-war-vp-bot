# Stand an ear on the special resource-collect points the map announces, and send a free squad at one.
# ru: Караул на спец-сбор ресурсов: ловить объявление точки и отправлять свободный отряд.
#
# WHAT THE SERVER SAYS, MEASURED (#2406, live client, 60 s of an ordinary session):
#
#     push.user.collect.reward.create
#         {uuid, pointId, type, contentId, expireTime, reward, rewardStatStr}
#
# That is the whole announcement, and it is the ONLY thing that carries the tile: the
# client's own list (`CollectRewardDataManager.collectRewardList`) is filled from this
# push and holds the same five numbers, while the alliance's shared list
# (`WorldPointDetailManager.worldAllianceResourceDataList`) carries a uuid, a remainder
# and an owner — and NO coordinate at all. Two days of #2406 went on trying to turn that
# uuid into a place; the push had the place all along.
#
# WHY AN EAR AND NOT A CLOCK. There is one moment a point exists and nothing before it:
# the push. Asking the server for the list on a clock is exactly the background question
# `CLAUDE.md` forbids, and the point is taken by whoever gets there first, so a clock
# would also be slower than the thing it replaced. So the send is made INSIDE the call
# that delivered the announcement — `SFSNetwork.HandleMessage`, the same ingress
# `watch_fireworks.md` presses from, at no cost to anything else.
#
# WHAT LEAVES: one ordinary gather march. `MarchUtil.SendCreateMarchMessage(formation,
# MarchTargetType.COLLECT, pointId, 0, 1, 1, false, serverId, nil)` — the layer under the
# squad screen, the same call `do_radar_marches.md` has been sending at resource points
# since #1473, with the tile's uuid left at 0 the way a mine's is. It goes through
# `TimerManager:DelayInvoke` because a march sent from the hijack thread is dropped
# silently (docs/research/attack-and-scout.md).
#
# THE GATES, all local, all before anything leaves:
#   * the announcement has no `pointId` — nothing to march at, so it is counted and
#     dropped rather than guessed at;
#   * already sent at — the uuid of every point marched at is kept for the session, so
#     the same push parsed twice sends once;
#   * expired — `expireTime` against the GAME's clock (`GetServerTime`, ms), never the
#     PC's (docs/research/game-clock.md);
#   * no free squad among the ones this ear was given — counted as «занят», not waited
#     for. That is the rule of `panel/runtime/squad_gate.py` said in Lua: a squad that is
#     out means skip, and the next announcement is a fresh chance.
#
# WHICH SQUADS IT MAY SPEND is an argument, and the default is the two nobody else has:
# slot 1 stands with the rally auto-join and slot 2 with the golden hunt, so this ear is
# handed 3 and 4. A slot that is marching, gathering, in a rally or in battle is not free
# and is skipped — `state == 0` and the formation's own `IsFree()`, both, because a squad
# walking home answers one of them and not the other.
#
# The ear keeps its own ring in `DataCenter.__lw_crw`. A client restart takes the VM and
# the hook with it, so the trigger `collect_reward_watch` re-plays this recipe when the
# flag is gone — one round trip, and it says «уже стоит» when it is still there.
ARGS squads = [3, 4]

LUA DataCenter.__lw_crw_squads = { {squads} }

READ_LUA (function() local VER = 2406 local B = DataCenter.__lw_crw if B ~= nil and B.on and (tonumber(B.ver) or 0) == VER then B.allow = DataCenter.__lw_crw_squads return 'уже стоит: услышал ' .. B.heard .. ', отправил ' .. B.sent .. ', пропустил ' .. B.skipped .. ', не смог ' .. B.failed end local replaced = '' if B ~= nil and B.on then B.on = false replaced = ' (сняли прежний караул версии ' .. tostring(B.ver or 'до 2406') .. ')' end B = {on = true, ver = VER, heard = 0, sent = 0, skipped = 0, failed = 0, gone = 0, blind = 0, err = '', seen = {}, rows = {}, allow = DataCenter.__lw_crw_squads} DataCenter.__lw_crw = B local function note(word) B.rows[#B.rows + 1] = word while #B.rows > 20 do table.remove(B.rows, 1) end end local function freeSquad() local allow = B.allow if type(allow) ~= 'table' or #allow == 0 then allow = {3, 4} end local pick = nil pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do local idx = math.floor((tonumber(v.index) or -1) + 0) local wanted = false for _, want in ipairs(allow) do if math.floor((tonumber(want) or -1) + 0) == idx then wanted = true end end if wanted and pick == nil then local st = math.floor((tonumber(v.state) or -1) + 0) local idle = true local ok, r = pcall(function() return v:IsFree() end) if ok and r ~= nil then idle = (r and true or false) end local men = math.floor((tonumber(v.totalSoldierNum) or 0) + 0) if st == 0 and idle and men > 0 then pick = {uuid = v.uuid, slot = idx, men = men} end end end end) return pick end local function take(msg) B.heard = B.heard + 1 local pid = math.floor((tonumber(tostring(msg.pointId or 0)) or 0) + 0) local key = tostring(msg.uuid or '') if pid <= 0 then B.blind = B.blind + 1 note('без координаты') return end if key ~= '' and B.seen[key] then B.skipped = B.skipped + 1 note('уже отправляли') return end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerTime() or 0) + 0) end) if now <= 0 then now = os.time() * 1000 end local exp = math.floor((tonumber(tostring(msg.expireTime or 0)) or 0) + 0) if exp > 0 and exp <= now then B.skipped = B.skipped + 1 note('просрочена') return end local squad = freeSquad() if squad == nil then B.skipped = B.skipped + 1 note('нет свободного отряда для точки ' .. pid) return end local srv = 0 pcall(function() srv = math.floor((tonumber(tostring(LuaEntry.Player.serverId)) or 0) + 0) end) if key ~= '' then B.seen[key] = true end local f = squad.uuid local okSend, why = pcall(function() TimerManager:GetInstance():DelayInvoke(function() pcall(function() MarchUtil.SendCreateMarchMessage(f, MarchTargetType.COLLECT, pid, 0, 1, 1, false, srv, nil) end) end, 0.1) end) if okSend then B.sent = B.sent + 1 note('отряд ' .. squad.slot .. ' пошёл на точку ' .. pid) else B.failed = B.failed + 1 B.err = tostring(why) if key ~= '' then B.seen[key] = nil end note('клиент отказал') end end local hm = SFSNetwork.HandleMessage SFSNetwork.HandleMessage = function(cmd, msg, ...) local out = hm(cmd, msg, ...) if B.on then pcall(function() local c = tostring(cmd or '') if c == 'push.user.collect.reward.create' then take(msg or {}) elseif c == 'push.user.collect.reward.remove' then B.gone = B.gone + 1 end end) end return out end return 'караул встал' .. replaced end)() INTO armed

LOG "Спец-сбор ресурсов: {armed}"
