# Join the alliance rallies that are out, one squad each.
# ru: Присоединиться к выставленным ралли альянса — по отряду на ралли.
#
# `squads` is which squad slots may be spent, in order — the 1/2/3/4 the player sees in
# the dispatch panel. Each squad goes to a DIFFERENT rally: `squads = [1]` joins only the
# first rally with squad 1, `squads = [2, 3]` joins two rallies, one with squad 2 and one
# with squad 3. With fewer rallies out than squads, the leftover squads stay home; with
# more rallies than squads, the run says so.
#
#   run join_rally                       -- every ticked squad, one rally each
#   run join_rally {"squads": [2, 3]}    -- only squads 2 and 3
#
# TWO CALLS FROM THE PUSH TO THE SEND, and that is the whole point of this recipe's
# shape. A rally lives tens of seconds during an event; a call into the game VM was
# measured at 0.14 s with the daemon free and 10–19 s under the panel's ordinary
# background load, with the client at 59 fps the whole time (#1281,
# `tools/dev/rally_latency.py`). The version this replaces took EIGHT readings before it
# sent anything — 5.5 s to the send with the daemon quiet, and 100 s twice over when it
# was not — so it arrived after the banner it was woken for. Everything those readings
# asked is now a local variable inside ONE chunk (`lua_actions.rally_join_all`): the
# rallies out, the squads at home, the pairing, the send. Measured back to back on the
# same client, same minute: **5.48 s → 0.19 s.**
#
# NO WINDOW IS OPENED ON THE PATH THAT CATCHES A BANNER. The join is one message — the
# same `SendCreateMarchMessage` the game's own squad screen ends at, aimed at the tile the
# joiners gather on rather than at the monster (#1237, #1238), with the march type as the
# SECOND argument (#1277). The one thing left off this path is the squad
# standing EMPTY: the client refuses a squad with no soldiers before a byte leaves. That
# is not the march, so it is not on the march's path — the fast send goes out first for
# every squad that has an army, and only a run that sent NOTHING because every candidate
# was empty pays for `fill_empty_squads`, one request that fetches the army the server had
# all along (#1285). No window is opened by that either; there is none left in this file.
#
# EVERY SQUAD AND EVERY RALLY LEFT BEHIND IS NAMED IN THE LOG. The chunk writes its own
# sentence — how many went, how many rallies were out, and one word per squad it passed
# over (`out`, `empty`, `no-formation`) plus the server's own refusal for a send that
# threw — and this recipe reads it back and logs it. There is no ending where nothing
# happened and nothing was said.
#
# ALL THE RALLIES OUT, NOT THE FIRST ONE. The chunk pairs every free squad with a
# different banner in one pass, so two banners in the same minute cost one run. The old
# recipe joined ONE rally per run and the push for the second arrived while the first run
# was still going, where the work queue coalesced it away (#1281).
#
# The engine calls live in tools/lib/game_buttons.py (`rally_join_*`) and
# tools/lib/lua_actions.py; the reverse-engineering is docs/research/rally-join.md.

ARGS squads = [1, 2, 3, 4]
ARGS targets = ""
ARGS slots = ""
ARGS points = ""

# HOW MANY RALLIES THIS ACCOUNT JOINS IN A DAY — `0` is «as many as there are» (#1317).
#
# The ceiling is the person's and the COUNT IS THE GAME'S: the client keeps one daily
# rally-boss counter (`MonsterManager.daily_kill_boss`, threshold 20), the server resets
# it on the server's own day, and nothing here or in the panel writes a tally of its own.
# The press reads both in the one chunk it was already making, so the door costs no call.
#
# This is a REVERSAL of #1281, made on the player's word, and both halves of it were
# true. #1281 removed the door because the panel's own count had drifted twelve ahead of
# the game's and was refusing banners the account was entitled to — and because past the
# twenty the game stops PAYING rather than stops joining. What that leaves is «лимит
# Роковой Элиты стоит 20, а бот целый день цепляется к стягам»: a squad in an unpaid
# rally is a squad away from home for nothing. So the door is back and the tally is not.
#
# The count lags by the squads still marching (it moves when a rally FINISHES), so a
# ceiling can be overshot by about the number of squads in flight. Measured live over one
# day: the game counted 275 where the panel had recorded 320 joins.
ARGS max_joins = 0

