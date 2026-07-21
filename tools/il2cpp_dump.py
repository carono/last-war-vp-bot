r"""IL2CPP class/method dumper over the proven thread-hijack primitive.

Strategy (safety-first, minimal game disturbance):

  * ONE hijack runs a self-contained x64 enumeration *function* we inject into a
    scratch region. That function walks
        il2cpp_domain_get
          -> il2cpp_domain_get_assemblies
             -> il2cpp_assembly_get_image / il2cpp_image_get_name
                -> il2cpp_image_get_class_count / il2cpp_image_get_class
    and dumps, into a big output buffer, a per-assembly table plus a flat array
    of every Il2CppClass* pointer. hijack_call() invokes it exactly like any
    other proven 4-arg call and hands back the class count in rax.

  * Everything else is pure ReadProcessMemory. We never do a hijack per class or
    per method (that would be hundreds of thousands of thread suspends). Instead
    we AUTO-DETECT the il2cpp struct layout from a couple of sample objects:
      - call il2cpp_class_get_name/namespace on a sample class, then scan the
        Il2CppClass bytes for the matching char* to learn the name/ns offsets,
      - iterate a sample class's methods via il2cpp_class_get_methods to learn
        the `methods` (MethodInfo**) and `method_count` (uint16) offsets,
      - call il2cpp_method_get_name on a sample method to learn the MethodInfo
        name offset; MethodInfo[0] is the compiled methodPointer (validated to
        lie inside GameAssembly.dll).
    With those offsets, every class name, namespace, method name and method
    address is resolved by plain RPM — fast and side-effect free.

Output: results/il2cpp_dump.json  +  a target search for the world-transition
call (GoToWorld / EnterWorld / LeaveCity / ... / Send* in networking classes).

Run under Windows Python (game must be running):
    C:\Python312\python.exe tools\il2cpp_dump.py [--full] [--methods]

Without --full it does a dry validation on the first assembly only. --methods
enables the (heavier) full method dump; otherwise only classes+names are dumped.
"""
from __future__ import annotations

import ctypes as C
import json
import os
import struct
import sys
import time

sys.path.insert(0, "tools")
import il2cpp_probe as P
import hijack_call as H

MODULE = "GameAssembly.dll"

# scratch region layout (offsets from region base S)
ASM_OFF = 0x100        # per-assembly table: [img, name_ptr, class_count, start_k] * 32 bytes
CLASS_OFF = 0x8000     # flat Il2CppClass* array, stride 8
CLASS_CAP = 200_000
REGION_SIZE = 0x200000  # 2 MiB, holds header + asm table + up to CLASS_CAP class ptrs

# il2cpp exports the enumeration function needs baked in as immediates
NEEDED = [
    "il2cpp_domain_get",
    "il2cpp_domain_get_assemblies",
    "il2cpp_assembly_get_image",
    "il2cpp_image_get_name",
    "il2cpp_image_get_class_count",
    "il2cpp_image_get_class",
]

TARGET_SUBSTR = [
    "gotoworld", "enterworld", "leavecity", "entermap", "go_to_world",
    "gotocity", "leaveworld", "switchmap", "worldmap", "changemap",
    "enterbigmap", "gobigmap",
]
NET_SUBSTR = ["send", "sendrpc", "netsend", "sendmessage", "request", "rpc", "notify"]


# --------------------------------------------------------------------------- #
# tiny label-aware x64 assembler (so we never hand-compute a rel32)
# --------------------------------------------------------------------------- #
# slot offsets inside the scratch region (used by the enum function; all state
# lives in memory, never in registers across an il2cpp call)
SL_CNT = 0x00    # asm_count (out from domain_get_assemblies)
SL_ASMS = 0x08
SL_N = 0x10      # min(asm_count, max_asm)
SL_A = 0x18      # assembly index
SL_IMG = 0x20
SL_CCNT = 0x28   # class count of current image
SL_C = 0x30      # class index
SL_K = 0x38      # total classes stored
SL_CAP = 0x40    # class_cap
SL_NAME = 0x48

_REGS = {"rax": (0, 0), "rcx": (1, 0), "rdx": (2, 0),
         "r8": (0, 1), "r9": (1, 1), "r10": (2, 1), "r11": (3, 1)}


