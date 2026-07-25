r"""Init game scene-manager classes and dump their (post-init) methods to find
the world/city transition entry point. Fresh-resolves; survives restarts.

    C:\Python312\python.exe tools\_scene_probe.py [ClassName ...]
"""
from __future__ import annotations
import ctypes as C
import sys

sys.path.insert(0, "tools/lib")
import il2cpp_probe as P
import il2cpp_dump as D

M_OFF, C_OFF, N_OFF = 0xA0, 0xFC, 0x48

TARGET_CLASSES = sys.argv[1:] or [
    "SceneManager", "SceneInterface", "ForceChangeScene", "IGameController",
    "GameController", "WorldManagerBase",
]


def main():
    pid = P.find_game_pid()
    gbase, gs = P.module_base(pid, D.MODULE)
    h = P.OpenProcess(0x1FFFFF, False, pid)
    exp = P.parse_exports(h, gbase)
    rci = exp["il2cpp_runtime_class_init"]
    getm = exp["il2cpp_class_get_methods"]
    getpc = exp.get("il2cpp_method_get_param_count")
    getfl = exp.get("il2cpp_method_get_flags")

    S = int(P.VirtualAllocEx(h, None, D.REGION_SIZE, 0x3000, 0x40))
    cr = int(P.VirtualAllocEx(h, None, 0x2000, 0x3000, 0x40))
    P.WriteProcessMemory(h, C.c_void_p(S), b"\x00" * D.CLASS_OFF, D.CLASS_OFF,
                         C.byref(C.c_size_t(0)))
    code = D.build_dump_all(exp, S)
    P.WriteProcessMemory(h, C.c_void_p(cr), code, len(code),
                         C.byref(C.c_size_t(0)))
    k = D.hj(h, pid, cr, [S, 100000, D.CLASS_CAP], "enum")
    n_asm = D.u64(P.rpm(h, S, 8), 0)
    print(f"enum k={k} asm={n_asm}")

    # build name -> cls map for Assembly-CSharp
    asms = D.read_asm_table(h, S, n_asm)
    cs = next(e for e in asms if D.cstr(h, e["name_ptr"]) == "Assembly-CSharp")
    want = set(TARGET_CLASSES)
    found = {}
    for idx in range(cs["start_k"], cs["start_k"] + cs["class_count"]):
        cls = D.u64(P.rpm(h, S + D.CLASS_OFF + idx * 8, 8), 0)
        if not cls:
            continue
        cb = D.rpm_safe(h, cls, 0x100)
        if not cb:
            continue
        nm = D.cstr(h, D.u64(cb, N_OFF))
        if nm in want and nm not in found:
            found[nm] = cls

    iter_slot = S + 0x20
    for nm in TARGET_CLASSES:
        cls = found.get(nm)
        if not cls:
            print(f"\n### {nm}: NOT FOUND")
            continue
        D.hj(h, pid, rci, [cls], "init")           # force class init
        cb = D.rpm_safe(h, cls, 0x120)
        cnt = D.u16(cb, C_OFF)
        marr = D.u64(cb, M_OFF)
        print(f"\n### {nm} @0x{cls:x}  post-init method_count={cnt} arr=0x{marr:x}")
        if not (0 < cnt <= 4096 and 0x10000 < marr < 0x7FFFFFFFFFFF):
            # fall back to iterator API
            P.WriteProcessMemory(h, C.c_void_p(iter_slot), b"\x00" * 8, 8,
                                 C.byref(C.c_size_t(0)))
            names = []
            for _ in range(400):
                m = D.hj(h, pid, getm, [cls, iter_slot], "it")
                if not m:
                    break
                mb = D.rpm_safe(h, m, 0x28)
                names.append(D.cstr(h, D.u64(mb, 0x18)))
            print(f"  (iterator) {len(names)} methods")
            for x in names:
                print("   ", x)
            continue
        ab = D.rpm_safe(h, marr, cnt * 8)
        for j in range(cnt):
            mi = D.u64(ab, j * 8)
            if not (0x10000 < mi < 0x7FFFFFFFFFFF):
                continue
            mb = D.rpm_safe(h, mi, 0x28)
            print("   ", D.cstr(h, D.u64(mb, 0x18)))

    P.VirtualFreeEx(h, C.c_void_p(S), 0, 0x8000)
    P.VirtualFreeEx(h, C.c_void_p(cr), 0, 0x8000)
    P.CloseHandle(h)


if __name__ == "__main__":
    main()
