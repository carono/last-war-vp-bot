# «Помощь союзников» in the Restricted Area Training (`idle.game.event.*`)

How an alliancemate's plea for help in the Forbidden/Restricted Area Training reaches the
client, what joining it sends, and what the panel can listen to instead of asking.

Task #2755. The activity the game calls **«Тренировка в запретной зоне»** (`t11_idle_game_name_1`,
EN «Restricted Area Training») is the client's `T11IdleGame`. While it runs, the player
meets *events* — quests handed out by characters — and some of them may be **shared to
alliance chat**, where alliancemates can join in and help until the event is done.

## 1. The chat card

The plea is an ordinary alliance-chat message with a special post type:

| | |
|---|---|
| post type | **730** — `Chat.Constant.PostType.T11IdleGameAllianceHelp` |
| card | `UI.UIChatNewV2.Component.ChatItem.Post.T11IdleGameAllianceHelp` |
| text | `t11_idle_game_desc_51` — «Дорогие могущественные союзники, мне очень нужна ваша помощь!» / «Mighty allies, I really need your help!» |
| window it opens | `UI.T11IdleGame.T11IdleGameTaskEventAllianceHelp.*` |

Measured on one live account: **6–11 of them a day** in one alliance room
(`profiles/<name>/chat_log.jsonl`, post `730`).

The message rides the chat **WebSocket**, not the game's plain-TCP leg, so a passive
capture is deaf to it by construction (`docs/research/chat.md` §1). The client's own
parse is the ear — the same hook `tools/chat_reader.py` already uses
(`Chat.Model.ChatMessage.onParseServerData`).

## 2. The wire

Read off the client's own message classes by handing the send a recording `SFSObject` and
aborting in `ToBinary`, so nothing was sent to learn this
(`docs/research/alliance-star.md`, «The wire»):

| command | fields |
|---|---|
| `idle.game.event.all` | none — «my own events» |
| `idle.game.event.share` | `eventUuid` — put mine in alliance chat |
| `idle.game.event.get` | `uid`, `eventUuid`, `clientParam` — fetch somebody else's event |
| **`idle.game.event.help`** | **`targetUid` (string), `eventId` (Int), `eventUuid` (Long)** — JOIN IT |
| `idle.game.event.receive` | `uuid` — take the reward of a finished event |
| `push.idle.game.events` | the push the client subscribes to for event changes |

So one join is one send, headless — no window, no tap:

```lua
SFSNetwork.SendMessage('idle.game.event.help',
    { targetUid = '<owner uid>', eventId = <event id>, eventUuid = <event uuid> })
```

## 3. What the client holds

`DataCenter.T11IdleGameDataManager`:

| field | meaning |
|---|---|
| `gameEventList` / `gameEventDict` | MY events — `uuid`, `eventId`, `questId`, `num`, `status`, `rewardId` |
| `InvitePlayersDict[eventUuid]` | the players already helping that event — uid, name, alliance abbr, power |
| `idleGameMainData` | the run itself — level, boss, timers |
| `lastShareTimestamp`, `shareCd` | the client-side cooldown on sharing mine |

`InvitePlayersDict` is the «места» reading: it is the list of helpers an event has, and it
is what a «пока есть места» gate has to count.

## 4. What it costs, and the refusals

Helping spends no troops and no march. The limits the game itself states
(`ru.bin` / `en.bin`, keys around `t11_idle_game_desc_49`):

* **«Приз за участие (сегодня получено {0}/{1})»** — a DAILY quota on the participation
  reward. Helping past it is possible; being paid for it is not.
* `t11_idle_game_desc_50` «Вы уже участвуете в этом событии» — one help per event.
* `t11_idle_game_desc_84` «Это событие завершено, проверьте, нужна ли кому-нибудь ещё помощь!»
  — the event filled up; the places are gone.
* `t11_idle_game_desc_85` «Вы не состоите в том же альянсе, что и инициатор этого события.»

## 5. What the panel does with it

| piece | where |
|---|---|
| the ear | `src/lastwar_bot/actions/watch_ally_training_help.md` — wraps the client's own chat parse and parks each plea in `DataCenter.__lw_help_queue` |
| the join | `src/lastwar_bot/actions/help_ally_training.md` — drains that queue, one `idle.game.event.help` per plea, then says what the CLIENT shows rather than that a press was made |
| the standing order | `panel/triggers.py::ally_training_help` — a poll over the parked queue (a local VM read, never a question to the server), **shipped off** because a join spends the day's participation-reward quota |

