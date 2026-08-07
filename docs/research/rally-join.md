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
