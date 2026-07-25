r"""Find the live CityInputManager instance by scanning the managed heap with
pure ReadProcessMemory — NO managed runtime_invoke, so it cannot wedge or crash
the il2cpp runtime (unlike FindObjectOfType, which repeatedly did).

How:
  1. One safe read-only class enum -> the current CityInputManager Il2CppClass*.
  2. VirtualQueryEx-walk the address space; keep committed, private, RW/RWX
     regions (the Boehm/il2cpp GC heap), skipping image/mapped/system regions.
  3. RPM each region and scan every 8-aligned qword for == class_ptr. Inside GC
     heap that value only appears at offset 0 of an actual instance (object
     fields hold heap pointers, never Il2CppClass* metadata pointers), so each
     hit is an instance header.
  4. Validate as a UnityEngine.Object: m_CachedPtr (+0x10) is a non-null native
     peer for a live object.

    C:\Python312\python.exe tools\find_instance_rpm.py [ClassName]
"""
from __future__ import annotations
import ctypes as C
import sys
from ctypes import wintypes

sys.path.insert(0, "tools/lib")
import il2cpp_probe as P
import il2cpp_dump as D
import hijack_call as H
import rip_gate as R

N_OFF = 0x48

k32 = C.WinDLL("kernel32", use_last_error=True)


