# The panel IS the link: three statuses, no daemon, no watchers (#1911)

> На русском: этот файл — исследовательская записка, как и все в `docs/research/`.
> Список возможностей для игрока — `docs/farming.md`.

The decision this records, in the operator's own words:

> «Демон — это теперь неотъемлемая часть панели, панель и есть демон, она всегда
> работает, она может подключаться к нужному клиенту. Если есть клиент, видит, но не
> получает трафик — статус ЖЁЛТЫЙ. Если клиент не обнаружен — статус КРАСНЫЙ. Если есть
> трафик от игры — статус ЗЕЛЁНЫЙ. Это всё, никаких кривых демонов.»

> «Если клиент жив, но нет сигнала, значит одно из двух: или клиент завис, или косяк в
> реализации подключения, и это нужно исправлять.»

Everything below is what that meant in code, what was deleted, and — the part worth
keeping — WHY the readings that survived are the ones that survived.

---

## 1. What a daemon was, and why it stopped being worth having

`tools/lua_daemon.py` existed for one measurable reason: `LuaEval.__init__` resolves the
xLua facade through a thread hijack and an il2cpp walk, which takes seconds, and a panel
that paid that per press would be unusable. Keeping ONE warm evaluator alive is worth
about 5 s a call ([`daemon-architecture.md`](daemon-architecture.md) §1).

Nothing about that argues for a separate PROCESS. The warm VM is what is valuable; the
process was where it happened to live, and the process is what everything since has been
about — «is it up», «is it warm», «is it holding the client that is running», «who starts
it», «who restarts it», «who watches the watcher». Six of the last twenty incidents were
about the supervision and none about the VM.

So the VM moved into the panel (`panel/runtime/lua_service.py`) and the supervision was
deleted rather than fixed. «The panel is running» and «the link is there» are now one
fact, which is the only version of this that cannot go wrong in a way nobody notices.

**The socket door stayed.** Two dozen tools under `tools/` are spawned as CHILD processes
by the panel and drive the game through `tools/lib/lua_client.py`; a child cannot share
the parent's evaluator, and two hijacks racing one client is what the lease exists to
prevent. So the service listens on the profile's port and speaks the protocol the daemon
always spoke — same ops, same lease, same pulse. From a child's side nothing changed. The
panel itself does not use the socket at all: `lua_service.LocalClient` is the same
surface with the round trip taken out.

## 2. The three statuses, and the two readings behind them

`tools/lib/profile_health.py` is the whole rule and it is a pure function of ids:

| colour | reason | what it means | what to do |
|---|---|---|---|
| RED | `no_client` | no client process | start the client |
| AMBER | `client_hung` | chunks do not land and the window is hung | restart the client |
| AMBER | `no_connection` | chunks do not land and the client is fine | **fix us** |
| AMBER | `no_traffic` | chunks land, the server says nothing | restart the client |
| GREEN | `traffic` | the game server answered | nothing |

Two independent readings decide it, and neither is a socket table:

* **does a chunk land?** The panel runs one trivial line in the client's Lua VM and it
  comes back (`daemon_pulse.Pulse` — every errand stamps it, a self-probe fills the
  silences, so it is free while the panel is working). No server is involved, so this is
  a reading of OUR wiring and of nothing else;
* **does the SERVER answer?** `actions/read_server_info.md` about a warzone that is NOT
  this account's. Its own warzone the client answers out of its own memory; a foreign one
  is a real round trip. Measured on a healthy client on 2026-08-24: **27 answers out of
  27, every one inside a second**. A client whose socket the far end has closed cannot
  make it — the send returns `true` and nothing arrives.

The panel asks the server question at most once every `PROBE_REFRESH_SEC` (120 s) while
the light is green and on the decision's own throttle while it is not, so a healthy
profile pays about one round trip every two minutes for its colour.

**Rejected readings, and why.** `GetServerTime()` — the local tick plus an offset fixed
at login, so it advances happily in a client that receives nothing. The socket table —
`game_link.classify` cannot say which conversation is the game: on 2026-08-24 a client
held six half-closed sockets on an ABANDONED gateway set (port 10012, `est=0`) and a live
game conversation on another port (10935, `est=1`), and the rule read the abandoned set
and declared the link dead. The damage was not theoretical: the scenario gate refused
every `join_rally` for hours.

## 3. Amber is a diagnosis, and it names the culprit

The operator's sentence — «или клиент завис, или косяк в реализации подключения» — is the
reason `client_hung` and `no_connection` are separate reasons under one colour. The cures
are opposites, and reaching for the wrong one is #1268's six pointless client relaunches
committed on purpose.

They are told apart by asking Windows: `game_client.responding(pid)` walks the client's
top-level windows and asks `IsHungAppWindow`. A wedged process is a restart;
a process that is answering its message queue while our chunks do not land is OURS —
the panel says so loudly, tries the attach again, and **never restarts the client for
it** (`panel/__main__.py::_recovery_check`). Where the question cannot be asked the
answer is «responding», because a machine that will not answer may not convict a client.

## 4. What was deleted

* `tools/lib/panel_guard.py` — the panel watchdog that lived INSIDE the daemon, elected
  one-per-machine by a lock file. It existed because the daemon was the process that
  outlived the panel; there is no such process now, and a guard the panel starts is a
  circle. The hourly Windows task (`panel/runtime/autostart.py`) still puts a panel back
  after a reboot, which is the case only the OS can answer;
* `GameLink.ensure/restart/stop/_shutdown/_wait_free/_kill/_start/health/last_health/
  listening/attached/ping/daemon_pid/launch_error` — the whole lifecycle;
* `Recovery.note_daemon`, `Recovery.note_daemon_down`, `down_wait_left`, the wait that
  doubled to `DOWN_WAIT_MAX_SEC`, and the ALTERNATION that moved the blame between two
  cures after `FRUITLESS` client restarts. There is one cure left. `fruitless` is still
  counted and drawn, because «второй перезапуск подряд впустую» is worth seeing;
* every intermediate verdict: `unknown`, `unread`, `not confirmed`, `daemon none`,
  `daemon stale`, `listening but no client`, `online/offline/lost`. Three colours means
  three, and a profile nothing has read yet is RED — the same thing a closed game shows,
  corrected by the first poll eight seconds later.

## 5. What did NOT change, deliberately

* **The claim.** Three locks, exactly as before: the link's own flag, the process-wide
  registry keyed by the client (`panel/runtime/claims.py`) and the lease
  (`tools/lib/game_lease.py`). One Windows session holds one client, so the panel's
  service is a per-process singleton and every profile open on it shares the run lock and
  the lease — which is what keeps two profiles pointed at one game taking turns;
* **the kick's patience** (15 → 30 → 45 min), the player gate, the cooldown, the
  maintenance knock. All of them were about a CLIENT and none about a daemon;
* **the second Windows session.** A hijack finds its client in the session it is itself
  running in, so a client over there cannot be driven from the panel's process however
  the panel is written. `tools/lua_daemon.py` remains for exactly that case, started by
  `GameLink._ensure_remote` and owned by it: nothing supervises it, nothing re-elects
  anything, and a silent one is simply started again.

## 6. What it costs

* A panel restart now costs the warm VM: the first call after a restart pays the attach
  (seconds, once, per local profile). Before, the daemon survived the restart. This is
  the price of «the panel is the link» and it was accepted deliberately.
* A fault in the hijack path now happens inside the panel's process rather than in a
  process that could be replaced. The attach is guarded and its failures are states
  (`no_connection`), not crashes — but the isolation a separate process gave is gone,
  and that is the other half of what was traded away.
