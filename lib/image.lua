local ffi = require("ffi")
local bit = require("bit")

-- Загрузка OpenCV библиотеки (предполагается, что она доступна)
ffi.cdef [[
    typedef struct {
        int width, height;
        unsigned char* data;
    } Image;

    Image* loadImage(const char* filename);
    void freeImage(Image* img);
    int findImage(Image* screenshot, Image* template, float minScale, float maxScale, float scaleStep,
                 float* outX, float* outY, float* outScale, float* outConfidence);
]]

local opencv = ffi.load("opencv_wrapper") -- Ваша обертка для OpenCV

-- Функция для поиска изображения с учетом масштабирования
function findScaledImage(screenshotPath, templatePath, options)
    options = options or {}
    local minScale = options.minScale or 0.5
    local maxScale = options.maxScale or 2.0
    local scaleStep = options.scaleStep or 0.1
    local minConfidence = options.minConfidence or 0.8

    -- Загрузка изображений
    local screenshot = opencv.loadImage(screenshotPath)
    local template = opencv.loadImage(templatePath)

    if screenshot == nil or template == nil then
        if screenshot then
            opencv.freeImage(screenshot)
        end
        if template then
            opencv.freeImage(template)
        end
        return nil, "Failed to load images"
    end

    -- Поиск изображения
    local outX = ffi.new("float[1]")
    local outY = ffi.new("float[1]")
    local outScale = ffi.new("float[1]")
    local outConfidence = ffi.new("float[1]")

    local result = opencv.findImage(screenshot, template, minScale, maxScale, scaleStep,
            outX, outY, outScale, outConfidence)

    -- Освобождение памяти
    opencv.freeImage(screenshot)
    opencv.freeImage(template)

    -- Проверка результата
    if result == 1 and outConfidence[0] >= minConfidence then
        return {
            x = outX[0],
            y = outY[0],
            scale = outScale[0],
            confidence = outConfidence[0]
        }
    end

    return nil, "Image not found or confidence too low"
end

-- Пример использования
local result, err = findScaledImage("screenshot.png", "template.png", {
    minScale = 0.7,
    maxScale = 1.5,
    scaleStep = 0.05,
    minConfidence = 0.75
})

if result then
    print(string.format("Found at: x=%.1f, y=%.1f, scale=%.2f, confidence=%.2f",
            result.x, result.y, result.scale, result.confidence))
else
    print("Error:", err)
end