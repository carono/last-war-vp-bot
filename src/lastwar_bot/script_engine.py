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
    scan_stmt  ::= "SCAN_SECRET_MISSIONS" { scan_opt }
    scan_opt   ::= "LEVEL" number | "STAR" | "CAN_LOOT"
                 | "FREE_SLOTS" number | "WITHIN" number [ "s" ]

    condition  ::= screen_check | "FOUND" | "NOT FOUND" | missions_check
    missions_check ::= "missions.count" ("=="|"!="|">="|"<="|">"|"<") number
    screen_check ::= "screen" ( "==" | "!=" ) screen_name
    screen_name  ::= "base" | "world" | "unknown"

    template_file ::= ident ".png"     (resolved under game/templates/)
    action_name   ::= ident            (resolved under actions/<name>.md)
    ident         ::= [A-Za-z0-9_]+

Implicit state during execution:

- ``LAST``       — the result of the most recent successful FIND.
                   Refreshed each time a FIND succeeds; consumed by
                   CLICK with no explicit target.
- ``MISSIONS``   — secret tasks from the most recent
                   SCAN_SECRET_MISSIONS, read off the wire rather than
                   the screen. Queried with ``missions.count``.
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
Two statements end a run deliberately: ``STOP`` ends it as a *success*
(the scenario decided it is done), while ``FAIL`` (also spelled ``RETURN
FAIL``) ends it as a *failure* — the run returns False, which a timer
turns into "not run" and retries later. Use FAIL for a precondition the
scenario cannot meet right now (``IF scene != city`` → ``FAIL``).

See `docs/dsl.md` for the user-facing reference.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ACTIONS_DIR = Path(__file__).parent / "actions"
# Untested / experimental actions live under actions/dev/. The blessed, verified ones
# sit directly in actions/ (only what the panel's Scenarios list should offer). Both
# are runnable — resolve_action() looks in the blessed dir first, then dev.
DEV_ACTIONS_DIR = ACTIONS_DIR / "dev"

EventCallback = Callable[[str], None]


def resolve_action(name: str) -> Path | None:
    """Locate an action script by name: blessed `actions/` first, then `actions/dev/`."""
    for base in (ACTIONS_DIR, DEV_ACTIONS_DIR):
        path = base / f"{name}.md"
        if path.exists():
            return path
    return None


# ---- Tokens / patterns -----------------------------------------------------

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"

_IF_RE = re.compile(rf"^IF\s+(.+?)\s*$", re.IGNORECASE)
_ELSE_RE = re.compile(r"^ELSE\s*$", re.IGNORECASE)
_WHILE_RE = re.compile(
    rf"^WHILE\s+(.+?)(?:\s+LIMIT\s+(\d+))?\s*$",
    re.IGNORECASE,
)
_FIND_RE = re.compile(rf"^FIND\s+({_IDENT}\.png)\s*$", re.IGNORECASE)
_PRESS_RE = re.compile(rf"^PRESS\s+({_IDENT})\s*$", re.IGNORECASE)
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
# FAIL ends the run as a FAILURE (unlike STOP, which ends it as a clean success):
# `run_action`/`run_text` return False, which a timer turns into a retry. `RETURN
# FAIL` is accepted as a synonym so the intent reads either way; an optional quoted
# reason lands in the log.
_FAIL_RE = re.compile(r'^(?:RETURN\s+)?FAIL(?:\s+"(.*)")?\s*$', re.IGNORECASE)
_CLOSE_WINDOW_RE = re.compile(r"^CLOSE_WINDOW\s*$", re.IGNORECASE)
_LAUNCH_RE = re.compile(r'^LAUNCH\s+"([^"]+)"\s*$', re.IGNORECASE)
# The other half of a restart: end the client, and re-point the warm Lua link at the
# one that comes back. CLOSE_WINDOW asks a window politely and LAUNCH starts a process;
# neither can end a client that is wedged, and neither knows that the link into the game
# VM is bound to a process id. See docs/dsl.md "Restarting the client".
_QUIT_GAME_RE = re.compile(r"^QUIT_GAME\s*$", re.IGNORECASE)
_ATTACH_GAME_RE = re.compile(
    r"^ATTACH_GAME(?:\s+WITHIN\s+(\d+(?:\.\d+)?)\s*s?)?\s*$", re.IGNORECASE)
# The opening half of the same story. LAUNCH spawns a process HERE, which is right for
# one account and wrong for two: a profile whose client lives in another Windows
# session (tools/rdp_instance.py) would get a third client on this desktop. START_GAME
# starts it where the profile says it lives. See docs/dsl.md "Restarting the client".
_START_GAME_RE = re.compile(
    r'^START_GAME(?:\s+"([^"]+)")?(?:\s+WITHIN\s+(\d+(?:\.\d+)?)\s*s?)?\s*$',
    re.IGNORECASE)

#: How long ATTACH_GAME waits for the daemon to resolve the new client, when the
#: script does not say. Resolving one is an il2cpp enumeration through a thread
#: hijack — seconds on a warm machine, and it is retried while the client finishes
#: settling, so the default is generous rather than tight.
ATTACH_TIMEOUT_SEC = 120.0
#: How long a QUIT_GAME waits for the client to actually disappear.
QUIT_TIMEOUT_SEC = 30.0
#: How long a START_GAME into ANOTHER Windows session waits for the client to appear.
#: Only that route waits at all — a launch on this desktop is fire-and-forget, and the
#: recipe's own `WAIT scene == city` is what says the base is up. Generous because a
#: cold start behind a launcher update is minutes.
START_TIMEOUT_SEC = 300.0
_READ_TEXT_RE = re.compile(
    rf"^READ_TEXT\s+\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)"
    rf"\s+INTO\s+profile\.({_IDENT})\s*$",
    re.IGNORECASE,
)
# SCAN_SECRET_MISSIONS [LEVEL n] [STAR] [CAN_LOOT] [FREE_SLOTS n] [WITHIN Ns]
# Modifiers are order-independent, hence the scan-then-parse split below
# rather than one positional regex.
_SCAN_MISSIONS_RE = re.compile(r"^SCAN_SECRET_MISSIONS\b(.*)$", re.IGNORECASE)
_SCAN_OPT_RE = re.compile(
    r"\b(LEVEL|FREE_SLOTS|WITHIN)\s+(\d+(?:\.\d+)?)\s*s?\b|\b(STAR|CAN_LOOT)\b",
    re.IGNORECASE,
)

# ---- Game-VM primitives (Lua daemon bridge) --------------------------------
# These drive the game through its own Lua VM (the warm daemon, tools/lua_daemon.py),
# not through pixels — so they need no hwnd. See docs/dsl.md "Game primitives".
#
# The building block is LUA: it runs one raw in-engine call, verbatim, so a recipe
# shows exactly what it does to the game (no hidden Python composites — humans edit
# these). READ_LUA evaluates an expression and stashes the result in a script
# variable, which numeric IF/WHILE conditions then test. GAME/JUMP are thin, single-
# call sugar over the common recipes in tools/lib/lua_actions.py.
_GAME_SCENE_RE = re.compile(r"^GAME\s+(WORLD|CITY)\s*$", re.IGNORECASE)
_JUMP_RE = re.compile(
    r"^JUMP\s+(\d+)\s*,\s*(\d+)(?:\s*,\s*(\d+))?\s*$", re.IGNORECASE,
)
# TAP presses a named "button" from the friendly catalogue (tools/lib/game_buttons.py),
# optionally N times (`TAP donate_1000 x30`) or `xall` — press as many times as the
# button reports it still can (its count_lua), re-reading until that reaches zero.
# This is the high-level, human-readable layer — engine calls stay in the catalogue.
_TAP_RE = re.compile(r"^TAP\s+([A-Za-z_]\w*)(?:\s+x\s*(\d+|all))?\s*$", re.IGNORECASE)
# LUA takes the rest of the line as a raw Lua chunk (no quotes — Lua is quote-heavy).
# READ_LUA <expr> INTO <var> captures a value; the `INTO <var>` tail is anchored at
# the end so the expression itself may contain anything up to it.
_LUA_RE = re.compile(r"^LUA\s+(.+)$", re.IGNORECASE)
_READ_LUA_RE = re.compile(
    r"^READ_LUA\s+(.+)\s+INTO\s+([A-Za-z_]\w*)\s*$", re.IGNORECASE,
)
# Numeric variable condition: `attempts > 0`, `haswin == 0`, etc. Evaluated after
# the screen/profile/missions predicates so those keywords keep priority.
_VAR_COND_RE = re.compile(
    r"^([A-Za-z_]\w*)\s*(==|!=|>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$",
)


