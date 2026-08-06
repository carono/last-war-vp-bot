r"""Where a chunk's answer is written, and what it costs to write it there (task #1232).

A chunk reports its result by logging one line. On this build that goes through
`Debug.LogError`, and a chunk that logs ANYTHING through the game costs 50–120 ms more
than one that does not — the same whether it logs one line or five (135.1 ms against
134.3 on a 90.5 ms floor, measured live under #1232; 163 against 155 under #1230). A file
of our own costs nothing: five appends measure cheaper than one log line. The game has
already reacted by then, so what that time delays is everything queued behind the call —
the daemon's lock, the panel's claim, the next step of a recipe.

Two hundred and eighty chunks in this repository log their answer, and NOT ONE of them
changes: `lua_eval.wrap_chunk` swaps the `CS` they see for a table that forwards
everything except `UnityEngine.Debug`'s logging. That is a lot of behaviour resting on
one Lua preamble, so most of what is pinned here is run in an actual Lua VM (`lupa`,
which both interpreters have) against a stand-in `CS` — the chunk really runs, the
answer really lands in a file, and the real `Debug.LogError` really is not called.

What must hold, in order of how much it would hurt to lose:

  * the answer arrives, and only through the file;
  * a chunk that cannot write the file, or that raises, still answers — through the
    game's log, the way it always did, because this is the channel of EVERY chunk and it
    must not be able to go silent;
  * a chunk that installs a logger firing later can opt out, or the tracer's whole
    output would vanish into a file it does not read.

No game and no Windows.

    C:\Python312\python.exe tests\test_lua_answer_channel.py
    python3 tests/test_lua_answer_channel.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))
sys.path.insert(0, str(ROOT / "src"))

import lua_eval  # noqa: E402

try:
    import lupa                                     # noqa: E402
except ImportError:                                 # pragma: no cover - optional
    lupa = None


# -- a Lua VM with a stand-in CS ------------------------------------------------


class _Game:
    """A Lua VM that answers `CS.…` the way the client's does, and remembers.

    Only the three members a chunk can reach through the shim are real:
    `UnityEngine.Debug.LogError` (recorded — the point is that a wrapped chunk does NOT
    call it), `UnityEngine.Time.deltaTime` (a plain value, to prove the forwarding
    works) and `System.IO.File.AppendAllText` (which really appends). Everything else
    resolves to nil, exactly as an unbound type would.
    """

    def __init__(self, with_file: bool = True, append_fails: bool = False) -> None:
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.logged: list = []
        self.append_fails = append_fails
        g = self.lua.globals()
        g.CS = self.lua.eval("{ UnityEngine = { Debug = {}, Time = {} }, System = {} }")
        g.CS.UnityEngine.Debug.LogError = self._log_error
        g.CS.UnityEngine.Debug.LogWarning = self._log_error
        g.CS.UnityEngine.Time.deltaTime = 0.0169
        if with_file:
            g.CS.System = self.lua.eval("{ IO = { File = {} } }")
            g.CS.System.IO.File.AppendAllText = self._append

    def _log_error(self, message) -> None:
        self.logged.append(str(message))

    def _append(self, path, text) -> None:
        if self.append_fails:
            raise RuntimeError("the file is not writable")
        with open(str(path), "a", encoding="utf-8") as fh:
            fh.write(str(text))

    def run(self, chunk: str) -> None:
        """`SafeDoString`: compile and run, swallowing whatever went wrong."""
        try:
            self.lua.execute(chunk)
        except Exception:                           # noqa: BLE001 — so does the game
            pass


def _answers(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().splitlines()
    except OSError:
        return []


def _played(chunk: str, **game) -> tuple:
    """Wrap `chunk`, run it in a stand-in VM, return (file lines, Debug.LogError calls)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, lua_eval.ANSWER_FILE)
        vm = _Game(**game)
        vm.run(lua_eval.wrap_chunk(chunk, path))
        return _answers(path), vm.logged


