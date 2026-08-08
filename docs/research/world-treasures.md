# World-map treasures — find & take (protocol)

*"Сокровища на карте"* — the named treasure chests an alliance's **Detect Event**
(radar / drone scan) drops onto the world map. Members march to the tile, dig it,
and the finisher claims the gift. This note is the protocol for **finding a
treasure's position** and **taking it**, reconstructed from one live session
(task #1107):

* trace : `results/traces/20260728_155726_сокровище_trace.log`
* wire  : `results/traffic/20260728_155731_сокровище_traffic.jsonl`

Everything below is confirmed against that capture plus the live Lua VM
(`SFSNetwork.SendMessage`, `push.world.point.update`, `push.detect.treasure.claim`,
`SceneUtils.IndexToTilePos`).

## What a treasure is on the wire

A treasure rides the same transport as every other interactable — it is a
**`world.get.block` / `push.world.point.update` tile** whose `WorldPointType`
(field `f2`) marks it as treasure. Relevant `WorldPointType` values (full enum
dumped from the live VM):

| value | name | meaning |
|---|---|---|
| **21** | `TREASURE` | the detect-event treasure captured here |
| 43 | `ACTIVITY_WORLD_TREASURE` | activity variant |
| 46 | `TreasureChest` | pick-one chest (`pick.one.start/end.request`) |
| 42 | `MONSETER_CHALLENGE_NEW_TREASURE` | monster-challenge treasure |
| 14 | `DETECT_EVENT_PVE` / 8 `EXPLORE_POINT` | other detect points |

The treasure's *sub-kind* is `WorldTreasureType`
(`RadarTreasure=1`, `SiegeTreasure=2`, `SupplyTreasure=4`, `OffSeasonDetect=11`,
`PlayerKillMonsterTreasure=9`, … 21 values total).

### The point object (find = read the position)

`push.world.point.update` (`type:"change"`) carries the treasure. Decoded blob
of the captured "Uzilla" treasure:

```
f1  = 500553                     -- pointId  →  SceneUtils.IndexToTilePos(500553) = (552,500)
f2  = 21                         -- WorldPointType.TREASURE
f11 = {                          -- the treasure record
  1  = 1397117530950313784       -- treasure UUID  (this is what you claim)
  3  = "25193"                   -- cfgId   (config tables detect_event / world_treasure id 25193)
  5  = "<alliance-id>"          -- alliance uuid
  6  = "<ALLY>"                    -- alliance abbr
  7  = "<uid>"        -- finisher/operator uid (once dug)
  12 = "Uzilla"                  -- treasure name
  13 = 1785322473766             -- expiry ts
  16 = { 1=<uuid>, 3=500553, 4=8 }
}
```

**Position** = `f1` (pointId) → `SceneUtils.IndexToTilePos(pointId)` → `(x,y)`.
The server id is the `…100` suffix on the ids (here server **100**). Same
`tools/lib/coords.py` / `SceneUtils.IndexToTilePos` used everywhere else applies.

Two ways to enumerate treasures already known to the client, no capture needed:

* pan the map → `world.get.block` returns the tiles (`f2 = 21/43/46/42`), exactly
  like `tools/secret_task_capture.py` does for `f2 = 17`;
* the Detect Event fetches them up front — `MsgDefines.DetectInfoGet =
  get.detect.info` / `activity.detect.list`, parsed into
  `DataCenter.ActDetectTreasureDataManager` (`.dataDict`, `.treasures_num`,
  handler `OnGetArrDataMsg`). Dormant when no detect event is running
  (`treasures_num == 0`).

## Taking it (dig → claim)

Two steps, both seen in the capture:

1. **March to the tile.** A normal `WorldMarch` to the treasure's `pointId`
   (the capture shows a dozen alliance marches — `push.world.march.new`, all
   `destTile = 500553` — converging and digging). This is the ordinary
   `SendCreateMarchMessage` path, not treasure-specific.
2. **Claim** once dug — the finisher sends:

   ```
   SFSNetwork.SendMessage("detect.event.claim.treasure",
       uuid         = 1397117530950313784,   -- PutLong  "uuid"  = f11.1 above
       targetServer = 100)                    -- PutInt   "targetServer"
   ```

   i.e. command **`detect.event.claim.treasure`**, body **`{uuid:<long>,
   targetServer:<int>}`** — the same shape as `ghost.recon.steal` and
   `hero.dispatch.steal`.

Server response:

* reward popup `UIGiftPackageRewardGet` (captured haul: *Сундук опыта героя* ×5, …);
* broadcast **`push.detect.treasure.claim { uuid, operator:{uid,name,abbr,…} }`**
  to the alliance;
* the point flips to dug (`f11.7` operator uid filled in) and a system chat line:
  *"Сокровище Uzilla, расположенное в (552,500), было раскопано!"*

The related `MsgDefines` (from the live registry, for follow-ups):
`detect.event.get.treasure.claim.info`, `receive.detect.event.reward`,
`push.detect.event.info` (treasure notification), `detect.event.put.point.in.world`
(server places the point on the map).

## Not this feature (disambiguation)

* **`DigTreasureManager`** = the in-panel *treasure-map* mini-game (hammer digs
  blocks, `MsgDefines.DigTreasureGameOpenBlock = hero.dispatch.dig.game.open.block`,
  item `771030`). Not on the world map.
* **`ExplorerTreasureManager`** = a treasure *box bubble in the base* (city),
  `hero.dispatch.explorer.treasure.open`. Not on the world map.
* **`ActDispatchTreasureManager`** = the secret-task fragment exchange.

## Lua path (DataCenter) & draft recipe — UNPROVEN

Read side (positions), no capture:

```lua
-- treasures the Detect Event has handed the client (empty when no event runs)
local m = DataCenter.ActDetectTreasureDataManager
-- m.dataDict  : keyed treasure records ; m.treasures_num : count
-- per-tile x/y for a record's pointId:
local tp = SceneUtils.IndexToTilePos(pointId)   -- e.g. 500553 -> (552,500)
```

On-map points also live in `DataCenter.WorldPointDetailManager` /
`WorldPointWaitOpenManager` and arrive as `push.world.point.update` (`f2 == 21`).

Take side (exactly what the in-game «раскопать» finish does):

```lua
SFSNetwork.SendMessage("detect.event.claim.treasure", <uuid_long>, <targetServer_int>)
-- body: PutLong("uuid", uuid) ; PutInt("targetServer", server)
```

## Primitives (built — task #1107 follow-up)

Both moves are packaged as reusable Lua chunks in `tools/lib/lua_actions.py`
(`dig_treasure_march`, `claim_treasure`, consts `MARCH_DETECT_TREASURE = 50`,
`MARCH_CROSS_DETECT_TREASURE = 182`) and driven by the standalone tool:

```
C:\Python312\python.exe tools\dig_treasure.py march <pid> <uuid> [serverId] [formation]
C:\Python312\python.exe tools\dig_treasure.py march --xy <x> <y> <uuid> [serverId] [formation]
C:\Python312\python.exe tools\dig_treasure.py claim <uuid> [serverId]
```

`march` fires `MarchUtil.SendCreateMarchMessage(formation,
MarchTargetType.DETECT_TREASURE|CROSS_DETECT_TREASURE, pid, uuid, 1,1,false,
serverId, nil)` (same/cross auto-picked from the viewed server, override
`--same`/`--cross`); `claim` fires `SFSNetwork.SendMessage(MsgDefines.
DetectEventClaimTreasure, uuid, targetServer)`.

**Validation so far:** both chunks compile in the live VM and every symbol they
touch resolves (`MarchUtil.SendCreateMarchMessage`, `MarchTargetType.DETECT_TREASURE=50`
/ `CROSS_DETECT_TREASURE=182`, `MsgDefines.DetectEventClaimTreasure=detect.event.claim.treasure`,
`SFSNetwork.SendMessage`). **Not yet fired end-to-end** — no treasure on the map
(`treasures_num == 0`); the actual dig→claim round-trip is unconfirmed until a live
detect event drops one.

### Recipe

`src/lastwar_bot/actions/dev/work_treasure.md` — "find a treasure; if still being
dug, dig; if already dug, collect." It reads the head of a parked target queue
`DataCenter.__lw_treasure_queue` (entries `{pid, uuid, server, dug, cross,
formation?}`) and, per target, presses `dig_treasure` (still digging) or
`claim_treasure` (dug). The **dug vs digging** split is the point's operator-uid
field, proven from the capture: while digging the point carries NO operator uid
(wire `f11.7` absent); once fully dug it is filled with the finisher's uid — the
finder sets `dug` from that. Buttons `dig_treasure` / `claim_treasure` /
`dismiss_treasure_reward` are in `tools/lib/game_buttons.py`; the queue helpers
(`treasure_queue_len`, `treasure_head_state`, `dig_head_treasure`,
`claim_head_treasure`) in `tools/lib/lua_actions.py`. All compile in the live VM
and the read-only helpers run (empty queue → clean no-op). It sits in `actions/dev/`
until a live treasure confirms the round-trip.

### The finder (task #1116)

`tools/find_treasures.py` is the step that fills `__lw_treasure_queue`: it asks the
server for the treasure list, reads the manager back, reports, and with `--queue`
parks the targets for the recipe.

```
C:\Python312\python.exe tools\find_treasures.py            # look and report
C:\Python312\python.exe tools\find_treasures.py --queue    # ... and park the targets
C:\Python312\python.exe tools\find_treasures.py --watch --for 40m --every 5m --queue
```

Exit code 0 = something to dig, 1 = nothing — so a schedule can gate the recipe on it.

**`--watch` — the wait.** A treasure is not a standing feature of the map: it exists
only while a detect event has one out, and the alliance digs it away quickly. So one
look answers "right now" and almost always says no; the watch repeats the ask-and-read
(`--every`, default 120 s) until a treasure appears — then it parks it (with `--queue`)
and exits 0 — or the window (`--for`, default 60 m) runs out and it exits 1. Intervals
take units: `90` (bare `--every` = seconds), `3m`, `2h`; a bare `--for` is minutes.

**Why it asks first.** `ActDetectTreasureDataManager` is a *pure reply cache*, and this
matters: an empty `dataDict` does not mean "no treasure", it can equally mean "nobody
ever asked". Read off the live VM with `string.dump` (the constants of each function):

* `GetArrData` — constants `dataDict`, `activityId`, `data`: it only *reads*
  `self.dataDict[activityId]`. Not a sender.
* `OnGetArrDataMsg` — constants `treasures_num`, `dataDict`, `ArrExpireTime`: the sole
  writer, i.e. the reply applier for the list message.
* `CheckTreasureReachDailyLimit` — constants `TreasureTemplateManager`, `daily_max`,
  `group`, `dailyGot`: the per-day gate, cfg-driven.

So nothing polls by itself. The refresh is **`activity.detect.list`**, and it *needs an
activity id* — sent bare it dies in the client serializer
(`SFSDataSerializer.lua:39: bad argument #2 to 'pack' (number expected, got nil)`).
The ids to ask for are the manager's own `dailyGot` keys (on this account `25194` and
`25196` — the treasure cfg groups it counts daily takes for; the captured treasure's
own cfgId was `25193`). `get.detect.info` sends fine with no argument but does not fill
`dataDict` — it is a different payload.

