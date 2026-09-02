# Heal the wounded soldiers in the base hospital ("Лечение юнитов").
# ru: Лечение раненых в госпитале базы («Лечение юнитов»).
#
# The operator's in-game routine is three presses — collect what has finished, send the
# wounded in, ask the alliance to speed it up — and all three are real messages
# (docs/research/hospital-heal.md).
#
# Every line below is a headless Lua send, not a screen tap: no hospital window is
# opened, the wounded list and the heal timer are read straight off the game state.
#
# AND SINCE #2085 THE RUN LEAVES SOMETHING BEHIND IT. The hospital is one queue with one
# timer, so «лечим и забираем» is not a thing that happens at a moment — it is a thing
# that happens WHEN THE TIMER ENDS, which may be hours later. The last step arms a watch
# that lives in the game itself and does the same three presses on the client's own
# calls: the collect leaves in the instant the game learnt the heal was over, the next
# portion goes in behind it, and nothing is asked of the server in between.

# How many soldiers one heal may send. 0 — the default — is «all of them», which is what
# the recipe did before there was a number. A ceiling is worth having because the hospital
# takes ONE job at a time: everything the base has wounded goes in as a single treatment
# that nothing can interrupt, while a portion is as much as the player wants to wait for
# and the watch below sends the next one the moment the queue frees.
ARGS portion = 0

# Whether the alliance is asked to speed the heal up — here and in the watch.
ARGS help = 1

# Whether the watch is armed. 1 leaves the hospital working by itself afterwards; 0 makes
# this run exactly the three presses and nothing more.
ARGS watch = 1

# Whether the run may open resource packs out of the bag when the base cannot pay for the
# heal. It spends somebody's inventory, so it is OFF unless asked for: with it at 0 the
# run still SAYS what the heal costs and what is short, and simply does not open anything.
ARGS chests = 0

# What this run may spend, parked where the presses can read it — a `TAP` takes no
# arguments of its own.
LUA DataCenter.__lw_heal_portion = {portion} DataCenter.__lw_heal_help = {help} DataCenter.__lw_heal_chests = {chests}

# --- 1. Collect the healed soldiers first --------------------------------------
# Only fires once the heal timer has finished — while one is still running this is a clean
# no-op, so the recipe can be run on any schedule. It goes FIRST because finished soldiers
# left in the hospital block the next heal.
TAP collect_healed xall

