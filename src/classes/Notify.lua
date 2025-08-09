--lua
Notify = {}

function Notify:execTelegramRequest(telegram_bot_id, telegram_chat_id, message)
    local query = { chat_id = telegram_chat_id, text = AnsiToUtf8(message) }
    local url = build_url('https://api.telegram.org/bot' .. telegram_bot_id .. '/sendMessage', query)
    log('Send telegram message "' .. message .. '" to ' .. telegram_chat_id)
    exec('curl --ssl-no-revoke "' .. url .. '"')
end

function Notify:sendTelegramMessage(message, telegram_chat_id, telegram_bot_id, message_prefix)
    if message == nil then
        return 0
    end
    telegram_chat_id = telegram_chat_id or Storage:get('telegram_chat_id')
    telegram_bot_id = telegram_bot_id or Storage:get('telegram_bot_id')
    message_prefix = message_prefix or true
    if (telegram_bot_id == nil) then
        log('Telegram bot token is not defined, please set variable "telegram_bot_id" in ' .. Storage:getConfig())
        return 0
    end
    if (telegram_chat_id == nil) then
        log('Telegram chat ID is not defined, please set variable "telegram_chat_id" in ' .. Storage:getConfig())
        return 0
    end

    if (message_prefix == true) then
        message = Storage:get('username', os.getenv('username')) .. ': ' .. message
    else
        message = message_prefix .. ': ' .. message
    end

    Notify:execTelegramRequest(telegram_bot_id, telegram_chat_id, message)
end

function Notify:accountIsLogout()
    local message = Storage:get('logout_notify_message', "Bip-Bup")
    Notify:sendTelegramMessage(message)
end

function Notify:sendHasLabel(message)
    local prefix = Storage:get('label_notify_message', "")
    Notify:sendTelegramMessage(message, nil, nil, prefix)
end

function Notify:accountStartGame()
    if (Storage:get('login_notify', 0) == 1) then
        local message = Storage:get('login_notify_message', "Login")
        Notify:sendTelegramMessage(message)
    end
end

function Notify:label()
    if (kfindcolor(716, 40, 7520751) == 1) then
        return 2
    end
    if (find_colors(679, 16, 757, 44, { { 706, 33, 2147311 }, { 738, 35, 10596246 } }) > 0) then
        return 'storm'
    end
end

function Notify:hasLabel()
    if (kfindcolor(1006, 24, 16250612) == 1) then
        return 1
    end
    return 0
end