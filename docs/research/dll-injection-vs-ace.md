# DLL injection into Last War without tripping ACE — theory

Task #1017. Theory only — no code, no live attempt. This surveys how a full
**DLL** could be loaded into the official PC client (`lastwar.exe`, Unity/IL2CPP
behind Tencent **ACE**, a Ring-0 kernel anti-cheat) without being detected, and
maps every classic injection route against what this specific ACE build has been
*empirically* shown to allow or block. It sits on top of three existing notes and
does not repeat their measurements:

- `il2cpp-invoke-stability.md` — thread-hijack shellcode + `il2cpp_runtime_invoke`
  is stable (task #1022).
- `socket-duplication.md` — `OpenProcess(PROCESS_DUP_HANDLE)` and handle
  duplication are granted (task #883).
- `command-injection-vectors.md` / `protocol.md` §10/§12 — the ACE-transparent
  posture is passive capture + userland MITM; kernel drivers and Frida ban.

The memory notes *ACE thread-start guard*, *Socket duplication WORKS*, and
*IL2CPP dumper + go.to.world* are the primary source of the "what ACE actually
does on this build" facts below.

---

## TL;DR

**A DLL loaded as a normal, linked, on-disk module cannot survive on this build
— not because loading it is hard, but because ACE fingerprints *modules*, the way
it already kills injected Frida modules.** The load *trigger* is also constrained:
ACE neuters `CreateRemoteThread` whose start address is in private memory or
inside `GameAssembly.dll`/il2cpp (thread exits `0xdeadc0de`); only a start inside
a **system module** runs. So the two hard problems are (1) getting execution
without a flagged thread start and (2) keeping the resulting code *invisible as a
module*.

Both are already solved for **shellcode**: thread **hijacking** (`SetThreadContext`
on an existing gated thread, never a new thread) runs arbitrary code, and that
code is a bare RWX region with no PE header, so it is not a "module" to scan. The
practical conclusion is therefore a reframe: **we do not need a DLL.** The stable
hijack+invoke path already gives in-process C# calls. If a DLL is genuinely
required (large native payload, imports, TLS callbacks), the only defensible
route is **manual mapping with the PE headers wiped and the module unlinked from
all three loader lists, its entry point driven by a hijacked thread, allocated
away from `GameAssembly.dll`'s range** — i.e. a DLL that is deliberately *not* a
module any enumeration can see. Everything short of that is a known ban vector.

---

## 1. Empirical ACE model for this build

This is the load-bearing part: the plan must be built on what was *measured on
this client*, not on ACE's general reputation. Consolidated from the three notes
and the memory records:

| Primitive | Observed on this build | Source |
|---|---|---|
| `OpenProcess(PROCESS_DUP_HANDLE)` | **Granted**; `NtQueryObject` shows the DUP bit *kept*, not stripped | socket-duplication |
| `ReadProcessMemory` / `WriteProcessMemory` | **Open** — RPM/WPM used freely for dumps and shellcode staging | il2cpp-dump, memory notes |
| `VirtualAllocEx` RWX in the target | **Works** — hijack shellcode lives in an RWX region | il2cpp-invoke-stability §1 |
| `SetThreadContext` on an existing thread (**hijack**) | **Works, repeatable** — used for the il2cpp dumper and `go.to.world`; connection stays intact | il2cpp-invoke-stability, memory |
| `CreateRemoteThread`, start in **private mem** or **GameAssembly/il2cpp** | **Neutered** — thread exits `0xdeadc0de`, never runs | memory: ACE thread-start guard |
| `CreateRemoteThread`, start in a **system module** (ntdll/kernel32) | **Runs** — only system-module starts are allowed | memory: ACE thread-start guard |
| Injected **module** present (Frida agent) | **Killed loudly** — ACE advertises anti-Frida, force-quits | network-protocol-sniffing §74 |
| Kernel driver on the game traffic (WinDivert) | **Ban** | protocol §12 |
| TLS MITM / CA install / pinning bypass | **Flagged / connection dropped** | network-protocol-sniffing §72 |
| Passive pcap on the host NIC | **Not flagged** — truly out-of-process | network-protocol-sniffing §71 |

Two facts about ACE's *shape* fall out of this table and drive the whole design:

1. **ACE here is a runtime guard on two things: thread starts and module image
   presence — not on raw memory access.** RPM/WPM/`VirtualAllocEx`/`DuplicateHandle`
   all pass. It is not a generic "any process interaction bans" wall (that was the
   task #366 assumption, since overturned). It gates *specific* events: a new
   thread pointing at non-system code, and a recognizable injected *module*.
2. **The `0xdeadc0de` guard is a thread-**origin** check, not a memory-write
   check.** The bytes get written fine (WPM works); what fails is *entering* them
   via a fresh thread whose start address is untrusted. This is exactly why thread
   *hijacking* — which reuses an already-trusted thread and merely redirects its
   RIP — slips under it: from ACE's view no new thread was created and no
   thread "started" in private memory; an existing, already-attached thread simply
   continued.

---

## 2. What "DLL injection" has to achieve, split into two problems

Injecting a DLL is two independent problems that the literature usually conflates:

- **P1 — Execution:** get *some* of our code running in the target's address
  space at all.
- **P2 — Persistence/stealth of the payload as a DLL:** have that code be a real
  PE image (imports resolved, TLS callbacks, exports, `DllMain`) *and* stay
  invisible to whatever enumerates loaded modules.

On this build P1 is **already solved** (thread hijack). The entire difficulty of
"DLL injection without ACE" collapses onto **P2**, because the moment the payload
is a *module*, it enters the same detection surface that kills Frida.

---

## 3. Classic injection routes vs. this ACE model

Every standard technique, rated against §1. "Trigger" = how execution is obtained
(P1); "Module?" = whether the payload ends up as an enumerable image (P2).

| Technique | Trigger | Module? | Verdict on this build |
|---|---|---|---|
| `LoadLibrary` via `CreateRemoteThread` | new thread → `kernel32!LoadLibraryW` | **Yes**, fully linked | **P1 borderline, P2 fatal.** The start address *is* in a system module (kernel32), so the thread-start guard may *allow* it — but the result is a linked module in the PEB, trivially found. Also the DLL path sits on disk. Rejected. |
| `LdrLoadDll` via `CreateRemoteThread` | new thread → `ntdll!LdrLoadDll` | **Yes** | Same as above — system-module start might run, but the module is linked and enumerable. Rejected. |
| `LoadLibrary` via **thread hijack** | hijacked RIP → `LoadLibraryW` | **Yes** | **P1 fine** (proven trigger), **P2 fatal** — still produces a linked module. The good trigger does not save a visible module. |
| `SetWindowsHookEx` | OS loads our DLL into the target on the next hooked event | **Yes**, and **on disk** | Needs an on-disk DLL exporting the hook proc; produces a linked module system-wide. Loud. Rejected. |
| APC injection (`QueueUserAPC` → `LoadLibrary`) | APC fires on an alertable thread | **Yes** | Trigger avoids `CreateRemoteThread`, but still loads a linked module. P2 fatal. The *APC-as-trigger* idea is reusable for shellcode (see §5), not for a linked DLL. |
| **Reflective DLL injection** | shellcode bootstraps the DLL's own loader | **Partly** — self-maps, not linked into PEB by default | **The realistic base.** No `LoadLibrary`, no on-disk file, not linked. But the mapped image *keeps its PE header* and RWX/RX sections unless scrubbed — so image scanning still finds an MZ/PE at an unbacked address. Needs the §4 hardening. |
| **Manual mapping** (external mapper writes the image) | mapper writes sections + relocs via WPM, then hijack-calls the entry | **No** if headers wiped + unlinked | **The recommended route.** Combines the proven hijack trigger with a module that is never linked and whose header is erased. Detail in §4. |
| Process hollowing / doppelgänging | replace image at create-time | n/a | Applies to a process *we* start; `lastwar.exe` is launched by the ACE-protected launcher, and starting it ourselves changes the integrity posture. Out of scope. |

**The pattern is unambiguous: the trigger problem is solved by hijack; the module
problem is only solved by manual mapping with aggressive image hiding.** Any route
whose right-hand column says "Yes (linked)" dies to the same module scan that
kills Frida, regardless of how clever the trigger was.

---

## 4. The only defensible DLL route: hardened manual map

If a DLL is truly required, this is the shape that respects every constraint in
§1. It is an *external* manual mapper (our controller process does the work via
RPM/WPM, which are open) plus a hijack-driven entry call:

1. **Allocate the image far from `GameAssembly.dll`.** `VirtualAllocEx` an
   RW region for the mapped image somewhere unrelated to the il2cpp module range.
   Two reasons: the `0xdeadc0de` guard specifically distrusts starts inside
   GameAssembly/il2cpp, and any heuristic that scans "code near the game module"
   should find nothing.
2. **Map sections with WPM, apply base relocations, resolve imports** against the
   target's already-loaded modules (read its PEB module list via RPM to find
   export addresses). All of this is plain memory work ACE tolerates.
3. **Wipe the PE headers after mapping.** Zero the MZ/DOS stub, PE signature,
   and section table in the target copy. A module scan keys on the `MZ`/`PE\0\0`
   magic at an image-aligned, unbacked address; erasing it removes the cheapest
   signature. (Keep an unmapped copy in the controller for any later fixups.)
4. **Do not link into any loader list.** Manual mapping already skips
   `InLoadOrder`/`InMemoryOrder`/`InInitializationOrder`; the point is to *keep* it
   unlinked. `EnumProcessModules`/`Module32Next`/`LdrEnumerateLoadedModules` then
   never see it. (ACE in kernel can still walk VADs — see §6 — but it is no longer
   a *module*.)
5. **Set final section permissions tightly.** Make the code section RX, data RW —
   not one big RWX blob. A private RWX region of image size is itself a classic
   heuristic; splitting permissions per section makes the region look less like a
   staged payload.
6. **Trigger the entry point by thread hijack, never by a new thread.** Reuse the
   `hijack_call` machinery: gate to a parked thread at `SAFE_RIP`, redirect RIP to
   a small stub that calls the manually-mapped `DllMain(base, DLL_PROCESS_ATTACH,
   0)` (or a custom exported init), then returns the thread. This inherits the
   proven, connection-safe trigger and completely avoids `CreateRemoteThread` and
   the `0xdeadc0de` guard.
7. **Erase the bootstrap stub and any scratch allocations** once init returns, so
   the only thing left resident is the (headerless, unlinked, per-section-permed)
   image.

Net: the DLL exists as executable code but is **not a module** by any userland
enumeration, has **no on-disk footprint**, was **never loaded by a flagged
thread start**, and lives **away from the il2cpp range**. That is the maximum
stealth achievable from userland against this guard.

---

## 5. …but reconsider whether a DLL is needed at all

The strongest recommendation is to question the premise. Everything a DLL usually
buys is already available by cheaper, lower-detection means here:

- **Running arbitrary logic in-process:** the hijack shellcode path does this and
  is stable (il2cpp-invoke-stability §3). A payload built as position-independent
  shellcode needs no PE header, no relocations, no import resolution against the
  target, and therefore **no module footprint at all** — it is strictly less
  detectable than even a hardened manual map.
- **Calling game code:** `il2cpp_runtime_invoke`, gated to the attached main
  thread, already reaches C# methods. The `MethodInfo->methodPointer` shortcut is
  dead here (`addr_off: null`), but `runtime_invoke` is enough.
- **Issuing network commands:** the socket-duplication / userland-MITM relay paths
  send real frames without touching the game process's code at all.

A DLL only starts to pay for itself when the payload is large, needs a C/C++
runtime, links many imports, or wants persistent hooks with proper unwind/TLS
semantics — i.e. when writing it as flat PIC shellcode becomes impractical. Absent
that, **prefer PIC shellcode over any DLL**: same execution, strictly smaller
detection surface, and it reuses machinery that already works.

Guidance:
- Payload fits in a few KB of self-contained logic → **PIC shellcode via hijack**.
- Payload needs imports / CRT / hooks / is large → **hardened manual map (§4)**.
- Payload is "make the client run one command" → **no in-process code**; use the
  MITM relay / socket dup (command-injection-vectors).

---

## 6. Detection surfaces a DLL must still respect (why kernel ACE limits this)

ACE is Ring-0. Manual mapping defeats *userland* module enumeration, but a kernel
driver has strictly more visibility, and an honest theory note must state where
the ceiling is:

- **VAD / private-executable scan.** The kernel can walk the process's Virtual
  Address Descriptor tree and flag large **private** (non-image-backed) regions
  marked executable. A manually-mapped image is exactly that: executable memory
  with no backing file. Splitting permissions and keeping regions small reduces
  the signal but does not remove it. This is the single biggest residual risk and
  is **not measurable without risking the account** — flag as an open question,
  do not assume safe.
- **Thread start-address provenance.** Already observed: a thread whose start is
  unbacked/untrusted is killed (`0xdeadc0de`). Hijack avoids *creating* such a
  thread, but if ACE also samples the **current RIP** of existing threads (not
  just start addresses) it could catch a hijacked thread executing in an unbacked
  region. The hijack window is milliseconds and returns RIP to `SAFE_RIP`, which
  shrinks but does not eliminate this.
- **Integrity / periodic memory hash of game modules.** Leaving `GameAssembly.dll`
  and the game's own code untouched (which manual mapping does — it maps *our*
  image elsewhere) sidesteps code-integrity checks on the game itself. Do not
  inline-hook game functions; prefer calling them (invoke) over patching them.
- **Handle-table scan.** ACE granted `PROCESS_DUP_HANDLE`, but a kernel callback
  (`ObRegisterCallbacks`) could still strip or audit handles to the game process
  held by *other* processes. It has not on this build, but a controller holding a
  long-lived `PROCESS_VM_WRITE|VM_OPERATION` handle is a latent signal. Prefer
  short-lived handles opened per operation.

The takeaway: userland stealth (headerless, unlinked, off-module) is real and
worth doing, but **against a Ring-0 anti-cheat the residual detection surface is
in the kernel's VAD/thread/handle visibility, which we cannot fully hide from
userland and cannot safely probe.** That is the honest ceiling of this line of
work.

---

## 7. Open questions to settle before any live attempt (emulator first)

Per the standing rule, prove any of this on an **Android emulator + throwaway
account** first — the emulator has no ACE Ring-0 driver, so it validates the
*mechanics* (P1/P2 correctness) without account risk; only the PC port carries the
detection risk, and only the questions below decide whether it is worth taking.

1. **Does ACE VAD-scan for private executable regions?** The whole manual-map
   route lives or dies here and it is unmeasured. Cheapest signal: the existing
   hijack shellcode already creates a small RWX region and has *not* triggered a
   ban across many runs — so *small, short-lived* executable private memory is
   tolerated. An image-sized, *persistent* one is the untested case.
2. **Start-address guard vs. current-RIP guard.** Confirm whether the
   `0xdeadc0de` guard is purely on thread *creation* (hijack is then fully safe)
   or also samples running RIPs (hijack into an unbacked region becomes risky).
   Inferable by timing: a hijack that spends longer in the unbacked region.
3. **Is a wiped-header image enough, or does ACE reconstruct modules from VADs?**
   If ACE rebuilds a module list from memory layout rather than the PEB lists,
   header-wipe + unlink buys less than expected. Emulator-side, dump ACE's own
   telemetry reaction (it force-quits on Frida — see whether a headerless map
   provokes the same).
4. **Handle-callback audit.** Re-confirm on the current build that a long-lived
   VM_WRITE handle from a separate controller is not stripped/flagged over time
   (socket-duplication saw it granted at a point in time, not audited over
   minutes).

---

## 8. Recommendation

1. **Default: do not inject a DLL.** The proven, lowest-detection in-process path
   is **PIC shellcode via thread hijack** + `il2cpp_runtime_invoke`, and for
   network actions the **userland MITM / socket-dup** relay. These reuse machinery
   that already works and never create a module for ACE to find.
2. **If a DLL is unavoidable**, the only route consistent with this build's ACE
   model is a **hardened external manual map** (§4): allocate off the il2cpp
   range, map + relocate + resolve imports via WPM, **wipe headers**, **stay
   unlinked**, split section permissions, and **trigger the entry via thread
   hijack — never `CreateRemoteThread`** (its `0xdeadc0de` guard is precisely why
   a normal `LoadLibrary` inject fails here).
3. **Never** use: `CreateRemoteThread`+`LoadLibrary` into non-system code, on-disk
   DLLs, `SetWindowsHookEx`, Frida, kernel drivers on game traffic, or inline
   hooks of game code — each maps to a measured or reputationally-certain ACE ban
   vector.
4. **The ceiling is the kernel.** Userland manual-map stealth is genuine but the
   residual VAD/thread-RIP/handle visibility belongs to ACE's Ring-0 driver and
   cannot be hidden from or safely probed in userland. Treat §7's questions as
   gates, validate on emulator + throwaway account, and do not assume the PC port
   is safe because the emulator mechanic worked.

This is a capability/theory note, not a decision to act. It exists to record how
DLL injection maps onto this specific ACE build's measured behaviour, and to make
the case that the cheaper shellcode-via-hijack path already covers the in-process
need without opening a new detection surface.
