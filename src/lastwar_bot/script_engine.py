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


def gated_chunk(btn, cap: int) -> str:
    """The Lua a gated press sends: read the button's count, and press if it is above zero.

    Out here rather than inside the interpreter so that it can be built — and compiled
    against the game's own Lua — without pressing anything
    (`tools/dev/check_gated_chunks.py`). See `Interpreter._press_gated` for why the two
    halves travel together.
    """
    if btn.batch_lua:
        body = ('local n = math.min(math.floor(tonumber(left) or 0), %d) '
                'if n > 0 then local ok2, e2 = pcall(function() %s end) '
                'if not ok2 then CS.UnityEngine.Debug.LogError('
                '"ACT fired=ERR:"..tostring(e2)) end end' % (int(cap), btn.batch_lua))
    else:
        body = ('local ok2, e2 = pcall(function() %s end) '
                'CS.UnityEngine.Debug.LogError("ACT fired="'
                '..(ok2 and "1" or ("ERR:"..tostring(e2))))' % btn.lua)
    return ('local left = nil '
            'local okc = pcall(function() left = %s end) '
            'CS.UnityEngine.Debug.LogError("ACT gate left="'
            '..(okc and tostring(left) or "ERR")) '
            'if okc and (tonumber(left) or 0) > 0 then %s end'
            % (btn.count_lua, body))


#: How long the link gate's verdict about one client stays good for
#: (:meth:`Interpreter._link_verdict`, #1290). Ten seconds is chosen from the other
#: side: the gate has always been asked once per RUN, and a run lasts anything from a
#: fifth of a second (a keyboard macro) to minutes (a recipe with a `WAIT` in it), so a
#: verdict was already allowed to be minutes old by the time a recipe finished acting on
#: it. Ten seconds of sharing it between runs is well inside that, and it is what turns
#: a macro's press from «two seconds of asking, 90 ms of pressing» into a press.
LINK_VERDICT_TTL = 10.0

#: `{(port, windows user): (expires_at, verdict)}` — see :meth:`Interpreter._link_verdict`.
#: Process-wide because the panel runs every profile's scenarios in one process, and
#: keyed by the client so that two profiles never read each other's answer.
_LINK_VERDICT: dict = {}


def forget_link_verdict() -> None:
    """Drop every cached link verdict — the next run asks the client again.

    For a caller that has just changed the thing the gate reads: a client restarted, a
    daemon re-attached, a test that must not inherit the previous one's answer.
    """
    _LINK_VERDICT.clear()


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
#: A `{name}` in a LOG line — the script's own variables, filled in as it is logged.
_VAR_REF_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
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
#: How long the socket verdict behind `client == ready` is reused before it is walked
#: again (#1399). A `WAIT` polls three times a second and the walk is the machine's whole
#: TCP table, so this is what keeps the CHEAP rung of the readiness ladder cheap. Two
#: seconds is `game_link.MACHINE_TTL_SEC` — the same answer the panel's own status poll
#: is content to be that far behind.
LINK_READ_TTL = 2.0
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

# COLLECT_VS_DUEL [STORE "<path>"] [NO_FETCH]
# The alliance duel, read out of the client and written down: both sides, every day.
# STORE names the ranking history to append to — a scenario passes the profile's own
# through an ARGS, so the recipe stays the same wherever it is played from.
_COLLECT_VS_RE = re.compile(r"^COLLECT_VS_DUEL\b(.*)$", re.IGNORECASE)
_COLLECT_VS_STORE_RE = re.compile(r"\bSTORE\s+(\"[^\"]*\"|'[^']*'|\S+)", re.IGNORECASE)

