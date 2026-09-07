# The drone: what it is in the client, what a level costs, and what still is not known

Task #2617. The duel's Monday pays for opening the drone's chip chests and for raising
the drone's level. This is what the running client says about both.

## 1. Nothing is called a «drone»

A shallow scan of `DataCenter` (610 keys) finds no `Drone`, no `UAV`, no `Uav`. The
drone is the client's **tactical weapon**, and the wire is what gives it away:

```
PushTWSkillChipDataChange = push.uav.skillchip.changes
PushWeaponEffectsChange   = push.uav.effects
```

So `TW…` is the drone throughout, which also settles a naming question the panel had:
**«Сундук Чипа Навыка» are the DRONE's skill-chip chests**, not a tactical-weapon
accessory of some other kind.

| what | where |
|---|---|
| the drone itself | `DataCenter.TacticalWeaponManager` — `GetTacticalWeaponInfo(1000)`, or the one entry of `tacticalWeaponInfos` |
| its level rows | `DataCenter.TacticalWeaponLevelTemplateManager` — `GetTemplateByLevel(n)` |
| its chips | `DataCenter.TWSkillChipManager`, `DataCenter.TacticalChipManager` |
| raise it | `MsgDefines.TacticalWeaponLevelUpMessage` = `weapon.up.lv` |

One drone per account, `id = 1000`.

## 2. What one level costs — read, never assumed

`info.levelTemplate` (or `info:GetLevelTemplate()`) carries `cost_resItem`, a list of
`{id, value}`. Two live readings, on two accounts:

```
level 130 → cost 7037 × 42 000   and 7038 × 400
level 174 → cost 7037 × 252 000  and 7038 × 140
```

The price therefore moves with the level in BOTH directions and cannot be written down
anywhere. `actions/upgrade_drone.md` reads it every time.

**The two cost items are not in the bag.** `ItemData.ItemInfos` holds none of them, while
`ResourceItemDataManager.itemList` holds 71 976 670 of 7037 and 540 of 7038 on the same
account: they are RESOURCES — running totals — not stacks. Reading the wrong store is how
a recipe reports «not enough» over a purse of seventy million (measured, #2617).

Useful gates on the info object, all read live:

```
IsReachMaxLevel   the drone's own ceiling
IsReachLevelLimit the ceiling the base building imposes
HasResItemToUpgrade  the client's own «can it pay»
```

`HasResItemToUpgrade` agreed with the arithmetic on both accounts, including the «no»
(120 gears against a price of 140).

## 3. The chip chests

Three grades in the live bag, all of them ordinary chests (`type = 5`), opened with
`item.use` one stack at a time:

| id | name | 
|---|---|
| 540201 | Сундук Чипа Навыка R |
| 540301 | Сундук Чипа Навыка SR |
| 540401 | Сундук Чипа Навыка SSR |

Proven live: 44 chests across three stacks opened in ONE call
(`ACT use_bag_ids … used=44 stacks=3 why=-`). The name, the rarity colour and the icon
file come from `ItemTemplateManager` — `GetName(id)`, and the row's `icon`, which must
never be computed from the id.

The nearby family that is NOT this — «Сундук Компонента Дрона 1/2/3 ур.», 630011…630013 —
is a different box and the panel deliberately does not touch it.

## 4. What is still unknown: the shape of `weapon.up.lv`

`SFSNetwork.SendMessage(MsgDefines.TacticalWeaponLevelUpMessage, {id = 1000})` is
accepted by the serialiser and changes nothing: live on an account that could afford two
levels, the level stayed at 130 and **not one resource moved** — so a wrong shape costs
nothing, which is the one good thing about it.

What has been ruled out or not tried:

* `{id = 1000}` — sent, no effect, nothing spent.
* the sender itself is not reachable from `_G`: there is no `TacticalWeapon…Ctrl` while
  the drone's window is closed, and the Lua sandbox has refused `string.dump` since
  2026-08, so a function's constants cannot be read out of it.
* the windows exist by name (`UITacticalWeaponLevelDisplay`,
  `UITacticalWeaponSkillLevelUp`, …), so opening one and reading the Ctrl it creates is
  the next thing to try.
* the honest alternative is one sniffed press: record, have the player raise the drone
  once by hand, and read the fields off the wire.

Until then `actions/upgrade_drone.md` reads, gates and reports correctly and its press
fails loudly («the drone did not move») rather than claiming success.
