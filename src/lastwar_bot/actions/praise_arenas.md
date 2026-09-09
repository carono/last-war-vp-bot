# Like the top of both arena ladders and take the free diamonds the likes pay out.
# ru: Лайкнуть топ рейтинга на обеих аренах и забрать бесплатные алмазы за лайки.
#
# HEADLESS. No window is opened, no tab is switched, nothing is tapped: every press is
# the client's own send, and a run with no likes left is one VM round trip.
#
# WHAT IT IS FOR. Both arenas hand out a few diamonds a day for LIKING somebody on the
# ladder, and the person's words for it are «3 раза там и 3 раза там» — three likes on
# «Арена Шторма» and three on the 3v3 challenge, given to whoever stands at the top. The
# likes come back every game day, they cost nothing at all, and a day they are not given
# is a day of free diamonds thrown away.
#
# WHO IS LIKED: the account at `rank = 1` of the ladder the game itself hands over — the
# rank list, never a name written down here. A ladder that came back without a first
# place is left alone rather than guessed at.
#
# NOTHING IS SPENT. A like is free; the only thing it uses is the day's own count of
# likes, which is what the reward is paid on. There is no diamond price anywhere on this
# path and this recipe never sends one.
#
# THE GATE IS THE SERVER'S OWN COUNT. `remainPraise` is how many likes the day still
# allows, and a zero means the day's are given — by us this morning or by the person
# themselves. **A run that finds a zero does nothing and says so**; it never presses to
# find out, because a press that is refused looks exactly like one that worked.
#
# THE TWO ARENAS ARE ASKED SEPARATELY and neither is made to look like the other: the
# storm arena is `new.arena.*` / `NewPeakArenaManager`, the challenge is `score.*` /
# `LW3V3ArenaManager` (`docs/research/storm-arena.md`, `docs/research/arena-3v3.md`). A
# manager that does not answer — the account has not unlocked that arena, the client is
# still at the login screen — is reported as unread and the OTHER one still runs.
#
# NOT DETACHED. The whole run is a few seconds and nothing about it is a race.

SHARE
ARGS likes = 3
ARGS storm = 1
ARGS three = 1

# ---- an ear of our own, and the two asks --------------------------------------------
# The rank lists and the answers to a like are parsed by the SCREENS, so a panel with no
# window open has nowhere to read them from. This hook is `__lw_praise` and NOT the ones
# `read_arena_3v3` / `read_storm_arena` install: those hold their own `armed` guard, and
# a second wrapper hung on the same name is silently not installed at all.
READ_LUA (function() local ok, res = pcall(function() local B = DataCenter.__lw_praise if B == nil or not B.armed then B = {armed = true} DataCenter.__lw_praise = B local hm = SFSNetwork.HandleMessage SFSNetwork.HandleMessage = function(cmd, msg, more) local s = string.lower(tostring(cmd or '')) if string.find(s, 'praise', 1, true) or string.find(s, 'rank', 1, true) then B[s] = msg end return hm(cmd, msg, more) end end B.storm_sent = 0 B.three_sent = 0 pcall(function() SFSNetwork.SendMessage(MsgDefines.NewArenaRankList) end) pcall(function() SFSNetwork.SendMessage(MsgDefines.Get3V3ArenaRankList, 0) end) return 1 end) if not ok then return 0 end return res end)() INTO praise_ear

IF praise_ear != 1
    FAIL "the arenas' wire could not be listened to — the client is not answering"

WAIT 3

# ---- «Арена Шторма» ------------------------------------------------------------------
# The counts and the ladder ride on the rank list, which the ask above brought back. The
# likes go out in ONE round trip: a read is a thread hijack into the client at half a
# second a time whatever it asks, and the count they are spending is the SERVER's, so
# three sends in a row cost one trip and the server decides how many of them land.
IF storm == 1
    READ_LUA (function() local ok, out = pcall(function() local B = DataCenter.__lw_praise local m = DataCenter.NewPeakArenaManager if m == nil then return 'Арена Шторма: клиент про неё ничего не знает' end local r = m.rankData if type(r) ~= 'table' then return 'Арена Шторма: рейтинг не пришёл — лайки не отправлены' end local left = -1 pcall(function() left = math.floor((r.remainPraise or -1) + 0) end) if left < 0 then return 'Арена Шторма: сколько лайков осталось — игра не сказала, ничего не отправлено' end if left == 0 then return 'Арена Шторма: лайки на сегодня уже отданы' end local top = nil pcall(function() for _, row in pairs(r.players or {}) do if math.floor((row.rank or 0) + 0) == 1 then top = row end end end) if top == nil or top.uid == nil then return 'Арена Шторма: в рейтинге нет первого места — лайкать некого' end local want = {likes} if want > left then want = left end local how = 'нет отправителя' local sent = 0 for i = 1, want do local one = false if type(m.SendNewArenaPraise) == 'function' then one = pcall(function() m:SendNewArenaPraise(top.uid) end) if one then how = 'через менеджер' end end if not one then one = pcall(function() SFSNetwork.SendMessage(MsgDefines.NewArenaPraise, top.uid) end) if one then how = 'сообщением' end end if one then sent = sent + 1 end end B.storm_sent = sent return 'Арена Шторма: лайков было ' .. left .. ', отправлено ' .. sent .. ' (' .. how .. ')' end) if not ok then return 'Арена Шторма: лайки не отправлены — ' .. tostring(out) end return out end)() INTO storm_praise
    LOG "{storm_praise}"

