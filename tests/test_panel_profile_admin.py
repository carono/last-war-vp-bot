r"""Renaming and deleting a profile FROM THE PHONE, and the word that guards them (#1976).

Both presses lived in the window on the grounds that they are destructive and rare. That
was an argument for a CONFIRMATION and never for exclusivity — the window is being
retired, and a press only the machine has is a press nobody will be able to make. So they
travel, each carrying the guard the window's message box used to be:

  * a DELETE happens only when the profile's own name is typed back. A mis-tap on a list
    of accounts is what the guard is for, and «press it again» is no answer when the press
    is an `rmtree` of a chat history, a rally log and every store the account has;
  * a RENAME needs a new name to be a rename at all, and is not offered for a profile open
    on ANOTHER page — that session holds its log files and its page carries the old name,
    so moving the directory under it would leave both pointing at nothing. The shell
    refuses it too, so the row simply does not carry a press it would be told no for;
  * and the shell, which does the work, opens NO message box for a press that came from
    away: a modal raised for somebody who is not at the machine is a panel that stops.

Needs no game, no display and no panel: the screen is a dictionary, the press is checked
before it is handed over, and the shell's own half is READ out of the source — drawing a
window would need a display and prove nothing this file is about.

    C:\Python312\python.exe tests\test_panel_profile_admin.py
    python3 tests/test_panel_profile_admin.py
"""
from __future__ import annotations

TIER = "offline"   # tkinter is stubbed below — no display, no widgets, no game

import ast
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "tools", ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _stub_tk() -> None:
    """A tkinter that answers everything and draws nothing (`test_panel_monster_filter`).

    Nothing under test here is a widget: a screen is a dictionary and a press is a
    dictionary answered before anything is handed to the Tk thread. The runtime package
    imports tkinter on the way in all the same, so it is given a stand-in rather than a
    display.
    """
    if "tkinter" in sys.modules:
        return

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

from panel.runtime import profile_control as profilectl   # noqa: E402
from panel.web import api as apimod                       # noqa: E402

SHELL = ROOT / "panel" / "__main__.py"
LOCALES = ROOT / "panel" / "locales"

#: Every locale the panel ships — the folder, never a table in the code.
LANGS = sorted(p.stem for p in LOCALES.glob("*.json"))

NEW_KEYS = ("profile.delete.prompt", "profile.rename.open",
            "profile.confirm.refused", "log.profile.rename_failed")


# ---------------------------------------------------------------------------
# a panel small enough to read
# ---------------------------------------------------------------------------
class _Profiles:
    def __init__(self, names, active) -> None:
        self._names, self.active = list(names), active

    def list(self) -> list:
        return list(self._names)

    def load(self, name) -> dict:
        return {"daemon_port": 47654}


class _Workspace:
    def __init__(self, open_names, showing) -> None:
        self.names = list(open_names)
        self.current = type("S", (), {"name": showing})()


class _Rt:
    def __init__(self, names=("one", "two", "three"), open_names=("one", "two"),
                 showing="one") -> None:
        self.profiles = _Profiles(names, showing)
        self.workspace = _Workspace(open_names, showing)

    def t(self, key, **fmt) -> str:
        return key


def _api(rt=None, handler=None) -> "apimod.WebApi":
    """An API object with nothing in it but the two things a profile press touches."""
    api = apimod.WebApi.__new__(apimod.WebApi)
    rt = rt or _Rt()
    api._runtime = lambda profile=None: rt                       # noqa: SLF001
    api._name_of = lambda runtime: runtime.profiles.active       # noqa: SLF001
    api._profile_client_text = lambda runtime, name: ""          # noqa: SLF001
    api._hand_over = lambda runtime, func: func()                # noqa: SLF001
    profilectl.set_handler(handler)
    return api


def _rows(view: dict) -> dict:
    return {item["text"]: item for item in view["cards"][0]["items"]}


def _press_ids(item: dict) -> set:
    return {action["id"] for action in item.get("actions") or ()}


# ---------------------------------------------------------------------------
# the table
# ---------------------------------------------------------------------------
def test_the_two_destructive_presses_are_declared_with_a_word_to_type() -> None:
    for action in (profilectl.RENAME, profilectl.DELETE):
        control = profilectl.BY_ID[action]
        assert control.prompt, f"«{action}» asks for no word — that is the whole guard"
        assert control.label, f"«{action}» has no label key"
    assert not profilectl.BY_ID[profilectl.OPEN].prompt, (
        "«open» grew a prompt — a press that costs nothing to undo must not ask")


def test_the_typed_word_reaches_the_shell() -> None:
    seen = []
    profilectl.set_handler(lambda action, name, text: seen.append((action, name, text)) or True)
    try:
        assert profilectl.carry_out(profilectl.RENAME, "one", "two") is True
        assert seen == [(profilectl.RENAME, "one", "two")], seen
    finally:
        profilectl.set_handler(None)


# ---------------------------------------------------------------------------
# the screen
# ---------------------------------------------------------------------------
def test_every_row_that_may_be_renamed_offers_it_and_no_other_does() -> None:
    view = _api()._profiles_view(None)                          # noqa: SLF001
    rows = _rows(view)
    assert profilectl.RENAME in _press_ids(rows["one"]), (
        "the profile the window is showing cannot be renamed from the phone")
    assert profilectl.RENAME in _press_ids(rows["three"]), (
        "a closed profile cannot be renamed from the phone")
    assert profilectl.RENAME not in _press_ids(rows["two"]), (
        "a profile open on another page offers a rename the shell would refuse")
    profilectl.set_handler(None)


