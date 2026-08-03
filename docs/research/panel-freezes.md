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
Tk thread loses the lock back to the scanner every time). The only cures are not doing
the walk while the UI matters, or doing it in a separate PROCESS.

The panel does such a walk at every start: the game-status probe
(`panel/runtime/game_process.py`), and — since #1212 — the machine-wide child sweep
(`panel/runtime/children.py::sweep`), which additionally reads `exe()`, `environ()` and
`cmdline()` of every python process and is uncached. The stall report names it outright:

    STALL 1156 ms
      meanwhile 100% — panel-child-sweep: _pswindows.py:758 exe

The sweep took the second cure: it is a CHILD PROCESS now
(`ChildFactory._sweep` → `python -c "…_cli()"`), with its own interpreter lock and its
own five seconds, and it reports what it ended through the pipe the panel already reads.
The game-status probe is still on the panel's own lock.

psutil caches its process map, so the SECOND walk costs nothing — which is why this is
invisible to any measurement taken on a panel that has been open a while.

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

### 3. Why «280 ms» was true and useless

`Notebook.select()` QUEUES `<<NotebookTabChanged>>`. A stopwatch around
`_switch_profile` therefore stops before the switch has happened — it measures 0–5 ms.
The number that matters is the one taken after the event queue has drained; the bench
prints both, as `call` and `settle`.

Measured on a warm panel with both profiles already open, a switch settles in
**100–280 ms**. The same switch while a process walk runs, or to a profile that is not
open, is **7–14 s**.

## What is left

* **A switch to a profile that is not open builds its whole page** — fifteen tabs. Of
  that build, one tab is most of it: VS Duel at 2.4–8.3 s against 50–450 ms for every
  other tab, because its week is laid out (and re-laid out) as it is built. Building a
  tab's content on first show instead of at page build is the fix, and it is a change to
  the tab contract rather than to one tab.
* **A profile is silently not restored when a stale `panel.lock` is left behind** by a
  panel that was killed rather than closed. It reads as «open in another panel», so the
  operator's every switch to it pays the full build above.
* ~~The machine-wide child sweep belongs off the panel's own lock~~ — done in #1212: it
  is a subprocess (see §1). The game-status probe's walk is still on the panel's lock at
  every start, and is now the only one left.
