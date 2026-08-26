r"""Every coordinate the phone shows, marked as a place it can be sent to (#1982).

THE PERSON'S WORDS: «Координаты не кликабельны, любые координаты должны быть кликабельны
и приводить к переходу на них в игре». The window has had this since it had a log — a
coordinate in a line is a link, and clicking it walks the camera there
(`panel/runtime/log_view.py`). The phone drew the same strings as plain text.

WHERE THE PARSING LIVES, AND WHY IT IS NOT IN THE BROWSER. `tools/lib/coords.py` is the
one parser in this repository: it knows the canonical `#935 X:961 Y:399`, the legacy
`@[x,y|s]`, `(x,y)`, `x/y`, «координаты x y» — and, just as importantly, what is NOT a
coordinate (a bare comma pair on a progress line, a `0/3` loot count). A second parser in
JavaScript would be a second answer to «is this a place», and the two would disagree the
first time either was touched. So the marking happens HERE, on the strings the panel is
already about to send, and the browser only draws what it is handed.

WHAT IT SENDS. A string that holds no coordinate is left exactly as it was — the payload
does not grow for the ninety per cent of lines that are prose. A string that holds one
gets a sibling field of PARTS:

    "text":  "#935 X:961 Y:399",
    "text_parts": [{"c": {"x": 961, "y": 399, "server": 935, "text": "#935 X:961 Y:399"}}]

Parts rather than character offsets, deliberately: Python counts code points and
JavaScript counts UTF-16 units, so an offset either side of an emoji — and these lines
carry ⭐ — would slice a coordinate in half. Parts cannot drift.
"""
from __future__ import annotations

#: The string fields worth looking at, per kind of thing a screen carries. Not every
#: field: a locale KEY is not prose (`label`, `title`, `pill`, `empty`) and running a
#: parser over it would be looking for coordinates in `secrettasks.col.level`.
CARD_FIELDS = ("head",)
ITEM_FIELDS = ("text", "detail", "note")
ROW_FIELDS = ("value",)
FACT_FIELDS = ("value",)


def parts(text) -> "list | None":
    """``[{"t": …} | {"c": {...}}, …]`` for a string with coordinates in it, else ``None``.

    ``None`` is «nothing to mark», and it is what keeps this cheap: the caller then adds
    no field at all.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    import coords                            # lazy: tools/lib is on the path by then

    try:
        found = coords.parse(text)
    except Exception:                        # noqa: BLE001 — a link, never the payload
        return None
    if not found:
        return None
    out: list = []
    at = 0
    for start, end, x, y, server in found:
        if start > at:
            out.append({"t": text[at:start]})
        out.append({"c": {"x": int(x), "y": int(y),
                          "server": int(server) if server else 0,
                          "text": text[start:end]}})
        at = end
    if at < len(text):
        out.append({"t": text[at:]})
    return out


def _mark(box: dict, fields) -> None:
    """Add `<field>_parts` beside every named field of ``box`` that holds a coordinate."""
    if not isinstance(box, dict):
        return
    for field in fields:
        said = parts(box.get(field))
        if said is not None:
            box[field + "_parts"] = said


def mark_screen(view: dict) -> dict:
    """Walk one screen's payload and mark every coordinate a person can see.

    In place and returned, because the caller is handing the dictionary straight out.
    A screen is small change — the map's thirteen cards and six hundred rows parse in a
    few milliseconds — and it is the same walk the page would otherwise do in the
    browser, done once and correctly.
    """
    if not isinstance(view, dict):
        return view
    for card in view.get("cards") or ():
        if not isinstance(card, dict):
            continue
        _mark(card, CARD_FIELDS)
        for row in card.get("rows") or ():
            _mark(row, ROW_FIELDS)
        for item in card.get("items") or ():
            if not isinstance(item, dict):
                continue
            _mark(item, ITEM_FIELDS)
            for fact in item.get("facts") or ():
                _mark(fact, FACT_FIELDS)
    return view


def mark_line(row: dict) -> dict:
    """The same for one log line — the window's own links, on the phone at last."""
    _mark(row, ("text",))
    return row
