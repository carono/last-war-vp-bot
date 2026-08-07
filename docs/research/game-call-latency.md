# What a press costs, from the button to the game (task #1230)

The complaint was exact and easy to reproduce: press a coordinate in the panel and the
game starts moving about a second later, while doing the same thing by hand inside the
game rebuilds the screen at once.

Everything below is measured on the live client, not reasoned about. The probes are in
`results/perf1230/` and can be re-run at any time against a warm daemon:

```
C:\Python312\python.exe tools\dev\call_latency.py                  # this client
C:\Python312\python.exe tools\dev\call_latency.py --port 47655     # the other one
C:\Python312\python.exe tools\dev\call_latency.py --patient        # the way it was
```

(The one-off probes the numbers below came from are in `results/perf1230/`, which is not
committed; `tools/dev/call_latency.py` is the keeper — it is the one worth running again
the next time somebody says the panel feels slow.)

The trick that makes the chain measurable is that a chunk's own log line IS the instant
the game reacted: the chunk ends with `Debug.LogError("ACT …")`, so a watcher tailing
`Player.log` from a second thread times the reaction independently of whatever the
caller is doing.

## The chain, link by link, with a number on each

Measured, not guessed at — the panel's own links against a live daemon
(`results/perf1230/panel_chain.py`), the rest as above:

| stage | cost |
| --- | --- |
| `needs_foreground` — does this scenario click at the screen? (reads the file) | 0.19 ms |
| `resolve_action` — find `actions/<name>.md` | 0.07 ms |
| read + `prepare_source` + `parse_text` — the whole interpreter front end | 0.15 ms |
| `new_context` | 0.001 ms |
| `up()` — is this profile's daemon there? (loopback connect) | 0.33 ms |
| `claim` — acquire + release of the game lease | 1.8 ms |
| daemon protocol (connect + JSON + reply) | 0.7 ms |
| **the hijack: park the main thread, run the call** | **~1 frame, TWICE per chunk** |
| the game runs the chunk and writes its line | included in the above |
| **`settle` — a fixed `time.sleep` after the call** | **0.1 – 1.6 s, always paid in full** |
| **a chunk the panel ran only to decide what to press** | **a whole extra call** |

Everything the panel does before it reaches the game adds up to under three
milliseconds, and that includes the parser and the lease. Nothing there was ever the
problem — which is worth writing down, because it is where one would naturally look.

