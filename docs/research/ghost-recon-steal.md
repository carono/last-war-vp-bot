# Robbing a ghost-recon squad — «Операция Призрак»

Task follow-up to #1005 (the wire capture) and #1099 (the secret-task robbery).
The Lua side below was pinned live against the VM through the warm daemon.

## 0. This is not the secret-task robbery

Two robberies exist and they are easy to confuse, because the in-game buttons
look alike:

| | «Секретка» / hero dispatch | «Операция Призрак» / ghost recon |
|---|---|---|
| command | `hero.dispatch.steal` | `ghost.recon.steal` |
| fields | `uuid`, `targetServer` | `uuid`, `ownerServer` |
| map tile | `f2 = 17` | `f2 = 29` |
| manager | `DataCenter.ActDispatchTaskDataManager` | `DataCenter.ActGhostreconManager` |
| map button | `WorldPointBtnType.DispatchTaskSteal` (54) | `WorldPointBtnType.GhostreconTaskSteal` (96) |
| daily budget | 5 (`GetDispatchSetting("steal_count")`) | 5 (`GetNowSettingCfg().stealCount`) |
| available | every day | the event's day, `IsOpenDay()` |
| docs | [`secret-task-steal.md`](secret-task-steal.md) | this file |

The budgets are counted separately, so a day can spend both. Everything in the
repo keeps them apart: separate primitives, separate buttons, separate queues
(`__lw_steal_queue` vs `__lw_ghost_queue`), separate recipes.

## 1. The wire (captured in #1005)

`results/ghost1005/steal.json` holds the real exchange:

```
--> ghost.recon.steal  {uuid: 1397117098857328280, ownerServer: 700, _id}
<-- ghost.recon.steal  {reward[], recordUuid, stealTimes: 2, ownerInfo{uid, name,
                        country, abbr, ...}, cfgId: "60302", ownerUid,
                        ownerServer, uuid}
```

Follow-up, same capture:

```
--> ghost.recon.leave.message {msgId, recordUuid, ownerServer}
<-- ghost.recon.leave.message {success: true}
```

`recordUuid` comes from the robbery's own reply, not from the tile.

## 2. The Lua path

* `MsgDefines.GhostReconSteal` = `ghost.recon.steal`;
  `MsgDefines.GhostReconLeaveMessage` = `ghost.recon.leave.message`;
  `MsgDefines.GhostreconGetTaskList` / `GhostReconGetAllianceTaskList` fetch the
  two task lists.
* `Net.Msgs.Ghostrecon.GhostReconStealMessage:OnCreate(uuid, ownerServer)` puts
  **exactly two** fields in the SFSObject — `PutLong uuid`, `PutInt ownerServer`
  — matching the capture byte for byte.
* The press is a branch of the giant map-button dispatcher
  `UI.UIWorldPoint.Component.UIWorldPointBtn:OnBtnClick`; its constants run
  `… GhostReconSteal | ownerServer …`, i.e. one `SFSNetwork.SendMessage`. So the
  robbery needs no window, no popup and no camera move.
* `GhostReconStealMessage:HandleMessage` is the **reply applier**
  (`RewardManager:AddRewardsAndRes` → `ActGhostreconManager:GhostReconStealHandler`,
  or `UIUtil.ShowTipsId` on an `errorCode`). Calling it sends nothing — the same
  trap as `OnHelpAll` and `DispatchStealMessage:HandleMessage`.

## 3. What the client knows about a target

`DataCenter.ActGhostreconManager.taskList` holds `ActGhostreconTaskInfo` records,
parsed from `ghost.recon.get.task.list`:

```
uuid, ownerId, cfgId, ownerServer, targetServer, completionTime, pointId,
state, allianceId, teamStartTime, sendChatTime, remindTime, taskExpireTime,
actEndTime, stealList[] (uid, time, name, abbr, msgId, reward), memberList[]
```

