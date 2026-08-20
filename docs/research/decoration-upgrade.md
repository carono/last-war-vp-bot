# Base decorations — the star upgrade (`decorator.progress.upgrade`)

Sources:

* three labelled sniffer runs driven by hand on the base —
  `20260730_142543` «Повышение украшений» (recorded with `filter="SFS"`),
  `20260730_155533` / `20260730_160800` (both flooded, nothing usable), and
  `20260730_162054` «улучшение украшений», the one that matters: a **broad** trace of a
  real, successful upgrade («открыл здание, улучшил украшение на 1»);
* live reads of the running Lua VM, including `string.dump` of the two readers involved;
* a live press driven by the bot itself (see §7).

Both `*_traffic.jsonl` files hold nothing but keepalives and alliance-alert pushes, so
every wire fact below comes from the Lua trace, not from decoded packets.

This ability was got wrong **twice** before it was got right. §6 is the post-mortem, and
it is the part worth reading before analysing any other press.

## 1. The walk in the game

Tap the building that carries decorations → its handbook (`LWDecorationBook`) → a
decoration cell → the upgrade panel (`LWDecorationBookUpgrade`; its art lives under
`Assets/Main/Sprites/UI/UIDecorationAdvanceUpgrade/`). The press is
`DecorateInfo/LevelUpBtn`.

None of that walk is needed. The message carries no window and no cell id, so the send is
the whole press — the three screens are UI only.

## 2. The message

One press puts exactly one message on the socket. Positional arguments, not a table:

```lua
SFSNetwork.SendMessage(MsgDefines.DecoratorProgressUpgradeMessage,  -- "decorator.progress.upgrade"
                       buildUuid, num)
--   PutLong(buildUuid, 1156814546481171486)
--   PutInt (num,       1)
```

Two keys and no more (`DecoratorProgressUpgradeMessage`). Both of them are easy to get
wrong:

* **`buildUuid` is the decoration GROUP's representative**, the building
  `BuildManager:GetMaxLvBuildDataByBuildId(itemId)` returns — not any building that
  happens to carry the decoration. Fed each recording's itemId it hands back exactly that
  recording's uuid:

  | recording | itemId | uuid on the wire | `GetMaxLvBuildDataByBuildId` |
  |---|---|---|---|
  | `20260730_142543` | 103401000 | 1156814307842051185 | same |
  | `20260730_162054` | 103402000 | 1156814546481171486 | same |

  Another building of the same decoration is the wrong target: the client accepts the send
  and nothing changes (fired live, state unchanged).

* **`num` is a COUNT of progress steps**, not a slot index — the count the panel calls
  `curCanUpgradeNum`, which is 1 for a single tap and more for a long press. Where that
  number comes from is §4.

The reply is `decorator.progress.upgrade` carrying the group's refreshed info, and the
server follows it with the effect and stat pushes the upgrade earns —
`push.batch.effect.change`, `push.hero.effects`, `push.dominator.data`,
`player.combat.change`, `player.info`.

## 3. Gate one — the step has to exist

`BuildingUtils.IsExistAdvanceUpgrade(itemId, level)`, with the representative's own level.
The trace shows the panel calling it over every decoration group it lists, with exactly
those two arguments.

Without it the server refuses the send outright — captured live off the reply:

```
errorCode = building_center_tips4
errorMsg  = "building no extra_lvup_para"
```

On this account 23 of 61 decoration groups pass it.

## 4. Gate two — the material is a spare duplicate

**A step is paid for with a spare copy of the same decoration, not with a currency.** One
spare copy buys one point of star progress.

`BuildingUtils.GetDecorateUpLevelBuilds(buildData)` returns the feed cells the panel
renders, one per level that can be fed in:

```
{itemId = 103404001, count = 2, needScore = 484, nextScore = 486, levelTemplate = …, buildData = …}
```

* **`itemId`** — the level-1 variant of the decoration (base id + 1), the thing consumed.
* **`count`** — how many steps are buyable **right now**: the spare copies held, capped by
  what is still missing to `nextScore`. The reader's own locals are `curScore`,
  `nextScore`, `math_min`, `math_floor` (read out of `string.dump`), so the cap is the
  `math.min`. This is the number `num` should carry.
* **`nextScore`** — the star threshold being climbed to. For a level-6 decoration the
  three thresholds are 162 / 324 / 486; a level-4 one is at 54, a level-3 one at 18.

`needScore` is only meaningful on a cell that has `count > 0`. With nothing to feed it
comes back equal to `nextScore` — which reads like "this one is maxed out" when it only
means "nothing to feed here". The dump in §8 says `no-spares` on those lines rather than
print a score it cannot know.

What the panel showed for the hand press, before and after, lines up with all of it:

```
before   spare copies <color=#5FEF87>1</color>/100      star bar 386/486  (preview 387)
after    spare copies <color=#F97077>0</color>/99       star bar 387/486
```

