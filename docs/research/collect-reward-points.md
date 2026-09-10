# Special resource-collect points — the push that names them, and the march that takes one

**#2406.** A point of "special resource collection" appears on the world map, the client
raises a notification for it, and a squad sent there gathers it. This is where the point
is announced, what the announcement carries, and what has to leave to claim one.

## The announcement — `push.user.collect.reward.create`

Measured live on an ordinary session (60 s of an idle account, four announcements):

```
push.user.collect.reward.create
    {uuid, pointId, type, contentId, expireTime, reward, rewardStatStr}
```

| field | meaning |
|---|---|
| `uuid` | names the point; the same uuid is the key of the client's own list |
| `pointId` | **the tile** — packed world point id (`x = p % 1000`, `y = p // 1000`) |
| `type` | the point's kind (`6` on every one seen) |
| `contentId` | the reward template row |
| `expireTime` | ms on the GAME's clock, not the PC's |
| `reward` / `rewardStatStr` | what is on the point |

`push.user.collect.reward.remove` retires one. The client parks both in
`DataCenter.CollectRewardDataManager.collectRewardList`, keyed by uuid, with the same
five numbers and nothing more.

**The push is the ONLY place the tile is stated.** That is the finding the task cost
most: the alliance's shared list
(`WorldPointDetailManager.worldAllianceResourceDataList`) holds `uuid`, `remainValue`,
`totalCount`, `totalSpeed`, `expireTime`, `isSelfCollect`, `creatorInfo`,
`allianceAbbr` — and **no coordinate at all**. `GetAllianceResourceData(pointId)`
answers `nil`, `GetDetailByPointId` on a point whose model is standing in the scene
answers `nil`, and asking the server for the detail by uuid brought nothing back. Two
directions were tried and both are dead ends; the push had the place all along.

Related but NOT this: the scene models `A_build_ziyuandian_<n>_<colour>` are the
alliance's own resource-point buildings, and `CollectResourceWood_world(Clone)` /
`CollectResourcesGold_world(Clone)` are ordinary mines. Their tile can be read off the
GameObject (`SceneUtils.WorldToTileIndex`), but only while the camera is over them — a
poll by another name, and unnecessary now.

## The march

An ORDINARY gather order at the announced tile:

```lua
MarchUtil.SendCreateMarchMessage(formationUuid, MarchTargetType.COLLECT, pointId, 0,
                                 1, 1, false, serverId, nil)
```

`MarchTargetType.COLLECT = 2`, the tile's own uuid left at `0` the way a mine's is
(`do_radar_marches.md`, live-proven 2026-08-17). It goes through
`TimerManager:GetInstance():DelayInvoke(…, 0.1)` because a march sent from the hijack
thread is dropped silently ([attack-and-scout.md](attack-and-scout.md)).

**Live, 2026-09-04:** four announcements in 3.5 minutes, two marches sent, both accepted
— `squad=3 state=1 free=0 status=MOVING march=NORMAL point=<the announced tile>`.

Other march kinds were considered and are not this: `ALLIANCE_RESOURCE_COLLECT = 75`
(the alliance's shared point), `LOTTO_RECEIVE_BASE_REWARD = 101`,
`VALENTINE_RECEIVE_BASE_REWARD = 112`.

`MsgDefines.GatherCollectReward = 'gather.collect.reward'` exists and is presumably the
claim after arrival; its field shape could not be read out of memory
(`Net.Msgs.GatherCollectRewardMessage:NewMessage(...)` returns an object with no visible
fields, and `string.dump` is refused by the sandbox since 2026-08). Nothing here sends
it — the ordinary gather completes on its own.

## The ability

`actions/watch_collect_rewards.md` wraps `SFSNetwork.HandleMessage` and marches from
inside the call that delivered the announcement — no clock, no question at the server.
Its gates are all local: no `pointId` → dropped; a uuid already marched at → skipped;
`expireTime` against `GetServerTime()`; and a free squad among the ones it was given
(default 3 and 4 — slot 1 stands with the rally auto-join, slot 2 with the golden hunt),
`state == 0` **and** the formation's own `IsFree()`, else the announcement is skipped
rather than waited on. `actions/read_collect_rewards.md` reads the ring back.

The trigger `collect_reward_watch` is a poll of the hook's OWN FLAG, not of the game: a
client restart takes the VM and the ear with it, and this puts it back.

## The kind decides whether a march is right at all (#2738)

**#2406 measured four announcements and every one was `type = 6`, so the ear marched at
whatever arrived. Live there are at least four kinds and only `6` is an ordinary gather
point.** Read straight off `CollectRewardDataManager.collectRewardList` on a live
account, 2026-09-10:

| `type` | seen | note |
|---|---|---|
| 6 | most of the list | the ordinary point a `COLLECT` march takes — the proven pair |
| 2 / 8 / 12 | one or two each | announcements of another shape; a `COLLECT` march at one of them is unproven |

What that cost, measured on the live client the same day: the ear's own ring read
`heard=14 sent=7`, and among the seven were **a march at the player's OWN base tile**
(the announced `pointId` was exactly `LuaEntry.Player.world_main_pos`) and **three
marches at one tile** — the base the person happened to be attacking by hand, announced
three times under three different uuids, so the uuid dedup let all three through. From
the person's chair that is «я атакую игрока, и после каждой атаки мои отряды уходят
куда-то в пустое место».

So the ear now:

* marches only at the kinds it is given (`kinds`, default `[6]`) and names the kind of
  everything else in its ring instead of guessing a march for it;
* refuses outright a point standing on our own base tile — there is nothing to march to;
* remembers the TILE as well as the uuid, so one tile costs one squad however many times
  it is announced.

Adding a kind is an argument, not an edit: prove the pair, then pass `kinds`.
