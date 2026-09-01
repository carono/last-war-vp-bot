# The alert tower — «Тренировка в запретной зоне» (#2084)

What the ability is, where every value comes from, and what was measured live on
2026-09-01. Every id, uuid and count below is INVENTED with the shape of the real one
(`CLAUDE.md`); only the field names, the types and the behaviour are from the account.

Delivered: `actions/read_alert_tower.md`, `actions/work_alert_tower.md`,
`panel/tabs/alert_tower.py`, the errand `work_alert_tower` with its three arguments.

---

## 1. What the player sees, and what it is called inside

The base building «Вышка оповещения» (`building 10216000`) opens a mini-game the client
calls **T11 Idle Game**: a squad marches into the forbidden zone along a strip of nodes,
opens chests, fights, and comes back. One march is **480 nodes at 30 s each = 4 hours**
(`lw_idle_game.node_num`, `node_interval`), it needs nobody watching it, and the zone
hands out TASKS while it walks.

Three managers, and only the middle one is ever needed:

| Module | What it is for |
|---|---|
| `T11IdleGameManager` | the CITY side: the entrance, the bubble, the guide, the boss-auto flag |
| `DataCenter.T11IdleGameDataManager` | the record: every send, every reading below |
| `T11IdleGameTemplateManager` | the config tables |

`T11IdleGameManager` is a class module, not a global — `package.loaded` holds it. Live:
`IsT11IdleGameFunctionOn() = true`, `IsShowCityAlertTowerEntrance() = true`,
`GetBossAutoIsOn() = true`.

## 2. The two sends that fill the record — and the one push behind them

```lua
DataCenter.T11IdleGameDataManager:SendGetIdleGameMainMessage()   -- the run's own state
DataCenter.T11IdleGameDataManager:SendIdleGameEventAllMessage()  -- every task
```

Before either of them `GetMainData()` and `GetIdleInfoData()` answer **nil**, measured on
a client that had not opened the tower this session. Afterwards the server keeps the
record up to date on its own — there is a `PushIdleGameEventsMessage` in the client, so
a task arriving is ANNOUNCED and nothing has to be polled for it. The recipes ask once,
on a press or a first look, and never on a clock (`CLAUDE.md`).

## 3. What the record holds

`GetMainData()` — `T11IdleGameMainData`:

```
bossId=104001  canReceiveEventNum=9  currentLevel=100005
lastChallengeTime=1780000000000  startGameLeftTime=1  surpriseBoxGainTime=0
```

`startGameLeftTime` is the daily allowance: `GetStartGameAddTimePerDay() = 1` is added a
day and `GetStartGameLeftTimeLimit() = 3` is the most that is stored.

`GetIdleInfoData()` — `T11IdleGameIdleInfoData`:

```
levelId=100005  passNode=480  startTime=<ms>  endTime=<ms>  nodeRecord=1;23|2;450|3;7
soldierId=3014  soldierNum=3123  challengePower=13000000  rewardPool={}  rewardNew={}
futureNodes={480={nodeId=11005 nodeIndex=480 triggerSeverTime=<ms>}}
```

`endTime - now` is how long the march still has; `now` is the game's own clock
(`UITimeManager.Instance:GetServerTime()`), never the machine's.

`GetGameEventList()` — one `T11IdleGameEventData` per task:

```
{eventId=100001, uuid=1400000000000000001, num=0, questId=9400120,
 rewardId=281300101, figure=30210, getTime=<ms>, status=1}
```

`status` is the client's own `TaskState`: **1 = not done, 2 = done and waiting to be
claimed, 3 = claimed** (`T11IdleGameIdleBattleConstant.TaskState`). A claimed task leaves
the list, which is how a claim is verified rather than assumed.

## 4. What a task asks for

`lw_idle_game_event[eventId]` — 94 rows, columns `event_type`, `quest_id`,
`battle_army`, `event_reward`, `event_character`, `share_id`, the plot ids and the
locale keys. `event_type` is `T11GameEventType`: `1` normal, `2` once-personal,
`3` once-alliance, `4` special.

The goal is in `quest[quest_id]`: `para1`/`para2` are the target and `para3`, when it is
there, is what has to be HANDED OVER — `itemId;count`, e.g. `900002;500`. Four rows of
the config name a squad instead (`battle_army = 910001…910004`, all `event_type = 2`):
those are fought, not paid.

## 5. The presses, and what each one was measured doing

All of them are methods of `DataCenter.T11IdleGameDataManager`, all headless — no window
opened, no marker tapped, no scene required:

| Call | Measured live |
|---|---|
| `SendIdleGameEventReceiveMessage(uuid)` | the task LEFT the list and the ready count fell by one; a run over ten of them claimed ten |
| `SendIdleGameEventGoods(uuid)` | on a task asking `900002;500`: the bag fell by exactly 500 and the task went `status=1 num=0` → `status=2 num=1` |
| `SendStartIdleGameMessage()` | a fresh `startTime`/`endTime` four hours apart, and `startGameLeftTime` 1 → 0 |
| `SendRewardReceiveMessage()` | the march's own loot; sent on a finished march, refused silently otherwise |
| `SendOpenSurpriseBoxMessage()` | only sent when `surpriseBoxGainTime > 0` |

**`SendIdleGameEventGoods` on a task WITHOUT a `para3` does nothing** — tried on a special
task (`event_type = 4`, `24/50`): the send went out, `status` and `num` did not move. So
the handover is gated on the config naming an item, and on the bag holding enough of it.

`num` is the SERVER's count and only moves when the server has taken the goods, which is
why the recipe pays once, waits, and asks again rather than sending a task's whole
requirement in one breath.

## 6. What is read and not pressed

* **The boss.** `SendChallengeBossMessage(bossId)` with `lw_idle_game_boss[bossId]` giving
  `boss_power`, `boss_cd`, `next_boss_id`. On the live account `GetBossAutoIsOn()` was
  already `true` and the boss's strength (`13025300`, invented) stood just under the
  squad's — so the challenge has never been seen answered by hand, and a press nobody has
  seen answered cannot be told from a refusal. Both numbers are READ and reported.
* **The battle tasks.** `SendIdleGameEventBattleMessage(uuid, armyId, heroInfo,
  chipEquipGroup)` — `armyId` is the config's own `battle_army`, not one of the player's
  four squads. None was on offer while this was written.
* **The alliance help.** `SendIdleGameEventGetMessage(playerUid, uuid, type)` with
  `IdleGameEventGetType = {OnlyGetPlayerList = 1, GetDataAndOpenHelpView = 2}` and
  `SendIdleGameEventHelpMessage(playerUid, uuid, eventId)` — helping somebody else's task,
  and `ShareToChat` / `CanShareAllianceHelp` beside them.

Each of the three is the next step, in that order.

## 7. The locale keys

`t11_idle_game_*` — `t11_idle_game_name`, `..._desc_<n>` for the stage names,
`..._normal_event_short_desc_<n>` / `..._long_desc_<n>` for a task's own words. The
tables shipped in the install tree are an OLDER build and do not have them
(`tools/game_locale.py` answers «no such key»); the running client resolves them, which
is where the Russian «запретная зона» in the name of this ability comes from.
