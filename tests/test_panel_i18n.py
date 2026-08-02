r"""A language is a FILE — there is no list of languages in the code (#1199).

The Language menu used to be built from a table in `panel/i18n.py`, so a locale file
somebody added by hand was loadable and invisible: nothing offered it. Now the menu is
the locales directory — the code stem from the file name, the label from the file's own
`language.name` — and that is what these tests pin, by dropping a locale into the real
directory and asking whether it turned up.

Needs no Tk and no display: this is the JSON layer.

    C:\Python312\python.exe tests\test_panel_i18n.py
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from panel import i18n  # noqa: E402


class _extra_locale:
    """Drop a `<lang>.json` into the shipped locales directory for one test."""

    def __init__(self, lang: str, table: dict) -> None:
        self.path = Path(i18n.LOCALES_DIR) / f"{lang}.json"
        self.lang = lang
        self.table = table

    def __enter__(self):
        assert not self.path.exists(), f"{self.path} exists — refusing to overwrite"
        self.path.write_text(json.dumps(self.table, ensure_ascii=False),
                             encoding="utf-8")
        i18n._CACHE.pop(self.lang, None)
        return self

    def __exit__(self, *exc):
        try:
            os.unlink(self.path)
        except OSError:
            pass
        i18n._CACHE.pop(self.lang, None)
        return False


def test_there_is_no_table_of_languages_in_the_code():
    """The whole point: the panel must not carry a list to keep in step with the
    directory. Not just the old name — any literal `{"en": …, "ru": …}` is the same
    bug wearing a different one, so the check is on the shape, over the parsed source
    rather than the text (a comment may still SAY «ru.json holds "Русский"»)."""
    assert not hasattr(i18n, "LANG_NAMES"), "the hard-coded table is back"
    for path in (_REPO / "panel" / "i18n.py", _REPO / "panel" / "__main__.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert "LANG_NAMES" not in {n.id for n in ast.walk(tree)
                                    if isinstance(n, ast.Name)}, \
            f"{path.name} still reads the table"
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict) or not node.keys:
                continue
            keys = [k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            looks_like_langs = (len(keys) == len(node.keys)
                                and all(len(k) == 2 and k.isalpha() for k in keys))
            assert not looks_like_langs, \
                f"{path.name}:{node.lineno} maps language codes to something"


def test_both_shipped_locales_name_themselves():
    """Every locale carries its own display name, in its own script — that is where the
    menu label comes from now, so a file without it is a menu entry saying «ru»."""
    for lang in ("en", "ru"):
        table = json.loads((Path(i18n.LOCALES_DIR) / f"{lang}.json")
                           .read_text(encoding="utf-8"))
        assert table.get(i18n.LANG_NAME_KEY), f"{lang}.json has no {i18n.LANG_NAME_KEY}"
    assert i18n.lang_name("en") == "English"
    assert i18n.lang_name("ru") == "Русский"


def test_a_language_added_by_hand_is_offered_and_usable():
    """Copy en.json, translate it, set `language.name` — and it is in the menu."""
    with _extra_locale("zz", {i18n.LANG_NAME_KEY: "Тестовый", "menu.language": "Мова"}):
        assert "zz" in i18n.available_langs(), i18n.available_langs()
        assert i18n.lang_name("zz") == "Тестовый"
        tr = i18n.I18n("zz")
        assert tr.lang == "zz", tr.lang
        assert tr.t("menu.language") == "Мова"
        # …and a key it does not translate still falls back to the default language
        # rather than showing the bare key: a half-translated locale stays usable.
        assert tr.t("menu.help") == i18n.I18n("en").t("menu.help")

        # And through the RUNTIME, which is what the Language menu iterates — the
        # module being right is no use if the panel asks something else.
        from panel.runtime.i18n import Translator
        menu = Translator()
        assert "zz" in menu.available(), menu.available()
        assert menu.name("zz") == "Тестовый"
        assert menu.known("zz")
    assert "zz" not in i18n.available_langs(), "the temporary locale was not removed"


def test_a_locale_without_a_name_falls_back_to_its_file_name():
    """Forgetting `language.name` must cost the label, not the language."""
    with _extra_locale("zy", {"menu.language": "Sprache"}):
        assert "zy" in i18n.available_langs()
        assert i18n.lang_name("zy") == "zy"


def test_a_broken_locale_is_not_a_crash():
    """A file somebody hand-edited into invalid JSON, and one whose value is not a
    string — neither may take the panel down, because the panel reads whatever is in
    the directory now."""
    path = Path(i18n.LOCALES_DIR) / "zx.json"
    assert not path.exists()
    try:
        path.write_text("{not json", encoding="utf-8")
        i18n._CACHE.pop("zx", None)
        assert i18n.load_locale("zx") == {}
        assert i18n.lang_name("zx") == "zx"
        assert i18n.I18n("zx").t("menu.language") == i18n.I18n("en").t("menu.language")
    finally:
        os.unlink(path)
        i18n._CACHE.pop("zx", None)

    with _extra_locale("zw", {"menu.language": {"nested": "map"},
                              i18n.LANG_NAME_KEY: 17}):
        assert i18n.lang_name("zw") == "zw"
        assert i18n.I18n("zw").t("menu.language") == "menu.language"


def test_known_tells_a_missing_language_from_the_current_one():
    """`set_lang` returns False for BOTH "no such language" and "already that one", and
    only the first is worth a line in the log — so the question is asked separately."""
    assert i18n.known("en") and i18n.known("ru")
    assert not i18n.known("zq")
    assert not i18n.known("")
    assert not i18n.known(None)


def test_a_profile_naming_a_language_with_no_file_falls_back_and_says_so():
    """A profile written where `de.json` existed, opened on a machine where it is not.

    English, a line in the log naming the language — and NOT a rewritten preference:
    the remembered choice survives, so the language comes back by itself the moment the
    file does.
    """
    try:
        import tkinter as tk
        from panel.runtime import host as hostmod
        root = tk.Tk()
    except Exception as exc:                            # noqa: BLE001
        print(f"  SKIP no Tk: {exc}")
        return
    root.withdraw()
    # The panel remembers the language in the REAL home directory; a test must not be
    # what changes it, and `set_lang` writes on every successful switch.
    pref, tmp = i18n._PREF_FILE, tempfile.mkdtemp()
    i18n._PREF_FILE = os.path.join(tmp, "pref.json")
    try:
        rt = hostmod.PanelRuntime(root, lang="zq")
        assert rt.i18n.lang == i18n.DEFAULT_LANG, rt.i18n.lang
        said = "\n".join(rt.log.drain())
        assert "zq" in said, f"the fallback was silent: {said!r}"
        assert rt.t("menu.language") == i18n.I18n("en").t("menu.language")
        # The fallback did not persist: nothing was remembered at all.
        assert not os.path.exists(i18n._PREF_FILE), "a fallback rewrote the preference"

        # …and a language there IS a file for is honoured, quietly.
        rt2 = hostmod.PanelRuntime(root, lang="ru")
        assert rt2.i18n.lang == "ru", rt2.i18n.lang
        assert not [ln for ln in rt2.log.drain() if "zq" in ln]
    finally:
        i18n._PREF_FILE = pref
        shutil.rmtree(tmp, ignore_errors=True)
        root.destroy()


def test_switching_to_a_profile_with_a_missing_language_says_so_too():
    """The same rule on the other door: a profile SWITCHED TO, not opened with.

    `Panel._profile_language` called unbound against a stand-in — no window, no profile
    on disk, no game.
    """
    import types

    from panel import __main__ as pm

    said = []
    stand_in = types.SimpleNamespace(
        _settings={"language": "zq"},
        _i18n=types.SimpleNamespace(known=i18n.known),
        _say=lambda tag, key, **fmt: said.append((tag, key, fmt)),
    )
    assert pm.Panel._profile_language(stand_in) == i18n.DEFAULT_LANG
    assert said and said[0][1] == "log.lang.unknown", said
    assert said[0][2]["lang"] == "zq", said

    said.clear()
    stand_in._settings = {"language": "ru"}
    assert pm.Panel._profile_language(stand_in) == "ru"
    assert said == [], said
    # A profile with no language at all is not a complaint either — it is the default.
    stand_in._settings = {}
    assert not pm.Panel._profile_language(stand_in)
    assert said == [], said


def test_the_default_language_is_always_offerable():
    """Even with the directory unreadable: a Language menu with nothing in it is worse
    than one with a single entry."""
    saved = i18n.LOCALES_DIR
    try:
        i18n.LOCALES_DIR = os.path.join(saved, "does-not-exist")
        assert i18n.available_langs() == [i18n.DEFAULT_LANG]
    finally:
        i18n.LOCALES_DIR = saved


def test_the_default_language_comes_first():
    langs = i18n.available_langs()
    assert langs[0] == i18n.DEFAULT_LANG, langs
    assert langs[1:] == sorted(langs[1:]), langs


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
