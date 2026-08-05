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
against the four presses and ~4 s the screens cost. The fallback below it did not run.
