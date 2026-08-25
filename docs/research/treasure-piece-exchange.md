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
| `DispatchTreasureSendALInfo` | `hero.dispatch.send.exchange.info` | `{uuid}` — announce it in the alliance chat |
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

## 5. The rule

A dig spends **one of each** piece in the set. The client says so itself:
`ActDispatchTreasureManager:GetCanDigCount()` equals the smallest of the seven counts,
exactly, on every reading. So an eighth copy of one piece buys nothing until it becomes a
copy of a scarcer one — which is why a trade is judged by the two COUNTS in the bag and by
nothing else.

The rule is the operator's, in their own words (#1975):

> **«Выгодный, если у нас меньше или столько же тех, что нам предлагают.»**
>
> take an offer when we hold NO MORE of the piece it GIVES US
> than of the piece it ASKS US FOR.

Put the other way round: never hand over a piece we are short of to get one we already
have more of. Equality is taken — it costs nothing and it moves a piece.

`strict` is the one knob. `0` (the default, and what was asked for) compares with «≤»;
`1` makes it «<» and refuses an even swap.

**The rule fits the board, which is worth checking rather than assuming.** The swap is one
piece for one piece — `needFragment` and `costFragment` are single ids, never lists, never
quantities — and every piece is an ordinary stackable bag item with a count. So «how many
of it do we hold» is a real number for both sides of every offer, and the comparison is
always answerable. Nothing about the board makes the rule inapplicable.

Our own offer is the same idea at the extremes: **ask for the scarcest piece, pay with the
most plentiful one** — which is always a trade our own rule would take.

## 6. Announcing an offer — «опубликовать в чат альянса»

The button beside a freshly stood offer is **one call and nothing else**:

```
hero.dispatch.send.exchange.info {uuid}
```

The client posts no chat message of its own — the server puts the card into the alliance
chat from our name. So this is **not** the mechanism `tools/lib/chat_share.py` uses for a
coordinate (`post = 13` with an `attachmentId` JSON through `ChatManager2.Net`), and
nothing about it needed inventing: the controller's `SendALShareMsg` reaches exactly this
one command.

The uuid is our own record's, which only exists once the server has answered the post —
hence the wait between the two steps in `exchange_treasure_pieces.md`. An announcement
built from the record held before the post names the offer that was just withdrawn.

**It is also the shortest road to the answer in §7.** An offer nobody has seen is an offer
nobody takes, so waiting to learn what arrives when ours is accepted meant waiting for an
alliancemate to happen to open the board. A card in the chat replaces that with a card in
the chat.

## 7. The push — CAUGHT, and what it carries

**There is one, and this is it**, off the wire watch on 2026-08-25, minutes after the
first offer of ours was announced in the chat:

```
push.treasure.fragment.exchange {DIG_GAME_TREASURE_FRAGMENT = 1}
```

One field, and the field NAME is the set — the same string `SplinterExchangeInfo.cfgData`
carries as `LogRedPoint` (set 1 is `TREASURE_FRAGMENT`). The value is a flag. **There is no
uuid in it, no piece id, and nobody's name**: it says «something on that board has moved»,
which is what the game draws its red dot from, and nothing more.

That is enough, and it is exactly the shape the listener was built for. The trigger
`piece_exchange` fires the errand on the command NAME and the errand re-reads the board
from the game — it never needed a field out of the push, which is why it was written that
way before the push had been seen.

**And it is not fired by our own posting** — that was the first reading of it and the
wire says otherwise. Two offers were stood and two pushes arrived, and in BOTH cases the
order in the ring is the same:

```
hero.dispatch.call.fragment.exchange  {… uuid = <ours>}     the offer goes up
hero.dispatch.get.exchange.info       {… uuid = <ours>}     …and is there when asked
push.treasure.fragment.exchange       {DIG_GAME_TREASURE_FRAGMENT = 1}
hero.dispatch.get.exchange.info       {type = 4}            …and is GONE when asked
```

The reply carrying no record at all is the game saying our offer is no longer on the
board — it was taken — and the push sits immediately before that, never between the post
and the first reply. So this is the announcement the listener wanted: **somebody accepted
our offer.** Both times the piece we had asked for was one higher in the bag afterwards
and the piece we paid with one lower, and the digs left went 12 → 13.

It cannot loop either. A run woken by it finds no offer of ours standing, posts a fresh
one and announces that — and the next push comes only when THAT one is taken.

How it was got, and it is worth repeating for the next unobserved push: the offer had been
standing for half an hour with nobody looking at it. The chat announcement (§6) put it in
front of the alliance, and the answer came within minutes — the piece we had asked for
turned up in the bag and the board went quiet. **An offer nobody has seen is a listener
nobody can test.**

The half-hourly timer stays regardless: if the push ever fails to reach the capture, the
errand still does the whole job on its own clock.

