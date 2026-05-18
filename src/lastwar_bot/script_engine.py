"""DSL runtime for the high-level skill scripts in ``actions/*.md``.

Grammar (formal-ish, case-insensitive keywords):

    script     ::= ( comment | blank | statement )*
    comment    ::= "#" any text
    blank      ::= empty line
    statement  ::= if_stmt | find_stmt | click_stmt | call_stmt
                 | wait_stmt | log_stmt
    indent     ::= one level deeper than the parent (consistent within a block)

    if_stmt    ::= "IF" condition NEWLINE { indented statement }
                   [ "ELSE" NEWLINE { indented statement } ]
    find_stmt  ::= "FIND" template_file NEWLINE { indented statement }
    click_stmt ::= "CLICK"
    call_stmt  ::= "CALL" action_name
    wait_stmt  ::= "WAIT" condition [ "WITHIN" number [ "s" ] ]
    log_stmt   ::= "LOG" "\"" any text "\""

    condition  ::= screen_check | "FOUND" | "NOT FOUND"
    screen_check ::= "screen" ( "==" | "!=" ) screen_name
    screen_name  ::= "base" | "world" | "unknown"

    template_file ::= ident ".png"     (resolved under game/templates/)
    action_name   ::= ident            (resolved under actions/<name>.md)
    ident         ::= [A-Za-z0-9_]+

Implicit state during execution:

- ``LAST``       — the result of the most recent successful FIND.
                   Refreshed each time a FIND succeeds; consumed by
                   CLICK with no explicit target.
- ``screen``     — the current screen, computed fresh from the live
                   capture on every condition evaluation.
- ``FOUND``      — true when the immediately preceding FIND at the same
                   block level succeeded. (Not yet implemented — for
                   now use the nested-block form: ``FIND x.png`` with
                   indented children that run only on success.)

Failure model: every action returns True/False. A nested FIND that
matched nothing simply skips its body and the surrounding action keeps
running. WAIT timeouts, CLICK without a prior FIND, missing template /
action files, and unknown keywords all raise and propagate as failure.

See `docs/dsl.md` for the user-facing reference.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ACTIONS_DIR = Path(__file__).parent / "actions"

EventCallback = Callable[[str], None]


# ---- Tokens / patterns -----------------------------------------------------

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"

_IF_RE = re.compile(rf"^IF\s+(.+?)\s*$", re.IGNORECASE)
_ELSE_RE = re.compile(r"^ELSE\s*$", re.IGNORECASE)
_FIND_RE = re.compile(rf"^FIND\s+({_IDENT}\.png)\s*$", re.IGNORECASE)
_CLICK_RE = re.compile(r"^CLICK\s*$", re.IGNORECASE)
_CLICK_AT_RE = re.compile(
    r"^CLICK\s+\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*$",
    re.IGNORECASE,
)
_CALL_RE = re.compile(rf"^CALL\s+({_IDENT})\s*$", re.IGNORECASE)
_WAIT_RE = re.compile(
    rf"^WAIT\s+(.+?)(?:\s+WITHIN\s+(\d+(?:\.\d+)?)\s*s?)?\s*$",
    re.IGNORECASE,
)
_LOG_RE = re.compile(r'^LOG\s+"(.*)"\s*$', re.IGNORECASE)
_STOP_RE = re.compile(r"^STOP(?:\s+\"(.*)\")?\s*$", re.IGNORECASE)
_CLOSE_WINDOW_RE = re.compile(r"^CLOSE_WINDOW\s*$", re.IGNORECASE)
_READ_TEXT_RE = re.compile(
    rf"^READ_TEXT\s+\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)"
    rf"\s+INTO\s+profile\.({_IDENT})\s*$",
    re.IGNORECASE,
)

_SCREEN_CHECK_RE = re.compile(
    rf"^screen\s*(==|!=)\s*({_IDENT})\s*$", re.IGNORECASE,
)
_FIND_COND_RE = re.compile(
    rf"^FIND\s+({_IDENT}\.png)\s*$", re.IGNORECASE,
)
_PROFILE_CHECK_RE = re.compile(
    rf'^profile\.({_IDENT})\s*(==|!=)\s*"([^"]*)"\s*$', re.IGNORECASE,
)


# ---- AST -------------------------------------------------------------------


@dataclass(slots=True)
class _Stmt:
    text: str       # original source line (for log/trace)
    line_no: int


@dataclass(slots=True)
class IfStmt(_Stmt):
    condition: str
    then_block: list[Any] = field(default_factory=list)
    else_block: list[Any] = field(default_factory=list)


@dataclass(slots=True)
class FindStmt(_Stmt):
    template_name: str
    body: list[Any] = field(default_factory=list)


@dataclass(slots=True)
class ClickStmt(_Stmt):
    # When set, click absolute client coords (x, y). When None, click the
    # centre of the most recent successful FIND (the LAST register).
    coords: tuple[int, int] | None = None


@dataclass(slots=True)
class ReadTextStmt(_Stmt):
    region: tuple[int, int, int, int]
    target_field: str  # written into Context.profile.data[target_field]


@dataclass(slots=True)
class CallStmt(_Stmt):
    action_name: str


@dataclass(slots=True)
class WaitStmt(_Stmt):
    condition: str
    timeout: float = 10.0


@dataclass(slots=True)
class LogStmt(_Stmt):
    message: str


@dataclass(slots=True)
class StopStmt(_Stmt):
    """Set the halt flag and bubble out of the entire action stack."""
    reason: str | None = None


@dataclass(slots=True)
class CloseWindowStmt(_Stmt):
    """Send WM_CLOSE to the game window (no force-kill)."""


# ---- Errors ----------------------------------------------------------------


class ScriptParseError(Exception):
    pass


class ScriptRuntimeError(Exception):
    pass


# ---- Parser ----------------------------------------------------------------


def parse_text(text: str) -> list[Any]:
    """Tokenise a script source string and return the top-level statements."""
    lines: list[tuple[int, str, int]] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        rstripped = raw.rstrip()
        stripped = rstripped.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(rstripped) - len(stripped)
        lines.append((indent, stripped, i))
    statements, _ = _parse_block(lines, 0, 0)
    return statements


def parse_file(path: Path) -> list[Any]:
    return parse_text(path.read_text(encoding="utf-8"))


def _parse_block(lines, i, base_indent):
    statements: list[Any] = []
    while i < len(lines):
        indent, _, _ = lines[i]
        if indent < base_indent:
            break
        if indent > base_indent:
            # An over-indented line that doesn't belong to a parent — the
            # parser hit this without a preceding compound statement. Treat
            # as a parse error so the user sees something concrete.
            _, text, ln = lines[i]
            raise ScriptParseError(
                f"line {ln}: unexpected indent (no block to attach to): {text!r}"
            )
        stmt, i = _parse_one(lines, i, indent)
        statements.append(stmt)
    return statements, i


def _parse_one(lines, i, indent):
    _, text, ln = lines[i]

    m = _IF_RE.match(text)
    if m:
        cond = m.group(1).strip()
        # Child block sits at a *strictly* greater indent. We don't fix the
        # step (2 or 4 spaces) — just require >, and reuse it for siblings.
        i += 1
        then_block, i = _parse_indented_block(lines, i, indent, ln)
        else_block: list[Any] = []
        if i < len(lines) and lines[i][0] == indent and _ELSE_RE.match(lines[i][1]):
            i += 1
            else_block, i = _parse_indented_block(lines, i, indent, ln)
        return IfStmt(text=text, line_no=ln, condition=cond, then_block=then_block, else_block=else_block), i

    m = _FIND_RE.match(text)
    if m:
        tpl = m.group(1)
        i += 1
        body, i = _parse_indented_block(lines, i, indent, ln, required=False)
        return FindStmt(text=text, line_no=ln, template_name=tpl, body=body), i

    m = _CLICK_AT_RE.match(text)
    if m:
        return ClickStmt(
            text=text, line_no=ln, coords=(int(m.group(1)), int(m.group(2)))
        ), i + 1
    if _CLICK_RE.match(text):
        return ClickStmt(text=text, line_no=ln), i + 1

    m = _READ_TEXT_RE.match(text)
    if m:
        x, y, w, h = (int(m.group(i)) for i in range(1, 5))
        return ReadTextStmt(
            text=text, line_no=ln,
            region=(x, y, w, h),
            target_field=m.group(5),
        ), i + 1

    m = _CALL_RE.match(text)
    if m:
        return CallStmt(text=text, line_no=ln, action_name=m.group(1)), i + 1

    m = _WAIT_RE.match(text)
    if m:
        cond = m.group(1).strip()
        timeout = float(m.group(2)) if m.group(2) is not None else 10.0
        return WaitStmt(text=text, line_no=ln, condition=cond, timeout=timeout), i + 1

    m = _LOG_RE.match(text)
    if m:
        return LogStmt(text=text, line_no=ln, message=m.group(1)), i + 1

    m = _STOP_RE.match(text)
    if m:
        return StopStmt(text=text, line_no=ln, reason=m.group(1)), i + 1

    if _CLOSE_WINDOW_RE.match(text):
        return CloseWindowStmt(text=text, line_no=ln), i + 1

    raise ScriptParseError(f"line {ln}: unrecognised statement: {text!r}")


def _parse_indented_block(lines, i, parent_indent, parent_line, required=True):
    """Parse a child block — statements whose indent > parent_indent.

    If `required` is True and the very next line is not indented further,
    raise a parse error. Used by IF/ELSE; FIND treats the body as optional.
    """
    if i >= len(lines) or lines[i][0] <= parent_indent:
        if required:
            raise ScriptParseError(
                f"line {parent_line}: expected an indented block underneath"
            )
        return [], i
    child_indent = lines[i][0]
    return _parse_block(lines, i, child_indent)


# ---- Interpreter -----------------------------------------------------------


@dataclass
class Context:
    hwnd: int
    on_event: EventCallback = field(default=lambda _msg: None)
    last_find: Any = None
    halt: bool = False
    halt_reason: str | None = None
    profile: Any = None  # `lastwar_bot.profile.Profile` instance, or None


class _HaltSignal(Exception):
    """Raised by STOP to unwind every enclosing block / sub-action.

    The signal is caught at the outermost `run_action` boundary. The
    actual reason and `halt=True` flag live in the shared Context so the
    caller (e.g. the runner) can react after execution returns.
    """


class Interpreter:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._depth = 0

    def _log(self, msg: str) -> None:
        self.ctx.on_event("  " * self._depth + msg)

    # ---- entry point ----

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
        except _HaltSignal:
            self._depth -= 1
            self._log(f"< action: {name} HALTED ({self.ctx.halt_reason or 'no reason given'})")
            return True
        except (ScriptParseError, ScriptRuntimeError) as exc:
            self._depth -= 1
            self._log(f"< action: {name} FAILED — {exc}")
            return False

    # ---- block / statement dispatch ----

    def _run_block(self, statements: list[Any]) -> None:
        for stmt in statements:
            self._run_stmt(stmt)

    def _run_stmt(self, stmt: Any) -> None:
        match stmt:
            case IfStmt():
                result = self.eval_condition(stmt.condition, stmt.line_no)
                self._log(f"IF {stmt.condition} -> {result}")
                self._depth += 1
                try:
                    self._run_block(stmt.then_block if result else stmt.else_block)
                finally:
                    self._depth -= 1
            case FindStmt():
                self._do_find(stmt)
            case ClickStmt():
                self._do_click(stmt)
            case CallStmt():
                self._do_call(stmt)
            case WaitStmt():
                self._do_wait(stmt)
            case LogStmt():
                self._log(f'LOG "{stmt.message}"')
            case StopStmt():
                self.ctx.halt = True
                self.ctx.halt_reason = stmt.reason or f"STOP at line {stmt.line_no}"
                self._log(f"STOP -> halt requested ({self.ctx.halt_reason})")
                raise _HaltSignal()
            case CloseWindowStmt():
                self._do_close_window(stmt)
            case ReadTextStmt():
                self._do_read_text(stmt)

    # ---- conditions ----

    def eval_condition(self, cond: str, line_no: int) -> bool:
        up = cond.strip().upper()
        if up == "FOUND":
            return self.ctx.last_find is not None
        if up == "NOT FOUND":
            return self.ctx.last_find is None

        m = _SCREEN_CHECK_RE.match(cond)
        if m:
            op = m.group(1)
            wanted = m.group(2).lower()
            current = self._current_screen()
            if op == "==":
                return (current or "unknown") == wanted
            return (current or "unknown") != wanted

        m = _FIND_COND_RE.match(cond)
        if m:
            return self._find_template_inline(m.group(1))

        m = _PROFILE_CHECK_RE.match(cond)
        if m:
            field_name = m.group(1)
            op = m.group(2)
            expected = m.group(3)
            actual = ""
            if self.ctx.profile is not None:
                actual = str(self.ctx.profile.get(field_name, ""))
            return (actual == expected) if op == "==" else (actual != expected)

        raise ScriptRuntimeError(f"line {line_no}: unknown condition: {cond!r}")

    def _find_template_inline(self, template_name: str) -> bool:
        """Run an ad-hoc FIND and update ``ctx.last_find``.

        Used by `FIND x.png` when it appears as a condition (in IF or
        WAIT) — distinct from the FIND statement, which has a body. A
        successful inline find leaves the match in LAST so the next
        statement can CLICK it.
        """
        from .game.skills.navigate import TEMPLATES_DIR
        from .perception import features
        from .perception.capture import grab

        path = TEMPLATES_DIR / template_name
        if not path.exists():
            raise ScriptRuntimeError(f"template not found: {template_name}")
        scene = features.SceneIndex(grab(self.ctx.hwnd))
        match = scene.find_sift(path)
        if match is None or match.inliers < 4:
            self.ctx.last_find = None
            self._log(f"(inline FIND {template_name} -> not found)")
            return False
        self.ctx.last_find = match
        self._log(f"(inline FIND {template_name} -> inliers={match.inliers} center={match.center})")
        return True

    def _current_screen(self) -> str | None:
        from .game.skills import navigate
        from .perception.capture import grab

        screen = navigate.identify_screen(grab(self.ctx.hwnd))
        self._log(f"(screen = {screen!r})")
        return screen

    # ---- primitives ----

    # Number of capture+match attempts inside a single FIND. SIFT matching
    # has a stochastic component (RANSAC + ratio-test cutoff right at the
    # 4-inlier floor), and a transient animation can briefly hide enough
    # keypoints. A couple of quick retries paper over both without changing
    # script semantics.
    _FIND_RETRIES: int = 3
    _FIND_RETRY_DELAY: float = 0.2

    def _do_find(self, stmt: FindStmt) -> None:
        from .game.skills.navigate import TEMPLATES_DIR
        from .perception import features
        from .perception.capture import grab

        path = TEMPLATES_DIR / stmt.template_name
        if not path.exists():
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: template not found: {stmt.template_name}"
            )

        match = None
        for attempt in range(1, self._FIND_RETRIES + 1):
            scene = features.SceneIndex(grab(self.ctx.hwnd))
            match = scene.find_sift(path)
            if match is not None and match.inliers >= 4:
                break
            if attempt < self._FIND_RETRIES:
                time.sleep(self._FIND_RETRY_DELAY)

        if match is None or match.inliers < 4:
            self.ctx.last_find = None
            self._log(f"FIND {stmt.template_name} -> not found (after {self._FIND_RETRIES} attempts)")
            return  # body skipped
        self.ctx.last_find = match
        self._log(f"FIND {stmt.template_name} -> inliers={match.inliers} center={match.center}")
        self._depth += 1
        try:
            self._run_block(stmt.body)
        finally:
            self._depth -= 1

    def _do_click(self, stmt: ClickStmt) -> None:
        from .inputs import click

        if stmt.coords is not None:
            cx, cy = stmt.coords
            click(self.ctx.hwnd, cx, cy, mode="foreground")
            self._log(f"CLICK at ({cx}, {cy})  [absolute]")
            return

        match = self.ctx.last_find
        if match is None:
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: CLICK without a preceding successful FIND"
            )
        cx, cy = match.center
        click(self.ctx.hwnd, cx, cy, mode="foreground")
        self._log(f"CLICK at ({cx}, {cy})")

    def _do_read_text(self, stmt: ReadTextStmt) -> None:
        if self.ctx.profile is None:
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: READ_TEXT INTO profile.* requires "
                "an active profile (start the bot with --profile <id>)"
            )
        from .perception.capture import grab
        from .perception.ocr import read_text

        img = grab(self.ctx.hwnd)
        text = read_text(img, stmt.region)
        self.ctx.profile.set(stmt.target_field, text)
        x, y, w, h = stmt.region
        self._log(
            f"READ_TEXT ({x}, {y}, {w}, {h}) -> profile.{stmt.target_field} = {text!r}"
        )

    def _do_call(self, stmt: CallStmt) -> None:
        self._log(f"CALL {stmt.action_name}")
        sub = Interpreter(self.ctx)
        sub._depth = self._depth + 1
        ok = sub.run_action(stmt.action_name)
        # A STOP inside the sub-action set ctx.halt. Re-raise so the chain
        # unwinds up to the outermost run_action boundary.
        if self.ctx.halt:
            raise _HaltSignal()
        if not ok:
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: sub-action {stmt.action_name} failed"
            )

    def _do_close_window(self, stmt: CloseWindowStmt) -> None:
        import win32con
        import win32gui

        win32gui.PostMessage(self.ctx.hwnd, win32con.WM_CLOSE, 0, 0)
        self._log("CLOSE_WINDOW -> WM_CLOSE posted")

    def _do_wait(self, stmt: WaitStmt) -> None:
        # Special case: "WAIT N" or "WAIT Ns" → fixed sleep.
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*s?\s*$", stmt.condition, re.IGNORECASE)
        if m:
            seconds = float(m.group(1))
            self._log(f"WAIT {seconds}s")
            time.sleep(seconds)
            return

        # Otherwise, poll the condition until True or timeout.
        deadline = time.monotonic() + stmt.timeout
        while time.monotonic() < deadline:
            if self.eval_condition(stmt.condition, stmt.line_no):
                self._log(f"WAIT {stmt.condition} -> matched")
                return
            time.sleep(0.3)
        raise ScriptRuntimeError(
            f"line {stmt.line_no}: WAIT {stmt.condition} timed out after {stmt.timeout:.1f}s"
        )


def run_action(
    name: str,
    hwnd: int,
    on_event: EventCallback | None = None,
    profile: Any = None,
) -> bool:
    """Convenience: parse and execute the named action.

    `profile` is an optional `lastwar_bot.profile.Profile` instance that
    becomes available to scripts as the ``profile.<field>`` namespace
    (read via conditions, write via ``READ_TEXT ... INTO profile.<field>``).
    """
    ctx = Context(hwnd=hwnd, on_event=on_event or (lambda _msg: None), profile=profile)
    return Interpreter(ctx).run_action(name)
