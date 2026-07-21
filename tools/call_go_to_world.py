r"""Call the world-transition entry point through the client's own il2cpp.

Discovery result (tools/il2cpp_dump.py + _scene_probe/_sig_probe):
    SceneManager.ChangeScene(SceneID)   public static, 1 arg   <-- go.to.world
    SceneManager.CreateWorld()          public static, 0 args
    SceneManager.CreateCity()           public static, 0 args
    SceneManager.IsInWorld()/IsInCity() public static, bool
    enum SceneID { None = 0, City = 1, World = 2 }

Because this hardened il2cpp keeps NO inline compiled methodPointer in
MethodInfo, we do NOT jump to a raw address. We invoke the MethodInfo* through
il2cpp_runtime_invoke, which is the engine's own, ABI-correct call path:

    il2cpp_runtime_invoke(method, obj, void** params, Il2CppException** exc)

For a static method obj = NULL. ChangeScene takes one value-type (enum/int)
argument, so params[0] points to the raw int32 (2 = World) — value types are
passed by pointer-to-value, not boxed.

SAFETY: this MUTATES live game state (moves the player to the world map) and is
executed on a hijacked game thread. It is gated behind --fire and only runs when
the game is up. Default (no flag) is a dry run: it just resolves and prints the
plan. The XMM-preserving hijack shellcode is used so float/vector regs survive.

    C:\Python312\python.exe tools\call_go_to_world.py                    # dry (safe)
    C:\Python312\python.exe tools\call_go_to_world.py --fire             # ChangeScene(World)
    C:\Python312\python.exe tools\call_go_to_world.py --scene city --fire
    C:\Python312\python.exe tools\call_go_to_world.py --scene world --create --fire
"""
from __future__ import annotations
import ctypes as C
import struct
import sys

sys.path.insert(0, "tools")
import il2cpp_probe as P
import il2cpp_dump as D
import hijack_call as H

N_OFF = 0x48
# enum SceneID { None = 0, City = 1, World = 2 }
SCENE_ID = {"world": 2, "city": 1}


def hjx(h, pid, func, args, label):
    """XMM-preserving hijack call."""
    return H.hijack_call(h, pid, func, args, label, save_xmm=True)


def resolve(h, pid, exp):
    """Return (SceneManager cls, dict method->MI)."""
    S = int(P.VirtualAllocEx(h, None, D.REGION_SIZE, 0x3000, 0x40))
    cr = int(P.VirtualAllocEx(h, None, 0x2000, 0x3000, 0x40))
    P.WriteProcessMemory(h, C.c_void_p(S), b"\x00" * D.CLASS_OFF, D.CLASS_OFF,
                         C.byref(C.c_size_t(0)))
    code = D.build_dump_all(exp, S)
    P.WriteProcessMemory(h, C.c_void_p(cr), code, len(code),
                         C.byref(C.c_size_t(0)))
    na = 0
    for _ in range(4):
        P.WriteProcessMemory(h, C.c_void_p(S), b"\x00" * D.CLASS_OFF, D.CLASS_OFF,
                             C.byref(C.c_size_t(0)))
        D.hj(h, pid, cr, [S, 100000, D.CLASS_CAP], "enum")
        na = D.u64(P.rpm(h, S, 8), 0)
        if na:
            break
    asms = D.read_asm_table(h, S, na)
    cs = next(e for e in asms if D.cstr(h, e["name_ptr"]) == "Assembly-CSharp")
    sm = None
    for idx in range(cs["start_k"], cs["start_k"] + cs["class_count"]):
        cls = D.u64(P.rpm(h, S + D.CLASS_OFF + idx * 8, 8), 0)
        if not cls:
            continue
        cb = D.rpm_safe(h, cls, 0x100)
        if cb and D.cstr(h, D.u64(cb, N_OFF)) == "SceneManager":
            sm = cls
            break
    D.hj(h, pid, exp["il2cpp_runtime_class_init"], [sm], "init")
    gmfn = exp["il2cpp_class_get_method_from_name"]

    def mi(name, argc):
        return D.hj(h, pid, gmfn, [sm, _cstr(h, name), argc], "gmfn")

    methods = {
        "ChangeScene": mi("ChangeScene", 1),
        "CreateWorld": mi("CreateWorld", 0),
        "CreateCity": mi("CreateCity", 0),
        "IsInWorld": mi("IsInWorld", 0),
        "IsInCity": mi("IsInCity", 0),
    }
    P.VirtualFreeEx(h, C.c_void_p(S), 0, 0x8000)
    P.VirtualFreeEx(h, C.c_void_p(cr), 0, 0x8000)
    return sm, methods