# WHICH KINDS TO GO FOR AT ALL — `kind,kind,…` naming the ones to LEAVE ALONE (#1317).
#
# «Кроме Роковой Элиты есть ещё генералы, простые и элитные.» The kinds are the game's own
# species, and the whole list of them was read off the live config rather than guessed:
# every `boss = 1` row of `lw_world_monster`, grouped by the `name` key it points at —
# 71 keys, 66 distinct names, because the game calls six different rows «Роковая Элита»
# (`tools/lib/rally_kinds.py`). The two events are matched off their own managers instead:
# the Alliance Exercise by the `bossUuid` the drill manager carries, the Zombie Invasion by
# its own monster lists.
#
# A FILTER, NOT A BUDGET, and that is what makes it exact: nothing is counted, so nothing
# can drift. The kind of a banner is known before a squad leaves, so «к этим цепляйся, к
# тем нет» is answerable with the game's own facts and nothing of ours.
ARGS kind_skip = 

# …and the per-kind DAILY BUDGET, `kind:left,…`, `-1` for «no ceiling».
#
# «По умолчанию на всех по 20, на золотых оставляем без лимита.» A budget per kind can only
# be counted by the PANEL — the client keeps one daily rally counter and no per-species
# number anywhere; every boss / monster / rally / activity / season manager was walked for
# #1317 and there is none, and the trophy list that carries a `contentId` per finished rally
# is emptied whenever the player collects. The person chose it with that said out loud, so
# the drift is answered rather than hoped away:
#
#   * a join is counted only when the game CONFIRMED it — the run's own `joined`, a
#     difference measured in the client, never a frame that left (#1281 counted sends and
#     went twelve ahead);
#   * the tally is the profile's own file and rolls on the SERVER's day
#     (`GetTomorrowZero`), not on this machine's midnight;
#   * it is compared with the game's `daily_kill_boss` every time it is used, and **while
#     ours is ahead of the game's, no per-kind door refuses anything** — a banner is never
#     held back by a number the game contradicts;
#   * and `max_joins` above, which the GAME counts, stands over all of it, so drift cannot
#     turn into an overspend either.
ARGS kind_left = 

# The squads this run may spend, parked where the press can read them — `TAP` carries no arguments of its own. One call, and it is the only
# thing that stands between the push and the send.
#
# `slots` is `team:seats,…` off the same push the targets come from: how big each banner
# is. The chunk counts how many marches are standing in it already and passes over the
# ones with no seat left — the player watched the Marshal event and named it, every squad
# thrown at a banner nobody could enter (#1281). `__lw_rally_shut` starts empty every run: it
# collects the banners THIS run has been refused by, and a refusal is only terminal for
# as long as that banner stands — the next run asks the map again.
#
# `points` is `team:tile/server,…` off the same push: WHERE a joiner is sent. It is the
# one thing the client is slow about, and it is the whole of the delay a person sees
# (#1301). Measured over 91 banners: the push reaches the trigger in 0.005 s and the
# send goes out 0.3 s later, but the client's own march table — everything the sieve
# reads — learns about the banner a MEDIAN OF 10 s after the push, and in 23 of 26 late
# cases only once somebody ELSE had joined it. Every run inside that window honestly
# answered «no rally is out» and sent nothing. So a banner the wire has announced and the
# client has not caught up with is offered as a candidate with the address the push
# carried, and one the client already knows about is left to the client — nothing here
# overrides a reading, it only fills the gap ahead of one.
#
# `__lw_rally_cap` is the day's ceiling, parked in the same line and for the same reason:
# the press is one chunk and a door in front of it would be a second call on the one path
# that is measured in fractions of a second (#1317).
LUA DataCenter.__lw_rally_squads = { {squads} } DataCenter.__lw_rally_targets = "{targets}" DataCenter.__lw_rally_slots = "{slots}" DataCenter.__lw_rally_points = "{points}" DataCenter.__lw_rally_cap = tonumber("{max_joins}") or 0 DataCenter.__lw_rally_kind_left = "{kind_left}" DataCenter.__lw_rally_kind_skip = "{kind_skip}" DataCenter.__lw_rally_shut = {}

