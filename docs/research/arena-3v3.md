# The 3v3 arena — «Испытание», the line-up and the day's five wins (#2081)

Read off a live client on 2026-09-01 and proven live: four battles in one run took the
day's wins from 2 to 5 and the day's challenges from 29 to 25.

The arena building's «Испытание» matches an opponent, puts the account's three arena
squads against theirs and settles the fight on the server. The day allows **30
challenges** and the reward the person is playing for is **five wins**.

«Арена шторма» is the event that replaces this one when it ends — `gale.arena.*`, a
different manager and different rules. Nothing here applies to it.

## 1. The wire

Off `MsgDefines` on the live client. The 3v3 arena is the `score.*` family; the older
single-squad arena is `arena.*` and the seasonal ones are `new.*`, `gale.*` and
`activity.arena.*` — four different events with four different managers, which is the
trap this file exists to mark.

| name | command | what it is |
|---|---|---|
| `Get3V3ArenaInfo` | `score.arena.info` | the event: its window, the challenges left |
| `Get3V3ArenaMatchInfo` | `score.challenge.match` | **«Испытание»** — match an opponent |
| `Get3V3ArenaBattlePreivew` | `score.arena.battle.preview` | look at the match before fighting |
| `Arena3V3Battle` | `score.arena.battle` | **the battle itself** |
| `Save3V3ArenaFormation` | `score.arena.save` | save the three-team line-up |
| `Get3V3ArenaRecords` | `score.arena.log.record` | the battle log — what was fought today |
| `Get3V3ArenaRevengeMatch` | `score.arena.revenge` | re-match somebody who beat us |

What the two that matter put on the wire, read by handing the message class a recording
stand-in for its SFS object (the trick in `alliance-train.md`):

```
score.challenge.match     — nothing at all
score.arena.battle        PutUtfString otherUid   PutSFSArray teamInfos   PutInt isRevenge
```

## 2. `teamInfos` is not ours to build — the client's own manager packs it

**Sending `score.arena.battle` by hand does not work, in any spelling.** Measured: an
array of ints, an array of `{index, squadNo}`, and an array echoing the match reply's own
army units with their heroes all came back `errorCode E000000`, which is this client's
«the payload is not what I asked for». The array carries the three teams' full
composition, and the code that packs it is the client's own.

So the press is the client's, and that is the whole of the ability:

```lua
DataCenter.LW3V3Manager:SetType(1)                 -- 1 = arena (2 is the train event)
DataCenter.LW3V3Manager:SetOpponentData(match.otherInfo)
DataCenter.LW3V3Manager:StartBattle()              -- packs teamInfos, sends the battle
```

`LW3V3Manager` (**not** `LW3V3ArenaManager` — there are two, and only this one holds the
squads) keeps `atkTeamsArena`, the three teams the person edits on the arena screen, and
`FormationToSFS` is what puts them on the wire. The bot therefore fights with whatever
line-up stands there and never re-orders it.

No window is opened for any of this. **Do not open `UIWindowNames.UILWArena3V3Popup`
cold to find out more** — it killed the client outright on 2026-09-01, and everything in
this file was read without it.

## 3. Reading the state

`DataCenter.LW3V3ArenaManager` holds the event; the readings that matter:

```
startTime  endTime          the event window, in server milliseconds
battleTimes                 challenges the day still allows
GetChallengeRemainTimes()   -> (true, 25)  — the same number, and the one to use
CanChallange()              -> true
```

**The manager is EMPTY until something asks**, exactly like the codename event: send
`score.arena.info` first and read afterwards, or a running event answers like a shut one.

**Neither manager keeps the battle log or the match** — both replies are parsed by the
SCREENS, so a headless run has nowhere to read them from. One guarded hook on
`SFSNetwork.HandleMessage` keeping the last `score.challenge.match`,
`score.arena.battle` and `score.arena.log.record` is what the recipes use.

The match reply carries `ownerInfo` (us) and `otherInfo` (them), each with
`armyUnit1..3` and a `playerInfo`. The battle reply is the result:

```
win = false   winTimes = 0   battleTimes = 29   battleStateArr = {2, 1, 2}
changeScore = -15   ownerNewScore = 958   curRank = 470   time = <server seconds>
battleArr = {…}                                  -- the three sub-fights
```

`battleTimes` in the reply is the challenges LEFT after this one, which is why the loop
believes it rather than counting its own presses.

## 4. How many wins the day already has

`score.arena.log.record` comes back with `logs`, the last 50 battles, each with `time`
(server seconds), `win` (1/0) and the score it moved. Today's are the ones at or after
the day's start, and the day's start is the GAME's:

```lua
local zero = UITimeManager:GetInstance():GetTomorrowZero() / 1000   -- MILLISECONDS
local dayStart = zero - 86400
```

That is how a day the person played by hand costs no battles at all: the wins are read
out of the server's own log, not out of anything this panel wrote down.

## 5. What the bot does

* `actions/read_arena_3v3.md` — one line: `open`, `left`, `fights`, `wins`, `score`,
  `rank`, `until`. A dash is «the game would not answer», never a zero.
* `actions/arena_3v3_battles.md` — the errand. Reads the window, the challenges and
  today's wins, then fights until the wins are in, the challenges run out, or the event
  closes. Stops (never fails) on a shut event, a spent day and wins already made; fails
  when two battles in a row could not be made at all.

The panel plays it from «Таймеры» as `arena_3v3_battles`, off until switched on, and
from «Чеклист» as the «Арена» line's press.

## 6. What is not done

* **The line-up is not chosen by the bot.** `SwitchAtkTeam` and `score.arena.save` exist
  and would let a scenario re-order the three teams; nobody has asked for it, and a
  wrong order costs a battle out of thirty.
* **Revenge is not taken.** `score.arena.revenge` and the manager's `revengeList` are
  there; an ordinary match is what the day's wins need.
* **«Арена шторма» (`gale.arena.*`) is untouched** — a different event, and it is not
  running yet.
