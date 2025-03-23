local ffi = require("ffi")
local os = require("os")

-- Путь, по которому будет сохранен BMP файл
local outputFilePath = "src/test_part.bmp"

-- Параметры теста
local x, y = 100, 100  -- координаты верхнего левого угла части изображения
local width, height = 200, 150  -- размеры части изображения

-- Тестирование функции сохранения изображения в BMP
function testSaveBitmapPart()
    -- Предполагаем, что hBitmap был получен каким-то образом, например, с помощью GetDC или других API
    local hBitmap = ffi.cast("HBITMAP", 0)  -- Тут должен быть реальный handle HBITMAP изображения

    -- Вызов функции для сохранения части изображения
    saveBitmapPart(hBitmap, x, y, width, height, outputFilePath)

    -- Проверка существования файла с помощью io.open
    local file = io.open(outputFilePath, "rb")
    if not file then
        print("Ошибка: файл не был создан!")
        return false
    end
    file:close()

    -- Получаем информацию о файле, используя os.rename для получения размера
    local fileSize = os.rename(outputFilePath, outputFilePath)
    if not fileSize then
        print("Ошибка: не удалось получить размер файла.")
        return false
    end

    -- Выводим размер файла
    print("Размер файла: " .. fileSize .. " байт.")

    -- Проверяем, что размер файла больше минимального размера BMP (обычно 54 байта для заголовка)
    -- Дополнительно проверим минимальный размер в зависимости от разрешения
    local expectedMinSize = 54 + (width * height * 3)  -- Заголовок + пиксели (24 бита)
    if fileSize < expectedMinSize then
        print("Ошибка: размер файла меньше минимально ожидаемого размера.")
        return false
    end

    -- Если файл существует и размер подходящий, считаем тест успешным
    print("Тест прошел успешно. Файл создан: " .. outputFilePath)
    return true
end

