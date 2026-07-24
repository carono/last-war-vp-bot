r"""City<->World via the game's STATIC SceneManager (task #1017).

The game SceneManager is entirely static (no instance needed — bypasses the
managed instance-discovery wall, see docs/research/xlua-state.md §8). This resolves
everything at RUNTIME (il2cpp_class_from_name, validated by reading the class name
back — NEVER the dump JSON `addr`, which crashed the game in §8.3), reads the
current scene, and if in City fires ChangeScene(SceneID.World).

`runtime_invoke` BOXES value-type returns → the real value is at ret+0x10.
SceneID.World == 2 (confirmed: CurrSceneID==2 while IsInWorld==true).

    C:\Python312\python.exe tools\scene_change.py            # read-only: report state
    C:\Python312\python.exe tools\scene_change.py --fire     # fire ChangeScene(World) if in City
"""
from __future__ import annotations
import sys

sys.path.insert(0, "tools")
import xlua_route as XR
import il2cpp_dump as D
import il2cpp_probe as P
import ctypes as C

WORLD = 2  # SceneID.World


def a(s):
    return str(s).encode("ascii", "replace").decode("ascii")


def unbox_i32(x, mi, label):
    r, exc = x.invoke(mi, 0, [], label)          # static -> obj=0, no args
    v = None
    if r and 0x10000 < r < 0x7FFFFFFFFFFF:
        b = D.rpm_safe(x.h, r + 0x10, 8)
        if b:
            v = D.u64(b, 0) & 0xffffffff
    return v, exc


def main():
    fire = "--fire" in sys.argv
    x = XR.X()
    e = x.e

    # --- resolve the game SceneManager via a RUNTIME resolver, validate by name ---
    S = int(P.VirtualAllocEx(x.h, None, D.REGION_SIZE, 0x3000, 0x40))
    cr = int(P.VirtualAllocEx(x.h, None, 0x2000, 0x3000, 0x40))
    P.WriteProcessMemory(x.h, C.c_void_p(S), b"\x00" * D.CLASS_OFF, D.CLASS_OFF,
                         C.byref(C.c_size_t(0)))
    code = D.build_dump_all(e, S)
    P.WriteProcessMemory(x.h, C.c_void_p(cr), code, len(code), C.byref(C.c_size_t(0)))
    x.hj(cr, [S, 100000, D.CLASS_CAP], "enum")
    na = D.u64(P.rpm(x.h, S, 8), 0)
    asms = D.read_asm_table(x.h, S, na)
    cs = next(o for o in asms if D.cstr(x.h, o["name_ptr"]) == "Assembly-CSharp")
    cls = x.hj(e["il2cpp_class_from_name"],
               [cs["img"], x.cstr(""), x.cstr("SceneManager")], "SceneManager cls")
    if not cls:
        raise SystemExit("SceneManager class not resolved at runtime")
    name_back = a(D.cstr(x.h, D.u64(P.rpm(x.h, cls + 0x48, 8), 0)))
    print(f"SceneManager cls=0x{cls:x} name_readback={name_back!r}")
    if name_back != "SceneManager":
        raise SystemExit(f"class name validation FAILED: {name_back!r} != 'SceneManager'")

    # --- resolve the exact MethodInfos by name (fresh — addresses are pid-specific) ---
    def mfn(nm, argc):
        m = x.hj(e["il2cpp_class_get_method_from_name"],
                 [cls, x.cstr(nm), argc], f"mfn:{nm}/{argc}")
        if not m:
            raise SystemExit(f"method {nm}/{argc} not found")
        return m
    curr_mi = mfn("get_CurrSceneID", 0)
    inw_mi = mfn("IsInWorld", 0)
    inc_mi = mfn("IsInCity", 0)
    change_mi = mfn("ChangeScene", 1)

    # --- read current state ---
    curr, _ = unbox_i32(x, curr_mi, "get_CurrSceneID")
    inw, _ = unbox_i32(x, inw_mi, "IsInWorld")
    inc, _ = unbox_i32(x, inc_mi, "IsInCity")
    inw_b = (inw & 0xff) if inw is not None else None
    inc_b = (inc & 0xff) if inc is not None else None
    print(f"BEFORE: CurrSceneID={curr} IsInWorld={inw_b} IsInCity={inc_b}")

    if not fire:
        print("(read-only; pass --fire to ChangeScene(World) when in City)")
        P.CloseHandle(x.h)
        return 0

    if curr == WORLD:
        print("already in World (CurrSceneID==2) — not firing ChangeScene")
        P.CloseHandle(x.h)
        return 0

    print(f"firing ChangeScene(SceneID.World={WORLD}) ...")
    r, exc = x.invoke(change_mi, 0, [("val", WORLD)], "ChangeScene")
    print(f"  ChangeScene ret=0x{(r or 0):x} exc=0x{exc:x} -> {'OK' if not exc else 'EXC'}")
    import time
    time.sleep(2.0)
    curr2, _ = unbox_i32(x, curr_mi, "get_CurrSceneID")
    inw2, _ = unbox_i32(x, inw_mi, "IsInWorld")
    print(f"AFTER: CurrSceneID={curr2} IsInWorld={(inw2 & 0xff) if inw2 is not None else None}")
    P.CloseHandle(x.h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
