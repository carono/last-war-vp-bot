r"""Learn the Unity main thread's SAFE_RIP — the parked-in-a-syscall return
address — so a hijack can be gated to that exact spot instead of "anywhere in
ntdll".

Why: hijack_call currently accepts any RIP inside ntdll. But ntdll is huge and
the main thread passes through many ntdll routines that are NOT a clean wait
(heap locks, APC dispatch, TLS callbacks). Hijacking there can wedge the
runtime. When the game sits IDLE in the base, the message-pump/main thread
spends almost all its time blocked in one syscall wait — NtWaitForSingleObject /
NtUserMsgWaitForMultipleObjectsEx — always returning to the SAME address. That
stable address is SAFE_RIP: if RIP == SAFE_RIP the thread is provably parked and
about to sleep, the safest possible moment to borrow it.

This tool suspends/samples/resumes the main thread many times and reports the
most frequent RIP + which module it lives in. Read-only: no memory is written,
the thread is only briefly suspended to read its context. Run while IDLE.

    C:\Python312\python.exe tools\rip_gate.py
"""
from __future__ import annotations

import ctypes as C
import struct
import sys
from collections import Counter

sys.path.insert(0, "tools/lib")
import il2cpp_probe as P
import hijack_call as H


def main_thread_tid(pid: int) -> int | None:
    import win32gui
    import win32process
    hit = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        if "last war" in win32gui.GetWindowText(hwnd).lower():
            tid, wpid = win32process.GetWindowThreadProcessId(hwnd)
            if wpid == pid:
                hit.append(tid)

    win32gui.EnumWindows(_cb, None)
    return hit[0] if hit else None


def module_of(pid: int, addr: int) -> str:
    """Return 'module.dll+0xOFF' for addr, or 'private/0x...' if not in a module."""
    import psutil  # noqa: F401  (ensures win path set up in probe)
    for name in ("ntdll.dll", "win32u.dll", "user32.dll", "kernel32.dll",
                 "kernelbase.dll", "GameAssembly.dll"):
        try:
            base, size = P.module_base(pid, name)
        except SystemExit:
            continue
        if base <= addr < base + size:
            return f"{name}+0x{addr - base:x}"
    return f"private/0x{addr:x}"


def sample_rip(pid: int, tid: int, n: int = 40, gap: float = 0.05) -> Counter:
    import time
    hthr = H.OpenThread(H.THREAD_ALL, False, tid)
    if not hthr:
        raise SystemExit(f"OpenThread({tid}) failed err={C.get_last_error()}")
    counts: Counter = Counter()
    try:
        for _ in range(n):
            if H.SuspendThread(hthr) == 0xFFFFFFFF:
                continue
            raw, cbase = H._aligned_context()
            off = cbase - C.addressof(raw)
            struct.pack_into("<I", raw, off + H.OFF_FLAGS, H.CONTEXT_FULL)
            if H.GetThreadContext(hthr, cbase):
                rip = struct.unpack_from("<Q", raw, off + H.OFF_RIP)[0]
                counts[rip] += 1
            H.ResumeThread(hthr)
            time.sleep(gap)
    finally:
        P.CloseHandle(hthr)
    return counts


def learn_safe_rip(pid: int, tid: int, n: int = 40) -> tuple[int, int] | None:
    """Return (safe_rip, hit_count) for the dominant parked RIP, or None."""
    counts = sample_rip(pid, tid, n=n)
    if not counts:
        return None
    rip, hits = counts.most_common(1)[0]
    return rip, hits


def main() -> int:
    pid = P.find_game_pid()
    mt = main_thread_tid(pid)
    print(f"pid={pid} main_thread_tid={mt}")
    if not mt:
        print("!! main thread (window owner) not found — abort")
        return 1

    counts = sample_rip(pid, mt, n=50)
    if not counts:
        print("!! no samples captured")
        return 1

    total = sum(counts.values())
    print(f"\nsampled {total} times; distinct RIPs = {len(counts)}")
    print("top parked RIPs:")
    for rip, hits in counts.most_common(6):
        print(f"  0x{rip:x}  x{hits:<3} ({100 * hits // total:3d}%)  {module_of(pid, rip)}")

    rip, hits = counts.most_common(1)[0]
    frac = 100 * hits // total
    mod = module_of(pid, rip)
    print(f"\nSAFE_RIP candidate = 0x{rip:x}  ({frac}% of samples)  {mod}")
    if frac < 60:
        print("!! dominant RIP < 60% of samples — game may not be idle; "
              "let it settle in the base and re-run")
        return 2
    if not mod.startswith("ntdll.dll"):
        print("!! dominant RIP is NOT in ntdll — unexpected for a parked wait; "
              "inspect before gating on it")
    print(f"\nSAFE_RIP=0x{rip:x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