The lease deserves its own line, because it HAD been the problem three days earlier: a
connect to a daemon that is not there is DROPPED rather than refused, so it used to sit
out its whole timeout on the Tk thread, once per press (#1226). Against a daemon that
IS there it is 1.8 ms, and against one that is not it is now the cached
`UP_TIMEOUT_SEC`. Nothing left to take.

### 1. The pre-read in front of the jump (~600 ms of the second)

A coordinate that carries no server — a link clicked in the log, a row in «Командный
пункт», every waypoint of the map sweep — used to be answered by reading
`current_server()` first and only then sending the jump. Measured, five presses:

```
server-read   571 ms | game reacted to the jump at   648 ms | panel free at  2248 ms
server-read   576 ms | game reacted to the jump at   670 ms | panel free at  2265 ms
server-read  1295 ms | game reacted to the jump at  1377 ms | panel free at  2974 ms
```

The read itself was one call plus its 0.5 s settle; the jump could not start until it
came back. That is the second the person was seeing, and it was spent waiting for a
number the jump chunk can ask for itself.

### 2. `settle` was a sleep, not a deadline (0.1 – 1.6 s per step)

`settle` was time the caller spent sleeping between sending a chunk and reading the log.
It bought nothing: a chunk that logs thirty lines has all thirty in `Player.log` before
the call returns — read with **no** wait at all, thirty of thirty, twice over. The game's
answer is synchronous with the call.

What the settle did cost is worse than the wait itself. The daemon serialises every
chunk behind one lock, so a background tab refreshing itself held the game for six
tenths of a second in front of whatever the person pressed next; and the panel's lease
is held for the whole of an action, so a jump left the button «занято» for 2.2–3.0 s
after the game had already moved.

### 3. The interpreter: a press that began with a reading

`script_engine` itself is not slow — the whole front end (find the file, apply `ARGS`,
substitute, tokenise, build the context) is **0.4 ms**, and a scenario run against a
game that answers instantly costs 1.3–1.8 ms of Python. What it DID cost was round
trips and pauses:

```
run_action(help_ally)                  7 calls into the VM   (4 readings, 3 presses)
run_action(heal_units)                 6 calls               (3 readings, 3 presses)
```

`TAP <button> xall` read the button's own count, waited for the answer, and only then
pressed — two trips through the VM per press, and **the first thing a person's press did
was a reading**. So the game did nothing visible for the length of two calls, which is
exactly the shape of the complaint.

The count and the press travel in ONE chunk now (`script_engine.gated_chunk`): the gate
is checked and spent in the same instant, on the same thread, with nothing able to
change the count in between.

```
run_action(help_ally)                  4 calls into the VM   (3 presses, then the confirming read)
run_action(heal_units)                 3 calls
TAP steal_secret_task xall, nothing to rob, live:   191 ms, one call, no press
TAP call_help xall, one press to make, live:       1228 ms — 1000 of them the button's own pause
```

The loop's LAST reading stays: it is what quietly recovers a press the client's
long-press throttle dropped, and reading the count straight after a press — before the
game has applied it — would spend a quota twice. That is also what the per-button
`wait` protects, and those pauses are NOT ours to cut: they are the game's own settling
times, per button (`tools/lib/game_buttons.py`), and a recipe like the alliance gifts is
6 presses × 0.5–1.5 s of window-opening. With an instant game underneath,
`collect_alliance_gifts` is 4.3 s of pauses and 4 ms of interpreter.

Every gated chunk is checked against the game's own Lua before it is ever run — the
client compiles all 23 of them with `load` and throws the result away
(`tools/dev/check_gated_chunks.py`); the client's Lua is 5.3, so `loadstring` is gone.

### 4. The floor: a call costs two of the client's frames

This is the part that cannot be argued away, and it is the answer to "why is it not
instant". A chunk reaches the Lua VM in TWO thread hijacks — one to build the managed
string, one to invoke `SafeDoString` — and each one waits for the game's main thread to
reach the safe park, which it does once a frame.

Sampled with the client's own `Time.deltaTime` logged by the very chunk being timed:

```
frame    p50 16.9 ms          reaction p50 34.6 ms      reaction / frame  p50 2.12
frame    p50 47   ms          reaction p50 75   ms      reaction / frame  p50 ~1.6
```

Two frames. At 60 fps that is 33 ms and nobody will ever feel it; at 21 fps — a client
sharing a GPU with a second one — it is 75 ms. **The client's frame rate sets the floor
under every press**, which is worth remembering before blaming the panel for a slow
day: `Time.deltaTime` is one `READ_LUA` away.

Polling granularity is NOT part of that floor, which was worth proving rather than
assuming: sampling the park five times faster (2 ms instead of 10) measured the same
2.06 frames, because the wait is for the frame and not for us to look — and each sample
suspends and resumes the render thread, so the finer sampling was reverted. The two
waits that were tightened (`START_POLL`, `CALL_POLL_FAST` in `tools/lib/hijack_call.py`)
read a byte out of our own region while the game runs freely, and cost it nothing.

## What was changed

* **`lua_actions.jump_to_coord(x, y, server=None)`** resolves the server INSIDE the
  chunk (`current_server_expr()`). One trip to the VM instead of two, and the line it
  logs says which server it landed on. `panel/runtime/daemon.py` no longer reads it
  first; `script_engine`'s `JUMP` no longer falls back to `HOME_SERVER`, which is 0 on a
  machine that never set it.
* **`settle` can be a deadline** — `lua_eval.collect(..., early=True)`, carried to the
  daemon as `"early": true`. The wait ends as soon as the marker has landed and stopped
  growing, and never runs past `settle`.
* It is **opt-in**, and that is the load-bearing part of the design. Only the caller
  knows whether the marker line its chunk logs IS the answer or merely the
  acknowledgement of a request the SERVER will answer later (the treasure refresh, the
  command-post reads). Cutting the second kind short returns an empty list. The callers
  that ask for it — the jump, the current-server read, the scenario interpreter, the
  four data tabs, the resource balance, the rally-type read, the ghost-recon watch — all
  log their result at the end of the chunk.
* The scenario interpreter asks for it on **everything** it runs (`_run_lua`), because
  every chunk it builds ends by logging its own marker, and waiting for the GAME rather
  than for the answer is what the DSL's own `WAIT` is for — which is what the recipes
  already do after a scene switch.
* **`TAP … xall` reads and presses in one chunk** (`gated_chunk` / `_press_gated`), so
  the first call of a press is a press. The gate, the cap and the confirming re-read are
  unchanged.

## Afterwards, on the same client at the same frame rate

```
                                   reaction (game acts)      round trip (panel free)
one chunk, before                  p50  30 ms                p50 1700 ms  (settle 1.6)
one chunk, after                   p50  33 ms                p50   65 ms
the jump, before                   650 – 1400 ms             2200 – 3000 ms
the jump, after                    p50  33 ms                p50   63 ms
a gated press (TAP … xall), before ~2 calls before it pressed
a gated press, after               the first call presses    191 ms for a whole no-op round
```

The reaction is unchanged and always was the frame floor; what went away is everything
that was in front of it and everything that was sitting behind it.

**The limit, plainly.** A press cannot beat two of the client's frames — 33 ms at 60
fps, 75 at 21, and the client's frame rate is a `READ_LUA` away
(`CS.UnityEngine.Time.deltaTime`) when a day feels slower than another. Halving that is
possible and is written up below; nothing else in the chain is worth more than a
millisecond.

## The answer channel cost the game 120 ms a call (task #1232)

Found while measuring the above, and done as its own task because it changes how EVERY
chunk in the repository reports its result.

A chunk gets its answer back by writing a line to `Player.log`
(`Debug.LogError("ACT …")`) which the caller then reads. That line is not free, and it
is not free in a way nobody would guess — the cost is per CHUNK, not per line:

```
empty chunk                                p50  37 ms
100 000 additions in Lua, no logging       p50  37 ms
a DataCenter read, no logging              p50  36 ms
1 x Debug.LogError                         p50 163 ms
2 x Debug.LogError                         p50 160 ms
5 x Debug.LogError                         p50 155 ms
1 x Debug.LogError with 2 KB of text       p50 163 ms
```

So the first log line of a chunk costs about 120 ms and the rest are free. (This was
written as "120 ms of the game's own main thread". It is not — the call itself takes a
quarter of a millisecond there, and the cost is paid afterwards; see «What the 120 ms
actually is» below.) It is not the stack trace either: `Application.SetStackTraceLogType(Error,
None)` changed nothing, and a warning costs the same as an error. `Debug.Log` proper
never reaches `Player.log` on this build at all, which is why the codebase uses
`LogError` in the first place.

The answer arrives BEFORE that cost is paid — the reaction is still ~2 frames — so the
game is not slow to act. What the 120 ms delays is everything queued behind the call:
the daemon's lock, the panel's claim, and the next chunk of a recipe.

A private file instead of the game's log, measured on the same client:

```
CS.UnityEngine.Debug.LogError('…')                   p50 214 ms
CS.System.IO.File.AppendAllText('…', '…')            p50 103 ms
```

Half. The chunks keep their shape; what changed is the one place that builds the call
and the one place that reads the answer back.

### How it was done without touching 280 chunks

Every chunk in the tree still says `CS.UnityEngine.Debug.LogError('MARK …')`, and not one
of them was edited. What is swapped is the `CS` they see: `lua_eval.wrap_chunk` puts a
preamble in front of the chunk that declares a LOCAL `CS` — a table forwarding everything
to the real one except `UnityEngine.Debug`, whose three logging functions buffer the line
instead. The chunk itself runs inside a `pcall`ed vararg function, so a top-level `return`
still returns and `...` is still legal, and the buffer is written out in ONE
`File.AppendAllText` when it comes back. A line logged after that — by a callback the
chunk installed — is appended on its own.

The answer file sits beside `Player.log`, in this account's `LocalLow`: two clients are
two Windows accounts with two folders, so the separation that stops two daemons reading
each other's answers is the one their logs already have. It is emptied when it passes a
megabyte, between calls.

Three things keep the channel from being able to go silent, which matters more here than
speed does — this is how every chunk in the repository answers:

* a client whose xLua binding cannot reach `System.IO.File` logs to the game the way it
  always did, and `LuaEval.run` reads `Player.log` whenever the private file came back
  empty. Every reach into the CS bridge in the preamble is made inside a `pcall`,
  *including the member access* — `pcall(File.AppendAllText, …)` resolves the method
  before `pcall` can catch anything;
* a failing append does the same, per call;
* a chunk that RAISED has its error appended to the file, where `SafeDoString` used to
  swallow it in silence. It carries no marker, so it reaches a person reading the file
  and never a caller parsing lines.

One kind of chunk must stay on the old channel and says so with the sentinel
`LW_GAME_LOG` in a comment: one that INSTALLS something which logs later. The call shim
of `tools/lua_trace.py` is the one in the tree — it would capture the shadowed `CS` and
divert an entire recording into a file the tracer does not tail.
`LW_ANSWER_CHANNEL=log` puts the whole panel back on `Debug.LogError`.

Most of this needs no game to check: `tests/test_lua_answer_channel.py` runs the wrapped
chunks in a real Lua VM (`lupa`) against a stand-in `CS`, and compiles the wrapped form
of every chunk the repository can build offline — 75 of them — because a compile error
here would break all of them at once and `SafeDoString` would swallow it.

What a stand-in `CS` cannot answer is asked of the real one by
`tools/dev/check_answer_channel.py`, which is the acceptance for this and is worth
re-running after anything that touches `lua_eval`: the six shapes an answer comes in
(nothing, one line, two hundred lines, a chunk that raised, one 8 KB line, one with
Cyrillic/German/Turkish in it), each read back through BOTH channels and required to
come out **identical** — plus the dashboard's thirteen readings through its own parser,
three `read_*` scenarios through the interpreter, and a gated press on a button the
dashboard has just reported empty. It presses nothing and moves nothing, so it is safe
to run while somebody else is using the client. Live, all of it green:

```
nothing at all        file 0 line(s) | log 0   identical=True
200 lines, in order   file 200       | log 200 identical=True
a chunk that raised   file 1         | log 1   identical=True
one 8 KB line         file 1         | log 1   identical=True
unicode               file 1         | log 1   identical=True
the dashboard's readings, through its own parser     13/13 resolved
scenario read_graphics_load / read_squad_state / read_daily_checklist   all ok
gated press 'help_ally_all' / 'recruit_survivor'     gate left=0, nothing pressed
```

To measure the two channels against each other again on one client, minutes apart:

```
C:\Python312\python.exe tools\dev\call_latency.py                  # the file
C:\Python312\python.exe tools\dev\call_latency.py --via-game-log   # Player.log
```

### What the 120 ms actually is — it is NOT the game's main thread

Re-measured live while doing the change, on a much busier client than #1230's (three
profiles sharing one daemon, so read the MINIMUM and the low percentiles — the median is
measuring the daemon's lock, not the call). Sixty samples of each, `settle=0` and no
marker, so the round trip is the hijack and the chunk and nothing else:

```
                      min                p05      p10
empty chunk          90.5 ms            109.0    130.6
1 x Debug.LogError  135.1 ms  (+44.7)   208.7    275.0
5 x Debug.LogError  134.3 ms  (+43.9)   187.4    249.6
1 x AppendAllText    80.0 ms  (-10.5)   122.1    173.9
5 x AppendAllText    29.9 ms  (-60.6)    63.1    111.2
```

**#1230's shape reproduces exactly: one log line and five cost the same** (135.1 against
134.3), and the file writes cost nothing at all — five of them land under the empty
chunk's own floor. The saving from swapping the channel is 55 ms at the minimum here and
about 100 at p10, against #1230's ~120 on a quieter client.

