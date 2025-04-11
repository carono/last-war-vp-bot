--lua
require("os")

local game_path = os.getenv('LOCALAPPDATA') .. "\\TheLastWar\\Launch.exe"
local username = os.getenv('username')
local logout_timeout = 7 * 60 * 1000
local check_queue_timeout = 1 * 60 * 1000
local delay_after_check = 3 * 60 * 1000
local win_pos_x = 0
local win_pos_y = 0

storageLib = require [[lib/storage]]
local configFile = "config/" .. username .. ".config.env"
config = {
    game_path = game_path,
    logout_timeout = logout_timeout,
    check_queue_timeout = check_queue_timeout,
    delay_after_check = delay_after_check,
    win_pos_x = win_pos_x,
    win_pos_y = win_pos_y,
}

if (fileexists(configFile) == "0") then
    storageLib.save(configFile, config)
end

config = storageLib.load(configFile)