# --- 2. What the heal will cost, and paying for it ------------------------------
# The bill is read out of the game, resource by resource: each wounded soldier's own type
# says what curing it takes and in what — metal and food on every type read so far — and
# what the base holds comes from the game too. «unknown» means the question could not be
# put, which is never the same as «free», and nothing is ever opened out of the bag for a
# price that could not be read (docs/research/hospital-heal.md §9).
TAP heal_bill
READ_LUA (function() local B = DataCenter.__lw_heal_bill or {} if B.why ~= nil and B.why ~= '' then return 'unknown ' .. tostring(B.why) end local out = {} for _, r in ipairs(B.res or {}) do out[#out+1] = tostring(r.name or r.id) .. ' need=' .. tostring(r.need) .. ' own=' .. tostring(r.own) .. ' short=' .. tostring(r.lack) end if #out == 0 then return 'nothing to pay for' end return 'soldiers=' .. tostring(math.floor(tonumber(B.sent) or 0)) .. ' of ' .. tostring(math.floor(tonumber(B.all) or 0)) .. ' :: ' .. table.concat(out, ' | ') .. ' | the window controller would say ' .. tostring(math.floor(tonumber(B.fn) or -1)) end)() INTO bill
LOG "the line above is the bill for this heal: soldiers= how many of the wounded the portion sends, then, per resource, need= what they cost, own= what the base holds and short= what is missing. The last number is what the hospital window's own controller would answer for the same soldiers — it is printed to be compared with the screen, and it is NOT what this run pays by"

# If the base is short and the run was told it may, the missing resources come out of the
# packs in the bag — out of exactly the packs the GAME picks for that shortfall, in the
# numbers it picks. Nothing here guesses which pack gives which resource: the client works
# that out itself, and it is the same list it shows a person who is short at a shop.
IF chests == 1
    TAP heal_open_packs
    WAIT 2
    READ_LUA (function() local P = DataCenter.__lw_heal_packs or {} if P.why ~= nil and P.why ~= '' then return 'opened nothing: ' .. tostring(P.why) end local out = {} for _, r in ipairs(P.rows or {}) do out[#out+1] = tostring(r.name or '?') .. ' short=' .. tostring(r.lack) .. ' item=' .. tostring(r.item or '-') .. ' asked=' .. tostring(r.want) .. ' opened=' .. tostring(r.used) .. ((r.why ~= nil and r.why ~= '') and (' ' .. tostring(r.why)) or '') end if #out == 0 then return 'nothing was short' end return table.concat(out, ' | ') end)() INTO opened
    LOG "the line above is what left the bag: per pack — short= how much the base was missing, item= which pack, asked= how many the game's own plan called for, opened= how many actually went. «opened nothing» with a reason means no pack was spent at all"
    TAP heal_bill
    READ_LUA (function() local B = DataCenter.__lw_heal_bill or {} if B.why ~= nil and B.why ~= '' then return 'unknown ' .. tostring(B.why) end local out = {} for _, r in ipairs(B.res or {}) do out[#out+1] = tostring(r.name or r.id) .. ' need=' .. tostring(r.need) .. ' own=' .. tostring(r.own) .. ' short=' .. tostring(r.lack) end if #out == 0 then return 'nothing to pay for' end return 'soldiers=' .. tostring(math.floor(tonumber(B.sent) or 0)) .. ' of ' .. tostring(math.floor(tonumber(B.all) or 0)) .. ' :: ' .. table.concat(out, ' | ') .. ' | the window controller would say ' .. tostring(math.floor(tonumber(B.fn) or -1)) end)() INTO bill2
    LOG "and this is the same bill read again, after the packs: {bill2}"

# --- 3. Send the next portion for treatment ------------------------------------
# One hospital.cure covers every soldier type at once, so one press is the whole heal.
# `xall` means "only if somebody is actually hurt", so a healthy army costs no round trip.
# The portion is spent highest-tier-first: a bigger soldier id is a better soldier.
TAP heal_portion xall

READ_LUA ((function() local h = DataCenter.__lw_heal or {} return 'asked=' .. tostring(math.floor(tonumber(h.want) or 0)) .. ' sent=' .. tostring(math.floor(tonumber(h.sent) or 0)) .. ' types=' .. tostring(math.floor(tonumber(h.types) or 0)) .. ((h.err ~= nil and h.err ~= '') and (' refused=' .. tostring(h.err)) or '') end)()) INTO healed
LOG "the line above is the heal itself: asked= the ceiling this run was given (0 = every wounded soldier), sent= how many actually went for treatment, types= over how many kinds of soldier they were spread, and refused= the game's own words when the send did not go — «no wounded soldiers» is the ordinary one and means the hospital was already empty"

# --- 4. Ask the alliance to speed it up ----------------------------------------
# The third press of the in-game routine, and it comes last because the heal has to be
# running before there is a queue to ask about. It asks for every working queue, not just
# the hospital, and skips the ones already asked for, so it is safe on any schedule.
IF help == 1
    TAP call_help xall

# --- 5. Leave the hospital working by itself -----------------------------------
# The watch is armed rather than run: it wraps three of the client's own calls once
# (`OnQueueEnd` when the queue retires, `HospitalCureHandle` when the server answers a
# cure, `UpdateHospitalDeadInfo` when soldiers are hurt) and pins ONE alarm to the heal's
# own `endTime` — a moment the server named, so there is nothing to poll for. Arming is
# idempotent: however often this recipe runs, the doors are wrapped once.
IF watch == 1
    TAP heal_watch_on
    READ_LUA ((function() local W = DataCenter.__lw_heal_watch if W == nil then return 'on=0 hooked=0 ticks=0 collected=0 healed=0 helped=0' end return 'on=' .. tostring(W.on and 1 or 0) .. ' hooked=' .. tostring(W.hooked and 1 or 0) .. ' ticks=' .. tostring(math.floor(tonumber(W.ticks) or 0)) .. ' collected=' .. tostring(math.floor(tonumber(W.collected) or 0)) .. ' healed=' .. tostring(math.floor(tonumber(W.healed) or 0)) .. ' helped=' .. tostring(math.floor(tonumber(W.helped) or 0)) .. ' state=' .. tostring(math.floor(tonumber(W.state) or -1)) .. ' wounded=' .. tostring(math.floor(tonumber(W.wounded) or 0)) .. ' woke=' .. tostring(W.why or '-') .. ' last=' .. tostring(W.last or '-') end)()) INTO watching
    LOG "the line above is the watch: on= is it armed, hooked= are the client's own calls wrapped, ticks= how many times it has looked since the client started, collected=/healed=/helped= what it has done by itself, state= the hospital queue right now (2 = working, 3 = finished and waiting to be collected), wounded= who is still lying there, woke= what called it last and last= what it did"

# NB — the order matters. The hospital takes ONE job at a time, and soldiers that have
# finished healing still occupy it until they are collected, so a heal sent before the
# collect is refused (errorCode 130069). The help request comes last because it needs a
# queue already working. All three are proven live: 681 wounded sent in one press, a
# finished batch collected back, and allies answering the request within seconds.
