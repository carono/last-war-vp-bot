# Donate to the alliance's priority (recommended) technology.
# ru: Донат в приоритетную (рекомендованную) технологию альянса.
#
# One line, because the donate press needs no window open: the controller method
# behind "Donate 1000" touches no window state, so it is called straight on the
# module and the player's view is left exactly as it was found. `xall` reads how
# many attempts are banked, spends all of them in a single call into the game (a
# round trip costs ~0.15 s and the loop inside it is free, so a full quota is one
# call) and re-reads the count to confirm the server took them.
#
# The messy engine calls live in the button library tools/lib/game_buttons.py and
# the Lua in tools/lib/lua_actions.py — a recipe never has to name them. The
# reverse-engineering is written up in docs/research/alliance-tech-donate.md.

# WHY A RUN THAT PRESSES NOTHING SAYS SO (#2070). «TAP … -> 0 press(es)» is one line
# for three different worlds: the quota is genuinely spent, the alliance has no
# recommended tech to give to, or the client's own counter has not been refreshed since
# the last login. Measured on a live profile: donations landed only in the minutes after
# a client restart and read 0 for the five hours in between. So the reading is printed
# before the press — one extra read of numbers the client already holds, no round trip
# to the server — and the log can be told which of the three it was.
READ_LUA (function() local M = DataCenter.AllianceScienceDataManager local rest, cap, can, tech = -1, -1, '?', 'none' pcall(function() rest = math.floor((M:GetResDonateRestCount() or 0) + 0) end) pcall(function() cap = math.floor((M:GetResDonateMaxCount() or 0) + 0) end) pcall(function() can = tostring(M:GetCanDonate()) end) pcall(function() local rec = M:GetCurRecommendScience() if rec ~= nil then tech = tostring(rec.scienceId) .. ' res=' .. tostring(rec.res) .. ' x' .. tostring(rec.resNum) end end) return 'attempts=' .. tostring(rest) .. '/' .. tostring(cap) .. ' can=' .. can .. ' tech=' .. tech end)() INTO donate_state

LOG "donate: {donate_state}"

TAP donate_1000 xall  # press "Donate 1000" for every attempt currently banked