def _coerce(raw: str) -> Any:
    """Turn a Lua `tostring` result into an int/float when it looks numeric.

    Keeps values usable by numeric conditions (`attempts > 0`) while leaving
    non-numeric strings (`"UIAllianceScienceInfo"`, `"nil"`) as-is.
    """
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    try:
        return float(raw)
    except ValueError:
        return raw

_SCREEN_CHECK_RE = re.compile(
    rf"^screen\s*(==|!=)\s*({_IDENT})\s*$", re.IGNORECASE,
)
# State-based scene check (via the game's Lua VM, NOT the SIFT screen matcher):
# `scene == city` / `scene == world` / `scene == unknown`. Preferred over `screen`.
_SCENE_CHECK_RE = re.compile(
    r"^scene\s*(==|!=)\s*(city|world|unknown)\s*$", re.IGNORECASE,
)
_FIND_COND_RE = re.compile(
    rf"^FIND\s+({_IDENT}\.png)\s*$", re.IGNORECASE,
)
_PROFILE_CHECK_RE = re.compile(
    rf'^profile\.({_IDENT})\s*(==|!=)\s*"([^"]*)"\s*$', re.IGNORECASE,
)
_MISSIONS_CHECK_RE = re.compile(
    r"^missions\.count\s*(==|!=|>=|<=|>|<)\s*(\d+)\s*$", re.IGNORECASE,
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
class PressStmt(_Stmt):
    key: str  # ESC, ENTER, A, F5, ... — see inputs._VK_NAMES


@dataclass(slots=True)
class ScanMissionsStmt(_Stmt):
    """Read secret tasks off the wire and leave them in the MISSIONS register."""
    level: int | None = None
    star_only: bool = False
    can_loot: bool = False
    free_slots: int | None = None
    timeout: float = 30.0


@dataclass(slots=True)
class WhileStmt(_Stmt):
    condition: str
    limit: int                # safety cap on iterations
    body: list[Any] = field(default_factory=list)


@dataclass(slots=True)
class GameSceneStmt(_Stmt):
    """Switch the game scene via the Lua VM: CITY (home base) or WORLD (the map)."""
    scene: str  # "world" | "city"


@dataclass(slots=True)
class JumpStmt(_Stmt):
    """Camera/coordinate jump to tile (x, y) — same-server or (with server) cross-server."""
    x: int
    y: int
    server: int | None = None


@dataclass(slots=True)
class TapStmt(_Stmt):
    """Press a named button `count` times. count=None means `xall` (spend all)."""
    name: str
    count: int | None = 1


@dataclass(slots=True)
class LuaStmt(_Stmt):
    """Run one raw Lua chunk in the game VM (verbatim rest-of-line). No return value."""
    chunk: str


@dataclass(slots=True)
class ReadLuaStmt(_Stmt):
    """Evaluate a Lua expression and store its value in the script variable `var`."""
    expr: str
    var: str


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
class FailStmt(_Stmt):
    """End the whole run as a FAILURE, bubbling out of every enclosing block.

    The mirror image of STOP: STOP ends the run as a deliberate *success* (the
    scenario decided it was done), FAIL ends it as a deliberate *failure* — so a
    timer leaves ``last_run`` where it was and retries the errand later. The
    canonical use is a precondition a scenario cannot meet right now (not on the
    base, an event closed), which should be tried again rather than counted done.
    """
    reason: str | None = None


@dataclass(slots=True)
class CloseWindowStmt(_Stmt):
    """Send WM_CLOSE to the game window (no force-kill)."""


@dataclass(slots=True)
class LaunchStmt(_Stmt):
    """Spawn a process (typically the game launcher). Fire-and-forget."""
    path: str


@dataclass(slots=True)
class QuitGameStmt(_Stmt):
    """Force-close the client this profile drives, and wait for it to go."""


@dataclass(slots=True)
class StartGameStmt(_Stmt):
    """Start the client this profile drives, in the session the profile lives in."""
    path: str | None = None
    timeout: float = START_TIMEOUT_SEC


@dataclass(slots=True)
class AttachGameStmt(_Stmt):
    """Re-point the warm Lua link at the client that is running now."""
    timeout: float = ATTACH_TIMEOUT_SEC


# ---- Errors ----------------------------------------------------------------


class ScriptParseError(Exception):
    pass


class ScriptRuntimeError(Exception):
    pass


def _no_template(name: str) -> str:
    """Why a template is missing, and what to do — not just that it is missing.

    The cropped UI images are screenshots of a running game and are git-ignored, so
    on a fresh clone they are all absent. «template not found: x.png» would read as a
    bug in the scenario; it is a step of setting the bot up that nobody has done yet.
    """
    return (f"template not found: {name}. The UI templates are not shipped with the "
            f"repository — crop it from a screenshot of your own client, as "
            f"src/lastwar_bot/game/templates/README.md describes")


# ---- Parser ----------------------------------------------------------------


# A trailing inline comment: whitespace, then '#' that is followed by a space or the
# end of line. The follow-up requirement is what keeps a Lua length operator (`#list`,
# `#t` — '#' glued to a name) from being mistaken for a comment, so `LUA local n = #t`
# survives while `TAP alliance   # the button` gets its note stripped.
_INLINE_COMMENT_RE = re.compile(r"\s+#(?=\s|$).*$")


def parse_text(text: str) -> list[Any]:
    """Tokenise a script source string and return the top-level statements."""
    lines: list[tuple[int, str, int]] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        rstripped = raw.rstrip()
        stripped = rstripped.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(rstripped) - len(stripped)   # from leading space, before comment strip
        stripped = _INLINE_COMMENT_RE.sub("", stripped).rstrip()
        if not stripped:
            continue
        lines.append((indent, stripped, i))
    statements, _ = _parse_block(lines, 0, 0)
    return statements


def parse_file(path: Path) -> list[Any]:
    return parse_text(path.read_text(encoding="utf-8"))


# ---- arguments -------------------------------------------------------------
# `ARGS <name> = <value>` declares a parameter and its default. The caller's value
# wins; the default is what makes a script runnable with no arguments at all.
# Values are JSON when they parse as JSON (numbers, lists, true/false, "strings")
# and plain text otherwise, so both `ARGS squads = [1, 2, 3]` and
# `ARGS leader = Rock` read naturally.
_ARGS_RE = re.compile(rf"^ARGS\s+({_IDENT})\s*=\s*(.*?)\s*$", re.IGNORECASE)


def extract_defaults(text: str) -> tuple[dict, str]:
    """Split `ARGS` declarations off a script; return ``(defaults, rest)``.

    The declarations are removed from the source, so the parser never sees them —
    they are about the script's signature, not its body. Blank lines take their
    place so every remaining statement keeps its original line number in errors.
    """
    defaults: dict = {}
    lines = []
    for raw in text.splitlines():
        m = _ARGS_RE.match(raw.strip())
        if m is None:
            lines.append(raw)
            continue
        value = m.group(2)
        try:
            defaults[m.group(1)] = json.loads(value)
        except ValueError:
            defaults[m.group(1)] = value
        lines.append("")
    return defaults, "\n".join(lines)


def render_value(value: Any) -> str:
    """A variable as it is written into the script text.

    A list becomes its comma-separated items — so a recipe writes `{ {squads} }`
    and gets a Lua table — and a bool becomes Lua's `true`/`false` rather than
    Python's capitalised spelling. Everything else is `str()`.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(render_value(item) for item in value)
    return str(value)


def substitute(text: str, variables: dict | None) -> str:
    """Replace every ``{name}`` with the matching variable's value.

    Plain textual replacement, NOT ``str.format``: a Lua line is full of braces of
    its own (`{a=1}`, `{}`), and format would choke on every one of them. Only the
    names actually passed are replaced, so an unknown `{placeholder}` is left
    standing — it shows up in the log line instead of silently becoming empty.
    """
    for name, value in (variables or {}).items():
        text = text.replace("{%s}" % name, render_value(value))
    return text


def prepare_source(text: str, variables: dict | None) -> tuple[str, dict]:
    """Apply a script's `ARGS` defaults and substitute `{name}`.

    Returns the ready-to-parse source and the merged variables (defaults first,
    the caller's values on top) so the caller can put them where conditions will
    find them.
    """
    defaults, body = extract_defaults(text)
    merged = dict(defaults)
    merged.update(variables or {})
    return substitute(body, merged), merged


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

    m = _WHILE_RE.match(text)
    if m:
        cond = m.group(1).strip()
        limit = int(m.group(2)) if m.group(2) else 20
        i += 1
        body, i = _parse_indented_block(lines, i, indent, ln)
        return WhileStmt(
            text=text, line_no=ln, condition=cond, limit=limit, body=body,
        ), i

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

    m = _SCAN_MISSIONS_RE.match(text)
    if m:
        return _parse_scan_missions(m.group(1), text, ln), i + 1

    m = _GAME_SCENE_RE.match(text)
    if m:
        return GameSceneStmt(text=text, line_no=ln, scene=m.group(1).lower()), i + 1

    m = _JUMP_RE.match(text)
    if m:
        server = int(m.group(3)) if m.group(3) is not None else None
        return JumpStmt(
            text=text, line_no=ln,
            x=int(m.group(1)), y=int(m.group(2)), server=server,
        ), i + 1

    m = _TAP_RE.match(text)
    if m:
        raw = m.group(2)
        if raw is None:
            count: int | None = 1
        elif raw.lower() == "all":
            count = None
        else:
            count = int(raw)
        return TapStmt(text=text, line_no=ln, name=m.group(1), count=count), i + 1

    m = _READ_LUA_RE.match(text)
    if m:
        return ReadLuaStmt(
            text=text, line_no=ln, expr=m.group(1).strip(), var=m.group(2),
        ), i + 1

    m = _LUA_RE.match(text)
    if m:
        return LuaStmt(text=text, line_no=ln, chunk=m.group(1).strip()), i + 1

    m = _CALL_RE.match(text)
    if m:
        return CallStmt(text=text, line_no=ln, action_name=m.group(1)), i + 1

    m = _PRESS_RE.match(text)
    if m:
        return PressStmt(text=text, line_no=ln, key=m.group(1)), i + 1

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

    m = _FAIL_RE.match(text)
    if m:
        return FailStmt(text=text, line_no=ln, reason=m.group(1)), i + 1

    if _CLOSE_WINDOW_RE.match(text):
        return CloseWindowStmt(text=text, line_no=ln), i + 1

    m = _LAUNCH_RE.match(text)
    if m:
        return LaunchStmt(text=text, line_no=ln, path=m.group(1)), i + 1

    if _QUIT_GAME_RE.match(text):
        return QuitGameStmt(text=text, line_no=ln), i + 1

    m = _START_GAME_RE.match(text)
    if m:
        return StartGameStmt(text=text, line_no=ln, path=m.group(1),
                             timeout=float(m.group(2) or START_TIMEOUT_SEC)), i + 1

    m = _ATTACH_GAME_RE.match(text)
    if m:
        return AttachGameStmt(text=text, line_no=ln,
                              timeout=float(m.group(1) or ATTACH_TIMEOUT_SEC)), i + 1

    raise ScriptParseError(f"line {ln}: unrecognised statement: {text!r}")


def _parse_scan_missions(rest: str, text: str, ln: int) -> ScanMissionsStmt:
    """Parse the modifier tail of SCAN_SECRET_MISSIONS.

    Every modifier is optional and order-independent. Anything left over
    after the known ones are consumed is a typo, and typos in a filter are
    dangerous — a silently-ignored ``STAR`` would raid the wrong tasks — so
    leftovers are a parse error rather than a warning.
    """
    stmt = ScanMissionsStmt(text=text, line_no=ln)
    consumed = []
    for m in _SCAN_OPT_RE.finditer(rest):
        consumed.append(m.span())
        if m.group(1):
            keyword, value = m.group(1).upper(), m.group(2)
            if keyword == "LEVEL":
                stmt.level = int(value)
            elif keyword == "FREE_SLOTS":
                stmt.free_slots = int(value)
            else:
                stmt.timeout = float(value)
        elif m.group(3).upper() == "STAR":
            stmt.star_only = True
        else:
            stmt.can_loot = True

    leftover = rest
    for start, end in reversed(consumed):
        leftover = leftover[:start] + leftover[end:]
    if leftover.strip():
        raise ScriptParseError(
            f"line {ln}: unrecognised SCAN_SECRET_MISSIONS option: "
            f"{leftover.strip()!r}"
        )
    return stmt


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
    # FAIL sets these — the deliberate-failure counterpart of halt/halt_reason. The
    # run boundary reads `failed` to return False (STOP returns True), so a timer
    # retries a scenario that bailed on a precondition rather than counting it done.
    failed: bool = False
    fail_reason: str | None = None
    profile: Any = None  # `lastwar_bot.profile.Profile` instance, or None
    # Result of the most recent SCAN_SECRET_MISSIONS — a list of
    # `net.missions.SecretMission`, read by the `missions.count` condition.
    missions: list = field(default_factory=list)
    # Lazily-created Lua-VM evaluator (daemon client or local LuaEval) shared by the
    # game primitives (LUA / READ_LUA / GAME / JUMP). Created on first use so
    # vision-only scripts never touch the daemon. See Interpreter._evaluator().
    evaluator: Any = None
    # WHICH client this run drives, and under whose lease. Both `None` mean "whatever
    # this process is set to" — the environment's LW_DAEMON_PORT and LW_GAME_LEASE —
    # which is right for every script started from a shell and is what every caller
    # got before these existed.
    #
    # A caller that holds the answer says it here instead. The panel does: a profile
    # naming a non-default port drives the client of ANOTHER Windows session
    # (tools/rdp_instance.py), and until this existed its scenarios went to the
    # console session's client regardless, because the module-level port in
    # `lua_client` is read from the environment at import. One panel process may also
    # hold two profiles' leases at once, and an environment variable can hold one
    # (#1206) — so the token travels with the run as well.
    game_port: int | None = None
    game_token: str | None = None
    # WHERE that client lives: the login of the Windows session it is in, or `None`
    # for this desktop. The port says what to TALK to and this says where the process
    # IS, which is a different question and the only one a launch can ask — there is
    # nothing running yet to be attached to. `None` keeps every script started from a
    # shell exactly as it was: the launcher spawns here (see START_GAME).
    game_user: str | None = None
    # Script variables written by READ_LUA and tested by numeric IF/WHILE conditions.
    vars: dict = field(default_factory=dict)
    # Optional stop flag — anything with `.is_set()` (a threading.Event). Checked
    # BETWEEN statements, between the presses of a repeat and between the polls of
    # a WAIT, so a caller (the panel's «Стоп») can end a run without killing a
    # thread mid-call. A set flag unwinds through the same _HaltSignal that STOP
    # uses, so the run ends the way a script's own STOP ends: cleanly, with a
    # reason, and reported as halted rather than failed.
    cancel: Any = None


class _HaltSignal(Exception):
    """Raised by STOP to unwind every enclosing block / sub-action.

    The signal is caught at the outermost `run_action` boundary. The
    actual reason and `halt=True` flag live in the shared Context so the
    caller (e.g. the runner) can react after execution returns.
    """


class _FailSignal(Exception):
    """Raised by FAIL to unwind every enclosing block / sub-action as a failure.

    The failure twin of `_HaltSignal`: caught at the same `run_action` /
    `run_text` boundaries, but there it returns ``False`` (STOP returns ``True``).
    The reason and `failed=True` flag live on the shared Context.
    """


class Interpreter:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._depth = 0

    def _log(self, msg: str) -> None:
        self.ctx.on_event("  " * self._depth + msg)

    def _check_cancel(self) -> None:
        """Raise if the caller asked the run to stop. Called between steps."""
        cancel = self.ctx.cancel
        if cancel is not None and cancel.is_set():
            self.ctx.halt = True
            self.ctx.halt_reason = self.ctx.halt_reason or "stopped by the operator"
            raise _HaltSignal()

    # ---- entry point ----

    def run_action(self, name: str) -> bool:
        path = resolve_action(name)
        if path is None:
            self.ctx.on_event(f"!! action not found: {name} (looked in {ACTIONS_DIR} and dev/)")
            return False
        self._log(f"> action: {name}")
        self._depth += 1
        try:
            # Arguments first: the script's own `ARGS` defaults fill in whatever the
            # caller left out, the merged set lands in ctx.vars (so conditions read
            # them too), and `{name}` is substituted before the source is parsed.
            source, merged = prepare_source(path.read_text(encoding="utf-8"),
                                            self.ctx.vars)
            self.ctx.vars.update(merged)
            statements = parse_text(source)
            self._run_block(statements)
            self._depth -= 1
            self._log(f"< action: {name} OK")
            return True
        except _HaltSignal:
            self._depth -= 1
            self._log(f"< action: {name} HALTED ({self.ctx.halt_reason or 'no reason given'})")
            return True
        except _FailSignal:
            self._depth -= 1
            self._log(f"< action: {name} FAILED — {self.ctx.fail_reason or 'FAIL'}")
            return False
        except (ScriptParseError, ScriptRuntimeError) as exc:
            self._depth -= 1
            self._log(f"< action: {name} FAILED — {exc}")
            return False

    # ---- block / statement dispatch ----

    def _run_block(self, statements: list[Any]) -> None:
        for stmt in statements:
            self._check_cancel()
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
            case FailStmt():
                self.ctx.failed = True
                self.ctx.fail_reason = stmt.reason or f"FAIL at line {stmt.line_no}"
                self._log(f"FAIL -> {self.ctx.fail_reason}")
                raise _FailSignal()
            case CloseWindowStmt():
                self._do_close_window(stmt)
            case LaunchStmt():
                self._do_launch(stmt)
            case QuitGameStmt():
                self._do_quit_game(stmt)
            case StartGameStmt():
                self._do_start_game(stmt)
            case AttachGameStmt():
                self._do_attach_game(stmt)
            case ReadTextStmt():
                self._do_read_text(stmt)
            case PressStmt():
                self._do_press(stmt)
            case ScanMissionsStmt():
                self._do_scan_missions(stmt)
            case WhileStmt():
                self._do_while(stmt)
            case GameSceneStmt():
                self._do_game_scene(stmt)
            case JumpStmt():
                self._do_jump(stmt)
            case TapStmt():
                self._do_tap(stmt)
            case LuaStmt():
                self._do_lua(stmt)
            case ReadLuaStmt():
                self._do_read_lua(stmt)

    # ---- conditions ----

    def eval_condition(self, cond: str, line_no: int) -> bool:
        up = cond.strip().upper()
        if up == "FOUND":
            return self.ctx.last_find is not None
        if up == "NOT FOUND":
            return self.ctx.last_find is None

        m = _SCENE_CHECK_RE.match(cond)
        if m:
            op = m.group(1)
            wanted = m.group(2).lower()
            current = self._current_scene()
            return (current == wanted) if op == "==" else (current != wanted)

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

        m = _MISSIONS_CHECK_RE.match(cond)
        if m:
            op, wanted = m.group(1), int(m.group(2))
            actual = len(self.ctx.missions)
            return {
                "==": actual == wanted, "!=": actual != wanted,
                ">=": actual >= wanted, "<=": actual <= wanted,
                ">": actual > wanted, "<": actual < wanted,
            }[op]

        m = _VAR_COND_RE.match(cond)
        if m:
            name, op, wanted = m.group(1), m.group(2), float(m.group(3))
            if name not in self.ctx.vars:
                raise ScriptRuntimeError(
                    f"line {line_no}: unknown variable {name!r} "
                    f"(set it first with READ_LUA ... INTO {name})"
                )
            try:
                actual = float(self.ctx.vars[name])
            except (TypeError, ValueError):
                raise ScriptRuntimeError(
                    f"line {line_no}: variable {name!r} = {self.ctx.vars[name]!r} "
                    "is not numeric"
                )
            return {
                "==": actual == wanted, "!=": actual != wanted,
                ">=": actual >= wanted, "<=": actual <= wanted,
                ">": actual > wanted, "<": actual < wanted,
            }[op]

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
            raise ScriptRuntimeError(_no_template(template_name))
        scene = features.SceneIndex(grab(self._ensure_hwnd()))
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
        from .perception.capture import (
            WindowNotFoundError, find_window, grab,
        )

        # Lazy window discovery. Scripts that start before the game is
        # running (e.g. launch_game.md) hold ctx.hwnd = 0 until the
        # window appears; each WAIT iteration re-tries find_window.
        if not self.ctx.hwnd:
            try:
                info = find_window()
                self.ctx.hwnd = info.hwnd
            except WindowNotFoundError:
                self._log("(window not running)")
                return None

        try:
            screen = navigate.identify_screen(grab(self.ctx.hwnd))
        except Exception as exc:
            # Window vanished between the find and the grab — invalidate
            # the cached handle so the next iteration will re-discover it.
            self._log(f"(screen detection failed: {exc!r})")
            self.ctx.hwnd = 0
            return None
        self._log(f"(screen = {screen!r})")
        return screen

    # ---- primitives ----

    def _ensure_hwnd(self) -> int:
        """Return a live game-window handle, discovering it lazily on first need.

        The vision primitives (FIND/CLICK/READ_TEXT/PRESS/CLOSE_WINDOW) need a real
        hwnd, but callers such as the panel start actions with hwnd=0 (they drive the
        game through the Lua daemon and never resolve a window). Resolve it here so a
        vision action run from anywhere just works; raise if the window is absent.
        """
        if not self.ctx.hwnd:
            from .perception.capture import WindowNotFoundError, find_window
            try:
                self.ctx.hwnd = find_window().hwnd
            except WindowNotFoundError as exc:
                raise ScriptRuntimeError(f"game window not found: {exc}") from exc
        return self.ctx.hwnd

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
                f"line {stmt.line_no}: {_no_template(stmt.template_name)}")

        hwnd = self._ensure_hwnd()
        match = None
        for attempt in range(1, self._FIND_RETRIES + 1):
            scene = features.SceneIndex(grab(hwnd))
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
            click(self._ensure_hwnd(), cx, cy, mode="foreground")
            self._log(f"CLICK at ({cx}, {cy})  [absolute]")
            return

        match = self.ctx.last_find
        if match is None:
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: CLICK without a preceding successful FIND"
            )
        cx, cy = match.center
        click(self._ensure_hwnd(), cx, cy, mode="foreground")
        self._log(f"CLICK at ({cx}, {cy})")

    def _do_press(self, stmt: PressStmt) -> None:
        from .inputs import press_key

        press_key(self._ensure_hwnd(), stmt.key)
        self._log(f"PRESS {stmt.key.upper()}")

    def _do_while(self, stmt: WhileStmt) -> None:
        iterations = 0
        while iterations < stmt.limit:
            if not self.eval_condition(stmt.condition, stmt.line_no):
                break
            self._log(f"WHILE {stmt.condition} (iter {iterations + 1}/{stmt.limit})")
            self._depth += 1
            try:
                self._run_block(stmt.body)
            finally:
                self._depth -= 1
            iterations += 1
        if iterations == stmt.limit and self.eval_condition(stmt.condition, stmt.line_no):
            self._log(f"WHILE -> LIMIT {stmt.limit} reached, giving up")
        else:
            self._log(f"WHILE -> done after {iterations} iteration(s)")

    def _do_read_text(self, stmt: ReadTextStmt) -> None:
        if self.ctx.profile is None:
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: READ_TEXT INTO profile.* requires "
                "an active profile (start the bot with --profile <id>)"
            )
        from .perception.capture import grab
        from .perception.ocr import read_text

        img = grab(self._ensure_hwnd())
        text = read_text(img, stmt.region)
        self.ctx.profile.set(stmt.target_field, text)
        x, y, w, h = stmt.region
        self._log(
            f"READ_TEXT ({x}, {y}, {w}, {h}) -> profile.{stmt.target_field} = {text!r}"
        )

    def _do_scan_missions(self, stmt: ScanMissionsStmt) -> None:
        """Read secret tasks off the wire for up to `timeout` seconds.

        The scan is passive: it decodes `world.get.block` responses the game
        is already sending, so **the map has to be moving** for anything to
        arrive. Pan the map (or run this alongside a scroll action) or the
        result will legitimately be empty.

        An empty result is not a failure — it leaves MISSIONS empty and the
        script decides via `IF missions.count == 0`. A missing capture stack
        *is* a failure, because the script asked for exact data and would
        otherwise silently act on nothing.
        """
        # The protocol stack lives in tools/ — framer, XOR mask, TLV parser,
        # task semantics — and is imported rather than duplicated. tools/ is
        # not an installed package, so the path is wired up here.
        tools = Path(__file__).resolve().parents[2] / "tools"
        if str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        try:
            from live_tshark import CaptureUnavailable, TaskListener
        except ImportError as exc:
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: SCAN_SECRET_MISSIONS needs the capture "
                f"stack in tools/ — {exc}"
            ) from exc

        criteria = dict(
            level=stmt.level,
            star_only=stmt.star_only,
            can_loot=stmt.can_loot,
            min_free_slots=stmt.free_slots,
        )
        wanted = ", ".join(
            part for part in (
                f"level {stmt.level}" if stmt.level is not None else "",
                "starred" if stmt.star_only else "",
                "lootable" if stmt.can_loot else "",
                f"{stmt.free_slots}+ free slots" if stmt.free_slots is not None else "",
            ) if part
        ) or "any"

        try:
            with TaskListener() as listener:
                self._log(
                    f"SCAN_SECRET_MISSIONS {wanted} — listening up to "
                    f"{stmt.timeout:g}s (pan the map to make tiles arrive)"
                )
                found = listener.wait_for(timeout=stmt.timeout, **criteria)
                seen = len(listener.tasks)
        except CaptureUnavailable as exc:
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: SCAN_SECRET_MISSIONS cannot capture — {exc}"
            ) from exc

        self.ctx.missions = found
        self._log(
            f"SCAN_SECRET_MISSIONS -> {len(found)} match(es) of {seen} task(s) seen"
        )
        for mission in found[:5]:
            self._log(
                f"  lvl {mission.level} at ({mission.x}, {mission.y}) "
                f"server {mission.server_id} — {mission.loot_count}/3 looted"
                f"{', starred' if mission.starred else ''}"
            )

    # ---- game-VM primitives (Lua daemon bridge) ----

    def _tools_lib_on_path(self) -> None:
        """Put tools/lib on sys.path so the Lua bridge modules import (they are not
        an installed package). Same wiring the SCAN_SECRET_MISSIONS primitive uses."""
        lib = Path(__file__).resolve().parents[2] / "tools" / "lib"
        if str(lib) not in sys.path:
            sys.path.insert(0, str(lib))

    def _evaluator(self):
        """Return the shared Lua evaluator, creating it on first use.

        Backed by the warm daemon when it is up, otherwise a fresh local `LuaEval`
        (see tools/lib/lua_client.get_evaluator). Cached on the Context so every game
        primitive in one action reuses the same connection.

        On the port and the lease the context names, when it names them — see
        `Context.game_port`. Left unsaid, the environment answers, exactly as before.
        """
        if self.ctx.evaluator is None:
            self._tools_lib_on_path()
            try:
                import lua_client
            except ImportError as exc:
                raise ScriptRuntimeError(
                    f"game primitives need the Lua bridge in tools/lib — {exc}"
                ) from exc
            opts = {}
            if self.ctx.game_port is not None:
                opts["port"] = int(self.ctx.game_port)
            if self.ctx.game_token is not None:
                opts["token"] = self.ctx.game_token
            self.ctx.evaluator = lua_client.get_evaluator(**opts)
        return self.ctx.evaluator

    def _run_lua(self, chunk: str, marker: str = "ACT", settle: float = 1.2,
                 early: bool = True) -> list:
        """Run one chunk in the game VM and hand back its marker lines.

        `settle` is a DEADLINE here, not a pause (`early`, see tools/lib/lua_eval.py):
        every chunk the interpreter builds ends by logging its own marker, so the answer
        is complete the moment that line lands — measured at ~30 ms, against the second
        and a half a step used to sit out (#1230). Waiting for the GAME rather than for
        the answer is the DSL's own job and always has been: that is what `WAIT` is for,
        and what the recipes already use after a scene switch or a request.
        """
        return self._evaluator().run(chunk, marker, settle, early=early)

    def _do_game_scene(self, stmt: GameSceneStmt) -> None:
        self._tools_lib_on_path()
        import lua_actions
        chunk = lua_actions.scene_world() if stmt.scene == "world" else lua_actions.scene_city()
        self._run_lua(chunk)
        self._log(f"GAME {stmt.scene.upper()} -> scene switch sent")

    def _do_jump(self, stmt: JumpStmt) -> None:
        self._tools_lib_on_path()
        import lua_actions
        # No explicit server → the one the client is looking at, resolved INSIDE the
        # chunk (lua_actions.jump_to_coord). It used to fall back to `HOME_SERVER`,
        # which is 0 unless the machine sets it — a jump to a server that does not
        # exist, where the live answer was one Lua expression away.
        self._run_lua(lua_actions.jump_to_coord(stmt.x, stmt.y, stmt.server))
        where = f"{stmt.x},{stmt.y}" + (f" srv {stmt.server}" if stmt.server is not None else "")
        self._log(f"JUMP -> {where}")

    def _do_tap(self, stmt: TapStmt) -> None:
        """Press a named button from the catalogue: a fixed count, or `xall`.

        Each press is its own game-VM call followed by the button's built-in pause, so
        even a big repeat can never busy-loop the client — the throttle/round-trip lands
        in the gap. A button that declares a `batch_lua` is the exception: its repeat
        goes into the game in ONE call, because the round trip (~0.15 s) is the whole
        cost and the loop inside the VM is free. `xall` re-reads the button's own count
        and keeps pressing until it hits zero (or a safety cap), which spends exactly
        what is available and quietly recovers any presses the client's long-press
        throttle dropped. Unknown button = a clear runtime error naming the ones that
        exist.
        """
        self._tools_lib_on_path()
        import game_buttons
        btn = game_buttons.get(stmt.name)
        if btn is None:
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: unknown button {stmt.name!r} "
                f"(known: {', '.join(game_buttons.names())})"
            )
        if stmt.count is None:                      # xall
            self._tap_all(stmt, btn)
            return
        if btn.batch_lua and stmt.count > 1:
            fired = self._press_batch(btn, stmt.count)
            self._log(f"TAP {btn.label} x{stmt.count} -> {fired} press(es)")
            time.sleep(btn.wait)
            return
        for n in range(1, stmt.count + 1):
            self._check_cancel()
            self._press_button(btn)
            suffix = f" ({n}/{stmt.count})" if stmt.count > 1 else ""
            self._log(f"TAP {btn.label}{suffix}")
            time.sleep(btn.wait)

    def _press_button(self, btn) -> None:
        """Fire one button press (its Lua), guarded, surfacing any Lua error."""
        chunk = (
            'local ok,err=pcall(function() %s end) '
            'CS.UnityEngine.Debug.LogError("ACT tap="..(ok and "ok" or ("ERR:"..tostring(err))))'
            % btn.lua
        )
        for out in self._run_lua(chunk, settle=0.1):
            if "ERR:" in out:
                self._log(f"TAP {btn.label} error: {out.split('tap=', 1)[-1]}")

    def _press_batch(self, btn, n: int) -> int:
        """Fire `n` presses in ONE game-VM call; returns how many the chunk really fired.

        The chunk reports its own tally (`ACT fired=<k>`), which can be short of `n` when
        the batch hit a gate of its own — donating stops there when the resources run out.
        A Lua error, or no tally at all, counts as zero fired: the caller re-reads the
        real count anyway, so an unreadable batch stalls the loop instead of inflating it.
        """
        chunk = (
            'local n=%d local ok,err=pcall(function() %s end) '
            'if not ok then CS.UnityEngine.Debug.LogError("ACT fired=ERR:"..tostring(err)) end'
            % (n, btn.batch_lua)
        )
        for out in self._run_lua(chunk, settle=0.1):
            if "fired=" not in out:
                continue
            raw = out.split("fired=", 1)[1].split()[0]
            if raw.startswith("ERR"):
                self._log(f"TAP {btn.label} error: {raw}")
                return 0
            try:
                return int(float(raw))
            except ValueError:
                return 0
        return 0

    def _tap_all(self, stmt: TapStmt, btn) -> None:
        """`TAP <button> xall`: press while the button's count_lua stays above zero.

        One press per call for an ordinary button; for one with a `batch_lua`, a whole
        round of presses per call — read the count, spend exactly that many in a single
        chunk, re-read to confirm. Either way the count, not a guess, says when to stop,
        and a round that presses nothing ends the loop.
        """
        if not btn.count_lua:
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: button {stmt.name!r} does not support 'xall' "
                "(no count defined in the catalogue)"
            )
        pressed = 0
        while pressed < btn.max_taps:
            self._check_cancel()
            remaining = self._eval_number(btn.count_lua)
            if remaining is None:
                self._log(f"TAP {btn.label} xall — count unavailable, stopping")
                break
            if remaining <= 0:
                break
            if btn.batch_lua:
                want = int(min(remaining, btn.max_taps - pressed))
                fired = self._press_batch(btn, want)
                if not fired:
                    break
                pressed += fired
                self._log(f"TAP {btn.label} ({pressed}; {int(remaining) - fired} left)")
            else:
                self._press_button(btn)
                pressed += 1
                self._log(f"TAP {btn.label} ({pressed}; {int(remaining)} available)")
            time.sleep(btn.wait)
        self._log(f"TAP {btn.label} xall -> {pressed} press(es)")

    def _eval_lua_value(self, expr: str) -> str | None:
        """Evaluate a Lua expression, returning its `tostring()` value.

        Returns None if the expression errors OR the game VM is unreachable (daemon
        down / mid-rehijack after a game restart) — callers decide what that means
        (a scene poll treats it as 'unknown'; a count read stops).

        `SystemExit` is in the catch on purpose: with no daemon the evaluator is a
        local `LuaEval`, and building one while no client is running raises
        `SystemExit("LastWar.exe not running")` from the pid probe. During a restart
        (actions/restart_game.md) that is not a reason to abandon the run — it is
        precisely the "not up yet" the poll is waiting out.
        """
        chunk = (
            'local ok,v=pcall(function() return %s end) '
            'CS.UnityEngine.Debug.LogError("RLUA "..(ok and tostring(v) or ("ERR:"..tostring(v))))'
            % expr
        )
        try:
            lines = self._run_lua(chunk, marker="RLUA", settle=0.35)
        except (RuntimeError, OSError, SystemExit):
            return None
        value: str | None = None
        for out in lines:
            if "RLUA " in out:
                raw = out.split("RLUA ", 1)[1].strip()
                value = None if raw.startswith("ERR:") else raw
        return value

    def _eval_number(self, expr: str) -> float | None:
        """Evaluate a Lua expression to a number (or None if not numeric / errored)."""
        raw = self._eval_lua_value(expr)
        if raw is None:
            return None
        c = _coerce(raw)
        return float(c) if isinstance(c, (int, float)) else None

    def _current_scene(self) -> str:
        """Read the game scene from the Lua VM (state, not pixels): 'city' / 'world' / 'unknown'.

        'city' means fully at the home base — the city scene AND the main HUD (UIMain)
        is up, so a still-loading client reads 'unknown', which is exactly what a launch
        `WAIT scene == city` wants. Any VM failure (game not up yet, daemon re-hijacking
        the freshly-launched process) also reads 'unknown', so the caller just keeps
        polling; the daemon auto-rebuilds its LuaEval on a stale handle, so this recovers
        by itself across a restart. No screenshots, no SIFT.
        """
        expr = (
            "(function() "
            "if not SceneUtils then return 'unknown' end "
            "if SceneUtils.GetIsInWorld and SceneUtils.GetIsInWorld() then return 'world' end "
            "if SceneUtils.GetIsInCity and SceneUtils.GetIsInCity() "
            "and UIManager and UIManager.Instance and UIManager.Instance:IsWindowOpen('UIMain') "
            "then return 'city' end "
            "return 'unknown' end)()"
        )
        try:
            val = self._eval_lua_value(expr)
        except Exception:  # noqa: BLE001 — any VM hiccup is just "unknown, poll again"
            return "unknown"
        return val if val in ("city", "world") else "unknown"

    def _do_lua(self, stmt: LuaStmt) -> None:
        """Run one raw Lua chunk in the game VM, verbatim.

        Wrapped in pcall so a Lua error surfaces as a log line instead of being
        swallowed by SafeDoString (which returns success even on error). The chunk
        runs on the game's main thread and returns immediately — do NOT put a busy
        loop here that waits on server state (it would freeze the client); express
        the loop in the DSL with WHILE + WAIT so the round-trip lands between calls.
        """
        chunk = (
            'local ok,err=pcall(function() %s end) '
            'CS.UnityEngine.Debug.LogError("ACT lua="..(ok and "ok" or ("ERR:"..tostring(err))))'
            % stmt.chunk
        )
        for ln in self._run_lua(chunk):
            if "ERR:" in ln:
                self._log(f"LUA error: {ln.split('lua=', 1)[-1]}")
        self._log(f"LUA {stmt.chunk[:80]}{'…' if len(stmt.chunk) > 80 else ''}")

    def _do_read_lua(self, stmt: ReadLuaStmt) -> None:
        """Evaluate a Lua expression and store its value in ctx.vars[stmt.var].

        Numeric results are stored as int/float so numeric conditions work; anything
        else is stored as its string form. A Lua-side error stores None and logs it.
        """
        chunk = (
            'local ok,v=pcall(function() return %s end) '
            'CS.UnityEngine.Debug.LogError("RLUA "..(ok and tostring(v) or ("ERR:"..tostring(v))))'
            % stmt.expr
        )
        value: Any = None
        for ln in self._run_lua(chunk, marker="RLUA"):
            if "RLUA " in ln:
                raw = ln.split("RLUA ", 1)[1].strip()
                if raw.startswith("ERR:"):
                    self._log(f"READ_LUA error: {raw[4:]}")
                    value = None
                else:
                    value = _coerce(raw)
        self.ctx.vars[stmt.var] = value
        self._log(f"READ_LUA {stmt.var} = {value!r}")

    def _do_call(self, stmt: CallStmt) -> None:
        self._log(f"CALL {stmt.action_name}")
        sub = Interpreter(self.ctx)
        sub._depth = self._depth + 1
        ok = sub.run_action(stmt.action_name)
        # A STOP inside the sub-action set ctx.halt. Re-raise so the chain
        # unwinds up to the outermost run_action boundary.
        if self.ctx.halt:
            raise _HaltSignal()
        # A FAIL inside it set ctx.failed. Re-raise the failure signal (rather than a
        # generic runtime error) so the reason travels up and the boundary returns
        # False — the sub-action's FAIL fails the whole chain.
        if self.ctx.failed:
            raise _FailSignal()
        if not ok:
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: sub-action {stmt.action_name} failed"
            )

    def _do_close_window(self, stmt: CloseWindowStmt) -> None:
        import win32con
        import win32gui

        win32gui.PostMessage(self._ensure_hwnd(), win32con.WM_CLOSE, 0, 0)
        self._log("CLOSE_WINDOW -> WM_CLOSE posted")

    def _do_launch(self, stmt: LaunchStmt) -> None:
        """Spawn the launcher as a detached child process.

        Path strings support environment variables and `~`:
        - ``%LOCALAPPDATA%\\FunFly\\...``  (Windows %VAR%)
        - ``$HOME/.local/bin/foo``         (Unix $VAR)
        - ``~/games/foo.exe``              (home directory)
        """
        import os
        import subprocess
        from pathlib import Path

        expanded = os.path.expanduser(os.path.expandvars(stmt.path))
        exe = Path(expanded)
        if not exe.exists():
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: launcher not found at {expanded}"
                + (f" (expanded from {stmt.path})" if expanded != stmt.path else "")
            )
        try:
            subprocess.Popen(
                [str(exe)],
                cwd=str(exe.parent),
                close_fds=True,
            )
        except OSError as exc:
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: failed to launch {expanded}: {exc}"
            )
        self._log(f"LAUNCH {expanded}")

    # -- restarting the client ------------------------------------------------
    #
    # A restart is two things the DSL had no word for. LAUNCH starts a process and
    # CLOSE_WINDOW asks a window to go away, but neither can end a client that is
    # sitting behind a modal, and — the part that bites — neither knows that the link
    # into the game's Lua VM is bound to a PROCESS ID. Left alone, everything after a
    # restart drives a pid that no longer exists.

    def _fail(self, reason: str) -> None:
        """End the run as a deliberate failure, in the scenario's own words.

        The same thing a `FAIL "…"` line does, raised from inside a primitive: the
        reason lands on the context, so the panel's timer row shows it verbatim and
        the errand is retried rather than counted as done. A `ScriptRuntimeError`
        would be the wrong shape here — the project keeps blow-ups and deliberate
        failures apart on purpose (tests/test_panel_action_outcome.py), and a client
        that did not come back is a condition to try again later, not a broken script.
        """
        self.ctx.failed = True
        self.ctx.fail_reason = reason
        self._log(f"FAIL -> {reason}")
        raise _FailSignal()

    def _detach(self) -> None:
        """Let go of this run's Lua link, so the next primitive builds a fresh one.

        The evaluator is cached on the Context for the whole action (one connection
        per run), which is exactly wrong across a restart: with no daemon it is a
        local `LuaEval` holding handles into the process we just ended, and it would
        keep failing for the rest of the run instead of re-resolving.
        """
        evaluator, self.ctx.evaluator = self.ctx.evaluator, None
        if evaluator is None:
            return
        try:
            evaluator.close()
        except Exception:                     # noqa: BLE001 — a dead handle, nothing to do
            pass

    def _game_port(self) -> int:
        """The daemon port this run drives — the context's, or the environment's.

        The same rule `_evaluator` follows (`Context.game_port`), and it matters more
        here than anywhere else: on a two-account box the port is what says WHICH
        client is being restarted, and a restart aimed at the wrong one ends the other
        account's session. A context that names no port — every script started from a
        shell — reads the environment, exactly as the rest of the engine does.
        """
        self._tools_lib_on_path()
        import lua_client
        return int(self.ctx.game_port if self.ctx.game_port is not None
                   else lua_client.PORT)

    def _do_quit_game(self, stmt: QuitGameStmt) -> None:
        """End the client this profile drives, and wait until it has really gone.

        WHICH client is the whole difficulty, and it is answered in
        tools/lib/game_client.py: with two accounts on one box there are two clients,
        each in its own Windows session with its own daemon, and closing «the client»
        by name would end the other account's session as well.

        A client that is already gone is not an error — the recipe's job is to get
        from "running" to "freshly started", and half of that being done for it is a
        head start, not a failure.

        The session travels with the close for the same reason it travels with the
        start, and for a sharper one: a client in another account's session refuses
        `TerminateProcess` outright for an unelevated panel, so without saying whose
        session it is the statement would kill nothing and then spend its whole
        timeout waiting for a process that never went away.
        """
        self._tools_lib_on_path()
        import game_client

        user = (self.ctx.game_user or "").strip() or None
        pid = game_client.target_pid(port=self._game_port(), user=user,
                                     log=lambda msg: self._log(f"  {msg}"))
        self._detach()                        # nothing may hold the old process
        if pid is None:
            self._log("QUIT_GAME -> no client is running")
            return
        if not game_client.close(pid, timeout=QUIT_TIMEOUT_SEC, user=user,
                                 log=lambda msg: self._log(f"  {msg}")):
            self._fail(f"the client (pid {pid}) would not close")
        self._log(f"QUIT_GAME -> client pid {pid} closed")

    def _do_start_game(self, stmt: StartGameStmt) -> None:
        """Start the client this profile drives — in the session it lives in.

        The opening half of what `QUIT_GAME` closes, and it has the same trap the other
        way round. `LAUNCH` spawns a process on the desktop the panel is on, which is
        the right answer for one account and the wrong one for two: a profile whose
        client lives in another Windows session (tools/rdp_instance.py) would get a
        THIRD client here — in front of whoever is using the machine, logged in to
        nothing, while the account that was asked for went on being down.

        Which session is `ctx.game_user`, the login the profile names. Nothing else can
        answer it here: the port resolves the client through the daemon *attached* to
        it, and at launch time there is no client to be attached to.

        Two shapes of "it did not work", kept apart because they want different things
        done. A launcher that is not where the path says is a configuration mistake and
        blows up like `LAUNCH`'s always has; a session nobody is logged on to, or a
        client that never appeared, is a condition to try again later — so it FAILs in
        words, and a timer retries it rather than counting the errand done.
        """
        self._tools_lib_on_path()
        import game_client

        user = (self.ctx.game_user or "").strip() or None
        where = f"{user}'s session" if user else "this desktop"
        try:
            pid = game_client.start(stmt.path, user=user, timeout=stmt.timeout,
                                    log=lambda msg: self._log(f"  {msg}"))
        except FileNotFoundError as exc:
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: launcher not found at {exc}"
            ) from exc
        except LookupError as exc:
            self._fail(str(exc))
        except TimeoutError as exc:
            self._fail(str(exc))
        except OSError as exc:
            self._fail(f"could not start the client in {where}: {exc}")
        else:
            self._log(f"START_GAME -> launched in {where}"
                      + (f" (client pid {pid})" if pid else ""))

    def _do_attach_game(self, stmt: AttachGameStmt) -> None:
        """Point the warm daemon at the client that is running NOW.

        The daemon caches one resolved `LuaEval` per client process. After a restart
        that cache names a dead pid; it does repair itself — the first failing call
        drops it and rebuilds — but that repair happens inside whatever errand runs
        next, which then pays for it and may read a failure that was only ever the
        handover. Doing it here makes the handover part of the restart, where it
        belongs, and gives the recipe something to fail on if the client never came
        back.

        THE DAEMON IS THE AUTHORITY on which client it drives, and the wait is for
        ITS answer rather than for a pid found here. That is not a nicety: a profile
        whose client lives in another Windows session is driven from this one over a
        port, so the panel's process and the client are not even in the same session
        — and checking the daemon's pid against a locally-discovered one would then
        never match, failing a restart that in fact worked.

        With no daemon there is nothing warm to re-point: the next game primitive
        builds a fresh local `LuaEval`, which resolves the live client by itself. Only
        then does a local reading make sense — and it is a same-session one, because
        a client in somebody else's session is not this profile's to report as up.
        """
        self._tools_lib_on_path()
        import game_client
        import lua_client

        self._detach()
        port = self._game_port()
        deadline = time.time() + float(stmt.timeout)
        seen = None
        while True:
            if lua_client.is_running(port=port):
                try:
                    lua_client.DaemonClient(port=port, token="").reload()
                except Exception:             # noqa: BLE001 — not warm yet; try again
                    pass
                pid = game_client.attached_pid(port)
                if pid:
                    self._log(f"ATTACH_GAME -> daemon attached to client pid {pid}")
                    return
            else:
                pid = game_client.running_pid()
                if pid:
                    self._log(f"ATTACH_GAME -> client pid {pid} (no daemon to re-point)")
                    return
            seen = seen or game_client.running_pid()
            if time.time() >= deadline:
                break
            time.sleep(2.0)
        self._fail(
            f"the game link did not come back within {stmt.timeout:g}s"
            + (f" — a client (pid {seen}) is up, but the daemon would not attach to it"
               if seen else " — no client is running"))

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
            self._check_cancel()
            if self.eval_condition(stmt.condition, stmt.line_no):
                self._log(f"WAIT {stmt.condition} -> matched")
                return
            time.sleep(0.3)
        raise ScriptRuntimeError(
            f"line {stmt.line_no}: WAIT {stmt.condition} timed out after {stmt.timeout:.1f}s"
        )


def new_context(
    hwnd: int = 0,
    on_event: EventCallback | None = None,
    profile: Any = None,
    variables: dict | None = None,
    cancel: Any = None,
    game_port: int | None = None,
    game_token: str | None = None,
    game_user: str | None = None,
) -> Context:
    """A run context, optionally pre-seeded with script variables.

    `variables` land in ``ctx.vars``, the same place ``READ_LUA ... INTO x``
    writes to — so a caller can hand a script its parameters and the script tests
    them with the ordinary ``IF x > 3`` / ``WHILE x > 0`` conditions.

    `game_port` / `game_token` name WHICH client this run drives and under whose lease;
    `game_user` names the Windows session it lives in, which is the only one of the
    three a launch can use. Left out, the environment and this desktop answer as they
    always have (see :class:`Context`).

    Pass the same context to several `run_action` / `run_text` calls to run them
    as one session: variables, the last FIND and the Lua evaluator are shared, so
    a sequence costs one daemon connection rather than one per step.
    """
    ctx = Context(hwnd=hwnd, on_event=on_event or (lambda _msg: None), profile=profile,
                  cancel=cancel, game_port=game_port, game_token=game_token,
                  game_user=game_user)
    if variables:
        ctx.vars.update(variables)
    return ctx


def run_action(
    name: str,
    hwnd: int,
    on_event: EventCallback | None = None,
    profile: Any = None,
    variables: dict | None = None,
    ctx: Context | None = None,
    cancel: Any = None,
    game_port: int | None = None,
    game_token: str | None = None,
    game_user: str | None = None,
) -> bool:
    """Convenience: parse and execute the named action.

    `profile` is an optional `lastwar_bot.profile.Profile` instance that
    becomes available to scripts as the ``profile.<field>`` namespace
    (read via conditions, write via ``READ_TEXT ... INTO profile.<field>``).

    `variables` seeds ``ctx.vars`` (see :func:`new_context`); `ctx` runs in an
    existing context instead of a fresh one, which is how a caller chains several
    actions into one session. `game_port` / `game_token` / `game_user` are ignored when
    `ctx` is given — the context already names its own client.
    """
    if ctx is None:
        ctx = new_context(hwnd, on_event, profile, variables, cancel,
                          game_port, game_token, game_user)
    return Interpreter(ctx).run_action(name)


def run_text(
    text: str,
    hwnd: int = 0,
    on_event: EventCallback | None = None,
    profile: Any = None,
    variables: dict | None = None,
    ctx: Context | None = None,
    cancel: Any = None,
    label: str = "inline",
    game_port: int | None = None,
    game_token: str | None = None,
    game_user: str | None = None,
) -> bool:
    """Execute DSL source given as text — the same language as an action file.

    For callers that hold a couple of commands rather than a script on disk (the
    panel's schedule lets a timer carry its steps inline in JSON). Everything the
    file form supports works here: several lines, blocks, conditions.

    Returns True when the script ran to the end (or STOPped deliberately), False
    on a parse or runtime error, which is reported through `on_event` exactly as
    a failing action file would be.
    """
    if ctx is None:
        ctx = new_context(hwnd, on_event, profile, variables, cancel,
                          game_port, game_token, game_user)
    interp = Interpreter(ctx)
    interp._log(f"> {label}")
    interp._depth += 1
    try:
        source, merged = prepare_source(text, ctx.vars)
        ctx.vars.update(merged)
        interp._run_block(parse_text(source))
        interp._depth -= 1
        interp._log(f"< {label} OK")
        return True
    except _HaltSignal:
        interp._depth -= 1
        interp._log(f"< {label} HALTED ({ctx.halt_reason or 'no reason given'})")
        return True
    except _FailSignal:
        interp._depth -= 1
        interp._log(f"< {label} FAILED — {ctx.fail_reason or 'FAIL'}")
        return False
    except (ScriptParseError, ScriptRuntimeError) as exc:
        interp._depth -= 1
        interp._log(f"< {label} FAILED — {exc}")
        return False
