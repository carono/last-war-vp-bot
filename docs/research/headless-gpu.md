# Running the client without paying for the picture

Task #1219. The bot never looks at the screen — it reads the game state out of the Lua VM
and sends messages — so every frame the client draws is work nobody needs. The question
was whether the client can be run without drawing at all, and what that is worth.

**Short answer.** There is no headless mode, and there is no way to ask for one at launch:
every command-line route is closed, and the two intuitive tricks (minimise the window, put
the client in a session nobody is looking at) are worth *nothing* and *less than nothing*
respectively. What does work is telling the running client to draw less — and that is
worth **−82 % of its GPU time at no cost to the bot**, three lines of Lua, applied after
every launch.

| | GPU, one client | vs stock |
|---|---|---|
| stock (60 fps, quality High, 1700×1065) | **22.8 %** | — |
| minimised | 9.1 % vs 8.9 % visible | **nothing** |
| in a disconnected Windows session | **27.2 %** | **+19 %** — worse |
| quality Low + vSync off + 10 fps | **8.2 %** | −64 % |
| …and rendering at 320×200 | **4.0 %** | **−82 %** |

Board power over the same runs: 27 W stock → 14 W. Measured on an RTX 2070 with two
clients on the machine; the tool is [`tools/gpu_load.py`](../../tools/gpu_load.py).

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

**`runInBackground = true`** is why minimising is pointless. Unity keeps the player loop
running and keeps drawing full frames into a swap chain nobody presents — 9.12 % minimised
against 8.92 % visible, which is noise. Setting `runInBackground = false` and minimising
*also* changed nothing (9.71 %): the client does not take Unity's background-pause path
here at all. There is no "it stops when you are not looking".

**`vSyncCount = 1`** is why `targetFrameRate` reads as 60 but is not actually enforcing
anything. While vSync is on, Unity ignores `targetFrameRate` entirely and lets the display
do the capping. On a real monitor that is a 60 Hz cap and no harm done. In a session with
no display it is a cap on nothing — see §4.

## 3. Every command-line route is closed

Unity's own flags are all present in `UnityPlayer.dll` — `-batchmode`, `-nographics` (with
its `PlayerInitEngineNoGraphics` null-device path), `-screen-width`, `-screen-height`,
`-screen-quality`, `-force-d3d11`, the lot. The engine would honour them. The *game* never
lets them through, and it fails three different ways depending on how you launch it:

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
   Low`** — these normally persist through the `Screenmanager …` registry values, so the
   self-restart should not have mattered. The client came back at **1700 × 1065, quality
   High** regardless: the game overwrites the screen and quality settings from its own
   saved configuration during startup (`SceneQualitySetting.ApplySavedGraphicsLevel`).

There is also a **single-instance guard**: while a client is running in a Windows session,
a second launch in that same session exits without creating a process and without writing
a log line. It cost one inconclusive `-batchmode` run before it was spotted — the client
under test had a sibling still alive, and its death looked like a `-nographics` refusal.
Kill the incumbent first, elevated, and check `tasklist` before believing a negative.

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

`actions/set_graphics_load.md`, after every launch. The settings are runtime-only — a
restarted client is back at full quality — so it belongs on the same schedule that starts
the game, next to `launch_game`.

For a client a person may want to watch, the same script restores it:

```
run_action("set_graphics_load", variables={"fps": 60, "quality": 2,
                                           "width": 1700, "height": 1065})
```

Proven live on the second client: 10 fps, quality Low, shadows off, anti-aliasing off,
320×200, and back again.

**Left for later.** Whether the panel should apply the profile on its own after a launch
(and which clients should get it — the headless second instance always, the console one
only when nobody is watching) is a product decision, not a research one, and the schedule
that would do it is not written. Nothing here measures CPU: the frame cap should cut that
too, and nobody has looked.