The poll is also true while nothing is listening: a client restart wipes the VM and the
ear with it, so «nobody is listening» is itself work and the errand's first step is to arm
— the same shape `treasure_auto` uses for the treasure share next door.

## 6. The live pass (2026-09-11)

Everything below was read off a running client through the panel's own door — the ear, the
client's chat backlog and the training's data manager. No window was opened and nothing
was joined to learn it.

### 6.1 The card carries nothing in its BODY

A post-730 message is one sentence (`t11_idle_game_desc_51`) and a sender; the chat
reader's own dump (`chat_log.jsonl`) records **47 of them over ten days**, all in the
alliance room, all with `msg`, `sender_uid`, `seq_id`, `server_time` — and no attachment
field at all, because that dump drops `extra`. So the event the card stands for is in
`extra` or nowhere.

### 6.2 `msg.extra` holds STRINGS; `msg:getExtra()` hands back a decoded object

Measured on live cards of other kinds in the same room: `msg:getExtra()` returns a table
whose interesting value prints as `json.object: 0000000397F95B60` — a pointer. An ear that
concatenates `tostring(v)` over that table and matches regexes against the result can
never find a uuid, which is what the first version of `watch_ally_training_help.md` did.
The way the client's own readers do it (`watch_red_packets.md`, post 611) is
`msg.extra.customJsonParam` — a STRING of JSON — decoded with `rapidjson`. The ear now
reads every `extra` value that looks like JSON, decodes it and walks the result for
`eventUuid` / `eventId`, and keeps the whole extra verbatim in `raw` beside them.

### 6.3 The server's own chat history does NOT replay these cards

`ChatManager2.Instance.Ctrl:ChatRoomRequestHistoryMsg(room, <oldest seqId>)` pages the
alliance room back 100 messages at a time, and the pages do arrive through
`Chat.Model.ChatMessage.onParseServerData` — **1715 messages** were re-parsed this way.
Post types seen in them: `0`, `13`, `601`, `633`, `645`, `687`. **Not one 730.** So a plea
cannot be recovered after the fact: the ear has to be listening when it lands, and a
client restart that wipes the hook loses everything said while it was down.

### 6.4 What the training manager holds, and what it does not

`DataCenter.T11IdleGameDataManager` (live): `gameEventList` / `gameEventDict` — MY three
events (`uuid`, `eventId`, `questId`, `num`, `status`, `rewardId`, `figure`, `getTime`);
`InvitePlayersDict` — **empty** while nobody is helping; `lastShareTimestamp`, `shareCd`;
`newEventList`, `newSpecialEventList`, `eventNodeUpdateList`. **There is no list of
alliancemates' shared events anywhere in it** — the manager knows only about our own, which
is the second half of why the chat card is the only announcement there is.

Its methods (`_class_type`), the ones that matter here:

| method | what it is |
|---|---|
| `ShareToChat` | puts one of MY events in alliance chat — the sender's half of the card |
| `CanShareAllianceHelp` | the gate on that |
| `CheckOpenTaskEventAllianceHelpView` | what the card's own click handler opens |
| `SendIdleGameEventGetMessage` | fetch somebody else's event |
| `SendIdleGameEventHelpMessage` | **the join** |
| `GetInvitePlayerInfoList` / `AddInvitePlayerInfoDict` | the helpers an event already has — the «места» reading |
| `ParsePushGameEvent` | what `push.idle.game.events` lands in |

### 6.5 `idle.game.event.get` takes THREE arguments

Asked live with a stale sharer's uid, in one recipe, each in a `pcall`:

```
SendIdleGameEventGetMessage(uid)        → SFSDataSerializer.lua:43 bad argument #2
SendIdleGameEventGetMessage(uid, 0)     → SFSDataSerializer.lua:39 bad argument #2
SendIdleGameEventGetMessage(uid, 0, 0)  → accepted
```

So the signature is `(uid, eventUuid, clientParam)` and **the uuid is not optional** — the
card is the only place it can come from, which is why the ear's job is to get it out of
`extra` intact. (The raw `SFSNetwork.SendMessage('idle.game.event.get', {…})` form is
refused by the serialiser; the manager's own method is the door.)
