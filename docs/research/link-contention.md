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

### 2.1 …and where the injection's own second goes

Measured with the hijack counting its own phases (`tools/lib/hijack_call.py::STATS`), one
minute of an ordinary farming panel:

```
hijacks 241 in 60s: 53.34s (0.221 s/hijack) = park 52.47 + start 0.05 + call 0.82
                                            + free 0.00; 22.0 park tries each, 0 gave up
```

| phase | share | what it is |
| --- | ---: | --- |
| **park** | **98.4 %** | sampling the client's MAIN THREAD until its RIP is at the learned safe gate |
| call | 1.5 % | the managed call itself, in flight on the runtime |
| start, free | 0.1 % | the shellcode starting, and the RWX region being released |

**Nothing is slow. The panel is waiting for a coincidence.** The main thread is only
borrowed within ±16 bytes of one exact return address — the idle message-pump wait, which
is the provably safe instant — and it takes **22 samples at 10 ms** to catch it there.
That is 0.22 s a hijack, and there are **three hijacks per chunk** (241 hijacks over 80
calls in the same minute: the byte array, the constant `"lw"` string, and
`DoString(byte[])`), which is the 0.6–0.7 s of exclusive every call pays.

So the five-to-tenfold gap against `docs/research/game-call-latency.md` is explained, and
the old reasoning there is what has expired rather than been wrong. It says `PARK_POLL` is
deliberately not tightened because «the wait is for the frame and not for us to look» —
true when the park is caught in one or two samples. Twenty-two samples is thirteen frames,
not one: this client reaches that exact address in about 4 % of the samples, so the wait
IS for us to look.

Two cuts follow, neither of them taken yet and both wanting their own measurement:

* **one hijack of the three is a constant.** `il2_string_new("lw")` builds the same
  managed string on every single call. Caching it is a third of the injection — with a GC
  question to answer first: a managed string nothing roots may be collected under us.
* **the sampling rate.** Every sample suspends and resumes the game's main thread, so
  looking five times as often is not free for the CLIENT — it is the one number in this
  file that costs the player as well as the panel, and it must be measured on the frame
  rate, not assumed.

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
side is reaching this VM by socket rather than in process. **The machine it was measured on had ONE client with TWO profiles open on it, and the
first reading of that was WRONG — the correction is worth more than the observation.**
`Get-CimInstance Win32_Process -Filter "Name='LastWar.exe'"` answers a single pid, in one
session, while the panel runs `--profile <a> --profile <b>`; from that it was written here
that two schedules were doubling every load in this file. They were not, and the way to
tell is to measure the second profile rather than to reason about it:

```
python3 tools/dev/link_holding.py --profile <a> --hours 2   held 3273 s = 45.5 %, 252 runs
python3 tools/dev/link_holding.py --profile <b> --hours 2   held    0 s =  0.0 %,  31 runs
```

The second profile held the client for **zero seconds and made zero calls** across two
hours. Its 31 runs are all `launch_game`, each failing at once with the game's own
instruction — nobody is logged on as that account, so it has no Windows session, no
client and no daemon on its port. Its config is CORRECT and always was: its own
`daemon_port`, its own Windows login, `rdp_session` on. Nothing sits on a foreign client
here; one account is simply not playing.

**So every percentage in this file is ONE profile's, not two profiles' halves.** The
lesson for the next reading of the same shape: «one client, two panels» is a hypothesis
about a CONFIG, and the config is not where it is settled — the second profile's own
`panel.log` settles it in one command, and a profile that is holding nothing says so by
holding nothing.

