--lua




require("src/color/def")

local rmem = ffi.cast
local C = ffi.C

local SRCCOPY = 0x00CC0020
local CAPTUREBLT = 0x40000000
local DIB_RGB_COLORS = 0
local BI_RGB = 0

local ext = {} -- функции для экспорта.
ext.images = {} -- список функций буфера.
local images = {} -- непосредственно буфер.
local internal = {} -- внутренние функции.


ext.wait = {} -- блок дейстивий по ожиданию цвета/изображений/кликов/окон.
ext.wait.log = 1  -- включить ввывод description в лог.
ext.wait.log_level = 2  -- уровень логирования для description.
ext.lg_level = 1       -- уровень логирования. Для вывода сообщения должен быть больше или равен
-- заданному при вызове функции.
-- Если при вызове функции уровень не задан, то он считается равным 0.

ext.getimage = function(x1, y1, x2, y2, handle)
    local w, h
    local x, y = windowpos(handle)

    handle = ffi.cast("void *", handle)
    w = x2 - x1 - 13
    h = y2 - y1 - 32

    x1 = x1 + x + 13
    y1 = y1 + y + 32
    x2 = x2 + x
    y2 = y2 + y

    local desktop = C.GetDesktopWindow()
    local hdcWindow = C.GetWindowDC(desktop)

    local hdcMemDC = C.CreateCompatibleDC(hdcWindow)
    local hbmScreen = C.CreateCompatibleBitmap(hdcWindow, w, h)
    local objBackup = C.SelectObject(hdcMemDC, hbmScreen)

    local rect = ffi.new("RECT")

    if C.GetWindowRect(handle, rect) == 0 then
        log("GetWindowRect failed")
        return nil
    end

    C.SelectObject(hdcMemDC, hbmScreen)
    C.BitBlt(hdcMemDC, 0, 0, w, h, hdcWindow, x1, y1, bit.bor(SRCCOPY, CAPTUREBLT))

    local bi = ffi.new('BITMAPINFO', { { ffi.sizeof('BITMAPINFOHEADER'), w, -h, 1, 24, BI_RGB, 0, 0, 0, 0, 0 } })
    C.GetDIBits(hdcWindow, hbmScreen, 0, h, nil, bi, DIB_RGB_COLORS)   -- узнать какого размера нужен массив

    local bitmap_address = ffi.gc(C.malloc(bi.bmiHeader.biSizeImage), C.free)
    local h_copied = C.GetDIBits(hdcWindow, hbmScreen, 0, h, bitmap_address, bi, DIB_RGB_COLORS)   -- получить битовый массив


    if h_copied > 0 then

        C.DeleteDC(hdcMemDC)
        C.SelectObject(hdcMemDC, objBackup)
        C.ReleaseDC(handle, hdcWindow)
        C.DeleteObject(hdcMemDC)
        C.DeleteObject(hbmScreen)

        return bitmap_address, w, h_copied, math.floor(w * 3 / 4 + 0.75) * 4
    else
        return nil
    end

end




-- ext.saveimage
-- Сохранение изображений.
-- Допустимый синтаксис:
-- <path>, <address>[, x1, y1, x2, y2] -- если загружено новым getimage
-- <path>, <{address, width, height}>[, x1, y1, x2, y2]
-- <path>, <{a=val, w=val, h=val}>[, x1, y1, x2, y2]
-- <path>, <{address=val, width=val, height=val}>[, x1, y1, x2, y2]
-- path - пусть по которому необходимо сохранить изображение
-- address - адрес в памяти по которму находится изображение
-- width - ширина изображения
-- height - высота изображения
-- x1, y1 - начальные координаты сохраняемого изображения
-- x2, y2 - конечные координаты сохраняемого изображения
-- Если указаны x1, y1, x2, y2, то указывать высоту исходного
-- изображения не обязательно.

ext.saveimage = function()
end
do

    local FILE_READ_DATA = 0x1
    local FILE_WRITE_DATA = 0x2

    local FILE_SHARE_READ = 0x00000001
    local FILE_SHARE_WRITE = 0x00000002

    local CREATE_ALWAYS = 0x2

    local FILE_ATTRIBUTE_NORMAL = 0x80

    local bmp_headers = {}

    bmp_headers[1] = ffi.new("const unsigned char[2]", { 0x42,
                                                         0x4D })
    --  file_size 4 bytes
    bmp_headers[2] = ffi.new("const unsigned char[12]", { 0x00,
                                                          0x00,
                                                          0x00,
                                                          0x00,
                                                          0x36,
                                                          0x00,
                                                          0x00,
                                                          0x00,
                                                          0x28,
                                                          0x00,
                                                          0x00,
                                                          0x00 })
    --  image_width 4 bytes signed integer
    --  image_height 4 bytes signed integer
    bmp_headers[3] = ffi.new("const unsigned char[8]", { 0x01,
                                                         0x00,
                                                         0x18, -- the number of bits per pixel, which is the color depth of the image. Typical values are 1, 4, 8, 16, 24 and 32
                                                         0x00,
                                                         0x00,
                                                         0x00,
                                                         0x00,
                                                         0x00 })
    --  bitmap_size (w*h*3)
    bmp_headers[4] = ffi.new("const unsigned char[16]", { 0x00,
                                                          0x00,
                                                          0x00,
                                                          0x00,
                                                          0x00,
                                                          0x00,
                                                          0x00,
                                                          0x00,
                                                          0x00,
                                                          0x00,
                                                          0x00,
                                                          0x00,
                                                          0x00,
                                                          0x00,
                                                          0x00,
                                                          0x00 })

    ext.saveimage = function(path, bitmap_address, w, h, l)
        local handle = C.CreateFileA(
                path,
                FILE_READ_DATA + FILE_WRITE_DATA,
                FILE_SHARE_READ + FILE_SHARE_WRITE,
                nil,
                CREATE_ALWAYS,
                FILE_ATTRIBUTE_NORMAL,
                nil
        )

        local dwbuf = ffi.new 'DWORD[1]'

        C.WriteFile(handle, bmp_headers[1], 2, dwbuf, nil)
        C.WriteFile(handle, ffi.new("uint32_t[1]", h * w * 3 + 54), 4, dwbuf, nil)
        C.WriteFile(handle, bmp_headers[2], 12, dwbuf, nil)
        C.WriteFile(handle, ffi.new("uint32_t[1]", w), 4, dwbuf, nil)
        C.WriteFile(handle, ffi.new("uint32_t[1]", -h), 4, dwbuf, nil)
        C.WriteFile(handle, bmp_headers[3], 8, dwbuf, nil)
        C.WriteFile(handle, ffi.new("uint32_t[1]", w * h * 3), 4, dwbuf, nil)
        C.WriteFile(handle, bmp_headers[4], 16, dwbuf, nil)
        C.WriteFile(handle, bitmap_address, h * l, dwbuf, nil)

        -- Проверка размера через io.open, но используем другую переменную
        local lua_file = io.open(path, "rb")
        if lua_file then
            log("Размер сохранённого файла: ", lua_file:seek("end"))
            lua_file:close()
        end

        -- Правильное закрытие HANDLE
        C.CloseHandle(handle)

        collectgarbage()
    end
end

getimage2 = ext.getimage
saveimage2 = ext.saveimage

return ext


