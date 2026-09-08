r"""Counting the hijacks by who asked for them (#2656).

Two halves, and both are about not fooling the reader:

  * the hijack's own per-label map is CAPPED, because a caller that builds a label per
    item would otherwise grow it without bound in a process that runs for days — and
    what falls past the cap is added up rather than dropped, so the parts still sum to
    the whole;
  * a snapshot is a COPY. A reader takes two and subtracts; a shared dict would leave it
    subtracting a map from itself and reporting a quiet nought for ever.

    C:\Python312\python.exe tests\test_hijack_tally.py
    python3 tests/test_hijack_tally.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hijack_tally  # noqa: E402

# `hijack_call` reaches for `ctypes.WinDLL` at import, so the two tests about its own
# tally can only run where there is a Windows to hijack into. The tally reader is pure
# and is checked everywhere — which is the half a machine without the game can break.
try:
    import hijack_call  # noqa: E402
except (AttributeError, ImportError, OSError):    # not Windows
    hijack_call = None


def _clear() -> None:
    hijack_call.STATS["by_label"] = {}


def test_a_snapshot_is_a_copy() -> None:
    if hijack_call is None:
        print("       (skipped — no Windows here)")
        return
    _clear()
    hijack_call._count("read")
    first = hijack_call.stats()
    hijack_call._count("read")
    hijack_call._count("write")
    second = hijack_call.stats()
    assert first["by_label"] == {"read": 1}, "the first snapshot must not have moved"
    assert second["by_label"] == {"read": 2, "write": 1}
    moved = {k: v - first["by_label"].get(k, 0) for k, v in second["by_label"].items()}
    assert moved == {"read": 1, "write": 1}


def test_the_map_is_capped_and_the_rest_still_counted() -> None:
    if hijack_call is None:
        print("       (skipped — no Windows here)")
        return
    _clear()
    for i in range(hijack_call.LABEL_CAP + 25):
        hijack_call._count(f"caller{i}")
    by = hijack_call.stats()["by_label"]
    assert len(by) == hijack_call.LABEL_CAP + 1, "the cap, plus the bucket"
    assert by[hijack_call.OTHER_LABEL] == 25, "and nothing is lost"
    assert sum(by.values()) == hijack_call.LABEL_CAP + 25
    _clear()


def test_a_day_is_added_up_from_the_log() -> None:
    lines = [
        "[2026-01-02 10:00:00.000] [INFO] [link] hijacks 7 in 60s: 1.00s (0.143 s/hijack)",
        "[2026-01-02 10:00:00.001] [INFO] [link] hijack labels 60s: read=4 write=3",
        "[2026-01-02 10:01:00.001] [INFO] [link] hijack labels 60s: read=2",
        "[2026-01-03 10:02:00.001] [INFO] [link] hijack labels 60s: read=99",
        "[2026-01-02 10:03:00.000] [INFO] [ui] something else entirely",
    ]
    by, labelled, total = hijack_tally.tally(lines, day="2026-01-02")
    assert by == {"read": 6, "write": 3}, by
    assert labelled == 9
    assert total == 7, "the minute totals are kept as a cross-check"

    everything, all_n, _ = hijack_tally.tally(lines)
    assert everything["read"] == 105, "and no --day means every day in the log"
    assert all_n == 108


def test_a_label_with_a_space_is_not_cut_in_half() -> None:
    if hijack_call is None:
        print("       (skipped — no Windows here)")
        return
    _clear()
    hijack_call._count("LuaEnv cls")
    hijack_call._count("LuaEnv cls")
    by = hijack_call.stats()["by_label"]
    assert by == {"LuaEnv_cls": 2}, by
    # …because the reader splits the minute's line on whitespace, and a raw space would
    # have filed both of these under «cls».
    read, n, _ = hijack_tally.tally(
        ["[2026-01-02 10:00:00.001] [INFO] [link] hijack labels 60s: "
         + " ".join(f"{k}={v}" for k, v in by.items())])
    assert read == {"LuaEnv_cls": 2} and n == 2
    _clear()


def test_a_label_with_odd_characters_survives() -> None:
    by, n, _ = hijack_tally.tally(
        ["[2026-01-02 10:00:00.001] [INFO] [link] hijack labels 60s: "
         "DoString(bytes)=12 il2cpp_class_get_methods=3 …other=1"])
    assert by == {"DoString(bytes)": 12, "il2cpp_class_get_methods": 3, "…other": 1}
    assert n == 16


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
