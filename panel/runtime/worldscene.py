"""The world as the PANEL believes it to be, as plain numbers (#2018).

Everything the bot decides — which mine to take, which starred tile to rob, which
truck is worth a march — rests on a model of the map assembled from what the wire
said. Nothing in the panel ever DREW that model, so «is our picture the same as the
game's?» could only be answered by reading tables of coordinates. This module is the
other half of that answer: one flat list of objects with a place, a kind and a couple
of readings each, which the web front-end paints on a canvas beside the real client.

**IT READS NOTHING FROM THE GAME.** Every source below is already on this profile's
disk — a capture checkpoint the sniffer child rewrites on its own tick, a blob the
tab that owns it saved, a table a scenario filled. Asking the client would make an
open page into a background poll of the wire, which is exactly what `CLAUDE.md`
forbids («Read once, then LISTEN»); a page that is out of date says HOW old it is
instead, and a person presses the tab that fills it if they want more.

**READ-ONLY, and there is nothing here that could be otherwise.** No press, no Lua,
no march — the person asked for a picture to compare against, not a second client.

What is drawn, and where each kind comes from:

===========  ============================================================
`base`       player bases — `world_map.json`, the map sweep's own players
`mine`       resource nodes — `world_map.json`
`truck`      player lorries on the road — `world_map.json` (interpolated)
`train`      alliance trains — `world_map.json`
`monster`    the `monsters` table (#1963) — filled by a client-memory read
`secret`     the ★ list the «Секретки» tab keeps (`secret_tasks_state`)
`ghost`      the list «Призрак: карта» keeps (`ghost_map_state`)
`treasure`   the treasure scan's checkpoint (`world_treasures.json`)
===========  ============================================================

**A record's shape is read leniently on purpose.** The eight sources were written by
six different authors over two years and spell the same fact three ways (`server_id`
/ `server`, `owner_name` / `name`, a level that is sometimes a string). A strict
reader would answer «пусто» for a source that had merely renamed a field, which is
the one failure mode a comparison tool must not have — it would look exactly like
«панель ничего не знает про эту область».
"""
from __future__ import annotations

import json
import os
import time

#: Every kind the scene can hold, in the order a legend lists them.
KINDS = ("base", "mine", "monster", "secret", "ghost", "treasure", "truck", "train")

#: How old a sighting may be and still be drawn. The same window the world pages age
#: their rows out by (`panel/tabs/secret_tasks/world.py`), so the picture and the
#: tables agree about what «current» means instead of one keeping what the other drops.
SIGHTING_TTL_SEC = 15 * 60

#: How many objects of one kind travel to the browser. A whole-server lap holds twelve
#: thousand mines; a phone handed all of them waits on the wire for what it cannot see
#: anyway at that zoom. What is left out is COUNTED and said out loud (`hidden`), the
#: same bargain the world tables already make with «скрыто».
MAX_PER_KIND = 4000

#: WHERE WE HAVE LOOKED, kept for good — the blob the checkpoint's own grid is folded
#: into (#2018). The capture child knows only what it has heard since it started; this
#: is what THIS ACCOUNT has swept, and it is game data, so it lives in the database and
#: not in a file (`CLAUDE.md`, «Game data lives only in the database»). Read and written
#: WHOLE, a few thousand small rows — which is the test for a blob rather than a table.
COVERAGE_BLOB = "world_coverage"

#: How long a swept cell is remembered here. Longer than the child's own day: the panel
#: is what accumulates, and a week is roughly how far back «мы там были» is still worth
#: drawing at all.
COVERAGE_KEEP_SEC = 7 * 24 * 3600

#: …and the ceiling, oldest dropped first. Eight warzones of a 1000-wide grid.
MAX_COVERAGE_CELLS = 13000


#: The last parse of each checkpoint, keyed by what the file LOOKED like when it was
#: read: `{path: (mtime, size, parsed)}` (#2660). A capture child rewrites these whole
#: on every tick, and `world_map.json` is megabytes — so a page being looked at was
#: parsing all of it on every poll, whether or not the child had written anything since.
#: The mtime and the size together are the honest test of «is this the same file»: a
#: rewrite always moves the mtime, and the size catches the rare rewrite inside one
#: clock tick.
#:
#: WHAT COMES BACK MUST NOT BE MUTATED. Every caller in this module reads it and builds
#: its own objects (`_object`, `_rows`), which is what makes the sharing safe; a caller
#: that wants to change something copies it first.
_PARSED: dict = {}


