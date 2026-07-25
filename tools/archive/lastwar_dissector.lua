-- Wireshark dissector for a Last War-style custom TCP protocol.
--
-- Assumed frame layout (LITTLE-ENDIAN), adjust once you confirm it in a
-- Follow-TCP-Stream hex dump:
--
--     [ uint32_le length ][ uint16_le opcode ][ body (length-2 bytes) ]
--       ^ length counts opcode + body (i.e. everything after the length field)
--
-- Install:  copy this file into your Wireshark "Personal Lua Plugins" folder
--   Windows:  %APPDATA%\Wireshark\plugins\
--   (Help -> About Wireshark -> Folders shows the exact path)
-- then Analyze -> Reload Lua Plugins (Ctrl+Shift+L).
--
-- Bind it to the game's port(s) — find them with tools/find_lastwar_connections.ps1
-- and edit LASTWAR_PORTS below. You can also right-click a packet ->
-- "Decode As..." -> LASTWAR to test without editing this file.

local LASTWAR_PORTS = { 0 }        -- <-- PUT THE REAL PORT(S) HERE, e.g. { 9339, 10001 }
local LENGTH_INCLUDES_OPCODE = true -- set false if `length` counts only the body

local p_lastwar = Proto("lastwar", "Last War game protocol")

local f_len    = ProtoField.uint32("lastwar.len",    "Length",  base.DEC)
local f_opcode = ProtoField.uint16("lastwar.opcode", "Opcode",  base.HEX)
local f_body   = ProtoField.bytes ("lastwar.body",   "Body")

p_lastwar.fields = { f_len, f_opcode, f_body }

local HEADER_LEN = 4      -- uint32 length prefix
local OPCODE_LEN = 2      -- uint16 opcode

-- Dissect one frame starting at offset 0 of `buf`. Returns number of bytes
-- consumed, or a negative value to request more bytes for reassembly.
local function dissect_one(buf, pinfo, tree)
    local avail = buf:len()
    if avail < HEADER_LEN + OPCODE_LEN then
        -- not even a full header yet: ask for one more TCP segment
        return -DESEGMENT_ONE_MORE_SEGMENT
    end

    local length = buf(0, HEADER_LEN):le_uint()
    local frame_len
    if LENGTH_INCLUDES_OPCODE then
        frame_len = HEADER_LEN + length          -- length already covers opcode+body
    else
        frame_len = HEADER_LEN + OPCODE_LEN + length
    end

    -- sanity guard against a mis-parsed length (endianness / layout wrong)
    if length == 0 or length > 10 * 1024 * 1024 then
        return avail   -- swallow the rest; layout is probably wrong — check hex dump
    end

    if avail < frame_len then
        return -(frame_len - avail)              -- need this many more bytes
    end

    local subtree = tree:add(p_lastwar, buf(0, frame_len))
    subtree:add_le(f_len, buf(0, HEADER_LEN))
    subtree:add_le(f_opcode, buf(HEADER_LEN, OPCODE_LEN))

    local body_off = HEADER_LEN + OPCODE_LEN
    local body_len = frame_len - body_off
    if body_len > 0 then
        subtree:add(f_body, buf(body_off, body_len))
        -- Uncomment to hand the body to Wireshark's Protobuf dissector once you
        -- have wired up a .proto search path (Preferences -> Protocols -> ProtoBuf):
        -- Dissector.get("protobuf"):call(buf(body_off, body_len):tvb(), pinfo, subtree)
    end

    local opcode = buf(HEADER_LEN, OPCODE_LEN):le_uint()
    pinfo.cols.info:append(string.format(" op=0x%04x len=%d", opcode, length))
    return frame_len
end

function p_lastwar.dissector(tvb, pinfo, tree)
    pinfo.cols.protocol = "LASTWAR"
    local offset = 0
    local n = tvb:len()

    while offset < n do
        local rest = tvb(offset):tvb()
        local consumed = dissect_one(rest, pinfo, tree)

        if consumed < 0 then
            -- reassembly request
            pinfo.desegment_offset = offset
            if consumed == -DESEGMENT_ONE_MORE_SEGMENT then
                pinfo.desegment_len = DESEGMENT_ONE_MORE_SEGMENT
            else
                pinfo.desegment_len = -consumed
            end
            return n
        end

        offset = offset + consumed
    end
    return n
end

local tcp_table = DissectorTable.get("tcp.port")
for _, port in ipairs(LASTWAR_PORTS) do
    if port and port > 0 then
        tcp_table:add(port, p_lastwar)
    end
end