**On a REAL chunk it is harder to see than that, and worth saying so.** The same pairing
run against the dashboard's own thirteen readings, thirty pairs, alternating:

```
after  (private file)   min 236.9   p10 374.4   p25 484.7   p50 677.4 ms
before (Player.log)     min 328.1   p10 387.0   p25 425.7   p50 630.3 ms
saved                      +91.2       +12.6       -59.0
```

Ninety milliseconds at the minimum, and nothing distinguishable above p10 — on a machine
where three profiles share one daemon, so most of the distribution is measuring the lock
rather than the call. The controlled comparison above is the honest measurement of the
effect; this one is the honest measurement of **how much of it a person gets back on a
busy box, which is less than the headline**. Re-run both on a quiet client before
quoting a number at anybody:

```
C:\Python312\python.exe tools\dev\call_latency.py
C:\Python312\python.exe tools\dev\call_latency.py --via-game-log
```

But the sentence #1230 wrote around those numbers — *"the first log line of a chunk costs
about 120 ms of the game's own main thread"* — **is wrong**, and it is worth correcting
because it points anybody optimising this at the wrong thing. Two measurements say so:

* **timed inside the VM, on the main thread itself**, with
  `System.Diagnostics.Stopwatch` (10 MHz) around each call: `Debug.LogError` takes
  **0.18–0.26 ms** and `File.AppendAllText` **0.20–0.28 ms**. Neither costs the main
  thread anything. (`Time.realtimeSinceStartup` is frame-cached on this build and reads
  0.00 for both — it cannot measure this.)
