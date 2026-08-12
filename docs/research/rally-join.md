# Alliance rally: listen / join / decline

Confirmed live via `tools/lua_trace.py` (`--filter March` / `--filter Message`) and reproduced
end-to-end with `tools/rally_join.py`. All calls run through xLua `SafeDoString` (see
`docs/research/xlua-state.md`); no UI is touched on the normal paths.

## Listing joinable rallies (no pcap)

`DataCenter.WorldMarchDataManager:GetAllMarches()` is a C# dictionary of every world march.
Iterate it with `GetEnumerator()` (the integer indexer returns nil — it is not a `List`):

```lua
local col = DataCenter.WorldMarchDataManager:GetAllMarches()
local e = col:GetEnumerator()
while e:MoveNext() do local mo = e.Current.Value ... end
```

A march with `teamUuid ~= 0` is part of a rally (стяг). Group marches by `teamUuid`; the
**leader** is the march whose `uuid == teamUuid - 1` (the game numbers `teamUuid = leaderUuid + 1`,
confirmed live). The leader march carries everything a join needs:

| field       | meaning                                   |
|-------------|-------------------------------------------|
| `teamUuid`  | rally id (non-zero)                       |
| `startPos`  | the leader's own tile — **the join's point argument** |
| `targetPos` | where the rally is going (the monster) — for a listing, never for a join |
| `serverId`  | target server                            |
| `ownerName` | player name (carries tags, e.g. `<Player3>`) |

`GetAllMarches()` returns **both sides** of a war; there is no reliable friend/foe field on the
march, so "joinable" = "led by an alliance-mate". Join is validated after the fact (a new own
march appears) rather than pre-filtered.

## Join

Wire command: `world.march.formation.new`. Sent by:

```
MarchUtil.SendCreateMarchMessage(formationUuid, 6, gatheringTile, teamUuid, 1, 1, false, server, nil)
```

`6` = rally target type. Joining an EXISTING rally = this call with the rally's non-zero
`teamUuid`. Re-joining a rally you are already in is suppressed client-side (no second message).

`gatheringTile` is the LEADER's own tile (`startPos`), not the rally's target — sending
the target is refused as «invalid end point», and it is what made this call look broken
for weeks. See «The wall was the END POINT» below.

**Choosing the squad:** the first argument (`formationUuid`) is which squad is sent. Squads
live in `DataCenter.ArmyFormationDataManager.ArmyFormationList` keyed by uuid; each has
`index` = the squad slot the player sees (1/2/3). So squad selection = pass the uuid whose
`index` is the wanted slot (`rally_join.py --squad N`, or `--list-squads` to see them). The
march object does not expose its formation back, so which squad was sent is confirmed visually.

Squad → formation mapping is account-specific. `formation_by_squad()` in
`tools/rally_join.py` reads the live `index` off `ArmyFormationDataManager` (authoritative),
and only falls back to an optional env-provided table (`LW_SQUAD_FORMATIONS`, see
`.env.example`):

| squad (index) | formationUuid       |
|---------------|---------------------|
| 1             | `<formationUuid-1>` |
| 2             | `<formationUuid-2>` |
| 3             | `<formationUuid-3>` |

**Empty-squad wall:** the send refuses a squad with no soldiers
(`ArmyFormationDataManager.ArmyFormationList[*].totalSoldierNum == 0`) before anything
reaches the wire — the client shows the «add soldiers» tip and the caller gets a clean
return. `MarchUtil.OnClickStartMarch(6, gatheringTile, teamUuid, -1, 1, 7, server, 0, 10)` —
the game's «в поход» entry — fills the squad from the base's pool (0 → 3123 verified),
**but it opens the dispatch panel**. A squad that already has soldiers needs none of that
and the join opens no UI at all. What the panel canNOT do is conjure soldiers that do not
exist: see «What the squad screen actually contributes» below for how an empty barracks
looks exactly like an unloaded squad.

Verify success by an increase in own marches:
`DataCenter.WorldMarchDataManager:GetOwnerMarches()` count (enumerate it). `IsHaveMarchInWorld()`
alone is not proof — it is already true whenever any unrelated march is out.

## Decline / leave

Wire command: `alliance.team.retreat`. Send it directly:

```
SFSNetwork.SendMessage("alliance.team.retreat", teamUuid, memberUuid)
```

`memberUuid` = your own march's `uuid` inside that rally (the entry in the team whose
`ownerName` is you). `MarchUtil.CancelRallyByMember(teamUuid, memberUuid)` also exists but only
pops a **confirm dialog**; the retreat message is what its OK button sends, so send it straight
to avoid the popup. Verify by re-checking the team members — your entry is gone.

`MarchUtil.CancelRallyByLeader(...)` is the leader-side disband (not used here).

## Tool

`tools/rally_join.py` wraps all of the above:

```
rally_join.py --list [--me NAME]              # print live rallies (leader/point/server/members)
rally_join.py --watch [--auto-join] [--me NAME]
rally_join.py --me NAME [--squad N]           # join the FIRST available rally (leader optional)
rally_join.py --leader <name|mask> --me NAME  # resolve + join a leader's rally
rally_join.py --team T --point P --server S   # join by explicit params
rally_join.py --cancel --leader <name|mask> --me NAME   # leave (auto-resolves memberUuid)
rally_join.py --cancel --team T --member M
```

`--me` / `--leader` match names as a case-insensitive substring (handles tag-wrapped names like
`<Player3>`).

---

## The send is accepted and does nothing — measured, not yet explained (#1237)

> **Explained since.** Everything in this section and the three after it was measured
> against a send aimed at the WRONG TILE; skip to «The wall was the END POINT» for the
> answer. Kept because the measurements are sound and the wrong turns are worth not
> taking twice.

`MarchUtil.SendCreateMarchMessage` returns cleanly and creates no march. This is the
same failure the tool's own verdict string has always named
(«no new march created … direct SendCreateMarchMessage no-ops»), measured properly so
whoever picks the reverse-engineering up does not have to start from scratch.

**What was measured.** Every reading below was taken with the state read and the press
run in ONE VM chunk, because squads come home and rallies expire between two calls and
the disagreement reads exactly like a bug (this cost three wrong conclusions first).

| Reading | Value |
|---|---|
| rallies the prelude finds | 1 (of 40 marches, 1 teamed, 1 leader) |
| squads sieved as at-home | all of the ones asked for |
| the press's own marker | `rally_join squad=1 team=… point=… server=<server>` |
| `pcall` around the send | `ok=true err=nil` |
| our squads in a rally, before → after | unchanged, every time |

**What it is not.**

* *Not the cold-formation rule.* It fails with `warmed=true` (the press ran the
  `OnClickStartMarch` warm-up) and with `warmed=false` (formations already loaded,
  direct send — the exact shape that worked on 2026-08-04). Warming by hand first,
  waiting for `totalSoldierNum` to come up (0 → 8319) and only then pressing, fails too.
* *Not the argument types.* The prelude hands `team`, `point`, `server` and the
  formation uuid as Lua **numbers**; an early reading that showed a string/number
  compare error inside `SceneUtils.lua:258` was an artefact of a probe that had
  `tostring()`-ed them.
* *Not the main-thread context on its own.* The press already goes through
  `TimerManager:DelayInvoke`, which is what a synchronous probe from the daemon lacks.
* *Not the squad state.* The sieve keeps only squads with `state == 0` and `IsFree()`.

**What is known to have worked**, once, on 2026-08-04 through the panel: formations
warm, `warmed=false`, and the alliance's `push.alliance.march.refresh` came back with
the player added to the participant list six seconds later. Nothing in the recipe
changed between that run and the failures.

**Where to look next.** The tool's own comment points at the panel-confirm context that
`OnClickStartMarch` → the squad screen → confirm sets up, and which the direct send
skips. That is a UI flow rather than one call, so the next step is to trace what the
game itself sends on a hand-made join (a capture of a manual join beside a bot one, on
the same rally) and diff the two — the wire is the only place the difference will be
unambiguous.

Until then `actions/join_rally.md` **counts the squads standing in a rally before and
after the press** and fails saying so when the number does not move, so the ability is
honest about the state it is in.

### The real signatures, read off the live VM (#1237)

The client's Lua is not stripped, so `debug.getinfo` + `debug.getlocal` give the true
parameter NAMES — which matters here because everything below used to be positional
guesswork copied from one working call:

```
SendCreateMarchMessage(formationUuid, targetType, targetPoint, targetUuid,
                       timeIndex, autoBackHome, needSoldier, targetServerId,
                       destroyTimeIndex)
OnClickStartMarch(targetType, pointIndex, uuid, index, backHome, rallyType,
                  targetServerId, targetWorldId, monsterSpecialType, ignoreNotice)
OnJoinRally(selfMarchUuid, rallyType, targetUuid, targetPointId, curStamina)
TryStartMarch(selfMarchUuid, theMarchTargetType, curStamina, isFormation, targetUuid,
              pointId, backHome, needSoldier, destroyTimeIndex, targetServerId)
StartMarch(targetType, targetPoint, targetUuid, timeIndex, mUuid, fUuid, autoBackHome,
           dataObj, pos, targetServer, desTimeIndex, extraParam)
```

**`MarchTargetType.JOIN_RALLY == 6`** — read out of the live enum, so the magic 6 the
tool has always passed is right, and «wrong target type» is not the explanation. (5 is
`ATTACK_ARMY`, 7 is `RALLY_FOR_BOSS`; the enum has 126 entries.)

**The march object carries exactly one point field.** Probed by name on a live march:
`targetPos`, `serverId`, `targetServer`, `worldId`, `uuid`, `ownerUid`, `status`, `type`
answer; `targetPoint`, `targetPointId`, `pointId`, `pointIndex`, `endPoint`, `endPos`,
`targetX`, `targetY` do not exist. So `targetPos` IS the end point and reading it is not
the mistake either.

### THE LEAD: the game has a join-a-rally entry and the bot has never used it

`MarchUtil.OnJoinRally(selfMarchUuid, rallyType, targetUuid, targetPointId, curStamina)`
— and its constants show what it does: `GetCostStaminaByTargetType` with
`MarchTargetType.JOIN_RALLY`, the `LWResourceLackUtil` energy check, then **`StartMarch`**.

The bot calls `SendCreateMarchMessage` instead, which is the low-level sender at the
BOTTOM of that path. `StartMarch` takes `mUuid`, `fUuid`, `dataObj`, `pos` and
`extraParam`; `SendCreateMarchToServer` takes `formationData` and `startPos`. None of
those reach the server when the bottom of the stack is called directly, and the player's
report of the error — «invalid end point» — is about exactly the kind of thing those
carry.

So the next thing to try is the game's own entry, on a live rally:

```lua
MarchUtil.OnJoinRally(formationUuid, rallyType, teamUuid, targetPos, curStamina)
```

`selfMarchUuid` is almost certainly the formation uuid (`TryStartMarch` takes the same
first argument and passes it to `CheckFormation` + `SendCreateMarchMessage`), and
`rallyType` is the btnType the create side already uses (`RALLY_FOR_BOSS = 7`). Both
need confirming against a rally that is actually out — none was during this session.

### The wire diff, both sides measured (#1237)

