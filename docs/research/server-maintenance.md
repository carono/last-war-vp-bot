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

**ANSWERED, AND THE ANSWER KILLS THE HYPOTHESIS (#1982, live on 2026-08-26).** `10935` is
an ORDINARY game port. Watched during a short outage the same afternoon: the captures
found the stream on `10935` at 12:37, and they were still decoding it half an hour later,
with the account back in the world — alliance pushes, rally banners going up and being
joined, chat. So the port a capture is following says nothing about whether the server is
open, and a panel that watched for `10935` would call an ordinary afternoon a maintenance
window. What DID change with the port is the address behind it, and that is a reconnect,
not a diagnosis. Read the client's own message instead (§4a) — which is what
`tools/lib/game_maintenance.py` does.

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

**And a second one is done (#1982): THE STATE HAS A NAME.** The key family in §4a is
what recognises it — `tools/lib/game_maintenance.py` reads the client's own message
window (the same round trip the kick already made, now made once and judged twice) and
compares the text with the game's own wording for every maintenance key, in every
language the client ships. What that buys:

* a fifth reason on the profile's light, `maintenance` (`tools/lib/profile_health.py`),
  drawn by BOTH front-ends out of the one verdict — «сервер на техобслуживании — игра
  закрыта, нужно ждать, а не чинить» in place of «клиент есть, трафика нет»;
* it NARROWS the amber it would have been and never touches green: a server that has
  just answered is playing, whatever dialog is on screen. Telling somebody their working
  account is closed is the expensive direction to be wrong in;
* the door CLOSING is its own state, and it is the one time the game names a number —
  `120036`/`120037` are read for their `{0}` and said in the log as «сервер уходит на
  техобслуживание через N мин». §4b's warning is therefore heard when it is drawn on the
  client; whether it also arrives on the wire is still unread;
* one log line per edge — shut, closing, open again — because a window lasts an
  afternoon and the strip is only true while somebody is looking at it;
* and `server_open_tips001` / `server_maintenance_001` are deliberately NOT read: they
  say somebody else's warzone is closed while this account's is playable.

What it does not do, said plainly: if the notice is drawn by some window other than the
client's generic message tip, the reading is «cannot tell» rather than «all is well» —
the knock above still runs, and the light stays the amber it was before. And it can only
be read while chunks land, which §3 says may not be true in the middle of a window; the
knock's restart is what gets the reading back.

The rest is still a proposal, written down so the next window is spent confirming rather
than rediscovering.

1. ~~**Name the state.**~~ **Done (#1982)** — the verdict is recognised by the game's
   own keys, exactly as this item asked and the way `docs/research/session-kick.md` does
   it. **What is left of the item is its SECOND rung**, still unwritten: a client whose
   VM will not answer at all shows nothing to read, and the heuristic for it was written
   down here — link up, the VM answering `None` to everything, the warzone reading `0`,
   and no traffic on the game port for N minutes. Until that exists, a window that eats
   the VM reads as «cannot tell» and the knock is what recovers the reading.
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
5. ~~**Say it in one place.**~~ **Done (#1982):** the profile light reads «сервер на
   техобслуживании» when the game's own message is on the client's screen, in the window,
   on the phone's pill and on the profile picker, out of one verdict. What it cannot do
   is say it when the client will not answer at all — that is rung 1's heuristic, still
   unwritten.

---

## 7. The second window, MISSED — and what was learned without it (#1982, 2026-08-26)

A maintenance window happened this afternoon and was gone before anybody could read the
client: «проворонил, игра вышла из режима ТО». The account was back on the world map,
chat scrolling, rally banners arriving. So this section is the OTHER way of learning the
state — out of what was already written down, and out of the client's own code and
tables — and it says plainly which parts are confirmed and which are inference.

### 7.1 What the recordings had (and did not)

* **`panel.log` — nothing at all.** The profile's own log had been frozen since 10:54,
  which is a bug of ours and now fixed (#1984): the machine's service runs the windowless
  panel and nothing drained the log queue. **The person's log was empty for exactly the
  minutes that mattered.**
* **`debug.log` — the whole shape of it**, and it is what §4's port claim was struck out
  on: the VM stopped answering at 12:34:35, «нет связи с игрой» at 12:37:07, «клиент не
  залогинен — он показывает пустой список альянса» at 12:38:44, and by 12:41 the client
  was in the city again. No error code, no message text: the panel had no way to read one.
* **The GAME's own log — silent.** `%LOCALAPPDATA%Low\<publisher>\<product>\Player.log`
  (and `Player-prev.log`, which is the client that lived through the outage) carries the
  Unity boot, shader warnings and scene unloads, and **not one line about the server, the
  connection or a dialog**. Worth knowing for next time: the client does not journal this.
* **`service.log`** has only the panel's own comings and goings — no game state.

### 7.2 The game's own name for the state — **`UIServerMaintenanceTip`**

The client's window table (`docs/research/ui-open-data/ui_window_names.json`, 2 221
names) has exactly one entry for this, and the live client confirms it exists:

```
READ_LUA … UIWindowNames.UIServerMaintenanceTip …
→ name=UIServerMaintenanceTip open=false cfg=false
```

`cfg=false` is not a contradiction: `windowsConfig` is filled when a window is first
built, so a window that has never been shown in this session has no entry — the same
behaviour every other UI class here has.

**That is the strongest rung the detector has**: a window name is the same in every
language and costs a flag rather than a comparison against nineteen locale tables. What
it is NOT is a sighting — nobody has yet seen it open, which is why the sentences below
are kept beside it and why the panel now records a sample the first time either fires.

The neighbours worth knowing, from the same table: `UIDisconnect`, `UICrossDisconnect`,
`UILogin`, `UILoginConfirm`. The panel reads all four as CONTEXT — where the client is
sitting while it shows what it shows — and none of them as evidence.

### 7.3 The key inventory, read out of the tables rather than guessed

The whole English table (52 970 keys) was scanned for the word. Everything that says it
**about the server**:

| key | what it is |
|---|---|
| `login_err_tips_maintenance_new` | the login screen's own, no code, no time |
| `login_err_tips_maintenance` | the older wording, carries a code: `({0}) …` |
| `E100069` | «Server under maintenance, login later!» — server error code |
| `129012` | «Server maintenance in progress. Please log in later.» |
| `2700002` / `2700003` | «Under Maintenance» / the update-notice title |
| `brickweb_desc_error5` | the in-client web view's wording |
| `120036` / `120037` | **the shutdown COUNTDOWN**, in minutes and in seconds |
| `season_close_tips01` | the season close — **the only sentence that estimates a LENGTH** |

…and what the same scan found and the detector deliberately leaves out: `132021`,
`132023`, `132024` (Radar / Rocket / Aircraft Maintenance — buildings), `zombieRush_tips_26`
(one subsystem down inside a playable game), `335002` / `335310` / `801010` (dialogue),
the whole `season_sN_update_notice_*` family (an announcement about a future patch, read
while the game is up), and `server_open_tips001` / `server_maintenance_001`, which say
somebody ELSE'S warzone is closed while this one plays.

The login-error family is small and worth having whole, because it is what the login
screen can say at all: `login_error_accountErr`, `login_error_client_ver_must`,
`login_error_connectFail`, `login_error_fileErr`, `login_error_serverErr`,
`login_error_updateFail`, and the two maintenance ones.

### 7.4 Is there an end time? Still no — with ONE exception, and it is the game's own

§4b stands: the message on the closed door carries no deadline. The two things that DO
carry a time are the countdown BEFORE it (`120036`/`120037`, «через N мин»), and the
season close, which writes its estimate into the sentence itself:

```
season_close_tips01  The season has ended, and the server is currently under maintenance.
                     (Estimated time: 10-30 minutes)
```

The panel now says that range when it sees that sentence — the game's own estimate,
never one of ours (`log.game.maintenance_estimate`).

### 7.5 What is CONFIRMED and what is INFERENCE

**Confirmed:** the key inventory (read off this machine's tables in 17 languages); the
wording in every language the panel ships; that `UIServerMaintenanceTip` exists on the
live client; that the countdown templates parse and yield minutes; that the game's own
log says nothing about any of it; that port `10935` is ordinary.

**Inference, and it is what the next outage settles:** that the server opens
`UIServerMaintenanceTip` (rather than the generic message tip, or a third window nobody
has named); that the login-time sentence reaches `UICommonMessageTip.View.tipText` at
all; and whether the countdown arrives as a push or is only drawn client-side.

**So the panel now writes the reading down when it fires** — `profiles/<name>/maintenance/
<stamp>-<state>.json`, git-ignored, holding the raw line the client answered, which rung
decided, which windows were open and what the light said. One real file ends the
guessing, and until there is one the ability stays 🟡 in `docs/farming.md`.
