# «Арена Шторма» — the five battles and the day's box (#2602)

Read off a live client on 2026-09-07 and proven live: a run fought the day up to five
battles against the weakest opponent outside our own alliance and took every daily box
the count had reached.

The arena building runs ONE event at a time and swaps it when the old one ends. The 3v3
challenge («Испытание», `score.*`, five WINS out of thirty attempts) is
`docs/research/arena-3v3.md`; this file is the one that replaced it. **What the day's
reward is paid on here is the NUMBER OF BATTLES, not the wins** — the game's own ladder
asks for one, three and five of them — so a lost battle costs an attempt and still counts.

## 1. Which event is which, and how that was got wrong once

`docs/research/arena-3v3.md` said «Арена шторма» was `gale.arena.*`. **It is not**, and
the guess is worth recording because the names do not line up with the words a player
reads. The client's own tables answer it in one line each:

```
new_arena_name_1   en «Storm Arena»   ru «Арена Шторма»
gale_arena_name_1  en «Gale Arena»    ru «Арена ветров»
```

So «Арена Шторма» is the `new.arena.*` family and `DataCenter.NewPeakArenaManager` —
whose own name says «peak», which is a third thing again. **Never name one of these
events from a manager or a command string; ask the language table**
(`tools/game_locale.py --term "Storm Arena"`, and it needs the install's locale tree —
`LW_GAME_DIR` when the tool is run from somewhere the game is not).

There are six arena families on this client and all six answer to the word «arena»:
`arena.*` (the old single-squad one), `score.*` (3v3), `new.*` (the storm arena),
`gale.*` (Арена ветров), `activity.arena.*` / `activity.arena.v2.*` (the newbie ones) and
`user.arena.*`. Six managers, six sets of rules.

## 2. The wire

| name | command | what it is |
|---|---|---|
| `NewArenaRankList` | `new.arena.rank.list` | the ladder — and **the day's counters** |
| `NewArenaRefresh` | `new.arena.refresh` | **the five opponents on offer** |
| `NewArenaKofBattlePreviewMessage` | `new.arena.kof.battle.preview` | look at a match |
| `NewArenaKofBattleMessage` | `new.arena.kof.battle` | **the battle** |
| `NewArenaBattleMessage` | `new.arena.battle` | the battle of the OTHER phase (§5) |
| `NewArenaReward` | `new.arena.reward` | **take a daily box** |
| `NewArenaKofSaveMessage` / `NewArenaSaveMessage` | `new.arena.kof.save` / `new.arena.save` | save the line-up |
| `NewArenaLogRecord` | `new.arena.log.record` | the battle log |
| `NewArenaPraise` / `NewArenaPromote` | `new.arena.praise` / `.promote` | the likes, the promotion |

What the ones that matter put on the wire, read by handing each message class a recording
stand-in for its SFS object (the trick in `alliance-train.md`):

```
new.arena.refresh            PutInt isRefresh
new.arena.kof.battle         PutUtfString otherUid   PutSFSArray teamInfos
new.arena.kof.battle.preview PutUtfString otherUid
new.arena.battle             PutUtfString otherUid   PutSFSArray heroInfos   PutInt squadNo
new.arena.reward             PutInt target
new.arena.rank.list          — nothing at all
```

**`isRefresh = 0` asks for the list the server already holds and costs nothing; `1` is a
RE-ROLL and has a price ladder** — `refresh_price` came back `0|0|0|100|200` beside
`refreshCount`, so the first three of the day are free and the fourth costs 100 diamonds.
The recipe re-rolls only while the next one on that ladder is a zero.

## 3. The line-up is not ours to build — but the game will hand it over

`teamInfos` is an **SFSArray**, not a Lua table: passing the preview's own
`ownerInfo.formationArr` straight through fails inside the serializer with
`attempt to call a nil value (method 'Size')`. Hand-building one is the same dead end the
3v3 arena documented.

What works, and it is three lines:

```lua
local pv    = <the reply to new.arena.kof.battle.preview>
local cls   = require('DataCenter.LW3V3ArenaManager.ArenaArmyFormationInfo')
local teams = {}
for i = 1, 3 do local t = cls:New() t:ParseData(pv.ownerInfo.formationArr[i]) teams[#teams+1] = t end
local packed = DataCenter.LW3V3Manager:FormationToSFS(teams)      -- a real SFSArray
SFSNetwork.SendMessage(MsgDefines.NewArenaKofBattleMessage, otherUid, packed)
```