# Sieve, pair, send — every rally, in one press. Nothing is read before it and no window
# is opened by it.
TAP rally_join_all

# What it did, and what it left behind. A reading, so it costs nothing a banner cares
# about: the sends are already away.
READ_LUA (DataCenter.__lw_rally_report or "the join left no report — the press did not run") INTO report

LOG "the line above is what the press did, banner by banner"

# One number, three answers: how many went out, `0` for nothing to be done, and `-1` for
# «there is a rally standing there and the only squads left are empty», which is the one
# case `fill_empty_squads.md` earns its keep in.
READ_LUA (DataCenter.__lw_rally_todo or 0) INTO todo

# WHAT EACH SQUAD WENT TO, in the order it went — the budget is told this rather than
# «one join happened», so an invasion boss is counted under `zombie_invasion` and never
# against the ordinary monsters' twenty (`Schedule._kinds`, #1281).
READ_LUA (DataCenter.__lw_rally_kinds or "") INTO kinds

# THE DAY'S CEILING, AND IT IS CHECKED BEFORE EVERY OTHER ENDING (#1317). `-4` says the
# game's own count of today's rallies has reached the number the person set, so a banner
# passed over here is not a fault and not a quiet map — and a squad standing empty is not
# a reason to go and fetch it an army. The report line above names both numbers (`cap=`).
IF todo == -4
    LOG "not sent — the rallies allowed for today are already joined; the count is the game's own and the ceiling is the one set in «Автосбор»"
    STOP

IF todo == 0
    LOG "nothing was sent — the reason is on the line above"
    STOP

# UNDER STRENGTH, AND THE TWO WAYS OF BEING SO ARE NOT THE SAME NEWS (#1281). A squad
# is sent only when it is filled to what its heroes can carry
# (`GetAllHeroSoldierCapacity`), and the report names every squad it passed over with
# both numbers. `-2` is a squad the player can top up in the base; `-3` is a base that
# has not got the soldiers to fill ONE squad, and that one is a wall: the auto-join goes
# quiet and stays quiet until the barracks grows, so it says which wall it hit rather
# than letting a permanent silence look like an evening with no rallies in it.
IF todo == -3
    LOG "not sent — there are not enough soldiers in the base to fill a single squad to its ceiling; the numbers are on the report line above, and the auto-join will stay quiet until the barracks catches up"
    STOP

IF todo == -2
    LOG "not sent — every squad that could go is below the ceiling its heroes can carry; top them up in the base and the next banner will be taken"
    STOP

# OFF THE BANNER'S PATH ON PURPOSE, and in its own file so that a reader of this one can
# see at a glance that none of it is on the way to a send. Reached only when every squad
# that could go had already gone and one is standing empty.
#
# A SQUAD THAT READS EMPTY IS USUALLY A SQUAD NOBODY HAS ASKED ABOUT (#1285): the army is
# on the server and the client has not fetched it, and one request puts it back in 0.37 s
# with nothing on screen. The four presses and the window that used to be here are gone,
# because the game's own launch threw from inside its own code and the case had no working
# route at all.
#
# WRITTEN OUT HERE RATHER THAN `CALL fill_empty_squads`, and that is a correction paid for
# on a live measurement: a sub-recipe's failure FAILS THE CALLER
# (`script_engine._do_call`), so one bad step inside the try turned «nothing could be
# sent» into «the join run failed» — 59 times in an hour, on a panel that had not been
# restarted since the button was added and so had never heard of it. A press looks up a
# button in a catalogue the running process holds in memory; a recipe is read off the disk
# every run. So the one thing standing between a banner and a second chance is a `LUA`
# chunk, wrapped in `pcall`s of its own, which cannot fail the run whatever it finds.
#
# `fill_empty_squads.md` is still the ability and still what the «Ралли» button plays —
# this is the same request, on the path where a banner is waiting and nothing may throw.
IF todo < 0
    LOG "every squad that could go has gone and one is standing empty — asking the game for its army before giving up"
    LUA pcall(function() local afd = DataCenter.ArmyFormationDataManager for _, f in pairs(afd.ArmyFormationList) do local n = 0 pcall(function() n = tonumber(f.totalSoldierNum) or 0 end) if n == 0 then pcall(function() SFSNetwork.SendMessage(MsgDefines.GetFormationSoldier, f.uuid) end) end end end)
    WAIT 0.4
    READ_LUA (function() local afd = DataCenter.ArmyFormationDataManager local n = 0 for _, f in pairs(afd.ArmyFormationList) do local v = 0 pcall(function() v = tonumber(f.totalSoldierNum) or 0 end) if v > 0 then n = n + 1 end end return n end)() INTO armed_squads

    IF armed_squads == 0
        LOG "the squad is empty and the game has no army to fill it — nothing was sent"
        STOP

    TAP rally_join_all
    READ_LUA (DataCenter.__lw_rally_report or "the second join left no report — the press did not run") INTO report
    LOG "the line above is what the press did, banner by banner"
    READ_LUA (DataCenter.__lw_rally_todo or 0) INTO todo
    # AND WHAT THIS PASS WENT FOR. Read again because the FIRST pass sent nothing —
    # that is why this branch was reached — so the kinds read up there are empty, and a
    # budget told «this run went for nothing» writes nothing down for a run that did
    # join. Live: `kinds = ''` on seven runs that each sent one and joined one (#1281).
    READ_LUA (DataCenter.__lw_rally_kinds or "") INTO kinds

