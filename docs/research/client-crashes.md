# Why the client crashes so often (#2066)

The operator's complaint is a rate, not an incident: the client dies several times a
day, the watchdog puts it back, and the day is full of holes. #1994 looked at the same
Windows log while fixing the link and concluded «not us» — worst day older than our
code, faulting address inside the game's own modules. This is that question asked again
after a month of driving the client from outside, with a control group.

**The answer changed. There is a correlation, it is with ONE thing we do, and it is not
the one the candidates list expected.**

## What the Windows log holds

`Application Error` (event 1000), the whole log the machine still has, entries for the
game only:

| module named as faulting | entries |
|---|---|
| **`unknown`** | **79** |
| `UnityPlayer.dll` | 68 |
| `GameAssembly.dll` | 22 |
| `KERNELBASE.dll` | 11 |
| `xlua.dll` | 5 |
| `ntdll.dll` | 5 |
| `d3d11.dll` | 1 |

Almost all are `c0000005` — an access violation.

`unknown` is the interesting row. Windows writes it when the faulting address is inside
no loaded module: the thread was executing (or returned into) a page that belongs to
nobody. A shipped game does not normally produce those. **A hijacked thread pointed at
an allocated RWX stub does.**

## The regime change, by date

| period | days | crashes | per day | of them `unknown` |
|---|---|---|---|---|
| 24 Jul – 12 Aug | 20 | 43 | 2.2 | 2 (4.7 %) |
| 13 Aug – 30 Aug | 18 | 137 | 7.6 | 73 (53 %) |

Two things moved at once — the rate roughly tripled, and a class of crash that barely
existed became the majority.

**And the signature has a rehearsal.** 21 July — the day the thread-hijack il2cpp dumper
was first written — stands alone in the quiet period: 11 crashes, 4 of them `unknown`,
2 in `xlua.dll`. The same fingerprint, on the day the mechanism was invented, three
weeks before it became routine.

## Is it just «more clients»?

No. Four accounts have been driven since 5–8 August, and 5–12 August is inside the quiet
period with 0–1 `unknown` crashes a day. The count of live clients does not explain the
step at 13 August.

Is it just «more Lua»? Also no — see the control below. Daily Lua volume and daily crash
count do not track each other: 25 August ran 25 919 Lua lines for 5 crashes, 24 August
ran 6 577 for 17.

## The control group

Naive «what was the panel doing before a crash» answers nothing: the panel is always
doing something, and every tag appears before most crashes. The measurement that
discriminates compares each candidate against a matched random moment.

Method: take every `hijacking tid=` line one profile's `panel.log` recorded, and every
crash in the same window. Control moments are drawn at random from the same period but
kept **only if a hijack happened within the previous 120 s** — that conditions the control
on «the client is alive and the Lua VM is in use», which is the confound that would
otherwise inflate everything.

| window | crashes inside it | of them `unknown` | control |
|---|---|---|---|
| ≤2 s after a hijack | 43.9 % | 36.7 % | 12.5 % |
| **≤5 s after a hijack** | **68.3 % (28/41)** | **70.0 %** | **15.1 %** |
| ≤10 s after a hijack | 73.2 % | 73.3 % | 19.3 % |

**×4.5.** Two thirds of the crashes that happen while the VM is in use land within five
seconds of us borrowing the game's main thread.

Against the same crashes, an ordinary Lua step (`LUA` / `pcall(`) scores **7.0 %** within
5 s against a control of **11.4 %** — below chance. Running a chunk is not what kills the
client; **attaching to run it is.**

The offset histogram is one-sided: of 34 crashes within ±20 s of a hijack, **all 34 are
after it**, peaking at +2…+3 s. That reads as causality, and it is worth saying plainly
that it is only half evidence — a dead client stops producing hijack lines, so the
negative side is partly empty by construction. The case–control above is the number to
trust; the histogram only says the crash follows within seconds rather than preceding.

## Which hijack

The label on the last hijack before a crash, and the label counts overall:

| label | last before a crash | total in the log |
|---|---|---|
| `rettypename` | 9 | 3 338 |
| `mpc` | 9 | 11 606 |
| `iterMgrM` | 3 | 11 720 |
| `getret` | 1 | 3 347 |
| everything else | 6 | ~1 700 |

