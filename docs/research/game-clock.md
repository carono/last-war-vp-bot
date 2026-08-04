# The game's clock is not this computer's clock

Task #1227. Every timestamp the client hands out — a hero dispatch's
`completionTime`, a tile's `actEndTime`, a ghost squad's return, a truck's arrival —
is epoch milliseconds on a clock the client and the server agree between themselves.
That clock drifts from the machine the game is played on, and it drifts by enough to
see.

## The measurement

Read straight off the live VM through the warm daemon, three samples, 2026-08-04:

```
local=1785840585.983  server=1785840599  delta(server-local)=+12.045 s  rtt=1.94
local=1785840588.428  server=1785840601  delta(server-local)=+11.898 s  rtt=1.35
local=1785840590.278  server=1785840603  delta(server-local)=+12.043 s  rtt=1.36
```

The same machine against an internet `Date:` header at the same moment was **within
two seconds of real UTC**. So the twelve seconds are the GAME's, not the PC's —
"fix the computer's time" does not close it, and it grows until the client next
re-syncs. The operator had been reading 25-30 s of it on the «Secret Tasks» tab
before this was measured.

The read is one line, and the game states it in whole seconds:

```lua
ChatInterface.getServerTime()      -- seconds; `lua_actions.game_server_time()`
```

## Why it is not cosmetic

Two different costs, and the second is the expensive one.

**A countdown that disagrees with the one beside it.** The panel drew «готово через
0:14» while the game drew «через 0:02» on the same tile. Nothing tells the person
which of the two is lying.

**A raid gate that is wrong by the same amount.** `SecretTask.can_loot` *is* the
comparison «has `completionTime` passed yet». Judged against `time.time()` it says
"not yet" to a tile the server would already pay out on, and the five daily
robberies are the scarce thing. `pending`, `awaiting`, the ghost-recon `can_loot`,
the world-treasure expiry and the truck positions all sit on the same comparison.

## Where it lives

`tools/lib/game_clock.py` holds one number: `offset = game_ms - local_ms`, as of the
last sample. `game_clock.now_ms()` is "now" as the game counts it, and every decoded
record in `lastwar_proto` is judged against that instead of `time.time()`.

Unsynced, the offset is zero and the behaviour is exactly what it was before — so a
tool with no live VM (a pcap being decoded, a test) is no worse off.

**Nobody pays a round trip for it.** The two alliance-task reads
(`secret_task_all_alliance`, `secret_task_raidable_alliance`) and the robbery's
status read open by emitting `ACT NOW=<seconds>`, so every list is judged on the
clock it was read with. The panel's tab re-measures every five minutes on top of
that, because a tab fed only by the capture checkpoint makes no VM read of its own.

One offset per process, deliberately. A panel drives several clients, but they are
playing the same game against the same time source, and what is being corrected is
that source's drift from the local machine — not something an account owns. If two
clients on one machine are ever found to disagree by more than the round trip, this
is the paragraph that was wrong.

## The sampling error

Half the round trip (~0.1 s on a warm daemon) plus the whole-second granularity of
the game's own answer. Both are noise next to twelve seconds, and the granularity is
arguably not an error at all: the game's own UI counts in those same whole seconds,
so matching it exactly is what is wanted.

## What this does not explain

Why the game's clock is ahead in the first place, and whether the drift is per
server, per session or per client build. Three samples two seconds apart cannot tell
those apart. What is certain is only that it exists, that it is the clock the
timestamps are stamped on, and that it is therefore the clock they must be judged by.
