# IL2CPP dump via thread hijacking — results (task #977)

## What was built
`tools/il2cpp_dump.py` — a full IL2CPP class/method dumper layered on the proven
thread-hijack primitive (`tools/hijack_call.py`). No CreateRemoteThread, no
LoadLibrary, no Frida. ACE only neuters threads that *start* in private memory;
hijacking an already-running, ntdll-parked thread runs our code fine.

### How it works
1. **One** hijack runs a self-contained x64 enumeration function injected into a
   scratch region. It walks
   `il2cpp_domain_get → domain_get_assemblies → assembly_get_image →
   image_get_name / image_get_class_count / image_get_class`
   and dumps a per-assembly table + a flat array of every `Il2CppClass*`.
   - Critical detail: the game's il2cpp exports **do not preserve non-volatile
     registers** across calls, so the enum function keeps *all* loop state in the
     scratch region (base address baked as an immediate) and never trusts a
     register to survive a call.
2. Everything else is pure `ReadProcessMemory`. Struct offsets are
   **auto-detected** from sample objects (call `il2cpp_class_get_name` etc., then
   find the matching pointer in the struct bytes), so no version-specific offset
   table is hard-coded.

### Scale
- 115 assemblies, **28 136 classes**, ~30 000 methods dumped.
- Output: `results/il2cpp_dump.json`, `results/il2cpp_targets.json`.

## Detected struct layout (this ACE-hardened il2cpp build)
| struct | field | offset |
|---|---|---|
| Il2CppClass | name | `+0x48` |
| Il2CppClass | namespace | `+0x50` |
| Il2CppClass | methods (MethodInfo**) | `+0xA0` |
| Il2CppClass | method_count (u16) | `+0xFC` |
| MethodInfo (size **0x28**) | token\|flags (u64, token = hi32) | `+0x00` |
| MethodInfo | klass (back-ref) | `+0x08` |
| MethodInfo | name (char*) | `+0x18` |

**Important:** MethodInfo on this build carries **no inline compiled
methodPointer** — the usual slot holds the MethodDef token, and no qword in the
0x28-byte struct lands inside GameAssembly's mapped range. The raw per-method
code address is therefore not directly recoverable this way. Calls must go
through the engine's own `il2cpp_runtime_invoke(MethodInfo*, ...)` path instead
of jumping to an address. All invoke tooling is exported and available.

## The world-transition function (go.to.world)
Found in the game's own static scene manager:

```
class SceneManager (Assembly-CSharp)
    ChangeScene(SceneID)     public static, 1 arg     <-- go.to.world
    CreateWorld()            public static, 0 args
    CreateCity()             public static, 0 args
    DestroyCurScene()        public static, 0 args
    IsInWorld() / IsInCity() public static, returns bool
    get/set_CurrSceneID(SceneID)

enum SceneID { None = 0, City = 1, World = 2 }
```

So switching to the world map = `SceneManager.ChangeScene(SceneID.World)`
(value type passed by pointer-to-int, `2`), or the arg-less `CreateWorld()`.

## Calling it
`tools/call_go_to_world.py` resolves `SceneManager`, the method `MethodInfo*`
and current `IsInWorld/IsInCity` state, then invokes via `il2cpp_runtime_invoke`
using an **XMM0-5-preserving** hijack shellcode (`build_shellcode_xmm` added to
`hijack_call.py`, per task step 3).

- Default = **dry run** (resolve + print plan only).
- `--fire` performs the transition — **gated on purpose**: it mutates live game
  state on a hijacked thread.

```
C:\Python312\python.exe tools\call_go_to_world.py            # dry, safe
C:\Python312\python.exe tools\call_go_to_world.py --fire     # ChangeScene(World)
C:\Python312\python.exe tools\call_go_to_world.py --fire --create-world
```

The actual `--fire` call was **not executed**: mid-investigation the game was
closed (a `field_static_get_value` probe on the enum's non-static `value__`
field faulted the hijacked thread — lesson: only call `static_get_value` on
fields with the STATIC flag). Firing is a live-state mutation and is left as an
explicit, confirmed step to run against a fresh game session.

## Notes / caveats
- Class addresses and `MethodInfo*` pointers in the JSON are per-process (ASLR);
  re-run the dumper after any game restart. Names, tokens and struct offsets are
  stable.
- Read-only enumeration is as safe as the proven `il2cpp_domain_get` hijack.
  Anything that *invokes* game methods (`runtime_invoke`, `static_get_value`,
  `class_init` on odd fields) carries real crash risk — gate and validate.

## Files
- `tools/il2cpp_dump.py`     — the dumper (`--full`, `--methods`)
- `tools/call_go_to_world.py`— resolve + gated invoke of the transition
- `tools/hijack_call.py`     — proven hijack primitive + `build_shellcode_xmm`
- `tools/_scene_probe.py`    — init a class & dump its post-init methods
- `tools/_sig_probe.py`      — method signatures + enum values (diagnostic)
- `tools/_mi_probe.py`       — raw MethodInfo byte inspector (diagnostic)
