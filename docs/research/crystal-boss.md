# «Кристальный босс» — the daily boss with three attacks, and how the client holds it

The game's own name: **Crystal Boss** in English, **«Кристальный босс»** in Russian, and
nine more in the locale files the panel ships. The CLIENT calls it the RED boss
everywhere in its own code — `DataCenter.CrystalBossDataManager`, `red.boss.*` on the
wire — and the crystal one everywhere a person can see it. Both names are the game's; the
panel uses the one the player reads.

Task #2077, and the person asked for it in one sentence: **«новая ежедневная атака на
кристалического босса, аналогична событию кодового имени, суть та же, 3 атаки»**. The
reverse-engineering agreed with them: it is
[«Кодовое имя»](codename-event.md) with a different manager, a different march type and
one difference that matters (below).

Everything here was read out of a live client through the panel's own Lua VM.

---

## The one difference from «Кодовое имя»

**Attempts here are RATIONED.** Its sister event pays for three attacks and allows an
unlimited number of them, so a fourth march there is still worth making for the damage
ranking. This event allows **three**, the server counts them, and a fourth march would
spend a squad for nothing.

So everything the panel draws and every gate the recipes hold is about what the day still
OWES, and the number comes from the server rather than from anything the panel counted:

| | «Кодовое имя» | «Кристальный босс» |
|---|---|---|
| the counter | `actBossTransTimes` — attacks MADE | `GetRemainAttackCount()` — attacks LEFT |
| the ration | none (`attackMaxNum` is −1) | `GetMaxAttackCount()`, three |
| a fourth attack | allowed, and worth making | refused |
| the march type | `DIRECT_ATTACK_ACT_BOSS` (33) | `DIRECT_ATTACK_RED_BOSS` (194) |
| across servers | `CROSS_…` (152) | `CROSS_DIRECT_ATTACK_RED_BOSS` (196) |

## The client answers «shut» until it is asked

The same trap, with a different manager, and it is the first thing every recipe here
does. The march state, the boss dictionary and the attack counter are **not there when
the client starts**: they arrive in the reply to `red.boss.get.march`, which the game
sends for itself when it opens the event's screen. Until something asks, `IsOpen()` and
its neighbours answer exactly as they would on a day the event were shut.

`RequestMarchData()` sends that one get and nothing else — measured live;
`RequestPanelData()` sends it plus the progress and the achievement gets, which this
feature never reads. The arrival is visible: `GetMarchState()` has an `activityId` once
the reply has landed, and `nil` before it.

**So the ask is part of the reading**, and every wait for it is BOUNDED: a client that is
not talking to the server has no reply to give, and running out of tries is itself an
answer — the reading then honestly says `open=0` with dashes beside it.

## Where the client keeps it: `DataCenter.CrystalBossDataManager`

| what | how | what it means |
|---|---|---|
| is it running | `IsOpen()` + `IsActivityTimeOpen()` + `IsBossAvailable()` | three different questions: the activity is switched on, the day's window is running, and there is a boss standing in it. All three, because «событие не идёт» and «нет босса» are drawn differently |
| attacks left | `GetRemainAttackCount()` | **the server's own number.** It counts an attack made from anywhere — this panel, the phone, or the person playing on the screen. The gate and the proof both |
| attacks the day pays for | `GetMaxAttackCount()` | three, read rather than written down |
| attacks made | — | DERIVED, `need - left`. The client keeps no counter of its own: `transInfo.attackTimes` belongs to the crystal TRANSPORT and read 0 on a day whose three attacks had all been made |
| may one be sent now | `CanAttackBoss()` | the client's own opinion |
| the boss | `GetCurrentBoss()` | `uuid`, `startPos` (a ready-made map index), `serverId`, `armyHealth` / `armyInitHealth` |
| how many are on the map | `GetBossDataCount()` | 0 with the event open means the list has not arrived yet, not that there is none |
| when the window ends | `GetAttackStageData().endTime` | **milliseconds** here, and the server clock is read in the same unit. Codename's stage speaks seconds; the two are not the same manager and neither number is guessed |

## The attack: ONE call, no window, no camera

A person walks five screens for this — the event window, its «Атака» (which sends
nothing, it only flies the camera to the boss), the boss on the map, «Атака» in its
popup, then the squad screen. All five end at one send, the same shape #1259 read off
the wire for the sister event:

```
MarchUtil.SendCreateMarchMessage(formation, DIRECT_ATTACK_RED_BOSS, point, uuid,
                                 timeIndex = 1, autoBackHome = 1, needSoldier = false,
                                 targetServerId = server, destroyTimeIndex = nil)
```

**The boss is addressed by its uuid**, so none of the walk is load-bearing: there is no
tile to wait for the client to stream in, and the server works the path out itself.
`CROSS_DIRECT_ATTACK_RED_BOSS` when the boss stands on another server, which the arm
step can tell because it parks the boss's own `serverId`.

