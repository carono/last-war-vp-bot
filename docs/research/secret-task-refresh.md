# Refreshing the day's own secret tasks, and sending every squad at once (#1902, #1903)

The Secret Command Post has a fourth thing behind it that the panel could not do: the
player's OWN tasks. Nine of them, four out on errands and five standing idle on the
reading this was written from; the idle ones can be re-rolled for a price, lifted to UR
in one press for a bigger price, and sent out all together in one message.

Everything below was read off the live client. Two of the three prices were not what
they were assumed to be, and one of the getters that looks like a price is an item id —
which is the whole reason this file exists.

## What the two commands are

| what | message | payload |
|---|---|---|
| refresh (ordinary and mega) | `hero.dispatch.refresh` — `MsgDefines.DispatchTaskRefresh` | `PutInt costType`, `PutInt isSuper` |
| send every squad | `hero.dispatch.batch.start` — `MsgDefines.DispatchBatchStart` | `PutSFSArray "list"` of `{uuid: long, heroList: LongArray}` |

Nearby, and not used here: `hero.dispatch.batch.reward` (`PutLongArray "uuidList"` — the
rewards in one press) and `hero.dispatch.list` / `hero.dispatch.alliance.list`, which are
the reads.

The batch send is pressed out of `UIDispatchTaskSuperPopupView:OnConfirmBtnClick`, which
gates on `SeasonUtil.IsInLandlordActAndOnCenterServer` and `LuaEntry.Player:IsInBlackRange`
first and, after the send, closes itself and moves the world camera to the tasks' point
(`SceneUtils.CheckCanGotoWorld` + `GoToUtil.MoveToWorldPoint`). The camera move is the
button's own doing and cannot be prevented from outside it.

## The prices, measured

```
GetDispatchSetting('refresh_item')   1520002      the item an ordinary refresh is paid in
GetTaskRefreshSetting()              100          diamonds, when the items have run out
GetTaskSuperRefreshSetting()         1520002      NOT a price — the same item id again
CheckSuperRefreshOpen()              true
```

The window says the rest of it. `refreshBtn` carries `item/itemCount = "<have>/<cost>"` —
live, `"21/1"`: twenty-one «Секретных приказов» in the bag, one per refresh. The mega
refresh's price is **only drawn**, in the confirm dialog its own button raises:

```
UIDispatchTaskRefreshConfirm
  panel/bg/txtTitle   «Мега-напоминание об обновлении»
  panel/bg/TipText    «Это мегаобновление улучшит <b>5</b> ваших секретных заданий
                       с не UR до UR редкости…»
  panel/bg/CostTitle  «Это обновление стоит»
  …/item_1/clickBtn/NameText  «Секретный приказ»
  …/item_1/clickBtn/NumText   20            ← a legacy UI Text, not a TMP one
```

Five idle non-UR tasks, twenty orders: **about four orders per task**, so the price
appears to scale with what it would improve. At three tasks that is twelve orders, and
twelve orders at the diamond rate of 100 is 1 200 — which is exactly the number the
operator quoted for a mega refresh, from the other side. One measurement, so it is a
reading and not yet a law; the recipe never assumes it, because it reads the dialog.

**`GetTaskSuperRefreshSetting()` answering `1520002` is the trap this file is for.** It
is the same number `GetDispatchSetting('refresh_item')` gives, i.e. an item id, and
reading it as diamonds is how a plan comes to spend a million and a half of them.

## Why the presses go through the game's own buttons

`costType` decides whether a refresh is paid for with the item or with diamonds, and its
values are written down nowhere that can be read from the VM. Building the frame by hand
is therefore a guess between two currencies, and the player pays for the wrong guess.
The window's button already knows which of the two the player can afford — it spends an
order while there is one and raises a cost dialog when there is not — and the batch
dispatch's popup arrives with a squad already chosen for every task, which is the one
part a hand-built frame would have to invent.

So the ability presses `refreshBtn`, `superRefreshBtn` + its dialog's `ConfirmBtn`, and
`superDispatchBtn` + its popup's confirm, all through `Button.onClick:Invoke()` on the
transform found by name under the window's root. Reading stays headless.

## Reading the state without a window

