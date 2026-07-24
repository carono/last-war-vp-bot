# Launching Last War from WSL + driving City↔World

Task #1017. End-to-end procedure to (1) launch the PC client from WSL and (2) switch
the game scene between City and World from out of process, plus the capture caveat
that stops a screenshot from being clean visual proof. Companion to
`xlua-state.md` (§8, §11 — the SceneManager route) and `il2cpp-invoke-stability.md`
(the hijack/invoke mechanism).

## 1. Install path

```
C:\Users\spame\AppData\Local\FunFly\Last War-Survival Game\Game\LastWar.exe
```
i.e. `%LOCALAPPDATA%\FunFly\Last War-Survival Game\Game\LastWar.exe` (Windows user
`spame`). `GameAssembly.dll` and `LastWar_Data` sit next to it. The same path is
derivable from `tools/extract_hero_icons.py` (`LOCALAPPDATA/FunFly/Last
War-Survival Game/Game/...`). Publisher folder is **FunFly**; a `LastWarLauncher.exe`
/ `LastWarSync.exe` / `LastWarUpdater.exe` live one level up but are not needed to
start the game directly.

WSL mount of that path:
`/mnt/c/Users/spame/AppData/Local/FunFly/Last War-Survival Game/Game/LastWar.exe`.

## 2. Launching from WSL — what worked, what didn't

| Method | Result |
|---|---|
| `subprocess.Popen([exe], cwd=game_dir)` (Windows Python) | **Did not spawn** a visible process (parent exited ~144, no `LastWar.exe`). |
| `cmd.exe /c start "" /D <dir> <exe>` | **Hung / no process.** |
| **Run the exe path directly via WSL interop, from its own dir** | **Worked.** |

Working invocation:

```bash
cd "/mnt/c/Users/spame/AppData/Local/FunFly/Last War-Survival Game/Game" \
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
  session is kicked (see §5). Launching here can itself trigger that on another
  device. Use a throwaway account for anything you would not want kicked.

Verify it is up:

```bash
/mnt/c/Windows/System32/tasklist.exe | grep -i lastwar.exe
```

## 3. Scene control procedure (City↔World)

The game `SceneManager` (Assembly-CSharp) is **entirely static**, so scene control
needs **no managed instance** — it sidesteps the instance-discovery wall that blocks
the xLua route (`xlua-state.md` §8/§9). `SceneID`: **City == 1, World == 2**.

Driver: `tools/scene_change.py` (re-resolves everything at runtime; not pid-bound):

```bash
# read-only: report current scene
C:\Python312\python.exe tools\scene_change.py
# City -> World (only fires if currently in City)
C:\Python312\python.exe tools\scene_change.py --fire
# explicit target / round-trip demo
C:\Python312\python.exe tools\scene_change.py --fire --to 1     # World -> City
C:\Python312\python.exe tools\scene_change.py --roundtrip       # other scene, then back
```

Exact steps the driver performs (this is the reusable recipe):

1. **`find_game_pid`** → open the process (`il2cpp_probe`).
2. **Learn `SAFE_RIP`** and gate all calls to the idle main thread (RIP-gated
   hijack — `il2cpp-invoke-stability.md`).
3. **Resolve the class at RUNTIME:** enumerate the assembly table, then
   `il2cpp_class_from_name(Assembly-CSharp, "", "SceneManager")`.
   **NEVER use the dump JSON `addr` as a class pointer** — that is not a runtime
   `Il2CppClass*` and feeding it to a runtime API crashed the game once
   (`xlua-state.md` §8.3).
4. **Validate by reading the name back:** `name@(cls+0x48)` must equal
   `"SceneManager"`. Abort otherwise.
5. **Resolve MethodInfos by name** (addresses are per-pid, re-fetch every run):
   `get_CurrSceneID/0`, `IsInWorld/0`, `IsInCity/0`, `ChangeScene/1`.
6. **Read state:** invoke `get_CurrSceneID` (static → obj=0). `runtime_invoke`
   **boxes** value-type returns, so read the value at **`ret+0x10`**; likewise
   unbox `IsInWorld`/`IsInCity` (low byte = bool).
7. **Transition:** if in City, `ChangeScene(('val', 2))` — one value-type arg,
   static call. Re-read `get_CurrSceneID`/`IsInWorld` to confirm.

Confirmed live (pid 20404): `CurrSceneID 1→2`, `IsInWorld 0→1`, `exc=0`, game alive.
Direction note: `ChangeScene(2)` (City→World) is exception-clean; `ChangeScene(1)`
(World→City) raises a **non-fatal** managed exception but still transitions — for the
reverse move, trust `get_CurrSceneID`, not the `exc` slot (`xlua-state.md` §11.1).

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
