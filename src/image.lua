local ffi = require("ffi")
local C = ffi.C

ffi.cdef [[
    typedef unsigned char BYTE;
    typedef unsigned short WORD;
    typedef unsigned int DWORD;
    typedef int BOOL;
    typedef long LONG;
    typedef unsigned long ULONG_PTR;
    typedef ULONG_PTR SIZE_T;
    typedef const void* LPCVOID;
    typedef void* HWND;
    typedef void* HDC;
    typedef void* HBITMAP;

    HDC GetDC(HWND hWnd);
    int ReleaseDC(HWND hWnd, HDC hDC);
    HDC CreateCompatibleDC(HDC hdc);
    int DeleteDC(HDC hdc);
    HBITMAP CreateCompatibleBitmap(HDC hdc, int width, int height);
    void* SelectObject(HDC hdc, void* h);
    int DeleteObject(void* hObject);
    BOOL BitBlt(HDC hdcDest, int xDest, int yDest, int width, int height, HDC hdcSrc, int xSrc, int ySrc, DWORD rop);
    int GetDIBits(HDC hdc, HBITMAP hbm, DWORD start, DWORD cLines, void* lpvBits, void* lpbi, DWORD usage);
    void* malloc(SIZE_T size);
    void free(void* ptr);

    typedef struct {
        DWORD  biSize;
        LONG   biWidth;
        LONG   biHeight;
        WORD   biPlanes;
        WORD   biBitCount;
        DWORD  biCompression;
        DWORD  biSizeImage;
        LONG   biXPelsPerMeter;
        LONG   biYPelsPerMeter;
        DWORD  biClrUsed;
        DWORD  biClrImportant;
    } BITMAPINFOHEADER;

    typedef struct {
        BITMAPINFOHEADER bmiHeader;
        BYTE bmiColors[1];
    } BITMAPINFO;

    typedef struct {
        WORD bfType;
        DWORD bfSize;
        WORD bfReserved1;
        WORD bfReserved2;
        DWORD bfOffBits;
    } BITMAPFILEHEADER;

    HWND FindWindowA(LPCVOID lpClassName, LPCVOID lpWindowName);
]]

local SRCCOPY = 0x00CC0020
local BI_RGB = 0
local DIB_RGB_COLORS = 0

local images = {}

function save_bmp(filename, bitmap_address, width, height, rowSize)
    -- �������� �� ������������ ������ � ������
    if not width or not height then
        log("������: ���������� ��������� �����������, ��������� �� ������ ������ ��� ������.")
        return false
    end

    if width <= 0 or height <= 0 then
        log("������: �������� �������� ������ ��� ������ �����������.")
        return false
    end

    local file = io.open(filename, "wb")
    if not file then
        log("������: �� ������� ������� ���� ��� ������.")
        return false
    end

    local fileHeader = ffi.new("BITMAPFILEHEADER")
    local infoHeader = ffi.new("BITMAPINFOHEADER")

    -- ���������� ����������
    fileHeader.bfType = 0x4D42  -- 'BM'
    fileHeader.bfOffBits = ffi.sizeof("BITMAPFILEHEADER") + ffi.sizeof("BITMAPINFOHEADER")
    fileHeader.bfSize = fileHeader.bfOffBits + height * rowSize
    infoHeader.biSize = ffi.sizeof("BITMAPINFOHEADER")
    infoHeader.biWidth = width
    infoHeader.biHeight = height
    infoHeader.biPlanes = 1
    infoHeader.biBitCount = 24  -- 24-������ ����
    infoHeader.biCompression = BI_RGB
    infoHeader.biSizeImage = height * rowSize
    infoHeader.biXPelsPerMeter = 0
    infoHeader.biYPelsPerMeter = 0
    infoHeader.biClrUsed = 0
    infoHeader.biClrImportant = 0

    -- ������ ���������� � ����
    file:write(ffi.string(fileHeader, ffi.sizeof("BITMAPFILEHEADER")))
    file:write(ffi.string(infoHeader, ffi.sizeof("BITMAPINFOHEADER")))

    -- ������ �������� ����� ����� (BMP ������ ������� ����� �������)
    local pixelData = ffi.cast("char*", bitmap_address)
    for y = height - 1, 0, -1 do  -- BMP ������ ���������� ������ ����� �����
        file:write(ffi.string(pixelData + y * rowSize, rowSize))
    end

    file:close()
    log("����������� ��������� � ����:", filename)
    return true
