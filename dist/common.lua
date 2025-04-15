--lua

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