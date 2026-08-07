# Is the account online, or is the process merely running? (#1223)

> На русском: этот файл — исследовательская записка, как и все в `docs/research/`.
> Список возможностей для игрока — `docs/farming.md`.

## 1. The state that has no symptom

A Last War client that has been up since yesterday can lose its server session and go on
looking perfectly healthy. Everything a panel normally asks still answers:

* the process is there, with its window drawing;
* the Lua VM answers every getter — with the numbers it last received;
* a fetch (`SendGetAllParkourInfosMessage()`) returns `true`;
* the start request for an event returns `true`;
* no tip fires, no error is logged, and the scene simply never loads.

`street_run_ai.py status` then prints `attempts=0` — exactly what it prints when the
day's allowance is genuinely spent. On 2026-08-02 an hour went into "the event has no
attempts today" before anybody looked at the sockets. Restarting the client turned
`remain=0, today=773` (a day old) into `remain=30, today=0`: the daily reset had happened
and the stranded client had never seen it.

**Every reading inside the client is worthless for this**, because the client itself does
not know. It is holding a socket the far end closed.

## 2. The tell

    /mnt/c/Windows/System32/NETSTAT.EXE -ano | grep ":10012"

A healthy client holds one or more **ESTABLISHED** connections to the game server. A
stranded one holds **CLOSE_WAIT** and nothing else: the server sent FIN, the client's
stack acknowledged it, and the application never called `close()`. It will sit there
until the process dies.

Confirmed from inside as well, by hooking `SFSNetwork.HandleMessage` and sending a
request: nothing comes back.

Two things make the check port-agnostic rather than a constant:

* the game port is not stable across builds — `:17935` historically, `:10012` on the
  current client, and it will move again;
* the client also talks HTTP to a CDN all day. So the rule is «any remote port that is
  not 80 or 443», the same rule `_endpoint` has used since the status strip first showed
  an endpoint.

### 2.1 Two things a live client does that a naive reading gets wrong

Both found in the FIRST live reading taken after this was written, on a perfectly
healthy client (pid 178804, twenty sockets):

**It keeps half-closed sockets while it is playing.** Six of them, all to `:10012`, on
six different gateway addresses — the client greets several while logging in, keeps one
and leaves the losers hanging for the rest of the session. So «there is a CLOSE_WAIT
socket» is NOT the tell on its own. The tell is «a half-closed socket and no established
one», which is why `link_of` asks for an established connection first and only then
counts the dead.

**It holds a pair of ESTABLISHED sockets to itself.** `127.0.0.1:63203 ↔ 63204`, both
ends owned by the game. They survive the server hanging up — nothing about them involves
the server — and the very first `probe()` reported `online -> 127.0.0.1:63203` while six
of the client's real sockets were half-closed. A loopback remote is excluded
(`_is_game_socket`); without that exclusion the whole reading would have been green for
ever and this feature would have shipped doing nothing at all.

A player who routes the game through a proxy on their own machine therefore reads
`unknown` (amber, «связь не подтверждена») rather than `online`. That is the honest
answer: from outside, that client's only remote peer is a program on the same computer.

### 2.2 …and the same trap once more, from OUTSIDE the machine (found 2026-08-06)

The loopback exclusion above closed the near case. The far case was still open, and it
cost a whole night of farming before anybody looked at a socket.

Caught while trying to spend a robbery for task #1188. The panel had been writing
`game=up link=online daemon=warm timers_on=8` into `debug.log` every eight seconds all
evening, every timer was reporting success, and every one of them was pressing nothing:

```
[timer] donate_alliance_tech:   TAP Donate 1000 xall -> 0 press(es)
[timer] donate_alliance_tech: < action: donate_alliance_tech OK
[timer] apply_ministry_interior:   WHILE post != 10007 -> LIMIT 4 reached, giving up
```

The socket table said what the readings would not:

```
TCP  <lan>:61136  <gateway-a>:10012  CLOSE_WAIT   147680
…six of them, and not one ESTABLISHED on :10012
```

And `probe()` said, at that exact moment:

```
Link(running=True, link='online', reason='', pid=147680,
     conn='<chat-host>:17935', dead=0, …)
```

**The live socket was a DIFFERENT SERVICE.** `:17935` is the chat / control channel
(`docs/research/chat-system.md`); the game's own traffic is `:10012`. The client had
lost every game socket and kept the control one, so `live_endpoint` found an
established, remote, non-80/443 peer and `classify` returned `ONLINE, dead=0` —
without even counting the six half-closed ones, because it returns before it gets
there.

So §2.1's rule — «an established connection outranks any pile of half-closed ones» —
holds only while «established» and «half-closed» are the SAME conversation. They were
not. The port-agnostic rule that made the check survive `:17935 → :10012` is exactly
what let a leftover `:17935` vouch for a dead `:10012`.

Two consequences, both observed rather than reasoned:

