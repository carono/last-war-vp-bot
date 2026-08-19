# The client update of 2026-08-19: encrypted Lua chunks, and a moved server port

**Tasks #1555 (what broke) and #1556 (how the bridge was reopened).** On 2026-08-19, after a morning of server maintenance, the panel stopped
being able to drive the game — while every indicator it draws stayed green. Two separate
things changed in the client that day, and a third was a reading of ours that had been
wrong for as long as it had existed. This file records all three, because a client update
is not a one-off: this is the second time the game's port has moved, and the first time it
has changed how its scripting layer accepts code.

## 1. What happened, on the clock

| time (game clock) | reading |
|---|---|
| 12:40:40 | the last `READ_LUA` in the whole log that came back with a value |
| 12:41 | the client exits; `lwScripts\LWScripts.data` (41 MB) and all 131 `Assemblies\*.rdl` are rewritten |
| 12:42 | the client is back — and never answers a Lua chunk again |
| 12:41 – 15:43 | four client restarts by the recovery, none of which helps |
| 15:16 | a capture reports `GAME STREAM FOUND — <ip>:10935`; the game's port has moved off `:10012` |

The panel's own systems line said `game=up link=online daemon=warm` through most of that.

## 2. The Lua VM now refuses plain source

Every chunk the panel sends goes to `XLuaManager.SafeDoString`. Since the update, every
one of them comes back in `Player.log` as:

```
xLua exception : syntax error
   at XLua.LuaEnv.ThrowExceptionFromError (System.Int32 oldTop)
  at XLua.LuaEnv.DoString (System.Byte[] chunk, System.String chunkName, XLua.LuaTable env)
  at XLua.LuaEnv.DoString (System.String chunk, System.String chunkName, XLua.LuaTable env)
  at XLuaManager.SafeDoString (System.String scriptContent)
```

It is not our transport, and that was measured rather than assumed:

* a fresh out-of-process route builds the managed string correctly — read straight back
  out of the client's memory, the `System.String` at the pointer we pass has the right
  length and the right characters;
* the same failure comes from `LuaEnv.DoString` called **directly**, which does not
  swallow errors the way `SafeDoString` does;
* **a comment-only chunk fails**. `-- LW_GAME_LOG` cannot be a syntax error in any Lua
  there has ever been. Whatever the loader is parsing, it is not what we sent.

The client says so itself. In its data folder, beside `Player.log`:

```
xlua_version.txt   ->  enc
lwScripts\LWScripts.data   41 MB, rewritten at 12:41
```

So the build now runs an **encrypted-chunk** Lua: the loader decrypts every buffer before
parsing it, our plaintext decrypts to noise, and the parser says the only thing it can.
The native side is `xlua.dll`, which exports `luaopen_*` and `xlua_pack_*` and **no**
`lua_*` / `luaL_*` by name — and that reading was half right for the wrong reason. The
exports are all still THERE — 255 in both builds, and the 231 that used to be the Lua
core now export under names of the shape `x` + eight hex digits. Nothing was removed and
nothing moved below the managed API; the plugin simply stopped saying what its functions
are called. (The mapping was never needed: the decrypt was found by the string `LENC` in
`.rdata` and its one cross-reference, not by a symbol.)

**Everything the bot does goes through this bridge**, so while it was refusing us the
panel could read the wire (the captures were untouched — rally pushes, map tiles and
secret tasks all still decoded) and press nothing at all. §2.1 is how it was reopened.

## 2.1 What the loader actually wants — and how it was read (#1556)

