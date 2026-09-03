# Give away the lucky packet a surprise box dropped — «раздать бесплатные алмазы».
# ru: Раздать в чат альянса счастливый пакет из ящика с сюрпризом.
#
# A surprise box sometimes drops a BIG BONUS: a red packet of free diamonds the player
# may give away, once, inside an hour of the drop. Giving it away costs nothing — the
# diamonds are the server's, not the account's — and an hour later the packet is gone
# whether or not anybody pressed anything.
#
# WHAT IT IS, IN THE CLIENT'S OWN WORDS (measured live 2026-09-03, #2397):
#
#   * `DataCenter.LuckyBuffManager.notSharedLuckyPacketList` — uuid -> `{configId, uid,
#     expireTime, count}`; the list this recipe empties.
#   * config `lw_conveyluck` row 102 — `red_packet = 502`, `type = 1`, `switch = 1`. The
#     packet BECOMES a red packet in chat; the row's `share_title`/`share_desc` are the
#     words the popup shows.
#   * the share itself is an ordinary chat share: `post = 611` (`PostType.RedPackge_New`)
#     with an attachment of `{redPocketId, uid, sid, worldId, worldType, expireTime,
#     redPocketType}` — the same shape `docs/research/chat-coord-share.md` records for a
#     coordinate, a different post type.
#
# WHY THIS DRIVES THE CLIENT'S OWN WINDOWS INSTEAD OF SENDING THE SHARE ITSELF. The
# payload above is fully known, so a headless `SendSFSMessage` is writable — and it was
# deliberately not written first, because the packet is ONE, the window is an hour, and a
# refused send cannot be tried again with a better guess until the next box drops. The
# client's own path is proven: `OpenLuckyPacketSharePopup` → the popup's «Поделиться» →
# the room chooser → the alliance room. Three windows, opened and closed inside this run.
# The headless send is the next step and is written up in docs/research/lucky-packet.md.
#
# THE CHOOSER IS PICKED BY CATEGORY AND NEVER BY POSITION. Live it offered exactly one
# room — the alliance one — but a share posted to the WORLD room is visible to the whole
# server and cannot be taken back, so the row is chosen by its own `group == 'alliance'`
# and a chooser without one is closed untouched. «Не нашёл чат альянса» is a fine outcome;
# «поделился не туда» is not.
#
# The gate is local and costs nothing: no packet, none alive, or no alliance to give it
# to, and the run stops before a window is opened.
CALL read_lucky_packet
READ_LUA (function() local m = DataCenter.LuckyBuffManager if not m then return 0 end local inst = m.Instance or m local now = 0 pcall(function() now = UITimeManager:GetInstance():GetServerTime() end) if now == nil or now == 0 then now = os.time() * 1000 end local live = 0 for _, e in pairs(inst.notSharedLuckyPacketList or {}) do if type(e) == 'table' and (tonumber(e.expireTime) or 0) > now then live = live + 1 end end local al = 0 pcall(function() local a = tostring(LuaEntry.Player.allianceId or '') if a ~= '' and a ~= 'nil' and a ~= '0' then al = 1 end end) if al == 0 then return -1 end return live end)() INTO live
IF live == 0
    STOP "делиться нечем — неотданных пакетов нет"
IF live == -1
    STOP "пакет есть, но раздать его некуда — аккаунт вне альянса"

# The popup, and then its «Поделиться» — which does not send anything by itself: it opens
# the room chooser with the packet already prepared inside it.
LUA (function() local m = DataCenter.LuckyBuffManager local inst = m.Instance or m pcall(function() inst:OpenLuckyPacketSharePopup() end) end)()
WAIT 2
LUA (function() local w = UIManager.Instance:GetWindow('UIShareLuckyBuffPopup') DataCenter.__lw_lucky_step = 'no popup' if w and w.View then local ok, err = pcall(function() w.View:OnBtnShareClick() end) DataCenter.__lw_lucky_step = 'share-click ok=' .. tostring(ok) .. (ok and '' or (' err=' .. tostring(err))) end end)()
WAIT 2

# The room, by its own category. `OnItemClick` takes the ROW, not an index — an index
# throws inside the view («attempt to index a number value (local 'channel')»), which is
# how it was found.
READ_LUA (function() local w = UIManager.Instance:GetWindow('UIPositionShare') if not w or not w.View then return 'no-chooser' end local v = w.View local room = nil local seen = 0 for _, r in pairs(v.list or {}) do seen = seen + 1 if room == nil and tostring(r.group) == 'alliance' then room = r end end if room == nil then return 'no-alliance-room rooms=' .. seen end local ok, err = pcall(function() v:OnItemClick(room, 1) end) if not ok then return 'refused ' .. tostring(err) end return 'sent' end)() INTO sent
WAIT 2.5

# What the game says afterwards: the list is the authority, exactly as it was before the
# press. A packet still in it was not given away, whatever the click returned.
READ_LUA (function() local m = DataCenter.LuckyBuffManager local inst = m.Instance or m local left = 0 for _ in pairs(inst.notSharedLuckyPacketList or {}) do left = left + 1 end return left end)() INTO left
LUA (function() local m = UIManager.Instance for _, n in ipairs({'LWUIRedPacketDetails', 'UIPositionShare', 'UIShareLuckyBuffPopup'}) do pcall(function() local w = m:GetWindow(n) if w and w.Ctrl and w.Ctrl.CloseSelf then w.Ctrl:CloseSelf() end end) end end)()
IF left == 0
    LOG "Счастливый пакет раздан в чат альянса — бесплатные алмазы забирают там ({sent})"
IF left > 0
    FAIL "пакет остался неотданным ({sent}), в списке ещё {left}"
