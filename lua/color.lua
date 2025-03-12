--lua

local ffi=require "ffi"
local rmem = ffi.cast
local C = ffi.C

local SRCCOPY = 0x00CC0020
local DIB_RGB_COLORS = 0
local BI_RGB = 0
ffi.cdef[[
    typedef long LONG;
    typedef unsigned short WORD;
    typedef unsigned long DWORD;
    typedef unsigned char BYTE;
    typedef void *LPVOID;
    typedef struct {DWORD biSize; LONG  biWidth; LONG  biHeight; WORD  biPlanes; WORD  biBitCount; DWORD biCompression; DWORD biSizeImage;
                    LONG  biXPelsPerMeter; LONG biYPelsPerMeter; DWORD biClrUsed; DWORD biClrImportant;} BITMAPINFOHEADER;
    typedef struct {BYTE rgbBlue; BYTE rgbGreen; BYTE rgbRed; BYTE rgbReserved;} RGBQUAD;
    typedef struct {BITMAPINFOHEADER bmiHeader; RGBQUAD bmiColors[1];} BITMAPINFO;
    int GetDC(int hWnd);
    int ReleaseDC(int hWnd, int hDC);
    int SelectObject(int hdc, int h);
    int CreateCompatibleDC(int hdc);
    int CreateCompatibleBitmap(int hdc, int cx, int cy);
    bool DeleteObject(int ho);
    bool BitBlt(int hdc, int x, int y, int cx, int cy, int hdcSrc, int x1, int y1, unsigned long rop);
    int GetDIBits(int hdc, int hbm, unsigned int start, unsigned int cLines, LPVOID lpvBits, BITMAPINFO* lpbmi, unsigned int usage);

    void free(void *ptr);
    void *malloc(size_t size);
]]

local ext          = {} -- ������� ��� ��������.
      ext.images   = {} -- ������ ������� ������.
local images       = {} -- ��������������� �����.
local internal     = {} -- ���������� �������.


ext.wait           = {} -- ���� ��������� �� �������� �����/�����������/������/����.
ext.wait.log       = 1  -- �������� ������ description � ���.
ext.wait.log_level = 2  -- ������� ����������� ��� description.
ext.lg_level  = 1       -- ������� �����������. ��� ������ ��������� ������ ���� ������ ��� �����
                        -- ��������� ��� ������ �������.
                        -- ���� ��� ������ ������� ������� �� �����, �� �� ��������� ������ 0.

function ext.lg(data, comment, level)
    if  (not level and ext.lg_level < 0) or (level and level < ext.lg_level) then
        return
    end
    if  comment ~= nil then
        log(comment)
    end

    local tab = ""
    local deep = 0

    local function show(data)
        -- ����� � ��� �����������.
        deep = deep + 1 -- ������� ����������� ������� �������.

        if type(data) == "table"    then
            local element_counter = 0
            for k,v in pairs(data) do
                element_counter = element_counter + 1
                if  type (v) == "table" then
                    log(tab..'table: '..tostring(k))
                    tab = tab .. "    "
                    show(v)
                    tab = string.sub(tab, 1, -5)
                else
                    if     type(v) == "nil"       then v = "nil"
                    elseif type(v) == "string"    then v = '"' .. v .. '"'
                    elseif type(v) == "number"    then v = tostring(v)
                    elseif type(v) == "function"  then v = tostring(v)
                    elseif type(v) == "thread"    then v = tostring(v)
                    elseif type(v) == "userdata"  then v = "userdata"
                    elseif type(v) == "boolean"   then v = tostring(v)
                    elseif type(v) == "table"     then
                        log(tab..""..k.." = "..v or "nil")
                    else
                        v = "uknown data type"
                    end
                    log(tab..""..k.." = " .. v)
                end
            end
            log(tab.."".."Elements in table: " .. element_counter)
        else
            log('table is "' .. type(data) .. '" data type. Value: ' .. tostring(data))
        end
        
        --tab = ""
        --deep = 0
    end
    
    show(data)
end

ext.images.add = function(a,w,h,l)
    a = tonumber(ffi.cast("int",a))
    images[a] = {}
    images[a].address = a
    images[a].bitmap_address = ffi.cast("unsigned char*",a)
    images[a].width = w
    images[a].height = h
    images[a].lenght = l or math.floor(w*3/4+0.75)*4
end

-- ��������� ������� �����.
function ext.images.flush()
    for k,_ in pairs(images) do ext.deleteimage(k) end
end

internal.getimage_orig = getimage
ext.getimage = function(x1, y1, x2, y2, method, abs_flag)
    method = method or 0
  
    if type(x1) == 'number' then
        -- ����������� ���������� ���������� � �������������.
        -- ��� ������ 0 ����������� ��������� � ������,
        -- � �� � ����������. ���������� �������� ��������.
        if method == 0 and not abs_flag then
            local w_x, w_y, _, _ = windowpos(workwindow())
            x1 = x1 + w_x
            y1 = y1 + w_y
            x2 = x2 + w_x
            y2 = y2 + w_y
        end


        if method > 2 or method == 0 then
            local a, w, h, l
            w = x2-x1 + 1
            h = y2-y1 + 1
            
            local hdcWindow = C.GetDC(method or 0)  -- ���� ����� �� ������, �� ������� ����� � ������
            local hdcMemDC = C.CreateCompatibleDC(hdcWindow)
            local hbmScreen = C.CreateCompatibleBitmap(hdcWindow, w, h)
            
            C.SelectObject(hdcMemDC,hbmScreen)
            C.BitBlt(hdcMemDC, 0, 0, w, h, hdcWindow, x1, y1, SRCCOPY)  -- ��������� � ������ ����� � ���� ��� ������

            local bi = ffi.new('BITMAPINFO', { {ffi.sizeof('BITMAPINFOHEADER'), w, -h, 1, 24, BI_RGB,0,0,0,0,0} })
            C.GetDIBits(hdcWindow, hbmScreen, 0, h, nil, bi, DIB_RGB_COLORS)   -- ������ ������ ������� ����� ������

            local bitmap_address = ffi.gc(C.malloc(bi.bmiHeader.biSizeImage), C.free)
            local h_copied = C.GetDIBits(hdcWindow, hbmScreen, 0, h, bitmap_address, bi, DIB_RGB_COLORS)   -- �������� ������� ������


            --return h_copied and ffi.cast("int", bitmap_address) or nil, w, h_copied, math.floor(w*3/4+0.75)*4
            if h_copied > 0 then
                a = tonumber(ffi.cast("int", bitmap_address))
                
                images[a] = {}
                images[a].method = method
                images[a].hdcWindow = hdcWindow
                images[a].hdcMemDC = hdcMemDC
                images[a].hbmScreen = hbmScreen
                images[a].bitmap_address = bitmap_address
                images[a].width = w
                images[a].height = h_copied
                images[a].lenght = math.floor(w*3/4+0.75)*4

                return a, w, h_copied, images[a].lenght
            else
                return nil
            end
        else
            return internal.getimage_orig(x1, y1, x2, y2, method, abs_flag)
        end
    else -- �������� ���� �����. �������� ����� � ������.
        if images[x1] then -- ��� ��������.
            return images[x1],
                   images[images[x1]].width,
                   images[images[x1]].height,
                   images[images[x1]].lenght
        else -- ����������
            local a, w, h, l = loadimage(x1)
            images[a] = {}
            images[a].method = x1
            images[a].bitmap_address = ffi.cast("void *",a)
            images[a].width = w
            images[a].height = h
            images[a].lenght = math.floor(w*3/4+0.75)*4
            images[x1] = a
            return a, w, h, l
        end
    end
end

internal.deleteimage_orig = deleteimage
ext.deleteimage = function(address)
--dbg.enable(1)
    if type(address) == "string" then
        local str = address
        address = image[address] -- ����������� ���� � �����.
        images[str] = nil
    end
    
    if images[address] then
        images[address].bitmap_address = nil
        if images[address].hdcWindow then -- �������� �������� �� ������ ��� ������� 0
            C.ReleaseDC(images[address].method, images[address].hdcWindow)
            C.DeleteObject(images[address].hdcMemDC)
            C.DeleteObject(images[address].hbmScreen)
        elseif type(images[address].method) == "string" then -- ��������� � �����, ������� ������
            internal.deleteimage_orig(address)
            images[images[address].method] = nil
        end
        if images[address].deviation then
            for k, v in pairs (images[address].deviation) do -- ������� ������������ deviation
                v[1] = nil
                v[2] = nil
                ext.deleteimage(v.a1)
                ext.deleteimage(v.a2)
            end
        end
        images[address] = nil
        collectgarbage()
    else
        internal.deleteimage_orig(address)
    end
    --stop_script()
