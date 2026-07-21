r"""Resolve SceneManager transition-method signatures + the SceneID enum values.

    C:\Python312\python.exe tools\_sig_probe.py
"""
from __future__ import annotations
import ctypes as C
import sys

sys.path.insert(0, "tools")
import il2cpp_probe as P
import il2cpp_dump as D

N_OFF = 0x48


def main():
    pid = P.find_game_pid()
    gbase, gs = P.module_base(pid, D.MODULE)
    h = P.OpenProcess(0x1FFFFF, False, pid)
    exp = P.parse_exports(h, gbase)
    rci = exp["il2cpp_runtime_class_init"]
    gmfn = exp["il2cpp_class_get_method_from_name"]
    gpc = exp["il2cpp_method_get_param_count"]
    gfl = exp["il2cpp_method_get_flags"]
    gcf = exp.get("il2cpp_class_get_fields")
    gfn = exp.get("il2cpp_field_get_name")
    gfv = exp.get("il2cpp_field_static_get_value")
    gff = exp.get("il2cpp_field_get_flags")

    S = int(P.VirtualAllocEx(h, None, D.REGION_SIZE, 0x3000, 0x40))
    cr = int(P.VirtualAllocEx(h, None, 0x2000, 0x3000, 0x40))
    P.WriteProcessMemory(h, C.c_void_p(S), b"\x00" * D.CLASS_OFF, D.CLASS_OFF,
                         C.byref(C.c_size_t(0)))
    code = D.build_dump_all(exp, S)
    P.WriteProcessMemory(h, C.c_void_p(cr), code, len(code), C.byref(C.c_size_t(0)))
    D.hj(h, pid, cr, [S, 100000, D.CLASS_CAP], "enum")
    n_asm = D.u64(P.rpm(h, S, 8), 0)
    asms = D.read_asm_table(h, S, n_asm)
    cs = next(e for e in asms if D.cstr(h, e["name_ptr"]) == "Assembly-CSharp")

    names = {}
    for idx in range(cs["start_k"], cs["start_k"] + cs["class_count"]):
        cls = D.u64(P.rpm(h, S + D.CLASS_OFF + idx * 8, 8), 0)
        if not cls:
            continue
        cb = D.rpm_safe(h, cls, 0x100)
        if not cb:
            continue
        nm = D.cstr(h, D.u64(cb, N_OFF))
        names.setdefault(nm, cls)

    sm = names.get("SceneManager")
    D.hj(h, pid, rci, [sm], "init")
    print(f"SceneManager @0x{sm:x}")
    STATIC = 0x0010
    for meth in ("ChangeScene", "CreateWorld", "CreateCity", "DestroyCurScene",
                 "IsInWorld", "IsInCity", "set_CurrSceneID", "get_CurrSceneID"):
        row = f"  {meth}: "
        got = None
        for argc in range(0, 5):
            mi = D.hj(h, pid, gmfn, [sm, _s(h, meth), argc], "gmfn")
            if mi:
                got = (mi, argc)
                break
        if not got:
            print(row + "not found by name")
            continue
        mi, argc = got
        pc = D.hj(h, pid, gpc, [mi], "pc")
        fl = D.hj(h, pid, gfl, [mi], "fl") or 0
        print(row + f"MI=0x{mi:x} argc={argc} paramcount={pc} "
              f"flags=0x{fl:x} {'STATIC' if fl & STATIC else 'instance'}")

    # SceneID enum values
    sid = names.get("SceneID")
    if sid and gcf and gfn and gfv:
        D.hj(h, pid, rci, [sid], "init2")
        print(f"\nSceneID enum @0x{sid:x}:")
        it = S + 0x30
        P.WriteProcessMemory(h, C.c_void_p(it), b"\x00" * 8, 8,
                             C.byref(C.c_size_t(0)))
        val_slot = S + 0x40
        for _ in range(32):
            fld = D.hj(h, pid, gcf, [sid, it], "fld")
            if not fld:
                break
            fname = D.cstr(h, D.hj(h, pid, gfn, [fld], "fn") or 0)
            flags = D.hj(h, pid, gff, [fld], "ff") if gff else 0
            # static literal enum members only
            P.WriteProcessMemory(h, C.c_void_p(val_slot), b"\x00" * 8, 8,
                                 C.byref(C.c_size_t(0)))
            D.hj(h, pid, gfv, [fld, val_slot], "fv")
            val = D.u64(P.rpm(h, val_slot, 8), 0) & 0xFFFFFFFF
            print(f"    {fname} = {val}  (flags=0x{flags:x})")
    else:
        print("\nSceneID enum class not found or field API missing")

    P.VirtualFreeEx(h, C.c_void_p(S), 0, 0x8000)
    P.VirtualFreeEx(h, C.c_void_p(cr), 0, 0x8000)
    P.CloseHandle(h)


_strcache = {}


def _s(h, text):
    """Write an ASCII C-string into a scratch alloc, return its address."""
    if text in _strcache:
        return _strcache[text]
    a = int(P.VirtualAllocEx(h, None, 0x40, 0x3000, 0x04))
    P.WriteProcessMemory(h, C.c_void_p(a), text.encode() + b"\x00",
                         len(text) + 1, C.byref(C.c_size_t(0)))
    _strcache[text] = a
    return a


if __name__ == "__main__":
    main()
