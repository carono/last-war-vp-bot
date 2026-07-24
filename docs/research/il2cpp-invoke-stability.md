# IL2CPP invoke stability over thread hijacking

Task #1022 (follow-up to #983 / #977). Goal: make in-process IL2CPP calls issued
from a hijacked game thread reliable instead of "sometimes hangs or crashes the
process." This documents the current mechanism, the root causes of the
instability, the fix already landed in `tools/hijack_call.py`, and whether the
`MethodInfo->methodPointer` direct-call shortcut is viable on this build.

Related notes: `command-injection-vectors.md`, and the RE background in the ACE
thread-guard / dumper work.

---

## TL;DR

`il2cpp_runtime_invoke` was never the real problem. Three *mechanical* faults in
the hijack driver made any managed call flaky:

1. **Force-recovery of an in-flight call.** On timeout the old driver yanked the
   thread's RIP back to its parked address and freed the RWX region — while the
   managed call was possibly still running inside il2cpp holding GC/loader locks.
   That corrupts the runtime; the *next* call then wedges and the process dies.
2. **Calling on the wrong thread.** IL2CPP calls must run on a runtime-**attached**
   thread. Proven live: `il2cpp_domain_get` returns the real domain
   (`0x66c22d20`) on the Unity main thread but **`0x0`** on random native workers,
   because it reads the current domain from thread-local state that only exists
   after GC attach. A managed `runtime_invoke` on a non-attached thread
   dereferences that null TLS and crashes.
3. **Null `MethodInfo`.** Invoking `mi == 0` (an unresolved method name)
   dereferences deep inside il2cpp and crashes instantly.

Stack alignment and XMM handling were already **correct** and were *not* the
cause. The stabilization is: gate to the attached main thread, never yank an
in-flight call, and refuse null targets. `il2cpp_domain_get x6` gated to the main
thread is now 6/6 correct, repeatable across separate runs, game stays alive.

---

## 1. How a call is issued today

Pipeline (all read-only steps unless noted):

1. **`rip_gate.learn_safe_rip`** samples the Unity main thread's RIP ~40× while
   the base is idle and takes the dominant value: `SAFE_RIP`, the return address
   of the idle message-pump wait inside ntdll (e.g. `ntdll+0xa0e84`). It is
   re-learned every run — the exact ntdll offset shifts with which wait syscall
   the pump settled in, so a stale absolute address never matches.
2. **`hijack_call.hijack_call(...)`** suspends the target thread, reads its
   context, and only proceeds if RIP is within `±rip_tol` (16) of `SAFE_RIP`
   (with `safe_rip=`) — i.e. the thread is provably parked and about to sleep,
   holding no runtime lock and not inside managed code.
