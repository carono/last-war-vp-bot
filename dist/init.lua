local path = "./config/" .. os.getenv('username') .. "_init"

require('dist/common')
require('dist/functions')
require('lib/storage')
require('dist/classes')

if (fileexists(path .. ".lua") == "1") then
    require(path)
end

if (Window:attachHandle() ~= 0) then
    Window:repos()
    Window:resizeCanonical()
end

originalLog = log

if (debug == 1) then
    originalLog("clear")
end

function log(...)
    local args = { ... }
    if (debug == 1) then
        originalLog(unpack(args))
    end
end