**Which ids to ask for, and the fresh-client trap.** The ids normally come from the
manager's own `dailyGot` keys — but `dailyGot` is filled by a *reply* as well, so a
client that has just started tracks nothing: read live on 2026-07-29 right after a
crash-restart, `dailyGot` was empty where the same account showed `25193 / 25194 /
25196` minutes earlier. Asking for no ids means never asking at all, and the tool would
have called the map empty without having looked once. The finder therefore falls back to
those three known ids (`KNOWN_ACTIVITY_IDS`) whenever the client tracks none, and prints
which source the ids came from; `--ids` still overrides both.

Chunks live in `tools/lib/lua_actions.py`: `treasure_refresh_request(ids)`,
`treasure_state()` (logs `treasures_num`, `dailyGot`, and every `dataDict` record as raw
`key=value` pairs) and `park_treasures(home_server)`.

**Validation:** the read/refresh path is confirmed live — the request is accepted, the
manager reads back cleanly, and the tool reports "nothing to dig" with exit 1. The
*record field names* are still unconfirmed (the dict has never been seen populated), so
`park_treasures` probes several spellings per field (`pointId|point_id|pid|index|
tileIndex`, `uuid|treasureUuid|id`, `targetServer|serverId|srcServer|server`,
`operatorUid|operator|operatorId|uid|userId`) and `treasure_state` prints records raw so
the first live treasure shows its own shape. The extraction was exercised against a
synthetic record shaped like the captured blob: two targets parked with the right
pid/uuid/server, `dug` set from the operator uid and `cross` from the home server.

