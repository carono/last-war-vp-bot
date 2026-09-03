# The shop, tab by tab: what it gives for nothing (#2395)

**Question asked:** «зайди в магазин, и найди все бонусы, что можно взять, там несколько
вкладок, пройдись по всем».

**Short answer.** Two things in the whole shop cost nothing, and both live on the gift
mall's week-card page: the **daily free gift**, handed out whether or not a card was ever
bought, and the **daily reward of the week cards the account already holds**. Everything
else on every tab has a price. The ability that takes those two is
`actions/collect_shop_freebies.md`, and the reading behind it is
`actions/read_shop_freebies.md`.

Everything below was read off the live client on 2026-09-03 through the panel's own web
API (`POST /api/actions/run` playing throwaway recipes under `actions/dev/`). Nothing was
bought and no currency of any kind was spent.

## 1. There are TWO windows called «магазин», and only one of them is the shop

| what a person calls it | how it opens | what it is |
|---|---|---|
| «Магазин» | `UIManager.Instance:OpenWindow(UIWindowNames.UICommonShop)` | the eight-tab shop that spends earned currencies |
| «Магазин» (the bottom bar) | `GoToUtil.GoGiftMall()` → window **`LWBuyDiamond`** | the seven-tab gift mall that spends money |

Both were opened, every tab of both was walked, and the census below is of both.

## 2. `UICommonShop` — eight tabs, 175 goods, not one of them free

The tab bar is keyed by a **shop type**, not an index (`w.View.shopTabTypeList` =
`{1, 2, 7, 8, 100, 200, 150, 10}`; the titles are in `docs/research/ui-open.md`). Every
row of every tab lives in `DataCenter.CommonShopManager.goodsShopDic[shopType]`, and a
row carries `costNum` and `currencyType`.

| shop type | tab | goods | currency |
|--:|---|--:|---|
| 1 | Магазин бриллиантов | 8 | 5 |
| 2 | VIP-магазин | 27 | 5 |
| 7 | Магазин Альянса | 36 | 1004 |
| 8 | Магазин чести | 16 | 40 |
| 100 | Магазин Экспедиции | 20 | 7 |
| 200 | Магазин Сезона | 18 | 7 |
| 150 | Магазин обликов | 6 | 7 |
| 10 | Магазин купонов | 13 | 7 |
| 9, 11 | not on the bar (held in the same dictionary) | 3, 6 | 7 |
| 3–6 | empty on this account | 0 | — |

**Goods with `costNum == 0`: none.** The scan was run twice — once cold, and once after
opening the window and switching through all eight tabs, so that every tab's rows had
been fetched from the server. Same answer both times.

## 3. The gift mall (`LWBuyDiamond`) — seven tabs

Read off `w.View.tabs`, in the order the bar draws them:

| # | tab id | `_type` | what it is | free? |
|--:|--:|--:|---|---|
| 1 | 9991_1110004 | 189 | a running activity | no |
| 2 | 1250000 | 17 | «Постоянный подарок» — a permanent pack | no, money |
| 3 | 1140000 | 2 | Месячная карта | no, money |
| 4 | 1050000 | 20 | **Недельная карта** | **the two free claims live here** |
| 5 | 1030000 | 103 | Ежедневные спецпредложения | no, and see §5 |
| 6 | 2010000 | 108 | Магазин золотых слитков | no, gold bricks are a currency |
| 7 | 9999999 | 110 | «Наборы» (pop-collect packs) | no, money |

## 4. The two claims that ARE free

Both live on `DataCenter.WeekCardManager`, and both gates are the client's own record —
filled at login, kept up to date by the server's pushes — so reading them costs one VM
round trip and puts nothing on the wire.

### 4.1 The daily free gift

* **Gate:** `WeekCardManager:CheckIfHasFreeReward()` — the game's own answer about today.
  There is no «last taken» to keep and no clock to consult.
* **Press:** `SFSNetwork.SendMessage(MsgDefines.ClaimWeekCardFreeReward)` →
  `receive.week.card.daily.free.reward`, no payload.
