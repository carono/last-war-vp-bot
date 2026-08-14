# Launching Last War from WSL + driving City↔World

Task #1017. End-to-end procedure to (1) launch the PC client from WSL and (2) switch
the game scene between City and World from out of process, plus the capture caveat
that stops a screenshot from being clean visual proof. Companion to
`xlua-state.md` (§8, §11 — the SceneManager route) and `il2cpp-invoke-stability.md`
(the hijack/invoke mechanism).

## 1. Install path

```
C:\Users\<user>\AppData\Local\FunFly\Last War-Survival Game\Game\LastWar.exe
```
i.e. `%LOCALAPPDATA%\FunFly\Last War-Survival Game\Game\LastWar.exe`.
`GameAssembly.dll` and `LastWar_Data` sit next to it. The same path is
derivable from `tools/extract_hero_icons.py` (`LOCALAPPDATA/FunFly/Last
War-Survival Game/Game/...`). Publisher folder is **FunFly**; a `LastWarLauncher.exe`
/ `LastWarSync.exe` / `LastWarUpdater.exe` live one level up but are not needed to
start the game directly.

WSL mount of that path:
`/mnt/c/Users/<user>/AppData/Local/FunFly/Last War-Survival Game/Game/LastWar.exe`.

## 2. Launching from WSL — what worked, what didn't

| Method | Result |
|---|---|
| `subprocess.Popen([exe], cwd=game_dir)` (Windows Python) | **Did not spawn** a visible process (parent exited ~144, no `LastWar.exe`). |
| `cmd.exe /c start "" /D <dir> <exe>` | **Hung / no process.** |
| **Run the exe path directly via WSL interop, from its own dir** | **Worked.** |

Working invocation:

```bash
cd "/mnt/c/Users/<user>/AppData/Local/FunFly/Last War-Survival Game/Game" \
  && ( "./LastWar.exe" >/dev/null 2>&1 & )
```

Notes:
- The process appears after **~30 s** (ACE/Unity bootstrap), alongside a normal
  `UnityCrashHandler64.exe` watchdog (Unity always spawns it — **not** a crash sign).
- Then allow **~90 s** for **auto-login** to reach a playable scene before issuing
  il2cpp calls. Memory grows steadily to ~1.2 GB and levels off when loaded.
- **Do not launch a second instance** while one is already running.
- **Single-session game:** if the same account logs in elsewhere, this client gets a
  *"В ваш аккаунт был выполнен вход с другого устройства"* modal and its network
  session is kicked (see §5, and [`session-kick.md`](session-kick.md) for its flag). Launching here can itself trigger that on another
  device. Use a throwaway account for anything you would not want kicked.

Verify it is up:

```bash
/mnt/c/Windows/System32/tasklist.exe | grep -i lastwar.exe
```

## 3. Scene control procedure (City↔World) — the Lua route