_strs = {}


def _cstr(h, text):
    if text in _strs:
        return _strs[text]
    a = int(P.VirtualAllocEx(h, None, 0x40, 0x3000, 0x04))
    P.WriteProcessMemory(h, C.c_void_p(a), text.encode() + b"\x00",
                         len(text) + 1, C.byref(C.c_size_t(0)))
    _strs[text] = a
    return a


def invoke_static(h, pid, exp, method_mi, arg_i32=None):
    """il2cpp_runtime_invoke(method, NULL, params, &exc) for a static method."""
    ri = exp["il2cpp_runtime_invoke"]
    scratch = int(P.VirtualAllocEx(h, None, 0x100, 0x3000, 0x04))
    # layout: [0x00]=exc*  [0x10]=int arg  [0x20]=params[0]
    P.WriteProcessMemory(h, C.c_void_p(scratch), b"\x00" * 0x100, 0x100,
                         C.byref(C.c_size_t(0)))
    params_ptr = 0
    if arg_i32 is not None:
        P.WriteProcessMemory(h, C.c_void_p(scratch + 0x10),
                             struct.pack("<i", arg_i32), 4,
                             C.byref(C.c_size_t(0)))
        P.WriteProcessMemory(h, C.c_void_p(scratch + 0x20),
                             struct.pack("<Q", scratch + 0x10), 8,
                             C.byref(C.c_size_t(0)))
        params_ptr = scratch + 0x20
    exc_ptr = scratch + 0x00
    ret = hjx(h, pid, ri, [method_mi, 0, params_ptr, exc_ptr], "invoke")
    exc = D.u64(P.rpm(h, exc_ptr, 8), 0)
    P.VirtualFreeEx(h, C.c_void_p(scratch), 0, 0x8000)
    return ret, exc


def _arg(name, default):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    fire = "--fire" in sys.argv
    use_create = "--create" in sys.argv or "--create-world" in sys.argv
    scene = _arg("--scene", "world").lower()
    if scene not in SCENE_ID:
        print(f"unknown --scene {scene!r} (use world|city)")
        return 2
    try:
        pid = P.find_game_pid()
    except SystemExit:
        print("LastWar.exe not running — start the game first.")
        return 1
    gbase, _ = P.module_base(pid, D.MODULE)
    h = P.OpenProcess(0x1FFFFF, False, pid)
    exp = P.parse_exports(h, gbase)

    sm, m = resolve(h, pid, exp)
    print(f"SceneManager @0x{sm:x}")
    for k, v in m.items():
        print(f"  {k}: MI={'0x%x' % v if v else 'MISSING'}")

    inworld = D.hj(h, pid, m["IsInWorld"], [], "isw") if m["IsInWorld"] else None
    incity = D.hj(h, pid, m["IsInCity"], [], "isc") if m["IsInCity"] else None
    print(f"  IsInWorld()={inworld}  IsInCity()={incity}")

    create_m = "CreateWorld" if scene == "world" else "CreateCity"
    if use_create:
        target = f"{create_m}()"
    else:
        target = f"ChangeScene(SceneID.{scene.capitalize()}={SCENE_ID[scene]})"
    print(f"\nPlan: invoke SceneManager.{target} via il2cpp_runtime_invoke "
          f"(XMM-preserving hijack).")

    if not fire:
        print("DRY RUN — pass --fire to actually perform the transition "
              "(mutates live game state).")
        P.CloseHandle(h)
        return 0

    print("FIRING ...")
    if use_create:
        ret, exc = invoke_static(h, pid, exp, m[create_m])
    else:
        ret, exc = invoke_static(h, pid, exp, m["ChangeScene"], SCENE_ID[scene])
    print(f"  runtime_invoke ret=0x{(ret or 0):x}  exception=0x{exc:x}"
          f"{'  (!! exception thrown)' if exc else ''}")
    inworld2 = D.hj(h, pid, m["IsInWorld"], [], "isw2")
    incity2 = D.hj(h, pid, m["IsInCity"], [], "isc2")
    print(f"  IsInWorld() now = {inworld2}  IsInCity() now = {incity2}")
    P.CloseHandle(h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