def test_every_row_offers_a_delete_and_the_last_profile_does_not() -> None:
    view = _api()._profiles_view(None)                            # noqa: SLF001
    for name, item in _rows(view).items():
        assert profilectl.DELETE in _press_ids(item), f"«{name}» cannot be deleted"
    alone = _api(_Rt(names=("one",), open_names=("one",)))._profiles_view(None)  # noqa: SLF001
    assert profilectl.DELETE not in _press_ids(_rows(alone)["one"]), (
        "the last profile on the disk offers a delete that cannot succeed")
    profilectl.set_handler(None)


def test_the_delete_press_asks_for_the_name_and_the_rename_for_a_new_one() -> None:
    rows = _rows(_api()._profiles_view(None))                     # noqa: SLF001
    by_id = {a["id"]: a for a in rows["one"]["actions"]}
    assert by_id[profilectl.DELETE]["prompt"] == "profile.delete.prompt"
    assert by_id[profilectl.DELETE].get("value") == "", (
        "the delete box opens with the name already in it — that is not a confirmation")
    assert by_id[profilectl.RENAME]["prompt"] == "profile.prompt_name"
    assert by_id[profilectl.RENAME]["value"] == "one", (
        "the rename box opens empty — the name it starts from is what is being edited")
    profilectl.set_handler(None)


# ---------------------------------------------------------------------------
# the press
# ---------------------------------------------------------------------------
def test_a_delete_whose_typed_name_does_not_match_does_nothing_at_all() -> None:
    done = []
    api = _api(handler=lambda *a: done.append(a) or True)
    try:
        for typed in ("", "onee", "ONE", "two"):
            answer = api._profiles_press(profilectl.DELETE,                # noqa: SLF001
                                         {"name": "one", "text": typed}, None)
            assert answer == {"ok": False, "reason": "profile.confirm.refused"}, answer
        assert not done, f"a delete was carried out on a wrong word: {done}"
        assert api._profiles_press(profilectl.DELETE,                      # noqa: SLF001
                                   {"name": "one", "text": "one"}, None)["ok"]
        assert done == [(profilectl.DELETE, "one", "one")], done
    finally:
        profilectl.set_handler(None)


def test_a_rename_needs_a_new_name_and_hands_it_over() -> None:
    done = []
    api = _api(handler=lambda *a: done.append(a) or True)
    try:
        for typed in ("", "one"):
            answer = api._profiles_press(profilectl.RENAME,                # noqa: SLF001
                                         {"name": "one", "text": typed}, None)
            assert answer == {"ok": False, "reason": "profile.confirm.refused"}, answer
        assert not done, f"a rename was carried out on nothing: {done}"
        assert api._profiles_press(profilectl.RENAME,                      # noqa: SLF001
                                   {"name": "one", "text": "four"}, None)["ok"]
        assert done == [(profilectl.RENAME, "one", "four")], done
    finally:
        profilectl.set_handler(None)


def test_opening_and_creating_are_untouched_by_the_guard() -> None:
    done = []
    api = _api(handler=lambda *a: done.append(a) or True)
    try:
        assert api._profiles_press(profilectl.OPEN, {"name": "three"}, None)["ok"]  # noqa: SLF001
        # «Создать» is a press with no name: the typed word IS the profile.
        assert api._profiles_press(profilectl.OPEN, {"text": "four"}, None)["ok"]   # noqa: SLF001
        assert [d[:2] for d in done] == [(profilectl.OPEN, "three"),
                                         (profilectl.OPEN, "four")], done
    finally:
        profilectl.set_handler(None)


# ---------------------------------------------------------------------------
# the shell's own half — read, because drawing a window needs a display
# ---------------------------------------------------------------------------
def _method(name: str) -> ast.FunctionDef:
    tree = ast.parse(SHELL.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from the shell")


def test_the_shell_takes_the_typed_word_and_carries_both_presses_out() -> None:
    press = _method("_profile_press")
    args = [a.arg for a in press.args.args]
    assert args[:4] == ["self", "action", "name", "text"], args
    body = ast.dump(press)
    for action in ("RENAME", "DELETE"):
        assert action in body, f"the shell knows nothing of «{action}»"


def test_neither_headless_press_can_open_a_message_box() -> None:
    """`ask` is what draws the box, and a press from away passes it `False`."""
    for name in ("_rename_profile", "_delete_profile", "_make_room_to_delete"):
        node = _method(name)
        assert "ask" in [a.arg for a in node.args.args], (
            f"{name} cannot be told nobody is at the machine")
    for node in ast.walk(_method("_profile_press")):
        if isinstance(node, ast.keyword) and node.arg == "ask":
            assert node.value.value is False, "a press from the phone draws a box"


def test_the_window_may_still_press_them_with_no_arguments() -> None:
    """The menu's buttons pass nothing — every added parameter has a default."""
    for name in ("_rename_profile", "_delete_profile"):
        node = _method(name)
        wanted = len(node.args.args) - 1                 # self
        assert len(node.args.defaults) >= wanted, (
            f"{name} can no longer be called the way the window's button calls it")


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------
def test_every_new_word_is_in_all_eleven_locales() -> None:
    missing = []
    for lang in LANGS:
        table = json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        for key in NEW_KEYS:
            if key not in table:
                missing.append(f"{lang}: {key}")
    assert not missing, "\n  ".join([""] + missing)


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
