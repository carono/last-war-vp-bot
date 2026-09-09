# The science centres: what each is studying, collecting it, and closing it early

What the duel's Wednesday is about (#2662): the account's research queues — «научные
центры» — what each is studying, taking a study that has finished, and spending speed-ups
to close one that is still running. Read live on 2026-09-09 entirely inside the game's own
Lua VM; no capture was needed and nothing was sent to find any of it.

Every id, uuid and name printed below is INVENTED with the shape the live reply had
(`CLAUDE.md`). The shape is the finding; the numbers are somebody's account.

## 1. A science centre is a queue slot

`DataCenter.QueueDataManager.queueDic` holds every queue slot the account has, of every
kind, and research is `NewQueueType.Science == 6` (the same table
[`ready-buildings.md`](ready-buildings.md) describes for buildings). One slot per centre
the account has unlocked — three on the account this was read against, and
`ScienceManager:HasExtraQueue()` / `HasUnlockSecondQueue()` are how the client itself
asks whether there is more than one.

```
{type=6, qid=1, state=2, itemId=70010000, funcUuid=1000000000000001,
 startTime=1780000000000, endTime=1780003600000, uuid=1000000000000002}
{type=6, qid=2, state=3, itemId=70020000, funcUuid=…, endTime=…, uuid=…}
{type=6, qid=3, state=0, itemId='',       funcUuid=0,  endTime=0,  uuid=…}
```

**The difference from a build slot is the whole reason the two speed-up messages exist:**

* a BUILD slot's `itemId` is the BUILDING's uuid and the slot names the building;
* a SCIENCE slot's `itemId` is the **science id**, and the slot names **itself** in
  `uuid`. Everything that acts on it — the speed-up, the claim — is addressed by that
  `uuid`.

`state` walks `Free (0) → Work (2) → Finish (3)`, and — exactly as with the build queue —
**a slot whose `endTime` has passed counts as finished whatever its `state` says**: the
flip is the client's own and the client can be behind. `qid` is the centre's own number
and is what the list is sorted by, so the rows do not shuffle between two readings.

## 2. What a study calls itself

`DataCenter.ScienceManager`, asked with the slot's `itemId`:

| call | answer |
|---|---|
| `GetScienceName(sid)` | the name in the CLIENT's language — `Fatal Strike III` |
| `GetScienceTemplate(sid)` | the template row of the level being researched |
| `GetScienceLevel(sid)` | the level already owned (`0` for a first research) |

The template row is the useful one:

```
{id=70010001, science_id=70010000, level=1, max_level=5, icon='science_icon01',
 name=211175, description=tech_desc_05_04, power=19500, tab=7, time=3470820, …}
```

* `level` is the level being studied and `max_level` the ceiling.
* `icon` is a sprite STEM, and it is **not** in the extracted item tree on this machine
  (`results/item_icons/item/` holds `icon_item_*`, no `science_icon*`). So the panel's
  rows draw with no picture rather than with somebody else's — `panel/tabs/vs.py`
  resolves the stem through `item_icons.raw_named` and simply omits the icon when it is
  not there. Extracting the science atlas would light them all up and change no code.
* `name` and `description` are KEYS into the game's own translation tables
  ([`game-locale-tables.md`](game-locale-tables.md)), which is why the name is asked of
  `GetScienceName` instead: the client resolves it in its own language, and the panel
  translates it through `panel/runtime/game_words.py` like every other game word.

The eighteen TABS these technologies are grouped into are a separate finding —
[`tech-center-tabs.md`](tech-center-tabs.md).

## 3. Taking a finished study

`MsgDefines.QueueFinish = queue.finish`, and the message class names exactly one field:

```
Net.Msgs.QueueFinishMessage  -> OnCreate(self, param), param = {uuid}
```

— the QUEUE's own uuid. There is no `SendQueueFinish` helper on `ScienceManager`
(`CheckResearchFinish` and `CheckResearchFinishByBuildUuid` are checks, and the lesson of
#2641 is that a `Check…` is not a send), so the recipe sends the message itself, scheduled
with `TimerManager:DelayInvoke` rather than called on the hijack thread.

`MsgDefines.QueueFinishBatch = queue.finish.batch` takes `(queueList, paraState)` and is
what the client's own «collect all» button uses. It is deliberately NOT used: one send per
centre is at most three sends, and a single reply per claim is what makes a refusal
readable.

**The proof is the reply.** `queue.finish` comes back either as an ordinary answer or
carrying an `errorMsg`; the queue cannot be the proof, for the reason it could not be for
buildings — the client's copy of it lags. Measured: the claim answered in about two
seconds and the client had already freed the slot by the time the recipe looked, which is
why `collect_research.md` reports «slots freed: 0» and still counts the claim as taken.

Live: one finished study claimed, `studies collected: 1 of 1`.

## 4. Closing a study early

`MsgDefines.QueueCcdMNew = queue.ccd.m.new`, `param = {qUUID, itemIDs, useGold}` — the
message EVERY non-build queue uses (`arms-race.md` §the four sends). `itemIDs` is the
game's own `"<itemId>;<count>"` string, one send per denomination, `useGold` false and the
gold-for-time argument `0`.

The parcel is chosen exactly as the arms race and the construction one choose theirs:
**specialised research speed-ups before universal, small denominations before large**, the
last piece allowed to overshoot because a study is not closed by a parcel that stops short
of it. The kind is `speedUpType` — `6` research, `1` universal — and, when a freshly
started client has not filled that field in yet, the item id: `2002<family><size>`,
`200200…` universal and `200220…` research.

`read_research_queues.md` prices every running centre for the page, walking the bag DOWN
as the earlier slot takes from it so two centres are never priced against the same piece;
`speedup_research.md` works the parcel out again for itself at the moment of the press,
because a plan a person read a minute ago is a plan the clock has already moved.

**It is an irreversible spend and it is never automatic**: the price is on the row, the
button asks, and a bag that falls short spends nothing at all.

## 5. What announces a change

Three, and none of them is a clock:

* `push.queue.add` / `push.queue.del` — a slot appeared or went away, which is what
  STARTING a research and COLLECTING one look like on the wire;
* `push.science.change` — the account's technology itself moved.

Together with the alarm on the earliest slot's own `endTime`, that is the whole of how the
panel's Wednesday page stays right without asking the game anything
(`CLAUDE.md`, «Read once, then LISTEN»).

## 6. What uses it

* `src/lastwar_bot/actions/read_research_queues.md` — the reading, prices included.
* `src/lastwar_bot/actions/collect_research.md` — taking what has finished.
* `src/lastwar_bot/actions/speedup_research.md` — closing one outright, one at a time.
* `panel/tabs/vs.py` — Wednesday's «Научные центры» block behind the day's gear.
