r"""The chat ear notices when the game drops it, and puts itself back (task #2418).

The listener is one hook inside the client's own Lua state. That state is rebuilt
without warning — a relogin, a client restart, a scene the game reloads — and the
wrapper goes with it. Nothing raises: the drain keeps succeeding, keeps reporting
nothing, and the panel goes on saying «слушаю» over a chat that stopped growing. On the
live panel that was one hole of 217 minutes in a day, with the reader process alive the
whole time and not one error written down — «чат не обновляется», exactly.

So the drain answers for the ear in the round trip it was already making. What is pinned
here runs in a real Lua VM (`lupa`, which both interpreters have) against a stand-in of
the two client classes the hook binds:

  * a freshly installed hook reports `H=1`, and records what arrives;
  * a Lua state that was rebuilt under it reports `H=0` — the ONE thing the old drain
    could not say, whatever else it printed;
  * installing again over the rebuilt state reports `H=1` and records again, and it
    wraps the LIVE method rather than the one saved before the reload;
  * a build with no `ChatRoomData` is not a lost ear (`H=1`), or the reader would
    reinstall for ever.

No game and no Windows.

    C:\Python312\python.exe tests\test_chat_hook_liveness.py
    python3 tests/test_chat_hook_liveness.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import chat_records                                     # noqa: E402

try:
    import lupa                                         # noqa: E402
except ImportError:                                     # pragma: no cover - optional
    lupa = None

#: The install chunk lives in the tool, because installing is what only the LISTENER
#: does; it is read out of it rather than copied, so this test cannot drift from it.
INSTALL = re.search(r'_INSTALL_LUA = chat_records\.record_lua\(\) \+ r"""(.*?)"""',
                    (ROOT / "tools" / "chat_reader.py").read_text(encoding="utf-8"),
                    re.S).group(1)

FAILED: list = []


def check(name: str, ok: bool, said: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (f" — {said}" if said else ""))
    if not ok:
        FAILED.append(name)


class Vm:
    """A Lua VM holding stand-ins for the two client classes the hook binds."""

    def __init__(self, *, with_room: bool = True) -> None:
        self.lines: list = []
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        say = self.lines.append
        self.lua.execute("""
        CS = {UnityEngine = {Debug = {}}}
        package = package or {}
        package.loaded = {}
        """)
        self.lua.globals().CS.UnityEngine.Debug.LogError = say
        self.reload(with_room=with_room)

    def reload(self, *, with_room: bool = True) -> None:
        """What a relogin does: brand-new class tables, and the panel is not told."""
        self.lua.execute("""
        package.loaded["Chat.Model.ChatMessage"] = {
          onParseServerData = function(self) _G.__seen = (_G.__seen or 0) + 1 end}
        """)
        if with_room:
            self.lua.execute("""
            package.loaded["Chat.Model.ChatRoomData"] = {
              __addChatData = function(self, data) end}
            """)
        else:
            self.lua.execute('package.loaded["Chat.Model.ChatRoomData"] = nil')

    def install(self) -> None:
        self.lines.clear()
        self.lua.execute(chat_records.record_lua() + INSTALL)

    def drain(self) -> list:
        self.lines.clear()
        self.lua.execute(chat_records.drain_lua(check_hook=True))
        return [str(x).strip() for x in self.lines]

    def hook_said(self) -> str:
        for line in self.drain():
            if line.startswith(chat_records.MARKER + " H="):
                return line.split("H=", 1)[1]
        return "<nothing>"

    def arrive(self) -> None:
        """One message reaches the client, through the method the hook wrapped.

        A `ChatMessage` is an object with getters, and the recorder calls every one of
        them — so the stand-in has them too. Invented values throughout: a real reply is
        somebody's account and never goes into this repository.
        """
        self.lua.execute("""
        local CM = package.loaded["Chat.Model.ChatMessage"]
        CM.onParseServerData({
          roomId = "world_1", seqId = 1, serverTime = 1000, post = 1, type = 1,
          senderUid = "1000000000000001",
          getMsg = function() return "hi" end,
          getMessageWithExtra = function() return "hi" end,
          isMySendChat = function() return false end,
          isShowTranslateBtn = function() return true end,
          getSenderName = function() return "Player1" end,
          getSenderInfo = function() return {allianceSimpleName = "AL1", lang = 1,
                                             gmFlag = 0, serverId = 1,
                                             headPic = 1, headPicVer = 1} end})
        """)

    def forget(self) -> None:
        """Forget how often the client's own method has been called, so far."""
        self.lua.execute("_G.__seen = 0")

    def buffered(self) -> int:
        return int(self.lua.eval("#(_G.__CR_BUF or {})"))


