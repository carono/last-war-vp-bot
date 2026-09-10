# Take the Minister of Defence seat — withdraw whatever application stands in its way.
# ru: Занять пост министра обороны — сняв заявку, которая этому мешает.
#
# The post that speeds TRAINING up. Asked for by the arms-race unit phase
# (actions/arms_race_units.md), and useful on its own: the buff is the game's, the
# application is one headless call, and no window is opened at any point.
#
# ## Why a recipe rather than one TAP
#
# Because an account may hold only ONE standing application, and the panel already has
# an errand asking for the Minister of the Interior every half hour. Asked for a second
# post while the first application stands, the server answers — measured live (#2709):
#
#     kingdom.position.apply  ->  errorCode = E000000  errorMsg = "uid exist in Appointment"
#
# and the client puts its own toast on the screen. That is the whole of «заявка на
# министра обороны не использовалась»: the request left and was refused, every time.
#
# So the order is: look at what is held, withdraw what is in the way, then apply.
#
# ## What the game answers, and what none of it is guessed from
#
#   the post held now          `OfficialApplyManager:GetOwnPositionId()` — 0 when none
#   OUR place in a queue       `OfficialApplyManager:GetAppointmentInfo('<id>')` — our own
#                              row, with `appointTime` in MILLISECONDS: the moment the
#                              seat becomes ours. Absent = we are not queued there.
#   the queue itself           `SendKingdomPositionAppointmentList('<id>', true)` fills it;
#                              nothing pushes it, so it is asked for before it is read
#   the apply cooldown         `GetOwnApplyCD('<id>')` — MILLISECONDS, half an hour a post
#   withdraw an application    `SFSNetwork.SendMessage(MsgDefines.KingdomPositionAppointmentDelete,
#                                  {positionId = '<id>', uid = '<our uid>'})`
#   apply                      `UIOfficialApplyCtrl.SendKingdomPositionApply(C, '<id>')`
#
# **The withdraw takes a TABLE, and both fields go out as strings.** The controller's own
# `SendKingdomPositionAppointmentDelete(positionId, data, isCtrl)` sends NOTHING from a
# recipe — measured with `SFSNetwork.SendMessage` wrapped, the wire stayed empty — because
# it belongs to an open window. The message class is the way in, and it wants
# `{positionId, uid}`: the same call with `uid` missing throws inside the client's own
# serialiser (`attempt to get length of a nil value`), which is the ordinary tell that a
# UtfString field was not filled in.
#
# Position ids are STRINGS everywhere in this manager (docs/research/ministry.md).
#
# ## What it does NOT do
#
# It never resigns a post that is already ours: «если мы министр, ждём пока закончим»
# (#2709). A post held is a post working for us, and the minimum term is the server's
# (`GetResignOfficeTime()` = 1801 s), so the run says which post and leaves it alone.
#
# ## Arguments
#
#   drop_other  1 to withdraw an application standing on ANOTHER post so this one can be
#               made, 0 to leave it alone and do nothing. 1 by default: the caller that
#               wants the seat is the one asking, and an application nobody withdrew is
#               the reason the seat was never asked for.
#
# What it leaves behind for the caller, in the game's own VM:
#
#     DataCenter.__lw_ministry = {post = <held post id, 0 for none>,
#                                 defence_in = <seconds until our seat, -1 when not queued>,
#                                 note = '<what happened, in words>'}
#
# The research is docs/research/ministry.md.

ARGS drop_other = 1

