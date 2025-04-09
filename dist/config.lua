--lua
require("os")

game_path = os.getenv('LOCALAPPDATA') .. "\\TheLastWar\\Launch.exe"
username = os.getenv('username')
logout_timeout = 15 * 60 * 1000
check_queue_timeout = 1 * 60 * 1000
dalay_after_check = 3 * 60 * 1000
win_pos_x = 0
win_pos_y = 0

storageLib = require [[lib/storage]]
configFile = username .. ".config.env"
config = {
    game_path = game_path,
    logout_timeout = logout_timeout,
    check_queue_timeout = check_queue_timeout,
    dalay_after_check = dalay_after_check,
    win_pos_x = win_pos_x,
    win_pos_y = win_pos_y,
}

if (fileexists(configFile) == "0") then
    storageLib.save(configFile, config)
end

config = storageLib.load(configFile)