class _Ev:
    """A stand-in for the game link: it remembers which chunks were run."""

    def __init__(self, answers: list) -> None:
        self.answers = answers
        self.ran: list = []

    def run(self, chunk: str, marker: str = "", settle: float = 0.0) -> list:
        kind = ("install" if "onParseServerData = function" in chunk
                else "backlog" if "SEED rooms=" in chunk
                else "drain" if "drained; keep the buffer small" in chunk
                else "other")
        self.ran.append(kind)
        if kind != "drain":
            return []
        return self.answers.pop(0) if self.answers else ["N=0", "H=1"]


def reader_run(answers: list, seconds: float = 0.7) -> list:
    """Run the listener's own loop against `_Ev`, and say what it asked the game."""
    import chat_reader

    ev = _Ev(list(answers))
    was_get, was_argv = chat_reader.lua_client.get_evaluator, sys.argv
    chat_reader.lua_client.get_evaluator = lambda *a, **k: ev
    sys.argv = ["chat_reader.py", "--seconds", str(seconds), "--interval", "0.2"]
    try:
        chat_reader.main()
    finally:
        chat_reader.lua_client.get_evaluator = was_get
        sys.argv = was_argv
    return ev.ran


def main() -> int:
    if lupa is None:                                    # pragma: no cover
        print("lupa is not installed — nothing to run")
        return 0

    print("a freshly installed hook")
    vm = Vm()
    vm.install()
    check("says it is bound", vm.hook_said() == "1", vm.hook_said())
    vm.arrive()
    check("records what arrives", vm.buffered() == 1, f"{vm.buffered()} in the buffer")

    print("after the game rebuilds its Lua state")
    vm.drain()                                          # empty the buffer first
    vm.reload()
    vm.arrive()
    check("nothing is recorded any more", vm.buffered() == 0)
    check("and the drain SAYS so", vm.hook_said() == "0", vm.hook_said())

    print("installing again over the rebuilt state")
    vm.forget()
    vm.install()
    check("says it is bound", vm.hook_said() == "1", vm.hook_said())
    vm.arrive()
    check("records again", vm.buffered() == 1, f"{vm.buffered()} in the buffer")
    check("and calls the LIVE method, not the one saved before the reload",
          int(vm.lua.eval("_G.__seen or 0")) == 1)

    print("a build without the room class")
    lone = Vm(with_room=False)
    lone.install()
    check("is not a lost ear", lone.hook_said() == "1", lone.hook_said())

    print("and what the listener does about it")
    ran = reader_run([["N=0", "H=1"], ["N=0", "H=0"], ["N=0", "H=1"]])
    check("a drain that failed to say H=1 does not stop the draining",
          ran.count("drain") == 4, " ".join(ran))
    check("an ear the game dropped is put back", ran.count("install") == 2)
    check("…and the gap is read back from the client, twice: at the start and on the "
          "loss", ran.count("backlog") == 2, " ".join(ran))

    quiet = reader_run([["N=0", "H=1"], ["N=0", "H=1"], ["N=0", "H=1"]])
    check("a listener nobody dropped asks for no gap at all",
          quiet.count("backlog") == 1 and quiet.count("install") == 1,
          " ".join(quiet))

    print("\n%s" % ("ВСЁ ЗЕЛЁНОЕ" if not FAILED else "ПРОВАЛЫ: " + ", ".join(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
