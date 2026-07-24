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
`results/il2cpp_dump.json` (class presence) and `tools/xlua_route.py` (working
managed driver, task #984).
