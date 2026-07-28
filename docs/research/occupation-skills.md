# Profession skills ("навыки профессии")

How the profession's active skills are fired, derived from one labelled sniffer run
and pinned against the live Lua VM.

- Recipe: `actions/occupation_skills.md` — press every ready no-target skill.
- Buttons: `tools/lib/game_buttons.py` (`use_profession_skill`,
  `profession_skills_panel`, `dismiss_skill_result`).
- Primitives: `tools/lib/lua_actions.py` (`mastery_ready_count`,
  `mastery_use_next_ready`, `mastery_use_skill`, `mastery_skill_ready`,
  `mastery_dump`).
- Reader / CLI: `tools/mastery_skills.py` — the table below, live, plus `--use`.
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
| Взаимовыгодное сотрудничество | 10417 | 801 | Building | 1410 min |
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

The readers were run live and agree with the recording: `mastery_dump()` lists all
thirteen skills with their states, and `mastery_ready_count()` returns `0` while every
`SkillView` skill sits in `CD` — correctly *excluding* 10450, whose state is `Normal`
but which needs a building target.

**Still unproven:** the server accepting a press this code path produced. Until a
charge is available and a run is confirmed in-game, the feature stays 🟡.

## The re-fire guard

`TAP use_profession_skill xall` re-reads the ready count between presses. The count
is client-side state that only changes when the server's reply lands — up to ~8 s in
the recording — so a naive loop would press, see the skill still `Normal`, and fire
it a second time. `mastery_use_next_ready()` therefore stamps each id it fires on
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
