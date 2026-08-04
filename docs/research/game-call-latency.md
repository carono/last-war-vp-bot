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

## The next big one: the answer channel costs the game 120 ms a call

Found while measuring the above, and left for its own task because it changes how EVERY
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

So the first log line of a chunk costs about 120 ms of the game's own main thread, and
the rest are free. It is not the stack trace: `Application.SetStackTraceLogType(Error,
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

Half. The chunks would keep their shape; what changes is the one place that builds the
call and the one place that reads the answer back.

## What is left on the table

* **One hijack per chunk instead of two** would halve the floor — 33 ms → 16 ms at 60
  fps. The shellcode would call `il2cpp_string_new` and then `il2cpp_runtime_invoke` in
  one borrowed frame, storing the string straight into the params array. It is also
  strictly safer than what is there now: today the fresh managed string sits unrooted
  between the two hijacks, where a GC could in principle take it. Not done here because
  16 ms is below anything a person can feel and the change is live shellcode on somebody
  playing.
* **Two background readers still hold the daemon's lock for their whole settle** — the
  dashboard strip poll (`panel/dashboard.py`'s `SETTLE`, passed at its call site in
  `panel/__main__.py`) and the trigger check in `panel/runtime/schedule.py`. Both are
  pure reads and both want `early=True`; a press that arrives while one of them is
  sleeping waits it out.
* **The daemon holds its lock across the settle at all.** The lock is there because the
  hijack is not reentrant, and the settle is a wait AFTER the invoke — but two chunks
  reading the log at once would have to tell their lines apart, and every one of them
  writes under `ACT`. Worth doing only if the marker becomes per-call.
