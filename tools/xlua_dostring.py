r"""Drive the game's xLua VM via LuaEnv.DoString — fixed instance discovery.

Supersedes the XLuaManager.get_Instance path in xlua_route.py (that accessor
returns null on this build — the singleton lives on a base MonoSingleton<T>).
This walks XLuaManager's parent chain, reads each STATIC field via
il2cpp_field_static_get_value, and takes the one whose value is a live
XLuaManager object; then LuaEnv = XLuaManager.get_Env(instance), validated by
its _G(LuaTable)/translator(ObjectTranslator) signature, then DoString(chunk).

All calls run RIP-gated on the attached main thread (see il2cpp-invoke-stability).
Read-only recon + a guarded DoString. Base must be idle.

    C:\Python312\python.exe tools\xlua_dostring.py                 # canary Debug.Log
    C:\Python312\python.exe tools\xlua_dostring.py --lua "print('x')"
"""
from __future__ import annotations
import ctypes as C
import sys

sys.path.insert(0, "tools")
import xlua_route as XR
import il2cpp_dump as D
import il2cpp_probe as P

GET_ENV_MI = 0x12a2fa4a8  # XLuaManager.get_Env (0-arg instance) — stable per game run


def a(s):
    """ASCII-safe: the stdout here is cp1251; class/field names can be CJK."""
    return str(s).encode("ascii", "replace").decode("ascii")


def main():
    lua = None
    if "--lua" in sys.argv:
        lua = sys.argv[sys.argv.index("--lua") + 1]
    chunk = lua or 'CS.UnityEngine.Debug.Log("xlua_test")'

    x = XR.X()
    e = x.e

    def alloc(n=8):
        p = int(P.VirtualAllocEx(x.h, None, n, 0x3000, 4))
        P.WriteProcessMemory(x.h, C.c_void_p(p), b"\x00" * n, n, C.byref(C.c_size_t(0)))
        return p

    lcls = x.find_luaenv_class()
    mgrcls = x.xluamgr_cls
    print(f"LuaEnv cls=0x{lcls:x} XLuaManager cls=0x{mgrcls:x}")

    # --- singleton discovery: static fields of XLuaManager and its parents ---
    found = None
    cls = mgrcls
    for depth in range(6):
        if not cls:
            break
        it = alloc(8)
        while True:
            f = x.hj(e["il2cpp_class_get_fields"], [cls, it], "fields")
            if not f:
                break
            fl = x.hj(e["il2cpp_field_get_flags"], [f], "ff")
            if not (fl & 0x10):  # FIELD_ATTRIBUTE_STATIC
                continue
            fnm = D.cstr(x.h, x.hj(e["il2cpp_field_get_name"], [f], "fn"))
            out = alloc(8)
            x.hj(e["il2cpp_field_static_get_value"], [f, out], "sget")
            val = D.u64(P.rpm(x.h, out, 8), 0)
            if not (0x10000 < val < 0x7FFFFFFFFFFF) or (val & 7):
                continue
            cn = x.clsname(val)
            if cn not in ("(null)", "(unreadable)", "(nonptr)"):
                print(f"  [d{depth}] static {a(fnm)} = 0x{val:x} [{a(cn)}]")
            if cn == "XLuaManager":
                found = val
        cls = x.hj(e["il2cpp_class_get_parent"], [cls], "parent")
    print(f"SINGLETON = {hex(found) if found else None}")
    if not found:
        raise SystemExit("no XLuaManager singleton via static fields")

    # --- LuaEnv via get_Env, validated by signature ---
    luaenv, exc = x.invoke(GET_ENV_MI, found, [], "get_Env")
    g = x.clsname(D.u64(P.rpm(x.h, luaenv + 0x10, 8), 0))
    tr = x.clsname(D.u64(P.rpm(x.h, luaenv + 0x18, 8), 0))
    print(f"get_Env -> 0x{(luaenv or 0):x} exc=0x{exc:x} cls={a(x.clsname(luaenv))} "
          f"_G={a(g)} translator={a(tr)}")
    if not (g == "LuaTable" and tr == "ObjectTranslator"):
        raise SystemExit("LuaEnv signature check failed")

    # --- DoString ---
    ds_mi, ds_pc = x.find_dostring_string(lcls)
    print(f"DoString mi=0x{ds_mi:x} params={ds_pc}")
    cs = x.il2_string_new(chunk)
    nm = x.il2_string_new("xlua_1017")
    args = [("ref", cs)]
    if ds_pc >= 2:
        args.append(("ref", nm))
    if ds_pc >= 3:
        args.append(("ref", 0))
    ret, de = x.invoke(ds_mi, luaenv, args, "DoString")
    print(f"DoString chunk={a(chunk)!r} ret=0x{(ret or 0):x} exc=0x{de:x} "
          f"-> {'OK' if not de else 'EXC'}")
    P.CloseHandle(x.h)
    return 0 if not de else 1


if __name__ == "__main__":
    sys.exit(main())