The SERVER names our own three teams in the preview (`ownerInfo.formationArr`, each with
`heros`, `soldiers`, `weapon`, `skillChipArr`, `chipEquipGroup`, `squadNo` and a power),
the arena's own formation class parses one of those rows back into an object, and the
client's own packer turns the three into the array the message wants. Nothing is invented
and the person's own line-up is what fights.

`LW3V3Manager:FormationToSFS` is reused only as a PACKER here — it is handed the teams
rather than reading its own, so the 3v3's `atkTeamsArena` being empty (its event is over)
does not matter.

## 4. The counters, and where they live

`DataCenter.NewPeakArenaManager.rankData`, which is the reply to `new.arena.rank.list`:

```
battleCount  = 1      battles made today — what the boxes are paid on
battleTimes  = 9      attempts still left today
curScore     = 1019   curRank = 110
dailyReward  = { {needCount = 1, rewarded = 0}, {needCount = 3, …}, {needCount = 5, …} }
startTime / endTime   the event's window, in server MILLISECONDS
```

Both counts also ride on every battle reply (`battleTimes`, and the reply's own
`battleList` — the NEXT five opponents, so a loop needs no refresh between rounds):

```
new.arena.kof.battle -> isWin = true  battleTimes = 9  changeScore = 14
                        ownerOldScore = 1000  ownerNewScore = 1019  oldRank = 460 curRank = 110
                        battleArr = {…}  battleList = {5 opponents}  typeKOF = 2
```

**`rankData` comes and goes.** It was full one minute and empty the next, so anything
that wants it asks for it (`actions/read_storm_arena.md`); a reading that must not ask —
the checklist board — reports a dash when the client has not been told, which is the
truth rather than a zero.

`m.info` is the same event's window from `arena.info`, and it survives longer; that is
what «is the arena building running anything» is read off (`actions/arena_battles.md`).

## 5. The phase — and why only one of the two is fought

`m:UseKofBattle()` says which battle the event is taking right now, and it is not a
formality: sending `new.arena.battle` while the KOF phase is on comes back

```
errorCode = E000000   errorMsg = "kof open"
```

and costs nothing. The KOF phase is the three-team one, and it is the one the recipe
fights. **The other phase is not implemented**: its message wants `heroInfos` and a
`squadNo` — a different shape, and no way to check a guess while the KOF phase is on.
`actions/storm_arena_battles.md` stops with that said rather than sending something it
cannot verify.

## 6. The opponent

`new.arena.refresh` answers with `battleList`, five rows:

```
{power = 105599603  formationPower = 105599603  formationSoldier = 3014  uid = …
 rank = 607  score = 985  playerInfo = {name, allianceId, allianceName, abbr, serverId,
                                        power, careerLevel, svipLevel, …}}
```

Two powers, and the difference decides the pick: the row's own `power` is the LINE-UP's
(it equals `formationPower`), while `playerInfo.power` is the whole base's and is more
than twice it. **The line-up's is the one that fights**, so «the weakest» is the row's
`power`.

«Not from our alliance» is `playerInfo.allianceId` against `LuaEntry.Player.allianceId` —
both are the game's own ids, so no alliance is named anywhere in the code. A list with
nobody else on it is re-rolled while re-rolls are free, and otherwise the run says so and
stops.

## 7. The day's box

`new.arena.reward` takes **the box's PLACE in the ladder — 1, 2 or 3 — and never the
number of battles it wants.** The two agree for the first box (one battle, first place)
and part company after it: measured on 2026-09-07, asking for `5` left the five-battle box
unclaimed and asking for `3` took it. The reply is `{target = …, reward = {…}}` and the
tier's own `rewarded` goes to 1, which is what the recipe checks rather than the fact that
a message left.

## 8. What the bot does

* `actions/read_storm_arena.md` — one line: `open`, `left`, `fought`, `need`, `chest`,
  `ready`, `score`, `rank`, `until`, `kof`. A dash is «the game would not answer».
* `actions/storm_arena_battles.md` — the errand. Fights until the day's five battles are
  in, the attempts run out or the event closes, then takes every box the count has
  reached. Stops (never fails) on a shut event, a spent day, a finished one and a phase
  it cannot fight; fails when two battles in a row could not be made at all.
* `actions/arena_battles.md` — the press behind the one «Арена» row: it asks the two
  managers' own windows which event the building is running and plays that one.
