# «Гонка вооружений» — do what the phase running now pays for, then sleep to its border.
# ru: «Гонка вооружений» — сделать то, за что платит текущая фаза, и уснуть до её границы.
#
# THE ERRAND OF THE EVENT. It is one row on «Таймеры» and it is a clock only in name:
# what decides when it comes back is the SERVER's own calendar. Every run reads the
# phase in front of it, does whatever that kind of phase is allowed to do, and leaves
# the seconds to the next border in `next_run_in` — so the schedule books the turn on
# the border itself rather than grinding a period against an event that changes five
# times a day.
#
# That is the whole reason this event needs no polling. `activity.hero.calender` hands
# over a week of borders in one message (docs/research/arms-race.md), and
# `push.person.arms.sc.change` says when the score moved. A clock here would be asking
# the game a question it has already answered.
#
# ## What each kind of phase does, and what it is still allowed to do
#
#   120000  «Улучшение героя»          hires in the tavern — actions/arms_race_hero.md
#   120001  «Строительство Города»     spends minutes — actions/arms_race_speedup.md
#   120002  «Прогресс юнита»           trains soldiers — actions/arms_race_units.md
#   120003  «Исследование технологий»  spends minutes — actions/arms_race_speedup.md
#   120004  «Улучшение Дрона»          raises rallies — actions/arms_race_drone.md
#
# Two of the three middle ones are one recipe, because they are one ability: building
# and research both pay for MINUTES of speed-up poured into a queue, and only the queue
# and the message differ. They SPEND the player's own speed-ups, so they are switched
# OFF by default and bounded by `minutes` — a run that has not been given a ceiling and
# a switch does nothing but read and book the next border, which is the point of it
# running at all.
#
# «Прогресс юнита» is the odd one out and has a recipe of its own: its points are not
# bought with minutes at all — what pays is the BATCH, 28 points a level-9 soldier
# measured live. So the run collects what the barracks have finished and starts the
# biggest batch each free one will take, under a ceiling in SOLDIERS rather than in
# minutes, because what it spends is the player's resources.
#
# Every run also claims whatever chests the server already owes, before doing anything
# else: a chest is taken and never spent, so there is no phase where it is wrong.
#
# ## Arguments
#
#   hero     1 to let the hero phase hire, 0 to read and book only. The number of hires
#            is the hero recipe's own `ARGS pulls`, and this file holds no second
#            opinion about it (`CLAUDE.md`).
#   drone    1 to let the drone phase raise rallies, 0 to read and book only.
#   speedup  1 to let the building and research phases spend speed-ups, 0 to read and
#            book only. OFF by default: the first live run of each of those is the
#            person's own, with a small `minutes` (`CLAUDE.md`).
#   units    1 to let the unit phase collect the finished batches and start new ones, 0
#            to read and book only. A separate switch from `speedup` because it spends a
#            different thing: RESOURCES, not items out of the bag.
#   soldiers the most soldiers ONE unit-phase run may put into training. 0 — the
#            default — means no ceiling of ours at all: what a barracks will take is the
#            GAME's answer, and the run asks each one for the size the game has already
#            accepted for it. A ceiling here is for the person who wants one, never a
#            safety somebody added on their behalf.
#   free_minutes  the minutes that run may spend FREEING a barracks that is still
#            training, so the emptied one can start a scoring batch. Not the same fuse as
#            `minutes`: that one buys POINTS in the building and research phases, this one
#            buys an empty barracks. 0 trains only into what is already free.
#   minutes  the ceiling those three phases spend under — the most minutes of speed-up
#            ONE run may pour into a queue. 60 by default, which is deliberately small.
#   stamina  the drone phase's ceiling — the most stamina one run may spend. 300.
#   rallies  how many rallies the DAY's own budget still allows (#2051/#2055). Handed
#            over by whoever plays this; **0 raises nothing**, because an arms-race
#            phase quietly overspending the person's rally budget is exactly the thing
#            that must not happen.
#   squad / level / target — which squad raises the drone phase's banners and what it
#            looks for. They travel straight through to actions/create_rally.md.
#
# The reading is actions/read_arms_race.md; the research is docs/research/arms-race.md.

ARGS hero = 1
ARGS drone = 1
ARGS speedup = 0
ARGS minutes = 60
ARGS units = 0
ARGS soldiers = 0
ARGS free_minutes = 0
ARGS stamina = 300
ARGS rallies = 0
ARGS squad = 1
ARGS level = 35
ARGS target = boss

CALL read_arms_race