class Asm:
    def __init__(self, S: int):
        self.buf = bytearray()
        self.labels: dict[str, int] = {}
        self.fixups: list[tuple[int, str]] = []
        self.S = S

    def db(self, b: bytes):
        self.buf += b

    def imm_call(self, addr: int):
        """mov rax, addr ; call rax"""
        self.db(b"\x48\xB8" + struct.pack("<Q", addr))
        self.db(b"\xFF\xD0")

    def label(self, name: str):
        self.labels[name] = len(self.buf)

    def jmp(self, op: bytes, name: str):
        self.db(op)
        self.fixups.append((len(self.buf), name))
        self.db(b"\x00\x00\x00\x00")

    # -- scratch addressing (r11 = S, reloaded before every access) ---------
    def base(self):
        """mov r11, imm64(S)"""
        self.db(b"\x49\xBB" + struct.pack("<Q", self.S))

    def _memop(self, opcode: int, reg: str, disp: int):
        code, hi = _REGS[reg]
        rex = 0x48 | (0x04 if hi else 0) | 0x01  # W=1, R=hi, B=1 (base r11)
        if -128 <= disp <= 127:
            self.db(bytes([rex, opcode, (0x40 | (code << 3) | 0b011)]))
            self.db(struct.pack("<b", disp))
        else:
            self.db(bytes([rex, opcode, (0x80 | (code << 3) | 0b011)]))
            self.db(struct.pack("<i", disp))

    def st(self, disp: int, reg: str):
        """mov [r11+disp], reg  (r11 must already = S)"""
        self._memop(0x89, reg, disp)

    def ld(self, reg: str, disp: int):
        """mov reg, [r11+disp]  (r11 must already = S)"""
        self._memop(0x8B, reg, disp)

    def finish(self) -> bytes:
        for pos, name in self.fixups:
            rel = self.labels[name] - (pos + 4)
            struct.pack_into("<i", self.buf, pos, rel)
        return bytes(self.buf)


