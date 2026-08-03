# Sharing coordinates in chat

Reverse-engineered live for task #1089 from a PM run to **<Player9>**
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
`[<ALLY>] <PlayerName> (БЗ #935 X:600 Y:400)`. A consumer that only reads `getMsg()`
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
| **node being gathered** | 13 | `posType: 6`, `olv: 10`, `oname: 129027`, `uname: "Добытчик: [<ALLY2>]<Player10>"` |
| **secret task / hero dispatch** | 13 | `posType: 22`, `uuid`, `cfgId`, `dispatch: 1`, `uname`, `abbr`, `oname: "Секретное задание"` |
| **own march** | **687** | `postType: 687`, `marchUuid`, `marchType: 15`, `key: "science_condition"`, `level`, `name`, `serverId`, `oname` |

`oname` is not one type — an integer template id for a node, a localised name for
a task, a `"[TAG] Name"` label for a base; any consumer must tolerate all three
(the same caveat `chat.md §3.3` records). The older passive capture additionally
reported `posType` 2 (monster) and 5 (mine); those were not re-observed in this
run, so treat the list as open-ended rather than exhaustive.

Note `uid` appears **only** on the bare pin (`posType 0`), where it identifies the
sharer. Every richer kind describes the object instead and carries no `uid`.

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

Three sends through the tool landed in the <Player9> DM room:

| seq | what | rendered bubble |
|---|---|---|
| 132 | bare pin at 500,500 | ` (БЗ #935 X:500 Y:500)` |
| 133 | `--my-base` | `[<ALLY>] <PlayerName> (БЗ #935 X:600 Y:400)` |
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

## 6. Sharing a secret task (posType 22)

Secret tasks ("секретки" / hero dispatch) do not need a capture to find: the client
keeps a parsed copy in `DataCenter.ActDispatchTaskDataManager` —

| field | meaning |
|---|---|
| `singleTask` | your own tasks; `pointId = 0`, they sit inside your base, so they have **no map position and cannot be shared** |
| `allianceTask` | alliance members' tasks placed on the world map (124 rows in the sample session) |

Each record has `uuid`, `cfgId`, `pointId` (→ tile via `SceneUtils.IndexToTilePos`),
`targetServer`, `completionTime` (dispatch finished), `actEndTime` (expiry),
`stealInfoList`, and an `avatar` holding the owner's `name` and alliance `abbr`.
"Worth sharing" is `completionTime <= now < actEndTime` — the same
dispatch-complete / not-expired gate the `can_loot` rule uses for tiles.

`tools/dispatch_tasks.py` lists them and prints the ready arguments:

```bash
C:\Python312\python.exe tools\dispatch_tasks.py --alliance --ready --nearest --share-args
C:\Python312\python.exe tools\chat_send.py --to <peerUid> \
    --coords "610,490" --coord-server 935 --coord-type 22 \
    --coord-label "Секретное задание" \
    --coord-extra '{"uuid":…,"cfgId":…,"uname":"<Player2>","abbr":"<ALLY>","dispatch":1}'
```

Verified live: `seq 137` in the <Player9> room rendered
`Секретное задание [<ALLY>] <Player2> (БЗ #935 X:610 Y:490)` — field-for-field the same
attachment shape the game's own tile-bubble share produced (`seq 126`, `seq 136`).

`uuid` exceeds 2^53, so it must never be round-tripped through a float: it is read
as a Lua 5.3 integer, printed exactly, and shipped as JSON text.

## 7. Using it from your own script

The reusable core lives in **`tools/lib/chat_share.py`** — import that, not the CLI.
`tools/chat_send.py` and `tools/dispatch_tasks.py` are thin wrappers over it, so
there is one implementation to keep correct.

```python
import sys, os
sys.path.insert(0, os.path.join("tools", "lib"))
import chat_share, lua_client

ev = lua_client.get_evaluator()          # warm daemon, or a local LuaEval
me = chat_share.self_profile(ev)         # {uid, srv, x, y, name, abbr}
room = chat_share.dm_room(peer_uid, me["uid"])

chat_share.share_point(ev, room, chat_share.point_attachment(610,490, 935),
                       peer_uid=peer_uid)
```

| function | what it gives you |
|---|---|
| `self_profile(ev)` | `{uid, srv, x, y, name, abbr}` — uid, home server, own base tile, name, alliance tag |
| `self_label(profile)` | `"[TAG] Name"`, the label the game puts on a shared base |
| `dm_room(peer, self)` / `peer_of(room)` | build a DM room id / read the peer back out of one |
| `point_attachment(x, y, srv, pos_type=0, label=…, uid=…, extra={…})` | `attachmentId` for any map object |
| `base_attachment(profile, label=None)` | `attachmentId` for "share my position" |
| `task_attachment(task)` | `attachmentId` for a secret task, from a `dispatch_tasks` record |
| `share_point(ev, room, attachment, peer_uid=None, lang="ru")` | send it; `True` when the game confirmed |

`dispatch_tasks.read_tasks(ev)` returns `(tasks, server_time_ms)`; each task is a
plain dict (`kind`, `uuid`, `cfgId`, `pointId`, `x`, `y`, `srv`, `owner`, `done`,
`expires`, `steals`, `name`, `abbr`) that `task_attachment()` consumes directly:

```python
sys.path.insert(0, "tools")
import dispatch_tasks

tasks, now = dispatch_tasks.read_tasks(ev)
ready = [t for t in tasks if t["kind"] == "alliance" and t["pointId"]
         and t["done"] and t["done"] <= now < t["expires"]]
chat_share.share_point(ev, room, chat_share.task_attachment(ready[0]),
                       peer_uid=peer_uid)
```

Things worth knowing before you build on this:

- **Outgoing chat cannot be unsent.** Build the attachment, print it, and only then
  call `share_point()`; the CLI's `--dry-run` exists for the same reason.
- `share_point()` returns `False` when the game did not confirm — treat that as a
  failed send, not a warning. It is also how you notice a dead daemon / dead game.
- Only the **DM** command is verified live; world / national / alliance are wired
  from the client's defines but untested.
- A record whose `pointId` is `0` has no map position (your own tasks sit inside
  your base) and cannot be shared.
- `uuid` exceeds 2^53 — keep it an `int`, never a float.

## 8. Tooling

- `tools/lib/chat_share.py` — the importable surface described above.
- `tools/lib/lua_actions.py` — `chat_share_point(room, attachment_json, ...)` and
  `chat_share_cmd(room)`, the Lua chunk builders underneath it.
- `tools/dispatch_tasks.py` — list live secret tasks (`--own` / `--alliance`,
  `--ready`, `--nearest`, `--json`, `--share-args`).
- `tools/chat_send.py`:
  - `--coords "600,400"` — share a map pin (accepts every spelling
    `tools/lib/coords.py` parses: `X:600 Y:400`, `@[600,400|935]`, `(600,400)`, …),
  - `--coord-server`, `--coord-label`, `--coord-type` (attachment `posType`),
  - `--coord-extra '<json>'` — kind-specific attachment fields (secret task, node, …),
  - `--my-base` — share own base like the in-game button,
  - `--dry-run` previews the room, command and attachment without sending.