— one copy consumed, one point gained, and the counter flipping green → red. The bonus the
bar pays out is read with `GetDecorationProgressUpValue`: at 386 the decoration was worth
`+135` «Защита героя & Повелителя» (effect 50062).

## 5. Reading the whole collection

* `BuildManager:GetAllDecoratorBuildingData()` — every decoration group on the base, keyed
  by itemId (61 here).
* `BuildManager:GetMaxLvBuildDataByBuildId(itemId)` — the group's representative
  `buildData`: `uuid`, `level`, `pointId`, `decorNum`, and the rest of the ordinary
  building record.
* `BuildingUtils.GetDecorateCountByLevel(itemId, level)` — spare copies held at that level.
  This is the numerator of the panel's counter; the denominator (100 → 99 above) is the
  total owned and comes from elsewhere.

## 6. Post-mortem — two wrong recipes, and why the traces let them through

**First pass (wrong).** Built from `20260730_142543` alone. That run was recorded with
`filter="SFS"`, so **only SFS calls reached the file** — the building, handbook and cell
taps are simply absent from it. Read as a complete record it says "the press is a uuid and
a slot index, and nothing else happens", which produced a recipe that parked a queue of
targets and did nothing in game. The absence of a UI walk in an SFS-filtered trace is not
evidence about the UI.

**Second pass (also wrong, and worse).** The live VM fixed `buildUuid` and `num`, found the
`IsExistAdvanceUpgrade` gate off the server's refusal — and then took
`BuildManager:IsCanUpgradeDecoration(itemId, level, buildData)` for the material gate
because it returns a plausible-looking `have, need` pair. It is the wrong reader. Its
`string.dump` constants name what it actually does — `equal_glue_value`, `hasCount`,
`upgradeNeedCount`, `levelOneBuildingData`, `UseNewDecorationCountLogic` — and the pair is
in **glue value**, pricing the ordinary decoration **level** upgrade:

```
103402000 lv 6   have = 110   need = 29160        (level 6 -> 7)
103523000 lv 5   have =   0   need =   162
```

`have >= need` is never satisfiable there, so the button's count read 0 forever and it
never pressed. The report "23 decorations have an upgrade step, 0 have the material" was
the bug describing itself, and it was mistaken for a true reading of a poor account.

What broke the tie was the `20260730_162054` recording: the player upgraded 103402000 by
hand **while that pair read 110 / 29160**. A gate the game itself walks straight past is
not the gate. The panel's own readout was the spare count all along.

Two lessons, both of which cost a commit:

* **A pair of numbers that type-checks is not a gate.** Read the function's constants
  (`string.dump` — the game's Lua is not stripped) and find out what it prices before
  wiring it to a press.
* **A gate that is never satisfiable is indistinguishable from a poor account** unless
  something independent says otherwise. One recording of the press succeeding settled in a
  minute what a day of reading could not.

## 7. What is proven

**Proven live on 2026-07-30, driven by the bot, one step at a time** — decoration
103404000, level 6, two spares banked:

```
before   score 484/486   steps 2
press    decor_upgrade item=103404000 uuid=1156814744896916569 lv=6 num=1 of 2
after    score 485/486   steps 1
```

The progress moved by exactly one point and the game charged one spare copy for it, which
is the per-unit resetting signal — not a screenshot. The uuid sent is the one
`GetMaxLvBuildDataByBuildId` resolves, i.e. the same identity both hand recordings put on
the wire for their own groups.

Also proven: the message and both its fields (from the broad recording of a real press),
the `IsExistAdvanceUpgrade` refusal, the spare-copy gate across all 61 groups, and the
do-nothing path (22 of the 23 eligible groups hold no spare, and the press correctly sends
nothing).

**`num > 1` in a single send, proven live on 2026-08-20 (#1560).** Decoration 103502000
read `needScore=52 cnt=2` (two spares, two points short of the next star); one message
carried `num=2`; the next read came back `needScore=54 cnt=0` — the whole gap crossed in
one round trip. Scaled up the same session on three groups at once, in one game-VM call:
103401000 read 25 spares banked and moved `461->486/486` (the star reached) on a single
`num=25` send; 103402000 moved `481->486/486` (+5); 103514000 moved `156->162/162` (+6).
`upgrade_all_decorations_now` in `tools/lib/lua_actions.py` sends every ready group its
whole available count this way, all inside one call — no more one step per press.

## 8. Code

* Lua chunks: `tools/lib/lua_actions.py` — `upgrade_all_decorations_now`,
  `upgrade_next_decoration`, `decoration_upgrade`, `decoration_upgrade_ready_count`,
  `decoration_state_dump`, `decorations_window`.
* Buttons: `upgrade_decoration`, `dump_decorations`, `decorations` in
  `tools/lib/game_buttons.py`.
* Recipe: `src/lastwar_bot/actions/upgrade_decorations.md`.