The whole answer is on disk, in two files the client keeps for itself, and it took no
live game to get at: the install keeps the plugin it replaced beside the new one
(`Plugins\x86_64\xlua.dll.bak`, and six more builds of it under `Temp\`), which makes
the update an A/B rather than a guess.

**The format.** A chunk is refused unless it arrives as:

```
LENC <ChaCha8 keystream XOR> ( raw source | zlib stream )
```

* `LENC` is four bytes and it is MANDATORY. The loader reads the whole buffer through
  the reader callback, compares the first four bytes, and on a mismatch returns failure
  before a single character is lexed. That is the entire outage: our plaintext never
  reached a parser, so the parser's only possible complaint — «syntax error» — is what
  came back, comment or no comment.
* the body is XORed with a **ChaCha8** keystream: four double rounds, 32-byte key,
  12-byte nonce, block counter starting at 0 — and **no final feed-forward addition** of
  the starting state. That last omission is what makes it not ChaCha20 and not any
  published ChaCha; a stock implementation decrypts it into noise.
* what comes out is inflated when it begins with a zlib header (`78 DA`) and taken as
  source otherwise. The game's own scripts are all deflated bytecode (`1B 4C 75 61 53`,
  Lua 5.3); ours are source, which is shorter than a deflate of itself at chunk sizes.

**Where the key is.** Not in the file as a run of bytes — it is assembled at use, and
that is why searching for it finds nothing. Two 44-way jump tables, each arm a
`mov al, imm8 ; ret`, are walked index by index and XORed together: bytes 0..31 are the
key, 32..43 the nonce. The dispatchers have a shape that is easy to recognise and hard
to confuse with anything else:

```asm
cmp cl, 44
jae  short
movzx eax, ecx
lea  rcx, [rip + table]
jmp  qword ptr [rcx + rax*8]
```

**So nothing here is written down as a constant.** `tools/lib/lua_chunk_enc.py` reads the
scheme out of the INSTALLED plugin at start-up, by that shape, and then checks the result
by decrypting the first chunk of the client's own `lwScripts\LWScripts.data` — which the
hot-update rewrites, so the sample always describes the build that is running. A patch
that rolls the key is followed silently; a patch that changes the CIPHER stops with a
sentence naming this file, instead of quietly producing chunks the game refuses. The
round count and the feed-forward flag are part of what the check chooses, so a rebuild
that merely re-tunes those is followed too. Sixteen milliseconds, once per process.

**And the way in had to change with it.** `XLuaManager.SafeDoString` takes a
`System.String`, and xLua UTF-8 encodes it on the way to the VM — which mangles every
byte above 0x7F, and half of a keystream is above 0x7F. So an encrypted build is driven
through `LuaEnv.DoString(byte[], string, LuaTable)` instead: the wrapper is built on this
side, handed over as a managed `byte[]` (`il2cpp_array_new`, written with
`WriteProcessMemory`), and arrives byte for byte. `LuaEval` picks the route from what the
plugin says rather than from a setting, so a client patched back to plain source goes
back to `SafeDoString` by itself, and `LW_LUA_ENC=off` forces that by hand.

One thing improves in passing: `DoString` does NOT swallow errors the way `SafeDoString`
does, so a chunk that will not COMPILE — which never reaches the `pcall` the answer
wrapper puts around it — now says so in the daemon's log instead of vanishing.

**What was NOT needed, and is worth not repeating.** No patching of the client's memory
(the LENC compare is one `jne` away from being nopped, and an anti-cheat is in the
process — feeding the loader what it asks for is both cheaper and quieter), no calling
the renamed native exports, and no rewriting the repository's ~280 chunks as calls into
the game's own functions. Every one of those was on the table before the two files were
compared.

## 3. The game's port moved: `:10012` -> `:10935`

The capture finds the port off the client's own socket table rather than a constant, so it
followed by itself and never went deaf. Two things did NOT follow:

* `game_paths.DEFAULT_GAME_PORT` is still the historical `17935`, used only as a
  last-resort fallback — harmless, and left alone deliberately: the live socket is asked
  first, and pinning a number that has now moved twice would be the same mistake again.
* the client kept its **old** `:10012` sockets in `CLOSE_WAIT` after the migration.

That second one is what made the panel restart the client four times for nothing.
`game_link.classify` takes a conversation with half-closed sockets and no established one
as positive proof of a loss — the rule bought with #1266, where a dead GAME conversation
was being outvoted by a live CONTROL one. Here it fired the other way round: the dead
conversation was the abandoned old port, the live one was the game on `:10935`, and
sockets alone cannot tell those two apart.

**A restart does NOT cure it, and the first draft of this file said it did.** Measured on
a client eight minutes old, started long after the update, while the game was plainly
running:

```
conversations = {10012: (None, 6),  10935: (<established>, 0)}
classify      = ("lost", None, 6)
```

Six half-closed sockets on the OLD port, to three different gateway addresses, on a client
that has never seen the old server come up. So the client still DIALS `:10012` on every
login — the old address is in the list it works through — the far end refuses, and the six
corpses stay for the session while the game runs on `:10935`. `lost` is therefore the
**permanent** reading on an updated client, not a leftover that one restart sweeps away.

**And by the socket table alone it is indistinguishable from #1266.** That night was six
half-closed sockets on one port and one established socket of another conversation — the
same two rows, differing only in which port number is which. Nothing else in the table
tells them apart, and this file is not going to guess: the last four times somebody
decided which conversation was the game from its shape, it cost a night each time.

What HAS changed under the rule is the assumption `conversations()` is written on — «one
conversation is many addresses on ONE port», because the client greets several gateways
and keeps one. The patch broke that: the race now runs across **two ports**, and grouping
by port cuts one race in half and reports the losing half as a dead conversation. That is
the thing to fix, and it needs a second reading to fix it honestly — the wire, which the
capture is already watching (`GAME STREAM FOUND — …:10935` is exactly the missing fact).
Left as its own task rather than guessed at here.

Also gone from the table: `:17935`, the control channel, entirely. Everything that is not
the game is now on `:443`, which was already excluded — so on THIS build the only
non-`:443` established conversation is the game. That is an observation, not a rule: it is
the very shape of reasoning that bought #1266.

## 4. The false green, and where it was manufactured

This is the part that was ours.

`tools/lib/daemon_pulse.py` exists precisely so that «warm» stops meaning «the port
answers». The rule is: a chunk that reached the game recently is the only proof; every
successful run stamps it; an idle daemon probes itself; the ping carries the AGE of the
last chunk that landed.

`Daemon.run()` broke it in one line. It did:

```python
lines = pending.harvest()
self.pulse.ok()            # <- regardless of whether anything came back
```

The panel is never idle, so every silent errand reset the landing clock, `heartbeat()`
(which DOES look at what came back) never became due, and the ping answered
`warm, last_ok_age 0.81, misses 0` after three hours in which not one chunk had run. The
one honest reading in the system had been turned into a rubber stamp by its busiest
caller.

Fixed: `run()` stamps a success only when the run brought something back. An empty run
stamps **nothing** — it is not a failure either, because a chunk that logs nothing
legitimately returns nothing; it is simply not evidence. The age then grows until either a
run brings a line back or the self-probe, which knows exactly what its own chunk should
print, answers for it. The cost is at most one probe per `IDLE_PROBE_SEC` on a daemon
serving nothing but silent chunks — which is what that interval was already priced for.

With that in place the same client reads `daemon=stale`, then `daemon=none` once the
daemon lets go of the port after three failed probes. The words already existed
(`daemon.warm` / `daemon.stale` / `daemon.none`, `health.daemon_stale`) in all eleven
locales; nothing new had to be said, the panel simply had to stop lying. Measured on the
live client immediately afterwards: `daemon=warm` for about twenty seconds after each
start, then `daemon=down`, and «демон не работает — таймеры и триггеры ждут, ничего не
запускается» in the log — where the three hours before it had said `warm` without a
break.

**And it settles into a cycle, which is the recovery working rather than thrashing.** The
daemon leaves because it cannot drive the client; the panel starts another because a port
nothing answers is a state it knows how to cure. Against a client whose Lua refuses
everything neither can win, so a fresh daemon is built once every `DAEMON_COOLDOWN_SEC`
(two minutes) — the log says «служебный демон недавно уже запускался — жду 2 мин» in
between, and that damper was already there. It is loud, which is what a wrong reading is
supposed to be, and it is not worth quietening: the cycle is a symptom of a client the
panel cannot use at all.

## 5. The checklist for the next client patch — with this patch's answers

A client update will happen again. This is the order to walk, what each step costs, and
what it answered on 2026-08-19, so the next agent reads a table instead of repeating two
hours of probing. Every one of them is asked of the LIVE machine; not one is answered from
a constant in this repository.

### 5.1 Is the daemon holding the client that is actually running?

The cheapest and the most often guilty: a client that updates is a NEW process, and a
daemon left on the old pid answers its port perfectly and drives nothing — from outside,
indistinguishable from maintenance.

Ask: the live client's pid (the process list, or `game_client.target_pid`) against the
`pid` field of a `{"op":"ping"}` to the profile's daemon port.

> **2026-08-19: NOT the fault.** Checked twice, across two different clients — ping said
> `pid 47292` while the live client was 47292, and later the daemon had already let go of
> the port with the live client at 12320. The binding was right the whole time.

### 5.2 Have the addresses and the paths moved?

Ask the live socket table for the port, never a constant, and
`tools/lib/game_paths.py`'s own `report()` for the install, the data folder, the download
tree and the bundle cache.

> **2026-08-19: the port moved, `:10012` → `:10935`.** The captures followed by
> themselves (they read the port off the socket table). Install, data folder, bundle
> cache and download tree were unchanged, and `game_paths.game_port()`'s historical
> `17935` is only a last-resort fallback, so nothing had to be edited. The trap here is
> §3 above: the corpses of the old port make the link read `lost` for ever.

### 5.3 Does the way INTO the game still exist under the names we use?

This is the expensive one, and it splits into two questions that look like one. First,
whether the names still resolve — a patch renames and moves C# classes, and everything we
reach is reached by name. Second, whether a chunk that reaches the VM actually runs.

Ask, in this order, and stop at the first that fails:
`GameEntry.get_Lua` resolves and is static → it returns a manager → `XLuaManager
.SafeDoString` resolves → `il2cpp_string_new` gives back a string that reads out of the
client's memory as the text we sent → the chunk produces its line.

> **2026-08-19: the names were all fine and the last step failed.** `get_Lua` resolved
> and returned a manager with no exception, `SafeDoString` resolved, and the string read
> back byte for byte (`len 15`, `-- LW1555 audit`). The chunk still came back as
> `xLua exception : syntax error` — so the break is the Lua PARSER, past everything we
> control (§2). Resolving the names and running a chunk are two different proofs; a patch
> can break either, and only the second one was broken here.

### 5.4 Is the reading empty because the client is new?

A panel restart does not clear the game's own Lua state, but a client update clears
everything: caches, managers, whatever a collector had accumulated. An empty reading right
after a patch is a new client, not a broken collector — do not go hunting the collector.

> **2026-08-19: not reached.** The VM answers nothing at all, so there is no empty reading
> to misread. Noted so the next patch — where the VM DOES answer — is not misdiagnosed.

### 5.5 Is the recovery fighting the patch?

A client that is downloading or applying an update is a client that is not in the game,
and the «knock on a client that is connected but not playing» cure will restart it out
from under the download.

> **2026-08-19: it behaved.** Two client restarts in the hour (15:53 and 16:01), then
> `«клиент не слышен, но недавно уже перезапускался — жду 7 мин»`. After `FRUITLESS = 2`
> restarts that changed nothing the blame moved off the client by itself (`blame:
> daemon`), which is what that counter is for. The patch had already been downloaded and
> applied at 12:41, so nothing was interrupted. Worth re-checking mid-download, where the
> `STALLED_GRACE_SEC` of seven minutes is the only thing standing between the cure and a
> half-applied patch.

### 5.6 And read the two logs that say it out loud

`Player.log` — `xLua exception` lines are the bridge refusing us, and nothing in the panel
says so. The daemon's ping — `last_ok_age` and `misses`, which mean something again since
§4.
