--lua
Notify = {}

function Notify:execTelegramRequest(telegram_bot_id, telegram_chat_id, message)
    local query = { chat_id = telegram_chat_id, text = AnsiToUtf8(message) }
    local url = build_url('https://api.telegram.org/bot' .. telegram_bot_id .. '/sendMessage', query)
    log('Send telegram message "' .. message .. '" to ' .. telegram_chat_id)
    exec('curl --ssl-no-revoke "' .. url .. '"')
end

function Notify:sendTelegramMessage(message, telegram_chat_id, telegram_bot_id)
    telegram_chat_id = telegram_chat_id or Storage:get('telegram_chat_id')
    telegram_bot_id = telegram_bot_id or Storage:get('telegram_bot_id')
    if (telegram_bot_id == nil) then
        log('Telegram bot token is not defined, please set variable "telegram_bot_id" in ' .. Storage:getConfig())
        return 0
    end
    if (telegram_chat_id == nil) then
        log('Telegram chat ID is not defined, please set variable "telegram_chat_id" in ' .. Storage:getConfig())
        return 0
    end

    message = Storage:get('username') .. ': ' .. message
    Notify:execTelegramRequest(telegram_bot_id, telegram_chat_id, message)
end

function Notify:accountIsLogout()
    local message = Storage:get('logout_notify_message', "Bip-Bup")
    Notify:sendTelegramMessage(message)
end

function Notify:accountStartGame()
    local message = Storage:get('login_notify_message', "Login")
    Notify:sendTelegramMessage(message)
end

function Notify:hasLabel()
    return kfindcolor(1006, 24, 16250612)
end