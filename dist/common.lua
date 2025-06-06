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

function table.shallow_copy(t)
    local t2 = {}
    for k, v in pairs(t) do
        t2[k] = v
    end
    return t2
end

function table.maxmin(T)
    if #T == 0 then
        return nil, nil  -- Если массив пустой, возвращаем nil
    end

    local min = T[1]
    local max = T[1]

    for i = 2, #T do
        if T[i] < min then
            min = T[i]
        elseif T[i] > max then
            max = T[i]
        end
    end

    return min, max
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

local ansi_decode = {
    [128] = '\208\130', [129] = '\208\131', [130] = '\226\128\154', [131] = '\209\147', [132] = '\226\128\158', [133] = '\226\128\166',
    [134] = '\226\128\160', [135] = '\226\128\161', [136] = '\226\130\172', [137] = '\226\128\176', [138] = '\208\137', [139] = '\226\128\185',
    [140] = '\208\138', [141] = '\208\140', [142] = '\208\139', [143] = '\208\143', [144] = '\209\146', [145] = '\226\128\152',
    [146] = '\226\128\153', [147] = '\226\128\156', [148] = '\226\128\157', [149] = '\226\128\162', [150] = '\226\128\147', [151] = '\226\128\148',
    [152] = '\194\152', [153] = '\226\132\162', [154] = '\209\153', [155] = '\226\128\186', [156] = '\209\154', [157] = '\209\156',
    [158] = '\209\155', [159] = '\209\159', [160] = '\194\160', [161] = '\209\142', [162] = '\209\158', [163] = '\208\136',
    [164] = '\194\164', [165] = '\210\144', [166] = '\194\166', [167] = '\194\167', [168] = '\208\129', [169] = '\194\169',
    [170] = '\208\132', [171] = '\194\171', [172] = '\194\172', [173] = '\194\173', [174] = '\194\174', [175] = '\208\135',
    [176] = '\194\176', [177] = '\194\177', [178] = '\208\134', [179] = '\209\150', [180] = '\210\145', [181] = '\194\181',
    [182] = '\194\182', [183] = '\194\183', [184] = '\209\145', [185] = '\226\132\150', [186] = '\209\148', [187] = '\194\187',
    [188] = '\209\152', [189] = '\208\133', [190] = '\209\149', [191] = '\209\151'
}
local utf8_decode = {
    [128] = { [147] = '\150', [148] = '\151', [152] = '\145', [153] = '\146', [154] = '\130', [156] = '\147', [157] = '\148', [158] = '\132', [160] = '\134', [161] = '\135', [162] = '\149', [166] = '\133', [176] = '\137', [185] = '\139', [186] = '\155' },
    [130] = { [172] = '\136' },
    [132] = { [150] = '\185', [162] = '\153' },
    [194] = { [152] = '\152', [160] = '\160', [164] = '\164', [166] = '\166', [167] = '\167', [169] = '\169', [171] = '\171', [172] = '\172', [173] = '\173', [174] = '\174', [176] = '\176', [177] = '\177', [181] = '\181', [182] = '\182', [183] = '\183', [187] = '\187' },
    [208] = { [129] = '\168', [130] = '\128', [131] = '\129', [132] = '\170', [133] = '\189', [134] = '\178', [135] = '\175', [136] = '\163', [137] = '\138', [138] = '\140', [139] = '\142', [140] = '\141', [143] = '\143', [144] = '\192', [145] = '\193', [146] = '\194', [147] = '\195', [148] = '\196',
              [149] = '\197', [150] = '\198', [151] = '\199', [152] = '\200', [153] = '\201', [154] = '\202', [155] = '\203', [156] = '\204', [157] = '\205', [158] = '\206', [159] = '\207', [160] = '\208', [161] = '\209', [162] = '\210', [163] = '\211', [164] = '\212', [165] = '\213', [166] = '\214',
              [167] = '\215', [168] = '\216', [169] = '\217', [170] = '\218', [171] = '\219', [172] = '\220', [173] = '\221', [174] = '\222', [175] = '\223', [176] = '\224', [177] = '\225', [178] = '\226', [179] = '\227', [180] = '\228', [181] = '\229', [182] = '\230', [183] = '\231', [184] = '\232',
              [185] = '\233', [186] = '\234', [187] = '\235', [188] = '\236', [189] = '\237', [190] = '\238', [191] = '\239' },
    [209] = { [128] = '\240', [129] = '\241', [130] = '\242', [131] = '\243', [132] = '\244', [133] = '\245', [134] = '\246', [135] = '\247', [136] = '\248', [137] = '\249', [138] = '\250', [139] = '\251', [140] = '\252', [141] = '\253', [142] = '\254', [143] = '\255', [144] = '\161', [145] = '\184',
              [146] = '\144', [147] = '\131', [148] = '\186', [149] = '\190', [150] = '\179', [151] = '\191', [152] = '\188', [153] = '\154', [154] = '\156', [155] = '\158', [156] = '\157', [158] = '\162', [159] = '\159' }, [210] = { [144] = '\165', [145] = '\180' }
}

function AnsiToUtf8(s)
    local r, b = ''
    for i = 1, s and s:len() or 0 do
        b = s:byte(i)
        if b < 128 then
            r = r .. string.char(b)
        else
            if b > 239 then
                r = r .. '\209' .. string.char(b - 112)

            elseif b > 191 then
                r = r .. '\208' .. string.char(b - 48)
            elseif ansi_decode[b] then
                r = r .. ansi_decode[b]
            else
                r = r .. '_'
            end
        end
    end
    return r
end

function info(message)
    writeLog(message, 'INFO')
end

function warning(message)
    writeLog(message, 'WARNING')
end

function error(message)
    writeLog(message, 'ERROR', 5)
end

function writeLog(message, category, level, filename)
    filename = filename or "logs/" .. os.getenv('username') .. ".log"
    local timestamp = os.date("%Y-%m-%d %H:%M:%S")
    level = level or 1
    local stacktrace = {}
    for i = 2, level do
        local info = debug.getinfo(i, "Snl")
        if not info then
            break
        end

        local func_name = info.name or "(anonymous)"
        local location = string.format("%s:%d", info.short_src, info.currentline)
        table.insert(stacktrace, string.format("%s (%s)", func_name, location))
    end

    -- Форматируем стектрейс в строку
    local stacktrace_str = #stacktrace > 0 and table.concat(stacktrace, " → ") or ""

    -- Открываем файл с обработкой ошибок
    local file, err = io.open(filename, "a")
    if not file then
        return nil, "Failed to open log file: " .. err
    end

    -- Формируем строку лога
    local logEntry = string.format("[%s] [%s] [%s] %s\n",
            timestamp, category, stacktrace_str, message)

    -- Записываем в файл
    local success, writeErr = pcall(function()
        file:write(logEntry)
        file:close()
    end)

    if not success then
        return nil, "Failed to write to log: " .. writeErr
    end

    return true
end