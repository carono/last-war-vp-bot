Window:resizeCanonical()

function save_image_from_screen(x, y, x2, y2, file)
    file = file or "img/tmp.bmp"
    local h = Window:getGameHandle()

    require("src/color/color")
    address, width, height, length = getimage2(x, y, x2, y2, h)
    saveimage2(file, address, width, height, length)
end

