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

## Limits of this reading

* Windows' event 1000 does not say which client or which Windows session crashed. Four
  accounts ran; the case–control uses one profile's `panel.log`. That mismatch can only
  DILUTE the association, not manufacture it.
* The daemon logs (the clients in their own sessions) carry no timestamps, so they could
  not be joined to the event log at all; their hijack counts are volume evidence only.
* `panel.log` records the hijacks of the paths that log through the panel; hijacks made
  elsewhere are invisible to the control. Again a dilution, not an inflation.
