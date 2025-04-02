--lua

require('dist/init')
require('dist/init-develop')
require('src/develop')
local allianceServiceTimeOut = 60 * 1000
local allianceTimer = ktimer(0)
::start::

Map:normalize()

if  (os.clock() > allianceTimer) then
  service_alliance()
  allianceTimer = ktimer(allianceServiceTimeOut)
end
Rally:joinIfExist()
Alliance:applyHelp()

goto start