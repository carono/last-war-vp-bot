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


#: How many times one parked address must be seen before a learn stops asking (#2667).
#: The learn's job is to name the dominant ntdll park, and three sightings of the same
#: address already decide it: measured live against the full 40-sample sweep, the early
#: stop picked THE SAME address every time and paid 5-8 suspensions for it instead of 40.
#: Every one of those is a suspend/resume of the game's main thread — 60-75 us each,
#: measured — so this is the same answer for a fifth of the interference.
ENOUGH_HITS = 3


#: How many parks the gate will aim at (#2678). The client's message pump alternates
#: between two ntdll waits — the A/B of #2667 kept turning up two dominant addresses 192
#: bytes apart — and a gate aimed at one of them waits out every visit to the other.
MAX_PARKS = 2


def _inside(counts: Counter, span) -> list:
    """``[(hits, rip), ...]`` for the sampled addresses inside ``span``, busiest first."""
    base, size = span
    rows = [(hits, rip) for rip, hits in counts.items() if base <= rip < base + size]
    rows.sort(reverse=True)
    return rows


def _decided(counts: Counter, span, enough: int) -> bool:
    """Has the sweep already named the client's parks beyond argument?

    THE STOP RULE CHANGED WITH THE GATE (#2678). It used to stop the moment ONE address
    led the field, which is the right answer to «which is the park» and the wrong one to
    «which parks are there»: a sweep that leaves as soon as the winner is clear can never
    see the second wait, so the gate it feeds is aimed at one of two and waits out every
    visit to the other. So it now stops on either of two proofs, and both of them are
    still evidence rather than a sample budget:

      * :data:`MAX_PARKS` addresses have each been seen ``enough`` times — the parks are
        known and there is no room for another one;
      * ONE address has been seen ``2 * enough`` times and no other has reached
        ``enough`` — this client parks in one place and the second slot stays empty.

    The `enough` sightings requirement is untouched, so a one-sighting winner still
    cannot aim the gate at a spot the thread rarely reaches (#1994).
    """
    inside = _inside(counts, span)
    if not inside:
        return False
    strong = [row for row in inside if row[0] >= enough]
    if len(strong) >= MAX_PARKS:
        return True
    return len(strong) == 1 and strong[0][0] >= 2 * enough


def sample_rip(pid: int, tid: int, n: int = 40, gap: float = 0.05,
               stop_at=None) -> Counter:
    """Suspend/read/resume the thread up to ``n`` times; the RIPs it was found at.

    ``stop_at`` is ``((base, size), enough)`` — stop the moment one address inside that
    module has been seen ``enough`` times. EVERY SAMPLE IS A SUSPENSION OF THE CLIENT'S
    MAIN THREAD (#2667), and a sweep that has already found the park three times is
    paying for an answer it has: measured live, an idle client hands over the park in
    3-6 samples and the remaining 34 change nothing.
    """
    import time
    hthr = H.OpenThread(H.THREAD_ALL, False, tid)
    if not hthr:
        raise SystemExit(f"OpenThread({tid}) failed err={C.get_last_error()}")
    counts: Counter = Counter()
    try:
        for _ in range(n):
            if stop_at is not None and _decided(counts, *stop_at):
                break
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


def _ntdll_span(pid: int) -> tuple[int, int] | None:
    """(base, size) of ntdll in the target, or None. Asked once per learn."""
    try:
        return P.module_base(pid, "ntdll.dll")
    except SystemExit:
        return None


def learn_safe_rip(pid: int, tid: int, n: int = 40,
                   enough: int = ENOUGH_HITS) -> tuple[int, int] | None:
    """Return (safe_rip, hit_count) for the dominant PARKED RIP, or None when the
    thread never parked while we watched.

    The park is the message-pump wait, which lives in ntdll — so a candidate
    OUTSIDE ntdll is not a park at all, it is merely wherever a busy main thread
    happened to be when the sampler caught it. Taking the most common sample with
    no such check is how a busy client used to hand out a SAFE_RIP the gate could
    never match: `hijack_call` accepts a thread only within +-16 bytes of the
    learned address, so every hijack of that run failed with "returned None" — and
    because the address is learned ONCE per build, it stayed wrong for the whole
    life of the process even after the client went quiet again (#1994: a panel
    spent fourteen hours reporting "no traffic" from behind exactly this).

    So the winner is the most-sampled ntdll address rather than the most-sampled
    address; and when the thread never reached ntdll at all, say so by returning
    None instead of aiming the gate at a random instruction in the render loop.
    """
    got = learn_parks(pid, tid, n=n, enough=enough)
    return got[0] if got else None


def learn_parks(pid: int, tid: int, n: int = 40, enough: int = ENOUGH_HITS,
                most: int = MAX_PARKS) -> list:
    """Every PARK the main thread was found in, busiest first: ``[(rip, hits), ...]``.

    The plural of :func:`learn_safe_rip`, and the one the gate is fed (#2678). A client
    being played alternates between two ntdll waits, and both of them are a park: the
    thread is in a syscall, about to sleep, which is the whole of what the gate is
    checking for. Aiming at one of the two is how a live client came back «busy — it did
    not reach its park once in 67s» for eighteen minutes on 2026-09-09 while a person was
    playing it.

    An address is a park when it has been seen ``enough`` times, exactly as before; a
    single-sighting address is noise and is left out. When nothing reached that bar the
    busiest ntdll address is returned alone, which is the old answer and keeps a quiet
    client — where the park wins on sample three — behaving as it always did.
    """
    span = _ntdll_span(pid)
    counts = sample_rip(pid, tid, n=n, stop_at=None if span is None else
                        (span, enough))
    if not counts:
        return []
    if span is None:        # cannot tell a park from anything else — old behaviour
        rip, hits = counts.most_common(1)[0]
        return [(rip, hits)]
    inside = _inside(counts, span)
    if not inside:
        return []
    strong = [(rip, hits) for hits, rip in inside if hits >= enough][:most]
    if strong:
        return strong
    hits, rip = inside[0]
    return [(rip, hits)]


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

    # What the GATE would take, which is not the same as what was sampled most: a
    # candidate outside ntdll is not a park, so the learner skips it (see above).
    span = _ntdll_span(pid)
    got = None
    for cand, hits in counts.most_common():
        if span and span[0] <= cand < span[0] + span[1]:
            got = (cand, hits)
            break
    if got is None:
        print("\n!! the main thread never reached ntdll in these samples — it is not "
              "parking at all. Let the game sit in the base, untouched, for a minute "
              "and re-run; nothing can be run in the client until then.")
        return 2
    rip, hits = got
    frac = 100 * hits // total
    print(f"\nSAFE_RIP candidate = 0x{rip:x}  ({frac}% of samples)  "
          f"{module_of(pid, rip)}")
    if frac < 60:
        print("!! the park holds < 60% of samples — the game is busy, so the gate will "
              "have to wait for it; let it settle in the base for a steadier read")
    print(f"\nSAFE_RIP=0x{rip:x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
