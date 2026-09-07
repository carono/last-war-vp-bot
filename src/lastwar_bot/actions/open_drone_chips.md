# Open every skill-chip chest in the bag — the duel's Monday, in one call.
# ru: Открыть в сумке все сундуки чипов — понедельник дуэли, одним вызовом.
#
# WHAT IT OPENS, and it is the person's own decision (#2617). The duel's Monday pays for
# opening chip chests; an account holds several GRADES of them and each grade is several
# stacks, which is what «их может быть несколько» means. The ids below are the three the
# live bag carries — «Сундук Чипа Навыка R / SR / SSR» — and they travel as an argument
# rather than being written into the press, so an account with a fourth grade adds it in
# the panel instead of in the code.
#
# THE NAMES ARE NOT THE SAME THING. «Компоненты дрона» (`Сундук Компонента Дрона N ур.`,
# 630011…630013) are a DIFFERENT box and this recipe deliberately does not touch them:
# the person was asked which of the two the Monday button opens and answered the chip
# chests. Nothing here guesses between them.
#
# ONE CALL, NOT ONE PER STACK. A press is a thread hijack into the client — about half a
# second, and the machine makes roughly 1.4 a second in total
# (docs/research/link-contention.md) — so opening a hundred stacks one press at a time is
# a minute of everybody's budget. The loop is inside `use_bag_ids`, exactly as the
# alliance donation's thirty attempts are.
#
# WHAT IT REPORTS. `chips_opened` is the total and `chips_per_id` is the same thing by
# GRADE — «540201:31,540401:3» — because the page that draws the chests keeps a tally per
# grade, and a chest that is open is gone: the count of them exists nowhere but in the
# panel's own store.
#
# WHAT IT SPENDS: the chests themselves, and nothing else. No diamonds, no daily quota,
# no march. An empty bag is a STATE and not a failure — it stops and says so.

# WHICH BOXES. Comma-separated item ids, as the bag reads them.
ARGS ids = 540201,540301,540401

# 1. Park them, because `TAP` carries no arguments of its own.
LUA DataCenter.__lw_use_ids = '{ids}'

# 2. What is there before anything is opened — a run that opens nothing must say why.
READ_LUA (function() local raw = tostring(DataCenter.__lw_use_ids or '') local D = DataCenter.ItemData if D == nil then return 0 end local want = {} for piece in string.gmatch(raw, '[^,]+') do local n = math.floor(tonumber(piece) or 0) if n > 0 then want[n] = true end end local total = 0 pcall(function() for _, v in pairs(D.ItemInfos or {}) do if want[math.floor(tonumber(v.itemId) or 0)] then total = total + math.floor(tonumber(v.count) or 0) end end end) return total end)() INTO chips_have
LOG "chip chests in the bag: {chips_have}"
IF chips_have == 0
    STOP "no chip chests in the bag — nothing to open"

# 3. Open every stack of every id.
TAP use_bag_ids
WAIT 2

# 4. Say what the client actually sent, in its own numbers.
READ_LUA (function() local u = DataCenter.__lw_use_all or {} return 'ids=' .. tostring(u.ids or '-') .. ' used=' .. tostring(math.floor(tonumber(u.used) or 0)) .. ' stacks=' .. tostring(math.floor(tonumber(u.stacks) or 0)) .. ' why=' .. tostring((u.why ~= nil and u.why ~= '') and u.why or '-') end)() INTO chips_report
LOG "opened: {chips_report}"

READ_LUA (function() local u = DataCenter.__lw_use_all or {} local s = tostring(u.per or '') if s == '' then return '-' end return s end)() INTO chips_per_id
LOG "by grade: {chips_per_id}"

READ_LUA (function() local u = DataCenter.__lw_use_all or {} return math.floor(tonumber(u.used) or 0) end)() INTO chips_opened
IF chips_opened == 0
    FAIL "nothing was opened — {chips_report}"
