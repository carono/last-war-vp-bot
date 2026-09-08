# Opening a finished building, and reading which ones are waiting

What the duel's Tuesday and the arms race's building hour are both about (#2632): a
construction that has run out its timer and is standing on the base with nothing taken
yet. Reverse-engineered live on 2026-09-08 against two accounts, entirely in the game's
own Lua VM — no capture was needed and nothing was sent to find any of it.

## 1. Where a construction lives

`DataCenter.QueueDataManager.queueDic` holds every queue slot the account has, of every
kind. Two enums name the fields:

* `NewQueueType` — `Default = 0` is the BUILDING queue; `Science = 6` is research,
  `Hospital = 3` the hospital, and so on for two dozen other kinds.
* `NewQueueState` — `Free = 0`, `Prepare = 1`, `Work = 2`, `Finish = 3`.

A slot of `type == NewQueueType.Default`:

```
{type=0, qid=1004, state=3, itemId=<the BUILDING's uuid>, funcUuid=0,
 startTime=1788756439220, endTime=1788780539368, isHelped=0, helpNum=0, uuid=<the slot>}
```

Two things about the shape are worth writing down, because both are easy to get wrong:

* **`itemId` is the building's uuid**, not an item id. The slot's own `uuid` is the
  slot's; `funcUuid` is `0` on a building slot (it carries something on the research
  ones).
