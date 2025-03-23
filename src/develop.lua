Window:resizeCanonical()

function saveimage_from_screen(x, y, x2, y2, file)
    file = file or "img/tmp.bmp"
    local handle = Window:getGameHandle()
    require("src/image")
    require("src/image-test")

    --saveBitmapPart(handle, 50, 50, 150, 150, file)
    testSaveBitmapPart()

    --address, width, height, length = getimage(x, y, x2, y2)
    --address, width, height, length = getimage(0, 0, 500, 500)
    --saveimage(file, address)
end

