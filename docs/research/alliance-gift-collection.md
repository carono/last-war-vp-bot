# Alliance gift collection ("Подарки альянса")

How the alliance "Gifts" screen claims its banked boxes, derived from one labelled
sniffer run and confirmed live in-game through the warm Lua daemon.

- Recipe: `actions/collect_alliance_gifts.md` — open the section, collect ordinary,
  collect premium, close (the player's exact clicks).
- Buttons: `tools/lib/game_buttons.py` (`alliance_gifts`, `collect_gifts_ordinary`,
  `collect_gifts_premium`).
- Source capture: `results/traffic/20260728_172314_Подарки_альянса_traffic.jsonl`.
  `results/` is git-ignored, so this note is the durable record.

## What the player did

One recording of: tap the alliance **Gifts** section, then its two "collect all"
buttons — ordinary gifts, then premium/privilege gifts.

## What crossed the wire

The `up` lines minus keepalives (§8.5 of `docs/skills/sniff.md`):

```
alliance.reward.list       {index:0, len:1000}          # open section (default tab)
alliance.reward.allreceive {type:2}                     # claim all of type 2 (premium)
alliance.reward.list       {index:0, type:2, len:1000}  # re-list to refresh
```

The feature is **type-parameterised**. A typeless `list` response carries
`info.list1`; a `type:2` `list` carries `info.list2` — so `type` selects the tab:
**type 1 = ordinary gifts, type 2 = premium/privilege gifts**. Only one
`allreceive` fired in the recording because the other tab had nothing pending (the
client swallows an empty claim, §8.5b). Both `alliance.reward.list` and
`alliance.reward.allreceive` were newly observed — added to
`tools/known_commands.txt`.

## The Lua behind it (live-probed and confirmed in-game)

The function-level trace was pure UI churn — the gift controller lives in
`package.loaded`, not on `_G` at depth 2 (the §8.5a blind spot). So the API was
recovered from the wire name and pinned on the live VM
(`tools/lib/lua_eval.py` → the warm `lua_daemon`):

| layer | where |
|---|---|
| window | `UIWindowNames.UILWAllianceGift` — `UIManager.Instance:OpenWindow(...)` opens the section (sends `alliance.reward.list`) |
| controller | `UI.UILWAlliance.UILWAllianceGift.Controller.UILWAllianceGiftCtrl` |
| collect all | `Ctrl:OnGetAllBtnClick(type)` — `debug.getinfo` reports `nparams=2` (self + type); type 1 = ordinary, type 2 = premium. Sends `alliance.reward.allreceive {type}` |
| data manager | `DataCenter.AllianceGiftDataManager` — `GetGiftInfoList(type)` (errors without a `type`, confirming the per-type shape), `GetRedPointNum()` = total unclaimed, `SetAllGiftReceiveByType(type)` (the manager-side claim) |

**Why the controller, not the data manager.** The player pressed real buttons, and
the two collect buttons read the loaded gift list, so the window must be open first.
Firing the data-manager `SetAllGiftReceiveByType` headlessly (with no window) sent
nothing on the wire; the real click path is the controller's `OnGetAllBtnClick`,
which is what the recipe drives.

### Acceptance

Ran live through the daemon, mirroring the recipe:

```
OpenWindow(UILWAllianceGift)            -> top window = UILWAllianceGift
Ctrl:OnGetAllBtnClick(1)                -> ok  (ordinary tab; no-op when empty)
Ctrl:OnGetAllBtnClick(2)                -> ok  (premium tab)
Ctrl:CloseSelf()                        -> top window = nil (back to HUD)
```

`OnGetAllBtnClick(2)` **collected the premium gifts in-game** (observed by the user
watching the client). That is the acceptance signal — state over screenshots, and
here the visible in-game claim is the state. (The wire sniffer running alongside
this probe mostly logged `down`/keepalive frames and missed the `up` claim; the
original human recording did capture the `up` commands, which is what the mapping
above rests on.)

## The "collected gifts" modal

A non-empty collect stacks a reward-list modal ("you received …") on top of the
gift window, and it shows up often. It has to be dismissed **between** the two
collects too, because the second collect's guard needs the gift window on top.

`dismiss_reward_popup` closes the top window only when its name carries `Reward`
or `GetGift` — the whole reward-show family (`UIGetRewardView`, `UIRewardShow`,
`UICommonRewardTip`, `UILWGetGiftView`, `UIGiftPackageRewardGet`, …). That guard
is provably safe: the gift window is `UILWAllianceGift` (no `Reward`, no `GetGift`)
and HUD windows match neither, so it can never close them — a no-op when no modal
is up.

**Caveat:** at authoring time `GetRedPointNum()` was 0, so no modal could be raised
to read its exact window name; the popup is matched by family, not by a pinned name.
It closed nothing wrongly in a full dry run (open → collect ×2 → dismiss ×2 → close
left the gift window on top throughout, then the HUD). Confirm the exact popup name
on the next real collection (`GetRedPointNum() > 0`) and tighten the match if needed.