def build_dump_all(exp: dict[str, int], S: int) -> bytes:
    """Enumeration function (rcx=S[baked], rdx=max_asm, r8=class_cap) -> rax=k.

    All persistent state is spilled to the scratch region between il2cpp calls,
    because the game's il2cpp exports do NOT preserve non-volatile registers.
    hijack_call already saves/restores the hijacked thread's GP regs, so we may
    clobber anything here.
    """
    dg = exp["il2cpp_domain_get"]
    dga = exp["il2cpp_domain_get_assemblies"]
    agi = exp["il2cpp_assembly_get_image"]
    ign = exp["il2cpp_image_get_name"]
    igcc = exp["il2cpp_image_get_class_count"]
    igc = exp["il2cpp_image_get_class"]

    a = Asm(S)
    a.db(b"\x48\x83\xEC\x28")            # sub rsp, 0x28  (align + shadow)
    a.base(); a.st(SL_CAP, "r8")        # cap = r8
    a.st(SL_N, "rdx")                   # n(tmp) = max_asm

    a.imm_call(dg)                      # rax = domain
    a.base(); a.st(0x50, "rax")         # dbg: domain
    a.db(b"\x48\x85\xC0")               # test rax, rax
    a.jmp(b"\x0F\x84", "fail")
    a.db(b"\x48\x89\xC1")               # mov rcx, rax (domain)
    a.base(); a.db(b"\x4C\x89\xDA")     # mov rdx, r11  (&SL_CNT = S)
    a.imm_call(dga)                     # rax = asms
    a.db(b"\x48\x85\xC0")
    a.jmp(b"\x0F\x84", "fail")
    a.base(); a.st(SL_ASMS, "rax")
    a.ld("rax", SL_CNT)                 # asm_count
    a.ld("rcx", SL_N)                   # max_asm
    a.db(b"\x48\x39\xC8")               # cmp rax, rcx
    a.jmp(b"\x0F\x82", "have_n")        # jb have_n (rax<rcx -> n=rax)
    a.db(b"\x48\x89\xC8")               # mov rax, rcx
    a.label("have_n")
    a.base(); a.st(SL_N, "rax")
    a.db(b"\x48\x31\xC0")               # xor rax, rax
    a.base(); a.st(SL_A, "rax"); a.st(SL_K, "rax")

    a.label("asm_loop")
    a.base(); a.ld("rax", SL_A); a.ld("rcx", SL_N)
    a.db(b"\x48\x39\xC8")               # cmp rax, rcx
    a.jmp(b"\x0F\x83", "done")          # jae done
    a.base(); a.ld("rcx", SL_ASMS); a.ld("rax", SL_A)
    a.db(b"\x48\x8B\x0C\xC1")           # mov rcx, [rcx+rax*8]  (asm)
    a.imm_call(agi)                     # img
    a.base(); a.st(SL_IMG, "rax")
    a.db(b"\x48\x89\xC1")               # mov rcx, rax
    a.imm_call(ign)                     # name
    a.base(); a.st(SL_NAME, "rax")
    a.ld("rcx", SL_IMG)
    a.imm_call(igcc)                    # eax = cnt
    a.db(b"\x48\x63\xC0")               # movsxd rax, eax
    a.base(); a.st(SL_CCNT, "rax")
    # ASM table entry: rax = S + a*32
    a.ld("rax", SL_A)
    a.db(b"\x48\xC1\xE0\x05")           # shl rax, 5
    a.db(b"\x4C\x01\xD8")               # add rax, r11   (r11 == S)
    a.base(); a.ld("rdx", SL_IMG)
    a.db(b"\x48\x89\x90\x00\x01\x00\x00")  # mov [rax+0x100], rdx (img)
    a.ld("rdx", SL_NAME)
    a.db(b"\x48\x89\x90\x08\x01\x00\x00")  # mov [rax+0x108], rdx (name)
    a.ld("rdx", SL_CCNT)
    a.db(b"\x48\x89\x90\x10\x01\x00\x00")  # mov [rax+0x110], rdx (cnt)
    a.ld("rdx", SL_K)
    a.db(b"\x48\x89\x90\x18\x01\x00\x00")  # mov [rax+0x118], rdx (start_k)
    a.db(b"\x48\x31\xC0")               # xor rax, rax
    a.base(); a.st(SL_C, "rax")

    a.label("cls_loop")
    a.base(); a.ld("rax", SL_C); a.ld("rcx", SL_CCNT)
    a.db(b"\x48\x39\xC8")               # cmp rax, rcx
    a.jmp(b"\x0F\x83", "asm_next")      # jae asm_next
    a.base(); a.ld("rax", SL_K); a.ld("rcx", SL_CAP)
    a.db(b"\x48\x39\xC8")               # cmp rax, rcx
    a.jmp(b"\x0F\x83", "done")          # jae done
    a.base(); a.ld("rcx", SL_IMG); a.ld("rdx", SL_C)
    a.imm_call(igc)                    # rax = cls
    a.base(); a.ld("rcx", SL_K)
    a.db(b"\x49\x89\x84\xCB\x00\x80\x00\x00")  # mov [r11+rcx*8+0x8000], rax
    a.ld("rax", SL_K); a.db(b"\x48\xFF\xC0"); a.st(SL_K, "rax")   # k++
    a.base(); a.ld("rax", SL_C); a.db(b"\x48\xFF\xC0"); a.st(SL_C, "rax")  # c++
    a.jmp(b"\xE9", "cls_loop")

    a.label("asm_next")
    a.base(); a.ld("rax", SL_A); a.db(b"\x48\xFF\xC0"); a.st(SL_A, "rax")  # a++
    a.jmp(b"\xE9", "asm_loop")

    a.label("fail")
    a.db(b"\x48\x31\xC0")               # xor rax, rax
    a.base(); a.st(SL_K, "rax")
    a.label("done")
    a.base(); a.ld("rax", SL_K)
    a.db(b"\x48\x83\xC4\x28")           # add rsp, 0x28
    a.db(b"\xC3")                       # ret
    return a.finish()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def u64(b: bytes, off: int) -> int:
    return struct.unpack_from("<Q", b, off)[0]


def u16(b: bytes, off: int) -> int:
    return struct.unpack_from("<H", b, off)[0]


def rpm_safe(hproc, addr: int, size: int) -> bytes | None:
    try:
        return P.rpm(hproc, addr, size)
    except OSError:
        return None


def cstr(hproc, addr: int, maxlen: int = 160) -> str:
    if not addr:
        return ""
    try:
        return P.read_cstr(hproc, addr, maxlen)
    except OSError:
        return ""


def hj(hproc, pid, func, args, label):
    """One proven hijack call, returns rax or None."""
    return H.hijack_call(hproc, pid, func, args, label)


