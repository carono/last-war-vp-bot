# Profession skills ("навыки профессии")

How the profession's active skills are fired, derived from one labelled sniffer run
and pinned against the live Lua VM.

- Recipe: `actions/occupation_skills.md` — press every ready no-target skill.
- Buttons: `tools/lib/game_buttons.py` (`use_profession_skill`,
  `profession_skills_panel`, `dismiss_skill_result`).
- Primitives: `tools/lib/lua_actions.py` — `apply_occupation_skill(id)` /
  `apply_next_occupation_skill()` (the press), `skill_can_use(id)` /
  `occupation_skills_ready_count()` (the gate), `skill_cooldown_remaining(id)`
  (ms until the next charge), `occupation_skills_dump()` (the reader).
- Reader / CLI: `tools/occupation_skills.py` — the table below, live, plus `--use`.
- Source capture: `results/traces/20260729_010052_навыки_профессии_trace.log` +
  `results/traffic/20260729_010053_навыки_профессии_traffic.jsonl`. `results/` is
  git-ignored, so this note is the durable record.

## What the feature is

Every account picks a **profession** — in the client's own vocabulary a *mastery
home*, `home_id`:

| home_id | name | flavour |
|---|---|---|
| 101 | Инженер (Engineer) | speeds up building, improves production, buffs allies |
| 102 | Военный лидер (Warlord) | troop potential, combat efficiency, extra damage |

Its tree holds ~57 nodes; the ones that matter here are the **active** ones — a
banked charge on a long cooldown that pays out when pressed. On the Engineer account
that was recorded, thirteen nodes are active:

| skill | id | node | use position | cooldown |
|---|---|---|---|---|
| Быстрое Производство | 10113 | 311 | SkillView | 1410 min |
| Мгновенный сбор | 10230 | 516 | SkillView | 1410 min |
| Случайный посетитель | 10225 | 512 | SkillView | 1410 min |
| Сундук ускорения | 10426 | 803 | SkillView | 1410 min |
| Снабжение Дрона | 10240 | 511 | SkillView | 1410 min |
| Построить сейчас | 10118 | 314 | SkillView | 2850 min |
| Исследуйте сейчас | 10130 | 325 | SkillView | 2850 min |
| Совместное исследование Ⅱ | 10450 | 905 | Building | 1410 min |
| Взаимовыгодное сотрудничество (Win-Win) | 10417 | 801 | Building | 1410 min |
| Совместное строительство Ⅱ | 10436 | 805 | Building | 1410 min |
| Совместное исследование | 10133 | 328 | Building | *covered* |
| Совместное строительство | 10120 | 317 | Building | *covered* |
| Осадное знамя | 10131 | 326 | Field | 4290 min |

Nothing accumulates past `max` charges, so an unspent charge is that day's payout
thrown away — which is what makes this worth automating at all.

## What crossed the wire

One press, `Быстрое Производство` (10113), minus keepalives:

```
--> use.desert.talent.skill  {skillId: "10113"}
<-- use.desert.talent.skill  {skillId: "10113", type: 1018, todayTimes: 1,
      recover: {lastTime: 1785268861119, duration: 84600000,
                max: 1, num: 1, type: 1, cdEndTime: 1785353461119},
      exeObj: {lucky: true, bTypes: "10207000;10201000;10202000",
               reward: [{type: 20, value: 26425872, total: 73470608},
                        {type: 31, value: 17469648, total: 106698298},
                        {type:  1, value: 25361424, total: 71997313}],
               effectDetail: {...}}}
```

Read it field by field, because every one of them is load-bearing:

* **The request is one field.** `skillId`, a *string*. No target, no coordinates, no
  server id — for this class of skill the whole press is its id.
* `type: 1018` is the skill's `type` from its template, not the message type; it is
  what tells the client which reward animation to play.
* `recover` **is the cooldown, and it comes from the server.** `duration` 84 600 000 ms
  = 1410 min, exactly the template's `cd_time`; `cdEndTime` is when the next charge
  lands. `num`/`max` are the charge counter. Nothing client-side sets this — which is
  why a second press fired before the reply arrives would go out against a skill the
  client still believes is ready. See "the re-fire guard" below.
* `todayTimes` counts uses today; `type: 1` in `recover` is `MasteryCdType.Countdown`
  (a rolling timer) against `2 = Everyday` (a daily reset).
* `exeObj.reward` is the payout, `{type, value, total}` per resource — `value` gained,
  `total` the new balance. `lucky: true` marks the bonus roll; `bTypes` names the
  building types that were harvested (food / iron / coin lines, matching the skill's
  `value1` field `10207000;10201000;10202000`).

