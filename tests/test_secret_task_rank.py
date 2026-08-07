r"""One tile, two readers, one answer — the level and the star (task #1267).

The same live tile was read two ways, one round trip apart, and came back different:

    dispatch_tasks.alliance_roster        cfgId=60009903 -> level 7,  starred False
    steal_secret_task._vm_raidable_tasks  cfgId=60009903 -> level 99

Four of the account's fifty-two raidable rows. #1244 had already established where the
truth is — the client's own `lw_dispatch_tasks` row, `level` and `is_special`, because
the cfgId's digits call a level-7 tile «level 99» and read the star off a family that
over-reports — but it taught only the reader the PANEL uses. The tool's read emitted
`ACT VT …` lines with no config columns on them, so its parser had nothing to go on.

It never reached the panel (since #1256 the panel names its targets outright and the
tool re-derives nothing). What it broke is the route a person drives from a shell:
`--from-vm` sorts targets by level, so a tile mislabelled 99 goes to the head of the
queue and spends raids the real level-7 stars were meant to get, and `--level-max 7`
drops the very tiles the panel calls level 7.

So this file drives BOTH readers over one table of records and asserts they agree —
including the fallback, which is the only case the arithmetic may still answer.

    C:\Python312\python.exe tests\test_secret_task_rank.py
    python3 tests/test_secret_task_rank.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lastwar_proto as proto      # noqa: E402
import dispatch_tasks              # noqa: E402
import steal_secret_task as steal  # noqa: E402

#: (cfgId, config level, config is_special, what the game shows). The first row is the
#: tile off the live report; the rest are the shapes around it — an ordinary star, an
#: ordinary unstarred task, and a genuine `is_special` whose digits deny it.
LIVE = [
    (60009903, 7, 0, (7, False)),      # digits say «level 99»; the game says level 7
    (60000703, 7, 1, (7, True)),       # a star, and the config says so
    (50000703, 7, 0, (7, False)),      # not a star family, and not starred
    (60000603, 6, 1, (6, True)),       # the star is `is_special`, not the family
]


def _from_the_tool(cfg_id, lvl, spec):
    """What `steal_secret_task` makes of one `ACT VT …` line — (level, starred)."""
    line = ("ACT VT uuid=1 cfg=%d srv=9 x=1 y=2 steals=0 lvl=%s spec=%s "
            "done=1 exp=0" % (cfg_id, lvl, spec))
    tasks = steal._parse_vt_lines([line])
    assert len(tasks) == 1, tasks
    return tasks[0].level, tasks[0].starred


def _from_the_panel(cfg_id, lvl, spec):
    """What `dispatch_tasks.alliance_roster` makes of the same tile — (level, starred)."""
    line = ("ACT T kind=alliance uuid=1 cfgId=%d pointId=7 x=1 y=2 srv=9 owner=0 "
            "done=1 expires=0 steals=0 lvl=%s spec=%s colour=0 tstar=0 name= abbr="
            % (cfg_id, lvl, spec))

    class _Ev:
        def run(self, _chunk, _marker, _settle):
            return ["ACT now=1780000000", line]

    rows = dispatch_tasks.alliance_roster(_Ev())
    assert len(rows) == 1, rows
    return rows[0]["level"], rows[0]["starred"]


def test_the_two_readers_agree_on_every_live_shape():
    """THE REGRESSION, in the only terms that catch it: one tile through both readers."""
    for cfg_id, lvl, spec, expected in LIVE:
        tool = _from_the_tool(cfg_id, lvl, spec)
        panel = _from_the_panel(cfg_id, lvl, spec)
        assert tool == panel, f"cfg {cfg_id}: tool {tool} vs panel {panel}"
        assert tool == expected, f"cfg {cfg_id}: {tool}, expected {expected}"


def test_they_agree_when_the_client_has_no_config_row_either():
    """`lvl=0` is «the client had no template» — both must fall back the same way."""
    for cfg_id, _lvl, _spec, _expected in LIVE:
        tool = _from_the_tool(cfg_id, 0, 0)
        panel = _from_the_panel(cfg_id, 0, 0)
        assert tool == panel, f"cfg {cfg_id}: tool {tool} vs panel {panel}"
        # …and that fallback is the digits, which is what makes it a FALLBACK: on the
        # live tile it is wrong, and the whole point is that the config outranks it.
        family, level, _variant = proto.split_cfg_id(cfg_id)
        assert tool[0] == level


def test_the_live_tile_is_the_one_that_used_to_disagree():
    """Named on its own, so a future edit that reintroduces «level 99» says so."""
    assert _from_the_tool(60009903, 7, 0) == (7, False)
    assert _from_the_tool(60009903, 0, 0) == (99, False)      # the old, digits-only read


def test_not_asking_and_being_told_no_are_different_answers():
    """A pcap record must not claim the game denied the star — it was never asked."""
    from_wire = proto.SecretTask(
        uuid=1, server_id=9, x=1, y=2, level=7, cfg_id=60000703, family="6000",
        looted_by=(), owner_uid=None, alliance_id=None,
        expires_at=None, completed_at=None)
    assert from_wire.starred_cfg is None
    assert from_wire.starred is True                # the digits' answer, unobstructed

    denied = proto.SecretTask(
        uuid=1, server_id=9, x=1, y=2, level=7, cfg_id=60000703, family="6000",
        looted_by=(), owner_uid=None, alliance_id=None,
        expires_at=None, completed_at=None, starred_cfg=False)
    assert denied.starred is False                  # the game's answer, and it wins


def test_the_star_survives_a_checkpoint():
    """`as_dict` → `from_dict` must not quietly re-derive it from the digits."""
    task = proto.SecretTask(
        uuid=1, server_id=9, x=1, y=2, level=7, cfg_id=60009903, family="6000",
        looted_by=(), owner_uid=None, alliance_id=None,
        expires_at=None, completed_at=None, starred_cfg=False)
    back = proto.SecretTask.from_dict(task.as_dict())
    assert back.starred_cfg is False and back.level == 7


def test_the_reads_carry_the_columns_the_parser_needs():
    """The Lua half: both alliance reads must emit `lvl` and `spec`, or none of the
    above can work at run time however right the Python is."""
    import lua_actions

    for chunk in (lua_actions.secret_task_raidable_alliance(),
                  lua_actions.secret_task_all_alliance()):
        assert 'getValue("level")' in chunk, chunk[:200]
        assert 'getValue("is_special")' in chunk, chunk[:200]
        assert '" lvl="' in chunk and '" spec="' in chunk, chunk[-300:]


def test_the_rule_has_exactly_one_home():
    """Nobody re-implements the precedence — that is how the two came apart (#1244).

    The check is on the ATTRIBUTE, not the word: prose may name `STAR_TASK_FAMILIES`
    and should, but a caller reaching for `proto.STAR_TASK_FAMILIES` is a caller
    writing the rule out for the third time. `task_rank` where there is a client,
    `starred_by_digits` where there is not.
    """
    for path in sorted((_REPO / "tools").rglob("*.py")) + \
            sorted((_REPO / "panel").rglob("*.py")):
        body = path.read_text(encoding="utf-8")
        assert "proto.STAR_TASK_FAMILIES" not in body, (
            f"{path.relative_to(_REPO)} spells the star rule out again — "
            "call proto.task_rank / proto.starred_by_digits")
        assert "proto.SPECIAL_TASK_LEVEL" not in body or "starred" not in body, (
            f"{path.relative_to(_REPO)} decides a star from the 99 class by hand")


class _Ev:
    """A client that answers `dispatch_task_cfg_rank` out of a table, and counts asks."""

    def __init__(self, rows):
        self.rows, self.asked = rows, []

    def run(self, chunk, marker, settle, **kw):  # noqa: ARG002 — the shape ev.run has
        self.asked.append(chunk)
        out = []
        for cfg, (lvl, spec) in self.rows.items():
            if str(cfg) in chunk:
                out.append(f"ACT CFG cfg={cfg} lvl={lvl} spec={spec}")
        return out


def _task(uuid: int, cfg: int):
    """A checkpoint tile as the CAPTURE writes it — level and star from the digits."""
    family, level, _v = proto.split_cfg_id(cfg)
    return proto.SecretTask.from_dict({
        "uuid": uuid, "server_id": 999, "x": 1, "y": 2, "level": level,
        "cfg_id": cfg, "family": family, "looted_by": [],
        "expires_at": 0, "completed_at": 0, "starred_cfg": None})


def test_a_capture_tile_is_re_ranked_against_the_clients_own_config():
    """The digits get the last word only when there is no client to ask (#1188/#1267).

    `60009903` is the template the fallback is wrong about in BOTH directions: the digits
    read `99` as the level and family 6000 as a star, and the game's row says level 7 and
    `is_special = 0`. A checkpoint carries the digits' answer by construction — the
    capture has no client in its process — so anything CHOOSING a raid out of one has to
    re-ask, or it spends one of the day's five on a tile that is not a star at all.
    """
    tasks = [_task(1, 60009903), _task(2, 60000701), _task(3, 300704)]
    assert [(t.level, t.starred) for t in tasks] == [(99, False), (7, True), (7, False)]

    ev = _Ev({60009903: (7, 0), 60000701: (7, 1), 300704: (7, 0)})
    changed = steal.apply_cfg_rank(ev, tasks, say=lambda _m: None)
    assert [(t.level, t.starred) for t in tasks] == [(7, False), (7, True), (7, False)]
    assert changed == 1, changed
    # One round trip for the whole list, not one per tile: three tiles, one chunk, and
    # every DISTINCT template in it.
    assert len(ev.asked) == 1, ev.asked
    for cfg in (60009903, 60000701, 300704):
        assert str(cfg) in ev.asked[0], cfg


def test_a_template_the_client_cannot_answer_for_keeps_the_digits():
    """`lvl=0` is «the game had no row», not «level zero» — degrade, never invent."""
    tasks = [_task(1, 60000701)]
    steal.apply_cfg_rank(_Ev({60000701: (0, 0)}), tasks, say=lambda _m: None)
    assert (tasks[0].level, tasks[0].starred) == (7, True), tasks[0]

    # …and no client at all is the same answer, not a crash and not an empty list.
    tasks = [_task(1, 60009903)]
    assert steal.apply_cfg_rank(None, tasks, say=lambda _m: None) == 0
    assert (tasks[0].level, tasks[0].starred) == (99, False), tasks[0]


def test_the_panel_re_asks_the_star_on_the_wire_feed_and_not_only_the_tool():
    """Both places that CHOOSE a raid out of a checkpoint go through the same call.

    Asked of the source rather than of a running tab: the wire feed is read off the Tk
    thread inside `_fetch_scan`, and a test that stood a whole tab up to prove one call
    site would break for a dozen reasons that are not this rule.
    """
    body = (_REPO / "panel" / "tabs" / "secret_tasks" / "tab.py").read_text("utf-8")
    scan = body.split("def _fetch_scan")[1].split("\n    def ")[0]
    assert "apply_cfg_rank" in scan, "the panel still merges the capture's guess"
    tool = (_REPO / "tools" / "steal_secret_task.py").read_text("utf-8")
    from_scan = tool.split("def targets_from_scan")[1].split("\ndef ")[0]
    assert "apply_cfg_rank" in from_scan, "--from-scan still selects on the digits"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as exc:                    # noqa: BLE001
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
        else:
            print(f"  ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