3. It writes shellcode into an RWX `VirtualAllocEx` region, points the thread's
   RIP at it, and resumes. The shellcode:
   - `push` all GP registers + `pushfq` (save the interrupted thread's state);
   - `and rsp,-16` then `sub rsp,0x20` → **16-byte aligned stack with the Win64
     shadow space** in place before the call;
   - loads up to 4 integer args into `rcx/rdx/r8/r9`, `mov rax, func`, `call rax`;
   - stores the return `rax` to `result_abs`, restores everything, and
     `jmp`s back to the original RIP so the thread continues as if nothing
     happened.
   - `build_shellcode_xmm` additionally spills/reloads `xmm0..xmm5` around the
     call (a 16-aligned 0x60 block below the shadow space).

### Parameter marshalling for `runtime_invoke`

`il2cpp_runtime_invoke(MethodInfo* mi, void* obj, void** params, Il2CppException** exc)`
— exactly 4 integer args, so all fit in registers (no stack args, `0x20` shadow
is sufficient). `params` points at an array of per-argument slots; per the
confirmed ABI (see the invoke fragility note):

- **value-type** arg *i* → `params[i] = &value` (pointer to the value);
- **reference-type** arg *i* → `params[i] = the object pointer directly`
  (NOT `&objptr`);
- `obj = 0` for a static method, else the instance pointer;
- `exc` is a `&slot` the callee fills on a managed exception — always read it.

`click_world.invoke()` implements this correctly.

### Call markers (added in #1022)

The shellcode now raises two bytes so the driver can tell *where* a call is:

- `started` — written the instruction **before** `call func`;
- `done` — written the instruction **after** the call returns.

---

## 2. Root-cause analysis

### Diagnostic checklist

| Question | Answer |
|---|---|
| Stack 16-aligned before the call? | **Yes.** `and rsp,-16` + `sub rsp,0x20` (shadow) → RSP%16==0 at `call`. Not the cause. |
| XMM saved/restored? | **Yes, and it was never the cause.** `build_shellcode_xmm` preserves `xmm0..5`. Note: `xmm0..5` are *volatile* (caller-saved), and `xmm6..15` are *callee-saved by ABI*, so strictly the save is belt-and-suspenders; because `SAFE_RIP` is a post-`call` return address in ntdll, the interrupted code already treats volatile regs as clobbered. Correct either way. |
| Called from the right thread? | **This is the core issue.** IL2CPP calls need a GC-**attached** thread. Only the Unity main thread is attached; a random parked worker is not, so its runtime TLS (current domain / current thread) is null and any managed call faults. Evidence: `il2cpp_domain_get` → `0x66c22d20` on main, `0x0` on workers. |
| GC pause / safe points? | **Handled by the RIP-gate, was never observed to fire.** We hijack only at `SAFE_RIP` = idle in the message-pump wait, i.e. *outside* managed code, holding no GC/loader lock. The managed call therefore starts from a clean state on the mutator thread, and il2cpp's own GC coordination runs normally. The danger is hijacking *mid-managed-execution* (reentrancy) — the gate prevents exactly that. |

### The three mechanical faults

1. **Force-recovery corrupted the runtime.** Old flow: wait 4 s; on timeout
   `SuspendThread` → force RIP back to `orig_rip` → `ResumeThread` → free the RWX
   region. If the managed call was genuinely still executing (holding GC/loader
   locks, mid-allocation), abandoning it mid-flight leaves those locks held. The
   thread returns to the message pump with a corrupt runtime; every later gated
   call that needs those locks hangs, then the process crashes. A prior aborted
   call also poisoned all *subsequent* calls — consistent with a permanently held
   lock. Freeing the region at `+0.5 s` regardless of whether RIP had left it
   compounded the risk (executing thread → freed page → fault).

2. **Thread selection was unreliable two ways.** (a) Many parked threads sit in
   *indefinite* kernel waits; after `SetThreadContext`+`Resume` they never return
   to user mode, so the shellcode never runs and the old code simply timed out
   (then force-recovered). (b) Even a thread that *does* run our code gives wrong
   results if it is not runtime-attached (the `domain_get == 0` case) — and for a
   real `runtime_invoke`, "wrong result" becomes "null-TLS deref → crash."

3. **Null `MethodInfo`.** A mistyped accessor name makes
   `il2cpp_class_get_method_from_name` return 0; invoking that crashes at once.

---

## 3. What landed in `tools/hijack_call.py` (#1022)

- **`started`/`done` two-phase markers** (both shellcode builders).
- **Split timeouts.** `start_timeout` (default 0.6 s) — time for `started` to
  flip; `call_timeout` (8 s) + `extend_timeout` (8 s) — time for `done` after the
  call began.
- **Non-destructive recovery.** RIP is force-restored **only when `started == 0`**
  (the call never began — safe). Once `started == 1` the call is in flight and we
  **never** yank it: we wait, and if it still never returns we leave the thread
  running untouched and **leak** the RWX region (freeing under a live RIP would
  fault). A slow-but-completing call now finishes instead of dying at 4 s.
- **Responsive-thread selection.** If `started` never flips within `start_timeout`
  on a swept thread, cleanly restore its RIP and try the **next** thread — no
  force-recovery, no timeout stall.
- **Attach-correct routing.** Real managed/IL2CPP calls go through the main thread
  via `only_tid=main_thread_tid(pid)` (what `click_world.py` / `find_instance_rpm`
  already do). The "any parked thread" sweep stays only as a diagnostic for
  stateless C exports.
- **Null-target guard.** `hijack_call` raises `ValueError` on `func == 0` at entry.
- **Region freed only after RIP is confirmed outside it** (`_free_region_when_clear`).

Validation harness: `C:\Python312\python.exe tools\hijack_call.py --reps=N`
(self-test `GetCurrentProcessId` → `il2cpp_domain_get` sweep, diagnostic → the
verdict step: `il2cpp_domain_get x N` gated to the main thread). Live result on
pid 32136: main-thread **6/6** correct domain, repeatable across separate process
runs, game alive throughout. `click_world.py` recon (no `--fire`) exercises the
full managed path but requires the base **idle** (main thread parked ≥30/40); it
aborts cleanly when the game is busy.

---

## 4. Direct `MethodInfo->methodPointer` call — viable?

**Not on this build, currently.** The idea: skip `runtime_invoke` (which walks an
`invoker_method` thunk) and `call` the compiled code directly. That needs the
per-method code pointer.

- Standard il2cpp: `MethodInfo` field 0 is `methodPointer` (a VA inside the AOT
  code, i.e. inside `GameAssembly.dll`). This build **reorders** MethodInfo
  fields, so `il2cpp_dump.py` looks for the code pointer by range-scanning the
  first `0x60` bytes of sampled `MethodInfo`s for the first qword that lands
  inside `GameAssembly.dll`'s mapped range (`addr_off`).
- **Result in the live dump (`results/il2cpp_dump.json`): `addr_off: null`.** No
  qword in the first 12 slots of any sampled MethodInfo points into the module.
  So the compiled code pointer is **not recoverable** as a plain VA from
  MethodInfo here — consistent with ACE relocating/obfuscating metadata (the
  same reason global-metadata is hidden on disk).

Implications:

- A naive `call methodPointer` is impossible without the pointer.
- Even if recovered, a direct call **bypasses il2cpp's argument setup and
  `Runtime::Invoke` bookkeeping** (boxing/unboxing, `this` handling, generic
  `MethodInfo` threading via `rcx`/hidden arg, exception frames). Getting the
  exact native ABI per method right is far more error-prone than `runtime_invoke`,
  which already does all of it. Direct calls would trade a *stability* problem we
  just solved for a *correctness* problem.

**Verdict: keep `runtime_invoke`.** It is now stable via §3. Pursue direct
method pointers only if a specific hot method must be called at high frequency,
and only after recovering the real code-pointer offset. Concrete research paths
to recover it, in order of effort:

1. Widen the detect window past `0x60` and vote again — the pointer may simply
   sit further into a larger MethodInfo on this build.
2. Resolve one known method both ways: get its `MethodInfo`, then find its true
   code address by another route (e.g. set a hardware breakpoint / single-step a
   `runtime_invoke` of it and capture the final `call` target inside
   `GameAssembly`), and diff to learn the real `methodPointer` offset — or confirm
   it is stored encrypted / behind the `invoker_method` indirection.
3. Inspect `invoker_method` (the thunk `runtime_invoke` actually jumps through):
   if MethodInfo holds an `invoker` VA in-range, that is the reusable entry, and
   the real code pointer can be read out of the invoker or its arguments.

---

## 5. Remaining hardening & a call-safety protocol

Even with §3, follow this protocol for every new managed target to keep the live
game safe:

1. **Idle gate.** Only fire when `learn_safe_rip` stability ≥ 30/40 (base idle,
   not loading). Otherwise abort — do not force it.
2. **Resolve, then guard.** Get the `MethodInfo` with `class_get_method_from_name`
   (matches by name **and** arg count → right overload). Refuse `mi == 0`. Confirm
   flags (static vs instance) and param count match your call shape.
3. **Classify before firing.** Read-only getters (`get_*`, `Is*`, enum reads,
   class/domain queries) are safe on the gated main thread. Treat any
   **allocating / scene-mutating / async-driving** method as high-risk: it may run
   long (now tolerated by the extended wait) *or* leave partial state. Prefer
   canary getters first (`get_CurrSceneID`) to confirm liveness.
4. **Never invoke on a non-attached thread.** Always `only_tid = main thread`.
5. **One call at a time.** Do not overlap hijacks; each call fully completes (or
   is cleanly abandoned) before the next.
6. **Recovery is restart.** If a call genuinely wedges (`done` never set), the
   driver leaks the region and leaves the thread — the game may be stuck. The
   reliable recovery is a game restart, not another forced hijack.

Known limitations to be aware of:

- The shellcode passes at most **4 integer args** (no stack args) and returns a
  single integer/pointer in `rax`. Methods with >4 params or returning large
  value types by hidden pointer need shellcode changes.
- `save_xmm=True` is required for any target that takes/returns float/vector args
  (e.g. `runtime_invoke` into methods with float params).
- This whole path only reaches **C# methods**. The game's UI/transition logic is
  in the embedded **xLua** layer, not invocable via `runtime_invoke` — see the
  City→World findings; the stable in-process call mechanism does not change that.

---

## 6. Recommendation

The invoke mechanism is stabilized: gate to the attached main thread, two-phase
markers, no force-recovery of in-flight calls, null-target guard, safe region
free. Use `runtime_invoke` (not direct method pointers — `addr_off` is
unrecoverable here). Validate any new target with the harness and the §5 protocol.
The remaining open item is orthogonal to call stability: the useful game actions
live in xLua, so a stable C# invoke is necessary but not sufficient for the
City→World goal.

---

## 7. Alternative code-entry vectors without `CreateRemoteThread` (task #1017 follow-up)

Theory + open-source review only — no process interaction. Motivation: this build's
ACE neuters `CreateRemoteThread` whose start address is in private memory or in
`GameAssembly.dll`/il2cpp (thread exits `0xdeadc0de`); only a start inside a
**system module** runs (memory note *ACE thread-start guard*). Thread **hijacking**
already sidesteps that guard and is stable (§1–§3). This section evaluates the
other classic entry vectors against that same guard, so the reframe in
`dll-injection-vs-ace.md` is grounded in what each technique actually requires.

### 7.1 APC injection — `QueueUserAPC` on an alertable thread

Mechanism (per ired.team / repnz "Low Level Pleasure" APC series): `QueueUserAPC`
wraps `NtQueueApcThread`, appending a user-mode APC to a specific thread's queue.
The APC's routine runs **only when that thread enters an alertable wait** —
`SleepEx`, `WaitForSingleObjectEx`, `MsgWaitForMultipleObjectsEx`, etc. with
`bAlertable = TRUE`. A thread not in an alertable wait never drains the queue, so
delivery is not guaranteed on demand.

- **Requirements:** a handle to a target thread (we have this — hijack already
  opens threads) and that thread reaching an alertable state. `NtTestAlert` drains
  the queue at thread startup, which is what the **Early Bird** variant exploits
  (queue the APC on a *suspended, freshly created* process before its entry point
  runs). Early Bird does **not apply here** — the game process is already running;
  we cannot create it suspended without changing the launch/integrity posture ACE
  expects.
- **vs. the ACE guard:** an APC is **not a new thread** — no `CreateRemoteThread`,
  no thread "start" in private memory. From the thread-start guard's point of view
  it should be as invisible as a hijack: an existing, already-attached thread
  simply runs an extra callback. This is APC's one real advantage over
  `CreateRemoteThread` here.
- **The catch — the callback target still executes untrusted code.** The APC
  routine we queue points at our RWX shellcode (private memory). If ACE also
  samples the **current RIP** of threads (not just thread *start* addresses), an
  APC executing our region is exposed exactly like a hijacked thread mid-call —
  the same open question §5/`dll-injection-vs-ace.md` §6 already flags. APC does
  not improve on hijack there; it only offers a second trigger.
- **The `LoadLibrary`-via-APC pattern is worthless here** (`QueueUserAPC` with
  `pfnAPC = LoadLibraryW`, `data = path-to-DLL`): the routine start would be in
  kernel32 (allowed), but the *result* is a fully linked, on-disk module — killed
  by the same module scan that kills Frida. Confirmed in `dll-injection-vs-ace.md`
  §3.
- **Verdict:** APC is a **viable alternate trigger** for PIC shellcode (no new
  thread, dodges the `0xdeadc0de` guard), but it is **strictly worse than hijack
  for reliability** — it needs the target thread to hit an alertable wait we do
  not control, whereas the RIP-gate deterministically catches the main thread
  parked at `SAFE_RIP`. Keep as a fallback trigger, not a primary. It buys nothing
  for loading a *DLL*.

### 7.2 `SetWindowsHookEx` — `WH_KEYBOARD`/`WH_MOUSE` hook

Mechanism (ired.team / cocomelonc / War Room writeups): install a hook with
`SetWindowsHookEx(idHook, lpfn, hMod, dwThreadId)` where `hMod` is a DLL exporting
the hook procedure. When the target thread processes a matching message, the OS
**maps that DLL into the target process** and calls the exported proc.

- **Hard requirements that kill it on this build:**
  1. **The payload must be an on-disk DLL** — `SetWindowsHookEx` maps a real file
     from a real module handle (`GetModuleHandle`/`LoadLibrary` of the hook DLL).
     No manual-map, no headerless image. On-disk footprint is exactly what we are
     trying to avoid.
  2. **It must export the hook procedure** — a named export, i.e. an obvious,
     scannable module with a telltale export.
  3. **The OS links it as a normal module** in the target's PEB — enumerable by
     `EnumProcessModules`/`Module32Next`, the same surface that flags Frida.
  4. It only reaches processes with a **message loop / GUI thread** and requires a
     matching input event to trigger (a Unity window has one, so this part is fine).
- **vs. the ACE guard:** the trigger is OS-driven (no `CreateRemoteThread`), so it
  passes the thread-start guard — but that is irrelevant because requirements 1–3
  produce a loud, linked, on-disk module. It trades a good trigger for the worst
  possible payload stealth.
- **Verdict:** **rejected.** `SetWindowsHookEx` cannot load a *stealthy* DLL by
  construction — it is defined in terms of a real, exported, on-disk module. It is
  a non-starter against a module-fingerprinting anti-cheat.

### 7.3 Using already-loaded DLLs / native extension points

The idea: instead of injecting anything, hijack an **existing** extension surface
the game already loads legitimately, so no foreign module ever appears.

- **Unity IL2CPP native plugins.** IL2CPP games load native plugins as ordinary
  DLLs via `[DllImport]`/`dlopen`, resolved at build/run time (Unity manual,
  "C++ source code plugins for IL2CPP"). But the plugin set is **fixed at build
  time** and shipped inside the game package; there is no runtime "drop a DLL in a
  folder and it loads" surface on a hardened retail client. Adding one means
  placing a DLL on disk where the loader looks — i.e. **DLL search-order / phantom
  hijack** — which (a) is an on-disk linked module again and (b) alters files ACE
  integrity-checks. Not viable for stealth.
  - Note the class of bug this maps to: **CVE-2025-59489** (Unity Runtime,
    2017.1+), an ACE-unrelated arbitrary-code-execution issue where Unity can
    `dlopen()` an attacker-controlled native library during **early init**
    (pre-init library injection, command-line/intent-driven on some platforms).
    Same shape as Early Bird — it needs the *pre-init* window and a controllable
    library path, neither of which we have on an already-running, ACE-guarded PC
    client. Recorded as a data point, not a usable path here.
- **xLua / embedded Lua.** The game logic is Lua (`chat.md`, protocol §5 —
  stringified Lua table on the wire), and xLua exposes a C API (`luaL_loadbuffer`,
  `lua_pcall`) plus a C#↔Lua bridge. If we can reach the live `lua_State`, running
  **Lua** needs *no injected native module at all* — it is data fed to code the
  game already trusts and runs. That is a fundamentally lower-detection surface
  than any DLL. The blocker is orthogonal to this note: we do not yet have a stable
  handle to the `lua_State` or a gated call into `luaL_loadbuffer`, and the
  City→World logic living in xLua is the standing open item (§6). This is the most
  promising "already-loaded extension point" and deserves its own task — reach Lua
  through the *existing* xLua C exports via a hijacked call, rather than injecting
  a module.
- **Verdict:** no drop-in native-plugin surface exists on the retail client; the
  real prize is the **already-present xLua interpreter** — calling into it executes
  our logic with zero foreign module, but requires resolving `lua_State` +
  `luaL_loadbuffer` first (open task, not solved here).

### 7.4 Can the existing thread hijack itself load arbitrary code? — yes

This is the practical answer to "which of these is realistic given a working
hijack." The hijack is already an **arbitrary-code entry primitive**: it redirects
a trusted, attached thread's RIP to bytes we wrote via WPM and runs them under the
Win64 ABI (§1). Consequences:

- **PIC shellcode:** run directly — this is what §1–§3 already do. No new thread,
  no module, dodges the `0xdeadc0de` guard. Lowest detection surface available.
- **A DLL, if genuinely needed:** the hijack supplies the *trigger* for a **manual
  map** — an external mapper writes the image (headers wiped, unlinked, off the
  il2cpp range), then a hijacked thread calls its entry point. This is the exact
  route recommended in `dll-injection-vs-ace.md` §4, and it exists precisely
  because hijack replaces the flagged `CreateRemoteThread` step.
- **Reaching game/engine code:** hijack + `il2cpp_runtime_invoke` for C#; hijack +
  the xLua C exports (§7.3) for Lua — both without loading anything foreign.

**Bottom line:** with a working hijack, APC and `SetWindowsHookEx` add nothing for
loading code — APC is a weaker duplicate trigger, `SetWindowsHookEx` forces a
loud on-disk module. The hijack itself is the entry vector; everything worth doing
is "run PIC / call an existing export" through it, and a DLL is only ever a
last resort delivered as a hijack-triggered manual map. The single genuinely new
avenue these sources surface is the **already-loaded xLua interpreter** as an
execution surface that needs no injection at all.

**Sources (open):** ired.team APC-queue & Early-Bird & SetWindowHookEx code-injection
notes; repnz "Low Level Pleasure" APC series (user-APC internals, `NtTestAlert`);
AbdouRoumi/Early_Bird_APC_Injection and redcanaryco/atomic-red-team T1055.004;
cocomelonc & War Room SetWindowsHookEx tutorials; Unity manual "C++ source code
plugins for IL2CPP" and IL2CPP overview; Tencent/xLua and zentia/xLua repos;
CVE-2025-59489 (Unity Runtime pre-init native-library injection).
