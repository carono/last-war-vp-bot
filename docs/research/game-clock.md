# The game's clock is not this computer's clock

Task #1227. Every timestamp the client hands out — a hero dispatch's
`completionTime`, a tile's `actEndTime`, a ghost squad's return, a truck's arrival —
is epoch milliseconds on a clock the client and the server agree between themselves.
The client keeps it as an offset from the device's rather than reading the device's
at all, and the two are far enough apart to see.

## Who is wrong, and by how much

Three chains of measurement on 2026-08-04, all within a minute of each other:

```
game (UITimeManager)  vs Windows      +11 … +13 s      (three samples through the daemon)
Windows               vs WSL          −10.93 s         (back-to-back, same machine, ×3)
WSL                   vs an internet `Date:` header    within ~2 s
```

So the game's clock matches real UTC and **the Windows clock is ~11 s slow**. It was
worth writing down the other way round first and then measuring properly: the fix is
the same either way, but the advice is not. Fixing Windows time sync is worth doing —
and the panel must not depend on anybody doing it, because the drift comes back.

The operator was reading 25-30 s of this, which is what an unsynced Windows clock does
between corrections.

## What the client itself counts with

Not an inference — `ActDispatchTaskDataManager.RefreshCompleteTimer`, string-dumped out
of the live VM, has exactly these constants:

```
UITimeManager  GetServerTime  curTime  completionTime  diff  math.ceil
completeDelay  DelayInvoke  TimerManager  EventId.DispatchTaskCompleteRefresh
```

Read that list carefully, because it settles the two alternatives #1227 had to rule
out:

* **there is no other event.** The countdown is `completionTime` minus a `curTime`
  from `UITimeManager`, and the tile record carries only two timestamps at all
  (`completionTime`, `actEndTime` — the full field dump of a live task has no third);
* **nothing is added for the road.** `completeDelay` looks like a grace period and is
  not: dumped live it is a `DelayInvoke` timer object (`timer_id`, `left`, `delay`,
  `one_shot`) — the handle for re-running the refresh when the next task matures.

`UITimeManager.Instance:GetServerTime()` returns **milliseconds**;
`ChatInterface.getServerTime()` is the same clock in whole seconds. Sampled together:
`…337743` ms against `…337` s.

## Why it is not cosmetic

Two costs, and the second is the expensive one.

**A countdown that disagrees with the one beside it.** The panel drew «готово через
0:13» where the game drew «через 0:02». Nothing tells the person which is lying.

**A raid gate that is wrong by the same amount.** `SecretTask.can_loot` *is* the
comparison «has `completionTime` passed yet». Judged against `time.time()` on a slow
machine it says "not yet" to a tile the server would already pay out on, and the five
daily robberies are the scarce thing. `pending`, `awaiting`, the ghost-recon
`can_loot`, the world-treasure expiry and the truck positions all sit on the same
comparison.

## A client at the login screen is the same read, lying

The second profile's client had not logged in. It did not fail, and it did not say so:

```
UITimeManager.Instance:GetServerTime()   6280648      ← process uptime, not a clock
UITimeManager.Instance.serverDeltaTime   0            ← nothing to add yet
ChatInterface.getSelfServerId()          -1
allianceTask                             0 entries
GetTodayStealNum()                       0            → "all five robberies left"
```

Every one of those is a plausible answer, which is exactly what makes them expensive.
A watcher reading them finds no target, robs nothing, and says nothing — indis­tin­guish­able
from a quiet map. That was «автолут не работает совершенно» on that profile.

The clock is the one thing a client at the login screen cannot fake, so it is the
question to ask first. `game_clock.plausible()` refuses anything below 2017 (an uptime
cannot reach it) or more than six hours from the local clock, `session_ready()` is that
test, and the VM reads raise `NotLoggedIn` rather than returning the empty list a
logged-in client with nothing to rob would return. The two must not look alike.

`ChatInterface.getSelfServerId()` answering `-1` is the same trap in miniature: passed
on as a server id it made «не грабить на своём сервере» compare every tile against a
server that cannot exist, so the prohibition lapsed silently. Anything that is not a
positive id is now "unreadable".

## Where it lives

`tools/lib/game_clock.py` holds one number: `offset = game_ms - local_ms`, as of the
last sample. `game_clock.now_ms()` is "now" as the game counts it, and every decoded
record in `lastwar_proto` is judged against that instead of `time.time()`.

Unsynced, the offset is zero and the behaviour is exactly what it was before — so a
tool with no live VM (a pcap being decoded, a test) is no worse off.

**Nobody pays a round trip for it.** The two alliance-task reads
(`secret_task_all_alliance`, `secret_task_raidable_alliance`) and the robbery's status
read open by emitting `ACT NOWMS=<ms>`, so every list is judged on the clock it was read
with. The panel's tab re-measures every five minutes on top of that, because a tab fed
only by the capture checkpoint makes no VM read of its own.

One offset per process, deliberately. A panel drives several clients, but they are
playing the same game against the same time source, and what is being corrected is that
source's drift from the local machine — not something an account owns. The
per-client thing is **whether the client can answer at all**, and that is not carried in
the offset: it is the `NotLoggedIn` a read raises, decided per read.

## The sampling error

Half the round trip (~0.1 s on a warm daemon), which is noise next to eleven seconds.
The whole-second fallback (`ChatInterface`) adds up to a second more, and even that is
arguably not an error: the game's own UI counts in those same whole seconds.

## What this does not explain

Why the Windows clock drifts as far as it does between syncs, and whether the game's
own clock is ever the wrong one on a machine whose time is good. What is certain is
that the game's timestamps are stamped on the game's clock, and that is therefore the
clock they must be judged by — whoever is at fault on any given day.