A trace of a HAND-MADE join (`results/traces/…_ралли_trace.log`, «присоединение к ралли
первым отрядом») against the bot's own press, hooked at `SFSNetwork.SendMessage`:

```
game: world.march.formation.new | <formation> | 6 | <team> | 400500;400900 | 1 | true | <heroInfos> | <server> | -1 | nil | nil | <OBJECT>
bot:  world.march.formation.new | <formation> | 6 | <team> | 400500;700400 | 1 | true | <heroInfos> | <server> | -1 | nil | nil | nil
```

Identical but for the LAST argument. Everything the earlier sessions suspected is
therefore ruled out by observation, not by argument:

* the **target type** is 6 in both — and `MarchTargetType.JOIN_RALLY == 6`;
* the **path** is well formed in both: `<our base tile>;<rally tile>`, so «invalid end
  point» is not a malformed endpoint but the server refusing the message as a whole;
* the **heroInfos** array is present in both — the heroes are not what is missing;
* the **formation uuid** is the same one in both.

What is missing is the thirteenth argument. `SendCreateMarchMessage` builds it from the
formation's own soldier state — its constants are `hasSolider`, `curSoldiers`,
`soldierIdNumArra`, `soldierIde`, `soldierNume`, `armyArrayT` — and the bot's press
produces `nil` there while the player's press produces an object. A march with heroes
and no soldiers is what the server is being asked for.

Leaving the squad screen OPEN and sending (rather than closing it first, which is what
`join_next_rally` does) makes `SendCreateMarchMessage` emit no message at all — so the
window is not simply «the thing that fills it in» either.

**The precedent to follow is the hospital** (`docs/research/hospital-heal.md`, the
`project_hospital_heal` note): the same shape of bug — a plain send silently dropping
the army array — and the fix there was to assemble the message and hand it to the Lua
message path rather than calling the convenience wrapper. That is the next thing to
build here: assemble `world.march.formation.new` with the soldier object filled in, and
send it the way `hospital.cure` is sent.

### Where the protocol route stopped (#1237)

Two more things were ruled out by direct test rather than by argument, and then the
route ran into a wall worth naming so the next attempt does not re-walk it.

**The thirteenth argument is not the cause.** The player's own join passes an EMPTY
table there and the bot passes `nil` — the only difference the two messages had. A patch
that substituted `{}` for `nil` on every march send was installed, a warm formation was
prepared, the press fired with the patch applied (counter = 1), and no march was
created. Measured, not reasoned.

**The message bodies match.** Unpacked from a live send, the bot's `formationParam` is
`{dataHolder = {formations = …, heroInfos = …, uuid = <formation>}}` — the same three
keys the trace shows the game building, and the same `path` shape (`<base tile>;<target
tile>`). The formation is warm at press time (3123 soldiers).

**Where it stopped.** How many entries are actually inside `heroInfos` and `formations`.
The trace shows the player's join carrying SIX heroes (`heroUuid` + `index` 1…6); the
bot's counts could not be read at all. Both containers cross the Lua/C# boundary as
`{Data = <C# collection>, Type = 17}`, and two attempts to count them — `pairs(x.Data)`
and a `:Size()` probe — returned `?` rather than a number. So «the bot sends no heroes»
is UNVERIFIED, not established, and must not be repeated as though it were.

Anyone picking this up again starts there: read those two collections properly (the
`Type = 17` wrapper is the thing to understand), and compare the counts against the six
the trace records.

One observation left unexplained: one bot send had a path starting `400502` where every
other send, the player's and the bot's, started `400500`.

---

## The wall was the END POINT, and everything above it was downstream (#1237)

None of the collections above needed reading. A joiner does not march to the monster —
the troops gather at the base of whoever raised the banner and set off from there
together — so the end point of a join is the LEADER'S OWN TILE. The three places a march
carries, read off a live rally:

| field       | is                                    |
|-------------|---------------------------------------|
| `targetPos` | where the rally is going — the monster |
| `startPos`  | the leader's own tile — where joiners gather |
| `homePos`   | the marcher's own base                 |

Every member march of every rally out says the same thing from the other side: its
`targetPos` is the leader's tile and its `homePos` is that member's own base. The bot
was sending the monster: a real tile, just not one a joining squad may be sent to — so
the server refused the march as «invalid end point» while the client dutifully flew the
camera there. The player saw it without a single probe: joining by hand moves the camera
to the PLAYER who raised the banner, the bot's press moved it to the monster.

Re-read in that light, the wire diff two sections up was already saying so. The two
paths were `400500;400900` (the player) and `400500;700400` (the bot) — the SAME start
and DIFFERENT ends. It was written up as «identical but for the last argument», and the
thirteenth argument, the hero arrays and the message bodies were all chased downstream
of a difference that was in plain sight.

`joinpoint` in `_RALLY_PRELUDE` (tools/lib/lua_actions.py) is that tile, kept beside
`point` rather than replacing it: a LISTING should show where a rally is going, and only
the join side wants the gathering tile.

## What the squad screen actually contributes (#1238)

Nothing, to the message. The client's Lua is not stripped, so a function's constants can
be read straight off the live VM with `string.dump` — unwrap any trace hook first by
walking `debug.getupvalue` down to the innermost function, or you get the hook:

* **`MarchUtil.SendCreateMarchMessage`** (`MarchUtil.lua:1633`) builds the whole thing
  out of the SQUAD: `GetFormationStartPos`, `ArmyFormationDataManager:GetOneArmyInfoByUuid`
  (→ `soldiers`, `heroes`), `GenerateServerHeroArray`, `RefreshFormationModelToJson`,
  then `StartMarch`. Not one window is read.
* **`MarchUtil.StartMarch`** (`:1828`) is what moves the camera and picks between
  `SendChangeMarchToServer` (this formation already has a march) and
  `SendCreateMarchToServer`.
* **`MarchUtil.TryStartMarch`** (`:574`) — the stamina check, `CheckFormation`, then
  `SendCreateMarchMessage`.
* **`UIFormationSelectListV2Ctrl:OnCheckTime`** — the screen's launch — is march-time and
  confirm dialogs (`alliance_boss_001/002`, `assembly_monster_toplimit`) and then
  `OnCreateClick`, which ends in the same send.

So the screen's contribution is: it lets a human pick the squad, it shows the
confirmations, and — the one that matters to a bot — **it fills an empty squad with
soldiers from the base's pool**. A squad that already has soldiers needs none of it.

**The client refuses to send an empty squad before a byte leaves.** The send's own
constants are `hasSolider` / `hasHero` and `UIUtil.ShowTipsId(GameDialogDefine.ADD_SOLDIER)`
— what the player gets is the «add soldiers» tip, not an error, and what a bot gets is
`ok=true` and no march. That is the whole of the «cold formation wall», and it is worth
naming precisely because it has a second cause that looks identical:

> **`totalSoldierNum == 0` can mean the ACCOUNT has no soldiers, not that the squad is
> unloaded.** Measured live on 2026-08-05: three squads, five heroes each, `state = 0`,
> `IsFree() = true`, `GetAllTotalSoldierNum() = 0`, nothing unformed, 555 wounded in the
> hospital. Nothing warms a squad in that state — not the screen, not
> `AutoInitFormationData`, `AutoAddSoldier`, `RefreshFormationSoldier` or
> `FetchFormationSoldier`, each tried and each a clean no-op — because there are no
> soldiers to put in it. The answer is the hospital, not this ability. A run in that
> state joins nothing by ANY path, and «нажали и ничего» is exactly what it looks like.

### Where that leaves the join

`actions/join_rally.md` sends first and opens the screens only if the map does not move:

    arm -> (squad has soldiers?) -> send -> poll ~1.5 s -> already in it? -> done
                                        \-> not in it -> open screen -> pick -> launch

The fallback is not decoration: it is what fills an empty squad, and it is what the run
falls back on if the screenless send turns out to want something else after all. The
same correction went into the two other places that send directly —
`join_next_rally()` and `tools/rally_join.py`, both of which were still aiming at the
monster.

**Confirmed live, 2026-08-05.** One run of `join_rally` against a banner the alliance had
just raised, with the game lease held so nothing else could be doing it:

```
TAP arm the join (rally + squad)
READ_LUA armed = 1
READ_LUA soldiers = 3123.0
IF soldiers > 0 -> True
  TAP join the rally with no screen
  READ_LUA joined = 0
  WAIT 0.25s
  READ_LUA joined = 1
  LOG "joined the rally without opening a screen"
```

One press, one quarter-second poll, no window: **`> action` to done in about a second**,
against the four presses the screens cost. The fallback below it did not run.

### What the screen costs, measured step by step

Both paths driven through the SAME buttons the recipe presses, on live rallies of the
alliance, with the game lease held so nothing else could be joining beside them. Each
line is that step's own time; the last is the server's answer arriving on the map.

```
  SEND (no window)                    SCREEN (the path before this)
  arm (rally + squad)     187 ms      arm (rally + squad)       204 ms
  read: armed?            148 ms      read: armed?              148 ms
  SEND                    233 ms      open the squad screen     301 ms
  the map says we are in  219 ms      wait: screen is up        204 ms
                       ────────       pick the squad            559 ms
                 TOTAL    788 ms      read: pick took?          392 ms
                                      read: rally still up?     251 ms
                                      launch                    773 ms
                                      the map says we are in    596 ms
                                                             ────────
                                                    TOTAL     3430 ms
```

**The screens are 2.48 s of a 3.43 s join — about 72% of it.** Not a rounding error and
not worth keeping for its own sake: on a banner that stands for a minute or two, it is
the difference between arriving with the places still open and arriving late.

Both runs above ended with a squad standing in the armed rally (`0 → 1` and `1 → 2`), and
the screenless send has now done it three times out of three unhooked runs (17:40:10,
17:46:31, 17:50:03; 788, 720 and ~1000 ms).

### The hero and formation arrays: built by the SEND, not by the screen

The wall the previous session hit — counting the `{Data = <C# collection>, Type = 17}`
wrappers — did not have to be climbed. Count the game's own array-building calls instead,
by wrapping `SFSArray.New` / `SFSArray.AddSFSObject` / `SFSObject.PutSFSArray` for the
length of one press. Our screenless send builds:

```
arrays=2  added=6  put=2  keys=formations,heroInfos
```

Which is, object for object, what the trace of a HAND-MADE join records: two arrays put
under `formations` and `heroInfos`, six objects added — the six heroes — and **nothing
added to `formations` at all**. So:

* the hero array is not something the screen produces; the send builds it from
  `GetOneArmyInfoByUuid` on the squad, with no window anywhere;
* the soldiers do NOT ride in `formations` — that array goes out empty on the player's
  own join too. What carries the army is the thirteenth argument, which the send builds
  for itself.

One caveat recorded rather than smoothed over: the run with those hooks installed built
the message and did NOT end in a march, where three unhooked runs did. The hooks are the
obvious suspect — they replace three xLua-bound statics for the length of the press — but
that is a suspicion, not a measurement, and anyone repeating this should count first and
judge the join on a clean run.

## Why the auto-join still missed banners, measured end to end (#1281)

The join itself worked. What did not was everything around it — and none of the four
causes below is visible from inside the recipe, which is why «пытается, эффекта ноль»
survived three tasks.

### 1. The recipe took eight readings before it sent anything