* **`state == Finish (3)` is the whole definition of «готовое здание».** There is no
  separate flag, no bubble to look for and nothing on the building itself that says it —
  `BuildManager:GetBuildQueueState(uuid)` answers `BuildQueueState.UPGRADE (16)` both
  while it is building and after it has finished, so it cannot tell the two apart. The
  times can be compared (`endTime` against the server's seconds ×1000) but there is no
  need: the server sets the slot to `Finish` itself.

An account has as many building slots as it has queues — four on the accounts this was
read on, `qid` 1001…1004 — so «сколько может ждать одновременно» is a small number, and
the list on the panel's page is never long.

## 2. What a finished building is called, and what it looks like

Everything else is asked of the building, by the uuid the slot carried:

| what | how |
|---|---|
| its building id and level | `BuildManager:GetBuildingDataByUuid(uuid)` -> `.itemId`, `.level` |
| its name, in the client's language | `BuildManager:GetBuildingNameByUuid(uuid)` |
| its picture | `BuildManager:GetBuildIconPath(buildId, level)` |

`GetBuildLevel(uuid)` is **not** the building's level — it answered `915` and `996` on
buildings standing at 12 and 29 — so the level comes off the building data.

`GetBuildIconPath` answers a full asset path,
`Assets/Main/Sprites/BuildIconOutCity/UI_building_10310000`; its last part is the sprite
stem, and the whole tree (180 sprites in this build's index) is what
`tools/extract_building_icons.py` pulls into `results/building_icons`. Nothing in the
repository maps a building to a picture: the client answers it, so an account whose art
revision differs simply gets a different stem and the same route serves it.

## 3. Opening one

`BuildManager:CheckSendBuildFinish(uuid, isDelaySend, info)` — the client's own claim.
Its parameter names were read off the live function (`debug.getlocal` on the function
object; `string.dump` has been refused by the sandbox since 2026-08), and the two extra
arguments are optional: the panel's recipe calls it with the uuid alone.

It is scheduled through `TimerManager:GetInstance():DelayInvoke(…, 0)` rather than
called on the hijack thread — the same precaution `SendCreateMarchMessage` needs, and it
costs nothing to take.

The proof a claim landed is the queue: the slot leaves `Finish`. That is what
`actions/open_ready_buildings.md` counts before and after, so a send the server dropped
fails loudly instead of reporting a success nobody got a building from.

## 4. The gate, and why it is in the recipe

Opening pays «Строительство Города» points, which the arms race pays for during exactly
one of its six four-hour phases (`event_id == 120001`, docs/research/arms-race.md). A
building opened in any other hour is points thrown away, and a finished building keeps
indefinitely — so the recipe reads the event's current record
(`ActivityPersonalArmsDataManager.dataDict`, the entry with an `event_id`, valid while
its `stage_end_time` is ahead of the server's own seconds) and stops unless it is the
building hour. A client that cannot answer stops too: «the manager was not loaded» must
never read as «go ahead».

## 5. Where it lives

* the abilities — `src/lastwar_bot/actions/read_ready_buildings.md` (the reading) and
  `src/lastwar_bot/actions/open_ready_buildings.md` (the claim, with its gate);
* the pictures — `tools/extract_building_icons.py`, `tools/lib/building_icons.py`, and
  the `/api/buildingicon` route in `panel/web/server.py`;
* the panel — the «VS» tab's Tuesday (`panel/tabs/vs.py`), which reads with the first,
  presses the second, and holds no gate of its own.

## 5. There IS a push, and the client drops it (#2641)

The section below was written on a measurement that was right about the LIST and wrong
about the wire, and it is left standing because the correction only makes sense beside
it. `MsgDefines` names three of them — `PushBuildQueueInfo = push.build.queue.info`,
`PushQueueAdd = push.queue.add`, `PushQueueDelete = push.queue.del` — and the first one
arrives every time a build queue slot moves. Hooking `SFSNetwork.HandleMessage` around
one speed-up caught it whole:

```
push.build.queue.info -> {updateQueues = {{qid = 1002, uuid = <the slot>, type = 0,
                                           sT = <start, ms>, uT = <the NEW end, ms>,
                                           unlock = 1, rentPrice = 500, rentTime = 120,
                                           expireTime = 0, gift = <an item id>}}}
```

…and the reply to the send itself carries the same number a second way:

```
build.ccd.m.new -> {finished = false, isFixRuins = false, _time = 12, _id = 259,
                    itemCostArr = {{itemId = <the piece>, costNum = 1, count = <left>}},
                    buildInfo = {uuid = <the building>, bId = <its id>, lv = 30,
                                 sT = <start>, uT = <the NEW end>, state = 1, ...}}
```

**And the client does not apply it.** Four minutes of speed-ups poured into one
construction over fourteen minutes moved `queueDic`'s `endTime` by nothing at all, while
the server's `uT` came back four minutes shorter every time. It is not a stale reference
either: `GetAllQueue()`, `GetQueueDatasByType()` and `GetAllQueueByType()` all answer the
same table with the same stale numbers, `BuildManager`'s own `updateTime` matches it, and
`CheckAllQueueTimeFinish()` only compares that table against the clock. The slot's fields
are `{type, qid, state, itemId, funcUuid, startTime, endTime, isHelped, helpNum,
lastHelpTime, newItemId, para, para2, uuid}` — there is no fresher field hiding in it.

That is the whole of #2641: four constructions were closed on the server by presses on
the panel, `finish_building.md` read the client's cache two seconds later, saw them still
running and reported FAILED four times over, and the finished buildings did not appear on
the page for another eight minutes — by which time the client had resynced on its own.

**What is done about it.** The recipe stops asking the cache and listens for its own
answer: it raises an ear on `SFSNetwork.HandleMessage` before the send, reads `finished`
off the `build.ccd.m.new` reply, and takes the ear down again. When the answer is yes it
writes the server's `uT` into the slot's `endTime` and the building's `updateTime` —
never later than what is there — and asks `CheckAllQueueTimeFinish()` to look again, so
the slot flips to `Finish` and the page is right at once instead of in eight minutes.
`read_ready_buildings.md` and `open_ready_buildings.md` also count a slot whose timer has
run out as finished whatever its `state` says, and the «VS» page subscribes to
`push.build.queue.info` so the list moves without anybody pressing anything.

## 5b. What the decision of #2633 was, and what still holds

A construction finishing announces **nothing**. The server sets the slot's `state` to
`Finish` and no command crosses the wire — the client redraws off its own timer, so a
panel that only listens would go on showing the list it read at login for the rest of the
day. That is the one reading on the «VS» page in that position: the survivors' tickets and
the chip chests are bag items, and the bag has `push.resource.item.update` behind it
(`docs/research/inventory.md`).

It was taken to the person rather than answered with a poll, and the decision was **«по
endTime слота»**: the slot already carries the millisecond it is due, so the panel sleeps
until exactly that second and asks once. `read_ready_buildings.md` therefore answers
`next_ready_sec` beside the list — how long the earliest slot that is still WORKING has
left, by the GAME's clock (`UITimeManager:GetInstance():GetServerSeconds()`; the PC's
disagrees and the PC is the one that lies), or `-1` when nothing is building at all.

The tab arms one alarm off that number (`panel/tabs/vs.py::_arm_build_alarm`). A
day-long construction is waited out in legs of an hour because an `after()` a day out is
a promise nobody should make — and **a leg that arrives early re-arms without asking the
game anything**, so the queue is read once, at the moment it becomes wrong, and never in
between. `-1` arms nothing: an account with an empty queue asks no questions at all until
its next login or its next press.

## 6. Closing a construction that has NOT finished (#2634)

The other half of the same queue: a slot in `Work` runs out its timer by itself, or a
speed-up carries it to the end. The send is the build queue's own —
`build.ccd.m.new`, `{bUUID, isFixRuins, itemIDs, useGold}` — where `bUUID` is the
BUILDING's uuid (the slot's `itemId`, §1) and `itemIDs` is the game's own
`"<itemId>;<count>"`. `useGold` is `false` and the gold-for-time argument is `0`: a
construction that could only be closed with diamonds is left running
(`docs/research/arms-race.md` settled the shape).

**Which speed-ups, and why the panel does not choose them.** The bag answers it:
`DataCenter.ItemData:GetItemsByType(2)` carries `speedUpType` (7 building, 1 universal),
`para3` — what one piece is worth in SECONDS, as a string — and `count`. On a freshly
started client `speedUpType` is `nil` until something fills it in, so the item id is the
fallback: they run `2002<family><size>`, `200210…` building and `200200…` universal. The
parcel is specialised before universal, small denominations before large, and a last
piece that overshoots, because a construction is not closed by a parcel that stops short
of it. All of that is in `actions/finish_building.md`; the panel passes a uuid.

**A bag that comes up short spends nothing.** Minutes poured into a construction that
stays open buy no building and cannot be taken back, so the recipe stops with «N
second(s) short» and the bag untouched — and the row on the page draws a dead button
saying the same thing, out of the `covered` flag `read_ready_buildings.md` prints beside
its plan.

**The price is named before it is paid.** `read_ready_buildings.md` answers
`building_builds` — one entry per running slot, with the seconds it has left, whether the
bag can close it, and the parcel that would: `<itemId>:<pieces>:<seconds each>:<own>`.
Several slots do not spend the same piece twice: the bag is walked down as the earliest
takes from it. The recipe works the parcel out AGAIN at the moment of the press — a plan
a person read a minute ago is a plan the clock has already moved.

**Nothing plays it by itself.** It is an irreversible spend, so it ships as a press with
a confirmation and no schedule anywhere near it (CLAUDE.md, «A new ability ships SWITCHED
ON» and its one exception).
