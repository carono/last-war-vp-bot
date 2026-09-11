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
