# The lucky packet — the free diamonds a surprise box drops, and how it is given away

Reverse-engineered live on 2026-09-03 for task #2397, on an account that had just opened
surprise boxes and been given the big bonus. Everything below was read out of the running
client through the panel's own dev scenarios; nothing here comes from a capture, because
the share rides the chat leg and that leg is TLS (`docs/research/chat.md`).

## 1. What the bonus is

A surprise box sometimes drops a **red packet of free diamonds the player may give away**.
The player has **one hour** from the drop to hand it to the alliance; the diamonds are the
server's, so giving it away costs the account nothing at all, and an hour later the packet
is gone whether or not anybody pressed anything.

The client calls it a LUCKY PACKET and its own tables call the mechanic
`lw_conveyluck` — «передача удачи».

## 2. Where the client keeps it

```
DataCenter.LuckyBuffManager                       (Instance is the manager itself)
  notSharedLuckyPacketList  uuid -> {configId, uid, expireTime, count}
  shortestTimePacketUUid    the uuid that runs out first
  luckyConfigList           configId -> a row of `lw_conveyluck`
  GetNotSharedLuckyPacketList / GetShortestExpireTime / FilterExpiredLuckyPacket
  OpenLuckyPacketSharePopup                       (opens the give-away window)
  AddLuckyPacket / UpdateLuckyPacket / OnReceiveLuckyPacketData
```

A live reading, with the identifiers replaced by invented ones of the same shape:

```
notSharedLuckyPacketList = {
  ["1000000000000000001"] = {configId = 102, uid = "1000000000000000001",
                             expireTime = 1700000000000, count = 1},
}
shortestTimePacketUUid = "1000000000000000001"
```

`expireTime` is the game's own millisecond stamp; the clock to judge it by is
`UITimeManager:GetInstance():GetServerTime()`, which answers in milliseconds too (the PC
clock lies — `docs/research/game-clock.md`).

The config row, by the column names its metadata gives:

| column | value on row 102 |
|---|---|
| `id` | 102 |
| `type` | 1 |
| `red_packet` | 502 — the red-packet template the share turns into |
| `switch` | 1 |
| `share_title` / `share_desc` | `luckyBuff_limit_reason_1` / `luckyBuff_desc_share_1` |
| `share_pic` | the popup's picture |

## 3. Giving it away — three of the client's own windows

`OpenLuckyPacketSharePopup()` opens **UIShareLuckyBuffPopup**. Its view holds the packet
(`curLuckyPacketList`, `curSelectedPacketIndex`, `curTotalPacketNum`) and, worth noting,
`isPlayerInAlliance` — an account outside an alliance has nowhere to put the packet.

The popup's `OnBtnShareClick()` **sends nothing**. It opens **UIPositionShare**, the same
room chooser a coordinate share uses (`docs/research/chat-coord-share.md`), with the
payload already prepared in `View.chat_data_param`:

```lua
{post = 611,                -- PostType.RedPackge_New
 redPocketId = 995002,      -- the packet the server will hand out
 redPocketType = 7,
 uid = "<the packet uuid>",
 sid = <server>, worldId = 0, worldType = 0,
 expireTime = <ms>}
```

The chooser's `View.list` holds the rooms it offers. **Live it offered exactly one — the
alliance room** (`group = "alliance"`, `category = "ALLIANCE"`, room id
`alliance_<server>_<32 hex>`); there was no world room and no DM in the list. Picking it
is `View:OnItemClick(row, 1)` — **the ROW, not an index**: an index throws inside the view
(`UIPositionShareView.lua:508: attempt to index a number value (local 'channel')`), which
is how the signature was found.

The moment the row is clicked the packet leaves `notSharedLuckyPacketList` and the client
opens `LWUIRedPacketDetails` over the chat. That transition — the list emptying — is the
only success signal there is, and it is what `actions/share_lucky_packet.md` checks.

