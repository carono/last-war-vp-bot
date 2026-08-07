# Fill an empty squad on the game's own screen and send it to a rally.
# ru: Заполнить пустой отряд на игровом экране и отправить его на ралли.
#
# THE FLOOR OF THE JOIN, NOT ITS ROUTE. `join_rally.md` sends a squad with one message
# and no window at all; this is what it CALLs when that send had nothing to send with —
# every candidate squad standing empty, with a banner out waiting for one. The client
# refuses a squad with no soldiers before a byte leaves (`hasSolider`,
# `GameDialogDefine.ADD_SOLDIER`), and filling one from the base's pool is what the
# game's own squad screen is for. No headless call for it is known yet; when one is
# found, this file goes away and `join_rally.md` loses its `CALL`.
#
# Kept apart from `join_rally.md` on purpose, and not merely for tidiness: everything
# here is four more calls into the game VM and a window on screen, and a reader of the
# join has to be able to see at a glance that none of it is on the path that catches a
# banner. The squad and the rally are already paired by the time this runs — the sieve
# and the pick live in `lua_actions.rally_join_all`, which parked them.
#
# It walks the windows the way `create_rally.md` drives the raise, waiting for STATES
# rather than sleeping:
#
#     OnClickStartMarch -> UIFormationSelectListV2 -> pick the squad -> OnCheckTime
#
# NOTHING CLOSES THAT SCREEN on the way. The old press opened it and shut it in the same
# breath, which is why the send behind it had nothing to stand on — the lesson #1172 paid
# for on the create side, repeated here because it cost this ability weeks. It closes
# itself when the launch is accepted.

TAP rally_join_arm

READ_LUA (function() local p = DataCenter.__lw_rally_join if p == nil or p.formation == nil then return 0 end return 1 end)() INTO armed

IF armed == 0
    FAIL "there is a rally out and a squad at home, but they could not be paired up — the squad has no formation the game knows"

TAP rally_join_open

READ_LUA (function() local function _isformation(w) return w ~= nil and (w.Name == 'UIFormationSelectListV2' or w.Name == 'UIFormationSelectListNew') end local w = UIManager.Instance:GetStackTopWindow() if _isformation(w) then return 1 end return 0 end)() INTO screen

WHILE screen == 0 LIMIT 12
    WAIT 0.25
    READ_LUA (function() local function _isformation(w) return w ~= nil and (w.Name == 'UIFormationSelectListV2' or w.Name == 'UIFormationSelectListNew') end local w = UIManager.Instance:GetStackTopWindow() if _isformation(w) then return 1 end return 0 end)() INTO screen

IF screen == 0
    FAIL "the rally did not bring up the squad screen — nothing was sent"

# A launch on a screen that is not holding the wanted squad is a press that ends in
# nothing, so the pick is confirmed before the send.
TAP rally_join_squad

READ_LUA (function() local function _isformation(w) return w ~= nil and (w.Name == 'UIFormationSelectListV2' or w.Name == 'UIFormationSelectListNew') end local p = DataCenter.__lw_rally_join or {} local w = UIManager.Instance:GetStackTopWindow() if not _isformation(w) then return 0 end if p.formation ~= nil and tostring(w.Ctrl.selectFormationUuid) == tostring(p.formation) then return 1 end return 0 end)() INTO picked

IF picked == 0
    TAP close
    FAIL "the squad screen would not take the chosen squad — nothing was sent"

# STILL THERE? A banner is minutes at best and seconds during an event, and the steps
# above cost a few of them. Launching at a rally that has already come down aims the send
# at a tile that is no longer one — the server refuses it, and what the player is shown is
# «invalid end point». Said apart from «pressed and nothing happened», because they are
# different things and only one of them is the bot's fault.
READ_LUA (function() local p = DataCenter.__lw_rally_join if p == nil then return 0 end local wm = DataCenter.WorldMarchDataManager local col = wm:GetAllMarches() if col == nil then return 1 end local e = col:GetEnumerator() while e:MoveNext() do local mo = e.Current local ok, v = pcall(function() return mo.Value end) if ok and v ~= nil then mo = v end local t = nil pcall(function() t = mo.teamUuid end) if t ~= nil and tostring(t) == tostring(p.team) then return 1 end end return 0 end)() INTO alive

IF alive == 0
    TAP close
    FAIL "the rally came down before the squad could be sent — it was gone by the time the screen was ready"

TAP rally_join_launch

# The proof is the same one the fast path uses: one more of OUR squads standing in a
# rally than there were before the press. `__lw_rally_before` was counted by the chunk
# that tried the headless send, in this same run.
READ_LUA ((function() local P=LuaEntry.Player local wm=DataCenter.WorldMarchDataManager local afd=DataCenter.ArmyFormationDataManager local n=0 for _,f in pairs(afd.ArmyFormationList) do pcall(function() local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) if m~=nil and tostring(m.teamUuid)~="0" then n=n+1 end end) end return n end)()) - (DataCenter.__lw_rally_before or 0) INTO joined

WHILE joined < 1 LIMIT 4
    WAIT 1.0
    READ_LUA ((function() local P=LuaEntry.Player local wm=DataCenter.WorldMarchDataManager local afd=DataCenter.ArmyFormationDataManager local n=0 for _,f in pairs(afd.ArmyFormationList) do pcall(function() local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) if m~=nil and tostring(m.teamUuid)~="0" then n=n+1 end end) end return n end)()) - (DataCenter.__lw_rally_before or 0) INTO joined

IF joined < 1
    FAIL "the empty squad was filled and launched and no squad joined the rally"

LOG "the squad was filled on the game's own screen and is in the rally"
