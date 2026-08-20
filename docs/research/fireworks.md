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

### The announcement, field by field (measured 2026-08-20, #1854)

§6 of the first write-up left these unknown — the recording's traffic file was empty and
no firework was in reach. They were read in the end by wrapping the client's own
`SFSNetwork.HandleMessage` in the live VM and printing the message's keys:

```
push.get.fireworks.gift
    configId    661502              -- WHICH firework: a row of the `firework` table
    pointId     400001              -- WHICH SQUARE it is standing over
    uid         1000000000000001    -- who has just TAKEN a box (not the owner)
    name        Player1             -- …their nickname, in full
    pic  picVer  headSkinId  headSkinET  isDouble   -- their avatar
```

**There is no box uuid in it and no `ownerUid`.** The push says «somebody took a box from
the firework on that square», and it names the TAKER rather than the prize — so a press
cannot be built out of it, in any spelling, and the client's own queue map is the only
source there is. That is not a gap to be closed later: it is why the collector reads
`LWFireworkGiftManager` and why the watcher below presses from inside the client.

It is also why the ear prints two fields and drops the rest: `tile=` and `kind=`. A push
carrying a player's nickname must not reach `panel.log` (#1293), and this one carries it
on every single announcement.

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
* **A firework outside the alliance is heard and not taken.** Measured 2026-08-20 by
  pressing one anyway: the server answers `errorCode = zombieRush_tips_19`,
  `errorMsg = "not same alliance"`. Nothing local says so first — the box's own
  `isAvailable` was already `false` and `IsHasAvailableBoxForMeByUid` already `false`, so
  the local gates and the server's agree; what the reply adds is the REASON, which is why
  a panel full of `push.get.fireworks.gift` can sit beside `taken=0` all evening and
  nothing is broken.
* **Lighting one needs the item**: `HasAnyFireworkGoods()` was false on the measured
  account, and the trace has 39 `UIFireworkGoodsLack` — the player had run out.

## 5. What the panel does with it

* `tools/wire_event_monitor.py::_firework_fields` builds the machine-only fields line for
  `push.get.fireworks.gift`: `tile=<square> kind=<configId>`, and `n=1` when the server
  spelled its fields some other way. **Nothing that names a person is in it** — the push
  carries the taker's uid, nickname and avatar, and a line the parent writes to
  `panel.log` is exactly #1293.
* `panel/runtime/wire.py` asks the one ear for that family beside the rally one and
  routes the line to `panel/runtime/firework_wire.py::FireworkBook`, which is the
  receiver: counted on the profile's intake ledger as `fireworks.push`, kept per tile,
  and checkpointed into the profile's own database under the `firework_state` blob.
* The trigger `firework_collect` (off by default, «сразу, без очереди») plays
  `src/lastwar_bot/actions/collect_fireworks.md` on every such push.
* The recipe walks the queue map and presses `get.fireworks.gift` for each box that is
  still ours to take. It never marks anything: what it reports afterwards is read back
  out of `giftUuid2TimeTable`.
* **The ANSWER to that press is heard too** (#1854), on the same ear:
  `get.fireworks.gift` with no `push.` in front of it. It is the only place the panel can
  watch a box ARRIVE — `got=1`, or `got=0 why=<code>` when the server refuses — so the
  book counts takes and refusals apart, keeps a count per day for a month, stamps when
  the last box came in and measures the milliseconds from the announcement to it. The
  «Салют» block on «События» draws exactly that, in the window and on the phone.
  The account's LIFETIME total stays the client's own (`giftUuid2TimeTable`) and is read
  from the game, never kept twice.

## 6. The press had never worked, and why nobody could tell (#1854)

The recipe shipped in #1677 wrote the three fields as three positional arguments:

```lua
SFSNetwork.SendMessage(MsgDefines.GetFireworksGift, uuid, ownerUid, type)   -- throws
```

The client refuses that before a byte leaves the machine —
`GetFireworksGiftMessage.lua:13: attempt to index a number value (local 'param')` —
and the throw happened inside the recipe's own `pcall`, where it was counted as
«unreadable» and the run went on to report success. One profile's log holds **553 runs
with `taken=0` in every single one**. The 28 boxes on that account's record were all
collected by hand.

Both shapes were sent at the same box to settle it:

```
positional = false   GetFireworksGiftMessage.lua:13: attempt to index a number value
table      = true    -- and the server answered, refusing on its own grounds
```

**The message takes one table**, `{uuid, ownerUid, type}` — exactly what the client's own
send builds. A press that throws is now reported as `failed=` with the error text, so the
next version of this mistake is one line in the log rather than a year of silence.

## 7. Taking the box in milliseconds — the watch inside the game

A box is decided in seconds, and hearing the announcement in the PANEL costs most of
them: the capture's child decodes the frame, writes a line, the hub reads it, the
schedule accepts an errand, a worker claims the client, and only then does a Lua round
trip go out. `actions/watch_fireworks.md` removes the whole chain the way the treasure
watch did before it (#1318): a wrapper on the client's own `SFSNetwork.HandleMessage`
that presses **inside the same call that delivered the push**, when the queue map has
just been updated by the client's own handling of it.

* `watch_fireworks.md` arms it. Idempotent — a second play says «already on» and installs
  nothing. It also asks `get.fireworks.info.list` when a push found nothing to take, at
  most once every three seconds, and presses again on the reply.
* `read_fireworks_watch.md` reads back `on / pushes / presses / taken / failed / lastMs /
  bestMs / onRecord` and empties the ring. `lastMs` is the milliseconds between the push
  arriving and the press leaving — the number the ability is measured by.
* `unwatch_fireworks.md` turns the flag off; the wrapper stays a pass-through, because
  unwrapping safely means knowing nobody wrapped it afterwards, and nobody can know that.
* The trigger `firework_watch` (off by default, every 180 s) exists only to RE-ARM: a
  client restart takes the VM and everything parked in it.

`collect_fireworks.md` remains the press-on-demand version and is what the wire trigger
`firework_collect` plays. It no longer opens with a refresh and a 1.5 s wait — it presses
first, on what the client already knows, and only asks the server when that found
nothing.
