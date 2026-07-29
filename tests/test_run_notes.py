r"""Unit tests for the sniffer-run notes (``tools/lib/run_notes.py``).

Covers what the panel's post-run dialog relies on: a description survives a
write/read roundtrip, "delete" takes the notes down with the files, and the two
halves of one session — whose timestamps differ by a second or two, because the
capture and the tracer do not come up together — are listed as ONE run.

    python3 tests/test_run_notes.py        # standalone, prints PASS/FAIL
    pytest tests/test_run_notes.py

Filesystem only: no game, no capture.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import run_notes  # noqa: E402


def _results(tmp_path=None) -> Path:
    """A throwaway ``results/`` with traffic/ and traces/ subdirectories."""
    root = Path(tmp_path or tempfile.mkdtemp()) / "results"
    for sub in run_notes.KIND_DIRS.values():
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _run(root: Path, stamp_trace: str, stamp_traffic: str | None = None,
         label: str = "") -> list[str]:
    """Write a fake session's files; returns their paths (trace first)."""
    tag = f"_{label}" if label else ""
    trace = root / "traces" / f"{stamp_trace}{tag}_trace.log"
    trace.write_text("XSTRACE installed wrapped=8730\n", encoding="utf-8")
    paths = [str(trace)]
    if stamp_traffic:
        traffic = root / "traffic" / f"{stamp_traffic}{tag}_traffic.jsonl"
        traffic.write_text('{"cmd": "al.help.all"}\n', encoding="utf-8")
        paths.append(str(traffic))
    return paths


def test_note_lands_beside_every_file_of_the_run(tmp_path=None):
    """Save writes the same description next to both halves — either one leads to it."""
    root = _results(tmp_path)
    paths = _run(root, "20260728_171425", "20260728_171426", "Сбор_ресурсов")
    written = run_notes.write_note(paths, "opened the base, pressed collect on 4 buildings",
                                   label="Сбор ресурсов")
    assert len(written) == 2, written
    for path in paths:
        assert Path(run_notes.note_path(path)).exists(), path
        assert run_notes.read_note(path) == "opened the base, pressed collect on 4 buildings"


def test_description_is_named_after_the_run_and_holds_the_words_alone(tmp_path=None):
    """`…_trace.log` -> `…_desc.txt` beside it, with nothing but what was typed.

    The file is read straight into an analysis prompt, so a header would only
    have to be stripped there.
    """
    root = _results(tmp_path)
    paths = _run(root, "20260728_155726", "20260728_155731", "сокровище")
    run_notes.write_note(paths, "тапнул на сокровище и собрал его", label="сокровище")
    trace_desc = Path(run_notes.note_path(paths[0]))
    assert trace_desc.name == "20260728_155726_сокровище_desc.txt", trace_desc
    assert trace_desc.read_text(encoding="utf-8") == "тапнул на сокровище и собрал его\n"
    assert Path(run_notes.note_path(paths[1])).name == \
        "20260728_155731_сокровище_desc.txt"


def test_unlabelled_and_same_second_runs_get_their_own_description(tmp_path=None):
    """No label -> `<stamp>_desc.txt`; the `_2` collision suffix travels with it."""
    root = _results(tmp_path)
    plain = root / "traces" / "20260727_223311_trace.log"
    plain.write_text("XSCALL A.b\n", encoding="utf-8")
    assert Path(run_notes.note_path(str(plain))).name == "20260727_223311_desc.txt"
    dup = root / "traces" / "20260727_223311_x_trace_2.log"
    assert Path(run_notes.note_path(str(dup))).name == "20260727_223311_x_2_desc.txt"


def test_note_names_do_not_collide_with_the_run_files(tmp_path=None):
    """A description must not look like a run file — else listing runs would find them."""
    root = _results(tmp_path)
    paths = _run(root, "20260728_171425", "20260728_171426", "gifts")
    run_notes.write_note(paths, "alliance -> gifts -> collect all", label="gifts")
    for path in paths:
        note = Path(run_notes.note_path(path))
        assert note.name.endswith(run_notes.NOTE_SUFFIX), note
        assert run_notes.parse_run_name(note.name) is None, note


