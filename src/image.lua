local ffi = require("ffi")

ffi.cdef[[
    typedef void* HBITMAP;
    typedef void* HDC;
    typedef void* HWND;
    typedef unsigned char BYTE;
    typedef unsigned int DWORD;

    HDC GetDC(HWND hWnd);
    HDC CreateCompatibleDC(HDC hdc);
    HBITMAP CreateCompatibleBitmap(HDC hdc, int width, int height);
    int GetDIBits(HDC hdc, HBITMAP hBitmap, uint32_t startY, uint32_t cLines, void* lpvBits, void* lpbi, uint32_t usage);
    int DeleteObject(void* hObject);
    int SelectObject(HDC hdc, void* hObject);
    int BitBlt(HDC hdcDest, int xDest, int yDest, int width, int height, HDC hdcSrc, int xSrc, int ySrc, int rop);
]]

ffi.cdef[[
    typedef struct {
        uint16_t bfType;
        uint32_t bfSize;
        uint16_t bfReserved1;
        uint16_t bfReserved2;
        uint32_t bfOffBits;
    } BITMAPFILEHEADER;

    typedef struct {
        uint32_t biSize;
        int32_t biWidth;
        int32_t biHeight;
        uint16_t biPlanes;
        uint16_t biBitCount;
        uint32_t biCompression;
        uint32_t biSizeImage;
        int32_t biXPelsPerMeter;
        int32_t biYPelsPerMeter;
        uint32_t biClrUsed;
        uint32_t biClrImportant;
    } BITMAPINFOHEADER;

    typedef struct {
        BITMAPINFOHEADER bmiHeader;
        BYTE bmiColors[1];
    } BITMAPINFO;
]]

function saveBitmapPart(hBitmap, x, y, width, height, outputFilePath)
    -- Получаем контекст устройства
    local hdcScreen = ffi.C.GetDC(0)
    local hdcMem = ffi.C.CreateCompatibleDC(hdcScreen)

    -- Создаем новый HBITMAP для сохраненной части
    local hBitmapPart = ffi.C.CreateCompatibleBitmap(hdcScreen, width, height)
    ffi.C.SelectObject(hdcMem, hBitmapPart)

    -- Копируем часть изображения из hBitmap в hBitmapPart
    ffi.C.BitBlt(hdcMem, 0, 0, width, height, hdcScreen, x, y, 0x00CC0020)

    -- Структура для хранения информации о картинке
    local dibHeader = ffi.new("BITMAPINFO")
    dibHeader.bmiHeader.biSize = ffi.sizeof("BITMAPINFOHEADER")
    dibHeader.bmiHeader.biWidth = width
    dibHeader.bmiHeader.biHeight = height
    dibHeader.bmiHeader.biPlanes = 1
    dibHeader.bmiHeader.biBitCount = 24 -- 24 бита на пиксель
    dibHeader.bmiHeader.biCompression = 0 -- BI_RGB (без сжатия)
    dibHeader.bmiHeader.biSizeImage = width * height * 3 -- Размер изображения
    dibHeader.bmiHeader.biXPelsPerMeter = 0
    dibHeader.bmiHeader.biYPelsPerMeter = 0
    dibHeader.bmiHeader.biClrUsed = 0
    dibHeader.bmiHeader.biClrImportant = 0

    -- Буфер для хранения данных пикселей
    local buffer = ffi.new("BYTE[?]", dibHeader.bmiHeader.biSizeImage)

    -- Получаем данные пикселей
    ffi.C.GetDIBits(hdcMem, hBitmapPart, 0, height, buffer, dibHeader, 0)

    -- Открываем файл для записи
    local file = io.open(outputFilePath, "wb")

    -- Записываем заголовок BMP
    local bmpFileHeader = ffi.new("BITMAPFILEHEADER")
    bmpFileHeader.bfType = 0x4D42 -- "BM"
    bmpFileHeader.bfSize = ffi.sizeof("BITMAPFILEHEADER") + ffi.sizeof("BITMAPINFOHEADER") + dibHeader.bmiHeader.biSizeImage
    bmpFileHeader.bfOffBits = ffi.sizeof("BITMAPFILEHEADER") + ffi.sizeof("BITMAPINFOHEADER")

    -- Заголовок файла
    file:write(ffi.string(bmpFileHeader, ffi.sizeof("BITMAPFILEHEADER")))
    -- Заголовок информации о картинке
    file:write(ffi.string(dibHeader, ffi.sizeof("BITMAPINFOHEADER")))

    -- Паддинг строк
    local rowSize = math.ceil(width * 3 / 4) * 4 -- Размер строки с паддингом (выравнивание)
    local paddedBuffer = ffi.new("BYTE[?]", rowSize * height)

    -- Копируем данные пикселей в выровненный буфер
    for row = 0, height - 1 do
        ffi.copy(paddedBuffer + row * rowSize, buffer + row * width * 3, width * 3)
    end

    -- Записываем выровненные данные пикселей в файл
    file:write(ffi.string(paddedBuffer, rowSize * height))

    -- Закрываем файл
    file:close()

    -- Освобождаем ресурсы
    ffi.C.DeleteObject(hBitmapPart)
    ffi.C.DeleteObject(hdcMem)
    ffi.C.DeleteObject(hdcScreen)
end