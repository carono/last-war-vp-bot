--lua
CodeNameEvent = {}
local bossAttackCount = 0
function CodeNameEvent:execute()
    if (os.date("*t").wday == 1) then
        return 0
    end
    log('Execute code_name event')
    if (Event:openEventTab('code_name') == 1) then
        if (click_blue_button(969, 1009) == 1) then
            wait(2000)
            CodeNameEvent:attackBoss(5)
            return 1
        end
        if (click_if_red(1154, 429) == 1 and click_if_green(1116, 303) == 1) then
            close_gift_modal()
            wait(1000)
        end
    end
    return 0
end

function CodeNameEvent:attackBoss(max_attack)
    log('Try attack boss')
    max_attack = max_attack or 5

    click(903, 529, 1000)
    if (Hero:openAttackMenu() == 1) then
        wait(1000)
        Hero:march()
        wait(62000)
        click_blue_button(924, 672)
        if (bossAttackCount < max_attack) then
            bossAttackCount = bossAttackCount + 1
            return CodeNameEvent:attackBoss(max_attack)
        end
        return 1
    end
    return 0
end