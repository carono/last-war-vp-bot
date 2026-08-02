r"""Every registered tab honours the contract — one test, parametrised over the registry.

A tab is added by putting it in `panel/tabs/__init__.py`, and from that moment this file
covers it: it must import, build against a COLD runtime, survive the lifecycle in order,
and leave nothing armed behind. That is the whole point of writing the contract down —
the guarantee is the registry's, not each tab's author's memory.

The runtime handed to `build()` is cold on purpose (`docs/research/panel-tabs-refactor.md`
§3.1): a standalone tab has to open with no daemon, no client and no network, so a tab
that reads the game while building would work in the shell and hang on its own. The fake
game link here refuses every call and records that it was asked.

Needs Tk and a display; says SKIP under the WSL python3.

    C:\Python312\python.exe tests\test_panel_tab_contract.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_runtime  # noqa: E402
from panel import tabs as tabsreg  # noqa: E402


def _skip(what, exc=None) -> None:
    print(f"  SKIP {what}: {exc}" if exc else f"  SKIP {what}")


def test_every_tab_imports():
    """A tab in the registry whose module does not import is a tab nobody can open."""
    for spec in tabsreg.TABS:
        cls = spec.load()
        assert cls.ID == spec.id, f"{spec.id}: class says ID={cls.ID!r}"
        assert cls.TITLE_KEY, f"{spec.id}: no TITLE_KEY"
        # The notebook labels a tab BEFORE building it, from the spec — importing the
        # module just to read one string would undo the registry's laziness. So the two
        # have to agree, and this is what keeps them agreeing.
        assert cls.TITLE_KEY == spec.title_key, (
            f"{spec.id}: registry says {spec.title_key!r}, class says {cls.TITLE_KEY!r}")


def test_the_registry_ids_are_unique_and_ordered():
    ids = [s.id for s in tabsreg.TABS]
    assert len(ids) == len(set(ids)), ids
    orders = [s.order for s in tabsreg.TABS]
    assert len(orders) == len(set(orders)), f"two tabs share an order: {orders}"


def test_resolve_defaults_to_the_default_enabled_set():
    got = [s.id for s in tabsreg.resolve()]
    assert got == [s.id for s in sorted(tabsreg.TABS, key=lambda s: s.order)
                   if s.default_enabled], got


def test_switching_a_tab_off_in_the_profile_leaves_it_out():
    """The whole point of the refactor, in one assertion: a tab the profile does not
    name is not resolved — so it is never built, contributes no settings page, and
    starts none of its captures or watchers."""
    every = [s.id for s in tabsreg.TABS]
    got = [s.id for s in tabsreg.resolve(enabled=["stats", "heroes"], known=every)]
    assert got == ["stats", "heroes"] or set(got) == {"stats", "heroes"}, got
    # …and an EMPTY list is "none of them", not "the defaults" — an operator who wants
    # a panel with nothing but the log must be able to say so.
    assert [s.id for s in tabsreg.resolve(enabled=[], known=every)] == []
    # A tab the profile has never been offered still appears: `known` is what tells
    # "switched off" from "did not exist when this profile was written".
    fresh = [s.id for s in tabsreg.resolve(enabled=["stats"], known=["stats", "heroes"])]
    assert "heroes" not in fresh, fresh
    assert "rally" in fresh, fresh


def test_a_profile_naming_a_tab_that_no_longer_exists_is_survivable():
    """A profile written by a newer build must not break an older panel."""
    unknown = []
    got = [s.id for s in tabsreg.resolve(enabled=["stats", "a-tab-from-the-future"],
                                         on_unknown=unknown.append)]
    assert unknown == ["a-tab-from-the-future"], unknown
    assert "stats" in got, got
    # …and a tab the profile has never heard of still appears, at its own order.
    assert "heroes" in got, got


def test_the_profile_order_wins_over_the_declared_one():
    got = [s.id for s in tabsreg.resolve(order=["stats", "heroes"])]
    assert got[:2] == ["stats", "heroes"], got


def test_every_tab_builds_cold_and_survives_the_lifecycle():
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:                                # noqa: BLE001
        _skip("tkinter not importable — run under the Windows Python", exc)
        return
    try:
        root = tk.Tk()
    except Exception as exc:                                # noqa: BLE001
        _skip("no display", exc)
        return
    root.withdraw()
    try:
        for spec in tabsreg.TABS:
            cls = spec.load()
            rt = fake_runtime.cold_runtime(root)
            rt.settings.register(cls.SETTINGS)
            frame = ttk.Frame(root)
            tab = cls(rt, frame)

            tab.build()
            assert rt.game.asked == [], (
                f"{spec.id}: build() touched the game ({rt.game.asked}) — a standalone "
                f"tab has to open with no daemon at all")

            # The page it contributes to Settings is built the same way and under the
            # same rule: it is drawn while the panel boots, long before a daemon.
            if cls.SETTINGS_PAGE_KEY:
                page = ttk.Frame(root)
                tab.settings_page(page)
                assert rt.game.asked == [], (
                    f"{spec.id}: settings_page() touched the game ({rt.game.asked})")
                page.destroy()

            # An EAGER tab is loaded AT BOOT, before anybody has opened anything —
            # so `ensure_loaded` must bring up what the tab is FOR (a capture that has
            # to be listening) and nothing that merely draws. A game read here is one
            # every profile pays at start-up for a tab it may never open; that read
            # belongs in `on_show`, which only fires when somebody is looking.
            if cls.EAGER:
                tab.ensure_loaded()
                assert rt.game.asked == [], (
                    f"{spec.id}: ensure_loaded() read the game ({rt.game.asked}) — an "
                    f"EAGER tab runs it at boot, so a read that only draws belongs in "
                    f"on_show()")

            # The lifecycle, in the order the shell and the harness both use it.
            tab.apply_config(rt.settings.tab_config(cls.ID, cls.LEGACY_KEYS))
            assert isinstance(tab.config(), dict), spec.id
            assert isinstance(tab.persist_vars(), list), spec.id
            tab.on_show()
            tab.on_hide()
            tab.on_language_change()
            tab.panic()
            tab.shutdown()

            assert rt.tick.armed() == 0, (
                f"{spec.id}: left {rt.tick.armed()} repeating callback(s) armed after "
                f"shutdown")
            assert rt.bus.topics() == {}, (
                f"{spec.id}: left bus subscriptions behind: {rt.bus.topics()}")
            frame.destroy()
            print(f"    · {spec.id}")
    finally:
        root.destroy()


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
