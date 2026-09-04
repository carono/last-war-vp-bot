# What the panel's hold on the game actually costs (task #2404)

The complaint was architectural and stated in one sentence: «линк захватывается на весь
прогон, а не на вызов — поручения стоят в очереди друг за другом». The reasoning behind
it was that only the conversation with the game's Lua VM is synchronous, that one such
conversation is «миллисекунды/доли секунды», and that everything else a run does — its
waits, its `IF`s over values it already has, its logging — holds an exclusive for
nothing.

**The first half is right and the second half is wrong by three orders of magnitude, and
that changes what is worth doing.** Everything below is measured on the live client over
2026‑09‑03/04, not reasoned about.

## How to re-run all of it

Two probes, both permanent:

```
python3 tools/dev/link_holding.py --hours 12          # runs, holds, and where they went
python3 tools/dev/link_holding.py --from "…" --to "…"
grep 'calls .* in .*s:' profiles/<name>/debug.log     # what one call costs, once a minute
```

The first parses `panel.log`, which is a complete stopwatch and needs no instrumentation
added — `> action:` / `< action:` bracket a run and every DSL step is timestamped inside
it. The second is written by `panel/runtime/lua_service.py::_say_timing` off the counters
`tools/lua_daemon.py::CallTimes` keeps: the minute's calls, split three ways, plus how
many of them carried no lease at all.

## 1. How much of the day is spent holding the client

One profile, 12 h ending 2026‑09‑04 05:00, farming normally:

| | |
| --- | --- |
| window | 12.00 h |
| held by a scenario run | **22 590 s = 52.3 %** |
| runs | 2 220 |
| claims turned away («занят», «пропуск — панель занята») | ~2 700 |

The ten costliest, and where each run's seconds went:

| scenario | runs | held s | % of window | avg s | in VM calls | waiting | local |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `join_rally` | 271 | 5 234 | 12.1 | 19.3 | 89 % | 8 % | 3 % |
| `auto_treasure` | 276 | 4 476 | 10.4 | 16.2 | 98 % | 0 % | 2 % |
| `read_server_info` | 221 | 2 372 | 5.5 | 10.7 | 100 % | 0 % | 0 % |
| `radar_full_cycle` | 15 | 2 059 | 4.8 | 137.3 | 84 % | 2 % | 13 % |
| `help_ally` | 630 | 1 999 | 4.6 | 3.2 | 100 % | 0 % | 0 % |
| `board_alliance_train` | 38 | 1 607 | 3.7 | 42.3 | 63 % | 6 % | 31 % |
| `rally_monitor` | 443 | 1 572 | 3.6 | 3.5 | 61 % | 0 % | 39 % |
| `assist_secret_task` | 10 | 783 | 1.8 | 78.3 | 100 % | 0 % | 0 % |
| `do_radar_marches` | 20 | 759 | 1.8 | 38.0 | 66 % | 8 % | 26 % |
| `exchange_treasure_pieces` | 22 | 690 | 1.6 | 31.4 | 66 % | 12 % | 22 % |

**89–100 % of what a run holds the client for, it holds INSIDE a call into the game.**
The local half of the premise — waits, branches, logging — is 0–3 % of a rally join and
under a third of the worst offender. There is no idle exclusive to give back: a claim
released between statements would be re-taken a few milliseconds later, by the same run,
for the same call.

A note on reading the table: the gap between two logged steps belongs to the SECOND of
them, because a step is written to the log once it has happened (`READ_LUA joined = 0`
carries the answer). Charging it to the first reads every recipe backwards and was the
first version of the tool — the tell was `read_server_info`, a scenario made of nothing
but reads, reporting one second on the wire out of 2 372.

## 2. What one call into the VM costs

`CallTimes` splits every chunk three ways: **wait** (queued behind another chunk's
injection, the run lock in `tools/lua_daemon.py`), **inject** (the thread hijack itself,
under that lock), **harvest** (reading the answer back, which holds no lock at all).

