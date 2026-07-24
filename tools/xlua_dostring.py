r"""Drive the game's xLua VM via LuaEnv.DoString — mutual-reference discovery.

Source-derived (Tencent/xLua, MIT — see docs/research/xlua-state.md §9):
  * LuaEnv has NO singleton (it is `new LuaEnv()`); fields rawL(lua_State),
    _G(LuaTable), translator(ObjectTranslator).
  * ObjectTranslator holds a back-reference `internal LuaEnv luaEnv;` and there is
    exactly one per LuaEnv.
So LuaEnv.translator and ObjectTranslator.luaEnv point at each other. That MUTUAL
link uniquely identifies the live pair among header-scan metadata noise — far more
robust than the one-directional signature check that found 0 hits (see §8), and it
needs no singleton and no XLuaManager.

Discovery:
  1. header-scan for ObjectTranslator instances (find_instance_rpm.scan);
  2. for each OT, read OT.luaEnv -> L; if L.translator == OT and clsname(L)=='LuaEnv'
     the pair is genuine.
Field offsets are resolved LIVE via il2cpp_field_get_offset (never source order —
this build reorders; §9.1).

All calls run RIP-gated on the attached main thread. Read-only recon + a guarded
DoString. Base must be idle.

!! UNTESTED since the game crash at the end of §8 — no live process was available
   to verify this path. Re-resolve every class pointer on the new pid first.

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
import find_instance_rpm as F


def a(s):
    """ASCII-safe: stdout here is cp1251; class/field names can be CJK."""
    return str(s).encode("ascii", "replace").decode("ascii")


def find_luaenv_via_translator(x, luaenv_cls):
    """Locate the live LuaEnv through the ObjectTranslator back-reference."""
    e, h = x.e, x.h
    # ObjectTranslator class (Assembly-CSharp, ns '') — resolved off the live enum
    ot_cls = F.resolve_class(h, x.pid, e, "ObjectTranslator")
    if not ot_cls:
        raise SystemExit("ObjectTranslator class not resolved")
    tr_off = x.foff(luaenv_cls, "translator")      # LuaEnv.translator offset
    le_off = x.foff(ot_cls, "luaEnv")              # ObjectTranslator.luaEnv offset
    print(f"ObjectTranslator cls=0x{ot_cls:x} LuaEnv.translator@0x{tr_off:x} "
          f"ObjectTranslator.luaEnv@0x{le_off:x}")
    if not (tr_off and le_off):
        raise SystemExit("could not resolve translator/luaEnv field offsets")

    def u(addr):
        b = D.rpm_safe(h, addr, 8)
        return D.u64(b, 0) if b else 0

    hits = F.scan(h, ot_cls, "ObjectTranslator")
    for ot in sorted(set(hits)):
        if ot_cls <= ot < ot_cls + 0x8000:        # inside the class struct
            continue
        if u(ot + 8) != 0:                         # monitor must be 0 for an object
            continue
        L = u(ot + le_off)                         # OT.luaEnv -> candidate LuaEnv
        if not (0x10000 < L < 0x7FFFFFFFFFFF) or (L & 7):
            continue
        if x.clsname(L) != "LuaEnv":
            continue
        if u(L + tr_off) == ot:                    # mutual link — decisive
            print(f"  MUTUAL: ObjectTranslator 0x{ot:x} <-> LuaEnv 0x{L:x}")
            return L
    return 0


def main():
    lua = None
    if "--lua" in sys.argv:
        lua = sys.argv[sys.argv.index("--lua") + 1]
    chunk = lua or 'CS.UnityEngine.Debug.Log("xlua_alive")'

    x = XR.X()
    lcls = x.find_luaenv_class()
    print(f"LuaEnv cls=0x{lcls:x}")

    luaenv = find_luaenv_via_translator(x, lcls)
    if not luaenv:
        raise SystemExit("no live LuaEnv found via ObjectTranslator back-reference")

    # signature confirm (offsets are live-resolved inside the finder already)
    g = x.clsname(D.u64(P.rpm(x.h, luaenv + x.foff(lcls, "_G"), 8), 0))
    tr = x.clsname(D.u64(P.rpm(x.h, luaenv + x.foff(lcls, "translator"), 8), 0))
    print(f"LuaEnv=0x{luaenv:x} _G={a(g)} translator={a(tr)}")

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
