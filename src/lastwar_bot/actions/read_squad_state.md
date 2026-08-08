# Read what every squad is doing right now, and the stamina left on the account.
# ru: Прочитать, чем занят каждый отряд, и сколько осталось стамины.
#
# A READ, and nothing else: it presses nothing, opens nothing and changes nothing, so it
# is safe to run beside anything (and beside another action — a read does not take the
# game's lease). One run answers the two questions every send has to ask first:
#
#   * **is this squad at home?** A rally, a gather, an attack — all of them start from a
#     squad standing in the base. A squad already out is the everyday reason a send
#     "did nothing": the game refuses it and the recipe fails at the last step, minutes
#     after the operator asked for it.
#   * **is there stamina for it?** It is one pool for the whole account, it refills by
#     itself, and a run started with none of it left cannot finish.
#
# The answer lands in ONE variable, `squads`, as one line of records separated by
# « | ». The first record is the account:
#
#     stamina=101 max=120 full=1785777706685
#
# `full` is when the pool is back to `max`, in epoch milliseconds (0 when it is already
# full). Every record after it is one squad, in the slot order the player sees:
#
#     squad=2 state=1 free=0 soldiers=3123 status=WAIT_RALLY march=ASSEMBLY_MARCH \
#             team=1399660254475822866 point=749650 arrive=1785766040800
#
#   * `state`   — the game's own `ArmyFormationState`: 0 Free (at home), 1 March,
#                 2 Prison, 3 Death (разбит), 4 GoHome, 5 Revival, 6 Prison_PickDNA,
#                 7 StationBuilding, 8 Formation.
#   * `free`    — the game's own «this squad is idle» answer (`IsFree()`), 1 or 0. It is
#                 read beside `state` on purpose: it is what the game itself gates on.
#   * `status`  — what the squad's march is doing, by NAME out of `MarchStatus`:
#                 `MOVING`, `COLLECTING` (добывает), `WAIT_RALLY` / `IN_TEAM` (стоит в
#                 стягивании), `ATTACKING`, `BACK_HOME`, `STATION`, … `-` when the squad
#                 has no march at all.
#   * `march`   — what KIND of march it is, by name out of `NewMarchType`
#                 (`ASSEMBLY_MARCH` is a rally, `MONSTER`, `BOSS`, `SCOUT`, …).
#   * `team`    — the rally id the march belongs to, `0` for a march of its own.
#   * `point`   — the tile it is heading for, `-` when there is no march.
#   * `arrive`  — when it gets there, epoch milliseconds (0 when unknown).
#
# A field the game will not answer is left at its «unknown» value rather than guessed:
# every read is wrapped, so a manager that is not loaded yet costs one dash and not the
# whole line. A squad whose march cannot be resolved still reports its `state`, which is
# what the at-home gate is really made of.
#
# The same three facts — the state, the idle flag and the march's `MarchStatus` — are
# what `create_rally.md` asks about ONE squad before it raises a banner, and what
# `join_rally.md` sieves its squads with. They read them the same way and mean the same
# thing by them; docs/research/squad-state.md is where that mapping is written down once.
#
# The panel keeps this in one place for every tab that needs it —
# `panel/runtime/squads.py` polls this recipe and hands the parsed answer around
# (`rt.squads`), so the full panel and a single tab opened on its own
# (`python -m panel.tabs.rally`) read the same thing the same way. The game side is
# written up in docs/research/squad-state.md.
#
# Read live off a running client (task #1222): the enums, the per-squad state, the
# stamina pool and its refill time all come back. What has NOT been seen live yet is a
# squad that is actually out — every squad was home when it was read — so the `status` /
# `march` / `team` half is best-effort until a march is caught in one.

# The whole answer is one line in one variable — no LOG line after it, because a poll
# runs this every few seconds and the interpreter already traces what it read.
READ_LUA (function() local afd = DataCenter.ArmyFormationDataManager local P = LuaEntry.Player local wm = DataCenter.WorldMarchDataManager local function num(v) local n = tonumber(v) if n == nil then return 0 end return math.floor(n) end local function name(v) local s = tostring(v) return (s:match("^[%u%d_]+")) or "-" end local parts = {} local cur, max, full = 0, 0, 0 pcall(function() cur = num(P:GetCurStamina()) end) pcall(function() max = num(afd:GetConfigData().FormationStaminaMax) end) pcall(function() full = num(P:GetStaminaFullTime()) end) local pool = 0 pcall(function() pool = num(DataCenter.SoldierDataManager:GetPlayerSoldiersTotalNum()) end) parts[#parts+1] = "stamina="..cur.." max="..max.." full="..full.." pool="..pool local rows = {} for _, f in pairs(afd.ArmyFormationList) do rows[#rows+1] = f end table.sort(rows, function(a,b) return (tonumber(a.index) or 0) < (tonumber(b.index) or 0) end) for _, f in ipairs(rows) do local st, free, sol = -1, 0, 0 pcall(function() st = num(f.state) end) pcall(function() free = f:IsFree() and 1 or 0 end) pcall(function() f:ConscriptSoldier() end) pcall(function() sol = num(f.totalSoldierNum) end) local fits = 0 pcall(function() fits = num(f:GetAllHeroSoldierCapacity()) end) local status, kind, team, point, arrive = "-", "-", "0", "-", 0 pcall(function() local m = wm:GetOwnerFormationMarch(P.uid, f.uuid, P.allianceId) if m ~= nil then pcall(function() status = name(m.status) end) pcall(function() kind = name(m.type) end) pcall(function() team = tostring(m.teamUuid) end) pcall(function() point = tostring(m.targetPos) end) pcall(function() arrive = num(m.endTime) end) end end) parts[#parts+1] = "squad="..num(f.index).." state="..st.." free="..free.." soldiers="..sol.." fits="..fits.." status="..status.." march="..kind.." team="..team.." point="..point.." arrive="..arrive end return table.concat(parts, " | ") end)() INTO squads