READ_LUA (function() local M = DataCenter.OfficialApplyManager local ids = {'10004'} local ap = nil pcall(function() ap = M:GetOwnApplyPositionId() end) if ap ~= nil and tostring(ap) ~= '10004' then ids[#ids + 1] = tostring(ap) end for _, id in ipairs(ids) do pcall(function() M:SendKingdomPositionAppointmentList(id, true) end) end return 'asked the game for ' .. #ids .. ' queue(s)' end)() INTO ministry_ask

WAIT 2

READ_LUA (function() local M = DataCenter.OfficialApplyManager local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local own = 0 pcall(function() own = tonumber(M:GetOwnPositionId()) or 0 end) local box = {post = own, defence_in = -1, note = '', want = 0} DataCenter.__lw_ministry = box if own == 10004 then box.note = 'the Minister of Defence seat is already ours' return box.note end if own > 0 then box.note = 'another ministry post is held (' .. own .. ') — waiting for its term rather than resigning' return box.note end local mine = nil pcall(function() mine = M:GetAppointmentInfo('10004') end) if type(mine) == 'table' then box.defence_in = math.floor((mine.appointTime or 0) / 1000) - now box.note = 'already queued for the Minister of Defence — the seat comes in ' .. box.defence_in .. ' s' return box.note end local drop = math.floor(tonumber("{drop_other}") or 1) local stands, uid = '', '' local look = {} local ap = nil pcall(function() ap = M:GetOwnApplyPositionId() end) if ap ~= nil then look[#look + 1] = tostring(ap) end for _, id in ipairs({'10002', '10003', '10005', '10006', '10007'}) do look[#look + 1] = id end for _, id in ipairs(look) do if stands == '' and id ~= '10004' then local d = nil pcall(function() d = M:GetAppointmentInfo(id) end) if type(d) == 'table' then stands = id uid = tostring(d.uid or '') end end end if stands == '' then box.want = 1 box.note = 'nothing stands in the way — asking for the seat' return box.note end if drop == 0 then box.note = 'an application stands on ' .. stands .. ' and withdrawing is switched off' return box.note end if uid == '' then box.note = 'an application stands on ' .. stands .. ' but the game would not say whose — nothing withdrawn' return box.note end local ok = pcall(function() SFSNetwork.SendMessage(MsgDefines.KingdomPositionAppointmentDelete, {positionId = stands, uid = uid}) end) box.want = ok and 1 or 0 box.note = 'withdrew the application standing on ' .. stands .. ' (sent=' .. tostring(ok) .. ')' return box.note end)() INTO ministry_step

LOG "ministry: {ministry_step}"

# THE GAME MAY ASK «are you sure» (#2709). Withdrawing through the message class raised no
# window in the run this was measured on — the confirm belongs to the button, not to the
# wire — but the person has seen one, so it is answered rather than left on the screen: if
# `CommonTipConfirm` is open, press whatever it calls its «yes» and then close it with the
# client's own `Ctrl:CloseSelf()`. Never `DestroyAllWindow` (`CLAUDE.md`), and never a blind
# press: an absent window is not a failure and the run walks past it.
#
# Whether the withdrawal actually took is NOT decided here. It is read back from the game
# two chunks below, which is the only answer that counts.
READ_LUA (function() local U = UIManager and UIManager.Instance if U == nil then return 'no window manager' end local name = nil pcall(function() name = UIWindowNames.CommonTipConfirm end) if name == nil then return 'the client has no name for a confirm box' end local open = false pcall(function() open = U:IsWindowOpen(name) and true or false end) if not open then return 'no confirm box was raised' end local w = nil pcall(function() w = U:GetWindow(name) end) if w == nil then return 'a confirm box is open but the manager would not hand it over' end local pressed = '' for _, holder in ipairs({w, rawget(w, 'View') or w, rawget(w, 'Ctrl') or w}) do if pressed == '' and type(holder) == 'table' then for _, m in ipairs({'OnClickSure', 'OnSureBtnClick', 'OnClickConfirm', 'OnConfirmBtnClick', 'OnClickOk', 'OnClickYes'}) do if pressed == '' and type(rawget(holder, m) or holder[m]) == 'function' then local ok = pcall(function() holder[m](holder) end) if ok then pressed = m end end end end end local closed = false for _, holder in ipairs({rawget(w, 'Ctrl') or w, w}) do if not closed and type(holder) == 'table' and type(holder.CloseSelf) == 'function' then closed = pcall(function() holder:CloseSelf() end) end end return 'a confirm box was raised — pressed ' .. (pressed ~= '' and pressed or 'nothing it would name') .. ', closed=' .. tostring(closed) end)() INTO ministry_confirm

LOG "ministry: {ministry_confirm}"

WAIT 2

READ_LUA (function() local box = DataCenter.__lw_ministry or {} if math.floor(tonumber(box.want) or 0) ~= 1 then return 'nothing to send' end local M = DataCenter.OfficialApplyManager local cd = 0 pcall(function() cd = math.floor((tonumber(M:GetOwnApplyCD('10004')) or 0) / 1000) end) if cd > 0 then box.note = 'the apply cooldown on the Minister of Defence has ' .. cd .. ' s to run' return box.note end local C = nil pcall(function() C = require('UI.UIGovernment.OfficialApply.Controller.UIOfficialApplyCtrl') end) if type(C) ~= 'table' then return 'the apply controller is not there' end local ok = pcall(function() C.SendKingdomPositionApply(C, '10004') end) return 'application for the Minister of Defence sent=' .. tostring(ok) end)() INTO ministry_apply

LOG "ministry: {ministry_apply}"

WAIT 2

READ_LUA (function() local M = DataCenter.OfficialApplyManager pcall(function() M:SendKingdomPositionAppointmentList('10004', true) end) return 'asked for the defence queue' end)() INTO ministry_refetch

WAIT 2

# WHERE WE STAND NOW, which is what the caller acts on. A seat that is ours is worth
# training under; a seat that is coming is worth waiting for; neither is worth asking
# the game about twice, so the answer is parked rather than re-read.
READ_LUA (function() local M = DataCenter.OfficialApplyManager local box = DataCenter.__lw_ministry or {} DataCenter.__lw_ministry = box local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) local own = 0 pcall(function() own = tonumber(M:GetOwnPositionId()) or 0 end) box.post = own if own == 10004 then box.defence_in = 0 box.note = 'the Minister of Defence seat is ours' return box.note end local mine = nil pcall(function() mine = M:GetAppointmentInfo('10004') end) if type(mine) == 'table' then box.defence_in = math.floor((mine.appointTime or 0) / 1000) - now box.note = 'queued for the Minister of Defence — the seat comes in ' .. box.defence_in .. ' s' else box.defence_in = -1 if own > 0 then box.note = 'another ministry post is held (' .. own .. ')' else box.note = 'not queued for the Minister of Defence' end end return box.note end)() INTO ministry_state

LOG "ministry: {ministry_state}"