CALL claim_arms_chests

READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0 end return math.floor((d.event_id or 0) + 0) end)() INTO arms_event

# When the phase ends, in seconds from now — the border the next turn is booked on. The
# `+30` is slack: a turn that lands ON the border reads whichever of the two phases the
# server happens to have switched to, and half a minute late reads the new one for sure.
READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 0 end local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then return 0 end local ends = math.floor((d.stage_end_time or 0) + 0) if ends <= now then return 0 end return (ends - now) + 30 end)() INTO next_run_in

IF arms_event == 0
    LOG "arms race: the game would not say which phase is running — nothing done, and no border to book"
    STOP "no reading"

IF arms_event == 120004
    IF drone == 0
        LOG "arms race: the drone phase is running and raising is switched off — coming back in {next_run_in} s"
        STOP "drone phase, raising off"
    CALL arms_race_drone
    LOG "arms race: drone phase done — coming back in {next_run_in} s, on the phase border"
    STOP "drone phase done"

IF arms_event != 120000
    # A phase paid for in MINUTES: building, units or research. It says what it would
    # pay for either way — the rules are the server's own `scores` (the ids of the rows
    # in the `score` table it is scoring this phase by) and the price of a minute of
    # speed-up is a client constant — so a run with the switch off still leaves the
    # numbers a person needs to decide a ceiling.
    READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local d = nil pcall(function() for _, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then d = v break end end end) if d == nil then return 'no reading' end local ids = tostring(d.scores or '') local top = math.floor((d.score_reward_max or 0) + 0) local sc = math.floor((d.sc or 0) + 0) local inst = nil pcall(function() inst = LocalController.instance() end) local want = {} for part in string.gmatch(ids, '[^|]+') do local n = tonumber(part) if n ~= nil then want[tostring(math.floor(n))] = true end end local rules = {} if inst ~= nil then local n = 0 pcall(function() n = inst:GetTableLength('score') + 0 end) for i = 1, n do local ok, line = pcall(function() return inst:getLine('score', i) end) if ok and line ~= nil then local function g(k) local v = nil pcall(function() v = line:getValue(k) end) if v == nil then return '' end return tostring(v) end local id = tonumber(g('id')) if id ~= nil and want[tostring(math.floor(id))] then rules[#rules+1] = 'type=' .. g('type') .. ' pays=' .. g('points') .. ' per=' .. g('value') end end end end local rate = 0 local kind = '' local map = {[120001] = 'Build', [120002] = 'Soldier', [120003] = 'Science'} local key = map[math.floor((d.event_id or 0) + 0)] if key ~= nil then kind = key pcall(function() rate = math.floor((SpeedScoreValue[key] or 0) + 0) end) end local need = '' if rate > 0 and top > sc then need = ' — ' .. math.ceil((top - sc) / rate) .. ' more minute(s) of ' .. kind .. ' speed-up would reach the top chest at ' .. rate .. ' a minute' end return 'score=' .. sc .. '/' .. top .. ' rules=[' .. table.concat(rules, '; ') .. '] ids=' .. ids .. need end)() INTO arms_phase_rules

    IF arms_event == 120002
        # «Прогресс юнита» is not a minutes phase, whatever its neighbours are: what
        # scores is the BATCH, so it has its own recipe and its own switch. The ceiling
        # is in soldiers, because what a batch costs is resources.
        IF units == 0
            LOG "arms race: the unit phase is running and training is switched off. {arms_phase_rules}. Coming back on the phase border"
            STOP "unit phase, training off"
        LOG "arms race: {arms_phase_rules}"
        CALL arms_race_units
        CALL claim_arms_chests
        LOG "arms race: unit phase done — coming back in {next_run_in} s, on the phase border"
        STOP "unit phase done"

    IF speedup == 0
        LOG "arms race: this phase is paid for in minutes of speed-up and spending is switched off. {arms_phase_rules}. Coming back on the phase border"
        STOP "minutes phase, spending off"

    LOG "arms race: {arms_phase_rules}"
    CALL arms_race_speedup
    CALL claim_arms_chests
    LOG "arms race: minutes phase done — coming back in {next_run_in} s, on the phase border"
    STOP "minutes phase done"

IF hero == 0
    LOG "arms race: the hero phase is running and hiring is switched off — coming back in {next_run_in} s"
    STOP "hero phase, hiring off"

CALL arms_race_hero
CALL claim_arms_chests
LOG "arms race: hero phase done — coming back in {next_run_in} s, on the phase border"
