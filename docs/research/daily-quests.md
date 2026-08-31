# Daily quests and the day's progress ladder (#2076)

What «Ежедневные задания» is, on the wire and in the client, and how the shapes below
were learnt without sending a single exploratory press.

## The manager

`DataCenter.DailyTaskManager` holds the whole screen:

| field / method | what it answers |
|---|---|
| `dailyQuestTasks` | the quest rows: `id`, `state`, `num` / `totalNum`, `totalTimes` |
| `dailyBoxActive` | the ladder's marks, by stage: `{1=40, 2=80, 3=120, 4=160, 5=200}` |
| `curReward` | the stages the client has data for — `{1=1, 2=2, 3=3}` on a day with three taken |
| `GetCurValue()` | the day's points so far (`150` on the measured day) |
| `GetDailyMaxValue()` / `GetDailyProgress()` | `200` and `0.65` — the bar's own two numbers |
| `GetBoxState(stage)` | one box's state, **by 1-based stage index** |
| `IsAllBoxRewardReceived()` | is the ladder finished |

**A quest row's `state` is the whole gate:**

    0 — not finished        1 — finished, NOT claimed        2 — claimed

Measured live 2026-08-31: two rows at `state = 1`, claimed, and both read back as `2`
in the same run — so the transition is `1 → 2` and «still `1` after the claim» is a
REFUSAL, which is what the recipe reports rather than counting its own presses.

`GetBoxState` answers `2` for a box already taken and **raises** for a stage the day has
not reached (`DailyTaskManager.lua:194: attempt to compare number with nil` — `curReward`
has no entry for it), so every reading is inside a `pcall` and «unreadable» is treated as
«not yet», never as «press it». A THRESHOLD passed instead of an index answers `0`:
`GetBoxState(40)` is not a question about the first box.

## What the two claims put on the wire

Learnt without sending anything, with the trick from `alliance-train.md`: build the
message with `NewEmpty`, give it an `sfsObj` whose `__index` returns a recording
function, and call its own `OnCreate` with marked arguments (`dev/_t2076_wire.md`).

| message | id | what it puts |
|---|---|---|
| `MsgDefines.DailyTaskReward` | `daily.task.reward` | `PutUtfString taskId` — ONE quest row, the id as a **string** |
| `MsgDefines.DailyQuestReward` | `daily.quest.reward` | `PutInt stage` — ONE ladder box, by its **1..5 index** |
| `MsgDefines.DailyQuestLs` | `daily.quest.ls` | nothing — «say the list again» |

Both take the value as the FIRST positional argument of `SendMessage`, not a table. The
guess this replaced would have been wrong in both directions — a numeric task id and a
threshold for the box — and neither failure would have raised: the send leaves and the
server simply does nothing, which is exactly the shape of #1854.

## The announcement

`push.daily.quest` (`MsgDefines.PushDailyQuest`) arrives whenever the day's progress
moves. That is what the `daily_quests` trigger listens to; there is nothing to poll for
and no clock is involved. It fires often — most of the time somebody is playing — so the
recipe's do-nothing path is one VM read and no wait at all, and only a run that actually
claimed something pays for the two `WAIT 2`s that let the answers land.

## The recipe

`src/lastwar_bot/actions/collect_daily_quests.md` — quests first (each row its own
message), then the ladder box by box, with a re-read after each half. Reachable from
«Чеклист» as well as from the listener, because a listener is «when the game says so»
and never «сделай сейчас».

Live, 2026-08-31: `finished 2, claim sent 2 [115 107]` → `claimed today 10, still
unclaimed 0, points 150`; the ladder read `1@40:2 2@80:2 3@120:2 4@160:nil 5@200:nil`
and correctly sent nothing at 150 points. A box actually being claimed has not been
watched yet — no stage was open on that day.
