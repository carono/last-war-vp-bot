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