```lua
local M = DataCenter.ActDispatchTaskDataManager
for _, v in pairs(M:GetAllSingleTasks()) do
    v.cfg:getValue('color')     -- 5 = UR (the four running ones), 3 = below it
    v.cfg:getValue('level')     -- 7, and `task_star` says the same
    v.cfg:getValue('is_special')-- the star
    v.completionTime            -- > 0 while a squad is out on it
end
M:GetSingleTaskIngCount()       -- 4 live
M:GetSingleTaskNormalCount()    -- 5 live
M:GetMaxMarch()                 -- 9.0 live (a float)
```

The orders in the bag are `DataCenter.ItemData.ItemInfos` summed over the stacks whose
`itemId` is `refresh_item` (docs/research/inventory.md); the diamonds are
`LuaEntry.Player.gold`. There is no `BagDataManager` and no `GetItemNum` on this client.

## `tonumber` is not safe here, and it fails silently

Measured while the price above kept reading zero:

```
local v = M:GetTaskRefreshSetting()   -- 100, type(v) == 'number'
tonumber(v)                           -- raises: bad argument #1 to 'tonumber'
                                      --         (string expected, got number)
```

The game hardens `tonumber` against non-strings. Every read in the panel's Lua lives
inside a `pcall`, so the raise is **silent**: the local keeps its default and the recipe
reports «price 0» — «free» — about a press that costs diamonds. Values the panel parked
itself (plain Lua numbers) go through `tonumber` unharmed; values coming back from the
game do not. `lua_actions._NUM` is the answer: `v + 0` first, `tonumber` only as the
fallback for a genuine string.

## What the panel does with it

One scenario, `actions/refresh_secret_tasks.md`, holds the rule and every press; the
reading half is `actions/read_secret_post.md`. The rule the operator gave, in their own
words, is «spend orders while there are orders; when they run out spend diamonds; take
the mega refresh when the orders cover it, or cover it all but a small top-up» — and only
the IDLE tasks are counted, because a task with a squad out cannot be re-rolled and the
mega refresh skips it anyway.

The «Свои задания» page of the Secret Command Post tab draws the readings, offers the
four knobs (`keep`, `use_diamonds`, `diamond_budget`, `mega`/`dispatch`) and plays the
scenario; the phone gets the same card and the same press.

## How to re-read any of this

Dev recipes through the panel's web API, so the client is never touched by hand:

```
POST /api/actions/run   {"profile": "<name>", "name": "<a recipe under actions/dev/>"}
```

A window's root GameObject is `w.gameObject` on a window that has finished loading and
`nil` on one that has not — `w.View.gameObject` answers either way, and a probe that
skipped the fallback read «no go» about a window plainly on screen.

## The order is «send, then refresh» — and a live run is what proved it

The first version of the ability refreshed to the end and sent everything afterwards. It
refreshed three times, a UR fell out on the third, and **the next seven presses did
nothing at all** — no ticket spent, no task moved:

```
post_refresh pressed=1 nonur=5 tickets=25
post_refresh pressed=1 nonur=5 tickets=24
post_refresh pressed=1 nonur=5 tickets=23
post_refresh pressed=1 nonur=4 tickets=22    ← a UR appeared
post_refresh pressed=1 nonur=4 tickets=22    ← and nothing moved again, seven times
```

Read off the window afterwards, with the idle UR still standing there:

```
refreshBtn   interactable=true  activeInHierarchy=false  activeSelf=false
superBtn     activeSelf=false
superBtns    activeSelf=true    (superRefreshBtn + superDispatchBtn)
```

**The client HIDES «Обновить» while an idle UR is waiting** and shows the «мега» pair in
its place. It is not a limit and not a cooldown: a refresh re-rolls every task nobody has
sent, so the game refuses to let the thing that was just paid for be thrown away. Send the
UR and the button comes back — measured, four rounds in a row.

So the cycle is: send whatever is selected, THEN refresh once, then look again. A UR that
could not be sent (no free hero, no march slot) stops the cycle instead of being refreshed
past — losing a UR is worse than losing a turn.

## Sending only the UR — the game's own toggle

`UIDispatchTaskSuperPopup` («Мега развертывание») is not all-or-nothing. Its view carries

```
View.isOnlySelectUR   = true          -- already on when the popup opens
View.toggleOnlySelectUR.unity_uitoggle -- the Toggle behind it
View.datas = { {heroList=#3, index=1, selected=true,  taskInfo=…},   -- the idle UR
               {heroList=#2, index=2, selected=false, taskInfo=…}, … }
```

