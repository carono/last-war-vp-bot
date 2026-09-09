# The shops, read and spent from the panel (#2666)

**Question asked:** «Доделываем магазины. Суть их в том, что бы в панели было
дублирование доступных магазинов, что бы в них отображались вещи картинками как в игре,
иметь возможность купить тот или иной предмет, а так же настроить автопокупку по
приоритету.»

Everything below was read off a live client through the panel's own web API (dev recipes
under `actions/dev/`) on 2026-09-09. What is written down is the SHAPE — the manager, the
field names, the message and its payload — never one account's numbers.

The census of what each shop tab SELLS, and the four claims in the shop that cost
nothing, is the older `shop-free-claims.md`; this file is about the shelves themselves.

## 1. Where a shelf lives

    DataCenter.CommonShopManager.goodsShopDic[<shop type>]

One entry per shop type, and the SET is the client's — a panel that writes it down is a
panel that goes wrong the day the game adds a tab. On the account this was read from the
dictionary held fourteen types, of which ten had rows; the eight on the window's own tab
bar are `1, 2, 7, 8, 100, 200, 150, 10` (`docs/research/ui-open.md`) and the rest are held
in the same dictionary without being drawn.

### A row

| field | meaning |
|---|---|
| `id` | the row's own id — what a purchase names |
| `shopType` | the shelf it belongs to |
| `itemId` / `itemNum` | what it hands over, and how many |
| `costNum` | the price |
| `currencyType` | the currency it is priced in |
| `maxTimes` | how many the account may ever buy — **0 means no limit at all** |
| `discount`, `vipLevel`, `subType`, `order` | how the window draws it |
| `configData` | the config line behind it |

What is NOT on the row and has to be asked for:

* **how many have been bought** — `CommonShopManager:GetShopGoodsNum(row)`;
* **whether the account can pay** — `CommonShopManager:CheckCostEnough(row, n)`. It is the
  GAME's own answer and it is used as the gate rather than a sum done in the panel: a
  price can be met out of more than one purse and that arithmetic is the client's;
* **when the quota comes back** — `CommonShopManager:GetLimitShopNextRefreshTs(shopType)`,
  in milliseconds;
* **the item's picture and rarity** — `ItemTemplateManager:GetItemTemplate(itemId)`
  (`icon`, `color`), exactly as the bag reads them, so the panel composes the game's own
  cell and never invents a border;
* **the currency's name** — `ResourceManager:GetResourceNameByType(currencyType)`. It
  answers `<23994>` for some types, which is the client's own «no word for this»; the
  panel then draws the amount alone rather than a name it made up.

`shopGoodsNumDic` is not the counter at all — it holds ONE NUMBER per shop type (how
many rows that shelf has: `1=12 2=27 7=36 …`).

