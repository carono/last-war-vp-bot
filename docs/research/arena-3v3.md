# The 3v3 arena — «Испытание», the line-up and the day's five wins (#2081)

Read off a live client on 2026-09-01 and proven live: a run fought until the server's own
win count reached five, spending one challenge per battle whether it was won or lost.

**The first version of this file got the win count wrong and the errand stopped two wins
short (#2081).** It counted today's rows in the battle log, and the log holds the battles
somebody else started too — see §4, which is the correction.

The arena building's «Испытание» matches an opponent, puts the account's three arena
squads against theirs and settles the fight on the server. The day allows **30
challenges** and the reward the person is playing for is **five wins**.

«Арена Шторма» is the event that replaces this one when it ends, and this file used to
name it `gale.arena.*`. **That was wrong** — `gale.arena.*` is «Арена ветров», and the
storm arena is the `new.arena.*` family with a manager called `NewPeakArenaManager`
(#2602). It is a different manager and different rules either way, and nothing here
applies to it: `docs/research/storm-arena.md`.

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

**The server counts it, and the count rides on the reply to a battle:**

```
score.arena.battle  ->  win = true   winTimes = 4   battleTimes = 24   changeScore = 15
                        ownerNewScore = 1005  curRank = 388  time = <server seconds>
```

`winTimes` is the day's arena wins — the five the reward is paid on — and `battleTimes`
is the challenges left after this one. Both are also written onto
`DataCenter.LW3V3ArenaManager`, but only by a battle: measured on 2026-09-01, the field
was on the manager one minute and gone the next, so a client that has not fought does not
know the number.

**Nothing else will tell it.** `score.arena.info` sent bare gets NO reply at all —
measured by poking sentinels into `battleTimes` and `startTime`, sending the ask and
finding both sentinels still there five seconds later. The free match ask
(`score.challenge.match`) carries only the two line-ups. So the count is had by fighting,
or not at all.

### The battle log is NOT the win count

`score.arena.log.record` answers with `logs`, the last 50 battles, each with `time`
(server seconds), `win` (1/0) and the score it moved. It is one row per battle the account
was **in**, and being attacked puts a row there exactly as attacking does. A defence costs
no challenge and counts towards no reward, so the log runs ahead of both:

| the day, measured on 2026-09-01 | |
|---|---|
| rows in the log for today | 11 |
| rows won | 6 |
| challenges spent (`30 - battleTimes`) | 6 |
| **wins the server counts** (`winTimes`) | **4** |

Five of those eleven rows were battles other players started, two of which we won. The
errand read «six wins, the day is done» over a day that stood at four.

**Nothing in a row says which side started it** — the fields are `changeScore`,
`ownerNewScore`/`ownerOldScore`, `otherNewScore`/`otherOldScore`, `power`,
`formationPower`, `win`, `uid`, `time`, `oldRank`, `curRank`, `playerInfo` and
`battleArr`; the score chain runs continuously through attacks and defences alike, and
the manager keeps one list (`records[50]`), not two. So the log is good for exactly one
thing: a **ceiling**. A real win always leaves a row, so «fewer than five rows won today»
proves fewer than five wins, and that is what the errand uses to tell «wins are owed for
certain» from «ask the server».

The day's start is the GAME's, and its stamp is in MILLISECONDS:

```lua
local zero = UITimeManager:GetInstance():GetTomorrowZero() / 1000   -- MILLISECONDS
local dayStart = zero - 86400
```

## 5. What the bot does

* `actions/read_arena_3v3.md` — one line: `open`, `left`, `used`, `wins`, `logged`,
  `score`, `rank`, `until`. `wins` is the server's count and `logged` is the log's row
  count, which is a different number (§4). A dash is «the game would not answer», never a
  zero, and `wins=-` means «this client has not been told yet».
* `actions/arena_3v3_battles.md` — the errand. Fights until the SERVER's `winTimes`
  reaches five, the challenges run out, or the event closes; a lost battle is a spent
  challenge and not a win, so the loop goes round again. When the count is not known
  yet it uses the log's ceiling: below five, wins are owed for certain; at or above it,
  one battle is fought and its reply says how the day really stands. What the reply says
  is parked in the client's own VM under the day's zero, beside the wire ear, so the
  probing battle is paid at most once per client session. Stops (never fails) on a shut
  event, a spent day and wins already made; fails when two battles in a row could not be
  made at all. Its last line is the report: `fought N, won W, lost L, wins today X of 5,
  challenges left K`.

The panel plays it from «Таймеры» as `arena_3v3_battles`, off until switched on, and
from «Чеклист» as the «Арена» line's press.

## 6. What is not done

* **The line-up is not chosen by the bot.** `SwitchAtkTeam` and `score.arena.save` exist
  and would let a scenario re-order the three teams; nobody has asked for it, and a
  wrong order costs a battle out of thirty.
* **Revenge is not taken.** `score.arena.revenge` and the manager's `revengeList` are
  there; an ordinary match is what the day's wins need.
* **«Арена Шторма» is no longer untouched, and it was never `gale.arena.*`** — it is
  `new.arena.*`, it is running, and the bot fights it: `docs/research/storm-arena.md`.
  The two share one row on the board, because they share one building (#2602).

## The card on «Таймеры» (#2688)

`actions/read_arena.md` answers «which arena is the building running, and how do we stand
in it» in one line, and `panel/runtime/arena_live.py` keeps the last one with the moment
it landed. The 3v3 half of it is the same reading as `read_arena_3v3.md` narrowed to what
a card shows: the score and rank off the newest row of the battle log, the challenges
left, and the day's wins — which stay a DASH until a battle has answered (§4), because a
count the server has not sent is not zero.

The target the card compares those wins against is the errand's own `wins` argument and
not a number written into the reading: the server carries no such field, and the row on
«Таймеры» is where that knob lives.

## The likes (#2689)

`MsgDefines.Arena3V3Like` = `score.arena.praise`, and the client's own sender is
`LW3V3ArenaManager:SendLike`. What the day still allows is `remainPraise` — on the
manager when the manager has been told, otherwise on the reply to the rank ask, which is
kept by the `__lw_praise` ear. The ability itself is `actions/praise_arenas.md` and it
does both arenas at once; the whole of what is known, what is not, and why the send is
written to fail safely is `docs/research/storm-arena.md` §10.

`Get3V3ArenaRankList` is asked with a bare `0`. It came back with nothing when it was
tried with `0`, `1` and `2` on 2026-09-09 — on a client whose 3v3 event was SHUT, which
is the likeliest reason and is not proven; the recipe reads the count off whichever of
the two places has it and gives no like at all when neither does.
