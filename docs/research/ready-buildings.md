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
