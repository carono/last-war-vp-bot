# Treasure-map piece exchange — «Обмен кусочками» (#1975)

The second tab of «Мобильный отряд», beside the secret tasks: a board where alliancemates
swap the pieces a treasure map is made of. This is what it is made of on the wire and in
the client, measured live on 2026-08-25.

**Nothing in this file is a real identifier.** Every uuid, uid and player name below is
invented with the shape of the real thing; the live readings this was written from are not
reproduced here (`CLAUDE.md`, «Not one identifier of a real account is written down»).

---

## 1. Who owns it

| thing | where |
|---|---|
| the data | `DataCenter.SplinterExchangeManager` (Lua) |
| one set's state | `SplinterExchangeManager.exchangeInfoList[type]` → `SplinterExchangeInfo` |
| a record | `SplinterExchangeData` — one alliance offer, or our own |
| the windows | `UISplinterExchange`, `…Confirm`, `…Log`, `…ShareConfirm` |
| the controller | `UI.UISplinterExchange.Exchange.Controller.UISplinterExchangeCtrl` |
| the pieces' own activity | `DataCenter.ActDispatchTreasureManager` (`exchangeType`, `digExchangeType`) |

`SplinterExchangeManager` is **generic**: the same board serves four different sets of
pieces, told apart by a `type`.

```
SplinterExchangeType = { DispatchTreasure = {Id = 1, LogRedPoint = 'TREASURE_FRAGMENT'},
                         SeasonSynthesiss = {Id = 2},
                         CookingIngredients = {Id = 3},
                         DigTreasure     = {Id = 4} }
SplinterExchangeLogType = { Own = 1, Alliance = 2 }
```

Each set names its own pieces in `exchangeInfoList[type].fragGoodsIdList` — seven ids for
sets 1 and 4, six for set 2, four for set 3. `ActDispatchTreasureManager` points at two of
them by name: `exchangeType = 1` and `digExchangeType = 4`.

**Set 4 is the one the current event runs**, and it is the default everywhere in the code.
A set the account holds no pieces of answers «nothing to trade» in one round trip.

## 2. The messages

All of them take **one table**, and the field names below are not guesses: each message
class was instantiated offline and handed a parameter table with a recording
`__index`, so what came back is the list of fields the message actually reads.

| `MsgDefines` | command | parameter |
|---|---|---|
| `DispatchTreasureGetALInfo` | `hero.dispatch.get.alliance.exchange.info` | `{type}` |
| `DispatchTreasureGetSelfInfo` | `hero.dispatch.get.exchange.info` | `{type}` |
| `DispatchTreasureALExchange` | `hero.dispatch.fragment.exchange` | `{uuid}` |
| `DispatchTreasureCallExchange` | `hero.dispatch.call.fragment.exchange` | `{type, needFragment, costFragment}` |
| `DispatchTreasureCancelExchange` | `hero.dispatch.cancel.fragment.exchange` | `{uuid}` |
| `DispatchTreasureAllianceExchangeRecord` | `hero.dispatch.get.alliance.exchange.record` | `{type}` |
| `DispatchTreasureExchangeRecord` | `hero.dispatch.get.exchange.record` | `{type}` |
| `DispatchTreasureLikeExchangeRecord` | `hero.dispatch.like.exchange.record` | `{uuid}` |
| `DispatchTreasureRemoveExchangeShow` | `hero.dispatch.remove.exchange.record.show` | `{type}` |
| `DispatchTreasureSendALInfo` | `hero.dispatch.send.exchange.info` | — (share to alliance chat) |
| `DispatchTreasurePushExchange` | **`push.treasure.fragment.exchange`** | — (server → client) |

**`…exchange.info` is the board; `…exchange.record` is the LOG.** They are one word apart
and they are not interchangeable — this cost an hour. Asking `get.exchange.record` where
`get.exchange.info` was meant does not fail: the reply lands in the same manager and
leaves `GetSelfExchangeData(type)` reporting `uuid = -1`, i.e. «we have no offer up» about
an offer that is standing on the board. The symptom is a read that keeps saying `mine=-`
while the game shows the offer.

## 3. What a record carries

`GetAlExchangeDataList(type)` → a list of `SplinterExchangeData`;
`GetSelfExchangeData(type)` → ours, with `uuid = -1` when there is none.

```
{uuid, uid, ownerId, allianceId, name, type,
 needFragment, costFragment, updateTime, headPic, headPicVer, headSkinId, headSkinET}
```

**`needFragment` and `costFragment` are the OWNER's side**, and that was worth one live
posting to settle rather than assume. `hero.dispatch.call.fragment.exchange`
`{type = 4, needFragment = A, costFragment = B}` came back as a record carrying exactly
`needFragment = A, costFragment = B` — so:

```
the owner NEEDS   needFragment          →  the accepter GIVES it
the owner PAYS    costFragment          →  the accepter GETS it
```

Reading it the other way round inverts the whole rule: it would spend the scarcest piece
to buy the most plentiful one.

## 4. What gates it

* **No daily cap was found.** Nothing in the client counts exchanges the way
  `hero.dispatch.list` counts `todayStealNum` / `todayAssistNum`, and no counter turned up
  on the manager, the info object or the record. The ceiling in
  `actions/exchange_treasure_pieces.md` (`limit`) is therefore OURS — a guard against a
  board that filled up overnight, not a rule of the game's.
* **A standing offer HOLDS BACK one copy of the piece it pays with**, and hands it straight
  back when it is withdrawn. This was got wrong first and the mistake is worth recording:
  posting an offer and cancelling it in the same run showed the seven counts identical on
  both sides, which reads as «nothing is escrowed» and is really «the cancel gave it back».
  Counting while the offer was still standing showed the paid piece one lower (20 → 19), and
  the withdrawal put it back (19 → 20). **Measure a hold while it is HELD, never across the
  release.** It does not change the default: we always pay with the piece we hold most of and
  the floor is the piece we hold least of, so the held copy can never be the one that decides
  how many digs are left — which is also why the offer step refuses to post when the seven
  are level.
* **One offer at a time.** `GetSelfExchangeData` holds a single record, and the client's own
  panel has one slot; posting a second is not something this ability tries.
* `isOpened` on `ActDispatchTreasureManager` says whether the activity is running at all.

## 5. Why the rule is about the MINIMUM

A dig spends **one of each** piece in the set. The client says so itself:
`ActDispatchTreasureManager:GetCanDigCount()` equals the smallest of the seven counts,
exactly, on every reading. So an eighth copy of one piece buys nothing until it becomes a
copy of the scarcest one, and the only measure of a trade is what it does to that floor.

The rule the operator chose (#1975) is the strictest of the three that were offered —
**«только добор минимума»**:

> take an offer only when the piece it PAYS is the scarcest we hold,
> and the piece it ASKS FOR is at least `gap` above that floor.

Every accepted trade then raises the floor by one and can never lower it. Our own offer is
the mirror image: **ask for the scarcest piece, pay with the most plentiful one.**

## 6. The push, and what it is worth

`push.treasure.fragment.exchange` exists — it is in `MsgDefines`, and
`Net.Msgs.DispatchTreasure.DispatchTreasurePushExchangeMessage` has a `HandleMessage` of
its own. **Its payload has not been observed yet**: it arrives when somebody takes OUR
offer, and no swap of ours had gone through while this was being written. That is stated
plainly rather than guessed at.

Nothing here depends on the payload. The trigger `piece_exchange` fires the whole errand on
the command NAME, and the errand re-reads the board from the game — the same shape
`watch_fireworks.md` uses, minus the urgency: a swap is not a race the way a firework or a
chest is, so it goes through the ordinary schedule rather than jumping the queue. If the
push turns out never to reach the capture, the half-hourly timer still does the whole job;
the push only makes the reaction prompt.

## 7. What the panel plays

| file | what it is |
|---|---|
| `actions/exchange_treasure_pieces.md` | the ability: read the board, take what the rule approves of, keep an offer of ours standing |
| `actions/read_piece_exchange.md` | the reading the page draws, with the same verdict on each offer |
| `actions/withdraw_piece_offer.md` | take our own offer off the board |
| `panel/tabs/secret_tasks/pieces.py` | the page and its copy on the phone — no Lua, no gate, no rule of its own |
| timer `exchange_treasure_pieces` | half-hourly, off by default |
| trigger `piece_exchange` | on `push.treasure.fragment.exchange`, off by default |

The page's two knobs (`gap`, trades per run) and its «keep an offer standing» box reach the
timer through `Schedule.register_args`, so a button press and a scheduled run can never
trade on different rules.

## 8. Dead ends worth not repeating

* `string.dump` is refused by this client's sandbox, so no sender could be read by
  decompiling. Building the message offline with a recording parameter table answers the
  same question in one round trip and costs nothing.
* `OnCreate` on these messages takes a TABLE. Handing it positional numbers throws
  `attempt to index a number value (local 'param')` — which is the same shape as the
  fireworks gift message (#1854).
* `ItemManager:GetItemCountById` does not exist here. Piece counts come from
  `DataCenter.ItemData.ItemInfos`, summed per `itemId` over the stacks — the same source
  `actions/read_inventory.md` uses.
* Ids read out of the game are Lua numbers and print as `771011.0`. `string.format('%d', …)`
  rather than `tostring`, and `v + 0` rather than `tonumber` (which fails silently inside a
  `pcall` on this client).