## Status / open ends

* Position read: **confirmed** (blob decoded, pointId→(x,y) matches the in-game
  system message).
* Take command: **confirmed** on the wire (`detect.event.claim.treasure` +
  `push.detect.treasure.claim`).
* Finding (is there one?): **built and confirmed to run** — `tools/find_treasures.py`,
  request + read + verdict. The record → queue-entry mapping inside it is still
  unconfirmed (see above).
* **Not yet built/proven headless:** driving march→claim from a script. The claim
  almost certainly gates on the dig being complete (a march must have worked the
  tile) and on per-day limits (`ActDetectTreasureDataManager:CheckTreasureReach
  DailyLimit`, cfg `treasureDailyLimit`). To prove end-to-end needs a live detect
  event with a treasure on the map — none was active during this analysis
  (`treasures_num == 0`), nor during the #1116 check on 2026-07-29: after asking
  `activity.detect.list` for both tracked ids the dict stayed empty, `dailyGot` was
  `25194=0 / 25196=0` (the daily allowance untouched), and the loaded world scene
  held no treasure object either.

### Why the map stays empty — the event itself is not running (2026-07-29)

The second #1116 pass looked past the treasure manager, at what the client says is
running at all, and the answer is one level up: **there is no detect event on this
server right now**, so there is nothing that could put a treasure out.

