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
#   120001  «Строительство Города»     NOT AUTOMATED YET
#   120002  «Прогресс юнита»           NOT AUTOMATED YET
#   120003  «Исследование технологий»  NOT AUTOMATED YET
#   120004  «Улучшение Дрона»          raises rallies — actions/arms_race_drone.md
#
# The three that are not automated are not an oversight and they are not «coming in the
# next commit»: each of them SPENDS the player's own speed-ups or troops, and a phase
# recipe with a guessed ceiling is a recipe that spends somebody else's items. They are
# written when the ceiling has been agreed, one at a time, and until then this errand
# says out loud which phase it declined to act on. A run that does nothing still books
# the next border, which is the point of it running at all.
#
# ## Arguments
#
#   hero     1 to let the hero phase hire, 0 to read and book only. The number of hires
#            is the hero recipe's own `ARGS pulls`, and this file holds no second
#            opinion about it (`CLAUDE.md`).
#   drone    1 to let the drone phase raise rallies, 0 to read and book only.
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
ARGS stamina = 300
ARGS rallies = 0
ARGS squad = 1
ARGS level = 35
ARGS target = boss

CALL read_arms_race

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
    LOG "arms race: this phase is not automated yet — its ceiling has not been agreed. Coming back on the phase border"
    STOP "phase not automated"

IF hero == 0
    LOG "arms race: the hero phase is running and hiring is switched off — coming back in {next_run_in} s"
    STOP "hero phase, hiring off"

CALL arms_race_hero
LOG "arms race: hero phase done — coming back in {next_run_in} s, on the phase border"