* **Confirmed live.** Before: `free=true`. After: `free=false`, `lastRewardTime` moved to
  the moment of the press, and the reply arrived with `push.resource.item.update` beside
  it:

  ```
  in[push.resource.item.update{resource_items=tbl}
   || receive.week.card.daily.free.reward{_id=…, _time=6, lastRewardTime=…, reward=tbl}]
  free=false
  ```

### 4.2 The daily reward of the cards already held

* **Gate:** each card's own `GetStatus()` on the rows of `GetWeekCardList()` —
  `1` = not held or expired, `2` = held and today's reward waiting, `3` = held and today's
  taken. The status is what moved when the claim landed, so it is the gate AND the proof.
* **Press:** `SFSNetwork.SendMessage(MsgDefines.ClaimAllWeekCardRewardMessage)` →
  `receive.all.week.card.reward`, no payload, one message for every card at once.
* **Confirmed live.** A card read `status=2 lastRecvTime=<yesterday>` before the press and
  `status=3 lastRecvTime=<now>` after it, with `cards` and `reward` in the reply.
* Claiming this **buys nothing**: the card was paid for once and pays out every day of its
  week. A claim that is not made is a day of that card thrown away.

## 5. What is NOT free, and why each one is excluded

* **Every row of `UICommonShop`** — §2. All 175 have a price.
* **«Ежедневные спецпредложения»** (`DataCenter.DailyMustBuyManager`). It looks like a
  free ladder — five stages, `ClaimRewardAtStage`, `GetCanGetStageNum` — but the score
  that climbs it is a PURCHASE score: this account reads `score=0/300`, `can=0`, and the
  stages are `10 / 50 / 100 / 200 / 300`. The rewards are behind money.
* **Магазин золотых слитков.** Gold bricks are a currency (`GoldBrickDataManager:
  GetGoldBrickCount()` = a balance). `GoldBrickTemplateManager:GetFreeGoldBrick()` reads
  `0` on this account.
* **Месячная карта.** `LWBuyDiamondCtrl:ClaimDailyRewards()` sends `month.card.reward`;
  it was pressed once with an ear on the wire and nothing came back, which is what an
  account with no active month card should look like. Not shipped: a press nobody has
  seen answered cannot be told from a refusal.
* **«Постоянный подарок», «Наборы», the activity tab.** Money.

## 6. The two free-SHAPED claims that were pressed and are NOT shipped

Both are named here so the next agent does not spend the afternoon finding them again.

* **`receive.week.free.reward`** (`MsgDefines.BuyFreeWeeklyPackage`) — the server answered
  `{success=true}` and **nothing moved**: no gate flipped, no item push arrived,
  `lastRecvFreeTime` unchanged. Either it wants a payload nobody has pinned or it is the
  ack of something already taken. Not shipped.
* **`decoration.shop.receive.free.reward`** (`MsgDefines.DecorationShopReceiveFreeReward`)
  — the decoration shop advertises a free daily reward
  (`ActivityListDataManager:GetActHasFreeDailyReward(1051010)` = `true`, and the activity
  is `activity_name_98800`, the decoration direct-purchase gift page). The claim came back
  `{errorCode=E000000}` with the gate still open. Not shipped for the same reason.

`MsgDefines` holds **33** message names containing `free`; the ones above are the only
ones that belong to a shop tab. The rest belong to activities, buildings and marches and
are somebody else's ability.

## 7. How to re-read any of this

Dev recipes through the panel's web API, so the client is never touched by hand:

```
POST /api/actions/run   {"profile": "<name>", "name": "<a recipe under actions/dev/>"}
```

The gates in one line, with no window opened:

```lua
local M = DataCenter.WeekCardManager
M:CheckIfHasFreeReward()                       -- today's free gift
for _, c in pairs(M:GetWeekCardList()) do print(c.id, c:GetStatus()) end   -- 2 = due
```