* `DataCenter.ActivityListDataManager.nowActivityList` — 23 activities open
  (secret task 94102, ghost recon 94111, parkour 80063, world boss 80002, treasure-map
  minigames 2200001 / 2200033, …). None of them is a detect event; `laterActivityList`
  is empty, so the client does not even know when the next one starts.
* The treasure cfg ids the manager counts daily takes for (25193 / 25194 / 25196) are
  *not* activity-list ids — the running list uses a different id space (94xxx / 4xxxx /
  22xxxxx), and `DetectEventTemplateManager.detectEventTemplateDic` holds nine *point*
  templates (10173, 15204, 24160-24164, 26314, 28170, 28171, 29171), not activity ids.
  So "is a detect event running?" cannot currently be answered by an id match — the
  reliable read stays "did the list reply bring a treasure".
* `DataCenter.WorldPointDetailManager` (`worldPointDetailList`,
  `worldSuppliesDataList`, `personalDiscoverSuppliesInfo`,
  `worldAllianceResourceDataList`) was empty in the city scene — no on-map treasure
  point loaded either.
* Also read live: `activity_detect_dig_times_expire = 1785376800000` = 2026-07-30
  02:00 UTC, i.e. the ordinary daily reset, not an event window.

The 40 `detect.*` messages the client knows (from `MsgDefines`, dumped live) are listed
for the follow-up that would make a treasure appear on demand rather than waiting for
one: `start.detect.event.pve`, `detect.event.put.point.in.world`,
`detect.event.batch.put.point.in.world`, `upgrade.detect.power`, `reset.detect.event`,
`get.detect.info`, `push.itemuse.detect.info`, plus the whole claim family already
mapped above. UI side: `UIDetectEvent`, `UILWActDetectTreasureALPanel` (the alliance
treasure panel), `UIDetectDigTreasure`, `UILWActDetectEventTreasureClaimInfo*`.
None of that was fired — sending the "start" family blind would poke a live event
system, and it is not needed for the read path.

**Practical consequence:** the honest way to catch a treasure is to wait for one, which
is what `find_treasures.py --watch` does. Live on 2026-07-29 the watch ran repeated
rounds against the game and stayed correctly empty throughout.

---

# The 2026-08-07 session: the whole thing, done by hand, on one trace

