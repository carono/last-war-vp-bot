# Take the treasures on the map: send the nearest free squad, take the gift.
# ru: Отработать сокровища на карте: отправить ближайший свободный отряд и забрать подарок.
#
#   run auto_treasure                        -- any squad may go
#   run auto_treasure {"squads": [3, 4]}     -- only squads 3 and 4
#
# THREE DOORS, ONE QUEUE, AND NONE OF THEM MOVES ANYTHING. A chest reaches this errand
# three ways, and every one of them is a thing the client was going to hear or see anyway:
#
#   1. **the alliance chat share** — one message naming the uuid, the server AND the
#      tile. The cheapest of the three and the least reliable: sharing is a thing a
#      PERSON does, and measured live, twenty minutes of the alliance digging a chest
#      produced not one share on the wire;
#   2. **the dig broadcast** (`push.detect.treasure.claim`) — arrives once per member who
#      finishes their part, and carries a uuid with no tile in it. Enough to claim, never
#      enough to march;
#   3. **what the client can already see** (`treasure_look`) — the chests in the box the
#      camera happens to be sitting in, read out of `WorldScene.PointManager`. It gives
#      both halves at once, uuid and tile, and it is the only door that finds a chest
#      nobody announced.
#
# THE THIRD ONE USED TO WALK THE WHOLE SERVER, AND THAT WAS DELETED (#1296). The lap cost
# 48 s of camera every five minutes and was measured twice: 19 chests and then 21 — with
# **ours zero both times**. A chest of one's own alliance is placed in the HIVE, not out on
# the open map, so the census was a census of other people's treasure. What is kept is the
# reading, which was never the expensive half: when we are on the map anyway, whatever is
# in the box comes home for free. Somebody who genuinely wants a whole-server census still
# has `scan_treasures` to press by hand; nothing presses it on a schedule.
#
# A chest that comes through two doors stays ONE target and keeps the best half of each: a
# uuid heard from the dig feed and a tile seen on screen are the same chest, and the look
# upgrades it rather than queuing it twice.
#
# THE FIRST TWO CANNOT BE A WIRE TRIGGER, and that is a measurement rather than a
# preference. The announcement is a chat post, and the chat broadcast rides a TLS
# websocket this repository cannot decode (`docs/research/chat-system.md`): in the
# 2026-08-08 recording the message is in the Lua trace and NOT in the capture taken
# beside it. The panel's ordinary wire listener is deaf to it by construction. What the
# trigger polls instead is a LOCAL Lua table — one daemon round trip, ~0.15 s with the
# daemon free, no request to the server and nothing the game can notice — so the «poll»
# in the catalogue is a poll of the panel's own ear, never of the world.
#
# AND THE THIRD ONE IS NOW AS CHEAP AS THE OTHER TWO, which is why it rides the same tick.
# It reads one box of the point manager — 0.03–0.04 s inside the VM — and moves nothing:
# no jump, no zoom, nothing sent to the server. A person playing on the map notices
# nothing. In the city it does nothing at all and says so, because the point manager
# belongs to the world scene.
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

# Whether the surroundings are read at all. 1 — the default — reads the box the camera is
# already in on every run; 0 leaves only the two ears. There is no period any more: the
# look costs a hundredth of a second and moves nothing, so «how often» stopped being a
# question worth a setting (#1296).
ARGS look = 1

# What this run may spend, parked where the press can read it — a `TAP` takes no
# arguments of its own. `grace` is how long after the march a claim may be tried without
# having heard the alliance's own «this chest is dug»; `ttl` is when a chest is written
# off as gone from the map.
LUA DataCenter.__lw_treasure_squads = { {squads} } DataCenter.__lw_treasure_grace = {grace} DataCenter.__lw_treasure_ttl = {ttl}

# The ear first, and it is idempotent: the hook is wrapped once however often this runs,
# and re-arming never throws the queue away. A client restarted since the last run has a
# fresh VM and no hook at all, which is exactly the case this covers — and the one the
# trigger's poll treats as work in its own right.
#
# AND WITH THE EAR, A CLOCK (#1318). Hearing a chest early buys nothing if the gift is
# taken ten seconds after the dig ends, and ten seconds is the best a panel poll can do:
# the trigger looks every ten with a twenty-second cooldown behind it, so a dig that
# finished a moment after a tick waited out both. So the claim half now lives in the game —
# it reads the dig's own deadline off our march (`MarchStatus.TREASURE_DIGGING` carries an
# `endTime`), pins a one-shot of the game's timer to that millisecond, and looks every
# fifth of a second besides. This press starts it, and runs it once itself at the end, so
# a run is never slower than the watch and a client whose watch has idled out still claims.
TAP treasure_auto_arm

