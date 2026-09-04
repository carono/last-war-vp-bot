# The shop, tab by tab: what it gives for nothing (#2395)

**Question asked:** «зайди в магазин, и найди все бонусы, что можно взять, там несколько
вкладок, пройдись по всем».

**Short answer.** Four claims in the whole shop cost nothing: the **daily free gift** of
the week-card page, handed out whether or not a card was ever bought; the **daily reward
of the week cards the account already holds**; the **daily reward of a running month
card**; and — added on the second pass, after the person said «раздел акции, там боевой
пропуск, появляются бонусы» — the **levels of every event BATTLE PASS that are earned and
not yet paid out** (§8). Everything else on every tab has a price. Buying a subscription is a purchase and
is never made — claiming what a running one owes costs nothing, and a day it is not
claimed is a day of it thrown away. Three more claims were pressed blind on the first pass, answered
with a shrug and written off as «not shipped»; the third pass (2026-09-04, «делай, там
разберёмся») found a real GATE behind each of them and they are now claimed like the rest
whenever that gate is open — §6. The ability that takes all seven is
`actions/collect_shop_freebies.md`, and the reading behind it is
`actions/read_shop_freebies.md`. There is ONE errand for them (every six hours), because
that is what the person asked for.

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

## 4. The three claims that are free EVERY day

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

### 4.3 The month card's daily reward — and the argument that decides everything

* **Gate:** `MonthCardNewManager:CheckIfMonthCardActive()` and `CheckIfHasGolloesGift()`.
  The second is the game's own answer about today; it flipped to `false` the moment the
  claim landed. The card's own record — `GetGolloesMonthCard()` — carries `monthCardId`,
  `buyTime`, `endTime` and `lastClaimTime`.
* **Press:** `SFSNetwork.SendMessage(MsgDefines.ClaimGolloesDailyReward, <monthCardId>)`
  → `month.card.reward`.
* **THE ARGUMENT IS THE WHOLE OF IT, and it cost two probes to find.** Sent BARE — which
  is what the mall's own `LWBuyDiamondCtrl:ClaimDailyRewards()` appeared to do — the
  message was answered by **silence**: nothing on the wire, `lastClaimTime` unmoved, the
  gate still open. Sent with the card's `monthCardId` it came back at once:

  ```
  push.resource.item.update{resource_items=tbl}
  month.card.reward{_id=…, _time=11, gold=…, golloesMonthCard=tbl, reward=tbl, tipsDay=0}
  ```

  and `lastClaimTime` moved to the second of the press with `CheckIfHasGolloesGift()`
  → `false`. A claim that answers with silence is not a claim that failed to be
  understood — it is one that was sent without what it asks for.

## 5. What is NOT free, and why each one is excluded

* **Every row of `UICommonShop`** — §2. All 175 have a price.
* **«Ежедневные спецпредложения»** (`DataCenter.DailyMustBuyManager`). It looks like a
  free ladder — five stages, `ClaimRewardAtStage`, `GetCanGetStageNum` — but the score
  that climbs it is a PURCHASE score: this account reads `score=0/300`, `can=0`, and the
  stages are `10 / 50 / 100 / 200 / 300`. The rewards are behind money.
* **Магазин золотых слитков.** Gold bricks are a currency (`GoldBrickDataManager:
  GetGoldBrickCount()` = a balance). `GoldBrickTemplateManager:GetFreeGoldBrick()` reads
  `0` on this account.
* **Buying anything at all.** A subscription, a pack, a skin, a diamond bundle. What a
  RUNNING subscription owes is claimed (§4.3); nothing is ever bought.
* **«Постоянный подарок», «Наборы», the activity tab.** Money.

## 6. The three claims that are open only some days — and the gate behind each