The first END-TO-END recording of the ability. Everything above was reconstructed from a
capture where the chest was already dug and from the live VM; this one is a player doing
the lot in one sitting — «отправил координаты сокровища, появился бадж о том, что
сообщили о сокровище, отправил отряд на раскопку, собрал сокровища, закрыл модалку»
(task #1277):

* trace : `results/traces/20260807_105327_сбор_сокровища_trace.log`
* wire  : `results/traffic/20260807_105328_сбор_сокровища_traffic.jsonl` — **0 bytes**

**The wire file being empty is not a dead client, and telling those two apart is the
lesson.** The secret-task monitor was already listening on the same interface, and a
second capture beside it gets crumbs — a picture indistinguishable from a client that is
not talking (044c19f). The trace, which reads the client's own Lua rather than the
network, was complete. **Check what else is capturing before believing a silent wire**,
and when one is up, analyse from the trace.

Every id below is INVENTED, of the same shape as the real one — a uuid is 19 digits, a
server is small, a tile index is `y * 1000 + x + 1`. The session's own values are in the
git-ignored trace and stay there (`CLAUDE.md`).

## What the client actually said, in order

Four messages, and they are the ability:

```
out  world.treasure.share.chat  ← the share; see below
in   world.treasure.share.chat  ← …and the badge that came back
out  world.march.formation.new  formationUuid, target=50, treasureUuid, "<from>;<to>"
in   push.detect.treasure.claim × 14        ← the alliance digging, one per finish
out  detect.event.claim.treasure  uuid, targetServer
in   detect.event.claim.treasure  → UIManager.OpenWindow(UIGiftPackageRewardGet)
```

Nothing else in the session is treasure-related: `get.player.cross.server.list`,
`detect.event.get.card.box.list` and the ordinary push traffic (`push.hero.data`,
`push.resource.info`, fifty `push.lw.alliance.alert.info.remove`).

### 1. Sharing the chest into alliance chat — NEW

The badge the player saw is a chat post, not a treasure message. `ChatTreasureShare`
builds an ordinary chat send whose `attachmentId` carries the chest:

```
SFSObject.PutInt      CurServerId  = <server>
SFSObject.PutLong     post         = <the chat room>
SFSObject.PutUtfString lang        = "ru"
SFSObject.PutUtfString msg         = ""
SFSObject.PutUtfString attachmentId =
  {"sid":<server>,"worldId":0,"shareType":27,"worldType":0,
   "uuid":<treasure uuid>,"treasureId":"<cfgId>","oname":"<uid>","x":<x>,"y":<y>}
SFSObject.PutUtfString uuid        = <treasure uuid>
```

**`shareType` 27 is the treasure share** — the same attachment mechanism the coordinate
share uses (`tools/lib/chat_share.py`), with its own type and its own payload. The reply
comes back as **`world.treasure.share.chat`**, handled by `ChatManager2.OnHandleMessage`,
and `DetectEventTemplate.GetChatBubblePath` is what draws the bubble. That message is the
cheapest «есть сокровище» detector there is: it names the uuid, the cfgId, the server and
the tile, and it arrives whether the chest was shared by this account or by anybody else
in the alliance.

### 2. The dig march — the call in `lua_actions` is right

Confirmed exactly as `dig_treasure_march` builds it, argument for argument:

```
MarchUtil.SendCreateMarchMessage(<formation uuid>, 50, <pid>, <treasure uuid>,
                                 1, 1, false, <server>, nil)
```

`50` is `MarchTargetType.DETECT_TREASURE` (same server; 182 cross-server, unexercised
here). It comes out on the wire as `world.march.formation.new`:

```
formationUuid  <long>          target        50
targetUid      <treasure uuid> path          "<from pid>;<to pid>"
soldierType    1               worldId       0
worldType      0               waitTimeIndex 1
autoBackHome   true            targetServer  <server>
formationParam { uuid, formations[], heroInfos[{heroUuid, index}×6] }
clientCreateUuid <a fresh uuid4 per march>
```

**The target type is the SECOND argument**, after the formation uuid — worth writing down
because a filter reading the first one sees a 19-digit number and matches nothing.

The pid confirms the tile arithmetic independently: the march's destination and the
`x`/`y` in the chat share are the same tile, `pid = y * 1000 + x + 1`, which is what
`SceneUtils.IndexToTilePos` inverts.

### 3. The claim — confirmed, and what it raises

```
UIUtil.GetDetectTreasureReward(<pid>)                 -- what is in it, before pressing
SFSNetwork.SendMessage("detect.event.claim.treasure", <uuid>, <server>)
  → SFSObject.PutLong uuid ; SFSObject.PutInt targetServer
```

Exactly the shape `claim_treasure` sends. The reply arrives under the same name and the
client answers it with `UIManager.OpenWindow(UIGiftPackageRewardGet, …)` — which is the
window `dismiss_treasure_reward` closes. The claim went out TWICE in this session
(the player pressed twice); the second send was answered the same way, so the press is
not obviously punished for being repeated.

**`push.detect.treasure.claim` is the alliance's own feed of the dig** — fourteen of them
arrived, in bursts, before and after the claim: one per member finishing their part.
It is a broadcast about somebody ELSE's finish as much as about ours, which makes it the
detector for «сокровище забрали» regardless of who took it.

## Status after this session

* Position read: **confirmed** (unchanged).
* Take command: **confirmed on the wire AND from the caller side** — the exact
  `SFSNetwork.SendMessage` call, its packing, its reply and the window it raises.
* Dig march: **confirmed from the caller side** — `MarchUtil.SendCreateMarchMessage` with
  target 50 and the full `world.march.formation.new` body.
* Announcement: **confirmed** — chat `shareType` 27 out, `world.treasure.share.chat` in.
* **Still unproven: the BOT doing it.** Every call `tools/lib/lua_actions.py` makes is now
  known to be the right one, but `actions/dev/work_treasure.md` has never been fired at a
  live chest — this session was a person pressing the game's own buttons. That is why the
  farming list still says 🟡.

## Watching it happen — the debug page (#1277)

A chest is out for minutes and the alliance digs it together, so the sniffer pair is
almost always too late: by the time anybody has started it the chest is gone. The answer
is something that is ALREADY listening —
`lua_actions.treasure_watch_install/stop/drain/state`, a pair of wrappers on
`SFSNetwork.SendMessage` / `SFSNetwork.HandleMessage` writing into a ring buffer that
lives in the game VM.

* **the buffer is in the game, not in the panel**, so a panel restart, a profile switch
  or a closed window loses nothing; the panel's own ring is the second copy, for what a
  GAME restart would wipe;
* **it does not touch the network interface at all**, so it coexists with the secret-task
  monitor's pcap — which is exactly what made this session's wire file empty;
* **it must not run beside `lua_trace`**: the tracer wraps the same two functions, and
  each would unwrap the other on the way out. **And since #1296 this is no longer only
  about a page somebody opened on purpose** — the auto-treasure errand's harvest lives in
  this same hook and is switched on by a TRIGGER, so a client nobody has touched can be
  holding one half of the pair. A thin or empty trace with a healthy client is explained by
  that far more often than by a fault; the check and the two calls that undo it are under
  «READ THIS BEFORE YOU RECORD A TRACE» below;
* the filter, with `wide` off, keeps anything `treasure`/`detect`, plus a `world.march.*`
  send at target 50/182 — the three moments above and nothing else.

Recipes: `actions/dev/watch_treasures.md`, `read_treasure_watch.md`,
`unwatch_treasures.md`. The page that plays them is `panel/tabs/treasure_debug/`, behind
«Разработка». `tests/test_treasure_watch.py` runs the hook in a real Lua.

---

# The 2026-08-08 session, and the errand that runs itself (#1296)

«Мне нужен триггер, реагирующий на уведомления о сокровищах с автоматической отправкой
ближайшего отряда и сбор подарка.» The recording that answered it:

* trace : `results/traces/20260808_125345_Сокровище_trace.log`
* wire  : `results/traffic/20260808_125346_Сокровище_traffic.jsonl`
* what the player did: «Собрал 2 сокровища, одно из них сам отправил в чат, чтобы пришло
  уведомление»

Every id quoted below is INVENTED, of the same shape as the real one — a uuid is 19
digits, a server is small, a tile index is `y * 1000 + x + 1`. The session's own values
are in the git-ignored trace and stay there (`CLAUDE.md`).

## The announcement, and where it does NOT travel

The badge the player sees is the chat share of §1 above, and this session confirms its
shape from the SENDING side, field for field:

```
SFSObject.PutUtfString attachmentId =
  {"shareType":27,"y":<y>,"x":<x>,"uuid":<treasure uuid>,"worldType":0,"worldId":0,
   "sid":<server>,"treasureId":"<cfgId>","oname":"<uid>"}
```

…and the reply arriving under `world.treasure.share.chat`, handled by
`ChatManager2.OnHandleMessage`. One message names everything the ability needs: the
chest's uuid, its server and its tile.

**And it is NOT on the wire.** The capture taken beside this trace holds
`push.world.march.new`, `push.lw.alliance.alert.info.remove`, `push.all.notice` and
keepalives — and not one `world.treasure.share.chat`. That is the chat channel doing what
`docs/research/chat.md` says it does: control on the game socket, broadcast on a TLS
websocket this repository cannot decode. **So a `panel/triggers.py` WIRE trigger on the
announcement is impossible, not merely slower** — the listener is deaf to it by
construction, and any design that starts «listen for the push» is finished before it
begins.

The measurement that pins it: the same message is in the Lua trace (line 10494 of the
run above) and absent from the JSONL recorded at the same second on the same interface.

## What else the session showed

* **The chest gets onto the map by hand.** `get.detect.info` fills the client's list of
  found chests (each record parsed by `DetectEventInfo.ParseData`, broadcast as event
  `91014`, positions read through `SceneUtils.IndexToTilePos`), and the player presses
  *Detect_Event_Info_Goto_Btn*, which sends **`detect.event.put.point.in.world {uuid}`**.
  That is a separate ability — «put my own found chest out» — and it is NOT what this
  task automates: the errand answers a chest that is already out.
* **`push.detect.treasure.claim` is not «somebody took it».** Fourteen of them arrived,
  in bursts, before and after our own claim: one per member who has finished their part,
  and every digger claims their own gift. Read as a loss it would hand the reward away;
  read as «this chest is dug and payable», it is the gate the claim waits for. The errand
  uses it as exactly that.
* **`UIUtil.GetDetectTreasureReward(pid)`** exists and answers `nil` on a tile with
  nothing on it (checked live on 2026-08-08, on tile 1 — no error, no window). It is
  logged as evidence but deliberately NOT used as the gate: there is no recording of it
  answering for a chest that IS dug, and a gate without a success recording is a guess
  (`CLAUDE.md`).

## «The nearest squad» — the negative finding, and it is the load-bearing one

**A squad has no position.** Read live off `ArmyFormationDataManager`, a formation
carries `index`, `uuid`, `totalSoldierNum`, its heroes, its capacity and its building —
and no tile, no coordinate, nothing that says where it is. The only positional read there
is is `WorldMarchDataManager:GetOwnerFormationMarch`, and a squad that HAS a march is by
definition not free.

So a free squad is standing in the base, every free squad is the same distance from the
chest, and **«send the nearest squad» cannot be resolved on the squad**. What can be
resolved is the CHEST: the errand orders its targets by Chebyshev distance from the
base's own tile (`LuaEntry.Player.world_main_pos` → `IndexToTilePos`) and works the
nearest first, spending the lowest free slot. The report names the distance it went by,
so the ordering is visible rather than claimed.

Anyone tempted to improve this: the thing to add is not a better search over squads, it
is **march speed** — squads differ by hero skill, and «nearest in time» is a different
question from «nearest in tiles». That needs a reading nobody has found yet.

## An empty squad is a squad nobody has asked about — measured again here

Live on 2026-08-08, twenty minutes apart, with nothing sent in between and the army
untouched in the game:

```
i1:n=3123  i2:n=2631  i3:n=2565      → later →      i1:n=0  i2:n=0  i3:n=0
```

The client's `totalSoldierNum` is a reply cache (#1285). A run that refused on it would
report «no squad to send» on a base with three full ones. So the errand ASKS —
`SFSNetwork.SendMessage(MsgDefines.GetFormationSoldier, <formation uuid>)` per empty
squad — marks that it asked (`asked-for-army` in the report), and the recipe presses
again after a short wait. Confirmed live: first press `free=0 empty=3 asked-for-army`,
second press `free=3`.

## The shape of the ability

The ear is the hook of #1277 — the same pair of wrappers on `SFSNetwork.SendMessage` /
`HandleMessage`, because a SECOND pair on the same two functions is how one unwrap
destroys the other. It now has two consumers: the debug page's ring buffer (`W.on`) and
the errand's harvest (`__lw_treasure_auto.on`), independent switches, and
`treasure_watch_stop` only puts the doors back when neither is listening.

The harvest turns an announcement into a target:

```
DataCenter.__lw_treasure_auto = {
  on, seen = {["<uuid>"] = <ms>}, news = <n>,
  targets = { {uuid, pid, x, y, server, at,   -- announced
               sent, squad,                   -- the march that went out
               dug,                           -- push.detect.treasure.claim seen
               claimed, done, why} },
}
```

…and `treasure_auto_step` walks the whole queue one step per press: the nearest free
squad marches onto the nearest chest (`MarchUtil.SendCreateMarchMessage(formation, 50|182,
pid, uuid, 1, 1, false, server, nil)` — **the target type is the SECOND argument**), and
a chest whose dig has been heard, or whose grace has run out, is claimed
(`SFSNetwork.SendMessage(MsgDefines.DetectEventClaimTreasure, uuid, targetServer)`). One
press, because a chest is a race — the same reasoning the rally join was rebuilt on
(#1281).

What plays it: `src/lastwar_bot/actions/auto_treasure.md`, and the poll trigger
`treasure_auto` in `panel/triggers.py` (10 s, `immediate`). **The poll reads the LOCAL
table above** — one daemon round trip, no request to the server, nothing asked of the
map — so «poll» here means polling the panel's own ear, and the chest is heard in the
same second the client hears it. The check is also true whenever nothing is listening, so
a client restart (which wipes the VM and the hook with it) re-arms on the next tick
instead of leaving the errand silently deaf.

Confirmed live on 2026-08-08 with no chest on the map: the arm, the poll, the step, the
army fallback, the disarm, and the blob parser with the tile arithmetic inside the game's
own Lua (`pid = y * 1000 + x + 1`, 19-digit uuid intact — Lua 5.3 integers).
`tests/test_treasure_auto.py` runs the whole errand in a real Lua.

## READ THIS BEFORE YOU RECORD A TRACE — the harvest and `lua_trace` collide

**While the #1296 harvest is installed, a simultaneous `lua_trace` hooks the same two
functions.** `SFSNetwork.SendMessage` and `SFSNetwork.HandleMessage` are wrapped by both,
and each unwraps the other on the way out: whichever restored last wins, and what the
loser was recording simply stops arriving. The trace comes out short or empty, the client
is perfectly healthy, and there is no bug to find.

This warning is louder than the #1277 one above it, and for a reason that has nothing to
do with the mechanism: the debug page's ring is something a person switches on knowing
they did, in the same sitting. **The harvest is switched on by a TRIGGER** — a checkbox on
another tab, on another profile, possibly weeks ago — and then it sits there in a client
nobody has touched, silently holding one half of the pair. Somebody records a session,
gets a thin trace, and starts looking for a fault in the tracer.

So, before recording: **check whether the auto errand is listening**, and stop it if it is.

```
# is anything holding the doors?
READ_LUA  treasure_watch_state()      -> `on=<ring> … `  and the auto switch:
          (DataCenter.__lw_treasure_auto or {}).on
# put them back (this also reports `hooked=` and `auto=`, so it says who was left):
          lua_actions.treasure_auto_disarm() ; lua_actions.treasure_watch_stop()
```

`treasure_watch_stop` deliberately refuses to unhook while the auto switch is on — it
mutes the ring and answers `hooked=1 auto=1` — so the disarm has to come first. That is
the state a thin trace is explained by, and reading it takes one call.

## A refused claim says NOTHING — measured, and it changed the design

Asked and answered live on 2026-08-08, by claiming a chest uuid that cannot exist
(`detect.event.claim.treasure` with an invented 19-digit id, on the home server):

| what was looked at | what came back |
|---|---|
| the send itself | returns cleanly, no error, no exception |
| `UICommonMessageTip` | **nothing on screen**, checked at 0.3 s, 0.8 s and 1.6 s |
| `UIGiftPackageRewardGet` | closed |
| the reply | arrives ~150 ms later **under the same command name**, and the hook reads NO fields off it |

So there is no observable difference between a claim the server paid and one it threw
away — in the moment of sending. **The consequence is a design constraint, not a
curiosity:** a step that treats «the send did not throw» as payment writes the chest off
and stops working it. The first version of the errand did exactly that, and it did it in
the worst possible case — the grace firing while the squad was still walking, which is the
case the grace was ADDED for. A chest 300 tiles from the base outlasts any grace worth
having.

What replaced it, both halves needed:

* **the grace waits for the clock AND for the march to be over.** The target keeps the
  uuid of the squad it was sent with, and `GetOwnerFormationMarch` on that squad answers
  «still out» for one call. A claim is never sent into a march in flight.
* **payment is the reward window.** `UIGiftPackageRewardGet` is what the client raises on
  a claim the server paid (seen in the 2026-08-07 trace), so the chest is spent when that
  window is up within seconds of our claim — and a chest whose tries all ran out is
  written off as `claim-unconfirmed`, never as `claimed`. Retries are on a clock
  (25 s apart, four of them), because a refusal gives nothing to retry ON.

The window is the client's for every reward there is, so it is only read as ours while it
is fresh. That is the honest limit of the proof, and it is still the best there is: the
wire says nothing either way.

**Still unproven: a live chest.** No detect event was running during the work, so the
march and the claim have never gone out at a real target from this path — the farming
list stays 🟡 until one has.