**WHERE «how many have I bought» REALLY LIVES (#2670), and the whole toast storm was
this:**

    CommonShopManager.goodsInfoDic[<shop type>][<row id>] = {id, startTime, boughtTimes}

`GetShopGoodsNum(row)` answers **0 for every row, always** — measured live against an
account that had just spent five quotas. Read straight out of `goodsInfoDic` the same
rows said `7/70035 5/5`, `7/70020 5/5`, `7/70030 1/1`, `7/70026 2500/2500`,
`100/100001 10/10`. So the autobuy walked its whole order every run, re-sent purchases
the server had already given out, and the client answered each with «произошла ошибка» /
«недостаточно предметов» — a toast per refusal, which is exactly what the person
reported. Every recipe here reads `boughtTimes` now; `GetShopGoodsNum` is not used.

Two neighbours that do NOT help: `MsgDefines.UserGetShopNumsInfo` raises for every
argument shape tried (none, int, int+array, array), and `GetCommonShopInfo(type)` sends
but changes nothing in those tables.

**AND A BALANCE IS NOT A CEILING.** Diamonds are `LuaEntry.Player.gold` (32093 on the
account this was read from); `LuaEntry.Resource:GetCntByResType(5)` answers 0 for them,
and answers correctly for alliance points (`1004`). For some currencies — the expedition
shelf's `7`, honour's `40` — it answers 0 on an account that demonstrably has them, so a
zero from it means «cannot see», never «empty»: the recipes trim by a balance only when
they actually read a positive one.

**And it does not move for a purchase made this way.** Measured live on 2026-09-09: a row
was bought, the item arrived in the bag (1004 → 1005) and `GetShopGoodsNum` read 0 before
and 0 after. The client keeps that counter up to date from the shop PAGE, which the panel
never opens. So the counter is what the panel draws for «сколько уже куплено», and the
PROOF that a purchase landed is **what the bag holds, before and after** — a proof that
read the counter reported every working purchase as a failed one, which is exactly what it
did until this was found.

## 2. What a purchase puts on the wire

`MsgDefines.BuyCommonShopGoods` → **`user.shop.buy.new`**, and its body was read WITHOUT
sending a byte, with the `NewEmpty` + recording `sfsObj` trick from `alliance-train.md`:

```
user.shop.buy.new{PutInt:id PutInt:num PutSFSArray:goodsArr}
```

and the arguments are positional, in this order:

```lua
SFSNetwork.SendMessage(MsgDefines.BuyCommonShopGoods, row.id, {}, count)
```

`goodsArr` is what the window fills when a purchase is paid out of RESOURCE ITEMS (the
«use up the stack in the bag first» path); a purchase paid with the shelf's own currency
sends it empty. Sent as a bare number in place of the array, the message raises inside
the client's own `BuyCommonShopGoodsMessage.lua` — which is how the argument order was
found in the first place.

**Confirmed live on 2026-09-09**, with the person's permission and on the cheapest row of
the alliance shelf: the send above, and the resource item it hands over went up by exactly
one in the bag. The alternative reading of the payload — `id` as the SHOP type with the
rows inside `goodsArr` — was never needed and is not what the client sends.

Two neighbours of it, read the same way and not used: `user.get.shop.info{PutInt:type}`
asks the server for one shelf, `user.shop.refresh{PutInt:type}` buys a re-roll.

**«Сверкающий рынок» is a different message and already had one** — `blue.shop.buy`,
proven live in #2636 (`glittering-market.md`). `actions/buy_shop_goods.md` therefore CALLs
`buy_glitter_market_goods.md` for that shelf instead of growing a second implementation.

## 3. The storefronts that want money

They are drawn and never pressed, and that is not a gap: **no message buys one**. A pack
is bought through the platform's own purchase, so a button would be a button that cannot
work, and the PRICE is not on this side of the client at all — what a pack costs is the
store's number in the player's own money.

What IS readable headless is the week-card shelf — `WeekCardManager:GetWeekCardList()`,
five rows with `id`, `status`, `endTime` and the reward they hand over. The gift mall's
own tabs (`LWBuyDiamond`) are not: `DailyPackageManager:GetVisibleIds()` raises until the
window has asked the server for the page, and the panel does not open windows.

## 4. What the panel does with all this

* `actions/read_shops.md` — one round trip against the client's own memory, no question on
  the wire. It packs every row of every shelf into one line (fifteen fields, the name
  last) and the money shelf into another.
* `actions/buy_shop_goods.md` — one row, by a person's press, with the price said first,
  and the modal it ends in shut behind it: the recipe puts in the reward EAR of #2027 /
  #2642 (`watch_reward_popups`) before it sends and drains it afterwards
  (`collect_reward_popups`), so the window the client raises is closed by the client the
  instant it opens — and only a window the game has just called a reward for. Never
  `DestroyAllWindow` (#2670).
* `actions/autobuy_shop_goods.md` — the order of preference, walked from the top, within
  the quota, within the CURRENCY's own ceiling and within the purchases-per-run ceiling. Ships
  OFF. It covers EVERY shelf, the diamond ones included — the person's decision, in their
  words, «любая автопокупка» — and the safeguard is a CEILING on what one run may spend in
  diamonds (300 by default, the number already settled for the energy refill in #2390)
  rather than a currency the errand may not touch. A diamond row is trimmed to what the
  ceiling still has room for, never dropped.
* `panel/runtime/shops_live.py` — the ear: one reading when the client gets into the game
  (`bus.GAME_READY`), one when a balance push says something moved (debounced hard —
  `push.resource.item.update` is the noisiest push in the game), one after a purchase of
  ours, and **no clock anywhere** (`CLAUDE.md`, «A STATISTIC IS NOT REFRESHED BY HAND»).
* `panel/tabs/shop.py` — the phone's page: the strip of every shelf, the goods as the
  game's own cells, the price and what is left of the quota, «Купить» behind a
  confirmation, and the autobuy's order behind each row's gear.

**HOW THAT PAGE IS DRAWN, and why it was redrawn (#2670).** The picker was a dropdown on
a card of its own, and a screen of more than two cards is drawn ONE card at a time behind
a chip strip — so the phone opened the card marked `main`, saw «Магазин бриллиантов», and
the other eleven shelves were a `select` inside a chip nobody had a reason to press. The
person's report was exactly that: «вижу магазин бриллиантов, других не вижу». Two
consequences, and both are contracts now:

* **the shelves are a STRIP on the goods card itself** — the field kind `chips`, which is
  `choice` wearing the chip the card strip and the sort bar already use. Every shelf is on
  screen, which is the whole difference between it and a dropdown. Still ONE shelf's goods
  in the payload: twelve at once is some eighty kilobytes every two and a half seconds;
* **a shelf that this panel has no word for is called by its NUMBER** — «Магазин №9».
  Two unnamed shelves both saying «Магазин» is one chip nobody can choose, and a name
  invented for a shelf is worse than a number (§5).

The goods are `layout: "grid"`: a small square tile with the item's own picture, how many
one purchase gives stamped on its corner, the name on one line and the price under it —
the game's own shape, and the whole tile is the purchase, which is the game's own gesture.

**HOW THE AUTOBUY'S ORDER IS SET (#2670), and it is no longer a typed number.** The
person's words: «В настройках товара нужна галка покупать все, и галка покупать
автоматически. Сортировка по приоритету, сделай драг-енд-дроп… Те что мы выбрали для
автопокупки, должны быть отделены от остальных». So:

* **the gear on a tile holds two ticks and a number** — «Покупать автоматически» (is the
  row in the order at all: on puts it at the END of the list, off drops it), «Покупать
  всё» (`count = 0` in the plan, which the recipe reads as «as many as the quota, the
  purse and the ceilings allow»), and how many per run for a row that is not «all»;
* **where a row stands is DRAGGED**, by the grip in the corner of its tile, and the whole
  new order travels back as one `set` press with the key `order`. The priority box is
  gone: a number and a gesture that both claim to set the same thing is one of them
  lying;
* **EVERY SHELF HAS AN ORDER OF ITS OWN**, and it is drawn as its own section above that
  shelf's goods — the person's correction, in their words: «Очередь для автопокупки у
  каждого магазина своя, не нужно все в одном месте выводить, меняем магазин, меняется
  очередь». So the block shows THIS shelf's queue, «№1» means «first on this shelf», and
  a drag moves only the rows it names: the named rows' slots in the plan are refilled in
  the new order, so the other shelves keep theirs. A row in the queue is not drawn a
  second time among the shelf's own goods.

  The STORE is still the one plan string — a row already carries the shop it belongs to
  (`kind:shop:id:count`), so «per shelf» is a way of READING it, not a second copy of
  anything (`CLAUDE.md`: one state, several places that draw it).

**A ROW WHOSE QUOTA IS SPENT IS GREY AND HAS NO BUTTON** (#2670, the person's words:
«Сери иконку предмета, если всё выкуплено»). The tile's picture greys, «осталось 0»
becomes the mark «выкуплено», and the panel does not send the press at all — a picture
that only LOOKS spent while its button still puts `user.shop.buy.new` on the wire is a
refusal a second late. `web_press` refuses it too, off the last reading, for the press
that arrives from an older screen. The KNOBS stay: the quota comes back on the shelf's
own reset, and putting a row into the queue is exactly what somebody does while looking
at one they have just used up.

**A CEILING BELONGS TO A CURRENCY, NOT TO A RUN** (#2670, the person's answer to «потолок
общий или на магазин»: «у каждого магазина своя валюта»). One number over every shelf
added alliance points to diamonds to honour, which is not a sum anybody can mean. So the
errand's argument is `caps` — «currency:limit», comma separated — and it is typed where it
is spent: the gear beside a shop's own heading edits THAT shop's currency, «Таймеры» draws
the same value as the one line it is stored as. A currency that is not named has no
ceiling: it is earned by playing and cannot be bought, so the row's own quota is already
the limit. `5:300` ships — the diamonds, the one irreversible spend, at the number settled
in #2390 — `5:0` means «not one diamond», and `-1` takes a ceiling away. A profile written
before this keeps `diamond_cap`, which is read through when `caps` says nothing.

The plan string is unchanged in shape — `kind:shop:id:count`, comma separated — so
nothing had to be migrated; what changed is that **0 now means «all of it»** rather than
being clamped up to 1, and the recipe reads it that way (`actions/autobuy_shop_goods.md`).

## 5. The shelves' own names

The client keeps them as locale KEYS — `CommonShopManager:GetDecorationShopName()` answers
`store_name_5`, and the family runs `store_name_1..7` (Alliance, Honor, Campaign, Season,
Cosmetics, VIP, Diamond). **No Lua entry point that turns a key into a word was found**:
`LanguageManager`, `Language.Get`, `LocalController:getText` and four more all answer
nothing, and the global `Language` is the enum of language ids rather than a table of
text. So the panel names the eight shelves it knows with its own locale keys — filled from
the GAME's own tables through `tools/game_locale.py`, which is the rule
(`CLAUDE.md`) — and any other shelf the client hands over is drawn by its number.
