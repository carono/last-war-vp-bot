#!/usr/bin/env python3
r"""One HTML page of everybody's rally squads, out of the rally archives — for reading.

    python tools/rally_report.py
    python tools/rally_report.py --input profiles/default/rally_log.jsonl \
                                --out cache/reports/rally_report.html

The rally monitor (`tools/rally_monitor.py`) archives one line per participant of every
`push.alliance.march.create/refresh` it sees, into `profiles/<profile>/rally_log.jsonl`.
This folds every profile's archive into one page: the players, each player's squads, the
last reading of each squad, and how each squad's power moved over the recorded window.

Players are grouped by alliance. The tag comes off the archive when it is there (the last
reading wins, so somebody who changed alliance mid-window counts under the one they are in
now), off the profiles' leaderboard stores when it is not, and off who rides with whom
when neither knows — a rally is an alliance affair, so its participants are one alliance.
A group nobody can name keeps its players and says so. See
`docs/research/rally-squad-identity.md`.

Avatars are files, not data inside the page — `cache/avatars/`, linked relatively, nothing
fetched. That folder is SHARED by every profile (#1306): the same player has the same face
whichever account met them, so one copy serves every page ever generated.

The picture a player uploaded comes out of the CLIENT'S PHOTO CACHE
(`tools/lib/player_photos.py`), which holds exactly the people this client has met, and is
copied as `<uid>.jpg` shrunk to 128 px. A player who never uploaded one wears a built-in
avatar instead: that is a `headSkinId`, and its sprite comes out of the bundles
(`tools/extract_hero_icons.py --sets head,head_s6 --out results/head_icons`) as
`<headSkinId>.png`, one file however many players wear it. Whoever neither source can
place gets a coloured initial, and the generator prints how many. See
`docs/research/player-avatars.md`.

**The page is not about rallies.** A rally is only the moment somebody's squad became
visible and its power was written down — a point on a time axis, and nothing else. Who
marched with whom, where they went and how many rallies anybody joined is not shown.
Accordingly a rally counts as ONE measurement however many lines it left: an archived
rally is re-broadcast on every refresh, and across every rally in every archive here the
`(power, curHp)` pair was identical on all the lines of a rally in 4 446 of 4 446 cases.

One self-contained file — no scripts fetched, no fonts fetched, no network at all — so
it opens on a phone that is nowhere near this machine. The charts are inline SVG built
in the page; there is no charting library.

**What identifies a squad between rallies: `armyInfo.f4`.**

That field is the squad slot the march was sent from — 1..4 on the sampled data, present
on 100% of 44 817 archived lines across four profiles. It is the only stable key there
is, and it was checked rather than assumed:

* two different slots of the same player never once shared a hero composition, so the
  slot is not being reused for unrelated armies;
* it survives a hero being swapped inside a squad, which a composition key does not —
  one player's slot 2 changed one of its five heroes mid-window and stayed slot 2;
* the formation preset (`armyInfo.f2.f13`) does NOT identify a squad: 253 players
  averaged 1.00 distinct formation values each, i.e. it is one setting per player, the
  same on every squad they own;
* the march uuid (`armyInfo.f1.f3`) is allocated per march, so keying on it turns every
  rally into a brand-new "squad" — which is what the previous report did.

**The charts are per DAY, one point each: the day's best reading.** A squad goes out
several times a day and the interesting figure is its ceiling, not whichever outing
happened to be last. The maximum is taken inside the chosen mode, so a day's best
full-strength march and a day's best per-soldier figure never end up on the same curve.
A day with no reading gets NO point — the line breaks and the jump is drawn as a thin
dash, because «not seen that day» and «power fell» must not look alike.

**Power in a rally is what marched, not what the squad is worth.** A squad that lost
soldiers marches at a fraction of its power — 27 M at 1 725 hp where the same slot sends
56 M at 3 123 hp. So the page offers two readings of the same series: `мощь` as archived,
and `на бойца` (power ÷ curHp), which takes the wound out and shows the underlying
growth. Neither is derived from the other by the page's author's guess — both are printed
from the archived pair.

**The output is other people's accounts and never belongs in the repository.** Every row
carries a nickname and a uid, most of them belonging to players who never heard of this
tool. The default destination is inside `profiles/`, which is git-ignored; `--out`
somewhere tracked is refused.
"""
from __future__ import annotations

import argparse
import collections
import glob
import html
import json
import os
import shutil
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

import game_paths                                   # noqa: E402  (needs the path above)

#: Written into a directory that is not git-ignored, this file is two hundred players'
#: nicknames and uids in a tracked tree. The check is deliberately crude and deliberately
#: refuses rather than warns.
#:
#: `cache` is where the page and the faces live now (#1306) and is git-ignored with the
#: rest; `profiles` stays allowed because somebody may still point `--out` at a profile
#: they are looking at, and it is ignored too.
_ALLOWED_ROOTS = ("cache", "profiles", "results", "screenshots")

#: The drone / air-support slot — a squad row, but not a hero.
DRONE_ID = 1000000

#: Grade at which the exclusive weapon ("专武") starts carrying its bonus levels.
ZW_GRADE = 30


# --------------------------------------------------------------------------- reading


