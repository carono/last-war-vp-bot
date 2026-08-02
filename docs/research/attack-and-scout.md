# Attacking an enemy base & sending a scout plane

How to programmatically **attack an enemy player base** and **send a scout
("разведывательный самолёт")**, plus where the scout report ends up. Derived from
a live `lua_trace` session (task #1070: user performed *select base → attack →
send first squad → wait → send scout → wait*) cross-checked against the live
`MarchTargetType` enum dumped straight from the game.

This is the same launch primitive proven for solo monster attacks
([`world-monsters.md`](world-monsters.md) Finding 17) and resource collection
([`world-tiles.md`](world-tiles.md)) — only the `MarchTargetType` changes.

---

## TL;DR

| Action | `MarchTargetType` | Launch call |
|---|---|---|
| Attack enemy base/city | `ATTACK_CITY = 11` | `MarchUtil.SendCreateMarchMessage(formationUuid, 11, pid, targetUuid, 1, 1, false, serverId, nil)` |
| Scout enemy base/city | `SCOUT_CITY = 17` | `MarchUtil.SendCreateMarchMessage(formationUuid, 17, pid, targetUuid, 1, 1, false, serverId, nil)` |

Both must be scheduled on the **game main thread** via
`TimerManager:GetInstance():DelayInvoke(fn, 0.5)` — a cold send from the
SafeDoString hijack thread returns `ok=true` but the server drops it (same rule
as the monster attack). Tool: [`tools/attack.py`](../../tools/attack.py).

The scout **report** arrives asynchronously as a **battle-report mail**
(`fightType 8`); a `WORLD_SCOUT_RED_DOT` PlayerPrefs flag marks it unread.

---

## 1. The live trace (what the UI actually did)

`lua_trace --dedup` overview, in chronological order (line = Player.log):

```
35741  SeasonUtil.OnClickWorldTile   <- 252825, 0, nil, <table>      -- tap the enemy tile (pId)
35742  UIManager.OpenWindow          <- UIWorldBlackTile, ..., 252825 -- select highlight
...    WorldPointDetailData.New / __init / ParseData                   -- parse world.get.detail.new (the base detail popup: power, troops, shield)
41402  MarchUtil.OnClickStartMarch   <- 11, 249828, 1153754361273489578, -1, 1, nil, 935
                                       -- tap «Attack»: targetType=ATTACK_CITY(11), pid, targetUuid, -1, 1, nil, serverId
41502  GoToUtil.GotoWorldPos         <- ..., -1, 0.2, <fn>, 935, 0    -- camera flies to target
47127  MarchUtil.OnAttackOtherCity   <- 1397117525879400249, BuildPointInfo, 52
                                       -- march resolves onto the enemy city (ownMarchUuid, buildPoint, ...)
50392  MarchUtil.LaunchScout         <- 17, 249828, 1153754361273489578
                                       -- «Scout»: targetType=SCOUT_CITY(17), pid, targetUuid
50442  MarchUtil.IsScoutMarch        <- 17                            -- confirms 17 is a scout type
51576  MarchUtil.OnLaunchMarchSuccess<- 17, 1153754361273489578, 249828 -- scout launched OK
51577  UIUtil.ShowTipsId             <- scouting_departure_tips        -- «scout departed» toast
...    CommonUtil.PlayerPrefsSetTable <- WORLD_SCOUT_RED_DOT, ...       -- (later) new scout report red-dot
...    IsMailNewFightType            <- 8                              -- scout report = fight mail type 8
...    GoToUtil.GotoOpenView         <- UILWMailMain                   -- open mail to read the report
```

The trace was a `--dedup` pass (first call of each name only), so the raw
`SFSNetwork.SendMessage` wire command for the marches was not re-logged — but the
send path is already fully established: `SendCreateMarchMessage →
SendCreateMarchToServer → SFSNetwork:SendMessage` (see `world-monsters.md`
Finding 16). Passive pcap of an earlier attack (`results/attack_capture/`)
confirms the server-side echo: outbound marches surface as
`push.world.march.new`, and completion/recall as `push.world.march.del`.

### Parameter meaning

For both the attack and the scout the two identifiers are the same pair:

- **`pid` / `targetPoint`** — the world **tile index** of the enemy base
  (`249828` above). Readable no-click from a tile clone via
  `SceneUtils.WorldToTileIndex(clone.transform.position)`.
- **`targetUuid`** — the enemy base's server **uuid** (`1153754361273489578`).
  The base does not expose its uuid client-side until the server sends it; a
  single tile select (`OnClickWorldTile` → `world.get.detail.new`) fetches it
  (mirrors the monster MODE‑1 `OnClick` uuid fetch).
- **`serverId`** — target server (`935`; may differ for cross-server targets).

> The `252825` in `OnClickWorldTile` vs `249828` in the march is the dedup pass
> catching a *different* earlier tile select; within one attack the select pid
> and the march `targetPoint` are the same tile.

---

## 2. `MarchTargetType` — the authoritative map

Dumped live from the running game (`_G.MarchTargetType`, ~200 entries). The ones
relevant to attacking/scouting another player:

| Value | Name | Meaning |
|---|---|---|
| **11** | `ATTACK_CITY` | **attack an enemy player base** |
| **17** | `SCOUT_CITY` | **scout an enemy player base** (the "plane") |
| 25 | `ATTACK_ALLIANCE_CITY` | attack an alliance city |
| 28 | `SCOUT_ALLIANCE_CITY` | scout an alliance city |
| 1 | `ATTACK_MONSTER` | attack a world monster (see `world-monsters.md`) |
| 2 | `COLLECT` | gather a resource tile (see `world-tiles.md`) |
| 6 | `JOIN_RALLY` | join an alliance rally (see `rally-join.md`) |
| 4 / 18 | `ATTACK_BUILDING` / `SCOUT_BUILDING` | attack / scout a world building |
| 5 / 22 | `ATTACK_ARMY` / `SCOUT_TROOP` | attack / scout a marching army |
| 143 / 148 | `CROSS_ATTACK_CITY` / `CROSS_SCOUT_CITY` | cross-server variants |

(Full enum is large; only the wire-verified pair `11`/`17` is used by the tool.)

---

## 3. Launch primitive (same as monster attack, retargeted)

```lua
TimerManager:GetInstance():DelayInvoke(function()
  MarchUtil.SendCreateMarchMessage(
    formationUuid,            -- which squad (formation uuid)
    MarchTargetType.ATTACK_CITY,   -- 11 attack   /   17 SCOUT_CITY to scout
    pid,                     -- enemy tile index (targetPoint)
    targetUuid,              -- enemy base uuid
    1,                       -- timeIndex   (marching speed slot)
    1,                       -- autoBackHome
    false,                   -- needSoldier
    serverId,                -- target server
    nil)                     -- destroyTimeIndex
end, 0.5)
```

Rules (all inherited from the confirmed monster-attack path):

1. **Send on the main thread** via `DelayInvoke(fn, 0.5)`. A direct cold send
   returns `ok=true` but is silently dropped by the server.
2. **Never** `UIManager:DestroyAllWindow()` — it kills the persistent HUD. If you
   ever open the detail popup to fetch the uuid, close it with `Ctrl:CloseSelf()`.
3. The `targetUuid` must resolve to a base that still exists on the server (same
   base, not moved/shielded), exactly like a monster uuid.

### The game's own entry points (equivalent, UI-driven)

- Attack: `MarchUtil.OnClickStartMarch(11, pid, uuid, -1, 1, nil, serverId)` —
  opens the formation-dispatch panel, then the player confirms. Good when you
  want the game to pick soldiers / show the panel; not needed for a headless send.
- Scout: `MarchUtil.LaunchScout(17, pid, uuid)` (5 formal params, last two
  optional) — builds a scout formation and launches directly, then fires
  `OnLaunchMarchSuccess` + the `scouting_departure_tips` toast. A scout uses a
  minimal auto-formation, so `LaunchScout` is the closest 1:1 to the button;
  `SendCreateMarchMessage(..., 17, ...)` is the lower-level equivalent the tool uses.

---

## 4. Getting the scout report (enemy intel)

There are **two** sources of enemy information:

### 4a. Pre-attack recon — the base detail popup (instant)

Selecting the tile issues `world.get.detail.new`; the reply is parsed by
`WorldPointDetailData.ParseData` into the popup you see (owner name, **power**,
troop preview, **shield** state, alliance). This is the quick "should I attack?"
read and is available the moment you select the base — no scout march required.
`WorldBuildUtil.HasShield(...)` reports the shield.

### 4b. Full scout report — a battle-report mail (after the plane lands)

When the scout march completes, the server pushes a **battle-report mail** of
`fightType = 8` (`IsMailNewFightType(8)` / `MailShowHelper.IsSeasonBattleMail`),
handled by `DataCenter.MailDataManager:CheckPushMailBattleReport` /
`HandlePushMailBattleReportMessage`. Client side:

- `CommonUtil.PlayerPrefsSetTable('WORLD_SCOUT_RED_DOT', ...)` — the unread
  red-dot flag (set when a new scout report arrives).
- `GoToUtil.GotoOpenView('UILWMailMain')` — opens the mailbox to the report,
  which contains the enemy's detailed troop composition / defense / resources.

`MailDataManager` exposes `GetMailInfosByTypeInDB`, `ReqMailByType(s)`,
`GetGroupMailList`, `GetMailInfoById`, `ReadMail` — the report body is a DB row
fetched asynchronously (callback-based), so a fully headless *parse* of the enemy
composition from the mail body is **not yet mapped**. What is confirmed and used
by the tool: the `WORLD_SCOUT_RED_DOT` unread signal and opening the report UI.

---

## 5. Tooling

[`tools/attack.py`](../../tools/attack.py) — daemon-backed (`lua_client`), MODE‑2
style (identifiers known):

```bash
# attack an enemy base
C:\Python312\python.exe tools\attack.py attack <pid> <uuid> [serverId] [formationUuid]
# send a scout plane at the same base
C:\Python312\python.exe tools\attack.py scout  <pid> <uuid> [serverId] [formationUuid]
# check for a new scout report (red dot) and optionally open the mailbox
C:\Python312\python.exe tools\attack.py scout-report [--open]
```

Each launch prints the owner-march count before/after (`IsHaveMarchInWorld`,
`GetOwnerMarches`) so you can confirm the march was actually created. Getting
`pid`/`uuid` for a target: select it in-game once, or enumerate bases via the
world-clone reader (see [`env-read-lua-clones`](../../tools/lib/lua_actions.py)).

## Related

- [`world-monsters.md`](world-monsters.md) — Finding 17, the proven launch primitive.
- [`world-tiles.md`](world-tiles.md) — `COLLECT` marches, `WorldToTileIndex`.
- [`rally-join.md`](rally-join.md) — `SendCreateMarchMessage` for rallies (type 6).
- [`rally-create.md`](rally-create.md) — raising one instead of joining it (type 7, and why the
  send has to go through the game's own squad screen).