`use.desert.talent.skill` was newly observed. The name is a leftover from the season
it shipped in — nothing about it is desert-specific.

## The Lua behind it

The owning manager is `DataCenter.MasteryManager`
(`Assets/Main/LuaScripts/DataCenter/Mastery/MasteryManager.lua`). Three of its methods
look like the press and only one is:

| method | what it really is |
|---|---|
| `UseSkill(skillId, pointId, msgId, serverId)` | **the click.** Routes on where the skill is cast from — a march for the targeted ones, straight to the sender for the rest |
| `SendUseSkillMsg(skillTemp, param, msgId)` | **the sender.** Its constants carry `SFSNetwork \| SendMessage \| MsgDefines \| MasteryUseSkill` |
| `HandleUseSkill(msg)` | **the reply applier.** Rewards, popups, `SetSkillCdAndEffectTime`. Calling it sends nothing — the `OnHelpAll` trap again (see `alliance-help.md`) |

The click itself is `LWUIMasterySkillUseInWorldCell:OnBtnClickFunc`, whose one
network-bearing line is `DataCenter.MasteryManager:UseSkill(skill_id, pointId, …,
serverId)`. `MsgDefines.MasteryUseSkill` = `use.desert.talent.skill`.

### Reading state

```
DataCenter.MasteryManager
    :GetData()                          -- home_id (= the profession), level, plans
    :GetHomeDict(home_id)               -- the profession's mastery node ids
    :GetCurSkillIdByMasteryId(nodeId)   -- node -> the skill id at its current level
    :GetSkillTemplate(skillId)          -- active_skills, type, cd_time, name, desc
    :GetMasteryGroupSkillState(nodeId)  -- MasterySkillState, the gate
data:GetSkillChargeData(skillId)        -- {num, max, type, lastTime, duration}
data:GetSkillAvailableTime(skillId)     -- epoch-ms the next charge lands (0 = now)
```

`MasterySkillState`: `0 None`, **`1 Normal` = pressable**, `2 Locked`, `3 CD`,
`4 Covered`, `5 NoUse`, `6 Effect`. `Covered` is the interesting one — it marks a
low-tier node superseded by a higher tier of the same skill (10133 under 10450), and
it has no charge data at all, so gating on the charge counter alone would misread it.

### How long until it can be pressed again

`skill_cooldown_remaining(id)` answers in milliseconds; `0` means a charge is banked
now, `-1` that the question does not apply (not an active skill of this profession, or
its node is `Locked` / `Covered`). It is `GetSkillAvailableTime` — the same instant the
server sent as `recover.cdEndTime` — minus **the server clock**, never the local one.

The `-1` is not pedantry. A `Covered` node's availability time is `0`, which read
naively says "ready now" about a skill that can never be pressed; the sentinel is what
lets a scheduler tell "castable, waiting" from "not a question about this skill". Live
against the recorded account:

```
10113 -> 82827685   (~23 h, the skill from the capture)
10130 ->  17231287  (~4 h 47 m)
10450 ->         0  (a charge banked — though it needs a target, so no press here)
10133 ->        -1  (Covered)
99999 ->        -1  (not a skill of this profession)
```

A recipe reads it directly:

```
READ_LUA <skill_cooldown_remaining(10113)> INTO wait_ms
```

### Which skills may be fired blind

`skillTemplate:CheckUsePosition(MasterySkillUsePosType.X)` answers where a skill is
cast from. Only **`SkillView` (3)** needs no target: it is pressed from the skill
panel and, as the capture shows, puts nothing but its own id on the wire.
`Building` (1) wants a world building and `Field` (2) a map tile — `UseSkill` sends
them through `MarchUtil.OnClickStartMarch` or a world-trigger prefab instead. Firing
those blind would aim at nothing, so the recipe skips them; they are the open half of
this feature.

Note that the template's `location` field is *not* this classification — it says
which panel shows the button (`WorldDesert` for 10113) and disagrees with
`CheckUsePosition` on most rows.

## Acceptance

`use.desert.talent.skill` has a 23.5-hour cooldown and one charge, so the press
cannot be replayed to check it — and at analysis time every no-target skill on the
account was in `CD`, the soonest ~5 h out. The call path was therefore proven
**without spending a charge**: with `SendUseSkillMsg` *and* `SFSNetwork.SendMessage`
temporarily stubbed out inside a single chunk (and restored in the same chunk),

```lua
DataCenter.MasteryManager:UseSkill(10113)   -- no pointId, no serverId
```

arrived at

```
DRY SendUseSkillMsg id=10113 param=nil msgId=use.desert.talent.skill
```

