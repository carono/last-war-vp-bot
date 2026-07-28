# Alliance gift collection ("Подарки альянса")

How the alliance "Gifts" screen claims its banked boxes, derived from one labelled
sniffer run and confirmed against the live Lua VM through the warm daemon.

- Recipe: `actions/collect_alliance_gifts.md`.
- Button: `tools/lib/game_buttons.py` (`collect_alliance_gifts`).
- Source capture: `results/traffic/20260728_172314_Подарки_альянса_traffic.jsonl`
  (+ the same-label `results/traces/…_trace.log`). `results/` is git-ignored, so
  this note is the durable record.

## What the player did

One recording of: tap the alliance **Gifts** section, then the two "collect all"
buttons — ordinary gifts and premium/privilege gifts.

## What crossed the wire

The `up` lines minus keepalives (§8.5 of `docs/skills/sniff.md`):

```
alliance.reward.list       {index:0, len:1000}          # open section (default tab)
alliance.reward.allreceive {type:2}                     # claim all of type 2
alliance.reward.list       {index:0, type:2, len:1000}  # re-list to refresh
```

Reading: list the gifts, claim all of a type, re-list. The response to a typeless
`list` carries `info.list1`; a `type:2` `list` carries `info.list2` + `redPoint2`.
So the feature is **type-parameterised**: `type` (absent ⇒ 1) selects the tab —
type 1 = ordinary gifts, type 2 = premium/privilege gifts.

Only **one** `allreceive` fired even though the player pressed two collect buttons:
the other tab had nothing pending, so the client swallowed that click (the "gated"
case, §8.5b / §8.11). Both `alliance.reward.list` and `alliance.reward.allreceive`
were newly observed — added to `tools/known_commands.txt`.

## The Lua behind it (live-probed)

The function-level trace was pure UI churn — the gift manager never appeared in it
(the §8.5a blind spot: the window controller lives in `package.loaded`, not on `_G`
at depth 2). So the API was recovered from the wire name and pinned on the live VM
(`tools/lib/lua_eval.py` → the warm `lua_daemon`):

| layer | where |
|---|---|
| manager | `DataCenter.AllianceGiftDataManager` (the "reward" domain surfaces as the **Gift** manager) |
| claim all | `AllianceGiftDataManager:SetAllGiftReceiveByType(type)` — the wire's `alliance.reward.allreceive {type}` |
| list | `AllianceGiftDataManager:GetGiftInfoList(type)` / `UpdateGiftInfoList` — the wire's `alliance.reward.list` (the getter errors without a `type` arg, confirming the per-type shape) |
| counter | `AllianceGiftDataManager:GetRedPointNum()` — total unclaimed; `0` when nothing is pending |
| controller (window) | `UI.UILWAlliance.UILWAllianceGift.Controller.UILWAllianceGiftCtrl`, click handler `OnGetAllBtnClick` — not needed for the headless call |

The harvest is headless, like `help_ally_all`: `SetAllGiftReceiveByType(type)` sends
straight from the data manager, so no window has to be open. The button sweeps both
types in one press:

```lua
local m = DataCenter.AllianceGiftDataManager
for _, t in ipairs({1, 2}) do pcall(function() m:SetAllGiftReceiveByType(t) end) end
```

## Verification caveat

At record and probe time `GetRedPointNum()` was **0** — nothing was pending — so
firing `SetAllGiftReceiveByType(1/2)` with the traffic sniffer running produced no
`alliance.reward.allreceive` on the wire (the client gates an empty claim). The
mapping therefore rests on: the exact name/param match (manager, method and the
`type` argument all mirror the wire), the type-parameterised list confirming the
model, and the method being callable headlessly. **Re-run the §8.10 acceptance test
when gifts are actually pending** (`GetRedPointNum() > 0`): the recipe is correct
when a single `TAP collect_alliance_gifts` emits `alliance.reward.allreceive` and
drops the red-point count to 0.
