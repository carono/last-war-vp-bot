# Running the client without paying for the picture

Task #1219. The bot never looks at the screen — it reads the game state out of the Lua VM
and sends messages — so every frame the client draws is work nobody needs. The question
was whether the client can be run without drawing at all, and what that is worth.

**Short answer.** There is no headless mode. `-batchmode`/`-nographics` cannot survive to
the point where the client is playing, and every intuitive way of hiding the picture —
minimise it, cover it, put the client in a session nobody is looking at — makes the cost
go **up**, not down. What works is making the client draw *less*: a small render size,
which can be set once in the registry and is then permanent, plus a frame cap and a low
quality preset at runtime. Together **−82 % of its GPU time at no cost to the bot**.

| | GPU, one client | vs stock |
|---|---|---|
| stock (60 fps, quality High, 1700×1065) | **22.8 %** | — |
| covered by another window | +16 % | **worse** |
| minimised | +53 % | **worse** |
| in a disconnected Windows session | **27.2 %** | **+19 %** — worse |
| quality Low + vSync off + 10 fps | **8.2 %** | −64 % |
| …and rendering at 320×200 | **4.0 %** | **−82 %** |

Board power over the same runs: 27 W stock → 14 W. Measured on an RTX 2070 with two
clients on the machine; the tool is [`tools/gpu_load.py`](../../tools/gpu_load.py).

**Every way of hiding the client costs more than leaving it alone.** Covering it,
minimising it and putting it in a session with no screen are three variations on the same
disappointment, and §3.5 has the paired numbers and the frame counts that rule out the
obvious explanation. There is no state in which the client stops loading the card.

The ability is [`actions/set_graphics_load.md`](../../src/lastwar_bot/actions/set_graphics_load.md),
and it runs in both directions — the same script hands the picture back to a person.

## 1. How this was measured

Per-process GPU on Windows comes from the `GPU Engine` performance counters, the source
behind Task Manager's *GPU* column. Two things make them the only usable source here:
`nvidia-smi` reports `N/A` for per-process utilisation on a WDDM driver, and it does not
even *list* a process that lives in another Windows session — the second client is
invisible to it while the counters see it fine.

```
C:\Python312\python.exe tools\gpu_load.py --seconds 20
C:\Python312\python.exe tools\gpu_load.py --seconds 20 --pid 153576 --label "stock"
```

CPU comes from WMI (`Win32_PerfFormattedData_PerfProc_Process`) and not from
`Get-Counter`, because **counter paths are localised**: on this Russian Windows
`\Process(*)\% Processor Time` does not resolve at all — `Get-Counter` answers "объекты
не найдены" — while the WMI class keeps English property names on every locale and
carries `IDProcess`, so no instance-name-to-pid mapping is needed. `\GPU Engine` survives
being spelled in English only because it has no localised name to be confused with. The
figure is a share of ONE core, the way Windows reports it, with the share of all eight
printed beside it.

One reading proves nothing. **What is on screen dominates the number** — the same client
idling in the city measured 9 % at one moment and 24 % twenty minutes later, with no
setting touched in between. Every comparison below is therefore *paired*: the two profiles
are applied alternately, several rounds, and compared round by round. Three rounds of
stock↔low gave 23.31 / 25.66 / 22.53 against 8.13 / 8.24 / 8.24 — and note how much
steadier the capped readings are. A frame cap does not only lower the cost, it stops the
cost depending on what the client happens to be showing.

## 2. What the client ships with

Read out of the running VM:

```
targetFrameRate = 60      vSyncCount = 1        quality = 2 of Low/Medium/High
antiAliasing = 4          shadows = HardOnly, distance 150
runInBackground = true    1700 × 1065 windowed
```

Two of those matter more than they look.

**`runInBackground = true`** is why hiding the client is pointless. Unity keeps the player
loop running and keeps drawing full frames whether or not anybody can see them. Setting
`runInBackground = false` and minimising changed nothing either: the client does not take
Unity's background-pause path here at all. There is no "it stops when you are not
looking" — §3.5 measures how much worse than nothing it actually is.

**`vSyncCount = 1`** is why `targetFrameRate` reads as 60 but is not actually enforcing
anything. While vSync is on, Unity ignores `targetFrameRate` entirely and lets the display
do the capping. On a real monitor that is a 60 Hz cap and no harm done. In a session with
no display it is a cap on nothing — see §4.

## 3. Every command-line route is closed