* **the automatic recovery (#1259) can never fire**, because it waits for three
  consecutive readings of a lost link and the link never reads lost;
* **the «client is on the link» gate in front of `LUA` / `TAP` / `GAME` / `JUMP` is
  defeated by the same reading**, so every scenario ran and every scenario pressed into
  a socket the far end had closed. That is precisely the state §1 says has no symptom —
  rebuilt, in a feature written to prevent it.

The cure was the documented one and it worked: `restart_game` → the client came back,
self-restarted into a new pid after login (as it always does), and came up with six
ESTABLISHED sockets on `:10012`. The Lua daemon had to be restarted alongside it —
attached to the dead pid it answered `snapshot failed err=5`, which is an access
failure and not a state anything reads as «lost» either.

#### What was done about it (#1266)

**The verdict is taken per CONVERSATION, and a dead one is never outvoted by a live
one.** `classify` groups the client's game sockets by remote PORT (`conversations`) and
answers `lost` if any group has half-closed sockets and no established one — whatever
the other groups are doing. The question §2.2 left open is answered the second way:
«connected» means a peer of the game's own talk, not any remote peer at all.

The port is the grain, and it is not a constant anywhere:

* **grouping by ADDRESS would not work** — the client greets several gateways while
  logging in, so one conversation is many addresses on one port; five of the six
  half-closed sockets would each become a «dead conversation» of its own on a perfectly
  healthy client;
* **and a port literal is not needed** — nothing here names 10012 or 17935. The rule is
  «sockets that share a remote port are one talk», which survives the next build moving
  the game exactly as the 80/443 exclusion always has. `game_paths.game_port()` was
  deliberately NOT used for this: its default is still `17935`, which is now the CHAT
  port, so asking it would have named the wrong conversation as the game's.

Read live off a healthy client the same day, which is what the rule was checked against:

| conversation | sockets |
|---|---|
| the game | 1 ESTABLISHED + **5 CLOSE_WAIT** (the losers of the gateway race) |
| the control channel | 1 ESTABLISHED, no half-closed |
| web (80/443) | excluded before any of this |

So the half-closed pile is not an anomaly to be explained away — it is the game's own
signature, present all session, and it is what identifies which talk is the game's.

**Which way it leans, and why.** The two errors are not symmetric. A wrong `online` is
silent and costs a night: every reading says the account is fine, the recovery counts no
strikes, the gate passes every scenario, and nothing in the log looks wrong. A wrong
`lost` is loud and costs one restart — after three consecutive readings, a cooldown and
an idle check — and the client comes straight back. So where the two conflict, the dead
conversation wins.

**Both consequences close with it**, because both read the same verdict: the recovery
(#1259) now counts its strikes on exactly this shape, and the `LUA`/`TAP`/`GAME`/`JUMP`
gate now refuses it. The endpoint on the strip is the game's too, rather than whichever
row the socket table happened to hand over first — that night it named the chat host as
the server.

**And the daemon on a dead pid says so.** A run that fails twice over now ASKS whether
the client is still there (the pin, and the machine) instead of leaving the words of a
Windows call to speak for it: the daemon raises `ClientUnreachable` and puts a
`client_gone` flag on the wire beside the text, and `lua_client` turns that into
`ClientGone` — «the client this daemon drives is not there any more … the link is what
is broken rather than the chunk». A daemon that was already running when this shipped has
no flag to set, and one may be warm for days, so `lua_client` also recognises
`il2cpp_probe`'s own three failure sentences (`GONE_WORDS`). It is a diagnosis, not an
act: restarting the daemon is still the person's press.

Pinned by `tests/test_game_link_status.py` (this exact table, and the healthy one beside
it, so the cure cannot become worse than the disease), `tests/test_engine_link_gate.py`
(the gate refuses it) and `tests/test_daemon_lease.py` (a run against a dead client, with
the daemon's own rebuild still attempted first).

### 2.3 It also catches MEASUREMENTS, not just monitors (#1053, 2026-08-07)

The night after this shipped, the same shape fooled a capture — which is worth writing
down, because nothing in #1266 suggests that a person taking a live reading is exposed
to it too.

Work on #1053 (the capture's hard-coded port) probed the client's sockets, found one
established peer on `:17935` and six on `:10012`, captured 25 s on each, and got nine
alliance pushes from `:17935` against **0 payload packets** from `:10012`. Every step is
sound and the conclusion — «the game port has moved back to `:17935`» — is false. The six
were CLOSE_WAIT, `probe()` said `link='lost', dead=6` at that moment, and what the
capture recorded was the **control channel of a stranded client**. When the client
reconnected an hour later, `:10012` came back established and a 20 s capture on it
carried `push.alliance.march.create` and the alert stream.

**So a traffic measurement inherits the link's state.** On a stranded client every
observation is about the control channel, and it looks like a discovery rather than a
failure — the frames decode, the counts are real, and the port that «works» is the wrong
one. Two habits follow, and both are cheap:

* **`game_link.probe()` before believing a capture**, exactly as the engine does before
  pressing. `link='lost'` invalidates the run rather than the tool;
* **capture the whole conversation set, decide nothing from one port's silence.** A port
  can be silent because it is dead, because the client is idle, or because the traffic
  went elsewhere, and a single-port capture cannot tell those apart.

`map_capture` now reads its filter through `conversations()` here rather than keeping a
rule of its own, and `primary_game_port` — the «one socket» answer that `steal_via_socket`
sends down — refuses to answer at all when the raced conversation has no established
socket. Pinned by `tests/test_game_port_detection.py`, which carries this night's table.

## 3. The four answers, and why not two

`game_link.probe()` returns a `Link`: the old `running` boolean, plus a `link` that is
one of four. (`panel/runtime/game_process.probe()` returns the same reading with the
panel's sentence attached — see §4.3.)

| link | how it is decided | why it is its own answer |
|---|---|---|
| `online` | an ESTABLISHED game socket, and no conversation of this client's left for dead | the only proof the account is playing (§2.2 — an established socket of ANOTHER service is not proof of this one) |
| `lost` | some remote port carries ≥1 socket in `CLOSE_WAIT` / `CLOSING` / `LAST_ACK` / `FIN_WAIT1` / `FIN_WAIT2` and no ESTABLISHED one | a fact, not a guess: that talk's far end hung up and nothing replaced it (§2.1 — the count alone proves nothing; §2.2 — nor does a live socket elsewhere disprove it) |
| `unknown` | the process is there and its sockets make no verdict | see below — «I cannot tell», which is not «it is broken» |
| `offline` | no client process (or nowhere to look for one) | unchanged from before |

**`unknown` is the honest half.** A client that is still starting has its web sockets
and its own loopback pair and no game socket yet, and a launch takes about 45 seconds —
calling that "lost" would put a red strip and a log line after every scheduled restart.
The same answer covers a machine that will not attribute a foreign process's sockets at
all. Amber, and the sentence says «связь не подтверждена».

**A second account is NOT that case, and the old comment saying so was wrong.** It had
been written into `server_connection` for a year — «the sockets come back without a
pid» — and the live reading of 2026-08-03 disproves it: the client in the second account's own
Windows session answered with eight sockets of its own and a gateway of its own, i.e.
a full `online` verdict from the console session's panel. Both accounts get a real
answer; `unknown` stays for the machine that genuinely cannot say.

**`TIME_WAIT` is deliberately not in the half-closed set.** It is what an ordinary, clean
close leaves behind, so a client that reconnects every few hours would look broken for a
minute after every healthy reconnect.

**`running` keeps its old meaning exactly**: the process exists. The watchdog
(`panel/__main__.py`, `_watchdog_check`) acts on it, and a client that lost the server is
not a client to kill and relaunch behind the person's back — the panel says so and leaves
the decision where it was.

### 3.1 Proven against a real socket table, both ways

Stubs prove the classifier; they cannot prove that `psutil` says `CLOSE_WAIT` where this
expects it, that the pid is attributed, or that the port and loopback filters keep the
right rows. So the flip was watched live (2026-08-03), on this machine:

* **the live client**, both profiles: the console one → `online -> <gateway>:10012` (25
  sockets visible), the second account, in its own Windows session → `online ->
  <another gateway>:10012` (8 visible);
* **a real hang-up**, end to end. A stand-in server was bound to this machine's LAN
  address (`<lan-ip>:10012` — deliberately not loopback, which the reading ignores),
  a socket connected to it, and the server closed:

      connected           -> ('online', '<lan-ip>:10012', 0)
      server hung up (1s) -> ('lost', None, 1)
      raw:  [('CLOSE_WAIT', '<lan-ip>:10012')]

  That is the stranded client's exact signature, read by the shipped code path.

What could NOT be produced on demand is the game server hanging up on its own: a socket
opened to the live gateway and left silent was still ESTABLISHED after two minutes,
so the real thing takes hours of idleness. The classifier is proven; catching it against
the actual game is a matter of waiting for the next one.

### 3.2 What the reading costs

The whole probe — which Windows session, which pids, one walk of the socket table —
measured **46–67 ms** on a live machine with two clients up. Nothing here is a
`process_iter`: on Windows the pids come from `WTSEnumerateProcesses`, and
`net_connections` is a kernel table rather than a walk of every process's handles. That
matters because a cold `process_iter` costs 6–7 s and slows the Tk thread by 40× while it
runs (`docs/research/panel-freezes.md` §1) — this reading must never grow into one.

Two rules keep it there:

* **one walk per reading.** `_client_sockets` is the single seam; the live endpoint and
  the dead count are both derived from what it returned. The first draft walked the table
  twice for one answer.
* **the callers already have a clock.** The window polls every eight seconds off the Tk
  thread (`_refresh_status`), and the phone's `/api/state` caches per profile for five
  seconds (`panel/web/api.py`, `STATUS_TTL_SEC`) — a phone polling every two seconds
  therefore does not add a reading. Nothing new was introduced for the link: it rides the
  probe that was already being made.

## 4. Where it shows

* **The window.** «Главная»'s status strip, coloured from `LINK_COLOURS`: green only for
  `online`, red for `lost` and `offline`, amber for `unknown`. The sentence names the
  state too (`game.st.lost`, `game.st.running_at` …), so a screenshot of the strip is
  readable without the colour.
* **The phone.** `/api/state` carries `game.link`; the pill on the state page is drawn
  from the same four ids (`docs/research/panel-web.md` §3.8).
* **The log.** Only the EDGES: the moment the link goes, and the moment it comes back
  after having gone. The strip is only true while somebody is looking at it, and this is
  the state nobody looks for — a line with a time on it is what makes the morning after
  answerable. A loss is said after `WATCHDOG_STRIKES` consecutive readings of it (the
  same patience a crash gets, because a client mid-reconnect has for a moment exactly the
  sockets of one that gave up); a recovery only after a loss was announced, and only into
  `online`, so a relaunched client is the watchdog's «клиент снова на связи» and not two
  lines saying the same thing.

## 4.1 What still does NOT read it: everything that SENDS (#1259)

The strip says it. The watchdog says it. **A scenario does not ask, and neither does the
thing running the scenario** — `script_engine` has no notion of the link at all, so a
recipe on a stranded client presses its way to the end, gets `true` from every send, and
then fails on the one honest step it has: the count it was going to prove itself by
never moves.

That is not a harmless "it fails anyway". It fails with the WRONG REASON, and the wrong
reason is a very believable one. #1259 spent an afternoon concluding «the server silently
refuses this march», wrote it up as a finding, and tried five variants of the message
against a client the panel had already declared dead in its own log two hours earlier —
`связь с сервером пропала — клиент жив, но всё, что он читает, вчерашнее`. On a
restarted client the very same call raised an ordinary Lua error on its first try.

So the rule this file has been making since #1223 needs one more line: **a reading taken
without the link beside it is not evidence, and a send made without it is not a test.**
Any live check that ends in «the game did not react» has to say which of the two it was
before it is believed, and the answer is one `probe()` away.

Where the gate belongs was the open question, because the probe lived in
`panel/runtime/game_process.py` and the sender lives in `src/lastwar_bot/script_engine.py`
— the panel is the player, so the engine importing from it is backwards, and the probe
could not simply move while it answered in `panel.i18n.Message`. §4.2 and §4.3 are the
answer that was agreed and built.

## 4.2 The gate, as built (#1259)

`script_engine` refuses on `lost`, naming the state and pointing here. Three properties
it was built to have, all pinned by `tests/test_engine_link_gate.py`:

* **only `lost` blocks.** `unknown` is a client 45 seconds into starting up, or a
  machine that will not attribute a foreign process's sockets; blocking on it would
  strand a healthy account behind a guess.
* **it fails OPEN.** No psutil, no socket table, no client found, an exception anywhere
  inside — all read as «cannot tell» and the run proceeds. A gate that becomes the fault
  is worse than no gate.
* **«no client at all» is not its business.** That is the run's own error, in the run's
  own words.

**It stands on the four primitives that DRIVE the game** — `LUA`, `TAP`, `GAME`, `JUMP` —
and not at the top of a run. It went in at the top of `run_action` first, and that
refused every recipe on a lost link *including `restart_game.md`*, whose `QUIT_GAME` /
`CALL launch_game` / `ATTACH_GAME` send nothing to the server at all: they repair the
client. The one cure would have been blocked by the symptom, and the six-hourly restart
timer would have stopped working in exactly the case it exists for. On the primitives,
the lifecycle statements are free BY CONSTRUCTION rather than by an exception list
somebody has to keep up to date. Read once per run, not once per press.

`READ_LUA` is deliberately NOT gated. A stranded client answers a read with yesterday's
numbers, which is a lie — but the answer to that is to mark the reading stale, not to
blind the diagnosis that is trying to work out what is wrong. That is #1261.

## 4.3 Where the reading lives (#1260)

[`tools/lib/game_link.py`](../../tools/lib/game_link.py) — **all of it**, not just the
socket predicates: `probe()`, the cached machine-wide walks, and the session attribution
that decides which of two accounts' clients is this profile's.

The rule came over first and the machinery stayed in the panel, which left the shared
half unable to answer the question anybody actually asks — «is THIS client on the
server» — without being handed a list of pids it had no way to obtain. Working out which
pids those are is most of the difficulty and all of the subtlety (§3.2, and
`docs/research/multi-instance-rdp.md`), so a second implementation of it in the engine
was never going to stay in step with the first.

It answers in **data**: a `Link` — the four states, the pid, the endpoint, the count of
half-closed sockets, and a `reason` id for the three different ways there can be no
client (`no_session` «there is nowhere to look» is not `session_not_found` «that session
is up and empty» is not `not_found`). `panel/runtime/game_process.py` is now the wording
and nothing else: `Probe` is `Link` plus the `panel.i18n.Message`, and every name the
panel used to reach for still resolves there as an alias.

**Nothing in `game_link.py` may import the panel**, and a test says so
(`test_the_reading_imports_nothing_of_the_panel`). That one line is what the whole move
is: while the reading answered in a front-end's message type, it could only be used by
that front-end, so «ask before you send» was a rule that held only for whoever happened
to be running the panel — which is precisely how a day was lost.

## 5. Putting it back

Not automated, and deliberately so — the fix is the one from the original session:

1. kill the client's pid;
2. relaunch it (`launch_game`; a second account's client is launched inside its own
   Windows session — `docs/research/multi-instance-rdp.md`);
3. wait for the game port to read ESTABLISHED again;
4. send the daemon `{"op":"reload"}` so it lets go of the dead VM (`tools/lua_daemon.py`).

Whether the watchdog should eventually do this on a LOST link is an open question and a
conversation to have with the person: a false positive there costs a live client, and the
socket table is a machine-wide reading that the panel does not always get to see.

## 6. Pinned by

`tests/test_game_link_status.py` — the four answers off a stubbed socket table, the web
ports ignored, `TIME_WAIT` not counted as a loss, an established socket winning over a
stale one beside it, `running` staying true through a loss, and every sentence the four
can produce present in all eleven locales. Since #1260 it also pins the split: the
machine is stubbed on `game_link` and the answer read back through the panel, so a second
copy of the rule in either layer fails it, and the panel-free half runs on a machine
where the panel will not import at all.

`tests/test_engine_link_gate.py` — the gate: only `lost` blocks, it fails open, it stands
on the driving primitives and leaves `restart_game.md` alone, and it reads once per run.

`tests/test_panel_rdp_session.py` and `tests/test_panel_multi_profile.py` — the session
attribution on top of the reading: which of two accounts' clients is this profile's, and
what «Проверить» says about each way it can be wrong.

## 7. Still open (#1261)

The reading is asked before anything is driven, and that is all it is asked before. What
it does not yet do: stop a scheduled errand before it starts, mark a board's numbers
stale while the link is down, or decide whether a lost link should relaunch the client.
The cost of leaving those is measured — 31 minutes of a panel working on yesterday's
numbers between the loss at 18:58:40 and the client being killed at 19:29:17 — and which
of them to build is the person's call, not an agent's.

## 4.3 The kick DOES announce itself — and how that was nearly missed

> **The whole of it, including the locale key, the two dead ends and the two live
> observations, is [`session-kick.md`](session-kick.md).** It was looked for twice;
> read that before going into the client for it a third time.

**The player sees a plain message: «В ваш аккаунт был выполнен вход с другого
устройства».** It is the game's own string, key `E100083`, in the tables
`tools/game_locale.py` reads. So a kick is not silent and never was.

This file previously said the opposite, as a finding. That was wrong, and the way it
went wrong is worth more than the fact:

> A client that had lost its link was read through the Lua VM and showed no modal, an
> empty window stack, the whole HUD up and the city on screen. From that one look the
> conclusion drawn was «a kick and a hang-up are indistinguishable by the client too».

One observation of an ABSENCE, at a moment chosen by nobody — after this panel had
already restarted the client once — was written up as a property of the game. The
player, who had watched the same event on the screen, knew better in one sentence. The
rule this repository already had (`ask what the player sees`, [[feedback_ask_what_the_player_sees]])
applies to negative findings above all: not seeing a thing is evidence about the
moment, not about the thing.

### Where the flag is, and why there is no manager to read

Nothing in the client's **Lua** mentions `E100083`, `UIDisconnect` or
`UICrossDisconnect` — 48 500 functions scanned, no hits. The disconnect flow belongs to
the **C# connection layer**, so there is no data manager holding a «kicked» field and
nothing to poll the way the ghost list or the event state is polled.

What Lua CAN see is the WINDOW, because `UIManager` holds it whoever opened it:

```lua
UIManager.Instance:IsWindowOpen('UIDisconnect')
UIManager.Instance:IsWindowOpen('UICrossDisconnect')
```

That is `tools/lib/game_kick.py`, and it is what the panel reads. It was originally asked
**only while the link was already `lost`** — a round trip into the VM, and a healthy
client would always answer the same. That assumption was disproved by §5.3 three days
later: a healthy-looking client with a kicked account answers differently, and the flag
was never consulted for two and a quarter hours. It is now asked whatever the sockets
say, which meant narrowing the reading from «a dialog is open» to «the dialog is showing
the game's own sentence» — see §5.3's fix. It still fails CLOSED: anything unreadable is
«no kick», so it can add a reason and never remove one.

**Still unwatched:** which of the two windows a kick raises. That it stays up long enough
for an eight-second poll is answered — seven minutes and still up, watched (§4 of
[`session-kick.md`](session-kick.md)).

## 4.4 The restart closed a window somebody was playing in

```
21:44:08  связь с сервером пропала
21:44:16  клиент не слышен серверу уже 24 с — перезапускаю     <- eight seconds later
21:44:16  QUIT_GAME -> client pid … closed
```

An account being PLAYED is not an account in trouble. `panel/runtime/recovery.py` now
holds a restart back while somebody has touched the client's own Windows session in the
last five minutes (`game_link.idle_sec()`), and both front-ends say which of the two
reasons is holding it — «за игрой человек» or «до следующего N мин» — because a restart
that silently does not happen is indistinguishable from one that is broken.

**IT DOES NOT SEE A PHONE.** Somebody playing the same account from another device is
invisible to any local reading, and that case is the worse one: the restart takes the
account back off them, and it is also exactly the case a kick creates. Whether the
automation should hold off entirely on a suspected kick is a decision for the person
and is deliberately not made here.

---

## 5. The pattern behind all of it: **the panel confidently fixing the wrong thing**

Three separate incidents in twenty-four hours, and they were treated as three bugs until
the third one made the shape obvious. They are one failure mode, and it is worth naming
because a fourth is likelier than not.

| # | What the panel believed | What was actually true | What it did about it |
|---|---|---|---|
| 2.2 | «the link is fine» — an established socket vouched for it | the socket belonged to ANOTHER service; the game link was long dead | nothing, for hours: every errand failed and the strip said online (#1266) |
| 4.3 | «the client was kicked, restarting» | it was — and the restart was announced and never played | nineteen minutes deaf, rescued only when the client died on its own (#1259) |
| 5.1 | «the client is broken, restarting it» | the CLIENT was fine; the daemon held a dead pid | six relaunches in fifty minutes, each ending in a five-minute scene timeout (#1268) |
| 5.2 | «the client is online, so errands may be sent» | it was online — on its CONTROL channel; the game's own conversation did not exist yet | every errand let through into a client still logging in, succeeding at nothing (#1269) |
| 5.3 | «the link is online, so nothing needs asking about a kick» | the account had been taken by another device; one of six sockets was still up, so the link read online | the kick flag was never consulted for 2¼ hours; every timer ran and pressed nothing (#1270) |

The common shape, in one sentence: **a reading that cannot distinguish two states was
used to choose between two cures, and the wrong cure left no trace that it was wrong.**

Each of the three has the same three ingredients, and they are what to look for next
time:

1. **A proxy stood in for the thing itself.** A socket for a conversation; a log line for
   a press; a link state for «can this be driven». The proxy is always cheaper to read,
   which is why it got chosen, and it is always true slightly less often than the thing.
2. **The failure was SILENT AND PLAUSIBLE.** Every one of these produced exactly the
   output a healthy system produces — «онлайн», «перезапускаю», a restart happening. None
   of them produced an error anybody could grep for. That is why they ran for hours.
3. **Repetition looked like persistence.** The panel doing the same useless thing on a
   timer reads, from outside, as the panel working on the problem. Nothing counted how
   many times a cure had been applied without the symptom changing — so nothing could
   notice that the cure was not one.

### The guards that come out of it

Written as rules rather than as fixes, because the next instance will not be about
sockets, presses or daemons:

* **Read the thing, not a proxy for it.** Where a proxy is unavoidable, say so in the
  reading's own name and make the caller opt into it. `game_link` now looks at the game's
  CONVERSATION rather than at any live socket (§2.2); `recovery` now compares the pid the
  daemon holds against the pid that is running rather than inferring from the link.
* **An act must be announced BY the thing that performs it, never beside it.** The kick
  bug lived entirely in the gap between «said» and «did». One door — `Panel._act_on` —
  turns every decision into its press, and the acts are grouped in sets (`RESTARTS`,
  `DAEMON_RESTARTS`) so a new one cannot be announced without a caller finding it.
* **Count the cures, not just the symptoms.** A cure applied N times with the symptom
  unchanged is evidence about the DIAGNOSIS. `recovery.FRUITLESS` is that count made
  explicit: after two client restarts with the link never once back, the next act is a
  different cure. Both front-ends draw the count while it is still evidence
  («перезапусков впустую: 2»), so a person can see the panel about to change its mind.
* **Alternate; never replace.** The first draft of that guard stopped restarting the
  client entirely once it blamed the daemon — one stuck loop swapped for another, and the
  worse one, since the client cure is right most of the time. A pre-existing test
  (`test_a_link_that_never_comes_back_is_retried_after_every_cooldown`) caught it. The
  rule is that no cure is repeated more than `FRUITLESS` times without another being
  tried in between, and none is ever abandoned.
* **Say WHAT is being fixed, not just that something is.** «Панель что-то перезапускает»
  is the same sentence for opposite diagnoses. `recovery.state()["blame"]` is `client` or
  `daemon`, and both front-ends word it.

### 5.1 The incident (2026-08-07, 03:14 → 04:05)

```
03:14:37  связь с сервером пропала
03:16:06  клиент не слышен серверу уже 24 с — перезапускаю      <- #1
03:26:09  … — перезапускаю                                      <- #2
03:31:18  restart_game (the six-hourly timer, on top of the watchdog)
03:36:22  launch_game FAILED — WAIT scene == city timed out after 300.0s
03:36:22  collect_alliance_gifts: the client this daemon drives is not there any more
…                                                               <- #3 … #6
04:05     one {"op":"shutdown"} on the daemon; the next reading came back OK
```

Six client restarts, fifty minutes, and the link never came back. Meanwhile the SAME
daemon happily answered `{"op":"ping"}` with the pid of a client killed at 03:31 — the
fault was legible on the wire the entire time and nothing asked.

The two readings that now tell it apart:

* **the pid comparison** — `{"op":"ping"}` names the client the daemon holds
  (`DaemonClient.target_pid`, which already existed); the status poll already knows the
  pid that is running. Two integers. `GameLink.attached_pid` and `Panel._daemon_stale`;
* **the fruitless count** — above.

The positive one matters most because of WHEN it is true: during the incident the link
read `online` for minutes at a time, with six established sockets. Any decision hung off
`link == lost` would never have been asked at all.

**The cure is the button that was already there.** «⭮» beside the daemon indicator has
always called `DaemonLink.restart` — shut the daemon down politely, start a fresh one,
which attaches to whatever client is actually running. It takes about two seconds.
Nothing was missing but the decision to press it.

### 5.2 «На связи» arrives before «готов играть» (2026-08-07, found while verifying #1268)

Watched during a client restart, three minutes apart:

```
04:35:16  онлайн (pid 26972) → 34.145.128.94:17935     <- the CONTROL channel
…                                                         (no :10012 conversation at all)
04:38:2x  онлайн (pid 179220) → 101.32.143.142:10012   <- the game, at last
```

`classify` was right by its own definition — an established non-HTTP conversation — and
answering a question nobody had asked it: **not «is a socket up» but «can this client be
played».** The send gate (`Interpreter._link_lost`) refused only on `lost`, so for those
three minutes every errand was let through into a client that was still logging in. They
do not fail loudly there; a client at the login screen answers everything with plausible
numbers (#1227), so they succeed at nothing. Ingredient 2 of §5, exactly.

**Sockets cannot close this, and that is the finding.** The bad case — one established
conversation which happens to be the control channel — is indistinguishable from the good
one — one established conversation which happens to be the game — unless something names
which port is which, and nothing on the machine may (`CLAUDE.md`: a hardcoded port that
has moved does not raise, it silently means the wrong thing). Measured, both orders
happen: on one bring-up :10012 came up first and :17935 twelve seconds later; on another,
:17935 alone held for three minutes.

**And the obvious socket shortcut is DISPROVED — measured, not reasoned.** The first fix
here skipped the round trip whenever the live conversation carried the gateway race
behind it (the losers a client leaves half-closed while logging in), on the reasoning
that a raced conversation must be the game's. Twenty minutes later, a perfectly healthy
client on the same machine:

```
{10012: ('…:10012', 0 half-closed),      <- the game, established, no race at all
 17935: ('…:17935', 0 half-closed)}      <- the control channel
```

An earlier settled client had five losers on :10012; this one had none. So the race is a
sometimes-marker, not a rule, and a shortcut built on it reads False on healthy clients.
It was deleted rather than kept as a "usually" — a helper that is wrong on the common
case is a trap for whoever reads it next. And the cost it was avoiding turns out to be
small: measured, the confirmation is **0.31 s** against a warm daemon, on a gate whose
socket walk already cost **~1.0 s** before any of this, once per scenario run.

**The gate therefore ASKS.** `online` with the race behind it passes for free; `online`
without it costs one round trip to the client's own clock, which a client at the login
screen cannot fake. Three properties, each pinned by a test:

* `unknown` still fails OPEN — a client 45 seconds old, or a second account whose sockets
  this machine will not attribute, must not be stranded behind a guess. **This is also
  what #1268's recovery stands on**, so it was the first thing checked. `classify` itself
  is untouched: the recovery reads exactly what it read before;
* `lost` is still `lost` whatever the client says about itself — a stranded client answers
  that question with yesterday's numbers too, so the confirmation may only ever ADD a
  refusal;
* the confirmation itself fails open on every way of not knowing, and never builds a local
  evaluator — a gate may not become the most expensive thing in a run.

#### The near-miss worth keeping

The obvious implementation is `game_clock.session_ready(ev)`. It is wrong here, and
silently: that helper answers `False` for «at the login screen» AND for «the read
failed», so a machine whose VM cannot be reached would have had every run refused, for
ever, with no error anywhere. Fail-closed is the one direction this gate is built never
to fail in. It was caught by writing the test for «every way of not knowing» BEFORE
believing the implementation — the round trip is now made in the gate, where a raised
call and an unanswered clock stay distinguishable.

That is the second time in two tasks that the guard was written by asking «what does this
do when it is wrong in the OTHER direction» — the first being #1268's anti-loop, whose
first draft stopped restarting the client entirely and was caught by a test that already
existed. **Both mistakes were the same shape as the bugs being fixed**: a fix that is
confident about one direction and has never been asked about the other. Adding the
opposite-direction test before trusting a fix is the cheapest guard here, and it has now
paid twice.

### 5.3 A KICK behind one live socket is invisible to the watchdog (2026-08-07, #1188 acceptance)

Two and a quarter hours of a client doing nothing while every indicator said it was fine.
Read live at the start of the acceptance:

```
probe()   -> Link(running=True, link='online', dead=0, conn='…:10012')
netstat   -> 1 ESTABLISHED :10012, 5 CLOSE_WAIT :10012   (same local ports 40 min later —
                                                          nothing had reconnected)
Lua       -> scene=Launch, UICommonMessageTip=true,
             kicked_out()=1, «В ваш аккаунт был выполнен вход с другого устройства»
```

The account had been taken by another device at ~04:38. The client kept ONE established
conversation, so `classify` answered `online` — and `_read_kicked` is asked **only while
the link already reads `lost`** (§4.3). The one flag that could have named the state was
therefore never consulted, `ACT_KICK` never fired, and the panel sat at `link=online`
from 05:13 to 07:27 playing timers into a client that could not send. `dead=0` beside
five half-closed sockets is the same shortcut §5.2 disproved, seen from the other side.

**Three readings that all looked healthy and were not**, worth naming because each is a
plausible thing to stop at:

* `probe().link == 'online'` — one live socket out of six;
* `game_clock.session_ready() == True` — it stayed True throughout, kick modal and all,
  which is a second reason not to lean on it as a gate (see the near-miss above);
* every `TAP … xall -> 0 press(es)` in the log — a client reading its own stale memory.

The only reading that told the truth was a ROUND TRIP: a request sent, and its answer
looked for. `world.get.detail.new` came back empty; so did `GetAllAllianceTasksFromServer`;
and the reply handler `PushHeroDispatchMissionStealHandler`, hooked for the occasion,
never fired for two robberies that left Lua cleanly (`pcall` → `ok=true`). Neither
robbery cost anything — `todayStealNum` does not move on a message the server never
answers, which is the same accounting as the out-of-sector refusal in §3 of
secret-task-steal.md.

**The cure was a restart, and it needed two goes.** The first `restart_game` reported
`launch_game FAILED — WAIT scene == city timed out after 300s`, and so had four automatic
attempts overnight — every one of them waiting for the scene through a daemon still
attached to the pid that had just been killed (#1268's shape, from the launch side). The
client that actually came back was the panel's own next attempt, which restarted the
daemon first: `WAIT scene == city -> matched`, and all six :10012 sockets ESTABLISHED.
After that the acceptance ran first time.

#### What was done about it (#1270)

**A kick is a state, not a footnote on a lost link.** It is asked on every status poll
and in front of every send, whatever the sockets and the clock say — the two readings
that agreed the client was fine.

Making it askable at any moment meant making it conclusive first, and that is the part
worth reading. The window is `UICommonMessageTip`, the client's GENERIC dialog: while the
question was only put to a client whose link already read `lost`, «a dialog is open» was
proof enough, because a merely stranded client shows none (watched live, twice —
[`session-kick.md`](session-kick.md) §4). Asked of a healthy client the same reading is a
false kick every time the game puts a message up, and the cure for a kick is a restart —
the expensive direction, since it closes the window somebody may be playing in.

**So the TEXT is compared with the game's own sentence.** The client renders the modal
from key `E100083`, and the tables are on disk in every language it ships
([`game-locale-tables.md`](game-locale-tables.md)) — nineteen of them, the same key in
each. Read live off this machine's install while this was written:

```
ru  В ваш аккаунт был выполнен вход с другого устройства
en  Your account is currently active on a different device!
de  Dein Konto ist derzeit auf einem anderen Gerät aktiv!
…   17 distinct sentences over 19 languages, ~60 ms a table, 1.2 s for the set, once
```

All of them are compared, not the panel's language and not the account's: what language
the player plays in is not something the panel knows or should ask. `tools/lib/game_kick.py`
is the whole reading — where the tables are (`game_paths.locale_dir()`, added for this and
answering `None` rather than raising), the scan that stops at the key rather than building
52 000 pairs, and the normalisation that lets Thai's zero-width spaces and a title prefix
still compare equal.

**It fails closed in both directions of not knowing.** A tip that cannot be read is «no
kick»; tables that cannot be found are «cannot judge the text», and then the reading
falls back to exactly the pair rule that shipped before — a dialog counts only while the
link is already `lost`. A machine that cannot locate its install is therefore no worse
off than it was, and never worse off than a false restart.

Where it is now read:

* **the status poll** (`Panel._read_kicked`) — on every poll while it matters (a lost
  link, or a kick already on screen) and every `KICK_POLL_SEC` otherwise, since the round
  trip is ~0.7 s and the modal does not self-dismiss. The throttle CARRIES the last
  answer rather than reporting «no kick» in the gaps: the recovery counts consecutive
  readings, and a gap that answered False would keep resetting the run it feeds;
* **the recovery** (`recovery.note`) — a positive kick is «deaf» whatever the link says,
  on its own shorter patience (`KICK_STRIKES`, two rather than three: this is the game's
  own sentence, not an inference off a socket table). Every gate around it is unchanged —
  the person at the machine still wins, the cooldown still holds — and the daemon
  alternation of #1268 is skipped, because here the diagnosis is known and no daemon on
  this machine can be restarted out of another device holding the account;
* **the send gate** (`script_engine._link_lost`) — asked after the socket verdict and the
  clock, and refused with its own sentence. It fails OPEN on every way of not knowing,
  like the rest of that gate.

**And `session_ready` lied for a reason worth writing down.** The clock it asks is
`UITimeManager.serverDeltaTime`, which the client sets at login and then keeps as a
difference from the DEVICE's clock rather than asking the server (`tools/lib/game_clock.py`).
It survives the session ending, so a kicked client answers with a perfectly plausible
epoch. The clock proves the client HAS logged in; it has never proved the client still IS
in a session, and reading it as though it did is this section's own pattern — the ONE
reading used to choose between two states. It now asks the kick too, and only a positive
one refuses.

**«Успешно ничего» is counted now, as evidence and not as a cure.** Every `TAP … xall ->
0 press(es)` in that morning's log was true and nothing was tallying them, so from
outside two and a quarter hours of doing nothing looked exactly like two and a quarter
hours of having nothing left to do. The interpreter counts GATED presses only — `xall`
and batches read the button's own count in the same call they press, so a zero means
something, while a plain `TAP x3` fires blind and is evidence of neither kind — and
`recovery.note_run` says so once after `BARREN` errands in a row. Deliberately no act
hangs off it: a spent account presses nothing all evening, and restarting a client for
being finished would be this same mistake made in the other direction.

Pinned by `tests/test_game_kick.py` (the reading, on stubbed tables and a fake client),
`tests/test_panel_recovery.py` (a live socket plus a kick modal means the client cannot be
played; the barren tally; a kick never blames the daemon) and
`tests/test_engine_link_gate.py` (the gate refuses it, and every way of not reading it is
a pass).

**Still the person's decision, and still not made here:** whether a kick should restart at
all. A restart takes the account back off whoever has it, and if that is the owner on
their phone, the panel is fighting its own player — §4.4 and
[`session-kick.md`](session-kick.md) §6. What #1270 changes is only that the panel can now
SEE the state; what it does about it is the wiring that was already there.

## 8. «daemon=warm» over a daemon bound to a client that has gone (#1281 → #1268)

Two separate ways the panel reports a working daemon while nothing it sends reaches the
game. Both were seen live inside one hour on 2026-08-07, while the rally auto-join's
numbers were being collected, and both make the auto-join deaf without saying so.

**The first was ours and is fixed.** `GameLink.ensure()` asked `up()` without
`fresh=True`, so a daemon that died inside the cache window (`UP_CACHE_SEC`) was
reported «already warm on port 47654», nothing was started, and the port stayed dead.
The class's own docstring already named `ensure` as the one caller that must ask fresh;
the wait loop below it did, the check in front of it did not. Pinned by
`tests/test_panel_daemon_port.py::test_ensure_asks_the_socket_rather_than_its_own_cache`.

**The second is #1268's and is NOT fixed.** A daemon can answer its port perfectly while
being attached to a client that no longer exists:

```
panel strip :  daemon=warm            <- the port answers, which is all `up()` means
ping        :  {"ok": true, "warm": false, "pid": null}
run         :  ClientGone  [SystemExit: snapshot failed err=5]
```

`Daemon.run` rebuilds once and retries on a stale handle, and that rebuild is what fails
here — so the daemon stays up, wedged, indefinitely. Every errand in that state fails
with a named reason, which is right, but the STRIP says warm and the recovery has nothing
to act on. **`up()` means «the port answers»; three callers read it as «the daemon
works».** The honest reading is the ping's `pid`: a daemon with no attached pid is not a
daemon anybody can use, and the cure is a restart of the daemon rather than of the
client.

Frequency, measured rather than guessed: the client was restarted four times in
thirty-five minutes by other work (each restart is somebody else's legitimate business),
and each one left the daemon in one of those two states. A babysitter that treated
«answers the port» as healthy missed the second kind entirely and had to be taught to ask
for the pid.