**The send itself was not seen on either ear.** A wrapper on `SFSNetwork.SendMessage`
caught nothing but ordinary traffic, and one on `ChatManager2:GetInstance().Net
.SendSFSMessage` installed a second earlier caught nothing at all — so the share leaves by
a path neither wrapper covered. What that means in practice: the headless send is
WRITABLE from the payload above (post 611 + the attachment, `al.msg` for the alliance
channel, exactly as `tools/lib/chat_share.py` does it for a coordinate), but it is not yet
PROVEN, and a packet is one and the window is an hour. The recipe drives the client's own
windows for that reason and no other.

## 4. Gates

* **Nothing to share** — `notSharedLuckyPacketList` empty.
* **Expired** — `expireTime` behind the server clock. The client sweeps the list itself
  (`FilterExpiredLuckyPacket`) but not instantly, so a dead packet can still be in it.
* **No alliance** — `LuaEntry.Player.allianceId` empty; the chooser has no room to offer.
* **Already shared** — the same reading: a packet given away is off the list.

## 5. What announces a drop — STILL OPEN

The bonus falls out of DIFFERENT boxes, so there is no one press to hang it on, and #2397
could not name the command that announces it: the drop it acted on had happened before
anybody was listening, and the client had loaded no push module for it — only
`Net.Msgs.RedPacket.GetAllianceRedPacketMessage` and `…RedPacketsRvdIdMessage` were in
`package.loaded`. The candidates the defines offer are

```
PushPrePareRedPacket            = push.prepare.red.packet
PushReceiveAssignRedPacketMessage = push.receive.assign.red.packet
```

and a wire trigger built on a guess either never fires or fires on the wrong thing.

**An ear was written and then removed, on the person's own decision** (#2397): «слушать
сейчас бесполезно, редкое событие, ставь хук, чтобы после открытия загадочных ящиков с
припасами проверял шаринг и раз в полчаса тоже проверял». The ear
(`watch_lucky_packet.md`) wrapped `SFSNetwork.HandleMessage` and compared the size of the
list before and after every message the client received — cheap per message, but on the
hottest path there is, to learn one name for an event that happens rarely. It is in the
history if it is ever wanted again (commit c1643c9f).

So the two moments that look for a packet are the ones that cost nothing:

* **the run that OPENED a box** — `use_item.md` when the item it spent was of a chest kind
  (`USABLE_ITEM_TYPES` 5 / 59 / 109 / 150), and `open_explorer_chests.md` at the end of
  its run;
* **the `lucky_share` errand, every half hour** — a local reading of the list against the
  client's own clock, one VM round trip, nothing on the wire.

Half an hour against an hour-long window catches a packet with the window to spare, and
neither moment is a background question to the SERVER, which is what `CLAUDE.md` forbids.

## 6. What the panel does with it

* `actions/read_lucky_packet.md` — `have= live= min= alliance=`, plus what the ear has
  heard. One VM round trip, no request to the server.
* `actions/share_lucky_packet.md` — the gate, then the three windows, then the list read
  back. It picks the room by `group == 'alliance'` and closes the chooser untouched when
  there is none: a share posted to the world room is visible to the whole server and
  cannot be taken back.
* «События» → «Ящик с сюрпризом» on the phone: the state, the minutes left, «Обновить»
  and the give-away, which asks first.
* The errand `lucky_share` (`panel/timers.py`), 30 minutes, and the two chest hooks above.

## 7. The other side: somebody ELSE's packet, and taking a share of it (#2405)

Read live on 2026-09-04, on a client that had none in flight — everything below was got by
INSPECTING the client (managers, message classes built in memory with sentinels and read
back), and nothing was sent while it was found.

### 7.1 What the announcement is

A shared packet arrives as one ordinary chat message, `post = 611`, and the payload is the
message's own `extra.customJsonParam` (JSON). Its keys, with invented values of the same
shape:

```json
{"uuid": "<33 chars>", "packetId": 502, "goodsId": 995002, "luckSiphonId": 102,
 "expiredTime": 1700000000000, "serverId": 8000, "redPacketServerId": 8000,
 "hasRob": true}
```

`packetId` is the red-packet template (`lw_conveyluck.red_packet` — 502 on row 102, §2),
`goodsId` the reward goods the sharer named (`redPocketId` in the share payload, §3), and
`luckSiphonId` the `lw_conveyluck` row itself. So the two sides line up field for field:
what §3 sends is what this reads.