Those four are one function: `xlua_route.X.luaenv_via_manager_method`, which walks up to
600 `XLuaManager` methods looking for the 0-arg getter that returns a `LuaEnv`, and spends
2–4 main-thread hijacks per method (`il2cpp_class_get_methods`, `il2cpp_method_get_param_count`,
`il2cpp_method_get_return_type`, `il2cpp_type_get_name`).

The arithmetic: that profile's log holds **164 evaluator builds and 32 317 hijacks** —
about 180 suspensions of the Unity main thread per build, to learn something that does
not change while the client is running. The other two clients' daemon logs hold 677 138
and 292 637 hijack lines over the same weeks.

So the exposure is not a rare risky call. It is ~30 000 chances a day, per client, to
suspend the main thread, redirect RIP into an allocated page and put it back — each of
them individually 99.99 % safe and collectively a several-times-a-day crash.

## What is NOT implicated

Named as candidates when the task was written, and cleared by the same measurement:

* **The «ear»** (the wrapper over `SFSNetwork.SendMessage`). It was installed for most of
  one day; the crash days do not follow the days it was up, and it is off now while the
  rate is unchanged.
* **Ordinary Lua traversals** — 214 buildings, the whole of `MsgDefines`, the bag, the
  queues. `LUA` lines score below the control rate before a crash.
* **The treasure errand's per-frame watch.** It ticks continuously and the crashes do not
  cluster around it any more than around anything else that runs all day.
* **`require` of UI classes without the window.** Never shipped; #2065's worker dropped it.

`UnityPlayer.dll` crashes at repeated offsets (`+0xc545e`, `+0x812ebb`, `+0x847427`) are
present in the quiet period at the same rate and are the game's own — those are the ones
#1994 saw, and its verdict was right about them. What #1994 could not see is that a second,
larger population arrived later and now outnumbers them.

## What to do about it

Not fixed here — this is the measurement. The cheap end of it:

1. **Do not re-walk `XLuaManager` on every evaluator build.** The getter's name does not
   change while the client is running; `il2cpp_class_get_method_from_name` costs three
   hijacks against the walk's ~180. `find_dostring` already learned this lesson and asks
   by name before walking; `luaenv_via_manager_method` never did.
2. **Cache the resolved `LuaEnv` for the life of the client process**, keyed on the pid, so
   a build is once per client rather than once per thread that finds the daemon down.
3. Anything that removes hijacks removes crash exposure proportionally, because the
   per-hijack risk is what it is.

## What was done about it (#2067)

Both cheap items, in `tools/lib/xlua_route.py`:

* `luaenv_via_manager_method` **asks for the getter by name** before walking anything —
  `il2cpp_class_get_method_from_name`, the return type, the call: **four hijacks against
  the walk's ~180**. The names tried are a short list (`get_Env` first, which is what
  this build answers to), and a build that renames the getter still falls through to the
  walk, which is unchanged.
* The name that answered is **remembered for the life of the process, keyed on the
  client's pid** — including one the walk had to find — so a rebuilt evaluator against
  the same client costs four hijacks again. Only the NAME is cached, never the `LuaEnv`
  pointer: a name is a fact about the build and cannot go stale while the client runs,
  and asking the live client for the pointer costs one hijack, so there is nothing to
  win by guessing it.

On the measured profile that turns ~180 hijacks per evaluator build into 4, i.e. the
32 317 hijacks its log holds into roughly 700. `tests/test_xlua_getter.py` pins the cost
without a client: the il2cpp layer is stubbed and the test counts the hijacks.

## Limits of this reading

* Windows' event 1000 does not say which client or which Windows session crashed. Four
  accounts ran; the case–control uses one profile's `panel.log`. That mismatch can only
  DILUTE the association, not manufacture it.
* The daemon logs (the clients in their own sessions) carry no timestamps, so they could
  not be joined to the event log at all; their hijack counts are volume evidence only.
* `panel.log` records the hijacks of the paths that log through the panel; hijacks made
  elsewhere are invisible to the control. Again a dilution, not an inflation.

---

# Asked a third time, a week later (#2656)

The complaint again, and sharper: thirteen disappearances in one afternoon, scenarios
torn in half (`ClientGone` one second after a press, `WAIT scene == world` timing out on
a client that had only just come up), and the suspicion pointed at the wrappers the panel
installs in the game's Lua VM.

