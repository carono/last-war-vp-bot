# Answer a treasure the alliance announced: send the nearest free squad, take the gift.
# ru: Отработать сокровище, о котором объявил альянс: отправить ближайший свободный отряд и забрать подарок.
#
#   run auto_treasure                        -- any squad may go
#   run auto_treasure {"squads": [3, 4]}     -- only squads 3 and 4
#
# WHAT THIS ANSWERS, AND WHY IT IS NOT A SWEEP OF THE MAP. A world-map chest is out for
# minutes and the whole alliance digs it together, so by the time a periodic scan of the
# map noticed one it would be gone — and each scan costs a request per look. The client
# is told the moment somebody shares a chest into alliance chat, and that message names
# everything the ability needs: the chest's uuid, its server and its tile. So the ear goes
# where the news already lands (a hook on the client's own two network doors, #1277) and
# this recipe is what happens afterwards.
#
# IT CANNOT BE A WIRE TRIGGER, and that is a measurement rather than a preference. The
# announcement is a chat post, and the chat broadcast rides a TLS websocket this
# repository cannot decode (`docs/research/chat-system.md`): in the 2026-08-08 recording
# the message is in the Lua trace and NOT in the capture taken beside it. The panel's
# ordinary wire listener is deaf to it by construction. What the trigger polls instead is
# a LOCAL Lua table — one daemon round trip, ~0.15 s with the daemon free, no request to
# the server and nothing the game can notice — so the «poll» in the catalogue is a poll of
# the panel's own ear, never of the world.
#
# EVERY STEP IS WRITTEN DOWN IN THE GAME VM, not here. A chest walks
# announced → squad sent → dug → claimed, and each stage is stamped on the target
# (`DataCenter.__lw_treasure_auto`), so a run interrupted anywhere is picked up by the
# next one instead of starting over: no second squad on a chest that already has ours, no
# claim on a chest already paid. The queue survives a panel restart and a profile switch
# because it lives where the client lives.
#
# «NEAREST» IS SAID PLAINLY AND ITS LIMIT WITH IT. A squad has no position of its own —
# a formation carries its army, its slot and its heroes, and no tile — and a squad that is
# free is standing in the base. So all free squads are the same distance away, and the
# only place the word can be earned is the CHEST: the nearest chest is worked first, and
# the report says the distance it went by. A squad already out is never counted as nearer,
# because it is not free.
#
# The protocol, the trace it came from and what is still unproven:
# `docs/research/world-treasures.md`. The primitives are `treasure_auto_*` in
# `tools/lib/lua_actions.py`.

ARGS squads = [1, 2, 3, 4]
ARGS grace = 240
ARGS ttl = 1800

# What this run may spend, parked where the press can read it — a `TAP` takes no
# arguments of its own. `grace` is how long after the march a claim may be tried without
# having heard the alliance's own «this chest is dug»; `ttl` is when a chest is written
# off as gone from the map.
LUA DataCenter.__lw_treasure_squads = { {squads} } DataCenter.__lw_treasure_grace = {grace} DataCenter.__lw_treasure_ttl = {ttl}

# The ear first, and it is idempotent: the hook is wrapped once however often this runs,
# and re-arming never throws the queue away. A client restarted since the last run has a
# fresh VM and no hook at all, which is exactly the case this covers — and the one the
# trigger's poll treats as work in its own right.
TAP treasure_auto_arm

# The whole queue, one step each, in ONE press: the nearest free squad marches onto the
# nearest chest, and a chest the alliance has already dug is claimed. Nothing is opened
# on screen by it.
TAP treasure_auto_step

# What it did, chest by chest. A reading, so it costs a chest nothing — the sends are
# already away.
READ_LUA (DataCenter.__lw_treasure_auto and DataCenter.__lw_treasure_auto.report or "the step left no report — the press did not run") INTO report

LOG "the line above is what the run did: sent= marches that went out, claimed= claims sent, paid= gifts actually received (the reward window came up), waiting= chests whose squad is still out or whose claim has not answered, and one note per chest"