* `actions/read_arena.md` — the READING behind the card on «Таймеры» (#2688): the same
  «which of the two is running» question, and then that event's score, rank, day count
  and attempts in one line. `panel/runtime/arena_live.py` takes it when the client gets
  into the game and then at the event's own end or the day's reset — the arena has no
  push, so those two known moments are all there is, and there is no «Обновить».

The panel plays it from «Таймеры» as `arena_3v3_battles` (the row's name is kept so
nobody's schedule is thrown away) and from «Чеклист» as the «Арена» line's press.

### …and pointing the CATALOGUE at it was not enough (#2688)

The row's name was kept and its SCENARIO changed, and that is the half that did not
arrive. A profile's list is its own and outlives the built-ins (#2017): every row saved
before #2602 spells out `"scenario": "arena_3v3_battles"`, and `parse_catalogue` takes
what the row says over the catalogue's — rightly, for a scenario somebody chose. So on
every account that had ever run, the hourly errand went on playing the 3v3 recipe alone,
which reads its own window, finds it shut while the storm arena is the event in the
building, and ends there. Measured on the live panel, 2026-09-07 17:07:33::

    [timer] arena_3v3_battles:   READ_LUA arena_open = 0
    [timer] arena_3v3_battles:     LOG "the 3v3 arena is not running right now"
    [timer] arena_3v3_battles:     STOP -> halt requested (the event is shut)

…once an hour, all day, with `open=1 left=5` on the storm arena beside it. The cure is
`panel/timers.SUPERSEDED_SCENARIOS`: a saved row whose scenario is EXACTLY the one this
errand used to run is upgraded to the built-in's, and anything else the row says still
wins. Whatever changes an errand's scenario next has to go on that list, or it reaches
only accounts that have never run.

## 9. What is not done

* **The other phase** (§5) — `new.arena.battle` with `heroInfos` and a `squadNo`.
* **The line-up is not chosen by the bot.** `new.arena.kof.save` would let a scenario
  re-order the three teams; nobody has asked for it.
* **The promotion** (`new.arena.promote`) is untouched.
* **The likes are done** (#2689): `actions/praise_arenas.md`, §10.

## 10. The likes, and the diamonds they pay (#2689)

The person's words: «нужно лайкать 3 раза топового игрока в рейтинге, 3 раза там и 3 раза
там» — three likes a day on this arena and three on the 3v3 one, and the game pays
diamonds for them. A like costs NOTHING; the only thing it uses is the day's own count.

| where | the count | the send |
|---|---|---|
| storm arena | `NewPeakArenaManager.rankData.remainPraise` (and `HavePraiseNum()`) | `MsgDefines.NewArenaPraise` = `new.arena.praise`, `NewPeakArenaManager:SendNewArenaPraise` |
| 3v3 challenge | `LW3V3ArenaManager.remainPraise`, else the rank reply's own | `MsgDefines.Arena3V3Like` = `score.arena.praise`, `LW3V3ArenaManager:SendLike` |

**WHO is liked is the game's own answer**: the row at `rank = 1` of the ladder, which for
the storm arena rides on `new.arena.rank.list` (`rankData.players`, 807 rows when it was
read, each with `rank`, `uid`, `praise`) and for the 3v3 on its own rank reply, kept by an
ear of its own — `__lw_praise`, never the guarded `__lw_a3v3` / `__lw_storm` hooks, which
refuse a second wrapper silently.

**THE GATE IS `remainPraise` AND NOTHING ELSE.** A zero is an honest «the day's likes are
given», not a fault: measured on 2026-09-09 the account read zero because the person had
already given them by hand. A run that finds a zero sends nothing.

**WHAT IS NOT CONFIRMED YET, and how it is written to fail safely.** The ARGUMENT of the
send could not be measured the day this was written — the likes were spent, so no send
could be made and nothing could be read back from one. The recipe therefore calls the
CLIENT'S OWN sender first (`SendNewArenaPraise` / `SendLike` with the top row's `uid`),
falls back to the bare message with the same `uid`, names in the log which of the two
carried, and re-asks both ladders afterwards so what it reports is what MOVED. The first
live run after a day reset is what settles it.

## 11. A stale opponent list is not a refusal (#2689)

Measured live: after a battle the five opponents on the reply can already be one row
behind the server's, and the next round is answered

```
errorCode = E000000   errorMsg = "new_arena_tips_38 not in battleList"
```

The battle costs nothing, but two of those in a row used to end the run in an error and
throw the rest of the day's attempts away. `storm_arena_battles.md` now tells that
refusal apart from every other one: it asks for the list again with the free
`isRefresh = 0`, fights on, and counts the round as empty rather than as a strike — up to
three re-asks a run.