The first pass pressed all three with no gate, got `success=true` or `E000000` back and
wrote them off. That was the wrong conclusion drawn from the right observation: the
sends were answered that way **because there was nothing on offer**, and a claim sent
blind cannot tell «nothing today» from «broken». Read live on **2026-09-04** the gate
turned out to exist for every one of them, and all three were CLOSED that day — which is
exactly what the sends had been saying.

| claim | message | the gate, in the client's own record | 2026-09-04 |
|---|---|---|---|
| the decoration shop's free spin | `decoration.shop.receive.free.reward` (`MsgDefines.DecorationShopReceiveFreeReward`), **`PutInt id`** — the shop row's own `id` | `CommonShopManager.decorationShopDic[150]`: `freeCount > 0` **and** `freeRewardId > 0` | `freeCount = 0`, `freeRewardId = 0`, `IsSaleInDecorationShop()` = `false`, no goods (`GetDecorationShopItemNum()` = 0) |
| the recharge page's free reward | `receive.week.free.reward` (`MsgDefines.BuyFreeWeeklyPackage`), **no payload at all** | `RechargeManager:GetIsCanReceiveFreeReward(type)` over types `0…8` | every type `false`; only type `1` has a `GetFreeRewardIdByType`, and `RechargeManager.freeRewardInfoDic[1]` held that game day's own claim stamp |
| the golloes camp's daily free one | `receive.golloes.daily.free.reward` (`MsgDefines.ClaimGolloesFreeReward`), **no payload** | `DataCenter.GolloesCampManager:CheckIfCanClaimFreeGolloes()` | `false`, with the camp empty: `GetGolloesCount()` = 0, trader and explorer states `0` |

Three things that cost time and are worth writing down once:

* **`GetActHasFreeDailyReward(1051010)` is NOT the decoration gate.** It reads `true` the
  whole time — it is the ACTIVITY advertising a free daily, not the account's counter.
  The counter is `freeCount` on the shop row, and asking the server for the page
  (`CommonShopManager:RequestDecorationShopInfo()`) does not conjure one: on a day the
  shop is not selling there is no attempt to spend.
* **The recharge one is a DAILY gate, not a purchase score.** It looked like a top-up
  reward and it is not. `freeRewardInfoDic` keeps a stamp per type: on 2026-09-04 type
  `1` held `1788517530`, which is **after** that game day's zero (`GetTomorrowZero()`
  minus a day), so it had already been taken that day and the gate had closed behind it.
* **The golloes claim has nothing to do with the month card.** `MsgDefines` says
  «Golloes» in both names — `ClaimGolloesDailyReward` is `month.card.reward` (§4.3) — but
  this one belongs to `GolloesCampManager`, the camp. Its own manager holds the gate, and
  `MonthCardNewManager` has no free-reward method at all.

The wire shapes were read **without sending a byte**, with the `NewEmpty` + recording
`sfsObj` trick: two of the three put nothing on the wire, and the decoration one asks its
param for `id` twice and puts a single `PutInt id`.

### `E000000` is a REFUSAL, not an «all clear»

The decoration claim came back `{errorCode=E000000}` and it was read here at first as
«accepted». It is not. The same code arrived on `week.month.card.reward.all` **with the
reason attached**:

```
week.month.card.reward.all{errorCode=E000000, errorMsg=already received}
```

— sent a second after the month card had genuinely been claimed. So `E000000` is the
generic «no» and the sentence beside it is where the answer is. Anything read off an
`errorCode` in this game is read together with `errorMsg` or not at all.

`week.month.card.reward.all` (`MsgDefines.ClaimSubscriptionsReward`) is worth a line of
its own: it looks like ONE message that would cover §4.2 and §4.3 together. It has only
ever been seen refusing, so it is not shipped in place of the two proven sends — but it
is the first thing to try if either of them ever changes shape.

`MsgDefines` holds **33** message names containing `free`; the ones above are the only
ones that belong to a shop tab. The rest belong to activities, buildings and marches and
are somebody else's ability.

## 8. The battle pass of the «Акция» tab — the fourth free claim (#2395, second pass)

