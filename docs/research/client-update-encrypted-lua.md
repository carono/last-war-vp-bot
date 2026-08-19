# The client update of 2026-08-19: encrypted Lua chunks, and a moved server port

**Task #1555.** On 2026-08-19, after a morning of server maintenance, the panel stopped
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
`lua_*` / `luaL_*` by name — so the decryption sits below the managed API, and Lua's own
`load` is behind the same door as `DoString`. There is no cheap way round it: this is a
reversing job on `xlua.dll` (find the decrypt, encrypt our chunks the same way, or call
the post-decrypt entry point), and it is its own task.

**Everything the bot does goes through this bridge.** Until it is solved the panel can
read the wire (the captures are untouched — rally pushes, map tiles and secret tasks all
still decode) but it cannot press anything.

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

**The rule was deliberately left as it is.** It leans towards `lost` because the two errors
are not symmetric — a wrong `online` is silent and costs a night, a wrong `lost` is loud
and costs one restart — and the lean did its job here: the restart is what dropped the
stale `:10012` corpses, after which the reading went green and stayed green. What is worth
knowing is the shape of it, so the next port move is recognised in minutes: **a client that
is plainly receiving traffic while the panel reads `lost` is a client whose old
conversation has not been cleaned up. Restart it once and the reading corrects itself.**

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
locales; nothing new had to be said, the panel simply had to stop lying.

## 5. What to check first, next time the client updates

In order, and none of them takes more than a minute:

1. `%LOCALAPPDATA_LOW%\<publisher>\<product>\xlua_version.txt` and the mtime of
   `lwScripts\LWScripts.data` — a rewrite there is a scripting-layer change.
2. the tail of `Player.log` — `xLua exception` lines say the bridge is refusing us, and
   nothing else in the panel will say so.
3. the client's socket table — which remote port carries the established conversation, and
   whether corpses of an older one are still hanging about.
4. the daemon's ping — `last_ok_age` and `misses`, which are now trustworthy again.
