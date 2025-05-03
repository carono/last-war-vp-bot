--lua
CodeNameEvent = {}

function CodeNameEvent:execute()
    if (Event:openEventTab('code_name') == 1 and click_blue_button(969, 1009) == 1) then
        wait(2000)
        CodeNameEvent:attackBoss()
        return 1
    end
    Map:normalize()
    return 0
end

function CodeNameEvent:attackBoss(attack_number)
    attack_number = attack_number or 1
    click(903, 529, 1000)
    if (Hero:openAttackMenu() == 1) then
        wait(1000)
        Hero:clickAttack()
        wait(62000)
        click_blue_button(924, 672)
        if (attack_number < 5) then
            return CodeNameEvent:attackBoss(attack_number + 1)
        end
        return 1
    end
    return 0
end