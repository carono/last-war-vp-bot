# «Уличный забег» / Street Run (Ghost Parkour endless runner)

Reconnaissance for task #1101 — a Subway-Surfers-style endless runner event, arrow
controlled, run as far as possible, limited attempts. Findings below are **proven
by live inspection of the client**; what is still open is called out per section.

## TL;DR

- The event display name is **«Уличный забег»** (`activity_parkour_name`). Internally
  it is the **Ghost Parkour endless runner** — window family `UIGhostParkour*`,
  data manager `DataCenter.LWGhostParkourDataManager`, locale keys `parkour_*` /
  `ghost_parkour_*`.
- **The event was NOT active at recon time** (2026-07-29). The manager reports
  `activityId=nil, beginTime=0, roundEndTime=nil, remainTimes=nil,
  endlessSwitch=false, personalHighest=0`. Opening its rank hub shows «Нет данных»;
  opening the battle window `UIGhostParkourBattleMain` just hides the HUD and renders
  nothing (no server session). **A run cannot be started until the event opens.**
- Because the runner is real-time, per-frame state must be read by **vision**
  (screenshot + image processing), not by Lua — a SafeDoString round-trip is ~1 s,
  far too slow for a reflex loop. The manager holds only meta (records, attempts,
  timings), not live lane/obstacle positions.

## Do NOT confuse with the other "parkour"

There are **two** unrelated features both called *parkour* internally:

| Feature | Entry | What it is |
|---|---|---|
| **LW Parkour campaign** | `GoToUtil.GoLWParkourBattle()` → `UIParkourMap` | A **squad auto-battle** stage campaign («Этап 1 / Очистите квартал», gates `+1`, boss, `UIParkourFormation` "В бой!"). **NOT the task target.** Windows `UIParkour*`, manager `ParkourManager` (`curStageId`). |
| **«Уличный забег» endless runner** | `LWGhostParkourDataManager` / activity panel | The Subway-Surfers dodge runner (meters, obstacles, resurrections, ranking). **Task target.** Windows `UIGhostParkour*`, manager `LWGhostParkourDataManager`. |

## Confirmed mechanics (from RU locale `parkour_*`)

- Score is **distance in metres** (`parkour_meters_show = {0}м`,
  `parkour_settlement_score = Итоговый результат: {0} м`). A "round" variant scores
  in **Parkour Coins** (`..._round` keys).
- **Obstacles spawn randomly** and must be dodged
  (`activity_torch_relay_help_desc_2_new`: «случайным образом будут появляться
  препятствия, которые необходимо…»).
- On death you may **resurrect** a limited number of times
  (`parkour_failed_start_btn = Воскрешение`,
  `parkour_failed_start_count = Оставшиеся воскрешения: {0}/{1}`) before the run ends
  (`parkour_failed_title = Испытание окончено`).
- There is an **Endless** mode toggle (`ghost_parkour_endless_btn = Endless`,
  manager `GetEndlessModeSwitch`).
- Entry requires **base level ≥ 12** (`parkour_rule_desc`). Current account is L21 — OK.
- Attempts: `allChallengeTimes = 10` per round (task says "~30 попыток" → likely
  across multiple rounds/days). Track with `GetRemainTimes` / `GetRemainChallengeTimes`.

## UI windows (`results/ui_window_names.txt`)

Gameplay & flow for the runner:
`UIGhostParkourBattleMain` (the run itself), `UIGhostParkourPause`,
`UIGhostParkourBattleResult`, `UIGhostParkourWaitLoading`,
`UIGhostParkourRankPanelView` (ranking hub), `UIGhostParkourRecordListView`,
`UIGhostParkourSettingView`, `UIGhostParkourChallengeResult`.

Open a window via the Lua UI manager:

```lua
UIManager:GetInstance():OpenWindow(UIWindowNames.UIGhostParkourRankPanelView)
```

(Proven: this opened the ranking hub. `UIGhostParkourBattleMain` opened but was empty
because no event session exists.)

## `DataCenter.LWGhostParkourDataManager` API (dumped live)

Meta / state (all currently empty because the event is off):

- `GetActivityId` / `SetActivityId`
- `GetBeginTime`, `GetRoundEndTime`, `GetNextRoundTime`, `GetDelayTime` (=120000)
- `GetRemainTimes`, `GetRemainChallengeTimes`, `GetAllChallengeTimes` (=10)
- `GetEndlessModeSwitch`, `GetGhostParkourRound`
- `GetPersonalHightestScore`, `GetGhostParkourRecord`, `GetNewRecordList`
- `GetMainUIDisplayInfo`, `GetTier`, `GetTierMaxExp`, `GetGhostParkourTierList`

Run control (send server requests):

- **`ReqStartGame`** — start a run · `OnStartGame` · `FightStartCheck`
- `ReqEndGame`, `ReqEndStage`
- `ReqFightChallenge`, `ReqFightMatch`, `ReqSyncChallengeInfo`, `ReqTimeCheck`
- `GetStartMsgCD`, `GetNitrogenBuffId`

Network fetch (populate the manager once the event is live):

- `SendGetGhostParkourInfosMessage`, `SendGetGhostParkourTierInfoMessage`,
  `SendGhostParkourRankInfoMessage`, `GetGhostParkourInfos…` etc.

Network commands (`tools/known_commands.txt`): `get.parkour.activity.info`,
`get.parkour.alliance.battlepass`, `parkour.accept.invite`.

## Reading live state — approach

Per-frame Lua is too slow, so the run loop is **vision-based** (this is the standard
Subway-Surfers-bot approach and matches the confirmed-fast mss capture on this client):

1. **Capture** the road region with `mss` in a tight loop (no per-frame focus trick —
   the game must already be foreground). Full-window grab measured fine and NOT black
   on this client (the old "3D renders black" note does not apply here).
