r"""A panel that cannot take hold of the client keeps SAYING so (#1994).

Half of the fourteen-hour outage was not the mechanism at all: the panel said one line
when the link first failed and then nothing for five minutes, over and over, while its
schedule stood still behind a held gate. To a person reading the log, a panel that has
stopped complaining is indistinguishable from a panel that is working.

What is pinned here is the behaviour, not the source:

  * the first refusal is said once, on the edge, as it always was;
  * the same refusal repeated seconds later is NOT said again — the noise this codebase
    keeps relearning (#1910);
  * but a minute on it IS said again, as «for how long», so the log shows a panel that
    is still waiting;
  * a refusal the route marked `client-busy` — somebody is playing, which is ordinary
    and not a fault — is said in the person's own words rather than the mechanism's;
  * and a reason that CHANGES is news immediately, whatever the clock says.

    C:\Python312\python.exe tests\test_link_speaks_while_stuck.py
    python3 tests/test_link_speaks_while_stuck.py
"""
from __future__ import annotations

TIER = "offline"

import pathlib
import sys
import types

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))


def _stub_tk() -> None:
    class _W:
        def __init__(self, *a, **k) -> None:
            pass

        def __getattr__(self, _n):
            return lambda *a, **k: None

    def _module(name: str):
        mod = types.ModuleType(name)
        made: dict = {}

        def _make(attr: str):
            if attr not in made:
                made[attr] = type(attr, (_W,), {})
            return made[attr]

        mod.__getattr__ = _make
        return mod

    tk = _module("tkinter")
    tk.TclError = type("TclError", (Exception,), {})
    sys.modules["tkinter"] = tk
    for sub in ("ttk", "font", "messagebox", "simpledialog", "scrolledtext",
                "filedialog"):
        child = _module(f"tkinter.{sub}")
        sys.modules[f"tkinter.{sub}"] = child
        setattr(tk, sub, child)


_stub_tk()

from panel.runtime.link import GameLink                      # noqa: E402


class _Log:
    def __init__(self) -> None:
        self.said: list = []

    def say(self, tag, key, **fmt) -> None:
        self.said.append((key, fmt))


def _link() -> "GameLink":
    """A GameLink with only what `_say_failure` touches — no client, no game, no Tk."""
    link = object.__new__(GameLink)
    link._said_fail = ""
    link._said_at = 0.0
    link._fail_since = 0.0
    link._log = _Log()
    link._note_warn = lambda *a, **k: None
    return link


def _at(link, seconds: float) -> None:
    """Move the scripted clock `_say_failure` reads."""
    import panel.runtime.link as mod
    mod.time = types.SimpleNamespace(monotonic=lambda: seconds, sleep=lambda *_: None)


def test_the_first_refusal_is_said_once():
    link = _link()
    _at(link, 1000.0)
    link._say_failure("attach", "log.link.attach_failed", error="boom")
    _at(link, 1003.0)
    link._say_failure("attach", "log.link.attach_failed", error="boom")
    assert [k for k, _ in link._log.said] == ["log.link.attach_failed"], \
        "the same refusal three seconds later was said twice"


def test_a_minute_on_it_says_how_long():
    link = _link()
    _at(link, 1000.0)
    link._say_failure("attach", "log.link.attach_failed", error="boom")
    _at(link, 1130.0)
    link._say_failure("attach", "log.link.attach_failed", error="boom")
    keys = [k for k, _ in link._log.said]
    assert keys == ["log.link.attach_failed", "log.link.attach_stuck"], keys
    assert link._log.said[-1][1]["minutes"] == 2, \
        "the repeat does not carry how long the link has been down"


def test_a_busy_client_is_named_as_such():
    link = _link()
    _at(link, 1000.0)
    err = "client-busy: enum: the client's main thread is busy"
    link._say_failure("attach", "log.link.attach_failed", error=err)
    _at(link, 1070.0)
    link._say_failure("attach", "log.link.attach_failed", error=err)
    assert link._log.said[-1][0] == "log.link.attach_busy", \
        "«somebody is playing» is reported as an ordinary fault"


def test_a_changed_reason_is_news_at_once():
    link = _link()
    _at(link, 1000.0)
    link._say_failure("attach", "log.link.attach_failed", error="boom")
    _at(link, 1005.0)
    link._say_failure("no client", "log.link.attach_failed", error="gone")
    assert len(link._log.said) == 2, "a different reason waited for the clock"


def test_coming_back_forgets_the_clock():
    link = _link()
    _at(link, 1000.0)
    link._say_failure("attach", "log.link.attach_failed", error="boom")
    link._said_fail, link._fail_since = "", 0.0        # what `ensure` does on success
    _at(link, 1300.0)
    link._say_failure("attach", "log.link.attach_failed", error="boom")
    assert [k for k, _ in link._log.said][-1] == "log.link.attach_failed", \
        "a link that came back and failed again reported the OLD outage's duration"


def test_a_repeat_with_no_reason_still_says_how_long():
    """A caller with no `{error}` to give gets a key that does not ask for one (#2578).

    `session_silent` carries a port, not an error, and the repeat is built from a
    DIFFERENT key — one whose text names an error. Handing it a `fmt` without one made
    the whole line fall back to its own template, so the live panel printed
    «уже {minutes} мин: {error}» once a minute for hours: the one line that was meant
    to say how long the client had been out of reach said nothing at all.
    """
    import json
    import pathlib as _pathlib

    link = _link()
    _at(link, 1000.0)
    link._say_failure("silent", "log.link.session_silent", port=40000)
    _at(link, 1130.0)
    link._say_failure("silent", "log.link.session_silent", port=40000)

    key, fmt = link._log.said[-1]
    assert key == "log.link.attach_stuck_quiet", \
        f"a reasonless repeat asked for a key that names an error: {key}"
    assert fmt.get("minutes") == 2, f"the repeat lost how long it has been: {fmt}"

    root = _pathlib.Path(__file__).resolve().parents[1] / "panel" / "locales"
    missing = []
    for path in sorted(root.glob("*.json")):
        text = json.loads(path.read_text(encoding="utf-8")).get(key)
        if not text:
            missing.append(path.stem)
            continue
        assert "{minutes}" in text, f"{path.stem}: {key} lost its minutes"
        assert "{error}" not in text, \
            f"{path.stem}: {key} asks for an error the caller has not got"
    assert not missing, f"{key} is missing from: {', '.join(missing)}"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
        else:
            print(f"  ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
