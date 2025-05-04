--lua
MilitaryRaceEvent = {}

local events = { "hero", "development", "unit", "science", "drone" }
local event_duration = 240

local function time_to_minutes(time_string)
    local hours, minutes = time_string:match("^(%d+):(%d+)$")
    return tonumber(hours) * 60 + tonumber(minutes)
end

local function get_server_time()
    local utc = os.date("!*t")
    utc.hour = utc.hour - 2
    local pacific_time = os.time(utc)
    return os.date("%H:%M", pacific_time)
end

function MilitaryRaceEvent:getEventName()
    local day_number = self:getCurrentRaceDay()
    local time_string = get_server_time()
    local minutes_today = time_to_minutes(time_string)
    local total_minutes = (day_number - 1) * 1440 + minutes_today
    local index = math.floor(total_minutes / event_duration) % #events + 1
    return events[index]
end

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
        click(680, 113, 2000)
        return 1
    end
    return 0
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

function MilitaryRaceEvent:openCodeName()
    Hud:clickButton('events')
    Hud:scrollLeftEnd()
    Hud:clickFirstTab()
    Hud:clickNextTab()
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