2. **Detect** the player's current lane and the nearest obstacle's lane from a fixed
   ROI band a little ahead of the character. Lane count and obstacle appearance must be
   **calibrated on the first live frames** (unknown until the event runs — likely 3
   lanes given the genre).
3. **React** with `pydirectinput` arrow keys (foreground input; PostMessage is ignored
   on this client — see memory `project_input_model`). Left/Right = change lane; Up =
   jump; Down = slide/roll (exact mapping to confirm live).

## Entry path & `activityId` (how to reach the run)

**Lua name of the event.** Display «Уличный забег» = locale key `activity_parkour_name`.
Internally it is the *Ghost Parkour* runner: manager `DataCenter.LWGhostParkourDataManager`,
windows `UIGhostParkour*`, locale `parkour_*` / `ghost_parkour_*`.

**`activityId`.** A server-assigned integer identifying the currently-running round of
the event. It is `SetActivityId`/`GetActivityId` on the manager and is **`nil` while the
event is closed** (recon state). It is populated when the server pushes the parkour
activity info — trigger the fetch with
`LWGhostParkourDataManager:SendGetGhostParkourInfosMessage()` once the event is live.
The same activity also appears in `DataCenter.ActivityListDataManager.nowActivityList`
when open — the entry whose name resolves to `activity_parkour_name`; its `activityId`
matches. (At recon the 28 active activities did NOT include parkour — that is how we know
the event is off. To re-check: `street_run_bot.py probe`, or scan `nowActivityList` for the
parkour entry.)

**Entry path (player flow).** Not reachable from the «События» panel — its tabs are
Чёрный рынок / Вызов ЧР II / Поле боя в пустыне / **Соревнование на игровых автоматах**
(arcade) / Разыскиваемый Босс / Сообщество. The arcade («Соревнование на игровых
автоматах», `s6_minigame_battle`) is a carousel of *other* minigames — «Сбор сыворотки»
(a Tetris/block puzzle), «Полдень настал» (S5 western), «Рётэй», «Под руинами» — **none
is the runner**. `UIRaceEntrance` is the warzone «Командный центр», also unrelated. When
live, «Уличный забег» is a timed seasonal activity with its own panel → Start button →
`UIGhostParkourBattleMain`.

**Headless launch flow** (confirmed by `string.dump`):

```
LWGhostParkourDataManager:ReqStartGame(fightType, restart)   -- restart=false for a fresh run
  → SFSNetwork:SendMessage(MsgDefines.GhostParkourFightStart, {...})
  → server reply → OnStartGame(message)   -- reads message.remainTimes / stageId / uuid
  → LWBattleManager:Enter(PVEType.GhostParkour, levelId, RestartParam)  -- loads the runner scene
```

`fightType` is an enum (personal vs endless / stage type) — **confirm the value live**
(`GhostParkourPassType` = {Personal=3, Alliance=4} is the *pass* type, not fightType).
While the event is closed the request is silently dropped (no `OnStartGame`, no attempt
spent) — verified: `ReqStartGame(1,false)` did nothing. Directly
`OpenWindow(UIWindowNames.UIGhostParkourBattleMain)` while closed only hides the HUD.

## Launch / attempt-tracking plan (once the event is open)

1. Fetch info: call `SendGetGhostParkourInfosMessage()` then read `GetActivityId`,
   `GetRemainTimes`. If `activityId` is nil/`remainTimes` 0 → event closed / no attempts.
2. Start a run headless with `LWGhostParkourDataManager:ReqStartGame(...)` (arg shape
   to confirm from `string.dump` when live) **or** by pressing the activity-panel Start
   button, then wait for `UIGhostParkourBattleMain`.
3. Run the vision reflex loop until death; on the death popup press **Воскрешение**
   while resurrections remain, else close and read the result (`GetPersonalHightestScore`).
4. Loop until `GetRemainTimes` reaches 0.

## Status vs. the task

- ✅ Found the UI and the manager; mapped the launch/attempt/record API.
- ✅ Confirmed the state-reading strategy (vision; Lua only for meta/launch).
- ⛔ **Blocked on the event being inactive** — cannot observe the live runner, calibrate
  the detector, or run the ~30 attempts until «Уличный забег» is scheduled/open on the
  account. `tools/street_run_bot.py` is the ready harness (`probe`/`shot`/`watch` work
  now; `calibrate` + `run` need a live event); the perception layer is a calibration
  stub pending live frames.

### Exhaustively verified NOT accessible (session 2)

The user reported ~30 attempts available, but the event is not reachable from this
client. Confirmed closed five independent ways:

1. `LWGhostParkourDataManager` state all empty — `activityId=nil, beginTime=0,
   remainTimes=nil, endlessSwitch=false, highest=0` — **even after** a forced
   `ActivityListDataManager:RequestActivityData()` resync + `SendGetGhostParkourInfosMessage()`.
2. Deep scan of `nowActivityList` (28) / `laterActivityList` / `overActivityList` —
   **zero** parkour references.
3. `ReqStartGame(1,false)` — silently dropped, no scene, no attempt spent.
4. Every «События» tab and the whole arcade carousel inspected — no runner.
5. `UIGhostParkourRankPanelView` = «Нет данных», `UIGhostParkourBattleMain` = empty HUD-hide.

Most likely: the event round is currently **closed / time-gated** (the user's "~30
attempts" is their remaining allowance from an open window, and it reopens on
schedule), **or** this automation drives a **different account** than the user plays
(the launch doc recommends a throwaway) where the event isn't active. Either way it
cannot be forced from here. Use `street_run_bot.py watch` to catch the next open
window, then `calibrate` + `run`.

Do not mark this ✅ in `docs/farming.md` until a run is proven live.
