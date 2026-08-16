# A warzone's own facts — when it opened, what day it is on, for ANY server

Task #1417. The question was «when was this server launched, what day of the server is
it, and what else does the game say about it — for any server, not only mine». The short
answer: the opening moment is one question on the wire, it can be asked about **any**
warzone **without going there**, and everything else worth having is arithmetic the
client already does for its own screens.

Read it with `src/lastwar_bot/actions/read_server_info.md` (`ARGS server = 0` — the
account's own) or `tools/server_info.py [<server>]`.

## 1. Where the opening moment lives

Two places, and which one answers depends only on whose warzone is being asked about.

| what | where | costs |
|---|---|---|
| the account's OWN warzone | `LuaEntry.Player.openServerTime` | nothing — the client is told at login |
| anybody else's | `LuaEntry.Player.otherServerOpenTimeDict[<serverId>]` | one question on the wire, once per warzone per session |

Both are epoch **milliseconds on the game's clock**, which is not this machine's clock
(`docs/research/game-clock.md`, measured eleven seconds apart, and the machine is the one
that is wrong).

The dictionary is filled by the client's own handler for the reply — read out of the live
VM with `string.dump` (`Msgs/GetOtherServerInfoMessage.lua`), whose constants are exactly:

```
HandleMessage  errorCode  openTime  server
LuaEntry  Player  SetCheckServerOpenTime  UIUtil  ShowTipsId  __targetServerId
```

— it takes `openTime` and `server` off the reply and hands them to
`PlayerInfo:SetCheckServerOpenTime(time, serverId)`, which writes
`otherServerOpenTimeDict[serverId]`. Nothing else in the client keeps it.

### The client's own accessor asks about the server it is LOOKING at

`PlayerInfo:GetCheckServerOpenTime()` is the game's own front door and it takes no
argument that matters: string-dumped, it is «if `IsInSelfServer()` then
`curServerOpenTime`, else `GetCurServerId()`, look in the dictionary, and if it is not
there `SendGetOtherServerInfo(serverId)`». So it answers about the warzone the camera is
in — which is why the recipe does not use it for a foreign warzone. **Live proof:** called
with an explicit `2500` it returned the account's own opening moment, unchanged.

## 2. The wire

```
--> get.other.server.info   {server: <id>}
<-- get.other.server.info   {server: <id>, openTime: <epoch ms>}
```

Nothing else is in the reply — no name, no state, no population, no merge history. Sent
from Lua as `SFSNetwork.SendMessage(MsgDefines.GetOtherServerInfo, <id>)`
(`MsgDefines.GetOtherServerInfo == "get.other.server.info"`).

**Live, 2026-08-16, on a client standing in its own warzone** (values invented, shape
verbatim):

```
get.other.server.info | server=<id-A> openTime=1700000000000 _id=1284
get.other.server.info | server=<id-B> openTime=1720000000000 _id=1285
```

The answer was back well inside a second and it is kept for the session, so asking the
same warzone twice costs nothing the second time.

**An id the server does not serve answers with an error that names no server:**

```
get.other.server.info | errorCode=E000000 errorMsg=server error
```

There is no server id on that reply, so it cannot be attributed to the question that
caused it. A caller therefore learns «no such warzone» only by the dictionary staying
empty until it gives up — which is what the recipe's four one-second retries are.

### What the neighbouring commands are NOT

Measured in the same session, so nobody has to try them again:

* `get.server.state` → `{success: true}`. No state, no fields. Not this.
* `get.one.server.info` (`ServerStatusManager:GetOneServerInfo`) → a `OneServerInfo`
  object whose `UpdateFromMsg`, string-dumped, copies exactly **one** field: `zoneStar`.
  The reply's other fields, opening moment included, are dropped on the floor. Useful for
  the zone star and nothing else.
* `get.player.cross.server.list` → a `list` of the warzones this account may cross into.
  A membership list, not facts about a warzone.
* `season.migrate.server.info` (`ActMigrationManager:ReqServerInfo`) → the migration
  screen's view of a warzone; it exists only while a migration event is running, so it is
  no basis for a reading that must work any day of the week.

## 3. The day of the server

The client counts it itself, and its arithmetic is the one that agrees with what the game
draws on screen. `UITimeManager:GetInstance()` has the whole family:

| call | what it answers |
|---|---|
| `GetOpenServerDay()` / `GetServerOpenDays()` | the day number of the account's OWN warzone |
| `GetServerOpenDaysByTimeStamp(openTime)` | **the day number of ANY warzone**, given its opening moment |
| `GetOpenServerWeek()` | the same count in whole weeks, own warzone only |
| `GetTomorrowZero()` | when this game-day turns over — the daily quotas' midnight |
| `GetServerTime()` | the game's clock, in milliseconds |

`GetServerOpenDaysByTimeStamp` is the one that makes «any server» work: string-dumped it
is `curTime` / `serverStartTime` reduced to their day-zeros (`GetTodayZeroServerTime`) and
subtracted, so it is a count of whole game-days and day 1 is opening day. Handed the
account's own opening moment it returns exactly what `GetOpenServerDay()` does — checked
live, both `692` on the same read.

**The day boundary it reduces to is the CLIENT's.** A warzone whose midnight falls at a
different hour would be counted against this client's boundary, and that is a caveat
rather than a measurement: nothing in this session could show two different boundaries.
`tools/lib/game_day.py` says the same thing about the daily reset — one warzone's boundary
is not another's, and the client's `GetTomorrowZero()` is the only one on offer.

## 4. What else the client knows, and only about its own warzone

`LuaEntry.Player` carries the rest, and every one of them is about the account's own
warzone — there is no equivalent for a foreign one:

| field | what it is |
|---|---|
| `serverId` | the warzone the character is in |
| `serverName` | its display name, of the form `State#<id>` |
| `serverMax` | the highest warzone id the game has opened so far |
| `serverType` | 0 on an ordinary warzone |
| `openServerTime` | when it opened, epoch ms |
| `nextDay` | when the game-day turns over, epoch ms — the same moment `GetTomorrowZero()` gives |
| `regTime` | when this character registered |
| `otherServerOpenTimeDict` | the cache from §1 |
| `GetSourceServerId()` | the warzone the account came from, during a cross-server fight |

A foreign warzone's **name** is not obtainable this way: there is no
`CommonUtil.GetServerName`, and `State#<id>` is composed for the account's own. Anything
richer about somebody else's warzone — its king, its alliances, its population — rides
the boards (`get.king.info`, `rank.get`, `get.al.points`), each of which takes a
`serverId` of its own and is a separate ability.

## 5. What needs a jump, and what does not

| reading | jump? |
|---|---|
| opening moment, day number, of any warzone | **no** — §2 |
| zone star of any warzone | no — `get.one.server.info`, same shape as §2 |
| the account's own name / max / type / day boundary | no — already in the client |
| a foreign warzone's TILES (bases, tasks, mines) | **yes** — `GotoWorldPos` / `GotoServerZone`, `docs/research/map-sweep-zoom.md` |
| a foreign warzone's display name | not available at all (§4) |

So the expensive part of «tell me about that server» is not the facts — it is the map.
A recipe that only wants the opening moment or the day never leaves home.

## 6. The login-screen trap

A client that has not finished logging in answers everything plausibly and wrongly
(`docs/research/game-clock.md`): server `-1`, empty lists, a clock that is really the
process's uptime. Here it has no opening moment at all, so the recipe's own gate is the
honest one — `open_ms == 0` after four tries fails the run instead of reporting day 1 of
1970. A caller that wants the stronger gate has `game_clock.session_ready`.

## 7. How it was found

No sniffer was run for this. The client was interrogated through the panel's web API —
`POST /api/actions/run` playing a throwaway recipe under `actions/dev/`, `GET /api/log`
reading the answer back — in a dozen rounds:

1. `DataCenter` has exactly one server-shaped manager, `ServerStatusManager`, and its
   cache holds `serverId` + `zoneStar` and no more;
2. `MsgDefines` scanned for values carrying `server` — which is where
   `GetOtherServerInfo = get.other.server.info` came from, beside `GetServerState`,
   `FetchCrossServerList`, `AccountGetAllServer`;
3. `string.dump` on `GetOneServerInfo`, `OnHandleOneServerInfo`, `OneServerInfo.
   UpdateFromMsg`, `GetOtherServerInfoMessage.HandleMessage`, `PlayerInfo.
   SetCheckServerOpenTime` / `GetCheckServerOpenTime` and the `UITimeManager` day family
   — the constant lists quoted above are those dumps
   ([[project_lua_string_dump_decompile]]);
4. a temporary wrapper on `SFSNetwork.HandleMessage` to read the replies as they landed,
   removed again in the same session.

The wire capture that started it is a `get.other.server.info` pair sitting in an old
session's `results/traffic/*.jsonl` — the command was already on the disk, unremarked,
before any of this ran.
