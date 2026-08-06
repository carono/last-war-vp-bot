r"""«This secret task has already been shared» — the mark, and the file it lives in.

A secret task worth a raid gets forwarded to the alliance, and once it has been there
is nothing to gain from forwarding it again: the people who were going to march on it
have already seen it. So the panel's list marks the tiles that have been shared — and
the mark has to come from BOTH places a share can happen (task #1245):

  * the panel's own «Поделиться» — the tab writes the mark itself when the send
    succeeds;
  * the **game's** own share button — pressed in the client, by this player or by an
    alliancemate. The server broadcasts every one of those to the whole alliance
    (`push.alliance.share.mission.add`) and hands the client the standing list on login
    (`get.alliance.share.mission.list`), so the passive captures this repository
    already runs see them without a single extra read
    (`lastwar_proto.share_missions`).

A mark written by the panel and a mark written by a capture child are the same fact
about the same tile, so they go into ONE file — and because the writers are separate
processes, the file is **append-only JSONL** rather than a rewritten map. An append of
one short line is the closest thing to atomic two processes can agree on without a
lock, and the worst a torn write can cost is that one line: :func:`load` skips whatever
it cannot parse instead of throwing the file away.

    >>> mark(path, uuid=1000000000000001, via=VIA_PANEL)
    >>> load(path)                        # {"1000000000000001": {...}}

The reader compacts (see :func:`load`): once the file is longer than it needs to be,
the surviving marks are rewritten as one line each, so a profile that shares every day
for a year does not grow a log nobody reads.

**Wall clock, not the game's.** Every other timestamp on the secret-task tab is judged
against `game_clock` because the game stamps it and the two disagree by seconds
(#1227). This one is stamped HERE, by us, and is only ever used to age a mark out after
the tile it belongs to is long gone — so the machine's own clock is the right one, and
mixing the two would be the mistake.
"""
from __future__ import annotations

import json
import os
import time

#: Where the mark came from. Kept as data rather than a bool because «я поделился этим
#: из панели» and «это расшарили в игре» are different sentences to the person reading
#: the row, and one of them is a thing the panel did on their behalf.
VIA_PANEL = "panel"
VIA_GAME = "game"

#: How long a mark is kept. A secret task expires within hours, so anything older than
#: this names a tile that cannot be on any list any more; the window is generous
#: because the only cost of keeping one is a line in a file.
MAX_AGE_MS = 48 * 60 * 60 * 1000

#: Compaction threshold: how many lines the file may hold beyond the number of distinct
#: marks in it before :func:`load` rewrites it. Not zero — rewriting on every read would
#: make a reader that runs once a second the busiest writer of the lot.
COMPACT_SLACK = 200


def now_ms() -> int:
    """The clock a mark is stamped on — this machine's, see the module docstring."""
    return int(time.time() * 1000)


def mark(path: str, uuid, via: str = VIA_GAME, uid: str = "", ts: int | None = None) -> bool:
    """Record that the task ``uuid`` has been shared. Best-effort; never raises.

    ``uid`` is who shared it when that is known — the push carries `shareUid` — and is
    empty for a share the panel made, where «who» is the player themself.

    Returns whether the line was written, so a caller that wants to log the fact can
    tell a real append from a read-only filesystem.
    """
    key = _key(uuid)
    if not key or not path:
        return False
    record = {"uuid": key, "via": str(via or VIA_GAME),
              "ts": int(ts if ts is not None else now_ms())}
    if uid:
        record["uid"] = str(uid)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def load(path: str, max_age_ms: int = MAX_AGE_MS, now: int | None = None) -> dict:
    """Every mark still worth keeping, as ``{uuid: record}``. Never raises.

    The newest line for a uuid wins, so a tile shared from the panel and then shared
    again in the game reads as the later of the two. Lines older than ``max_age_ms``
    are dropped — and if dropping them (or de-duplicating) left the file meaningfully
    longer than its contents, it is rewritten compact on the way out.
    """
    cutoff = (now_ms() if now is None else int(now)) - max(0, int(max_age_ms))
    out: dict = {}
    lines = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                lines += 1
                try:
                    record = json.loads(raw)
                except ValueError:
                    continue          # one torn line, not the whole history
                if not isinstance(record, dict):
                    continue
                key = _key(record.get("uuid"))
                if not key:
                    continue
                try:
                    stamp = int(record.get("ts") or 0)
                except (TypeError, ValueError):
                    stamp = 0
                if stamp and stamp < cutoff:
                    continue
                previous = out.get(key)
                if previous is None or stamp >= int(previous.get("ts") or 0):
                    out[key] = {"uuid": key,
                                "via": str(record.get("via") or VIA_GAME),
                                "ts": stamp,
                                "uid": str(record.get("uid") or "")}
    except (OSError, ValueError):
        return out
    if lines > len(out) + COMPACT_SLACK:
        _compact(path, out)
    return out


def _compact(path: str, records: dict) -> None:
    """Rewrite the file as one line per surviving mark. Best-effort, never raises.

    Through a temporary file and a replace, so a reader compacting while a capture
    child appends cannot leave a half-written history behind — the append either lands
    in the old file (and is lost, one mark, which the next share re-states) or in the
    new one.
    """
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            for record in records.values():
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def mark_missions(path: str, missions, uid: str = "") -> int:
    """Mark every `ShareMission` in an iterable; return how many were written.

    The shape `lastwar_proto.share_missions` yields, so a capture that already decodes
    a share frame marks it in one line. ``uid`` is a fallback for a mission that
    carries no `shareUid` of its own.
    """
    written = 0
    for mission in missions or ():
        who = str(getattr(mission, "share_uid", "") or uid or "")
        if mark(path, getattr(mission, "uuid", None), VIA_GAME, who):
            written += 1
    return written


def _key(uuid) -> str:
    """A task uuid as the string both sides key on.

    Always a string: a uuid is an 18-digit number that does not survive a float, and
    JSON object keys are strings anyway — so the panel's rows, which are keyed by
    `str(uuid)`, and this file agree without anybody converting.
    """
    if uuid is None:
        return ""
    text = str(uuid).strip()
    return "" if text in ("", "0", "None", "nil") else text