The send is scheduled on the main thread through `TimerManager:DelayInvoke`: a send from
the hijack thread returns `true` and is dropped by the server
([[project_march_send_needs_main_thread]]).

«A free squad» is the first formation with `state == 0` that answers `IsFree()`. A squad
already marching, gathering, standing in a rally or wiped cannot be sent, and the game
only says so at the last press — which is why the boss, the squad and the count before
are all taken BEFORE anything is sent.

## The count is the SERVER's, and nothing pushes it

The same lesson as its sister event, and it is why the proof loop asks again on every
turn instead of merely re-reading: the client learns the new count from the reply to
`red.boss.get.march` and, as far as the polling goes, from nothing else. Measured on the
live run below, the server took **8 attacks' worth of asks** — about 13 s — to own up to
the first attack, and 5–7 asks for the two after it. The limit is twelve.

## Proven live

One run of `attack_crystal_boss_daily` on a day nobody had touched, from the panel's own
log, with the times as the panel wrote them:

```
07:02:06  cr_left = 3
07:02:08  armed = 1            <- boss + free squad
07:02:11  send
07:02:25  sent = 1             <- after 8 asks
07:02:27  cr_left = 2
…
07:03:08  cr_left = 0
          "The day's «Кристальный босс» attacks are made"
```

Three marches, 64 seconds, no window opened and the camera not moved. The reading taken
hours later on the same day, through the panel's web API:

```
open=1 left=0 need=3 made=3 can=0 hp=100 targets=1 until=67975
```

`can=0` beside `left=0` is the client agreeing with the server: the day is spent. The
run the evening before, on a day already played, ended the way it is meant to — «the
day's attacks are already made», a STOP and not a failure.

**A count that does not move can also mean the client is no longer talking to the
server**: a stranded client answers every getter with yesterday's numbers and returns
`true` from every send ([`server-link-status.md`](server-link-status.md)). The panel's
status strip is what says that, and it is worth a glance before believing a failure.

## The three endings, and why the clock reads them differently

* **the event is not running** — `STOP`, a deliberate SUCCESS. A failure would sit out
  the retry hold and try again every retry period until midnight over a state that cannot
  change until the next window;
* **the day's attacks are already made**, by whatever hand made them — `STOP`, the same;
* **the day still owes attacks and one could not be made** — `FAIL`. No squad standing in
  the base, the boss not in the list yet, the client no longer talking to the server.
  Every one of those mends itself within minutes — usually because the squad this errand
  itself just sent is on its way home — so `retry_sec` is 900 s and the next attempt
  re-asks the count and does only what is STILL owed, never the three again.

`interval_sec` is a day because a day's reward is the thing being spent and there is one
of it; `retry_sec` is what actually finishes a day, in two or three short goes.

## The chests: what the fight earns and nobody hands over (#2638)

The fight is not the whole of the event. It pays out along **two lists of its own**, and
the game names both itself out of its own tables:

| the list | the game's key | one chest per |
|---|---|---|
| «Weekly Damage Rewards» | `red_world_boss_title14` | a segment of the WEEK's damage record. Resets weekly (`red_world_boss_desc16`) |
| «Achievement Rewards» | `red_world_boss_title15` | an achievement finished in the event |

**Neither is handed over by winning.** They wait in the event's window until somebody
presses «Получить всё» (`red_world_boss_tab18`) — which is why the account this was
written on had **55 unclaimed chests** and a `claimedMax` of 108 while its three attacks
had been made by the panel every day for a week. The person put it in one sentence:
«после 3х атак, нужно проверять, есть ли бонусы, которые можно забрать».

### Where the counts are

| what | how | what it means |
|---|---|---|
| chests waiting, damage list | `GetClaimableCount()` | the week's segments earned and not taken. **55**, live |
| chests waiting, achievements | `GetAchievementClaimableCount()` | **0** on the same client |
| segments already taken | `GetProgressData().claimedMax` | the furthest segment claimed — the count, because they are claimed in order. **108**, and **163** a minute after the claim |
| the achievements themselves | `GetAchievementDisplayTasks()` | the list the event's screen draws. `state == 2` is «taken» |
| is a claim in flight | `IsAnyRewardClaiming()` | the claim is asynchronous; the counts move when the replies land |
| the red dot | `GetRed()` / `GetWeeklyRed()` / `GetAchievementRed()` | the client's own opinion, and it went `true` → `false` across the claim |

**The lists are not there until something asks**, exactly as the boss is not:
`RequestPanelData()` sends the progress get and the achievement get beside the march
one. The attack path deliberately sends only `RequestMarchData()`, so a reading that
wants the chests has to ask a second time.

### `ClaimAllRewards()` is a trap

