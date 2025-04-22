--lua

require('dist/init')

:: start ::

if (Radar:hasEasterEggNotification() == 1 or Radar:searchEasterEggInChat() > 0) then
    if (kfindcolor(1168, 1013, 16765462) == 0) then
        click_and_wait_color(1045, 970, color_blue, 1168, 1015)
    end
    local x, y = Radar:searchEasterEggInChat()
    if (x > 0) then
        click_and_wait_color(x, y, blue_color, 957, 704)
        Radar:clickEasterEggModal()
        escape(1000, 'Close easter egg modal')
        escape(1000, 'Close chat')
    end
end

if (Radar:hasTreasureExcavatorNotification() == 1) then
    local telegram_chat = Storage:get('telegram_chat')
    log(telegram_chat)
    local telegram_bot_id = Storage:get('telegram_bot')
    local treasure_message = Storage:get('treasure_message')
    if (telegram_bot_id ~= nil) then
        exec('curl --ssl-no-revoke "https://api.telegram.org/bot' .. telegram_bot_id .. '/sendMessage?chat_id=' .. telegram_chat .. '&text=' .. treasure_message .. '"')
        click(1045, 970, 1000)
    end
end

goto start