`tools/dev/rally_latency.py` walks the readings the old `join_rally.md` made, in its
order, against the live client and times each. Two rounds, taken while the panel was
doing its ordinary background work:

```
rally_monitor read        11500 ms      16406 ms
squads sieve              13422 ms      17204 ms
free_squads               10328 ms      18296 ms
rallies_out               12719 ms      13360 ms
before-count              15031 ms      12422 ms
armed?                    19156 ms      10875 ms
soldiers                  19000 ms      11640 ms
TOTAL before the send    101156 ms     100203 ms
```

**A hundred seconds to the send, twice over.** The client was not the problem: measured
in the same session, `tools/dev/call_latency.py` reported a frame time of 16.9 ms (59
fps) with a reaction of 4.2 s p50 — 227 client frames spent waiting for a chunk to be
delivered. Nor is the floor anything like that: with the daemon free the same call is
**0.14 s**. What varies by two orders of magnitude is how much else is queued in front of
it, because `lua_daemon.Daemon.run` serialises every chunk behind one lock and holds it
across the settle (`docs/research/architecture-audit.md` §1.1).

So the number of CALLS is the only part of this the ability controls, and it is the part
that was wrong. `lua_actions.rally_join_all` does the sieve, the pairing and the send in
one chunk; the recipe parks its argument in another. Measured back to back on the same
client, in the same minute, with a rally out:

```
OLD to the send: 5.48 s (7 calls)      # the daemon happened to be quiet
NEW to the send: 0.19 s (2 calls)
```

### 2. One run joined ONE rally, and the second push was coalesced away

The old recipe armed one rally, sent one squad and stopped. A second banner going up
while that run was in flight fired the trigger again — and `TimerScheduler.submit`
dropped it, because an errand of the same name was already claimed. Two banners in a
minute were one join at best. The chunk now pairs every free squad with a different
banner in one pass, and a fire that lands mid-run is re-armed rather than dropped.

### 3. The daily-cap gate cost a whole game call, in front of the join

`panel/tabs/rally/limits.py::join_gate` read the march table through the VM
(`settle=0.8`) before the recipe was allowed to start — to be told the constant the
module already knew, since no rally classification is confirmed live and every rally came
back as the fallback type. It answers from the counts file now.

### 4. A fire was announced, a run was not

`TriggerWatcher._fire` logged «пришло push.alliance.march — запускаю сценарий» BEFORE
submitting, and discarded what submit answered. On 2026-08-07 one profile logged that
line **10 035 times and ran the scenario not once**: its client was down, the schedule's
gate refused every one of them, and the refusal — «жду запуска игры» — is said once per
stretch and names no errand. Thirty-one lines for ten thousand skips, none of them
attached to a rally.

That profile heard those pushes at all because a capture cannot separate two accounts by
port and falls back to the whole machine when it cannot resolve the client's pids
(`panel/runtime/wire.py`) — with the client down, there are no pids, so it was firing off
ANOTHER account's alliance. Worth knowing when reading a log: a profile with no client
still hears everything.

### What a squad screen is still for

The one thing the headless send cannot do is fill a squad standing EMPTY from the base's
pool — the client refuses a squad with no soldiers before a byte leaves. That is not the
march, so it is no longer on the march's path: `join_rally.md` sends for every squad that
has an army first, and only a run that sent nothing at all calls
`join_rally_via_screen.md`. On the account this was measured against, all three
formations read `totalSoldierNum = 0` with `state = 0` and `IsFree() = true`, so that
path is not hypothetical — dropping it would have dropped the ability.

### The live run, with the numbers (#1281)

Panel restarted onto the new recipe, the auto-join trigger on, squads 1–3 allowed.
Observed on real alliance banners:

```
16:09:52  push.alliance.march lands, the trigger fires
16:09:54  LUA  __lw_rally_squads = { 1, 2, 3 }
16:09:54  TAP  join every rally that can be joined
16:09:54  report = 'sent=1 rallies=1 free=3'
16:09:54  joined = 1                      <- a squad of ours standing in the rally
```

**Two seconds from the push to a squad in the rally, with no window opened.** The
re-arm can be seen working in the same minute: «пришло push.alliance.march на ходу —
сценарий будет запущен ещё раз» at 16:09:54, and the extra run went out at once and
reported, correctly, that there was nothing left to join.

Every run that sent nothing said why, in the chunk's own words — `left=[1:out 2:empty
3:empty]`, `-- no rally of this alliance is out that we are not already in`, `-- not one
of the chosen squads can be sent`. There is no longer an ending that is silent.

**The screen fallback is NOT proven and failed the once it was reached.** At 16:10:29 a
banner was out with one squad marching and two standing empty, `todo = -1` sent the run
into `join_rally_via_screen.md`, and the game's own launch threw from inside its own
code:

```
TAP launch the join error: ERR: …/Util/SceneUtils.lua:258: attempt to compare nil with number
```

The four presses before it all confirmed their state (`armed=1`, `screen=1`, `picked=1`,
`alive=1`), so the screen path reached the launch and the launch is what broke. It is
unchanged code — the same presses the old recipe made — so this is not a regression from
this task, but it does mean the empty-squad case has no working route at all right now.
Whoever picks that up: the error is in the CLIENT's Lua, so the argument it compares is
one the screen expects and the press is not giving it.

**Two banners, one press, both landed** — the thing the old shape could not do at all:

```
16:18:40  report = 'sent=2 rallies=2 free=3'
16:18:40  joined = 2
```

Thirteen minutes of a live alliance, counted off the panel's own log: **13 pushes fired
(7 re-armed mid-run, 7 coalesced onto a run that had not looked yet), 16 runs, 3 squads
sent, 3 joins confirmed, 0 endings that said nothing.** The one run that joined nothing
with a banner out is the empty-squad case above.

## The empty squad was never empty (#1285)

The one gap left by #1281, and it turned out not to be the gap it looked like. A squad
reading `totalSoldierNum = 0` is not a squad with no army — it is a squad **the client
has never asked the server about**. One message fetches it, no window is opened, and
the case that had no working route at all now has a headless one.

```lua
SFSNetwork.SendMessage(MsgDefines.GetFormationSoldier, formationUuid)
--                     MsgDefines.GetFormationSoldier == "formation.get.soldier"
```

Measured live, on an account whose three squads all read zero while the base held
sixteen thousand soldiers:

| step | reading |
|---|---|
| all three squads before | `totalSoldierNum = 0`, `soldiers = {}`, `state = 0`, `IsFree() = true` |
| the base's pool | `SoldierDataManager:GetPlayerSoldiersTotalNum()` in the thousands |
| one message per squad | all three came back with an army, in one pass |
| blank the client's copy and ask again | **0 → full in 0.37 s**, the two VM round trips included |

The reply lands in `ArmyFormationDataManager:RefreshFormationSoldier`, which fills
`formation.soldiers` — `posIndex → {soldierId = count, supply = n}`, one entry per hero
slot — and the total every gate downstream reads. The base's own pool does not go down:
the soldiers are spent when the march goes out, not when the client learns about them.

### Every filler the client has of its own is a no-op, and why

Each was pressed on a live empty squad, one at a time, with the count read before and
after. All four returned cleanly and changed nothing (`0 → 0`):

`AutoInitFormationData`, `AutoAddSoldierByForm`, `AutoAddSoldier` (with `useForm` both
ways), `FetchFormationSoldier`.

They share a source. `AutoAddSoldierByForm` sorts `GetArmyUnFormationList()` by level and
tops the squad up to `MarchUtil.GetMaxCanAddSoldierNum(heroes, index)`;
`GetArmyUnFormationList` is `ArmyManager:GetArmyFreeList()` filtered by `restCount`; and
`GetArmyFreeList` walks **`ArmyManager.allArmy`, which is EMPTY** on a live logged-in
client — measured repeatedly, in the city, across two client restarts. `ArmyManager` is
filled by `InitData(message)` off `army.info`; sending `army.info` by hand does not fill
it either. So the client-side recruitment path is not the one to chase — the fetch is.

**This is the difference between «unloaded» and «empty», and the log now says which.**
A squad that still reads zero AFTER the fetch is genuinely empty, and nothing the bot can
press changes that — the answer is the barracks or the hospital.
`actions/fill_empty_squads.md` says so in its own words, and `join_rally.md` ends on
«the squad is empty and the game has no army to fill it — nothing was sent» rather than
on a failure.

### `SceneUtils.lua:258`, explained and then made irrelevant

The screen path's launch threw from inside the client's own Lua (#1281, above). The line
belongs to **`SceneUtils.IndexToTilePos(index, forceType)`** (`@244-280`, found by walking
every loaded function for one whose `debug.getinfo` source is `SceneUtils` and whose line
range covers 258), and the nil is the INDEX. Reproduced by calling it directly:

```
IndexToTilePos(nil)      -> SceneUtils.lua:258: attempt to compare nil with number
IndexToTilePos(nil, 1)   -> the same
IndexToTilePos("400500") -> :258: attempt to compare string with number
IndexToTilePos(400500)   -> fine, with or without a forceType
```

So a point index arrives nil on the way to the send: `MarchUtil.SendCreateMarchToServer`
is the caller that turns one into a tile (`IndexToTilePos`, `TilePosToIndex`), and for
`JOIN_RALLY` the end point is the argument rather than something read off the march.
Which of the screen's own values was missing was not chased further, because the screen
went away with this task: `join_rally_via_screen.md` is deleted, its three buttons with
it, and `join_rally.md` calls the fetch instead. If the screen is ever needed again, this
is where to start — and instrumenting `IndexToTilePos` with a `debug.traceback` shim is
one line.

### Two hazards worth not repeating

* **Do not walk `_G` and `package.loaded` recursively with `string.dump`.** A broad scan
  for a constant took the client down; the narrow version — name the handful of tables to
  look in — costs nothing and has been run many times since.
* **The UI classes are not there when the window is not.** `package.loaded` carried the
  fourteen `UIFormationSelectListV2` modules while the screen had been up and none of
  them minutes later, so a controller can only be dumped while its window lives.

## The game's own record: the trophy list (#1281)

The person playing asked how the banners were proved real, and answered it in the same
breath: **a finished rally always pays a trophy**, and the world map has a gift button
beside the heroes listing every one and what it was for. That is the first evidence in
this task that does not come from the panel's own log — everything before it was the log
agreeing with itself.

It is `DataCenter.CollectRewardDataManager.collectRewardList`, found the way the
ghost-recon list and the «Кодовое имя» status were: by asking the client which of its own
managers hold something reward-shaped. One row per unclaimed trophy:

| field | what it is |
| --- | --- |
| `uuid` | the trophy's own id |
| `type` | `6` — the same march type a rally join is sent with |
| `pointId` | the tile the rally attacked; **this is what identifies which banner** |
| `contentId` | what was rallied |
| `expireTime` | when it stops being claimable |
| `rewardList` | what it pays (five entries on every row seen) |

**What empties the list is COLLECTING, not time.** A first reading of this said a trophy
lives «about an hour», from a delta of 1:01:03–1:02:48 across eight rows; that was an
artefact — the log's time of day pasted onto the trophy's expiry DATE, measuring two
clocks three hours apart rather than an age. Against the game's own clock (offset 0.0 h
from the PC here) those same rows had **98–100 hours left**. The horizon is therefore the
last collection, and nothing in this repository's schedule claims these rows — checked:
no scenario or timer touches `CollectRewardDataManager`, so the bot is not destroying its
own evidence. A person collecting them by hand does.

**It holds only the rallies WE were in.** Eight rows while the alliance ran forty-nine
banners in one earlier window. So it gives the exact number we WORKED and cannot show a
banner we missed; «missed» stays a subtraction — joinable minus these.

### What it said about our own numbers

`tools/dev/rally_trophies.py --check FROM TO` counts the trophies whose banner the panel
first saw inside a window and prints them beside the joins the log confirmed there:

```
18:00–19:00   trophies 5   log 5   MATCH
17:00–18:00   trophies 3   log 2   the log missed one
before 17:08  trophies 0   log 5   no evidence either way — the rows are gone
```

The MATCH is on the newest code and is the one the summary was reported from. The
17:00–18:00 gap is ours: the counter's needles carried the interpreter's indent and
stopped matching the confirming read inside a nested branch, which is the same defect
this file records under the counter. The third line is not a disagreement and must not be
read as one — a window reaching past the last collection has no rows to check against.

## The game keeps the count itself, and ours was wrong (#1281)

The person asked how rallies are counted per monster kind, and the answer turned out to
be that the question has a different shape: **the client keeps ONE daily rally-boss
counter, and it is the game's, not ours.**

```
DataCenter.MonsterManager
  daily_kill_boss          = 8      GetKillBossNum()        -> 8
  kill_boss_max_num        = 20     GetMaxKillBossNum()     -> 20
                                    GetRestKillBossNum()    -> 12
  find_monster_max_level   = 35     GetCanFindMonsterMaxLevel()
                                    GetCurCanAttackBossMaxLevel() -> 3
  UpdateKillBossNum(...)
