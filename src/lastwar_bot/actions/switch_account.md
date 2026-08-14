# Switch the client to another character of this account.
# ru: Смена персонажа — переключить клиент на другого персонажа этого аккаунта.

ARGS server = 0

# One account can hold several characters, one per server, and the game switches
# between them from «Профиль → Аккаунт → Персонажи»: tap a character, and the client
# logs out and comes back as it. This is that tap, without the two screens.
#
# `server` is the server the wanted character is on — the same number the panel's
# «Аккаунты» tab shows in its «Сервер» column, and the `id` field of the character
# list the server sends. There is no other way to name a character: one account has
# at most one character per server.
#
# How the switch works, and why the earlier attempt did not, is written up in
# docs/research/account-list.md §4. The short version: the login screen's cell handler
# builds its message out of a table only that screen fills, so from inside a session
# it sent an empty user name and the server refused it (`120618`). The character
# screen's route needs nothing typed — every credential is already in the character
# list the server sent (`ip`, `port`, `zone`, `loginKey`, `gameUid`) — and that is
# what `TAP switch_account` presses.
#
# The list has to be loaded first: a session that never opened «Персонажи» has none,
# and the server answers the request asynchronously, so it is asked once and then
# polled. Once it is there the two ways this can be a no-op — no character on that
# server, or that character is already the one in play — are refusals with their own
# names, rather than a press that quietly does nothing.
#
# After the press the client tears the session down and reconnects on its own. That
# takes a good few seconds and looks exactly like a relog: the game window returns to
# the loading screen and comes back on the other character's base. It happens IN the
# same process, so the Lua daemon lives through it and nothing has to be reattached.
# The run only succeeds once the game itself says the new character is the one in play
# and its base is up, so a switch that stalls halfway is a failure and not a false
# "done".
#
# Proven live 2026-08-02 (#1192): 100 -> 200 and back, both directions from a cold
# session that had never asked for the character list.
#
# NOT for a timer. This ends the session it was started in — anything else the panel
# was doing on the old character stops with it.

IF server == 0
    FAIL "no character was named — pass the server its character is on"

# --- the character list, asked for once and then polled ---------------------
READ_LUA (function() local n = 0 local function scan(fn) local roles = DataCenter.AccountManager.rolesList if type(roles) ~= 'table' then return end for _, v in pairs(roles) do if type(v) == 'table' and not v.isEmpty then fn(v) end end end scan(function() n = n + 1 end) return n end)() INTO characters

IF characters == 0
    TAP list_characters

WHILE characters == 0 LIMIT 6
    WAIT 1
    READ_LUA (function() local n = 0 local function scan(fn) local roles = DataCenter.AccountManager.rolesList if type(roles) ~= 'table' then return end for _, v in pairs(roles) do if type(v) == 'table' and not v.isEmpty then fn(v) end end end scan(function() n = n + 1 end) return n end)() INTO characters

IF characters == 0
    FAIL "the server did not answer with this account's characters"

# --- the character to switch to, parked where the press can read it ---------
LUA DataCenter.__lw_switch_account = {server}

READ_LUA (function() local sid = tostring(DataCenter.__lw_switch_account or 0) local hit = 0 local function scan(fn) local roles = DataCenter.AccountManager.rolesList if type(roles) ~= 'table' then return end for _, v in pairs(roles) do if type(v) == 'table' and not v.isEmpty then fn(v) end end end scan(function(v) if tostring(v.id) == sid then hit = 1 end end) if hit == 0 then return 0 end local cur = 0 pcall(function() cur = LuaEntry.Player.serverId end) if tostring(cur) == sid then return -1 end return 1 end)() INTO target

IF target == 0
    FAIL "this account has no character on server {server}"

IF target < 0
    FAIL "the character on server {server} is the one already in play"

# --- the switch itself, then the reconnect ----------------------------------
TAP switch_account

READ_LUA (function() local cur = 0 pcall(function() cur = LuaEntry.Player.serverId end) if not cur or tonumber(cur) == nil or tonumber(cur) == 0 then pcall(function() cur = DataCenter.WorldFavoDataManager.curServerId end) end return tonumber(cur) or 0 end)() INTO playing

WHILE playing != {server} LIMIT 40
    WAIT 2
    READ_LUA (function() local cur = 0 pcall(function() cur = LuaEntry.Player.serverId end) if not cur or tonumber(cur) == nil or tonumber(cur) == 0 then pcall(function() cur = DataCenter.WorldFavoDataManager.curServerId end) end return tonumber(cur) or 0 end)() INTO playing

IF playing != {server}
    FAIL "the client did not come back on server {server} — it may still be reconnecting"

# The player record is restored a few seconds before the scene finishes drawing, so
# "done" waits for that too — otherwise whatever runs next arrives mid-load.
#
# A SCENE, not the base (#1399, the lesson of #1281 applied here). The switch reconnects
# on the other character's LAST scene, and a character left standing on the world map
# never reaches `city` — so this waited out its whole 180 s and failed a switch that had
# worked. `scene != unknown` is «the client is drawing something a person could play»,
# which is all this line was ever for. The daemon lives through the relog (same process),
# so the scene is readable throughout and there is nothing weaker to fall back to.
WAIT scene != unknown WITHIN 180s

LOG "now playing the character on server {server}"
