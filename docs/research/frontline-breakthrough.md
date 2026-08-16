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

**209 stages played on two accounts, 130 of them cleared.** Every row below is that log,
not an impression; `lane` is what the recipe held for the whole stage, and «policy» rows
are the steering described under the table.

| Stage | what was held | runs | cleared | most soldiers left |
|---|---|---:|---:|---:|
| 20451 | **middle (36)** | 70 | **64** | **415** |
| 20451 | feed, lean middle (-2) | 9 | 8 | 306 |
| 20451 | feed, eager (-5) | 5 | 2 | 285 |
| 20451 | left (31.5) · avoid-heaviest (-1) · hold-middle-dodge (-3) | 3 | 0 | — |
| 20452 | **feed, lean middle (-2)** | 39 | **22** | **407** |
| 20452 | feed, eager (-5) | 20 | 5 | 438 |
| 20452 | any lane held flat (31.5 / 36 / 40.5) | 6 | 0 | — |
| 20453 | **right (40.5)** | 14 | **14** | 5 |
| 20453 | left (31.5) | 4 | 4 | 2 |
| 20453 | the policies (-2 / -5) | 9 | 3 | 3 |
| 20454 | **left (31.5)** | 10 | **8** | 17 |
| 20454 | right (40.5) · the policies | 11 | 0 | — |
| 20455 | middle · left · right · (-2) · (-8) | 8 | **0** | — |

So four of the five stages fall, each to a different answer, and **stage 20455 has not
fallen to anything tried**. It always ends the same way: the squad peaks at 7–12 (29 in
the middle, the least bad of them) and is wiped inside ten seconds. What is missing there
is soldiers arriving, not a better dodge — and soldiers do not carry between stages
(every stage starts at its own `expect_num = 30`; a stage 2 that ended with 407 is
followed by a stage 3 that peaks at 22, exactly like one that ended with 4).

The steering policies score each lane over the units within 18 of the squad: a unit of
5 hp or less is worth +1 (it is what the squad grows on), 6–20 hp is worth nothing, and
anything heavier is worth −hp/10. `-2` adds a point to the middle lane and needs a 1.5
margin before it moves; `-5` neither leans nor waits; `-8` ignores lanes and aims at the
weighted middle of the weak units, stepping 4.5 aside when a heavy one shares that spot.
`-1` and `-3` avoid threat instead of chasing food, and both are worse than standing
still — **running away from the heavy lane loses stage 1 outright**, because the squad
grows on what walks into it.

**Stage 20455 is not a steering problem, and the telemetry says why.** The ring of the
last ten samples on a losing run reads `x36 n18 f0 h1968` for the whole run: eighteen
soldiers, **not one weak unit anywhere within eighteen of the squad** to grow on, and
about 1 900 hit points of heavy ones walking in. Every other stage hands the squad
something to eat in the first seconds; this one does not. So what it wants is a squad
that arrives already large — and soldiers do not carry between stages — or an account
whose units simply out-damage the wave.

**Settling in the middle first is worse, not better** (`-9`: hold the middle for 120
frames, then feed). One win in eight on stage 20452 against `-2`'s 22 in 39. The early
seconds are exactly when the squad needs to be where the weak units are.

**A cleared stage is worth at most sixty units** (`special_stage_tips_01`). Stage 1 alone
pays that full sixty in about forty seconds, while stage 3 leaves five soldiers standing
after a minute — so depth is worth having for the event's ranking and stage 1 is where
the units are.

**The runs are far more deterministic than they look.** Stage 20454 held in the left lane
ended with exactly 17 soldiers on every one of its eight clears; stage 20453 in the right
lane with 1 or 5. The variance that looked like luck early on was the policy changing
under the measurement, plus two client-side accidents worth knowing: a kicked client
(the account was played elsewhere) and a panel restart, both of which end a session
mid-`WHILE` with no error line in the log.

**The two clients do not run at the same speed, and it does not decide the run.** The
same cleared stage 20451 is 570–650 frames of `OnUpdate` on the profile whose client sits
in a disconnected Windows session and 4 000–5 900 on the one with a desktop — ten frames
a second against sixty. Both clear it, with the same order of soldiers (285 and 351), so
a slow client is not a reason to distrust a measurement here and the frame count is a
fine clock for «how long did that stage last».

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
* **A per-frame hook must never be the thing that raises.** One unprotected
  `team:GetPosition()` inside the `OnUpdate` wrapper froze the client mid-battle: the Lua
  daemon went `busy` for seventeen minutes, every `READ_LUA` queued behind it, and the
  session sat at `WAIT 3` with no error line in any log. The tell is `daemon.busy` staying
  true in `/api/state` while the run's `secs` climbs. Recovery is a client restart
  (`POST /api/game {"action":"restart"}`), and the cure is `pcall` around everything the
  hook does per frame.
* A session dies silently when the panel restarts under it — another agent pressing
  «⟳ Перезапустить панель» is enough — so anything meant to grind for hours needs
  something outside the panel to notice and press play again.
