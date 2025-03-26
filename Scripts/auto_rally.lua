--lua

require('dist/init')
require('dist/init-develop')
require('src/develop')
local allianceTimer = ktimer(300000)
::start::

Map:normalize()
if  (os.clock() > allianceTimer) then
  service_alliance()
  allianceTimer = ktimer(300000)
end
Rally:joinIfExist()


goto start