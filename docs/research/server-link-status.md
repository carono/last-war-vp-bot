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

## 3. The four answers, and why not two

`panel/runtime/game_process.probe()` returns a `Probe`: the old `running` boolean, plus a
`link` that is one of four.

| link | how it is decided | why it is its own answer |
|---|---|---|
| `online` | an ESTABLISHED game socket owned by this client | the only proof the account is playing |
| `lost` | no ESTABLISHED one, and ≥1 in `CLOSE_WAIT` / `CLOSING` / `LAST_ACK` / `FIN_WAIT1` / `FIN_WAIT2` | a fact, not a guess: the far end hung up and nothing replaced it (§2.1 — the count alone proves nothing) |
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
can produce present in all eleven locales.
