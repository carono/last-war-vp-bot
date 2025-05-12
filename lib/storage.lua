--lua
require("os")
local write, writeIndent, writers, refCount;

Storage = {}

local persistence = {
    save = function(path, ...)
        local file, e = io.open(path, "w");
        if not file then
            return error(e);
        end
        local n = select("#", ...);
        -- Count references
        local objRefCount = {}; -- Stores reference that will be exported
        for i = 1, n do
            refCount(objRefCount, (select(i, ...)));
        end ;
        -- Export Objects with more than one ref and assign name
        -- First, create empty tables for each
        local objRefNames = {};
        local objRefIdx = 0;
        file:write("-- Persistent Data\n");
        file:write("local multiRefObjects = {\n");
        for obj, count in pairs(objRefCount) do
            if count > 1 then
                objRefIdx = objRefIdx + 1;
                objRefNames[obj] = objRefIdx;
                file:write("{};"); -- table objRefIdx
            end ;
        end ;
        file:write("\n} -- multiRefObjects\n");
        -- Then fill them (this requires all empty multiRefObjects to exist)
        for obj, idx in pairs(objRefNames) do
            for k, v in pairs(obj) do
                file:write("multiRefObjects[" .. idx .. "][");
                write(file, k, 0, objRefNames);
                file:write("] = ");
                write(file, v, 0, objRefNames);
                file:write(";\n");
            end ;
        end ;
        -- Create the remaining objects
        for i = 1, n do
            file:write("local " .. "obj" .. i .. " = ");
            write(file, (select(i, ...)), 0, objRefNames);
            file:write("\n");
        end
        -- Return them
        if n > 0 then
            file:write("return obj1");
            for i = 2, n do
                file:write(" ,obj" .. i);
            end ;
            file:write("\n");
        else
            file:write("return\n");
        end ;
        if type(path) == "string" then
            file:close();
        end ;
    end;

    load = function(path)
        local f, e;
        if type(path) == "string" then
            f, e = loadfile(path);
        else
            f, e = path:read('*a')
        end
        if f then
            return f();
        else
            return nil, e;
        end ;
    end;
}



-- Private methods

-- write thing (dispatcher)
write = function(file, item, level, objRefNames)
    writers[type(item)](file, item, level, objRefNames);
end;

-- write indent
writeIndent = function(file, level)
    for i = 1, level do
        file:write("\t");
    end ;
end;

-- recursively count references
refCount = function(objRefCount, item)
    -- only count reference types (tables)
    if type(item) == "table" then
        -- Increase ref count
        if objRefCount[item] then
            objRefCount[item] = objRefCount[item] + 1;
        else
            objRefCount[item] = 1;
            -- If first encounter, traverse
            for k, v in pairs(item) do
                refCount(objRefCount, k);
                refCount(objRefCount, v);
            end ;
        end ;
    end ;
end;

-- Format items for the purpose of restoring
writers = {
    ["nil"] = function(file, item)
        file:write("nil");
    end;
    ["number"] = function(file, item)
        file:write(tostring(item));
    end;
    ["string"] = function(file, item)
        file:write(string.format("%q", item));
    end;
    ["boolean"] = function(file, item)
        if item then
            file:write("true");
        else
            file:write("false");
        end
    end;
    ["table"] = function(file, item, level, objRefNames)
        local refIdx = objRefNames[item];
        if refIdx then
            -- Table with multiple references
            file:write("multiRefObjects[" .. refIdx .. "]");
        else
            -- Single use table
            file:write("{\n");
            for k, v in pairs(item) do
                writeIndent(file, level + 1);
                file:write("[");
                write(file, k, level + 1, objRefNames);
                file:write("] = ");
                write(file, v, level + 1, objRefNames);
                file:write(";\n");
            end
            writeIndent(file, level);
            file:write("}");
        end ;
    end;
    ["function"] = function(file, item)
        -- Does only work for "normal" functions, not those
        -- with upvalues or c functions
        local dInfo = debug.getinfo(item, "uS");
        if dInfo.nups > 0 then
            file:write("nil --[[functions with upvalue not supported]]");
        elseif dInfo.what ~= "Lua" then
            file:write("nil --[[non-lua function not supported]]");
        else
            local r, s = pcall(string.dump, item);
            if r then
                file:write(string.format("loadstring(%q)", s));
            else
                file:write("nil --[[function could not be dumped]]");
            end
        end
    end;
    ["thread"] = function(file, item)
        file:write("nil --[[thread]]\n");
    end;
    ["userdata"] = function(file, item)
        file:write("nil --[[userdata]]\n");
    end;
}

function Storage:get(var, default, path)
    path = path or Storage:getConfig()
    if (fileexists(path) == "0") then
        persistence.save(path, {})
    end
    local data = persistence.load(path)

    local T = split(var, '.')
    if (table.length(T) >= 2) then
        local section = table.remove(T, 1)
        var = table.concat(T, '.')
        if (data[section] == nil) then
            data[section] = {}
        end

        if (data[section][var] == nil) then
            data[section][var] = default;
            persistence.save(path, data)
            return default
        end
        return data[section][var]
    end

    if (data[var] == nil) then
        data[var] = default;
        persistence.save(path, data)
        return default
    end
    return data[var]
end

function Storage:getConfig()
    return "config/" .. os.getenv('username') .. ".config.env"
end

function Storage:set(var, value, path)
    path = path or Storage:getConfig()
    local data = {}
    if (fileexists(path) == "0") then
        data = {}
    else
        data = persistence.load(path) or {}
    end
    local T = split(var, '.')
    if (table.length(T) >= 2) then
        local section = table.remove(T, 1)
        if (data[section] == nil) then
            data[section] = {}
        end
        data[section][table.concat(T, '.')] = value
    else
        data[var] = value
    end
    persistence.save(path, data)
    return value
end

function Storage:getDay(var, value, path)

end

function Storage:getServer(var, value, path)

end