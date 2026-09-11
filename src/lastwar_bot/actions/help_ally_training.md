# Help the alliancemates who asked for it in the Restricted Area Training.
# ru: Помочь союзникам, попросившим о помощи в тренировке запретной зоны.
#
#   run help_ally_training                     -- every plea the ear has parked
#   run help_ally_training {"limit": 1}        -- one of them
#
# WHAT IT IS. «Тренировка в запретной зоне» (`t11_idle_game_name_1`) hands the player
# events, and one of them may be shared to alliance chat — «Дорогие могущественные
# союзники, мне очень нужна ваша помощь!». Alliancemates join it while there are places
# left; both sides are paid (`docs/research/idle-game-alliance-help.md`).
#
# WHAT IT SENDS. One join is one message, headless — no window, no tap, no march:
#
#     idle.game.event.help { targetUid = <owner uid>, eventId = <id>, eventUuid = <uuid> }
#
# read off the client's own message class by handing the send a recording `SFSObject` and
# aborting in `ToBinary`, so the shape was learnt without sending anything.
#
# WHAT IT COSTS. No troops and no march leave the base. What it does spend is the day's
# PARTICIPATION REWARD quota — the game's own «Приз за участие (сегодня получено {0}/{1})»
# — so a help beyond it still lands and is not paid for.
#
# THE PLEAS COME FROM THE EAR, NEVER FROM A SWEEP. The card rides the chat websocket, so
# `watch_ally_training_help.md` parks what the client parsed and this drains that queue;
# nothing here asks the server «is anybody in trouble».
#
# WHAT IT REFUSES, in the game's own words: «Вы уже участвуете в этом событии»
# (`t11_idle_game_desc_50`), «Это событие завершено, проверьте, нужна ли кому-нибудь ещё
# помощь!» (`desc_84` — the places are gone) and «Вы не состоите в том же альянсе, что и
# инициатор этого события» (`desc_85`).
SHARE

# How many pleas one run may answer.
ARGS limit = 5

# 1. Make sure somebody is listening — a client restart wipes the VM and the ear with it.
CALL watch_ally_training_help

# 2. What is waiting.
READ_LUA (function() return #(DataCenter.__lw_help_queue or {}) end)() INTO parked
IF parked == 0
    LOG "nobody has asked for help in the training today"
    STOP

# 3. Join them. The queue entry carries everything the send needs, so this is one round
#    trip per plea and no window is opened.
READ_LUA (function() local Q = DataCenter.__lw_help_queue or {} local sent, bad, names = 0, 0, {} while #Q > 0 and sent < {limit} do local e = table.remove(Q, 1) local uuid = tonumber(e.uuid) local eid = tonumber(e.eventId) or 0 if uuid and e.uid then local ok = pcall(function() SFSNetwork.SendMessage('idle.game.event.help', { targetUid = tostring(e.uid), eventId = eid, eventUuid = uuid }) end) if ok then sent = sent + 1 names[#names+1] = tostring(uuid) DataCenter.__lw_help_sent = DataCenter.__lw_help_sent or {} table.insert(DataCenter.__lw_help_sent, { uid = tostring(e.uid), uuid = uuid }) else bad = bad + 1 end else bad = bad + 1 end end return 'sent=' .. sent .. ' unusable=' .. bad .. ' [' .. table.concat(names, ',') .. ']' end)() INTO report
LOG "help sent: {report}"
WAIT 2

# 4. Say what the GAME says came of it, rather than that a press was made: an event the
#    client now lists us on is a help that landed.
READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local me = tostring(LuaEntry.Player:GetUid()) local done, seen = 0, 0 for _, e in ipairs(DataCenter.__lw_help_sent or {}) do seen = seen + 1 local list = (M.InvitePlayersDict or {})[e.uuid] or (M.InvitePlayersDict or {})[tostring(e.uuid)] if type(list) == 'table' then for _, p in pairs(list) do if type(p) == 'table' and tostring(p.uid) == me then done = done + 1 break end end end end DataCenter.__lw_help_sent = {} return 'checked=' .. seen .. ' confirmed=' .. done end)() INTO landed
LOG "the game's own answer: {landed}"
