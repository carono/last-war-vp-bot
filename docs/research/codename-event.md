# «Кодовое имя» — the world-boss event, and how the client holds it

The game's own name, out of the client's own tables: key `100086` — **Codename** in
English, **«Кодовое имя»** in Russian, and nine more in
[`docs/game-glossary.md`](../game-glossary.md). The panel may not call it anything else.

Task #1257, then #1259. Everything below was read out of a live client through the Lua
VM (`tools/lib/lua_client.py`).

**#1257 read it on a day the client SAID the event was shut, and the client was
wrong.** That mistake is the most useful thing in this file, so it is written up
before anything else — see «The client answers «shut» until it is asked», below. The
schedule and the four «windows» in the first version of this document came from
reading a manager that had never been filled in.

---

## The client answers «shut» until it is asked

`IsBossAvailable()` walks `self.stageTimeList` against the server clock. **That list is
not there when the client starts.** It arrives in the reply to `user.get.act.boss.march`
— the get the game sends for itself when it opens the event's own screen — and until
something asks, the list is `nil`, `GetActBossDataList()` is empty, and every reading
answers exactly as it would on a Sunday:

```
avail=false  actBossTransTimes=0  targets=0  stage=nostage      <- never asked
avail=true   actBossTransTimes=0  targets=1                     <- after one get
             stage start=…02:00Z end=…01:00Z (23 h)
```

Nothing distinguishes the two zeros from the client's side, which is why #1257 shipped a
reading that greyed the whole feature out on a running event and looked right doing it.
`RefreshTransTime()` does not rescue it either: it returns early when the stage list is
nil, so a client nobody asks stays empty for the entire session.

**So the ask is part of the reading.** `codename_fetch()` sends it,
`codename_loaded()` says when the reply has landed, and both
`read_codename_event.md` and the attack begin with them. The wait is bounded — on a
Sunday there is no stage to send, and running out of tries is the answer.

## What the event is

One boss stands on the world map, and which boss depends on the weekday
(`worldboss_rules_desc_new_87` / `_39` / `_64`):

| boss | days |
|---|---|
| «Кодовое имя 87» | Monday, Thursday |
| «Кодовое имя 64» | Tuesday, Friday |
| «Кодовое имя 39» | Wednesday, Saturday |

**It runs Monday to Saturday and it is open all day.** One stage covers the whole
server day — `IsAllDayFuncOpen` is true, `NewStartTime = 0`, `NewDurationTime = 23`, and
the live stage read back as 23 hours from the server's midnight. Sunday is the only day
there is nothing to attack.

The four times the client keeps in `bossRefreshTimeSvr` (00:00, 06:00, 12:00, 18:00
server; `bossRefreshTimeLocal` holds the same four converted for display) are when the
boss RESPAWNS during the day — **not four separate windows**. Reading them as windows is
what the first version of this document did, on a client whose stage list was empty.

Three things in that text decide the shape of everything the panel does with it:

1. **«Кол-во попыток в день не ограничено»** — attempts are NOT rationed. So the thing
   the day owes is a count being REACHED (three attacks earn the reward), never an
   allowance being spent. A panel drawing «осталось 2 из 5» would be inventing a limit
   the game does not have.
2. **«Только самый высокий урон, нанесённый за одну атаку, будет учитываться в
   ежедневном рейтинге»** — the biggest SINGLE hit is the score. That is why the second
   number the panel shows is the maximum and not a total.
3. **«Сбор для атаки невозможен»** — no rallies. Every attack is one squad of one's own,
   which is what makes «send the first free squad» a complete answer rather than a
   simplification.

A base of level 8 is needed to attack at all, and one hero class per boss does 50% extra
damage (tank for 87, aircraft for 39, missile for 64 — `456035` / `456036` / `456037`).
Neither is something the panel acts on.

---

## Where the client keeps it: `DataCenter.ActBossDataManager`

One manager holds the whole event. What it answers, live:

```
avail=false  maxDamage=12607399171  rewardMaxTimes=3  attackMaxNum=-1
bossId=2000001  activityId=80001  actBossTransTimes=0  targets=0
```

| what | how | what it means |
|---|---|---|
| is it running now | `IsBossAvailable()` | `GetAttackStageData()` against the server clock: a stage with a `startTime` and an `endTime`, and «now» inside it. The stage is the whole server day, so this is «is it not Sunday» — **and «has anything asked yet», which is the trap at the top of this file**. |
| attacks made | `actBossTransTimes` | The count the reward is paid against. **The server owns it**: `RefreshTransTime` sends `UserGetActBossMarch` and broadcasts `OnActBossAttackTimesRefresh`, so it counts an attack sent from anywhere — this panel, the phone, or the person playing. |
| attacks needed | `rewardMaxTimes` | Three, from `lw_worldboss_config` `k21`. Read rather than written down. |
| attempts left | `GetRestTransNum()` | `attackMaxNum - actBossTransTimes`, and `attackMaxNum` is **−1** — the unlimited attempts, in the client's own words. |
| biggest hit | `maxDamage` | The ranking's number. `GetMaxDamageShow()` is NOT this: it walks `damage_list_show` and answers the next display tier (32 000 000 000 against a real 12 607 399 171). |
| the bosses on the map | `GetActBossDataList()` | One entry per instance, carrying `uuid`, `monsterId`, `startPos`, `actStartTime` / `actEndTime` and the combat units. Empty outside a window. |
| when it ends | `GetAttackStageData().endTime` | Server seconds. `nil` when no window is open. |

`AchievementTaskData` is a different thing and worth not confusing with the count: it is
the *damage* ladder (`Нанести {1} урона {0} одной атакой` — `456064`), one rung per
threshold from 6 to 12 billion, each with its own rewards.

