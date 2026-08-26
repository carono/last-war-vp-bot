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

Live, on a logged-in account (values invented, of the shape observed):

```
GetName=Player1 | GetFullName=[AL1] Player1 | level=35 | power=231590771
```

## 3. Three neighbouring fields that look like power and are not

Measured on a live account, all four read in the same round trip:

| field | live value | what it is |
|---|---|---|
| `power` | 231 590 771 | the figure the client hands out for this character |
| `playerMaxPower` | 290 163 525 | a different, larger figure — not the current one |
| `playerPower` | 0 | empty on a live account |
| `lastPower` | 0 | empty on a live account |

So the choice is not «pick the field whose name reads best». Two of the four are zero,
and a reader that had reached for `playerPower` — the most player-ish of the names —
would have drawn a confident `0` for a 231-million account. This is the same lesson the
resource reading learned the hard way (`base-resources.md`: the field spelled `wood` is
drawn as «Золотые монеты»): **the client's field names are not what the game shows.**

## 4. The breakdown, for when somebody wants it

`DataCenter.PlayerPowerDataManager` holds the components — hero, army, building, science,
decoration, squad equipment, tactical card, dominator, and finer splits inside each
(`heroLevelPower`, `heroEquipPower`, `weaponChipPower`, …), plus
`GetValByPowerType` / `GetValByPowerSourceType`. It is **not** part of this reading: the
components do not sum to `power` exactly, and showing them needs the game's own names for
each, which is a separate ability rather than a row the panel could label for itself.

## 5. The login gate

A client sitting at the login screen answers everything cheerfully and wrongly
(`tools/lib/game_clock.py`). The scenario therefore asks the game what time it is first —
an implausible clock ends the reading with an empty string and the panel keeps the card it
had. The check is the same round trip, so it is free. It is the identical gate
`read_base_resources.md` uses, for the identical reason.

## 6. The answer's shape

One variable, `player_card`, three fields separated by `;;` — a name may contain spaces,
so the separator is not one:

```
Player1;;35;;231590771
```

The tab splits it and fills its three rows; the phone's screen draws the same three from
the same `fetch()`, so the two front-ends cannot disagree.