Unity's own flags are all present in `UnityPlayer.dll` — `-batchmode`, `-nographics` (with
its `PlayerInitEngineNoGraphics` null-device path), `-screen-width`, `-screen-height`,
`-screen-quality`, `-force-d3d11`, the lot. The engine would honour them. The *game* lets
almost none of them through, and it fails three different ways depending on how you
launch it — with one exception that turns out to matter more than all the failures (§3.6):

1. **Through the launcher** — `LastWarLauncher.exe` is what `session_launch.py --game`
   starts, and it does not forward its own command line to `LastWar.exe`. The flags are
   simply gone.
2. **`LastWar.exe` directly, with `-batchmode -nographics`** — the client starts, loads
   normally, reaches 1.15 GB, and then **restarts itself into a fresh pid with an empty
   command line**. That self-restart after the first login is already known
   (`docs/research/game-launch-and-scene-control.md`); what matters here is that it drops
   every argument. Reading the survivor's command line elevated shows a bare
   `"…\Game\LastWar.exe"` and nothing else. So `-nographics` cannot survive to the point
   where the client is playing, whatever the engine would have done with it.
3. **`LastWar.exe` directly, with `-screen-width 640 -screen-height 480 -screen-quality
   Low`** — the quality half is swallowed like the rest: the saved `SCENE_GRAPHIC_LEVEL`
   and `UnityGraphicsQuality` were still 3 and 2 afterwards and the client ran at High,
   because the game applies its own saved configuration during startup
   (`SceneQualitySetting.ApplySavedGraphicsLevel`). **The size half is the one thing on
   this page that does get through** — see §3.6. It is easy to miss, because it does not
   take effect on the client you pass it to.

## 3.6 The render size, and only the render size, is permanent

`-screen-width 640 -screen-height 480` looked ignored: the client launched with them read
**1700 × 1065** out of the VM afterwards, which is what the flat "every flag is lost"
conclusion above was first written from. That reading was true and the conclusion drawn
from it was wrong. Unity had written the values where it keeps them —

```
HKCU\Software\FunFly\Last War-Survival Game
    Screenmanager Resolution Width   = 640     (0x280)
    Screenmanager Resolution Height  = 480     (0x1e0)
```

— and they take effect from the **next** start onwards. Checked the only way that settles
it: the client was stopped and brought back up through `rdp_instance.py --bring-up`, i.e.
through `LastWarLauncher.exe`, **with no command line of any kind**. It came up at
**640 × 480**, and stayed there across the restarts that followed.

So the biggest single lever of §5 — render size — is reachable **before the client ever
starts, permanently, with no scenario and no Lua**. Write the two values and every launch
from then on is small, including a launch by the crash watchdog, by the launcher, or by a
person double-clicking the icon.

```
reg add "HKCU\Software\FunFly\Last War-Survival Game" ^
    /v "Screenmanager Resolution Width_h182942802"  /t REG_DWORD /d 640 /f
reg add "HKCU\Software\FunFly\Last War-Survival Game" ^
    /v "Screenmanager Resolution Height_h2627697771" /t REG_DWORD /d 480 /f
```

(The `_h…` suffixes are Unity's own name hashes and are stable for this product. For a
client in another Windows session the same values live under that user's hive —
`HKEY_USERS\<their SID>\Software\FunFly\…`, reachable while they are logged on.)

What it is worth on its own: the second client, at **640 × 480 from the registry** with
quality still High and no frame cap, in its disconnected session — **1.85 % GPU**, against
27.2 % for the same client at full size in §4. Its **CPU** was 41 % of a core, though,
because nothing was capping its frame rate. Which is the division of labour worth
remembering:

- **render size → the GPU cost.** Registry, permanent, no scenario.
- **frame cap → the CPU cost of a client with nothing to pace it.** Runtime only, dies
  with every restart, which is what the scenario and its timer are for.

Neither substitutes for the other, and the quality preset is a runtime-only extra on top.

There is also a **single-instance guard**: while a client is running in a Windows session,
a second launch in that same session exits without creating a process and without writing
a log line. It cost one inconclusive `-batchmode` run before it was spotted — the client
under test had a sibling still alive, and its death looked like a `-nographics` refusal.
Kill the incumbent first, elevated, and check `tasklist` before believing a negative.

## 3.5 Hiding the window: covered and minimised, measured paired

The window was put through three states in turn — foreground, fully covered by an opaque
top-most window of the same size, and minimised — three rounds, twelve seconds each:

| state | GPU (3 rounds) | mean | CPU, share of one core |
|---|---|---|---|
| foreground | 15.14 / 14.07 / 14.83 | **14.68 %** | 8.9 % |
| covered | 18.03 / 17.15 / 15.97 | **17.05 %** | 8.5 % |
| minimised | 23.32 / 21.33 / 22.89 | **22.51 %** | 11.1 % |

