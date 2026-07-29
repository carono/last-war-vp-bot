# Robbing a secret task — «кража секретки»

Task #1099. Sources: `results/traces/20260729_013329_кража_серкетки_trace.log` and
`results/traces/20260729_013404_Кража_секретки_trace.log` (the player opened a
marker in one and robbed it in the other), pinned against the live Lua VM through
the warm daemon. The wire half was already captured on 2026-07-19 —
`docs/research/protocol.md` §7 "Stealing — `hero.dispatch.steal`".

**Both traffic checkpoints of these runs are empty** (`(keepalive)` lines only —
the capture port was stale, the known failure in
`project_env_read_wgb_blocked`). So nothing below rests on the new traffic files;
the command names come from `MsgDefines` in the VM and the field lists from the
message classes' own constants.

## 1. What one robbery is

A finished hero-dispatch task on another player's tile can be robbed three times
before its loot slots are full. One robbery is a single client message:

```
--> hero.dispatch.steal   {uuid, targetServer}
<-- push.hero.dispatch.mission.steal {pointId, serverId, worldId, playerInfo}
<-- hero.dispatch.steal   {reward[], ownerInfo, recordUuid, todayStealNum, ...}
```

`MsgDefines.DispatchSteal` is that command, and
`Net.Msgs.DispatchTask.DispatchStealMessage:OnCreate(uuid, targetServer)` puts
**exactly two fields** in the SFSObject — `PutLong uuid`, `PutInt targetServer`.
There is no coordinate, no formation, no march: the robbery is instant and costs
no troops.

## 2. The press, and the thing that only looks like it

The in-game button is the «украсть» icon on a marker's popup:
`UI.UIWorldPoint.Component.UIWorldPointBtn:onDispatchTaskClick(btnType)` with
`btnType == WorldPointBtnType.DispatchTaskSteal` (**54** — the same 54 the trace
hands to `LoadPath.GetBuildBtnSpritePath`, whose sprite stem is `…_touqu`,
*steal*). That handler's only network line for this branch is the
`SFSNetwork.SendMessage(MsgDefines.DispatchSteal, …)` above, so **the send needs
no window open**.

`DispatchStealMessage:HandleMessage` is the **reply applier** — rewards,
`RewardManager:AddRewardsAndRes`, `ShowReward`, `UpdateTodayNum`, `UpdateSteal`.
Calling it sends nothing and only fakes a robbery on screen. Same trap as
`AllianceHelpDataManager:OnHelpAll` (`docs/research/alliance-help.md`); the rule
holds — read a candidate's constants with `string.dump` before calling it.

## 3. The gates

`onDispatchTaskClick` checks, in its own order: the activity being open, the base
level (`needMainCityLevel`), the tile's `protect_times` (from config table
`lw_dispatch_tasks`), the tile's looter list (`stealList:Contains(selfUid)`),
`GetTodayStealNum()` against `GetDispatchSetting("steal_count")`,
`IsOpenCrossSteal()` and `CrossServerUtil.NeedIntercept`.

Only some of that is answerable for a bare uuid:

| Gate | Readable headless? | How |
|---|---|---|
| daily budget | **yes** | `steal_count` (5 live) − `GetTodayStealNum()` |
| cross-server robbery enabled | **yes** | `ActDispatchTaskDataManager:IsOpenCrossSteal()` (true live) |
| three loot slots | only off a map scan | `stealInfoList` / tile field `f10.f4`, max 3 |
| `protect_times` window | no | hangs off the rendered tile (0 in every config row read) |
| "I already robbed this one" | no | `stealList` lives on the world object, not the detail |
| **the victim must be in reach** | no | server-side, see below |

So the primitives gate on the budget only, and let the server refuse the rest —
which it does cleanly, with a tip and no cost.

**Range is real and it bites.** Robbing a task on server 971 while the client sat
on 534 was refused with tips `458632`: «Операция не удалась! Не в том же секторе,
что и целевая зона боевых действий!» `todayStealNum` did not move, so a refusal
costs nothing but the attempt. (`MsgDefines.GetServerStealRangeList` =
`get.server.steal.range.list` presumably enumerates the reachable servers; it was
not requested here.)