```

**Twenty a day in total, not twenty per kind.** The «20» the daily plan speaks of is real
and it is the client's own number; what is not real is the per-kind split, and no reading
found anywhere in this task supports one (see the four dead ends below).

**And our own count disagreed with it, in the direction that costs rallies.** At the same
instant the game said `daily_kill_boss = 8`, `profiles/<name>/rally_counts.json` said
`{"monster": 20}` and the auto-join had been refusing every banner since 19:42 with «the
daily cap is spent». Twelve rallies we were entitled to, refused by a number we keep
ourselves. The cure is not a better tally — it is to stop keeping one: `GetRestKillBossNum()`
is the answer, from the authority that decides it.

### …and the door came back, on the same number (#1317)

#1281 removed the tally AND the refusal that rode with it, on the true observation that
past twenty the game stops PAYING rather than stops joining. The player has since said
what the second half of that costs: **«лимит Роковой Элиты стоит 20, а бот целый день
цепляется к стягам»**. A squad in an unpaid rally is a squad that is not at home for the
next banner, for the rest of the evening — measured on the live profile the day #1317 was
written: `daily_kill_boss = 275` against a threshold of 20, and 320 joins in the panel's
own per-kind record over the same day.

So the door is back and the tally is not:

* **the ceiling is the person's** — one number on «Автосбор», stored in the «Ралли» tab's
  own profile block (`autorally.daily_max`, default 20 = the game's own threshold, `0` =
  no ceiling). It travels to `actions/join_rally.md` as `max_joins`, from BOTH drivers:
  the schedule's «rally_auto_join» hook and the tab's own capture reader;
* **the count is the game's** — `GetKillBossNum()`, read inside `rally_join_all`'s single
  chunk, so the door costs no call on the path a banner is decided in;
* **nothing is written down** — `rally_counts.json` stays what #1281 left it as: a record
  of what the joins went for, and the cap on the tab's own «Запустить» run. It is not read
  back to refuse a join and never will be.

When the ceiling is reached the chunk sends nothing, names every banner it passed over as
`day-capped`, reports `cap=<done>/<ceiling>` and sets `__lw_rally_todo = -4`; the recipe
stops on that verdict BEFORE its «fetch an army for the empty squad» branch — a spent day
is spent whether or not a squad is standing empty.

**Two limits are known and written down rather than left to be discovered:**

1. **the count lags the joins.** It moves when a rally FINISHES, so a ceiling can be
   overshot by roughly the squads in flight (four here). Nothing readable in the client
   counts a JOIN — see the four dead ends below, which were re-checked for #1317 and are
   still dead.
2. **it is one total, not a split.** There is no per-kind number in the client at all
   (below), so a per-kind budget can only be one the panel keeps — which is what #1317
   went on to build, with that said out loud first.

### Every kind a banner can be, and the search for a counter per kind (#1317)

The player asked for a counter per kind — «кроме Роковой Элиты есть ещё генералы,
простые и элитные». Two questions, and they have different answers.

**What the kinds ARE — read out of the live config,** `lw_world_monster` through
`LocalController.instance():getTable(...)`: 12 115 rows, 97 columns, values reached as
`row[index[col][1]]` and localised strings through the table's own `vExt` pool. Grouped by
`type` there are 25 species families and 13 of them carry `boss = 1`; grouped by the
`name` key — which is what actually identifies a species — the ones a player meets are:

| kind key | name key | the game's own words (en / ru) | where it lives |
| --- | --- | --- | --- |
| `doom_elite` | `300602` | Doom Elite / Роковая Элита | types 1, 3 **and** 17 |
| `doom_walker` | `monster_boss_name_001` | Doom Walker / Разрушитель | type 8 |
| `zombie_boss` | `2901012` | Zombie Boss / Зомби-Босс | type 7 |
| `general_trial` | `2010220` | Vanguard Instructors / Инструкторы Авангарда | `activity = 107` |
| `general_trial_elite` | `challenge_zombie_001` | Elite Instructor / Элитные Инструкторы | `activity = 107` |
| `alliance_drill` | `500426` | Alliance Exercise / Учение Альянса | its own manager |
| `zombie_invasion` | `2901000` | Zombie Invasion / Вторжение Зомби | its own manager |

**THE `doom_elite` KEY HAD BEEN COUNTING THE WRONG SPECIES.** It was `type == 8`, which is
the Doom WALKER line; Doom Elite is `300602` and appears under three types across seasons.
That is why the identity is the `name` key now, and why #1317 carries the stored number
onto both rows rather than renaming in place (`rally_limits.RENAMED_KINDS`).

The two events are not species on the map and are matched off their own managers:
`AllyDrillDataManager.actInfo.data` carries the exercise's `bossUuid` / `bossPointId`
(read live while a drill was running, with `isAutoRally = 1` beside it), and the invasion
keeps its own monster lists, as before.

**And the counter per kind does not exist.** Walked for #1317, in the live VM:

* `MonsterManager` in full — `daily_kill_boss`, `kill_boss_max_num`,
  `find_monster_max_level`, `whistleRewardNum`, `lastTime`. One total, no split;
* every manager in `DataCenter` whose name matches boss / monster / rally / act / season,
  for any numeric field named `*times*`, `*remain*`, `*num*`, `*count*`, `*limit*`. What
  came back is other events' own budgets — `ActGhostreconManager.stealTimes`,
  `ActDispatchTaskDataManager.todayStealNum`, `SeasonDataManager.daily*` — and nothing
  that counts rallies by kind;
* the trophy list (`CollectRewardDataManager.collectRewardList`), which does carry a
  `contentId` per finished rally and could be grouped by kind: **it is emptied when the
  player collects**, and it read `0` rows at the time of this check.

### The whole vocabulary, and what each event answers to (#1317, round two)

The player's answer to «сколько видов взять» was «делай всех, кого перечислил», so the
list is not a selection any more: every `boss = 1` row of `lw_world_monster` — **71 name
keys, 66 distinct names**, because the game gives six different rows the same words
(«Роковая Элита» is `300602`, `s6_monster_eliteboss_name`, `season_monster_name001`,
`season_s2_monster_name001`, `season_s3_monster_name007` and `season_s4_monster_lang_name`).
The map lives in `tools/lib/rally_kinds.py`, was generated from the live config rather
than typed, and the labels are pulled out of the game's own locale tables into
`panel/locales/*.json` by the same generator.

What that list covers, by season: the Doom line (Doom Elite, Doom Walker), the zombie line
(Zombie Boss, Invading Zombies, Zombie Horde, Zombie Raider, Mutant Raider), season 1's
Crimson family, season 2's mutated beasts and the Glacieradon, season 3's Golden guards,
the sandworms and the Desert Boss, season 4's Oni family (Oni General, Oni Dōji, Oni
Tengu, Oni Samurai, the Oniwagon and the two Oni legions, the Bloodnight Alpha Wolf and
the Blood Night Doom Elite), season 5's Plague nomads, season 6's Shadow four and the
Wonder boss, plus the one-offs (Ironclad Vehicle, Maxwell's «Comrades», Sky Predator,
Willson the Slugger, the Corruptors, the summoned mummies and the Night Army).

**Each event was checked on its own, as asked:**

| event | what identifies it | state when checked |
| --- | --- | --- |
| Alliance Exercise | `AllyDrillDataManager.actInfo.data.bossUuid` / `bossPointId` | **running** — the ids were read live, `isAutoRally = 1` beside them |
| General's Trial | its species: `activity = 107` (Vanguard Instructors, Elite Instructor) and `2010221` Elite Forces, the alliance boss | config only; the event was not on |
| Zombie Invasion | `ActivityMonsterInvasionDataManager.monsterInvasionData` lists | **off**: `invasionId = 0` and `monsterInvasionData` is nil, which is why every read of it is inside a `pcall` |

Two more trial-shaped managers exist and are NOT the General's Trial —
`JungleTrialDataManager` and `LWActivityLockhartManager`; they are named here so the next
reader does not spend the same twenty minutes on them.

So a per-kind budget is the panel's own tally or it is nothing. The person was told that
in those words and chose it — «по умолчанию на всех по 20, на золотых оставляем без
лимита» — so every kind ships capped at twenty and the whole Golden line uncapped
(`desert_boss`, `golden_defender`, `golden_striker`, `golden_annihilator`,
`wandering_mummy_warlord` — the person listed them when the first, narrower reading of
«на золотых» proved to be one species), and the drift has rules rather than hopes:

* **one writer** (`limits.record_run`), counting only what the game CONFIRMED — the run's
  own `joined`, a difference measured in the client. #1281's tally counted sends and went
  twelve ahead;
* **the day is the server's** — `GetTomorrowZero()`, stored as `day_end_ms` in
  `rally_counts.json`, never this machine's midnight;
* **the decision is inside the press**, so two banners of one kind in a single run cannot
  both take the last slot;
* **the tally is reconciled with the game's own count every time it is used**
  (`limits.ahead_of_game`): while the panel's sum is AHEAD of `daily_kill_boss`, **no
  per-kind door refuses anything**. A banner may never be held back by a number the game
  contradicts — that is exactly the failure #1281 suffered;
* **the game-counted total ceiling stands over all of it**, so drift cannot cause an
  overspend either;
* and **both numbers are on screen** — «наш счёт / игра» under the table in the window and
  as a row on the phone — because a tally nobody can check is a tally nobody should trust.

The two files carry a `v` since #1317, and that version is the only thing that can say
whether a stored `doom_elite` means the old key (the Doom Walker line) or the species the
game calls Doom Elite: both names are legitimate now, so the rename is applied to
unversioned files exactly once and never again.

### How the kind was looked for, and the four places it is not

Recorded so the next person does not repeat them:

1. **the leader's march** — `monsterId=0`, `monsterType=0` on every rally on the map;
2. **`GetMonsterData(targetUuid)`** — no data: the monster is outside the loaded part of
   the map, and the bot never looks there;
3. **the trophy's `contentId`** — not a monster: `getLine('lw_monster', <contentId>)`
   answers nil for every one of them. **The «740 config tables know nothing about it»
   written here first is WITHDRAWN**: that sweep called
   `LocalController.instance:getValue(...)`, and `instance` is a GETTER, not a field —
   every one of those 740 answers came off the wrong object. Redone against
   `LocalController.instance()` the monster tables still say nil, so the conclusion
   stands and its evidence does not. Anyone re-opening this: the accessor is
   `LocalController.instance():getLine(table, id)` / `:getValue(table, id, field,
   default)`, and a row comes back as a lazy proxy — `pairs()` on it shows only
   `_xmlId` / `_xmlType`, the columns answer one at a time;
4. **the rally list's own window** — `UIAllianceAutoJoinRally`, opened once and closed
   with `Ctrl:CloseSelf()`. Its view reaches for `MonsterManager`, `GetKillBossNum`,
   `GetMaxKillBossNum` and `ShowRewardList` — a COUNT and a reward, no per-kind
   vocabulary anywhere in its bytecode.

So «who the rally is going for» is drawn from something the view resolves at paint time,
and the counter behind the screen is a single number. Until a reading proves otherwise,
per-kind budgeting has nothing to stand on.

## The game has its own server-side auto-join (#1281 — NOT enabled, not experimented with)

Found while looking for the list above, written down because it is potentially larger
than everything this task built. **Nothing here has been switched on**; a separate task
decides whether it complements our path or replaces it.

| `MsgDefines` name | wire command |
| --- | --- |
| `GetAllianceAutoJoinRallyInfo` | `user.get.auto.join.team.info` |
| `StartAllianceAutoRally` | `user.create.auto.join.team` |
| `StopAllianceAutoRally` | `user.cancel.auto.join.team` |
| `AllianceBossSetAutoRally` | `alliance.boss.set.auto.rally` |
| `RadarRallyGetBossCount` | `get.rally.boss.count` |

The settings window is `UIAllianceAutoJoinRally`; its view calls
`StartAllianceAutoRally` / `StopAllianceAutoRally` off `OnClickAutoJoinBtn`, so the
server joins on the player's behalf and the whole race on the wire — the push, the queue,
the two-call send this task spent a day shortening — may not be needed for the plain case.

What is known about the state: `DataCenter.AllianceBaseDataManager.autoRallyInfo` holds
`{endTime = 0}`, which reads as «the subscription is not running». Asking
`user.get.auto.join.team.info` headlessly succeeded (`ok=true`) and left the field
unchanged, so `endTime` is this account's own subscription rather than a list of rallies,
and the list the window draws comes from somewhere else.


## Where the per-kind split is NOT, checked properly (#1281)

The player says the rally list shows what each banner is going for, so the client has it.
These are the places it turned out not to be, so the next search starts further on:

* **`MonsterManager`, in full** — every field and every method, not just the ones the
  window names: `daily_kill_boss`, `kill_boss_max_num`, `find_monster_max_level`,
  `lastTime`, `whistleRewardNum`, and eleven methods. ONE counter, no per-kind anything.
  It does hold two different CEILINGS, which is a split of a sort and worth knowing:
  `GetCurCanAttackMaxLevel() = 35` for ordinary monsters against
  `GetCurCanAttackBossMaxLevel() = 3` for bosses.
* **the daily quests** — the 23 rows of `DailyTaskManager.dailyQuestTasks` resolved: each
  row's `desc` is a locale id (`daily_quest` table, columns `desc name reward id`), and
  the texts are «Help Allies {1} Times», «Greet Visitors {1} times», «Train {1} units of
  any level», «Gather {0} x {1} at resource tile», «Dispatch Trade Trucks {1} time(s)».
  **Not one of them is about a rally.** Resolve them with
  `python tools/game_locale.py --key <desc>`; the in-game `Localization.GetString`
  returned nil for all of them.
* **`UIAllianceAutoJoinRally`'s own data** — opened once and closed with
  `Ctrl:CloseSelf()`. Its data source is `AllianceBaseDataManager.autoRallyInfo`, which
  held `{endTime = 0}` before and after: that field is this account's own auto-join
  subscription, and it is off, so the window had nothing to draw and nothing to read.
  A list WITH banners in it is what would have to be caught.

## The type IS in the client, and where (#1281)

The player was right and this file was wrong twice over. Corrections first, because both
mistakes were mine and both were method rather than luck:

**`LocalController.instance` is a GETTER, not a field.** Every «no table knows this id»
in this task was asked of the function object. Done properly —
`LocalController.instance():getValue(table, id, field, default)` and `:getLine(table,
id)`, `:hasLine(table, id)` — the answers change completely.

**The trophy's `contentId` IS the monster's config id.** Swept over all 740 tables with
`hasLine`, exactly one answers:

```
lw_world_monster / 1031023  ->  id=1031023  type=7  level=115  name=2901012  desc=2901028
```

So the vocabulary the player sees on screen is `lw_world_monster.type`:

| type | ids | levels | name key | the game's own words |
| --- | --- | --- | --- | --- |
| 7 | 10300xx | 5…150, step 5 | `2901011` | Invading Zombies / Вторгшиеся Зомби |
| 7 | 10310xx | 5…150, step 5 | `2901012` | Zombie Boss / Зомби-Босс |
| 8 | 1040001+ | 100 and up | `monster_boss_name_001` | Doom Walker / Разрушитель |

Resolve a name key with `python tools/game_locale.py --key <id>`; the in-game
`Localization.GetString` answered nil for every one of them.

**Today's rallies, by type, off the trophies:** eleven seen, **all type 7 (Zombie Boss)**
— one at level 110, seven at 115, one each at 120, 125 and 135 — and **not one type 8**.
One kind, all day. Which is also why the player's «the trophy list carries a limit
message for a Doom Elite rally» could not be found in it: every field of every row was
read (`uuid`, `type`, `pointId`, `contentId`, `expireTime`, `rewardList[5]`, and the five
reward items each) and there is no status field — but there was also no Doom Elite rally
to carry one. That check needs a type-8 banner.

### …but the trophy arrives AFTER the fight

`contentId` is paid out with the reward, so it cannot decide whether to send. The list
the player reads the type off is the rally BUBBLE on the world map —
`UIWindowNames.UIAllianceRally`, module `UI.UIAlliance.UIAllianceRally.*`, which is the
marker you tap to join. Its Config and Ctrl carry **`rallyType`**, `world_rally`,
`GetTroop`, `OnClickRally` → `OnClickStartMarch`, and it is positioned by
`WorldToScreenPoint` over the rally's point — so the type is known to the client at the
moment the marker is drawn, before anything is sent.

What is still missing is the link from a rally's `targetUuid` / `targetPos` to that
monster's row: `WorldScene.PointManager:GetMonsterData(targetUuid)` answers nil while the
map around the target is not streamed in, which it is not when the bot never looks there.
The map CAN be made to stream (docs/research — the map sweep sets a zoom and jumps), so
this is a known road rather than an unknown one; it is simply not walked yet.

## «На кого идёт стяг» — the chain, whole (#1281)

```
push.alliance.march.create/refresh          33 fields on the wire
    └─ targetContentId  (== targetUid)      the monster's config id
         └─ lw_world_monster / <id>         LocalController.instance():getValue(...)
              ├─ type   7  → the zombie line      name 2901011 Invading Zombies
              │            │                      name 2901012 Zombie Boss
              │            8  → the Doom line     monster_boss_name_001 Doom Walker
              │                                   («Роковая Элита»)
              └─ level  5…150 in steps of 5
                   └─ python tools/game_locale.py --key <name>   the game's own words
```

**IT IS NOT IN THE CLIENT'S MARCH RECORD, and that is the part worth writing down.**
`WorldMarchDataManager:GetAllMarches()` keeps 25 of the push's 33 fields and
`targetContentId` is not one of them. Read the record through the wrapper's metatable
and it answers to exactly these:

```
uuid teamUuid ownerUid ownerName allianceName allianceAbbr type:userdata status:userdata
targetPos targetUuid startPos homePos serverId targetServer srcServer
startTime endTime createTime curHp power monsterId=0 monsterType=0
fixedSoldierType worldId worldType
```

`monsterId` and `monsterType` are present and **always zero**. `pairs()` on the wrapper
yields nothing and IL2CPP has no reflection metadata (`GetType():GetProperties()` comes
back empty), so the field list can only be built by naming — which is why this took four
wrong turns before the wire was tried.

**So the wire is the only source, and the panel already has it.** `tools/rally_monitor.py`
prints `content=<targetContentId>` on its rally line, the «Ралли» tab remembers
`teamUuid -> contentId`, and the join is handed the map as `targets=«team:id,…»`. The
chunk resolves each one and the run's report says what every squad went for:

```
going_for=[<team>=monster lv115 <team>=doom_elite lv120]
```

Two ways it can still not know, both said rather than assumed: a banner raised before the
panel started listening has no push behind it (counted as `monster`, tallied under
`unclassified=`), and a type nobody has seen lands under `monster_type_<n>` instead of
being folded into an existing key.

### Two dead ends already paid for

* **the rally bubble** `UIWindowNames.UIAllianceRally` carries a `rallyType` — the marker
  the player taps. Not needed once the wire is read, and never compared against
  `lw_world_monster.type`; if anybody wants that comparison it needs a live banner.
* **the target's tile** — `WS.PointManager:GetPointInfo(pointId)` (note: `WS`, found via
  `FIND_WORLD_SCENE`; `WorldScene.PointManager` is nil) answers `false` for a rally's
  target after a jump, and a jump costs 0.14–0.57 s. Not needed either.

## A banner that is still gathering can already be shut (#1281)

The player watched the Marshal event and said it plainly: the list of active rallies is
full of banners **you can no longer enter**, and the auto-join was throwing every squad
it had at one of them. `endTime` cannot see that — it answers «still standing», which is
true and useless here.

### Where the seats are, and where they are not

```
push.alliance.march.create/refresh
    ├─ assemblyMarchMax      how many marches fit          measured live: 5
    ├─ leaderMarch           one march                     ┐ occupancy =
    └─ members[]             the rest                      ┘ 1 + #members
```

`WorldMarchDataManager:GetAllMarches()` keeps **neither** — the same 25-of-33 truncation
that drops `targetContentId`. So the size is wire-only, and the panel learns it exactly
where it learns the target: `tools/rally_monitor.py` prints `slots=<taken>/<max>` on its
rally line, the «Ралли» tab remembers `teamUuid -> taken/max`, and the join is handed the
map as `slots="team:taken/max,…"`.

**Occupancy is the LARGER of the two counts, and that is a correction paid for on the
wire.** This section used to say the opposite — count in the client, ignore the push,
because every member march of a rally IS in `GetAllMarches()` and so the count is current
at the moment of the send rather than as of the last push we happened to hear. It sounds
right and it is not what happens. Over a three-and-a-half-hour window, checked against
the wire rather than against our own log:

```
seats the wire last announced      squads sent    squads that arrived
1                                   1              1
2                                  55             24
3                                  20              6
4                                  16              8
5                                  21              0      <-- not one
never heard                       123             92
```

Twenty-one squads at a banner the wire had already called full, and **not one of them
reached it** — while the client's own count of those same banners still showed a seat.
The two disagree in both directions and each is a floor of the truth: a march the other
side has not told us about is missing from ours, and a member who joined since the last
push is missing from theirs. So the sieve takes the larger, and only a banner both agree
is open stays a candidate. The report names which count shut it —
`banner-full(5/5 by wire)` or `… by client)` — so the next disagreement is visible
instead of being argued about.

### A banner that swallows squads stops being asked

`__lw_rally_shut` empties every run on purpose: a refusal is terminal only while the
banner stands, and a squad that came home deserves a second look. What that cannot see is
a banner asked again and again ACROSS runs. In the same window one banner took
**fourteen** squads and let none of them in, and eighteen banners between them ate 108 of
the 137 sends that reached nothing.

Retrying still earns its keep, and the numbers say exactly how much: of the 114 banners
joined, **97 landed on the first send**, 9 needed a second or a third (six to eleven
seconds later), and one took eight. So the count is kept per banner
(`__lw_rally_tries`), lives only as long as the banner is on the map, is cleared the
moment a march of ours stands in that team, and **the third failure is the last** — which
keeps 8 of those 9 and saves 51 sends that could not have worked. The price is measured
rather than assumed: one join in 114, the eight-send outlier.

### How «did it arrive?» is measured at all

Every number in the sections above and below comes from the WIRE rather than from the
panel's own log, and that distinction is the whole reason they can be trusted: our log
says what was SENT, and this ability spent weeks sending cleanly into nothing. The push
stream says who is standing in each banner, so it is the only thing that can answer
whether a send arrived.

The landing rule, and it has two halves that both matter:

* our name is **absent** from the last `push.alliance.march.*` for that team BEFORE the
  send, and
* **present** in some push at or after it.

Leave the first half out and the count triples: the push our own join causes is
timestamped in the same second as the send line, so a naive «was our name there?» reads
111 successes as duplicate sends to banners we were already in. That mistake was made
once and caught by noticing every «duplicate» had a gap of exactly 0 s.

The player's own name is DERIVED from the data rather than written down — it is the one
name common to the participant lists of every banner a confirmed run sent to — so the
tool carries no account identifier. It is `results/rally1281/wire_truth.py`:

```
python3 results/rally1281/wire_truth.py 02:44 06:19 [profile]
```

### What the window actually says about «not one missed»

158 banners announced on the wire, **114 of them joined** — with three squads, against an
alliance that raises one every eighty seconds. Of the 44 not joined: 37 were sent to and
never entered (29 of those filled to 5 of 5 without us — a race lost, not a miss), and 7
were never sent to at all, each with its reason already in the log: every squad out,
«панель занята другой работой», «занят — дождись завершения». Push to send was **0 s
median, 4 s worst** over 252 measured sends, and no window was opened on the way.

Nine banners sampled on the wire during the event, every one of them:

```
#    max    occupied  currSoldiers
1    5      5         2675
2    5      5         545
…    5      5         …
9    5      5         537
```

A banner whose size was never heard is **not** filtered. An unheard size is not a full
banner, and shutting an open one costs a join for nothing; the refusal below is what
catches those.

### «Мест уже нет» — the key, and what to do about it

The game's own words are key **`390857`** — *«Rally participant full. Unable to join.»*
(`tools/game_locale.py --key 390857`). Its neighbours in the same family are worth
knowing apart: `120210` «The troop is full» is about an army, `dispatch_march_full_1..3`
are about your own march queue, and `ghostrecon_051/069/077` belong to the other event.

It is a **terminal** refusal: nothing about that banner will change while it stands. So
the rule the auto-join follows now, and the rule any future refusal should follow:

* **terminal** (full / gone / not allowed) → drop the target, move to the next one in the
  SAME run;
* **can still change** (a squad on its way, a server that has not answered yet) → wait,
  which is what the join's `WHILE joined < 1` already does.

In the recipe that is: the chunk records where each pass sent
(`__lw_rally_sent_teams`), and if no march of ours appeared, those banners go into
`__lw_rally_shut` and the sieve runs again — the squads that came back are aimed at the
next rallies on the map instead of at the one that just refused them. `__lw_rally_shut`
starts empty every run: a refusal is terminal for the banner, not for ever.

The report names both:

```
no_seat=[<team>:banner-full(5/5) <team>:refused-full]
```

**THE KEY IS NOT WHAT THE HEADLESS SEND SEES, and that is a negative finding worth the
space.** `390857` is what the GAME shows when a person taps a full banner. The join does
not tap anything — it is one `SendCreateMarchMessage` — and the server answers a refused
join of that shape with **silence**. Measured: the recipe reads the client's own message
tip on the failing path (`UIWindowNames.UICommonMessageTip`), and across every failure in
a three-and-a-half-hour window it came back with the same thing:

```
READ_LUA refusal = 'the server said nothing on screen'
```

No key, no tip, no error frame — the send goes out, nothing comes back, and no march
appears. So **the rule cannot be built on the refusal**: what the auto-join actually
stands on is «a squad of ours did not appear in that team within three seconds», and the
tip is read only so that a future refusal which DOES speak is not missed. Anybody who
sets out to match `390857` on this path will find nothing and conclude the code is
broken; it is not, the server simply does not say it to us.

### The run that should never have started

«Не нужно вообще запускать сценарий авторалли, если все отряды заняты — только стек
заполнять понапрасну.» Every banner on the map sends a push, and each one used to raise
a run: a claim on the client, a scenario context, a queue slot behind it — to discover in
its own first chunk that there was nobody to send.

The question is answered before any of that now, by the schedule's own gate
(`Schedule.register_precondition` → `panel/tabs/rally/limits.py::join_precondition`).
Three things make it safe:

* **It is cheap.** Counting the free squads is `state == 0` and `IsFree()` over
  `ArmyFormationList` — measured five times back to back on the live client at
  **0.059 / 0.095 / 0.062 / 0.063 / 0.062 s**. The run it saves costs more than that
  before it sends anything.
* **It is fresh.** Asked at the moment of the decision and never cached: «занят» stops
  being true in seconds, and a cached answer would skip banners for a reason that had
  already expired.
* **It cannot refuse blindly.** No reading, no game, an answer it cannot parse — the run
  goes ahead, and the sieve inside it reports `left=[…:out]` as before.

**An EMPTY squad is not a busy one.** The chunk never looks at `totalSoldierNum`: a squad
with no soldiers is one request away from being full (#1285) and is not a reason to skip
a banner.

The express path had to learn the gate too. «Сразу» skips the queue — and skipped
`_run_queued`, which was the only place a refusal was read; the errand most likely to
carry that flag is this one. The reason is rolled up like any other skip, so it is said
once with a count rather than once per push.

## A squad below its own ceiling is not sent, and the ceiling had to be found (#1281)

Asked for as «нужно проверять, есть ли МАКСИМУМ СОЛДАТ для отряда — если не хватает,
автостяг пропускаем», with the threshold named explicitly: **full means the squad's own
capacity, not whatever happens to be standing in it.**

### Where the ceiling lives, and why it reads nil

`ArmyFormation:GetAllHeroSoldierCapacity()` is a one-line getter: its dump names exactly
one field, `heroTotalSoldierCapacity`. On a headless client that field is **nil**, and
stays nil through `formation.get.soldier`, through `FetchFormationSoldier` and through
`RefreshFormationSoldier` (which throws). Read live on three squads it answered `0`,
while the same three had answered `3123 / 2631 / 2565` an hour earlier.

The way to find out what fills it is not to guess a message — it is to ask which methods
of the class MENTION the field. Dump every function on the metatable's `__index` and grep
the bytecode:

```lua
for k, fn in pairs(getmetatable(f).__index) do
  local ok, d = pcall(string.dump, fn)
  if ok and string.find(d, 'heroTotalSoldierCapacity', 1, true) then … end
end
-- answers: GetAllHeroSoldierCapacity (reads) · ConscriptSoldier (writes)
```

**`ConscriptSoldier` is both halves of the player's instruction.** Its constants are the
whole recipe: `SoldierDataManager.GetInsideSoldiers`, `HeroDataManager.GetHeroByUuid`,
`GetSoldierCapacity`, `DominatorManager`, then `soldiers`, `totalSoldierNum`,
`totalSoldierBurden`, `heroTotalSoldierCapacity`. It draws from the base's pool up to
what the squad's heroes can carry and writes the ceiling on the way. **There is no
`SFSNetwork` and no `MsgDefines` anywhere in it** — it is local, and it costs nothing a
banner cares about.

Measured back to back on the same three squads, one call apart:

```
before  cap = nil      after  cap = 3123.0
before  cap = nil      after  cap = 2631
before  cap = nil      after  cap = 2565
```

3123 is the number the game's own dispatch screen had shown as **«3,123/3,123 units»**
([world-monsters.md](world-monsters.md), finding 10) — so the field is right, it is
merely absent until something computes it. Before this was found the gate could only see
a ceiling on a client whose dispatch screen had been rendered by hand, and it said so on
every run under `ceiling-unknown=[…]` rather than passing the squads in silence.

So the sieve's order is the game's own: **ask for the army → fill → count → compare →
below the ceiling, do not send.** The fill works from the POOL rather than from the
squad, so it does not stand in for `formation.get.soldier` (#1285) and does not replace
the recipe's `todo = -1` path.

### What the fill actually puts in — measured, not assumed

The player said it before the numbers did: «помещается или максимум, или сколько есть в
казармах», and «в интерфейсе я вижу, что отряд НЕ полный». Both halves check out.

**On the ceiling side the identity is exact.** With the barracks holding more than any
squad can carry (8583 against ceilings of 3123 / 2631 / 2565), every squad came out at
`min(ceiling, barracks)` to the soldier:

```
pool=8583
sq=1 filled=3123  ceiling=3123  min(ceiling,pool)=3123  diff=0
sq=2 filled=2631  ceiling=2631  min(ceiling,pool)=2631  diff=0
sq=3 filled=2565  ceiling=2565  min(ceiling,pool)=2565  diff=0
```

**On the barracks side it is `min` less a remainder of one or two.** The same account
earlier, with 1256 soldiers in all, filled its three squads to 1254 / 1255 / 1255 — the
whole pool bar a soldier or two, because the fill is per hero slot and the last few fit
no slot. So the honest statement is «as much as the barracks allows, up to the ceiling»,
and a check written as an exact `==` against `min()` would fail on a full barracks day
out of three. What the person SEES on the squad screen is that number, which is what made
the reading trustworthy: 1254 of 3123 is «отряд НЕ полный», in the game and in the panel.

The panel reads both sides of that `min` for its own reasons — the ceiling to gate on,
the barracks to tell «this squad has not been topped up» from «there are not enough
soldiers to fill one» — and `read_squad_state.md` answers `fits=` per squad and `pool=`
for the base, filling with the SAME `ConscriptSoldier()` call the join uses so the two
can never disagree about what a squad holds.

### Two ways of being under strength, and why they are not one word

The instruction came with its own warning: an account that cannot fill a squad at all
would have the auto-join go quiet **for ever**, and a permanent silence must not read as
an evening with no rallies in it. The data says the warning is today, not hypothetical —
this account owns fewer soldiers than its smallest squad can carry:

```
squad 1   1254 / 3123        base has 1256 soldiers in total
squad 2   1255 / 2631
squad 3   1255 / 2565
```

The fill is working — the squad took 1254 of the 1256 there are. There simply are not
2565 of them. So the report names the two cases apart and the recipe ends on two
different sentences:

| word in `left=[…]` | `todo` | what it means |
|---|---|---|
| `not-full(n/cap)` | `-2` | the base could top this squad up — a chore |
| `short-of-troops(n/cap, base has N)` | `-3` | the base has not got the soldiers to fill ONE squad — a wall |

Both rank BELOW `-1`, so a run holding one squad nobody has asked about still tries the
fetch first; under-strength is only reported when there is nothing left to try. Live, end
to end, from both drivers:

```
report … sent=0 rallies=1 free=0 … left=[1:short-of-troops(1254/3123, base has 1256) …]
READ_LUA todo = -3
IF todo == -3 -> True
  LOG "not sent — there are not enough soldiers in the base to fill a single squad to
       its ceiling … the auto-join will stay quiet until the barracks catches up"
```

**What the person is shown, and where.** The reason is not left in the run's roll-up of
skipped squads: rolled in there a silence lasting days reads as an evening with no
rallies in it. It is a line of its own under the squad strip in the window and a card of
its own on the phone, and it carries every number that can be acted on — the squad, what
it holds, what it takes, what the barracks has, and how many more soldiers make it
fillable. The squad it names is the one with the SMALLEST ceiling: that is the first that
will start joining again, and naming the roomiest would overstate the work.

> В отряде 2 — 1255 из 2565: в казарме всего 1256 солдат, полный не собрать.
> Наберите ещё 1309, и он снова начнёт присоединяться.

### The threshold, and the one line that would move it

**«Полный = вместимость» is what is in the code, and it is the player's decision rather
than a technical one.** Asked for once («нужно проверять, есть ли МАКСИМУМ СОЛДАТ для
отряда»), and confirmed a second time after being shown exactly what it costs
(«Отправлять в стяг только полные отряды» — with the barracks at 1256 against a smallest
ceiling of 2565, i.e. knowing the auto-join would go silent). Nobody may soften it
without being asked to.

This is written down because the alternative WILL come up, and it should take a minute
rather than an afternoon.

**What a fractional threshold is.** Instead of «send only at the ceiling», send at
`share × ceiling` — «not below 80% of what the squad can carry». It is one comparison, in
one place, in `tools/lib/lua_actions.py::rally_join_all`, in the squad sieve:

```lua
-- now
elseif cap > 0 and n < cap then …
-- a fraction instead (0.8 would be the knob, wherever it is read from)
elseif cap > 0 and n < math.ceil(cap * share) then …
```

Everything else already works unchanged: `not-full` / `short-of-troops` keep their
meaning (the second becomes «cannot reach the SHARE», which is the honest wording then),
`todo = -2 / -3` keep theirs, and both front-ends keep drawing `have / fits` — only the
sentence would want «нужно {n} для {share}%» instead of «полный не собрать». A knob would
belong on «Автосбор» beside the squads, saved in the profile's rally block, and mirrored
in `web_view` like every other reading (CLAUDE.md).

**What each choice costs, in the numbers this task measured:**

Both sides of the hard threshold have now been seen live, which is what makes the table
below a measurement rather than a projection. With the barracks at 1256 against ceilings
of 3123 / 2631 / 2565: four runs reached `todo = -3`, twenty-four squad verdicts of
`short-of-troops`, and **not one send**. With the barracks at 8583 and all three squads
full: three runs sent, **three joins confirmed, 3 of 3**, and neither `not-full` nor
`ceiling-unknown` appeared at all.

| threshold | what goes out | what it costs |
|---|---|---|
| `= ceiling` (now) | nothing at all while the barracks is short — 0 joins over the window that had 158 banners | strongest squad in every banner; the auto-join can be silent for days, and says so |
| `≥ 80%` | with 1256 soldiers and ceilings 3123 / 2631 / 2565, still nothing (80% of the smallest is 2052) | the wall moves but does not disappear on a base this far behind |
| `≥ 50%` | all three squads would have gone (1254–1255 against 1283 / 1316 / 1562… squad 3 only) | weaker squads in a rally; a half-strength squad still fills a seat somebody else could have used |
| no threshold (before this task) | everything went | the state the player asked to change |

The middle rows are the point: **a fraction is not a milder version of the same rule, it
is a different rule with a different failure**. At the ceiling the auto-join is silent and
honest; at a fraction it joins with squads the player did not want in a rally, and there
is no reading afterwards that says which banners were fought at half strength. If the
fraction is ever turned on, the report should name it (`not-full(n/cap, share 80%)`) so
that stays visible.

### The soldier floor: one door over the run, because the pool is shared (#1317)

The per-squad ceiling above answers «is THIS squad full». The player then asked the other
question — «наполненность не одного отряда, а всех трёх; если на 3 отряда солдат не
хватает, не присоединяемся» — and it cannot be answered by running the same check over
three squads, because **the soldiers are one pool and every squad draws from it**. Filling
squad 1 to its heroes' ceiling is precisely what leaves nothing for squads 2 and 3; each
of them is «full» only at the expense of the next. The measurements above say the same
thing from the other side: three squads reading 1725 / 1724 / 1725 out of **1727 soldiers
owned in total** — the same soldiers, counted three times.

So the gate is not per squad at all. One number stands in front of the whole run:

| reading | what it is |
|---|---|
| `SoldierDataManager:GetPlayerSoldiersTotalNum()` | soldiers standing in the BASE — it falls when a march leaves and rises when one returns |
| `DataCenter.__lw_rally_min_soldiers` | the floor, parked by the panel off «Автостяг» (`min_soldiers`) |
| `short_pool` | `floor > 0 and pool > 0 and pool < floor` → `todo = -5`, nothing is sent |

Three decisions in it, all the player's, all made with the alternatives on the table:

* **an absolute number rather than a sum of ceilings.** The ceilings move whenever a hero
  is levelled; the number that means something to the person is the one they read off
  their own base. (The other options offered were `pool ≥ Σ ceilings` and a percentage of
  it.)
* **marching soldiers do not count.** The pool is what is home, so once the squads are out
  the door shuts until they come back — one decision per wave rather than three. Said out
  loud when it was chosen: this is what makes «не хватает на три — не цепляемся» literal.
* **the squads it covers are the ticked ones**, and the floor covers them together — a
  banner refused by it is refused for all of them at once.

The rank of `-5` matters. It sits ABOVE `-1` / `-2` / `-3`: fetching an army for a squad
that may not be spent is a call spent on a run that is already refused. It sits BELOW
`-4` (the day's ceiling), because «сегодня всё» is the more final of the two — a base that
fills up an hour later still has nothing to join today.

`pool = 0` is «the reading failed», and then the floor refuses nothing: the same rule the
ceiling follows. Both numbers are in the report whether or not anything was held back
(`soldiers=<pool>/<floor>`), and the panel draws them side by side — the floor as a box,
the pool as a reading fetched on the same background worker that asks for the day's count
(≈0.1 s, «Автостяг», and mirrored on the phone). **The join itself needs no thread for
it**: the pool is read inside the chunk the press was already making.

### The per-kind tally: one write path, and no numbers to check it against yet

Two things play `join_rally` — the schedule's «rally_auto_join» trigger and the «Ралли»
tab's own reader, which raises one for every banner the capture hears. The counting rule
used to live in `panel/runtime/schedule.py`, which exactly ONE of those two passes
through, so every join the tab's driver made went unrecorded: over one live window the
tally recorded 1 join of 13 and `rally_counts.json` read 11 against 13 confirmed.

The rule is now `panel/tabs/rally/limits.py::record_run(rt, ctx)` and both drivers call
it; the schedule's hook is handed the finished context and keeps no opinion of its own
about what a join is worth. One entry per squad the run sent, capped by what the run
confirmed — `joined` is a DIFFERENCE, so a squad the OTHER driver sent that lands
mid-run falls inside both runs' differences and both would record it without the cap. A
run that sent nothing records nothing.

**Confirmed live, and by the driver that used to be invisible.** The barracks grew past
the ceilings the same morning and the joins started again; over the first hour:

```
07:36:46  the tab's own reader   to=[…/s1]  kinds=['monster']  confirmed
07:45:25  the schedule's trigger to=[…/s1]  kinds=['monster']  confirmed
07:50:09  the tab's own reader   to=[…/s1]  kinds=['monster']  confirmed

rally_counts.json   monster 88 -> 91        three joins, three entries
```

**Two of the three came from the tab's driver** — precisely the one whose joins used to
be dropped. Before the fix this window would have recorded 1 of 3, which is the shape the
original complaint had (11 against 13). The other two ways of checking the same thing,
when a bigger window is available: the log's own confirmations, and the game's trophy
list (`tools/dev/rally_trophies.py --check FROM TO`, horizon about an hour).


## Where the 5–7 seconds actually go, second by second (#1301)

«Авторалли отвечает на 5–7 секунде.» The decomposition below is off the live profile's
own logs for 2026-08-08 — 91 create-pushes and the run they each woke — and the answer
is that **almost none of the delay is ours**.

| stage | median | tail |
|---|---|---|
| push crosses the wire → the trigger fires | **0.005 s** | 0.08 s |
| fire → the run starts | 0.26 s | 2.3 / 4.2 / 5.8 / 9.9 / 14.8 s |
| run starts → `SendCreateMarchMessage` | ~0.30 s | stable — one call into the VM |
| **the banner's age when our squad left** | **11.6 s** | p25 8.6 s, max 78 s (30 sends) |

Three things fall out of it, and the first two kill hypotheses that had been carried for
a while:

* **the detection is not a poll and never was.** `rally_auto_join` is a WIRE trigger
  (`push.alliance.march`), so «half a polling period» explains nothing. The handful of
  4 / 17 / 43 s outliers are the listener child being restarted, not a cadence;
* **the DSL costs nothing measurable.** A recipe is parsed once when it is loaded — the
  measurement shows it nowhere. What costs is a round trip into the game VM (~0.15 s, and
  there is exactly ONE before the send since #1281) and waiting on the client. Rewriting
  the recipe «natively» would buy fractions of the 0.3 s and leave the 10 s untouched;
* **the queue was worth removing anyway.** The fire waited a median of 0.26 s but a p90
  of several seconds behind the ordinary schedule, so the trigger now ships
  `immediate=True` — the same flag, for the same reason, that `alliance_help` got in
  #1288.

### The client's own march table is a median of 10 s late

This is the whole of it. Every reading the sieve makes — which banners are out, whose
they are, how full, whether they have arrived — comes off
`DataCenter.WorldMarchDataManager:GetAllMarches()`, and that table does not learn about a
banner when the push announcing it arrives:

| create push → the teamUuid first appears in `GetAllMarches()` | |
|---|---|
| min | 0.08 s |
| p25 | 8.07 s |
| **p50** | **10.34 s** |
| p75 | 19.13 s |
| p90 | 38.03 s |
| max | 62.15 s |

Over 31 banners. And in **23 of the 26 late cases the client noticed within 1.5 s of a
REFRESH push** — that is, only once somebody else had joined the banner and the server
said so again.

One case end to end, entirely in the log:

```
16:19:49.682  push.alliance.march.create      the banner goes up
16:19:50.175  TAP rally_join_all              0.49 s later — as fast as it gets
              sent=0 rallies=0 free=2 seen=0 ours=0        …and there is nothing to join
16:19:57.929  push.alliance.march.refresh     somebody else joins; the client notices
16:19:58.314  TAP rally_join_all → sent=1     banner age at the send: 8.6 s
```

Nothing in that run is slow. It is a correct run against a client that has not been told.

### What the push already carries

Everything the send needs, from the first byte — confirmed against recorded
`push.alliance.march.create` frames:

| field | is |
|---|---|
| `uuid` | the teamUuid (the leader's march uuid plus one) |
| `attackPointId` | **the tile joiners gather on** — the same value as `leaderMarch.startId` and the first leg of `leaderMarch.path` |
| `server` / `nowServer` / `srcServer` | the server |
| `assemblyMarchMax` | the seats (already used, #1281) |
| `targetContentId` | what it is going for (already used, #1281) |

`SendCreateMarchMessage(formation, 6, point, team, 1, 1, false, server, nil)` needs
nothing else. Note **`attackPointId`, not `targetPointId`** — the second is the monster,
and aiming a join at it is the «invalid end point» refusal that cost this ability weeks
(«The wall was the END POINT», above).

So the address travels the way the target and the seat count already do: the monitor
prints `join=<tile>/<server>`, the tab keeps it per teamUuid with the time it was heard,
`join_rally.md` parks it as `points`, and `rally_join_all` offers a wire-only banner as an
extra candidate — in front of the client's, since it is by definition the fresher. A team
the client already lists is skipped and stays the client's; the wire only ever ADDS.

Three guards, each of which has a way of failing quietly without it:

* **a 60 s shelf life** on a heard address. The leader's tile is right only while the
  banner STANDS, and the wire has no `endTime` — a banner gathers for 60 s (`waitTime`
  minus `createTime` on every push measured), and after that the client's table is the
  authority anyway;
* **a round trip on the uuid.** A teamUuid is 19 digits; an integer VM holds it exactly, a
  float rounds it, and a send at a rounded uuid reaches nothing while returning cleanly —
  which is exactly the shape this ability spent weeks in (#1237). The candidate is kept
  only when `tostring(tonumber(t)) == t`;
* **the ordinary filters still apply.** Seats (the wire's own count), a march of ours
  already in that team, and the banners this run has been refused by.

### …and the create push was being thrown away, which made all of it dead code

The mechanism above shipped and then never once fired: over 44 MB of one profile's log,
across dozens of banners, not a single run reported `from_wire=`. The reason is one line
of the monitor, and it is worth writing down because everything else was right.

A banner announces itself twice — `create` when it goes up, `refresh` every time somebody
joins it. **`create` is the whole of the head start**, and in a `create` the leader is
still standing alone, so the game sends his march with `teamUuid = 0`: the seat that
becomes a team has not been filled yet. `RallyMonitor.emit` read the team off the marches,
found a zero, and tagged the line `solo` — and `RallyTab._on_line` needs `team=` to key
anything by, so it dropped the line whole. The address, the seat count and the target of
the freshest banner on the map all went in the bin, and the wire's advantage was spent
waiting for a `refresh` — which only arrives once SOMEBODY ELSE has joined. That is the
same 10 s the client's own table takes, arrived at by a different road.

The uuid was one level up the whole time. Verified over a recorded rally:

| push | `payload.uuid` | `teamUuid` on the marches |
|---|---|---|
| `create` | `<banner>` | `0` (leader alone) |
| `refresh` ×5 | `<banner>` | `<banner>` on every march |

So `_banner_uuid(payload)` takes the marches' team when they have one — that is the value
the rest of the file keys by — and falls back to `payload.uuid`, which is present from the
first frame. A push with neither is still tagged `solo`, as before.

### PROVEN LIVE: the server accepts a join the client has not heard of

One banner, one log, three readings that can only be true together:

```
01:20:01.014  push.alliance.march.create  team=<banner>  participants=1  slots=1/5  join=<tile>/<server>
01:20:01.017  the trigger fires                                     (+0.003 s)
01:20:02.704  the client, asked directly:  rallies = 'no active rallies'
01:20:04.597  the press goes out
01:20:04.742  push.alliance.march.refresh team=<banner> participants=2 [us, the leader]   (+0.145 s)
              report: sent=1 rallies=1 seen=0 ours=0 already_in=0 from_wire=[<banner>]
```

`seen=0` is the whole of it: the client's march table held NOTHING, the address came off
the wire, and the server put our squad in the banner 145 ms after the send. **3.73 s from
the push to standing in the rally**, against a median banner age of 11.6 s before.

Note the create push carries `team=<banner>` — that is the fix below this section
(`_banner_uuid`); before it the same line read `solo` and the panel binned it.

What is left inside those 3.7 s is all panel, and all of it is measurable: 0.45 s the
join spent behind `rally_monitor`, which fires on the same push and got into the queue
first; 1.28 s from «запуск» to `> action`; 1.85 s of the recipe itself (1.08 s parking
the arguments, 0.77 s the press).

### The argument this replaces

**Whether the server accepts a join aimed at a banner the client has not registered.**
Nothing in the protocol suggests it should care — the message carries the team, the tile
and the server, and the server holds the banner regardless of what our client has
rendered — but that is an argument, not a measurement, and this ability has a long
history of arguments that measured wrong. The client was signed out elsewhere while this
was written, so it could not be tried — it was measured two days later, above, and the
argument turned out to be right. It is kept here because the reasoning is what would have
been wrong if the measurement had gone the other way, and because the fallback it names
is still the behaviour a refusal falls back to: the client catches up and the next run
joins, exactly as before.


## Everything this task believed and then disproved (#1281)

A negative result saves the next person a day exactly as often as a positive one, and
this ability produced an unusual number of them — it spent weeks looking like it worked.
Each row below was BELIEVED, acted on, and then killed by a specific measurement; the
measurement is what makes it safe to stop re-deriving.

### «Six joinable banners were held shut by a stale mark»

**Refuted by `endTime`.** The reading was real — `seen=6 ours=6 already_in=0 rallies=0`,
six banners of the alliance and a march of ours in none of them — and the conclusion
(«the join marks outlive the squads and shut open banners») was wrong. Ageing the marks
did not free those banners; it removed an accidental guard. All six had **already
arrived**: the client keeps a resolved rally in its march table with the same `teamUuid`,
the same `type=ASSEMBLY_MARCH` and `status` still saying MOVING, and nothing in the shape
of the entry says it is over. Nine «banners» on the map at one point and every one of
them had been fought, the oldest thirty-two minutes earlier — 54 sends in fifteen
minutes, zero marches, the server dropping every one without a word. `endTime` against
the server clock is the only field that tells them apart.

### «Occupancy is better counted in the client than taken from the push»

**Refuted by the wire, and this doc used to say the opposite in as many words.** The
argument was sound-sounding: every member march of a rally IS in `GetAllMarches()`, so
the count is current at the moment of the send rather than as of the last push we heard.
Measured against the wire over three and a half hours: of **21 squads sent at a banner
the wire had last announced as 5 of 5, not one arrived** — while the client's own count
of those same banners still showed a seat. Both numbers are floors of the truth; the
sieve takes the larger and names which one shut the banner.

### «A trophy lives about an hour»

**Refuted by reading the stamps against the game's own clock.** The figure came from a
delta of 1:01:03–1:02:48 across eight rows and was an artefact of the arithmetic that
produced it: the log's time of day had been pasted onto the trophy's expiry DATE, so what
got measured was two clocks three hours apart rather than an age. Read as absolute stamps
the same eight rows had **98–100 hours** left. The list is not a TTL at all — what empties
it is COLLECTING, and nothing in the schedule collects, which is why it can be used as
evidence.

### «The tally counts joins»

**Refuted twice, by two different miscounts.** First it counted march EVENTS and called
them banners — 304 events against 49 banners. Then, fixed to count banners, it recorded
what a run had merely SEEN rather than what it sent: the second driver's run reported
`joined=1` for a squad the FIRST one had sent, carried no kinds of its own and fell back
to the gate's list, so it counted somebody else's join under whichever kind happened to
be first. Over one live event that read 53 against 34 confirmed joins and 35 trophies.
The rule that survived: one entry per squad THIS run sent, capped by what it confirmed.

### «The ceiling can only be read on a client whose dispatch screen has been rendered»

**Refuted by `ConscriptSoldier`.** It looked settled: `heroTotalSoldierCapacity` was nil
through `formation.get.soldier`, through `FetchFormationSoldier` and through
`RefreshFormationSoldier`, and the one time it had answered was right after a cold
session's first fetch — which lines up neatly with the `canMarch` recompute the real
dispatch render does ([world-monsters.md](world-monsters.md), finding 10). The conclusion
was that the gate could only work with a window open. Dumping every method of the class
and grepping the bytecode for the field name found the writer in one step, and it is
local, sends nothing, and costs nothing.

### «A filled squad is exactly `min(ceiling, barracks)`»

**Refined by the barracks side.** Exact on the ceiling side — three squads, `diff=0`,
with 8583 soldiers against ceilings of 3123 / 2631 / 2565 — and one or two short when the
barracks binds: 1256 soldiers filled three squads to 1254 / 1255 / 1255, because the fill
is per hero slot and the last few soldiers fit no slot. A check written as `== min(...)`
would have been wrong on the very day the rule was written.

### «`push.alliance.march.remove` is the gate that was missing»

**Refuted by counting.** Sends to a banner whose first push was more than ten seconds old
arrived only 8 times in 45, which looked exactly like «the gathering window closes and we
keep firing into it» — and `remove` (1740 of them in one window, `{teamUuid, isCancel}`,
deliberately ignored by `rally_monitor` as carrying no army) was the obvious candidate for
where that window ends. It is not: of 236 checkable sends, **exactly one** went out after
a `remove` for that team. The banner leaves the client's march table at the same moment,
so the sieve had already stopped offering it. The age correlation is explained by the
`arrived` and seat filters instead.

### «`tools/dev/rally_trophies.py --check` can verify any window»

**Bounded by a log that rotates.** It pairs trophies with banners through `debug.log`,
and `debug.log` holds roughly the last hour while `panel.log` reaches back days. A window
older than that answers «0 joins the log confirmed» and looks like a mismatch when it is
simply out of range. Checked 18:00–19:00: trophies 5 / log 5, agreed. 17:00–18:00:
trophies 3 / log 2 — the log undercounted by one.

### «A `{placeholder}` in `LOG` / `FAIL` carries what a later `READ_LUA` wrote»

**Refuted by the DSL's own documentation** (`docs/dsl.md`): substitution happens ONCE,
before the run. `{refusal}` / `{report}` / `{joined}` printed literally, as themselves.
The lines now point at the reading above them, which logs its own value, and a test pins
the behaviour.
