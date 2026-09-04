r"""xLua route: drive the game's Lua VM from out of process.

The City->World transition lives in the game's Lua layer (xLua), not C#. This
tool finds the live XLua.LuaEnv, resolves LuaEnv.DoString, and runs Lua chunks
via a RIP-gated main-thread hijack (managed runtime_invoke). Read-only recon
(class/method/instance resolution, string_new) plus a guarded DoString.

Steps (per task #984):
  1. resolve XLua.LuaEnv class
  2. RPM-scan the heap for the live LuaEnv instance
  3. resolve LuaEnv.DoString overloads
  4. DoString a test chunk (proof of life)
  5+. run the world-open Lua

    C:\Python312\python.exe tools\xlua_route.py            # steps 1-4 (test chunk)
    C:\Python312\python.exe tools\xlua_route.py --lua "print('x')"
"""
from __future__ import annotations
import ctypes as C
import struct
import time
import sys

sys.path.insert(0, "tools/lib")
import il2cpp_probe as P
import il2cpp_dump as D
import hijack_call as H
import rip_gate as R
import find_instance_rpm as F

N_OFF = 0x48

#: The 0-argument `XLuaManager` getters that have been seen to hand back the live
#: `LuaEnv`, likeliest first. Names of a game class, not of this machine — a build that
#: renames the getter falls through to the walk below and the walk teaches the cache.
LUAENV_GETTERS = ("get_Env", "get_LuaEnv", "get_luaEnv", "GetEnv", "GetLuaEnv")

#: pid -> the getter name that answered on that client. Only the NAME is remembered,
#: never the LuaEnv pointer: a name is a fact about the build and cannot go stale while
#: the client runs, whereas a cached instance is a bet on the collector. Asking the live
#: client for the pointer costs one hijack, so there is nothing to win by guessing it.
_LUAENV_GETTER: dict = {}