Four consecutive minutes, live:

```
calls 54 in 62s: 195.91s total (3.628 s/call) = wait 138.77 + inject 54.05 + harvest 3.09
calls 56 in 60s: 142.19s total (2.539 s/call) = wait  82.46 + inject 57.53 + harvest 2.19
calls 57 in 60s: 164.09s total (2.879 s/call) = wait 103.00 + inject 58.89 + harvest 2.20
calls 92 in 63s: 120.42s total (1.309 s/call) = wait  64.31 + inject 51.78 + harvest 4.33
                                       … found 1.22 already in flight, 34 unleased, busiest 5
```

| part of a call | share | what it is |
| --- | ---: | --- |
| wait for the run lock | 53–71 % | somebody else's chunk was in the hijack |
| **inject** | 28–43 % | **0.56–1.03 s** — the hijack, and the only genuinely exclusive part |
| harvest | 1.5–3.6 % | 40 ms — the answer is already in the file |

**One injection is 0.56–1.03 s, not «доли секунды», and it is not divisible.** A chunk
reaches the Lua VM through thread hijacks that each wait for the game's main thread to
reach its safe park — once a frame, measured at 2.06× the client's own `deltaTime`
(`docs/research/game-call-latency.md`) — and the encrypted-chunk path takes three of them.
The client is not the reason: it reports `targetFrameRate = 60`, `vSyncCount = 1` and a
`deltaTime` under 3 ms.

So the machine's ceiling is **about one call a second**, and the panel spends the whole
day sitting on it. That is the queue people see. Moving the claim from the run to the
call would move the queue from `claims.py` to the run lock and change nothing about its
length.

## 3. A third of the traffic ignores the claim entirely

The same minute: **34 of 92 calls (37 %) carried no lease**, and up to **5 chunks were in
flight at once** against a claim that is supposed to let one run drive the game.

That is not a bug in the lease — it is its documented rule: an empty token is «unleased»
rather than «no lease», and an unleased run is let straight through
(`tools/lib/game_lease.py::check_run`). What it means for this task is that the exclusive
being argued about is already advisory: the readings a tab takes, a wire handler's
lookup and a child tool's probe queue at the run lock beside whatever holds the claim,
and every one of them costs the holder most of a second of `wait`.

## 4. Who is actually making the calls

The per-minute line names its callers now, grouped by what a thread is FOR (a scenario
worker is named per run, so counted raw one errand reads as sixty different callers).
Three consecutive minutes on the live panel:

```
callers: thread:_serve=48, thread:work=6, thread:_read_work=6, panel-rally=4,
         panel-trigger=4, thread:_loop=3, trigger-poll-session_kick=3,
         panel-timers:default=3, thread:_day_work=3
callers: thread:_serve=34, thread:work=5, panel-trigger=4, trigger-poll-treasure_auto=3,
         trigger-poll-session_kick=3, thread:_day_work=3, thread:_read_work=2
```

**Two thirds of the traffic arrives through the socket door**, not from a scenario this
profile ran — and `panel.log`, which is where every «панель занята» investigation starts,
cannot see a single one of those calls. They are not all capture tools either: the chunks
coming through it include scenario reads (`DataCenter.LWAllyStationDataManager…`, the
alliance-train recipe, and the `__v0` locals of a merged read), so something on the panel
side is reaching this VM by socket rather than in process. **And the machine it was measured on had ONE client and TWO profiles open on it**, with
thirteen child tools between them (`Get-CimInstance Win32_Process -Filter
"Name='LastWar.exe'"` answered a single pid, in one session, while the panel was running
`--profile default --profile sooperj`). That is the accident `panel/runtime/claims.py`
opens by describing — two profiles are two views of one client — and it doubles
everything above: two schedules, two sets of listeners, two fleets of captures, against
one VM that can take about 1.4 calls a second. Whether it is deliberate here is the
operator's to say; it is written down because a measurement of contention taken on such a
machine reads high for a reason that is not in any code.

