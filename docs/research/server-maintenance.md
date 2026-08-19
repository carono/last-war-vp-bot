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

`None` on six runs spread over ten minutes, while `daemon=warm` and every run itself
reported `OK`.

**And here is the caveat that keeps this honest:** the client's process was replaced at
least twice inside the window. A daemon pinned to a process that no longer exists answers
exactly the same way — warm, `OK`, nothing back — so the VM's silence cannot be blamed on
maintenance alone from this recording. What settles it costs one reading and was not
taken: **compare the daemon's attached pid with the client's live pid**. Do that first
next time; if they match, the silence is the game's.
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

**And it came back on the game port before the game did.** At 13:13 the client was
dialling `<gw5>:10012` again — the ordinary game port — with a third process id, and the
VM was still answering nothing and every errand still failing on the same gate. So «the
game port is back» is not «the server is back», and a panel that waited on the port alone
would resume too early.

**The sockets did not close.** The link verdict stayed `ONLINE` the whole time — this is
NOT the half-closed `LOST` state (`docs/research/server-link-status.md`), which is a
different failure that happens to look the same from the outside. The client kept opening
fresh connections rather than sitting on a dead one.

## 4a. THE GAME'S OWN WORDS — the key, found (2026-08-19)

The one artefact §5 called the most valuable, read out loud by the person at the machine
and then looked up in the client's own tables (`tools/game_locale.py`, all nineteen
languages ship on disk). It is not a guess: the sentence matches a key exactly.

**`login_err_tips_maintenance_new`** — what was on screen:

```
en  The server is under maintenance.\nPlease wait a moment, we'll be back with you shortly!
ru  Сервер находится на техническом обслуживании.\nПодождите немного, мы скоро встретимся!
```

It is one of a small family, and the differences matter to whoever writes the gate:

| key | what it is |
|---|---|
| `login_err_tips_maintenance_new` | **the one shown here** — no code, no time |
| `login_err_tips_maintenance` | the older wording, and it carries a code: `({0}) Server is under maintenance.` |
| `E100069` | «Server under maintenance, login later!» — the ERROR-CODE namespace, the same family the session kick lives in (`E100083`, docs/research/session-kick.md) |
| `129012` | «Server maintenance in progress. Please log in later.» |
| `2700002` / `2700003` | «Under Maintenance» / the update-notice title |
| `brickweb_desc_error5` | «Servers under maintenance» — the web view's wording |
| `server_open_tips001` | «The target warzone is under maintenance» — a CROSS-SERVER jump refused, not this account's own zone |
| `server_maintenance_001` | «the opponent's server is under maintenance» — a duel refused, ditto |

The last two are worth keeping apart from the rest: they say somebody ELSE'S warzone is
closed while this one is playable, which is a completely different thing to do about.

**So the recognisable sign exists and it is a key, not a sentence.** Any of
`login_err_tips_maintenance_new`, `login_err_tips_maintenance`, `E100069` or `129012`
showing in the client is «the server is closed», in whatever language that client runs.
Reading which key a dialog was built from still needs the Lua VM — which is exactly what
was silent (§3) — so the practical order stays: try the VM, and fall back to matching the
rendered text against these keys read out of the game's own tables.

## 4b. Is there a finish time? Not in this message — but a WARNING exists

The login message carries neither a deadline nor a code. Two other keys say the game does
announce the shutdown BEFORE it happens:

```
120036  The server will shut down for maintenance in {0}-min
120037  The server will shut down for maintenance in {0}s
```

…and the season variant is the only one that estimates the length at all:

```
season_close_tips01  The season has ended, and the server is currently under maintenance.
                     (Estimated time: 10-30 minutes)
```

**That changes the shape of the fix.** A panel cannot ask «when does it end» — nothing
offers that — but it CAN hear «it starts in {0} minutes» and park the queue before the
door closes rather than discovering it shut. Whether those two arrive as a push or only
as a client-side countdown was not established and is the next thing to read.

## 5. What was NOT captured, and how to catch it next time

Said plainly, because a gap nobody names is a gap nobody closes:

* ~~the game's own words~~ — **got them** (§4a), and the way it was done is the lesson:
  the person at the machine read the dialog out loud and the key fell out of the client's
  own tables in one lookup. Ask for the sentence FIRST, before anything clever.
* ~~whether the game says when it ends~~ — **answered** (§4b): it does not, but it warns
  before it starts.
* **which key the dialog was actually built from.** §4a matches the rendered text, which
  is one step short of reading the key off the window itself. That still needs the VM.
* **whether `120036`/`120037` arrive as a push** or are drawn from a client-side clock.
  If they are on the wire, the panel can hear the door closing.
* **the frames on `10935`.** Nobody decoded them; the captures were filtered for the
  panel's own patterns and reported zero map responses, which says only that nothing they
  KNOW about arrived.
* **whether the client was kicked or restarted into this state.** Its process changed at
  least twice during the window, once in the same minute as a panel restart, so nothing
  here separates «maintenance replaced the client» from «the panel's own recovery did».
* **the daemon's attached pid against the client's** (§3). One reading, and it decides
  whether the VM silence in this file is the game's or the toolkit's.

## 6. What the panel should do about it

**One of these is now done.** The operator's instruction was one sentence — «при
техобслуживании клиент перезапускай каждые 15 минут» — and it is
`Recovery.note_session` (`panel/runtime/recovery.py`, pinned by
`tests/test_panel_maintenance_knock.py`): a client that is up, connected and NOT in the
game for longer than the grace is restarted, then once every fifteen minutes for as long
as that lasts. A restart cannot reopen a server; what it does is KNOCK, because a client
left on the maintenance dialog does not come back by itself when the door opens, and this
way the account is playing again within a quarter hour of the server returning instead of
whenever somebody notices. The grace is deliberately longer than a login takes (`launch_game`
waits up to 300 s for the city scene), a person at the machine still wins, and a kick's
own wait is not interrupted to knock. Both front-ends draw «не в игре N мин — перезапуск
через M» rather than silence.

The rest is still a proposal, written down so the next window is spent confirming rather
than rediscovering.

1. **Name the state.** A fifth verdict beside `online` / `offline` / `lost` /
   `session_unknown`, recognised by the game's own keys — §4a has them now, and
   `docs/research/session-kick.md` is the worked example of reading exactly this kind of
   sign off a live client. The heuristic stays useful as a second rung for a client whose
   VM will not answer: link `ONLINE`, VM answering `None` to everything, warzone reading
   `0`, and no traffic on the game port for N minutes.
2. **Park, do not spend.** Every errand currently FAILS once per fire, which burns retry
   budgets and fills the log with the same sentence twenty times. A recognised maintenance
   state should hold the queue the way a refused gate already does (#1416) and say so once.
   The knock above does NOT do this: it puts the client back and says so, and the errands
   in between still fail one by one.
3. **Stop conflating «cannot say» with «is not there».** `not_in_world` must mean the
   client answered and said «city»; a VM that answers nothing deserves its own reason, and
   the flow strip already has the vocabulary for it (`panel/runtime/flow.py`, `refused`).
4. **Hear the door closing.** `120036`/`120037` count the shutdown down in minutes and
   then seconds. If they are readable, the honest behaviour is to stop starting new
   errands a minute before the server goes rather than to have twenty of them fail after
   it has.
5. **Say it in one place.** The profile light should read «сервер на обслуживании», not
   «не удалось спросить клиент» — the person then knows to wait rather than to restart the
   client, which is what «не удалось спросить» invites and what makes it worse.
