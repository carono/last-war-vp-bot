# «Сверкающий рынок» — what it gives away, what it sells, and when it runs

The event the game calls *Glittering Market* (`activity_name_5301`, ru «Сверкающий
рынок»). Internally it is the **blue shop**: every one of its locale keys is
`activity_blue_shop_*`, its messages are `blue.shop.*`, and the client's manager is
`LWTitaniumBlueStoreManager`.

Everything below was read off a live client on 2026-09-08 (#2636). What is written down
is the SHAPE — the manager, the messages, the field names, the config ids — never one
account's numbers.

## What a person sees

* a **daily free reward**, and on the day this was read it was **100 diamonds** — that is
  the «забрать алмазы бесплатно» half, and it is one message with no cost at all;
* a shop of ~24 rare goods priced in **Glitter Coins** (`item 654001`, ru «Блестящая
  монета») — hero-shard boxes, skill chips, equipment blueprints, armament materials,
  decorations, a permanent skin;
* three of those goods cost **nothing** and still have a per-event quota;
* a **progress ladder** of five chests at 100 / 400 / 1 000 / 4 000 / 10 000 points,
  where the points come from BUYING coins;
* and the coins themselves, sold in packs. Those packs are the one part of the event that
  is not on the wire — see «What cannot be automated» below.

## The manager

    DataCenter.LWTitaniumBlueStoreManager

| field | meaning |
|---|---|
| `activityId` | the run's id — **a STRING**, and every message wants it as one |
| `activityType` | the event's kind (`156` on the client this was read from) |
| `startTime` / `endTime` | the run's borders, in **milliseconds** |
| `dayRewardList` | today's free reward: `{count, itemId, rewardType}` |
| `dayRewardReceiveState` | `0` while today's free reward is still waiting |
| `dayRewardLastReceiveFreeTime` | when it was last taken, server seconds |
| `dayRewardNextRefreshTime` | when the free reward and the daily rows restock |
| `activityFreeRewardData` | the same reward as an object, with `CanGetFreePack()` |
| `productList` | the shop, keyed by display order (below) |
| `boxRewardsList` | the five progress chests: `{index, targetCount, rewardsList}` |
| `boxReceiveList` | which of them have been claimed |
| `totalScore` | the progress the ladder is measured against |
| `para_4`, `para_7` | the coin-pack groups, copied off the activity's config row |

Useful methods on it: `CanGetFreePack()`, `GetBoxRewardState(index)`,
`GetBoxRewardMaxValue()`, `GetRedNum()`.

**Nothing has to be asked for.** The whole record arrives with the activity and is kept
up to date by the server (`ParseTitaniumBlueStoreMessage`, `UpdateDailyRewardData`,
`UpdateProductDataAfterBuy`, `UpdateTotalScoreData`), so a reading is one round trip
against the client's own memory and not one question on the wire.

### A product

    {id, displayOrder, costId, costNum, costResId, costResNum,
     buyTimeLimit, buyTimes, refreshType, nextResetTime, extraDisplay,
     rewardList = {{count, itemId, rewardType}}}

`id` is a **string**, like `activityId`. `costId` is `654001` (the coin) on every priced
row; `costNum` is the price. `buyTimeLimit` minus `buyTimes` is what is left, and
`refreshType = 1` means that quota comes back at `nextResetTime` — the rest are for the
whole run.

**Three rows are priced at nothing** (`costNum = 0`, `costId = 0`) and still carry a
quota. They are as free as the daily reward is, and the collecting recipe takes them.

## The messages

| `MsgDefines` | on the wire | what it does |
|---|---|---|
| `BlueShopDayReward` | `blue.shop.day.reward` | takes today's free reward |
| `BlueShopBuy` | `blue.shop.buy` | buys one row of the shop |
| `BlueShopBoxReward` | `blue.shop.box.reward` | claims one progress chest |
| `PushBlueShopSc` | `push.blue.shop.sc` | the score moved — the event's only push |

**The payloads were found by trying them on the live client**, because the sender's own
Lua cannot be read any more (the sandbox refuses `string.dump`). Both of the two that
matter are BARE ARGUMENTS and not a table, and the ids must stay STRINGS — a table, and
a numeric id, are both accepted by the client and answered by silence:

```lua
-- today's free reward. Confirmed live: dayRewardReceiveState 0 -> 1.
SFSNetwork.SendMessage(MsgDefines.BlueShopDayReward, D.activityId)

-- one purchase. Confirmed live on a row priced at nothing: buyTimes 0 -> 1 -> 2.
SFSNetwork.SendMessage(MsgDefines.BlueShopBuy, D.activityId, product.id, count)
```

What did NOT move anything, so nobody tries them again: `SendMessage(msg)` with no
argument, `{}`, `{activityId = …}`, `{id = …, num = …}`,
`{activityId = …, id = …, num = …}`, `{activityId = …, productId = …, num = …}`,
`{activityId = …, id = …, buyNum = …}`, `(activityId, {id = …, num = …})`,
`(id, num)`, `{goodsId = …, num = …}`, and the same three arguments with a NUMERIC id.

The chest claim is written the same way — `SendMessage(MsgDefines.BlueShopBoxReward,
D.activityId, index)` — and has **not been proved live**: the account it was read on had
no points, so no chest was claimable. It is gated on the score and on `GetBoxRewardState`
rather than sent blind.

## When it runs, and how often

The run's own borders are on the manager (`startTime`, `endTime`, milliseconds) and
nothing has to be computed from a calendar. What the CALENDAR adds is how long a run is
and that it comes back at all — the activity's config row, read live:

    LocalController.instance():getLine('activity', <activityId>)

| column | value | meaning |
|---|---|---|
| `name` | `activity_name_5301` | the event's name key |
| `desc` / `bannerDes` | `activity_desc_5301` / `activity_blue_shop_desc1` | its wording |
| `icon` | `zyf_tailanshangcheng_biaoqian_icon` | its own sprite |
| `calendar_display` | `1` | it appears in the game's event calendar |
| `limitTime` | `6` | **the run is six days long** |
| `timeType` | `200` | the schedule kind the server drives it by |
| `type` | `156` | the same activity type the manager carries |
| `tableInfo` | `acitivity_blue_shop` | its own config table (the typo is the game's) |

Six days is exactly what the live borders said: `endTime - startTime` was one second
under six days. **The dates are never written into the panel** — the card reads
`startTime`/`endTime` off the manager, and `dayRewardNextRefreshTime` for the restock.
When the run ends the manager stops answering and the card says the event is not running;
the next run brings its own borders with it, which is what «регулярная» costs us: nothing.

## What cannot be automated, and why it is not a gap

The Glitter Coins themselves are sold as PACKS, and the packs are not on the wire. The
pack groups are named on the activity's config row (`para_4`, `para_7`) and the manager
answers `GetGiftPackId()` / `GetActivityGiftPackId()` with them, but:

* no manager anywhere in `DataCenter` holds the pack — a full sweep of every manager to a
  depth of four found the two ids nowhere else;
* no config table on the client has a row for them;
* there is no `MsgDefines` entry that buys one — the only ways in are
  `OpenGiftPackWindow()` and `OpenShopPanel()`, which are windows.

So buying coins is a purchase made in the game's own pack window, by the person. What the
panel CAN spend is the coins already bought, and that is what
`actions/buy_glitter_market_goods.md` does — one named row, its price said out loud
first, and switched off by default, because a coin spent does not come back
(`CLAUDE.md`, «A new ability ships SWITCHED ON» — and its one exception).

## What the panel does with all this

* `actions/read_glittering_market.md` — one reading: is it running, when it ends, what is
  free right now, how many coins the account has, what the ladder stands at.
* `actions/collect_glittering_market.md` — the free half, on by default: today's free
  reward, every row priced at nothing that still has a quota, and any progress chest
  already earned. It can spend nothing at all.
* `actions/buy_glitter_market_goods.md` — the spend, off by default: one row of the shop,
  bought as many times as it is told, with the price named before anything is sent.
* `panel/runtime/market_live.py` — the last reading, kept where both front-ends find it.
  It is taken when the client gets into the game (`bus.GAME_READY`) and again on
  `push.blue.shop.sc`, and never on a clock (`CLAUDE.md`, «A STATISTIC IS NOT REFRESHED
  BY HAND»).
