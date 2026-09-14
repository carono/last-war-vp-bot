# «Мировой поход» / Global Expedition — the season's four-zone expedition

Reconnaissance and live measurements for task #2852, taken on 2026-09-14 against a live
account. Everything below was read out of the running client's Lua VM through the panel's
web API; nothing here comes from a capture or from guessing at pixels.

## What it is

A season event played in the **«База мирового похода»** (`season_tower_building_name10261000`
— *Global Expedition Base*, building id `10261000`). The game's own rules, quoted from
`season_tower_info`:

> 1. Each Global Expedition round lasts for **14 days**. Each round contains **4 areas**,
>    which unlock on Days 1, 3, 5 and 7 of the round.
> 2. After an area is unlocked, Commanders can progress through stages via **Challenge**
>    or **Auto-Battle**. Each cleared stage grants 1 point.
> 3. When Area Points and Total Points reach the required thresholds, you can claim
>    generous rewards from Stage Rewards.
> …
> 6. Global Expedition is a season event held over three rounds, which open in Weeks 1, 3
>    and 5 after the season begins.

**Nothing is rationed.** There is no attempt counter, no stamina cost and no item spent:
the auto challenge climbs the stages until the lineup loses one, and that is the whole of
the price. That is why the panel's errand ships switched ON (`CLAUDE.md`, «A new ability
ships SWITCHED ON»).

**Losing is the ordinary end of a day.** The player's own words — «пытаться проходить
нужно каждый день, даже если упёрлись в сильного соперника» — are what the event is: the
wall stays where it is until the account grows, so the press is repeated daily and a day
that cleared nothing is a result rather than a fault.

## Where it lives in the client

| Thing | Where |
|---|---|
| Manager | `DataCenter.LWSeasonTowerManager` |
| Config | `SeasonTowerConfig` — `BattleType = {Battle = 0, Sweep = 1}`, `RewardType = {Group = 1, Stage = 2}`, `RewardState = {CanReceive = 0, NoComplete = 1, Received = 2}` |
| The four zones | `M.stageList[1..4]` — `stageId`, `floor` (stages cleared), `openTime` (ms) |
| The round | `M.startTime` / `M.endTime` (ms). Fourteen days apart |
| The score | `M.score`, `M.nextScore` |
| Lineup | `M:GetFormation(stageId)` — `heroes` is `{heroUuid = slot}`, `localIndexToHeroDic` is `{slot = heroUuid}` |
| Save a lineup | `M:SaveFormation(stageId, chipSetId, heroes)` → `season.tower.save.formation` |
| Press a challenge | `M:Battle(stageId, battleType, heroes)` → `season.tower.battle` |
| Rewards of a zone | `M:GetStageScoreRewards(index)` — rows of `{stageId, received, template = {floor, rewardId}}` |
| Rewards of the score | `M:GetGroupScoreRewards()` — rows of `{stageId = -1, received, template = {score, rewardId, titleId}}` |
| Claim | `M:ClaimReward(stageId)` → `season.tower.reward`; `-1` claims the score tiers |
| Anything to claim | `M:HasRewardToClaim(index)` per zone, `M:HasAnyRewardToClaim()` for all |
| The safe | `M:IsHasClaimSafeBoxReward()`, `M:SendClaimSafeBoxRewardMessage()` → `season.tower.box.award` |
| Re-ask the server | `M:RequestSeasonInfo()` → `season.tower.info` |
| A zone unlocking | `push.season.tower.open` |

`heroes` is an **array of `{heroUuid = …, index = …}`** in both messages. That shape was
not guessed: the message's `OnCreate` was handed a table of proxies whose `__index`
recorded every key it read, and it read exactly `heroUuid` and `index`.

## The lineup

The player's instruction was «герои из первого отряда + питомец если есть», and the game
agrees: the lineup the account already had in zones 1 and 2 was, uuid for uuid, the five
heroes of **squad 1** (`ArmyFormationDataManager:GetHeroUuidListInSquad(1)`) plus the same
`dominatorUuid` («Повелитель», the game's own word — there is no separate «питомец» term
in the tables).

**Nothing is taken out of the base.** The expedition's formation is one of its own:
`buildingUuid = 0`, `canMarch = false`, no soldiers. The heroes go on defending the base
and riding rallies while they clear stages here.

**The Overlord is the one thing that does NOT travel headless.** Neither
`season.tower.save.formation` nor `season.tower.battle` carries a dominator field — proven
by catching both messages' parameters — and a zone whose lineup was saved from the panel
comes back with `dominatorUuid = nil` while zones set up by hand in the game keep theirs.
The recipe attaches it locally (`formation:SetLocalDominator`), which is all the client
offers; a zone that must have the Overlord on it wants one touch in the game's own window,
once per round. **The sweep works either way** — measured below.

## What one press does — measured live

Zone 3 (`60223`) had just unlocked, `floor = 0`, no lineup:

    SaveFormation(60223, 1, <squad 1's five heroes>)   → lineup set
    Battle(60223, 1, heroes)                           → floor 0 → 352, score 860 → 1212

Then zones 1 and 2, both long since played:

    Battle(60221, 1, heroes)   → floor 461 → 466
    Battle(60222, 1, heroes)   → floor 399 → 399   (the wall — nothing cleared, no error)

Then the rewards, both kinds:

    ClaimReward(60223)   → 35 rows of that zone went CanReceive → Received
    ClaimReward(-1)      → 7 rows of the score tiers went the same way

Every one of those is a single message. No window was opened, no pixel was read.

## What the panel does with it

* **The reading** — `actions/read_world_expedition.md`. One VM round trip; leaves a flat
  line (`known`, `open`, `zones`, `live`, `unset`, `rewards`, `score`, `ends`,
  `next_zone`, and `oN`/`fN`/`hN`/`rN` per zone).
* **The ear** — `panel/runtime/expedition_live.py`. The reading is taken when the client
  gets into the game (`bus.GAME_READY`), when a zone unlocks (`push.season.tower.open`),
  when the season's own record arrives, and on the way out of every run of the errand.
  **Nothing ticks**, and the card draws the age of its reading.
* **The ability** — `actions/world_expedition.md`, which calls
  `world_expedition_lineup.md`, `world_expedition_sweep.md` and
  `collect_world_expedition_rewards.md` in that order.
* **The card** — the errand `world_expedition` on «Таймеры», daily, switched ON, with the
  line under it drawn by `panel/runtime/errand_stats.py::_expedition`. Its manual press is
  the card's own «Выполнить».

## What was NOT done, and why

* **The safe** (`season.tower.box.award`) is only asked for once the round's own end time
  has passed — the game fills it at the season's settlement and there is nothing in it on
  an ordinary day.
* **The rankings** (`season.tower.rank`) are read by nobody: they pay out by mail when the
  round settles, and nothing has to be pressed for them.
* **The tactics-card buff** (`season_tower_card_buff_*`) is a property of the account, not
  something the expedition can be made to spend or claim.
