# «Судный день» — the event, its window and its gifts (#2842)

**The ask:** «Нужна новая карточка, событие судный день, раз в 2 недели, по воскресеньям,
нужно регулярно собирать подарки в событии».

Everything below was read off a live client on 2026-09-13, while the event was running.

---

## 1. What the client calls it

| thing | name |
|---|---|
| manager | `DataCenter.LWDoomsdayManager` |
| window | `UIWindowNames.UIDoomsdayDetails` (three pages: achievements, rewards, ranking) |
| activity row | the event's id in `ActivityListDataManager.activityList`, `type=157` |
| name key | `doomsday_activity_name1001` (the client's own text key) |

The manager is tiny — it holds four things and nothing else:

```
activityId (string) · activityEndTime (ms) · redDotCount (number) · IsOpen()
```

Its methods are all receivers: `OnGetMainInfo`, `OnGetQuestInfo`, `OnRecieveQuests`,
`OnSingleQuestUpdate`, `OnGetRankInfo`, `OnGetRankRewards`, `GetRedDotCount`, `IsOpen`.

## 2. The messages

```
activity.doomsday.main.info            MsgDefines.ActivityDoomsdayMainInfo
activity.doomsday.quest.info           MsgDefines.ActivityDoomsdayQuestInfo
activity.doomsday.quest.reward         MsgDefines.ActivityDoomsdayQuestReward
activity.doomsday.quest.rank.info      MsgDefines.ActivityDoomsdayQuestRankInfo
activity.doomsday.quest.rank.show.info MsgDefines.ActivityDoomsdayQuestRankShowInfo
push.doomsday.quest                    MsgDefines.PushDoomsdayQuest
```

`main.info` answers with the day's bosses (`boss_info.server_boss[]`, each with a
`monster_uid`, a `monster_id`, a `point_id` and an `expire_time`) — the fight half of the
event, which this task does not touch.

## 3. The window, and where the gifts are

One question — `activity.doomsday.quest.info` with the activity id — is answered with the
whole achievement list, and the reply is handed to `OnGetQuestInfo`:

```
quest_info = {
    has_rewards     = "2001,2002,…,1019",     -- the ids already paid out, as one string
    doomsday_quests = { { uuid = "<19 digits>", quest_id = 101, state = 1,
                          count = 100, rewards = { {type = 7, value = {…}}, … } }, … },
}
```

**`state` is the whole of it, and the window agrees.** With the details window open, the
view's own `achieveVOs` were compared against the payload, uuid by uuid:

| payload | the window's VO | how many |
|---|---|---|
| `state = 1` | `hasRecieved = true`, `canRecieve = false` | 38 |
| `state = 0` | `hasRecieved = false`, `canRecieve = false` | 3 |

So **`state = 1` is «already paid out»** and anything else is an achievement the event
still owes. `count` is progress and it MOVES between two readings (one quest went 120 →
130 in an hour). The config table `doomsday_quest` holds `id`, `desc` and `reward` per
achievement and no target at all, so the client cannot tell «earned» from «not earned» on
its own — `canRecieve` is the server's word, delivered in the same payload.

## 4. Claiming one

The message class `Net.Msgs.Activity.Doomsday.ActivityDoomsdayQuestRewardMessage` has an
`OnCreate` of ONE argument, and what it puts on the wire is one field:

```lua
SFSNetwork.SendMessage(MsgDefines.ActivityDoomsdayQuestReward, tostring(quest.uuid))
-- wire: { uuid = <string> }     (SFS type 8 — UTF_STRING)
```

Read off the class rather than guessed: `OnCreate` was called with a marker value and the
resulting `sfsObj` dumped (`{dataHolder = {uuid = {Type = 8, Data = …}}}`), with a string,
a number and a table all landing in the same single field.

**A claim for an achievement that is not earned is refused by paying nothing.** Measured
live: the reply to `activity.doomsday.quest.reward` came back with `rewards = {}` and an
unchanged `quest_info`, no error and no toast. That is what makes the collector safe — it
asks for everything the event has not paid out, and the server hands over exactly what is
owed.

Pressing the window's own «take all» (`pageAchieve:RecieveAll()`) with a hook on
`SFSNetwork.SendMessage` sent NOTHING while nothing was claimable, which is the same
verdict from the other side.

## 5. The schedule, and what is NOT known

The activity row names the window the event is running in, in server milliseconds:

```
startTime = Sunday 00:00 (of the warzone's day)   endTime = the same day 23:59:59
limitTime = 1   type = 157   timeType = 200   para1 = 7   para2 = 99   para3 = 13
```

The run measured was a **Sunday, one game day long**, which matches the ask. **The
FORTNIGHTLY period is NOT in the client's data**: the activity row describes the instance
that is running and no table on the client lists the next one, and `getTable('activity')`
holds no future doomsday row. `para1 = 7` sits where a weekday would (Sunday = 7), and
that is as far as the data goes — it is written down here as an observation, not as a
confirmed period.

So the panel never predicts a date: the card says what the game says — the window it is in
now — and «when is the next one» stays «—» until the game announces one. The errand is
hourly rather than fortnightly for the same reason (`panel/timers.py`).

## 6. What the panel does with it

| piece | what it is |
|---|---|
| `actions/read_doomsday.md` | one reading: is it on, the window, `quests` / `taken` / `pending`. Asks the server only while the event is ON |
| `actions/collect_doomsday_gifts.md` | asks for every achievement not paid out, then re-reads and reports what MOVED |
| `panel/runtime/doomsday_live.py` | the ear: one reading on `GAME_READY`, one per `push.doomsday.quest`, debounced, no clock |
| «События» → «Судный день» | the card on the phone: state, time left, the window's end, gifts taken / owed, the AGE of the reading, and «Собрать» |
| `panel/timers.py` → `collect_doomsday_gifts` | the hourly safety net; a run outside the event costs one local VM round trip and no wire traffic |
| `panel/triggers.py` → `doomsday_gifts` | the same recipe on the event's own push, which is what makes the collection regular |

## 7. What was NOT done

* the FIGHT — the day's bosses out of `main.info` — is a separate ability and is not
  touched here;
* the ranking pages (`quest.rank.info`, `quest.rank.show.info`) are not read;
* `push.doomsday.quest` was not observed firing during the hours this was written in, so
  the trigger is not proven live yet; the hourly errand covers that case by design.
