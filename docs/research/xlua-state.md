# xLua architecture in Last War — the Lua VM as an execution surface

Task #1017 follow-up. Analysis of the open-source **Tencent/xLua** project (MIT)
to understand how the game's Lua layer is structured, and how that maps onto what
this client actually ships. Companion to `il2cpp-invoke-stability.md` §7 (which
names the xLua interpreter as the lowest-detection code-entry surface) and
`dll-injection-vs-ace.md`. **Theory + repo inspection only — no process
interaction.**

---

## TL;DR

xLua is **not a separate native DLL to inject** on this build — it is
**AOT-compiled into `GameAssembly.dll`** as ordinary il2cpp code, and the game
already runs Lua through it constantly. That makes it the ideal "already-loaded
extension point" from §7.3: executing our Lua injects **no foreign module** — it
is data handed to an interpreter the game itself trusts. The project **already
has a working driver for it** — `tools/xlua_route.py` (task #984) resolves the
live `XLua.LuaEnv` instance and calls `LuaEnv.DoString(chunk)` through the stable
hijack + `il2cpp_runtime_invoke` path. So the "reach Lua" open item in §7.3 is
further along than that note implied: the **managed** route (call `DoString`) is
implemented; only the **native** route (touch the raw `lua_State`) is blocked, and
it turns out we do not need it.

---

## 1. What the repo scan found

- **Files referencing xLua:** `tools/xlua_route.py` (the driver),
  `tools/il2cpp_probe.py` (a comment: an obfuscated resolver stub is *"likely a
  stub/obfuscated; try xLua or internal resolver"*), and
  `docs/research/il2cpp-invoke-stability.md` (§7).
- **No `xlua.dll` / `lua*.dll` on disk.** `find` over the game drive returned
  nothing (the mounted `/mnt/d` was empty in this environment; the broad
  multi-mount search timed out without a hit). The absence is consistent with the
  next point, not just with the game living elsewhere.
- **The xLua *managed* classes are in the il2cpp dump.**
  `results/il2cpp_dump.json` contains `XLua.LuaEnv`, `LuaTable`,
  `ObjectTranslator`, `LuaFunction`, `LuaBase`, `XLuaManager`, and 46 `XLua`
  namespace hits. These are C# types compiled into `GameAssembly.dll`.

**Conclusion:** the C# half of xLua (the `XLua.*` wrapper classes) is baked into
`GameAssembly.dll` by il2cpp. The native Lua core is either statically linked into
`GameAssembly.dll` or shipped as a native plugin not visible in this environment —
but crucially there is **no separate managed module and no obvious `xlua.dll`
export surface** to lean on. This matches the zentia/xLua "xLua-il2cpp" variant
lineage, where the binding layer is generated into the il2cpp output rather than
kept as a standalone assembly.

## 2. xLua architecture (from the open MIT project)

xLua embeds a Lua VM into Unity and bridges it to C#. The pieces that matter here:

- **`XLua.LuaEnv`** — the top-level object wrapping one Lua VM. Public API:
  `DoString(string chunk, string chunkName = "chunk", LuaTable env = null)`
  compiles and runs a Lua chunk; `Global` exposes the global table; `Tick()`
  drives GC. One `LuaEnv` owns one `lua_State`.
- **The raw `lua_State`** — `LuaEnv` holds it as an `IntPtr` (the `L` /
  `rawL` field in the open source). This is what the **native** Lua C API
  (`luaL_loadbuffer`, `lua_pcall`, `luaL_dostring`) operates on.
- **`LuaTable`** — a managed handle to a Lua table (the `_G` global table is a
  `LuaTable`). Referenced by a registry index into the Lua VM.
- **`ObjectTranslator`** — the marshalling core: maps C# objects ↔ Lua userdata,
  resolves method calls across the boundary. Every `LuaEnv` has exactly one.
- **`LuaBase` / `LuaFunction`** — base handle type and a callable Lua-function
  handle.

The important architectural fact: **`LuaEnv.DoString` is a managed method that
internally calls the native `luaL_loadbuffer` + `lua_pcall` on its `lua_State`.**
So there are two levels at which our code can enter the same VM — call the managed
wrapper, or call the native core directly.

## 3. How this maps onto the game — validated by `xlua_route.py`

`tools/xlua_route.py` (task #984) already exercises the managed route end to end,
and its structure confirms the open-source layout against the live process:

1. **Resolve `XLua.LuaEnv` class** via `il2cpp_class_from_name` on the
   `Assembly-CSharp` image.
2. **Get the *live* instance through `XLuaManager.Instance`** — header-scanning the
   heap only finds `FieldInfo` metadata, so it invokes the `XLuaManager`
   singleton's `get_Instance` and scans its fields for a pointer whose class name
   is `LuaEnv`.
3. **Signature-check the instance** against the known xLua field layout:
   `LuaEnv._G` (offset resolved via `il2cpp_class_get_field_from_name`) must
   deref to a `LuaTable`, and `LuaEnv.translator` to an `ObjectTranslator`. Both
   holding matches the open-source `LuaEnv` shape and proves the object is real.
4. **Pick the right `DoString` overload** — iterate `LuaEnv` methods, select the
   one whose first parameter is `System.String` (not `byte[]`), with 3 params
   `(string chunk, string chunkName, LuaTable env)`.
5. **Call `DoString`** via `il2cpp_runtime_invoke` on the RIP-gated main thread
   (`save_xmm=True`, `only_tid=main`), passing an il2cpp `System.String` chunk, a
   name string, and null env; read the exception slot to confirm `exc == 0`.

This is the §7.3 idea realized: the Lua chunk is **data** fed to the game's own
interpreter through its own public entry point. No module is injected; the only
active primitive is the already-stable managed invoke.

## 4. Two entry routes into the same VM — trade-offs

| | **Managed route (implemented)** | **Native route (blocked)** |
|---|---|---|
| Entry | `LuaEnv.DoString` via `runtime_invoke` | `luaL_loadbuffer` + `lua_pcall` on the raw `lua_State` |
| Needs | LuaEnv instance + DoString `MethodInfo` (have both) | the `lua_State` ptr **and** native Lua export addresses |
| Blocker | none — works (`xlua_route.py`) | no `xlua.dll` exports; core is static/obfuscated in `GameAssembly.dll`, so the native symbols are not readily resolvable (same `addr_off: null` obfuscation seen for method pointers) |
| Detection surface | lowest — a trusted managed call with a string arg | slightly lower call overhead, but requires locating native code inside the guarded module |
| Verdict | **use this** | not needed; pursue only if a managed `DoString` proves insufficient |

The native route's only theoretical advantage is skipping the managed wrapper, but
it costs the hard part — resolving `luaL_loadbuffer`'s address without an export
table — for no stealth gain. The managed route already runs arbitrary Lua.

## 5. Why the Lua surface matters for the City→World goal

`il2cpp-invoke-stability.md` §6 records the standing blocker: the useful game
actions (UI transitions, City→World) live in **Lua**, so a stable C# invoke is
necessary but not sufficient. The xLua route closes exactly that gap — `DoString`
lets us run the same Lua the game's own buttons run, from a chunk we author,
through the already-proven hijack+invoke primitive. Concretely, the next steps are
Lua-authoring problems, not injection problems:

- enumerate the global Lua functions the client uses for scene/world transitions
  (read `_G` via a `DoString` that serializes keys, or via `LuaTable` access);
- call the world-open Lua function with the right args from a `DoString` chunk;
- keep every call gated (base idle, main thread at `SAFE_RIP`) per the §5 protocol.

## 6. Open items

- **Native `lua_State` handle** — locatable via `LuaEnv`'s raw `IntPtr` field, but
  the native Lua exports it would feed are not resolvable without an export table.
  Parked; the managed route makes it unnecessary.
- **Whether `DoString` on the gated main thread is safe for *mutating* Lua** —
  `xlua_route.py` proves a read/print chunk; a scene-mutating chunk is the same
  risk class as any allocating/async-driving invoke (§5) and must be validated on
  an emulator + throwaway account first.
- **Confirm the native core's location** — establish whether the Lua core is
  statically linked into `GameAssembly.dll` or a separate (here-invisible) native
  plugin. Not blocking, but it settles whether a native route could ever exist.

**Sources (open):** Tencent/xLua (MIT) — `LuaEnv`, `LuaTable`, `ObjectTranslator`
API and `DoString` semantics; zentia/xLua (xLua-il2cpp variant) for the
il2cpp-baked binding layout; Unity IL2CPP manual for how managed assemblies and
native plugins compile in an IL2CPP player. Live confirmation is from this repo:
`results/il2cpp_dump.json` (class presence) and `tools/xlua_route.py` (managed
driver skeleton, task #984 — but see §7 for the live blocker).

---

## 7. Live attempt to run `DoString` (task #1017, pid 32136)

Active run against the focused game process. **Outcome: the C# scaffolding for
`DoString` fully resolves, but no live `LuaEnv` instance could be pinned, so no
Lua chunk was executed. The City→World transition was therefore not attempted —
it is correctly gated behind a working `DoString` test.** The game process stayed
alive throughout (all hijacks fired against tid 43404 parked at
`SAFE_RIP=0x7ffd40710e84`; base was idle).

### What worked

- **The gated hijack + invoke path is healthy.** Every `il2cpp_*` call landed:
  class enum, `il2cpp_class_from_name`, field/method resolution — all 6/6 style
  reliability described in `il2cpp-invoke-stability.md`.
- **`XLua.LuaEnv` class resolved** (`0x1264660a8`) with the open-source field
  layout confirmed live: `_G` at **+0x10**, `translator` at **+0x18**
  (`il2cpp_class_get_field_from_name` + `field_get_offset`).
- **`XLuaManager` methods enumerated at runtime** (the dump lists 0 methods for
  game classes, so this had to be read live via `il2cpp_class_get_methods`). The
  singleton accessor is **not** `get_Instance` — that call returns `mi == 0`, which
  is why `xlua_route.py`'s `luaenv_via_manager` aborts. Instead `XLuaManager` has
  an **instance** method **`get_Env` (0 params, `MethodInfo 0x12a2fa4a8`)** that
  returns the `LuaEnv`, plus `InitLuaEnv`, `LuaLoadPb`, `ClearLuaReference`, etc.
- **`DoString(String, String, LuaTable)` overload is resolvable** on the LuaEnv
  class (3 params, first arg `System.String`).

### What did not work — the blocker

- **`XLuaManager.get_Instance` → null.** No static 0-arg `Instance` accessor exists
  on `XLuaManager` itself (only `get_DelayLuaStartGame`, `get_s_useLwLuaFile`,
  `get_s_lwLuaFile`, `.cctor`). The singleton is almost certainly inherited from a
  base `MonoSingleton<T>` — its `Instance`/static field lives on the **base**
  class, which `il2cpp_class_get_method_from_name(XLuaManager, …)` does not surface.
- **Heap header-scan finds only metadata, not a live instance.**
  `find_instance_rpm.py LuaEnv` → 58 raw header hits, 7 candidates, **none** pass
  the `_G→LuaTable` / `translator→ObjectTranslator` signature; the surviving
  candidates cluster at `0x12684exxx` with `+0x18` pointing **into** the
  `GameAssembly` module range (FieldInfo/metadata, exactly the false-positive the
  `xlua_route.py` comment warned about). `find_instance_rpm.py XLuaManager` → 323
  hits, 4 candidates; the cleanest (`0x1297eff00`) reports class `XLuaManager`.
- **`get_Env` on that candidate returns a non-instance.** Calling
  `get_Env(0x1297eff00)` succeeded with `exc == 0` but returned **`0x12646a018`** —
  an address in the module's static-data range (near the LuaEnv class struct), not
  a heap object: its class deref is unreadable and `_G`/`translator` point at
  garbage. So `0x1297eff00` is not the live, initialized singleton (or its
  `LuaEnv` field is unset), and no valid `LuaEnv` was obtained.

### Interpretation

The managed `DoString` route is **wired but not yet reachable**: we can resolve
every type and method, but cannot currently hand `runtime_invoke` a genuine live
`LuaEnv` object. The gap is purely **instance discovery** — the game's xLua
variant does not keep the singleton where a header-scan or a self-declared
`get_Instance` finds it.

### Next steps (in order of expected payoff, all still gated + emulator-first for
mutation)

1. **Resolve the singleton via its base class.** Walk `XLuaManager`'s parent chain
   (`il2cpp_class_get_parent`) to the `MonoSingleton<T>`/`Singleton<T>` base, read
   its static **`Instance`** field with `il2cpp_field_static_get_value` (or
   `class_get_field_from_name` on the base + read static data). This is the
   canonical fix and does not need a heap scan.
2. **Back-reference from `ObjectTranslator`.** There is exactly one live
   `ObjectTranslator` per VM; scan for it, then find the `LuaEnv` that references
   it (LuaEnv+0x18 → this translator). A single ObjectTranslator is a much cleaner
   scan target than LuaEnv.
3. **Hook `InitLuaEnv`'s return** (read-only): resolve its MethodInfo and, on the
   next gated call, capture the constructed `LuaEnv` — but this only helps at VM
   init, not mid-session.
4. Only once a valid `LuaEnv` is confirmed by signature: run the canary
   `print(...)` / `CS.UnityEngine.Debug.Log(...)` chunk, *then* author the
   City→World Lua and validate on an emulator + throwaway account.

**Correction to earlier sections:** `xlua_route.py` is a *skeleton that resolves
the types* but does **not** currently drive a live VM end to end on this build —
its `luaenv_via_manager` depends on a `get_Instance` that returns null here. The
"working managed driver" phrasing above overstated it; the real state is
"mechanism proven, live instance not yet pinned."

---

## 8. Autonomous session (task #1017, unattended) — the xLua route is walled, but
the C# **static** `SceneManager` route is the answer; and one crash

Ran unattended against pid 32136 (`tools/xlua_dostring.py` + ad-hoc probes). Two
big outcomes and one incident.

### 8.1 The xLua managed route is definitively blocked on this build

Every avenue to obtain a *live managed instance* failed — this is structural, not
a missing detail:

- **No `get_Instance`.** `XLuaManager` inherits directly from `System.Object`
  (parent chain: `XLuaManager → Object`), so it is **not** a `MonoBehaviour` /
  `MonoSingleton<T>`. Its static fields are only path/config strings — **no
  `Instance` field**. So there is no static accessor to the singleton at all.
- **Heap header-scan finds only metadata.** `find_instance_rpm LuaEnv` → 7
  candidates, none signature-valid; `XLuaManager` → 4 candidates, **all metadata**
  (calling `get_Env` on each returned garbage class pointers like `NetworkManager`,
  `EventNotifyWrap` — module-range `Il2CppClass*`, not objects).
- **A full 3.38 GB scan of every committed region** for an object with
  `*(obj)==LuaEnv_class && +0x10→LuaTable && +0x18→ObjectTranslator` returned
  **0 hits.** The live VM exists (82 raw `ObjectTranslator` / 10 `LuaTable` header
  hits) but no locatable `LuaEnv` object carries the resolvable class pointer.

**Conclusion:** on this ACE build, managed **object headers do not carry an
`Il2CppClass*` that matches `il2cpp_class_from_name`** (or the live objects sit
outside scannable regions) — so *instance discovery by memory scan is dead*, and
with no static singleton accessor, the xLua `DoString` route has no reachable
`LuaEnv`. Park it.

### 8.2 Breakthrough — the game `SceneManager` is entirely **static**, which
bypasses the instance wall

Enumerating the game `SceneManager` (Assembly-CSharp) at runtime: **all 38 methods
are static.** Static methods need no `this`, so they sidestep the instance-discovery
wall completely. Confirmed working live (all `exc==0`; `runtime_invoke` **boxes**
value-type returns, so the real value is at `ret+0x10`):

| Static method | MethodInfo | Result at time of test |
|---|---|---|
| `get_CurrSceneID` | `0x12992e4d8` | **2** |
| `IsInWorld` | `0x12995c9b8` | **true** |
| `IsInCity` | `0x12a206eb8` | false |
| `IsSceneNone` | `0x129e43390` | false |
| `get_CurrentSceneSubType` | `0x12992ec20` | 7 |
| `ChangeScene(SceneID)` | `0x362370b68` | *the City↔World primitive (1 value-type arg)* |
| `CreateWorld` / `CreateCity` | `0x2e76d1170` / `…1198` | static 0-arg scene builders |
| `get_World` | `0x12a206ee0` | returns a `WorldScene` object, not the enum |

So **`SceneManager.ChangeScene(SceneID.World)` is the City→World primitive**, it is
static and directly callable, and **`SceneID.World == 2`** is confirmed
(`CurrSceneID==2` while `IsInWorld==true`). This supersedes the xLua route for the
scene-transition goal: the useful action is reachable in C# after all, via a
*static* call. `get_CurrSceneID`/`IsInWorld` also give a perfect read-only canary
and a post-transition verification.

### 8.3 Incident — the game crashed (my error), and `ChangeScene` never actually
fired

While enumerating the `SceneID` enum's members to confirm the **City** value, I
called `il2cpp_class_get_fields` with an **invalid class pointer** — `0x1266F9C08`,
taken from the dump JSON's `addr` field, which is **not** the runtime
`Il2CppClass*` (its name read as `SupportsType`). Feeding a garbage `Il2CppClass*`
to a runtime API **on the gated main thread** dereferenced bad memory
(`RPM err=299` inside `hijack_call`) and **crashed `LastWar.exe`** (process and ACE
both gone afterwards).

Consequently **`ChangeScene(SceneID.World=2)` was never executed** — the run that
would have fired it failed at startup because the game was already down. The
transition is *identified and argument-confirmed* but **not yet demonstrated live.**

I did **not** restart the game — relaunching the client and re-authenticating the
user's account while they are away is their call, not an autonomous one.

**Root-cause lesson (matches il2cpp-invoke-stability §5 "refuse null targets", now
generalized):** guard **class pointers** the same way as MethodInfo. Never pass an
`Il2CppClass*` to a runtime API unless it was returned by a runtime resolver
(`il2cpp_class_from_name` / the live enum table) and validated by reading its name
back. The dump JSON's `addr` is **not** a usable class pointer. A bad
`Il2CppClass*` on the main thread is as fatal as a null MethodInfo.

### 8.4 State and next steps

- **Confirmed and reusable:** static invoke works; `SceneManager` is all-static;
  `ChangeScene(SceneID)` @ `0x362370b68`; `World==2`; read-only canaries
  `get_CurrSceneID` / `IsInWorld` / `IsInCity`.
- **Still open:** the **City** `SceneID` value (enumerate `SceneID` via a *valid*
  runtime class ptr — resolve it from the live class-enum table, not the dump
  `addr`); and an actual live `ChangeScene(World)` fire, done **with the game in
  City and the user present**, verified by `IsInWorld` flipping true.
- **Parked:** the xLua `DoString` route (no reachable live `LuaEnv`); revisit only
  if a static/singleton accessor to a VM handle is ever found.
- **Safety:** any real `ChangeScene` fire is a scene mutation — gate on idle base,
  validate the enum arg, and prefer the emulator + throwaway account first per §5.
  MethodInfo/class pointers above are stable only for pid 32136's lifetime; that
  process is gone, so all addresses must be **re-resolved** on the next launch.

---

## 9. xLua source analysis (task #1017, Step 0) — from the real MIT repo

Read the actual `Tencent/xLua` sources (not the 0-method dump) to stop guessing.
This resolves *why* the managed route kept failing and gives a robust discovery
plan. **The game was down during this step, so Steps 1–2 (resolve + canary) could
not run — see §9.4.**

### 9.1 `LuaEnv` — no singleton, exact field order

From `Assets/XLua/Src/LuaEnv.cs`:

- **`LuaEnv` has NO singleton.** It is created with `new LuaEnv()`. So there is
  nothing to reach via a static `Instance` on `LuaEnv` itself — the earlier
  `get_Instance` hunt was doomed at the type level.
- **Instance fields, declaration order:**
  1. `internal RealStatePtr rawL;` — the raw **`lua_State`** pointer (`RealStatePtr`
     = `System.IntPtr`).
  2. `private LuaTable _G;` — the global table.
  3. `internal ObjectTranslator translator;`
  4. `internal int errorFuncRef = -1;`
  5. `internal object luaLock;`
- **Raw `lua_State` is exposed** via property `internal RealStatePtr L { get; }`
  (throws if `rawL == Zero`). So once a live `LuaEnv` is in hand, the native Lua
  C API is reachable through `rawL`.
- **Run-Lua API:** `public object[] DoString(string chunk, string chunkName =
  "chunk", LuaTable env = null)` (and a `byte[]` overload). Matches the overload
  `xlua_route.py` already selects.

> **Offset caveat.** Source order is `rawL(0)→_G(1)→translator(2)`, but this build's
> runtime `il2cpp_field_get_offset` reported `_G@0x10, translator@0x18` — i.e. the
> compiled layout differs from upstream declaration order (il2cpp reorders, and the
> game's xLua may be patched). **Always trust runtime `field_get_offset`, never the
> source order, for offsets.** Resolve `rawL`/`_G`/`translator` offsets live by name.

### 9.2 `ObjectTranslator` — the back-reference that makes discovery robust

From `Assets/XLua/Src/ObjectTranslator.cs`:

- **`ObjectTranslator` holds `internal LuaEnv luaEnv;`** — a back-reference to its
  owning `LuaEnv`, set in the ctor `ObjectTranslator(LuaEnv luaenv, RealStatePtr L)`
  (`this.luaEnv = luaenv;`). **One `ObjectTranslator` per `LuaEnv`.**
- First instance fields (order): `methodWrapsCache`, `objectCheckers`,
  `objectCasters`, `objects` (ObjectPool), `reverseMap` (Dictionary), **`luaEnv`**.
- It does **not** store the `lua_State` as a field (it's passed per-call).

This is the key that §8 was missing. `LuaEnv.translator` and
`ObjectTranslator.luaEnv` form a **mutual reference**. That mutual link is a far
stronger instance-discovery filter than the one-directional signature check that
found 0 hits in §8:

> **Mutual-reference discovery (robust):**
> 1. header-scan for `ObjectTranslator` candidates (§8 found ~82, mostly metadata);
> 2. for each candidate `OT`, read `OT.luaEnv` (offset via runtime `field_get_offset`
>    on the `luaEnv` field) → candidate `L`;
> 3. read `L.translator` → if it equals `OT` **and** `clsname(L) == "LuaEnv"`,
>    the pair is genuine. Metadata false-positives cannot satisfy the mutual link.
>
> This does not depend on any singleton, on `_G` being non-null, or on `XLuaManager`
> at all — it keys purely on the two objects pointing at each other.

### 9.3 The game's `XLuaManager` — not a `MonoSingleton`

The proposed "`MonoSingleton<T>` → static `Instance`" path does **not** hold on
this build: `XLuaManager` inherits `System.Object` **directly** (runtime parent
chain `XLuaManager → Object`, §8.1) and has no static `Instance` field — only path
strings. `XLuaManager` is a *game-specific* wrapper (not part of xLua core; the
xLua repo has no `XLuaManager.cs`). Its `get_Env` returns the `LuaEnv`, but it is
an **instance** method, so it still needs a live `XLuaManager` — which the
header-scan cannot pin either. **Therefore the mutual-reference route (§9.2), which
avoids the manager entirely, is the recommended discovery path**, superseding both
the `get_Instance` and the `get_Env`-on-a-scanned-manager approaches.

### 9.4 Blocker — Steps 1–2 need a live process, and the game is down

The game crashed at the end of §8 (my invalid-class-pointer error) and has not
been relaunched. Resolving a live `LuaEnv` (Step 1) and the `DoString` canary
(Step 2) both require the running process. **I am not autonomously relaunching the
client / re-authenticating the account while the user is away** — that is an
account-touching action for them to take.

What is ready for the next live session (game up, user present):
- `tools/xlua_dostring.py` now implements the **mutual-reference discovery**
  (§9.2) — read-only, but **untested since the crash** (no live process to verify
  against). Re-resolve all class pointers on the new pid first.
- Then the canary: `DoString("CS.UnityEngine.Debug.Log('xlua_alive')")`.
- **Reminder:** the C# **static `SceneManager` route (§8.2)** already reaches the
  actual City→World goal (`ChangeScene(SceneID.World==2)`) without any of this
  instance-discovery difficulty. The xLua route is worth finishing for arbitrary
  Lua, but it is **not** on the critical path for the scene transition.

**Sources:** `Tencent/xLua` (MIT) `Assets/XLua/Src/LuaEnv.cs` and
`ObjectTranslator.cs`; xLua `LuaBehaviour` example and community notes on the
"one global LuaEnv, held by a manager" pattern.

---

## 10. Autonomous `ChangeScene` fire attempt — blocked (game still down)

Directive: check the process, and if up, re-resolve `SceneManager` via a **runtime
resolver** (`il2cpp_class_from_name`, validated by reading the class name back —
never the dump JSON `addr`, which caused the §8.3 crash), then
`get_CurrSceneID` → if in City, `ChangeScene(2)` → verify `IsInWorld`.

**Result: not run.** `LastWar.exe` was polled **5 times, 30 s apart (~2 min)** and
stayed **down** the whole time. The game has not been relaunched since the §8.3
crash. Steps 2–4 need a live process; I am not autonomously relaunching the client
or re-authenticating the account.

The procedure is ready to execute the instant the game is up (all addresses must be
re-resolved on the new pid):
1. `find_game_pid`; `il2cpp_class_from_name(Assembly-CSharp, "", "SceneManager")` →
   **validate** by reading the class name back (must equal `SceneManager`).
2. Enumerate its methods at runtime to re-fetch `get_CurrSceneID`, `IsInWorld`,
   `IsInCity`, `ChangeScene` MethodInfos (last run's absolutes are dead with pid
   32136).
3. `get_CurrSceneID` (unbox at `ret+0x10`): if `!= 2` and `IsInCity`, fire
   `ChangeScene(('val', 2))` on the gated idle main thread.
4. Re-read `IsInWorld` — expect it to flip true; confirm the process stays alive.