Minimising costs **+53 %**, covering **+16 %**, and the spread inside each state is small
enough that neither is noise.

The obvious explanation would be that a hidden window free-runs the way the disconnected
session does in §4. It does not — frames counted through the VM in the same three states:

| state | frames per second |
|---|---|
| foreground | 60, 60 |
| covered | 60, 60 |
| minimised | 58, 58 |

**Identical work, more GPU time.** The client draws exactly the same 60 frames whether it
is in front of you, under another window, or minimised; what changes is what the desktop
compositor can do with the result. A visible window's frames go out through the cheap flip
path; a hidden one's have to be copied instead, and that copy is charged to the client.
CPU tells the same story — 8.5–11 % of one core in every state, no meaningful drop.

So "the client is minimised, it can't be drawing much" is false twice over: it is drawing
everything, and it costs more to do it. If a client is going to run hidden, it needs the
frame cap; hiding it is not an alternative to the cap, it is a reason for it.

> This was nearly recorded the other way round. A first, sequential pass read 14.67 % /
> 15.78 % / 24.12 % and looked like the same conclusion — but sequential readings of this
> client are worthless (§1), and it was only the frame counts that showed the gap was
> real. Measure paired, then explain; not the other way round.

## 4. A session nobody is looking at is the *expensive* case

The obvious idea — park the client in a disconnected Windows session, where there is no
monitor and nothing to composite — is exactly backwards.

`tsdiscon` on the second client's session took it from **8.0 % to 27.2 %**. The reason is
§2's second point: with no display, `vSyncCount = 1` has no refresh to lock to, so it caps
nothing and the client free-runs. Frame-counted through the VM it was doing **212 frames a
second**, and a later reading during loading reached 430.

So the multi-instance arrangement in `docs/research/multi-instance-rdp.md` — a second
client in its own session, left disconnected — is quietly the most expensive way to run a
client, and it gets more expensive the moment nobody is connected to it. It needs the
frame cap **more** than a visible client does, not less. With `vSyncCount = 0` and
`targetFrameRate = 10` the same client dropped to 4.4 %, and to 4.0 % with the render size
as well.

## 5. Ten frames a second is free; below that is not

A `SafeDoString` call is executed by hijacking the client's main thread at a safe RIP,
which comes round once per frame. Cap the frames hard enough and every call the bot makes
waits for one.

| cap | Lua round trip |
|---|---|
| 60 fps | 0.57 s |
| 30 fps | 0.60 s |
| **10 fps** | **0.54 s** |
| 5 fps | 1.25 s |
| 3 fps | 1.00 s |
| 2 fps | 1.60 s |
| 1 fps | 2.80 s |

**10 is the floor that costs nothing** — identical to 60 within the noise. It is also
where the GPU curve has already given up most of what it has: cost is close to linear in
frame rate (10 fps → 2.25 %, 5 → 1.20 %, 1 → 0.27 % at 320×200), so going below 10 buys a
couple of percent of one card and pays for it with every action the bot takes.

The render size is the other half and it is free in every sense: 320×200 halves what is
left after the cap, because fill rate is where the time actually goes.

## 6. The game's own settings — read, but not the lever

The game keeps its graphics options in the registry under
`HKCU\Software\FunFly\Last War-Survival Game`, and they *are* the persistent route in
principle:

```
SCENE_FPS_LEVEL          SCENE_GRAPHIC_LEVEL      UnityGraphicsQuality
QualitySetting.Resolution / .ShaderLOD / .Terrain / .PostProcess.*
Screenmanager Resolution Width / Height / Fullscreen mode
```

The managers behind them are `GameQualitySettings` and `SceneQualitySetting` in the Lua
VM (`EGameQuality`: Low 1, Mid 2, High 3, Default 4).

Its **power-saving mode** looked like the answer and is not. `GameQualitySettings
.EnablePowerSavingMode(true)` sets the flag, persists it, and on this platform leaves
`targetFrameRate = 60` and `vSyncCount = 1` untouched — reading the function's constants
back (`string.dump`, per `docs/research/…` house trick) shows an `IsPC` branch around the
frame-rate half. So the in-game «энергосбережение» is a phone feature that does nothing on
the PC client. It was turned back off.

Driving the saved settings from outside — writing the registry before launch — was not
pursued: it needs the level→value semantics decoded for each key, it only reaches the
coarse presets the settings screen offers, and it cannot express "10 frames a second at
320×200", which is the profile that actually pays. The runtime route gets all of it in
three lines.

