# Server maintenance, caught live (#1549)

**Recorded while it was happening, 2026-08-19, roughly 13:00–13:15 game-machine time**,
on the operator's word: «сейчас сервер находится на тех обслуживании, поймай это
сообщение для будущих анализов». It is a state nobody can reproduce on demand, so this
file is what was actually observed plus an honest list of what was NOT captured and how to
catch it next time.

**No account identifier is in this file.** Server addresses are written `<gwN>`, the
warzone is whatever the reading said (`0`, which is the game's own «nobody could say»),
and process ids are left out because they say nothing a reader needs.

---

## 1. The headline: every indicator the panel has was GREEN

This is the finding, and it is worth more than anything else here.

```
[panel] systems: game=up link=online daemon=warm timers_on=10 triggers_on=7 dashboard=on
```

That line repeated every few seconds throughout. The client process was up, its socket was
open, the Lua daemon was warm — and the game was unplayable. The only amber came from the
profile light, and it named the wrong thing:

```
light: warn | session_unknown | «не удалось спросить клиент, в игре ли он»
tips:  Игра: онлайн → <gw1>:10935 · Демон: тёплый · Сессия: не спрашивали
```

**`session_unknown` is the verdict for «we could not ask», not for «the server is
closed».** The panel therefore cannot tell maintenance from a client that is still
logging in, from a client sitting in its base, or from a daemon that has lost the VM. All
four print the same sentence.

## 2. What every scenario said

Not one errand ran. All of them stopped at the link gate, with the same words
(`script_engine`'s last rung, `docs/research/server-link-status.md`):

> the client is connected but not in the game yet — the link that is up is not the
> game's own conversation and the client will not say what time it is. Wait for the
> login to finish

That is the gate's FALLBACK sentence: the socket verdict was `ONLINE`, the client was not
showing the «logged in elsewhere» message, and the session simply would not confirm. So
maintenance arrives at the gate's «still logging in» branch and waits for a login that is
not going to finish for as long as the window lasts.

Two more readings, both from the same window:

* `[secret] сервер взят из игры: 0` — the warzone reads as `0`, the game's «no answer».
* `[secret] …running — server unknown yet, 0 map response(s), 0 tile(s)` — the captures
  are alive and decode nothing.

## 3. The Lua VM answers NOTHING while the daemon reports warm

A one-line probe played through the panel's own scenario runner:

```
READ_LUA (function() … SceneUtils.GetIsInCity() … end)() INTO probe1
→ READ_LUA probe1 = None
```

`None` twice, on two separate runs, while `daemon=warm` and the run itself reported `OK`.
So during maintenance the VM is reachable enough for the interpreter to call it and
returns nothing usable. **Everything that reads the game therefore answers «unknown»
rather than failing** — which is why the monster poll's own reason came out as
`not_in_world`: the DSL condition `IF scene == world` cannot be true when the scene reads
`unknown`, and the recipe took its ELSE branch. That reason is a CONFLATION, and it is the
second-biggest finding here: «the client is in its base» and «the client cannot say» are
one word in the panel today.

## 4. On the wire: a different port, and a rotating address

Normal play on this machine uses two ports — `10012` for the game's own conversation and
`17935` for the control channel. Throughout the maintenance window the client was dialling
**`10935`**, and the address behind it kept changing:

```
13:03:03  GAME STREAM FOUND — <gw1>:10935
13:03:09  GAME STREAM FOUND — <gw2>:10935
13:06:56  GAME STREAM FOUND — <gw3>:10935
13:10:52  Игра: онлайн → <gw4>:10935
```

Four different addresses on the same port inside eight minutes, and `10012` disappeared
entirely — the panel's own port detection had by then rewritten every capture's filter to
`tcp port 10012 or tcp port 10935`.

**What this is NOT yet:** proof that `10935` is «the maintenance port». It is the port the
client was using while the game was closed, and it was not in use before 13:03 in a log
covering the whole day. Two readings would settle it, and neither was taken: whether
`10935` is also used during an ordinary login, and what the frames on it actually carry.

**The sockets did not close.** The link verdict stayed `ONLINE` the whole time — this is
NOT the half-closed `LOST` state (`docs/research/server-link-status.md`), which is a
different failure that happens to look the same from the outside. The client kept opening
fresh connections rather than sitting on a dead one.

## 5. What was NOT captured, and how to catch it next time

Said plainly, because a gap nobody names is a gap nobody closes:

* **the game's own words.** The exact on-screen text and, more importantly, the LOCALE KEY
  behind it and any error code the server sent. This is the single most valuable artefact
  — a key like `E1000xx` is how the state gets recognised in code — and it could not be
  read, because the Lua VM answered nothing (§3). Next time: ask the person at the machine
  to read the dialog out loud BEFORE trying anything clever, and take a `tools/…` packet
  capture on `10935` while the dialog is up.
* **whether the game says when it ends.** Nothing was readable, so it is unknown whether a
  finish time is offered at all. If it is, it is a ready-made gate: the panel could park
  every errand until then instead of failing each one on its own clock. Worth one probe
  the moment a VM answers during a window.
* **the frames on `10935`.** Nobody decoded them; the captures were filtered for the
  panel's own patterns and reported zero map responses, which says only that nothing they
  KNOW about arrived.
* **whether the client was kicked or restarted into this state.** The client's process
  changed around the same minute as a panel restart, so the two cannot be told apart from
  this log.

## 6. What the panel should do about it — a proposal, not a change

Nothing in this file has been acted on; it is written down so the next window is spent
confirming rather than rediscovering.

1. **Name the state.** A fifth verdict beside `online` / `offline` / `lost` /
   `session_unknown`, recognised by the game's own message key once §5 has it. Until then
   a HEURISTIC is available and cheap: link `ONLINE`, VM answering `None` to everything,
   warzone reading `0`, and no traffic on the game port for N minutes.
2. **Park, do not spend.** Every errand currently FAILS once per fire, which burns retry
   budgets and fills the log with the same sentence twenty times. A recognised maintenance
   state should hold the queue the way a refused gate already does (#1416) and say so once.
3. **Stop conflating «cannot say» with «is not there».** `not_in_world` must mean the
   client answered and said «city»; a VM that answers nothing deserves its own reason, and
   the flow strip already has the vocabulary for it (`panel/runtime/flow.py`, `refused`).
4. **Say it in one place.** The profile light should read «сервер на обслуживании», not
   «не удалось спросить клиент» — the person then knows to wait rather than to restart the
   client, which is what «не удалось спросить» invites and what makes it worse.