— byte-for-byte the send the human click produced in the trace
(`SFSNetwork.SendMessage <- use.desert.talent.skill, 10113, nil`), with no
confirmation dialog on the way and nothing reaching the wire.

The readers were run live and agree with the recording: `occupation_skills_dump()` lists all
thirteen skills with their states, and `occupation_skills_ready_count()` returns `0` while every
`SkillView` skill sits in `CD` — correctly *excluding* 10450, whose state is `Normal`
but which needs a building target.

A second state turned up by accident and is worth recording: the client later came up
on a different, much younger account (mastery level 12) where **no node of the tree has
a skill learned at all** — `GetCurSkillIdByMasteryId` is nil for all 62 nodes and
`GetCurLvByMasteryId` is 0. The readers handle it without a special case: the dump is
empty, the ready count is `0`, and `TAP use_profession_skill xall` is a no-op. So the
recipe is safe to put in a routine that runs across accounts of different ages.

**Still unproven:** the server accepting a press this code path produced. Until a
charge is available and a run is confirmed in-game, the feature stays 🟡.

## Win-Win Cooperation — the skill that is cast on ANOTHER PLAYER (#2598)

«Взаимовыгодное сотрудничество» / `Win-Win Cooperation`, skill **10417**, is the first of
the targeted half of this feature to be finished. It is an Engineer node whose
use-position is `Building`, so it needs a tile — and, per the game's own description
(`season_mastery_s3_name_2_1` / `_text_2_1`, read out of the client's own locale tables
with `tools/game_locale.py`), a very particular one:

> Can only be used on the War Leader: Reduces their construction and tech research costs
> by 5% for 24 hours. Earn 1 rewards. Cooldown: 23.5 hours.

The discount is theirs, the reward is ours, and the whole thing costs one banked charge —
no diamonds, no resources, no troops.

### The open question was «can the profession be read off the data», and the answer is YES

It was the question the task was written around, and it needed no capture to settle.
**Every record the client keeps about another player carries `careerType`** — the same
scale as one's own `home_id`, `101` Engineer and `102` War Leader — with `careerLv`
beside it. It is on the world point detail a marker tap fetches (`world.get.detail.new`,
alongside `name`, `power`, `allianceId`, `pointId`) and it is on the alliance roster.

The roster is the useful one, because the client keeps it **already indexed by
profession**:

```lua
DataCenter.AllianceCareerManager:GetAllianceMemberListByCareer(102)
```

Each record it hands back holds `careerType`, `careerLv`, `uid`, `name`, `online`,
`mainCityLv`, `power`, `serverId` and — the field that matters — `pointId`, the base tile
the press aims at. Live on the account this was worked out on: **77 Engineers and 18 War
Leaders, all 18 with a `pointId`, 4 of them online.**

So there is nothing to imitate on the wire. `MsgDefines` has no mastery message that asks
for a candidate — the mastery family is `use.desert.talent.skill`, `learn.desert.talent.new`,
`change.desert.talent.page`, the two `push.desert.talent.*` patches and the reset — and the
camera flight a player sees after picking the skill is the client walking its own roster.
**Read once, then listen** is satisfied for free: the roster is already there.

### What the press actually is

Proven the same way the untargeted press was, with `SFSNetwork.SendMessage`,
`MasteryManager.SendUseSkillMsg` **and `MarchUtil.OnClickStartMarch`** stubbed inside one
chunk and restored in the same chunk. Calling

```lua
DataCenter.MasteryManager:UseSkill(10417, <pointId>, nil, <serverId>)
```

arrived at exactly one call:

```
SendUseSkillMsg id=10417 param={otherUid=<16-digit string>, serverId=<number>}
                msg=use.desert.talent.skill
```

Three things follow, and each closes a worry:

* **No march.** `OnClickStartMarch` was never reached, so nothing leaves the base and no
  squad is tied up. The «Building» use-position names where the skill is AIMED, not that
  it travels.
* **The uid is resolved inside `UseSkill`.** The caller passes the tile and the server;
  the client turns that into `otherUid` itself. So a recipe never has to hold a player's
  id — it holds a point.
* **It is headless and scene-free.** The whole of the above was run with the client
  standing in the city, no world scene loaded and no window open.

### The gates, and what each of them says

`lua_actions.win_win_state()` answers all of it in one round trip, and the recipe prints
the line whatever happens, because «не сработало» has five different causes here:

