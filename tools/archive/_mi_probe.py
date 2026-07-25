r"""Throwaway: dump raw MethodInfo bytes of a real game method to locate the
compiled methodPointer offset (Last War's il2cpp reorders MethodInfo fields and
the pointer is not in the usual slot). Fresh-resolves everything, so it survives
game restarts.

    C:\Python312\python.exe tools\_mi_probe.py
"""
from __future__ import annotations
import ctypes as C
import struct
import sys

sys.path.insert(0, "tools/lib")
import il2cpp_probe as P
import il2cpp_dump as D

M_OFF = 0xA0    # Il2CppClass.methods (detected)
C_OFF = 0xFC    # Il2CppClass.method_count (detected)


def main():
    pid = P.find_game_pid()
    gbase, gsize = P.module_base(pid, D.MODULE)
    glo, ghi = gbase, gbase + gsize
    print(f"pid={pid} {D.MODULE} 0x{gbase:x}..0x{ghi:x} (size 0x{gsize:x})")
    hproc = P.OpenProcess(0x1FFFFF, False, pid)
    exp = P.parse_exports(hproc, gbase)

    S = int(P.VirtualAllocEx(hproc, None, D.REGION_SIZE, 0x3000, 0x40))
    code_region = int(P.VirtualAllocEx(hproc, None, 0x2000, 0x3000, 0x40))
    P.WriteProcessMemory(hproc, C.c_void_p(S), b"\x00" * D.CLASS_OFF, D.CLASS_OFF,
                         C.byref(C.c_size_t(0)))
    code = D.build_dump_all(exp, S)
    P.WriteProcessMemory(hproc, C.c_void_p(code_region), code, len(code),
                         C.byref(C.c_size_t(0)))
    k = D.hj(hproc, pid, code_region, [S, 100000, D.CLASS_CAP], "enum")
    asm_count = D.u64(P.rpm(hproc, S, 8), 0)
    print(f"enum k={k} asm_count={asm_count}")
    asms = D.read_asm_table(hproc, S, asm_count)
    csharp = next(e for e in asms
                  if D.cstr(hproc, e["name_ptr"]) == "Assembly-CSharp")
    print(f"Assembly-CSharp: classes={csharp['class_count']} "
          f"start_k={csharp['start_k']}")

    # walk a few game classes; dump the first one that has methods
    for idx in range(csharp["start_k"], csharp["start_k"] + csharp["class_count"]):
        cls = D.u64(P.rpm(hproc, S + D.CLASS_OFF + idx * 8, 8), 0)
        if not cls:
            continue
        cblob = D.rpm_safe(hproc, cls, 0x120)
        if not cblob:
            continue
        cname = D.cstr(hproc, D.u64(cblob, 72))
        marr = D.u64(cblob, M_OFF)
        cnt = D.u16(cblob, C_OFF)
        if not (0 < cnt <= 200) or not (0x10000 < marr < 0x7FFFFFFFFFFF):
            continue
        ablob = D.rpm_safe(hproc, marr, cnt * 8)
        if not ablob:
            continue
        print(f"\n=== class {cname!r} @0x{cls:x} methods={cnt} arr=0x{marr:x} ===")
        shown = 0
        for j in range(cnt):
            mi = D.u64(ablob, j * 8)
            if not (0x10000 < mi < 0x7FFFFFFFFFFF):
                continue
            mb = D.rpm_safe(hproc, mi, 0x60)
            if not mb:
                continue
            mname = D.cstr(hproc, D.u64(mb, 24))
            # list every qword and flag in-module ones
            marks = []
            for off in range(0, 0x60, 8):
                q = D.u64(mb, off)
                tag = "  <== IN-MODULE (code ptr?)" if glo <= q < ghi else ""
                marks.append(f"    +0x{off:02x}: 0x{q:016x}{tag}")
            print(f"\n  method[{j}] {mname!r} @MI 0x{mi:x}")
            print("\n".join(marks))
            shown += 1
            if shown >= 4:
                break
        break

    P.VirtualFreeEx(hproc, C.c_void_p(S), 0, 0x8000)
    P.VirtualFreeEx(hproc, C.c_void_p(code_region), 0, 0x8000)
    P.CloseHandle(hproc)


if __name__ == "__main__":
    main()