def _needs_lua(name: str) -> bool:
    if lupa is None:
        print(f"       (skipped {name}: no lupa here — pip install lupa)")
        return False
    return True


# -- the answer arrives, and through the file -----------------------------------


def test_the_answer_lands_in_the_file_and_not_in_the_game_log():
    if not _needs_lua("the answer lands in the file"):
        return
    lines, logged = _played("CS.UnityEngine.Debug.LogError('ACT tap=ok')")
    assert lines == ["ACT tap=ok"], lines
    assert logged == [], f"the game's own log was written to anyway: {logged}"


def test_every_line_of_a_many_lined_answer_arrives_in_order():
    """A data tab logs a row per item; losing the tail would read as an empty account."""
    if not _needs_lua("a many-lined answer"):
        return
    lines, logged = _played(
        "for i = 1, 30 do CS.UnityEngine.Debug.LogError('ITEM n=' .. i) end")
    assert lines == ["ITEM n=%d" % i for i in range(1, 31)], lines[:3]
    assert logged == [], logged


def test_the_chunk_still_sees_the_rest_of_the_game():
    """The shim replaces the logging and nothing else — `CS.x` must still be `CS.x`."""
    if not _needs_lua("the rest of the game"):
        return
    lines, _ = _played("CS.UnityEngine.Debug.LogError("
                       "'LAT dt=' .. tostring(CS.UnityEngine.Time.deltaTime))")
    assert lines == ["LAT dt=0.0169"], lines


def test_a_chunk_that_returns_early_still_answers():
    """`return` at the top level of a chunk is ordinary; the wrapper must not eat it."""
    if not _needs_lua("an early return"):
        return
    lines, _ = _played("CS.UnityEngine.Debug.LogError('ACT gate=shut') "
                       "do return end "
                       "CS.UnityEngine.Debug.LogError('ACT unreachable')")
    assert lines == ["ACT gate=shut"], lines


def test_a_line_logged_after_the_chunk_has_finished_is_not_lost():
    """A chunk that installs a callback: the buffer is closed, so the line goes straight
    out rather than into a list nobody will ever flush."""
    if not _needs_lua("a late line"):
        return
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, lua_eval.ANSWER_FILE)
        vm = _Game()
        vm.run(lua_eval.wrap_chunk(
            "_G.later = function() CS.UnityEngine.Debug.LogError('ACT late=1') end "
            "CS.UnityEngine.Debug.LogError('ACT installed=1')", path))
        assert _answers(path) == ["ACT installed=1"], _answers(path)
        vm.lua.execute("later()")
        assert _answers(path) == ["ACT installed=1", "ACT late=1"], _answers(path)


# -- and it cannot go silent ----------------------------------------------------


def test_a_client_that_cannot_write_the_file_logs_to_the_game_instead():
    """`CS.System.IO` unbound. Slow, but an answer — and `run` reads Player.log when the
    private file stayed empty, so the caller never notices anything but the wait."""
    if not _needs_lua("no System.IO"):
        return
    lines, logged = _played("CS.UnityEngine.Debug.LogError('ACT tap=ok')",
                            with_file=False)
    assert lines == [], lines
    assert [ln.strip() for ln in logged] == ["ACT tap=ok"], logged


def test_a_failing_append_falls_back_to_the_game_log_too():
    if not _needs_lua("a failing append"):
        return
    lines, logged = _played("CS.UnityEngine.Debug.LogError('ACT tap=ok')",
                            append_fails=True)
    assert lines == [], lines
    assert [ln.strip() for ln in logged] == ["ACT tap=ok"], logged


def test_what_a_chunk_logged_before_it_raised_still_arrives():
    """`SafeDoString` swallows the error; the lines in front of it are still the answer."""
    if not _needs_lua("a raising chunk"):
        return
    lines, _ = _played("CS.UnityEngine.Debug.LogError('ACT step=1') "
                       "error('the manager is not loaded')")
    assert lines[0] == "ACT step=1", lines
    assert any("lua-error" in ln for ln in lines), lines


