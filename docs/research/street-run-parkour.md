# «Уличный забег» / Street Run (Surfing endless runner)

Reconnaissance for task #1101 — a Subway-Surfers-style 3-lane endless runner event:
run as far as possible, dodge obstacles, limited attempts. Findings are **proven by
live inspection of the client** (server **935**, 2026-07-29); open items are called out.

> **Correction (2026-07-29).** Earlier sessions mapped this to *Ghost Parkour*
> (`LWGhostParkourDataManager`) — **wrong**. That manager reports `nil` even while the
> event is open. On the correct account the event is internally **Surfing**:
> `DataCenter.LWSurfingDataManager`, windows `UISurfingBattle*`, source
> `Assets/Main/LuaScripts/DataCenter/LWSurfing/LWSurfingDataManager.lua`. The two
> earlier blockers compounded: wrong account **and** wrong manager.

## TL;DR

- Display name **«Уличный забег»**; internally the **Surfing** minigame. Manager
  `DataCenter.LWSurfingDataManager` (method names say *Parkour*, e.g.
  `SendGetAllParkourInfosMessage`, `MsgDefines.ParkourFightStart` — the feature was
  renamed «surfing» in code but keeps parkour message names).
- **Event is OPEN** (live-proven). Fingerprint that pinned the manager: the panel shows
  best distance **8185** and **28** attempts → `LWSurfingDataManager` is the *only*
  manager whose `GetRemainTimes()==28` **and** `GetPersonalHightestScoreData()==8185`.
  `GetActId()==80063` = activity `id=80063, type=349` in `ActivityListDataManager`.
- Because the run is real-time, per-frame state must be read by **vision** (mss
  screenshot + image processing), not Lua — a SafeDoString round-trip is ~1 s, far too
  slow for a reflex loop. The manager holds only meta (records, attempts, timings).

## Three "parkour"-named things — do NOT confuse

| Feature | Manager / entry | What it is |
|---|---|---|
| **«Уличный забег» runner** ✅ target | `DataCenter.LWSurfingDataManager`, windows `UISurfingBattle*` | The Subway-Surfers 3-lane dodge runner (metres, obstacles, revives). |
| LW Parkour campaign | `ParkourManager`, `GoLWParkourBattle()` → `UIParkourMap` | A **squad auto-battle** stage campaign. NOT the target. |
| Ghost Parkour co-op | `LWGhostParkourDataManager`, `UIGhostParkour*` | Weekly co-op «Операция Призрак» / ghost-recon. Reports `nil` here. NOT the target. |

## `DataCenter.LWSurfingDataManager` API (dumped live, 92 methods)

State / meta (live values in parens):

- `GetActId` (=80063 — the activityId) · `SetActId`
- `GetRemainTimes` (=28 — «Попыток испытания») · `GetRound` (=4)
- `GetPersonalHightestScoreData` (=8185 — best distance, metres, a plain number)
- `GetTodayPersonalProgressScore` (=3282) · `GetTheBattleEndTime`
  (=1785722400000 ms; `endTime−now ≈ 5.006 d`, matches on-screen «5d»)
- `GetResurgenceLimit` (=3) · `GetResurgenceCost` (revive price, x100 coins)
- `GetCoinId`/`GetCoinNum` (parkour coins) · `GetParkourRankInfo`, `GetSurfingRankInfo`,
  `GetMvpPlayer`, `GetAllianceScore`, `GetSurfingBuffData`, buff/battlepass getters

Run control (send server requests — do NOT call idly, each `ReqFightStartCheck`
**consumes an attempt**):

- **`ReqFightStartCheck(restart)`** — the in-game «Начать» button. `string.dump`:
  checks `ActWinterStormManager:CheckInMatchingViewState`, the start-msg cooldown
  (`GetStartMsgCD`/`startMsgTs`; on cooldown → `UIUtil:ShowTipsId(avatar_tips002)`),
  then `SFSNetwork:SendMessage(MsgDefines.ParkourFightStartCheck, restart, curTs)`.
  Server-approved flow → `OnStartGame` → the runner scene loads. **Proven live:**
  `ReqFightStartCheck(false)` started a real run (attempts 28→27).
- `ReqStartGame(restart)` — raw `SFSNetwork:SendMessage(MsgDefines.ParkourFightStart,…)`,
  skips the checks. `restart=false` = fresh run.
- `ReqRebirthGame` / `ReqRebirthInfo` — revive on the death popup (3 available, x100 coins).
- `ReqEndGame`, `ReqEndStage`, `ReqMonsterCheck`, `ReqTimeCheck`, `FightStartCheck`.
- **`GoBackToActivityPanel()`** — dismisses the «Испытание окончено» result popup and
  returns to the event panel. **Proven live** — required between runs (the popup blocks
  a fresh `ReqFightStartCheck`).