The manager has a method of that name and it is the obvious thing to press. Measured on
a live client with 55 chests waiting, **it returned cleanly and claimed nothing at all**
— the count, the `claimedMax` and the red dot were all exactly as before:

```
P3BEFORE true:55
P3PRESS  true:nil                     <- ClaimAllRewards(), no error
P3AFTER  claimable=55 claimedMax=108 red=true
```

What claims is the pair behind it, on the same client, in the same minute:

```
P4B  ClaimAllProgress()=ok  ClaimAllAchievementRewards()=ok
P4C  claimable=0  claimedMax=163  red=false  claiming=false
```

So the press is those two calls, and the proof is the SERVER's own count going to zero —
never the send returning. `GetWeeklySegments()` answers an empty list throughout, before
and after: it is built by the event's own screen, and nothing here needs it.

## The DAY'S chest — the third one, and the one the two-list claim cannot see (#2702)

The event grew a third reward beside the two above, and the person reported it in one
sentence: «в событии кристалического босса появился новый сундук». It is a different
shape from both lists — **one chest a DAY, whose whole gate is «the day's attacks are
made»** — and the manager answers for it with a family of its own that nothing in #2638
touches:

| what | how | what it means |
|---|---|---|
| may it be claimed now | `CanClaimDailyReward()` | the CLIENT'S own verdict. This is what the press is gated on |
| the claim | `ClaimDailyReward()` | one call, and unlike «Получить всё» there is no trap behind it |
| the chest's own data | `GetDailyRewardData()` | `attackCount`, `target`, `claimed`, `claimPending`, `rewardId` |
| the red dot | `GetDailyRewardRed()` | the client's own opinion |

Read live on a client whose three attacks were in and whose chest was still in the
window:

```
can=true red=true claiming=false dataType=table
d.attackCount=3 d.target=3 d.claimed=false d.claimPending=false d.rewardId=<a reward id>
```

`target` is what the day asks for, `attackCount` is what the day has done and `claimed`
is whether the chest has been taken. **The panel does not rebuild «attackCount >= target
and not claimed» for itself** — `CanClaimDailyReward()` is asked instead, for the same
reason the attack counter is the server's: a count that said one thing to a board and
another to the button would be worse than no count.

**Claimable and claimed are not opposites, and both are drawn.** A day whose attacks are
not in yet is neither, and a card that inferred one from the other would call it
«забран» on a morning when nothing had been fought.

### Why the collect recipe had to be restructured, and not merely extended

The chest arrives with the SAME `RequestPanelData()` as the two lists, so nothing extra
has to be asked for it — but the recipe of #2638 **stopped the moment the two lists were
empty**:

```
IF cr_bonus < 1
    STOP "no chest is waiting"
```

That is exactly the state the day's chest lives in on an ordinary day: the week's
segments were claimed by the last run, the achievements are all taken, `bonus` is 0 —
and the day's chest is sitting in the window. The early return would have walked past it
every single day. So the claim now runs THREE gates in order, the day's chest first, and
the early «nothing to claim» is what is left over after all three have been offered.
`tests/test_panel_events.py` pins the ordering rather than merely the presence of the
press, because «the line is in the file» would have passed on the broken version too.

## Where it lives

| | |
|---|---|
| the reading | `src/lastwar_bot/actions/read_crystal_boss.md` — one round trip, one line of `key=value` |
| the attack | `src/lastwar_bot/actions/attack_crystal_boss.md` — one attack, one squad |
| the day's worth | `src/lastwar_bot/actions/attack_crystal_boss_daily.md` — as many as the day still owes, then the chests |
| the chests | `src/lastwar_bot/actions/collect_crystal_boss_rewards.md` — all THREE, each on its own gate, claimed when the game says so (#2702) |
| the clock | `panel/timers.py`, the errand `attack_crystal_boss_daily` — a day, retried in 15 min, off until somebody turns it on |
| the presses | `tools/lib/game_buttons.py`, `crystal_*` |
| the Lua | `tools/lib/lua_actions.py`, `crystal_*` |
| the card | `panel/tabs/events/` — «События», second card. **The phone only**: new work goes to the web while the window is being retired (`CLAUDE.md`, #1976) |
| the tests | `tests/test_panel_events.py` |

## What is not established

* **whether the boss changes with the weekday**, the way the sister event's does. One
  boss was seen, on one day; `GetBossDataCount()` answered 1 throughout.
* **what the window's borders are.** The live stage had 67 975 s left in the evening,
  which is longer than a day, so the stage is not a server day — but one reading is not a
  schedule and the panel does not draw one.
* **whether `hp` is worth anything to a person.** It read 100 hours after this account
  had spent all three of its attacks, which hints that the bar is community-sized rather
  than ours — but it was read once, and once is not a measurement. It is drawn because it
  costs nothing and it is the game's own number.
