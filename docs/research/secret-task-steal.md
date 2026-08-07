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
costs nothing but the attempt. **`MsgDefines.GetServerStealRangeList` does enumerate
the reachable servers, and it has been asked now — §6e**, which also has the reply's
surprising home and the 153 servers it came back with.

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
| `--queue-only` + `actions/steal_secret_task.md`, starred level-7 tile (#1188) | `queued 1 target(s)` → `xall -> 1 press(es)` → **robbed**, 5 → 4 left, queue emptied |
| the same, on a FOREIGN server, chosen by the panel's own rule (#1188 acceptance) | `own server: 935 — its tiles are not targets` → `starred targets: 1 at level 7` → **robbed**, 4 → 3 left; tile on server 1002, `cfg 60000701` = level 7 / `is_special` 1 by the game's config |

## 6a. Auto-loot — the panel checkbox

The panel's «Автолут ★» (Secret tasks frame) robs **starred tasks only, at or
above the one level its «минимальный уровень» field asks for**, best first. With
no star in view it does nothing at all — deliberately, because the scarce thing is
the day's five robberies, not the targets: an attempt spent on a plain level-5
tile is one a level-7 star cannot have until the daily reset.

It is a **checkbox, not a press** (task #1109). A raidable star is perishable —
the window closes, or someone else fills the third loot slot — so the gap between
a finding appearing and a human noticing the log line was where targets were lost.
While the box is ticked a watcher thread looks at the panel's own list every 2 s
and fires the robbery the moment the rule has a target; unticking it stops the
watching (a robbery already under way finishes).

**It chooses out of the panel's own list, not out of the sources (task #1256).**
Everything below about *where a tile comes from* is still true — it is how the
list gets filled — but the watcher itself no longer re-reads any of it. It asks
the «Секретки» tab which of ITS rows the rule wants
(`SecretTasksTab.rob_candidates`: raidable, starred, at or above the minimum, not
at home while «не грабить на своём сервере» is ticked), and hands what comes back
to `tools/steal_secret_task.py --targets uuid:server,…`, which re-derives nothing.
Before that, the panel and the child each re-read the sources through a copy of
the rule, so three answers about one map had to agree and did not have to: a row
the list had dropped as expired could still be a target, and the ready-row poll
carried a fourth copy of the rule and a robbery of its own. The list is the model
the capture, the client's tables and the alliance pushes all fill and the one the
30-second ready-row poll re-verifies against the game, so it is the only sensible
thing to spend five robberies out of.

**The primary source is the live game VM, not a capture (task #1124).** The old
watcher read only the capture checkpoint, and that checkpoint only learns a tile
when the map is *panned over it* (`world.get.block`, `f2=17`) — so the whole chain
was: the map sweep reaches the tile → the capture flushes the checkpoint (15 s
tick) → the panel polls the file (5 s) → a subprocess robs. A shared secret task
could sit raidable for the better part of a minute before the bot moved, and a
human watching the log would jump to it and press first — the exact complaint that
opened #1124. The client, though, already keeps that same tile in
`ActDispatchTaskDataManager.allianceTask` the instant the share push lands (see
`docs/research/…` and `project_secret_task_list`), with no panning and no capture.
So the watcher now reads that table directly through the warm daemon on every poll
(`secret_task_raidable_alliance()` → `steal_secret_task.targets_from_vm`), applies
the very same star-max rule to it, and reacts in about a poll's length — a second
or two — which comfortably beats a human reading the same information.

**The truly event-driven path: rob on the push itself (task #1124, second pass).**
A poll — even a 2 s one off the VM — still reacts *after the fact*. The event that
matters, an ally pressing "share" on a raidable secret task, is broadcast to the
whole alliance as `push.alliance.share.mission.add` on the plain-TCP game leg
(passively decodable — see "Shared secret missions" below and
`project_shared_secret_missions`). So alongside the poll the checkbox now starts
`tools/secret_share_autoloot.py`: a `live_sniffer.LiveDecoder` (same scapy/npcap
transport as `rally_monitor.py`) that decodes that one command as it crosses the
wire and fires `hero.dispatch.steal` through the warm daemon *in the same handler*.
Reaction is one wire frame plus one daemon round-trip — well under a second. The
push carries everything the robbery needs with no resolve step: `missionUuid` is
the dispatch task's uuid and `missionCurrentServerId` is its `targetServer`. It
applies the identical star / level rule (`mission_passes`, the single-mission form
of `_select_targets`), dedupes by `(uuid, server)`, and reads the live budget
before every send. It does **not** need the «Мониторинг» capture running — it is
its own sniffer — and a level typed while it runs restarts it (debounced) so it
never robs to a stale minimum. The poll stays on as the slower safety net for
the cases a push does not cover (enemy tiles the sweep saw, tasks already present
before the listener started); the two are safe together because a redundant attempt
at a tile the other path already took is simply refused, and a refusal spends no
budget.

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

The capture checkpoint is kept as a **second source**, unioned with the VM by
`(uuid, server)` (VM copy first, the fresher of the two). Its one remaining job is
**enemy tiles the sweep panned over**: `allianceTask` holds only your own
alliance's tasks, so a raidable enemy star is knowable only from a capture. When
the monitor is off the union is just the VM, and the feature still works in full
for alliance-shared tasks — the old "the monitor is off, so there are no targets"
warning is gone, replaced by a note that the monitor now only *adds* enemy tiles.
Both sources feed the tab's list, and `load_fresh_tasks` recomputes `can_loot`
against the current clock as they do; the VM reader recomputes it the same way, so
neither can put a tile on the list that is already gone. The tool's own
`--from-vm` / `--from-scan` / `--star-max` / `--level-min` / `--level-max` route
is still there and is what a human uses from the shell — it is simply not what the
panel drives any more (#1256, above).

**«Минимальный уровень» is a FLOOR, and it is one number (task #1256).** One box,
in the same row as the checkbox: the level typed and everything above it, best
first. It replaced a «уровень от / до» pair that read as two bounds and behaved as
one — with `--star-max` the level robbed was exactly `--level-max`, so «от 1 до 7»
took 7s and left a raidable level-6 star alone however long it was the only star
on the map. That was deliberate once (below) and wrong in practice: a 6 nobody
takes is not a saved attempt, it is a robbery nobody made, and the five reset
daily whether they were spent or not. The floor keeps the part that mattered — a
level nobody wants is still never robbed — and drops the part that did not.

The reasoning it came from, kept because it is still why the order matters: **the
five daily attempts are the scarce resource, not the targets.** So the choice is
sorted best-level-first, and "nothing raidable at or above the asked-for level" is
a normal answer rather than a failure — the watcher holds fire and says so.

Learned the hard way, twice on 2026-07-29: at 14:15 the range said 6..7 and
auto-loot robbed the only raidable star, a level 6, because the range never
reached the rule at all. That half is what still matters — the rule the panel
shows and the rule that spends the budget have to be one thing — and it is now
structural rather than remembered: the panel chooses, and the child is told the
answer instead of the question.

With **an empty box** there is no floor at all: every raidable star on the list is
a target, best first.

Two things it does NOT do, both on purpose:

* it ignores the **display** checkboxes (stars / pending / lootable) — those
  decide what is *printed*, and a display filter quietly changing who gets raided
  would be a nasty surprise. «Минимальный уровень» is the deliberate exception
  above, and it hides nothing;
* it does not queue a star whose dispatch is still running. A starred tile that
  is not raidable *right now* is simply not a target on this poll — the watcher
  will pick it up on a later one, once the scan shows it free. Observed live
  (when this was still a press): three level-7 stars in view, all «ещё
  выполняется» (12–90 minutes out), 19 ordinary tiles raidable — it correctly
  robbed nothing. Ten minutes later the nearest star came free and the same
  command robbed it (level 7, `#200 X:504 Y:314`, budget 2 → 1), leaving the
  other two — still running — alone. Both halves of the *rule* are therefore
  confirmed against the live game; the automatic trigger on top of it has not
  yet run a live session.

A successful run closes the loot window it raised, so the client is left as it
was found.

`starred` is the decoder's reading of `cfgId` (family 6000 minus the `99` class),
not something the game states on the wire — see §7 of `protocol.md`. That is the
one soft spot in this rule.

**And the soft spot is still open on the TOOL's own route (measured 2026-08-06).**
#1244 replaced the cfgId arithmetic with the game's own config row — `level` and
`is_special` out of `lw_dispatch_tasks` — but only where the PANEL reads. Both
readings taken from the same live client, one round trip apart:

| source | what it reads a `cfgId=60009903` tile as |
|---|---|
| `dispatch_tasks.alliance_roster` (what the tab lists) | **level 7**, `starred=False` |
| `steal_secret_task._vm_raidable_tasks` (what `--from-vm` selects on) | **level 99** |

Four of the fifty-two raidable rows on the account disagreed that way. The cause is
the read, not the parser: `secret_task_raidable_alliance()` emits `ACT VT …` lines
carrying `cfg` and no config columns, so `_parse_vt_lines` has nothing to go on but
`split_cfg_id` — the arithmetic #1244 exists to stop trusting.

**It does not reach the panel**, and that is worth being precise about rather than
relieved by: since #1256 the panel chooses out of its own list and names the targets
(`--targets uuid:server,…`), and `parse_targets` re-derives nothing — so the level a
threshold is judged against is the config's. What is still wrong is the route a
PERSON uses from a shell: `--from-vm --star-max --level-min 7` sorts a mislabelled
tile to the top, and with no `--level-max` the star rule takes `top = max(level) =
99` and robs only those, leaving the real level-7 stars alone. A rule that silently
prefers the tiles it has misread is the #1099 failure exactly — it does not raise,
it spends a raid in the wrong place.

The fix is the same one #1244 made on the other side: teach
`secret_task_raidable_alliance()` / `secret_task_all_alliance()` to emit `lvl` and
`spec` off `v.cfg` the way `dispatch_tasks` already does, and read them in
`_parse_vt_lines` with the cfgId kept only as the fallback for a template the client
has not loaded. Filed separately; not folded into #1188, whose panel path is
unaffected.

### 6a.1 Fixed, and what the damage actually was

Done exactly as prescribed above (#1267): both reads emit `lvl` / `spec` off
`v.cfg:getValue(...)`, and the precedence now lives in ONE function —
`lastwar_proto.task_rank(cfg_id, cfg_level, cfg_special)` — which both readers call.
The two used to spell the same rule out separately, which is the whole reason one of
them could be corrected and the other not. `SecretTask` carries `starred_cfg`
alongside it: `None` means «no client was asked», deliberately not `False`, so a pcap
record cannot look like a tile the game denied the star to.

**The mechanism above is wrong in one place, and the correction matters because it
changes which command hurts.** `--star-max` does NOT promote the mislabelled tile:
`starred` excludes the `99` class, so a tile reading level 99 is not in the starred
set at all and never becomes `top = max(level)`. Driven over the four live shapes,
the pre-fix behaviour was:

| command | what actually happened |
|---|---|
| `--from-vm` (any limit) | targets sort by `-level`, so the mislabelled 99 goes **first** and takes the raid a real level-7 star was meant to get |
| `--from-vm --level-max 7` | the tile the panel calls level 7 is **dropped** — 99 > 7 |
| `--from-vm --level-min 8` | it is **picked up** as if it were the best thing on the map |
| `--from-vm --star-max` | unaffected: not starred by either reading |

So the harm is the sort and the two level gates, not the star rule — and it is the
same #1099 failure either way: no error, a raid spent in the wrong place.

**Three more places computed a rank from the digits; two of them mattered.**

* `panel/.../tab.py::_load_persisted` re-derived the star from the cfgId on the way
  back in, while the checkpoint did not store one. A tile both feeds had accepted was
  therefore dropped on restart — the restore quietly shortening the list #1242 exists
  to keep. The star is checkpointed now and believed; the digits answer only for a
  file written before it was.
* `tools/dev/ghost_recon_tile_dump.py::_decode_cfg` split a GHOST cfgId by hand and
  printed `MM` as the level, where the ghost mapping is `MM + 2` (#1137) — the one
  ghost reading that disagreed with every other. It calls `proto.ghost_recon_level`.
* `panel/.../capture.py::_starred` is the digits BY NECESSITY and stays: a capture
  decodes a pcap in a child process with no client in it to ask. It goes through
  `proto.starred_by_digits` now so the fallback rule also has one home, and the
  consequence is written down rather than left to be rediscovered — **a tile whose
  digits lie is filtered out of the findings log even though the tab's own list keeps
  it.** The same holds for `ShareMission.starred`: a share push carries no config row,
  so `secret_share_autoloot --star-max` is robbing on the digits' word.

`tests/test_secret_task_rank.py` drives one table of records through BOTH readers and
fails if they part company on the level or the star — checked against the commit
before the fix, where it reports `cfg 60009903: tool (99, False) vs panel (7, False)`.
It also fails on any file under `panel/` or `tools/` that reaches for
`proto.STAR_TASK_FAMILIES` again.

**Confirmed against the live client, both readers over one list:** 62 rows compared,
62 agree, 0 disagree — and 9 of those 62 (every one of them a `60009903`) are rows the
digits-only reader would still be calling level 99. The share of the list that was
being mis-sorted is not small: an eighth of it, all of it to the head of the queue.

**The five reset at the server midnight, and the client will say when that is.**
`UITimeManager:GetInstance():GetTomorrowZero()` is the next one — live on 2026-08-06 it
read `2026-08-07 02:00:00 UTC`, so the server day runs **02:00 UTC → 02:00 UTC**.
`GetLocalUTCOffset()` gives this machine's offset (5 hours there, so 07:00 by the
panel's clock). Corroborated by `protocol.md` §7: 597 of 636 tile expiries share the
timestamp `01:59:59 UTC`, one second before the same boundary. Ask those two rather
than counting from the PC — it was 17.9 s slow when this was measured.

Note the difference from the OTHER robbery: this budget genuinely comes back every
midnight, so «wait for the reset» is a real plan here. It is not for ghost recon, whose
event day ends at the very instant its budget resets
(`ghost-recon-steal.md` §4.1).

The gate is judged on the GAME's clock, which is not this computer's — the two were
eleven seconds apart when measured, with the PC the slow one (`game-clock.md`,
task #1227). Against `time.time()` the same `completionTime` reads as "not yet" for
that long after the server would already pay out, and the countdown on the tab
disagrees with the one the game draws beside it.

## 6b. «Уже поделились» — the mark on a tile that has been forwarded (task #1245)

Forwarding a raid to the alliance is worth doing once. The second post reaches the
same people and tells them nothing, so both tables on the tab mark the tiles that
have already been shared — a badge on the coordinate cell and
`secrettasks.shared_mark` beside the countdown, mirrored on the phone.

The mark is a FACT ABOUT THE TILE, not a memory of the panel's own button, so it has
two producers and they write the same file:

| producer | when | what it writes |
|---|---|---|
| the tab (`_share_done`) | the panel's «Поделиться» succeeded | `via = "panel"` |
| `tools/secret_task_capture.py` («Мониторинг») | `push.alliance.share.mission.add` **and** the `get.alliance.share.mission.list` backlog | `via = "game"`, `uid = shareUid` |
| `tools/secret_share_autoloot.py` (the auto-loot listener) | every `…mission.add` it decodes, **before** the level rule | `via = "game"`, `uid = shareUid` |

That is what covers the half the panel cannot see by itself: a share pressed in the
game — by this player or by an alliancemate — never touches the panel, and the only
place it is observable is the broadcast the server sends the alliance. Both captures
already decode that stream for other reasons, so the mark costs no extra read and no
extra child; the price is that the game-side half is only recorded while one of those
two standing orders is running.

The login snapshot is included **for marking only**. `secret_share_autoloot` refuses
to ROB from `get.alliance.share.mission.list` on purpose (a backlog replayed on every
reconnect would re-rob yesterday), but «this has already been shared» is exactly what
a backlog is good for — it is the only source for shares made while nothing here was
listening.

Storage is `profiles/<name>/secret_shared.jsonl`, append-only because three
processes write it (`tools/lib/share_marks.py`): one JSON line per share, newest line
per uuid wins, marks age out after 48 h, and the reader compacts the file once it has
grown past its contents. The tab re-reads it on the per-second countdown pass, but
only when the mtime moved — so an idle tab pays one `os.stat` a second, and a share
pressed in the game shows up within a second of the capture writing it.

Stamped on the machine's own clock, unlike everything else on this tab: the timestamp
is ours rather than the game's, and it is only ever used to age a mark out long after
the tile itself is gone.

## 6c. Reading `level` / `is_special` with no task record in hand

`task_rank` wants the game's own `lw_dispatch_tasks` row, and every reader in this
repo gets there through `v.cfg` — the row already hanging off a live record in
`allianceTask` / `singleTask`. When neither table holds the tile (a pcap target, or a
client that has only just restarted, §6d) there was no way to ask the game at all, so
the digits were the only answer left. There is one, and it is two globals:

```lua
local row = LocalController.instance():getLine(TableName.LwDispatchTask, cfgId)
local level      = tonumber(row:getValue("level"))
local is_special = tonumber(row:getValue("is_special"))
```

`LocalController.instance` is a FUNCTION, not a field — `LocalController.instance:getLine(…)`
raises «attempt to index a function value». The path was read out of the bytecode of
`ActDispatchTaskDataManager:UpdateOneAllianceTask` (`string.dump`, then its string
constants in order), which is the method that attaches `cfg` to a task in the first
place. It is `lua_actions.dispatch_task_cfg_rank` now, and a template the client has no
row for answers `lvl=0 spec=0` — which `proto.task_rank` already reads as «the config
said nothing», so an unknown id degrades to the digits rather than to «not starred».

**That closes the hole this file used to describe as unclosable.** Up to #1188 the
capture's star was final for every tile that reached the list off the wire, because «a
pcap has no client in it to ask» — true of the capture CHILD, and not true of the two
places that CHOOSE a raid, both of which have a live client. `steal_secret_task.apply_cfg_rank`
re-asks every distinct template on a checkpoint in one round trip, and both callers use
it: `targets_from_scan` before it selects, and the panel's `_fetch_scan` before the
findings reach the list (off the Tk thread, so the window pays nothing). Live, on a
list of three: `60009903` came back level 7 / not special, where the checkpoint had it
at level 99 and starred.

Read live while accepting #1188, and it settles the #1267 example from the other side:

| cfgId | the game's config row | the digits |
|---|---|---|
| `60000701` | level 7, `is_special` 1 | level 7, starred |
| `60000501` | level 5, `is_special` 1 | level 5, starred |
| `60000301` | level 3, `is_special` 1 | level 3, starred |
| `300704` | level 7, `is_special` 0 | level 7, not starred |
| **`60009903`** | **level 7**, `is_special` **0** | **level 99**, starred family |

## 6d. `allianceTask` is EMPTY for a while after every client restart

It is not a list the client fetches — it is one that ACCUMULATES from
`push.alliance.share.mission.*` as allies press «поделиться» (§6a). A restart throws
it away, and calling `GetAllAllianceTasksFromServer()` moves `lastGetAllianceTasksTime`
and populates nothing: measured live, the table stayed at 0 rows for 40+ s after a
restart that had reached the city scene with six ESTABLISHED game sockets, and
`singleTask` stayed at 0 with it.

So **`--from-vm` is blind for a while after a restart, and its silence looks exactly
like «nothing raidable on the map»** — the same shape as the stranded client in
server-link-status.md §5.3. The deterministic route to a target is the one the
checkpoint half of the tab uses: run `tools/secret_task_capture.py --json …` and play
`actions/scan_map.md` over it. One lap at zoom 600 took ~8 s and brought back 755
tasks, 8 of them raidable — which is also the cheapest POSITIVE proof that the link
round-trips at all, since those tiles come off the wire rather than out of the
client's memory.

## 6e. Which servers are robbable at all — `get.server.steal.range.list` ANSWERED

§3 left this as «presumably enumerates the reachable servers; it was not requested
here». It was requested (#1188). `SFSNetwork.SendMessage(MsgDefines.GetServerStealRangeList)`
takes no arguments and the reply lands in **`DataCenter.ActGhostreconManager.dispatchStealRange`**
— note the manager: the GHOST-recon one holds the range for the hero-dispatch steal, which
is not where anybody would look. It is a SET keyed by server id (`{[935] = true, …}`), not
a list, so `#t` is 0 and it has to be walked with `pairs`. Found by dumping
`ActGhostreconManager:OnStealRangeUpdate`, whose constants name `dispatchStealRange` and
broadcast `EventId.DispatchStealRangeUpdate`.

Live it came back with **153 servers**, in runs (`933…1060`, plus `8117…8132` and
`8903…8911`), the account's own among them.

**This corrects §3's other half.** The tips-`458632` refusal recorded there is real, but
it is not what a modern out-of-range attempt looks like from here: server `1033` is IN the
range list, and an attempt on a tile there was written up during this task as «refused,
out of sector» when the truth was that the client was kicked and NOTHING was
round-tripping (server-link-status.md §5.3). Read the range before blaming the sector.

## 6f. Starred level-7 tiles abroad are COMMON — and how the opposite got measured

An earlier draft of this section said they were rare, on the strength of four servers
that each showed exactly one starred tile, all level 5. **That was wrong, and the way it
was wrong is the useful part.**

Counted off the panel's own monitor over one day: **2474** foreign starred level-7 tiles
with a free loot slot, against 90 at home. One server alone (`1007`) held 283 stars, 167
of them level 7. So «rob abroad, level 7, starred» has targets most of the time, and a
standing order idling is worth investigating rather than explaining away.

**The bad measurement came from running a SECOND capture.** `tools/secret_task_capture.py`
was started by hand while the panel's «Мониторинг секреток» — the same script — was
already running on the same interface. The hand-started one saw a trickle:

```
traffic: 20 delivered / 11 with payload, 0 map response(s), 0 tile(s), kinds {}
Packets arrived but no map data.
```

…while the panel's own instance, at that same minute, was reporting `5117 map
response(s), 918999 tile(s)`. Two npcap captures over one stream, and the second one
gets almost nothing. It reads exactly like a dead client — a full map lap producing no
map data at all — which is why it was believed twice before anybody compared the two
counters.

**So: do not start a capture of your own while the panel's monitor is on.** Use what it
is already writing — `profiles/<profile>/secret_tasks.json`, which is the tab's own
source — or switch its monitor off first. Two more traps found alongside:

* the capture's port auto-detection can elect the CHAT port (`:17935`) and then decode
  nothing, because the map rides `:10012`. Take the port from the client's own live
  socket (`game_link.probe().conn`) rather than from a default;
* the monitor re-elects the on-screen server and **drops its index when the camera
  crosses to another server**, so hopping servers loses the previous one's findings.
  Read the checkpoint after each server, not at the end of a tour.

What survives from the earlier draft: the level minimum is where the tuning lives
(`autoloot_level_min` — a minimum, not an equality), and the wire listener still catches
an ally SHARING a tile faster than any sweep can pan over it.

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

## Pressing before the tile is ready, and pressing again (task #1272)

A raidable star is taken in the first instant it exists, so one send at the moment of
maturity loses to anybody who was already pressing. Two facts make the answer simple.

**A premature robbery costs nothing.** `DispatchStealMessage:HandleMessage` reads back
as `errorCode -> UIUtil.ShowTipsId(errCode)`, and the other branch is the only one that
touches the counter — through `ActDispatchTaskDataManager:UpdateTodayNum`, whose
constants are `todayStealNum | todayAssistNum | … DispatchTaskTodayNumUpdate`: it takes
the SERVER's numbers out of the reply rather than incrementing anything locally. So a
refusal — «ещё не готово», out of sector, slots full — leaves `todayStealNum` exactly
where it was. The operator states the same thing from the game side: «штрафа за
преждевременный сбор нет, сервер просто отвечает, что ещё не готово».

**Which makes the counter the only honest confirmation.** A `steal_sent` line proves a
frame left the client and nothing else. `secret_task_taken()` compares
`GetTodayStealNum()` against `__lw_steal_mark`, stamped when the target was armed; the
mark moving is the reply landing.

Together those turn the press into a loop. `secret_task_steals_pending()` answers «press
the same one again» — a head is queued, the day's budget is not spent, and the server has
not confirmed this one — so `TAP steal_secret_task xall` becomes a spam at the speed of
the channel (~7 presses a second; one round trip through the warm daemon is 80-135 ms,
task #1232), started a couple of seconds before the tile matures and stopped by the
server's yes. `secret_task_queue_pop()` moves to the next target; the head is no longer
dropped before its own send, which is what used to make the press a one-shot.

Verified live as far as a spent account allows: the queue is set, the mark stamped, the
pop advances, and the gate answers **0 with the day's five gone** — the spam cannot
hammer a server that has nothing left to give it. The taking half needs a budget and a
maturing tile in reach, which is a live acceptance still to be run.

The panel's own path shrank with it. «Автолут ★» used to spawn
`tools/steal_secret_task.py --queue-only` to park the targets and then play the recipe;
**that child costs five seconds, measured end to end**, which is the whole race. The
queue travels as an argument now (`ARGS queue`) and the recipe parks it. The tool keeps
`--from-scan` and `--coords`, which genuinely need a map scan and a round trip to resolve
a coordinate — neither of them in anybody's hot path.

## The three answers a robbery can get, and the one that was being ignored

Live report: «автолут пытается собрать то, чего уже нет… сервер отвечает, что забирать
уже нечего». The panel's own log showed it exactly — `TAP Rob a secret task xall -> 60
press(es)` on a single tile, the gate answering «1 available» every round, because the
loop had only two stop conditions: the counter moving, and the button's cap.

`DispatchStealMessage:HandleMessage` is `errorCode -> UIUtil.ShowTipsId(errCode)`, and
**the errorCode IS the message key**. Enumerating the client's own `dispatch_des*` family
gives the four that mean the tile is gone:

| key | text |
|---|---|
| `dispatch_des040` | Это задание выполнено, украсть его невозможно. |
| `dispatch_des041` | Невозможно выполнить: срок задачи истек. |
| `dispatch_des042` | Задание уже взято |
| `dispatch_des043` | Это задание больше не доступно |

**And the family holds no «ещё не готово» at all.** An early press is answered by silence
rather than by a refusal — which is why «any tip» would also have worked as a rule, and
why the four are named anyway: a message nobody has met should leave the loop pressing
rather than stop it.

So a robbery has three outcomes and the recipe now reports which, per target, as
`ACT steal_done uuid=<u> how=<taken|gone|unanswered>`:

* **taken** — `todayStealNum` moved. Ours; the row is marked and kept for sharing.
* **gone** — one of the four above. Terminal: the spam stops on the spot and the panel
  takes the row OFF the list (`SecretTasksTab._drop_gone`).
* **unanswered** — the spam ran out its cap with neither. The row stays: nothing said it
  should not.

`gone` is the one absence that IS evidence about a particular tile, and it is deliberately
not the rule #1272 added a few hours earlier (`_answerable`: a read may only testify about
its own source). That rule is about a tile missing from a LIST; this is the server
answering about the tile itself.

The tip is captured by a pass-through wrapper on `UIUtil.ShowTipsId`, installed once when
the queue is armed and cleared on every arm, so only a tip raised during our own press
window is read. Verified live: arming installs the hook, a real `dispatch_des042` raised
through the client's own function is recorded, and the gate falls to 0.
