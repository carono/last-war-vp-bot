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
import sys
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