# THE ENDINGS THAT ARE A SKIP AND NOT A FAILURE. The squads were asked about and what
# came back is not enough to send: nothing the bot can press changes that, and the answer
# is the barracks rather than this ability. Each is said in its own words so that none of
# them reads as the join being broken — and, more to the point, so that a silence lasting
# weeks can be told from an evening with no rallies in it (#1281).
IF todo == -3
    LOG "not sent — the squads were asked about and the base has not got the soldiers to fill a single one to its ceiling; the auto-join will stay quiet until the barracks catches up"
    STOP

IF todo == -2
    LOG "not sent — the squads were asked about and every one of them is below the ceiling its heroes can carry; top them up in the base"
    STOP

IF todo < 0
    LOG "the squad is empty and the game has no army to fill it — nothing was sent"
    STOP

IF todo == 0
    LOG "nothing was sent even after the squads were asked about — the reason is on the line above"
    STOP

# --- the send went out: did the map move? ----------------------------------------
# A send returns cleanly whether the server took it or dropped it, and this ability spent
# weeks reporting success while joining nobody (#1237). The proof is one more of OUR
# squads standing in a rally than before the press, counted by the same chunk that sent
# them.
READ_LUA ((function() local P=LuaEntry.Player local wm=DataCenter.WorldMarchDataManager local afd=DataCenter.ArmyFormationDataManager local n=0 for _,f in pairs(afd.ArmyFormationList) do pcall(function() local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) if m~=nil and tostring(m.teamUuid)~="0" then n=n+1 end end) end return n end)()) - (DataCenter.__lw_rally_before or 0) INTO joined

# A few more looks and no more. The server answers in well under a second when it accepts
# off the fast path, and a poll that keeps asking is a poll holding the game in front of
# the next banner — but a run that came through `fill_empty_squads` waits longer, because
# the squad it just fetched an army for has to reach the map. Two looks called that a
# failure while the squad was already on its way (#1285, measured on a live banner), so
# the ceiling is three seconds and it is only ever paid when nothing has appeared yet.
WHILE joined < 1 LIMIT 6
    WAIT 0.5
    READ_LUA ((function() local P=LuaEntry.Player local wm=DataCenter.WorldMarchDataManager local afd=DataCenter.ArmyFormationDataManager local n=0 for _,f in pairs(afd.ArmyFormationList) do pcall(function() local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) if m~=nil and tostring(m.teamUuid)~="0" then n=n+1 end end) end return n end)()) - (DataCenter.__lw_rally_before or 0) INTO joined

IF joined >= 1
    LOG "the squads are in the rally — the count above is how many more of ours are standing in one"
    STOP