## 4. Naming a target: coordinate → uuid, headless

A steal is keyed by uuid, and a map scan (`world.get.block`, `f2 = 17`) is one way
to get one. The other is the request the client itself fires when a marker is
tapped:

```
SFSNetwork.SendMessage("world.get.detail.new", pointId, serverId, 0, 17, "")
   -> DataCenter.WorldPointDetailManager:GetDetailByPointId(pointId)
      .uuid   the task uuid            .uid    the owner's uid
      .srcServer  the task's server    (plus name, alliance, career…)
```

`pointId` is `SceneUtils.TilePosToIndex(Vector2Int(x, y))`, and the reply lands in
a cache that survives across chunks — so the shape is **request → settle → read**,
never both in one chunk. Verified live: asking for a known alliance task's pointId
returned the same uuid its dispatch record carries, and the three markers visible
on server 534 resolved to three distinct uuids with three distinct owners.

## 5. What is automated

* `tools/lib/lua_actions.py` — `secret_task_steals_left()`,
  `secret_task_request_detail()`, `secret_task_uuid_at()`,
  `secret_task_owner_at()`, `secret_task_steal()`,
  `secret_task_leave_message()`, plus the target queue
  (`secret_task_queue_set/clear/len`, `secret_task_steals_pending`,
  `steal_next_secret_task`).
* `tools/lib/game_buttons.py` — `steal_secret_task` (one press = one robbery from
  the queue, `count_lua` = min(queued, budget)) and `dismiss_steal_reward`.
* `tools/steal_secret_task.py` — names targets (`--uuid`, `--coords`,
  `--from-scan` over a `secret_task_capture.py --json` checkpoint), fills the
  queue, prints `--status`.
* `src/lastwar_bot/actions/steal_secret_task.md` — the recipe: `TAP
  steal_secret_task xall` + close the loot window.

`TAP` takes no arguments, hence the queue: the targets are parked on the dispatch
manager's own table (`__lw_steal_queue` — this VM rejects some new globals) and
the button robs the first one and drops it. The pop happens **before** the send,
so a refused target costs one queue entry instead of wedging `xall` on a doomed
uuid.

## 6. Confirmed live

| Step | Result |
|---|---|
| resolve (400,678)@971, (588,300)/(580,311)/(584,298)@534 | four uuids + owners, no taps |
| rob uuid …4357954463 on **971** | refused, tips 458632, `todayStealNum` unchanged |
| rob uuid …2503547575 on **534** (direct) | **robbed**, 1 → 2, loot window raised |
| `TAP dismiss_steal_reward` | loot window closed |
| queue + `actions/steal_secret_task.md` (uuid …0444144278) | **robbed**, 3 → 2 left, queue emptied |

## 6a. Auto-loot — the panel checkbox

The panel's «Автолут ★ макс. уровня» (Secret tasks frame) robs **starred tasks
only, and only the highest level the scan actually found**. With no star in view
it does nothing at all — deliberately, because the scarce thing is the day's five
robberies, not the targets: an attempt spent on a plain level-5 tile is one a
level-7 star cannot have until the daily reset.