end

-- ������������ ��� ����� �� ��������� ������.
ext.color_to_rgb = function(c)
    local r,g,b
    b = math.floor(c/65536)
    g = math.floor(c/256-b*256)
    r = c-b*256*256-g*256
    return r, g ,b
end

ext.color_to_bgr = function(c)
    local r,g,b
    b = math.floor(c/65536)
    g = math.floor(c/256-b*256)
    r = c-b*256*256-g*256
    return b, g, r
end

ext.rgb_to_color = function(r, g, b)
    return b*256*256 + g*256 + r
end

ext.bgr_to_color = function(b, g, r)
    return b*256*256 + g*256 + r
end

internal.color_deviation_parse = function(b1, g1, r1, b2, g2, r2)
    if type(b1) == "table" then
    
    else
    
    end

    if not g1 then
        g1 = b1
        r1 = b1
        b2 = b1
        g2 = b1
        r2 = b1
    elseif not b2 then
        b2 = b1
        g2 = g1
        r2 = r1
    else
        -- ������ ����������� �������� �������, ������������ ������.
        b1, g1, r1, b2, g2, r2 = b2, g2, r2, b1, g1, r1
    end
    return b1, g1, r1, b2, g2, r2
end

--[[=internal.color_deviation_parse = function(c1, c2, b1, g1, r1, b2, g2, r2)
    if type(b1) == "table" then
        if type(g1) == "table" then
            b2 = g1[1]
            g2 = g1[2]
            r2 = g1[3]
        else
            r2 = b2
            g2 = r1
            b2 = g1
        end
        r1 = b1[3]
        g1 = b1[2]
        b1 = b1[1]
    elseif type(b2) == "table" then
        r2 = b2[3]
        g2 = b2[2]
        b2 = b2[1]
    elseif not g1 and not r1 and not b2 and not g2 and not r2 then
        g1 = b1
        r1 = b1
        b2 = b1
        g2 = b1
        r2 = b1
    end

    if not b2 and not g2 and not r2 then
        r2 = r1
        g2 = g1
        b2 = b1
    end
    
    local c1r, c1g, c1b
    c1b = math.floor(c1/65536)
    c1g = math.floor(c1/256-c1b*256)
    c1r = c1-c1b*256*256-c1g*256
    
    local c2r, c2g, c2b
    c2b = math.floor(c2/65536)
    c2g = math.floor(c2/256-c2b*256)
    c2r = c2-c2b*256*256-c2g*256
    
    
    return b1, g1, r1, b2, g2, r2, c1r, c1g, c1b, c2r, c2g, c2b
end
]]

internal.color_deviation_a = function(c1b1, c1g1, c1r1, c1b2, c1g2, c1r2, c2b, c2g, c2r, b1, g1, r1, b2, g2, r2)
    if  c1r1 - b1 <= c2r and c1g1 - g1 <= c2g and c1b1 - r1 <= c2b and
        c1r2 + b2 >= c2r and c1g2 + g2 >= c2g and c1b2 + r2 >= c2b then
        return true
    else
        return false
    end
end

internal.color_deviation_r = function(c1b1, c1g1, c1r1, c1b2, c1g2, c1r2, c2b, c2g, c2r, b1, g1, r1, b2, g2, r2)
    local r1d = math.ceil(c1r1 * r1 * 0.01)
    local g1d = math.ceil(c1g1 * g1 * 0.01)
    local b1d = math.ceil(c1b1 * b1 * 0.01)
    
    local r2d = math.ceil(c1r2 * r2 * 0.01)
    local g2d = math.ceil(c1g2 * g2 * 0.01)
    local b2d = math.ceil(c1b2 * b2 * 0.01)

    if  c1r1 - r1d <= c2r and c1g1 - g1d <= c2g and c1b1 - b1d <= c2b and
        c1r2 + r2d >= c2r and c1g2 + g2d >= c2g and c1b2 + b2d >= c2b then
        return true
    else
        return false
    end
end

internal.color_deviation_s = function(c1b1, c1g1, c1r1, c1b2, c1g2, c1r2, c2b, c2g, c2r, br1, rg1, gb1, br2, rg2, gb2)
    c1b1, c1g1, c1r1, c1b2, c1g2, c1r2, c2b, c2g, c2r = c1b1+1, c1g1+1, c1r1+1, c1b2+1, c1g2+1, c1r2+1, c2b+1, c2g+1, c2r+1

    local c1br1 = c1b1/c1r1
    local c1rg1 = c1r1/c1g1
    local c1gb1 = c1g1/c1b1
    
    local c1br2 = c1b2/c1r2
    local c1rg2 = c1r2/c1g2
    local c1gb2 = c1g2/c1b2    
    
    local br_d1 = c1br1 * br1 * 0.01
    local rg_d1 = c1rg1 * rg1 * 0.01
    local gb_d1 = c1gb1 * gb1 * 0.01
    
    local br_d2 = c1br2 * br2 * 0.01
    local rg_d2 = c1rg2 * rg2 * 0.01
    local gb_d2 = c1gb2 * gb2 * 0.01
    
    local c2br = c2b/c2r
    local c2rg = c2r/c2g
    local c2gb = c2g/c2b
    
    --[[
    log(
    "", c1b1, c1g1, c1r1, "\r\n",
        c1b2, c1g2, c1r2, "\r\n",
        c2b, c2g, c2r
    )
    
    log(
    "", c1br1, c1rg1, c1gb1, "\r\n",
        c1br2, c1rg2, c1gb2, "\r\n",
        c2br,  c2rg,  c2gb
    )
    
    log(
    "", c1br1 , br_d1 , c2br , c1rg1 , rg_d1 , c2rg , c1gb1 , gb_d1 , c2gb , "\r\n",
        c1br2 , br_d2 , c2br , c1rg2 , rg_d2 , c2rg , c1gb2 , gb_d2 , c2gb
    )
    log(
    "", tostring(c1br1 - br_d1 <= c2br) , tostring(c1rg1 - rg_d1 <= c2rg) , tostring(c1gb1 - gb_d1 <= c2gb) , "\r\n",
        tostring(c1br2 + br_d2 >= c2br) , tostring(c1rg2 + rg_d2 >= c2rg) , tostring(c1gb2 + gb_d2 >= c2gb)
    )
    
    log(
    "", c1br1 - br_d1 ,"<=", c2br , c1rg1 - rg_d1 ,"<=", c2rg , c1gb1 - gb_d1 ,"<=", c2gb , "\r\n",
        c1br2 + br_d2 ,">=", c2br , c1rg2 + rg_d2 ,">=", c2rg , c1gb2 + gb_d2 ,">=", c2gb
    
    )
    ]]

    if  c1br1 - br_d1 <= c2br and c1rg1 - rg_d1 <= c2rg and c1gb1 - gb_d1 <= c2gb and
        c1br2 + br_d2 >= c2br and c1rg2 + rg_d2 >= c2rg and c1gb2 + gb_d2 >= c2gb then
        return true
    else
        return false
    end
end

internal.color_deviation = function(compare_func, c1, c2, b1, g1, r1, b2, g2, r2)
    local b1, g1, r1, b2, g2, r2 = internal.color_deviation_parse(b1, g1, r1, b2, g2, r2)
    local c2b, c2g, c2r = ext.color_to_bgr(c2)
    local cc = internal.parse_split_color_to_min_max_bgr(c1)

    return compare_func(cc[1][0], cc[1][1], cc[1][2], cc[1][3], cc[1][4], cc[1][5], c2b, c2g, c2r, b1, g1, r1, b2, g2, r2)
end

--[==[ color_deviation_a
-- ���������� true, ���� ���������
-- ������ � ���������� ���������� �����,
-- ����� ������ false.
-- ��� ����� �������� � ������� bgr, �� rgb.
-- ����� ��� �� ������������� ����� � ������� bgr.
-- b, g, r � ����� �������� ����� ���� ������ ��������.
-- ���������� ���������:
-- <����1>, <����2>, <value>
-- �������� ����������� ����������
-- �������� ����������� +/- b, g, r.
-- <����1>, <����2>, <b, g, r>
-- �������� ����������� ����������
-- �������� ����������� +/- b, g, r.
-- <����>, <����2>, <b1, g1, r1>, <b2[, g2[, r2]]>
-- �������� b1, g1, r1 ��������� ����������� � ����.
-- �������� b2, g2, r2 ��������� ����������� � �����.
-- ����� �� �������.]==]

