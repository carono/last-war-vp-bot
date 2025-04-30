--lua
ffi = require "ffi"

ffi.cdef[[
typedef long LONG;
typedef unsigned short WORD;
typedef unsigned long DWORD;
typedef unsigned char BYTE;
typedef unsigned int UINT;
typedef int BOOL;
typedef void* LPVOID;
typedef void* HANDLE;
typedef HANDLE HDC;
typedef HANDLE HBITMAP;
typedef HANDLE HGDIOBJ;
typedef HANDLE HWND;
typedef HANDLE HRGN;
typedef unsigned long ULONG_PTR;
typedef ULONG_PTR SIZE_T;

// Структуры
typedef struct {
  DWORD biSize;
  LONG  biWidth;
  LONG  biHeight;
  WORD  biPlanes;
  WORD  biBitCount;
  DWORD biCompression;
  DWORD biSizeImage;
  LONG  biXPelsPerMeter;
  LONG  biYPelsPerMeter;
  DWORD biClrUsed;
  DWORD biClrImportant;
} BITMAPINFOHEADER;

typedef struct {
  BYTE rgbBlue;
  BYTE rgbGreen;
  BYTE rgbRed;
  BYTE rgbReserved;
} RGBQUAD;

typedef struct {
  BITMAPINFOHEADER bmiHeader;
  RGBQUAD bmiColors[1];
} BITMAPINFO;

typedef struct {
  LONG left;
  LONG top;
  LONG right;
  LONG bottom;
} RECT;

// Функции из GDI32 и User32
HDC GetDC(HWND hWnd);
HDC GetWindowDC(HWND hWnd);
int ReleaseDC(HWND hWnd, HDC hDC);
HDC CreateCompatibleDC(HDC hdc);
HBITMAP CreateCompatibleBitmap(HDC hdc, int cx, int cy);
HGDIOBJ SelectObject(HDC hdc, HGDIOBJ h);
BOOL DeleteDC(HDC hdc);
BOOL DeleteObject(HGDIOBJ ho);
BOOL BitBlt(HDC hdcDest, int xDest, int yDest, int w, int h, HDC hdcSrc, int xSrc, int ySrc, DWORD rop);
int GetDIBits(HDC hdc, HBITMAP hbmp, UINT uStartScan, UINT cScanLines, LPVOID lpvBits, BITMAPINFO *lpbi, UINT uUsage);
BOOL PrintWindow(HWND hwnd, HDC hdcBlt, UINT nFlags);
BOOL RedrawWindow(HWND hWnd, const RECT* lprcUpdate, HRGN hrgnUpdate, UINT flags);
BOOL GetClientRect(HWND hWnd, RECT* lpRect);
BOOL RedrawWindow(void* hWnd, const RECT* lprcUpdate, void* hrgnUpdate, unsigned int flags);
HWND GetDesktopWindow(void);
BOOL GetWindowRect(HWND hWnd, RECT* lpRect);
// memory (C stdlib)
void free(void *ptr);
void *malloc(SIZE_T size);
]]


ffi.cdef [[
typedef void           VOID, *PVOID, *LPVOID;
typedef VOID*          HANDLE, *PHANDLE;
typedef void           VOID, *PVOID, *LPVOID;
typedef const void*    LPCVOID;
typedef char*          LPSTR;
typedef const char*    LPCSTR;
typedef wchar_t        WCHAR;
typedef const WCHAR*   LPCWSTR;
typedef unsigned long  DWORD, *PDWORD, *LPDWORD;

typedef struct {
    DWORD  nLength;
    LPVOID lpSecurityDescriptor;
    BOOL   bInheritHandle;
} SECURITY_ATTRIBUTES, *LPSECURITY_ATTRIBUTES;

HANDLE CreateFileA(
    LPCSTR lpFileName,
    DWORD dwDesiredAccess,
    DWORD dwShareMode,
    LPSECURITY_ATTRIBUTES lpSecurityAttributes,
    DWORD dwCreationDisposition,
    DWORD dwFlagsAndAttributes,
    HANDLE hTemplateFile
);
BOOL CloseHandle(HANDLE hObject);

BOOL WriteFile(
    HANDLE       hFile,
    LPCVOID      lpBuffer,
    DWORD        nNumberOfBytesToWrite,
    LPDWORD      lpNumberOfBytesWritten,
    void*        lpOverlapped
);
]]