end

function capture_window_region(hWndInt, x1, y1, x2, y2)
    local hWnd = ffi.cast("HWND", hWndInt)
    log("������ ����������� �� ���� � hWnd:", hWnd)

    if not hWnd or hWnd == ffi.NULL then
        log("������: �� ������� �������� hwnd ����!")
        return nil
    end

    local w = x2 - x1 + 1
    local h = y2 - y1 + 1
    if w <= 0 or h <= 0 then
        log("������: �������� ��������� ������ ��� ������!")
        return nil
    end

    log("������:", w, "������:", h)

    local hdcWindow = C.GetDC(hWnd)
    if not hdcWindow or hdcWindow == ffi.NULL then
        log("������: �� ������� �������� DC ����!")
        return nil
    end

    local hdcMemDC = C.CreateCompatibleDC(hdcWindow)
    if not hdcMemDC or hdcMemDC == ffi.NULL then
        C.ReleaseDC(hWnd, hdcWindow)
        log("������: �� ������� ������� ����������� DC!")
        return nil
    end

    local hBitmap = C.CreateCompatibleBitmap(hdcWindow, w, h)
    if not hBitmap or hBitmap == ffi.NULL then
        C.DeleteDC(hdcMemDC)
        C.ReleaseDC(hWnd, hdcWindow)
        log("������: �� ������� ������� ������!")
        return nil
    end

    local old = C.SelectObject(hdcMemDC, hBitmap)
    local res = C.BitBlt(hdcMemDC, 0, 0, w, h, hdcWindow, x1, y1, SRCCOPY)
    if res == 0 then
        log("������ ��� ���������� BitBlt.")
        C.SelectObject(hdcMemDC, old)
        C.DeleteObject(hBitmap)
        C.DeleteDC(hdcMemDC)
        C.ReleaseDC(hWnd, hdcWindow)
        return nil
    end

    local info = ffi.new("BITMAPINFO")
    info.bmiHeader.biSize = ffi.sizeof("BITMAPINFOHEADER")
    info.bmiHeader.biWidth = w
    info.bmiHeader.biHeight = -h
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 24
    info.bmiHeader.biCompression = BI_RGB
    info.bmiHeader.biSizeImage = 0

    local rowSize = math.floor((24 * w + 31) / 32) * 4
    local imageSize = rowSize * h
    local buffer = ffi.cast("uint8_t*", C.malloc(imageSize))

    if not buffer or buffer == ffi.NULL then
        C.SelectObject(hdcMemDC, old)
        C.DeleteObject(hBitmap)
        C.DeleteDC(hdcMemDC)
        C.ReleaseDC(hWnd, hdcWindow)
        log("������: �� ������� �������� ������ ��� �����������.")
        return nil
    end

    local ok = C.GetDIBits(hdcMemDC, hBitmap, 0, h, buffer, info, DIB_RGB_COLORS)
    if ok == 0 then
        log("������: �� ������� �������� ������ DIB.")
        C.free(buffer)
        C.SelectObject(hdcMemDC, old)
        C.DeleteObject(hBitmap)
        C.DeleteDC(hdcMemDC)
        C.ReleaseDC(hWnd, hdcWindow)
        return nil
    end

    C.SelectObject(hdcMemDC, old)
    C.DeleteObject(hBitmap)
    C.DeleteDC(hdcMemDC)
    C.ReleaseDC(hWnd, hdcWindow)

    local id = tonumber(ffi.cast("intptr_t", buffer))
    images[id] = {
        data = buffer,
        width = w,
        height = h,
        rowSize = rowSize,
        size = imageSize
    }

    -- ���������� � BMP
    local filename = "screenshot.bmp"
    if save_bmp(filename, buffer, w, h, rowSize) then
        log("����������� ������� ��������� � ����", filename)
    else
        log("�� ������� ��������� ����������� � ����.")
    end

    return id, w, h, rowSize
end