| answer | what it means |
|---|---|
| `state=-2` | the client cannot answer for the tree at all — the login screen, which answers everything and knows nothing |
| `state=-1` | this account has no such node: a War Leader, or an Engineer who has not learnt it. Not a cooldown and not an error |
| `state=3`  | on cooldown; `next_ms` is the server's own countdown (`GetSkillAvailableTime`, i.e. `recover.cdEndTime`) |
| `cands=0`  | nobody in the alliance is a War Leader the client can name a base tile for |
| `state=1`  | a charge is banked and the press may go |

The node is found by walking `GetHomeDict` for the mastery id whose current skill is
10417, never written down — the same reason `_occupation_ready_ids` resolves everything
off the tree: which node a skill sits at depends on the profession and on how far the
tree is levelled.

**Which** War Leader is picked is a decision rather than «the first row»: somebody who is
`online` will actually spend the discount inside the day it lasts, and among those the
biggest `mainCityLv` has the most building and research left to spend it on. Every
candidate is a legal target and the reward is ours either way, so the tie-break costs
nothing to get wrong.

The re-fire guard covers this press too, and has to: the charge only drops when the
server's reply lands, so without the stamp a second tap inside that window would fire at
a SECOND player off one charge.

### On the board

The checklist carries it as a quota of one — `winwin_left` of `winwin_cap`, gated on
`winwin_open` — so «потрачено 1 из 1» is «применено сегодня». It is the only errand of
that board whose day is 23.5 hours rather than the server's midnight, which is why the row
also draws `winwin_next_min` as a countdown («снова через 20:41»): without it the one
question a person has after seeing «сделано» has no answer on the page. The `occupation_skills`
timer counts this charge into its own wake-up clock for the same reason.

**Still unproven:** the server accepting this press. The reading, the candidate list and
the call path are all confirmed live; the charge had not been spent at the time of
writing, so the feature stays 🟡 until a run is watched in-game.

## On a clock — and the clock is the game's

The recipe is a timer row (`occupation_skills`, `panel/timers.py`), switched off until
somebody turns it on. What matters is that its period is a FALLBACK and not the
schedule: a charge recovers on a countdown the server sets — the press's own reply
carries it as `recover.cdEndTime` — so the run reads the soonest of those instants over
the profession's no-target skills and hands it back as `next_run_in` (seconds from now,
plus a minute's margin; `docs/dsl.md`). The schedule books that turn and asks nothing in
between. A row on an hourly period would put twenty-three questions to the game for
every one that had an answer, which is exactly what «читаем один раз, остальное слушаем»
forbids.

The reading skips `Locked`, `Covered` and `None` nodes for the same reason
`skill_cooldown_remaining` returns `-1` for them, and it skips whatever the re-fire
guard has stamped in the last two minutes — a skill just fired still reads `Normal`
until the reply lands, and booking the next turn off that would ask again at once. When
nothing at all is readable — no mastery data, no learned active skill — the answer is
`0`, which leaves the row's own six hours standing. A reading that fails costs one
ordinary turn and can never quietly stop the timer.

The gate at the top of the recipe is the same count the press uses
(`MasterySkillState == Normal` over the profession's own tree, never a written-down list
of ids — a season adding a node would leave the list pressing last season's set). It
distinguishes three answers where a bare count has two: a number is what to fire, `0` is
an honest «nothing ripe», and `-1` is a client that cannot answer for the tree at all —
the login screen, which answers everything and knows nothing. The last is a FAILED run,
so the errand is retried in minutes rather than written off as done for the day.

## The re-fire guard

`TAP use_profession_skill xall` re-reads the ready count between presses. The count
is client-side state that only changes when the server's reply lands — up to ~8 s in
the recording — so a naive loop would press, see the skill still `Normal`, and fire
it a second time. `apply_next_occupation_skill()` therefore stamps each id it fires on
`MasteryManager.__lw_fired` and drops anything stamped within
`MASTERY_REFIRE_GUARD_MS` (120 s) from the ready list. The stamps live on the manager
table rather than in a global because this VM refuses some new globals
(`Lua 全局变量 '__XSTRACE' 不可<新增/修改>`).

Two rules from `docs/skills/sniff.md` §8.7 apply directly and were followed: one
press per chunk (a `while ready > 0 do press() end` inside one chunk spins the main
thread and freezes the client), and the gate is the client's own `Normal` check —
pressing on cooldown is not a no-op, it is a server rejection with a player-facing
toast.

## Aftermath on screen

A successful use raises its own modal — `UIMasterySkillUseResultShow` for most
skills, `UIBuyOneGetOneFree` for the resource ones (that is the one the trace shows
after 10113), `UIGetVirus` for Cultivate Virus. They are separate windows from the
generic reward popup, so `dismiss_reward_popup` does not match them;
`dismiss_skill_result` closes all three by name.