def _as_list(value):
    """A protobuf repeated field collapses to a bare dict when it occurs once."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _squad_rows(army):
    """The per-slot rows of a decoded ``armyInfo`` — heroes and the drone."""
    if not isinstance(army, dict):
        return []
    body = army.get("f2")
    if not isinstance(body, dict):
        return []
    return [row for row in _as_list(body.get("f2")) if isinstance(row, dict)]


def _slot(army):
    """The squad slot the march was sent from — ``armyInfo.f4``. See the module doc."""
    if not isinstance(army, dict):
        return 0
    value = army.get("f4")
    return value if isinstance(value, int) else 0


def _detail(army) -> dict:
    """Heroes, drone and formation of one archived march, in display shape."""
    heroes, drone = [], None
    for row in _squad_rows(army):
        hero_id = row.get("f1")
        grade = row.get("f15")
        if hero_id == DRONE_ID:
            payload = row.get("f16") if isinstance(row.get("f16"), dict) else {}
            drone = {"grade": payload.get("f2") if payload else row.get("f8")}
            continue
        bonus = [
            {"stage": b.get("f1"), "level": b.get("f2")}
            for b in _as_list(row.get("f17")) if isinstance(b, dict)
        ]
        bonus.sort(key=lambda b: b.get("stage") or 0)
        heroes.append({
            "id": hero_id,
            "slot": row.get("f4"),
            "level": row.get("f2"),
            "tier": row.get("f3"),
            "grade": grade,
            "zw": bonus,
        })
    heroes.sort(key=lambda h: h.get("slot") or 0)
    body = army.get("f2") if isinstance(army, dict) else None
    formation = body.get("f13") if isinstance(body, dict) else None
    return {"heroes": heroes, "drone": drone, "formation": formation}


def live_head_skins() -> dict:
    """``uid -> headSkinId`` for the reader's own alliance, asked of the live client.

    The archive only started carrying `headSkinId` in #1305, so everything captured
    before it has no avatar at all. The running game still knows: its alliance roster
    (`DataCenter.AllianceMemberDataManager.allianceMembers`) holds a `headSkinId` per
    member, and that covers the one alliance the reader is in. Empty when there is no
    client — no client is an answer, not an error.
    """
    try:
        from lua_client import get_evaluator
        ev = get_evaluator()
        lua = (
            'local out = {}\n'
            'local m = DataCenter.AllianceMemberDataManager\n'
            'for _, v in pairs((m and m.allianceMembers) or {}) do\n'
            '  if v.uid and v.headSkinId then\n'
            '    out[#out+1] = tostring(v.uid) .. ":" .. tostring(v.headSkinId)\n'
            '  end\n'
            'end\n'
            'CS.UnityEngine.Debug.LogError("RRHEADS " .. table.concat(out, ","))')
        for line in ev.run(lua, marker="RRHEADS", settle=1.5):
            if "RRHEADS " not in line:
                continue
            out = {}
            for pair in line.split("RRHEADS ", 1)[1].strip().split(","):
                uid, _, head = pair.partition(":")
                if uid.isdigit() and head.strip().isdigit():
                    out[uid] = int(head)
            return out
    except (Exception, SystemExit):              # noqa: BLE001 — no client is an answer
        # SystemExit, and it is not paranoia: `il2cpp_probe` RAISES ONE — «snapshot
        # failed err=5» — when the client it was told to attach to has gone, and
        # `SystemExit` does not descend from `Exception`, so it walked straight past
        # this guard and took the whole report with it. The docstring above said «no
        # client is an answer, not an error» while the code disagreed, and it only
        # showed up the first time the report was run against a client that had been
        # kicked (#1306).
        pass
    return {}


#: Avatars are drawn 34 px wide, so a 55 KiB photo out of the cache is fifty times more
#: picture than the page can show. Shrunk to this, a folder of two hundred is under a
#: megabyte and still sharp on a 3× phone screen.
AVATAR_PX = 128


def _shrink(source: str, destination: str) -> None:
    """Copy a picture down to `AVATAR_PX`, or copy it whole if PIL is not installed."""
    try:
        from PIL import Image
        with Image.open(source) as img:
            img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
            img.thumbnail((AVATAR_PX, AVATAR_PX), Image.LANCZOS)
            img.save(destination, "JPEG", quality=82, optimize=True)
        return
    except Exception:                            # noqa: BLE001 — see below
        pass
    # No PIL, or a cache entry that is not a picture the library can read — the file is
    # still what the client downloaded, so hand it over whole rather than dropping the
    # player's face over a resize.
    shutil.copyfile(source, destination)


def copy_avatars(players, out_path: str, root: str = None) -> tuple:
    """Put the players' avatars in the SHARED cache; return the hrefs into it.

    The pictures travel WITH the page as files rather than inside it: one file per
    picture however many rows show it, and relative links from the page. Nothing is
    fetched from anywhere.

    SHARED BY EVERY PROFILE, not kept per report or per account (#1306). The same
    player's face is the same file whichever account happened to meet them first, so it
    lives in `game_paths.avatar_cache()` — `cache/avatars/` — and every page ever
    generated links into the one folder. It used to be `<report>_avatars/` beside the
    page, which put a directory into `profiles/` that the panel then read as an account.

    Two sources, in that order:

    1. **The client's photo cache** — the picture the player uploaded for themselves,
       downloaded by the client the first time it met them
       (`tools/lib/player_photos.py`). One file per uid, named `<uid>.jpg`.
    2. **The extracted head sprites** — the built-in avatar a player picked instead of
       uploading one, named by its `headSkinId` so forty players wearing it cost one
       file (`tools/lib/head_icons_map.py`).

    Whatever neither source can place gets a coloured initial in the page.

    Returns ``({key: "folder/<file>"}, stats)`` — the key is the uid for a cached photo
    and the `headSkinId` for a sprite, which is how `avatar()` decides in the page.
    """
    stats = {"photos": 0, "sprites": 0, "ids": 0, "copied": 0, "unmapped": [],
             "bytes": 0, "folder": "", "cache": ""}
    directory = game_paths.avatar_cache()
    # The page links RELATIVELY, so it keeps working when the whole tree is copied to a
    # phone — `../avatars/<uid>.jpg` from `cache/reports/`, and whatever the distance is
    # when somebody passes `--out` of their own.
    folder = os.path.relpath(directory,
                             os.path.dirname(os.path.abspath(out_path))).replace("\\", "/")
    stats["folder"] = directory
    hrefs = {}

    try:
        import player_photos
        stats["cache"] = root or player_photos.game_paths.local_images()
    except Exception:                            # noqa: BLE001 — no cache is an answer
        player_photos = None

    if player_photos is not None:
        for player in players:
            found = player_photos.newest_for(player["uid"], root=root)
            if not found:
                continue
            os.makedirs(directory, exist_ok=True)
            destination = os.path.join(directory, f"{player['uid']}.jpg")
            _shrink(found[0], destination)
            hrefs[player["uid"]] = f"{folder}/{player['uid']}.jpg"
            stats["photos"] += 1
            stats["bytes"] += os.path.getsize(destination)

    # Only the players the cache could not answer for need a built-in sprite.
    wanted = sorted({p["head"] for p in players
                     if p["head"] is not None and p["uid"] not in hrefs})
    stats["ids"] = len(wanted)
    try:
        import head_icons_map as head_map
    except Exception:                            # noqa: BLE001 — no map is an answer
        head_map = None
    for head_id in wanted:
        source = head_map and head_map.icon_path(head_id)
        if not source:
            stats["unmapped"].append(head_id)
            continue
        os.makedirs(directory, exist_ok=True)
        destination = os.path.join(directory, f"{head_id}.png")
        shutil.copyfile(source, destination)
        hrefs[str(head_id)] = f"{folder}/{head_id}.png"
        stats["sprites"] += 1
        stats["bytes"] += os.path.getsize(destination)

    stats["copied"] = stats["photos"] + stats["sprites"]
    return hrefs, stats


def _hero_names() -> dict:
    """``heroId -> display name`` for the ids anybody has confirmed by eye.

    Most ids resolve to nothing — the table lives in the game's encrypted config
    (`tools/lib/hero_icons_map.py`), so the page falls back to `#<id>`.
    """
    try:
        import hero_icons_map as hero_map
    except Exception:                            # noqa: BLE001 — a missing table is fine
        return {}
    return {hero_id: name.replace("_", " ")
            for hero_id, name in getattr(hero_map, "CONFIRMED", {}).items()}


def load(paths) -> dict:
    """Fold every archive into ``{players: [...], sources: [...], window: [from, to]}``.

    The same rally reaches every profile that was watching, so the lines are deduplicated
    on ``(teamUuid, ownerUid, second, power, curHp)`` before anything is counted — four
    profiles of the same alliance carry 44 817 lines and 13 206 distinct readings.
    """
    seen: set = set()
    players: dict = {}
    sources: list = []
    rally_members: dict = {}
    lo = hi = 0.0

    for path in paths:
        kept = 0
        try:
            handle = open(path, encoding="utf-8")
        except OSError:
            continue
        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                uid = str(row.get("ownerUid") or "")
                stamp = float(row.get("timestamp") or 0)
                power = int(row.get("power") or 0)
                hp = int(row.get("curHp") or 0)
                team = str(row.get("teamUuid") or "0")
                key = (team, uid, round(stamp), power, hp)
                if not uid or key in seen:
                    continue
                seen.add(key)
                kept += 1
                lo = stamp if not lo else min(lo, stamp)
                hi = max(hi, stamp)

                player = players.get(uid)
                if player is None:
                    player = players[uid] = {"uid": uid, "name": "", "aliases": set(),
                                             "squads": {}, "alliance": None, "head": None}
                name = row.get("ownerName") or ""
                if name:
                    player["aliases"].add(name)
                    # The archive is read oldest-first per file but files interleave, so
                    # the displayed name is the one from the latest line, not the last
                    # line read.
                    if stamp >= player.get("_named", 0):
                        player["name"], player["_named"] = name, stamp
                # LAST KNOWN wins for both: a player who changed alliance during the
                # window belongs to the one they are in now, not the one they left.
                if row.get("allianceAbbr") and stamp >= player.get("_allied", 0):
                    player["alliance"] = {"tag": row.get("allianceAbbr"),
                                          "name": row.get("allianceName") or "",
                                          "id": str(row.get("allianceId") or "")}
                    player["_allied"] = stamp
                if row.get("headSkinId") is not None and stamp >= player.get("_headed", 0):
                    player["head"], player["_headed"] = row["headSkinId"], stamp
                if team != "0":
                    rally_members.setdefault(team, set()).add(uid)

                army = row.get("armyInfoRaw")
                slot = _slot(army)
                squad = player["squads"].get(slot)
                if squad is None:
                    squad = player["squads"][slot] = {
                        "slot": slot, "moments": {}, "_best": (-1, 0.0), "detail": None,
                    }
                # ONE reading per moment. A rally is re-broadcast on every refresh and
                # the archive keeps a line each time; measured over every rally in every
                # archive, `(power, curHp)` was identical across all the lines of a rally
                # in 4 446 of 4 446 cases. So the rally is the moment the squad was seen,
                # not five measurements — and the moment is stamped when it was FIRST
                # seen. A create push arrives before the team id exists (`teamUuid` is
                # "0"), so those fall back to a ten-minute bucket.
                moment = team if team != "0" else "t%d" % (stamp // 600)
                held = squad["moments"].get(moment)
                if held is None or (hp, power) > (held[2], held[1]):
                    squad["moments"][moment] = [min(stamp, held[0]) if held else stamp,
                                                power, hp]
                elif stamp < held[0]:
                    held[0] = stamp
                # The composition to display is the FULLEST reading, latest among equals.
                # A squad that marched wiped is archived with the one hero that survived,
                # and the newest line is not the one that says what the squad is.
                detail = _detail(army)
                mark = (len(detail["heroes"]), stamp)
                if mark > squad["_best"]:
                    squad["_best"], squad["detail"] = mark, detail
        sources.append({"path": path, "kept": kept})

    names = _hero_names()
    out = []
    for player in players.values():
        for key in ("_named", "_allied", "_headed"):
            player.pop(key, None)
        squads = []
        for squad in player["squads"].values():
            moments = sorted(squad["moments"].values(), key=lambda m: m[0])
            for moment in moments:
                moment[0] = round(moment[0])
            # EVERY moment travels, and the run of identical readings in the middle is
            # NOT thinned out. It used to be — the shape of a line through them is the
            # same either way — but the page buckets the series BY DAY now, and a day
            # whose only reading was dropped as "interior" comes out as a day with no
            # reading, which the chart draws as a break meaning «not seen». That is the
            # one thing the whole page is trying not to say by accident, and it would
            # have been said most often about the squads that changed least.
            series = moments
            detail = squad["detail"] or {"heroes": [], "drone": None, "formation": None}
            for hero in detail["heroes"]:
                hero["name"] = names.get(hero["id"], "")
            full = max((hp for _, _, hp in moments), default=0)
            squads.append({
                "slot": squad["slot"],
                "moments": len(moments),
                "fullMoments": sum(1 for _, _, hp in moments if hp >= full * 0.95),
                "first": series[0][0] if series else 0,
                "last": series[-1][0] if series else 0,
                "power": series[-1][1] if series else 0,
                "hp": series[-1][2] if series else 0,
                "peak": max((p for _, p, _ in series), default=0),
                "fullHp": full,
                "formation": detail["formation"],
                "heroes": detail["heroes"],
                "drone": detail["drone"],
                "series": series,
            })
        squads.sort(key=lambda s: s["slot"])
        last = max((s["last"] for s in squads), default=0)
        out.append({
            "uid": player["uid"],
            "name": player["name"] or player["uid"],
            "aliases": sorted(a for a in player["aliases"] if a != player["name"]),
            "moments": sum(s["moments"] for s in squads),
            "last": last,
            "power": sum(s["power"] for s in squads),
            "peak": sum(s["peak"] for s in squads),
            "alliance": player["alliance"],
            "head": player["head"],
            "squads": squads,
        })
    out.sort(key=lambda p: -p["peak"])
    return {"players": out, "sources": sources, "window": [round(lo), round(hi)],
            "rallies": rally_members}


# ----------------------------------------------------------------------- the alliance


def _components(rally_members: dict, uids) -> dict:
    """``uid -> group id``, where a group is everybody who ever rode together.

    A rally is an alliance affair, so co-participation is alliance membership. Checked
    on this machine's archives: 253 players fall into 7 groups, and the 100 whose tag is
    independently known from the leaderboard store landed in exactly one of them, with no
    group holding two different known tags. That is what makes it safe to spread one
    member's tag over a whole group when the archive predates #1305 and carries none.
    """
    parent = {uid: uid for uid in uids}

    def find(uid):
        while parent[uid] != uid:
            parent[uid] = parent[parent[uid]]
            uid = parent[uid]
        return uid

    for members in rally_members.values():
        members = [uid for uid in members if uid in parent]
        for other in members[1:]:
            first, second = find(members[0]), find(other)
            if first != second:
                parent[first] = second
    return {uid: find(uid) for uid in parent}


def _leaderboard_alliances(paths) -> dict:
    """``uid -> {tag, name, id}`` out of the profiles' leaderboard stores, latest wins.

    A fallback for archives written before #1305, which carry no alliance at all. It only
    ever knows the reader's OWN alliance — a ranking lists your side — so it names one
    group and leaves the rest to `_components`.
    """
    out: dict = {}
    stamps: dict = {}
    for path in paths:
        store = os.path.join(os.path.dirname(path), "leaderboard_history.db")
        if not os.path.exists(store):
            continue
        try:
            conn = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
            rows = conn.execute(
                "SELECT uid, alliance, alliance_id, ts FROM entries "
                "WHERE alliance IS NOT NULL AND alliance != ''").fetchall()
            conn.close()
        except sqlite3.Error:
            continue
        for uid, tag, alliance_id, stamp in rows:
            uid = str(uid)
            if stamp >= stamps.get(uid, -1):
                stamps[uid] = stamp
                out[uid] = {"tag": tag, "name": "", "id": str(alliance_id or "")}
    return out


def group_by_alliance(data: dict, paths) -> list:
    """Fold the players into alliances, saying for each how the tag was arrived at.

    Order of trust: the tag the archive carries (last known reading wins, so a player who
    changed alliance mid-window is counted under the one they are in now), then the
    profiles' leaderboard stores, then the tag of anybody who rode in the same rallies.
    A group nobody can name stays a group and keeps its players — never a bin.
    """
    players = {p["uid"]: p for p in data["players"]}
    known = {uid: p["alliance"] for uid, p in players.items() if p["alliance"]}
    for uid, alliance in _leaderboard_alliances(paths).items():
        if uid in players and uid not in known:
            known[uid] = alliance
            players[uid]["source"] = "leaderboard"

    groups = _components(data.get("rallies") or {}, players)
    # One group at a time: if anybody in it is named, the whole group takes that name.
    by_group: dict = {}
    for uid, player in players.items():
        by_group.setdefault(groups.get(uid, uid), []).append(player)

    out = []
    for index, (group, members) in enumerate(sorted(
            by_group.items(), key=lambda kv: -sum(p["peak"] for p in kv[1])), 1):
        tags = [known[p["uid"]] for p in members if p["uid"] in known]
        counted = collections.Counter(t["tag"] for t in tags)
        tag = counted.most_common(1)[0][0] if counted else ""
        named = next((t for t in tags if t["tag"] == tag), None)
        direct = sum(1 for p in members if p["alliance"])
        members.sort(key=lambda p: -p["peak"])
        out.append({
            "tag": tag,
            "name": (named or {}).get("name", ""),
            "id": (named or {}).get("id", ""),
            # How the tag got here, in the reader's terms: on every player's own lines,
            # on some of them, or on none at all and only on the group's shape.
            "how": ("archive" if direct == len(members)
                    else "partial" if direct else "inferred" if tag else "unknown"),
            "known": len(tags),
            "index": index,
            "players": members,
            "power": sum(p["peak"] for p in members),
            "last": max((p["last"] for p in members), default=0),
        })
    out.sort(key=lambda g: (-g["power"],))
    return out


# --------------------------------------------------------------------------- drawing


_CSS = """
:root{--bg:#12141a;--card:#1b1e27;--line:#2b303d;--ink:#e8eaf0;--dim:#98a0b3;
--accent:#4da3ff;--warn:#ff8a5c;--good:#5fd68a;--gold:#ffd23f;
--s1:#4da3ff;--s2:#5fd68a;--s3:#ffd23f;--s4:#ff8a5c;--s0:#b07cff}
*{box-sizing:border-box}
body{margin:0;padding:16px;background:var(--bg);color:var(--ink);
font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
-webkit-text-size-adjust:100%}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--dim);font-size:13px;margin-bottom:14px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
input[type=search]{flex:1 1 200px;min-width:0;background:var(--card);color:var(--ink);
border:1px solid var(--line);border-radius:10px;padding:9px 12px;font-size:15px}
.seg{display:flex;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.seg button{background:var(--card);color:var(--dim);border:0;padding:9px 12px;
font-size:14px;cursor:pointer}
.seg button.on{background:var(--accent);color:#0d1017;font-weight:600}
.al{background:var(--card);border:1px solid var(--line);border-radius:12px;
margin-bottom:10px;overflow:hidden}
.al>.hd{display:flex;align-items:center;gap:10px;padding:13px 14px;cursor:pointer}
.al>.hd:active{background:#222631}
.al.open>.hd{border-bottom:1px solid var(--line)}
.tag{font-size:17px;font-weight:700;color:var(--accent);white-space:nowrap}
.tag.none{color:var(--dim)}
.albd{padding:2px 10px 8px}
.how{font-size:11px;color:var(--dim);padding:6px 4px 2px}
.pl{border-top:1px solid var(--line)}
.pl:first-child{border-top:0}
.pl>.hd{display:flex;align-items:center;gap:9px;padding:9px 4px;cursor:pointer}
.pl>.hd:active{background:#222631}
.ava{width:34px;height:34px;border-radius:9px;flex:0 0 auto;object-fit:cover;
background:#222631}
.ava.ph{display:flex;align-items:center;justify-content:center;font-size:13px;
font-weight:700;color:#0d1017}
.nm{font-weight:600;flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;
white-space:nowrap}
.who{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:1px;
overflow:hidden}
.who .nm{display:block}
.who .meta{overflow:hidden;text-overflow:ellipsis}
.pw{font-variant-numeric:tabular-nums;font-weight:700;white-space:nowrap;
margin-left:auto}
.pw .up,.pw .dn{font-weight:600;font-size:12px;margin-left:4px}
.meta{color:var(--dim);font-size:12px;white-space:nowrap}
.bd{padding:0 4px 12px}
.sq{border-top:1px solid var(--line)}
.sq>.hd{display:flex;align-items:baseline;gap:8px;padding:10px 2px;cursor:pointer}
.sq>.hd:active{background:#222631}
.chip{display:inline-block;padding:1px 7px;border-radius:999px;font-size:12px;
font-weight:700;color:#0d1017}
.c1{background:var(--s1)}.c2{background:var(--s2)}.c3{background:var(--s3)}
.c4{background:var(--s4)}.c0{background:var(--s0)}
.sqbd{padding:2px 0 12px}
.heroes{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.hero{background:#222631;border:1px solid var(--line);border-radius:8px;padding:5px 8px;
font-size:12px;line-height:1.3}
.hero b{display:block;font-size:13px;font-weight:600}
.hero .g{color:var(--dim)}
.hero .zw{color:var(--gold);margin-left:6px}
.kv{display:flex;flex-wrap:wrap;gap:4px 14px;color:var(--dim);font-size:12px;
margin-top:4px}
.kv b{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
svg{display:block;width:100%;height:auto;touch-action:pan-y}
.legend{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--dim);
margin-top:6px}
.legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}
.empty{color:var(--dim);font-size:13px;padding:10px 0}
.up{color:var(--good)}.dn{color:var(--warn)}
@media(max-width:520px){body{padding:10px}.pl>.hd{padding:11px 11px}.bd{padding:0 11px 10px}}
"""

_JS = r"""
var MODE = 'full';
var COL = ['#b07cff','#4da3ff','#5fd68a','#ffd23f','#ff8a5c'];

function num(v){
  v = Math.round(v || 0);
  return String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}
function big(v){
  if (v >= 1e6) return (v / 1e6).toFixed(v >= 1e7 ? 1 : 2).replace('.', ',') + ' M';
  if (v >= 1e4) return Math.round(v / 1e3) + ' k';
  return num(v);
}
function when(sec){
  var d = new Date(sec * 1000), p = function(n){ return (n < 10 ? '0' : '') + n; };
  return p(d.getDate()) + '.' + p(d.getMonth() + 1) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
}
function day(sec){
  var d = new Date(sec * 1000), p = function(n){ return (n < 10 ? '0' : '') + n; };
  return p(d.getDate()) + '.' + p(d.getMonth() + 1);
}
function value(pt){
  return MODE === 'unit' ? (pt[2] > 0 ? pt[1] / pt[2] : 0) : pt[1];
}
/* What a squad's power series is worth reading.
   `full` — only the marches that went out at (near) full strength, which is the only
   series where a rise or a fall is the squad changing rather than its wounds;
   `all`  — every archived reading, wounds and all;
   `unit` — power per soldier, which takes the wound out of every reading. */
function fullPoints(s){
  var floor = s.fullHp * 0.95;
  return s.series.filter(function(p){ return p[2] >= floor; });
}

var DAY = 86400;

/* One point per DAY: the day's best reading. A squad goes out several times a day and
   the interesting figure is the ceiling, not whichever outing happened to be last.
   The maximum is taken INSIDE the chosen mode — a day's best full-strength march and a
   day's best per-soldier figure are different readings, and mixing them draws a curve
   that is neither. A day with nothing in it produces NO point: that is a hole, and the
   chart breaks the line across it rather than inventing a value. */
function byDay(pts){
  var best = {};
  pts.forEach(function(p){
    var d = new Date(p[0] * 1000);
    d.setHours(0, 0, 0, 0);
    var key = Math.round(d.getTime() / 1000);
    var held = best[key];
    if (!held || value(p) > value(held)) best[key] = [key, p[1], p[2], p[0]];
  });
  return Object.keys(best).map(function(k){ return best[k]; })
              .sort(function(a, b){ return a[0] - b[0]; });
}

function points(s){
  return byDay(MODE === 'full' ? fullPoints(s) : s.series);
}
function esc(s){
  return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];
  });
}

/* An inline SVG line chart. series = [{name, color, pts:[[t, power, hp], ...]}] */
function chart(series){
  var W = 640, H = 240, L = 58, R = 12, T = 14, B = 26;
  var pts = [];
  series.forEach(function(s){ s.pts.forEach(function(p){ pts.push(p); }); });
  if (!pts.length) return '<div class="empty">нет данных</div>';
  var xs = pts.map(function(p){ return p[0]; }), ys = pts.map(value);
  var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
  var y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
  if (x1 === x0) { x0 -= DAY / 2; x1 += DAY / 2; }
  if (y1 === y0) { y0 = y0 * 0.98 - 1; y1 = y1 * 1.02 + 1; }
  else { var pad = (y1 - y0) * 0.12; y0 -= pad; y1 += pad; }
  if (y0 < 0 && Math.min.apply(null, ys) >= 0) y0 = 0;   /* no negative power */
  var X = function(t){ return L + (t - x0) / (x1 - x0) * (W - L - R); };
  var Y = function(v){ return T + (1 - (v - y0) / (y1 - y0)) * (H - T - B); };

  var out = ['<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" font-family="inherit">'];
  for (var i = 0; i <= 3; i++) {
    var v = y0 + (y1 - y0) * i / 3, y = Y(v);
    out.push('<line x1="' + L + '" y1="' + y.toFixed(1) + '" x2="' + (W - R) +
             '" y2="' + y.toFixed(1) + '" stroke="#2b303d" stroke-width="1"/>');
    out.push('<text x="' + (L - 6) + '" y="' + (y + 4).toFixed(1) + '" fill="#98a0b3" ' +
             'font-size="12" text-anchor="end">' + big(v) + '</text>');
  }
  /* The axis is days now, so the ticks are days — one per day while they fit. */
  var days = Math.round((x1 - x0) / DAY) + 1;
  var ticks = Math.min(Math.max(days, 2), 5) - 1;
  for (var k = 0; k <= ticks; k++) {
    var t = x0 + (x1 - x0) * k / ticks, tx = X(t);
    var anchor = k === 0 ? 'start' : (k === ticks ? 'end' : 'middle');
    out.push('<text x="' + tx.toFixed(1) + '" y="' + (H - 6) + '" fill="#98a0b3" ' +
             'font-size="12" text-anchor="' + anchor + '">' + day(t) + '</text>');
  }
  var gaps = 0;
  series.forEach(function(s){
    if (!s.pts.length) return;
    /* A missing day breaks the line. The run either side is drawn solid; the jump over
       the hole is a thin dashed hint, so «not seen» never looks like a reading. */
    var run = [];
    var flush = function(){
      if (run.length > 1) {
        out.push('<path d="' + run.map(function(p, i){
          return (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(value(p)).toFixed(1);
        }).join(' ') + '" fill="none" stroke="' + s.color + '" stroke-width="2" ' +
        'stroke-linejoin="round" stroke-linecap="round"/>');
      }
      run = [];
    };
    s.pts.forEach(function(p, i){
      if (i && p[0] - s.pts[i - 1][0] > DAY * 1.5) {
        gaps++;
        var a = s.pts[i - 1];
        flush();
        out.push('<path d="M' + X(a[0]).toFixed(1) + ' ' + Y(value(a)).toFixed(1) +
                 ' L' + X(p[0]).toFixed(1) + ' ' + Y(value(p)).toFixed(1) +
                 '" fill="none" stroke="' + s.color + '" stroke-width="1" ' +
                 'stroke-dasharray="3 4" opacity=".45"/>');
      }
      run.push(p);
    });
    flush();
    s.pts.forEach(function(p){
      out.push('<circle cx="' + X(p[0]).toFixed(1) + '" cy="' + Y(value(p)).toFixed(1) +
               '" r="2.8" fill="' + s.color + '"><title>' + esc(s.name) + ' · ' +
               day(p[0]) + ' · максимум ' + num(p[1]) + ' при ' + num(p[2]) +
               ' бойцах (замер ' + when(p[3] || p[0]) + ')</title></circle>');
    });
  });
  out.push('</svg>');
  if (gaps) {
    out.push('<div class="empty">пунктир — дни, в которые отряд не выходил: ' +
             'это пропуск, а не падение мощи</div>');
  }
  return out.join('');
}

function legend(series){
  return '<div class="legend">' + series.map(function(s){
    return '<span><i style="background:' + s.color + '"></i>' + esc(s.name) + '</span>';
  }).join('') + '</div>';
}

function squadSeries(s){
  return {name: 'Отряд ' + (s.slot || '?'), color: COL[s.slot] || COL[0], pts: points(s)};
}

/* The squad's headline number: what it marched at, at full strength, most recently.
   The last archived reading is not it — a squad that went out wiped is archived at a
   twentieth of its power, and calling that "the squad" is reading a casualty list. */
function headline(s){
  var pick = points(s);
  if (!pick.length) pick = byDay(s.series);
  var last = pick[pick.length - 1];
  return last ? value(last) : 0;
}

function delta(s){
  var pts = points(s);
  if (pts.length < 2) return '';
  var a = value(pts[0]), b = value(pts[pts.length - 1]);
  if (!a) return '';
  var pc = (b - a) / a * 100;
  var cls = pc >= 0 ? 'up' : 'dn';
  return '<span class="' + cls + '">' + (pc >= 0 ? '+' : '') +
         pc.toFixed(1).replace('.', ',') + ' %</span>';
}

function heroCard(h){
  var name = h.name ? esc(h.name) : '#' + h.id;
  var zw = (h.zw || []).map(function(b){ return b.stage + ':' + b.level; }).join(' ');
  return '<div class="hero"><b>' + name + '</b>' +
         '<span class="g">★' + (h.tier == null ? '?' : h.tier) +
         ' · ур. ' + (h.level == null ? '?' : h.level) +
         (h.grade == null ? '' : ' · оруж. ' + h.grade) + '</span>' +
         (zw ? '<span class="zw">专武 ' + esc(zw) + '</span>' : '') + '</div>';
}

function squadBody(s){
  var parts = [];
  parts.push('<div class="heroes">' + s.heroes.map(heroCard).join('') +
             (s.drone ? '<div class="hero"><b>Дрон</b><span class="g">ур. ' +
              (s.drone.grade == null ? '?' : s.drone.grade) + '</span></div>' : '') +
             '</div>');
  var full = fullPoints(s), lastFull = full.length ? full[full.length - 1] : null;
  parts.push('<div class="kv">' +
    '<span>мощь в полном составе <b>' + (lastFull ? num(lastFull[1]) : '—') +
      '</b></span>' +
    '<span>пик <b>' + num(s.peak) + '</b></span>' +
    '<span>на бойца <b>' + (s.hp ? num(s.power / s.hp) : '—') + '</b></span>' +
    '<span>последний замер <b>' + num(s.power) + '</b> при ' + num(s.hp) + ' из ' +
      num(s.fullHp) + ' бойцов</span>' +
    '<span>замеров <b>' + s.moments + '</b> (в полном составе ' + s.fullMoments +
      ')</span>' +
    '<span>замечен <b>' + when(s.last) + '</b></span>' +
    '<span>с <b>' + when(s.first) + '</b></span></div>');
  var series = squadSeries(s);
  if (series.pts.length < 2) {
    parts.push('<div class="empty">на этом режиме у отряда один день с замерами — ' +
               'график будет со второго</div>');
  } else {
    parts.push(chart([series]));
  }
  return '<div class="sqbd">' + parts.join('') + '</div>';
}

function playerBody(p){
  var series = p.squads.map(squadSeries).filter(function(s){ return s.pts.length >= 2; });
  var parts = [];
  parts.push('<div class="kv"><span>uid <b>' + esc(p.uid) + '</b></span>' +
    (p.aliases.length ? '<span>раньше <b>' + p.aliases.map(esc).join(', ') +
      '</b></span>' : '') +
    '<span>замеров <b>' + p.moments + '</b></span>' +
    '<span>замечен <b>' + when(p.last) + '</b></span></div>');
  if (series.length) {
    parts.push(chart(series) + legend(series));
    var quiet = p.squads.filter(function(s){ return points(s).length < 2; });
    if (quiet.length) {
      parts.push('<div class="empty">не на графике: ' + quiet.map(function(s){
        return 'отряд ' + (s.slot || '?'); }).join(', ') +
        ' — меньше двух дней с замерами на этом режиме</div>');
    }
  } else {
    parts.push('<div class="empty">пока по одному дню с замерами на отряд — общего ' +
               'графика нет</div>');
  }
  p.squads.forEach(function(s, i){
    var who = s.heroes.map(function(h){ return h.name ? esc(h.name) : '#' + h.id; })
                      .join(', ') || 'состав не записан';
    parts.push('<div class="sq" data-sq="' + i + '"><div class="hd">' +
      '<span class="chip c' + (s.slot || 0) + '">' + (s.slot || '?') + '</span>' +
      '<span class="nm">' + who + '</span>' +
      '<span class="pw">' + num(headline(s)) + ' ' + delta(s) + '</span>' +
      '</div></div>');
  });
  return parts.join('');
}

/* The avatar: a file beside the page when the id resolved to one, a coloured square
   with the first letter when it did not. Nothing is fetched from anywhere. */
function avatar(p){
  /* the player's own photo out of the client's cache first, the built-in avatar they
     picked second, a coloured initial when neither is on disk */
  var href = DATA.avatars[p.uid] ||
             (p.head != null ? DATA.avatars[String(p.head)] : null);
  if (href) return '<img class="ava" src="' + esc(href) + '" alt="" loading="lazy">';
  var hash = 0;
  for (var i = 0; i < p.uid.length; i++) hash = (hash * 31 + p.uid.charCodeAt(i)) % 360;
  var letter = (p.name || '?').trim().charAt(0).toUpperCase() || '?';
  return '<span class="ava ph" style="background:hsl(' + hash + ',45%,62%)">' +
         esc(letter) + '</span>';
}

function playerRow(p, ai, pi){
  var sum = p.squads.reduce(function(a, s){ return a + headline(s); }, 0);
  return '<div class="pl" data-al="' + ai + '" data-pl="' + pi + '"><div class="hd">' +
    avatar(p) +
    '<span class="who"><b class="nm">' + esc(p.name) + '</b>' +
    '<span class="meta">' + p.squads.length + ' отр. · ' + when(p.last) + '</span>' +
    '</span>' +
    '<span class="pw">' + num(sum) + '</span></div></div>';
}

var HOW = {
  archive: '',
  partial: 'тег альянса записан не у всех — остальным проставлен по общим стягам',
  inferred: 'тег альянса взят из таблицы рангов и разошёлся по тем, кто ездит в одних ' +
            'стягах с ним',
  unknown: 'тег альянса нигде не записан — это просто те, кто ездит в одних стягах'
};

function allianceBody(g, ai, q){
  var out = [], shown = 0;
  if (HOW[g.how]) out.push('<div class="how">' + HOW[g.how] + '</div>');
  g.players.forEach(function(p, pi){
    if (q && p.name.toLowerCase().indexOf(q) < 0 && p.uid.indexOf(q) < 0) return;
    shown++;
    out.push(playerRow(p, ai, pi));
  });
  if (!shown) out.push('<div class="empty">никого не нашлось</div>');
  return '<div class="albd">' + out.join('') + '</div>';
}

function render(){
  var q = document.getElementById('q').value.trim().toLowerCase();
  var host = document.getElementById('list');
  var out = [], shown = 0;
  DATA.alliances.forEach(function(g, ai){
    var hits = q ? g.players.filter(function(p){
      return p.name.toLowerCase().indexOf(q) >= 0 || p.uid.indexOf(q) >= 0; }) : g.players;
    if (q && !hits.length) return;
    shown += hits.length;
    var label = g.tag ? esc(g.tag) : 'без тега №' + g.index;
    out.push('<div class="al' + (q ? ' open' : '') + '" data-al="' + ai + '">' +
      '<div class="hd"><span class="tag' + (g.tag ? '' : ' none') + '">' + label +
        '</span>' +
      '<span class="nm meta">' + (g.name ? esc(g.name) : '') + '</span>' +
      '<span class="pw">' + num(g.players.reduce(function(a, p){
        return a + p.squads.reduce(function(b, s){ return b + headline(s); }, 0); }, 0)) +
        '</span>' +
      '<span class="meta">' + hits.length + ' игр.</span></div>' +
      (q ? allianceBody(g, ai, q) : '') + '</div>');
  });
  host.innerHTML = out.join('') || '<div class="empty">никого не нашлось</div>';
  document.getElementById('count').textContent = shown + ' из ' + DATA.total;
}

document.addEventListener('click', function(ev){
  if (!ev.target.closest) return;
  /* Only the header row toggles — a click inside an open body (a hero card, the
     chart) must not fold the thing the reader is looking at. */
  var sqHead = ev.target.closest('.sq > .hd');
  var sq = sqHead && sqHead.parentNode;
  if (sq) {
    var pl = sq.closest('.pl');
    var p = DATA.alliances[+pl.dataset.al].players[+pl.dataset.pl];
    var open = sq.querySelector('.sqbd');
    if (open) { open.remove(); } else {
      pl.querySelectorAll('.sqbd').forEach(function(n){ n.remove(); });
      sq.insertAdjacentHTML('beforeend', squadBody(p.squads[+sq.dataset.sq]));
    }
    return;
  }
  var plHead = ev.target.closest('.pl > .hd');
  var pl = plHead && plHead.parentNode;
  if (pl) {
    var body = pl.querySelector('.bd');
    if (body) { body.remove(); pl.classList.remove('open'); return; }
    pl.classList.add('open');
    pl.insertAdjacentHTML('beforeend', '<div class="bd">' +
      playerBody(DATA.alliances[+pl.dataset.al].players[+pl.dataset.pl]) + '</div>');
    return;
  }
  var alHead = ev.target.closest('.al > .hd');
  var al = alHead && alHead.parentNode;
  if (!al) return;
  var albd = al.querySelector('.albd');
  if (albd) { albd.remove(); al.classList.remove('open'); return; }
  al.classList.add('open');
  al.insertAdjacentHTML('beforeend',
    allianceBody(DATA.alliances[+al.dataset.al], +al.dataset.al, ''));
});

document.getElementById('q').addEventListener('input', render);
document.querySelectorAll('.seg button').forEach(function(b){
  b.addEventListener('click', function(){
    document.querySelectorAll('.seg button').forEach(function(o){ o.classList.remove('on'); });
    b.classList.add('on');
    MODE = b.dataset.mode;
    render();
  });
});
render();
"""


def render(data: dict, alliances: list = None, avatars: dict = None) -> str:
    """The page — data, style and behaviour in one file, avatars in a folder beside it."""
    if alliances is None:
        alliances = [{"tag": "", "name": "", "id": "", "how": "unknown", "known": 0,
                      "index": 1, "players": data["players"],
                      "power": sum(p["peak"] for p in data["players"]),
                      "last": max((p["last"] for p in data["players"]), default=0)}]
    avatars = avatars or {}
    window = data["window"]
    span = ""
    if window and window[1]:
        span = (time.strftime("%d.%m %H:%M", time.localtime(window[0])) + " — "
                + time.strftime("%d.%m %H:%M", time.localtime(window[1])))
    squads = sum(len(p["squads"]) for p in data["players"])
    moments = sum(p["moments"] for p in data["players"])
    files = ", ".join(html.escape(os.path.basename(os.path.dirname(s["path"])) or s["path"])
                      for s in data["sources"] if s["kept"])
    # The page holds the alliances, and each alliance holds its players — `players` and
    # `rallies` would be the same objects a second and a third time.
    payload = json.dumps({"alliances": alliances, "avatars": avatars,
                          "total": len(data["players"])},
                         ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    faces = sum(1 for p in data["players"]
                if p["uid"] in avatars or str(p["head"]) in avatars)
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Мощь отрядов</title><style>" + _CSS + "</style></head><body>"
        "<h1>Мощь отрядов</h1>"
        f'<div class="sub">{html.escape(span)} · альянсов {len(alliances)} · игроков '
        f'{len(data["players"])} · отрядов {squads} · замеров {moments} · '
        f'аватаров {faces} · профили: {files or "—"}</div>'
        '<div class="bar"><input type="search" id="q" placeholder="имя или uid" '
        'autocomplete="off"><div class="seg">'
        '<button class="on" data-mode="full" title="только замеры полным составом">'
        'мощь</button>'
        '<button data-mode="all" title="каждый замер, включая раненый отряд">все '
        'замеры</button>'
        '<button data-mode="unit" title="мощь, делённая на число бойцов">на бойца'
        '</button></div>'
        '<span class="meta" id="count"></span></div>'
        '<div id="list"></div>'
        "<script>var DATA=" + payload + ";\n" + _JS + "</script>"
        "</body></html>"
    )


# --------------------------------------------------------------------------- entry


def _default_inputs() -> list:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return sorted(glob.glob(os.path.join(root, "profiles", "*", "rally_log.jsonl")))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", action="append", default=None,
                    help="a rally_log.jsonl to read; repeatable. Every profile's "
                         "archive when left out — a player's squads often sit in a "
                         "neighbour's capture rather than your own")
    ap.add_argument("--out",
                    default=os.path.join(game_paths.report_dir(),
                                         "rally_report.html"),
                    help="where to write the page (default: the shared "
                         "report folder, cache/reports/)")
    ap.add_argument("--min-moments", type=int, default=0,
                    help="drop players seen fewer times than this")
    ap.add_argument("--no-live", action="store_true",
                    help="do not ask the running client for the avatars its alliance "
                         "roster knows (archives written before #1305 have none)")
    args = ap.parse_args()

    head = os.path.normpath(args.out).replace("\\", "/").split("/")[0]
    if head not in _ALLOWED_ROOTS and not os.path.isabs(args.out):
        print(f"refusing to write outside {'/, '.join(_ALLOWED_ROOTS)}/ — the page is "
              f"full of real nicknames and uids, and those trees are the git-ignored "
              f"ones", file=sys.stderr)
        return 1

    paths = args.input or _default_inputs()
    if not paths:
        print("no rally_log.jsonl found — the rally monitor writes one per profile "
              "while «Монитор стягиваний» is on", file=sys.stderr)
        return 1

    data = load(paths)
    if args.min_moments:
        data["players"] = [p for p in data["players"]
                           if p["moments"] >= args.min_moments]
    if not data["players"]:
        print("no rally rows in " + ", ".join(paths), file=sys.stderr)
        return 1

    if not args.no_live:
        live = live_head_skins()
        filled = 0
        for player in data["players"]:
            if player["head"] is None and player["uid"] in live:
                player["head"] = live[player["uid"]]
                filled += 1
        if filled:
            print(f"  {filled} avatar id(s) taken from the running client's alliance "
                  f"roster — the archive predates #1305 and carries none")

    alliances = group_by_alliance(data, paths)
    avatars, faces = copy_avatars(data["players"], args.out)
    page = render(data, alliances, avatars)
    directory = os.path.dirname(os.path.abspath(args.out))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    squads = sum(len(p["squads"]) for p in data["players"])
    moments = sum(p["moments"] for p in data["players"])
    named = sum(1 for g in alliances if g["tag"])
    print(f"{args.out} — {len(alliances)} alliance(s) ({named} named), "
          f"{len(data['players'])} player(s), {squads} squad(s), {moments} moment(s), "
          f"{os.path.getsize(args.out) // 1024} KiB")
    drawn = sum(1 for p in data["players"]
                if p["uid"] in avatars or str(p["head"]) in avatars)
    print(f"  avatars: {drawn} of {len(data['players'])} player(s) — "
          f"{faces['photos']} from the client's photo cache, {faces['sprites']} "
          f"built-in sprite(s); {faces['copied']} file(s), "
          f"{faces['bytes'] // 1024} KiB in {faces['folder']}")
    if faces["unmapped"]:
        print(f"  {len(faces['unmapped'])} avatar id(s) have no sprite on disk: "
              f"{sorted(set(faces['unmapped']))} — see docs/research/player-avatars.md")
    if not faces["photos"] and faces["cache"]:
        print(f"  the photo cache answered for nobody: {faces['cache']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
