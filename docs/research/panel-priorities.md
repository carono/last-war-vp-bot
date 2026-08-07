# Priorities over one queue: where the real boundary is, and what it costs (#1288)

> На русском: этот файл — исследовательская записка, как и все в `docs/research/`.
> Список возможностей для игрока — `docs/farming.md`.

The question, in the person's own words: *«Сейчас все сценарии идут строго в один поток,
но нужно сделать исключение… кнопки, которые человек нажимает в панели сам, должны иметь
ПРИОРИТЕТ над тем, что выполняется в фоне: нажал — действие.»*

Read alongside [`architecture-audit.md`](architecture-audit.md) §1.1–1.2 (what still
sleeps and what still serialises) and [`daemon-architecture.md`](daemon-architecture.md)
§2.1 (the lock, and what #1287 took out of it). This file does not repeat their numbers;
it says what the queue was actually protecting, and what is left of it.

---

## 1. What it cost, measured

Three profiles' `panel.log`, 2026-07-25 → 2026-08-08, aggregated by pattern.

| | count |
|---|---|
| presses turned away with «занят — дождись завершения текущего действия» | **857** (profile A), 251 (profile B), 208 (profile C) |
| …of them on **one day**, 2026-08-07, one profile | **343** |
| every «занято» line of any kind, one profile | 11 077 |

The refused presses are the ordinary work of the panel: `[rally]`, `[macro]`,
`[checklist]`, `[events]`. Nothing was wrong with any of them — the client was simply
busy with something the person had not asked for.

**How long is «busy»?** Pairing each `стартую` / `запуск вручную` with the next `готово`
or `ошибка`, n = 11 701 across the three profiles:

| errand | n | median | max |
|---|---|---|---|
| all of them together | 11 701 | **1.0 s** | 309 s |
| `restart_game` | 15 | **304 s** | 309 s |
| `apply_ministry_interior` | 158 | 7 s | 31 s |
| `alliance_help` | 1 168 | 2 s | 81 s |
| p90 over all | | **4 s** | |

So the great majority of the wait is one or two seconds — and the tail is five minutes,
because `restart_game` holds the client for the whole of a client restart. That is the
same five minutes #1281 was about.

**And what the queue costs the errands themselves.** From the trigger's `пришло … —
запускаю сценарий` to the run's `стартую`:

| trigger | n | median | p90 | max | fires waiting >10 s |
|---|---|---|---|---|---|
| `alliance_help` (profile A) | 1 142 | 0 s | **8 s** | **1 276 s** | 61 |
| `alliance_help` (profile C) | 286 | 3 s | **10 s** | 209 s | 23 (8 %) |
| `rally_auto_join` (profile A) | 4 241 | 0 s | 5 s | — | 144 |

An alliance help request pays points only while it is open. A two-second press waiting
ten seconds for its turn is the flag's whole justification, and it is the errand the
person named.

---

## 2. Where the boundary really is — three layers, not one

The reason to be careful: two chunks in one game VM at once is a race, and the queue was
built for it. It turns out the queue is not what prevents it.

1. **The daemon's run lock** (`tools/lua_daemon.py::Daemon.run`). The hijack is not
   reentrant, so one chunk is injected at a time. **Since #1287 the lock is held over
   `_send` only — ~60 ms — and not over the settle.** This is the layer that actually
   stops two chunks going in together, it is per client, and it holds whatever the panel
   above it does.
2. **The panel's claim** (`panel/runtime/claims.py` keyed by `(host, port)`, plus this
   link's own `_busy` flag). Held for the WHOLE scenario. This is what says «панель
   занята».
3. **The daemon's lease.** Cross-process, same duration as (2).

**Layer 1 already prevents the race.** What layer 2 prevents is something else, and it is
worth naming exactly, because everything below turns on it: **semantic interleaving.** A
scenario is a sequence — open a window, read it, press in it, close it — and two
scenarios interleaved at chunk granularity would press into each other's windows. That is
a real hazard and it is not a race in the VM.

Layer 2 also does a fourth job nothing else does: it is what makes two open profiles
pointed at ONE client take turns (#1226, §4.3 of `multi-profile-panel.md`).

---

## 3. What to do with the run that is in the way

Three options were considered for «нажал — действие».

**(a) Interrupt it.** Cheap to write, and wrong: the run loses whatever it had done, and
a scenario killed between «open the alliance window» and «close it» leaves a window open
with nobody left to close it. The panel's own «Стоп» already refuses to kill a run
mid-call for this reason (`TimerScheduler.cancel`).

**(b) Run the press in parallel.** Tempting after #1287, because layer 1 makes it *safe
in the VM*: two chunks would simply queue 60 ms on the daemon's lock. But it is exactly
the semantic interleaving of §2 — at the finest possible granularity, one chunk at a
time. Rejected: it would trade a wait for a class of failure nobody can reproduce.

**(c) Park the background run at a checkpoint, hand the client over, resume.** Chosen.
Single-file access is kept — the client is never held by two runs at once — and the join
is the COARSEST one available: a statement boundary, or a poll inside a `WAIT`. The run
resumes where it stood rather than starting over.

**What (c) costs, stated rather than hidden.** A parked run can come back to a game the
press has moved: a window opened, a scene changed. That is a real risk and it is the
price of the feature the person asked for. It is bounded three ways — only BACKGROUND
runs carry the hook, the join is at a statement boundary rather than mid-call, and a run
that cannot get the client back **fails with its reason said** instead of going on to
press a client it does not hold.

---

## 4. The mechanism

**Three levels** (`panel/runtime/claims.py`), ordered so that a comparison is the whole
rule: `BACKGROUND` (the schedule's ordinary errands, the rally loops) · `EXPRESS` (an
errand its catalogue marks «сразу») · `HUMAN` (a button in the window, a hotkey, a screen
on the phone, the shell putting the client back).

**A demand is a note on the door, not a lock.** `claims.demand(key, level, owner)` always
succeeds and blocks nothing; `claims.wanted(key, above)` is what the holder asks, and it
is one dict lookup under a lock — which is why it can sit in the path of every statement
of every scenario. Nothing can make a holder park: it reads the note at its own
checkpoints and decides.

**The checkpoint is the interpreter's.** `Context.yield_to` is called at exactly the
three places `cancel` is checked — between statements, between the presses of a repeat,
between the polls of a `WAIT`. Those are the only moments a scenario is between two
thoughts rather than inside one, and the interpreter is the only thing that knows where
they are. The panel supplies the callable and decides what «more urgent» means; the DSL
only offers the moment.

**And the hook is handed the CONTEXT, which is not a detail.** Standing aside means
letting the daemon's LEASE go, and the run is carrying both the token it was granted
(`ctx.game_token`) and an evaluator built with it (`ctx.evaluator`). A hook that took no
argument would have no way to say that both are stale, and every call after the first
park would come back «lease lost» — which reads in the log exactly like the game going
deaf, and is the sort of bug this arrangement would otherwise have introduced silently.

**The press never waits on the Tk thread.** `play_async` tries the claim, and if it is
refused by something it outranks it says so, starts the worker, and the WORKER calls
`GameLink.claim_soon` — demand, then poll. The window learns only that the run has been
accepted, which is what «нажал — действие» has to mean from the window's side.

**Two ceilings, both with a reason.** `YIELD_WAIT_SEC = 12` is how long a press waits for
a park: p90 of an ordinary errand is 4 s, so nearly every press gets in at the first
checkpoint, and past twelve seconds the honest answer is the «занят» it always was —
waiting out a `restart_game` would be worse than refusing. `PARK_WAIT_SEC = 60` is how
long the parked run waits to get the client back before failing; longer, because the
alternative to waiting is a failed errand and a retry hold.

**And it says both, in every language.** `priority.ahead` when a press is let in front of
a run, `priority.parked` / `priority.resumed` around the park, `priority.lost` when the
run could not get the client back. #1288 asks for exactly that: «если что-то прервано или
отложено ради приоритетного — сказать, что и почему».

---

## 5. The flag

`immediate` on `panel.timers.Timer` and on `panel.triggers.Trigger` — a field on the
errand, written in the profile's own catalogue, ticked from a box on the Timers tab.
**Never a list of names in the code**: whose errands are urgent is one account's answer
and not another's.

It does two things at once. The errand skips the shared worker queue and runs on a thread
of its own (`TimerScheduler._express`), and it asks for the client at `EXPRESS`, which
makes an ordinary errand step aside for it. Both halves are needed: the claim alone would
still leave it queued behind a five-minute `restart_game` on the one worker.

What is kept: the dedup (a burst of pushes is one run, not ten), the mid-run re-fire
(#1281 — a second banner going up while the first is being joined), and the fallback
(an express errand that still cannot get in after twelve seconds goes onto the ordinary
queue rather than disappearing).

`alliance_help` ships with it on. Nothing else does — and a long errand marked this way
would be a mistake, because nothing can make an EXPRESS run park.

---

## 6. What was NOT done, and why

* **The claim was not made re-entrant or shared.** One client, one holder, still.
* **`restart_game` and the other lifecycle recipes were not made parkable.** They hold
  the client for five minutes by nature; a press during one is refused with «занят», as
  it always was. Making a client restart interruptible is a different task.
* **The secret-task autoloot takes no claim at all** and never did
  (`panel/tabs/secret_tasks/autoloot.py::_spend` says why: its interlock is «one run at a
  time» of its own, and a claim would invent a refusal in the middle of a robbery). So
  nothing here touches it — a press already runs beside it, exactly as before, and the
  daemon's lock is what keeps that safe.
* **The rally tab's two spin-waits** (`panel/rally/tab.py::_join`, `_send`) still poll
  `claim` at BACKGROUND. They are background loops and behave exactly as before; giving
  them a level is a one-line change whenever somebody decides which.
* **The triggers are not on the phone at all.** They were not before this either, so
  the «сразу» box on a trigger row is the whole section's pre-existing absence and not a
  divergence this task introduced. The TIMERS are on the phone, and their box was
  mirrored in the same commit — reading (`/api/timers` carries `immediate`) and press
  (`/api/timers/now`, through the tab's own variable when the tab is drawn), exactly as
  the switch beside it travels.

---

## 7. How the numbers were taken

* `profiles/<profile>/panel.log` for the three profiles open on the machine this was
  taken on — called A, B and C here, because a profile name is an account's and this
  file is public — 2026-07-25 20:17 → 2026-08-08 00:19. Those files are git-ignored and
  were never committed.
* Refusals: lines matching the `busy` locale string, counted per file and per day.
* Hold durations: each `timers.log.fire` / `timers.log.manual` paired with the next
  `timers.log.done` / `timers.log.failed` for the same errand name; median, p90 and max
  over the pairs.
* Queue latency: each `triggers.log.fire` paired with the next start of the same errand.
  The unbounded maxima in that table are honest for `alliance_help` and unreliable for
  `rally_auto_join`, where a fire whose run never started pairs across a long gap.
* Not measured, and named as such: the park itself, against a live client. Every number
  above is from the panel's own record of the arrangement it replaces; what a parked
  scenario finds when it resumes needs a live session and is the acceptance run.
