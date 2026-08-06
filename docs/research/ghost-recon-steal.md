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
