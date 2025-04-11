--lua

require('dist/init')

:: start ::

Game:waitIfUserIsActive()

if (cooldown('checkHandle') == 1 and Window:attachHandle() == 0) then
    Game:start()
end

if (cooldown('MapNormalize') == 1) then
    Map:normalize()
end

if (cooldown('checkMinistryRequests') == 1) then
    Game:checkMinistryRequests()
end

if (Game:isLogout() == 1) then
    Game:clickLogout()
end

close_connection_error()

goto start