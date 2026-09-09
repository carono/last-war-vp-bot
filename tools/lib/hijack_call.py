r"""Thread-hijack remote call — bypass ACE's CreateRemoteThread start-guard.

ACE neuters threads that START in private memory or in GameAssembly (exit
0xdeadc0de); only starts in trusted system modules run. Thread hijacking creates
NO new thread: we suspend an existing game thread that is already past the guard,
point its RIP at our shellcode, let it run one call, and return it to its
original RIP. The thread continues as if nothing happened.

Safety measures:
  * Only hijack a SLEEPING thread — one whose RIP (after suspend) is inside
    ntdll (parked in a syscall wait), never one mid-computation in the engine.
  * Shellcode saves/restores every GP register + flags and jumps back to the
    exact original RIP.
  * Done-flag + delayed free so the thread has left our region before we free.
  * Recovery: on timeout, re-suspend and force the original context back.

First proven on kernel32!GetCurrentProcessId (no side effects, no XMM), then on
il2cpp_domain_get. Read-only calls — no game state changed.

Run under Windows Python:
    C:\Python312\python.exe tools\hijack_call.py
"""
from __future__ import annotations

import ctypes as C
import struct
import sys
import time
from ctypes import wintypes

sys.path.insert(0, "tools/lib")
import il2cpp_probe as P  # module_base, parse_exports, rpm, VM helpers, handles

k32 = C.WinDLL("kernel32", use_last_error=True)


def _decl(fn, restype, argtypes):
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


OpenThread = _decl(k32.OpenThread, wintypes.HANDLE,
                   [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD])
SuspendThread = _decl(k32.SuspendThread, wintypes.DWORD, [wintypes.HANDLE])
ResumeThread = _decl(k32.ResumeThread, wintypes.DWORD, [wintypes.HANDLE])
GetThreadContext = _decl(k32.GetThreadContext, wintypes.BOOL,
                         [wintypes.HANDLE, C.c_void_p])
SetThreadContext = _decl(k32.SetThreadContext, wintypes.BOOL,
                         [wintypes.HANDLE, C.c_void_p])

THREAD_ALL = 0x1FFFFF
CONTEXT_CONTROL = 0x00100001
CONTEXT_INTEGER = 0x00100002
CONTEXT_FULL = CONTEXT_CONTROL | CONTEXT_INTEGER

TH32CS_SNAPTHREAD = 0x00000004
CONTEXT_SIZE = 1232  # sizeof(CONTEXT) on x64


