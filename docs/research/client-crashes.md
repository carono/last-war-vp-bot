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
