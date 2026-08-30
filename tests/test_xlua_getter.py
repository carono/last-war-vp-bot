r"""How the live `LuaEnv` is reached — asked by name, and walked only when it must be.

No game and no Windows: the il2cpp layer under `tools/lib/xlua_route.py` is replaced by
a stub that answers like a client would, and what is pinned is the number of MAIN-THREAD
HIJACKS the resolution costs. That number is the point (#2066,
`docs/research/client-crashes.md`): the client crashes 4.5x more often in the five
seconds after a hijack, and walking `XLuaManager` spent ~180 of them per evaluator build.

Run it anywhere::

    python3 tests/test_xlua_getter.py
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "lib"))

EXPORTS = ("il2cpp_class_get_method_from_name", "il2cpp_method_get_return_type",
           "il2cpp_type_get_name", "il2cpp_class_get_methods",
           "il2cpp_method_get_param_count", "il2cpp_method_get_name",
           "il2cpp_runtime_invoke", "il2cpp_method_get_flags")


def _stub_modules() -> None:
    """il2cpp_probe & co. open a live process at import; stand in for them."""
    probe = types.ModuleType("il2cpp_probe")
    probe.VirtualAllocEx = lambda *a, **k: 0x9000
    probe.WriteProcessMemory = lambda *a, **k: True
    probe.rpm = lambda *a, **k: b"\x00" * 8
    dump = types.ModuleType("il2cpp_dump")
    dump.MODULE = "GameAssembly.dll"
    dump.u64 = lambda b, off=0: 0x2000
    dump.rpm_safe = lambda *a, **k: b"\x00" * 8
    dump.cstr = lambda h, p: p if isinstance(p, str) else ""
    for name, mod in (("il2cpp_probe", probe), ("il2cpp_dump", dump),
                      ("hijack_call", types.ModuleType("hijack_call")),
                      ("rip_gate", types.ModuleType("rip_gate")),
                      ("find_instance_rpm", types.ModuleType("find_instance_rpm"))):
        sys.modules.setdefault(name, mod)


_stub_modules()
import xlua_route as XR                                            # noqa: E402

ENV = 0x1234_5678_0000            # a plausible heap pointer, 8-byte aligned


class FakeClient(XR.X):
    """An `X` over a made-up XLuaManager. `methods` maps a name to its return type."""

    def __init__(self, methods, pid=4242):
        self.pid = pid
        self.h = 1
        self.e = {name: i + 1 for i, name in enumerate(EXPORTS)}
        self._by_ptr = {v: k for k, v in self.e.items()}
        self.methods = list(methods.items())          # [(name, return type)]
        self.calls = []                               # every hijack, by label
        self.xluamgr_cls = 0x1000
        self._s = {}
        self._iter = 0

    # the string a name is passed as — the stub reads it back as itself
    def cstr(self, text):
        return text

    def hj(self, func, args, label):
        self.calls.append(label)
        what = self._by_ptr[func]
        if what == "il2cpp_class_get_method_from_name":
            _cls, name, argc = args
            for i, (nm, _rt) in enumerate(self.methods):
                if nm == name and argc == 0:
                    return i + 1
            return 0
        if what == "il2cpp_class_get_methods":
            self._iter += 1
            return self._iter if self._iter <= len(self.methods) else 0
        if what == "il2cpp_method_get_param_count":
            return 0
        if what == "il2cpp_method_get_name":
            return self.methods[args[0] - 1][0]
        if what == "il2cpp_method_get_return_type":
            return args[0]
        if what == "il2cpp_type_get_name":
            return self.methods[args[0] - 1][1]
        raise AssertionError(f"unexpected hijack {what}")

    def invoke(self, mi, obj, args, label="invoke"):
        self.calls.append(f"invoke:{label}")
        return (ENV if self.methods[mi - 1][1].endswith("LuaEnv") else 0), 0


def _walked(client) -> bool:
    return any(c in ("iterMgrM", "mpc", "mname") for c in client.calls)


ORDINARY = {"get_Env": "XLua.LuaEnv", "Init": "System.Void", "get_Name": "System.String"}


def test_named_getter_costs_a_handful_of_hijacks():
    XR._LUAENV_GETTER.clear()
    c = FakeClient(ORDINARY)
    assert c.luaenv_via_manager_method(0x2222, 0x3333) == ENV
    assert not _walked(c), c.calls
    assert len(c.calls) <= 5, c.calls        # lookup + return type (2) + the call


def test_a_renamed_getter_is_walked_once_and_remembered():
    XR._LUAENV_GETTER.clear()
    build = {"Boot": "System.Void", "Mystery": "XLua.LuaEnv"}
    first = FakeClient(build)
    assert first.luaenv_via_manager_method(0x2222, 0x3333) == ENV
    assert _walked(first), "an unknown name has to be walked for"
    assert XR._LUAENV_GETTER[first.pid] == "Mystery"

    second = FakeClient(build)                # same pid: the next evaluator build
    assert second.luaenv_via_manager_method(0x2222, 0x3333) == ENV
    assert not _walked(second), second.calls
    assert len(second.calls) <= 5, second.calls


def test_the_cache_is_per_client():
    XR._LUAENV_GETTER.clear()
    build = {"Boot": "System.Void", "Mystery": "XLua.LuaEnv"}
    FakeClient(build, pid=1).luaenv_via_manager_method(0x2222, 0x3333)
    other = FakeClient(build, pid=2)
    other.luaenv_via_manager_method(0x2222, 0x3333)
    assert _walked(other), "another client's name is not this client's"


def test_no_getter_at_all_is_zero_not_a_crash():
    XR._LUAENV_GETTER.clear()
    c = FakeClient({"Boot": "System.Void"})
    assert c.luaenv_via_manager_method(0x2222, 0x3333) == 0


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