# One number: how many sends this run actually made. `0` is an ordinary quiet minute —
# nothing was announced, or the squads are all out — and not a failure.
READ_LUA (function() local A = DataCenter.__lw_treasure_auto if A == nil then return 0 end return tonumber(A.did) or 0 end)() INTO did

# A SQUAD THAT READS EMPTY IS USUALLY A SQUAD NOBODY HAS ASKED ABOUT (#1285). The
# client's soldier count is a reply cache: measured on this account, the same three
# squads read 3123 / 2631 / 2565 and then 0 / 0 / 0 twenty minutes later with the army
# untouched in the game. So a run that found a chest and no squad to send has already
# asked the server for the army — that is `asked-for-army` in the report — and one short
# wait later the numbers are back and the same press goes again. Off the fast path on
# purpose: it costs nothing on a run that had a squad.
READ_LUA (function() local A = DataCenter.__lw_treasure_auto if A == nil then return 0 end return A.asked and 1 or 0 end)() INTO asked

IF asked == 1
    LOG "every squad that could go reads as empty — the game was asked for its army, trying again"
    WAIT 0.6
    TAP treasure_auto_step
    READ_LUA (DataCenter.__lw_treasure_auto and DataCenter.__lw_treasure_auto.report or "the second press left no report") INTO report
    LOG "the line above is the second pass, with the army the game had all along"
    READ_LUA (function() local A = DataCenter.__lw_treasure_auto if A == nil then return 0 end return tonumber(A.did) or 0 end)() INTO did

# A CLAIM IS NOT PROOF OF PAYMENT, and finding that out cost one experiment worth
# repeating: a claim the server refuses is COMPLETELY silent — no message on screen, no
# window, no error, and its reply comes back under the same name with nothing readable in
# it (measured live on 2026-08-08 against a chest uuid that cannot exist). The one
# observable answer is the reward window the client raises when a claim is PAID, and that
# window goes up a moment after the send rather than during it. So a run that claimed
# comes back to look — and only such a run pays for the extra glance.
READ_LUA (function() local A = DataCenter.__lw_treasure_auto if A == nil then return 0 end return tonumber(A.claim_sent) or 0 end)() INTO claim_sent

IF claim_sent > 0
    LOG "a claim went out — looking again in a moment to see whether the reward window came up, because a refusal says nothing at all"
    WAIT 1.5
    TAP treasure_auto_step
    READ_LUA (DataCenter.__lw_treasure_auto and DataCenter.__lw_treasure_auto.report or "the confirming press left no report") INTO report
    LOG "the line above is the confirmation pass: paid= is a chest whose reward window came up, and a chest that is still queued will be claimed again on a later run"

IF did == 0
    LOG "nothing was sent this run — the reason is on the report line above"
    STOP

# WHERE EACH CHEST STANDS NOW, for the log and for the person reading it later. The
# positions and the servers are the account's own; they belong on screen and nowhere
# else (CLAUDE.md).
READ_LUA (function() local A = DataCenter.__lw_treasure_auto if A == nil then return 'the auto errand has never been armed' end local out = {} for i, t in ipairs(A.targets or {}) do local st = 'new' if t.claimed then st = 'claimed' elseif t.dug then st = 'dug' elseif t.sent then st = 'digging' end out[#out+1] = tostring(i) .. ') @[' .. tostring(t.x) .. ',' .. tostring(t.y) .. '|' .. tostring(t.server) .. '] ' .. st .. (t.squad and (' squad' .. tostring(t.squad)) or '') end if #out == 0 then return 'no chest is left in the queue' end return table.concat(out, ' ; ') end)() INTO queue

# A claim that the server paid raises the reward window. Closing it is the panel's
# housekeeping, not part of the send: harmless when nothing is up, and left to the very
# end so it never stands between a chest and a squad.
TAP dismiss_treasure_reward
