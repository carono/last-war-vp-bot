--lua
Server = {}

local function get_time()
    local utc = os.date("!*t")
    utc.hour = utc.hour - 2
    return os.time(utc)
end

function Server:getTime()
    local pacific_time = get_time()
    return os.date("%H:%M", pacific_time)
end

function Server:getDay(as_text)
    as_text = as_text or 0
    local pacific_time = get_time()
    if (as_text == 1) then
        return os.date("%A", pacific_time)
    end
    return os.date("*t", pacific_time).wday
end