def test_run_stats_counts_what_the_file_is_made_of(tmp_path=None):
    """The dialog's «calls» / «frames» — a byte count cannot tell an empty run."""
    root = _results(tmp_path)
    trace = root / "traces" / "20260728_171425_x_trace.log"
    trace.write_text("XSTRACE installed wrapped=8730\n"
                     "XSCALL A.b <- 1\nXSCALL C.d <- 2\n", encoding="utf-8")
    traffic = root / "traffic" / "20260728_171426_x_traffic.jsonl"
    traffic.write_text('{"cmd": "a"}\n{"cmd": "b"}\n\n', encoding="utf-8")
    assert run_notes.run_stats(str(trace))["records"] == 2      # not the status line
    assert run_notes.run_stats(str(traffic))["records"] == 2    # not the blank line
    assert run_notes.run_stats(str(trace))["size"] == trace.stat().st_size
    assert run_notes.run_stats(str(root / "traces" / "gone.log")) == {"size": 0, "records": 0}


def test_empty_description_writes_nothing(tmp_path=None):
    """A note that says nothing looks like an answer — do not write one."""
    root = _results(tmp_path)
    paths = _run(root, "20260728_171425", "20260728_171426", "x")
    assert run_notes.write_note(paths, "   \n  ") == []
    assert run_notes.read_note(paths[0]) is None


def test_read_note_of_a_run_without_one(tmp_path=None):
    root = _results(tmp_path)
    paths = _run(root, "20260728_171425", label="x")
    assert run_notes.read_note(paths[0]) is None


def test_discard_removes_the_files_and_their_notes(tmp_path=None):
    """Delete must leave nothing of the run behind, notes included."""
    root = _results(tmp_path)
    paths = _run(root, "20260728_171425", "20260728_171426", "wrong_thing")
    run_notes.write_note(paths, "recorded the wrong action", label="wrong thing")
    gone = run_notes.discard_run(paths)
    assert len(gone) == 4, gone
    for path in paths:
        assert not Path(path).exists()
        assert not Path(run_notes.note_path(path)).exists()
    assert run_notes.discard_run(paths) == []      # idempotent


def test_list_runs_pairs_the_two_halves(tmp_path=None):
    """The children start ~1 s apart, so the pairing cannot key on an equal stamp."""
    root = _results(tmp_path)
    paths = _run(root, "20260728_205159", "20260728_205200", "Сбор_ресурсов_на_базе")
    run_notes.write_note(paths, "pressed collect on every building", label="Сбор ресурсов")
    runs = run_notes.list_runs(str(root))
    assert len(runs) == 1, runs
    assert set(runs[0]["files"]) == {"trace", "traffic"}, runs[0]
    assert runs[0]["description"] == "pressed collect on every building"


def test_list_runs_keeps_separate_sessions_apart(tmp_path=None):
    """Same label, hours apart -> two runs; newest first."""
    root = _results(tmp_path)
    _run(root, "20260728_013329", "20260728_013330", "кража_секретки")
    _run(root, "20260729_013404", "20260729_013405", "кража_секретки")
    runs = run_notes.list_runs(str(root))
    assert [r["stamp"] for r in runs] == ["20260729_013404", "20260728_013329"], runs


def test_list_runs_reports_a_half_session(tmp_path=None):
    """Only the tracer came up — that is the run, and it must read that way."""
    root = _results(tmp_path)
    _run(root, "20260728_171425", None, "Сбор_ресурсов")
    runs = run_notes.list_runs(str(root))
    assert len(runs) == 1 and set(runs[0]["files"]) == {"trace"}, runs
    assert runs[0]["description"] is None


def test_parse_run_name_forms():
    """Unlabelled, labelled and same-second-collision names all parse."""
    plain = run_notes.parse_run_name("20260727_223311_trace.log")
    assert plain == {"stamp": "20260727_223311", "label": "", "kind": "trace",
                     "dup": None}, plain
    labelled = run_notes.parse_run_name("20260728_171425_Сбор_ресурсов_trace.log")
    assert labelled["label"] == "Сбор_ресурсов" and labelled["kind"] == "trace", labelled
    dup = run_notes.parse_run_name("20260728_171425_x_traffic_2.jsonl")
    assert dup["kind"] == "traffic" and dup["dup"] == "2", dup
    assert run_notes.parse_run_name("notes.md") is None


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
