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

## Where it lives

| | |
|---|---|
| the reading | `src/lastwar_bot/actions/read_crystal_boss.md` — one round trip, one line of `key=value` |
| the attack | `src/lastwar_bot/actions/attack_crystal_boss.md` — one attack, one squad |
| the day's worth | `src/lastwar_bot/actions/attack_crystal_boss_daily.md` — as many as the day still owes |
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
