r"""The words of the panel: where they live, and that none of them live anywhere else.

Two rules, both binding (`CLAUDE.md`, «Not one word of the panel is written in the
panel»), and this file is what enforces them:

* **Nothing a person reads is a literal.** A label, a button, a menu entry, a dialog —
  all of them name a locale key and the runtime says it. `test_no_hardcoded_text_…`
  walks the source of every module under `panel/` and fails on the first translatable
  string handed to a widget.
* **A key is in EVERY shipped locale, translated.** English silently covers a locale
  that is behind, so a half-translated tab looks exactly like a finished one;
  `test_every_shipped_locale_…` compares the key sets both ways.

And the older rule this file was written for (#1199): a language is a FILE — there is no
list of languages in the code. The Language menu used to be built from a table in
`panel/i18n.py`, so a locale file somebody added by hand was loadable and invisible:
nothing offered it. Now the menu is the locales directory — the code stem from the file
name, the label from the file's own `language.name` — and that is pinned here too, by
dropping a locale into the real directory and asking whether it turned up.

Needs no Tk and no display: this is the JSON layer.

    C:\Python312\python.exe tests\test_panel_i18n.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import ast
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from panel import i18n  # noqa: E402


def _shipped() -> dict[str, dict]:
    """Every locale the repository ships, read from disk: `{lang: table}`."""
    out = {}
    for path in sorted(Path(i18n.LOCALES_DIR).glob("*.json")):
        out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return out


#: Every module that can put a word in front of a person.
def _panel_sources():
    for path in sorted((_REPO / "panel").rglob("*.py")):
        if "__pycache__" in path.parts or "profiles" in path.parts:
            continue
        yield path


#: A locale key: dotted, lower-case, no spaces. Used to tell a key from a sentence.
_KEYISH = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")

#: Where the first argument (or the named one) is a locale key: `t(key)`, `tr(w, key)`,
#: `say(tag, key)`. The number is which positional argument holds it.
_KEY_AT = {"t": 0, "_t": 0, "tr": 1, "_tr": 1, "say": 1, "_say": 1}


def _keys_asked_for_in_code() -> set[str]:
    """Every locale key the panel names as a literal, plus its `*_KEY` class attributes."""
    found: set[str] = set()
    for path in _panel_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                at = _KEY_AT.get(name)
                if at is not None and len(node.args) > at:
                    arg = node.args[at]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        found.add(arg.value)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Name) and target.id.endswith("_KEY")
                            and isinstance(node.value, ast.Constant)
                            and isinstance(node.value.value, str)):
                        found.add(node.value.value)
    return {k for k in found if _KEYISH.match(k)}


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


def test_every_key_the_code_asks_for_exists_in_every_locale():
    """The other direction: a key the panel renders but no locale defines.

    `t` falls back to the key itself, so the person reads «tab.mything» off the tab
    strip. Only the keys spelled as literals can be checked from here — the ones built
    at run time (`"cmdpost.tab." + key`) are each covered by their own tab's test.
    """
    shipped = _shipped()
    asked = _keys_asked_for_in_code()
    assert len(asked) > 300, f"the scanner found only {len(asked)} keys — it is broken"
    for lang, table in sorted(shipped.items()):
        missing = sorted(k for k in asked if k not in table)
        assert not missing, f"{lang}.json does not define {missing[:12]}"


def test_a_refusal_worded_far_from_the_ui_is_still_translated():
    """Not every string starts life next to a translator.

    The profile store refuses a duplicate name; the timers catalogue makes no sense of a
    hand-edited entry. Both modules are deliberately UI-agnostic, so what reached the
    person used to be whatever English they raised — «profile already exists: main» in a
    Russian dialog. `Message` carries the locale key alongside the English, and
    `translated()` is what the dialog and the log call.
    """
    from panel import profile as profilemod
    from panel import timers as timersmod

    ru, en = i18n.I18n("ru").t, i18n.I18n("en").t

    # It IS the English string — every consumer that had a `str` is untouched…
    msg = i18n.Message("profile.error.exists", "profile already exists: main",
                       name="main")
    assert msg == "profile already exists: main"
    assert "already exists" in msg
    # …and it says itself in the panel's language when something asks it to.
    assert i18n.translated(ru, msg) == ru("profile.error.exists", name="main")
    assert "main" in i18n.translated(ru, msg)
    assert i18n.translated(ru, msg) != i18n.translated(en, msg)

    # Raised, caught, and shown — the path `Panel._error_text` takes.
    try:
        profilemod.ProfileManager().create("")
    except ValueError as exc:
        assert i18n.translated(ru, exc) == ru("profile.error.empty_name")
    else:
        raise AssertionError("an empty profile name was accepted")

    # A plain exception carries no key and is shown as it came — an OSError from the
    # filesystem must not turn into a locale key nobody has.
    assert i18n.translated(ru, OSError("disk on fire")) == "disk on fire"
    assert i18n.translated(ru, "already words") == "already words"

    # And the catalogue's complaints, which reach the log the same way.
    bad = timersmod.parse_catalogue([{"name": ""}], "timers.json")
    assert bad.errors, "a nameless entry must be complained about"
    for problem in bad.errors:
        said = i18n.translated(ru, problem)
        assert said != str(problem), f"{problem!r} reached the log untranslated"
        assert said == ru(problem.key, **problem.fmt)


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


#: The languages the panel ships — the ones the game has a table for AND that Tk can
#: draw. The game has nineteen; Chinese (zh_CN, zh_TW, gn_CN), Japanese, Korean, Arabic
#: and Thai are deliberately not here (Tcl/Tk 8.6 does no bidi reordering and no Arabic
#: joining, and nobody on this side can proofread the CJK ones), and `vr` is not either
#: — it is a 99.7% copy of `vi`. Kept in step with `tools/game_locale.py`.
BASE_LANGS = {"en", "ru", "de", "fr", "es", "it", "pt", "pl", "tr", "id", "vi"}

#: What each locale calls itself, in its own script — the Language menu reads this out
#: of the file, so a typo here is a menu entry nobody recognises.
LANG_NAMES = {
    "en": "English", "ru": "Русский", "de": "Deutsch", "fr": "Français",
    "es": "Español", "it": "Italiano", "pt": "Português", "pl": "Polski",
    "tr": "Türkçe", "id": "Bahasa Indonesia", "vi": "Tiếng Việt",
}


def test_every_shipped_locale_names_itself():
    """Every locale carries its own display name, in its own script — that is where the
    menu label comes from now, so a file without it is a menu entry saying «ru»."""
    shipped = _shipped()
    missing = sorted(BASE_LANGS - set(shipped))
    assert not missing, f"a base language is gone: {missing}"
    for lang, table in shipped.items():
        assert table.get(i18n.LANG_NAME_KEY), f"{lang}.json has no {i18n.LANG_NAME_KEY}"
    for lang, name in sorted(LANG_NAMES.items()):
        assert i18n.lang_name(lang) == name, f"{lang} calls itself {i18n.lang_name(lang)!r}"


def test_every_shipped_locale_translates_every_key():
    """The rule that costs nothing to break and months to notice.

    A key a locale is missing falls back to English WITHOUT a word anywhere, so a tab
    added in two languages out of three looks finished. English is the canonical set;
    the comparison runs both ways, because a key deleted from one file only is the same
    bug from the other side — and a locale carrying a key nobody uses any more is dead
    weight nobody will ever diff away.
    """
    shipped = _shipped()
    english = set(shipped["en"])
    for lang, table in sorted(shipped.items()):
        if lang == "en":
            continue
        missing = sorted(english - set(table))
        extra = sorted(set(table) - english)
        assert not missing, (f"{lang}.json does not translate {len(missing)} key(s): "
                             f"{missing[:8]}{' …' if len(missing) > 8 else ''}")
        assert not extra, (f"{lang}.json has {len(extra)} key(s) en.json does not: "
                           f"{extra[:8]}{' …' if len(extra) > 8 else ''}")


def test_every_translation_is_a_string_with_the_same_placeholders():
    """A value must be a string, and it must carry the same `{named}` slots as the
    English one: `t` swallows a `format` that raises and shows the raw template, so a
    typo in a placeholder is a line that quietly says «{n} min» to the person."""
    shipped = _shipped()
    english = shipped["en"]
    slots = re.compile(r"\{(\w+)")
    for lang, table in sorted(shipped.items()):
        for key, value in sorted(table.items()):
            assert isinstance(value, str), f"{lang}.json[{key}] is not a string"
            if lang == "en" or key not in english:
                continue
            want, got = set(slots.findall(english[key])), set(slots.findall(value))
            assert want == got, (f"{lang}.json[{key}] has placeholders {sorted(got)}, "
                                 f"en.json has {sorted(want)}")


def test_no_hardcoded_text_anywhere_in_the_panel():
    """Nothing a person reads may be written in the code.

    Source-only, over the parsed tree rather than the text, so a docstring explaining
    the rule is not itself a violation. What counts as «a person reads it»: `text=`,
    `title=` and `placeholder=` on any call, `label=` on a menu entry, and the
    positional arguments of a message box — that is every door the panel has ever put a
    word through. A string with no run of three letters is not a word (`"(%d–%d)"`,
    «·», «⟳»), and neither is an internal tag: those stay literals on purpose.
    """
    words = re.compile(r"[A-Za-zА-Яа-яЁёÄÖÜäöüß]{3,}")
    menu_add = {"add_command", "add_cascade", "add_checkbutton", "add_radiobutton"}
    dialogs = {"showinfo", "showerror", "showwarning", "askyesno", "askokcancel",
               "askquestion", "askstring", "askretrycancel"}
    found = []
    for path in _panel_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = (node.func.attr if isinstance(node.func, ast.Attribute)
                      else node.func.id if isinstance(node.func, ast.Name) else "")
            said = []
            for kw in node.keywords:
                if kw.arg in ("text", "title", "placeholder") or (
                        kw.arg == "label" and called in menu_add):
                    said.append(kw.value)
            if called in dialogs:
                said.extend(node.args)
            for value in said:
                if (isinstance(value, ast.Constant) and isinstance(value.value, str)
                        and words.search(value.value)):
                    found.append(f"{path.relative_to(_REPO)}:{node.lineno} "
                                 f"{value.value!r}")
    assert not found, ("words written in the panel instead of panel/locales/:\n  "
                       + "\n  ".join(found))


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
