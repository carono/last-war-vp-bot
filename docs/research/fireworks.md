# Fireworks — «салют»: how the game announces one, and how a gift box is taken

Task #1677. Recorded 2026-08-20 (`results/traces/20260820_150539_салют_trace.log`,
operator's note: «Сигнал о салютах, 3 разных типа, сбор подарков с них»), and completed
against the live Lua VM through the panel's web API, because **the traffic file of that
run is 0 bytes** — the capture never got a frame, so §8.11 of `docs/skills/sniff.md`
applies and the client's own managers are the source.

Every id, uid and coordinate below is invented. The shapes are real; the values are not
(`CLAUDE.md`, «Not one identifier of a real account is written down»).

## 1. What a firework is

A player lights a firework over their own base with an inventory item. While it burns it
drops **gift boxes**: anybody who can see it may take one, and each account may take one
box per firework. The trace's three item ids are the three kinds the operator meant —
`firework` is a config table and `661501` / `661502` are two of its rows
(`GetTableData('firework', 661501, …)`; the manager's own default is
`LWFireworkManager.defaultFireworkItemId = "661501"`).

## 2. The wire

`MsgDefines`, read live off the VM, has exactly seven names with `firework` in them:

| Constant | Command | What it is |
|---|---|---|
| `PushGetFireworksGift` | `push.get.fireworks.gift` | **the announcement** — somebody (anybody) has just taken a box |
| `GetFireworksGift` | `get.fireworks.gift` | **the press** — take a box |
| `GetFireworksInfoList` | `get.fireworks.info.list` | ask what is burning right now |
| `FindFireworksGiftWorldPoint` | `find.fireworks.gift.world.point` | move the camera to the firework |
| `GetFireworksGiftRecord` | `get.fireworks.gift.record` | the history of a firework's boxes |
| `PushFireworksStatus` | `push.fireworks.status` | a firework's state changed |
| `UseItemFireworks` | `use.item.fireworks` | light one |

**The announcement is `push.get.fireworks.gift`, and in practice it is the only one.**
The 155 208-line trace carries **109** of them and **not one** `push.fireworks.status`.
Each is handled by `UIUtil.ShowFireworkGiftGotBroadcastPopUI(<tile index>, <the message>,
1, "Assets/Main/Sprites/ItemIcons/item200")` — so the push names the SQUARE the firework
is standing over, which is how the panel's ear identifies one
(`SceneUtils.TileIndexToWorld(<tile>, 1, <server>)` right after it in the same trace).

There is no «a firework has started» push at all. A firework becomes known to a client
because a box was taken off it, or because the client asked. That is why the ear is the
ability: a periodic sweep would have to guess when to ask.

### The press, field by field

Off the trace, `SFSNetwork.SendMessage` → `SFSObject.Put*`, in the order the client
writes them:

```
get.fireworks.gift
    PutLong       uuid      1000000000000000001     -- the BOX, not the firework
    PutUtfString  ownerUid  1000000000000001        -- whose base it is burning over
    PutInt        type      0
```

and the reply is an `ItemInfo` (`EventManager.Broadcast(91015, <item>)`) plus the
`UIFireworkGiftGotShow` window. Ten presses in the recording, nine distinct box uuids,
`type` was `0` every time.

`find.fireworks.gift.world.point` is the same message minus `type` — camera only,
nothing is taken.

Lighting one is `item.use {uuid = <the item's own uuid string>, num = 1, prtUid = <the
uid the firework is lit for>}`, five times in the recording, three distinct item uuids.
Not implemented here: it spends an item and the panel has no reason to.

## 3. The client's own book — where the collector reads

Two managers, both on `DataCenter`:

**`LWFireworkGiftManager`** — the boxes.

* `uid2FireworkGiftQueueMap` — `ownerUid -> LWFireworkQueue` (a class with `ToArray`,
  `Peek`, `Enqueue`, `GetSize`); one queue per firework that this client has heard of.
* `IsHasAvailableBoxForMeByUid(uid)` — **the gate.** Has THIS account still got a box to
  take from that firework. Local, no request.
