local path = "./config/" .. os.getenv('username') .. "_init"

if (fileexists(path .. ".lua") == "1") then
    require(path)
else
    require('dist/common')
    require('dist/config')
    require('dist/functions')
    require('dist/classes')
    Window:attachHandle()
    Window:repos()
    Window:resizeCanonical()

    function log()

    end
end
