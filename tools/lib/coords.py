r"""Canonical world-coordinate format + a tolerant parser (single source of truth).

To make every script emit coordinates the same way, format them with `fmt()`:

    coords.fmt(561, 492)        -> "X:561 Y:492"          (current server)
    coords.fmt(561, 492, 972)   -> "#972 X:561 Y:492"     (explicit server)

The format is human-readable on purpose: a `#server` prefix and labelled `X:`/`Y:` fields.
The panel turns that token — and, tolerantly, a few other formats seen in the wild
(`@[123,456]`, `(123,456)`, `123/456`, `координаты 123 456`) — into a clickable link that
jumps there. `parse()` returns the spans so the log can tag them.

The parser is deliberately conservative about *bare* number pairs: a comma pair like the
`1045, 408` in "server 1045, 408 map response(s)" is NOT a coordinate. Only labelled forms
(`X:.. Y:..`), bracketed `(..)`, the legacy `@[..]`, or a slash pair are recognised, so a
progress line full of counts never lights up as a link.
"""
from __future__ import annotations
import re

MAX_COORD = 2000  # sanity bound: real world tiles sit well under this; filters stray numbers


def fmt(x: int, y: int, server=None) -> str:
    """Canonical token for a world coordinate. Use this everywhere coords are printed."""
    core = f"X:{x} Y:{y}"
    return core if server in (None, "") else f"#{server} {core}"


# Optional trailing server: "|972", "@972", "server 972", "сервер 972".
_SRV = r"(?:\s*(?:\||@|(?:server|сервер)\s+)\s*(?P<srv>\d{1,5}))?"

_PATTERNS = [
    # canonical, human-readable: #972 X:561 Y:492  (leading #server, labelled fields)
    re.compile(r"#\s*(?P<srv>\d{1,5})\s+[XxХх]\s*[:=]?\s*(?P<x>-?\d{1,4})\s*[,; ]{0,3}\s*[YyУуy]\s*[:=]?\s*(?P<y>-?\d{1,4})"),
    # labelled without a server: X:123 Y:456  /  Х=123 У=456  (optional trailing server)
    re.compile(r"[XxХх]\s*[:=]?\s*(?P<x>-?\d{1,4})\s*[,; ]{0,3}\s*[YyУуy]\s*[:=]?\s*(?P<y>-?\d{1,4})" + _SRV),
    # legacy canonical @[X,Y] / @[X,Y|S]
    re.compile(r"@\[\s*(?P<x>-?\d{1,4})\s*,\s*(?P<y>-?\d{1,4})\s*(?:\|\s*(?P<srv>\d{1,5})\s*)?\]"),
    # keyword: координаты 123 456 / coords 123, 456
    re.compile(r"(?:коорд\w*|coord\w*)\D{0,6}?(?P<x>-?\d{1,4})\D{1,4}?(?P<y>-?\d{1,4})" + _SRV, re.I),
    # (X,Y)
    re.compile(r"\(\s*(?P<x>-?\d{1,4})\s*,\s*(?P<y>-?\d{1,4})\s*\)" + _SRV),
    # X/Y (>=2 digits each so loot counts like "0/3" are not coordinates)
    re.compile(r"(?<!\d)(?P<x>\d{2,4})\s*/\s*(?P<y>\d{2,4})(?!\d)" + _SRV),
    # NB: a *bare comma* pair (e.g. "1045, 408") is intentionally NOT matched — it produced
    # false links on progress lines like "server 1045, 408 map response(s)".
]


def parse(text: str):
    """Return non-overlapping matches as (start, end, x, y, server|None), left to right.

    Earlier patterns win on overlap (canonical/labeled beat a bare comma pair). Coordinates
    outside [0, MAX_COORD] are dropped as noise; the server, if present, is not range-limited.
    """
    found = []
    for pat in _PATTERNS:
        for m in pat.finditer(text):
            try:
                x, y = int(m.group("x")), int(m.group("y"))
            except (TypeError, ValueError):
                continue
            if not (0 <= x <= MAX_COORD and 0 <= y <= MAX_COORD):
                continue
            srv = m.groupdict().get("srv")
            found.append((m.start(), m.end(), x, y, int(srv) if srv else None))
    # resolve overlaps: leftmost first, longer span wins at the same start
    found.sort(key=lambda t: (t[0], -(t[1] - t[0])))
    out, last_end = [], -1
    for f in found:
        if f[0] >= last_end:
            out.append(f)
            last_end = f[1]
    return out


if __name__ == "__main__":  # quick self-check
    samples = [
        fmt(561, 492), fmt(561, 492, 972),          # canonical: "X:561 Y:492" / "#972 X:561 Y:492"
        "@[561,492]", "@[561,492|972]",             # legacy still parses
        "X:123 Y:456", "(123,456)", "123/456",
        "координаты 123 456", "lvl 12 (561,492)  server 935  steal 0/3", "rc=1 done",
        # the reported false positive: must NOT produce a link
        "…running — server 1045, 408 map response(s), 12 tile(s)",
    ]
    for s in samples:
        print(f"{s!r:60} -> {parse(s)}")
