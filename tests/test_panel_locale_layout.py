r"""A language may be one file or many, and the panel cannot tell (#1282).

`panel/locales/<lang>.json` is how the tables began: eleven files, every key in every
one. That rule is why the tables are complete and it is not changing — what it costs is
the LAYOUT. Over the last 200 commits each of the eleven was touched by 37 different
tasks and 85 commits (43 %) touched all eleven at once, so two agents adding two keys to
two unrelated tabs collided every single time.

The cure is a cut by TAB — `panel/locales/ru/secret_tasks.json` — merged into the same
table at load. This file pins the merge itself, on temporary directories rather than on
the shipped locales, so it says the same thing before the migration, half way through it
and after it:

  * a flat file alone still loads (nothing has changed for a language nobody has split);
  * a per-tab file alone loads, and its language is offered in the menu;
  * both together are ONE table, and a key defined twice resolves to the per-tab copy;
  * a broken part is skipped rather than crashing the panel, exactly as a broken flat
    file always was;
  * and no key is defined twice across the shipped locale files as they stand today —
    which is the thing a half-finished migration would leave behind.

Needs neither Tk nor a display: `panel.i18n` is a JSON reader.

    C:\Python312\python.exe tests\test_panel_locale_layout.py
    python3 tests/test_panel_locale_layout.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel import i18n as i18nmod                                       # noqa: E402


class _Locales:
    """A temporary locales directory `panel.i18n` is pointed at for one test."""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._saved = i18nmod.LOCALES_DIR

    def __enter__(self) -> "_Locales":
        i18nmod.LOCALES_DIR = str(self.dir)
        i18nmod._CACHE.clear()
        return self

    def __exit__(self, *exc) -> None:
        i18nmod.LOCALES_DIR = self._saved
        i18nmod._CACHE.clear()
        self.tmp.cleanup()

    def flat(self, lang: str, data: dict) -> None:
        (self.dir / f"{lang}.json").write_text(json.dumps(data), encoding="utf-8")

    def part(self, lang: str, tab: str, data) -> None:
        (self.dir / lang).mkdir(parents=True, exist_ok=True)
        text = data if isinstance(data, str) else json.dumps(data)
        (self.dir / lang / f"{tab}.json").write_text(text, encoding="utf-8")


def test_a_language_that_is_still_one_file_loads_exactly_as_it_did() -> None:
    with _Locales() as loc:
        loc.flat("en", {"a.one": "One", "b.two": "Two"})
        assert i18nmod.load_locale("en") == {"a.one": "One", "b.two": "Two"}
        assert "en" in i18nmod.available_langs()


def test_a_language_made_only_of_per_tab_files_is_a_language() -> None:
    """No flat file at all — the end state of the migration, not a broken install."""
    with _Locales() as loc:
        loc.part("ru", "rally", {"rally.title": "Сбор"})
        loc.part("ru", "secret_tasks", {"secret_tasks.title": "Секретки"})
        table = i18nmod.load_locale("ru")
        assert table == {"rally.title": "Сбор", "secret_tasks.title": "Секретки"}
        assert "ru" in i18nmod.available_langs(), i18nmod.available_langs()


def test_the_two_layouts_merge_into_one_table() -> None:
    """Half migrated is a state the panel spends weeks in; it must read as one table."""
    with _Locales() as loc:
        loc.flat("de", {"shell.title": "Panel", "rally.title": "flat"})
        loc.part("de", "rally", {"rally.title": "Sammlung", "rally.join": "Beitreten"})
        table = i18nmod.load_locale("de")
        assert table["shell.title"] == "Panel"      # untouched by the split
        assert table["rally.join"] == "Beitreten"   # only in the per-tab file
        # A key in both: the per-tab file is the one being migrated TO, so it wins —
        # otherwise a move would silently keep serving the copy it was moving away from.
        assert table["rally.title"] == "Sammlung"


def test_a_broken_part_does_not_take_the_panel_down_with_it() -> None:
    """Same promise the flat file always had: a bad locale is missing, not fatal."""
    with _Locales() as loc:
        loc.flat("en", {"a.one": "One"})
        loc.part("en", "broken", "{ this is not json")
        loc.part("en", "good", {"b.two": "Two"})
        assert i18nmod.load_locale("en") == {"a.one": "One", "b.two": "Two"}


def test_no_shipped_key_is_defined_twice() -> None:
    """The real locales, as they are today — no key in both a flat and a per-tab file.

    This is what a migration abandoned half way leaves behind: two answers to one key,
    one of them stale, and nothing that reads the panel can tell which it is getting.
    """
    locales = _REPO / "panel" / "locales"
    for flat in sorted(locales.glob("*.json")):
        lang = flat.stem
        both: dict[str, list[str]] = {}
        flat_keys = set(json.loads(flat.read_text(encoding="utf-8")))
        for part in sorted((locales / lang).glob("*.json")):
            part_keys = set(json.loads(part.read_text(encoding="utf-8")))
            for key in flat_keys & part_keys:
                both.setdefault(key, []).append(part.name)
        assert not both, f"{lang}: defined in {flat.name} AND in a part — {both}"


def _run() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:                              # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
