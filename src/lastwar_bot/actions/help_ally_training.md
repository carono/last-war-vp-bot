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
#     T11IdleGameDataManager:SendIdleGameEventHelpMessage(<owner uid>, <event uuid>, <event id>)
#
# THE DOOR MATTERS, and the live pass is how we know (#2755). `idle.game.event.help` is
# the command underneath, but handing it to `SFSNetwork.SendMessage` as a TABLE is refused
# by the client's own serialiser — the first live plea came back «sent=0 unusable=1» with
# the throw swallowed by the `pcall` around it. The manager's method takes the three
# values POSITIONALLY, in the order `(uid, eventUuid, eventId)`; the other orders are
# refused by the serialiser, which is how the order was established without guessing.
#
# FIVE PLACES, AND THEY GO FAST. `GetInvitePlayerInfoList(eventUuid)` — after asking the
# game for the event with `SendIdleGameEventGetMessage(uid, eventUuid, 0)` — is the
# «места» reading. The first live plea was read 2 minutes after it was said and already
# had its five: joining is a matter of seconds, which is what the standing order is for.
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
READ_LUA (function() local Q = DataCenter.__lw_help_queue or {} local sent, bad, names = 0, 0, {} while #Q > 0 and sent < {limit} do local e = table.remove(Q, 1) local uuid = tonumber(e.uuid) local eid = tonumber(e.eventId) or 0 if uuid and e.uid and e.uid ~= 'nil' then local ok = pcall(function() DataCenter.T11IdleGameDataManager:SendIdleGameEventHelpMessage(tostring(e.uid), uuid, eid) end) if ok then sent = sent + 1 names[#names+1] = tostring(uuid) DataCenter.__lw_help_sent = DataCenter.__lw_help_sent or {} table.insert(DataCenter.__lw_help_sent, { uid = tostring(e.uid), uuid = uuid }) else bad = bad + 1 end else bad = bad + 1 DataCenter.__lw_help_bad = (DataCenter.__lw_help_bad or {}) table.insert(DataCenter.__lw_help_bad, tostring(e.raw or '')) end end return 'sent=' .. sent .. ' unusable=' .. bad .. ' [' .. table.concat(names, ',') .. ']' end)() INTO report
LOG "help sent: {report}"
READ_LUA (function() local B = DataCenter.__lw_help_bad or {} DataCenter.__lw_help_bad = {} if #B == 0 then return 'none' end return table.concat(B, ' || '):sub(1, 400) end)() INTO unusable
# A plea the ear could not read is worth SAYING, not swallowing: the card is the
# only place the event's uuid comes from, so a run that parks one and cannot use it
# is the ear being wrong about the shape rather than the alliance being quiet.
LOG "cards that carried no event: {unusable}"
WAIT 2

# 4. Say what the GAME says came of it, rather than that a press was made: an event the
#    client now lists us on is a help that landed.
READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local me = tostring(LuaEntry.Player:GetUid()) local sent = DataCenter.__lw_help_sent or {} for _, e in ipairs(sent) do pcall(function() M:SendIdleGameEventGetMessage(tostring(e.uid), e.uuid, 0) end) end return 'asked=' .. #sent end)() INTO asked
LOG "asked the game about {asked} event(s)"
WAIT 3
READ_LUA (function() local M = DataCenter.T11IdleGameDataManager local me = tostring(LuaEntry.Player:GetUid()) local done, seen, full = 0, 0, 0 for _, e in ipairs(DataCenter.__lw_help_sent or {}) do seen = seen + 1 local l = nil pcall(function() l = M:GetInvitePlayerInfoList(e.uuid) end) if type(l) == 'table' then local n = 0 local mine = false for _, p in pairs(l) do n = n + 1 if type(p) == 'table' and tostring(p.uid) == me then mine = true end end if mine then done = done + 1 elseif n >= 5 then full = full + 1 end end end DataCenter.__lw_help_sent = {} return 'checked=' .. seen .. ' confirmed=' .. done .. ' full=' .. full end)() INTO landed
LOG "the game's own answer: {landed} — confirmed= the events that now list us among their helpers, full= the ones whose five places were taken before we got there"