**The wrappers are not it. Every disappearance is a hard crash, the population is the one
#2066 measured, and the exposure that drives it is BIGGER than it was, not smaller.**
Two real wrapper bugs were found on the way and fixed — neither of them the crash.

## Every «клиент пропал» is a fault, and none of them is a kick

For one profile's day (2026-09-08) the panel logged 30 disappearances. The Windows
`Application Error` log holds an event 1000 for the client **before every one of them**,
5–25 s earlier:

| faulting module | exception | that day |
|---|---|---|
| `UnityPlayer.dll` | `0xc0000005` | 17 |
| **`unknown`** | `0xc0000005` | **17** |
| `GameAssembly.dll` | `0xc0000005` | 2 |
| `GameAssembly.dll` | `0xc0000409` | 1 |
| `ntdll.dll` | `0xc0000005` | 1 |

38 faults, three clients driven on the machine — the log does not say which client, so
that column is all three and the panel column is one.

So the three readings a person could have made are settled: it is **not** the account
being kicked (a kick makes the client say so and quit cleanly, and there is no event
1000 for a clean exit — the one disappearance a person reported as a kick has a crash of
its own beside it), it is **not** anything killing the process, and it is **not** our Lua
raising: a Lua error in this build is caught and logged, it does not take the process
down.

`0xc0000409` is `STATUS_STACK_BUFFER_OVERRUN`, which is also how a managed stack
overflow ends — and the client's own `Player-prev.log` for that hour ends on
`StackOverflowException: The requested operation caused a stack overflow`. That one is
worth its own line below.

## Why the scenarios tore

The panel notices the corpse **8–22 s** after the fault, and spends that window driving
it: `ConnectionError: OpenThread(<tid>) failed err=87`, `snapshot failed err=5`,
`ClientGone`, a `read_*` that fails, an errand that logs an error and gives up. Then the
watchdog relaunches and the next scenario meets a client that is 20 s old, which is where
`WAIT scene == world` times out. Nothing there is a second bug: it is the crash, seen
from inside.

## What the dumps say

Three minidumps survived the day's rotation (`tools/crash_report.py --dumps` reads them
without a debugger):

* one faulted **executing an address in no module at all** — exception parameter 0 = 8,
  a DEP/execute violation, at an address in private memory holding zeros. Its stack is an
  ordinary Unity main-thread player loop with managed frames on top and **no injected
  frame anywhere**: this is the game calling through a corrupted pointer, not our stub
  running. The `unknown` row above is that shape, not «our shellcode was executing».
* two faulted in ONE `UnityPlayer.dll` function, reading through an object pointer whose
  two halves are small integers — a garbage object, not a garbage address.

That is the useful negative: `unknown` in the event log means «RIP was in no module»,
and #2066 read it as the hijack's own stub. At least this crash is the game jumping
through a pointer that has been corrupted, arriving from its own code.

## The exposure did not shrink

#2067 removed ~180 hijacks per evaluator build. It did not remove the hijack per Lua
call, and the panel's read volume has gone up since. Measured on the same profile over
the 401 minutes its current `debug.log` covers:

| | |
|---|---|
| hijacks (the link's own per-minute tally) | **43 969** |
| that is | **110 a minute, ~1.8 a second, continuous** |
| DSL steps the panel ran in the same window | 11 693 |
| so, hijacks per step | **≈ 3.8** |
| of those steps, `rally_monitor` + `join_rally` | 2 303 (one every ~9 s) |

Per #2066's own arithmetic — «anything that removes hijacks removes crash exposure
proportionally» — that is the whole finding. The cheapest reductions available, none of
them taken here because each changes behaviour a person should agree to first:

1. **3.8 hijacks per step.** One `DoString` should be one. The array refill and the
   string pinning were already made once-per-attach (#2404); whatever is left is worth a
   count before it is worth a guess.
2. **`rally_monitor` + `join_rally` are half the day's steps.** Every
   `push.alliance.march` (a rally emits several — create, then a refresh per joiner)
   plays both. Weighing one banner state once, rather than once per push about it, is the
   same «read once, then listen» the rest of the panel follows.
3. Anything that answers from what the panel already holds instead of asking the VM.

## The naive correlation, again, still says nothing

Tagging each fault with what the panel was doing in the preceding 30 s spreads across
every tag — scene switches, rally presses, radar claims, plain reads — in roughly the
proportion those tags appear anyway. That is #2066's finding reproduced, and it is why
the case–control there is the number to trust and this is not.

## The two wrapper bugs that ARE real (and are fixed)

Found by reading the client's own log rather than ours, and neither shows up anywhere in
the panel:

**The build refuses new globals.** `Global/GlobalProtect.lua` installs an `__newindex` on
`_G` that REFUSES an unknown name and only logs it (`Lua 全局变量 '…' 不可<新增/修改>` —
«cannot be added/modified»). It does not raise, so nothing on our side notices.

* **The red-packet ear parked its callback on `_G`.** The write was dropped, the wrapper
  installed anyway, `B.on` went true, and every chat message then called `pcall(nil, …)`.
  The panel reported the ear armed and «слышал 0, забрал 0» for as long as it has
  existed. It hangs off `DataCenter.__lw_rpw.take` now.
* **`dev/wire_catch.md` kept its saved original on `_G` too** — and that one compounds.
  With `_G.__lw_catch_old` for ever nil, the «already wrapped?» guard was never true, so every
  run wrapped `SFSNetwork.HandleMessage` AGAIN over the previous wrapper, the unwrap at
  the end restored nothing, and the layers stayed for the life of the client. Three runs
  in one afternoon is three extra frames on every message the client receives. That is a
  stack overflow with enough runs, and a stack overflow is what one of the day's faults
  was. It keeps its state on `DataCenter.__lw_wcatch` now and recognises its own wrapper.

**The rule that falls out of it: nothing of ours is ever parked on `_G`.** One table on
`DataCenter` per ability, and a guard that compares the installed function to our own.

## The tool

`tools/crash_report.py` — the whole of the above in one command, so the next time this is
asked it is answered in seconds rather than a day:

    python3 tools/crash_report.py --days 1 --profile <name> --dumps

It reads the Windows event log (through whatever PowerShell the machine has,
`LW_POWERSHELL`), the minidumps under `%LOCALAPPDATA%\CrashDumps` (`LW_CRASH_DUMPS`), and
quotes the profile's own `panel.log` around each fault — one pass of the log for all of
them. Event 1000 is translated on most installs, so the fields are read by shape and not
by wording; `tests/test_crash_report.py` pins that.

## What the owner decided about the three (#2656)

The three exposure reductions above were put to the person with their behaviour cost
stated. **Two of them are refused, and they are written down here so that the next agent
reading the arithmetic does not re-open a settled question.**

**2 — coalescing the rally pushes: NO.** In their own words: «По пушам марша не вижу
проблему, один просто собирает статистику, другой присоединяется, они никому не должны
мешать, оба прозрачные и в разных потоках.» The two subscribers on
`push.alliance.march` — `rally_monitor` (which only reads what is out) and
`rally_auto_join` → `join_rally` (which joins) — stay one run per push, minus the dedup
they already have. The measurement stands and is not the point: 6 154 pushes a day for
931 rallies (`create` 931, `refresh` 4 312 — a median of five per rally, one per joiner,
— `remove` 911), 1 913 + 1 817 runs, 7 486 of the day's 18 524 DSL steps, 40 %. **The
cost of the change was a rally slot** (a banner fills 5/5 and launches in seconds; any
window that coalesces `refresh` delays the decision by that window), and that is not a
price the owner will pay for an unmeasured reduction in crashes. Do not propose it again
without evidence that the crash rate actually follows the hijack count — which is the A/B
nobody has run.

**3 — answering from what the panel already holds: NO.** «3 оставь как есть.» And the
investigation had already found why it was the wrong target: `read_server_info` — 608
runs a day, the biggest single candidate — is **not a reading of an unchanging number, it
is the LIVENESS PROBE** (`panel/runtime/status.py::PROBE_ACTION`, every 120 s while
nothing else has proved the link). Green means «the game server answered», so caching the
probe's answer would cache exactly the thing the light is about, and the panel's health
model is where two whole nights have already been lost (#1910, #2446). The probe stays as
it is, at its present cadence.

**1 — cheapening the hijack itself: YES, and it is the only one.** It is the only one
with **no behaviour change at all for the player** — nothing runs later, rarer, or not at
all; only the number of attaches per answer moves. That is the owner's condition on it.
The order of work is theirs too: *«со счётчика по label на сутки, потом правка»* — the
per-label tally lands first (`tools/lib/hijack_call.py::STATS["by_label"]`, a line a
minute in the profile's debug log, `tools/hijack_tally.py` to add a day up), a day is
allowed to accumulate, and only then is the 3.8-attaches-per-step figure taken apart with
the numbers in hand.

---

# The morning of ten crashes, taken apart (#2665)

Ten of them between 07:01 and 09:52 on 2026-09-09, the owner's words: «падения разбирай
тщательно, нужно это править». This section is the arithmetic, one claim per heading, and
then what was changed on the strength of it.

## The counts

`python3 tools/crash_report.py --days 3`, run at 10:24 on 2026-09-09. Event 1000 for the
client, 85 faults over the three days:

| faulting module | exception | count |
|---|---|---|
| `UnityPlayer.dll` | `0xc0000005` | 40 |
| *unknown* (no loaded module) | `0xc0000005` | 32 |
| `GameAssembly.dll` | `0xc0000005` | 7 |
| `ntdll.dll` | `0xc0000005` | 3 |
| `xlua.dll` | `0xc0000005` | 1 |
| `GameAssembly.dll` | `0xc0000409` (stack overrun) | 1 |
| `UnityPlayer.dll` | `0xc000041d` | 1 |

By day: 6 Sep 15 (partial — the window opens at 10:20), 7 Sep 17, **8 Sep 36**, 9 Sep 17
by 10:24. The one `xlua.dll` fault is 09:09:52 on the 9th, and the offsets repeat across
days — `UnityPlayer+0xc545e` six times, `+0x28b43a` and `+0x28b1c6` twice each,
`GameAssembly+0x21a9f6` three times — so this is a handful of code paths, not a spray.

The profile's own log agrees: `default` wrote «клиент пропал — процесса игры больше нет»
at 02:50:48, 03:33:29, 06:41:51, 07:01:32, 07:08:45, 07:44:43, 09:10:06, 09:18:26,
09:28:52, 09:43:45, 09:52:12, 09:57:17, 09:58:42 and 10:22:33, with two more deaths at
09:21:22 and 09:46:02 that were answered by a wait rather than a relaunch (below).
**Every one of the day's faults is that one account's client**: the other two profiles
drive clients in other Windows sessions and neither lost one.

## The hijack rate does NOT predict a fault

44 444 hijacks in `default`'s own debug log between 00:00 and 10:24 — median 58 a minute,
mean 67.3. Adding up the three minutes before each of the day's 17 faults gives a **mean
of 202**, against a baseline of 3 × 67.3 = **202**. The medians are 149 against 174.

That is the third time this correlation has been asked for and the third time it has said
nothing (#2066, #2656), and it is worth writing down plainly: **the client is not killed
by being busy.** Whatever kills it is a particular thing done in a particular way, not a
volume.

## A PANEL RESTART is what predicts a fault

Nine panel restarts on the 9th between 08:34 and 10:21 (`profiles/panel_relaunch.log`).
**Six of them are followed by the client dying 59–95 s later**: 09:17:09 → 09:18:26,
09:27:53 → 09:28:52, 09:42:39 → 09:43:45, 09:56:09 → 09:57:17, 09:57:30 → 09:58:42,
10:20:59 → 10:22:33.

Sixteen deaths over the 530 minutes the log covers is one per 33 minutes, so a 95-second
window catches one **4.8 %** of the time and nine of them should have caught **0.4**.
Six is not a coincidence anybody can argue with.

What a restart is, that a busy hour is not: a fresh attach to the client, plus every
scenario a profile owns asking for the link inside one minute. Read the 10:20:59 boot in
`profiles/default/panel.log` — a rally join at 10:21:49, the glittering market read
10:21:59–10:22:02, and then `read_player_place`, `read_ready_buildings`,
`read_research_queues`, `read_drone_chips`, `read_drone_parts`, `read_survivor_tickets`,
`read_arms_race`, `read_vs_score`, `read_zombie_invasion` and `inventory_refresh` all
queued behind one another. The client dies in the middle of that, and the first line that
knows is `«read_player_place» остановился на ошибке: ConnectionError: OpenThread(90564)
failed err=87` — the thread the panel was holding is gone.

## The minidumps say WHICH thread

Six dumps survive from the 9th (`%LOCALAPPDATA%\CrashDumps`). Reading the exception
record, the CONTEXT and the module list out of each:

| time | RIP | in |
|---|---|---|
| 09:28:41 | `…690040` | no module |
| 09:43:35 | `…660040` | no module |
| 09:45:43 | `UnityPlayer.dll+0x28b1c6` | the engine |
| 09:52:01 | `UnityPlayer.dll+0xc545e` | the engine |
| 09:56:58 | `…000ac8` | no module |
| 09:58:18 | `0` | nowhere |
| 10:22:12 | `0` | nowhere |

Two things fall out of it.

**Every one of them is the process's FIRST thread.** RSP is `0x13e880`–`0x13f530` in all
six — the low stack a Win32 process gives its main thread and nothing else. That is the
thread `hijack_call` is told to take (`only_tid=main`), and it is the thread the panel
suspends and resumes twenty-odd times per hijack while sampling for the safe park.

**And two of them died AT OUR SHELLCODE'S FIRST BYTE.** `hijack_call` allocates a 0x400
RWX region and puts the code at `region + 0x40`; `VirtualAllocEx` hands out 64 KB-aligned
bases. `0x129660040` and `0x2e8690040` are 64 KB-aligned + 0x40 — that address is this
layout's entry point and nothing else in the process. Both faulted there with
`ExceptionInformation = [0, 0xffffffffffffffff]`, i.e. an instruction fetch with no
address to report: memory that is not there.

## The two races that produce exactly that

Both are in `tools/lib/hijack_call.py`, in the branch the code itself called benign — the
one taken when the redirected thread has not raised its `started` byte inside
`start_timeout` (0.6 s), described as «thread never returned to user mode».

It cannot be known that a thread never will. It is only known that it has not YET.

1. **The abandoned thread's region was REUSED.** One region was allocated per
   `hijack_call` and rewritten with a fresh `orig_rip` for the next candidate. A thread
   abandoned as «not started» that then does wake runs the shellcode built for a
   DIFFERENT thread and returns to that thread's parked address.
2. **…and then FREED.** The miss path released the region unconditionally. A thread that
   wakes at `code_abs` afterwards is executing memory that no longer exists — which is
   what the two dumps above are a photograph of.

There is a third, smaller one in the same branch: `started` is raised some twenty
instructions in, after seventeen pushes and a `pushfq`. A thread suspended in that gap
has our prologue on its stack while the flag still says nothing began, and putting its
RIP back returns it into the parked function with RSP 0x88 too low. It does not die
there; it dies later, in the engine, with nothing of ours in the picture — which is what
40 `UnityPlayer.dll` faults with clean engine stacks look like.

## The wrappers: the client's own log names them

The rule from #2656 — «nothing of ours is ever parked on `_G`» — was written down and not
swept for. `Global/GlobalProtect.lua:54` refuses an unknown global and logs it, and the
client's `Player.log` on the 9th holds one refusal per install:

```
Lua 全局变量 '__CR_BUF' 不可<新增/修改>      … and __CR_CAP, __CR_REC, __CR_ORIG,
Lua 全局变量 '__CR_WRAP' 不可<新增/修改>      __CR_CLASS_HOOKED, __CR_ADD, __CR_ADDWRAP
Lua 全局变量 'WS' 不可<新增/修改>             (twice)
Lua 全局变量 '__LW_TRB' 不可<新增/修改>
```

`tools/chat_reader.py` is started by every profile on every boot. With `CR.ORIG` for ever
nil its wrapper called `nil` for every message the client parsed, and — the part that
kills — with `CR.WRAP` for ever nil the «is my wrapper already there?» guard was never
true, so **every install wrapped `ChatMessage:onParseServerData` again over the last
one**. Nine panel restarts is nine layers on the method the client runs per message, for
the life of the client. That is the mechanism #2656 found in `dev/wire_catch.md` and
predicted a stack overflow from; 8 September's `GameAssembly.dll 0xc0000409` at 10:08:57
is one.

`WS` is the cached `WorldScene`: refused, so every world read re-walked every
MonoBehaviour in the scene. `__LW_TRB` is the chat translation batch, which answered
nothing.

## What is NOT implicated, measured rather than assumed

* **The GPU.** No event 4101/4102/13/14 in the System log over two days. Driver
  32.0.15.9636, RTX 2070 SUPER. A TDR does not present as `0xc0000005` in-process anyway.
* **Memory and handles.** The live client at 10:30: working set 1.80 GB, private
  2.27 GB, 1 877 handles, 64-bit. Nothing is near a limit, and the fault codes are
  in-process access violations rather than allocation failures.
* **The anti-cheat.** `ACE-Base64.dll` is loaded in every dump. Not one of the six faults
  has RIP inside it.
* **A second Windows session, and «too many clients».** On the 9th only ONE client ran
  after 08:34 — and it is the one that died sixteen times. On the 8th three ran and there
  were 36 faults. The per-client rate is of the same order either way.
* **The cstr fix of #2660** (`5923fd5a`, committed 08:39:56, live from the 08:40:23
  restart). Seven faults in the 485 minutes before it, ten in the 102 minutes after. It
  did not lower the rate — which is expected: it was a leak fix, and a leak is not what
  any of this is.

## The watchdog's cooldown

`WATCHDOG_COOLDOWN_SEC` is 300 s and the latch used to survive the client coming back. On
the 9th that cost two waits over a client that was already down and playable: «вотчдог:
перезапуск был 2 мин назад — жду» at 09:21:22 with the relaunch at 09:23:31 (**129 s**),
and again at 09:46:02 with the relaunch at 09:52:12 (**370 s**).

The number itself is right for what a cooldown is FOR — a client that cannot start does
not start any better for being asked again in thirty seconds, and the person should be
told once rather than ten times an hour. What was wrong is that it was applied to a
relaunch that had WORKED. So the number stays and the latch is cleared the moment the
client answers again.

## What was done about it (#2665)

1. **`hijack_call` never reuses or frees a region a thread was pointed at.** A candidate
   abandoned as «not started» keeps its own region, with the shellcode replaced by a stub
   that jumps straight to that thread's own parked address, and the region is leaked
   rather than released — 64 KB of address space against a dead client. The next
   candidate gets a fresh one. The leak is counted (`STATS["abandoned"]`) and printed in
   the panel's per-minute hijack line, so the rate of the race is readable.
2. **…and it looks at the thread's RIP before restoring it.** Inside the region means the
   thread is running our code whatever the flags say, and it is handled by phase 2 like
   any other call instead of being sent home with a wrecked stack.
3. **Nothing of ours is on `_G` any more, anywhere.** `DataCenter.__lw_chat` for the chat
   pair, `DataCenter.__lw_ws` for the world scene, and the same for the frontline
   recipes, the translation batch, the street-run autopilot, the Lua tracer and the dev
   probes. `tests/test_repository_hygiene.py` fails on a new one, and
   `tests/test_chat_hook_liveness.py` now runs its Lua VM behind a stand-in for
   `GlobalProtect` and pins that six installs are one wrapper rather than six.
4. **The watchdog latch is cleared when the client comes back**
   (`panel/runtime/status.py`), with the cooldown's real purpose written beside the
   number.

## The boot stampede is spread out, and the million suspensions are not what they were called (#2667)

Both of the open items below were taken up together, and one of them turned out to be
mis-attributed. What follows is measured, not argued.

### The burst is gone: a tick starts ONE errand

The operator's decision, in their words: «Да, разноси, сделай правило, пусть лаг будет,
нет веской причины все разом делать». `panel/timers.py` now queues at most one errand
that came due by the clock and waits `SPREAD_SEC` (20 s) after it has FINISHED before
offering the next; a boot's fifteen overdue errands are played out over about five
minutes instead of one. A person's press and an event-driven fire (a push, a trigger,
«сразу») are never spread — they have no clock to come round on. The rule is written in
`CLAUDE.md` and pinned by `tests/test_panel_timers.py`.

**The first live restart on the fix showed where the rest of the burst was**, and it is
worth recording because the clock was not it: the panel restarted at 11:16:17 on
2026-09-09, the gate held everything while the client was down, and when the link went
green six PARKED FIRES were released inside one second (11:17:04). The client crashed at
11:17:08 — `UnityPlayer.dll`, four seconds later. So a fire coming off the gate is spread
on the same gap; it is already minutes late and `GATE_KEEP_SEC` (600 s) leaves room for
thirty of them to drain at 20 s apart.

What is still NOT spread, and is a question for the person rather than an agent: the
tabs' first readings on `bus.GAME_READY`. The same boot put ten of them in the log inside
thirty seconds (`read_drone_chips`, `read_arms_race`, `read_vs_score`, …). Each is one
chunk rather than a scenario, and delaying one shows a board a minute older than it could
be — which is exactly the kind of visible change this work may not make on its own.

### Where the suspensions actually come from

Read off 765 minute-lines of the live panel's own tally (`hijack_call.STATS`, four
profiles, 2026-09-08…09):

| | |
| --- | ---: |
| hijacks | 67 532 |
| suspend/resume of the client's main thread | **1 836 605** |
| samples per hijack | 27.2 |
| wall time spent waiting for the park | 18 769 s |
| of those suspensions belonging to `learn_safe_rip` | **2 320 (0.13 %)** |

**The bullet that used to stand here blamed `learn_safe_rip`, and it is wrong.** A learn
is 40 samples and happens once per evaluator build (plus once per hijack that gave up:
58 in the whole window). The million suspensions are `hijack_call`'s park sampling —
`PARK_POLL` at 10 ms, run until the main thread is caught within ±16 bytes of the learned
park.

One sample costs the client **60–75 µs** (median of 400, measured live, `CONTEXT_FULL`;
`CONTEXT_CONTROL` is 5–7 % cheaper and not worth the second code path). So 1.8 M samples
is about two minutes of suspended main thread a day in total — the interference is real
but small, and what the crash rate correlates with is the ATTACH (67 532 of them, ×4.5
above control), not the sample.

### Polling slower is NOT the lever — measured

The obvious cut is to sample less often. It does not work, and here is the A/B on the
live client (12 s per rate, same thread, same session):

| poll gap | samples taken | park hit rate | samples to a hit | wall to a hit |
| ---: | ---: | ---: | ---: | ---: |
| 10 ms | 1 147 | 1.6 % | 64 | 0.64 s |
| 20 ms | 588 | 1.9 % | 54 | 1.07 s |
| 40 ms | 297 | 2.0 % | 50 | 2.0 s |
| 80 ms | 150 | 4.0 % | 25 | 2.0 s |

The hit rate rises with the gap, but sublinearly: eight times slower buys 2.5× fewer
suspensions and costs 3× the wait. The panel already spends 30 % of its wall clock
waiting for the park, so paying it three times over is a slower panel all day — a
behaviour change, and the one thing this work may not cost. **`PARK_POLL` stays at
10 ms**; the paragraph beside it in `tools/lib/hijack_call.py` says so with these
numbers.

### What was cut, and by how much

A learn stops as soon as the park is DECIDED — one ntdll address seen three times and
clearly ahead of every other ntdll address (`rip_gate._decided`). Live A/B against the
full 40-sample sweep, six pairs on a busy client: 26 / 40 / 23 / 38 / 12 / 34 samples
against 40 every time — 28 % fewer on a client being played, and 3–6 samples instead of
40 on an idle one, where the park wins at once.

It also answers BETTER. On the busy client the full sweep's winner was an address seen
**once or twice** in four of the six runs — noise, and two candidate addresses 192 bytes
apart (two different wait syscalls) took turns. The gate accepts ±16 bytes, so a
one-sighting winner aims it at a spot the thread rarely returns to, which is the shape of
#1994. Requiring three sightings and a clear lead answers only when the evidence is real.

### Still open

* **The gate is aimed at ONE park, and the client has two.** The A/B above kept turning
  up two dominant ntdll addresses 192 bytes apart. Accepting both learned parks would
  roughly double the hit rate — halving both the suspensions per hijack and the wait —
  but widening the gate is the thing that keeps the client alive, so it is a decision for
  the person and not an agent's. Nothing here does it.
* **The only other lever is FEWER hijacks.** 89 % of them are `DoString(bytes)`, one per
  Lua chunk: 40 638 chunks in the same window. Cutting suspensions at scale means running
  fewer chunks, which is a question about what the panel does, not about how it attaches.
* **The A/B nobody has run.** With the races of #2665 removed and the burst of #2667
  spread out, the honest next step is a day of the panel against the days recorded here —
  specifically, how many restarts kill the client within two minutes (it was six of nine).
