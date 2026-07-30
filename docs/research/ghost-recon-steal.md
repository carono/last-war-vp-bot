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
--> ghost.recon.steal  {uuid: 1397117098857328280, ownerServer: 1006, _id}
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
* `dispatchStealRange[server]` — the set of servers the event lets you rob
  (live: 421–676 plus 8053–8084; the account's own server 509 is in it). This is
  the ghost-recon analogue of the secret task's "not in the same sector" refusal;
* `ownerId ~= my uid` — robbing my own squad is not a thing.

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
  `--queue-only`.
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
| `dispatchStealRange` covers the account's server | true (509) |
| a queued target while the event is closed | `steals_pending` 0, the press sends **nothing** |
| `actions/steal_ghost_recon.md` end to end | runs, 0 presses, no error |

**Not confirmed: an actual robbery.** `taskList` is empty outside the event, so no
real uuid was available and no `ghost.recon.steal` was sent from this code. The
feature therefore stays 🟡 in `docs/farming.md` until it is run on an event day —
what to do then is: `--list` to see the squads, `--all` to queue what the client
calls robbable, then the recipe (or `--all` without `--queue-only`).

Also open: which `cfgId` families are worth robbing (the capture shows `60302` —
family "6", the star, ур.5 by the `MM + 2` rule in §3a, `stealMaxtimes` 3), and
whether `leave.message` needs the window open — it is built from the reply's
`recordUuid` and has never been sent from here.