— five rows offered, exactly one selected, and that one the idle UR. So «send the task the
refresh just won» is the game's own answer and nothing here has to pick heroes. Untick the
toggle and every row is selected, which is what the run's last step does for the leftovers.

`MsgDefines.DispatchStart = hero.dispatch.start` exists for a single task, and is not
needed while the popup answers this well.

### Who unticks «только UR» — measured, one claim withdrawn and then re-established (#2022)

The operator: «отправлены не только UR задания, но и дешевые, вчера я заметил, что во
время выполнения скрипт снял галку только UR при мега отправке». Three explanations were
put up. Two of them are established now. The first version of this section asserted (c) as
fact with nothing behind it, the second withdrew it, and the third — this one — puts it
back because the panel's own log turned out to hold the measurement all along. Every step
of that is left standing rather than quietly tidied, because the next agent has to be able
to tell an exception from an omission, and because the lesson is that the evidence was in
`panel.log` before anybody thought to look for it there.

**(a) OUR OWN CODE — CONFIRMED, and it explains the whole report on its own.**
`secret_post_batch_all()` is the only writer of that toggle anywhere in the repository
(`toggleOnlySelectUR.unity_uitoggle.isOn = false`); it is reached from exactly one button
(`select_all_batch_dispatch`); and step 7 of `refresh_secret_tasks.md` called that button
whenever `dispatch == 1`, which is the default and was the default on the live profile.
The very next press was `confirm_batch_dispatch`, which sends every SELECTED row — and
unticking the filter is what selects them all. So within ONE run, with nothing else
involved: the box comes off, the cheap tasks go out. That is the report, sentence for
sentence. `grep -n "toggleOnlySelectUR\|isOnlySelectUR" tools/ panel/ src/` is the whole
of the evidence and it fits on one screen.

**(b) THE GAME RESETTING IT ON A MEGA REFRESH — nothing supports it, and it is not
excluded.** No path in this repository writes the toggle from a refresh, and (a) needs no
help to explain what was seen. It cannot be ruled out without watching the toggle across
a mega refresh on a live client, which has not been done. It also does not matter to the
fix: the toggle is re-armed at EVERY popup this ability opens, so a game that resets it
is answered by the same code as a game that does not.

**(c) THE UNTICK SURVIVING TO THE NEXT POPUP — CONFIRMED, from the live panel log, and it
survives a client restart and a night.** The first version of this section stated it as
fact with no measurement, and the second withdrew it on the strength of one recorded popup
reading (`View.isOnlySelectUR = true`, «already on when the popup opens»). Both were wrong
about the evidence: `profiles/<name>/panel.log` had recorded the whole thing. Grep it for
`post_send_open` / `post_send_rows` / `post_send_all` and the pair falls out —

```
2026-08-27 17:34:27  post_scan  idle=3 nonur=0 ur=3 …
2026-08-27 17:34:30  post_send_all only_ur=0        <- our own untick, the last one of the day
2026-08-27 17:34:31  post_send_rows rows=3 picked=3

… client restarted twice overnight (restart_game, 22:13 and 22:41) …

2026-08-28 07:02:08  post_scan  idle=9 nonur=7 ur=2  <- SEVEN of the nine idle are below UR
2026-08-28 07:02:11  post_send_open pressed=1        <- the FIRST popup of the new day
2026-08-28 07:02:14  post_send_rows rows=9 picked=9  <- and all nine are selected
2026-08-28 07:02:19  post_send_done pressed=1        <- «sending 9 UR task(s)» — seven of them cheap
```

There is no `post_send_all` in the morning run and no other `post_send_open` between the
two, so nothing in this repository touched the toggle in between: the popup simply opened
with the filter still off, thirteen and a half hours and two client restarts after it was
unticked. That is (c), and it is not a client-session thing either — the state outlives the
process. It also raises the damage back up: an untick is not confined to the run that made
it, it is inherited by whatever opens the popup next, which is how a morning run that never
touched the toggle sent seven cheap tasks.

The earlier `View.isOnlySelectUR = true` reading is not contradicted — it was taken on a
day nothing had unticked the box. «On when the popup opens» is the state the popup was
LEFT in, not a default it returns to.

**What that means for the fix: nothing changes, and that is the point.** The toggle is
re-armed at every popup this ability opens, so an inherited untick is answered by the same
code as a fresh one — and `__lw_ref_onlyur_fixed` now has a known-good meaning: on the
first popup after somebody has turned the filter off by hand, it reports 1 once.

