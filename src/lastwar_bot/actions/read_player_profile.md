# Read this character's own card: name, HQ level, power, alliance, energy, join date.
# ru: Прочитать карточку персонажа: имя, уровень, мощь, альянс, энергию, дату входа в игру.
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
#   * `GetName()`             — the character's name, as the game writes it.
#   * `level`                 — the HQ level. There is no `GetLevel()` on this client.
#   * `power`                 — the power the client keeps for this character.
#                               `GetValue('power')` answers the same number.
#   * `GetFullAllianceName()` — the alliance's tag and name, ALREADY COMPOSED by the game
#                               in the player's own language and punctuation. Nothing here
#                               glues a tag to a name: `GetAllianceAbbr()` and
#                               `GetAllianceName()` exist separately, and joining them
#                               would be the panel deciding what the game already decided.
#                               Empty when the character is in no alliance, which
#                               `IsInAlliance()` states rather than being guessed from an
#                               empty string.
#   * `GetCurStamina()`       — the energy purse right now. It refills with TIME, which is
#                               why it is read on every look rather than remembered.
#   * `GetStaminaFullTime()`  — when the purse will be full, epoch ms on the game's clock.
#                               0 when it already is.
#   * `regTime`               — when this character was registered, epoch ms. The client
#                               also offers `GetUserRegDay()`, a FRACTIONAL count of days
#                               (692.11…) — a reader wanting «how long have I played» would
#                               have to round it, and a rounded number is the panel's
#                               arithmetic rather than the game's word, so the moment
#                               itself is reported and the reader renders a date.
#
# ASK FOR WHAT THE GAME COUNTS, not for what a field is called. Three neighbouring fields
# read like power and are not it: `playerPower` and `lastPower` are 0 on a live account,
# and `playerMaxPower` is a different, larger figure. The one the client itself hands out
# is `power`, and the breakdown behind it lives elsewhere
# (`DataCenter.PlayerPowerDataManager` — a separate ability, not this one).
#
# AND WHAT IS DELIBERATELY NOT HERE. `playerMaxPower` is a real number the client keeps and
# nothing in the client says what it MEANS — a peak, a season high, a cap. A row is a claim,
# so an unnamed number would be the panel inventing a caption for the game; it stays out
# until the game itself names it. Same for the kill/loss/heal tallies (`armyKill`,
# `armyDead`, `armyCure`), which read 0 on a live account that has certainly fought: they
# are not the counters the game draws.
#
# THE ANSWER lands in one variable, `player_card`, as seven fields separated by « ;; »,
# in this order — a name may contain spaces, so the separator is not one:
#
#     Player1;;35;;100000000;;[AL1] Alliance One;;67;;1700000000000;;1600000000000
#
#   * nick            — the character's name.
#   * level           — the HQ level.
#   * power           — the power.
#   * alliance        — the alliance's tag and name as the game composes them; empty when
#                       the character is in none.
#   * stamina         — the energy purse right now.
#   * stamina_full_ms — when the purse fills up, epoch ms; 0 when it is already full.
#   * reg_ms          — when the character was registered, epoch ms.
#
# EVERY MOMENT IS THE GAME'S CLOCK, not this machine's (docs/research/game-clock.md), so a
# reader turning one into a date judges it with `tools/lib/game_clock.py` and never with
# `time.time()`.
#
# A CLIENT THAT HAS NOT LOGGED IN IS REFUSED BEFORE ANYTHING IS READ, exactly as the
# resource reading is: a client sitting at the login screen answers every question
# cheerfully and wrongly (`tools/lib/game_clock.py`), and an empty card is better than a
# level-1 character with no name. The check is the same round trip, so it is free.

READ_LUA (function() local nowms=0 pcall(function() nowms=UITimeManager.Instance:GetServerTime() end) nowms=math.floor(tonumber(nowms) or 0) if nowms < 1600000000000 then return '' end local P=LuaEntry and LuaEntry.Player if P==nil then return '' end local nick='' pcall(function() nick=tostring(P:GetName() or ''):gsub('%s+',' ') end) local lv=0 pcall(function() lv=math.floor((tonumber(P.level) or 0)+0) end) local pw=0 pcall(function() pw=math.floor((tonumber(P.power) or 0)+0) end) local al='' pcall(function() if P:IsInAlliance() then al=tostring(P:GetFullAllianceName() or ''):gsub('%s+',' ') end end) local st=0 pcall(function() st=math.floor((tonumber(P:GetCurStamina()) or 0)+0) end) local sf=0 pcall(function() sf=math.floor((tonumber(P:GetStaminaFullTime()) or 0)+0) end) local rg=0 pcall(function() rg=math.floor((tonumber(P.regTime) or 0)+0) end) if nick=='' and lv==0 and pw==0 then return '' end return nick..';;'..lv..';;'..pw..';;'..al..';;'..st..';;'..sf..';;'..rg end)() INTO player_card
LOG "player card: {player_card}"