The client can be asked about it in its own words too: `ChatMessage:isRedPack()`,
`isSystemOrFestivalRedPack()`, and `RedPacketManager` has `GetIsOverdue` / `GetIsReceive`
/ `GetIsNone` / `GetReceiveCountByChatData` — but every one of those wants the manager's
own parsed data object rather than the raw message (`GetIsOverdue(msg)` raises
`attempt to perform arithmetic on a nil value (local 'expiredTime')`), so the recipe reads
the JSON itself and judges `expiredTime` against `UITimeManager:GetServerTime()`.

### 7.2 The press

```
MsgDefines.OpenRedPacket = open.red.packet     →  {uuid, cfgId, chatType, serverId}
```

The shape was read by building the message and reading its own SFS object back, never by
sending one:

```lua
local cls = SFSNetwork.GetMsgType('open.red.packet')
local msg = cls:NewMessage('ARG1', 2222, 3333, 4444)   -- in memory; nothing leaves
-- msg.sfsObj  ->  uuid=ARG1  cfgId=2222  chatType=3333  serverId=4444
```

**The fourth field is not optional.** The first live run of the recipe sent three and the
client's own serialiser refused it before a byte left the machine —
`SFSDataSerializer.lua:39: bad argument #2 to 'pack' (number expected, got nil)`. It is the
packet's own `redPacketServerId`.

`chatType` is `RedPacketManager.ChannelType`: World 1, **Alliance 2**, Season 3,
AliFriend 4 — taken from the room the message arrived in.

**`cfgId` is sent as `packetId`, and it is the one guess in the ability.** The attachment
holds two ids that could be it and there was no live packet to settle it; the ear records
which one it sent (`cfg=` in its own rows) so the first live packet answers the question.

The neighbouring commands, for whoever needs them next:

| define | command | args | what it is |
|---|---|---|---|
| `GetAllianceRedPacket` | `get.alliance.red.packet` | none | the alliance's packet list — a REQUEST, deliberately not made on a clock |
| `RedPacketDetail` | `red.packet.detail` | `uuid, cfgId, chatType, serverId` | who took what out of one |
| `RedPacketsRvdId` | `redPackets.rvd.id` | — | ids already received |
| `GetRedPack` / `SendRedPack` | `get.red.pack` / `send.red.pack` | one param each | the ordinary (non-lucky) red packets |
| `PushNewSysRedPacket`, `PushPrePareRedPacket`, `PushReceiveAssignRedPacketMessage` | pushes | — | announcements the client knows how to receive; none of them carries the chat share |

### 7.3 The daily ceiling, and who counts it

`RedPacketManager:GetRedPacketGetNum()` / `GetRedPacketGetMaxNum()` — measured `0 / 10`.
That is the CLIENT's own count of packets taken today and it is the only authority the
panel uses; nothing keeps a tally of its own (the rule the fireworks card already goes by).
`GetIsOpen()` = 1, `GetOpenLevel()` = 4 and `entrySwitch` = true say the mechanic is on for
this account.

### 7.4 Why it is an ear and not a clock

The announcement rides the chat leg, which is TLS and cannot be sniffed
(`docs/research/chat.md`), so there is no wire event to trigger on; and
`get.alliance.red.packet` on a clock is precisely the background question `CLAUDE.md`
forbids. What the client does give is the ingress the chat reader already uses —
`Chat.Model.ChatMessage:onParseServerData`, which runs for every parsed message with the
chat window shut. `actions/watch_red_packets.md` wraps it and presses inside the call that
delivered the announcement; `read_red_packet_watch.md` says what it heard;
`collect_red_packets.md` offers the same gate to the messages the client is ALREADY
holding (`roomDatas[<room>].msgs`), which asks the server nothing either.

The gates, all local: the day's count against its ceiling, `expiredTime` against the game's
clock, `redPacketServerId` against our own server, a room whose channel the client does not
name, and a uuid the ear has already pressed at — a second open at an emptied packet is
refused WITH A POPUP, which is the mistake #2365 paid for on the fireworks.

