r"""The remote control's knobs, set with no window under them (#1976, P3).

The panel's own port, host, token and certificate are the MACHINE's setting (#1313), and
they are deliberately unreachable from the web: it is the door the person came in
through. Until now the only way IN was the Tk dialog, and the window is being deleted —
so `panel/web_settings.py` is the way in that is neither the window nor the door, and
what is pinned here is that it is exactly that and nothing more:

  * reading changes nothing — a bare run must not rewrite the block it prints;
  * every knob travels, and `--token new` really produces a new one;
  * a contradiction (`--on --off`) and a number that is not a port are refused with a
    code and NOTHING stored — a half-applied door is how somebody locks themselves out;
  * and the divergence itself is untouched: the web API still cannot reach the setting.

Runs anywhere: no window, no display, no game.

    C:\Python312\python.exe tests\test_panel_web_settings_cli.py
    python3 tests/test_panel_web_settings_cli.py
"""
from __future__ import annotations

TIER = "offline"   # no window, no display, no Tk

import contextlib
import io
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from panel import web_settings as cli            # noqa: E402
from panel.runtime import web_control            # noqa: E402


class _Store:
    """The machine's block, in memory — never this machine's real `settings.json`."""

    def __init__(self, block=None) -> None:
        self.block = dict(block or {})
        self.writes = 0

    def read(self) -> dict:
        return dict(self.block)

    def write(self, values) -> None:
        self.block = dict(values)
        self.writes += 1


@contextlib.contextmanager
def _store(block=None):
    """Point `web_control` at a store of our own for the length of one check."""
    store = _Store(block)
    saved = (web_control.profilemod.web_settings,
             web_control.profilemod.set_web_settings,
             web_control.profilemod.migrate_web_settings)
    web_control.profilemod.web_settings = store.read
    web_control.profilemod.set_web_settings = store.write
    web_control.profilemod.migrate_web_settings = lambda: None
    try:
        yield store
    finally:
        (web_control.profilemod.web_settings,
         web_control.profilemod.set_web_settings,
         web_control.profilemod.migrate_web_settings) = saved


def _run(*argv):
    """The command, its exit code and everything it printed."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_reading_the_block_writes_nothing_at_all():
    with _store({"enabled": True, "port": "9763", "token": "abc"}) as store:
        code, out, _ = _run()
        assert code == 0, code
        assert store.writes == 0, "a bare run rewrote the setting it was asked to print"
        assert "9763" in out and "abc" in out, out


def test_every_knob_travels_and_lands_in_the_block():
    with _store() as store:
        code, _, _ = _run("--on", "--port", "9763", "--host", "127.0.0.1",
                          "--token", "SECRET", "--cert", "c.pem", "--key", "k.pem")
        assert code == 0, code
        assert store.block["enabled"] is True, store.block
        assert store.block["port"] == "9763", store.block
        assert store.block["host"] == "127.0.0.1", store.block
        assert store.block["token"] == "SECRET", store.block
        assert store.block["cert"] == "c.pem" and store.block["key"] == "k.pem"

        assert _run("--off")[0] == 0
        assert store.block["enabled"] is False, store.block
        assert store.block["port"] == "9763", "--off forgot the rest of the block"


def test_a_new_token_is_new_and_none_removes_it():
    with _store({"token": "old"}) as store:
        assert _run("--token", "new")[0] == 0
        fresh = store.block["token"]
        assert fresh and fresh != "old", fresh
        assert len(fresh) >= 16, f"a guessable token: {len(fresh)} characters"

        assert _run("--token", "none")[0] == 0
        assert store.block["token"] == "", store.block


def test_a_contradiction_and_a_non_port_are_refused_with_nothing_stored():
    for argv in (("--on", "--off"), ("--port", "70000"), ("--port", "0")):
        with _store({"port": "9763"}) as store:
            code, _, err = _run(*argv)
            assert code == 2, f"{argv} answered {code}"
            assert err.strip(), f"{argv} was refused without saying why"
            assert store.writes == 0, f"{argv} was refused AFTER writing"


def test_the_link_is_the_one_a_phone_is_given():
    with _store({"enabled": True, "port": "9763", "token": "TOK"}):
        code, out, _ = _run("--address")
        assert code == 0, code
        assert out.count("\n") == 1, f"--address printed more than the link:\n{out}"
        assert ":9763/?token=TOK" in out, out
        assert out.startswith("http"), out


def test_the_divergence_is_untouched_and_the_web_still_cannot_reach_the_knobs():
    """#1313: the door is not managed from the far side of it. This is a way IN on the
    machine, not a screen — so the web API must still know nothing about the setting."""
    api = (_REPO / "panel" / "web" / "api.py").read_text(encoding="utf-8")
    assert "web_control" not in api, "the remote control's own knobs reached the web API"


def main() -> int:
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
        except Exception as exc:                  # noqa: BLE001 — a report, not a crash
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok   {name}")
    print("FAILED" if failed else "OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