def test_the_error_line_carries_no_marker_so_no_caller_can_parse_it():
    """It is for a person reading the file. A caller asked for `ACT` lines and must not
    be handed a Lua traceback as one of them."""
    if not _needs_lua("the error line"):
        return
    lines, _ = _played("error('boom')")
    assert lines and "lua-error" in lines[0], lines
    assert not any(ln.startswith(("ACT", "DASH", "RLUA")) for ln in lines), lines


# -- opting out -----------------------------------------------------------------


def test_a_chunk_that_installs_a_logger_keeps_the_game_log():
    chunk = "-- LW_GAME_LOG: this one keeps firing after we return\nlocal L = CS"
    assert lua_eval.redirects(chunk) is False
    assert lua_eval.answer_path_for(chunk) == lua_eval.player_log_path()


def test_the_tracer_is_that_chunk():
    """The one in the tree. If its sentinel is ever lost, every traced call disappears
    into a file the tracer does not tail — and a recording looks simply empty."""
    sys.path.insert(0, str(ROOT / "tools"))
    import lua_trace                                # noqa: PLC0415
    install = lua_trace.install_chunk("Steal", 3, False)
    assert lua_eval.GAME_LOG_SENTINEL in install
    assert lua_eval.GAME_LOG_SENTINEL in lua_trace.RESTORE_CHUNK


def test_the_whole_channel_can_be_put_back_with_one_variable():
    was = os.environ.get("LW_ANSWER_CHANNEL")
    try:
        os.environ["LW_ANSWER_CHANNEL"] = "log"
        assert lua_eval.redirects("CS.UnityEngine.Debug.LogError('ACT x')") is False
        os.environ["LW_ANSWER_CHANNEL"] = "file"
        assert lua_eval.redirects("CS.UnityEngine.Debug.LogError('ACT x')") is True
    finally:
        os.environ.pop("LW_ANSWER_CHANNEL", None)
        if was is not None:
            os.environ["LW_ANSWER_CHANNEL"] = was


def test_by_default_the_answers_sit_beside_this_accounts_player_log():
    """Two clients are two Windows accounts with two LocalLow folders, which is what
    keeps two daemons from reading each other's answers — the same separation the logs
    already have, with nothing new to get wrong."""
    was = os.environ.get("LW_ANSWER_LOG")
    try:
        os.environ.pop("LW_ANSWER_LOG", None)
        assert (os.path.dirname(lua_eval.answer_log_path())
                == os.path.dirname(lua_eval.player_log_path()))
        assert lua_eval.answer_log_path() != lua_eval.player_log_path()
        os.environ["LW_ANSWER_LOG"] = os.path.join("X:", "elsewhere.log")
        assert lua_eval.answer_log_path() == os.path.join("X:", "elsewhere.log")
    finally:
        os.environ.pop("LW_ANSWER_LOG", None)
        if was is not None:
            os.environ["LW_ANSWER_LOG"] = was


# -- against the chunks the repository actually sends ---------------------------


def _real_chunks() -> dict:
    """Every chunk this repository can build without a game, by name.

    `lua_actions` is the bulk of them; the gated presses (`TAP … xall`) are the ones that
    read and press in one breath, and the dashboard's is the widest — thirteen readings,
    each in its own `pcall`. Builders that need a live reading to construct at all are
    skipped, which is what the live check is for
    (`tools/dev/check_gated_chunks.py`).
    """
    import inspect                                  # noqa: PLC0415
    import lua_actions                              # noqa: PLC0415

    out = {}
    for name, fn in sorted(vars(lua_actions).items()):
        if name.startswith("_") or not inspect.isfunction(fn):
            continue
        params = inspect.signature(fn).parameters.values()
        if any(p.default is p.empty and p.kind is not p.VAR_KEYWORD for p in params):
            continue
        try:
            chunk = fn()
        except Exception:                           # noqa: BLE001 — needs a game
            continue
        if isinstance(chunk, str) and "Debug.LogError" in chunk:
            out["lua_actions." + name] = chunk

    try:
        import game_buttons                         # noqa: PLC0415
        from lastwar_bot.script_engine import gated_chunk   # noqa: PLC0415
        for key, btn in game_buttons.BUTTONS.items():
            if btn.count_lua:
                out["gated:" + key] = gated_chunk(btn, 99)
    except Exception as exc:                        # noqa: BLE001
        out["gated:UNAVAILABLE " + str(exc)] = "CS.UnityEngine.Debug.LogError('x')"

    try:
        from panel import dashboard                 # noqa: PLC0415
        out["dashboard"] = dashboard.build_chunk()
    except Exception:                               # noqa: BLE001 — no Tk here
        pass
    return out


