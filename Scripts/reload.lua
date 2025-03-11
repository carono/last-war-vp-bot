--lua
local path =  homepath()     .. "Scripts\\reload.tmp"

::START::
if (fileexists(path) == "1") then
  load_script (99, "proc.lua")
  filedelete (path)
end
goto START
