--lua

function encodeURIComponent(str)
    str = tostring(str)
    str = string.gsub(str, "([^%w%-_%.%~])", function(c)
        return string.format("%%%02X", string.byte(c))
    end)
    return str
end

function build_url(base_url, query)
    local query_string = {}
    for key, value in pairs(query) do
        table.insert(query_string, encodeURIComponent(key) .. "=" .. encodeURIComponent(value))
    end
    return base_url .. "?" .. table.concat(query_string, "&")
end


function table.length(T)
    local count = 0
    for _ in pairs(T) do
        count = count + 1
    end
    return count
end

function split(str, sep)
    if sep == nil then
        sep = "%s"
    end
    local t = {}
    for _ in string.gmatch(str, "([^" .. sep .. "]+)") do
        table.insert(t, _)
    end
    return t
end