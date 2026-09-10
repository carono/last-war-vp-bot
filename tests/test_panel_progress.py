r"""A lifecycle press that DESCRIBES ITSELF — steps, seconds, and a final point (#2742).

The complaint this answers was not about a button. «Если я нажимая перезапустить игру, я
должен видеть прогресс что происходит с финальной точкой и когда все завершается, оно
гарантированно должно работать» — three separate demands, and each has its cases here:

  * the recipe names its own phases (`STEP <locale.key>` in the DSL) and the panel holds
    them: what has passed, what is running, how long each took;
  * a press ENDS with a sentence whichever way it goes — done, failed with the reason,
    or «never started, something else is driving the game», which is the one that used
    to be pure silence;
  * a run that came up without reaching the game is given one more launch before it is
    called a failure;
  * «игра не найдена» is not said about a client the panel is in the middle of starting;
  * and the watchdog's five-minute cooldown is stamped by a relaunch that HAPPENED,
    never by one the claim refused — three of 2026-09-10's outages were exactly that,
    298, 313 and 317 s of a dead client that nobody was putting back.

Nothing here touches Tk, the game or the network::

    python3 tests/test_panel_progress.py
    C:\Python312\python.exe tests\test_panel_progress.py
"""
from __future__ import annotations

TIER = "offline"      # no Tk, no display, no game — see tools/run_tests.py

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (str(_REPO), str(_REPO / "src"), str(_REPO / "tools"), str(_REPO / "tools" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lastwar_bot import script_engine as se           # noqa: E402
from panel.runtime import game_control, progress as progressmod  # noqa: E402

ACTIONS = _REPO / "src" / "lastwar_bot" / "actions"
LOCALES = _REPO / "panel" / "locales"

_fails: list = []


def _walk(stmts):
    """Every statement, including the ones inside an `IF`/`FIND`/`WHILE` block.

    The retry lives under an `IF`, which is exactly where a top-level scan would miss
    the one step this task added.
    """
    for stmt in stmts or ():
        yield stmt
        for field in ("then_block", "else_block", "body", "block"):
            child = getattr(stmt, field, None)
            if isinstance(child, list):
                yield from _walk(child)


def check(ok: bool, what: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        _fails.append(what)


# -- the object both front-ends draw ---------------------------------------
def test_progress_object() -> None:
    print("progress: begin, steps, the final point")
    p = progressmod.Progress()
    check(p.state() is None, "nothing pressed yet — nothing to draw")

    p.begin("restart", "game.restart")
    check(p.running() == "restart", "the press in flight is named")
    check(p.starting() is True, "a restart counts as «the client is being put up»")

    p.step("progress.game.quit")
    p.step("progress.game.start")
    state = p.state()
    check([s["state"] for s in state["steps"]] == ["done", "running"],
          "the step before the current one is done by definition")
    check(state["running"] is True and state["final"] is None,
          "a run in flight has no final point yet")

    p.finish(True, "progress.done")
    state = p.state()
    check(all(s["state"] == "done" for s in state["steps"]), "finishing closes the last step")
    check(state["ok"] is True and state["final"]["key"] == "progress.done",
          "the final point is there, and it is the one that was given")
    check(p.running() == "" and p.starting() is False, "and nothing is in flight any more")

    # A FAILURE CARRIES ITS STEP. «Не удалось» with no idea where is the sentence this
    # whole task exists to remove.
    p.begin("restart", "game.restart")
    p.step("progress.game.quit")
    p.step("progress.game.attach")
    p.finish(False, "progress.failed", reason="the client never came back")
    state = p.state()
    check([s["state"] for s in state["steps"]] == ["done", "failed"],
          "the step it stopped on is the one marked failed")
    check(state["final"]["fmt"]["reason"] == "the client never came back",
          "and the reason travels with it")

    # A run nobody began still describes itself: a scenario played by hand has `STEP`
    # lines too, and dropping them would make the panel's answer depend on who pressed.
    q = progressmod.Progress()
    q.step("progress.game.quit")
    check(q.state() is not None, "a STEP with no begin is kept, not dropped")

    # …and a finished run does not sit on the page for ever.
    old = progressmod.Progress()
    old.begin("launch", "game.launch")
    old.finish(True)
    old._ended -= progressmod.KEEP_SEC + 1        # noqa: SLF001 — the clock, in a test
    check(old.state() is None, "a run older than KEEP_SEC is not drawn")


# -- the DSL primitive ------------------------------------------------------
def test_step_primitive() -> None:
    print("STEP: a locale key, its numbers, and nobody listening")
    seen: list = []
    ctx = se.new_context(0, on_event=lambda _m: None,
                         on_step=lambda key, **fmt: seen.append((key, fmt)))
    ctx.vars["lap"] = 3
    ok = se.run_text('STEP progress.game.quit\nSTEP progress.sweep.lap n={lap}', ctx=ctx)
    check(ok, "a script of nothing but STEPs runs")
    check(seen == [("progress.game.quit", {}), ("progress.sweep.lap", {"n": "3"})],
          "the key and its filled-in numbers arrive")

    lines: list = []
    check(se.run_text('STEP progress.game.quit', ctx=se.new_context(
        0, on_event=lambda m: lines.append(m))),
        "…and a run with no listener plays it anyway")
    check(any("STEP progress.game.quit" in line for line in lines),
          "a STEP is in the log as well as in the progress")


# -- the recipes ------------------------------------------------------------
def test_lifecycle_recipes() -> None:
    print("the four lifecycle recipes name their phases")
    steps = {}
    for name in ("launch_game", "quit_game", "restart_game", "recover_from_kick"):
        stmts = se.parse_file(ACTIONS / f"{name}.md")
        steps[name] = [s.key for s in _walk(stmts) if isinstance(s, se.StepStmt)]
        check(bool(steps[name]), f"{name} says where it has got to")

    check("progress.game.quit" in steps["restart_game"]
          and "progress.game.attach" in steps["restart_game"]
          and "progress.game.in_play" in steps["restart_game"],
          "a restart names the close, the attach and the end")
    # THE GUARANTEE: a client that came up without reaching the game is given one more
    # launch before the run is called a failure.
    check("progress.game.retry" in steps["restart_game"],
          "…and a half-done restart has a second go")
    text = (ACTIONS / "restart_game.md").read_text(encoding="utf-8")
    check(text.count("CALL launch_game") == 2, "the retry is a second launch, not a wait")
    check("FAIL" in text, "and a second failure is still an honest FAIL")


# -- every word is a key, in every locale -----------------------------------
def test_words() -> None:
    print("the keys exist in all eleven locales")
    wanted = set()
    for name in ("launch_game", "quit_game", "restart_game", "recover_from_kick"):
        for stmt in _walk(se.parse_file(ACTIONS / f"{name}.md")):
            if isinstance(stmt, se.StepStmt):
                wanted.add(stmt.key)
    wanted |= {"progress.done", "progress.failed", "progress.busy",
               "progress.running", "progress.took", "progress.secs", "progress.ago",
               "game.st.starting", "game.st.session_starting",
               "log.game.watchdog_busy"}
    files = sorted(LOCALES.glob("*.json"))
    check(len(files) == 11, f"eleven locales ship ({len(files)} found)")
    for path in files:
        table = json.loads(path.read_text(encoding="utf-8"))
        missing = sorted(k for k in wanted if not table.get(k))
        check(not missing, f"{path.name}: nothing missing ({', '.join(missing) or 'ok'})")


# -- the press, from either front-end ---------------------------------------
class _FakeRT:
    """Just enough runtime for `game_control.play`: a log, a progress, a player."""

    def __init__(self, started: bool = True, outcome=None) -> None:
        self.progress = progressmod.Progress()
        self.said: list = []
        self._started = started
        self._outcome = outcome

    def say(self, tag, key, **fmt) -> None:
        self.said.append((tag, key))

    def play_async(self, name, args=None, *, tag="action", human=False,
                   on_result=None, **kw):
        if self._started and on_result is not None and self._outcome is not None:
            on_result(self._outcome)
        return self._started


class _Outcome:
    def __init__(self, ok: bool, reason: str = "") -> None:
        self.ok, self.reason = ok, reason


def test_press() -> None:
    print("a press begins the description and always ends it")
    rt = _FakeRT(started=True, outcome=_Outcome(True))
    answer = game_control.play(rt, game_control.RESTART, up=True)
    check(answer["ok"] is True, "the press is accepted")
    check(rt.progress.state()["final"]["key"] == "progress.done",
          "and it finishes with «готово»")

    rt = _FakeRT(started=True, outcome=_Outcome(False, "the client never came back"))
    game_control.play(rt, game_control.RESTART, up=True)
    state = rt.progress.state()
    check(state["ok"] is False and state["final"]["key"] == "progress.failed",
          "a failed run says so")
    check(state["final"]["fmt"]["reason"] == "the client never came back",
          "…with the recipe's own reason")

    # THE SILENCE THIS TASK IS ABOUT: `play_async` answers False when something else is
    # driving the client, and neither callback fires. Live on 2026-09-10 that was a
    # «перезапускаю клиент…» in the log followed by nothing at all.
    rt = _FakeRT(started=False)
    answer = game_control.play(rt, game_control.RESTART, up=True)
    check(answer["busy"] is True, "a refused press is reported busy")
    check(rt.progress.state()["final"]["key"] == "progress.busy",
          "and it is NOT silent — the progress says why nothing happened")


# -- the honest word --------------------------------------------------------
def test_starting_word() -> None:
    print("«игра не найдена» is not said about a client being started")
    from panel.runtime import game_process

    class _Found:
        running = False
        link = game_process.OFFLINE
        message = game_process.Message("game.st.not_found", "game not found")

    found = _Found()
    check(game_process.worded(found).key == "game.st.not_found",
          "with nothing in flight the sentence is unchanged")
    said = game_process.worded(found, starting=True)
    check(said.key == "game.st.starting", "a launch in flight changes the sentence")
    said = game_process.worded(found, starting=True, user="Player1")
    check(said.key == "game.st.session_starting" and said.fmt.get("user") == "Player1",
          "…and the session's half names the session")

    class _Up(_Found):
        running = True
        link = game_process.ONLINE
        message = game_process.Message("game.st.running_at", "online")

    check(game_process.worded(_Up(), starting=True).key == "game.st.running_at",
          "a client that IS running says what it always said")


# -- the cooldown -----------------------------------------------------------
def test_watchdog_cooldown() -> None:
    """A relaunch the claim refused must not spend the five-minute cooldown."""
    print("the watchdog's cooldown is stamped by a launch that happened")
    import inspect

    from panel.runtime import status as statusmod

    src = inspect.getsource(statusmod.StatusPoll._watchdog_check
                            if hasattr(statusmod, "StatusPoll")
                            else statusmod)
    # The stamp is inside the branch that saw a run START — read off the source rather
    # than by driving a whole poll, because the poll needs a client, a gate and a clock.
    check("if not self._relaunch(" in src and "self._watchdog_last = 0.0" in src,
          "a refused relaunch clears the latch instead of stamping it")
    after = src.split("if not self._relaunch(")[-1]
    check("self._watchdog_last = time.time()" in after,
          "…and the stamp is only reached when the run was accepted")
    check("log.game.watchdog_busy" in src, "and the refusal is said out loud")


def main() -> int:
    for test in (test_progress_object, test_step_primitive, test_lifecycle_recipes,
                 test_words, test_press, test_starting_word, test_watchdog_cooldown):
        test()
    print()
    if _fails:
        print(f"FAILED {len(_fails)}:")
        for line in _fails:
            print("  - " + line)
        return 1
    print("all good")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