# --- refused: TAKE THAT BANNER OUT AND GO TO THE NEXT ONE, in the same run ---------
#
# «Мест уже нет» is a TERMINAL refusal — the game's own words for it are key `390857`,
# «Rally participant full. Unable to join.» — and the one thing that must not happen next
# is asking the same banner again. Nothing about it will change while it stands; every
# further squad spent on it is a squad not spent on the banner beside it, and during an
# event that is the whole difference (#1281).
#
# So the banners this pass sent to are written off for the rest of the run and the sieve
# runs again immediately: the squads that came back go to the NEXT rallies on the map,
# and the report names the shut ones under `no_seat=[…]` with `refused-full`. Only what
# can actually change is retried — a squad still on its way is caught by the wait above,
# not by this.
#
# Bounded on purpose. Two passes, because the third would be spending seconds a banner
# does not have, and what is left is reported rather than chased.
LUA pcall(function() local b = DataCenter.__lw_rally_shut or {} for t in string.gmatch(tostring(DataCenter.__lw_rally_sent_teams or ""), "[^,]+") do b[t] = true end DataCenter.__lw_rally_shut = b end)

LOG "no squad appeared where this pass sent — those banners are written off as full for this run, going to the next ones"

TAP rally_join_all

READ_LUA (DataCenter.__lw_rally_report or "the second pass left no report — the press did not run") INTO report

LOG "the line above is the second pass, with the shut banners taken out"

# …and what THIS pass went for: the first pass's squads never arrived, so its kinds
# stand for nothing and the run must be counted by what actually went out.
READ_LUA (DataCenter.__lw_rally_kinds or "") INTO kinds

READ_LUA (DataCenter.__lw_rally_sent or 0) INTO resent

IF resent == 0
    LOG "no other banner had a seat for the squads that came back — nothing more to try this run"
    STOP

READ_LUA ((function() local P=LuaEntry.Player local wm=DataCenter.WorldMarchDataManager local afd=DataCenter.ArmyFormationDataManager local n=0 for _,f in pairs(afd.ArmyFormationList) do pcall(function() local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) if m~=nil and tostring(m.teamUuid)~="0" then n=n+1 end end) end return n end)()) - (DataCenter.__lw_rally_before or 0) INTO joined

WHILE joined < 1 LIMIT 6
    WAIT 0.5
    READ_LUA ((function() local P=LuaEntry.Player local wm=DataCenter.WorldMarchDataManager local afd=DataCenter.ArmyFormationDataManager local n=0 for _,f in pairs(afd.ArmyFormationList) do pcall(function() local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) if m~=nil and tostring(m.teamUuid)~="0" then n=n+1 end end) end return n end)()) - (DataCenter.__lw_rally_before or 0) INTO joined

IF joined >= 1
    LOG "the squads are in a rally after moving on from the shut ones"
    STOP

# A PLACEHOLDER DOES NOT WORK HERE, and it is documented not to: `{x}` is substituted
# ONCE, before the run (docs/dsl.md), so a value a later `READ_LUA` writes never
# reaches a `LOG` or a `FAIL` — it prints as the literal `{x}`, which is what the
# first version of this line did. The reading logs its own value on the line above,
# so the sentence points there instead of pretending to carry it.
# WHAT THE SERVER SAID, before giving up on it (#1281). «The send went out and no squad
# appeared» is the same shape this ability spent weeks in — a press that returned cleanly
# over nothing happening — and naming it without naming the REFUSAL leaves the next reader
# exactly where we were. The client puts the server's own words on screen as a message
# tip; that tip is what «invalid end point» was, and reading it costs one call on the
# failing path only. Empty when the server said nothing, which is itself the answer: then
# the message never reached it.
READ_LUA (function() local ok, v = pcall(function() local m = UIManager.Instance if not m:IsWindowOpen(UIWindowNames.UICommonMessageTip) then return '' end local w = m:GetWindow(UIWindowNames.UICommonMessageTip) local t = w and w.View and w.View.tipText return t == nil and '' or tostring(t) end) if not ok or v == nil or v == '' then return 'the server said nothing on screen' end return v end)() INTO refusal

FAIL "the join was sent and no squad appeared in a rally — the game's own words are on the «refusal» line above"
