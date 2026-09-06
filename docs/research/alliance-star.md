# «Звезда альянса» — the weekly ceremony, its likes and its two chests

Task #2584. Everything below was read off a live client on Sunday 2026-09-06, edition 69
of the ceremony. Every identifier in the examples is invented and of the same shape as
the real one.

## What the event is

Once a week the alliance duel is totted up and the game holds a **ceremony**: fourteen
categories, three nominees in each, one of them the **star**. A member may give each star
a **like**, and the likes pay **two chests** — one for having liked (its tiers are
`GetRewardSetting()`), one for taking part. Both are free: no diamonds, no quota shared
with anybody, nothing that expires unclaimed inside the week.

Nothing has to be opened to do any of it. The ceremony has a scene of its own
(`Scene.AllianceStarCeremony.*`) and the panel never enters it.

## Where it lives

`DataCenter.AllianceStarManager`, with `DataCenter.AllianceStar.*` for the rows and
`Net.Msgs.AllianceStar.*` for the messages.

| field | what it is |
|---|---|
| `hasCeremony` | true while there is a ceremony to act on. `nil` until asked |
| `ceremonyEdition` | which ceremony this is — the argument the like board is asked for |
| `endTime` | server milliseconds; judge with `tools/lib/game_clock.py`, never the PC's clock |
| `ceremonyThumbs[configId]` | the board: one list per category, each row `{configId, uid, isStar, thumbsInfo, selfThumbs}` |
| `ceremonyInfo` | the stage being played — `stateId`, `configId`, `nominatePlayerInfoList`, `ceremonyInfoList` |
| `ceremonyFullData` | `participateReceive`, `scratchClaimed`, `allianceDuelWeekScore`, `emojiThumbsRewardInfo` |
| `GetEmojiThumbsRewardInfo()` | `{count, claimedIndex, canReward}` — the like chest's tiers |

`thumbsInfo` is `emojiIndex -> how many likes that face has been given`, and `selfThumbs`
is the same map for OUR OWN likes — which is the gate «уже поставлено», read off the
server rather than counted here.

## The wire

Read off the client's own message classes by handing the send a recording stand-in for
its `SFSObject` and aborting in `ToBinary`, so nothing was ever sent to find this out:

| command | fields |
|---|---|
| `alliance.star.gain.activity.info.new` | none — «is there a ceremony» |
| `alliance.star.gain.ceremony.info.new` | none — the ceremony and its stage |
| `alliance.star.gain.thumbs.up` | `PutInt edition`, `PutUtfString extParams` — the board of likes |
| `alliance.star.thumbs.up.new` | `PutInt configId`, `PutUtfString targetUid`, `PutInt thumbsIndexId`, `PutInt type` — **A LIKE** |
| `alliance.star.ceremony.quest.emoji.reward.new` | none — the chest the likes earned |
| `alliance.star.ceremony.quest.reward.new` | none — the chest for taking part |
| `push.alliance.star.ceremony.info` | the announcement the panel listens on |
| `push.alliance.star.thumbs.up.info.change.new` | somebody's like landed, ours included |

```lua
-- one like: category, the star of it, which of the five faces, and the kind
SFSNetwork.SendMessage('alliance.star.thumbs.up.new', 30000, "1000000000000001", 1, 1)
```

Proven live: `thumbsInfo[1]` went 68 → 69, `selfThumbs` became `{1 = 1}`, and the reply
carried `emojiThumbsRewardInfo = {count = 1, canReward = true, claimedIndex = 0}`.

**Thirteen likes in ONE Lua chunk all landed** — no pacing was needed, and `emojiSetting`
(`numInterval {1, 6}`, `sendInterval {1, 3}`) turned out to describe the ceremony's own
face-spamming panel rather than a rate limit on this. So the loop is inside the game and
the recipe pays one round trip for the lot.

## The two chests, and how each says it is taken

* **The like chest** — `alliance.star.ceremony.quest.emoji.reward.new`, claimed one tier
  at a time. The first claim answered with the item it paid; when there is nothing left
  `canReward` is false and `GetEmojiThumbsRewardInfo()` returns nothing at all, so a
  `nil` reads exactly like a «no» and the loop ends either way.
* **The taking-part chest** — `alliance.star.ceremony.quest.reward.new`, whose reply is
  `participateReceive = true`. That flag is the gate.

## What was NOT done, and why it is written down

* **`alliance.star.gain.scratch.reward`** — a scratch card, `ceremonyFullData.scratchClaimed`
  beside it and `TryOpenScratchCardPanel` / `MarkScratchClaimed` around it. It looks free,
  it is a third reward rather than one of the two the person asked for, and the client
  reaches it through a panel — so it was left alone rather than sent blind.
* **`alliance.star.request.enter` / `EnterCeremonyScene`** — attending the ceremony as a
  scene. Not needed for either chest: the taking-part one was claimed with no scene at all.
* **The score chest** (`GetScoreRewardByScore(allianceDuelWeekScore)`) pays out of the
  duel's own week and has no claim of its own on this route.

## What the panel does with it

| piece | where |
|---|---|
| the ability | `src/lastwar_bot/actions/work_alliance_star.md` |
| the reading | four fields of `read_daily_checklist.md` — `alstar_open`, `alstar_stars`, `alstar_liked`, `alstar_chests` |
| the card's line | `panel/runtime/errand_stats.py::_alliance_star` |
| the ear | the `alliance_star_ceremony` trigger on `push.alliance.star.ceremony.info` |
| the errand | «Таймеры» → `work_alliance_star`, Sunday only (`Timer.weekdays`) |
