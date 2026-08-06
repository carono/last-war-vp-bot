# «Кодовое имя» — the world-boss event, and how the client holds it

The game's own name, out of the client's own tables: key `100086` — **Codename** in
English, **«Кодовое имя»** in Russian, and nine more in
[`docs/game-glossary.md`](../game-glossary.md). The panel may not call it anything else.

Task #1257. Everything below was read out of a live client through the Lua VM
(`tools/lib/lua_client.py`), on a day when the event was **shut** — which is why the
reading is proven and the attack is not (see «What is unproven», last).

---

## What the event is

One boss stands on the world map for a few hours at a time. Which boss depends on the
weekday, and the client's own rules text (`worldboss_rules_desc_new_87` / `_39` / `_64`)
spells the whole thing out:

| boss | days | windows |
|---|---|---|
| «Кодовое имя 87» | Monday, Thursday | 00:00, 06:00, 12:00, 18:00 server time |
| «Кодовое имя 64» | Tuesday, Friday | the same four |
| «Кодовое имя 39» | Wednesday, Saturday | the same four |

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
| is it running now | `IsBossAvailable()` | `GetAttackStageData()` against the server clock: a stage with a `startTime` and an `endTime`, and «now» inside it. **Not «is today a boss day»** — the boss comes and goes four times a day, and outside a window there is nothing on the map. |
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

Same five steps as raising a rally, because it is the same popup and the same squad
screen ([`rally-create.md`](rally-create.md), proven live). Only the target and the march
type differ:

1. **find the boss** — `GetActBossDataList()`; the map index comes from the entry's
   `startPos` (`pointId = y * 1000 + x`, as everywhere else on the map);
2. **tap it** — `GoToUtil.OnClickWorldPoint(pointId, WorldPointType.WorldBoss, uuid)`,
   the arg-routed handler from [`world-monsters.md`](world-monsters.md) Finding 7. The
   server resolves the point and opens the populated `UIWorldPoint` popup — the same one
   `UI.UIWorldPoint.Component.WorldActBossDes` decorates for this event;
3. **press «Атаковать»** — `MarchUtil.OnClickStartMarch(kind, pointId, uuid)` with
   `kind = MarchTargetType.DIRECT_ATTACK_ACT_BOSS` (33), or
   `CROSS_DIRECT_ATTACK_ACT_BOSS` (152) when the boss is standing on another server.
   **The popup must still be on top**, exactly as for a rally;
4. **pick the squad** on `UIFormationSelectListV2`, and read the pick back;
5. **launch** with `Ctrl:OnCheckTime(formationUuid, nil)`, and confirm by the SERVER's
   count moving — `actBossTransTimes` going up by one. A press that returned cleanly
   proves nothing.

«A free squad» is the first formation with `state == 0` and `IsFree()`. A squad already
marching, gathering, standing in a rally or wiped cannot be sent, and the game only says
so at the last press — which is a camera flight and an open popup later.

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

**Proven against a live client:** the reading, end to end. The scenario runs and answers

```
open=0 attacks=0 need=3 left=3 maxdmg=12607399171 targets=0 until=-
```

which is exactly the state of a shut event — and the panel greys the block on it. Every
field, the manager behind it and the constant tables above were read from the running
game.

**Not proven:** the attack. No squad has gone out at this boss, because the event has not
been open since the work was done. What IS established is that each call it makes is one
the game itself makes — the popup and the squad screen are the ones a live rally walked,
the march type is the event's own, and the gate («the event is not running») was watched
refusing the run on the live client. What has never been watched is the middle: the boss
entry's `startPos` turning into a point index the tap resolves, and the popup's attack
button accepting `DIRECT_ATTACK_ACT_BOSS`. Both stay guesses of the right shape until a
window opens.

`docs/farming.md` therefore marks «Кодовое имя» 🟡 and not ✅.