class THREADENTRY32(C.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


# CONTEXT field offsets we touch (x64)
OFF_FLAGS = 0x30
OFF_RSP = 0x98
OFF_RIP = 0xF8

# How often each of the three waits looks again.
#
# WHAT A CALL ACTUALLY COSTS, measured live (#1230, results in
# docs/research/game-call-latency.md): a chunk reaches the game's Lua VM in TWO hijacks
# (make the string, then invoke), and each one waits for the main thread to reach the
# safe park — which it does once a frame. The reaction of the game came out at 2.06x the
# client's own `Time.deltaTime` across a run of samples: 32 ms at 60 fps, 75 ms at 21.
# The frame is the floor, and nothing here can go under it.
#
# So PARK_POLL is deliberately NOT tightened. Sampling the park costs the game something
# — every sample suspends and resumes the render thread — and sampling it five times
# faster measured exactly the same 2.06 frames, because the wait is for the frame and
# not for us to look. The two flag waits are the opposite: they read a byte out of our
# own region with the game running freely, so they cost the game nothing and their old
# 10/20 ms granularity was pure sitting about.
#
# THAT REASONING WENT STALE AND CAME BACK TRUE, and both halves are worth keeping.
# §2.1 of `docs/research/link-contention.md` measured 22 samples per hijack — thirteen
# frames, not one — and concluded the wait WAS for us to look. It was, and the cause was
# on this side: a chunk paid THREE hijacks, so the panel suspended the client's main
# thread some sixty times a call and the thread never reached its idle message-pump wait.
# Two of the three are gone (`xlua_route.py::il2_string_pinned`, `::il2_bytes_reused`) and
# the samples are back to 1.7-2.1, which is the frame the paragraph above describes.
#
# So the rule stands as written — do not tighten PARK_POLL — and the way to tell whether
# it has gone stale again is the `park tries each` figure in the per-minute line, not an
# argument about it.
#
# AND DO NOT LOOSEN IT EITHER (#2667). «Sample less often» is the obvious answer to a
# million suspensions of the client's main thread a day, and it was measured on the live
# client rather than argued: 12 s at each rate, same thread, same session —
#
#   gap 10 ms: 1 147 samples, park hit 1.6 %, 64 samples to a hit, 0.64 s to a hit
#   gap 20 ms:   588 samples, park hit 1.9 %, 54 samples to a hit, 1.07 s to a hit
#   gap 40 ms:   297 samples, park hit 2.0 %, 50 samples to a hit, 2.0  s to a hit
#   gap 80 ms:   150 samples, park hit 4.0 %, 25 samples to a hit, 2.0  s to a hit
#
# The hit rate does rise as we look less often, but sublinearly: eight times slower buys
# 2.5x fewer suspensions and costs 3x the wait. The panel already spends ~30 % of its
# wall clock in this wait (18 769 s of park over 765 logged minutes, live), so paying it
# three times over is a slower panel all day — and «the player must not notice» is the
# condition the whole optimisation runs under. The lever that works is FEWER HIJACKS,
# not slower sampling: 89 % of them are one `DoString(bytes)` per Lua chunk.
#
# The call wait starts tight and backs off: a managed call that returns in a millisecond
# should not be found 20 ms later, and one that runs for eight seconds should not be
# polled five thousand times to find that out.
PARK_POLL = 0.01
START_POLL = 0.001
CALL_POLL_FAST, CALL_POLL_SLOW, CALL_FAST_FOR = 0.001, 0.02, 0.1

#: WHERE THE SECONDS OF A HIJACK GO (#2404). Cumulative, never reset; a reader takes two
#: snapshots and subtracts.
#:
#: The chain is supposed to cost two frames — 2.06x the client's own `deltaTime`, measured
#: in #1230 — which is about 34 ms at 60 fps, and three of those per chunk is a tenth of a
#: second. Live it is 0.5–1.2 s (`docs/research/link-contention.md`), against a client
#: reporting 60 fps and a 3 ms frame, and the whole panel is rationed by it: the injection
#: lock is busy 72–100 % of every minute. Five to ten times the theory is not a thing to
#: reason about, so each phase counts itself:
#:
#: * **park** — sampling the target thread until its RIP is at the safe park. Each sample
#:   suspends and resumes the game's main thread, so this is the phase that can cost the
#:   CLIENT something as well as us;
#: * **start** — from redirecting RIP to the shellcode raising its `started` byte;
#: * **call** — the managed call itself, in flight on the runtime;
#: * **free** — waiting for RIP to leave the RWX region so it can be released.
STATS = {"n": 0, "park_sec": 0.0, "park_tries": 0, "start_sec": 0.0,
         "call_sec": 0.0, "free_sec": 0.0, "misses": 0, "abandoned": 0,
         "by_label": {}}

#: HOW MANY DISTINCT LABELS THE TALLY WILL HOLD (#2656). A label is written by the
#: caller, and a caller that builds one per item (`dom.main0`, `dom.main1`, …) would
#: otherwise grow this map without bound in a process that runs for days. Everything past
#: the cap is added up under one name, so the total still adds up to `n`.
LABEL_CAP = 64
OTHER_LABEL = "…other"


def _count(label: str) -> None:
    """One more hijack under this label — the per-caller half of :data:`STATS`.

    WHY PER LABEL (#2656). The whole tally said 110 hijacks a minute and ~3.8 per DSL
    step, which is the size of the exposure but not its address: «one call costs 3.8
    attaches» is not something to fix until it is known WHICH call. The label is already
    carried through the hijack for its log lines, so counting by it is free.
    """
    # A label is free text and several of them have a space in them («LuaEnv cls»,
    # «dom.main0»). The minute's line is read back as `name=count` pairs, so a space
    # would hand the reader half a name and file 3 hijacks under «cls» — measured live
    # the first minute this shipped. The separator wins; the label is collapsed.
    label = "_".join(str(label).split()) or "?"
    by = STATS["by_label"]
    if label not in by and len(by) >= LABEL_CAP:
        label = OTHER_LABEL
    by[label] = by.get(label, 0) + 1


def stats() -> dict:
    """A copy of :data:`STATS`, for whoever is drawing or logging it.

    The per-label map is copied too: a reader takes two snapshots and subtracts, and a
    shared dict would leave it subtracting a map from itself.
    """
    out = dict(STATS)
    out["by_label"] = dict(STATS["by_label"])
    return out


def _aligned_context():
    """Return (buffer, base_addr) for a 16-aligned CONTEXT."""
    raw = (C.c_char * (CONTEXT_SIZE + 16))()
    addr = C.addressof(raw)
    aligned = (addr + 15) & ~15
    return raw, aligned


def list_threads(pid: int) -> list[int]:
    CreateToolhelp32Snapshot = _decl(k32.CreateToolhelp32Snapshot,
                                     wintypes.HANDLE, [wintypes.DWORD, wintypes.DWORD])
    Thread32First = _decl(k32.Thread32First, wintypes.BOOL,
                          [wintypes.HANDLE, C.POINTER(THREADENTRY32)])
    Thread32Next = _decl(k32.Thread32Next, wintypes.BOOL,
                         [wintypes.HANDLE, C.POINTER(THREADENTRY32)])
    snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    te = THREADENTRY32()
    te.dwSize = C.sizeof(te)
    out = []
    ok = Thread32First(snap, C.byref(te))
    while ok:
        if te.th32OwnerProcessID == pid:
            out.append(te.th32ThreadID)
        ok = Thread32Next(snap, C.byref(te))
    P.CloseHandle(snap)
    return out


def build_shellcode(func: int, args: list[int], result_abs: int,
                    flag_abs: int, started_abs: int, orig_rip: int) -> bytes:
    a = (args + [0, 0, 0, 0])[:4]
    return b"".join([
        b"\x50\x51\x52\x53\x55\x56\x57",                       # push rax rcx rdx rbx rbp rsi rdi
        b"\x41\x50\x41\x51\x41\x52\x41\x53\x41\x54\x41\x55\x41\x56\x41\x57",  # push r8..r15
        b"\x9C",                                               # pushfq
        b"\x48\x89\xE3",                                       # mov rbx, rsp
        b"\x48\x83\xE4\xF0",                                   # and rsp, -16
        b"\x48\x83\xEC\x20",                                   # sub rsp, 0x20 (shadow)
        b"\x48\xB8" + struct.pack("<Q", started_abs),          # mov rax, started_abs
        b"\xC6\x00\x01",                                       # mov byte [rax], 1  (about to call)
        b"\x48\xB9" + struct.pack("<Q", a[0]),                 # mov rcx, arg1
        b"\x48\xBA" + struct.pack("<Q", a[1]),                 # mov rdx, arg2
        b"\x49\xB8" + struct.pack("<Q", a[2]),                 # mov r8,  arg3
        b"\x49\xB9" + struct.pack("<Q", a[3]),                 # mov r9,  arg4
        b"\x48\xB8" + struct.pack("<Q", func),                 # mov rax, func
        b"\xFF\xD0",                                           # call rax
        b"\x48\xB9" + struct.pack("<Q", result_abs),           # mov rcx, result_abs
        b"\x48\x89\x01",                                       # mov [rcx], rax
        b"\x48\x89\xDC",                                       # mov rsp, rbx
        b"\x9D",                                               # popfq
        b"\x41\x5F\x41\x5E\x41\x5D\x41\x5C\x41\x5B\x41\x5A\x41\x59\x41\x58",  # pop r15..r8
        b"\x5F\x5E\x5D\x5B\x5A\x59\x58",                       # pop rdi rsi rbp rbx rdx rcx rax
        b"\x51",                                               # push rcx
        b"\x48\xB9" + struct.pack("<Q", flag_abs),             # mov rcx, flag_abs
        b"\xC6\x01\x01",                                       # mov byte [rcx], 1
        b"\x59",                                               # pop rcx
        b"\x50",                                               # push rax
        b"\x48\xB8" + struct.pack("<Q", orig_rip),             # mov rax, orig_rip
        b"\x48\x87\x04\x24",                                   # xchg rax, [rsp]
        b"\xC3",                                               # ret -> jmp orig_rip
    ])


def build_shellcode_xmm(func: int, args: list[int], result_abs: int,
                        flag_abs: int, started_abs: int, orig_rip: int) -> bytes:
    """Same as build_shellcode but also preserves XMM0-5 across the call.

    Needed when calling engine functions that pass/return floats or vectors
    (e.g. il2cpp_runtime_invoke into methods with float args). The 6 xmm regs
    are spilled into a 16-aligned 0x60 block right below the shadow space and
    restored before rsp is rolled back to the saved value.
    """
    a = (args + [0, 0, 0, 0])[:4]
    return b"".join([
        b"\x50\x51\x52\x53\x55\x56\x57",                       # push rax rcx rdx rbx rbp rsi rdi
        b"\x41\x50\x41\x51\x41\x52\x41\x53\x41\x54\x41\x55\x41\x56\x41\x57",  # push r8..r15
        b"\x9C",                                               # pushfq
        b"\x48\x89\xE3",                                       # mov rbx, rsp
        b"\x48\x83\xE4\xF0",                                   # and rsp, -16
        b"\x48\x83\xEC\x60",                                   # sub rsp, 0x60 (xmm save)
        b"\x0F\x29\x04\x24",                                   # movaps [rsp+0x00], xmm0
        b"\x0F\x29\x4C\x24\x10",                               # movaps [rsp+0x10], xmm1
        b"\x0F\x29\x54\x24\x20",                               # movaps [rsp+0x20], xmm2
        b"\x0F\x29\x5C\x24\x30",                               # movaps [rsp+0x30], xmm3
        b"\x0F\x29\x64\x24\x40",                               # movaps [rsp+0x40], xmm4
        b"\x0F\x29\x6C\x24\x50",                               # movaps [rsp+0x50], xmm5
        b"\x48\x83\xEC\x20",                                   # sub rsp, 0x20 (shadow)
        b"\x48\xB8" + struct.pack("<Q", started_abs),          # mov rax, started_abs
        b"\xC6\x00\x01",                                       # mov byte [rax], 1  (about to call)
        b"\x48\xB9" + struct.pack("<Q", a[0]),                 # mov rcx, arg1
        b"\x48\xBA" + struct.pack("<Q", a[1]),                 # mov rdx, arg2
        b"\x49\xB8" + struct.pack("<Q", a[2]),                 # mov r8,  arg3
        b"\x49\xB9" + struct.pack("<Q", a[3]),                 # mov r9,  arg4
        b"\x48\xB8" + struct.pack("<Q", func),                 # mov rax, func
        b"\xFF\xD0",                                           # call rax
        b"\x48\xB9" + struct.pack("<Q", result_abs),           # mov rcx, result_abs
        b"\x48\x89\x01",                                       # mov [rcx], rax
        b"\x48\x83\xC4\x20",                                   # add rsp, 0x20 (drop shadow)
        b"\x0F\x28\x04\x24",                                   # movaps xmm0, [rsp+0x00]
        b"\x0F\x28\x4C\x24\x10",                               # movaps xmm1, [rsp+0x10]
        b"\x0F\x28\x54\x24\x20",                               # movaps xmm2, [rsp+0x20]
        b"\x0F\x28\x5C\x24\x30",                               # movaps xmm3, [rsp+0x30]
        b"\x0F\x28\x64\x24\x40",                               # movaps xmm4, [rsp+0x40]
        b"\x0F\x28\x6C\x24\x50",                               # movaps xmm5, [rsp+0x50]
        b"\x48\x89\xDC",                                       # mov rsp, rbx
        b"\x9D",                                               # popfq
        b"\x41\x5F\x41\x5E\x41\x5D\x41\x5C\x41\x5B\x41\x5A\x41\x59\x41\x58",  # pop r15..r8
        b"\x5F\x5E\x5D\x5B\x5A\x59\x58",                       # pop rdi rsi rbp rbx rdx rcx rax
        b"\x51",                                               # push rcx
        b"\x48\xB9" + struct.pack("<Q", flag_abs),             # mov rcx, flag_abs
        b"\xC6\x01\x01",                                       # mov byte [rcx], 1
        b"\x59",                                               # pop rcx
        b"\x50",                                               # push rax
        b"\x48\xB8" + struct.pack("<Q", orig_rip),             # mov rax, orig_rip
        b"\x48\x87\x04\x24",                                   # xchg rax, [rsp]
        b"\xC3",                                               # ret -> jmp orig_rip
    ])


def _thread_rip(hthr) -> int | None:
    """Suspend-read RIP of an already-suspended thread's context (no resume)."""
    raw, cbase = _aligned_context()
    off = cbase - C.addressof(raw)
    struct.pack_into("<I", raw, off + OFF_FLAGS, CONTEXT_FULL)
    if not GetThreadContext(hthr, cbase):
        return None
    return struct.unpack_from("<Q", raw, off + OFF_RIP)[0]


def hijack_call(hproc, pid: int, func: int, args: list[int], label: str,
                save_xmm: bool = False, only_tid: int | None = None,
                safe_rip: int | None = None, rip_tol: int = 16,
                park_timeout: float = 2.0, start_timeout: float = 0.6,
                call_timeout: float = 8.0, extend_timeout: float = 8.0) -> int | None:
    """Run func(args) by hijacking a game thread parked in ntdll.

    only_tid: if given, hijack ONLY that thread (retrying until it parks in
    ntdll). Use the Unity main/UI thread for managed-code calls
    (runtime_invoke / class_init): running managed code on a random native
    worker that is not GC-registered corrupts the runtime and crashes the game.

    safe_rip: if given (an absolute address, see rip_gate.learn_safe_rip), the
    thread is only hijacked when its RIP is within +-rip_tol of that exact
    parked-in-a-syscall-wait address. "Anywhere in ntdll" is too loose — the
    main thread also passes through ntdll heap locks, APC dispatch and ACE's
    private RWX stubs; borrowing it there can wedge the runtime. SAFE_RIP is the
    single dominant return address of the idle message-pump wait: at that spot
    the thread is provably about to sleep, the safest instant to take it.

    park_timeout: wall-clock seconds to keep re-sampling for the safe park
    before giving up cleanly (returns None; never wedges). Only used with
    only_tid.

    Stability model (why this does not wedge il2cpp). The shellcode raises a
    `started` byte the instant before it executes `call func`, and a `done` byte
    the instant after it returns. Two independent timeouts key off those:

      * start_timeout — how long we wait for `started` to flip. A thread parked
        in a long/indefinite kernel wait (a worker blocked on a semaphore) never
        returns to user mode when we redirect its RIP, so our shellcode never
        runs and `started` stays 0. That is BENIGN: the call has not begun, so we
        cleanly restore the thread's RIP and (without only_tid) try the next
        candidate. This is the fix for "il2cpp_domain_get times out on a random
        parked thread".
      * call_timeout / extend_timeout — once `started` is up the managed call is
        genuinely in flight ON the runtime. We NEVER force its RIP back here:
        yanking a thread out of the middle of il2cpp (holding GC/loader locks,
        mid-allocation) is exactly what wedged the runtime and crashed the game.
        We wait call_timeout, then extend_timeout more, and if it still has not
        returned we leave the thread running untouched and LEAK the RWX region
        (freeing it while RIP is inside would fault the thread). A slow call that
        used to be aborted at 4s now completes cleanly.

    The RWX region is only freed once we have confirmed RIP is outside it.
    """
    if not func:
        # A null target is dereferenced deep inside the callee and crashes the
        # game. Callers must resolve the address first; never hijack into 0.
        raise ValueError(f"[{label}] refusing to hijack-call a null func pointer")

    ntbase, ntsize = P.module_base(pid, "ntdll.dll")
    nt_lo, nt_hi = ntbase, ntbase + ntsize

    def _parked(rip: int) -> bool:
        if safe_rip is not None:
            return abs(rip - safe_rip) <= rip_tol
        return nt_lo <= rip < nt_hi

    # ONE REGION PER ATTEMPT, AND NEVER A SECOND THREAD IN IT (#2665). It used to be
    # one region for the whole call, rewritten with a fresh `orig_rip` for each candidate
    # thread and freed at the end whatever had happened. Both halves of that can kill the
    # client, and the second one is written in the crash dumps:
    #
    #   * REWRITTEN — a thread abandoned as «never started» that then does wake up runs
    #     the shellcode built for the NEXT candidate and returns to THAT thread's parked
    #     address, i.e. jumps into unrelated code;
    #   * FREED — the same thread wakes at `code_abs` in memory that is no longer mapped.
    #     On 2026-09-09 two of the client's six minidumps have RIP exactly at a
    #     64K-aligned private address + 0x40, which is this layout's entry point and
    #     nothing else in the process.
    #
    # So a region belongs to ONE thread for ever: a candidate that is abandoned keeps its
    # own, with the shellcode replaced by a stub that goes straight home, and the region
    # is leaked rather than freed. A leak is 64 KB of address space in a 64-bit process,
    # counted in :data:`STATS` so it stays measurable; a free is a dead client.
    def _new_region() -> tuple:
        base = P.VirtualAllocEx(hproc, None, 0x400, 0x3000, 0x40)  # RWX
        if not base:
            raise OSError(f"alloc failed err={C.get_last_error()}")
        base = int(base)
        return base, base, base + 8, base + 9, base + 0x40

    region, result_abs, flag_abs, started_abs, code_abs = _new_region()
    #: True once a thread's RIP has been pointed at the live region. Such a region is
    #: never reused and never freed by the miss path below.
    aimed = False

    def _byte(addr: int) -> int:
        b = P.rpm(hproc, addr, 1)
        return b[0] if b else 0

    def _in_region(rip: int | None) -> bool:
        return rip is not None and region <= rip < region + 0x400

    def _go_home(orig_rip: int) -> bytes:
        """`jmp orig_rip`, clobbering nothing — the shellcode's own tail, alone."""
        return b"".join([
            b"\x50",                                            # push rax
            b"\x48\xB8" + struct.pack("<Q", orig_rip),           # mov rax, orig_rip
            b"\x48\x87\x04\x24",                               # xchg rax, [rsp]
            b"\xC3",                                            # ret -> jmp orig_rip
        ])

    def _abandon(code: int, orig_rip: int) -> None:
        """Leave a region to a thread that may still wake up in it, and let it go."""
        stub = _go_home(orig_rip)
        P.WriteProcessMemory(hproc, C.c_void_p(code), stub, len(stub),
                             C.byref(C.c_size_t(0)))
        STATS["abandoned"] += 1

    def _free_region_when_clear(hthr) -> None:
        """Free the RWX region only after RIP has left it (else a running thread
        would fault). Give it up to ~1.5s; fall back to a leak, never a fault."""
        deadline = time.time() + 1.5
        while time.time() < deadline:
            if SuspendThread(hthr) != 0xFFFFFFFF:
                rip = _thread_rip(hthr)
                ResumeThread(hthr)
                if not _in_region(rip):
                    P.VirtualFreeEx(hproc, C.c_void_p(region), 0, 0x8000)
                    return
            time.sleep(PARK_POLL)
        print(f"[{label}] WARN: RIP still inside shellcode region — leaking it "
              f"(cannot free safely)")

    builder = build_shellcode_xmm if save_xmm else build_shellcode

    def _run_on(tid: int, hthr, raw, cbase, off, orig_rip) -> tuple[bool, int | None]:
        """Redirect an already-suspended, parked thread into the shellcode and
        drive it. Returns (handled, result). handled=False means the thread
        never ran our code (not_started) — caller should try another thread;
        the thread is cleanly restored and the handle closed here. handled=True
        means we owned the outcome (done or wedged) and freed/leaked as needed."""
        gate = f" SAFE_RIP+0x{orig_rip - safe_rip:x}" if safe_rip is not None else ""
        # fresh markers + shellcode baked with THIS thread's return address
        P.WriteProcessMemory(hproc, C.c_void_p(region), b"\x00" * 0x40, 0x40,
                             C.byref(C.c_size_t(0)))
        sc = builder(func, args, result_abs, flag_abs, started_abs, orig_rip)
        P.WriteProcessMemory(hproc, C.c_void_p(code_abs), sc, len(sc),
                             C.byref(C.c_size_t(0)))
        struct.pack_into("<Q", raw, off + OFF_RIP, code_abs)
        struct.pack_into("<I", raw, off + OFF_FLAGS, CONTEXT_FULL)
        if not SetThreadContext(hthr, cbase):
            ResumeThread(hthr)
            P.CloseHandle(hthr)
            raise OSError(f"SetThreadContext failed err={C.get_last_error()}")
        ResumeThread(hthr)

        # phase 1: wait for the call to actually START (or finish outright)
        phase_began = time.time()
        sdl = time.time() + start_timeout
        while time.time() < sdl:
            if _byte(flag_abs) == 1:
                break
            if _byte(started_abs) == 1:
                break
            time.sleep(START_POLL)

        STATS["start_sec"] += max(0.0, time.time() - phase_began)
        phase_began = time.time()
        started, done = _byte(started_abs), _byte(flag_abs)
        if not started and not done:
            # thread never returned to user mode to run our code — restore & pass
            if SuspendThread(hthr) != 0xFFFFFFFF:
                # re-check: it may have started in the tiny race window
                started, done = _byte(started_abs), _byte(flag_abs)
                # …AND THE FLAGS ARE NOT THE WHOLE ANSWER (#2665). `started` is raised
                # some twenty instructions in — after seventeen pushes and `pushfq`. A
                # thread suspended in that gap has our prologue on its stack and a flag
                # still saying nothing began; putting its RIP back there returns it into
                # the parked function with RSP 0x88 too low, and it dies later somewhere
                # in the engine with nothing of ours in the picture. So the thread's own
                # RIP decides: inside the region means it is running our code, whatever
                # the flags say, and it is then handled by phase 2 like any other call.
                inside = _in_region(_thread_rip(hthr))
                if not started and not done and not inside:
                    struct.pack_into("<Q", raw, off + OFF_RIP, orig_rip)
                    struct.pack_into("<I", raw, off + OFF_FLAGS, CONTEXT_FULL)
                    SetThreadContext(hthr, cbase)
                    ResumeThread(hthr)
                    P.CloseHandle(hthr)
                    # The restore may not take: a thread parked in the kernel can come
                    # back on the trap frame it went in with, i.e. at `code_abs`. The
                    # region is therefore NOT freed and NOT reused — it keeps a stub that
                    # sends such a thread straight home.
                    _abandon(code_abs, orig_rip)
                    return False, None
                ResumeThread(hthr)

        # phase 2: the call is in flight (or already done) — NEVER yank it now
        print(f"[{label}] hijacking tid={tid}, orig RIP=0x{orig_rip:x} "
              f"(in ntdll{gate})")
        cdl = time.time() + call_timeout
        fast_until = time.time() + CALL_FAST_FOR
        while time.time() < cdl:
            if _byte(flag_abs) == 1:
                done = 1
                break
            time.sleep(CALL_POLL_FAST if time.time() < fast_until else CALL_POLL_SLOW)
        if not done:
            print(f"[{label}] slow call — extending wait {extend_timeout:.0f}s "
                  f"(NOT restoring RIP: would wedge the runtime)")
            edl = time.time() + extend_timeout
            while time.time() < edl:
                if _byte(flag_abs) == 1:
                    done = 1
                    break
                time.sleep(0.05)

        STATS["call_sec"] += max(0.0, time.time() - phase_began)
        if done:
            result = struct.unpack("<Q", P.rpm(hproc, result_abs, 8))[0]
            print(f"[{label}] done, result=0x{result:x}")
            freeing = time.time()
            _free_region_when_clear(hthr)
            STATS["free_sec"] += max(0.0, time.time() - freeing)
            P.CloseHandle(hthr)
            return True, result

        # genuinely wedged: leave the thread alone, leak the region (safe), report
        print(f"[{label}] WEDGE — call never returned in "
              f"{call_timeout + extend_timeout:.0f}s; leaving thread untouched "
              f"and leaking region (NOT force-restoring — that crashes il2cpp)")
        P.CloseHandle(hthr)
        return True, None

    park_began = time.time()
    park_deadline = time.time() + park_timeout
    # the "any parked thread" sweep pays start_timeout for each non-responsive
    # thread, so give it a wider overall budget than the tight only_tid re-park.
    sweep_give_up = time.time() + (park_timeout if only_tid else max(park_timeout, 12.0))
    seen_rip = None
    tried_this_pass = False
    while True:
        for tid in ([only_tid] if only_tid else list_threads(pid)):
            if not only_tid and time.time() >= sweep_give_up:
                break
            STATS["park_tries"] += 1
            hthr = OpenThread(THREAD_ALL, False, tid)
            if not hthr:
                continue
            if SuspendThread(hthr) == 0xFFFFFFFF:
                P.CloseHandle(hthr)
                continue
            raw, cbase = _aligned_context()
            struct.pack_into("<I", raw, (cbase - C.addressof(raw)) + OFF_FLAGS, CONTEXT_FULL)
            if not GetThreadContext(hthr, cbase):
                ResumeThread(hthr)
                P.CloseHandle(hthr)
                continue
            off = cbase - C.addressof(raw)
            rip = struct.unpack_from("<Q", raw, off + OFF_RIP)[0]
            seen_rip = rip
            if not _parked(rip):
                ResumeThread(hthr)
                P.CloseHandle(hthr)
                continue
            tried_this_pass = True
            STATS["n"] += 1
            _count(label)
            STATS["park_sec"] += max(0.0, time.time() - park_began)
            aimed = True
            handled, result = _run_on(tid, hthr, raw, cbase, off, rip)
            if handled:
                return result
            # not_started: this thread won't run our code — try the next one, in a
            # region of its own. The abandoned one belongs to the thread that was
            # pointed at it for as long as the client lives (#2665).
            region, result_abs, flag_abs, started_abs, code_abs = _new_region()
            aimed = False

        if only_tid and time.time() < park_deadline:
            time.sleep(PARK_POLL)  # let the target thread reach the safe park
            continue
        if not only_tid and tried_this_pass:
            # some threads were parked but none ran our code; one more sweep
            tried_this_pass = False
            if time.time() < park_deadline:
                continue
        break

    if not aimed:
        # Nothing was ever pointed at this one, so it is ours to release.
        P.VirtualFreeEx(hproc, C.c_void_p(region), 0, 0x8000)
    STATS["misses"] += 1
    _count(label)
    STATS["park_sec"] += max(0.0, time.time() - park_began)
    who = f"tid={only_tid}" if only_tid else "any parked thread"
    target = (f"SAFE_RIP 0x{safe_rip:x}+-{rip_tol}" if safe_rip is not None
              else "ntdll")
    extra = f" (last RIP seen 0x{seen_rip:x})" if seen_rip else ""
    print(f"[{label}] {who} never ran our shellcode at {target}{extra} — "
          f"aborting (safe, nothing wedged)")
    return None


def _plausible_ptr(x: int | None) -> bool:
    return bool(x) and 0x10000 < x < 0x7FFFFFFFFFFF


def main() -> int:
    """Stability harness for the hijack-call mechanism (all read-only targets).

    Escalation, each step gated on the previous:
      1. kernel32!GetCurrentProcessId — proves the hijack round-trips at all.
      2. il2cpp_domain_get x N via the "any parked thread" sweep — proves the
         thread-selection fix: unresponsive parked workers are skipped instead
         of timing out, so a stateless il2cpp export returns reliably.
      3. il2cpp_domain_get x N gated to the Unity main thread — the path real
         managed calls use; proves repeated calls on the main thread stay stable
         and the game survives every one.
    """
    reps = 5
    for a in sys.argv[1:]:
        if a.startswith("--reps="):
            reps = int(a.split("=", 1)[1])

    pid = P.find_game_pid()
    print(f"[hijack] LastWar.exe pid={pid}")
    hproc = P.OpenProcess(0x1FFFFF, False, pid)
    if not hproc:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")
    try:
        import psutil
        alive = lambda: psutil.pid_exists(pid)

        kbase, _ = P.module_base(pid, "kernel32.dll")
        gcpi = P.parse_exports(hproc, kbase)["GetCurrentProcessId"]
        print(f"[hijack] SELF-TEST GetCurrentProcessId @0x{gcpi:x} (expect {pid})")
        r = hijack_call(hproc, pid, gcpi, [], "selftest")
        if r is None or (r & 0xFFFFFFFF) != pid:
            print(f"[hijack] self-test FAILED got={r} — stop")
            return 1
        print("[hijack] SELF-TEST OK\n")

        gbase, _ = P.module_base(pid, "GameAssembly.dll")
        dom = P.parse_exports(hproc, gbase)["il2cpp_domain_get"]

        # -- step 2: any-thread sweep, repeated ----------------------------
        # NOTE: il2cpp_domain_get reads the CURRENT domain from thread-local
        # state, which is only set on runtime-ATTACHED threads. A random parked
        # worker runs our shellcode fine (no wedge, game stays alive) but returns
        # 0 because it is not attached. So a nonzero here means we happened to
        # borrow an attached thread; a zero is expected, not a failure. Either
        # way the game must survive — that is what this step proves. The lesson:
        # route real il2cpp/managed calls through the main thread (step 3).
        print(f"[hijack] il2cpp_domain_get x{reps} via any-parked-thread sweep …")
        ok_sweep = 0
        for i in range(reps):
            d = hijack_call(hproc, pid, dom, [], f"dom.sweep{i}")
            if _plausible_ptr(d):
                ok_sweep += 1
            if not alive():
                print("!! game died during sweep test")
                return 1
        print(f"[hijack] sweep: {ok_sweep}/{reps} borrowed an attached thread, "
              f"game alive={alive()} (zeros are non-attached threads, expected)\n")

        # -- step 3: gated to the Unity main thread, repeated --------------
        try:
            import rip_gate as R
            mt = R.main_thread_tid(pid)
        except Exception as ex:
            print(f"[hijack] (skip main-thread gate: {ex})")
            mt = None
        ok_main = 0
        if mt:
            print(f"[hijack] il2cpp_domain_get x{reps} on main thread tid={mt} …")
            for i in range(reps):
                d = hijack_call(hproc, pid, dom, [], f"dom.main{i}", only_tid=mt)
                if _plausible_ptr(d):
                    ok_main += 1
                if not alive():
                    print("!! game died during main-thread test")
                    return 1
            print(f"[hijack] main-thread: {ok_main}/{reps} valid, "
                  f"game alive={alive()}\n")

        # The stability verdict is the MAIN-THREAD path: every gated call must
        # return the real domain and the game must survive all of them. The
        # sweep is diagnostic (it only has to keep the game alive).
        main_ok = (ok_main == reps) if mt else (ok_sweep >= 1)
        if main_ok and alive():
            print("[hijack] STABLE — in-process il2cpp calls on the main thread "
                  "are reliable and repeatable, no wedge/crash across the run.")
            return 0
        print(f"[hijack] NOT fully stable (sweep {ok_sweep}/{reps}, "
              f"main {ok_main}/{reps}, alive={alive()})")
        return 1
    finally:
        P.CloseHandle(hproc)


if __name__ == "__main__":
    sys.exit(main())
