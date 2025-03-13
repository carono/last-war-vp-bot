Window:resizeCanonical()

function saveimage_from_screen(x, y, x2, y2)
    local handle = Window:getGameHandle()
    address, width, height, length = getimage(x, y, x2, y2, handle)
    saveimage("img/tmp.bmp", address)
end