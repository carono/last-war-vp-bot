"""DSL runtime for the `actions/*.md` script files.

Each `.md` file in ``src/lastwar_bot/actions/`` describes a high-level
skill in a small Russian-flavoured pseudo-language:

    Если находимся не на базе                # IF screen != base
      Клик на картинку базы [click_base_button]   # CALL action click_base_button
      Ждем пока база откроется               # WAIT until screen == base

Indentation (multiples of 2 spaces) defines nested blocks. References in
``[brackets]`` mean either a template (when ending in ``.png``) or
another action (otherwise). The text around the brackets is a human-
readable description — the parser only looks at keywords and the bracket.

Recognised keywords (case-insensitive):

- ``Если <condition>``  — IF on current screen state. ``Иначе`` for ELSE.
- ``Ищем картинку [X.png]`` — SIFT-find a template; nested block runs
  only on success and can use ``Кликаем`` to click the match.
- ``Клик на ... [action_name]`` — CALL another action by name.
- ``Кликаем`` — click the centre of the most recent successful FIND.
- ``Ждем пока <X> откроется`` — wait until ``identify_screen`` returns
  ``X`` (``база`` / ``мир``), with a timeout.
- ``Ждем N секунд`` — sleep N seconds.

Conditions recognise: ``на базе``, ``не на базе``, ``в мире`` /
``на карте мира`` and their negations. Add new ones by extending
``Interpreter.eval_condition``.

Failure semantics: every action returns True / False. Inner failures
(template not found, wait timed out, missing action file) propagate up
as ``False`` and are logged.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ACTIONS_DIR = Path(__file__).parent / "actions"

_BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")
_NUMBER_SEC_RE = re.compile(r"(\d+(?:\.\d+)?)\s*секунд")

EventCallback = Callable[[str], None]


# -- AST ---------------------------------------------------------------------


@dataclass(slots=True)
class _BaseStmt:
    text: str        # raw source line, for logging
    line_no: int


@dataclass(slots=True)
class IfStmt(_BaseStmt):
    condition: str
    then_block: list[Any] = field(default_factory=list)
    else_block: list[Any] = field(default_factory=list)


@dataclass(slots=True)
class FindStmt(_BaseStmt):
    template_name: str
    body: list[Any] = field(default_factory=list)


@dataclass(slots=True)
class ClickStmt(_BaseStmt):
    pass


@dataclass(slots=True)
class CallStmt(_BaseStmt):
    action_name: str


@dataclass(slots=True)
class WaitStmt(_BaseStmt):
    target: str       # 'base' / 'world' / 'seconds:<float>' / 'unknown'
    timeout: float = 10.0


@dataclass(slots=True)
class UnknownStmt(_BaseStmt):
    pass


# -- Parser ------------------------------------------------------------------


def parse_text(text: str) -> list[Any]:
    """Parse a script source string into a list of top-level statements."""
    raw = []
    for i, ln in enumerate(text.splitlines(), start=1):
        rstripped = ln.rstrip()
        if not rstripped.strip():
            continue
        indent = len(rstripped) - len(rstripped.lstrip())
        raw.append((indent, rstripped.strip(), i))
    statements, _ = _parse_block(raw, 0, 0)
    return statements


def parse_file(path: Path) -> list[Any]:
    return parse_text(path.read_text(encoding="utf-8"))


def _parse_block(lines: list[tuple[int, str, int]], i: int, base_indent: int) -> tuple[list[Any], int]:
    statements: list[Any] = []
    while i < len(lines):
        indent, _, _ = lines[i]
        if indent < base_indent:
            break
        if indent > base_indent:
            # Stray over-indent at top — caller picks it up via their own block.
            break
        stmt, i = _parse_line(lines, i, indent)
        statements.append(stmt)
    return statements, i


def _parse_line(lines: list[tuple[int, str, int]], i: int, indent: int) -> tuple[Any, int]:
    _, text, ln = lines[i]
    low = text.lower()

    # IF / ELSE
    if low.startswith("если "):
        condition = text[5:].strip()
        i += 1
        then_block, i = _parse_block(lines, i, indent + 2)
        else_block: list[Any] = []
        if i < len(lines) and lines[i][0] == indent and lines[i][1].lower().startswith("иначе"):
            i += 1
            else_block, i = _parse_block(lines, i, indent + 2)
        return IfStmt(text=text, line_no=ln, condition=condition,
                      then_block=then_block, else_block=else_block), i

    # FIND
    if low.startswith("ищем "):
        m = _BRACKET_RE.search(text)
        if m:
            tpl = m.group(1).strip()
            i += 1
            body, i = _parse_block(lines, i, indent + 2)
            return FindStmt(text=text, line_no=ln, template_name=tpl, body=body), i

    # CLICK / CALL via the "клик" verb
    if low.startswith("кликаем") or low.startswith("клик "):
        m = _BRACKET_RE.search(text)
        if m and not m.group(1).strip().lower().endswith(".png"):
            return CallStmt(text=text, line_no=ln, action_name=m.group(1).strip()), i + 1
        return ClickStmt(text=text, line_no=ln), i + 1

    # WAIT
    if low.startswith("ждем") or low.startswith("ждём"):
        return _parse_wait(text, ln), i + 1

    # Fallback: a bare bracket reference (template or action)
    m = _BRACKET_RE.search(text)
    if m:
        ref = m.group(1).strip()
        if ref.lower().endswith(".png"):
            i += 1
            body, i = _parse_block(lines, i, indent + 2)
            return FindStmt(text=text, line_no=ln, template_name=ref, body=body), i
        return CallStmt(text=text, line_no=ln, action_name=ref), i + 1

    return UnknownStmt(text=text, line_no=ln), i + 1


def _parse_wait(text: str, line_no: int) -> WaitStmt:
    low = text.lower()
    # "Ждем N секунд"
    m = _NUMBER_SEC_RE.search(low)
    if m:
        return WaitStmt(text=text, line_no=line_no, target=f"seconds:{m.group(1)}")
    # "Ждем пока база/мир откроется/появится/загрузится"
    if "баз" in low:
        return WaitStmt(text=text, line_no=line_no, target="base")
    if "мир" in low or "карт" in low:
        return WaitStmt(text=text, line_no=line_no, target="world")
    return WaitStmt(text=text, line_no=line_no, target="unknown")


# -- Interpreter -------------------------------------------------------------


@dataclass
class Context:
    hwnd: int
    on_event: EventCallback = field(default=lambda _msg: None)
    last_find: Any = None


class ScriptError(Exception):
    pass


class Interpreter:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._depth = 0

    def _log(self, msg: str) -> None:
        self.ctx.on_event("  " * self._depth + msg)

    def run_action(self, name: str) -> bool:
        path = ACTIONS_DIR / f"{name}.md"
        if not path.exists():
            self.ctx.on_event(f"!! action not found: {name} ({path})")
            return False
        self._log(f"> action: {name}")
        self._depth += 1
        try:
            statements = parse_file(path)
            self._run_block(statements)
            self._depth -= 1
            self._log(f"< action: {name} OK")
            return True
        except ScriptError as exc:
            self._depth -= 1
            self._log(f"< action: {name} FAILED — {exc}")
            return False

    # -- block / statement dispatch --

    def _run_block(self, statements: list[Any]) -> None:
        for stmt in statements:
            self._run_stmt(stmt)

    def _run_stmt(self, stmt: Any) -> None:
        if isinstance(stmt, IfStmt):
            cond = self.eval_condition(stmt.condition)
            self._log(f"IF {stmt.condition!r} → {cond}")
            self._depth += 1
            try:
                self._run_block(stmt.then_block if cond else stmt.else_block)
            finally:
                self._depth -= 1
        elif isinstance(stmt, FindStmt):
            self._do_find(stmt)
        elif isinstance(stmt, ClickStmt):
            self._do_click(stmt)
        elif isinstance(stmt, CallStmt):
            self._do_call(stmt)
        elif isinstance(stmt, WaitStmt):
            self._do_wait(stmt)
        elif isinstance(stmt, UnknownStmt):
            self._log(f"(skipped: {stmt.text})")
        else:
            self._log(f"(unhandled stmt: {stmt!r})")

    # -- primitives --

    def eval_condition(self, cond: str) -> bool:
        from .game.skills import navigate
        from .perception.capture import grab

        screen = navigate.identify_screen(grab(self.ctx.hwnd))
        low = cond.lower()
        if "не на базе" in low:
            return screen != "base"
        if "на базе" in low:
            return screen == "base"
        if "не в мире" in low or "не на карте" in low:
            return screen != "world"
        if "в мире" in low or "на карте" in low:
            return screen == "world"
        raise ScriptError(f"unknown condition: {cond!r}")

    def _do_find(self, stmt: FindStmt) -> None:
        from .game.skills.navigate import TEMPLATES_DIR
        from .perception import features
        from .perception.capture import grab

        path = TEMPLATES_DIR / stmt.template_name
        if not path.exists():
            raise ScriptError(f"template not found: {stmt.template_name}")
        scene = features.SceneIndex(grab(self.ctx.hwnd))
        match = scene.find_sift(path)
        if match is None or match.inliers < 4:
            self._log(f"FIND {stmt.template_name} → not found")
            return  # body not executed
        self.ctx.last_find = match
        self._log(f"FIND {stmt.template_name} → inliers={match.inliers} center={match.center}")
        self._depth += 1
        try:
            self._run_block(stmt.body)
        finally:
            self._depth -= 1

    def _do_click(self, stmt: ClickStmt) -> None:
        from .inputs import click

        match = self.ctx.last_find
        if match is None:
            raise ScriptError("CLICK without a prior successful FIND")
        cx, cy = match.center
        click(self.ctx.hwnd, cx, cy, mode="foreground")
        self._log(f"CLICK at ({cx}, {cy})")

    def _do_call(self, stmt: CallStmt) -> None:
        self._log(f"CALL {stmt.action_name}")
        sub = Interpreter(self.ctx)
        sub._depth = self._depth + 1
        if not sub.run_action(stmt.action_name):
            raise ScriptError(f"sub-action {stmt.action_name} failed")

    def _do_wait(self, stmt: WaitStmt) -> None:
        if stmt.target.startswith("seconds:"):
            seconds = float(stmt.target.split(":", 1)[1])
            self._log(f"WAIT {seconds}s")
            time.sleep(seconds)
            return
        target = stmt.target
        if target not in ("base", "world"):
            raise ScriptError(f"WAIT — unknown target {target!r}")

        from .game.skills import navigate
        from .perception.capture import grab

        deadline = time.monotonic() + stmt.timeout
        while time.monotonic() < deadline:
            screen = navigate.identify_screen(grab(self.ctx.hwnd))
            if screen == target:
                self._log(f"WAIT screen={target!r} → matched")
                return
            time.sleep(0.3)
        raise ScriptError(f"WAIT screen={target!r} timed out after {stmt.timeout:.1f}s")


def run_action(name: str, hwnd: int, on_event: EventCallback | None = None) -> bool:
    """Convenience: parse and execute the named action."""
    ctx = Context(hwnd=hwnd, on_event=on_event or (lambda _msg: None))
    return Interpreter(ctx).run_action(name)
