# Turn the client's rendering down (or back up) so it stops loading the video card.
# ru: Снизить нагрузку клиента на видеокарту (или вернуть картинку обратно).
#
# The bot does not look at the picture — it reads the game state out of the Lua VM and
# sends messages — so every frame the client draws is work nobody needs. Drawn at the
# settings it ships with, one client costs about a quarter of this machine's card; told
# to draw ten frames a second at the lowest quality it costs a twelfth of that, and
# nothing the bot does gets slower (docs/research/headless-gpu.md).
#
# The settings do NOT survive a restart — the client comes back at 60 frames a second and
# full quality every time — so this belongs after every launch. A timer is the easy way:
# re-applying costs one round trip and is idempotent, so a period of a quarter of an hour
# covers restarts, crashes and the watchdog without anybody thinking about it.
#
# The render size is the exception and does not need this script at all: Unity keeps it in
# the registry (`Screenmanager Resolution Width` / `Height` under
# `HKCU\Software\FunFly\Last War-Survival Game`), where it survives every restart and
# every launch route. Setting it there once is better than setting it here every time —
# docs/research/headless-gpu.md §3.6. The width/height below are for changing it live.
#
#   fps      frames per second to allow. 10 is the floor that costs nothing: below it
#            the Lua round trip starts to stretch (5 → ~1.2 s, 1 → ~2.8 s) because a
#            call can only land on the main thread once per frame. 60 restores stock.
#   quality  the game's own preset — 0 Low, 1 Medium, 2 High.
#   width    render size. The window keeps its position; the picture inside it shrinks,
#   height   which is where the second half of the saving comes from. Pass the real
#            window size (1700 × 1065) to get a readable picture back.
#
# The defaults are the low-power profile. To hand the client back to a person:
#
#   ARGS fps = 60, quality = 2, width = 1700, height = 1065
#
# A client whose Windows session is disconnected needs this MORE than a visible one, not
# less: with no display to lock to, vSync stops capping anything and the client free-runs
# at ~200 frames a second — three times the cost of the same client on screen. That is
# why the chunk clears `vSyncCount` before setting the cap; while vSync is on, Unity
# ignores `targetFrameRate` entirely.
#
# vSync stays off in both directions, including the restore, on purpose. A cap of 60 with
# no vSync draws the same 60 frames a person's monitor would have shown, and it keeps
# working in the session where vSync would have capped nothing at all.

ARGS fps = 10
ARGS quality = 0
ARGS width = 640
ARGS height = 480

# --- 1. The frame cap ----------------------------------------------------------
# vSync first, and in the same chunk: the cap does nothing until it is cleared.
LUA CS.UnityEngine.QualitySettings.vSyncCount = 0 CS.UnityEngine.Application.targetFrameRate = {fps}

# --- 2. The quality preset -----------------------------------------------------
# `true` applies the expensive parts too (shadows, anti-aliasing, texture limits) instead
# of leaving them for the next level change. It settles at the end of the frame, so the
# render size below is set separately rather than being overwritten by the preset.
LUA CS.UnityEngine.QualitySettings.SetQualityLevel({quality}, true)
WAIT 1.0

# --- 3. The render size --------------------------------------------------------
# `false` keeps the client windowed. This is the single biggest lever of the three —
# fill rate is what the card actually spends its time on.
LUA CS.UnityEngine.Screen.SetResolution({width}, {height}, false)