class X:
    def __init__(self):
        try:  # game strings may be non-cp1251; keep console prints from crashing
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        self.pid = P.find_game_pid()
        self.gb, _ = P.module_base(self.pid, D.MODULE)
        self.h = P.OpenProcess(0x1FFFFF, False, self.pid)
        self.e = P.parse_exports(self.h, self.gb)
        self.mt = R.main_thread_tid(self.pid)
        if self.mt is None:
            # The main thread is found through the client's own WINDOW, so «no window»
            # and «no thread» are the same answer here — a client still on its loading
            # screen, one whose window has not appeared, or one on a desktop this
            # session cannot see. Said in a sentence because the alternative is what it
            # used to be: `argument 3: TypeError: 'NoneType' object cannot be
            # interpreted as an integer`, five times a minute, in the daemon's log.
            raise SystemExit(f"the client at pid {self.pid} has no window this session "
                             "can see, so its main thread cannot be found — nothing can "
                             "be run in it yet")
        self.sr = self._learn_park()
        self.sc = int(P.VirtualAllocEx(self.h, None, 0x400, 0x3000, 4))
        self._s = {}
        self._pinned = {}
        print(f"pid={self.pid} SAFE_RIP=0x{self.sr:x}")

    #: BUSY_MARK — how the panel tells «the client is busy» from every other reason
    #: nothing lands. It travels inside the message rather than as a type, because the
    #: message crosses a `SystemExit` through code that only ever reads its text.
    BUSY_MARK = "client-busy"

    #: One hijack's wait for the park. The gate itself is UNCHANGED — the thread is
    #: still only taken within ±16 bytes of the learned park — but how long we are
    #: prepared to wait for it to get there is not a safety property at all, and four
    #: seconds was written for a client sitting idle in the base. A client somebody is
    #: PLAYING parks for a few per cent of its samples, so four seconds is a coin toss
    #: and a build makes dozens of these calls: one refusal used to throw the whole
    #: evaluator away (#1994).
    PARK_WINDOW = 15.0

    #: …and how long a single step keeps trying across re-learns before it gives up.
    #: Spent only while the client is busy; a step that can be taken costs nothing.
    STEP_BUDGET = 60.0

    #: How often a step that is still waiting says so, so the log shows a panel that is
    #: WAITING rather than a panel that has gone quiet.
    SAY_EVERY = 20.0

    def busy(self, label: str, waited: float) -> SystemExit:
        """The refusal, in words that say what is happening and for how long."""
        return SystemExit(f"{self.BUSY_MARK}: {label}: the client's main thread is busy "
                          f"— it did not reach its park once in {waited:.0f}s, so nothing "
                          f"can be run in it yet")

    def _learn_park(self, budget: float = 30.0) -> int:
        """The main thread's parked RIP, waited for rather than sampled once.

        A busy client reaches the park a few per cent of the time, so a single sweep of
        40 samples can genuinely miss it — and answering «busy» off one miss is how a
        client that was perfectly takeable a second later got refused.
        """
        started = time.time()
        while True:
            got = R.learn_safe_rip(self.pid, self.mt, n=40)
            if got is not None:
                return got[0]
            if time.time() - started >= budget:
                raise self.busy("park", time.time() - started)
            time.sleep(0.5)

    def hj(self, func, args, label):
        """One gated hijack — retried, and with the park re-learned between tries.

        THE GATE IS NOT WIDENED, THE WAIT IS. Where the thread may be taken is what
        keeps the client alive (§1 of `docs/research/il2cpp-invoke-stability.md`), and
        that is untouched: ±16 bytes of the park, main thread only. What changes is that
        a step no longer gives up after one four-second look — it waits, re-learns the
        park in case the thread has moved to a different wait, and only calls the client
        busy after :data:`STEP_BUDGET`. A build of the evaluator makes dozens of these,
        so a per-step refusal used to be an all-or-nothing throw of the whole build.
        """
        started = time.time()
        said = 0.0
        tries = 0
        while True:
            tries += 1
            r = H.hijack_call(self.h, self.pid, func, args, label, save_xmm=True,
                              only_tid=self.mt, safe_rip=self.sr, rip_tol=16,
                              park_timeout=self.PARK_WINDOW)
            if r is not None:
                if tries > 1:
                    print(f"[{label}] taken on try {tries} after "
                          f"{time.time() - started:.0f}s of a busy client")
                return r
            waited = time.time() - started
            if waited >= self.STEP_BUDGET:
                raise self.busy(label, waited)
            fresh = R.learn_safe_rip(self.pid, self.mt, n=40)
            if fresh is not None and fresh[0] != self.sr:
                print(f"[{label}] re-learned SAFE_RIP 0x{self.sr:x} -> 0x{fresh[0]:x}")
                self.sr = fresh[0]
            if waited - said >= self.SAY_EVERY:
                said = waited
                print(f"[{label}] still waiting for the client's park — {waited:.0f}s")

    def cstr(self, t):
        if t not in self._s:
            b = t.encode("utf-8") + b"\x00"
            a = int(P.VirtualAllocEx(self.h, None, len(b), 0x3000, 4))
            P.WriteProcessMemory(self.h, C.c_void_p(a), b, len(b), C.byref(C.c_size_t(0)))
            self._s[t] = a
        return self._s[t]

    def clsname(self, obj):
        if not (0x10000 < obj < 0x7FFFFFFFFFFF) or (obj & 7):
            return "(null)"
        kb = D.rpm_safe(self.h, obj, 8)
        if not kb:
            return "(unreadable)"
        kls = D.u64(kb, 0)
        cb = D.rpm_safe(self.h, kls, 0x100) if 0x10000 < kls < 0x7FFFFFFFFFFF else None
        return D.cstr(self.h, D.u64(cb, N_OFF)) if cb else "(unreadable)"

    def il2_string_new(self, text):
        """Create a managed System.String via il2cpp_string_new (runs on main)."""
        return self.hj(self.e["il2cpp_string_new"], [self.cstr(text)], "string_new")

    def il2_string_pinned(self, text):
        """The same managed string every time, built ONCE per attach and rooted.

        A hijack is 0.22-0.32 s of the client's main thread (§2.1 of
        `docs/research/link-contention.md`) and a chunk pays three of them; one is
        always the same constant, the chunk name `DoString(byte[], string)` wants. So
        it is built once and kept.

        Keeping a managed pointer is only safe if something roots it: an object no
        handle names may be collected, and the address would then be another object's
        or nothing at all. `il2cpp_gchandle_new(obj, pinned=1)` does both jobs — it
        roots the string for the life of the attach AND forbids the collector moving
        it, so the pointer cached here stays this string. The handle is deliberately
        never freed: the attach ends when the client does.

        A client whose runtime refuses the handle gets the old behaviour — the string
        is used for THIS call and not remembered, which is correct but not cheap.
        """
        got = self._pinned.get(text)
        if got:
            return got
        s = self.il2_string_new(text)
        if not s:
            return s
        pin = self.e.get("il2cpp_gchandle_new")
        if not pin or not self.hj(pin, [s, 1], "gchandle:pin"):
            print(f"[xlua] could not pin {text!r} — rebuilding it every call")
            return s
        self._pinned[text] = s
        return s

    def gmfn(self, cls, name, argc):
        m = self.hj(self.e["il2cpp_class_get_method_from_name"],
                    [cls, self.cstr(name), argc], f"gmfn:{name}/{argc}")
        if not m:
            return 0, 0, 0
        fl = self.hj(self.e["il2cpp_method_get_flags"], [m], "fl")
        pc = self.hj(self.e["il2cpp_method_get_param_count"], [m], "pc")
        return m, fl, pc

    def foff(self, cls, name):
        fld = self.hj(self.e["il2cpp_class_get_field_from_name"],
                      [cls, self.cstr(name)], f"field:{name}")
        if not fld:
            return 0
        return self.hj(self.e["il2cpp_field_get_offset"], [fld], f"foff:{name}")

    def method_ret_type(self, mi):
        """Type name of a method's return type (read-only)."""
        t = self.hj(self.e["il2cpp_method_get_return_type"], [mi], "getret")
        if not t:
            return "?"
        nm = self.hj(self.e["il2cpp_type_get_name"], [t], "rettypename")
        return D.cstr(self.h, nm) if nm else "?"

    def method_named(self, cls, name, argc):
        """One hijack: the MethodInfo of `name`, or 0.

        :meth:`gmfn` asks for the flags and the parameter count as well, which is two
        more suspensions of the game's main thread than a caller that only means to
        CALL the method has any use for.
        """
        return self.hj(self.e["il2cpp_class_get_method_from_name"],
                       [cls, self.cstr(name), argc], f"gmfn:{name}/{argc}")

    def _getter_order(self):
        """Getter names to try, the one that answered on this client first."""
        seen = _LUAENV_GETTER.get(self.pid)
        return ([seen] if seen else []) + [n for n in LUAENV_GETTERS if n != seen]

    def _getter_result(self, mgr, mi, name):
        """Invoke a 0-arg getter on the manager; the plausible heap object, or 0."""
        cand, exc = self.invoke(mi, mgr, [], f"mgr.{name}")
        kls = D.u64(D.rpm_safe(self.h, cand, 8) or b"\x00" * 8, 0) if cand else 0
        print(f"    XLuaManager.{name}() -> 0x{cand:x} exc=0x{exc:x} clsptr=0x{kls:x}")
        # Trust the getter's il2cpp return type (LuaEnv, from metadata). The runtime
        # instance's class pointer differs from the metadata class (obfuscated build —
        # game class names don't decode), so we do NOT require kls==luaenv_cls; a
        # plausible heap pointer with exc==0 is it.
        if cand and not exc and 0x10000 < cand < 0x7FFFFFFFFFFF and not (cand & 7):
            return cand
        return 0

    def luaenv_via_manager_method(self, mgr, luaenv_cls):
        """The live LuaEnv off a 0-arg XLuaManager getter — ASKED BY NAME, walked last.

        **Every step of this suspends the game's main thread**, and that is what makes
        the walk below dangerous rather than merely slow: it costs 2–4 hijacks for each
        of up to 600 methods, about 180 per evaluator build, and the client crashes 4.5×
        more often in the five seconds after one (#2066,
        `docs/research/client-crashes.md`). Asking `il2cpp_class_get_method_from_name`
        for the getter costs THREE — the lookup, the return type and the call — and the
        name that answered is remembered for the life of this process, so the next build
        against the same client costs three again. `find_dostring` has asked by name
        first since #1994; this never did, and it is the larger of the two.

        The walk is kept as the fallback for a build that renames the getter, and a walk
        that finds one teaches :data:`_LUAENV_GETTER`, so the price is paid once.
        """
        for name in self._getter_order():
            mi = self.method_named(self.xluamgr_cls, name, 0)
            if not mi:
                continue
            if "LuaEnv" not in self.method_ret_type(mi):
                continue          # a getter of that name, but not of what we are after
            env = self._getter_result(mgr, mi, name)
            if env:
                _LUAENV_GETTER[self.pid] = name
                return env
        return self._luaenv_by_walking(mgr, luaenv_cls)

    def _luaenv_by_walking(self, mgr, luaenv_cls):
        """Every 0-arg XLuaManager method that returns a LuaEnv, tried in turn.

        The expensive way, and the only one left when the build has renamed its getter.
        Prefer getter-shaped names; a getter has no side effects.
        """
        print("    no named LuaEnv getter answered — walking XLuaManager (expensive)")
        gm = self.e["il2cpp_class_get_methods"]
        gmn = self.e["il2cpp_method_get_name"]
        gmpc = self.e["il2cpp_method_get_param_count"]
        it = int(P.VirtualAllocEx(self.h, None, 8, 0x3000, 4))
        P.WriteProcessMemory(self.h, C.c_void_p(it), b"\x00" * 8, 8, C.byref(C.c_size_t(0)))
        cands = []
        for _ in range(600):
            m = self.hj(gm, [self.xluamgr_cls, it], "iterMgrM")
            if not m:
                break
            if self.hj(gmpc, [m], "mpc") != 0:
                continue
            if "LuaEnv" not in self.method_ret_type(m):
                continue
            nmp = self.hj(gmn, [m], "mname")
            nm = D.cstr(self.h, nmp) if nmp else ""
            cands.append((m, nm))
        # getters first (get_*/Get*), then the rest
        cands.sort(key=lambda mn: 0 if mn[1][:3].lower() == "get" else 1)
        for m, nm in cands:
            env = self._getter_result(mgr, m, nm)
            if env:
                if nm:
                    _LUAENV_GETTER[self.pid] = nm
                return env
        return 0

    def method_param0_type(self, mi):
        """Type name of a method's first parameter (read-only)."""
        p = self.hj(self.e["il2cpp_method_get_param"], [mi, 0], "getparam0")
        if not p:
            return "?"
        nm = self.hj(self.e["il2cpp_type_get_name"], [p], "typename")
        return D.cstr(self.h, nm) if nm else "?"

    def il2_bytes_new(self, data: bytes):
        """Create a managed ``byte[]`` holding `data` (runs on main).

        The way a chunk reaches an encrypted-Lua build: its wrapper is arbitrary bytes
        (`tools/lib/lua_chunk_enc.py`), and the only string this side can build is one
        that will be UTF-8 encoded on the way into the VM — which mangles every byte
        above 0x7F. An array is handed over as it is written.
        """
        if not getattr(self, "_byte_cls", 0):
            corlib = self.hj(self.e["il2cpp_get_corlib"], [], "corlib")
            self._byte_cls = self.hj(self.e["il2cpp_class_from_name"],
                                     [corlib, self.cstr("System"), self.cstr("Byte")],
                                     "Byte cls")
            if not self._byte_cls:
                raise SystemExit("System.Byte not resolved — cannot build a byte[]")
            # Asked rather than assumed: the header is the object plus its bounds and
            # length, and il2cpp is the only thing entitled to say how big that is.
            self._arr_head = self.hj(self.e["il2cpp_array_object_header_size"], [],
                                     "array header")
        arr = self.hj(self.e["il2cpp_array_new"], [self._byte_cls, len(data)], "array_new")
        if not arr:
            raise SystemExit("il2cpp_array_new returned null")
        P.WriteProcessMemory(self.h, C.c_void_p(arr + self._arr_head), data, len(data),
                             C.byref(C.c_size_t(0)))
        return arr

    def find_dostring(self, cls, want="String"):
        """The DoString overload whose first parameter is `want`, and its param count.

        `want` is matched inside the il2cpp type name, so ``"String"`` picks the source
        overload and ``"Byte"`` the buffer one.

        **Asked by name first, and walked only if that misses.** Every step of this runs
        on the game's main thread through a gated hijack, and an evaluator is built by
        every thread that finds the daemon down — so a walk of a hundred methods is not a
        tidy way to do it twice, it is a hundred hijacks the rest of the panel is queuing
        behind. `get_method_from_name` costs three, and on this build it lands on the
        overload we want.
        """
        mi, _, _ = self.gmfn(cls, "DoString", 3)
        if mi and want in self.method_param0_type(mi):
            return mi, 3
        gm = self.e["il2cpp_class_get_methods"]
        gmn = self.e["il2cpp_method_get_name"]
        gmpc = self.e["il2cpp_method_get_param_count"]
        it = int(P.VirtualAllocEx(self.h, None, 8, 0x3000, 4))
        P.WriteProcessMemory(self.h, C.c_void_p(it), b"\x00" * 8, 8, C.byref(C.c_size_t(0)))
        found = []
        for _ in range(400):
            m = self.hj(gm, [cls, it], "iterM")
            if not m:
                break
            nmp = self.hj(gmn, [m], "mname")
            nm = D.cstr(self.h, nmp) if nmp else ""
            if nm != "DoString":
                continue
            pc = self.hj(gmpc, [m], "mpc")
            t0 = self.method_param0_type(m)
            print(f"    DoString overload MI=0x{m:x} params={pc} param0={t0}")
            found.append((m, pc, t0))
            if want in t0:
                break            # the walk is expensive; stop the moment it has answered
        for m, pc, t0 in found:
            if want in t0:
                return m, pc
        return (found[0][0], found[0][1]) if found else (0, 0)

    def find_dostring_string(self, cls):
        """The DoString overload that takes source — what a plain build is driven with."""
        return self.find_dostring(cls, "String")

    def find_dostring_bytes(self, cls):
        """The DoString overload that takes a buffer — what an encrypted build needs."""
        return self.find_dostring(cls, "Byte")

    def field_validity(self, obj, span=0x80):
        """Count how many qword fields (0x10..span) are valid heap-object
        pointers (deref -> class with a readable ASCII name). Real objects score
        high; metadata false-positives score ~0."""
        score = 0
        for off in range(0x10, span, 8):
            p = D.u64(P.rpm(self.h, obj + off, 8), 0)
            if not (0x10000 < p < 0x7FFFFFFFFFFF) or (p & 7):
                continue
            kls = D.u64(D.rpm_safe(self.h, p, 8) or b"\x00" * 8, 0)
            if not (0x10000 < kls < 0x7FFFFFFFFFFF):
                continue
            cb = D.rpm_safe(self.h, kls, 0x100)
            if not cb:
                continue
            nm = D.cstr(self.h, D.u64(cb, N_OFF))
            if nm and 2 <= len(nm) <= 60 and all(0x20 <= ord(c) < 0x7F for c in nm[:6]):
                score += 1
        return score

    def invoke(self, mi, obj, args, label="invoke"):
        """runtime_invoke(mi, obj, params, &exc). args: list of ('ref', ptr) or
        ('val', int32). Each param slot holds the argument value; params[i]
        points at that slot (il2cpp ABI, matches the value/ref path proven in
        click_world.py)."""
        if not mi:
            raise SystemExit(f"{label}: null MethodInfo")
        sc = self.sc
        P.WriteProcessMemory(self.h, C.c_void_p(sc), b"\x00" * 0x400, 0x400,
                             C.byref(C.c_size_t(0)))
        slot_base = sc + 0x20        # value-type arg storage (0x10 each)
        parr = sc + 0x200            # params[] array
        # il2cpp ABI: reference-type params[i] = the object pointer DIRECTLY;
        # value-type params[i] = a pointer to the value.
        for i, (kind, val) in enumerate(args):
            if kind == "val":
                slot = slot_base + i * 0x10
                P.WriteProcessMemory(self.h, C.c_void_p(slot), struct.pack("<i", val),
                                     4, C.byref(C.c_size_t(0)))
                entry = slot
            else:  # 'ref' — pass the object pointer (or 0 for null) directly
                entry = val
            P.WriteProcessMemory(self.h, C.c_void_p(parr + i * 8),
                                 struct.pack("<Q", entry), 8, C.byref(C.c_size_t(0)))
        pp = parr if args else 0
        ret = self.hj(self.e["il2cpp_runtime_invoke"], [mi, obj, pp, sc], label)
        exc = D.u64(P.rpm(self.h, sc, 8), 0)
        return ret, exc

    # --- step 1: LuaEnv class ------------------------------------------------
    def find_luaenv_class(self):
        S = int(P.VirtualAllocEx(self.h, None, D.REGION_SIZE, 0x3000, 0x40))
        cr = int(P.VirtualAllocEx(self.h, None, 0x2000, 0x3000, 0x40))
        P.WriteProcessMemory(self.h, C.c_void_p(S), b"\x00" * D.CLASS_OFF, D.CLASS_OFF,
                             C.byref(C.c_size_t(0)))
        code = D.build_dump_all(self.e, S)
        P.WriteProcessMemory(self.h, C.c_void_p(cr), code, len(code), C.byref(C.c_size_t(0)))
        self.hj(cr, [S, 100000, D.CLASS_CAP], "enum")
        na = D.u64(P.rpm(self.h, S, 8), 0)
        asms = D.read_asm_table(self.h, S, na)
        cs = next(x for x in asms if D.cstr(self.h, x["name_ptr"]) == "Assembly-CSharp")
        cls = self.hj(self.e["il2cpp_class_from_name"],
                      [cs["img"], self.cstr("XLua"), self.cstr("LuaEnv")], "LuaEnv cls")
        self.xluamgr_cls = self.hj(self.e["il2cpp_class_from_name"],
                                   [cs["img"], self.cstr(""), self.cstr("XLuaManager")], "XLuaManager")
        self.gameentry_cls = self.hj(self.e["il2cpp_class_from_name"],
                                     [cs["img"], self.cstr(""), self.cstr("GameEntry")], "GameEntry")
        P.VirtualFreeEx(self.h, C.c_void_p(S), 0, 0x8000)
        P.VirtualFreeEx(self.h, C.c_void_p(cr), 0, 0x8000)
        return cls

    def excdesc(self, exc):
        """Describe an il2cpp exception object: 'ClassName: message' or '-'."""
        if not exc:
            return "-"
        nm = self.clsname(exc).encode("ascii", "replace").decode()
        # System.Exception._message is an early string field; scan for it
        msg = ""
        for off in range(0x18, 0x60, 8):
            p = D.u64(P.rpm(self.h, exc + off, 8), 0)
            if 0x10000 < p < 0x7FFFFFFFFFFF and not (p & 7):
                kls = D.u64(D.rpm_safe(self.h, p, 8) or b"\x00" * 8, 0)
                cb = D.rpm_safe(self.h, kls, 0x100)
                if cb and D.cstr(self.h, D.u64(cb, N_OFF)) == "String":
                    ln = int.from_bytes(P.rpm(self.h, p + 0x10, 4), "little")
                    if 0 < ln < 200:
                        raw = P.rpm(self.h, p + 0x14, ln * 2)
                        msg = raw.decode("utf-16-le", "replace").encode("ascii", "replace").decode()
                        break
        return f"{nm}: {msg}"

    def setup_luaenv(self):
        """Steps 1-3: resolve XLua.LuaEnv, fetch the live instance via
        XLuaManager, validate it, and pick the DoString(string,...) overload.
        Stores self.luaenv / self.ds_mi / self.ds_pc for later dostring() calls."""
        luaenv_cls = self.find_luaenv_class()
        print(f"[1] XLua.LuaEnv class @0x{luaenv_cls:x}")
        # step 2 — live LuaEnv via XLuaManager.Instance (header-scan only finds
        # FieldInfo metadata). Validate by signature: _G=LuaTable, translator=ObjectTranslator.
        g_off = self.foff(luaenv_cls, "_G")
        tr_off = self.foff(luaenv_cls, "translator")
        print(f"[2] offsets _G=0x{g_off:x} translator=0x{tr_off:x}; via XLuaManager:")
        luaenv = self.luaenv_via_manager(luaenv_cls)
        if not luaenv:
            raise SystemExit("could not get LuaEnv via XLuaManager")
        g = self.clsname(D.u64(P.rpm(self.h, luaenv + g_off, 8), 0))
        tr = self.clsname(D.u64(P.rpm(self.h, luaenv + tr_off, 8), 0))
        print(f"    LuaEnv=0x{luaenv:x}  _G={g!r} translator={tr!r}")
        # NOTE: on this obfuscated build game class names don't decode (see
        # luaenv_via_manager_method) so this string signature check is advisory,
        # not a hard gate — the typed getter already vouches for the instance.
        if not (g == "LuaTable" and tr == "ObjectTranslator"):
            print("    (signature names undecodable on this build — trusting typed getter)")
        # step 3 — pick the overload this BUILD can be driven with: a build whose
        # loader wants its chunks wrapped takes them as bytes and only as bytes
        # (tools/lib/lua_chunk_enc.py).
        print("[3] DoString overloads:")
        import lua_chunk_enc
        self.enc = lua_chunk_enc.scheme()
        if self.enc is not None:
            print(f"    chunks are wrapped: {self.enc.describe()}")
        ds_mi, ds_pc = (self.find_dostring_bytes(luaenv_cls) if self.enc is not None
                        else self.find_dostring_string(luaenv_cls))
        if not ds_mi:
            raise SystemExit("DoString not found")
        print(f"    -> DoString(String) MI=0x{ds_mi:x} params={ds_pc}")
        self.luaenv, self.ds_mi, self.ds_pc = luaenv, ds_mi, ds_pc
        return luaenv, ds_mi, ds_pc

    def dostring(self, chunk, name="xlua_inject"):
        """Run a Lua chunk through the live LuaEnv.DoString. Returns (ret, exc).
        NOTE: LuaEnv.DoString does NOT swallow Lua errors (unlike XLuaManager
        .SafeDoString) — a bad chunk surfaces in the exc slot. Requires
        setup_luaenv() to have run first."""
        enc = getattr(self, "enc", None)
        chunk_s = (self.il2_bytes_new(enc.pack(chunk)) if enc is not None
                   else self.il2_string_new(chunk))
        name_s = self.il2_string_new(name)
        args = [("ref", chunk_s)]
        if self.ds_pc >= 2:
            args.append(("ref", name_s))
        if self.ds_pc >= 3:
            args.append(("ref", 0))
        return self.invoke(self.ds_mi, self.luaenv, args, f"DoString@0x{self.luaenv:x}")

    def luaenv_via_manager(self, luaenv_cls):
        """Get the real LuaEnv instance through the live XLuaManager's fields —
        header-scanning finds only FieldInfo metadata, not the live object. The
        manager is reached via the static facade GameEntry.get_Lua() (task #1017);
        XLuaManager.get_Instance is absent on this build."""
        m, fl, pc = self.gmfn(self.gameentry_cls, "get_Lua", 0)
        if not m or not (fl & 0x10):
            return 0
        mgr, exc = self.invoke(m, 0, [], "GameEntry.get_Lua")
        print(f"    GameEntry.get_Lua()=0x{mgr:x} exc=0x{exc:x} class={self.clsname(mgr)!r}")
        if not mgr or exc:
            return 0
        # Preferred: call a 0-arg XLuaManager getter that returns LuaEnv.
        via_m = self.luaenv_via_manager_method(mgr, luaenv_cls)
        if via_m:
            print(f"    LuaEnv via manager getter -> 0x{via_m:x}")
            return via_m
        # Fallback: scan the manager's fields for a LuaEnv object. Compare the
        # runtime class POINTER against the resolved LuaEnv class (exact) — matching
        # by decoded class-name string is unreliable (some names read as garbage).
        for off in range(0x10, 0x2000, 8):
            p = D.u64(P.rpm(self.h, mgr + off, 8), 0)
            if not (0x10000 < p < 0x7FFFFFFFFFFF) or (p & 7):
                continue
            kls = D.u64(D.rpm_safe(self.h, p, 8) or b"\x00" * 8, 0)
            if kls == luaenv_cls:
                print(f"    XLuaManager+0x{off:x} -> LuaEnv 0x{p:x}")
                return p
        return 0


def main():
    lua = None
    if "--lua" in sys.argv:
        lua = sys.argv[sys.argv.index("--lua") + 1]

    x = X()

    # steps 1-3: resolve the live LuaEnv and the DoString overload
    x.setup_luaenv()

    # step 4 — run a chunk via LuaEnv.DoString
    chunk = lua or "print('[[xlua-inject]] alive')"
    print(f"[4] DoString chunk={chunk!r}")
    ret, exc = x.dostring(chunk)
    print(f"    ret=0x{(ret or 0):x} exc[{x.excdesc(exc)}]")
    if not exc:
        print(f"    *** DoString OK on LuaEnv=0x{x.luaenv:x} — Lua VM driven ***")
    P.CloseHandle(x.h)
    return 0 if not exc else 1


if __name__ == "__main__":
    sys.exit(main())
