# «Вход с другого устройства» — the session kick, and where its flag is

> На русском: этот файл — исследовательская записка, как и все в `docs/research/`.
> Список возможностей для игрока — `docs/farming.md`.

**Read this before going into the client after a kick flag. It has been looked for
twice.** The second search (#1259) rediscovered a phrase already written down in
[`street-run-parkour.md`](street-run-parkour.md) in July and walked into a dead end
already documented in [`protocol.md`](protocol.md). Both cost about an hour each, and
both were avoidable by reading. That is the whole reason this file exists as its own
file rather than a paragraph inside another one.

## 1. What it is

The game is **single-session**. Logging the account in anywhere else kicks this client:
the server closes the connection and the client puts a modal on screen —

> **«В ваш аккаунт был выполнен вход с другого устройства»**

Observed twice, months apart:

* **2026-07-29** (street-run work): the client **froze mid-run**, the modal came up, and
  the client **closed when it was confirmed**. So the window is modal, it blocks, and
  confirming it ends the process — which matters for how long anything has to catch it.
* **2026-08-06** (#1259): the player logged in, was thrown out «a couple of minutes
  later», logged in again and stayed. Part of that was this panel's own restart — see
  [`server-link-status.md`](server-link-status.md) §4.4 — and the kick itself was seen
  by the player on screen.

## 2. The key, and how it was found

**`E100083`** in the game's own locale tables:

| lang | text |
|---|---|
| ru | В ваш аккаунт был выполнен вход с другого устройства |

Found by going **from the text**, which is the technique to reuse:

```bash
# the tables live in the install, not in the repo — point the tool at them
LW_LOCALE_DIR="<install>/Game/LastWar_Data/StreamingAssets/locale/<build>" \
    python3 tools/game_locale.py --term "…"
```

`tools/game_locale.py` without that variable says «no game found» and stops; the build
number under `locale/` changes with the client, so glob it rather than writing it down.
The RU table holds ~52 800 keys, and a plain substring scan over its values is what
turned the phrase into a key in one pass — `--term` matches the panel's glossary terms
and did NOT find this one.

Keys of the shape `E1000xx` are **server error codes**: the server sends the code and
the client renders whatever the table says. That is why the next step found nothing.

## 3. Where the flag is NOT (both dead ends, both already documented)

* **`login.other` is not the kick.** It is `MsgDefines.LoginOther` = `login.other`, and
  its handler (`LoginOtherMessage.HandleMessage`) updates alliance data —
  `UpdateAllianceBaseData`, `AllianceNoticeManager`, `payDollerTotal`.
  [`protocol.md`](protocol.md) already records it in the login trace as
  «`login.other {alliance}` → full alliance record». It is «another player's login
  info», not «logged in elsewhere».
* **Nothing in the client's Lua mentions it at all.** A scan of **48 534 functions**
  across every loaded module — `string.dump` on each, substring search — found zero
  references to `E100083`, `UIDisconnect` or `UICrossDisconnect`. The disconnect flow
  belongs to the **C# connection layer**, so there is no data manager holding a
  «kicked» field and nothing to poll the way an event's state is polled.

## 4. Where the flag IS — caught live, 2026-08-06

The player kicked this client on purpose while a watcher polled it **twice a second**.
The whole recording:

```
22:43:15   link=online  dead=0   no window          city     <- baseline
22:45:08   link=lost    dead=6   no window*         city     <- the kick
                                                             (*by the stack; see below)
22:48:53   the panel, restarted, calls it: «связь с сервером пропала»
22:49:02                                  «выкинуло: вход с другого устройства»
22:52+     window STILL open, 7+ minutes later
```

**The sockets and the modal are simultaneous** — one poll apart at 0.5 s resolution.
Six half-closed, zero established, and the client sitting in the city with its HUD up.

### The window is `UICommonMessageTip` — not either of the guesses

`UIDisconnect` and `UICrossDisconnect` both stayed SHUT through the whole kick. What
opened was the client's generic message dialog, and its `View.tipText` carries the
message word for word:

```
Внимание
В ваш аккаунт был выполнен вход с другого устройства
```

Buttons `text1=110006`, `text2=110106`. Read it with
`UIManager.Instance:GetWindow('UICommonMessageTip').View.tipText`.

### Why it looked like «no window at all»

**`UICommonMessageTip` sets `DontPushWindowStack`.** So `GetStackTopWindow()` answers
`nil` and `WindowStack` is empty **with the modal plainly on screen**. That is what the
earlier reading did — it asked the stack, saw nothing, and concluded the kick leaves no
trace. Wrong accessor as well as wrong moment.

**`IsWindowOpen` is the only accessor that sees it**, and it has to be asked BY NAME:
sweeping all 2 221 names in `UIWindowNames` is what found it
(`TouchScreenEffect, UICommonMessageTip, UIMain, UINpcTalkLayer` were the four open).

### How long it holds, and whether a poll catches it

**Over seven minutes and still up when this was written**, unattended. The July
observation said the modal blocks until confirmed, and this agrees: it does not
self-dismiss. **The panel's ordinary eight-second poll catches it with room to spare** —
no fast polling is needed in production, and #1259's design (ask only while the link is
already `lost`) is comfortably enough.

### Is it distinguishable from an ordinary hang-up? Yes

| | stranded (server hung up) | kicked (logged in elsewhere) |
|---|---|---|
| sockets | half-closed, none established | the same |
| `UICommonMessageTip` | **not open** (watched live, twice) | **open, with text** |
| stack / `GetStackTopWindow` | empty / nil | empty / nil — no help |

The sockets alone cannot tell them apart; the window can. `UICommonMessageTip` is a
GENERIC dialog and proves nothing on its own — the client uses it for anything — so the
pair was what made it conclusive: **a lost link AND a message tip carrying text**, asked
only while the link already read lost.

**That pairing was not enough, and §4.1 below is what it cost.** A kick can sit behind a
link that reads `online`, so the flag has to be askable of a client that looks perfectly
healthy — and there «a dialog is open» is a false kick every time the game puts a message
up. What makes it conclusive on its own is the TEXT: the modal is compared with the
game's own wording for `E100083`, in every language the client ships
(`tools/lib/game_kick.py`, #1270).

The READING was proven end to end by accident of timing: the panel was brought back up
while the client was still kicked, and its very first poll said «выкинуло: вход с
другого устройства» rather than «связь пропала».

**The PRESS was not, and it was not happening at all.** Written here as proof of the
whole flow, that sentence covered only half of it: the panel said the words and
restarted nothing, because the caller tested `key == recovery.ACT` and `ACT_KICK` is
not `ACT`. It was found the same night by asking the log a different question — WHAT
RAN after each sentence — and the answer was the two ordinary hang-ups at 21:44 and
22:15 ran `restart_game` in the second they were announced, and the two kicks at 22:49
and 22:59 ran nothing at all. The client stayed deaf for nineteen minutes and was
rescued by the process watchdog when it finally died on its own.

**A log line is evidence that something was SAID, never that it was DONE.** Both
readings above came out of the same log and only one of them was true; the difference
is that «выкинуло» was checked against the game and «перезапускаю» was not checked
against anything. Fixed with `recovery.RESTARTS` — the set of every act that means the
press — so the next act added to the decision cannot be announced-only.

### 4.1 …and asking it only on a lost link hid the next one entirely (#1270)

Written into the design as a saving — «a healthy client would always answer the same, and
this is a round trip» — and true right up until a kick that left one socket standing.

On 2026-08-07 the account was taken by another device at ~04:38. Five of the client's six
game sockets went to `CLOSE_WAIT` and the sixth stayed established, so `classify`
answered `online, dead=0`; the client had logged in hours before, so it still knew what
time it was and `game_clock.session_ready()` said `True`; and every timer ran and pressed
nothing, reporting success. `kicked_out()` would have answered 1 at any moment of those
two and a quarter hours, and nothing asked it.

The flag is now read on every status poll and in front of every send. What that cost was
not a round trip — it was the reading's precision: it had to stop meaning «a dialog is
open» and start meaning «the dialog says what the game says when an account is taken».
The whole of it is `docs/research/server-link-status.md` §5.3.

### What this does NOT fix

A kick means the account is being played somewhere else, so restarting cannot win it
back for long. This file used to say that had been watched failing — «restart, kicked
again, жду 10 мин» — and it had not: those are the two kicks above, where no restart
ever ran. **Nobody has yet seen what a real restart does against a live second
device.** Whether the automation should stand down entirely on a kick instead of
restarting is a decision for the person, and it is the same open question as §6.

## 5. The wrong conclusion this produced, and why it was convincing

#1259 read a client that had lost its link and found no modal, an empty window stack,
the whole HUD up and the city on screen, and wrote up:

> «A kick and an ordinary hang-up are indistinguishable not only by their sockets but by
> the client too.»

That is false, and the player disproved it in one sentence: they had **seen the message
with their own eyes**. The reading was taken at a moment chosen by nobody — after the
panel had already restarted the client — so it was evidence about that moment and
nothing else.

**One observation of an ABSENCE is not a property of the system.** The rule this
repository already had — ask what the player sees, `[[feedback_ask_what_the_player_sees]]`
— applies to negative findings first of all, because a negative finding closes a line of
enquiry and nobody reopens it.

## 6. What the panel does with it

A kick and a silent hang-up are the same ACT (restart) and a different EVENT, so they
get different sentences — «выкинуло: вход с другого устройства» against «связь
пропала» — and separate counters, in both front-ends. Both go through the same gate: a
restart is withheld while somebody has touched the machine in the last five minutes,
because being kicked is not a licence to close a window a person is playing in
(`panel/runtime/recovery.py`).

### 6.1 The unresolved one, resolved: a kick is WAITED OUT (#1291)

What stood here as «left to the person deliberately» was this: a kick means the account
is in use somewhere else, restarting takes it back off whoever has it, and if that is the
owner on their phone the panel is fighting its own player. Nothing local can see a phone.

**It is not undecidable, because nothing has to be decided.** The panel does not need to
know WHO took the account to know that acting within half a minute is wrong either way:
if it is the owner, they are thrown out of the game they just opened; if it is not, a
quarter of an hour costs a quarter of an hour of farming and nothing else. The asymmetry
does the deciding.

Reported live on 2026-08-08 as the panel throwing the player out roughly a minute after
they logged in — three restarts in a row, `launch_game` timing out on each pass, the
daemon dying with every client. The minute was the two `KICK_STRIKES` readings of an
eight-second poll; the loop was the person's own client taking the account back each
time.

So a kick now earns a WAIT before anything is done about it — fifteen minutes by
default, `kick_hold_min` in the profile, 0 for the old behaviour — after which the
ordinary scheme runs unchanged (strikes, player gate, cooldown, client/daemon
alternation). Two things make it work rather than look like it works:

* **the wait is a deadline, not a streak.** A kick usually takes the sockets with it, so
  a hold that depended on the modal still being readable would be walked straight through
  by three ordinary `lost` readings;
* **every restarter asks it.** Three things put a client back — the recovery decision,
  the process watchdog, and the `restart_game` errand that `Schedule.gate` lets through
  precisely when the game looks down — so the deadline is a reading
  (`Recovery.kick_hold_left`) and all three consult it. A wait honoured by one of them is
  not a wait.

The player gate stays exactly where it was and is asked FIRST: it is about somebody at
THIS machine and has no end, while the kick's wait is about another device and runs out.
Neither replaces the other.

### The first real kick, minute by minute (2026-08-08)

The whole of it is in one profile's `panel.log`, and it is worth keeping because it
proved three of the four claims above and killed the fourth.

```
07:55:06  выкинуло: вход с другого устройства — жду 15 мин, клиент не трогаю
07:55:59  … donate_alliance_tech FAILED — logged in on another device
07:59:59  … collect_base_resources FAILED — logged in on another device
08:01:19  … donate_alliance_tech FAILED — logged in on another device
08:05:19  … collect_base_resources FAILED — logged in on another device
08:06:39  … donate_alliance_tech FAILED — logged in on another device
08:07:34  клиент не слышен, но за машиной кто-то есть — не трогаю ещё 5 мин
08:07:42  клиент пропал — процесса игры больше нет
08:07:42  выкинуло: вход с другого устройства — жду 3 мин, клиент не трогаю
          … thirty-one minutes of nothing …
08:38:25  запускаю игру рецептом launch_game…        ← a PERSON pressed «Запустить»
08:38:31  клиент снова на связи
```

**What held.** The wait was armed on the run of kick readings and nothing relaunched the
client for the twelve and a half minutes it was deaf — under the old code the second
reading, at about 07:55:30, was a restart. The deadline survived the sockets and then the
process: `08:10:06 − 08:07:42 = 144 s`, and `-(-144 // 60) = 3`, which is the number in
the log. That second line is also the whole of the follow-up fix (`8ce8d57`) doing its
job — the client had gone `offline`, which takes the early return in `note`, and the
sentence would otherwise have stopped there.

**What broke.** Nothing put the client back afterwards. The wait ran out at 08:10:06 and
the account sat closed until a person pressed the button at 08:38:25 — the log has no
`вотчдог:` line anywhere in the episode, and `log.game.launching` is the lifecycle
control, i.e. a hand.

The cause was in `panel/__main__.py::_watchdog_check` and had nothing to do with the
deadline: it acted on the EXACT strike,

```python
self._game_gone += 1
if self._game_gone != WATCHDOG_STRIKES:
    return                        # counting, or already reported
```

so the watchdog looked at a dead client on exactly ONE poll per death. The hold spoke on
that poll and returned — and that was the last time anything asked. The same `!=` had
already made the relaunch cooldown below it unreachable inside an episode, so
«вотчдог: перезапуск был N мин назад — жду» promised a retry that never existed.

The cure is the one `Recovery.note` was given for its own cooldown: **the hold suppresses
the ACT, never the next LOOK.** Counting and reporting stay once (`< STRIKES`,
`== STRIKES`); the two holds are re-asked every poll and say themselves once each, latched
on `_wd_held`, which the client coming back clears. `tests/test_panel_recovery.py`
compiles the real method out of the shell and runs it against a stub, so the retry, the
cooldown and the silence are pinned by behaviour rather than by grep.

**What was NOT a kick.** An hour later the same client lost the server again —
`08:41:44 связь с сервером пропала`, the player gate at `08:41:52`, a restart at
`08:44:02` after 24 s deaf. No kick reading anywhere near it, `kick_hold_left` long back
at 0 (the wait had been cleared at `08:38:31`, `клиент снова на связи`). Three minutes
from loss to restart is the ordinary hang-up path behaving exactly as it should, and it
is worth writing down because from outside the two look identical: the person reporting
it saw «связь с сервером пропала» and «панель перезапустила клиент» and read the wait as
broken. The two messages are the tell — `log.game.link_lost` is a hang-up, and only
`log.game.kick_hold` / `log.game.kick_restart` mean the account was taken.

---

## The kick recovery had never once run — the poll it rides was dead (#1296)

Found sideways, while a different poll trigger (the treasure errand) refused to arm
itself, and it applies to **every** poll trigger there has ever been — the kick recovery
above included.

`Schedule.poll` built the check's chunk and read its answer in the same method:

```python
chunk = '… CS.UnityEngine.Debug.LogError("TRIGCHK=" .. tostring(…))'
return any("TRIGCHK=true" in ln.lower() for ln in (lines or []))
```

The needle is spelled in the marker's own capitals; the haystack is lowered.
`"TRIGCHK=true" in "trigchk=true"` is **False for every reading the game can give**, so
the verdict was False always. The listener started, the log said `listening on
session_kick (poll)`, the chunk reached the client, the client answered `TRIGCHK=true`
when the modal was up — and the panel read «nothing to do».

**Why it survived so long, and this is the lesson rather than the typo.** A poll that
does not fire writes NOTHING. There is no line for «checked, answer was no», because that
is the normal case a hundred times an hour. So a recovery that never ran and a recovery
that was never needed produce byte-identical logs, and the only way to tell them apart is
to make the condition true on purpose and watch. That is what caught it: the treasure
errand's check is true whenever its hook is missing, so removing the hook by hand created
a poll that MUST fire — and nothing happened.

How it was pinned, in order:

1. the panel's own log: `listening on treasure_auto (poll)`, then no `fire` for minutes;
2. the same chunk run by hand through the daemon: `['TRIGCHK=true']`;
3. the panel's verdict on those very lines, computed in isolation: `False`.

Step 3 is the one that named it. Steps 1 and 2 are equally consistent with a dozen other
faults — a dead poll thread, a `ready()` refusing, a claim held elsewhere — and each of
those was chased first.

The chunk and its reading are now one pair in `panel/triggers.py`
(`poll_chunk` / `poll_said_yes`, case-insensitive on both sides), because a contract
duplicated as two strings in one method is a contract no test can reach; `Schedule.poll`
calls them. `tests/test_treasure_auto.py` drives the real line shape the daemon returns
and the whole round trip through a real Lua.

**If a poll trigger of yours has never visibly done anything, check this first**, and
check it by forcing the condition rather than by reading logs — the logs of a broken poll
and an idle one are the same.

## THE CLASS BEHIND IT: a reading that cannot tell «nothing» from «could not read»

Both of this task's worst bugs are one shape, and it is worth naming once so the next
person recognises it in a third place:

* **the poll** wrote nothing when its check said no — and nothing when it had never run.
  «Quiet» and «dead» were byte-identical, so the fault was invisible for weeks
  (this note, above);
* **the treasure ring** (#1277) recorded `f=""` on every push it ever caught, and that
  blank read as «the message carried no fields». It was not: the reader was wrong. An
  INCOMING message is a plain Lua table, and `SFSObject.GetKeys` — which the ring used —
  answers nothing at all for one. So the field list was empty for the same reason a broken
  poll is quiet: the code could not read, and said «nothing» in exactly the words it uses
  for a real nothing (`docs/research/world-treasures.md`). It cost the dig gate: the
  harvest read the uuid with `SFSObject.GetData` and got `nil` for every broadcast there
  has ever been.

**An empty value is not evidence until the reader is above suspicion.** Both cases had a
line in the log that LOOKED like a reading and was a trace of a failed read, and in both
the reasonable-looking conclusion — «the poll is fine, nothing is happening» / «the push
carried nothing» — was the wrong one for months. So when a field comes back empty, doubt
the reader before you doubt the game: read the same thing a second way (walk the table as
well as asking the accessor), or force the value to be non-empty and see whether it
arrives. A reading that cannot distinguish «no» from «I could not tell» must say which —
that is what the poll's trace and the ring's two-way field read now do.

### Everything that was affected, by name

Poll triggers are the only users of `Schedule.poll`, and there have only ever been two.
Grepped across `DEFAULT_TRIGGERS` and every profile's `triggers.json`; nothing else in the
panel calls it.

| trigger | since | what it was supposed to do | what actually happened |
|---|---|---|---|
| **`session_kick`** | 2026-07-30 (#1128) | poll the client for the «logged in on another device» modal; when it is up, run `recover_from_kick` — acknowledge the modal and relaunch — with an adaptive backoff of 15 → 30 → 45 min so a repeating kick is not answered by a relaunch war | never fired once. `grep "fire session_kick"` across every profile's logs, the whole history: **0** |
| **`treasure_auto`** | 2026-08-08 (#1296) | hear a chest announced in alliance chat and work it | born into the same fault; found and fixed before it was ever relied on |

**The damage from the first is smaller than it sounds, and saying so precisely matters
more than sounding alarming.** Kicks WERE recovered from — by the other half of the
machinery, not by the trigger. `panel/runtime/recovery.py` reads `kicked`
(`tools/lib/game_kick.py`, key `E100083`) on every dashboard poll and acts on it through
`ACT_KICK`; the same logs that hold zero `fire session_kick` hold fourteen «выкинуло: вход
с другого устройства», each followed by either «перезапускаю» or «жду N мин, клиент не
трогаю». So the recovery ran, on recovery.py's own hold of 15 minutes.

What was genuinely lost is the trigger's own **backoff policy** — the 15 → 30 → 45 min
escalation with a reset after 10 quiet minutes — which never applied to anything, and the
`recover_from_kick` scenario, which has never been played by the panel at all.

The practical consequence for whoever picks this up: **two mechanisms are aimed at the
same event**, and only one of them was ever working. Now that the poll runs, they will
both act on the next kick. That wants deciding — not by an agent in passing — and until it
is decided, `session_kick` stays off by default, which is how it ships.

### What was decided (2026-08-08), and what is left

Decided by the person, on a live account that had been kicked six times that morning:
**one executor for the act, and it is the proven one.**

1. **One relaunch at a time, by construction rather than by timing.** Four things put this
   client back — the process watchdog, this module's verdict, the `restart_game` errand and
   a person's button — and everything that kept them apart was a hold or a cooldown. The
   claim does not help: it is released when a scenario ends, and «`launch_game` finished»
   is not «the client is up», so the next detector takes the freed claim and launches a
   client that is already starting. The lock now sits at the one door they all come
   through, `PanelRuntime.play_async`, over the named set `RELAUNCHES` — which already
   includes `recover_from_kick`, so the day it is switched on it is inside the lock rather
   than added to it afterwards. `tests/test_panel_relaunch_lock.py`.
2. **`recovery.py` stays the executor.** It has done the job fourteen times live; the
   trigger has never done it once. Swapping them on a hot account, blind, was refused —
   correctly.
3. **The backoff moved here** (`KICK_HOLD_STEP_SEC`, `KICK_HOLD_MAX_SEC`,
   `KICK_STABILITY_SEC`): 15 → 30 → 45 min while the kicks keep coming back within ten
   minutes of a restart, and back to the profile's own hold once a session finally holds
   that long. Measured from `note_kick_restart` — the moment the client was PUT BACK —
   because the question is «did the session hold», not «how long between two readings».
   That is the one piece of the trigger that carried real value and had never applied to
   anything.
4. **Still open: making `recover_from_kick` the act.** The scenario is the right shape — a
   press, in one file, played by whoever needs it — and it has never been played by the
   panel at all. The order of work, which is not this task's:
   * prove it live: it acknowledges the modal and the client comes back;
   * only then does `recovery.py` stop acting for itself, so there is never a day with two
     executors again;
   * the lock already covers it, so that step cannot reintroduce a double relaunch.

Until that is done, `session_kick` may be left ON as a poll that **observes and carries
the escalation** while `recovery.py` acts — which is what the profile it was tested on has
now.

### The clock trap, paid for in the same hour

`Recovery` is handed `time.time()` by the poll, and the first version of
`note_kick_restart` was called with `time.monotonic()`. Subtracting one from the other
makes every difference look like hours, so **every kick would have read as a fresh
incident and the escalation would silently never have escalated** — a third instance, in
one task, of the same class as the two comparisons below: both ends of a comparison have
to be in the same units, and nothing tells you when they are not.
`test_the_panel_stamps_the_kick_restart_with_the_clock_recovery_uses` fails on a
monotonic stamp, verified by putting one back.