Network fetch (populate the manager): **`SendGetAllParkourInfosMessage`**,
`SendGetParkourAllianceBattlePassInfoMessage`. Rank refresh:
`UpdateSurfingBattleRankInfo`, `UpdateAllianceBattleList`.

## Confirmed mechanics (live frames — `results/street_run/frames/live_*.png`)

- **3-lane endless runner**, third-person behind-the-back. The avatar auto-runs
  forward and starts in the **centre** lane (screen x ≈ 0.49·W, y ≈ 0.63·H).
- **Obstacles**: cars, container trucks, side barriers/blocks, streetlamps — occupy
  specific lanes; dodge by switching lanes (jump/slide likely exist — unconfirmed).
- **Coins** float along a lane (collectible; top-right counter).
- **Score = distance in metres** (top-left «NNм» + running icon). Best so far 8185.
- **Uncontrolled the run dies at ~88 m** (first obstacle) in <3 s — deterministic;
  useful as a control-signal baseline.
- **Death popup** «Испытание окончено»: result metres, parkour coins earned, buttons
  **«Выйти»** and **«Воскрешение ×100»**, «Оставшиеся воскрешения: 3/3». Dismiss via
  `GoBackToActivityPanel()` (or click «Выйти»). A **«Пауза»** button sits bottom-left
  during the run.

## Vision reflex loop — approach & open items

1. **Capture** the road ROI with `mss` in a tight **in-memory** loop (no per-frame PNG
   save — the calibration capture ran ~4 fps only because it wrote a PNG each frame;
   in-memory grab+detect should hit <30 ms, fast enough).
2. **Detect** the avatar's current lane and the nearest obstacle's lane from a fixed
   band ahead of the avatar. Lane x-boundaries to calibrate from `live_*.png`.
3. **React** with `pydirectinput` (foreground input; PostMessage ignored — see memory
   `project_input_model`). **Input model UNCONFIRMED** — Left/Right = change lane and
   Up/Down = jump/slide is the genre default, but the exact keys must be tested live
   (or read off the user playing).

## Input model (confirmed by the user)

Keyboard arrows via `pydirectinput` (foreground): **← / →** switch lane, **↑** jump,
**↓** slide. v1 of the bot uses lane-switch only.

## Auto-play — how `detect()`/`decide()` work (v1)

- **Player lane**: blue-helmet centroid in the bottom-centre ROI → x-threshold to
  lane 0/1/2. Avatar sits at x≈0.499 (centre) by default. Reliable.
- **Obstacles**: sampled in a danger band ahead (`_BAND_DEPTHS` 0.34/0.40/0.47) at
  three perspective-converged lane centres. A fixed colour threshold FAILS (the
  cartoon palette swings scene to scene), so the mask is **adaptive**: reference =
  the clear road patch just in front of the avatar; an obstacle pixel is markedly
  darker (`V < road_V−45`) or more saturated (`S > road_S+70`) than that, with bright
  gold coins (`V>175, hue 12–45`) carved back out. Lane blocked if the band fraction
  exceeds `_OBST_THRESH`.
- **decide()**: if the player's lane is blocked, step to a clear neighbour (prefer
  centre); if boxed in, jump. No jump/slide obstacle classification yet.
- **Loop**: in-memory grab+detect at **~16 fps** (61 ms; the PNG-saving path was ~4).
  A 0.28 s cooldown after each key stops lane-change overshoot. Death = the big
  near-white «Испытание окончено» card centre-screen.

## Status vs. the task

- ✅ **Manager identified & proven** — `LWSurfingDataManager`; probe reports OPEN.
- ✅ **Launch/loop proven live** — `ReqFightStartCheck(false)` starts a run;
  `GoBackToActivityPanel()` clears the popup between runs; `run` chains attempts,
  logs, screenshots each result, and keeps a reserve.
- 🟡 **Auto-dodge works but is weak.** Live autonomous batch (10 attempts, server
  935, 2026-07-29): distances **89, 317, 439, 132, 89, 132, 89, 316, 419, 132 m**
  — best **439 m**, median ~132 m, vs the **~88 m** no-control baseline. So the bot
  genuinely dodges (3–5× baseline on good runs) but is nowhere near the human record
  (8185 m). To improve: jump/slide obstacle classification, a per-lane outlier
  detector for reliability at distance, and a faster capture. Attempts left for the
  user (reserve honoured).

`tools/street_run_bot.py`: `probe` (state), `shot`, `watch` (durable poll + sentinel),
`calibrate` (start a run + grab frames), `record` (capture-only for user play),
`run [reserve]` (the reflex loop; keeps `reserve` attempts, default 5).
