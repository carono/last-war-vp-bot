# The Lua daemon: what it buys, what it costs, and what «green» has to mean (#1287)

> На русском: этот файл — исследовательская записка, как и все в `docs/research/`.
> Список возможностей для игрока — `docs/farming.md`.

The question this answers, in the person's own words: *«Демон отвратительно контролирует
игру… если демон зелёный, я точно должен быть уверен, что панель работает. Нам вообще
нужен этот демон в принципе?»*

Twenty incidents' worth of patches went into the symptoms — #1268 (a daemon holding a
killed pid, six pointless CLIENT restarts), #1281 (`ensure()` asking a cache), #1286 (a
shutdown acknowledged and not carried out). This is the measurement that has to come
before the next one: **what the daemon is worth, what it breaks, whether anything else
would do, and what a hard guarantee would actually cost.**

Everything below is a number taken on this machine on 2026-08-07 against the live client
and the daemon the panel had started for it. How they were taken is §7.

---

## 1. What the daemon buys — measured today, not remembered

The claim in the code and in every note since is «~0.1 s warm against ~5 s cold». Both
halves needed re-checking on the current code, and both moved.

| what | median | n |
|---|---|---|
| one trivial chunk, warm daemon, `early`, `settle=0.5` | **60 ms** (min 48, max 68) | 15 |
| the same chunk, warm daemon, patient `settle=1.2` | 1351 ms | 5 |
| **building a `LuaEval` from scratch** (`{"op":"reload"}` — drop and re-resolve, inside the daemon's own already-privileged process) | **2282 ms** (2236 / 2282 / 2316) | 3 |
| a bare Windows interpreter start | 32 ms | 1 |
| `import lua_eval` | 1.4 ms | 1 |

So the cold price is **~2.3 s**, not five — but it is 2.3 s of *thread hijack and il2cpp
resolution against a running game*, and it is paid per call, not per session.

**How many calls is that a day?** One profile's `debug.log`, 2026-08-07, 16 hours:
**1 522** scenario primitives (`READ_LUA` / `LUA` / `TAP` / `GAME` / `JUMP`) plus
**3 068** dashboard readings — call it 4 600 chunk round trips, and that is a floor: the
status poll's own reads are not logged line by line.

| | 4 600 chunks/day cost |
|---|---|
| warm daemon (60 ms) | **4.6 minutes** |
| no daemon, a fresh `LuaEval` per call (2 314 ms) | **3 hours** |

Three hours a day of hijacking a game somebody is playing in, to do the same work.
And that is one profile on a day when the other two clients were not even logged on.

**One more thing the daemon buys, which is not about speed at all.** The attach is
privilege-sensitive: the same `LuaEval` build, run from a Windows interpreter launched
out of WSL without the panel's rights, fails in 6.1–8.7 s with `snapshot failed err=5`
three times out of three. Whatever drives the game has to be a process started beside the
client, with the client's rights, in the client's Windows session. A second account's
client lives in its own Windows login (`docs/research/multi-instance-rdp.md`), and
`GameLink._start_in_session` exists for exactly that reason.

**Verdict on question 1: the daemon is not an optimisation. It is the only affordable
way to drive the game at all.**

---

## 2. What it breaks

### 2.1 One lock, and the settle is inside it

`Daemon.run` takes `self._lock` and holds it for the whole of `LuaEval.run` — which
includes `collect`, i.e. the settle. The lock is right (the hijack is not reentrant); its
*extent* is not. Measured:

| the same foreground call | median |
|---|---|
| daemon idle | **60 ms** |
| behind 3 background readers each holding a patient `settle=1.2` | **3 855 ms** (min 3 247, max 4 793) |

**64× — and the foreground call itself did nothing different.** That is #1281's «0.14 s
free, 10–19 s under panel load» reproduced on demand. A patient call holds the lock for
~1 350 ms of which ~60 ms is the invoke: **95 % of the lock's occupancy is a sleep that
needs no lock.** `docs/research/architecture-audit.md` §1.1 already names the fix (hold
the lock over `_send` only, one answer file per call); it is unfinished because it needs
a live client to accept.

What is NOT the problem: the connections. The daemon serves every connection on its own
thread, so a `ping` costs **0.8 ms while three patient runs are queued on the lock** —
identical to an idle daemon. Adding sockets buys nothing; the lock is the hijack, not the
wire.

### 2.2 It is bound to a process id, and a restarted client is a new one

`LW_GAME_PID` pins the daemon to a client. A client restart is a new pid, and the daemon
went on holding the old one until something drove it into a call that failed twice over
— after which its rebuild failed too, and it sat wedged with the port still bound.

### 2.3 «Green» means «a port accepted a connection»

`GameLink.up()` is `socket.connect` and nothing else, and it is what the strip, the
phone's `/api/state`, the schedule gate and eleven other readers call. Measured:

| reading | median | what it actually proves |
|---|---|---|
| `up()` — daemon there | 0.29 ms | a socket is bound |
| `up()` — nothing there, `timeout=0.35` | 356 ms | (and 1 011 ms at the old 1.0 s default — #1226) |
| `ping` / `status` | 0.76 ms | the daemon's own thread is alive; the pid it *believes* it holds |
| `health()`-shaped (ping + the pid actually running) | 40 ms | those two integers agree |
| **a real chunk that must answer** | **62 ms** | the game ran it |

### 2.4 …and the reading was cached, so it could be stale on top of being weak

`up()` reuses its answer for `UP_CACHE_SEC`. Fixed for `ensure` in 1f6d14a (#1281); the
other thirteen callers still read the cached port.

---

## 3. What that adds up to, in one day of one profile's logs

2026-08-07, 01:17 → 17:17, one profile, read out of `panel.log` and `debug.log`:

| | count |
|---|---|
| client restarts (`не слышен серверу … перезапускаю` + recipe restarts + process gone) | **25** |
| «the daemon holds a client that is gone» detected by the panel | **17** |
| daemon restarts | **19** |
| errands that failed with `ClientGone` | **10** |
| recovery refused because a restart was too recent (cooldown) | **16** |

And the strip, 2 100 readings on an eight-second poll:

| strip line | readings |
|---|---|
| `game=up link=online daemon=warm` | 1 879 |
| `game=up link=lost  daemon=warm` | **186** |
| `game=up link=unknown daemon=warm` | 5 |
| `game=down link=offline daemon=warm` | **3** |
| `game=up link=online daemon=down` | 27 |

**194 of the 2 073 «warm» readings — 9 % — were taken while the client was not
up-and-online, and three of them while there was no client process at all.** One of those
three was on screen while this document was being written. That is the complaint, exactly
as reported, in the panel's own log.

**And the recovery, which does work, is slow.** Pairing each client restart with the next
«daemon ready»: **n=12, median 250 s, min 35 s, max ≈ 2.7 h.** Four minutes of deaf
farming per restart is the normal case, and the tail is unbounded because a second
restart inside the cooldown is refused (16 times today).

**What is already in flight, and is not re-proposed here.** #1286 — uncommitted in the
tree as this is written — adds `Daemon.follow_client` (a 5 s watch that lets go of a dead
pid and takes the client that replaced it), `GameLink.health()` with three answers
(`none` / `stale` / `live`), an exit that cannot be blocked by the run lock, and `_kill`
for a daemon that will not go. That is the right direction and it fixes §2.2 and half of
§2.4. It does **not** change what `up()` means to its thirteen remaining callers, and it
does not make «green» a guarantee — `health()` compares two integers, and two integers
agreeing is still an inference.

---

## 4. Could we do without it? Four options, priced

**(а) No daemon — a fresh `LuaEval` per call.** 2 314 ms and a hijack per chunk; 3 hours
a day of parking the game's main thread for today's traffic on one profile. It also
cannot be done from anywhere without the client's rights (§1). **Rejected on the
numbers.**

**(б) A daemon not bound to a pid, which re-aims itself.** This is #1286's
`follow_client`, and it is correct as far as it goes: it removes the *pid* half of the
staleness. It cannot remove the other half, because a daemon can hold a live pid and
still be unable to drive it — a wedged rebuild, a hijack that lost its race, a client mid-
login. **Necessary, not sufficient.**

**(в) The evaluator inside the panel process.** Attractive until the second account:
the daemon has to run in the client's Windows session, under that login's rights, and the
panel runs in the console session. It would also put a hijack, `SystemExit`-raising
il2cpp resolution and a 60 ms-to-1.3 s lock inside the process that draws the window —
against a Tk loop that already starves (`docs/research/panel-freezes.md`) — and it would
throw the warm state away on every «⟳ Перезапустить панель» (#1258), which is a press
that exists because the panel is restarted often. **Rejected.**

**(г) More connections instead of one lock.** The connections are already concurrent
(§2.1: a ping is 0.8 ms under full lock contention). The lock is the hijack and cannot be
removed; what can be removed is the *settle* from inside it — audit §1.1, which cuts a
patient call's lock hold from ~1 350 ms to ~60 ms. **Not an alternative to the daemon; the
right next optimisation, and a prerequisite for §5 being cheap under load.**

**So: keep the daemon.** The thing that is wrong is not its existence — it is that
nothing it says is a promise.

---

## 5. The hard link: what «green» must mean, and what it costs

> «Зелёный» обязан означать: *вызов прямо сейчас дойдёт до живого клиента и вернётся с
> ответом.* Не «порт слушается», не «кэш говорит warm», не «pid был живым минуту назад».

The only proof of that sentence is a chunk that ran. Measured: **62 ms** — 22 ms more
than comparing two integers, and 61 ms more than a ping. Cheap enough to be the answer,
and too expensive to be asked by every caller on every poll, because it takes the run
lock and therefore queues behind whatever the panel is doing (3 855 ms behind three
patient readers, §2.1).

**So the probe moves into the daemon, and the ping carries its age.**

1. **The daemon remembers its last success.** Every `run` that returns without raising
   stamps `last_ok = monotonic()`. Real traffic therefore refreshes the proof for free —
   a busy daemon never probes at all.
2. **It probes itself only when idle.** A watch thread (the one `follow_client` already
   runs) executes one trivial chunk when `now - last_ok > IDLE_PROBE_SEC`. At 10 s that is
   62 ms per 10 s of idleness — **0.6 % lock occupancy**, and zero while errands are
   running.
3. **The ping answers with the age, not with a boolean.**
   `{"ok", "warm", "pid", "self", "lease", "last_ok_age": 3.2, "probe_error": null}`.
   Still 0.8 ms, still served while the lock is held, still one round trip.
4. **`health()` reads the age.** `DAEMON_LIVE` only when a chunk actually reached the game
   within `2 × IDLE_PROBE_SEC` **and** the held pid is the running one. Anything else is
   `DAEMON_STALE`. The pid comparison stays — it is what tells «wedged» from «attached to
   the wrong client» — but it is no longer the evidence.
5. **One reading, one meaning.** The strip, `/api/state`, the schedule gate, `reads.py`,
   `squads`, the rally limits and the tabs stop calling `up()` and call the same reading.
   `up()` becomes what it always was — port bookkeeping for `ensure` / `restart` /
   `_wait_free` — and stops being the thing anybody paints green.

**And the guarantee is made structural, not advisory:**

6. **A daemon that cannot drive its client does not hold the port.** When the self-probe
   fails, the daemon drops and re-attaches itself (that is `follow_client`, extended from
   «my pid died» to «my last call did not land»). If re-attaching fails `N` times in a
   row, **the daemon exits** — `_leave` already guarantees the process goes whatever the
   lock is doing (#1286). The port comes free, and the panel's existing `_start` puts a
   fresh daemon on it.

That last line is what makes the person's sentence true again for every caller, including
the thirteen that still ask `up()`: **the port is only held while a chunk has recently
reached the game.**

### 5.1 What it costs

| | cost |
|---|---|
| self-probe, idle, `IDLE_PROBE_SEC = 10` | 62 ms per 10 s → **0.6 %** of the daemon's lock; **0** while errands run |
| the game's own cost | the probe is one invoke — ~2 client frames of parked main thread (33 ms at 60 fps, 200 ms at the 10 fps headless floor, `docs/research/headless-gpu.md`). **This is the number that decides `IDLE_PROBE_SEC`**, and it is why the probe must never run while real calls are landing |
| ping, per status poll | unchanged, 0.8 ms |
| `health()` per poll | unchanged, ~40 ms (the pid walk dominates, and the poll already pays it) |
| the deaf window after a client restart | today median **250 s**, max hours → bounded by `IDLE_PROBE_SEC` + a daemon start (~3 s measured in the log: `перезапуск` → `готов` in 1–4 s) |

### 5.2 What it breaks

* **The probe takes the run lock**, so a daemon wedged inside a call can never run it. That
  is not a bug — it is the reporting path: the age grows, `health()` says `stale`, and the
  panel restarts the *daemon*. It does mean `last_ok_age` measures «nothing has landed»,
  which is exactly the property wanted, and never «the daemon is idle».
* **A probe every 10 s writes a line into the answer log.** `ANSWER_CAP` (1 MB) already
  empties it between calls; a one-line probe adds ~30 bytes per 10 s ≈ 260 KB/day, so the
  cap fires roughly daily instead of never. Acceptable, and worth pinning in a test.
* **A busy daemon reports an age that is somebody else's success.** Right by construction
  — the question is «does a call reach the game», not «did *this* caller's call».
* **`IDLE_PROBE_SEC` is a new knob that can be got wrong.** Too short and a 10 fps client
  pays 2 % of its frames for being watched; too long and the deaf window grows back. It
  belongs beside `CLIENT_WATCH_SEC`, with the reasoning written where the constant is.
* **Thirteen call sites change**, most of them one line. The risk is a caller that wanted
  «is the port there» and now gets «is the game reachable» — `settings.py`'s three
  readings, in particular, are about the daemon as a *thing to start*, not as a link.

---

## 6. Self-recovery: what has to be true for nobody to intervene

Today the cure is the panel's, it is rate-limited, and 16 times today it was refused for
being too recent. The daemon should not need a nanny:

| the state | who notices today | who should |
|---|---|---|
| the client's pid is gone | the panel's status poll (8 s) → restart the daemon | **the daemon**, 5 s, `follow_client` — in flight (#1286) |
| the client is there and nothing lands | nobody until an errand fails | **the daemon**, `IDLE_PROBE_SEC`, §5 |
| the daemon cannot re-attach at all | nobody; it holds the port for ever | **the daemon exits** (§5.6); the panel starts a fresh one |
| there is no client to attach to | the panel's watchdog | the panel — unchanged; a daemon must not launch a game |
| the client is up but the *server* hung up | `game_link.probe()` → recovery (#1259/#1266) | unchanged — that is the account's link, not the daemon's, and the two must stay separate readings |

**The last row is the one to be careful with.** A self-probe answers «did a chunk run»,
and a stranded client runs chunks perfectly (`server-link-status.md` §1). So `last_ok_age`
must never be painted as «the account is online», and the strip must go on showing both.
Conflating them would rebuild #1266's bug from the other side.

---

## 7. How the numbers were taken

* Live client and the panel's own daemon on the default port, one profile active, the
  other two clients not logged on. Windows interpreter, repo root, `results/dbench/`
  (git-ignored).
* Latencies: `perf_counter` around `lua_client.DaemonClient` calls, n as stated, median
  reported with min/max. The chunk is `Debug.LogError('BENCH ok')` — one line, no server
  round trip, so the measurement is the transport and the invoke, not the game's reply.
* The cold build is `{"op":"reload"}` — the daemon dropping and rebuilding its own
  `LuaEval`. That is the right measurement for «what warmth is worth», and the only one
  available: a `LuaEval` built from a WSL-launched interpreter fails with `snapshot failed
  err=5` for want of rights (which is itself §1's second finding).
* Lock contention: three threads looping a patient `settle=1.2` run, one foreground `early`
  run timed against them, n=8.
* The day's counts: `profiles/<profile>/panel.log` and `debug.log`, 2026-08-07 only,
  aggregated by pattern. Deaf windows pair each client-restart line with the next
  `[daemon] готов`.
* Not measured, and named as such: daemon lock occupancy at idle (audit §6, number 7) —
  it needs the daemon to report it, which is §5.1's stamp; and `follow_client` recovering
  a live client, which needs a client restart that was not worth staging on a farming
  account.

---

## 8. Recommendation

**Keep the daemon. Rebuild what it promises. Do not put it in the panel, and do not
remove it.**

In this order, each one a separate task:

1. **The heartbeat** (§5.1–5.4): `last_ok` stamped by every successful run, an idle
   self-probe, `last_ok_age` on the ping, `health()` deciding on it. ~1 day, needs a live
   client to accept. This is the item that makes «green» a promise.
2. **The daemon that lets go of the port** (§5.6): re-attach on a failed probe, exit after
   `N` failures. Half a day, and it is what makes the promise hold for callers that were
   never migrated.
3. **One reading everywhere** (§5.5): thirteen `up()` call sites move to the new reading;
   `up()` becomes internal. Half a day, mechanical, pinned by a test that fails on a new
   `up()` outside `panel/runtime/daemon.py`.
4. **The lock off the settle** (audit §1.1): patient calls stop holding the hijack for
   1.3 s. ~1 day, live acceptance. Without it the heartbeat still works — it just waits
   behind the panel like everything else.

What NOT to do: do not add a fourteenth reading, and do not let the heartbeat answer the
question `game_link.probe()` answers (§6). Two different truths — «a chunk reaches the
client» and «the client reaches the server» — and every incident in this file so far came
from one of them being read as the other.