### What the live probe can and cannot settle (measured 2026-08-28)

`actions/dev/_t2022_only_ur_probe.md` opens the popup, unticks the toggle, closes and
reopens it, and puts the toggle back — spending nothing. It was run twice on the live
client and both times stopped at its own first gate:

```
post_send_rows rows=0 picked=0 only_ur=0 cheap=0 unread=0 read_ok=0
probe: the popup could not be read at all — nothing below means anything, stopping
```

**«Мега развертывание» does not become readable on an empty command post.** The probe's
own header used to claim it needed no idle tasks; it needs at least one. Check `idle` on
`read_secret_post` before running it.

That is also the freshness stamp earning its keep on a live client: `only_ur=0 cheap=0
picked=0` beside `read_ok=0` is indistinguishable from a clean popup, and without the
stamp the run would have gone on reasoning about numbers nobody had read.

The account that day had no tasks at all to work with — `idle=0 nonur=0 ur=0 run=0
finished=9 tickets=30`, with the claim press reporting `0 press(es)`, and a full
`work_secret_tasks` run went end to end without refreshing or sending anything and without
spending a ticket or a diamond. So the SEND gate's own live proof waits for a day with an
idle task in the post: judge it by `post_send_rows` / `post_send_done` / `post_send_refused`
in `panel.log` — every row that goes out must read `col5` or above.

### What the fix does, and why it does not rest on the answer

1. `only_ur` is a knob of its own, on by default, and `dispatch` no longer unticks
   anything. Sending the cheap leftovers is still possible — it is what turning `only_ur`
   off means — but it is now a decision somebody makes rather than the default.
2. The toggle is put back on at every popup the run opens (`force_batch_only_ur` /
   :func:`secret_post_batch_only_ur`), which is what answers (c) — an untick inherited
   from yesterday's run is undone before anything is selected — and covers (b) whatever
   its answer turns out to be. `__lw_ref_onlyur_fixed` reports whether it had to be restored,
   which is the standing measurement: a run that keeps reporting 1 is being unticked by
   something outside this ability, and that is when this section gets rewritten again.
3. **The PRESS asks the verdict itself, at the moment it fires**
   (:func:`secret_post_dispatch_confirm`) — the shape the ghost robbery arrived at in
   #2010. It refuses `no_popup`, `filter_off`, `rarity_unreadable`, `cheap_selected`,
   `more_than_ur` and `nothing_selected`, each said by name on the stream. A caller that
   forgets the gate cannot send cheap tasks; an unreadable popup is never confirmed on
   the grounds that it was probably fine.
4. The reading has a freshness stamp (`read_ok`), cleared before the walk and set only
   after a live popup was really looked at. The numbers live on the manager between
   calls, so without it a read that died would leave the previous run's «all clear»
   standing — «we set it» passing itself off as «we checked it», which is the exact
   failure being fixed.
5. Every send and every refusal NAMES the rows: `#<n>/col<colour>/lvl<level>[/star]`.
   Rarity comes from the row's own config — `color` 5 and above is UR, and the `cfgId`
   digits are not looked at, because they lie about it.

### The probe that settles (c), written out because its file is git-ignored

`src/lastwar_bot/actions/dev/_*.md` is ignored on purpose (temporary probes), so the
steps live here — the same convention #1993 used for its fare probe. It spends nothing:
no confirm, no refresh, no squad leaves. Run it on a client that is logged in; it needs
no idle tasks, because the toggle is readable whether or not the popup has rows.

```
TAP open_secret_post
TAP open_batch_dispatch
TAP read_batch_dispatch
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_read_ok) or 0) INTO read_ok
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_onlyur) or 0) INTO on_open
IF read_ok == 0
    LOG "the popup could not be read — nothing below means anything"
    STOP
TAP select_all_batch_dispatch          # untick
TAP read_batch_dispatch
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_onlyur) or 0) INTO after_untick
TAP cancel_batch_dispatch
TAP open_batch_dispatch                # …and open it again
TAP read_batch_dispatch
READ_LUA (tonumber(DataCenter.ActDispatchTaskDataManager.__lw_ref_onlyur) or 0) INTO reopened
TAP force_batch_only_ur                # leave the account right, whatever the answer
TAP cancel_batch_dispatch
TAP close_secret_post
```

**`after_untick` is the control and is not optional.** Without it a `reopened` of 1 could
mean «the game put the toggle back» or «our write never landed», and those are opposite
conclusions. Read the result as:

| `after_untick` | `reopened` | what it means |
|---|---|---|
| 1 | — | the untick never landed; the probe says nothing, fix the write first |
| 0 | 0 | the untick SURVIVES a reopen — (c) is true, the damage spread through the refresh cycle |
| 0 | 1 | the popup restores the filter itself — (c) is false, the damage was the one send at the end of each run |

Either way the last two steps put the toggle back on, and the ability re-arms it at its
own next popup regardless.

#### First live attempt, 2026-08-28: blocked on the account having nothing idle

Run against the live client, the whole probe, cost nothing:

```
post_send_open pressed=1
post_send_rows rows=0 picked=0 only_ur=0 cheap=0 unread=0 read_ok=0
LOG "probe: popup read=0, «только UR» on opening = 0, 0 row(s) offered"
LOG "probe: the popup could not be read at all — nothing below means anything, stopping"
```

…and the post itself, read a moment later, says why:

```
secret post: idle=0 non-UR=0 UR=0 out=0 finished=9 tickets=30 price=100 marches=0/11
```

**Zero idle tasks, so «Мега развертывание» has nothing to offer and its view never
becomes readable.** The button press lands (`pressed=1`) and there is no popup behind
it. So (c) stays open, and the probe wants an account with at least one idle task —
which is what claiming the nine finished ones would produce.

**What this run DOES prove, and it is the half that matters most.** `read_ok=0` is the
freshness stamp doing exactly its job on a live client: the four numbers beside it read
`only_ur=0 cheap=0 picked=0`, which without the stamp is indistinguishable from a clean
popup with nothing selected. The probe said «I could not look» and stopped, instead of
reasoning from a reading nobody took. That is «не отправлять и сказать почему» happening
for real, rather than in a unit test.

## There are more tasks than heroes, and the client says when one is home

A running task's `completionTime` is the game's own millisecond clock, so «wait for a
squad» is never a poll. The scan takes the nearest one, and the scenario leaves the
seconds in `next_run_in` — the schedule books this errand's next turn for exactly then
(docs/dsl.md; the same convention `tavern_free_pull.md` uses). A run that sent everything
leaves `0` and the timer's own period stands.

## The whole ability, proven live

One run, from five idle tasks (four non-UR and the UR the broken version had abandoned):

```
idle=5 nonur=4 ur=1 run=4 tickets=22
  sending 1 UR task(s) before touching the refresh      -> run=5
  refresh 22->21->20->19, a UR falls
  sending 1 UR task(s) before touching the refresh      -> run=6
  refresh -> nonur=3, the threshold                     -> the cycle ends, 4 rounds
mega refresh: cost=12 tasks=3 ok=1 gold=0 -> confirmed  -> tickets 18->6, nonur=0 ur=3
sending 3 of the 3 idle task(s)                         -> idle=0 run=9 march=9/9
```

Sixteen orders and **no diamonds**. The mega's price scaled exactly as the first reading
suggested — twenty for five tasks, twelve for three, four apiece — so at the threshold of
three it is twelve orders, which is 1 200 diamonds at the ordinary rate. Untried still:
the diamond branch (the tickets have never run out mid-run) and the «no hero free» stop.

## The mega dialog's item row is NOT the price — it is what comes out of the bag