`DataCenter.ActGhostreconAllianceManager.allianceTaskList` is the alliance view and
is **not** usable as a raid list: `ActGhostreconAllianceTaskInfo` carries only
`uuid, cfgId, targetServer, pointId, teamStartTime, ownerId, memberList` — no
`completionTime`, no `stealList`, so it cannot answer "is this robbable".

Templates: `ActGhostreconTaskTemplate` gives `stealMaxtimes` (3 on cfg 60302),
`protectTime`, `level`, `times`; `ActGhostreconSettingTemplate` gives
`stealCount` (5/day), `teamworkCount`, `maxTaskQueue`.

### 3a. The cfgId — family is rarity, `MM + 2` is the level (#1137)

A ghost cfgId is five digits, `F` + `MM` + `VV`:

* `F` — the rarity family, 4/5/6 (the UI colours SSR / UR / UR★). "6" is the top
  tier, the star (`GHOST_STAR_FAMILY`). It does **not** set the level.
* `MM` — two digits, 01/02/03, that carry the level.
* `VV` — a variant (mission subtype); 6 variants exist for `MM=01`, 9 for `02`,
  12 for `03`.

The player-facing level ("ур.5") is **`MM + 2`**, the same for every family:

| `MM` | game level | seen on the map |
|---|---|---|
| 01 | ур.3 | rare — below the edge tiers |
| 02 | ур.4 | yes |
| 03 | ур.5 | yes (the common edge tier) |

This was read straight off the live template — `ActGhostreconManager:GetTaskTemplate(cfgId).level`
returns exactly `MM + 2` for every real cfgId (a real one has `template.id ==
cfgId`; an unknown cfgId returns a level-1 fallback with `id = 0`), identical
across families 4/5/6. Only `MM` 01..03 has a real template today, so levels run
3..5; a higher `MM` would extend the same `+2` line but none has appeared.

The bug this fixes (#1137): the generic `split_cfg_id` (built for a secret task's
`family` + `LLVV` cfgId) reads `MM` straight as the level and reported 1/2/3 — so
an ур.5 mission showed as "lvl3". `lastwar_proto.ghost_recon_level` applies the
`+2` mapping instead (`GHOST_LEVEL_OFFSET`), correcting both the poll and the
`f2 = 29` map-tile decode paths.

## 4. The gate — ask the game, but route around its own crash

`ActGhostreconManager:GetPointStealType(cfgId, completionTime, stealList)` is the
client's verdict, returning `GhostreconPointStealType`:

| value | name | meaning |
|---|---|---|
| 1 | `Preview` | visible, not robbable yet |
| 2 | `CanSteal` | robbable now |
| 3 | `UnSteal` | budget spent / already robbed by me |
| 4 | `UnShow` | still running, or no template |

Verified live against cfg `60302`:

```
GetPointStealType(60302, <finished a minute ago>, {})  -> 2  CanSteal
GetPointStealType(60302, <finishes in 10 min>,    {})  -> 4  UnShow
GetPointStealType(60302, <finished>, {{uid=…}})        -> error
```

**That last line is a bug in the game, not in the call.** With a non-empty
`stealList` the client throws
`ActGhostreconManager.lua:570: attempt to index a nil value (field 'player')` — it
reads `LuaEntry.player` (lowercase), which does not exist in this VM
(`LuaEntry.Player` does). So `ghost_recon_can_steal()` calls the game's gate with
an **empty** list for the timing half, and counts the looter half itself:
`#stealList < template.stealMaxtimes` and my own uid not among them — the same
arithmetic the crashing branch was doing.

The remaining conditions are read straight off the manager:

* `IsOpenDay()` — the event runs one day a week; off-day, everything is dark;
* `stealTimes` vs `GetNowSettingCfg().stealCount` — the daily budget;
  **and the two run out at the SAME INSTANT** — see below, it is why an unspent
  ghost budget is not a thing you can come back to in the morning;