# --------------------------------------------------------------------------- #
# struct-offset auto-detection
# --------------------------------------------------------------------------- #
def detect_class_name_offsets(hproc, pid, exp, sample_classes, scratch):
    """Return (name_off, ns_off) into Il2CppClass, or (None, None)."""
    get_name = exp.get("il2cpp_class_get_name")
    get_ns = exp.get("il2cpp_class_get_namespace")
    if not get_name:
        return None, None
    name_votes: dict[int, int] = {}
    ns_votes: dict[int, int] = {}
    for cls in sample_classes:
        blob = rpm_safe(hproc, cls, 0x400)
        if not blob:
            continue
        np = hj(hproc, pid, get_name, [cls], "cls_name")
        if np:
            for off in range(0, len(blob) - 8, 8):
                if u64(blob, off) == np:
                    name_votes[off] = name_votes.get(off, 0) + 1
        if get_ns:
            sp = hj(hproc, pid, get_ns, [cls], "cls_ns")
            if sp:
                for off in range(0, len(blob) - 8, 8):
                    if u64(blob, off) == sp:
                        ns_votes[off] = ns_votes.get(off, 0) + 1
    name_off = max(name_votes, key=name_votes.get) if name_votes else None
    ns_off = max(ns_votes, key=ns_votes.get) if ns_votes else None
    return name_off, ns_off


def iterate_methods(hproc, pid, exp, cls, scratch, cap=96):
    """Hijack-iterate one class's methods; returns list of MethodInfo*."""
    get_methods = exp["il2cpp_class_get_methods"]
    iter_slot = scratch  # a persistent qword in game memory for the iterator
    P.WriteProcessMemory(hproc, C.c_void_p(iter_slot), b"\x00" * 8, 8,
                         C.byref(C.c_size_t(0)))
    out = []
    for _ in range(cap):
        m = hj(hproc, pid, get_methods, [cls, iter_slot], "iter_m")
        if not m:
            break
        out.append(m)
    return out


def detect_method_layout(hproc, pid, exp, sample_classes, scratch):
    """Detect Il2CppClass.methods/method_count and MethodInfo.name offsets."""
    result = {"methods_off": None, "count_off": None, "mname_off": None,
              "addr_off": 0}
    get_mname = exp.get("il2cpp_method_get_name")
    m_votes: dict[int, int] = {}
    c_votes: dict[int, int] = {}
    mn_votes: dict[int, int] = {}
    addr_votes: dict[int, int] = {}
    gbase, gsize = P.module_base(pid, MODULE)
    glo, ghi = gbase, gbase + gsize

    for cls in sample_classes:
        methods = iterate_methods(hproc, pid, exp, cls, scratch)
        if len(methods) < 2:
            continue
        n = len(methods)
        m0 = methods[0]
        blob = rpm_safe(hproc, cls, 0x400)
        if not blob:
            continue
        # methods array offset: a qword P where *(P) == m0 and P[1] == methods[1]
        for off in range(0, len(blob) - 8, 8):
            ptr = u64(blob, off)
            if ptr < 0x10000 or ptr > 0x7FFFFFFFFFFF:
                continue
            arr = rpm_safe(hproc, ptr, 8 * min(n, 4))
            if not arr:
                continue
            ok = all(u64(arr, i * 8) == methods[i]
                     for i in range(min(n, 4)))
            if ok:
                m_votes[off] = m_votes.get(off, 0) + 1
        # method_count offset (uint16 == n)
        for off in range(0, len(blob) - 2, 2):
            if u16(blob, off) == n:
                c_votes[off] = c_votes.get(off, 0) + 1
        # MethodInfo.name offset from m0, and methodPointer offset by range scan.
        # Last War runs a customised il2cpp: MethodInfo fields are reordered, so
        # the compiled code pointer is NOT at offset 0 — we locate it as the
        # (first) qword that lands inside GameAssembly.dll's mapped range.
        for mi in methods[:6]:
            mblob = rpm_safe(hproc, mi, 0x60)
            if not mblob:
                continue
            if get_mname:
                mnp = hj(hproc, pid, get_mname, [mi], "m_name")
                if mnp:
                    for off in range(0, len(mblob) - 8, 8):
                        if u64(mblob, off) == mnp:
                            mn_votes[off] = mn_votes.get(off, 0) + 1
            for off in range(0, len(mblob) - 8, 8):
                q = u64(mblob, off)
                if glo <= q < ghi:
                    addr_votes[off] = addr_votes.get(off, 0) + 1

    if m_votes:
        result["methods_off"] = max(m_votes, key=m_votes.get)
    if c_votes:
        result["count_off"] = max(c_votes, key=c_votes.get)
    if mn_votes:
        result["mname_off"] = max(mn_votes, key=mn_votes.get)
    if addr_votes:
        # the code pointer offset that is in-range for (nearly) every method
        result["addr_off"] = max(addr_votes, key=addr_votes.get)
    else:
        result["addr_off"] = None
    print(f"[detect] addr_off votes: "
          f"{ {k: addr_votes[k] for k in sorted(addr_votes)} }")
    return result


