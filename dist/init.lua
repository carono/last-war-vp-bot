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

function log(data)
    if (debug == 1) then
        originalLog(data)
    end
end