ext.color_deviation_a = function(c1, c2, b1, g1, r1, b2, g2, r2)
    return internal.color_deviation(internal.color_deviation_a, c1, c2, b1, g1, r1, b2, g2, r2)
end

--[==[ color_deviation_r
-- ���������� true, ���� ���������
-- ������ � ���������� ���������� �����,
-- ����� ������ false.
-- ��� ����� �������� � ������� bgr, �� rgb.
-- ����� ��� �� ������������� ����� � ������� bgr.
-- b, g, r � ����� �������� ����� ���� ������ ��������.
-- ����������� ������� �
-- ��������� �� �������� �������� ������,
-- � ����������� � ������� �������.
-- �������� ��� ����� �����: 50 101 200 � �����������
-- ������ 10% ���������� ����������� ��������:
-- 50*10%=5, 101*10%=10.1=11, 200*10%=20
-- 50 101 200 �������� ����
-- 45  90 180 ���������� ����������
-- 55 112 220 ����������� ����������
-- ���������� ���������:
-- <����1>, <����2>, <value>
-- �������� ����������� ����������
-- �������� ����������� +/- b, g, r.
-- <����1>, <����2>, <b, g, r>
-- �������� ����������� ����������
-- �������� ����������� +/- b, g, r.
-- <����>, <����2>, <b1, g1, r1>, <b2[, g2[, r2]]>
-- �������� b1, g1, r1 ��������� ����������� � ����.
-- �������� b2, g2, r2 ��������� ����������� � �����.
-- ����� �� �������.]==]

ext.color_deviation_r = function(c1, c2, b1, g1, r1, b2, g2, r2)
    return internal.color_deviation(internal.color_deviation_r, c1, c2, b1, g1, r1, b2, g2, r2)
end

--[==[ color_deviation_s
-- ���������� true, ���� ���������
-- ������ � ���������� ���������� �����,
-- ����� ������ false.
-- ��� ����� �������� � ������� bgr, �� rgb.
-- ����� ��� �� ������������� ����� � ������� bgr.
-- b, g, r � ����� �������� ����� ���� ������ ��������.
-- ����������� ������� �
-- ��������� �� ��������� ������� ���� � �����,
-- � ����������� � ������� �������.
-- �������� ��� ����� �����: 50 101 200 � �����������
-- ������ 10% ���������� ����������� ��������:
-- 50*10%=5, 101*10%=10.1=11, 200*10%=20
-- 50 101 200 �������� ����
-- 45  90 180 ���������� ����������
-- 55 112 220 ����������� ����������
-- ���������� ���������:
-- <����1>, <����2>, <value>
-- �������� ����������� ����������
-- �������� ����������� +/- br, rg, gb.
-- <����1>, <����2>, <br, rg, gb>
-- �������� ����������� ����������
-- �������� ����������� +/- br, rg, gb.
-- <����>, <����2>, <br1, rg1, gb1>, <br2[, rg2[, gb2]]>
-- �������� br1, rg1, gb1 ��������� ����������� � ����.
-- �������� br2, rg2, gb2 ��������� ����������� � �����.
-- ����� �� �������.]==]

ext.color_deviation_s = function(c1, c2, br1, rg1, gb1, br2, rg2, bg2)
    return internal.color_deviation(internal.color_deviation_s, c1, c2, br1, rg1, gb1, br2, rg2, bg2)
end

internal.parse_channel_to_min_max = function(v)
    local min, max
    if v then
        min, max = string.match (v, "([0-9x]+)-*([0-9x]*)")
        min = tonumber(min)
        max = tonumber(max)
        if not max then max = min end               
    else
        min, max = 0, 255
    end
    return min, max
end

