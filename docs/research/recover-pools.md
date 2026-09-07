# «Вернуть» — the rewards a secret task or a trade truck never delivered

Both windows the person named carry a button called «Вернуть» — the command post's hero
dispatch and the trade station's departure — and behind the two of them is ONE manager
with two lists of the same shape. Task #2605; the ability is part of
`actions/collect_secret_tasks.md` (the tasks' half) and `actions/send_trucks.md` (the
trucks'), because neither is worth an errand of its own: each is two presses on the way
past, and each belongs beside the income it completes.

## What lands in it

A day's worth of what was earned and nobody took. A secret task that finished while
nobody was collecting, a truck that came home to an empty station — at the day's end the
server sweeps them into a pool, one pool per server day, and holds it for a few days
before it is gone for good. Nothing is lost by not looking TODAY; everything is lost by
not looking this week.

That is why it is folded into the two collecting abilities rather than left to a person:
the pools expire quietly, and a panel that empties the station every few hours is exactly
what should be emptying them too.

## The manager

`DataCenter.DispatchRecoverManager` — one object, both halves, and the only place in the
client where either is answered. `UIDispatchTaskRecover` and `UITrainRecover` are its two
windows; neither is opened by anything here.

| call | what it answers |
|---|---|
| `dispatchRecoverList` / `trainRecoverList` | the pools, keyed by `customId` — the day's own stamp |
| `IsDispatchRecoverOpen()` / `IsTrainRecoverOpen()` | whether the account has the feature at all |
| `IsDispatchRecoverBtnShow()` / `IsTrainRecoverBtnShow()` | whether the window would draw the button |
| `HasDispatchRecoverContent()` / `HasTrainRecoverContent()` | there is a pool of some sort, claimed or not |
| `HasUnclaimedTrainRecoverReward()` | …and the trucks' half of it, unclaimed only. There is no `HasUnclaimedDispatch…`: count the rows |
| `RequestRecoverListsBySwitch()` / `RequestDispatchRecoverList()` / `RequestTrainRecoverList()` | ask the server for fresh lists — what the window sends when it opens |
| `ClaimDispatchRecoverReward(customId)` / `ClaimTrainRecoverReward(customId)` | **the «Вернуть» press**, one pool per send |
| `GetDispatchRecoverCostStr()` / `GetTrainRecoverCostStr()` | what a claim costs |
| `dispatchRecoverLog` / `trainRecoverLog` | the book of what each day's pool was made of — a hundred rows deep, and read by nothing here |

### A row

```
{customId = <the server day, in ms>, createTime = <ms>, dayNum = 1, totalNum = 8,
 state = 1,                                   -- ABSENT until it is claimed
 totalReward = {[1] = {type = 7, value = …}, …}}          -- the tasks' half
{customId = …, dayNum = 1, totalNum = 5,
 curRewardArr = {…}, fullRewardArr = {…}}                 -- the trucks' half
```

**`state` is the whole verdict.** A pool that has never been claimed has no `state` field
at all; a claimed one comes back with `state = 1`. That is what both recipes count, and it
is why they ask for the list a second time instead of believing the send — #2585 is the
run that reported success while putting nothing on the wire, and a count that only ever
looks at what was SENT would have repeated it exactly.

### The frame

Recorded with the SENDING LAYER stubbed rather than the sender (#2598): `SFSNetwork.SendMessage`
was replaced by a recorder for the length of the call and put back immediately, so the
manager's own method ran whole and nothing left the client.

```
dispatch.recover.reward, <customId>
train.recover.reward,    <customId>
```

Exactly one field wide, on both. `MsgDefines` also carries `…RecoverRewardList` and
`…RecoverRewardLog` — the two requests — and there is **no batch**: a claim is one pool,
so the press walks the unclaimed rows and sends one message each.

## It costs nothing

`GetDispatchRecoverCostStr()` and `GetTrainRecoverCostStr()` both answer **0**, asked bare,
by row and by `customId`, on both accounts measured. It is income that was earned already
and never collected, so there is no budget gate in front of it and nothing to refuse —
which is what makes it safe to fold into an ability that is otherwise careful about every
press it makes.

## Measured live (#2605)

Two accounts, and they were in opposite states, which is the useful part:

| | pools of secret tasks | pools of trucks |
|---|---|---|
| the first account | 0 (the list is empty) | 1, already claimed → 0 unclaimed |
| the second account | 7 rows, **1 unclaimed** | 7 rows, **4 unclaimed** |

The claims: one truck pool by hand first (4 → 3, and the row came back with `state = 1`),
then the finished ability over the rest — `rec_trucks before=3 sent=3`, and the list read
again said **3 waiting, 0 still unclaimed**, with 0 trade contracts spent on the run.
The tasks' half the same way: `rec_tasks before=1 sent=1`, **1 waiting, 0 still unclaimed**.

## Where the number is drawn

`read_daily_checklist.md` reads `recover_tasks` and `recover_trucks` off the list the
client ALREADY holds — no request, because a reading must not cost a question (`CLAUDE.md`,
«Read once, then LISTEN»). The claim itself asks for a fresh list, inside the run that is
about to press.

A closed feature answers a DASH and never a 0: «nothing to take» and «this account cannot
take anything» must not draw alike, which is the trap the locked trade station already set
once ([`truck-dispatch.md`](truck-dispatch.md)).

Both cards on «Таймеры» — «Отправка грузовиков» and «Секретки за день» — gain
«возвращённых N» beside what they already say (`panel/runtime/errand_stats.py`), and only
when it is not zero: a permanent «возвращённых 0» is noise on every card every day.
`tests/test_recover_pools.py` and `tests/test_panel_errand_stats.py` hold both halves.

## What was NOT worked out

* **`dayNum` / `totalNum`.** Every row measured had `dayNum = 1` and a `totalNum` between
  1 and 9, so `totalNum` is most likely how many things went into that day's pool. Nothing
  here reads either, and nothing needs to.
* **`curRewardArr` vs `fullRewardArr`** on the trucks' rows — the first is about two thirds
  of the second on every row seen. There is a `multiple` field in the LOG entries beside a
  `costReward`, which suggests a paid way of taking the full one. Not touched: the free
  claim is what the ability makes, and anything with a `costReward` on it is a different
  conversation.