## 7. What to do with this

**Two halves, and they are set in different places.**

1. **Render size — once, in the registry** (§3.6). Permanent, survives every restart and
   every launch route, needs no scenario. This is where most of the GPU saving is.
2. **Frame cap and quality preset — `actions/set_graphics_load.md`.** Runtime-only, so a
   restarted client is back at 60 fps and High; it belongs on a timer (below), which also
   covers restarts without anybody thinking about them.

For a client a person may want to watch, the same script restores it:

```
run_action("set_graphics_load", variables={"fps": 60, "quality": 2,
                                           "width": 1700, "height": 1065})
```

Proven live on the second client: 10 fps, quality Low, shadows off, anti-aliasing off,
320×200, and back again.

### Turning it on from the panel

**A switch on «Настройки → Игра», under «Windows-сессия».** Two states — «Обычный» and
«Упрощённый (беречь видеокарту)», the economy one being 10 fps + quality Low + 640 × 480 —
and a line saying what the client is actually drawing, read back out of the game rather
than trusted from what the panel last wrote. It is a per-profile setting, which is the
granularity that matters: the second account's client, headless in a session nobody is
connected to, is exactly the one that should be economising while the client somebody is
watching is not.

Switching to economy reads the picture **first** and remembers it, so «Обычный» puts back
that person's own settings rather than a constant — worth having because the size asked
for is only a request: `SetResolution` is clamped to what fits, and to the window's own
shape. Measured asks and answers: 1700 × 1065 → 1608 × 768, 640 × 480 → 600 × 480. There
is no size a panel could hard-code that is right on two machines, or even on one twice.

**Nothing here waits for a restart.** Every part of the switch — cap, quality and size —
is in force the moment it is pressed; `Screen.SetResolution` at runtime is immediate, and
the read in the same run comes back with the new size. (The thing that needs a restart is
the *launch flag* `-screen-width`, §3.6 — a different mechanism, and easy to confuse with
this one.)

**What a restart does is take half of it away, and the half that stays is the misleading
one.** Measured on a real stop-and-start of the second client, with the economy mode on
beforehand:

| | before the restart | after |
|---|---|---|
| render size | 640 × 480 | **640 × 480** — survives (Unity keeps it, §3.6) |
| frame cap | 10 fps, vSync off | **60 fps, vSync on** — gone |
| quality | Low | **High** — gone |

So a lapsed client still *looks* economised — small window — while costing what an
untouched one costs. The switch therefore judges the mode by the cap and the quality and
never by the size, and when the profile says economy and the client does not, the line
under it says so in as many words and asks for another press. Offering to restart the
client at that point would be exactly backwards: a restart is what *loses* the mode.

Everything it knows about the game is two scenario names and a dict of arguments:
`actions/set_graphics_load.md` to change it, `actions/read_graphics_load.md` to read it.

**And a timer, for the half that dies on a restart.** The Timers tab already edits
scenario, period and args (`panel/timers.py`), and `set_graphics_load` shows up in its
catalogue like any other action. Add:

```jsonc
{ "scenario": ["set_graphics_load"],
  "args": { "fps": 10, "quality": 0, "width": 320, "height": 200 },
  "period": 900 }
```

A period suits this better than it looks. The profile is runtime-only and dies with every
client restart, so *something* has to re-apply it; a timer that re-applies every fifteen
minutes covers restarts, crashes and the watchdog's relaunches without anybody thinking
about it. Re-applying is free — the calls are idempotent and cost one Lua round trip.

The timer belongs to the profile, like the switch does.

**Not recommended: hanging it off `launch_game`.** One `CALL set_graphics_load` at the end
of that scenario would cover the restart case, but `CALL` takes no arguments, so every
profile on every machine would get the same hard-coded low-power picture — including the
client someone is sitting in front of.

**Still open: the switch NOTICES a restart but does not undo one.** It says the mode has
lapsed and asks for a press; it does not re-apply by itself. The timer covers that, and
making the switch follow a launch is the tidier answer and is not written.

**Also open: what «Обычный» means for a client that was already economised.** The picture
is remembered on the first switch into economy, so a person whose very first press happens
while the client is already small records that small window as their normal. It has not
bitten — a restarted client comes back at full quality, which is when the reading is
taken — but nothing prevents it, and there is no way to know a size the client has never
been at.

**Left open.** Nothing here has run through a whole session — the numbers are windows of
seconds to minutes, not a night. And no measurement was made of what the profile does to
the game's own behaviour over hours: a client drawing ten frames a second is still a
client the server sees, but whether anything in it is paced off the frame rate has not
been checked.