Telling the door's callers apart properly is its own task. What is settled is that **the
scenario catalogue is a minority of the calls**, so tuning recipes alone cannot reach the
ceiling.

## 5. What may NOT be cut — the atomic blocks

Whenever the claim does move from the run to the call, these are the series that must
still be held whole. **The list is the operator's, decided question by question**, and it
is written down here so the next agent does not take one apart by accident.

| series | why it may not be broken |
| --- | --- |
| a zombie march being re-aimed | the window is 0.08–3.4 s; a chunk in the middle of it and the march is already somewhere else |
| picking a squad → sending the march | somebody else's run spends the squad between the two, and the march goes out empty or not at all |
| raising the rally popup → `OnClickStartMarch` → picking the squad → `OnCheckTime` | the popup carries the whole banner; closing or losing it mid-way loses the rally |
| parking arguments in `DataCenter.__lw_*` → the `TAP` that reads them | another run overwrites the parking, and the press acts on somebody else's targets (`join_rally`, `auto_treasure`, both robberies) |
| refilling a squad → sending it again | the same shape as picking a squad: another run spends the army that was just fetched. The `WAIT 0.4` between them is a pause, not a guard |
| ONE ROUND of `TAP <btn> xall` — «read the quota left → press» | the press would otherwise go out against a stale number |

And two that deliberately are NOT atomic, for the reason each names:

* **`TAP <btn> xall` as a whole.** Every round re-reads the quota from the game, so a run
  that ate part of it in between cannot cause a wrong press — the next round simply sees
  less. The round is atomic; the loop is not.
* **`assist_secret_task` as a whole.** 150 calls under one claim is precisely what makes
  the panel unresponsive, and a run interrupted between two helps spoils nothing: each
  help is independent, the state is the game's, and a repeat is refused by the server
  because the help has already happened.

## 6. What was done, and what it moved

Read the measurement in the order it puts them, largest first:

1. **Make fewer calls.** Done for the catalogue: the DSL grew `READ_LUA <expr> INTO a, b,
   c` (`docs/dsl.md`), which reads several Lua return values in ONE hijack, and thirteen
   recipes stopped asking one question at a time — `join_rally`, `auto_treasure` and
   `read_server_info` by hand, the radar cycle and eight ordinary errands mechanically.
   `join_rally` also lost the confirmation poll that looked six times after every send,
   twice per run: a ceiling written when a read cost 0.14 s had grown into seven seconds
   of exclusive a pass.

   Measured on the same probe afterwards: `read_server_info`, the status probe that runs
   every few minutes, went from **3.0 calls and 10.7 s a run to 2.0 calls and 4.2 s**;
   `auto_treasure` from 13.2 calls a run to 10; `join_rally` from 10.7 to 9.5 with its
   worst path shortened by twelve. The price of a call did not move, because nothing here
   could move it.

2. **The socket door (§4)** — now the biggest single source, and unexplained. Whoever
   takes it next has the histogram already.

3. **Decide the gates before claiming.** «Сейчас не час дрона», «отряд не тот», «квота
   выбрана» — a run that takes the client to find out it has nothing to do costs a claim,
   a context, and at least one call.

4. **The injection itself.** 0.5–1.0 s against a client reporting 60 fps and a 3 ms frame
   is five to ten times the two-frames-per-hijack the chain is supposed to cost
   (`docs/research/game-call-latency.md`). Nothing in this task explains the difference,
   and a five-fold cut there would end the queue outright — it is the largest unopened
   lever there is.

5. **The claim itself, last.** With calls at a second each, per-call claiming buys
   interleaving at call granularity, not parallelism: a 137 s `radar_full_cycle` should
   not make a rally join wait, and that is worth having — but it is fairness, not
   throughput, and it is not what turns 52 % into single figures.