internal.parse_split_color_to_min_max_bgr = function(c)
    c = type(c) == "table" and c or {c}
    if c.r or c.g or c.b then
        c = {c}
    end
    local cc = ffi.new("uint8_t["..#c.."][6]")
    --log(type(c,#c))
    for i = 1, #c do
        if type(c[i]) == "table" then
            cc[i][0],cc[i][3] = internal.parse_channel_to_min_max(c[i].b)
            cc[i][1],cc[i][4] = internal.parse_channel_to_min_max(c[i].g)
            cc[i][2],cc[i][5] = internal.parse_channel_to_min_max(c[i].r)
        else
            local c1, c2 = string.match (c[i], "([0-9xabcdefABCDEF]+)-*([0-9xabcdefABCDEF]*)")
            c1 = tonumber(c1)
            c2 = tonumber(c2)
            cc[i][0] = math.floor(c1/65536)
            cc[i][1] = math.floor(c1/256-cc[i][0]*256)
            cc[i][2] = c1-cc[i][0]*256*256-cc[i][1]*256
            if c2 then
                cc[i][3] = math.floor(c2/65536)
                cc[i][4] = math.floor(c2/256-cc[i][3]*256)
                cc[i][5] = c2-cc[i][3]*256*256-cc[i][4]*256
            else
                cc[i][3],cc[i][4],cc[i][5] = cc[i][0],cc[i][1],cc[i][2] 
            end
        end
    end

    return cc
end

internal.deviation_parse = function(v)
    if type(v) == "number" then
        if v > 0 then
            v = {v, v, v, v, v, v}
        else
            v = nil -- �������� ��������� ����������.
        end
    elseif type(v) == "table" then
        vv[i][0],vv[i][3] = internal.parse_channel_to_min_max(c[i].b)
        vv[i][1],vv[i][4] = internal.parse_channel_to_min_max(c[i].g)
        vv[i][2],vv[i][5] = internal.parse_channel_to_min_max(c[i].r)
    end
    return v[1], v[2], v[3], v[4], v[5], v[6] 
end

--[====[ findcolor
-- ������� ������ ����� ���� ���������� ������,
-- � ������������ ������ ��������� ���������� � �������.
-- ���������:
-- result = findcolor(<x_start, y_start, x_end, y_end | table_crds>,
-- <color> [,method [,count [,deviaton [,deviation_type [,abs_flag]]]]])
--
-- <x_start, y_start, x_end, y_end | table_crds>
-- ���������� �������� � ���� ������������� �������
-- � ��������� ���������� ������ �������� ����
-- � ������� ������� ����.
-- ���������� ����� ���� ������ ������� �����������:
-- x_start, y_start, x_end, y_end
-- ���� �������� � ����������� ���������� ������:
-- {x_start, y_start, x_end, y_end}
-- ������ ��������� ��������� � 0, � �� 1.
-- �.�. ��� FullHD ������� ������ �����
-- 0, 0, 1919, 1079.
--
-- <color>
-- �����, ������� ��������������� ������.
-- ��������� ������ ������:
-- <color | {color_1 [,color_2 [,... [,color_N]]]}>
-- ���������� ������� �����:
-- < dec_hex_color | dec_hex_color_1-dec_hex_color_2 |
-- {[r=val_1] [,g=val_2] [,b=val_3]} | [{r="val_1-val_2"] [,g="val_3-val_4"] [,b="val_5-val_6"}] >
-- ������� ������ ����� ������������ � ������ ������. ��������:
-- 133972, 0x5060DD-0x5170DD, {r, g=0xFF, b-18}
--
-- [method]
-- ����� ������. �������� �� ���������: workwindow() - ����� ��������� ����.
-- 0/�� �����     - ������� �����. ������������ � ������ ���� ���������� �������� �����������
--                  �� ������, ����������� ��������.�������� ����������� ����� ������.
--                  ��� ��������� ����������� ����� ������, � �� ���� ����������� abs_flag.
-- 1              - ���������� �����, ������������ ��� �������������. ����� ���������.
--                  ��� ��������� ����������� ����� ������, � �� ���� ����������� abs_flag.
-- 2              - �������� �����. ������� ��������.
--                  ��� ��������� ����������� ����� ������, � �� ���� ����������� abs_flag.
-- ������_����    - ����� ������� �����. �������� � ����������� ������.
--                  ��������������� ������������ ������ ���. �� �������� � ���������� ������������.
--                  ��� ���������� ������ ����� ������������� ������ ����� ������������� ����.
-- �����_�������� - ����� ����������� � ������� bmp 24 ����.
--                  "my_image.bmp" - ����������� ����� � exe ������.
--                  "folder\\my_image.bmp" - ����������� � ����� folder ����� � exe ������
--                  "\\my_image.bmp" - ����������� � ����� �����, �� ������� ����� �����.
--                  [[d:\uopilot\images\my_image.bmp]] - ���������� ����.
--                  ������, ��� ��� ������� ������� � lua ������ '\' ���������� ���������,
--                  ���� �������� �� '/', ���� ����� ���� ����� � ������� ��������� ������.
-- �����_������,  - ����� � ����� ���������� ����������� �� ��������� ������� getimage()
-- ������_�����,    ����������� ����� ������� �����, ������ �����������, ������ � ����������
-- ������_�����,    ���� �� ������ ������. ��-�� ������������ ������ ������ ����� ����
-- �����.           �� ������� �������� �����������. ������ �������� ��� �� ������������
--                  ��� ����������� ������� ������� ����� (24 ���� ���� 24 ���� ���� + 8 ������).
--
-- [count]
-- ���������� ������� �����������. 0 | -1 - ����� ���.
--
-- [deviation]
-- ���������� ���������� �����.
-- ���������:
-- deviation_general | {blue, green, red} |
-- {blue_bottom, green_bottom, red_bottom, blue_upper, green_upper, red_upper}
-- ���������� ����� ����� ���� ������ ����� ������ �� ��� ������ � + � � -,
-- ���� �� ������ ����� ��������,
-- ���� �� ������ ����� �������� � �������� ������ � ������� ������� ������.
--
-- [deviation_type]
-- ��� ������� ����������� ���������� �����. �������� �� ��������� "r".
-- ��������� ��������:
-- "a" - absolute. ���������� ���������� ������.
--       ��������, ��� ����� 50 100 200 � ���������� ���������� 10,
--       ���������� �������� ������ ����� ����� 40-60, 90-110, 190-210
-- "r" - relative. ������������� ����������, �������� � ���������.
--       ��������, ��� ����� 50 100 200 � ������������� ���������� 10,
--       ���������� �������� ������ ����� ����� 45-55 90-110 180-220.
--       ���������� �������� � ������� ���������� ���������.
--       ��������, ��� �������� ������ 101 � ���������� ���������� 10%,
--       ����������� ���������� ������ ����� 101-11� 101+112, �.�. 90-112.
-- "s" - shadow. ����������/����������. �������������� ����������� �������, �������� � ���������.
--       ������ ����� ����� ���� �������, ��������, ��� ����� ����� � ����.
--       � ������ ������� ������ ���� 50 100 200 � ���� 25 50 100 - ����� ��������� ���������.
--       ��� ��������� ������: 200/50=4 50/100=0.5 100/200=0.5
--                             100/25=4  25/50=0.5  50/100=0.5
--       ��� ���������� ���������� � 10, ����� ��������� ����������� ����������� �������:
--       3.6-4.4 0.45-0.55 0.45-0.55
--
-- [abs_flag]
-- ���� ����������� �� ��, ��� ����������� ������ ���� �������� �� ������������ � ����
-- � �������� ����������� �������� ������ ����� Ctrl+A ��� workwindow,
-- � ������������ ������ �������� ���� ������.
-- ��������� ��� method 1, 2.]====]

ext.findcolor = function(x1, y1, x2, y2, c, method, count, deviation, deviation_type, abs_flag)
local t = os.clock()
    if  type(x1) == "table" then
        abs_flag       = count
        deviation_type = method
        deviation      = c
        count          = y2
        method         = x2
        c              = y1    
    end
--log(1, os.clock() - t)    
    c                  = type(c) == "table" and c or {c}
    method             = method or workwindow()
    deviation_type     = deviation_type or "r"
--log(2, os.clock() - t)     
    local compare_func
    if deviation_type == "r" then
        compare_func = internal.color_deviation_r
    elseif deviation_type == "a" then
        compare_func = internal.color_deviation_a
    elseif deviation_type == "s" then
        compare_func = internal.color_deviation_s
    end
--log(3, os.clock() - t)    

    local offset_x1, offset_y1, offset_x2, offset_y2 = 0, 0, 0, 0
    local a, w, h, l
    if type(method) == "table" then
        a, w, h, l = method[1], method[2], method[3], method[4]
    elseif type(method) == "number" then
        a, w, h, l = ext.getimage (x1, y1, x2, y2, method, abs_flag) -- ������ getimage (����� 1 � 2) ���������� x2, y2
        --log(a, w, h, l)
        if method == 1 or method == 2 then
            offset_x2 = w - math.min(x2+1, w)  -- getimage ���������� x2, y2
            offset_y2 = h - math.min(y2+1, h)  -- getimage ���������� x2, y2
        end
      --  saveimage(a,"img\\check.bmp")
    elseif type(method) == "string" then
        a, w, h, l = getimage(method)
        offset_x1 =     math.min(x1,   w)
        offset_y1 =     math.min(y1,   h)
        offset_x2 = w - math.min(x2+1, w)
        offset_y2 = h - math.min(y2+1, h) 
    end
--log(4, os.clock() - t)    
    if not a then
        log("capture failed")
        stop_script()
    end
    --log(a, w, h, l)
    
    local cc = internal.parse_split_color_to_min_max_bgr(c)

    local t = os.clock()
    
    --log(a + offset_y1*l, a+(h-offset_y2)*l-1, l)
    
    local r = {}
    if deviation then
        local d = ffi.new("uint8_t[6]")
        d[0], d[1], d[2], d[3], d[4], d[5] = internal.deviation_parse(deviation, d)
        for i = a + offset_y1*l, a+(h-offset_y2)*l-1, l do
            local y = i
            for i = i+offset_x1*3, i+l-offset_x2*3-1, 3 do
                for j = 1, #c do    
                
                    --log(cc[j][0], cc[j][1], cc[j][2], cc[j][3], cc[j][4], cc[j][5], rmem("unsigned char*",i)[0],rmem("unsigned char*",i+1)[0],rmem("unsigned char*",i+2)[0], d[0], d[1], d[2], d[3], d[4], d[5])

                    --if  cc[j][0] - d[0] <= rmem("unsigned char*",i)[0] and cc[j][1] - d[1] <= rmem("unsigned char*",i)[1] and cc[j][2] - d[2] <= rmem("unsigned char*",i)[2] and
                     --   cc[j][3] + d[3] >= rmem("unsigned char*",i)[0] and cc[j][4] + d[4] >= rmem("unsigned char*",i)[1] and cc[j][5] + d[5] >= rmem("unsigned char*",i)[2] then
                    
                    
                    if compare_func(cc[j][0], cc[j][1], cc[j][2], cc[j][3], cc[j][4], cc[j][5], rmem("unsigned char*",i)[0],rmem("unsigned char*",i)[1],rmem("unsigned char*",i)[2], d[0], d[1], d[2], d[3], d[4], d[5]) then                    
                        r[#r+1] = {}
                        r[#r][1] = (i-y)/3
                        r[#r][2] = math.floor((y-a)/l)
                        r[#r][3] = rmem("unsigned char*",i)[0]*256*256 + rmem("unsigned char*",i)[1]*256 + rmem("unsigned char*",i)[2]
                        r[#r][4] = cc[j][0]*256*256 + cc[j][1]*256 + cc[j][2]
                        r[#r][5] = cc[j][3]*256*256 + cc[j][4]*256 + cc[j][5]
                        --log(r[#r][1],r[#r][2])
                        if count == #r then
                            ext.deleteimage(a)
                            return r
                        end
                    end
                end
            end
        end
    else -- deviation �� �����, ���������� ������� ���������.
        for i = a + offset_y1*l, a+(h-offset_y2)*l-1, l do
            local y = i
            for i = i+offset_x1*3, i+l-offset_x2*3-1, 3 do
                for j = 1, #c do              
                    if cc[j][0] <= rmem("unsigned char*",i)[0] and cc[j][1] <= rmem("unsigned char*",i)[1] and cc[j][2] <= rmem("unsigned char*",i)[2] and
                       cc[j][3] >= rmem("unsigned char*",i)[0] and cc[j][4] >= rmem("unsigned char*",i)[1] and cc[j][5] >= rmem("unsigned char*",i)[2] then
                    
                        r[#r+1] = {}
                        r[#r][1] = (i-y)/3
                        r[#r][2] = math.floor((y-a)/l)
                        r[#r][3] = rmem("unsigned char*",i)[0]*256*256 + rmem("unsigned char*",i)[1]*256 + rmem("unsigned char*",i)[2]
                        r[#r][4] = cc[j][0]*256*256 + cc[j][1]*256 + cc[j][2]
                        r[#r][5] = cc[j][3]*256*256 + cc[j][4]*256 + cc[j][5]
                        --log(r[#r][1],r[#r][2])
                        if count == #r then
                            ext.deleteimage(a)
                            return r
                        end
                    end
                end
            end
        end
    end
    
    if not abs_flag then
        for i = 1, #r do
            r[i][1] = r[i][1] + x1
            r[i][2] = r[i][2] + y1
        end
    end
    
    ext.deleteimage(a)
    speed = speed + os.clock() - t
    catch = #r
    
    return #r > 0 and r or nil
end

ffi.cdef[[
typedef void           VOID, *PVOID, *LPVOID;
typedef VOID*          HANDLE, *PHANDLE;
typedef void           VOID, *PVOID, *LPVOID;
typedef const void*    LPCVOID;
typedef char*          LPSTR;
typedef const char*    LPCSTR;
typedef wchar_t        WCHAR;
typedef const WCHAR*   LPCWSTR;
typedef unsigned long  DWORD, *PDWORD, *LPDWORD;
typedef int            BOOL;

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
//typedef char ai[3];
]]


-- ext.saveimage
-- ���������� �����������.
-- ���������� ���������:
-- <path>, <address>[, x1, y1, x2, y2] -- ���� ��������� ����� getimage
-- <path>, <{address, width, height}>[, x1, y1, x2, y2]
-- <path>, <{a=val, w=val, h=val}>[, x1, y1, x2, y2]
-- <path>, <{address=val, width=val, height=val}>[, x1, y1, x2, y2]
-- path - ����� �� �������� ���������� ��������� �����������
-- address - ����� � ������ �� ������� ��������� �����������
-- width - ������ �����������
-- height - ������ �����������
-- x1, y1 - ��������� ���������� ������������ �����������
-- x2, y2 - �������� ���������� ������������ �����������
-- ���� ������� x1, y1, x2, y2, �� ��������� ������ ���������
-- ����������� �� �����������.

ext.saveimage = function()end
do
    local FILE_READ_DATA = 0x1
    local FILE_WRITE_DATA = 0x2

    local FILE_SHARE_READ = 0x00000001
    local FILE_SHARE_WRITE = 0x00000002

    local CREATE_ALWAYS = 0x2

    local FILE_ATTRIBUTE_NORMAL = 0x80

    local bmp_headers = {}
        
    bmp_headers[1] = ffi.new("const unsigned char[2]",{ 0x42,
                                                        0x4D}    )
                                                    --  file_size 4 bytes
    bmp_headers[2] = ffi.new("const unsigned char[12]",{0x00,
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
                                                        0x00    })
                                                    --  image_width 4 bytes signed integer
                                                    --  image_height 4 bytes signed integer
    bmp_headers[3] = ffi.new("const unsigned char[8]",{ 0x01,
                                                        0x00,
                                                        0x18, -- the number of bits per pixel, which is the color depth of the image. Typical values are 1, 4, 8, 16, 24 and 32
                                                        0x00,
                                                        0x00,
                                                        0x00,
                                                        0x00,
                                                        0x00    })
                                                    --  bitmap_size (w*h*3)
    bmp_headers[4] = ffi.new("const unsigned char[16]",{0x00,
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
                                                        0x00    })

    ext.saveimage = function(path, a, x1, y1, x2, y2)
        local f = C.CreateFileA(
            path,
            FILE_READ_DATA + FILE_WRITE_DATA,
            FILE_SHARE_READ + FILE_SHARE_WRITE,
            nil,
            CREATE_ALWAYS,
            FILE_ATTRIBUTE_NORMAL,
            nil)

        local dwbuf = ffi.new'DWORD[1]'
        
        if type(a) == "number" then
            w = images[a].width
            h = images[a].height
            l = images[a].lenght
        else
            w = a[2] or a.width    or a.w
            h = a[3] or a.height   or a.w
            l = math.ceil(w*3/4)*4
            a = a[1] or a.address  or a.a
        end
        
        if x1 then
            a, w, h, l = ext.image_copy({a, w}, x1, y1, x2, y2)
        end

        local success = C.WriteFile(f,                            bmp_headers[1],                 2, dwbuf, nil)
        local success = C.WriteFile(f, ffi.new("uint32_t[1]",     h*w*3+54     ),                 4, dwbuf, nil)
        local success = C.WriteFile(f,                            bmp_headers[2],                12, dwbuf, nil)
        local success = C.WriteFile(f, ffi.new("uint32_t[1]",     w            ),                 4, dwbuf, nil)
        local success = C.WriteFile(f, ffi.new("uint32_t[1]",    -h            ),                 4, dwbuf, nil)
        local success = C.WriteFile(f,                            bmp_headers[3],                 8, dwbuf, nil)
        local success = C.WriteFile(f, ffi.new("uint32_t[1]",     w*h*3        ),                 4, dwbuf, nil)
        local success = C.WriteFile(f,                            bmp_headers[4],                16, dwbuf, nil)
        local success = C.WriteFile(f, ffi.cast("const void*",    a            ),               h*l, dwbuf, nil)

        C.CloseHandle(f)
        if x1 then
            ext.deleteimage(a)
        end
        collectgarbage()
    end
end

ext.color = function(x, y, c, deviation, deviation_type, method, abs_flag)
    c = c or "0x000000-0xFFFFFF"
    local cc = ext.findcolor(x, y, x, y, c, method, 1, deviation, deviation_type, abs_flag)
    if cc then
        return cc[1][3]
    else
        return nil
    end
end

internal.image_convert = {}

internal.image_convert.a = function(a, a1, a2, d)
--[[    fi_a0 = rmem("unsigned char*",fi_a)
    fi_a1 = rmem("unsigned char*",fi_a1)
    fi_a2 = rmem("unsigned char*",fi_a2)
    for i = 0, h*l-1, l do   
        for j = i, i+w*3-1, 3 do            
            a1[j]   = math.max(rmem("unsigned char*",a)[0]-d[0], 0)
            a1[j+1] = math.max(rmem("unsigned char*",a)[1]-d[1], 0)
            a1[j+2] = math.max(rmem("unsigned char*",a)[2]-d[2], 0)
            a2[j]   = math.min(rmem("unsigned char*",a)[0]+d[3], 255)
            a2[j+1] = math.min(rmem("unsigned char*",a)[1]+d[4], 255)
            a2[j+2] = math.min(rmem("unsigned char*",a)[2]+d[5], 255)
        end
    end
    ]]
        
    local w = images[a].width
    local h = images[a].height
    local l = images[a].lenght
    a  = rmem("unsigned char*",a)
    a1 = rmem("unsigned char*",a1)
    a2 = rmem("unsigned char*",a2)

    for i = 0, h*l-1, l do   
        for j = i, i+w*3-1, 3 do   
            a1[j]   = math.max(a[j]  -d[0], 0)
            a1[j+1] = math.max(a[j+1]-d[1], 0)
            a1[j+2] = math.max(a[j+2]-d[2], 0)
            a2[j]   = math.min(a[j]  +d[3], 255)
            a2[j+1] = math.min(a[j+1]+d[4], 255)
            a2[j+2] = math.min(a[j+2]+d[5], 255)
        end
    end

--[[
--log(a,a1,a2,w,h,l)
    a0 = tonumber(ffi.cast("int", a0))
    a1 = tonumber(ffi.cast("int", a1))
    a2 = tonumber(ffi.cast("int", a2))



--log(dec2hex(a0))
--log(tostring(a))
    a0i = rmem("ai *",a0)
   -- log(tostring(a0))

--log(tostring(a))
    a1i = rmem("ai *",a1)
    a2i = rmem("ai *",a2)
--    log("__")
--    log(tostring(a0))
--    log(tostring(a1))
--    log(tostring(a0i))
--    log(tostring(a1i))
    
    for i = 0, h-1 do
--    log(tostring(a1i))
        for j = 0, w-1 do
        --log(tostring(a))
            a1i[j][0] = math.max(a0i[j][0]-d[0], 0)
            a1i[j][1] = math.max(a0i[j][1]-d[1], 0)
            a1i[j][2] = math.max(a0i[j][2]-d[2], 0)
            a2i[j][0] = math.min(a0i[j][0]+d[3], 255)
            a2i[j][1] = math.min(a0i[j][1]+d[4], 255)
            a2i[j][2] = math.min(a0i[j][2]+d[5], 255)
        end
        --log(tostring(a0i),l)
        --log(tostring(tonumber(a0)+l))
        --log(tostring(tonumber(a1)+l))
        a0i = rmem("ai *",a0+l*i)
        --log(tostring(a0i))
        --stop_script()

    --log(tostring(a))
        a1i = rmem("ai *",a1+l*i)
        a2i = rmem("ai *",a2+l*i)
    end
]]
--[[    a  = rmem("unsigned char*",a)
    a1 = rmem("unsigned char*",a1)
    a2 = rmem("unsigned char*",a2)
    for i = 0, h*l-1, l do
        for j = i, i+w*3-1, 3 do
            local n = 0
            for k = j, j + 2 do
                a1[k]   = math.max(a[k]  -d[n]  ,   0)
                a2[k]   = math.min(a[k]  +d[n+3], 255)
                n = n + 1
            end
        end
    end
]]

end

internal.image_convert.r = function(fi_a, fi_a1, fi_a2, d)
    fi_a0 = rmem("unsigned char*",fi_a)
    fi_a1 = rmem("unsigned char*",fi_a1)
    fi_a2 = rmem("unsigned char*",fi_a2)

    for i = 0, images[fi_a].height*images[fi_a].lenght-1, images[fi_a].lenght do   
        for j = i, i+images[fi_a].width*3-1, 3 do
            local b1d = math.ceil(fi_a0[j]   * d[0] * 0.01)
            local g1d = math.ceil(fi_a0[j+1] * d[1] * 0.01)
            local r1d = math.ceil(fi_a0[j+2] * d[2] * 0.01)

            local b2d = math.ceil(fi_a0[j]   * d[3] * 0.01)
            local g2d = math.ceil(fi_a0[j+1] * d[4] * 0.01)
            local r2d = math.ceil(fi_a0[j+2] * d[5] * 0.01)
            
            fi_a1[j]   = math.max(fi_a0[j]  -b1d,   0)
            fi_a1[j+1] = math.max(fi_a0[j+1]-g1d,   0)
            fi_a1[j+2] = math.max(fi_a0[j+2]-r1d,   0)
            fi_a2[j]   = math.min(fi_a0[j]  +b2d, 255)
            fi_a2[j+1] = math.min(fi_a0[j+1]+g2d, 255)
            fi_a2[j+2] = math.min(fi_a0[j+2]+r2d, 255)
        end
    end
end

internal.image_convert.s = function(a,a1,a2,w,h,l,d)
    a  = rmem("unsigned char*",a)
    a1 = rmem("unsigned char*",a1)
    a2 = rmem("unsigned char*",a2)

    local c1b1, c1g1, c1r1, c1b2, c1g2, c1r2, c2b, c2g, c2r = a1[j]+1, a1[j+1]+1, a1[j+2]+1, a2[j]+1, a2[j+1]+1, a2[j+2]+1, a[j]+1, a[j+1]+1, a[j+2]+1
    local c1br1 = c1b1/c1r1
    local c1rg1 = c1r1/c1g1
    local c1gb1 = c1g1/c1b1
    
    local c1br2 = c1b2/c1r2
    local c1rg2 = c1r2/c1g2
    local c1gb2 = c1g2/c1b2    
    
    local br_d1 = c1br1 * br1 * 0.01
    local rg_d1 = c1rg1 * rg1 * 0.01
    local gb_d1 = c1gb1 * gb1 * 0.01
    
    local br_d2 = c1br2 * br2 * 0.01
    local rg_d2 = c1rg2 * rg2 * 0.01
    local gb_d2 = c1gb2 * gb2 * 0.01
    
    local c2br = c2b/c2r
    local c2rg = c2r/c2g
    local c2gb = c2g/c2b



    for i = 0, h*l-1, l do   
        for j = i, i+w*3-1, 3 do  
            local b1d = math.ceil(a[j]   * d[0] * 0.01) 
            local g1d = math.ceil(a[j+1] * d[1] * 0.01)  
            local r1d = math.ceil(a[j+2] * d[2] * 0.01)  

            local b2d = math.ceil(a[j]   * d[3] * 0.01)
            local g2d = math.ceil(a[j+1] * d[4] * 0.01)
            local r2d = math.ceil(a[j+2] * d[5] * 0.01)
            
            a1[j]   = math.max(a[j]  -b1d,   0)
            a1[j+1] = math.max(a[j+1]-g1d,   0)
            a1[j+2] = math.max(a[j+2]-r1d,   0)
            a2[j]   = math.min(a[j]  +b2d, 255)
            a2[j+1] = math.min(a[j+1]+g2d, 255)
            a2[j+2] = math.min(a[j+2]+r2d, 255)
        end
    end
end

internal.image_convert.general   = function(fi_a,d,deviation_type)
    -- ������������� �� ��� ����������� ��������� ����������� � ����� deviaton
    local deviation_string = deviation_type.."|"..d[0].."|"..d[1].."|"..d[2].."|"..d[3].."|"..d[4].."|"..d[5]
    --log(tostring(images[fi_a]))
    --log(deviation_string)
    --log(tostring(images[fi_a].deviation[deviation_string]))
    --ext.lg(images)
    if images[fi_a].deviation and images[fi_a].deviation[deviation_string] then
    --log("!!!")
        return images[fi_a].deviation[deviation_string]["a1"], images[fi_a].deviation[deviation_string]["a2"]
    else
        local t = os.clock()
        images[fi_a][deviation_string] = {}
        -- ����������� ������� �� ������.
        local fi_w, fi_h, fi_l = images[fi_a].width, images[fi_a].height, images[fi_a].lenght
        -- �������� ������ ��� ����� �����������.
        if not images[fi_a].deviation then
            images[fi_a].deviation = {}
        end
        images[fi_a].deviation[deviation_string] = {}
        images[fi_a].deviation[deviation_string][1] = ffi.gc(C.malloc(fi_l*fi_h), C.free)
        images[fi_a].deviation[deviation_string][2] = ffi.gc(C.malloc(fi_l*fi_h), C.free)
        -- ��������� � �����. images[fi_a].deviation[deviation_string]["a1"] - ��� ��� ����� �������� �������.
        images[fi_a].deviation[deviation_string]["a1"] = tonumber(rmem("int", images[fi_a].deviation[deviation_string][1]))
        images[fi_a].deviation[deviation_string]["a2"] = tonumber(rmem("int", images[fi_a].deviation[deviation_string][2]))

        images[images[fi_a].deviation[deviation_string]["a1"]]                       = {}
        images[images[fi_a].deviation[deviation_string]["a1"]].width                 = fi_w
        images[images[fi_a].deviation[deviation_string]["a1"]].height                = fi_h
        images[images[fi_a].deviation[deviation_string]["a1"]].lenght                = fi_l
        images[images[fi_a].deviation[deviation_string]["a1"]].bitmap_address        = images[fi_a].deviation[deviation_string][1]
        images[images[fi_a].deviation[deviation_string]["a2"]]                       = {}
        images[images[fi_a].deviation[deviation_string]["a2"]].width                 = fi_w
        images[images[fi_a].deviation[deviation_string]["a2"]].height                = fi_h
        images[images[fi_a].deviation[deviation_string]["a2"]].lenght                = fi_l
        images[images[fi_a].deviation[deviation_string]["a2"]].bitmap_address        = images[fi_a].deviation[deviation_string][2]
        
        internal.image_convert[deviation_type](
                                                fi_a,
                                                images[fi_a].deviation[deviation_string]["a1"],
                                                images[fi_a].deviation[deviation_string]["a2"], 
                                                d
                                               )
                                               --images[fi_a].deviation[deviation_string][1]=nil
                                               --images[fi_a].deviation[deviation_string][2]=nil
                                               --collectgarbage()

        return images[fi_a].deviation[deviation_string]["a1"], images[fi_a].deviation[deviation_string]["a2"]
    end
end

internal.fi_compare = function(fi_a, fi_a1, fi_a2, acc, count)
--log(fi_a, fi_a1, fi_a2, acc, count)

    local fi_w = images[fi_a1].width  or fi_w
    local fi_h = images[fi_a1].height or fi_h
    local fi_l = images[fi_a1].lenght or fi_l
    
    local pix_total = fi_w*fi_h
    local acc_max   = pix_total*acc/100
    local acc_min   = math.floor(pix_total-acc_max)
    
--    log(pix_total,acc_max,acc_min)
    
    fi_a0 = rmem("unsigned char*",fi_a)
    fi_a1 = rmem("unsigned char*",fi_a1)
    fi_a2 = rmem("unsigned char*",fi_a2)
    
--[===[
    local r = {}

    for i = 0, (images[fi_a].height-fi_h)*images[fi_a].lenght, images[fi_a].lenght do
        local y = i
--local s_x = 0
        for j = i, i+(images[fi_a].width-fi_w)*3-1, 3 do
--s_x = s_x +1
--source_checks = source_checks + 1        
--        log()
            local checked = 1
            local br = false
            local catch = 0
--local ch_y = 0
            for k = 0, fi_h*fi_l-1, fi_l do
                jj = j + images[fi_a].lenght*math.floor((k/fi_l))
--ch_y = ch_y + 1
--fi_checks_x = fi_checks_x + 1
                for l = k, k+fi_w*3-1, 3 do
                    total_checks = total_checks + 1
--[====[
                    --[[
--                    log()

if 1 == 1 then
                    log(
                        tonumber(rmem("unsigned char*", fi_a+jj  )[0]).." "..">=".." "..tonumber(rmem("unsigned char*", fi_a1+l  )[0]).." "..tonumber(rmem("unsigned char*", fi_a+jj  )[0]).." ".."<=".." "..tonumber(rmem("unsigned char*", fi_a2+l  )[0]).." \n"..
                        tonumber(rmem("unsigned char*", fi_a+jj+1)[0]).." "..">=".." "..tonumber(rmem("unsigned char*", fi_a1+l+1)[0]).." "..tonumber(rmem("unsigned char*", fi_a+jj+1)[0]).." ".."<=".." "..tonumber(rmem("unsigned char*", fi_a2+l+1)[0]).." \n"..
                        tonumber(rmem("unsigned char*", fi_a+jj+2)[0]).." "..">=".." "..tonumber(rmem("unsigned char*", fi_a1+l+2)[0]).." "..tonumber(rmem("unsigned char*", fi_a+jj+2)[0]).." ".."<=".." "..tonumber(rmem("unsigned char*", fi_a2+l+2)[0])
                    )
end        
if 1 == 1 then
                    log(
                        tostring(rmem("unsigned char*", fi_a+jj  )[0] >= rmem("unsigned char*", fi_a1+l  )[0]) , tostring(rmem("unsigned char*", fi_a+jj  ) <= rmem("unsigned char*", fi_a2+l  )) ," \n",
                        tostring(rmem("unsigned char*", fi_a+jj+1)[0] >= rmem("unsigned char*", fi_a1+l+1)[0]) , tostring(rmem("unsigned char*", fi_a+jj+1) <= rmem("unsigned char*", fi_a2+l+1)) ," \n",
                        tostring(rmem("unsigned char*", fi_a+jj+2)[0] >= rmem("unsigned char*", fi_a1+l+2)[0]) , tostring(rmem("unsigned char*", fi_a+jj+2) <= rmem("unsigned char*", fi_a2+l+2))
                    )
end
]]    
--                    log("k:",k)
--                    log("fi pos:", l)
]====]
                    if rmem("unsigned char*", fi_a+jj  )[0] >= rmem("unsigned char*", fi_a1+l  )[0] and rmem("unsigned char*", fi_a+jj  )[0] <= rmem("unsigned char*", fi_a2+l  )[0] and
                       rmem("unsigned char*", fi_a+jj+1)[0] >= rmem("unsigned char*", fi_a1+l+1)[0] and rmem("unsigned char*", fi_a+jj+1)[0] <= rmem("unsigned char*", fi_a2+l+1)[0] and
                       rmem("unsigned char*", fi_a+jj+2)[0] >= rmem("unsigned char*", fi_a1+l+2)[0] and rmem("unsigned char*", fi_a+jj+2)[0] <= rmem("unsigned char*", fi_a2+l+2)[0] then
                        --log("!!!")
--[[                        
                        catch = catch + 1
                        if checked >= acc_max then
--                            log("found +1")
                            r[#r+1] = {}
                            r[#r][2] = math.floor(y/images[fi_a].lenght)
                            r[#r][1] = (j-r[#r][2]*images[fi_a].lenght)/3
                            r[#r][3] = r[#r][1]+fi_w-1
                            r[#r][4] = r[#r][2]+fi_h-1
                            r[#r][5] = math.floor(checked/pix_total*100)
                            if #r == count then
                                return r
                            end
                            br = true
                            break
                        end
]]                        
                    else
--                        log("___")
                    end
                    --log("checked:",checked)
                    --log("catch:",catch)
--                    log(checked - catch, ">",acc_min)
                                                    
                    --if 1 then br = true break end
                    if checked - catch > acc_min then
--                        log("fail")
--log("checked:", checked)
                        br = true
                        break
                    end
                    jj = jj + 3                
                    checked = checked + 1
                end
--log("checked:", checked)
                if br then break end
            end
--log(ch_y)
        end
--log("s_x:", s_x)
    end
]===]
    
    local r = {}
    for i = 0, (images[fi_a].height-fi_h)*images[fi_a].lenght, images[fi_a].lenght do
        local y = i
        for j = i, i+images[fi_a].width*3-fi_w-1, 3 do
        
--        log()
            local checked = 1
            local br = false
            local catch = 0
            for k = 0, fi_h*fi_l-1, fi_l do
                jj = j + images[fi_a].lenght*math.floor((k/fi_l))

                for l = k, k+fi_w*3-1, 3 do
--                    log()
                    --log()
--                    log(fi_a0[l  ],fi_a0[jj+1],fi_a0[jj+2])
--                    log(fi_a1[l  ],fi_a1[ l+1],fi_a1[ l+2])
--                    log(fi_a2[l  ],fi_a2[ l+1],fi_a2[ l+2])
--                    log(
--                        fi_a0[jj  ].." "..">=".." "..fi_a1[l  ].." "..fi_a0[jj  ].." ".."<=".." "..fi_a2[l  ].." \n"..
--                        fi_a0[jj+1].." "..">=".." "..fi_a1[l+1].." "..fi_a0[jj+1].." ".."<=".." "..fi_a2[l+1].." \n"..
--                        fi_a0[jj+2].." "..">=".." "..fi_a1[l+2].." "..fi_a0[jj+2].." ".."<=".." "..fi_a2[l+2]
--                    )
--                    log("k:",k)
--                    log("fi pos:", l)
                    if fi_a0[jj  ] >= fi_a1[l  ] and fi_a0[jj  ] <= fi_a2[l  ] and
                       fi_a0[jj+1] >= fi_a1[l+1] and fi_a0[jj+1] <= fi_a2[l+1] and
                       fi_a0[jj+2] >= fi_a1[l+2] and fi_a0[jj+2] <= fi_a2[l+2] then
--                        log("!!!")
                        catch = catch + 1
                        if checked >= acc_max then
                            --log("found +1")
                            r[#r+1] = {}
                            r[#r][2] = math.floor(y/images[fi_a].lenght)
                            r[#r][1] = (j-r[#r][2]*images[fi_a].lenght)/3
                            r[#r][3] = r[#r][1]+fi_w-1
                            r[#r][4] = r[#r][2]+fi_h-1
                            r[#r][5] = math.floor(checked/pix_total*100)
                            br = true
                            break
                        end
                    else
--                        log("___")
                    end
--                    log("checked:",checked)
--                    log("catch:",catch)
--                    log(checked - catch, ">",acc_min)
                    if checked - catch > acc_min then
--                        log("fail")
                        br = true
                        break
                    end
                    jj = jj + 3
                    checked = checked + 1
                end
                if br then break end
            end
        end
    end
    return r
end

ext.findimage = function(x1, y1, x2, y2, img, method, accuracy, count, deviation, deviation_type, abs_flag)
--log(x1, y1, x2, y2, img, method, accuracy, count, deviation, deviation_type, abs_flag)
    if  type(x1) == "table" then
        abs_flag       = count
        deviation_type = method
        deviation      = img
        count          = y2
        method         = x2
        img            = y1    
    end
--log(1, os.clock() - t)    
    img                = type(img) == "table" and img or {img}
    method             = method or workwindow()
    deviation_type     = deviation_type or "r"
--log(2, os.clock() - t)     
    local image_convert_func
    if deviation_type == "r" then
        image_convert_func = internal.image_convert_r
    elseif deviation_type == "a" then
        image_convert_func = internal.image_convert_a
    elseif deviation_type == "s" then
        image_convert_func = internal.image_convert_s
    end
--log(3, os.clock() - t)    

    local offset_x1, offset_y1, offset_x2, offset_y2 = 0, 0, 0, 0
    local a, w, h, l
    if type(method) == "table" then
        a, w, h, l = method[1], method[2], method[3], method[4]
        if type(a) ~= 'number' then
            a = tonumber(ffi.cast('int',method[1]))
        end
        if not images[a] then
            images[a] = {}
            images[a].bitmap_address = ffi.cast("void *",a)
            images[a].width = w
            images[a].height = h
            images[a].lenght = math.floor(w*3/4+0.75)*4
            images[x1] = a
        end
    elseif type(method) == "number" then
        a, w, h, l = ext.getimage (x1, y1, x2, y2, method, abs_flag) -- ������ getimage (����� 1 � 2) ���������� x2, y2
        --log(a, w, h, l)
        if method == 1 or method == 2 then
            offset_x2 = w - math.min(x2+1, w)  -- getimage ���������� x2, y2
            offset_y2 = h - math.min(y2+1, h)  -- getimage ���������� x2, y2
        end
        --saveimage(a,"image\\check.bmp")
    elseif type(method) == "string" then
        a, w, h, l = ext.getimage(method)
        offset_x1 =     math.min(x1,   w)
        offset_y1 =     math.min(y1,   h)
        offset_x2 = w - math.min(x2+1, w)
        offset_y2 = h - math.min(y2+1, h) 
    end
--log(4, os.clock() - t)    
    if not a then
        log("capture failed")
        stop_script()
    end
    --log(a, w, h, l)
    local fi_a, fi_w, fi_h, fi_l = ext.getimage(img[1])
--log(5, os.clock() - t) 
    --local t = os.clock()
    
    local r = {}
    if deviation then
        -- ������ deviation
        local d = ffi.new("uint8_t[6]")
        d[0], d[1], d[2], d[3], d[4], d[5] = internal.deviation_parse(deviation, d)
--log(6, os.clock() - t) 
        local fi_a1, fi_a2 = internal.image_convert.general(fi_a,d,deviation_type)
        --speed = speed + os.clock() - t      
--log(7, os.clock() - t)         
        --ext.saveimage ([[image\tmp_1.bmp]], fi_a1, fi_w, fi_h, fi_l)
        --ext.saveimage ([[image\tmp_2.bmp]], fi_a2, fi_w, fi_h, fi_l)
        
        
        r = internal.fi_compare(a,fi_a1,fi_a2,accuracy,count)
--log(8, os.clock() - t) 
        if type(method) ~= "table" then
            ext.deleteimage(a)
        end
--log(9, os.clock() - t)       

        
        
        return r
        
        --stop_script()
  --[[      for i = a + offset_y1*l, a+(h-offset_y2)*l-1, l do
            local y = i
            for i = i+offset_x1*3, i+l-offset_x2*3-1, 3 do
                for j = 1, #c do    
                
                    --log(cc[j][0], cc[j][1], cc[j][2], cc[j][3], cc[j][4], cc[j][5], rmem("unsigned char*",i)[0],rmem("unsigned char*",i+1)[0],rmem("unsigned char*",i+2)[0], d[0], d[1], d[2], d[3], d[4], d[5])

                    --if  cc[j][0] - d[0] <= rmem("unsigned char*",i)[0] and cc[j][1] - d[1] <= rmem("unsigned char*",i)[1] and cc[j][2] - d[2] <= rmem("unsigned char*",i)[2] and
                     --   cc[j][3] + d[3] >= rmem("unsigned char*",i)[0] and cc[j][4] + d[4] >= rmem("unsigned char*",i)[1] and cc[j][5] + d[5] >= rmem("unsigned char*",i)[2] then
                    
                    
                    if compare_func(cc[j][0], cc[j][1], cc[j][2], cc[j][3], cc[j][4], cc[j][5], rmem("unsigned char*",i)[0],rmem("unsigned char*",i)[1],rmem("unsigned char*",i)[2], d[0], d[1], d[2], d[3], d[4], d[5]) then                    
                        r[#r+1] = {}
                        r[#r][1] = (i-y)/3
                        r[#r][2] = math.floor((y-a)/l)
                        r[#r][3] = rmem("unsigned char*",i)[0]*256*256 + rmem("unsigned char*",i)[1]*256 + rmem("unsigned char*",i)[2]
                        r[#r][4] = cc[j][0]*256*256 + cc[j][1]*256 + cc[j][2]
                        r[#r][5] = cc[j][3]*256*256 + cc[j][4]*256 + cc[j][5]
                        --log(r[#r][1],r[#r][2])
                        if count == #r then
                            ext.deleteimage(a)
                            return r
                        end
                    end
                end
            end
        end
       ]]
    else -- deviation �� �����, ���������� ������� ���������.
        for i = a + offset_y1*l, a+(h-offset_y2)*l-1, l do
            local y = i
            for i = i+offset_x1*3, i+l-offset_x2*3-1, 3 do
                for j = 1, #c do              
                    if cc[j][0] <= rmem("unsigned char*",i)[0] and cc[j][1] <= rmem("unsigned char*",i)[1] and cc[j][2] <= rmem("unsigned char*",i)[2] and
                       cc[j][3] >= rmem("unsigned char*",i)[0] and cc[j][4] >= rmem("unsigned char*",i)[1] and cc[j][5] >= rmem("unsigned char*",i)[2] then
                    
                        r[#r+1] = {}
                        r[#r][1] = (i-y)/3
                        r[#r][2] = math.floor((y-a)/l)
                        r[#r][3] = rmem("unsigned char*",i)[0]*256*256 + rmem("unsigned char*",i)[1]*256 + rmem("unsigned char*",i)[2]
                        r[#r][4] = cc[j][0]*256*256 + cc[j][1]*256 + cc[j][2]
                        r[#r][5] = cc[j][3]*256*256 + cc[j][4]*256 + cc[j][5]
                        --log(r[#r][1],r[#r][2])
                        if count == #r then
                            ext.deleteimage(a)
                            return r
                        end
                    end
                end
            end
        end
    end
end

-- ext.image_copy
-- �������� ����� �����������.
-- ���������� ���������:
-- <address>,<x1>,<y1>,<x2>,<y2> -- ���� ����������� ��������� ����� getimage
-- <{address, width}>,<x1>,<y1>,<x2>,<y2>
-- <{address=val, width=val}>,<x1>,<y1>,<x2>,<y2>
-- <{a=val, w=val}>,<x1>,<y1>,<x2>,<y2>
-- ����������:
-- address, width, height, lenght
ext.image_copy = function(a, x1, y1, x2, y2)
--log(fi_a, x1, y1, x2, y2)
    local w,l
    if type(a) == "number" then
        w = images[a].width
        l = images[a].lenght
    else
        local w = a[2] or a.w or a.width
        l = math.ceil(w*3/4)*4
        a = a[1] or a.a or a.address
    end
    
    -- ������������� ���������
    a = rmem("unsigned char*",a)
    local cut_w = x2-x1 + 1
    local cut_h = y2-y1 + 1
    local cut_l = math.ceil(cut_w*3/4)*4
    local cut_a = ffi.gc(C.malloc(cut_h*cut_l), C.free)
    cut_a = rmem("unsigned char*", cut_a)
    
    -- ��������� ����������� � �����
    ext.images.add(cut_a, cut_w, cut_h, cut_l)
    
    -- ��������
    local r = {}
    local y = 0
    for i = y1*l, y2*l, l do
        local cut_x = y
        for i = i+(x1)*3, i+(x2+1)*3 do  
            cut_a[cut_x] = a[i]
            cut_x = cut_x + 1
        end

        y = y + cut_l
    end   
    
    return tonumber(ffi.cast("int", cut_a)), cut_w, cut_h, cut_l
end


--   �������� ���� ����������� ������
--   ������������ ������� ��������� ��������
colortorgb = ext.color_to_rgb
getimage = ext.getimage
deleteimage = ext.deleteimage
findcolor = ext.findcolor
color = ext.color
saveimage = ext.saveimage
findimage = ext.findimage
return ext

--[[
TODO
1)+ ���������� ����� 0 ��� ������ �� ������������� �����������
2)+ ���������� ������������ ������ � <x> <y> <���������_���� <�������_����1> <�������_����2>
3)0 �������� ��� ������.
4)+ �������� � images �������� ������, ������, �����
5)+ ������������ images ��� ��������� � ������� ��������� ������ �� ������ �����������. �������� ������� ��������� path, a.
6)+ ���������� c�lor � local c = color(x,y[,color][,deviation][,method][,abs])
7)+ ����� loadimage
8)- ���������
9)+ �������� � ��� ��� ��� ���������� x y ������������ ��������� ������ � ������ �� ���������� �������� ����������.
10)- ���������� loadimage �������� ��� � getimage. loadimage = ������� ������ getimage. ��������� �������� �������������.
11)- �������� �������� deviation ����������� �� ������.



]]



