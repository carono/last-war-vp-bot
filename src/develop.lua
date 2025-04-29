Window:resizeCanonical()

function save_image_from_screen(x, y, x2, y2, file)
    file = file or "img/tmp.bmp"

    require("lib/color")

    address, width, height, length = getimage(x, y, x2, y2)
    saveimage(file, address)


end

