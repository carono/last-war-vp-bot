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