* **timed as visibility**: a chunk that writes BOTH, the log line first, then polling the
  two files 500 times a second — the log line becomes readable a median of **0.0 ms**
  after the file one (spread ±5 ms over ten runs). So it is not a flush delay either;
  Unity's line is in `Player.log` as promptly as ours is in the file.

The call is instant and the answer is readable instantly, yet a chunk *containing* one
costs the caller 50–100 ms more, flat, however many lines it logs. So the cost is paid
**after the chunk returns, in the main thread's availability for the NEXT hijack** —
whatever Unity does with a log line at the frame boundary keeps the thread away from the
safe park the following call has to wait for. Which is also why it is per chunk and not
per line, and why nothing in the game looks slow while the panel does.

The practical consequences are unchanged — the channel is worth swapping and it was —
but two of them are worth spelling out. Chasing this further means looking at Unity's log
handler and the frame boundary, not at how much text a chunk logs. And a chunk that
writes its answer to the file is now genuinely free to write MORE of it: five appends
measured cheaper than one log line by a factor of four.

Also verified live, because eleven locales depend on it: both channels carry UTF-8
intact — Cyrillic, German umlauts and Turkish dotless i all survive the round trip
through the file and through `Player.log` alike.

## What is left on the table

* **One hijack per chunk instead of two** would halve the floor — 33 ms → 16 ms at 60
  fps. The shellcode would call `il2cpp_string_new` and then `il2cpp_runtime_invoke` in
  one borrowed frame, storing the string straight into the params array. It is also
  strictly safer than what is there now: today the fresh managed string sits unrooted
  between the two hijacks, where a GC could in principle take it. Not done here because
  16 ms is below anything a person can feel and the change is live shellcode on somebody
  playing.
