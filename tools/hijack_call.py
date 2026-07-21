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

sys.path.insert(0, "tools")
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
                    flag_abs: int, orig_rip: int) -> bytes:
    a = (args + [0, 0, 0, 0])[:4]
    return b"".join([
        b"\x50\x51\x52\x53\x55\x56\x57",                       # push rax rcx rdx rbx rbp rsi rdi
        b"\x41\x50\x41\x51\x41\x52\x41\x53\x41\x54\x41\x55\x41\x56\x41\x57",  # push r8..r15
        b"\x9C",                                               # pushfq
        b"\x48\x89\xE3",                                       # mov rbx, rsp
        b"\x48\x83\xE4\xF0",                                   # and rsp, -16
        b"\x48\x83\xEC\x20",                                   # sub rsp, 0x20 (shadow)
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
                        flag_abs: int, orig_rip: int) -> bytes:
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


def hijack_call(hproc, pid: int, func: int, args: list[int], label: str,
                save_xmm: bool = False) -> int | None:
    ntbase, ntsize = P.module_base(pid, "ntdll.dll")
    nt_lo, nt_hi = ntbase, ntbase + ntsize

    region = P.VirtualAllocEx(hproc, None, 0x400, 0x3000, 0x40)  # RWX
    if not region:
        raise OSError(f"alloc failed err={C.get_last_error()}")
    region = int(region)
    result_abs, flag_abs, code_abs = region, region + 8, region + 0x40

    # zero result+flag
    P.WriteProcessMemory(hproc, C.c_void_p(region), b"\x00" * 0x40,
                         0x40, C.byref(C.c_size_t(0)))

    chosen = None
    for tid in list_threads(pid):
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
        if nt_lo <= rip < nt_hi:
            chosen = (tid, hthr, raw, cbase, off, rip)
            break
        ResumeThread(hthr)
        P.CloseHandle(hthr)

    if not chosen:
        P.VirtualFreeEx(hproc, C.c_void_p(region), 0, 0x8000)
        print(f"[{label}] no sleeping thread parked in ntdll found — aborting (safe)")
        return None

    tid, hthr, raw, cbase, off, orig_rip = chosen
    print(f"[{label}] hijacking tid={tid}, orig RIP=0x{orig_rip:x} (in ntdll)")

    builder = build_shellcode_xmm if save_xmm else build_shellcode
    sc = builder(func, args, result_abs, flag_abs, orig_rip)
    P.WriteProcessMemory(hproc, C.c_void_p(code_abs), sc, len(sc), C.byref(C.c_size_t(0)))

    # redirect RIP to shellcode, keep every other register as-is
    struct.pack_into("<Q", raw, off + OFF_RIP, code_abs)
    struct.pack_into("<I", raw, off + OFF_FLAGS, CONTEXT_FULL)
    if not SetThreadContext(hthr, cbase):
        ResumeThread(hthr)
        P.CloseHandle(hthr)
        P.VirtualFreeEx(hproc, C.c_void_p(region), 0, 0x8000)
        raise OSError(f"SetThreadContext failed err={C.get_last_error()}")

    ResumeThread(hthr)

    # wait for done flag
    done = False
    deadline = time.time() + 4.0
    while time.time() < deadline:
        flag = P.rpm(hproc, flag_abs, 1)
        if flag and flag[0] == 1:
            done = True
            break
        time.sleep(0.02)

    result = None
    if done:
        result = struct.unpack("<Q", P.rpm(hproc, result_abs, 8))[0]
        print(f"[{label}] done, result=0x{result:x}")
    else:
        # recovery: force the original context back (RIP restored to orig)
        print(f"[{label}] TIMEOUT — recovering thread to original RIP")
        SuspendThread(hthr)
        raw2, cbase2 = _aligned_context()
        off2 = cbase2 - C.addressof(raw2)
        C.memmove(cbase2, C.addressof(raw) + off, CONTEXT_SIZE)  # copy captured ctx
        struct.pack_into("<Q", raw2, off2 + OFF_RIP, orig_rip)
        struct.pack_into("<I", raw2, off2 + OFF_FLAGS, CONTEXT_FULL)
        SetThreadContext(hthr, cbase2)
        ResumeThread(hthr)

    # let the thread leave our region before freeing
    time.sleep(0.5)
    P.CloseHandle(hthr)
    P.VirtualFreeEx(hproc, C.c_void_p(region), 0, 0x8000)
    return result


def main() -> int:
    pid = P.find_game_pid()
    print(f"[hijack] LastWar.exe pid={pid}")
    hproc = P.OpenProcess(0x1FFFFF, False, pid)
    if not hproc:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")
    try:
        kbase, _ = P.module_base(pid, "kernel32.dll")
        gcpi = P.parse_exports(hproc, kbase)["GetCurrentProcessId"]
        print(f"[hijack] SELF-TEST GetCurrentProcessId @0x{gcpi:x} (expect {pid})")
        r = hijack_call(hproc, pid, gcpi, [], "selftest")
        if r is None:
            return 1
        if (r & 0xFFFFFFFF) != pid:
            print(f"[hijack] self-test MISMATCH got={r & 0xFFFFFFFF} — NOT escalating")
            return 1
        print("[hijack] SELF-TEST OK — hijack mechanism works, thread returned")

        gbase, _ = P.module_base(pid, "GameAssembly.dll")
        dom = P.parse_exports(hproc, gbase)["il2cpp_domain_get"]
        print(f"[hijack] il2cpp_domain_get @0x{dom:x} via hijack …")
        d = hijack_call(hproc, pid, dom, [], "domain")
        if d and 0x10000 < d < 0x7FFFFFFFFFFF:
            print(f"[hijack] domain=0x{d:x} PLAUSIBLE — in-process il2cpp works!")
            return 0
        print(f"[hijack] domain={d} — still blocked/invalid")
        return 1
    finally:
        P.CloseHandle(hproc)


if __name__ == "__main__":
    sys.exit(main())
