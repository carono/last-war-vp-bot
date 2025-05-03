--lua
MilitaryRaceEvent = {}



function MilitaryRaceEvent:scrollDownDayInCalendar(count)
    count = count or 1
    wheel_down(912, 623, count * 18)
end

function MilitaryRaceEvent:hasActiveHourInCalendar()
    if find_color(897, 460, 966, 788, 8701688) > 0 then
        return 1
    end
    return 0
end

function MilitaryRaceEvent:openEvent()
    if (Hud:clickButton('events') == 1) then
        Hud:scrollLeftEnd()
        click(680, 113, 300)
    end
end

function MilitaryRaceEvent:determineCurrentRaceDayNumber()
    MilitaryRaceEvent:openEvent()
    if (kfindcolor(1144, 174, 16777215) == 1 and click_and_wait_color(1144, 174, modal_header_color, 1071, 345) == 1) then
        wheel_up(912, 623, 7 * 18)
    end
    for i = 1, 7 do
        if (MilitaryRaceEvent:hasActiveHourInCalendar() == 1) then
            return i
        end
        MilitaryRaceEvent:scrollDownDayInCalendar(1)
    end
    Map:normalize()
end

function get_event_start_day(today_wday, event_number_today)
    local start_day = (today_wday - (event_number_today - 1)) % 7
    if start_day == 0 then
        start_day = 7
    end
    return start_day
end

function MilitaryRaceEvent:getCurrentRaceDay()
    local start_day
    start_day = Storage:get('first_race_day_number')
    if (start_day == nil) then
        local currentRaceDay = MilitaryRaceEvent:determineCurrentRaceDayNumber()
        start_day = (os.date("*t").wday - (currentRaceDay - 1)) % 7
        if start_day == 0 then
            start_day = 7
        end
        Storage:set('first_race_day_number', start_day)
    end

    return (os.date("*t").wday - start_day) % 7 + 1
end