> **The C# `SceneManager` primitives do NOT work for this.** `ChangeScene(SceneID
> .World)` and `CreateWorld()` (Assembly-CSharp, static) flip the engine scene *enum*
> and return `exc=0`, but they do **not** render a City→World transition — the view is
> torn to black and the target scene never composites (`ChangeScene` is destructive;
> `CreateWorld` flips the enum non-destructively but still never switches the view, and
> it desyncs state so the real «Мир» button then no-ops). See `xlua-state.md` §11/§11.3
> for the decisive A/B test. **Do not use the C# route.**

The **working** City→World is a **Lua** call, reached through a **static facade** that
bypasses the managed instance-discovery wall (`xlua-state.md` §8/§9, §12):

```
GameEntry.get_Lua()  (static)                       -> XLuaManager
XLuaManager.SafeDoString("SceneUtils.ChangeToWorld()")   -> renders World
# reverse: SafeDoString("SceneUtils.ChangeToCity()")
```

Driver: `tools/scene_change.py` (re-resolves everything at runtime; not pid-bound):

```bash
# read-only: report current scene (state read FROM Lua)
C:\Python312\python.exe tools\scene_change.py
# City -> World (only fires if currently in City)
C:\Python312\python.exe tools\scene_change.py --fire
# World -> City
C:\Python312\python.exe tools\scene_change.py --to-city
# add --shot to screenshot before/after
C:\Python312\python.exe tools\scene_change.py --fire --shot
```

Exact steps the driver performs (this is the reusable recipe):

1. **`find_game_pid`** → open the process (`il2cpp_probe`).
2. **Learn `SAFE_RIP`** and gate all calls to the idle main thread (RIP-gated
   hijack — `il2cpp-invoke-stability.md`).
3. **Resolve `GameEntry` + `XLuaManager` classes at RUNTIME** (enumerate the assembly
   table, then `il2cpp_class_from_name(Assembly-CSharp, "", ...)`).
   **NEVER use the dump JSON `addr` as a class pointer** — that is not a runtime
   `Il2CppClass*` and feeding it to a runtime API crashed the game once
   (`xlua-state.md` §8.3).
4. **Resolve MethodInfos by name** (addresses are per-pid, re-fetch every run):
   `GameEntry.get_Lua/0` (static), `XLuaManager.SafeDoString/1`.
5. **Get the live manager:** invoke `GameEntry.get_Lua` (static → obj=0) → the live
   `XLuaManager` object (`exc=0`).
6. **Read state FROM LUA, not C# flags:** `SafeDoString` a chunk that logs
   `SceneUtils.GetIsInWorld()`/`GetIsInCity()` to the Unity `Player.log`, then parse
   the marker. `SafeDoString` **swallows** Lua errors and returns nothing, so state is
   confirmed via the log — the il2cpp `exc` slot is always 0 here.
7. **Transition:** `SafeDoString("SceneUtils.ChangeToWorld()")` (or `ChangeToCity()`).
   Re-read the Lua state to confirm.

Confirmed live (pid 35688, task #1024): `GetIsInWorld false→true`, `GetIsInCity
true→false`, world map rendered, toggle button flips «Мир»→«База». Unlike the C#
`ChangeScene` (enum-only, black torn-down view), the Lua call performs the full flow
(data + scene build + camera) and the client renders the world.

## 4. Visual capture caveat — the 3D scene photographs black

Screenshots use **mss** (`tools/` inline; `win32` BitBlt returns all-black on this
Unity window). To capture the game window, focus it first with the **Alt-key trick**
(Windows blocks `SetForegroundWindow` from a background caller otherwise):

```python
win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)          # Alt down
win32gui.SetForegroundWindow(hwnd)                        # now permitted
win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
```
(window title: `Last War-Survival Game`; find its hwnd by pid via `EnumWindows`.)

**But the capture only shows the 2D UI overlay — the 3D scene renders BLACK.** The
Unity DirectX swapchain surface does not composite into a DWM/mss screen grab, so the
world terrain / city base are not visible in the PNG even when focused. Consequence:

> **A screenshot cannot visually confirm World-vs-City by terrain on this client.**
> The only confirmed evidence is the engine scene enum (`get_CurrSceneID` /
> `IsInWorld` / `IsInCity`), read directly from il2cpp state.

### 4.1 Important caveat — engine flag flipped, full visual transition NOT confirmed

The engine enum reliably reports World after `ChangeScene(2)` (`CurrSceneID=2`,
`IsInWorld=1`, read twice). **But that is not the same as the client rendering the
World map**, and the visible UI actually casts doubt:

- The focused screenshot's bottom-right toggle button read **«Мир» (go-to-World)**.
  Per `[[project_screenshot_and_map_switch]]`, on this client the go-to-World button
  is visible **only when the client is on base/City** (it names the destination). So
  the UI suggests the **client view may still be City** even though the engine enum
  says World.
- The same prior finding warns that flipping server/engine state does **not**
  necessarily flip what the Unity client renders — the reliable *visual* switch there
  was a **toggle-button click**, not a state write.
- A session-kick modal (§5) was also on screen, which may have reverted the HUD.

So the honest status is: **`SceneManager.ChangeScene(2)` reliably sets the engine's
current scene enum to World; whether it drives a full, rendered City→World client
transition is UNCONFIRMED** (3D not capturable, the one readable UI element points at
base, session was kicked). To settle it, either read `UnityEngine…SceneManager
.GetActiveScene().name` (the actually-loaded Unity scene, stronger than the game
enum) on a *healthy* session, or compare against the known-good visual switch
(toggle-button click) from `[[project_screenshot_and_map_switch]]`.

## 5. Observed during task #1017 — account session kick

After the transition, a focused screenshot showed the UI overlay plus a modal:
**«Внимание — В ваш аккаунт был выполнен вход с другого устройства» / «Подтвердить»**
(account logged in from another device). The engine scene flags still read World
(`CurrSceneID=2`) underneath, so the transition held, but the **network session was
kicked** by a concurrent login on the account. The modal was left untouched
(dismissing an account-security prompt is a user decision, not an autonomous one).
Takeaway: this is a strict single-session client — drive it on a throwaway account,
and expect a kick if the account is used elsewhere.

## 6. When a launch is DONE, and why the scene alone cannot say (#1399)

Measured on the live client, 2026-08-14/15, one machine, one account.

### 6.1 What a launch actually costs, step by step

Pressing «Перезапустить игру» plays `actions/restart_game.md`. Wall-clock, from the log
of a real press:

| step | elapsed |
|---|---|
| `QUIT_GAME` — force-close, waited until the process is gone | 14 s |
| `WAIT 3` — a breath before the launcher looks at the files | 3 s |
| `START_GAME` → the client's **process** exists again | 8 s |
| … → its sockets say anything at all | ~20 s |
| … → **ESTABLISHED to the game server** (`game_link` ONLINE) | **33.7 s** |
| `ATTACH_GAME` + the final readiness gate | 2 s |
| **whole restart** | **53 s** |

The client's own conversation with the server is therefore up about half a minute after
the launcher is spawned, and that is the earliest honest «it is up».

### 6.2 The daemon is NOT up at that moment, and stays down for minutes

The Lua daemon is pinned to a process id, so the client it was driving dying takes it
with it. On the same machine the gap between «the client is playable» and «the daemon
can be asked anything» was:

* 2026-08-14 23:29 — daemon down from 23:29:58 to 23:32:40, **2 min 42 s**, while the
  client had been link-online since 23:30:22;
* 2026-08-15 00:21 — daemon still down **ten minutes** after the client came back, and
  it only returned when the panel itself was restarted.

The second one is a hole of its own and is written up as a finding rather than fixed
here: nothing in a running panel starts a daemon that is **down** (as opposed to stale).
`GameLink.ensure()` is called from the errand path, and the daemon gate (#1393) stops
errands while the daemon is down — so the thing that would start it is behind the gate
that is waiting for it. The recovery's daemon branch only fires on a daemon that is UP
and holding a dead client (`DAEMON_STRIKES`, `recovery.py::note_stale`), which this is
not.

### 6.3 What that did to the launch

`launch_game` waited on `WAIT scene != unknown`, and the scene is a Lua read. So for the
whole of the window above the wait could not observe anything, sat out its 180 s cap and
reported a FAILED launch. On the evening of 2026-08-14 that happened **twelve times in a
row**, and the client it was failing over was read as `scene == city` by the very next
scenario, one second after the failure.

### 6.4 The ladder, and what each rung costs

`client == ready` (`docs/dsl.md`, `Interpreter._client_ready`) asks the strongest reading
that can be taken right now:

| rung | cost, warm | what it proves |
|---|---|---|
| daemon port probe | 1 ms | whether rung 1 can be asked at all |
| `scene` through the daemon | 61 ms | the client is interactive |
| socket walk (`game_link`) | 32 ms | the client is talking to the game server |
| the whole ladder | 77 ms | — |

A client that ANSWERS `unknown` is the game saying «still loading» and stops the ladder
there; only «nobody could be asked» falls through to the socket. So with a warm daemon the
wait matches on its first poll — 0.08 s against the 180 s the old sign spent failing — and
with no daemon at all it matches when the link comes up, 33.7 s live.

The socket rung is deliberately weaker than the errand gate's (`_link_lost`, which makes
every scenario prove the session for itself with the game's own clock). That asymmetry is
the point: a launch may end as soon as the client is up, and what to do with a client that
is up is somebody else's question.
