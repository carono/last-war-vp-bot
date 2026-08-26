# Read this character's own card: name, HQ level and power.
# ru: Прочитать карточку персонажа: имя, уровень штаба и мощь.
#
# A READ, and nothing else: it presses nothing, opens nothing and sends nothing to the
# server. No window has to be open and no scene is required.
#
# WHERE THE NUMBERS COME FROM (#1991, docs/research/player-profile.md). `LuaEntry.Player`
# is the client's own character object, filled at login and kept up to date by the server's
# own updates — the same object the warzone card already asks about its server
# (`actions/read_server_info.md`). So this costs one VM round trip and no question on the
# wire, from the base or from the world map alike.
#
#   * `GetName()`      — the character's name, as the game writes it.
#   * `level`          — the HQ level. There is no `GetLevel()` on this client.
#   * `power`          — the power the client keeps for this character. `GetValue('power')`
#                        answers the same number.
#
# ASK FOR WHAT THE GAME COUNTS, not for what a field is called. Three neighbouring fields
# read like power and are not it: `playerPower` and `lastPower` are 0 on a live account,
# and `playerMaxPower` is a different, larger figure. The one the client itself hands out
# is `power`, and the breakdown behind it lives elsewhere
# (`DataCenter.PlayerPowerDataManager` — a separate ability, not this one).
#
# THE ANSWER lands in one variable, `player_card`, as three fields separated by « ;; »,
# in this order — a name may contain spaces, so the separator is not one:
#
#     Player1;;35;;231590771
#
#   * nick   — the character's name.
#   * level  — the HQ level.
#   * power  — the power.
#
# A CLIENT THAT HAS NOT LOGGED IN IS REFUSED BEFORE ANYTHING IS READ, exactly as the
# resource reading is: a client sitting at the login screen answers every question
# cheerfully and wrongly (`tools/lib/game_clock.py`), and an empty card is better than a
# level-1 character with no name. The check is the same round trip, so it is free.

READ_LUA (function() local nowms=0 pcall(function() nowms=UITimeManager.Instance:GetServerTime() end) nowms=math.floor(tonumber(nowms) or 0) if nowms < 1600000000000 then return '' end local P=LuaEntry and LuaEntry.Player if P==nil then return '' end local nick='' pcall(function() nick=tostring(P:GetName() or ''):gsub('%s+',' ') end) local lv=0 pcall(function() lv=math.floor((tonumber(P.level) or 0)+0) end) local pw=0 pcall(function() pw=math.floor((tonumber(P.power) or 0)+0) end) if nick=='' and lv==0 and pw==0 then return '' end return nick..';;'..lv..';;'..pw end)() INTO player_card
LOG "player card: {player_card}"