def test_every_chunk_the_repo_can_build_still_compiles_once_it_is_wrapped():
    """The whole risk of #1232 in one assertion.

    The wrapper puts the chunk inside a function, so anything a MAIN chunk may do and a
    function body may not would break it — and it would break it everywhere at once,
    silently, since `SafeDoString` swallows a compile error. So every chunk that can be
    built without a game is compiled in its wrapped form.
    """
    if not _needs_lua("compiling the real chunks"):
        return
    lua = lupa.LuaRuntime()
    compiles = lua.eval("function(s) local f, e = load(s) "
                        "if f then return true else return e end end")
    chunks = _real_chunks()
    assert len(chunks) > 40, f"only {len(chunks)} chunks were built — did an import die?"
    broken = {}
    for name, chunk in chunks.items():
        verdict = compiles(lua_eval.wrap_chunk(chunk, "C:\\lw\\lw_answers.log"))
        if verdict is not True:
            broken[name] = verdict
    assert not broken, broken


def test_a_chunk_that_needs_its_varargs_is_still_legal():
    """`...` is legal in a main chunk and in a vararg function, and nowhere else — which
    is why the wrapper's function takes them even though it is never passed any."""
    if not _needs_lua("varargs"):
        return
    lines, _ = _played("CS.UnityEngine.Debug.LogError('ACT n=' .. select('#', ...))")
    assert lines == ["ACT n=0"], lines


# -- housekeeping ---------------------------------------------------------------


def test_a_windows_path_survives_being_written_into_lua():
    """Backslashes, and every one of them an escape until it is doubled."""
    path = "C:\\Users\\somebody\\AppData\\LocalLow\\Pub\\Game\\lw_answers.log"
    wrapped = lua_eval.wrap_chunk("CS.UnityEngine.Debug.LogError('ACT x')", path)
    assert path.replace("\\", "\\\\") in wrapped, wrapped[:200]
    if not _needs_lua("the escaped path"):
        return
    written = {}
    vm = _Game(with_file=False)
    vm.lua.globals().CS.System = vm.lua.eval("{ IO = { File = {} } }")
    vm.lua.globals().CS.System.IO.File.AppendAllText = \
        lambda p, t: written.setdefault("path", str(p))
    vm.run(wrapped)
    assert written.get("path") == path, written


def test_the_answer_file_is_emptied_once_it_has_grown_too_big():
    """It is appended to for ever otherwise. Emptying happens between calls, never
    during one, and the byte offset the caller reads from moves with it."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, lua_eval.ANSWER_FILE)
        with open(path, "wb") as fh:
            fh.write(b"x" * (lua_eval.ANSWER_CAP // 2))
        assert lua_eval._empty_if_huge(path) == lua_eval.ANSWER_CAP // 2
        with open(path, "wb") as fh:
            fh.write(b"x" * (lua_eval.ANSWER_CAP + 1))
        assert lua_eval._empty_if_huge(path) == 0
        assert os.path.getsize(path) == 0


def test_a_chunk_that_never_ran_reads_as_no_answer_rather_than_as_an_error():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "not-there.log")
        assert lua_eval._empty_if_huge(path) == 0
        assert lua_eval.collect(path, 0, "ACT", 0.05) == []


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