It is a **checkbox, not a press** (task #1109). A raidable star is perishable —
the window closes, or someone else fills the third loot slot — so the gap between
the capture printing the finding and a human noticing the log line was where
targets were lost. While the box is ticked a watcher thread re-reads the
checkpoint every 5 s and fires the robbery the moment the rule has a target;
unticking it stops the watching (a robbery already under way finishes).

Three things keep the standing order from wasting the budget:

* **a uuid is sent once per session.** The checkpoint keeps showing a tile the
  server refused, and one we already robbed until a fresh scan brings its loot
  count back, so every target of a fired run is remembered and never re-sent.
  Switching the profile (a different checkpoint) clears that memory;
* **one run at a time.** A new poll while the child is still robbing is skipped;
* **an exhausted budget pauses the watcher for 30 minutes** instead of firing at
  every new star. The child says so in words (`the day's robberies are spent` /
  `robberies left today: 0`), and the pause is short enough that the daily reset
  is picked up without a human.

It reads the capture's own checkpoint — the monitor runs with
`--json <profile>/secret_tasks.json`, rewritten every tick — and hands it to
`tools/steal_secret_task.py --from-scan … --star-max`, the same entrypoint a
human uses from the shell; the same call (`targets_from_scan`, a pure file read)
is what the watcher polls with, so the panel holds no second copy of the rule.
`load_fresh_tasks` drops any tile not re-seen in the last 15 minutes and
recomputes `can_loot` against the current clock, so a stale file cannot aim a
robbery at a tile that is already gone — which is also why the watcher is
harmless when «Мониторинг» is off: nothing refreshes the checkpoint, so nothing
stays fresh enough to be a target (the panel says as much when the box is ticked
with the monitor stopped).

**The «уровень от / до» entries bound it.** They sit in the same row as the
checkbox and read as one control, so they are a hard gate on what may be robbed,
not a display preference: the range is applied *before* `--star-max` looks for
its top level, and both the watcher's poll and the child process get it
(`--level-min` / `--level-max`) — the child re-reads the checkpoint, so a range
that reached only the panel would let it rob outside the range anyway. Set «от 7»
and a level-6 star is not a target at all, however alone it is on the map.

This was learned the hard way: on 2026-07-29 14:15 the range said 6..7, the day's
last two robberies were being saved for 7s, and auto-loot spent one on the only
raidable star — a level 6 — because the range never reached the rule. Note that
6 *is* inside 6..7; what the range now guarantees is that «от 7» means it.

Two things it does NOT do, both on purpose:

* it ignores the **display** checkboxes (stars / pending / lootable) — those
  decide what is *printed*, and a display filter quietly changing who gets raided
  would be a nasty surprise. The level range is the deliberate exception above;
* it does not queue a star whose dispatch is still running. A starred tile that
  is not raidable *right now* is simply not a target on this poll — the watcher
  will pick it up on a later one, once the scan shows it free. Observed live
  (when this was still a press): three level-7 stars in view, all «ещё
  выполняется» (12–90 minutes out), 19 ordinary tiles raidable — it correctly
  robbed nothing. Ten minutes later the nearest star came free and the same
  command robbed it (level 7, `#509 X:504 Y:314`, budget 2 → 1), leaving the
  other two — still running — alone. Both halves of the *rule* are therefore
  confirmed against the live game; the automatic trigger on top of it has not
  yet run a live session.

A successful run closes the loot window it raised, so the client is left as it
was found.

`starred` is the decoder's reading of `cfgId` (family 6000 minus the `99` class),
not something the game states on the wire — see §7 of `protocol.md`. That is the
one soft spot in this rule.

## 7. Open

* **Finding targets is still the weak half.** The queue has to be filled from a
  packet scan (`tools/secret_task_capture.py`, which needs a live capture and a
  moving map) or from coordinates somebody already has. The client *does* render a
  marker per visible task — `dispatchTaskRewardUI(Clone)`, whose
  `TouchObjectEventTrigger` is what a tap hits — but their transforms carry
  world-space tile coordinates with a per-zone offset (a tile at y = 298 sits at
  z/2 = 2298), and that offset was not resolved into a primitive here.
* **`hero.dispatch.leave.message` is unproven.** The emoji a victim gets is
  `MsgDefines.DispatchLeaveMessage {recordUuid, msgId, targetServer}` from
  `UIDispatchTaskRewardView:OnStealMessageBtnClick`; `recordUuid` comes from the
  robbery's own reply, which is not read back yet. `GetStealEmojiList()` returns
  11 entries. Pure flavour — it pays nothing.
* **The prospective reward is still not quoted anywhere** before the robbery (the
  open question from `protocol.md` §7); the loot only appears in the reply.