# COLLECT_SERVER_LIST [STORE "<path>"] [NO_FETCH] [DATES [N]]
# Every warzone the game has, written into the machine's own list. The game opens them
# continuously, so the list is re-read rather than shipped; DATES additionally asks when
# each of them opened, in batches, which is thousands of messages and therefore never
# implicit. STORE names the file, so a caller can keep a list of its own.
_COLLECT_SERVERS_RE = re.compile(r"^COLLECT_SERVER_LIST\b(.*)$", re.IGNORECASE)
_COLLECT_SERVERS_DATES_RE = re.compile(r"\bDATES(?:\s+(\d+))?\b", re.IGNORECASE)

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
    r"^JUMP\s+(\d+)\s*,\s*(\d+)(?:\s*,\s*(\d+))?(?:\s+ZOOM\s+(\d+))?\s*$",
    re.IGNORECASE,
)
# One lap of the whole map, scheduled inside the game. Every modifier is optional and
# order-independent; an unknown one is a parse error rather than a shrug, for the reason
# SCAN_SECRET_MISSIONS gives — a silently dropped ZOOM sweeps at the wrong height and
# comes back with the wrong half of the map.
_SWEEP_RE = re.compile(r"^SWEEP_MAP\b(.*)$", re.IGNORECASE)
_SWEEP_OPT_RE = re.compile(
    r"(ZOOM|STEP|EVERY|SERVER)\s+(\d+(?:\.\d+)?)", re.IGNORECASE,
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
# "Is the client up and in play?" — the readiness sign a LAUNCH waits on, and the one
# reading in the DSL that survives the Lua VM being unreachable. See
# Interpreter._client_ready() for the ladder and why a launch may not stand on `scene`
# alone (#1399).
_CLIENT_CHECK_RE = re.compile(
    r"^client\s*(==|!=)\s*(ready)\s*$", re.IGNORECASE,
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
    #: Camera height. `None` is the game's own jump height, which is what a jump about
    #: ONE tile wants; a scan passes a bigger one to load more map per jump (#1265).
    zoom: int | None = None


@dataclass(slots=True)
class SweepMapStmt(_Stmt):
    """One lap of the whole server map, so a passive scan has something to read."""
    zoom: int | None = None
    step: int | None = None
    every: float | None = None
    #: WHICH server the lap walks. `None` — and 0, which is what an empty argument
    #: substitutes to — means «ask the client inside the chunk», which is what every lap
    #: did before #1280 and what is right when nobody has said otherwise. A caller that
    #: KNOWS (the panel's «Сервер» box) names it, because the client's own answer is a
    #: cached manager field that keeps pointing at the server before last.
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
class CollectVsDuelStmt(_Stmt):
    """Read the alliance duel out of the client and write it into a ranking history.

    `store` is the SQLite file to append to — empty means «read and report, store
    nothing», which is what a run from a bare console does. `fetch` sends the duel
    screen's own ranking request first; without it only what the client already holds
    is read.
    """
    store: str = ""
    fetch: bool = True


@dataclass(slots=True)
class CollectServerListStmt(_Stmt):
    """Read every warzone the game has and write the list down.

    `store` names the file (empty = the machine's own, `server_list.cache_path()`);
    `fetch` sends the cross-server screen's own request first; `dates` is how many
    warzones may additionally be asked for an opening moment this run — 0 means «none»,
    which is the default, because asking about all of them is thousands of messages.
    """
    store: str = ""
    fetch: bool = True
    dates: int = 0


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

    m = _COLLECT_VS_RE.match(text)
    if m:
        rest = m.group(1)
        store = _COLLECT_VS_STORE_RE.search(rest)
        return CollectVsDuelStmt(
            text=text, line_no=ln,
            store=(store.group(1).strip("\"'") if store else ""),
            fetch="NO_FETCH" not in rest.upper(),
        ), i + 1

    m = _COLLECT_SERVERS_RE.match(text)
    if m:
        rest = m.group(1)
        store = _COLLECT_VS_STORE_RE.search(rest)
        dates = _COLLECT_SERVERS_DATES_RE.search(rest)
        return CollectServerListStmt(
            text=text, line_no=ln,
            store=(store.group(1).strip("\"'") if store else ""),
            fetch="NO_FETCH" not in rest.upper(),
            # `DATES` with no number means «as many as are missing» — the recipe that
            # wants a ceiling says one, and the cap is what keeps a run interruptible.
            dates=(int(dates.group(1)) if dates and dates.group(1) else
                   (10 ** 6 if dates else 0)),
        ), i + 1

    m = _GAME_SCENE_RE.match(text)
    if m:
        return GameSceneStmt(text=text, line_no=ln, scene=m.group(1).lower()), i + 1

    m = _JUMP_RE.match(text)
    if m:
        server = int(m.group(3)) if m.group(3) is not None else None
        zoom = int(m.group(4)) if m.group(4) is not None else None
        return JumpStmt(
            text=text, line_no=ln,
            x=int(m.group(1)), y=int(m.group(2)), server=server, zoom=zoom,
        ), i + 1

    m = _SWEEP_RE.match(text)
    if m:
        return _parse_sweep_map(m.group(1), text, ln), i + 1

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


def _parse_sweep_map(rest: str, text: str, ln: int) -> SweepMapStmt:
    """Parse the modifier tail of SWEEP_MAP — same rules as the scan's.

    A dropped modifier here is the same class of mistake: `ZOOM` decides whether the lap
    collects secret tasks or only bases, so ignoring a misspelt one would come back with
    the wrong half of the map and no complaint.
    """
    stmt = SweepMapStmt(text=text, line_no=ln)
    consumed = []
    for m in _SWEEP_OPT_RE.finditer(rest):
        consumed.append(m.span())
        keyword, value = m.group(1).upper(), m.group(2)
        if keyword == "ZOOM":
            stmt.zoom = int(float(value))
        elif keyword == "STEP":
            stmt.step = int(float(value))
        elif keyword == "SERVER":
            # 0 is «not named» — an unset `ARGS server` substitutes to it.
            stmt.server = int(float(value)) or None
        else:
            stmt.every = float(value)

    leftover = rest
    for start, end in reversed(consumed):
        leftover = leftover[:start] + leftover[end:]
    if leftover.strip():
        raise ScriptParseError(
            f"line {ln}: unrecognised SWEEP_MAP option: {leftover.strip()!r}"
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
    # THE OPERATOR ENDED THIS RUN (`cancel` below fired). A halt, so it unwinds like
    # `STOP` — but a `STOP` is the scenario deciding it is done and this is somebody
    # taking the game back, and the two must not look the same to a caller. A run marked
    # here has NOT finished: the panel's runner reports it as unsuccessful, and a
    # multi-step errand sharing one context refuses the steps behind the one that was
    # stopped rather than playing them into whatever made somebody press the button
    # (`panel/runtime/interrupt.py`).
    cancelled: bool = False
    # WHERE THE RUN HAS GOT TO — the statement about to be executed, as the script wrote
    # it, with its line number. Written by the interpreter and read by whoever is
    # watching: the panel's «Прервать» names it, because «прервали heal_units» says
    # nothing the press did not already say and «прервали heal_units на `WAIT wounded ==
    # 0` (строка 7)» says which minute of waiting was thrown away.
    step: str = ""
    #: The action being played right now — the innermost one, so a `CALL` names the
    #: sub-recipe the run is actually inside rather than the file it started from.
    action: str = ""
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
    # Optional STEP-ASIDE hook — a callable, checked at exactly the same moments as
    # `cancel` (between statements, between the presses of a repeat, between the polls
    # of a WAIT). It is handed THIS context and answers nothing; if somebody more urgent
    # wants the game it BLOCKS until they are done, and if it raises, the run ends the
    # way any runtime error does.
    #
    # It is handed the context because standing aside means letting the LEASE go, and
    # the lease is what `game_token` names and what `evaluator` was built with. A hook
    # that took no argument would have no way to tell the run that both are stale, and
    # every call after the first park would be refused as a lost lease.
    #
    # Why here and not in the panel: those three moments are the only ones a scenario
    # can be interrupted at without lying about what the game is doing, and the
    # interpreter is the only thing that knows where they are. The panel supplies the
    # callable (`panel/runtime/host.py`, `panel/runtime/schedule.py`) and decides what
    # «more urgent» means; the DSL only offers the moment (#1288).
    yield_to: Any = None
    # Optional LEASE-REGAIN hook — a callable handed THIS context, answering whether the
    # run may carry on. Called when the daemon refuses a chunk with `LeaseLost`, which is
    # what a run hears when the daemon RESTARTED underneath it: the new daemon starts
    # with no lease at all and the token this context was granted names one that no
    # longer exists.
    #
    # Without it the run is deaf for the rest of its life (#1411). `game_token` is read
    # ONCE, when the context is built, and every call after the restart is refused —
    # silently, because `_eval_lua_value` reads a refusal as «could not ask». That is how
    # `launch_game` sat out its last ten seconds against a daemon that had been warm for
    # three of them.
    #
    # `yield_to` already had to solve the same problem for the parking case, and it
    # solves it the same way: the hook takes a fresh lease, writes it here and drops the
    # evaluator that was built with the old one. This one only answers `True`/`False`,
    # because a lease that cannot be regained is a run that must stop rather than one
    # that must raise from inside a hook.
    regain: Any = None
    # Has the server link been read for this run yet? The gate on the driving
    # primitives (`_require_link`) is once per context, not once per press: a recipe
    # that taps thirty times must not walk the socket table thirty times, and a
    # caller chaining several actions through one context pays for it once.
    link_checked: bool = False
    # COUNTED presses attempted, and presses that actually went in. Only the gated
    # forms are counted (`TAP … xall`, a batch): they read the button's own count in
    # the same call they press, so a zero MEANS something. A plain `TAP x3` fires
    # blind and learns nothing, and is deliberately evidence of neither kind.
    #
    # What reads them is `panel/runtime/recovery.py::note_run` — «успешно ничего», the
    # only line in the log that was true through the two and a quarter hours of
    # docs/research/server-link-status.md §5.3, and which nothing was counting.
    taps_tried: int = 0
    taps_fired: int = 0


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
        #: Why the last `client == ready` reading said what it said, in words. A wait
        #: that runs out puts it in the failure, so «it did not come up» is never the
        #: whole of what the log gets to say (#1399).
        self._ready_why: "str | None" = None
        #: `(good until, state)` — the socket verdict, throttled (:meth:`_client_link`).
        self._link_read: "tuple[float, str] | None" = None

    def _log(self, msg: str) -> None:
        self.ctx.on_event("  " * self._depth + msg)

    def _fill(self, text: str) -> str:
        """Put the script's live variables into a `{name}` placeholder (#1292).

        `ARGS` substitution happens once, before the file is parsed, so `{level}` in a
        `LOG` line carries what the run STARTED with. This is the other half: a name a
        `READ_LUA … INTO` has since written is replaced with what it holds NOW, at the
        moment the line is logged. A star's countdown, a budget, a count — the numbers a
        standing order is judged on are all read rather than passed in, and a log line
        that cannot name them says «waiting» without ever saying for what or how long.

        An unknown name is left standing exactly as it is written, which is what the
        `ARGS` substitution does with a placeholder it does not know: a visible
        `{typo}` in the log beats a silently empty sentence.
        """
        def one(m: "re.Match") -> str:
            name = m.group(1)
            if name not in self.ctx.vars:
                return m.group(0)
            value = self.ctx.vars[name]
            return "?" if value is None else str(value)

        return _VAR_REF_RE.sub(one, text)

    def _check_cancel(self) -> None:
        """The run's checkpoint: stop if asked, step aside if somebody outranks us.

        Called between steps, between the presses of a repeat and between the polls of
        a WAIT — the three places a scenario is between two thoughts rather than in the
        middle of one.

        Stopping comes first: a run the operator has ended has no business waiting for
        anybody. `yield_to` is a no-op for every run that has none (a script from a
        shell, a press, an errand marked «сразу»), and one dict lookup for the rest.
        """
        cancel = self.ctx.cancel
        if cancel is not None and cancel.is_set():
            self.ctx.halt = True
            # …AND MARKED AS CANCELLED, not merely halted. `STOP` is the scenario saying
            # it is done and this is the operator taking the game back; a caller that
            # cannot tell them apart reports an interrupted run as a success and, worse,
            # plays the next step of the same errand (`panel/runtime/interrupt.py`).
            self.ctx.cancelled = True
            self.ctx.halt_reason = self.ctx.halt_reason or "stopped by the operator"
            raise _HaltSignal()
        step_aside = self.ctx.yield_to
        if step_aside is not None:
            step_aside(self.ctx)

    def _nap(self, seconds: float, slice_sec: float = 0.2) -> None:
        """Sleep, but stay interruptible — a long step must not be «доиграно до конца».

        A fixed `WAIT 60s` used to be one `time.sleep(60)`, which meant a Stop pressed a
        second into it was noticed a minute later: the flag is checked BETWEEN steps, and
        a sleep is the one step that spends its whole life inside itself. So the sleep is
        cut into slices and the ordinary checkpoint runs between them — which also lets a
        more urgent errand step in during a wait, exactly as it may during a polling one
        (:attr:`Context.yield_to`, and `WAIT <condition>` has always done this).

        The slice is short enough to feel instant to whoever pressed the button and long
        enough that a minute of waiting costs a few hundred cheap checks rather than
        thousands. Nothing else about the wait changes: it still sleeps the whole span
        unless somebody ends the run.
        """
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            self._check_cancel()
            left = deadline - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(slice_sec, left))

    # ---- entry point ----

    def run_action(self, name: str) -> bool:
        path = resolve_action(name)
        if path is None:
            self.ctx.on_event(f"!! action not found: {name} (looked in {ACTIONS_DIR} and dev/)")
            return False
        self._log(f"> action: {name}")
        self._depth += 1
        # WHICH recipe the run is inside, innermost first, put back on the way out: a
        # `CALL` three levels down is where a Stop actually lands, and «прервали
        # daily_routine» would point at the wrong file (`Context.action`).
        outer, self.ctx.action = self.ctx.action, name
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
            if self.ctx.cancelled:
                # A DIFFERENT WORD FROM «HALTED», and a different answer. The operator
                # ended this run: it did not finish, so the caller hears False (a `STOP`
                # still hears True), and the log says which of the two happened —
                # otherwise a month from now nobody can tell a scenario that decided it
                # was done from one somebody took the game back from (#1296 was the same
                # class of confusion).
                self._log(f"< action: {name} INTERRUPTED "
                          f"({self.ctx.halt_reason or 'no reason given'})")
                return False
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
        finally:
            self.ctx.action = outer

    # ---- block / statement dispatch ----

    def _run_block(self, statements: list[Any]) -> None:
        for stmt in statements:
            self._check_cancel()
            # WHERE THE RUN IS, for anybody watching from outside (`Context.step`). The
            # statement's own source line, which the parser kept for the log, and the
            # line number that finds it in the file. Two attribute writes per statement,
            # and they are what lets «Прервать» say what it threw away.
            self.ctx.step = f"{stmt.text.strip()} (line {stmt.line_no})"
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
                self._log(f'LOG "{self._fill(stmt.message)}"')
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
            # The four that DRIVE the game. The link gate stands here and nowhere else
            # — see `_require_link` for why «here» is the primitive and not the run.
            case GameSceneStmt():
                self._require_link(stmt)
                self._do_game_scene(stmt)
            case JumpStmt():
                self._require_link(stmt)
                self._do_jump(stmt)
            case SweepMapStmt():
                self._require_link(stmt)
                self._do_sweep_map(stmt)
            case TapStmt():
                self._require_link(stmt)
                self._do_tap(stmt)
            case LuaStmt():
                self._require_link(stmt)
                self._do_lua(stmt)
            # Gated with the SENDS, not with the reads: it asks the server for the
            # duel's ranking before reading it, so a deaf link makes it read whatever
            # the client happened to be holding and call it this week. Kept above
            # `ReadLuaStmt` so that case stays the last one — a read must not be gated,
            # and `tests/test_engine_link_gate.py` reads the arms in order to say so.
            case CollectVsDuelStmt():
                self._require_link(stmt)
                self._do_collect_vs_duel(stmt)
            # Gated for the same reason as the duel above: it ASKS the server for the
            # list before reading it back, so a deaf link would write down whatever the
            # client happened to be holding — or, on a fresh client, nothing at all.
            case CollectServerListStmt():
                self._require_link(stmt)
                self._do_collect_server_list(stmt)
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

        m = _CLIENT_CHECK_RE.match(cond)
        if m:
            ready = self._client_ready()
            return ready if m.group(1) == "==" else not ready

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

        **A LOST LEASE IS RETRIED ONCE, NEVER MORE** (#1411). The one refusal that says
        nothing about the chunk is `LeaseLost`: the daemon that granted this run's token
        went and came back, and the new one holds no lease at all. Everything else about
        the run is still true — the client, the port, the scenario's place in itself — so
        the honest answer is to take a lease again and send the same chunk, not to fail a
        recipe halfway through. Once, because a second refusal means somebody ELSE now
        holds the game, and going on pressing beside them is the one thing the lease
        exists to prevent.

        A run with no :attr:`Context.regain` (a script from a shell, a test) is exactly
        as it was: the refusal is raised and the caller decides.
        """
        try:
            return self._evaluator().run(chunk, marker, settle, early=early)
        except Exception as exc:               # noqa: BLE001 — re-raised unless it is the one
            if not (self._lease_lost(exc) and self._regain_lease()):
                raise
        return self._evaluator().run(chunk, marker, settle, early=early)

    @staticmethod
    def _lease_lost(exc: Exception) -> bool:
        """Is this the daemon saying «that token is not the live lease»?

        Asked by TYPE rather than by wording: `lua_client.LeaseLost` is raised for exactly
        this and nothing else, while the text is a sentence the daemon composes — and a
        matcher on it would also catch a chunk that happened to print it.
        """
        try:
            import lua_client
        except ImportError:                    # no bridge on the path, no lease to lose
            return False
        return isinstance(exc, lua_client.LeaseLost)

    def _regain_lease(self) -> bool:
        """Ask the caller for a lease again. ``False`` leaves the refusal to be raised.

        The hook is the panel's (`panel/runtime/host.py::regain_hook`) and it writes the
        new token onto the context. The evaluator is dropped HERE as well as there,
        because this side is the one that knows a retry is about to happen and a cached
        connection would carry the dead token straight back into the daemon.

        A hook that raises is treated as a hook that said no: the original `LeaseLost` is
        the failure worth reporting, and it is already on its way up.
        """
        hook = self.ctx.regain
        if hook is None:
            return False
        try:
            ok = bool(hook(self.ctx))
        except Exception:                      # noqa: BLE001 — the refusal is the report
            return False
        if ok:
            self.ctx.evaluator = None
        return ok

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
        self._run_lua(lua_actions.jump_to_coord(stmt.x, stmt.y, stmt.server, stmt.zoom))
        where = f"{stmt.x},{stmt.y}" + (f" srv {stmt.server}" if stmt.server is not None else "")
        if stmt.zoom is not None:
            where += f" zoom {stmt.zoom}"
        self._log(f"JUMP -> {where}")

    def _do_sweep_map(self, stmt: SweepMapStmt) -> None:
        """One lap of the whole map, and then WAIT it out.

        The lap runs inside the game — `lua_actions.fast_map_sweep` hands the waypoint
        list to the game's own timer — so the call returns in milliseconds while the
        camera is still walking. Returning there would let the next statement run over a
        sweep in flight, so the step sits out the span it just scheduled; a lap is a few
        seconds, which is the whole point of it.
        """
        self._tools_lib_on_path()
        import lua_actions
        self._run_lua(lua_actions.fast_map_sweep(stmt.zoom, stmt.step, stmt.every,
                                                 server=stmt.server))
        span = lua_actions.fast_sweep_seconds(stmt.step, stmt.every)
        zoom = stmt.zoom if stmt.zoom is not None else lua_actions.SWEEP_ZOOM_MAX
        where = f", server {stmt.server}" if stmt.server else ""
        self._log(f"SWEEP_MAP -> zoom {zoom}{where}, one lap, ~{span + 2:.0f}s")
        # …plus a breath for the last waypoint's answer to arrive: the map data lands a
        # beat after the camera stops, and a scan reading it must not be cut off mid-reply.
        # Sliced, so a lap of the whole map is not several seconds of a Stop being ignored.
        self._nap(span + 2.0)

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
            self.ctx.taps_tried += 1
            self.ctx.taps_fired += fired
            self._log(f"TAP {btn.label} x{stmt.count} -> {fired} press(es)")
            time.sleep(btn.wait)
            return
        for n in range(1, stmt.count + 1):
            self._check_cancel()
            moved = self._press_button(btn)
            suffix = f" ({n}/{stmt.count})" if stmt.count > 1 else ""
            if moved is False:
                raise ScriptRuntimeError(
                    f"line {stmt.line_no}: TAP {stmt.name} pressed and nothing moved — "
                    f"{btn.verify_lua} did not change within {btn.wait:g}s"
                )
            self._log(f"TAP {btn.label}{suffix}")
            if not btn.verify_lua:
                # A verified press has already waited for the thing it was waiting FOR.
                time.sleep(btn.wait)

    def _press_button(self, btn):
        """Fire one button press (its Lua), guarded, surfacing any Lua error.

        Returns `None` for a button with no `verify_lua` — the old contract, «it was
        issued» — and `True` / `False` for one that has it: whether the expression's
        value MOVED after the press.

        WHY THE RETURN EXISTS. Without a verifier this logs `ACT tap=ok` when the pcall
        did not throw, which says the call ran and nothing more. 32 of the 44 `TAP`
        lines in the shipped recipes cannot tell «pressed» from «did anything», and six
        fixes in a single day were that same shape (#1259, #1263, #1266, #1269) — an
        action reporting from the fact that it was ISSUED rather than from a re-read of
        what it changed.

        The before-value is read in the SAME chunk as the press, so nothing can move in
        between, and the poll afterwards uses the button's `wait` as a deadline rather
        than as a sleep (#1282, and §1.3 of the audit): a verified button is usually
        quicker as well as honest.
        """
        if not btn.verify_lua:
            chunk = (
                'local ok,err=pcall(function() %s end) '
                'CS.UnityEngine.Debug.LogError("ACT tap="..(ok and "ok" or ("ERR:"..tostring(err))))'
                % btn.lua
            )
            out_lines = self._run_lua(chunk, settle=0.1)
            for out in out_lines:
                if "ERR:" in out:
                    self._log(f"TAP {btn.label} error: {out.split('tap=', 1)[-1]}")
            self._relay(btn, out_lines)
            return None

        chunk = (
            'local okb,before=pcall(function() return %s end) '
            'local ok,err=pcall(function() %s end) '
            'CS.UnityEngine.Debug.LogError("ACT tap="..(ok and "ok" or ("ERR:"..tostring(err)))'
            '.." was="..(okb and tostring(before) or "ERR"))'
            % (btn.verify_lua, btn.lua)
        )
        before = None
        out_lines = self._run_lua(chunk, settle=0.1)
        self._relay(btn, out_lines)
        for out in out_lines:
            if "ERR:" in out and "tap=ERR" in out:
                self._log(f"TAP {btn.label} error: {out.split('tap=', 1)[-1]}")
                return False
            if " was=" in out:
                before = out.split(" was=", 1)[1].split()[0]
        # An unreadable before-value is not a verdict: the expression may have been
        # meaningless until the press opened the thing it reads. Poll for ANY readable
        # value in that case, which is still more than «the Lua did not raise».
        deadline = time.monotonic() + max(0.0, float(btn.wait))
        while True:
            now = self._eval_lua_value(btn.verify_lua)
            if now is not None and now != before:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def _relay(self, btn, lines) -> None:
        """Say the marker lines this button DECLARED the run is entitled to hear (#1416).

        Everything a chunk logs comes back from :meth:`_run_lua`; the press paths read
        out the two or three fields they need and drop the rest, which is where a
        button's own verdict about what the SERVER said used to end. `Button.relay`
        names the ones that must not be dropped — the robbery's
        `steal_done uuid=<u> how=<taken|gone|unanswered>` is the first, and the tab and
        the standing order have both been matching it in the event stream since #1272,
        against a stream that never carried it.

        Said through :meth:`_log`, so it lands wherever the rest of the run's commentary
        does — the profile's log, the phone, and the `on_event` callback a caller passed.
        The `ACT ` prefix is stripped: it is the marker the evaluator keys on, not a word
        anybody reads.
        """
        if not btn.relay:
            return
        for out in lines or ():
            body = out[4:] if out.startswith("ACT ") else out
            if body.startswith(tuple(btn.relay)):
                self._log(body)

    def _press_gated(self, btn, cap: int) -> tuple:
        """Read the button's own count AND press, in ONE call. -> ``(left, fired)``.

        `left` is what the count said BEFORE the press (``None`` if it could not be
        read), `fired` how many presses went in — 0 when the count was already zero, so
        a caller can tell "nothing to do" from "it would not press".

        WHY IT IS ONE CALL. `xall` used to read the count, get the answer back, and only
        then press: two trips through the game VM, and the FIRST thing a person's press
        did was a reading. Every trip is two of the client's frames plus the ~120 ms its
        answer costs (docs/research/game-call-latency.md), so the game did not visibly
        do anything for a third of a second after a button that should have moved at
        once. Reading and pressing in the same chunk is also more honest than it was:
        the gate is checked and spent in the same instant, on the same thread, with
        nothing able to change the count in between (#1230).

        The gate itself is unchanged — the count decides, not a guess — and so is the
        loop's confirming re-read afterwards: the next round's call reads before it
        presses, which is what quietly recovers a press the client's throttle dropped.
        """
        left, fired = None, 0
        out_lines = self._run_lua(gated_chunk(btn, cap), settle=0.35)
        self._relay(btn, out_lines)
        for out in out_lines:
            if "gate left=" in out:
                raw = out.split("gate left=", 1)[1].split()[0]
                try:
                    left = float(raw)
                except ValueError:
                    left = None
            elif "fired=" in out:
                raw = out.split("fired=", 1)[1].split()[0]
                if raw.startswith("ERR"):
                    self._log(f"TAP {btn.label} error: {raw}")
                    continue
                try:
                    fired = int(float(raw))
                except ValueError:
                    fired = 0
        return left, fired

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

        One round is ONE call — the count and the press travel together
        (:meth:`_press_gated`) — and a round that presses nothing ends the loop. A
        button with a `batch_lua` spends its whole quota inside that one call; an
        ordinary one goes a press at a time, with the button's own pause between them.
        Either way the count, not a guess, says when to stop, and the next round reads
        before it presses, which is what recovers a press the client's throttle dropped.
        """
        if not btn.count_lua:
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: button {stmt.name!r} does not support 'xall' "
                "(no count defined in the catalogue)"
            )
        pressed = 0
        while pressed < btn.max_taps:
            self._check_cancel()
            remaining, fired = self._press_gated(btn, cap=btn.max_taps - pressed)
            if remaining is None:
                self._log(f"TAP {btn.label} xall — count unavailable, stopping")
                break
            if remaining <= 0 or not fired:
                break
            pressed += fired
            if btn.batch_lua:
                self._log(f"TAP {btn.label} ({pressed}; {int(remaining) - fired} left)")
            else:
                self._log(f"TAP {btn.label} ({pressed}; {int(remaining)} available)")
            time.sleep(btn.wait)
        self.ctx.taps_tried += 1
        self.ctx.taps_fired += pressed
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

    def _require_link(self, stmt) -> None:
        """FAIL before a primitive that DRIVES the game, if the client cannot be heard.

        THE PLACEMENT IS THE POINT, and the first version got it wrong. Standing at the
        top of `run_action` this refused every recipe — including `restart_game.md`,
        whose `QUIT_GAME` / `CALL launch_game` / `ATTACH_GAME` send nothing to the server
        at all: they REPAIR the client. A lost link would have blocked the one cure for
        a lost link, and the six-hourly restart timer would have stopped working in
        exactly the case it exists for. It also re-probed on every nested `CALL`.

        So the gate stands on the four primitives that actually reach the game — `LUA`,
        `TAP`, `GAME`, `JUMP` — and the lifecycle primitives are free by construction
        rather than by an exception somebody has to remember to keep up to date. Reads
        (`READ_LUA`) are deliberately NOT gated: a stranded client answers them with
        yesterday's numbers, which is a lie, but the answer to that is to MARK the
        reading stale rather than to blind the diagnosis that is trying to find out why.

        Once per run, not once per press: a recipe that taps thirty times must not walk
        the socket table thirty times, and a link that dies mid-recipe is caught by the
        next run rather than mid-press.

        …AND NOT ONCE PER RUN EITHER, WHEN A RUN IS A KEYPRESS (#1290). «Once per run»
        was written for a recipe that then presses for a minute; a keyboard macro is a
        whole run that lasts a fifth of a second, and there the gate WAS the latency —
        two seconds of it against 90 ms of actual pressing. The verdict is a property of
        the CLIENT and not of the run, so it is cached per client for
        :data:`LINK_VERDICT_TTL` (:func:`_link_verdict`) — which is strictly inside the
        staleness the gate already lives with, since a run that passed it a moment
        before a kick goes on pressing for its whole length regardless.
        """
        if self.ctx.link_checked:
            return
        self.ctx.link_checked = True
        lost = self._link_verdict()
        if lost:
            self._log(f"line {getattr(stmt, 'line_no', '?')}: {lost}")
            self._fail(lost)

    def _link_verdict(self) -> "str | None":
        """:meth:`_link_lost`, remembered per client for :data:`LINK_VERDICT_TTL` (#1290).

        The cache is keyed by the CLIENT — the daemon port and the Windows session the
        run drives — because that is what the verdict is about; two profiles never share
        one. Both answers are kept, the refusal as well as the pass: a client that has
        lost the server is asked about again at the same rate as one that has not, and a
        panel full of timers hammering a dead link does not turn into a probe storm.

        A press made while a background errand is running usually finds the answer
        already there, which is the whole point: the errand paid for it a second ago.
        """
        key = (self._game_port(), (self.ctx.game_user or "").strip())
        now = time.monotonic()
        cached = _LINK_VERDICT.get(key)
        if cached is not None and now < cached[0]:
            return cached[1]
        verdict = self._link_lost()
        _LINK_VERDICT[key] = (now + LINK_VERDICT_TTL, verdict)
        return verdict

    def _link_lost(self) -> "str | None":
        """A sentence when this client has demonstrably lost the server, else ``None``.

        THE ONE THING NO READING INSIDE THE CLIENT CAN ANSWER. A stranded client draws
        its window, answers every Lua getter with the numbers it last received, and
        returns `true` from every send while nothing arrives — it is holding a socket
        the far end closed and does not know it
        (docs/research/server-link-status.md). So a recipe run against one presses all
        the way to the end and then fails on whatever it proves itself by, which reads
        as «the game refused» and is nothing of the kind: #1259 spent a day writing up a
        server refusal that never happened, against a client the panel had already
        declared dead in its own log two hours earlier.

        Refused ONLY on `lost` — an established socket is absent for perfectly innocent
        reasons (a client 45 seconds into starting up, a machine that will not attribute
        a foreign process's sockets), and `unknown` blocking a run would strand a
        healthy account behind a guess. A missing psutil, an unreadable socket table and
        an unresolvable session all land in `unknown` by construction, so the gate fails
        OPEN: it can only ever stop a run it has positive evidence against.

        …AND `online` IS NOT ENOUGH EITHER (#1269). «На связи» arrives before «готов
        играть»: a client that is starting up opens its control channel first, and for
        the minutes before the game's own conversation exists the socket verdict is
        `online` — honestly, by its own definition, and about the wrong conversation.
        Errands let through in that window reach a client that is not in the game yet and
        report success for doing nothing, which is the whole family of bug this file's
        gate exists to end (docs/research/server-link-status.md §5).

        So `online` is not taken as an answer: it is taken as «there is something to
        ask», and the client itself is asked whether it is in a session. Its own clock
        does that in one call and a client at the login screen cannot fake it (#1227).

        **NO SOCKET SHORTCUT, and that was measured rather than assumed.** The first
        version of this skipped the round trip when the live conversation carried the
        gateway race behind it — the losers a client leaves half-closed while logging in
        — on the reasoning that a raced conversation IS the game's. Live, twenty minutes
        later, a perfectly healthy client read `{10012: (established, 0 dead), 17935:
        (established, 0 dead)}`: no race at all. The shortcut would have been False on a
        healthy client, which is the harmless direction here but disproves the premise —
        so the premise is gone rather than kept as a "usually". Measured on this machine,
        the confirmation costs 0.31 s against a warm daemon, on a gate whose socket walk
        already cost ~1.0 s before it, and it runs once per scenario rather than once per
        statement.

        **NOR IS A CLOCK THE WHOLE ANSWER (#1270).** The confirmation above asks the
        client what time it is, because a client at the login screen cannot say. A
        KICKED one can, and does: the offset it answers from was set when it logged in
        and is kept locally (`UITimeManager.serverDeltaTime`), so it survives the account
        being taken and `game_clock.session_ready` stayed `True` throughout the two and a
        quarter hours of §5.3. The clock proves the client HAS logged in — never that it
        still IS in a session. So the kick is asked as its own question, of every client
        that gets this far, whatever its sockets and its clock said.

        **A failed ASK is not a refusal.** No daemon, no evaluator, a read that raised —
        all of that is «could not tell», and the gate goes on failing open, exactly as it
        does for `unknown`. Only a client that answers and says it is NOT in a session,
        or that shows the game's own «logged in on another device», is stopped.
        """
        try:
            self._tools_lib_on_path()
            import game_client
            import game_link

            pid = game_client.target_pid(port=self._game_port(),
                                         user=(self.ctx.game_user or "").strip() or None,
                                         log=lambda _msg: None)
            if pid is None:                  # no client to judge — the run will say so
                return None
            sockets = game_link.sockets_of([pid])
            state, _conn, _dead = game_link.classify(sockets)
            if state == game_link.LOST:
                return ("the client is no longer talking to the game server (its sockets "
                        "are half-closed) — nothing sent from here would reach it. "
                        "Restart the client; see docs/research/server-link-status.md")
            if state != game_link.ONLINE:    # unknown / offline still fail OPEN
                return None
            # The two questions a live-looking client still has to answer, in the order
            # that costs least: the socket verdict was free, the clock is one round trip,
            # the kick is another — and it is asked LAST because it is the rarer state,
            # not because it is the weaker reading.
            if self._kicked():
                return ("the account has been logged in on another device — this client "
                        "is showing the game's own «logged in elsewhere» message and "
                        "nothing sent from here will reach the server. See "
                        "docs/research/session-kick.md")
            if self._session_confirmed():
                return None
        except Exception:                    # noqa: BLE001 — a gate must never be the fault
            return None
        return ("the client is connected but not in the game yet — the link that is up "
                "is not the game's own conversation and the client will not say what "
                "time it is. Wait for the login to finish; see "
                "docs/research/server-link-status.md")

    def _kicked(self) -> bool:
        """Is this client showing «logged in on another device»? Anything else is False.

        The same fail-open rule as everything else in this gate, arrived at the same
        way: `game_kick.read` answers `None` for every way of not knowing — no daemon, a
        read that raised, a client that would not say — and `None` is a pass. Only a
        positive reading of the game's own sentence stops a run.

        No `link_lost` fallback is passed, deliberately: this is asked only where the
        sockets read `online`, so the reading has to stand on the game's own wording or
        not at all. A machine whose language tables cannot be found therefore keeps
        exactly the behaviour it had before this existed, rather than gaining a guess.

        **Only ever through a WARM daemon**, for the same reason
        :meth:`_session_confirmed` insists on one: a gate may not build an evaluator, and
        a vision-only scenario is documented never to touch the daemon at all.
        """
        try:
            import game_kick
            import lua_client

            ev = self.ctx.evaluator
            if ev is None:
                port = self.ctx.game_port
                port = int(port) if port is not None else lua_client.PORT
                if not lua_client.is_running(port=port, timeout=0.3):
                    return False
                ev = self._evaluator()
            return game_kick.read(ev) is True
        except Exception:                    # noqa: BLE001 — «could not tell» is a pass
            return False

    def _session_confirmed(self) -> bool:
        """Does the CLIENT say it is in a session? ``True`` also when it cannot be asked.

        Fails OPEN on purpose, like everything else in this gate: a missing daemon or a
        read that raised is «could not tell», and a gate may only ever stop a run it has
        positive evidence against. The question itself is the game's own clock — a client
        at the login screen answers every other question with a plausible lie and cannot
        answer that one (`game_clock`, #1227).

        **Only ever through a WARM daemon.** `_evaluator()` would happily build a local
        `LuaEval` instead, and that costs seconds and an attach — paid by every scenario
        passing this gate, including the vision-only ones that are documented never to
        touch the daemon at all. A gate may not be the most expensive thing in a run: no
        daemon on the port means «could not tell», which is a pass.

        **NOT `game_clock.session_ready`, and the difference is the whole safety of it.**
        That helper answers `False` for «at the login screen» AND for «the read failed»,
        which is fine for its own callers and fatal here: a daemon that raised would come
        back as positive evidence of not playing, and this gate would refuse every run on
        a machine whose VM simply cannot be reached. Fail-closed, silently, for ever —
        the exact direction the rest of this gate is built not to fail in. (Caught by
        `test_the_confirmation_fails_open_on_every_way_of_not_knowing`, which is why the
        round trip is made here rather than borrowed.)

        So the call is made directly: a raised `run` lands in the handler below and reads
        as «could not tell», while an answer that carries no plausible clock is the
        client itself saying it is not in a session. The chunk and both checks are
        `game_clock`'s own — no second copy of the question.

        THE SETTLE IS A DEADLINE (`early`, #1290), for the reason `game_clock.read` now
        gives: the client answers out of a field it already holds, so sitting out the
        whole second bought nothing. 1055 ms became 90.
        """
        try:
            import game_clock
            import lua_actions
            import lua_client

            ev = self.ctx.evaluator
            if ev is None:
                port = self.ctx.game_port
                port = int(port) if port is not None else lua_client.PORT
                if not lua_client.is_running(port=port, timeout=0.3):
                    return True
                ev = self._evaluator()
            lines = ev.run(lua_actions.game_server_time(), game_clock.MARKER, 1.0,
                           early=True)
            server_ms = game_clock.parse_ms(lines)
            return server_ms is not None and game_clock.plausible(server_ms)
        except Exception:                    # noqa: BLE001 — «could not tell» is a pass
            return True

    def _current_scene(self) -> str:
        """Read the game scene from the Lua VM (state, not pixels): 'city' / 'world' / 'unknown'.

        'city' means fully at the home base — the city scene AND the main HUD (UIMain)
        is up, so a still-loading client reads 'unknown', which is exactly what a launch
        `WAIT scene == city` wants. Any VM failure (game not up yet, daemon re-hijacking
        the freshly-launched process) also reads 'unknown', so the caller just keeps
        polling; the daemon auto-rebuilds its LuaEval on a stale handle, so this recovers
        by itself across a restart. No screenshots, no SIFT.

        THE TWO KINDS OF 'unknown' ARE FOLDED TOGETHER HERE ON PURPOSE — «the client is
        loading» and «nobody could be asked» read the same, which is what every `scene`
        condition wants. What must NOT fold them is a launch: see :meth:`_scene_reading`.
        """
        return self._scene_reading() or "unknown"

    def _scene_reading(self) -> "str | None":
        """The scene, or ``None`` when the VM could not be asked at all (#1399).

        The same round trip :meth:`_current_scene` makes, with the one distinction that
        method deliberately throws away: `'unknown'` is the CLIENT saying it is in no
        scene yet, and `None` is nobody having answered — no daemon, no client, a read
        that raised. A launch has to tell those apart, because «could not ask» is
        precisely the state a freshly relaunched client is in while its daemon is being
        rebuilt, and treating it as «not ready» is what made `launch_game` sit out its
        whole 180 s cap over a client that had been playable for two minutes.
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
        except Exception:  # noqa: BLE001 — any VM hiccup is just "could not ask"
            return None
        if val is None:
            return None
        return val if val in ("city", "world") else "unknown"

    def _vm_reachable(self) -> bool:
        """Is there a WARM Lua daemon to ask, right now?

        The same rule :meth:`_session_confirmed` and :meth:`_kicked` already keep, and
        for a sharper reason here: with no daemon `_evaluator()` builds a LOCAL
        `LuaEval`, which is an il2cpp enumeration through a thread hijack — seconds of
        work, against a client that is still booting, repeated on every poll of a wait
        that may run for three minutes. A readiness poll may not be the most expensive
        thing on the machine, so when the port does not answer this says so and the
        ladder falls back to a reading that costs a socket table.

        An evaluator already built and cached on the context counts: the run has one, so
        asking is free whatever the port says.
        """
        if self.ctx.evaluator is not None:
            return True
        try:
            self._tools_lib_on_path()
            import lua_client

            port = self.ctx.game_port
            port = int(port) if port is not None else lua_client.PORT
            return bool(lua_client.is_running(port=port, timeout=0.3))
        except Exception:                    # noqa: BLE001 — cannot even ask the port
            return False

    def _client_link(self) -> str:
        """This profile's client as the OPERATING SYSTEM sees it: online/lost/unknown/offline.

        `tools/lib/game_link.py`, the same reading the panel's status line prints and the
        run gate (:meth:`_link_lost`) judges by — not a second opinion invented for the
        launch. It needs no Lua, no daemon and no screenshot, which is the whole reason
        the ladder can lean on it while the VM is being rebuilt.

        Held for :data:`LINK_READ_TTL` between walks. `sockets_of` is an uncached walk of
        the machine's whole TCP table, and a `WAIT` polls three times a second: without
        this the cheap rung of the ladder would be the expensive thing on the box.
        """
        now = time.monotonic()
        if self._link_read is not None and now < self._link_read[0]:
            return self._link_read[1]
        state = self._read_client_link()
        self._link_read = (now + LINK_READ_TTL, state)
        return state

    def _read_client_link(self) -> str:
        """:meth:`_client_link` without the throttle — one walk of the socket table."""
        try:
            self._tools_lib_on_path()
            import game_client
            import game_link

            pid = game_client.target_pid(port=self._game_port(),
                                         user=(self.ctx.game_user or "").strip() or None,
                                         log=lambda _msg: None)
            return game_link.state_of([pid] if pid else [])
        except Exception:                    # noqa: BLE001 — cannot tell is not a verdict
            return "unknown"

    def _client_ready(self) -> bool:
        """«The client is up and a person could play» — the LAUNCH sign, as a ladder (#1399).

        THE BUG THIS EXISTS FOR. `launch_game` waited on `scene != unknown`, and the
        scene can only be read through the Lua VM — which, after a relaunch, is the one
        thing on the machine that is down: the daemon is pinned to the process that just
        died and the panel is rebuilding it. Live on 2026-08-14 the client's process was
        back 8 s after `START_GAME` and its conversation with the game server 32 s after
        it, while the daemon stayed down until 170 s — so the wait sat out its whole
        180 s cap and reported a FAILED launch, twelve times in one evening, over a
        client that the very next scenario read as `scene == city`.

        So the sign is a ladder, strongest first, and every rung is a reading the
        repository already had:

        1. **The scene**, when there is a warm daemon to ask (:meth:`_vm_reachable`).
           A named scene is the whole answer — the client is interactive. A client that
           answers `'unknown'` is loading, and THAT is a real «not yet»: it is the game
           itself saying so, so the ladder stops here rather than falling through to a
           weaker rung that would overrule it.
        2. **The socket**, when nobody could be asked at all. `game_link` ONLINE means
           the client holds an established conversation with the game server — it got
           through the launcher, the update check and the login. It is a weaker sign
           than a scene (docs/research/server-link-status.md: «на связи» arrives before
           «готов играть»), which is exactly why it is only ever consulted when the
           stronger one is unavailable, and why the errand gate goes on making every
           scenario prove the session for itself.

        Nothing here starts a daemon, a client or a scenario: it is a reading, and the
        daemon gate (#1393) stays the only thing that decides whether anything may run.
        """
        scene = self._scene_reading() if self._vm_reachable() else None
        if scene is not None:
            self._ready_why = ("the game says it is in no scene yet (still loading)"
                               if scene == "unknown" else f"scene {scene}")
            return scene != "unknown"
        link = self._client_link()
        self._ready_why = {
            "online": "no daemon to ask, but the client's link to the game server is up",
            "lost": "no daemon to ask, and the client's sockets say the server hung up",
            "offline": "no daemon to ask, and no client process is running",
        }.get(link, "no daemon to ask, and the client's sockets make no verdict yet")
        return link == "online"

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

    def _do_collect_vs_duel(self, stmt: CollectVsDuelStmt) -> None:
        """Read the alliance duel and, when asked, write it into a ranking history.

        Two registers come back for the recipe to gate on — `VS_DAYS`, how many days of
        the week have rows, and `VS_ROWS`, how many rows in all. A week that has not
        started reads as zero of both and is a state, not a failure: `IF VS_DAYS == 0`
        is how a recipe says so.

        NOTHING IS STORED WHEN NOTHING CAME BACK. An empty read written down would put
        an empty week on top of a full one, and the store's own «unchanged, skip» rule
        cannot tell the two apart — it compares a board against its last snapshot, and
        an empty board is not the same board.
        """
        self._tools_lib_on_path()
        try:
            import leaderboard_store
            import vs_duel
        except ImportError as exc:               # pragma: no cover — a broken checkout
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: COLLECT_VS_DUEL needs tools/lib — {exc}"
            ) from exc

        if stmt.fetch:
            # The duel screen's own request, one message per ranking. A `type = 0`
            # reply carries every day of the week at once.
            for rank_type in (vs_duel.RANK_DAY, vs_duel.RANK_WEEK):
                self._run_lua(vs_duel.fetch_chunk(rank_type), marker=vs_duel.MARKER,
                              settle=2.0)
        lines = self._run_lua(vs_duel.read_chunk(), marker=vs_duel.MARKER, settle=3.0,
                              early=False)
        state = vs_duel.parse(lines)
        players = state.get("players", [])
        days = sorted({p.get("day") for p in players if p.get("day") is not None})
        self.ctx.vars["VS_DAYS"] = len(days)
        self.ctx.vars["VS_ROWS"] = len(players)
        self.ctx.vars["VS_SIDES"] = len(state.get("sides", []))

        if not players and not state.get("sides"):
            self._log("COLLECT_VS_DUEL — no duel in this client; nothing stored")
            return
        if not stmt.store:
            self._log(f"COLLECT_VS_DUEL — {len(state.get('sides', []))} side(s), "
                      f"{len(days)} day(s), {len(players)} row(s); not stored")
            return
        conn = leaderboard_store.connect(stmt.store)
        try:
            rows = vs_duel.store_records(state, int(time.time()))
            saved = leaderboard_store.save_records(conn, rows, int(time.time()))
            leaderboard_store.save_sighting(
                conn, int(time.time()), "al.battle.rank.info",
                leaderboard_store.VERDICT_KEPT if saved
                else leaderboard_store.VERDICT_EMPTY,
                None if saved else "every board identical to its last snapshot",
                rows_seen=len(rows), rows_kept=sum(saved.values()), source="game")
        finally:
            conn.close()
        self._log(f"COLLECT_VS_DUEL — {len(state.get('sides', []))} side(s), "
                  f"{len(days)} day(s), {len(players)} row(s), "
                  f"{sum(saved.values())} stored")

    def _do_collect_server_list(self, stmt: CollectServerListStmt) -> None:
        """Read every warzone the game has, and write the list down.

        Three registers come back for a recipe to gate on — `SERVERS_TOTAL` (how many the
        game says there are), `SERVERS_READ` (how many came back this run) and
        `SERVERS_DATED` (how many opening moments are on file afterwards).

        NOTHING KNOWN IS FORGOTTEN. The read is paged, so an interrupted one brings back
        a prefix rather than the lot — and a prefix written over the file would lose every
        warzone past it until somebody read the whole thing again. `server_list.merge`
        folds instead of replacing, which is also what lets the dates arrive over several
        runs (they are asked for in batches of a few hundred).
        """
        self._tools_lib_on_path()
        try:
            import server_list
        except ImportError as exc:               # pragma: no cover — a broken checkout
            raise ScriptRuntimeError(
                f"line {stmt.line_no}: COLLECT_SERVER_LIST needs tools/lib — {exc}"
            ) from exc

        path = stmt.store or server_list.cache_path()
        # The reply is not kept by the client, so the catcher goes on FIRST and the
        # request second; a client that already has the wrapper keeps the one it has.
        self._run_lua(server_list.install_chunk(), marker=server_list.MARKER, settle=1.0)
        if stmt.fetch:
            self._run_lua(server_list.fetch_chunk(), marker=server_list.MARKER, settle=1.0)
            self._nap(1.5)                       # the list travels; nothing to poll for

        found: list = []
        total = -1
        offset = 0
        while True:
            lines = self._run_lua(server_list.read_chunk(offset, server_list.BATCH),
                                  marker=server_list.MARKER, settle=2.0, early=False)
            if total < 0:
                total = server_list.total(lines)
            page = server_list.parse_page(lines)
            found.extend(page)
            offset += len(page)
            if not page or total <= 0 or offset >= total:
                break
            self._check_cancel()

        saved = server_list.merge(server_list.load(path), servers=found)
        dated = 0
        if stmt.dates:
            dated = self._ask_server_dates(server_list, saved, path, stmt.dates)
            saved = server_list.load(path)
        else:
            server_list.save(saved, path)

        on_file = sum(1 for row in server_list.rows(saved) if row.get("open_ms"))
        self.ctx.vars["SERVERS_TOTAL"] = total if total > 0 else len(found)
        self.ctx.vars["SERVERS_READ"] = len(found)
        self.ctx.vars["SERVERS_DATED"] = on_file
        self._log(f"COLLECT_SERVER_LIST — {len(found)} of {total} warzone(s) read, "
                  f"{on_file} dated ({dated} asked for this run), stored in {path}")

    def _ask_server_dates(self, server_list, saved: dict, path: str, cap: int) -> int:
        """Ask for the opening moments still missing, in batches, and keep each batch.

        Kept AS IT GOES rather than at the end: this is thousands of messages on a full
        list, and a run somebody interrupts half way through should leave half the dates
        on file instead of none.
        """
        wanted = server_list.undated(saved)[:max(0, int(cap))]
        if not wanted:
            server_list.save(saved, path)
            return 0
        asked = 0
        for start in range(0, len(wanted), server_list.ASK_BATCH):
            batch = wanted[start:start + server_list.ASK_BATCH]
            self._run_lua(server_list.ask_dates_chunk(batch),
                          marker=server_list.MARKER, settle=1.0)
            asked += len(batch)
            self._nap(3.0)                       # measured: 300 answers land inside 3 s
            dates: dict = {}
            offset = 0
            while True:
                # NARROWED TO THIS BATCH on purpose: the client's dictionary keeps
                # everything every earlier batch put in it, so re-reading all of it after
                # each one turns a sweep of thousands into a quadratic crawl.
                lines = self._run_lua(
                    server_list.read_dates_chunk(batch, offset, server_list.BATCH),
                    marker=server_list.MARKER, settle=2.0, early=False)
                page = server_list.parse_dates(lines)
                dates.update(page)
                offset += len(page)
                if len(page) < server_list.BATCH:
                    break
                self._check_cancel()
            saved = server_list.merge(server_list.load(path), dates=dates)
            server_list.save(saved, path)
            self._check_cancel()
        return asked

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
        forget_link_verdict()                 # …and nothing may quote the old client's link
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
        forget_link_verdict()                 # the client is a new one; so is its link
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
            self._nap(2.0)                   # a minute of waiting for a client, stoppable
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
            self._nap(seconds)               # …and stoppable while it waits (see _nap)
            return

        # Otherwise, poll the condition until True or timeout. THE TIMEOUT IS A CAP AND
        # NOT A DURATION: the loop leaves the moment the sign is there, and `WITHIN` only
        # decides how long a sign that never arrives is waited for.
        started = time.monotonic()
        deadline = started + stmt.timeout
        self._ready_why = None
        said: "str | None" = None
        while time.monotonic() < deadline:
            self._check_cancel()
            if self.eval_condition(stmt.condition, stmt.line_no):
                self._log(f"WAIT {stmt.condition} -> matched after "
                          f"{time.monotonic() - started:.1f}s"
                          + (f" ({self._ready_why})" if self._ready_why else ""))
                return
            # The steps of a long wait, as they happen — a launch that takes two minutes
            # should say WHERE those two minutes went, not just that they passed. Only
            # when the reading itself changes, so a three-minute wait writes four lines.
            if self._ready_why and self._ready_why != said:
                said = self._ready_why
                self._log(f"WAIT {stmt.condition} — {said} "
                          f"({time.monotonic() - started:.1f}s)")
            time.sleep(0.3)
        raise ScriptRuntimeError(
            f"line {stmt.line_no}: WAIT {stmt.condition} timed out after {stmt.timeout:.1f}s"
            + (f" — {self._ready_why}" if self._ready_why else "")
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
    yield_to: Any = None,
    regain: Any = None,
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
                  game_user=game_user, yield_to=yield_to, regain=regain)
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
    yield_to: Any = None,
    regain: Any = None,
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
                          game_port, game_token, game_user, yield_to, regain)
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
    yield_to: Any = None,
    regain: Any = None,
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
                          game_port, game_token, game_user, yield_to, regain)
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
        if ctx.cancelled:                    # the operator, not the script (see run_action)
            interp._log(f"< {label} INTERRUPTED ({ctx.halt_reason or 'no reason given'})")
            return False
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
