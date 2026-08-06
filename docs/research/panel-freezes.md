# Why the panel freezes, measured (#1211)

The panel had been reported as freezing when the operator switches profiles. It had
been «fixed» twice — the page build was cut into steps (#1208) and the switch was timed
at 280 ms — and it went on freezing. This is what the freeze actually consists of,
measured on a live panel rather than on a cold start, and the tools that measured it.

## How to measure it yourself

Two things, both permanent, both off unless asked for.

**`panel/runtime/stall.py`** samples the Tk thread FROM ANOTHER THREAD. A heartbeat
armed with `after` stamps the clock from inside the event loop; a sampler wakes every
10 ms and, whenever the stamp is older than the threshold, grabs the main thread's stack
until the beat returns. It also records what every OTHER thread was running meanwhile,
which is what turned this investigation around. Reports go to stderr and the debug log:

    LW_PANEL_STALL_MS=200 C:\Python312\python.exe -m panel

**`tools/dev/panel_switch_bench.py`** opens the real panel and drives the switches:

    C:\Python312\python.exe tools\dev\panel_switch_bench.py --profiles a,b --open-only a ^
        --rounds 2 --threshold 250 --trace-build

`--open-only` leaves the second profile closed, so a switch to it has to BUILD its page
— which is what a switch does whenever a profile was not restored. `--trace-build` times
every staged build step. `--no-sweep` and `--no-force-redraw` are A/B switches for the
two suspects below. `--live` uses the real profile directory instead of copies.

## What a freeze is made of

### 1. A cold psutil walk on a background thread starves the Tk thread (40×)

The first `psutil.process_iter()` in a process takes **6.2–7.2 s** on this machine
(~300 processes). It is Python code holding Python's lock, so putting it on a thread of
its own does NOT make it free: for as long as it runs, everything the Tk thread does is
ten to forty times slower.

| | one ttk widget | VS Duel tab build |
|---|---|---|
| idle Tk thread | 1.0 ms | 180 ms |
| while a process walk runs | 37–74 ms | 8.9–9.7 s |

Lowering `sys.setswitchinterval` does not help (measured at 5 ms, 1 ms and 0.2 ms: the
Tk thread loses the lock back to the scanner every time). The cures are not doing the
walk while the UI matters, doing it in a separate PROCESS — or, as it turned out, not
doing an expensive walk at all.

The panel did such a walk at every start: the game-status probe
(`panel/runtime/game_process.py`), and — since #1212 — the machine-wide child sweep
(`panel/runtime/children.py::sweep`), which additionally reads `exe()`, `environ()` and
`cmdline()` of every python process and is uncached. The stall report names it outright:

    STALL 1156 ms
      meanwhile 100% — panel-child-sweep: _pswindows.py:758 exe

The sweep took the second cure: it is a CHILD PROCESS (`ChildFactory._sweep` →
`python -c "…_cli()"`), with its own interpreter lock and its own five seconds, and it
reports what it ended through the pipe the panel already reads.

psutil caches its process map, so the SECOND walk in a process costs nothing — which is
why this is invisible to any measurement taken on a panel that has been open a while,
and why the one walk that IS paid lands at start-up, while the tabs are being built.

### 1a. …and the walk did not have to be expensive (#1214)

The frame in the stall report is the answer: `_pswindows.py:758 exe`. On Windows,
psutil's `Process.name()` is `os.path.basename(self.exe())` and `exe()` is
`cext.proc_exe(pid)` — **one `OpenProcess` per process**, with a slower fallback whenever
the handle is refused. The names are not what is slow; opening four hundred processes to
read them is. Windows will hand over the whole table in one call, and it does not open
anything (389 processes, this machine):

| | cost |
|---|---|
| `psutil.process_iter(["pid", "name"])` | **3.96 s** (cold; 0.03 s warm) |
| `psutil.process_iter(["pid", "name", "cmdline"])` | **7.66 s** |
| `win32ts.WTSEnumerateProcesses(0, 1, 0)` | **0.027 s** (always — nothing is cached) |
| `psutil.net_connections("tcp")` | 0.002 s — never was the problem |

So `tools/lib/proc_table.py` is the one place the table is read: the terminal-services
enumeration where it can be had, `process_iter` as the fallback for a box that cannot be
asked (no pywin32, not Windows). The rule for callers is **narrow first, then open** —
take the names, keep the few you care about, and only then ask psutil for their
`cmdline()`, `environ()` or `create_time()`. Everything that runs in the panel's own
process was moved onto it, and the same-answer-before-and-after was checked each time:

| | before | after |
|---|---|---|
| `autostart.panel_pids` (the second-panel guard) | **15.26 s** | **0.058 s** |
| `children.sweep` (the machine-wide orphan pass) | **4.93 s** | **0.044 s** |
| `game_client.session_pids` (restarts, force-closes) | ~4 s cold | 0.044 s |
| `rdp_instance.click_dialogs` (a loop, twice a second, for two minutes) | ~4 s + 0.03 s a turn | 0.03 s a turn |

`tests/test_proc_table.py` pins it, including the part that would otherwise come back:
nothing under `panel/`, nor in the three shared modules the panel calls on its own
threads, may spell `psutil.process_iter` — checked as an AST call, so the docstrings
explaining why are not mistaken for the thing itself. Run it with `--bench` to take the
numbers above on another machine.

The subprocess sweep STAYS, and not out of politeness: on the fallback route the walk is
six or seven seconds again, and a cost that depends on the machine belongs in a process
of its own whatever this machine measures.

**The game-status probe was never the other half.** Measured cold at **55 ms**: it takes
its process list from `WTSEnumerateProcesses` and its sockets from `net_connections`, and
only reaches `process_iter` on a box that cannot attribute sessions at all. The line in
the old version of this file that said otherwise was written from the #1212 stall reports
and never re-measured.

### 2. The duel's text wrap was machine-wide, not the tab's

`panel/tabs/vs_duel.py` wraps its labels to the width of the day column they sit in, and
a ttk Checkbutton takes `wraplength` only through a STYLE. The styles were named
`VsDuelWrap<indent>` — and a ttk style belongs to the interpreter, not to the widget.
So configuring one re-laid out every widget wearing it: the other five days of that tab,
and the same tab in every other open profile, pages not even on screen. Each re-layout
fires `<Configure>`, which re-wraps, which re-lays out.

| | settle after the build | one window resize |
|---|---|---|
| one tab open | 1.1 s | — |
| three tabs open | 5.0 s | 4.4 s, in pages nobody was looking at |
| three tabs, after the fix | 4.0 s | 1.1 s |

Fixed by giving every day frame of every tab its own style namespace, and by refusing to
re-wrap a page that is not mapped (`on_show` wraps it when somebody actually looks).

### 3. Fifteen tabs were drawn so that one could be looked at (#1215)

A page is built when the panel opens and again the first time a profile is switched to,
and it drew every tab the profile had. The person is looking at one of them.

Measured by building a real page (the `_Harness` of `tests/test_panel_page_build.py`,
a temporary profile, `staged=False` so the whole build lands in one number):

| | tabs drawn | page build, median of 3 | first build (cold imports) |
|---|---|---|---|
| before | 16 | 1334 ms | 4216 ms |
| after | 4 | 471 ms | 1209 ms |

The four that are left are the EAGER ones — a capture that has to be listening before
anybody clicks. Everything else is `__init__` and a saved block handed over, some tens of
milliseconds for the lot, and the widgets are made when the tab is first shown. What that
costs when it is shown is what the tab always cost: 5–212 ms each, measured cold against
a fake runtime, and the duel's week (0.5 s) which had already moved to `on_show` in this
task's §2.

The contract is `PanelTab.LAZY` (`panel/tabs/base.py`), and it is the default rather than
something to opt into. What it asks of a tab is that four things answer before it is
drawn — its saved block, a trigger it declared, the phone's screen and the lifecycle —
and each of those has one line in the contract saying how. The half that would fail
SILENTLY is the block: `config()` reads widgets, so a tab with none has to hand back what
it was given (`stored_config`) or a panel opened and closed without a click would write
defaults over every tab's settings at once.

### 4. Why «280 ms» was true and useless

`Notebook.select()` QUEUES `<<NotebookTabChanged>>`. A stopwatch around
`_switch_profile` therefore stops before the switch has happened — it measures 0–5 ms.
The number that matters is the one taken after the event queue has drained; the bench
prints both, as `call` and `settle`.

Measured on a warm panel with both profiles already open, a switch settles in
**100–280 ms**. The same switch while a process walk runs, or to a profile that is not
open, is **7–14 s**.

## The other half, found later (#1226)

Everything above is about the Tk thread being BUSY. The complaint that came next —
«действия одного профиля блокируют интерфейс; на 3-4 аккаунта панель будет
парализована» — turned out to be about the Tk thread being the only door: a profile's
background work talked to the window on the window's thread, so N profiles' worth of it
queued behind the one event loop. The measurement, the two seams and what was done are
in `docs/research/multi-profile-panel.md` §12, and the tool that measures it is
`tools/dev/panel_thread_bench.py`.

Two things there belong here.

**A blocking call on the Tk thread is worth more than it looks in a total.** The
four-profile boot went 81.5 s → 8.6 s, and almost all of that was the queueing; the
blocking calls found alongside it were ~0.3 s of the total and were still worth every
one of them, because they are not spread evenly — they are a second of dead window at
the moment somebody presses a button. The list, with what each measured, is in
`multi-profile-panel.md` §12. The one to remember: **a connect to a local port nothing
is listening on is dropped on this machine, not refused**, so every «is my daemon there»
check cost its whole timeout, and two of those timeouts were 1 s and 90 s.

The second is about reading THIS tool's output:
**`stall.py::_PARKED` filters a thread out by the NAME of its innermost frame**, so a
thread blocked inside a C read called from a method of ours — `panel/childmon.py::_read`
sitting in `for raw in proc.stdout` — is reported as competing when it has released
Python's lock and is doing nothing at all. It was 32 of 43 reports' top «meanwhile» line
and it was noise. Discount any «meanwhile» whose frame is a function of ours that is
merely sitting in a blocking call.

## What is left

* ~~A switch to a profile that is not open builds its whole page~~ — done in #1215: the
  page makes every tab and draws the ones that have to be there, which is §3 above.
* ~~A profile is silently not restored when a `panel.lock` is left behind~~ — half done
  in #1215, and the half that was skipped was skipped on purpose. **The lock is not
  broken on the strength of a heartbeat.** It is an exclusive OS lock on a file in the
  profile directory, so the kernel drops it when its holder dies: a leftover `panel.lock`
  FILE holds nothing, and a lock that is genuinely held is held by a process that is
  genuinely there — usually a panel that has stopped answering its own event loop, which
  a heartbeat cannot tell from a busy one either. Overruling it would put two panels on
  one `config.json`, which is the failure the lock exists to prevent.

  What WAS wrong is that the refusal was silent. `Workspace.restore` runs before any
  session has been adopted, so `log.profile.held_elsewhere` was said into a log that did
  not exist yet and fell through to a stderr a windowed panel does not have. The note is
  kept now and said once there is a page, and it names the holder: an ordinary second
  panel reads as one line, and a lock whose heartbeat has been silent for an hour as
  another (`log.profile.held_stale`, with the pid and how long). The second is the one
  the person has to go and close — and until they do, this panel opening that profile
  anyway is the thing that must not happen.
* ~~The machine-wide child sweep belongs off the panel's own lock~~ — done in #1212: it
  is a subprocess (see §1).
* ~~The game-status probe's walk is still on the panel's lock at every start~~ — it never
  was, and the expensive walks that WERE are gone: #1214 took the process table off
  `psutil.process_iter` altogether (see §1a). Nothing in the panel's process now costs
  more than a few tens of milliseconds to ask what is running.
