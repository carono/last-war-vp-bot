local path = "./config/" .. os.getenv('username') .. "_init"

if (fileexists(path .. ".lua") == "1") then
    require(path)
else
    require('dist/common')
    require('dist/functions')
    require('lib/storage')
    require('dist/classes')

    if (Window:attachHandle() ~= 0) then
        Window:repos()
        Window:resizeCanonical()
    end
end

originalLog = log

function log(...)
    local args = { ... }
    if (debug == 1) then
        originalLog(unpack(args))
    end
end