# --------------------------------------------------------------------------- #
# main dump
# --------------------------------------------------------------------------- #
def read_asm_table(hproc, S, asm_count):
    blob = rpm_safe(hproc, S + ASM_OFF, asm_count * 32)
    out = []
    for i in range(asm_count):
        base = i * 32
        out.append({
            "img": u64(blob, base + 0),
            "name_ptr": u64(blob, base + 8),
            "class_count": u64(blob, base + 16),
            "start_k": u64(blob, base + 24),
        })
    return out


def read_class_ptrs(hproc, S, k):
    ptrs = []
    CH = 8192
    got = 0
    while got < k:
        n = min(CH, k - got)
        blob = rpm_safe(hproc, S + CLASS_OFF + got * 8, n * 8)
        if not blob:
            break
        for i in range(n):
            ptrs.append(u64(blob, i * 8))
        got += n
    return ptrs


def run(full: bool, do_methods: bool):
    pid = P.find_game_pid()
    print(f"[dump] LastWar.exe pid={pid}")
    gbase, gsize = P.module_base(pid, MODULE)
    print(f"[dump] {MODULE} base=0x{gbase:x} size=0x{gsize:x}")
    hproc = P.OpenProcess(0x1FFFFF, False, pid)
    if not hproc:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")

    try:
        exports = P.parse_exports(hproc, gbase)
        il = {k: v for k, v in exports.items() if k.startswith("il2cpp_")}
        print(f"[dump] exports total={len(exports)} il2cpp_={len(il)}")
        missing = [n for n in NEEDED if n not in exports]
        if missing:
            raise SystemExit(f"[dump] missing required exports: {missing}")

        # baseline self-test via the proven mechanism
        kbase, _ = P.module_base(pid, "kernel32.dll")
        gcpi = P.parse_exports(hproc, kbase)["GetCurrentProcessId"]
        r = hj(hproc, pid, gcpi, [], "selftest")
        if r is None or (r & 0xFFFFFFFF) != pid:
            raise SystemExit(f"[dump] self-test failed (got {r}); aborting")
        print("[dump] self-test OK — hijack mechanism live")

        # allocate code + scratch regions
        code_region = int(P.VirtualAllocEx(hproc, None, 0x2000, 0x3000, 0x40))
        S = int(P.VirtualAllocEx(hproc, None, REGION_SIZE, 0x3000, 0x40))
        if not code_region or not S:
            raise OSError("region alloc failed")
        # zero the header/asm area
        P.WriteProcessMemory(hproc, C.c_void_p(S), b"\x00" * CLASS_OFF,
                             CLASS_OFF, C.byref(C.c_size_t(0)))
        code = build_dump_all(exports, S)
        P.WriteProcessMemory(hproc, C.c_void_p(code_region), code, len(code),
                             C.byref(C.c_size_t(0)))
        print(f"[dump] enum function {len(code)}B @0x{code_region:x}, "
              f"scratch @0x{S:x}")

        # --- staged: validate on first assembly only -----------------------
        max_asm = 1 if not full else 100_000
        k = asm_count = 0
        for attempt in range(4):
            # re-zero header so a retry starts clean
            P.WriteProcessMemory(hproc, C.c_void_p(S), b"\x00" * CLASS_OFF,
                                 CLASS_OFF, C.byref(C.c_size_t(0)))
            k = hj(hproc, pid, code_region, [S, max_asm, CLASS_CAP], "enum")
            asm_count = u64(rpm_safe(hproc, S, 8) or b"\x00" * 8, 0)
            if k and asm_count:
                break
            print(f"[dump] enum attempt {attempt+1} empty (k={k} "
                  f"asm={asm_count}) — retrying on another thread")
            time.sleep(0.4)
        print(f"[dump] enumeration done: asm_count={asm_count} classes_k={k}")
        if asm_count == 0 or k == 0:
            dbg = rpm_safe(hproc, S, 0x60) or b""
            print(f"[dbg] slots: {dbg.hex()}")
            print(f"[dbg] domain=0x{u64(dbg,0x50):x} asms=0x{u64(dbg,0x08):x} "
                  f"n=0x{u64(dbg,0x10):x} cap=0x{u64(dbg,0x40):x}")
            raise SystemExit("[dump] empty result — il2cpp likely returned null; "
                             "abort (game intact)")

        asms = read_asm_table(hproc, S, min(asm_count, max_asm))
        print(f"[dump] first assemblies:")
        for e in asms[:6]:
            print(f"    {cstr(hproc, e['name_ptr'])}: "
                  f"classes={e['class_count']} start_k={e['start_k']}")

        if not full:
            hdr = rpm_safe(hproc, S, 0x20) or b""
            print(f"[dbg] header  : {hdr.hex()}")
            tbl = rpm_safe(hproc, S + ASM_OFF, 8 * 32) or b""
            cum = 0
            for i in range(8):
                b = i * 32
                nm = cstr(hproc, u64(tbl, b + 8))
                cc = u64(tbl, b + 16)
                sk = u64(tbl, b + 24)
                cum += cc
                print(f"[dbg] asm[{i}] name={nm!r:20} cnt={cc} start_k={sk}")
            print(f"[dbg] class[0]: 0x{u64(rpm_safe(hproc, S+CLASS_OFF, 8) or b'0'*8,0):x}")
            print("[dump] DRY validation OK. Re-run with --full to dump all "
                  "assemblies.")
            P.VirtualFreeEx(hproc, C.c_void_p(code_region), 0, 0x8000)
            P.VirtualFreeEx(hproc, C.c_void_p(S), 0, 0x8000)
            return 0

        class_ptrs = read_class_ptrs(hproc, S, k)
        print(f"[dump] read {len(class_ptrs)} class pointers")

        # map class index -> assembly name via start_k ranges
        def asm_of(idx):
            name = "?"
            for e in asms:
                if e["start_k"] <= idx < e["start_k"] + e["class_count"]:
                    return cstr(hproc, e["name_ptr"])
            return name

        # --- offset auto-detection ----------------------------------------
        samples = [c for c in class_ptrs if c][:40]
        name_off, ns_off = detect_class_name_offsets(
            hproc, pid, exports, samples[:8], S + 0x20)
        print(f"[dump] Il2CppClass name_off={name_off} ns_off={ns_off}")

        mlayout = {"methods_off": None, "count_off": None, "mname_off": None,
                   "addr_off": 0}
        if do_methods:
            mlayout = detect_method_layout(hproc, pid, exports, samples[:6],
                                           S + 0x20)
            print(f"[dump] method layout: {mlayout}")

        # --- resolve everything via RPM -----------------------------------
        classes = []
        methods_total = 0
        t0 = time.time()
        for idx, cls in enumerate(class_ptrs):
            if not cls:
                continue
            blob = rpm_safe(hproc, cls, 0x100)
            if not blob:
                continue
            cname = cstr(hproc, u64(blob, name_off)) if name_off is not None else ""
            cns = cstr(hproc, u64(blob, ns_off)) if ns_off else ""
            rec = {"addr": cls, "assembly": asm_of(idx),
                   "namespace": cns, "class": cname, "methods": []}
            if (do_methods and mlayout["methods_off"] is not None
                    and mlayout["count_off"] is not None):
                marr = u64(blob, mlayout["methods_off"])
                mcnt = u16(blob, mlayout["count_off"])
                if 0 < mcnt <= 4096 and 0x10000 < marr < 0x7FFFFFFFFFFF:
                    ablob = rpm_safe(hproc, marr, mcnt * 8)
                    if ablob:
                        for j in range(mcnt):
                            mi = u64(ablob, j * 8)
                            if not (0x10000 < mi < 0x7FFFFFFFFFFF):
                                continue
                            mblob = rpm_safe(hproc, mi, 0x28)
                            if not mblob:
                                continue
                            mname = ""
                            if mlayout["mname_off"] is not None:
                                mname = cstr(hproc, u64(mblob, mlayout["mname_off"]))
                            # MethodInfo (0x28) on this ACE-hardened il2cpp holds
                            # no inline compiled pointer; +0x00 high dword is the
                            # MethodDef token. Calls go through the MethodInfo* via
                            # il2cpp_runtime_invoke, so we record the pointer+token.
                            rec["methods"].append({
                                "name": mname,
                                "token": u64(mblob, 0) >> 32,
                                "methodinfo": mi,
                            })
                            methods_total += 1
            classes.append(rec)
            if idx % 2000 == 0 and idx:
                print(f"    ... {idx}/{len(class_ptrs)} classes "
                      f"({methods_total} methods, {time.time()-t0:.0f}s)")

        print(f"[dump] resolved {len(classes)} classes, {methods_total} methods "
              f"in {time.time()-t0:.0f}s")

        # --- save ----------------------------------------------------------
        os.makedirs("results", exist_ok=True)
        out = {
            "module": MODULE, "module_base": gbase, "module_size": gsize,
            "offsets": {"class_name": name_off, "class_namespace": ns_off,
                        **mlayout},
            "assemblies": [{"name": cstr(hproc, e["name_ptr"]),
                            "class_count": e["class_count"]} for e in asms],
            "class_count": len(classes),
            "method_count": methods_total,
            "classes": classes,
        }
        path = "results/il2cpp_dump.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"[dump] wrote {path} ({os.path.getsize(path)} bytes)")

        # --- target search -------------------------------------------------
        search_targets(out, gbase)

        P.VirtualFreeEx(hproc, C.c_void_p(code_region), 0, 0x8000)
        P.VirtualFreeEx(hproc, C.c_void_p(S), 0, 0x8000)
        return 0
    finally:
        P.CloseHandle(hproc)


