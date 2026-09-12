# The peace shield: what raises one, and what says a base is under it

Measured live on 2026-09-12 against a running client (#2822). Everything below is a
reading taken from the game's own Lua VM; no value here belongs to one account.

## 1. The item

The bag holds shields as ordinary stacks. Two were on the live account:

| id | the game's own name | `type` | `type2` |
|---|---|---|---|
| `200411` | «24-часовой щит» | 4 | 1 |
| `200406` | «12-часовой щит» | 4 | 1 |

`type = 4` matters: `USABLE_ITEM_TYPES` in `tools/lib/lua_actions.py` (the set behind
`use_bag_item`) does not contain it, so the general «use N of item X» primitive refuses a
shield outright with `why = not-usable`. The game's own check disagrees —
`DataCenter.ItemData:CheckUseStateTool(template)` answers `true` for `200411` — which is
why the shield got a press of its own (`use_peace_shield`) rather than a widened set: the
set is what keeps a hero shard from being «used», and loosening it for a shield would
loosen it for everything else of that type.

Note the argument: `CheckUseStateTool` takes the TEMPLATE, not the id. Passed an id it
raises `attempt to index a number value (local 'template')` inside the pcall, which is
the silent-failure shape this repository has been bitten by before.

## 2. Whether a shield is up, and until when

`DataCenter.DefenceWallDataManager` is the client's own record of the base's wall, and it
answers both questions with no window open and from any scene:

```lua
DataCenter.DefenceWallDataManager:IsInShield()              -- true / false
DataCenter.DefenceWallDataManager:GetDefenceWallData()      -- the wall's own record
```

`GetDefenceWallData()` on the live account:

```
durability = 10000        morale = 3000
protectEndTime = <ms>     fireEndTime = <ms>       cityBroken = false
lastDurabilityTime = <ms> lastMoraleTime = <ms>    lastGoldRecoverDurabilityTime = <ms>
```

`protectEndTime` is epoch **milliseconds on the GAME's clock**, which is not this PC's
(`tools/lib/game_clock.py`) — so «сколько осталось» is `protectEndTime - game_clock.now_ms()`
and never a subtraction against `time.time()`.

**There is no push behind it.** Nothing on the wire announces «щит поставлен» to a
listener the panel already keeps, so the reading is taken on `bus.GAME_READY`, when
somebody opens the screen, and after the panel's own run — and what is LEFT is arithmetic
on a moment the game itself named, which is why no clock is needed for it
(`CLAUDE.md`, «Read once, then LISTEN»).

Two wrong turns worth not repeating: `DataCenter.CityDomeManager` and
`CityDomeProtectEffectManager` are the base's DOME — its radius and the animation of it
growing — and have nothing to do with protection; `WorldBuildUtil.HasShield(...)` reports
the shield of a world point (somebody else's base as the camera crosses it), not your own.

## 3. Raising one

The send is the bag's own `item.use`, one stack at a time, in the shape this client will
serialise (`docs/research/inventory.md`):

```lua
SFSNetwork.SendMessage(MsgDefines.ItemUse, {uuid = <the stack's uuid>, num = 1})
```

Which stack does not matter — a shield is a shield — so the first one holding any is
taken. `tools/lib/game_buttons.py::use_peace_shield_24h` is the press and carries no
gate at all; every gate is in `src/lastwar_bot/actions/raise_peace_shield.md`:

1. **the day** — the GAME's weekday, `0` for «any»;
2. **a shield already up** — `IsInShield()`, because a second shield over a live one is
   an item that cannot be earned back;
3. **the bag** — no 24-hour shield gives a reason, never a silent no-op.

## 4. The game's weekday, without asking anything new

The warzone's day turns at its own 00:00 — 02:00 UTC on the account measured — so for two
hours out of every twenty-four this machine has already moved on while the game is still
handing out yesterday. `UITimeManager:GetInstance():GetTomorrowZero()` says when the
current game day ENDS, and the end of a Saturday is a Sunday timestamp; half a day back
from it lands in the middle of the day it belongs to:

```lua
local d = math.floor((GetTomorrowZero() - 43200000) / 86400000)
local weekday = ((d + 3) % 7) + 1        -- 1 = Monday … 7 = Sunday; epoch day 0 = Thursday
```

Verified live: at 01:35 UTC on Saturday 2026-09-12 it answered **5** (Friday), which is
what the game was still on. A PC-side `datetime.weekday()` would have answered Saturday
and fired the errand a day early, every week.

## 5. The schedule

`panel/timers.py` grew `Timer.offset_sec` for this (#2822): a weekday-bound errand is due
at the start of a matching game day **plus** the offset. The shield's is 60 seconds — the
person's own «через минуту после сброса сервера» — which puts the request on the far side
of the day's turnover. The offset moves the moment and nothing else: «has it run in this
day» is still asked about the day's own start, so an errand that ran at the boundary
before the offset existed is not offered a second time a minute later.

The errand ships **switched off**, which is the exception `CLAUDE.md` names to «a new
ability ships switched on»: a shield leaves the bag and cannot be earned back.