## 8. What the panel plays

| file | what it is |
|---|---|
| `actions/exchange_treasure_pieces.md` | the ability: read the board, take what the rule approves of, keep an offer of ours standing |
| `actions/read_piece_exchange.md` | the reading the page draws, with the same verdict on each offer |
| `actions/withdraw_piece_offer.md` | take our own offer off the board (and get the held piece back) |
| `panel/tabs/secret_tasks/pieces.py` | the page and its copy on the phone — no Lua, no gate, no rule of its own |
| timer `exchange_treasure_pieces` | half-hourly, off by default |
| trigger `piece_exchange` | on `push.treasure.fragment.exchange`, off by default |

The page's two knobs (`strict`, trades per run) and its «keep an offer standing» box reach
the timer through `Schedule.register_args`, so a button press and a scheduled run can
never trade on different rules. The rule itself is pinned by
`tests/test_piece_exchange_rule.py`, which lifts the verdict step out of the recipe and
runs it under `lupa` against an invented bag and board — no game, no client, no pieces
spent, and a rule edited in the recipe and nowhere else still fails the test.

## 9. What switching the listener on actually did (measured)

The trigger and the half-hourly row were turned on for one profile and watched. Seven
minutes later, off the profile's own log:

| reading | number |
|---|---|
| runs of the errand | 18 |
| woken by the push | 18 (every one — the timer's own turn never came round) |
| offers stood | 18 |
| **messages into the alliance chat** | **34, in four minutes** |
| digs at the start / at the end | 14 / 14 |

Both of the numbers in bold are faults, and neither was visible from a single run.

**The loop is real and it runs through living people.** An offer we stand is taken within
seconds by an active alliance; the acceptance is a push; the push wakes the errand; the
errand finds no offer of ours, stands a fresh one and announces it — and that one is taken
too. Nothing here is a bug in the ordinary sense: every swap obeyed the rule and every
announcement obeyed «one message per offer». The guard was simply written for a world
where offers are rare, and nothing in the recipe knew how often an offer would be.

**And the churn bought nothing.** Eighteen swaps and the digs left never moved off
fourteen. With the seven counts one apart, an offer that asks for the scarcest piece and
pays with the most plentiful just moves the shortage from one piece to another: the floor
cannot rise, because the piece paid with becomes the new floor. A swap only raises it when
the piece we pay with is at least **two** above the piece we ask for.

Both are fixed by a threshold each, and they are separate on purpose:

* `offer_gap` (2) — how far apart the most plentiful and the scarcest must be before an
  offer of OURS is worth standing. It governs only what we POST. What we ACCEPT stays the
  operator's «≤»: an even swap somebody else is paying for costs us nothing, while
  standing one of our own costs a held piece and a message in a channel people read.
* `share_cooldown` (30 min) — a floor under how often the chat may be written to at all,
  whatever the rest of the recipe decides. A second guard rather than a better first one,
  because the first one was not wrong: it was answering a different question.

### …and a third thing, found in the SAME way once the two above were quiet

With the thresholds in and the board flat — nothing to post, nothing to take, no push
anywhere — the errand still ran **three times in six minutes**. None of them was a push. A
WIRE trigger sweeps once every time the ear is re-armed, and the panel re-arms the shared
capture whenever it comes back, which on a live profile is several times an hour. Each of
those sweeps paid two reads to be told the board had not moved.

`cooldown_sec` does not help: it is a POLL trigger's knob (`Trigger.as_dict` only writes
it when `is_poll`), and this one is a wire trigger. So the gate is the recipe's own and it
is the FIRST thing it does — `min_gap`, sixty seconds, checked against a stamp in the game
VM before a single request goes out. Long enough to swallow a re-arm, far too short to
delay a real acceptance, which is the one thing this errand must not be late for.

Verified: two runs thirteen seconds apart, and the second one stopped with
«the board was read 16 s ago» before it asked the game anything.

The lesson is not about this ability. **A rule that is quiet in a measurement of one run
can be loud in a measurement of an hour**, and the way to find out is to switch the thing
on and count — not to reason about how often the event «should» happen. All three of the
faults on this page were found that way and none of them by reading the code.

## 9. Dead ends worth not repeating

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
* **And a float id is refused on the WIRE, not just misprinted.** Posting an offer with
  `needFragment = 771011.0` comes back as

  ```
  hero.dispatch.call.fragment.exchange {errorCode = "E000000", errorMsg = "not fragment item"}
  ```

  — which reads as «you do not hold that piece» about a piece there are twenty of. The
  identical post with an integer wins. So the two ids are `math.floor`ed on the way out.
  The failure is silent from the client's side: `pcall` succeeds, the run reports a posted
  offer, and only the board being empty afterwards says otherwise. This is what the wire
  watch (`actions/dev/_t1975_push.md`) is for.