* `dispatchStealRange[server]` — the set of servers the event lets you rob
  (live: 421–676 plus 8053–8084; the account's own server is in it). This is
  the ghost-recon analogue of the secret task's "not in the same sector" refusal;
* `ownerId ~= my uid` — robbing my own squad is not a thing.

### 4.1 When the day ends — asked of the client, not counted on a PC clock

Measured 2026-08-06 for #1188, because «wait for the daily reset» turned out to be the
wrong plan for this event and nobody could have known that from the outside.

`IsOpenDay` is one comparison, read out of its own bytecode
(`string.dump`, the trick in `secret-task-steal.md` §2):

```
openTime · UITimeManager · GetInstance · GetServerTime · IsSameDayForServer · self
```

— «is `self.openTime` on the same SERVER day as now». So both answers are readable
without guessing at a timezone:

| what | how | live value |
|---|---|---|
| the event's day | `DataCenter.ActGhostreconManager.openTime` | `2026-08-06 02:00:00 UTC` |
| the next server midnight | `UITimeManager:GetInstance():GetTomorrowZero()` | `2026-08-07 02:00:00 UTC` |
| this machine's offset | `UITimeManager:GetInstance():GetLocalUTCOffset()` | `5` (hours) |

The server day therefore runs **02:00 UTC → 02:00 UTC**, and `openTime` is exactly the
start of the day the event is on. Independently corroborated: `protocol.md` §7 recorded
597 of 636 tile expiries sharing one timestamp, `01:59:59 UTC` — one second before this
same boundary.

**The consequence is the point.** The daily steal budget resets at the server midnight,
and `IsOpenDay()` goes false at the same instant, because the event's day is the day
that just ended. So a ghost budget spent on the event day is spent for the WEEK: there
is no moment at which `left > 0` and `IsOpenDay()` are both true again until the next
`openTime`. Anything waiting on «the quota comes back at midnight» — a person, a
standing order, a task's acceptance — is waiting for a state that will not occur.

`openTime` is pushed by the server with the activity list, so next week's is not
readable today; the next window is *expected* one week on and should be confirmed by
reading `openTime` again rather than assumed.

Never compute any of this from the PC clock: the game's is the authority and the two
were 17.9 s apart when this was measured, with the PC the slow one (`game-clock.md`).

## 5. What is automated

* `tools/lib/lua_actions.py` — `ghost_recon_is_open()`,
  `ghost_recon_steals_left()`, `ghost_recon_steal_state(uuid)`,
  `ghost_recon_can_steal(uuid)`, `ghost_recon_refresh()`,
  `ghost_recon_targets_dump()`, `ghost_recon_steal(uuid, server)`,
  `ghost_recon_leave_message(...)`, and the queue
  (`ghost_recon_queue_set/clear/len`, `ghost_recon_steals_pending`,
  `steal_next_ghost_recon`).
* `tools/lib/game_buttons.py` — `steal_ghost_recon` (one press = one squad off
  the queue, `count_lua` = min(queued, budget), 0 while the event is closed) and
  `dismiss_ghost_recon_reward`.
* `tools/ghost_recon_steal.py` — `--status`, `--list` (every known squad with the
  game's verdict), `--all` (queue everything robbable), `--uuid/--server`,
  `--targets uuid:server,…` (queue exactly these, in this order, re-deriving
  nothing — what the panel's standing order hands over, #1256), `--queue-only`.
* `src/lastwar_bot/actions/steal_ghost_recon.md` — the recipe.

## 6. Confirmed, and what is not

Confirmed live (event **closed** — this is the honest limit of this session):

| Check | Result |
|---|---|
| `MsgDefines.GhostReconSteal` / `…LeaveMessage` / the two list commands | present, names as above |
| `GhostReconStealMessage:OnCreate` field set | `PutLong uuid` + `PutInt ownerServer` |
| the sender is `UIWorldPointBtn:OnBtnClick`'s btnType-96 branch | constants read `GhostReconSteal \| ownerServer` |
| `GetPointStealType` finished vs running | 2 vs 4, as tabulated |
| non-empty `stealList` | reproducible client-side error (§4) |
| budget / open-day reads | `stealCount` 5, `stealTimes` 0, `IsOpenDay()` false |
| `dispatchStealRange` covers the account's server | true (200) |
| a queued target while the event is closed | `steals_pending` 0, the press sends **nothing** |
| `actions/steal_ghost_recon.md` end to end | runs, 0 presses, no error |

**Not confirmed: an actual robbery.** `taskList` is empty outside the event, so no
real uuid was available and no `ghost.recon.steal` was sent from this code. The
feature therefore stays 🟡 in `docs/farming.md` until it is run on an event day —
what to do then is: `--list` to see the squads, `--all` to queue what the client
calls robbable, then the recipe (or `--all` without `--queue-only`).

## 6a. The standing order, and where its targets come from (#1256)

The «Командный пункт» page's checkbox is the unattended form of the same robbery,
and since #1256 the choosing is the PAGE's rather than the tool's. A look fills
the page's own list from the two sources it has — the client's `taskList` and
whatever a map sweep wrote into the ghost checkpoint, which is the only one that
ever shows another alliance's tiles — and then the list is asked which squads the
rule wants: robbable by the game's own verdict, not my own, and at or above the
page's «минимальный уровень» (its own number, since a squad runs levels 3-5 where
a secret task runs 1-7). Those go to `--targets` by name; «Ограбить всё» presses
the very same call, so the button and the watcher can no longer take different
squads. The event day and the five-a-day budget stay the GAME's gates — read
before anything is chosen, and read again by the tool before every send.

Also open: which `cfgId` families are worth robbing (the capture shows `60302` —
family "6", the star, ур.5 by the `MM + 2` rule in §3a, `stealMaxtimes` 3), and
whether `leave.message` needs the window open — it is built from the reply's
`recordUuid` and has never been sent from here.

## 6b. Why the list was empty, and the day the squads stopped riding a file (#2010)

«Автолут заданий призрака не работает, грид не заполняется.» Two complaints, one
cause, and it was upstream of both: nothing the sniffer decoded ever reached the
panel's list, so the standing order had nothing to spend the event's own five a day on
(five, counted apart from the five secret-task robberies — different manager, different
counter; measured live on 2026-08-27, `steal_left=0 of 5` while `ghost_left=5 of 5`).

**Measured on a live profile before the fix.** `ghost_map_state` in `panel.db`
held `[]` and the capture's checkpoint held `[]`, while the same profile's log
said, of the very same minute:

```
…running — server <N>, 1551 map response(s), 168938 tile(s), 3 task(s)      ← ★ sniffer
…running — server <N>, 1018 map response(s), 112950 tile(s), 1 mission(s)   ← ghost sniffer
```

A hundred thousand tiles decoded, one squad in the file, an empty page.

**Three things had to be wrong at once, and they were:**

1. **A ghost squad reached the panel only through a checkpoint FILE**, rewritten
   every tick out of an index that drops every tile not on the warzone currently on
   screen (`MissionIndex.on_server_left`). A lap of the map walks eighteen warzones
   in a few seconds, so what a lap found was gone before anything read it. The ★
   tiles stopped depending on that in #1416, when each one began travelling as its
   own event (`##TILE##`) at the moment it was decoded; the ghost ones never did.
2. **The merge saved before it restored.** `refresh_ghost_map` runs headless
   (#1523) and ends in `apply` → `persist`, while `GhostMapGrid.restore` hung on
   somebody opening the tab. A panel nobody had looked at therefore merged an empty
   file into an empty list and wrote the result over what the last session had
   gathered. That is the `[]` above — not a list that never filled, a list erased.
3. **The standing order chose out of a third thing again** — `load_fresh_ghost_recon`
   over that same vanishing file, through its freshness window. So even a lap that
   did land somewhere left the robbery with nothing.

**What it is now, and it is the ★ shape throughout.** The squad is an event
(`##GHOST##`, printed beside the human line, carrying the tile and nobody's uid —
#1293); the panel's hook parses it and hands it over; the merge is one Tk pass over
whatever piled up, and it restores the kept list first (`_ensure_ghost_model`, the
twin of `_ensure_model`). The checkpoint stays what it always should have been: the
fallback for a restart. And the standing order reads the list the person is looking
at — `store.GHOST_MAP_STATE`, judged against the clock as it is read, so a stale
`ready` cannot spend one of the five and a tile robbed out is never offered.

The age rule the ★ list got in #1999 applies to the map page too, for the reason it
bites hardest there: a lap brings back everybody's tiles and nothing re-sends them.
It is the same field, the same number and the same promise — a filter, never a
delete, and the robbery never asks.

**Still open, and named here so it is not rediscovered as a bug:** the ghost sniffer
is a second npcap reader on one interface, which is why its counters run below the ★
one's in the same minute (1018 against 1551 above). Two captures over one adapter
starve each other (044c19f, `docs/research/world-monitor.md` §1), and the cure is the
one that worked for the mines: fold the index into the ★ capture's process behind a
flag rather than run a second child. It costs three forwarded calls and it was not
part of this fix.

## 6c. …and the order moved to the page holding its list (#2010)

The other half of «автолут не работает», and it was not a bug in the watcher: on the
live profile the watcher did not EXIST. Its switch, its «минимальный уровень» and
«Ограбить всех» were on «Командный пункт», which is a dev-only tab
(`DEFAULT_ENABLED = False`); that profile had it switched off, so the order was never
built, on either front-end, and `ghost_autoloot` sat `false` in a block nobody could
open.

So it went where «Автолут ★» has been since #1271 — the page holding the list it spends,
which is «Секретки» → «Призрак: карта», a tab every profile has and one that is EAGER
(its capture listens from boot, which is what an order over a weekly event needs).

What that changed, and what it deliberately did not:

* the switch, the level rule and «Ограбить всех» are on that page in the window and on
  its card on the phone — a knob nobody can reach is worse than one somebody can get
  wrong, and this one was unreachable from both;
* the choosing is simpler, because the page's rows are LIVE: a look no longer has to
  re-read anything to have a list. `GhostMapGrid.rob_candidates` judges readiness
  against the clock rather than off `row["ready"]`, which is only recomputed while there
  is a table to draw — this list is fed and spent headless;
* the display filters do not narrow it. «Только звезда», the level range and the age
  rule are a pair of eyes; somebody narrowing them to read something must not thereby
  change how the event's own five a day are spent — a budget of its own, not a share of
  the secret tasks'. That is the same separation the ★ list keeps;
* «Командный пункт» keeps what it is — the squads with the game's own verdict and
  «Ограбить» beside a row. Its per-row press asks the runtime's tab register for the one
  order (`docs/panel-tabs.md`), never for a second one, and answers «занят» when
  «Секретки» is switched off. One ability, one place;
* a profile written before the move is carried across once: the flat `ghost_autoloot`
  and `command_post.pages.ghost.level_min` are read into the page's own block the first
  time it is applied, so a rule somebody was already running under is not lost.

## 6d. Why the presses take nothing: the client does not know the tile (#2010)

The order was switched on with the operator's go-ahead and given a live event day.
It pressed, and the counter did not move — twice on hour-old targets and once on
targets a map lap had stamped two minutes earlier, so **staleness is not the
reason**:

```
TAP Rob a ghost-recon squad xall -> 5 press(es)
READ_LUA taken = 0
READ_LUA left  = 5          ← the event's own five, none of them spent
```

`actions/read_ghost_steal_gate.md` was written to answer the one question the logs
cannot — the send is fire-and-forget, so a robbery the server refuses reads exactly
like one it accepted until `stealTimes` fails to move. It takes the game's own gate
apart for one uuid. Three targets the order had just pressed at, on three separate
runs:

```
ghost_gate found=0 left=5 range_size=144
```

**`found=0` is the whole answer.** The uuid is not in the client's own ghost lists —
neither `taskList` nor `allianceTaskList` — because those hold MY squads and MY
alliance's, and every target the order chooses comes off a map sweep, which is the
only place another alliance's squads are ever seen. `dispatchStealRange` holds 144
warzones, so reach was never the problem, and the budget was never touched.

So `ghost.recon.steal {uuid, ownerServer}` is not the whole robbery for a tile the
client has not loaded. The in-game press is a CLICK on the tile: the client fetches
that point first and the squad enters its knowledge, exactly as the secret-task
robbery has to resolve a coordinate through `world.get.detail.new` before
`hero.dispatch.steal` will land (docs/research/secret-task-steal.md).

**What that makes the next step:** fetch the tile's detail for the chosen uuid, wait
for the client to hold it, then press — and only count a run as a robbery when
`stealTimes` moves. Until that is written, the ghost robbery stays 🟡 in the farming
list: it presses, and nothing is taken.

**And the two budgets are separate, which this run also measured.** On 2026-08-27,
with the ★ five long gone, the event's five were untouched all evening:

```
steal_left=0 steal_cap=5      ← secret tasks, spent
ghost_open=1 ghost_left=5 ghost_cap=5   ← ghost recon, in hand
```

Different manager, different counter, and neither watcher reads the other's
(`tests/test_panel_secret_tasks.py::test_the_two_robbery_budgets_are_never_the_same_number`).

## 6e. The press asks first, and spends nothing on a refusal (#2010)

§6d ended on a measurement — `found=0`, twenty presses, nothing taken — and the
operator's answer to it was one sentence: «Спрашивать у игры, а если можно обновить
состояние без смены сервера, то тоже делай.» Both halves are in the recipe now, and
both happen INSIDE the robbery. There is no new clock and no sweep: the panel does
not poll the server, it asks about the tile it is about to press and about nothing
else.

**Refreshing one tile, from where we stand.** `world.get.detail.new` takes the
tile's own `serverId`, so a squad on another warzone is asked about without a jump —
the same round trip the client fires when a finger taps that tile, and the same one
the secret-task robbery uses to resolve a coordinate before it sends. It is asked
per QUEUED target, and the queue is at most the day's remaining robberies; the list
itself stays current the way it has since #2010's first half, by the sniffer's
events.

**Then the game's own verdict, per target, at the moment of the press.** Two forms,
and the tile decides which:

| the target | judged by |
|---|---|
| a squad in the client's `taskList` | `GetPointStealType(...) == CanSteal`, plus «not mine», «looter list not full» and «`dispatchStealRange` covers its warzone» |
| a tile only a map lap has seen | the detail asked for a moment earlier: the point must have answered, and it must still carry that uuid |

Anything the game does not confirm is skipped **without a send**, with the reason on
the stream: `ghost_steal_skipped uuid=… why=no_detail|gone|mine|looted_out|out_of_range|state_N`.
The five a day are spent only on what the game called available, which is the whole
point — a press that goes out and is refused costs nothing on the counter but tells
the operator nothing either, and twenty of them is how this fault stayed invisible.

**And the only success is `stealTimes`.** Not a frame that left, not a reply without
an error, not the reward window closing: the counter is the account's own spent
count and only the server's reply moves it. The recipe still reads it before and
after and says `ghost_taken` on a difference.

Verified offline against a Lua stand-in of the manager, one case per refusal (no
detail, a detail about another task, out of range, looted out, my own squad, the
game's own «not yet») and one per send.