What a profile needs before it can have a client of its own is a Windows session that
only a person can create (`tools/rdp_instance.py --bring-up`), and a credential slot of
its own: Windows keys an RDP password by `TERMSRV/<address>` and by nothing else, so two
accounts brought up over one address cannot both have one (#1263).

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

## 7. The injection is three hijacks, and two of them were building rubbish

§2.1 named the lever and did not pull it: an injection is 98 % waiting for the client's
main thread to reach one exact address, an encrypted chunk pays **three** of those waits,
and only one of them is the actual `DoString`. The other two build arguments:

* `il2cpp_string_new("lw")` — the chunk NAME, the same two characters on every call the
  panel has ever made;
* `il2cpp_array_new(Byte, n)` — a `byte[]` that is filled, read once inside the very same
  injection, and never looked at again.

Both are now built ONCE per attach and rooted with a pinned GC handle
(`tools/lib/xlua_route.py::il2_string_pinned`, `::il2_bytes_reused`). Pinned because a
cached managed pointer is only a pointer while something forbids the collector moving or
reclaiming the object; the handle is never freed, since the attach ends when the client
does. Each call then writes the chunk's bytes into the array's body and its LENGTH into
the header field the managed side reads — two process-memory writes, no call into the
runtime. A byte array holds no references, so the collector never walks its contents and
its real size lives in the collector's own header rather than in that field; the field's
offset is PROVED against a fresh array rather than assumed, and a build that answers
differently falls back to allocating one a call and says so in the log.

Reusing the array is only safe because the whole of `lua_eval.LuaEval._send` runs under
the run lock: the array is filled and consumed inside one injection, so nothing can be
halfway through reading it. **A caller that means to overlap two chunks must use
`il2_bytes_new`** — that is the one rule this optimisation adds.

### What it moved, measured on the live panel the same hour

| | before | after |
| --- | ---: | ---: |
| hijacks per call | 2.9–3.7 | **1.0** |
| seconds per hijack | 0.24–0.32 | **0.015–0.057** |
| park samples per hijack | 23–31 | **1.5–4.2** |
| inject, per call | ~0.73 s | **~0.037 s** |
| a call, end to end | 0.80–1.19 s | **0.054–0.130 s** |
| wait for the run lock, per minute | 65–100 s | **0.03–0.22 s** |
| `assist_secret_task` | 15 calls in 24 s | 16 calls in 4 s |

**A tenfold cut out of a threefold change, and the extra factor is the interesting part.**
Removing two hijacks can only remove two thirds of the injections; what also fell is the
price of the one that remains — 27 park samples down to 2. The explanation the numbers
support is a feedback loop the panel was driving itself: every sample SUSPENDS and resumes
the game's main thread, three hijacks a call meant ~66 suspensions per call, and a main
thread being interrupted that often does not reach its idle message-pump wait — which is
the only address the gate accepts. Fewer hijacks, more idle, cheaper hijacks, fewer still.
The control is in the log: a restart at 09:59 with the old code left the park samples at
23–31, and the restart that shipped the first half took them to 1.7–3.0 within a minute.

### What that does to the rest of this file

Every number in §1–§4 was taken at ~1 s a call. At ~0.1 s a call:

* **the queue is gone as a measured thing.** The run lock's `wait` was 53–71 % of a call
  and is now 0.03–0.22 s per MINUTE. Nothing is standing behind anything.
* **§5's atomic blocks stand unchanged.** They are correctness, not cost, and a cheaper
  call makes the windows they protect no wider.
* **moving the claim from the run to the call (§6.5) is now fairness only, and small.**
  It was already «not what turns 52 % into single figures»; with the calls a tenth of
  their price the case for it is a 137 s `radar_full_cycle` not making a rally join wait,
  and that is worth deciding on its own merits rather than as a cure for a queue.
* **the socket door (§4, §6.2) is still unexplained** and is still the next thing to open.

### The catalogue, twenty minutes later

The same probe that produced §1's table, over 10:45–11:05 with the change in:

| scenario | §1 avg s a run | after | calls | s a call |
| --- | ---: | ---: | ---: | ---: |
| `radar_full_cycle` | 137.3 | **17.0** | 23 | 0.22 |
| `board_alliance_train` / `exchange_treasure_pieces` | 42.3 / 31.4 | — / **2.5** | 7 | 0.14 |
| `do_radar_marches` | 38.0 | **8.0** | 10 | 0.15 |
| `help_ally` | 3.2 | **0.9** | 17 | 0.53 |
| `work_secret_tasks` | — | 44.0 | 170 | **0.33** |

**And it moved what the remaining hold is MADE of, which is the next thing to argue
about.** `arena_3v3_battles` held the client 54 s and spent 4 of them in the VM: the other
50 are its own `WAIT`s. That is precisely the «idle exclusive» §1 said did not exist — and
§1 was right at the time, because at a second a call the VM swamped everything else. It
does not any more, so a run's own pauses are now the biggest thing holding the client for
nothing.

**Handing it back during those pauses is NOT a free change**, and the reason is §5's list.
The machinery exists and is wired up already — `claims.demand` / `claims.wanted` /
`panel/runtime/host.py::yield_hook`, called between statements, between the presses of a
repeat and between the polls of a `WAIT` — but it is given to DETACHED runs only. Giving
it to an ordinary background errand would let a press through in the middle of a series
that §5 says may not be broken, including one whose entry names a `WAIT` explicitly:
«refilling a squad → sending it again — the `WAIT 0.4` between them is a pause, not a
guard». So the honest order of work is the operator's own third point: **name the atomic
blocks in the recipes first** (a marker the interpreter reads, so a run cannot park inside
one), and only then let ordinary runs step aside. That is a decision, not a tidy-up, and
it is left to the person.

## 8. The chat was the largest unclaimed caller of all (#2594)

§3 measured that a third of the traffic ignores the claim. This is who most of it was,
and what it cost. Measured off one profile's own `panel.log`, **2026-09-03 19:53 →
2026-09-06 23:35** (3.16 days), before the change:

| ability | runs | median | p90 | max | link held |
|---|---|---|---|---|---|
| `translate_chat_batch` | 1538 | 5 s | 11 s | **127 s** | 11 071 s |
| `read_chat_history` | 7 | 8 s | 12 s | 12 s | 50 s |
| `read_chat_rooms` | 47 | 0 s | 1 s | 20 s | 33 s |
| `fetch_chat_history` | 5 | 5 s | 6 s | 6 s | 27 s |
| `translate_chat_message` | 10 | 4 s | 5 s | 5 s | 41 s |
| `send_chat_message` | 10 | 2 s | 3 s | 3 s | 19 s |
| **chat, all of it** | **1617** | | | | **11 241 s** |

11 241 s of 112 033 s of all scenario time — **10.0 %** of everything the panel played,
for an ability whose own work is one call, one wait and two reads. `translate_chat_batch`
is nominally a 3-second recipe; its median was 5 s and its p90 11 s.

The gap is entirely contention, and it had three separate authors:

1. **No claim at all.** The tab reached the game through `rt.actions.play(...)`, which
   takes the FOREGROUND claim (for a vision recipe) and no game claim whatever. So the
   chat's calls interleaved into a timer's run, using whatever lease token the runtime
   held — and the two took the lease off each other. **16** runs in the window ended
   «lease lost — it expired or was taken by default/timer», and the regain hook's 90-second
   ceiling is where the 127-second maximum comes from.
2. **No `SHARE`.** What the chat DID hold, it held across its own `WAIT 3` — the game's
   translator thinking — which by §7's own argument is the biggest remaining kind of
   idle exclusive.
3. **A press that gave up.** `play_async` refuses outright when the holder is of equal
   rank, so a person's typed line was DROPPED: **8** «занят» in four minutes on
   2026-09-06 for one message, while `default/web` held the client at `HUMAN`.

…and a fourth that was not contention at all: **61** chat runs in the window were turned
away by #2446's gate («статус не зелёный»), which is «чат молчит, пока фарм чинится».

**What was done.** All six recipes declare `SHARE`; the five readings go through
`PanelRuntime.play_now` — `play_async` with the thread taken out, so the same gate, the
same relaunch lock and the same reserve/lease dance apply and the Outcome comes back in
the caller's own hand; a person's press of a sharing recipe is no longer demoted to
`claims.SHARED`; a sharing run queues behind an equal instead of dying; and the gate has
a chat exception, narrow to «the panel still reaches the client»
(`panel/runtime/gate.py::CHAT_ACTIONS`). Pinned by `tests/test_panel_chat_thread.py`.

**This is also the first ordinary — non-detached — caller to get the step-aside hook**,
and it is legal under §5 for the reason §5 gives: no chat recipe opens a window, and none
of them is an atomic series. `translate_chat_batch` parks between its ask and its read,
and the answer waits for it in `_G.__LW_TRB` in the client's own Lua state.
