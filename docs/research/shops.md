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

`shopGoodsNumDic` was empty on the account this was read from even where goods had been
bought, so **the count is asked for, never read off that dictionary**.

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
* `actions/buy_shop_goods.md` — one row, by a person's press, with the price said first.
* `actions/autobuy_shop_goods.md` — the order of preference, walked from the top, within
  the quota, within the diamond ceiling and within the purchases-per-run ceiling. Ships
  OFF; the ceiling on diamonds is 0 until somebody types one.
* `panel/runtime/shops_live.py` — the ear: one reading when the client gets into the game
  (`bus.GAME_READY`), one when a balance push says something moved (debounced hard —
  `push.resource.item.update` is the noisiest push in the game), one after a purchase of
  ours, and **no clock anywhere** (`CLAUDE.md`, «A STATISTIC IS NOT REFRESHED BY HAND»).
* `panel/tabs/shop.py` — the phone's page: the shelf picker, the goods as the game's own
  cells, the price and what is left of the quota, «Купить» behind a confirmation, and the
  autobuy's order behind each row's gear.

## 5. The shelves' own names

The client keeps them as locale KEYS — `CommonShopManager:GetDecorationShopName()` answers
`store_name_5`, and the family runs `store_name_1..7` (Alliance, Honor, Campaign, Season,
Cosmetics, VIP, Diamond). **No Lua entry point that turns a key into a word was found**:
`LanguageManager`, `Language.Get`, `LocalController:getText` and four more all answer
nothing, and the global `Language` is the enum of language ids rather than a table of
text. So the panel names the eight shelves it knows with its own locale keys — filled from
the GAME's own tables through `tools/game_locale.py`, which is the rule
(`CLAUDE.md`) — and any other shelf the client hands over is drawn by its number.