This one cost a thousand diamonds nobody had allowed (#1903, live on a second account).
The recipe read the dialog, saw `2`, saw that the bag held 2, concluded «no diamonds
needed» and confirmed:

```
post_mega_cost cost=2 tasks=3 ok=1 gold=0     <- what the dialog's item row said
post_mega_done pressed=1
…                    tickets 2 -> 0,  purse 32 921 -> 31 921
```

Twelve orders were wanted for three tasks; the bag had two; **the game took the missing
ten in diamonds by itself**, at the ordinary hundred each. Nothing asked, nothing warned,
and the row had shown the two it was about to take out of the bag rather than the twelve
the refresh costs.

So the row is a reading and not a gate. The gate is judged on the larger of the row and
what the price is known to scale to — `MEGA_ITEMS_PER_TASK = 4`, measured three times
now: 20 orders for five tasks, 12 for three, and this run's 12 for three. And a press is
never believed on its own word: the purse is stamped when the price is read and read
again after the confirm, so the run SAYS what it really paid.

**And a mixed payment is the ordinary case, not the mistake.** The operator's rule, in
their own words: «1200 — это нормальный прайс. Если мега-обновление с билетами требует
1200 или меньше, можно смело соглашаться». So what was learned here is not «never let the
game top a short bag up» — it is «know the whole price before agreeing». The ceiling is
one number, `diamond_cap` (1 200 by default), and it is read two ways that the log says
apart: the WHOLE diamond price of one mega is judged against it, and the ordinary
hundred-diamond refreshes spend against it as a per-run allowance. The run's grind does
not narrow the mega's decision — a mega that fits under the ceiling is taken whenever it
appears. Going over is still possible, because the game tops a short bag up by itself;
that is precisely why the purse is read again afterwards and the difference said out
loud.

What is still unknown, because neither account had an idle non-UR task left to reproduce
it with: where the diamond amount is drawn in that dialog. Whoever gets a chance should
dump every text under `UIDispatchTaskRefreshConfirm` while the bag is SHORT of the price
— there is a second cost row somewhere and reading it would turn the estimate above back
into a measurement.

## Claiming the finished tasks, and the boxes they pay out in

A finished task is not an errand: its `completionTime` is in the past, its reward is
waiting, and **it holds its march slot until the reward is claimed**. Live: six finished
tasks on six of the nine marches with nothing running at all, `GetSingleTaskIngCount = 6`.
Counting them as «out» is how nine marches look busy while the account is idle, so the
scan asks the server clock and counts `done` apart from `run`.

`ActDispatchTaskDataManager:TryRewardAll()` is the game's own «забрать всё» and sends
`hero.dispatch.batch.reward`. Measured: `GetSingleTaskRewardableCount` 6 -> 0, every one
of them `rewarded = 1`, every march slot free. It raises `UIDispatchTaskReward`, which
`dismiss_steal_reward` already closes.

The box a task pays out in is **«Загадочный ящик с припасами», item 710005**, `type` 5 —
already inside `USABLE_ITEM_TYPES`, so the bag's ordinary `item.use` opens it and no new
primitive was needed. One kind, not a family: the `SR/SSR/UR сундук с …` chests (type
109) are what comes OUT of it. Live, 1 200 of them opened in twelve sends of a hundred:

```
-1200 Загадочный ящик с припасами
+1013 Сундук ресурсов, +37 Ускорение строительства 5мин, +33 Ускорение 5мин,
 +26 Торговый контракт, +15 Ускорение лечения, +14 Ускорение тренировки,
 +12 Секретный приказ, +11 Сундук Компонента Дрона, +11 «10 бриллиантов»,
 +11 Ускорение исследования, +3 Билет найма выжившего, …
```

— and note the twelve refresh orders among them: the boxes pay back part of what the
refreshing costs. «What fell out» has no other answer than a difference: the reward
window is a picture and the server sends no receipt the panel can read, so the bag is
noted down before and read again after.

## Both gaps closed, live

The two branches sooperj never reached, both exercised on the second account in one run:

* **the orders ran out with diamonds forbidden** (`use_diamonds = 0`): sixteen rounds,
  tickets 18 -> 0, five URs rescued and sent as they fell, and not one diamond spent by
  the refresh loop.
* **nothing left to send them with**: after the mega, three idle URs and three free march
  slots — and the popup selected NOTHING, because the heroes were out.
  `post_send_rows rows=3 picked=0`, and the run said so and booked its own return:
  «3 task(s) still waiting for a squad — coming back in 7112 s, when the nearest one is
  home».

## One row on the schedule, and why not two

The operator asked for two things that turn out to be one: a collector that takes each
reward as its task ripens, and a daily errand that sends and collects everything, coming
back through the day because the heroes run out.

**They wake at the same instants.** A running task's `completionTime` is simultaneously
the moment its reward becomes claimable, the moment the march slot an unclaimed reward
was holding is freed, and the moment its heroes are home to be sent again. Two rows would
be woken by the same clock, would take the same game claim and would race each other over
the same list — with the collector firing in the middle of the day errand's own cycle.

So there is one row, `secret_tasks_day`, playing `actions/work_secret_tasks.md`:

1. `CALL collect_secret_tasks` — claim, then open the boxes. The order is the operator's
   instruction and it also pays: the boxes hand back «Секретные приказы», so the
   refreshing that follows is cheaper.
2. `CALL refresh_secret_tasks` — the price rule, the UR rescues, the sending.
3. read the nearest finish and leave it in `next_run_in` (+30 s).

`CALL` shares the context — `prepare_source(text, ctx.vars)` merges the sub-recipe's own
`ARGS` defaults UNDER the caller's variables, and `ctx.vars.update(merged)` writes the
sub-recipe's readings back — so the day's knobs travel down by declaring the same names,
and the sub-recipe's `next_run_in` is visible to the caller, which then overwrites it with
its own fresher scan.

The row's period is `DAY_SEC`, which the schedule anchors to the server's own midnight;
it is only where a day with nothing running starts from. Live end to end on a second
account: claim (nothing due), boxes (none left), the cycle (no non-UR to refresh), the
send refused for want of heroes and said so — and «back in 5377 s, when the first of them
finishes».

## The window that was being missed, and the four things that were missing it (#2073)

The operator's report: «Плохо сделан таймер сбора наших секретных заданий, время
пропускается, их могут украсть». A finished task of the account's OWN is robbable until
its reward is claimed — the same `hero.dispatch.steal` this bot spends five of a day on
strangers, pointed back at us — so every minute between «выполнено» and «получено» is a
minute somebody else may be paid for. The appointment machinery was already there
(`next_run_in`, above); what it did in practice was arrive late, and sometimes not at all.

Read off the code rather than guessed, four separate defects, each of which alone loses
the window:

1. **The turn was booked half a minute AFTER the finish** (`free + 30`), on top of the
   scheduler's own tick — `TICK_SEC = 20`, so an appointment is kept up to twenty seconds
   after it is due — and on top of the run's preamble. Fifty to sixty seconds of a ripe
   task standing in the open, by construction, on the happy path.
2. **A run that FAILED booked nothing at all.** `Errands._honour_next_run` was the last
   thing a *successful* run did; a recipe that raised half way through left no `due_at`,
   and `due_names` then fell back on the row's period. For `secret_tasks_day` that period
   is `DAY_SEC` anchored to the server's midnight — so ONE failed run stopped the claiming
   until the next reset.
3. **A successful run could book zero over its own good reading.** `refresh_secret_tasks`
   step 9 was gated on `idle > 0`: a run that had just sent every task it had wrote
   `next_run_in = 0`, and zero means «the row's period stands» — the same lost day as (2),
   reached from a run that worked perfectly.
4. **The retry hold outranks the appointment.** `due_names` sits out
   `now - failed_at < retry_sec` *before* it ever looks at `due_at`, and this row's
   `retry_sec` was 1800. A client that was briefly not answering therefore silenced a
   game-named appointment for half an hour.

### What was done

* **The last stretch is waited out inside the run, not on the schedule.** The client holds
  every running task's `completionTime` to the millisecond, so
  `collect_secret_tasks.md` now scans (a walk over the client's own table — no question
  goes to the server), and while something ripens within `ripe_wait` seconds it sleeps
  `ripe_poll` and presses «Получить» again. `claim_secret_task_rewards` is `xall` over
  `GetSingleTaskRewardableCount`, so a round that finds the task still counting down
  presses nothing. This is the same shape as the star sprint of #1294 and for the same
  reason: seconds decide, and only there.
  `ripe_wait` defaults to **0** — the button on the tab claims what is ripe and returns —
  and the day's errand passes **150** down through `CALL`.
* **The appointment is booked with a LEAD** (`ARGS lead = 45`): the nearest finish MINUS
  the lead, floored at ten seconds, so the run is already under way when the task ripens.
* **It is booked THREE times, early first.** `collect_secret_tasks` books before any of
  the spending starts, `refresh_secret_tasks` books again on its way out, and
  `work_secret_tasks` overwrites with the freshest scan. A run that dies anywhere after
  the first of them still leaves a good appointment behind.
* **`Errands._run_errand` honours it from the `finally`**, so a FAILED run keeps whatever
  it had read. A recipe that never reached such a line leaves nothing in its variables and
  the call is a no-op, exactly as before.
* **`refresh_secret_tasks` step 9 lost its `idle` gate.** What is out has to be claimed
  whether or not anything is standing idle.
* **`secret_tasks_day.retry_sec` 1800 -> 300.** The hold is the one thing that outranks
  the game's own appointment, and half an hour of it is half an hour of a finished task
  standing on the map.

Worst case on the happy path is now: fires between 45 and 25 seconds before the finish,
polls every 3 s, claims within about three seconds of the server turning the task over.