# ---- the 3v3 challenge ---------------------------------------------------------------
# The challenge's own ladder is the reply to `score.arena.rank.list`, kept by the ear:
# the manager holds the event but not the list.
IF three == 1
    READ_LUA (function() local ok, out = pcall(function() local B = DataCenter.__lw_praise local m = DataCenter.LW3V3ArenaManager if m == nil then return 'Арена 3 на 3: клиент про неё ничего не знает' end local rep = nil pcall(function() for k, v in pairs(B) do local s = tostring(k) if string.find(s, 'rank', 1, true) and string.find(s, 'score', 1, true) and type(v) == 'table' then rep = v end end end) local left = -1 pcall(function() if type(m.remainPraise) == 'number' then left = math.floor(m.remainPraise + 0) end end) if left < 0 then pcall(function() if type(rep) == 'table' and type(rep.remainPraise) == 'number' then left = math.floor(rep.remainPraise + 0) end end) end if left < 0 then return 'Арена 3 на 3: сколько лайков осталось — игра не сказала, ничего не отправлено' end if left == 0 then return 'Арена 3 на 3: лайки на сегодня уже отданы' end local list = nil pcall(function() if type(rep) == 'table' then list = rep.players or rep.rankList or rep.list end end) if list == nil then pcall(function() list = m.rankList end) end local top = nil pcall(function() for _, row in pairs(list or {}) do if math.floor((row.rank or 0) + 0) == 1 then top = row end end end) if top == nil then return 'Арена 3 на 3: в рейтинге нет первого места — лайкать некого' end local uid = top.uid if uid == nil then pcall(function() uid = top.playerInfo.uid end) end if uid == nil then return 'Арена 3 на 3: у первого места нет опознавателя — лайкать нечем' end local want = {likes} if want > left then want = left end local how = 'нет отправителя' local sent = 0 for i = 1, want do local one = false if type(m.SendLike) == 'function' then one = pcall(function() m:SendLike(uid) end) if one then how = 'через менеджер' end end if not one then one = pcall(function() SFSNetwork.SendMessage(MsgDefines.Arena3V3Like, uid) end) if one then how = 'сообщением' end end if one then sent = sent + 1 end end B.three_sent = sent return 'Арена 3 на 3: лайков было ' .. left .. ', отправлено ' .. sent .. ' (' .. how .. ')' end) if not ok then return 'Арена 3 на 3: лайки не отправлены — ' .. tostring(out) end return out end)() INTO three_praise
    LOG "{three_praise}"

WAIT 3

# ---- what MOVED, not what was sent ---------------------------------------------------
# The server answers a like it accepted by moving its own count, and one it refused by
# leaving it where it was. So the report asks the ladders again and names a count that
# did not move as refused.
LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.NewArenaRankList) end)
LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.Get3V3ArenaRankList, 0) end)

WAIT 3

READ_LUA (function() local ok, out = pcall(function() local B = DataCenter.__lw_praise or {} local said = {} local function num(v) if v == nil then return '-' end local n = -1 pcall(function() n = math.floor(v + 0) end) if n < 0 then return '-' end return tostring(n) end local sleft = nil pcall(function() sleft = DataCenter.NewPeakArenaManager.rankData.remainPraise end) local ssent = math.floor((B.storm_sent or 0) + 0) said[#said + 1] = 'Шторм: отправлено ' .. ssent .. ', осталось лайков ' .. num(sleft) .. ((ssent > 0 and num(sleft) ~= '-' and math.floor((sleft or 0) + 0) > 0) and ' (часть ОТКАЗАНА)' or '') local tleft = nil pcall(function() tleft = DataCenter.LW3V3ArenaManager.remainPraise end) if tleft == nil then pcall(function() for k, v in pairs(B) do local s = tostring(k) if string.find(s, 'rank', 1, true) and string.find(s, 'score', 1, true) and type(v) == 'table' and v.remainPraise ~= nil then tleft = v.remainPraise end end end) end local tsent = math.floor((B.three_sent or 0) + 0) said[#said + 1] = '3 на 3: отправлено ' .. tsent .. ', осталось лайков ' .. num(tleft) .. ((tsent > 0 and num(tleft) ~= '-' and math.floor((tleft or 0) + 0) > 0) and ' (часть ОТКАЗАНА)' or '') return table.concat(said, ' | ') end) if not ok then return 'итог лайков не прочитан: ' .. tostring(out) end return out end)() INTO praise_report

LOG "Лайки на аренах: {praise_report}"