The first census wrote the mall's activity tab off as «праздничные наборы · деньги». That
is true of what it SELLS and false about the tab: what runs there is a **battle pass**,
and its ladder pays out for levels the account earned by playing. Claiming a level costs
nothing. The person said so in one sentence and it was worth a whole second pass.

### Where it lives

| what | where |
|---|---|
| the record | `DataCenter.ActBattlePassData` — one entry per running pass in `.list`, keyed by `activityId` |
| the ladder | `entry.stateInfo[level]` — `normalState` / `hightRewardState` / `specialState`, `1` = the level is REACHED, `0` = not |
| the account's place on it | `entry.battlePass` — `level`, `exp`, `unlock`, `high_unlock` |
| how much is still owed | `ActBattlePassData:GetActRed(activityId)` — a COUNT, `0` when there is nothing |
| the tasks that earn the levels | `entry.taskArr` — `state` `0` not done, `2` / `4` done; **there is no task-claim message at all**, the experience is granted by the server |
| the levels | 50 on one of the two passes seen, 20 on the other; `entry.extraExp` is what an overflow box costs beyond the last level |

Two passes were running when this was written; the recipe never names one — it walks
`.list`, so a pass that starts tomorrow is read the same way.

### The three families, and only one of them is the live one

This is the part that cost the time, and it is written down so nobody pays for it twice:

| family | messages | what the server said |
|---|---|---|
| v1 | `receive.battlepass.all.reward`, `.stage.`, `.task.`, `.extra.` | `E000000 battle pass not exist` — and `get.battlepass.info` answered **`E000000 activity is new battlePass`**, which is the whole clue |
| season | `receive.season.battlepass.*` | the send leaves and **nothing comes back at all** |
| **bpv2 — the live one** | `receive.bpv2.all.reward`, `receive.bpv2.stage.reward`, `receive.bpv2.extra.reward` | the reward, and the record pushed back |

All of them take the same first field, `PutInt activityId` (read without sending a byte,
with the `NewEmpty` + recording `sfsObj` trick from `alliance-train.md`); the stage one
adds `level` and `type`. The recipe sends **`receive.bpv2.all.reward` and nothing else**:
one message per pass, no level list to get wrong, and the server hands over every level
the account has earned on every track it has unlocked.

### What is free here and what is not

* **Free, and taken:** every earned level of the free track, always; and of the premium
  track when it has ALREADY been unlocked, because unlocking was paid for once and the
  payout costs nothing — the same argument as a running month card (§4.3). The game keeps
  the two apart by itself: a pass whose premium is not unlocked leaves those rewards out
  of `GetActRed`, so a recipe that trusts the count cannot claim what it has not got.
* **Free, and taken when it is there:** the overflow box past the last level,
  `receive.bpv2.extra.reward`. Gated on `level >= <the last level>` **and**
  `exp >= extraExp`; sent early it answers `E000000 not reach max level`.
* **PAID, and never sent:** `buy.battle.pass.level` (`MsgDefines.BuyBattlePassLevel`) —
  buying your way up the ladder. It is not in the recipe and must not be.

### Measured live, 2026-09-03

| pass | before | the one message | after |
|---|---|---|---|
| the 50-level one, premium unlocked | level 40, `GetActRed` = 2 | `receive.bpv2.all.reward` | level 41, `GetActRed` = 0, reward in the reply |
| the 20-level one, free track only | level 14, `GetActRed` = 6 | `receive.bpv2.all.reward` | level 16, `GetActRed` = 0, `push.resource.item.update` beside it |

The level rose because some of what the ladder pays out is pass experience — which is why
the recipe reads the count back afterwards and reports what MOVED rather than what it
sent, exactly as the other three claims do.

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

local P = DataCenter.ActBattlePassData         -- and the battle pass, §8
for id, v in pairs(P.list) do print(id, v.battlePass.level, P:GetActRed(id)) end
```