def search_targets(dump, gbase):
    print("\n[search] scanning for world-transition + networking calls ...")
    hits_strong, hits_world, hits_net = [], [], []
    for c in dump["classes"]:
        cn = (c.get("class") or "").lower()
        for m in c.get("methods", []):
            mn = (m.get("name") or "").lower()
            if any(s in mn for s in TARGET_SUBSTR):
                hits_strong.append((c, m))
            elif "world" in mn or (any(s in cn for s in TARGET_SUBSTR)):
                hits_world.append((c, m))
            elif any(s in mn for s in NET_SUBSTR):
                hits_net.append((c, m))
        if not c.get("methods"):
            if any(s in cn for s in TARGET_SUBSTR) or "world" in cn:
                hits_world.append((c, None))

    def show(title, hits, limit):
        print(f"\n[search] {title}: {len(hits)} hit(s)")
        for c, m in hits[:limit]:
            if m:
                tok = m.get("token")
                mi = m.get("methodinfo")
                print(f"    {c['assembly']} | {c['namespace']}.{c['class']}"
                      f".{m['name']}  MI=0x{mi:x} token=0x{tok:x}")
            else:
                print(f"    {c['assembly']} | {c['namespace']}.{c['class']}"
                      f"  @0x{c['addr']:x}  (class match)")

    show("STRONG transition-verb matches", hits_strong, 120)
    show("world-related candidates", hits_world, 40)
    show("networking send candidates", hits_net, 40)

    with open("results/il2cpp_targets.json", "w", encoding="utf-8") as f:
        json.dump({
            "strong": [{"assembly": c["assembly"], "namespace": c["namespace"],
                        "class": c["class"], "method": m["name"],
                        "methodinfo": m.get("methodinfo"),
                        "token": m.get("token"), "class_addr": c["addr"]}
                       for c, m in hits_strong],
            "world": [{"assembly": c["assembly"], "namespace": c["namespace"],
                       "class": c["class"],
                       "method": (m["name"] if m else None),
                       "methodinfo": (m.get("methodinfo") if m else None),
                       "token": (m.get("token") if m else None),
                       "class_addr": c["addr"]}
                      for c, m in hits_world],
            "net": [{"assembly": c["assembly"], "class": c["class"],
                     "method": m["name"], "methodinfo": m.get("methodinfo"),
                     "token": m.get("token")}
                    for c, m in hits_net],
        }, f, ensure_ascii=False, indent=1)
    print("\n[search] wrote results/il2cpp_targets.json")


def main() -> int:
    full = "--full" in sys.argv
    do_methods = "--methods" in sys.argv
    return run(full, do_methods)


if __name__ == "__main__":
    sys.exit(main())
