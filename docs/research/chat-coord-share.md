# Sharing coordinates in chat

Reverse-engineered live for task #1089 from a PM run to **EleNita**
(`results/traces/20260728_223330_sniff_sharing_cords_trace.log`, messages
`seq 125…130` in that DM room). This is the coordinate half of
[`chat-send.md`](chat-send.md) (text / emoji / stickers) and complements
[`chat.md §3.3`](chat.md) (the passive-capture view of the same feature).

The wire capture was again useless — chat rides the TLS WSS leg, and the recorded
`*_traffic.jsonl` held only keepalives and `push.world.march.*`. Everything below
comes from the Lua trace plus live introspection through the warm daemon.

## 1. A coordinate is not text

A shared map point is an ordinary `ChatMessage` with three distinguishing fields:

| field | value |
|---|---|
| `post` | **13** (`PostType.Text_PointShare`) |
| `msg` | the literal placeholder `"?"` |
| `attachmentId` | a JSON string describing the map object |

The bubble the player sees is rendered client-side from the attachment —
`ChatMessage:getMessageWithExtra()` turns it into e.g.
`[TLou] Carono (БЗ #935 X:567 Y:471)`. A consumer that only reads `getMsg()`
sees `"?"`; `tools/chat_reader.py` already prefers `getMessageWithExtra()` for
exactly this case.

On the received copy `extra` is `{attachmentId, post, userLang, isProxy = 1}` —
note there is **no** `senderLevel`, unlike a plain text message.

## 2. attachmentId shapes

Every kind carries `x`, `y`, `sid` (server), `worldId`, `worldType`. What
identifies the object is `posType` plus a few kind-specific fields. Observed
live, one message per row:

| shared object | `post` | attachment |
|---|---|---|
| **own base** ("share my position" button) | 13 | `{x, y, sid, worldId, worldType, oname:"[TAG] Name"}` — **no `posType`** |
| **bare map tile** | 13 | `posType: 0`, `uid: "<sharer uid>"` |
| **resource node** | 13 | `posType: 1`, `olv: 21`, `oname: "2000001"` (a template id, not a name) |
| **node being gathered** | 13 | `posType: 6`, `olv: 10`, `oname: 129027`, `uname: "Добытчик: [WPBs]tonyv811976"` |
| **secret task / hero dispatch** | 13 | `posType: 22`, `uuid`, `cfgId`, `dispatch: 1`, `uname`, `abbr`, `oname: "Секретное задание"` |
| **own march** | **687** | `postType: 687`, `marchUuid`, `marchType: 15`, `key: "science_condition"`, `level`, `name`, `serverId`, `oname` |

`oname` is not one type — an integer template id for a node, a localised name for
a task, a `"[TAG] Name"` label for a base; any consumer must tolerate all three
(the same caveat `chat.md §3.3` records). The older passive capture additionally
reported `posType` 2 (monster) and 5 (mine); those were not re-observed in this
run, so treat the list as open-ended rather than exhaustive.

A march share is a different `post` entirely (687) and is produced by
`MarchUtil.ShareOneMarch(uuid, key, level, name, ownerName)`.

## 3. Sending — NOT `__sendToRoom`

The text/emoji choke point `ChatManager2:__sendToRoom(roomId, msg, extra, reply,
isProxy, post)` **cannot** send a coordinate. It rebuilds `extra` itself and
silently drops `attachmentId`: a probe send came back from the server as

```
seq=131 post=13 att='' extra='post=13; senderLevel=35'
we='Сообщение этого типа не поддерживается текущей версией игры.'
```

Shares have their own command class, `Chat.NetMessage.ChatShareCommand`, built by

```
ChatShareCommand:OnCreate(param)
```

and dispatched on the **chat** connection, not the game gateway
(`SFSNetwork.GetMsgType("chat.room.send")` is `nil`):

```lua
ChatManager2:GetInstance().Net:SendSFSMessage(cmd, param)
```

`ChatNetManager` has two senders — `SendMessage` is the WebSocket/`tableData`
variant and dies with `attempt to index a nil value (field 'tableData')`;
`SendSFSMessage` is the one that matches an `sfsObj`-building command like this.

### param

`OnCreate` reads these keys, in this order (revealed with a proxy table whose
`__index` logs every lookup):

```
post, lang, msg, roomId, tradeName, itemIds, tradePoint, attachmentId,
chatType, langRoomLang, toUser, reportUid, cardUuid, planIndex, bossUid,
ossAddress, serverIdEx, introductionEx, freeEx
```

Everything from `tradeName` on belongs to other share kinds and may be nil. A
coordinate share needs:

```lua
{post = 13, lang = "ru", msg = "?", roomId = <room>, attachmentId = <json>,
 toUser = <peer uid>, chatType = 0}
```

### command per channel

`ChatMsgDefines` names one command per channel (`getShareChannelGroup` picks it):

| channel | command | extra param |
|---|---|---|
| DM | `chat.room.send` (`ChatSharePerson`) | `toUser` = peer uid |
| World | `chat.country` (`ChatShareCountry`) | — |
| National | `chat.country` | `langRoomLang` = `ru` / … |
| Alliance | `al.msg` (`ChatShareAlliance`) | — |

**Only the DM command is verified live.** The other three are read off the
client's own defines and are implemented but untested (posting to those rooms is
visible to other players).

## 4. Verified live

Three sends through the tool landed in the EleNita DM room:

| seq | what | rendered bubble |
|---|---|---|
| 132 | bare pin at 500,500 | ` (БЗ #935 X:500 Y:500)` |
| 133 | `--my-base` | `[TLou] Carono (БЗ #935 X:567 Y:471)` |
| 134 | `--coords "X:512 Y:498" --coord-label "Тест координат"` | `Тест координат (БЗ #935 X:512 Y:498)` |

seq 133 is shape-identical to `seq 125`, which the player produced by pressing
the game's own "share my position" button — so the tool reproduces the client
byte-for-byte, and Cyrillic labels survive the daemon hop.

## 5. Reading the self profile

A "share my position" attachment is labelled from live player state:

| value | source |
|---|---|
| base tile | `SceneUtils.IndexToTilePos(ChatInterface.getPlayer().world_main_pos)` |
| server | `ChatInterface.getSelfServerId()` |
| name / alliance tag | `ChatInterface.getUserData(uid).userName` / `.allianceSimpleName` |

`ChatUtil.GeneratePrivateRoomId(userId)` is the client's own DM-room builder, if
the hand-rolled `custom_<peer>_<self>_v2` concatenation ever needs replacing.

## 6. Tooling

- `tools/lib/lua_actions.py` — `chat_share_point(room, attachment_json, ...)` and
  `chat_share_cmd(room)`.
- `tools/chat_send.py`:
  - `--coords "567,471"` — share a map pin (accepts every spelling
    `tools/lib/coords.py` parses: `X:567 Y:471`, `@[567,471|935]`, `(567,471)`, …),
  - `--coord-server`, `--coord-label`, `--coord-type` (attachment `posType`),
  - `--my-base` — share own base like the in-game button,
  - `--dry-run` previews the room, command and attachment without sending.