* **The daemon holds its lock across the settle at all.** The lock is there because the
  hijack is not reentrant, and the settle is a wait AFTER the invoke — but two chunks
  reading the log at once would have to tell their lines apart, and every one of them
  writes under `ACT`. Worth doing only if the marker becomes per-call.

Done since, and struck off this list: the two background readers that held the daemon's
lock for the whole of their settle — the dashboard strip poll (`panel/__main__.py`) and
the trigger check (`panel/runtime/schedule.py`). Both are pure reads whose chunk logs its
own answer, and both ask for `early=True` now, so a press arriving while one of them is
waiting no longer sits behind it.

---

## A key press is a whole RUN (#1290)

The complaint the second time was the same sentence about a different thing: «нажимаю
кнопку, а реакция лишь через пару секунд» — the keyboard macros of
[`march-hotkeys.md`](march-hotkeys.md). Two seconds, and the guess offered with it was
that the pseudo-language and the scenarios were the cost.

They are not. **Parsing the recipe is 1.0 ms** — file, `prepare_source`, `parse_text`,
eleven statements. Everything else was two things this file already knows about: a wait
that was not needed, and round trips that did not have to be separate.

Measured live against a warm daemon, from `run_action` to the press landing in the game:

| stage | before | after |
|---|---|---|
| the hook, the queue, the worker thread | ~0 | ~0 |
| `claim` at `HUMAN` (#1288) | 3 ms | 3 ms |
| resolve + `prepare_source` + `parse_text` | 1.0 ms | 1.0 ms |
| **the link gate, `_require_link`** | **1990 ms** | **215 ms, then 0** |
| ├─ `target_pid` + `sockets_of` + `classify` | 20 ms | 20 ms |
| ├─ `game_kick.tip` (settle 0.4, no `early`) | 450 ms | 90 ms |
| └─ the clock (settle 1.0, no `early`) | 1055 ms | 90 ms |
| `LUA` — park which squad | 90 ms | 90 ms |
| `TAP macro_arm` | 90 ms | — |
| …and the 0.2 s it sat out afterwards | 200 ms | — |
| `READ_LUA armed` | 90 ms | — |
| `TAP macro_launch` / `TAP macro_send` ← **the march goes out here** | 90 ms | 60 ms |
| **from the key to the march** | **~2000 ms** | **370 ms cold · 125 ms warm** |

Three findings, in the order they are worth reading:

**1. A settle that is not a deadline is pure waiting, and two of them were in the gate
every scenario passes through.** `game_clock.read` and `game_kick.tip` both ask the
client about something it already holds — the time it thinks it is, the dialog on its own
screen — so the answer is in the file before the injection returns. `early=True` turned
1055 ms into 90 and 450 into 90. This is the same lesson as #1230 and #1287, found in a
third place; the way to look for the fourth is to grep for `ev.run(` without `early`.

**2. «Once per run» stops meaning anything when a run is a keypress.** The gate was
written for a recipe that then presses for a minute. A macro is a whole run that lasts a
fifth of a second, so the gate WAS the latency. The verdict is a property of the client
rather than of the run, so it is now cached per client for `LINK_VERDICT_TTL` (10 s) —
which is well inside the staleness the gate already lived with, since a run that passed
it a moment before a kick goes on pressing for its whole length regardless. A restart
(`QUIT_GAME`, `ATTACH_GAME`) drops it: that is exactly when the cached answer is about a
process that is gone.

**3. Three calls that read and press the same screen should be one.** `macro_arm` →
`macro_armed` → `macro_launch` was 270 ms of round trips plus a 200 ms pause, and the
correctness half is worth more than the milliseconds: the check and the press were 200 ms
apart, over a screen the person's own click had put up and could close in between.
`macro_send` reads the target, resolves the squad and presses the game's own launch in
one chunk, in one frame, and parks what it decided for the recipe to read back afterwards.

**What did NOT need changing.** The DSL, the scenarios, the player, the hook. #1290 was
allowed to take the macros out of the scenario system if the measurement asked for it;
the measurement asked for a `wait` to become a deadline and three calls to become one,
and both are ordinary work inside the rule. The abilities are still one file each.

**What is left on the table here.** The warm 125 ms is two calls: parking which squad,
then pressing. They are two only because `TAP` carries no arguments — the squad has to
be put somewhere the press can read it. A primitive that handed a button one value would
make it one call of ~60 ms, which is the floor of the channel itself. Not done because
60 ms is below what a person can feel and a new DSL primitive is a bigger change than the
thing it would buy.

Re-run it with `results/_t1290/measure.py` (not committed — a page of `perf_counter`
around the same public calls).