# WHAT IS ALREADY ON SCREEN, every run. Reading the box the camera sits in costs a
# hundredth of a second and moves nothing — in the city it does nothing and says so — so
# there is no «is it due» to ask any more. Whatever it saw becomes targets exactly as a
# lap's findings did.
IF look == 1
    TAP treasure_look
    TAP treasure_scan_harvest
    READ_LUA (DataCenter.__lw_treasure_auto and DataCenter.__lw_treasure_auto.scan_report or 'nothing has been looked at yet') INTO seen
    LOG "the line above is what the client could see from where it stands: found= every chest in the box, ours= the ones this alliance's own event placed, foreign= another alliance's, which the game refuses outright and which are never queued. A chest of one's own alliance is placed in the HIVE rather than out on the map, so this door is the rare one — and the reason the whole-server lap was deleted: two full laps found 19 and 21 chests with ours zero both times."

# The whole queue, one step each, in ONE press: the nearest free squad marches onto the
# nearest chest, and a chest the alliance has already dug is claimed. Nothing is opened
# on screen by it.
TAP treasure_auto_step

# What it did, chest by chest. A reading, so it costs a chest nothing — the sends are
# already away.
READ_LUA (DataCenter.__lw_treasure_auto and DataCenter.__lw_treasure_auto.report or "the step left no report — the press did not run") INTO report

LOG "the line above is what the run did: sent= marches that went out, claimed= claims sent, paid= gifts actually received (the reward window came up, or the server answered «claim repeat», which is the same thing said from the other side), waiting= chests whose squad is still out or whose claim has not answered, resent= sends the client had dropped in silence and which went again, lag=/worst= how long the last and the worst chest waited between becoming takeable and their first claim leaving — the acceptance criterion in milliseconds — watch= whether the game-side clock is running, and one note per chest"

# WHAT THE WATCH ITSELF IS DOING, read apart from the press. The report above is written by
# a press; this is written by the thing that runs between presses, and the two disagreeing
# is the one symptom worth chasing — a watch that says `on=0` after an arm is a client that
# lost its timer, and every claim is back to waiting for a panel tick.
READ_LUA (function() local A = DataCenter.__lw_treasure_auto if A == nil then return 'on=0 ticks=0 live=0 claims=0 paid=0 lag=-1 worst=-1 eye=never' end return 'on=' .. tostring((A.reap_on and A.reap_on ~= 0) and 1 or 0) .. ' ticks=' .. tostring(A.ticks or 0) .. ' live=' .. tostring(A.t_live or 0) .. ' claims=' .. tostring(A.claims_all or 0) .. ' paid=' .. tostring(A.paid_all or 0) .. ' lag=' .. tostring(A.lag_ms or -1) .. ' worst=' .. tostring(A.lag_worst or -1) .. ' eye=' .. tostring(A.look_why or 'never') end)() INTO watch

LOG "the line above is the game-side watch: on= is its timer alive, ticks= how many times it has looked since the client started, live= chests it is working right now, claims=/paid= what it has sent and been paid for, lag=/worst= milliseconds from takeable to claim (-1 = no chest has been taken yet), eye= what the second ear last saw — «looked» on the map, «city» in the base, and «no-point-manager» when the client has not been out on the map since it started"

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
# window goes up a moment after the send rather than during it.
#
# THIS RECIPE NO LONGER WAITS FOR IT (#1318). It used to sleep a second and a half and
# press again, which was the only way to see the window when nothing else was looking —
# and it also meant the whole confirmation, and every retry after it, happened at the pace
# of the panel. The watch above looks every fifth of a second, so it sees the window while
# it is still up, reads the server's own «claim repeat» as payment when the window was
# missed, and keeps claiming until the chest is paid or gone. A run therefore reports what
# is true at the moment it asks and stops pretending to be the last word.
READ_LUA (function() local A = DataCenter.__lw_treasure_auto if A == nil then return 0 end return tonumber(A.claim_sent) or 0 end)() INTO claim_sent

IF did == 0
    LOG "nothing was sent this run — the reason is on the report line above"
    STOP

# WHERE EACH CHEST STANDS NOW, for the log and for the person reading it later. The
# positions and the servers are the account's own; they belong on screen and nowhere
# else (CLAUDE.md).
READ_LUA (function() local A = DataCenter.__lw_treasure_auto if A == nil then return 'the auto errand has never been armed' end local out = {} for i, t in ipairs(A.targets or {}) do local st = 'new' if t.done then st = 'spent:' .. tostring(t.why or '?') elseif t.claimed then st = 'claimed' elseif t.dug then st = 'dug' elseif t.sent then st = 'digging' end out[#out+1] = tostring(i) .. ') @[' .. tostring(t.x) .. ',' .. tostring(t.y) .. '|' .. tostring(t.server) .. '] ' .. st .. (t.squad and (' squad' .. tostring(t.squad)) or '') end if #out == 0 then return 'no chest is left in the queue' end return table.concat(out, ' ; ') end)() INTO queue

# A claim that the server paid raises the reward window. Closing it is the panel's
# housekeeping, not part of the send: harmless when nothing is up, and left to the very
# end so it never stands between a chest and a squad.
TAP dismiss_treasure_reward