class MEMORY_BASIC_INFORMATION(C.Structure):
    _fields_ = [
        ("BaseAddress", C.c_void_p),
        ("AllocationBase", C.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("__alignment1", wintypes.DWORD),
        ("RegionSize", C.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("__alignment2", wintypes.DWORD),
    ]


VirtualQueryEx = k32.VirtualQueryEx
VirtualQueryEx.restype = C.c_size_t
VirtualQueryEx.argtypes = [wintypes.HANDLE, C.c_void_p,
                           C.POINTER(MEMORY_BASIC_INFORMATION), C.c_size_t]

MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
PAGE_READWRITE = 0x04
PAGE_EXECUTE_READWRITE = 0x40
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01


def resolve_class(h, pid, e, name):
    """Live Il2CppClass* for an Assembly-CSharp class via one safe enum hijack."""
    mt = R.main_thread_tid(pid)
    sr = R.learn_safe_rip(pid, mt, n=30)
    S = int(P.VirtualAllocEx(h, None, D.REGION_SIZE, 0x3000, 0x40))
    cr = int(P.VirtualAllocEx(h, None, 0x2000, 0x3000, 0x40))
    P.WriteProcessMemory(h, C.c_void_p(S), b"\x00" * D.CLASS_OFF, D.CLASS_OFF,
                         C.byref(C.c_size_t(0)))
    code = D.build_dump_all(e, S)
    P.WriteProcessMemory(h, C.c_void_p(cr), code, len(code), C.byref(C.c_size_t(0)))
    r = H.hijack_call(h, pid, cr, [S, 100000, D.CLASS_CAP], "enum",
                      only_tid=mt, safe_rip=sr[0], rip_tol=16)
    if not r:
        raise SystemExit("enum failed")
    na = D.u64(P.rpm(h, S, 8), 0)
    asms = D.read_asm_table(h, S, na)
    cs = next(x for x in asms if D.cstr(h, x["name_ptr"]) == "Assembly-CSharp")
    found = None
    for idx in range(cs["start_k"], cs["start_k"] + cs["class_count"]):
        cl = D.u64(P.rpm(h, S + D.CLASS_OFF + idx * 8, 8), 0)
        if not cl:
            continue
        cb = D.rpm_safe(h, cl, 0x100)
        if cb and D.cstr(h, D.u64(cb, N_OFF)) == name:
            found = cl
            break
    # Free our own enum scratch so its flat Il2CppClass* table (which contains
    # class_ptr) doesn't pollute the later heap scan.
    P.VirtualFreeEx(h, C.c_void_p(S), 0, 0x8000)
    P.VirtualFreeEx(h, C.c_void_p(cr), 0, 0x8000)
    if not found:
        raise SystemExit(f"{name} class not found")
    return found


def iter_regions(h):
    addr = 0
    mbi = MEMORY_BASIC_INFORMATION()
    while addr < 0x7FFFFFFF0000:
        got = VirtualQueryEx(h, C.c_void_p(addr), C.byref(mbi), C.sizeof(mbi))
        if not got:
            break
        base = mbi.BaseAddress or 0
        size = mbi.RegionSize or 0
        if size == 0:
            break
        yield base, size, mbi.State, mbi.Protect, mbi.Type
        addr = base + size


def scan(h, class_ptr, name):
    hits = []
    scanned = 0
    key = class_ptr.to_bytes(8, "little")
    for base, size, state, prot, mtype in iter_regions(h):
        if state != MEM_COMMIT or mtype != MEM_PRIVATE:
            continue
        if prot & (PAGE_GUARD | PAGE_NOACCESS):
            continue
        # RW only. The il2cpp/Boehm GC heap is PAGE_READWRITE; ACE decrypts the
        # game's real code into PAGE_EXECUTE_READWRITE pages scattered across the
        # address space, and class_ptr appears there as embedded code constants —
        # pure noise. Excluding RWX removes it.
        if prot != PAGE_READWRITE:
            continue
        # chunked read of the region
        off = 0
        CH = 4 * 1024 * 1024
        while off < size:
            n = min(CH, size - off)
            blob = D.rpm_safe(h, base + off, n)
            if blob:
                scanned += len(blob)
                start = 0
                while True:
                    i = blob.find(key, start)
                    if i < 0:
                        break
                    if i % 8 == 0:  # 8-aligned qword -> object header
                        hits.append(base + off + i)
                    start = i + 1
            off += n
    print(f"scanned {scanned // (1024 * 1024)} MiB private RW; "
          f"{len(hits)} raw hits with header==0x{class_ptr:x}")
    return hits


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "CityInputManager"
    pid = P.find_game_pid()
    gb, _ = P.module_base(pid, D.MODULE)
    h = P.OpenProcess(0x1FFFFF, False, pid)
    e = P.parse_exports(h, gb)
    cls = resolve_class(h, pid, e, name)
    print(f"{name} class @0x{cls:x}")

    # Raw hits also land inside il2cpp metadata arrays and our own enum buffer
    # (flat Il2CppClass* tables), where class_ptr sits in array slots, not object
    # headers. A real Il2CppObject has monitor(+0x8)==0 and, for a UnityEngine
    # .Object, a native peer m_CachedPtr(+0x10); an array slot has another
    # Il2CppClass* right after it (monitor != 0). Filter on both.
    # Most raw hits are MethodInfo.klass back-pointers (every method of the class
    # stores klass == class_ptr) and other metadata, not object headers. The
    # decisive test for a genuine live UnityEngine.Object: its m_CachedPtr(+0x10)
    # is a native peer whose first qword is a C++ vtable inside a loaded module
    # (0x7ff… range). Metadata "peers" point at name strings or metadata instead.
    hits = sorted(scan(h, cls, name))

    def looks_ascii(ptr):
        """True if ptr points at a readable ASCII/identifier string (a method
        name → the hit is a MethodInfo.klass, not an object)."""
        b = D.rpm_safe(h, ptr, 16)
        if not b:
            return False
        s = b.split(b"\x00")[0]
        return len(s) >= 3 and all(0x20 <= c < 0x7F for c in s[:8])

    # A real il2cpp object header: klass(+0)==class_ptr, monitor(+8)==0. Reject
    # the two big false-positive sources: MethodInfo.klass back-pointers (their
    # +0x10 is the method-name char*, i.e. ASCII) and the class's own struct /
    # vtable region (contiguous with class_ptr).
    cand = []
    for a in hits:
        if cls <= a < cls + 0x8000:
            continue  # inside the Il2CppClass struct / vtable
        monitor = D.u64(P.rpm(h, a + 0x08, 8), 0)
        if monitor != 0:
            continue
        cached = D.u64(P.rpm(h, a + 0x10, 8), 0)
        if 0x10000 < cached < 0x7FFFFFFFFFFF and looks_ascii(cached):
            continue  # MethodInfo (name string at +0x10)
        f2 = D.u64(P.rpm(h, a + 0x18, 8), 0)
        f3 = D.u64(P.rpm(h, a + 0x20, 8), 0)
        cand.append(a)
        print(f"  CANDIDATE 0x{a:x}  +8=0x{monitor:x} +0x10=0x{cached:x} "
              f"+0x18=0x{f2:x} +0x20=0x{f3:x}")
    print(f"\n{len(cand)} candidate instance(s)")
    if cand:
        print("INSTANCES=" + ",".join("0x%x" % a for a in cand))
    P.CloseHandle(h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