### How the method names were read

`string.dump` on the manager's own functions, the way
[[project_lua_string_dump_decompile]] describes — the client's Lua is not stripped, so a
function's constant table names everything it touches:

```
CanShowGoBtnReddot :: rewardMaxTimes | IsBossAvailable | actBossTransTimes
RefreshTransTime   :: actBossTransTimes | UserGetActBossMarch |
                      OnActBossAttackTimesRefresh
GetRestTransNum    :: attackMaxNum | math.max | actBossTransTimes
IsBossAvailable    :: GetAttackStageData | UITimeManager | GetServerTime |
                      startTime | endTime
```

`actBossTransTimes` reads like a teleport counter and is not one: those three constant
tables together are what identify it as the attack count.

---

## The attack

What a person does, in their own words: **open the event, go to the «Кодовое имя» tab,
press «Атака» there — which does not send anything, it FLIES THE CAMERA to the boss —
then click the boss on the map, «Атака» in its popup, pick a squad, march.** So the only
part that belongs to the event is the camera flight; from the popup onwards it is the
ordinary world-map target of [`world-monsters.md`](world-monsters.md) and
[`rally-create.md`](rally-create.md).

### What it actually takes: ONE call

The five screens all end at a single send, and #1259 read it off the wire while the
player made one attack by hand — then reproduced it byte for byte:

```
MARCH  <formation> , 33 , <boss point> , <boss uuid> , 1 , 1 , false , <server> , nil
SFS    world.march.formation.new , <formation> , 33 , <boss uuid> ,
       "<our point>;<boss point>" , 1 , true , <army table> , <server> , -1
```

i.e. `MarchUtil.SendCreateMarchMessage(formation, DIRECT_ATTACK_ACT_BOSS, point, uuid,
timeIndex = 1, autoBackHome = 1, needSoldier = false, targetServerId = server,
destroyTimeIndex = nil)`, scheduled on the main thread. **The boss is addressed by
uuid**, and the server works the path out itself — the `start;target` pair in the
message is built from the formation, not from anything the client had to have on screen.
So none of the walk is load-bearing: no camera flight, no tile to stream in, no popup,
no squad screen. `CROSS_DIRECT_ATTACK_ACT_BOSS` (152) for a boss on another server.

Proven live, three times over: the reading went `attacks=1 → 2` on the first headless
send, and the whole recipe run end to end took it `3 → 4`.

### The count is the SERVER's, and nothing pushes it

The first end-to-end run FAILED — «the squad was sent and the attack count did not
move» — over an attack that had gone out and was visible in the game. `actBossTransTimes`
had not changed in the client for the ten seconds the run polled it, and changed the
instant the next reading asked.

So the client learns the new count from the reply to `user.get.act.boss.march` and, as
far as ten seconds of watching goes, from nothing else. **A proof loop has to ASK on
every turn**, not merely re-read; the recipe does, and the server took eight seconds —
six asks — to own up to the attack, which is why the limit is twelve and not six.

### `maxDamage` is a record, not a counter

It did not move across four attacks, and that is correct: it is the biggest single hit
ever landed, so it only changes when a hit beats it. Useful to show, useless as proof
that an attack happened — the count is the proof. (Whether the daily ranking uses this
number or a per-day one the client keeps elsewhere is not established.)

### Two wrong turns worth not repeating

* **`CheckCanBattle` takes the squad's uuid as an ARGUMENT.** Called bare it reads a nil
  formation, decides the stamina check failed, and pops tip `300007`
  («STAMINA_IS_NOT_ENOUGH») over squads holding 116 stamina against a cost of 0. A wrong
  answer that names a real, plausible cause costs more than an error does.
* **Driving `UIFormationSelectListV2` by hand does not work and is not needed.** Setting
  `currentFormationUuid` and calling `OnCreateClick()` raises
  `UIFormationSelectListV2Ctrl.lua:873: attempt to compare number with nil` — the screen
  fills in state the caller cannot see. The send above skips the screen entirely.

«A free squad» is the first formation with `state == 0` and `IsFree()`. A squad already
marching, gathering, standing in a rally or wiped cannot be sent.

---

## Where it lives

| | |
|---|---|
| the reading | `src/lastwar_bot/actions/read_codename_event.md` — one round trip, one line of `key=value` |
| the attack | `src/lastwar_bot/actions/attack_codename_boss.md` — one attack, one squad |
| the presses | `tools/lib/game_buttons.py`, `codename_*` |
| the Lua | `tools/lib/lua_actions.py`, `codename_*` |
| the tab | `panel/tabs/events/` — «События», first group |
| the checklist block | `panel/tabs/checklist/`, the `codename` group |
| the tests | `tests/test_panel_events.py` |

---

## What is proven, and what is not

**Proven against a live client:** the reading, once it asks. On a running event, with the
stage list deliberately wiped first so the read had to earn its answer, the scenario
sends the get, waits for the reply and answers with `open=1` and the day's counts. The
same read without the get answers `open=0` on the same running event — that is the bug
#1259 fixed, and it is the reason the numbers in the first version of this file
described a shut event that was not shut.

**Proven against a live client: the attack.** Squads went out and the server's own count
moved for each — `1 → 2` on the first headless send, and `3 → 4` on a full run of
`attack_codename_boss.md` end to end. No window was opened and the camera was not moved
for any of them. The recipe's failure path was proven too, and by accident: it reported
«the count did not move» over an attack that had gone out, which is how the ask-on-every-
poll rule above was found.

**Not established:** whether the daily ranking reads `maxDamage` or some per-day number
kept elsewhere. `maxDamage` did not move across four attacks because none of them beat
the record — which is what a record does, and why it is drawn but never used as proof.

`docs/farming.md` marks «Кодовое имя» ✅.