* `IsThisGiftUuidGot(uuid)` / `SetGiftUuidGot(uuid)` / `giftUuid2TimeTable` — the record
  of the boxes this account has already been given, box uuid → when. **This is the
  authority on «how many did we get», and the panel keeps no second copy of it.**
* `GetRandomAvailableFireworkBoxPlayerUid()`, `IsHasAvailableBoxByUid(uid)`,
  `GetGiftQueueByPlayerUid(uid)`, `OnGetFireworksGift`, `OnSelfGetFireworksGift`.

**`LWFireworkManager`** — the fireworks themselves. `uid2FireworkQueueMap`,
`IsFiringByUid(uid)`, `GetFireworkQueueRemainTimeByUid(uid)`, `GetQueueCountByUid(uid)`,
`GetMainBuildingWorldPosByOwner(uid)`, `GetFireworkMaxNum()`, `HasAnyFireworkGoods()`,
`SendUseFireworkMessage`, `UseFireworkItem`, `GetDefaultFireworkItemId()`.

The world-side effect is `BaseBuildingDiscoManager.AddFireworkEffect(<base uuid>, <tile
index>, <ends at, ms>)` and a `FireworkWorldBuildBubble` over the base.

## 4. Gates

* **One box per firework per account.** Not a daily quota, not a cooldown — the whole
  limit is `IsHasAvailableBoxForMeByUid`, which is why the recipe asks it rather than
  counting anything itself.
* **A box that is already ours** answers `IsThisGiftUuidGot` true, so a second run over
  the same firework presses nothing.
* **The wrong server.** `get.fireworks.info.list` can answer
  `errorCode = firework_tips_1013`, `errorMsg = "not in this server"` — measured live on
  2026-08-20 while the account was on a cross-server map. The client's queue map is then
  whatever it last heard and the refresh is a no-op; the recipe reports it as
  `boxes=0` rather than failing.
* **Lighting one needs the item**: `HasAnyFireworkGoods()` was false on the measured
  account, and the trace has 39 `UIFireworkGoodsLack` — the player had run out.

## 5. What the panel does with it

* `tools/wire_event_monitor.py::_firework_fields` builds the machine-only fields line for
  `push.get.fireworks.gift`: `gift=<box uuid> tile=<square> type=<kind>`, and `n=1` when
  the server spelled its fields some other way. **`ownerUid` is deliberately not in it**
  — a player id in a line the parent writes to `panel.log` is exactly #1293.
* `panel/runtime/wire.py` asks the one ear for that family beside the rally one and
  routes the line to `panel/runtime/firework_wire.py::FireworkBook`, which is the
  receiver: counted on the profile's intake ledger as `fireworks.push`, kept per tile,
  and checkpointed into the profile's own database under the `firework_state` blob.
* The trigger `firework_collect` (off by default, «сразу, без очереди») plays
  `src/lastwar_bot/actions/collect_fireworks.md` on every such push.
* The recipe refreshes the list, walks the queue map, and presses
  `get.fireworks.gift` for each box that is still ours to take. It never marks anything:
  what it reports afterwards is read back out of `giftUuid2TimeTable`.

## 6. What is still unproven

The field NAMES of `push.get.fireworks.gift` itself. The recording's traffic file is
empty and no firework was burning within reach of the measured account for the whole
session (`uid2FireworkGiftQueueMap` held 12 owners with 0 boxes between them, and
`GetRandomAvailableFireworkBoxPlayerUid()` answered nil), so the payload was never seen
decoded. The fields builder therefore tries four spellings of «the box»
(`uuid`/`giftUuid`/`fireworksUuid`/`id`) and five of «the square»
(`pointId`/`tileIndex`/`pId`/`posId`/`point`), and **falls back to `n=1` rather than to
nothing** — a push it cannot name is still counted as one push, and the receiver drops it
with the reason `no-tile`. The recipe does the same on its side: it reports the field
names of the first box it finds (`fields=[…]`), so the first live firework says in one
log line which spelling this server uses.