def _load(path: str):
    """The JSON at `path`, or `None` — a checkpoint that is missing or half-written.

    A capture child rewrites these whole on every tick, so a reader that happened to
    look mid-write sees a truncated file. That is a moment old, never an error worth
    showing: the next read has it.

    Parsed once per WRITE rather than once per read (:data:`_PARSED`).
    """
    try:
        stat = os.stat(path)
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        _PARSED.pop(path, None)
        return None
    held = _PARSED.get(path)
    if held is not None and held[0] == stamp:
        return held[1]
    try:
        with open(path, encoding="utf-8") as fh:
            parsed = json.load(fh)
    except (OSError, ValueError):
        # A half-written file is a moment old and not an error — and it is deliberately
        # NOT remembered, so the next reader tries again rather than being handed the
        # nothing this one saw.
        return None
    _PARSED[path] = (stamp, parsed)
    return parsed


def _age(path: str):
    """How many seconds ago `path` was last written, or `None` if it is not there."""
    try:
        return max(0.0, time.time() - os.path.getmtime(path))
    except OSError:
        return None


def _int(value):
    """`value` as a whole number, or `None` — never a raise on somebody else's field."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _text(value) -> str:
    return "" if value is None else str(value)


def _pick(record: dict, *names):
    """The first of `names` this record actually carries — see the module docstring."""
    for name in names:
        if name in record and record[name] is not None:
            return record[name]
    return None


def _object(kind: str, record: dict, *, name_from=(), detail: str = "") -> dict | None:
    """One record as a drawable object, or `None` when it has no place on the map.

    Short keys, because this list is the whole payload: four thousand objects with
    `"kind"`, `"server"`, `"level"` spelled out is a third more bytes over a phone's
    link for nothing a reader of the code needs — the shape is written down here.
    """
    x, y = _int(_pick(record, "x")), _int(_pick(record, "y"))
    if x is None or y is None:
        return None
    out = {"k": kind, "x": x, "y": y}
    server = _int(_pick(record, "server_id", "server", "owner_server"))
    if server is not None:
        out["s"] = server
    level = _int(_pick(record, "level"))
    if level is not None:
        out["l"] = level
    name = _text(_pick(record, *name_from)).strip() if name_from else ""
    if name:
        out["n"] = name
    if detail:
        out["d"] = detail
    seen = _int(_pick(record, "seen_at"))
    if seen is not None:
        out["t"] = seen
    return out


def _mine_detail(record: dict) -> str:
    """What a mine yields, and whether somebody is already on it — data, not a key.

    The resource is the game's own word for the family (`bread` / `iron` / `gold`) and
    the browser turns it into a colour; «occupied» is the one thing about a mine that
    decides whether it is worth walking to.
    """
    what = _text(_pick(record, "resource", "family")).strip()
    taken = record.get("free") is False or bool(_pick(record, "owner_uid"))
    return (what + ("*" if taken else "")).strip()


def _rows(value) -> list:
    """`value` as a list of dicts — a blob may be a list, a dict of lists, or junk."""
    if isinstance(value, list):
        return [r for r in value if isinstance(r, dict)]
    if isinstance(value, dict):
        return [r for r in value.values() if isinstance(r, dict)]
    return []


def _blob(store, name: str) -> list:
    if store is None:
        return []
    try:
        return _rows(store.blob_get(name))
    except Exception:      # noqa: BLE001 — a picture is never worth an exception
        return []


def _store(rt):
    """This profile's database, or `None` when it cannot be opened.

    A page of numbers must not be what a half-provisioned profile falls over on: a
    store that is missing means «мы ничего не знаем», which is a perfectly good thing
    for a comparison tool to say and a terrible thing for it to crash about.
    """
    try:
        return rt.store
    except Exception:      # noqa: BLE001
        return None


def coverage(rt, fresh=None) -> dict:
    """Where this account has looked — the checkpoint's grid folded into the kept one.

    **Nothing here asks the game anything.** The rectangle each map reply answered about
    already rides in the reply (`lastwar_proto.block_areas`); the world listener stopped
    throwing it away (#2018), and this is where it stops being forgotten at the end of a
    capture. That distinction is the whole reason the coverage layer is allowed to exist
    under «read once, then listen»: it is not a new reading, it is a field we had and
    discarded.

    Why it matters more than anything else on the picture: without it, empty ground on
    our map means either «there is nothing there» or «we never looked», and those two
    are the opposite answers to the question the page exists to ask.

    ``{"cell": 25, "sizes": {"935": 1000},
       "cells": [{"s": 935, "cx": 4, "cy": 7, "t": 1785776747, "v": 0}]}``

    `v` is the LOWEST view height the cell was ever heard at, because the client asks
    for less the higher it is (docs/research/map-sweep-zoom.md) — ground swept only from
    above has been looked at for bases and not for tasks.
    """
    store = _store(rt)
    held = None
    if store is not None:
        try:
            held = store.blob_get(COVERAGE_BLOB)
        except Exception:      # noqa: BLE001
            held = None
    if not isinstance(held, dict):
        held = {}
    cells = held.get("cells")
    merged: dict = dict(cells) if isinstance(cells, dict) else {}
    sizes: dict = dict(held.get("sizes") or {})
    cell = int(held.get("cell") or 0)

    if fresh is None:
        fresh = (_load(rt.profiles.world_json()) or {}).get("coverage")
    changed = False
    if isinstance(fresh, dict):
        incoming = int(fresh.get("cell") or 0)
        if incoming and cell and incoming != cell:
            # The grid was re-cut. Two grids cannot be merged honestly, and the newer
            # one is the one the picture will be drawn on, so the old cells go rather
            # than being stretched into a lie about where we have been.
            merged, changed = {}, True
        if incoming:
            cell = incoming
        for name, size in (fresh.get("sizes") or {}).items():
            if int(size or 0) > int(sizes.get(str(name)) or 0):
                sizes[str(name)] = int(size)
                changed = True
        for row in fresh.get("cells") or ():
            if not isinstance(row, dict):
                continue
            key = f"{_int(row.get('s')) or 0}:{_int(row.get('cx')) or 0}:{_int(row.get('cy')) or 0}"
            seen = _int(row.get("t")) or 0
            view = _int(row.get("v"))
            was = merged.get(key)
            if not isinstance(was, list) or len(was) != 2:
                merged[key] = [seen, view if view is not None else 0]
                changed = True
            elif seen > was[0] or (view is not None and view < was[1]):
                merged[key] = [max(seen, was[0]),
                               min(was[1], view) if view is not None else was[1]]
                changed = True

    cutoff = time.time() - COVERAGE_KEEP_SEC
    for key, row in list(merged.items()):
        if not isinstance(row, list) or len(row) != 2 or (row[0] or 0) < cutoff:
            merged.pop(key, None)
            changed = True
    if len(merged) > MAX_COVERAGE_CELLS:
        keep = sorted(merged.items(), key=lambda kv: -(kv[1][0] or 0))[:MAX_COVERAGE_CELLS]
        merged = dict(keep)
        changed = True

    if changed and store is not None:
        try:
            store.blob_set(COVERAGE_BLOB,
                           {"cell": cell, "sizes": sizes, "cells": merged})
        except Exception:      # noqa: BLE001 — a picture is never worth an exception
            pass
        # …and NOT through `blob_submit`, which the audit of #2659 proposed: the very
        # next poll reads this row back and folds the checkpoint into it again, so a
        # queued write that has not landed yet is coverage silently thrown away. The
        # write is rare in any case — a poll that finds nothing new leaves `changed`
        # false and writes nothing at all.

    rows = []
    for key, row in merged.items():
        parts = key.split(":")
        if len(parts) != 3:
            continue
        rows.append({"s": int(parts[0]), "cx": int(parts[1]), "cy": int(parts[2]),
                     "t": row[0], "v": row[1]})
    return {"cell": cell or 0, "sizes": sizes, "cells": rows}


def scene(rt, *, server=None, max_per_kind: int = MAX_PER_KIND) -> dict:
    """Everything this profile believes is on the map, ready to be painted.

    `server` narrows it to one warzone; `None` keeps every object and lets the front
    end choose, which is what the tab does — the person comparing two pictures is
    looking at one warzone at a time, and which one is a question about the client
    rather than about the panel.

    The answer::

        {"at": 1785776747.0,                  # when it was assembled
         "servers": [935, 1122],              # the warzones it holds, busiest first
         "server": 935,                       # the one it was narrowed to, or None
         "bounds": {"x0":…, "y0":…, "x1":…, "y1":…},
         "objects": [{"k": "mine", "x": 512, "y": 377, "s": 935,
                      "l": 5, "d": "iron", "t": 1785776700}],
         "counts": {"mine": 1204, …},         # what is IN the list
         "hidden": {"mine": 0, …},            # what the cap left out, per kind
         "ages":   {"world_map": 12.4, …}}    # how old each source is, seconds

    Called from an HTTP worker thread, so it touches no widget and no Tk variable — it
    reads files and this profile's database and nothing else.
    """
    profiles = rt.profiles
    objects: list = []
    counts: dict = {}
    hidden: dict = {}
    ages: dict = {}

    def take(kind: str, records, *, name_from=(), detail=None) -> None:
        """Turn `records` into objects of `kind` and put them in the scene.

        `detail` is a function of the record when a kind has something to say about
        itself beyond its level — only the mines do, so far.
        """
        made = []
        for record in records:
            obj = _object(kind, record, name_from=name_from,
                          detail=detail(record) if detail else "")
            if obj is not None:
                made.append(obj)
        _extend(objects, counts, hidden, kind, made, server, max_per_kind)

    # -- the map sweep's own checkpoint: bases, mines, lorries, trains ----------------
    world_path = profiles.world_json()
    ages["world_map"] = _age(world_path)
    world = _load(world_path) or {}
    if isinstance(world, dict):
        take("base", _rows(world.get("players")), name_from=("name",))
        take("mine", _rows(world.get("mines")), detail=_mine_detail)
        take("truck", _rows(world.get("trucks")), name_from=("owner_name", "name"))
        take("train", _rows(world.get("trains")),
             name_from=("alliance_abbr", "owner_name"))

    # -- the monsters, out of their own table (#1963) ---------------------------------
    store = _store(rt)
    monsters = []
    try:
        if store is not None:
            monsters = store.monsters_all(cutoff=time.time() - SIGHTING_TTL_SEC)
    except Exception:      # noqa: BLE001 — a profile whose database is not open yet
        monsters = []
    take("monster", monsters, name_from=("kind_name",))
    ages["monsters"] = _freshest(monsters)

    # -- the two lists the tabs keep, and the treasure checkpoint ---------------------
    from . import store as store_names

    stars = _blob(store, store_names.SECRET_TASKS_STATE)
    take("secret", stars)
    ages["secret_tasks"] = _freshest(stars)

    ghosts = _blob(store, store_names.GHOST_MAP_STATE)
    take("ghost", ghosts)
    ages["ghost_map"] = _freshest(ghosts)

    treasure_path = profiles.treasures_json()
    ages["treasures"] = _age(treasure_path)
    take("treasure", _rows(_load(treasure_path)))

    # WHERE WE LOOKED, beside WHAT WE FOUND. Folded in from the checkpoint we have just
    # read, so a page that is being looked at accumulates coverage without a clock.
    cover = coverage(rt, (world or {}).get("coverage") if isinstance(world, dict) else None)
    if server is not None:
        cover = {**cover,
                 "cells": [c for c in cover["cells"] if c["s"] == server],
                 "sizes": {k: v for k, v in cover["sizes"].items() if int(k) == server}}
    ages["coverage"] = _newest([c["t"] for c in cover["cells"]])

    servers: dict = {}
    for obj in objects:
        got = obj.get("s")
        if got is not None:
            servers[got] = servers.get(got, 0) + 1
    order = [s for s, _ in sorted(servers.items(), key=lambda kv: (-kv[1], kv[0]))]

    return {"at": time.time(), "server": server, "servers": order,
            "bounds": _bounds(objects, cover), "objects": objects,
            "coverage": cover,
            "counts": counts, "hidden": hidden, "ages": ages}


def _extend(objects, counts, hidden, kind, made, server, cap) -> None:
    """Add `made` to the scene under the cap — see :data:`MAX_PER_KIND`."""
    if server is not None:
        made = [o for o in made if o.get("s") in (None, server)]
    counts[kind] = counts.get(kind, 0) + min(len(made), cap)
    hidden[kind] = hidden.get(kind, 0) + max(0, len(made) - cap)
    objects.extend(made[:cap])


def _newest(stamps) -> float | None:
    """How old the newest of `stamps` is, or `None` when there are none."""
    newest = 0
    for stamp in stamps or ():
        value = _int(stamp) or 0
        if value > newest:
            newest = value
    if not newest:
        return None
    return max(0.0, time.time() - newest)


def _freshest(records) -> float | None:
    """How old the newest sighting in `records` is, or `None` when there is none.

    A blob and a table have no file to stat, and «когда это в последний раз видели» is
    the same question a checkpoint's mtime answers — so it is answered the same way,
    off the records' own `seen_at`.
    """
    newest = 0
    for record in records or ():
        seen = _int(record.get("seen_at")) if isinstance(record, dict) else None
        if seen and seen > newest:
            newest = seen
    if not newest:
        return None
    return max(0.0, time.time() - newest)


def _bounds(objects, cover=None) -> dict:
    """What the canvas opens fitted to — the objects AND the ground we have swept.

    Coverage counts because empty swept ground is a finding: a picture cropped to the
    dots would hide the very thing the layer was added to show.
    """
    xs = [o["x"] for o in objects]
    ys = [o["y"] for o in objects]
    cell = int((cover or {}).get("cell") or 0)
    for row in (cover or {}).get("cells") or ():
        xs.extend((row["cx"] * cell, row["cx"] * cell + cell))
        ys.extend((row["cy"] * cell, row["cy"] * cell + cell))
    if not xs:
        return {"x0": 0, "y0": 0, "x1": 0, "y1": 0}
    return {"x0": min(xs), "y0": min(ys), "x1": max(xs), "y1": max(ys)}


def overview(rt) -> dict:
    """How much of each kind is on disk, and how old it is — WITHOUT building a scene.

    What a card and a window row want: eight numbers. Both are re-read on the ordinary
    poll, and turning thirty thousand monster rows into thirty thousand dictionaries
    five times a minute — on the Tk thread, which is what «панель тормозит» was made of
    once (#1963) — to end up printing one integer is precisely the cost that measurement
    taught us not to pay. The canvas asks for :func:`scene` when somebody is looking.

    ``{"counts": {kind: n}, "ages": {source: seconds|None}}``
    """
    from . import store as store_names

    profiles = rt.profiles
    counts = dict.fromkeys(KINDS, 0)
    ages: dict = {}

    world_path = profiles.world_json()
    ages["world_map"] = _age(world_path)
    world = _load(world_path) or {}
    if isinstance(world, dict):
        for kind, key in (("base", "players"), ("mine", "mines"),
                          ("truck", "trucks"), ("train", "trains")):
            counts[kind] = len(_rows(world.get(key)))

    store = _store(rt)
    try:
        counts["monster"] = int(store.monsters_count()) if store is not None else 0
    except Exception:      # noqa: BLE001 — a database this profile has not opened yet
        counts["monster"] = 0

    stars = _blob(store, store_names.SECRET_TASKS_STATE)
    counts["secret"] = len(stars)
    ages["secret_tasks"] = _freshest(stars)

    ghosts = _blob(store, store_names.GHOST_MAP_STATE)
    counts["ghost"] = len(ghosts)
    ages["ghost_map"] = _freshest(ghosts)

    treasure_path = profiles.treasures_json()
    ages["treasures"] = _age(treasure_path)
    counts["treasure"] = len(_rows(_load(treasure_path)))

    # …and how much ground we have swept, which is a reading of its own: «мы туда не
    # смотрели» is half the answer the page exists to give.
    swept = 0
    try:
        held = store.blob_get(COVERAGE_BLOB) if store is not None else None
        cells = (held or {}).get("cells") if isinstance(held, dict) else None
        swept = len(cells) if isinstance(cells, dict) else 0
        ages["coverage"] = _newest([row[0] for row in (cells or {}).values()
                                    if isinstance(row, list) and row])
    except Exception:      # noqa: BLE001 — a database this profile has not opened yet
        ages["coverage"] = None

    return {"counts": counts, "ages": ages, "swept": swept}


def summary(scene_data: dict) -> list:
    """The scene's counts as `(kind, shown, hidden)`, busiest first — for the cards."""
    counts = scene_data.get("counts") or {}
    hidden = scene_data.get("hidden") or {}
    rows = [(kind, int(counts.get(kind) or 0), int(hidden.get(kind) or 0))
            for kind in KINDS]
    return sorted(rows, key=lambda row: (-row[1], row[0]))
