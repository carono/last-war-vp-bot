# The bag: where the item list is, and where the pictures are

Task #1469. The «Инвентарь» tab had never shown anything; this is what was found and
what it now reads.

## 1. Why the tab was empty — a name that does not exist

The tab asked for `DataCenter.ItemDataManager`, then `DataCenter.BagDataManager`, then
three method names on whichever answered. A live probe:

```
ItemData                n=6   KEYS[ItemInfos, ItemIdAndUuid, StatusItems, …]
ItemManager             n=2   MT[ItemUseHandle, ItemBuyHandle, …]
ResourceItemDataManager n=13  KEYS[itemList, itemTemplateDic, warehouseStorageMax, …]
ItemTemplateManager     n=9   KEYS[itemDic, heroFrame, typeTools, …]
ItemExchangeManager     n=4
BagDataManager          MISSING
ItemDataManager         MISSING
```

Both guessed names are absent, so every branch fell through the `pcall`s and the tab
drew an empty list with no error anywhere. **Nothing was broken; nothing was ever
connected.** The lesson is the ordinary one — a `pcall` around a guess turns a wrong
name into silence.

`GetItemList()` exists on `ItemData` but answers `nil` when called with no arguments;
the table itself is the reading.

## 2. The list — `DataCenter.ItemData.ItemInfos`

A table keyed by the stack's own uuid, one entry per STACK:

```
key = <32 hex>  {itemId=850113, uuid=<24 hex>, count=1, goods=<config row>,
                 use=1, para1=1, para2=s4, para3=, para4=,
                 newCount=0, preCount=0, redState=true, cbnum=, cbpart=, cbitem=,
                 rightseffect=}
```

Measured on one live account: **417 stacks, 371 distinct item ids.** The game's bag
draws one cell per ID with the total on it, so `read_inventory.md` sums the stacks.

It is **not a push and not a capture.** `push.resource.item.update` — which the panel
already listens for, and which the tab's `inventory_refresh` trigger hangs off — only
says a balance moved; the client applies it to this table itself. The honest re-read is
therefore the table, not the push, exactly as the ghost list works
(`docs/research/world-monsters.md`).

## 3. The item's config row — `DataCenter.ItemTemplateManager`

`GetItemTemplate(itemId)` returns the row `goods` already points at. It carries the
fields the panel needs and answers three of them through helpers that do the locale
lookup:

| what | where |
|---|---|
| name | `T:GetName(id)` — already in the player's language |
| description | `T:GetDes(id)` — likewise |
| picture | row field `icon`, e.g. `icon_item_850409` |
| rarity | row field `color` (= `quality`), 1..6 |
| kind | row field `type` (137 hero shard, 99, 3 resource, 141 …) |
| rarity frame | `T:GetToolBgByColor(colour)` |

The raw row keeps the untranslated keys (`name = item_name_850113`,
`des = item_desc_510050`), so **always go through `GetName`/`GetDes`** — that is the
game's own table for all nineteen of its languages and nothing here is ever translated
by the panel.

**The picture is not derivable from the id.** Item `850113` («a hero shard») wears
`icon_item_850409`. Compute it and you draw the wrong hero.

## 4. The composite icon — the guess was right

The operator's hunch («картинки составные: фон отдельно, картинка отдельно») is exactly
how the game does it. `GetToolBgByColor` answers, for colours 1..6:

```
Assets/Main/Sprites/UI/LWCommon/Sprite/cfm_tongyong_daojukuang_<colour>.png
```

and the picture is `Assets/Main/Sprites/ItemIcons/<icon>`. The frames are **162×170**
(a plate, not a hollow ring — the extra 8 px of height is where the game prints the
count) and every item picture is **154×154**, so the composition ratio is the measured
`154/162`, not a taste call. A seventh frame ships beside the six,
`cfm_tongyong_daojukuang_xuanzhong` — the «selected» highlight.

## 5. Getting the sprites out

`tools/extract_item_icons.py`, on the same route the hero icons already use
(`docs/research/hero-icons.md`): walk the `gameres` text index for the sprite names in a
directory, open only the cached bundles that carry them, save those Sprites as PNGs. The
index reading is shared with the hero extractor in `tools/lib/gameres_index.py`.

Measured on this install: **2012 sprites indexed across 338 bundles → 1997 item PNGs +
7 frames**, 8 names in bundles the client has not downloaded. Coverage of a real bag:
**249 distinct icon names, 249 found — 100 %.** Every one of them was in the
`ItemIcons` tree, including the hero shards, whose portrait is copied into the item tree
under the same name.

This is NOT the wall `hero-icons.md` hit. That one was the `heroId → resName` mapping,
which lives in an encrypted datatable; here the mapping is the config row the client
already has parsed in memory, and the sprites were never encrypted.

Composition and caching are `tools/lib/item_icons.py`: one PNG per (icon, colour, size)
under `results/item_icons/cells/`, built on first use, served to the Tk window as a
`PhotoImage` and to the phone as `/api/itemicon?cell=<name>`.

## 6. What the panel does with it

* `actions/read_inventory.md` — the whole bag in one `READ_LUA`, ~25 KB, one round trip.
* `actions/read_inventory_desc.md` — descriptions for named ids only. Split off because
  all 371 descriptions are ~58 KB and a description never changes: they are asked for
  once and kept.
* `panel/tabs/inventory.py` — a grid of composed cells in the window, the same cells as
  rows on the phone, both searchable. The last reading and the descriptions live in the
  profile's database (`blobs`: `inventory_state`, `inventory_descs`), so the tab opens
  full before the game is asked anything.

## 7. Sizes, for whoever tunes this next

| reading | bytes |
|---|---|
| whole bag, id + count + colour + type + icon + name | ~25 000 |
| names alone | 16 128 |
| descriptions alone | 57 671 |

The daemon carried the 25 KB answer in one line without trouble; 83 KB was not
attempted, which is why the descriptions are a second scenario asked in slices of 60.

## 8. The trap: a newline inside a reading ends it

An answer comes back as ONE line. Item **descriptions contain line breaks** — the game
wraps them for its own tooltip — and the first one ends the reading. Everything behind
it is lost with no error anywhere, and what it looks like is «those items have no
description».

It was caught by measurement rather than by reading the code. The client's own answer,
asked directly, was **409 of 415 items described**; the panel was storing 154, in runs
of 15, 26, 35, 23, 53, 1, 1 per slice of sixty — uneven exactly where a long description
happened to fall early in a slice. One `gsub('%s+',' ')` in the scenario, and the panel
gets 409.

So: **any `READ_LUA` that returns text a human wrote must flatten its white space.**
`read_inventory.md` does it for names too, though no item name has yet been seen with a
newline in it — the failure is silent and the guard costs nothing.

The second half of the same lesson is on the panel's side. `_play` now answers `None`
for «the read did not happen» as against `""` for «the game said nothing», and only
NON-EMPTY descriptions are written to the database: an empty one is what a half-failed
read also produces, and a profile that cached one would have blanked those items for
good. The genuinely-undescribed six are remembered for the session only.
