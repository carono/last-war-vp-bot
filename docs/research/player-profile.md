# The character's own card — name, HQ level, power (#1991)

Goal: the «Профиль» tab drew three dashes where the player's name, HQ level and power
belong. Establish where the client actually keeps them, and make the reading a scenario.

Method: live probes through the panel's web API against a logged-in client
(`src/lastwar_bot/actions/dev/…`, deleted afterwards). No wire capture was needed: every
value below is already in the client's memory before anything is asked.

Result: `actions/read_player_profile.md`. One VM round trip, no question on the wire, no
window and no scene.

---

## 1. What was there, and why it could never work

The tab assembled its own Lua chunk — from before «everything is a scenario» — and asked:

```lua
local R = DataCenter.RoleDataManager or DataCenter.PlayerDataManager
R:GetName() / R.name ; R:GetLevel() / R.level ; R:GetPower() / R.power
```

**Neither manager exists in this client.** `DataCenter` has no `RoleDataManager` and no
`PlayerDataManager`, so `R` was `nil`, every access raised, every `pcall` swallowed it,
and the chunk printed three empty fields on every call it ever made. Nothing said so —
the same shape of failure `panel/runtime/reads.py` records for the resource balance, and
the same cost of wrapping a guess in a `pcall`.

## 2. Where the values really are — `LuaEntry.Player`

The client's own character object, filled at login and kept current by the server's
updates. It is the object `actions/read_server_info.md` already asks about the warzone,
so this reading costs nothing new.

| what | how |
|---|---|
| name | `LuaEntry.Player:GetName()` — the plain name; `GetFullName()` prefixes the alliance tag |
| HQ level | the field `level` — **there is no `GetLevel()`** on this client |
| power | the field `power`; `GetValue('power')` answers the same number |
| alliance | `GetFullAllianceName()` — tag and name, already composed by the game; `GetAllianceAbbr()` / `GetAllianceName()` are the halves |
| in an alliance at all | `IsInAlliance()` — stated, rather than inferred from an empty name |
| energy | `GetCurStamina()`, and `GetStaminaFullTime()` for the moment it fills (epoch ms, 0 when full) |
| registered | the field `regTime`, epoch ms. `GetUserRegDay()` answers the same thing as a FRACTIONAL day count (`692.11…`) |

Live, on a logged-in account (values invented throughout, of the shape observed):

```
GetName=Player1 | GetFullName=[AL1] Player1 | level=35 | power=100000000
GetFullAllianceName=[AL1] Alliance One | IsInAlliance=true
GetCurStamina=67 | GetStaminaFullTime=1700000000000 | regTime=1600000000000
```

**The alliance's tag and name are never glued together here.** The game composes the
string itself, with its own punctuation and in its own language; the two halves exist
separately and joining them would be the panel re-deciding something the game already
decided. Same reasoning as the resource names in `base-resources.md`.

**`GetUserRegDay()` is deliberately not used.** It is a fraction, so anything readable
comes from rounding it — and a rounded figure is the panel's arithmetic wearing the
game's authority. `regTime` is a moment, and rendering a moment as a date is drawing,
not deciding.

## 3. Three neighbouring fields that look like power and are not

Measured on a live account, all four read in the same round trip:

| field | live value (shape only) | what it is |
|---|---|---|
| `power` | ~2.3 × 10⁸ | the figure the client hands out for this character |
| `playerMaxPower` | ~2.9 × 10⁸ | a different, larger figure — not the current one |
| `playerPower` | 0 | empty on a live account |
| `lastPower` | 0 | empty on a live account |

So the choice is not «pick the field whose name reads best». Two of the four are zero,
and a reader that had reached for `playerPower` — the most player-ish of the names —
would have drawn a confident `0` for an account with hundreds of millions of it. This is the same lesson the
resource reading learned the hard way (`base-resources.md`: the field spelled `wood` is
drawn as «Золотые монеты»): **the client's field names are not what the game shows.**

## 4. What is read and NOT shown, and why

`playerMaxPower` is a real number the client keeps, and **nothing in the client says what
it means** — a peak, a season high, a cap. A row on a card is a claim, so drawing it under
a caption of the panel's own choosing would be inventing the game's word. It stays out
until the game names it. The same goes for `armyKill` / `armyDead` / `armyCure`, which
read 0 on a live account that has certainly fought: they are not the counters the game
draws.

## 5. The breakdown, for when somebody wants it

`DataCenter.PlayerPowerDataManager` holds the components — hero, army, building, science,
decoration, squad equipment, tactical card, dominator, and finer splits inside each
(`heroLevelPower`, `heroEquipPower`, `weaponChipPower`, …), plus
`GetValByPowerType` / `GetValByPowerSourceType`. It is **not** part of this reading: the
components do not sum to `power` exactly, and showing them needs the game's own names for
each, which is a separate ability rather than a row the panel could label for itself.

## 6. The login gate

A client sitting at the login screen answers everything cheerfully and wrongly
(`tools/lib/game_clock.py`). The scenario therefore asks the game what time it is first —
an implausible clock ends the reading with an empty string and the panel keeps the card it
had. The check is the same round trip, so it is free. It is the identical gate
`read_base_resources.md` uses, for the identical reason.

## 7. The answer's shape

One variable, `player_card`, seven fields separated by `;;` — a name may contain spaces,
so the separator is not one:

```
Player1;;35;;100000000;;[AL1] Alliance One;;67;;1700000000000;;1600000000000
```

`nick ;; level ;; power ;; alliance ;; stamina ;; stamina_full_ms ;; reg_ms`. The window's
card draws the first three (it is being retired, so nothing new goes into it); the phone's
card draws all six readings from the same `fetch()`.

## 8. Read on a look, not on an event — and why

The resource balance next to this card lives on a push
(`push.resource.item.update`, `base-resources.md`) and re-reads itself. **This card
deliberately does not**, and the reason is what the values are:

* **name, HQ level, power** change when the PLAYER does something — a rename, an upgrade,
  a research — which means the player is in the game, not reading the panel. There is no
  «the character changed» push in the client's vocabulary either: the pushes the panel
  knows are about resources, marches, help, chat, tiles, heroes — none about the role.
* **energy is the one thing that moves on its own, and no event could carry it**: it
  refills with TIME. That is exactly why the reading is not a lone number — the moment the
  purse fills comes back beside it, so an hour-old reading still answers «when will I have
  a full purse» correctly.

So the card is read when the tab is opened and when «Обновить» is pressed, at one VM round
trip a time. An ear would cost a subscription, and would fire on events that cannot change
any of these six values.
