# «Прорыв обороны» / Frontline Breakthrough — the Sunday minigame

Reconnaissance and live measurements for task #1466, taken on 2026‑08‑16 against two
live accounts. Everything below was read out of the running client's Lua VM through the
panel's web API; nothing here comes from a capture or from guessing at pixels.

## What it is

A one-day event — it opened at `startTime` and closes at `endTime`, ten minutes before
the game‑day rolls over, and `limitTime` on its row says 24 hours. **Attempts are not
limited.** The player's own name for it is «Прорыв обороны»; the game's English is
**Frontline Breakthrough** (`special_stage_name`), and internally it is
`ActFrontBreakSunday`, activity **2400001**, `type=312`.

Five stages, played as a **chain**: `20451 → 20452 → 20453 → 20454 → 20455`. Clearing
one offers the next; losing one — or leaving the chain alone for a few minutes — puts
the next entry back at **20451**. The client publishes the top-rank criteria itself:

    topRankCriteriaStage        = 5
    topRankCriteriaRemainSolder = 2000

so «пять уровней подряд и максимум солдат» is the event's own scoring, not an
interpretation of it.

What a stage is worth is written in the game's own tips (`special_stage_tips_01`):
the units still standing when a stage is cleared are converted into the account's
highest-level units, **up to 60 per stage**.

## Where it lives in the client

| Thing | Where |
|---|---|
| Manager | `DataCenter.ActFrontBreakSundayDataManager` (`dataDict[2400001]`) |
| Its data class | `DataCenter.ActFrontBreakSundayManger.ActFrontBreakSundayData` |
| Stage ids | `d.stageIds` = `{20451,…,20455}`; the one to play next is `d.nextStageId` |
| Progress | `d.info.extra` — `curStage`, `state`, `maxS` (best stage), `maxL` (best soldiers in one stage), `totalL` |
| Stage rows | `LocalController.instance():getLine('lw_stage_feature', <id>)` — `expect_num=30`, `max_soldier≈1800`, `birth_point=36|7`, `boss_line`, `farm_monster` |
| Enter | `M:RequestToEnterStage(stageId)` → `activity.plane.feature.start` |
| Result | sent by the client itself → `activity.plane.feature.save`; the reply carries `curLeft`, `totalLeft`, the new ranks and **the next stage id** |
| Result windows | `UIBattleResultFrontBreakSundayVictory` / `…Defeat` |
| The battle | `DataCenter.LWBattleManager` — `PVEType.Parkour`, `param.fromActFrontBreakSunday=true`, `param.cheatCheck=true` |
| Leaving it | `DataCenter.LWBattleManager:Exit()` |

The wire names all sit under `activity.plane.feature.*`
(`MsgDefines.FrontBreakSundayStartChallenge` / `…GetChallengeResult` /
`…SaveSoliderReward` / `…GetRankInfo`).

## How a stage actually plays

* The squad is **fixed** at the stage's birth point (`x=36, z=7`) and the world comes to
  it. Monsters arrive down **three lanes**, `x ≈ 31.5 / 36 / 40.5`.
* The **only** control is the lane: `logic.team:MoveHorizontalTo(x)`, clamped to
  `[31, 41]` (`logic:GetMinMaxMoveX()`). Calling it from Lua works — proven live, the
  squad walked 36 → 31.5 within a second, `speedX = 40`.
* `logic.auto` is `true`: the game plays the run by itself and never leaves the middle.
* Soldiers are `team.teamUnitCount + team.overflowUnitCount`. **`GetMemberCount()` is
  not the number** — it stops at the formation size (124) while the overflow keeps
  counting, so a run that reads «124» may really be holding 370.
* Per-frame telemetry is easy: replace `logic.OnUpdate` on the instance and call the old
  one — that is where the steering and the sampling in
  `actions/frontline_breakthrough_stage.md` live.

A trace of stage 20451 (one sample per 20 frames, `dz` relative to the squad):

    20|36.0,7.0|2+0|1000021@32,+14/1  1000021@41,+14/1
    140|36.0,7.0|8+0|1000159@36,+7/100
    240|36.0,7.0|24+0|1000024@41,+4/0  1000027@32,+7/0
    300|36.0,7.0|28+0|99201001@35,+2/19  99201002@35,+3/16
    460|36.0,7.0|2+0|99201004@35,+0/4  1000029@41,-1/91  1000035@36,-1/126

— the squad grows while the trash (`hp` 1–3) comes, and the run ends when the heavy
units (`hp` 90–126) arrive.

## What was measured

Two accounts, one lane held for the whole stage, soldiers standing at the end:

| Stage | lane 31.5 | lane 36 (spawn) | lane 40.5 | adaptive «avoid the heaviest lane» |
|---|---|---|---|---|
| 20451 | wiped, peak 24 | **cleared: 297 / 324 / 332 / 333 / 339 / 349 / 377** (and 78 once) | — | wiped, peak 23 |
| 20452 | wiped, peak 16 | wiped, peak 13 / 23 | wiped, peak 10 | — |

Two things follow, and both were surprises:

1. **Holding the middle is not a no-op — it is the best of the three.** Both other lanes
   wipe stage 1 outright.
2. **Running away from the heavy lane is worse than standing still.** The «avoid the
   highest total HP within 18 units ahead» policy died at peak 23 where standing in the
   middle clears with 300+. The squad grows by killing what walks into it, so a policy
   that dodges everything starves.

Stage 20452 wipes the squad within 6–10 seconds in every lane tried. The human player
on the account with the best record never cleared it either (`maxS` = 20452 means the
chain reached it, not that it was beaten), so this is a wall of stage power rather than
a steering problem.

## Traps that cost time here

* **`{name}` in a sub-recipe is filled in at CALL time, not at LOG time.** A
  `READ_LUA` chunk in `frontline_breakthrough_stage.md` written with `{lane}` reaches
  the game as the literal four characters, and the run silently stops steering; a `LOG`
  line written with `{fb_left}` in the same file prints the PREVIOUS call's number. Park
  values in the VM (`_G.__fb_lanes`) and log from the file that has the `ARGS`.
* **A stage entered while the client still sits in the finished battle is refused,
  silently.** Exit first (`LWBattleManager:Exit()`), wait for the logic to go away, then
  request.
* **The next stage id arrives with the result, a second or two after the battle ends.**
  Enter on the id the client still holds and it replays the stage just cleared.
* **`IsBattleFinish()` goes true before the result window opens.** Read the verdict by
  polling for either window *or* for `nextStageId` to move — a run that reads the window
  immediately calls a win «unknown».
* A client that has been kicked answers every read plausibly and sends nothing: a stage
  that ends with soldiers standing and no verdict at all is that, not a loss.
