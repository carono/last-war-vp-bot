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
| `targetPos` | targetPointId (the join's point argument) |
| `serverId`  | target server                            |
| `ownerName` | player name (carries tags, e.g. `8888 Rock 8888`) |

`GetAllMarches()` returns **both sides** of a war; there is no reliable friend/foe field on the
march, so "joinable" = "led by an alliance-mate". Join is validated after the fact (a new own
march appears) rather than pre-filtered.

## Join

Wire command: `world.march.formation.new`. Sent by:

```
MarchUtil.SendCreateMarchMessage(formationUuid, 6, targetPointId, teamUuid, 1, 1, false, server, nil)
```

`6` = rally target type. Joining an EXISTING rally = this call with the rally's non-zero
`teamUuid`. Re-joining a rally you are already in is suppressed client-side (no second message).

**Choosing the squad:** the first argument (`formationUuid`) is which squad is sent. Squads
live in `DataCenter.ArmyFormationDataManager.ArmyFormationList` keyed by uuid; each has
`index` = the squad slot the player sees (1/2/3). So squad selection = pass the uuid whose
`index` is the wanted slot (`rally_join.py --squad N`, or `--list-squads` to see them). The
march object does not expose its formation back, so which squad was sent is confirmed visually.

**Cold-formation wall:** the send silently no-ops unless a formation is loaded
(`ArmyFormationDataManager.ArmyFormationList[*].totalSoldierNum > 0`). Formations start cold
(soldiers=0). `MarchUtil.OnClickStartMarch(6, targetPointId, teamUuid, -1, 1, 7, server, 0, 0)` —
the game's «в поход» entry — warms them (0 → 3123 verified), **but it opens the dispatch panel**,
so close it afterwards with `GoToUtil.CloseAllWindows()` (the same close the game runs in this
flow; not `DestroyAllWindow`, which kills the HUD). If a formation is already warm, skip
OnClickStartMarch entirely and the join opens no UI at all.

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
rally_join.py --leader <name|mask> --me NAME  # resolve + join a leader's rally
rally_join.py --team T --point P --server S   # join by explicit params
rally_join.py --cancel --leader <name|mask> --me NAME   # leave (auto-resolves memberUuid)
rally_join.py --cancel --team T --member M
```

`--me` / `--leader` match names as a case-insensitive substring (handles tag-wrapped names like
`8888 Rock 8888`).