**Still open:** how many diamonds a share was worth. The reply was not read (no live
packet), so the card counts PACKETS and says nothing about diamonds rather than inventing
a number.

### 7.5 The thank-you, and the window it leaves open (#2603)

Taking a gift is not the whole gesture a person makes: they press the **like** and then
shut the window the client opened over the chat. Both are done by the ear now, two
seconds after the press, so neither is in the way of the race the press itself is in.

**The like is a THUMBS-UP of its own kind.** `InteractiveUtil.ThumbsUpType` names sixty
of them and two are this mechanic — `AllianceLuckSiphonBuff = 60` and
`AllianceLuckSiphonRedPacket = 61`. That 61 is the gift and not something else is the
client's own word for it:

```lua
InteractiveUtil.GetLangKeyByThumbType(61)   -- conveyLuck_like_tips
-- «Спасибо за Счастливый подарок, которым ты поделился»
```

The send is

```lua
InteractiveUtil.DoSendMessage(<sharer uid>, 61, <chat message seqId>, '')
--  thumbs.up  {targetUid, type, content, extParam}
```

and **the types are not free**. The uid and the sequence go as STRINGS: passing the
sequence as a number is refused by the client's own serialiser before a byte leaves —
`SFSDataSerializer.lua:55: attempt to get length of a number value (local 'val')` — the
same shape of mistake the fourth field of `open.red.packet` cost in §7.2.

**`InteractiveUtil.TryThumbsUp` is deliberately not used.** It is the front door
(`TryThumbsUp(targetUid, thumbsUpType, identifier, callback, extParam, notSendMessage_)`)
and it answers `true` while sending nothing at all: measured three ways — from the VM
thread, from the main thread through `TimerManager:DelayInvoke`, and with a wrapper on
`SFSNetwork.SendMessage` watching the wire — the wire stayed empty and the day's count
did not move.

**The proof is a spent charge, never a send that did not raise.** Likes of a kind are
capped and the client counts them itself:

| call | answer, measured |
|---|---|
| `GetMaxThumbsUpCount(61)` | 10 a day |
| `GetCanThumbsUpCount(61)` | what is left of them today |
| `CanThumbsUp(61)` | is the mechanic open at all |

So the ear reads the count, sends, reads it again, and only a count that DROPPED is
reported as a thank-you. Verified end to end on the ordinary chat like (type 2, the same
command and the same field types): 20 → 19.

**«Уже поставлен» is NOT a flag the client keeps — measured, and it is a negative
finding worth stating loudly.** Three candidates were tried on a message this account had
just liked for real (type 2, the charge spent, 20 → 19):

* `ChatMessage:getLikeNum()` stayed `0` on the liked message and on its neighbours;
* `ChatManager2:CheckThumbsUp(index, uid, seqId, callback, upType)` is a GATE, not a
  memory: it needs a callback (without one it raises `attempt to call a nil value (local
  'callback')`) and it called back — with no arguments — for the liked message exactly as
  for the four that were not;
* `GetGiveLikeAnim` / `GetGiveLikeMsgTime` are the popup's own bookkeeping, not the
  server's.

So there are two things that keep a like from going twice, and neither is a per-gift
flag: **the day's charges** (`GetCanThumbsUpCount(61)`, ten of them, refused when spent)
and **the ear's own ring of uuids** — a gift is opened once, so the thank-you that
follows the opening goes once too. A client restart empties the ring, and the day count
is what stands behind it.

**The window** is `LWUIRedPacketDetails`, with `LWUIRedPacketOperation` beside it, and
both are closed with the client's own `Ctrl:CloseSelf()` — never `DestroyAllWindow`,
which takes the HUD with it and does not give it back.

**And the card the ability lives under was a dead one.** `lucky_watch` played
`watch_lucky_packet`, the ear removed in §5 — the recipe went in #2397 and the row did
not, so every profile that ever ran it kept failing every five minutes («unrecognised
statement») under a card showing its bare name, because a listener that is not in the
code has no label key either. `panel/triggers.py::RETIRED_TRIGGERS` drops it, and
`red_packet_watch` is the card, named the way the game names the thing.
