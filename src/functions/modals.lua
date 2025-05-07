function close_gift_modal()
    log('Waiting modal with gifts')
    if (wait_color(1068, 342, 7059183, 2000) == 1) then
        escape(1000, 'Close gift modal')
        if (kfindcolor(1068, 342, 7059183) == 1) then
            escape(1000, 'Close gift modal second try')
        end
        return 1
    end
    return 0
end

function close_help_modal()
    log('Waiting modal with gifts')
    if (wait_color(1084, 327, 2669297, 2000) == 1) then
        escape(1000, 'Close help modal')
        return 1
    end
    return 0
end