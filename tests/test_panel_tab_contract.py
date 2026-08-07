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
from panel.tabs.base import PanelTab  # noqa: E402


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
        # Same bargain for «does this tab draw the others' pages»: `build_order` answers
        # it before anything is imported, so the spec carries it and the class declares
        # it, and neither may drift from the other (#1237).
        assert cls.AGGREGATES_TABS == spec.aggregates, (
            f"{spec.id}: registry says aggregates={spec.aggregates}, class says "
            f"{cls.AGGREGATES_TABS}")
        # …and for «is this tab still being written» (#1273), which `resolve` has to
        # answer before a single module is imported. Declared in both places, so
        # neither may drift: a mark taken off the class and left in the registry is a
        # finished tab nobody can see.
        assert cls.IN_DEVELOPMENT == spec.in_development, (
            f"{spec.id}: registry says in_development={spec.in_development}, class "
            f"says {cls.IN_DEVELOPMENT}")


def test_the_aggregator_is_built_after_every_page_it_collects():
    """«Настройки» draws pages contributed by other tabs, so it must be built last.

    This is the one ordering the panel cannot get wrong loudly. `SettingsTab.build()`
    walks `rt.tabs.live` and asks each tab for its page; a contributor built AFTER it is
    simply not in that list, and its page is not drawn — no error, no log line, just a
    settings page with a section missing. That is how «Автосбор» disappeared: settings
    sits at order 40 and rally at 300, so the aggregator ran ninth-from-last and the
    squad list the auto-join spends was never on screen to be filled in (#1237).

    No tab contributes a page TODAY — «Автосбор» moved onto the «Ралли» tab itself, which
    is where it belongs — so the registry half of this is checked against a stand-in.
    The mechanism stays, and so does its guarantee: the next tab to want a settings page
    of its own must not have to discover this by losing one.
    """
    specs = tabsreg.resolve()
    order = [spec.id for spec in tabsreg.build_order(specs)]
    aggregators = [spec.id for spec in specs if spec.aggregates]
    assert aggregators, "no tab collects contributed settings pages any more"
    # Whatever else moves, an aggregator is filled after every ordinary tab.
    for agg in aggregators:
        plain = [s.id for s in specs if not s.aggregates]
        assert all(order.index(agg) > order.index(other) for other in plain), order

    # …and a contributor, wherever the registry would place it, is built before it.
    contributor = tabsreg.TabSpec("zz-contributor", "panel.tabs.stats", "StatsTab",
                                  order=999)
    mixed = tabsreg.build_order(list(specs) + [contributor])
    ids = [spec.id for spec in mixed]
    for agg in aggregators:
        assert ids.index(agg) > ids.index("zz-contributor"), ids

    # The tab BAR is untouched by all this: the aggregator keeps its place.
    assert [s.id for s in specs] == [s.id for s in tabsreg.resolve()], "resolve moved"


def test_no_tab_contributes_a_settings_page_without_declaring_the_key():
    """`settings_page()` and `SETTINGS_PAGE_KEY` are one thing said twice.

    A tab that draws a page without naming it is a page the aggregator never asks for;
    a tab that names one without drawing it is an empty sub-tab. Neither fails loudly,
    so they are pinned to each other here.
    """
    for spec in tabsreg.TABS:
        cls = spec.load()
        own = cls.settings_page is not PanelTab.settings_page
        assert own == bool(cls.SETTINGS_PAGE_KEY), (
            f"{spec.id}: SETTINGS_PAGE_KEY={cls.SETTINGS_PAGE_KEY!r} but "
            f"settings_page is {'overridden' if own else 'the default'}")


def test_the_registry_ids_are_unique_and_ordered():
    ids = [s.id for s in tabsreg.TABS]
    assert len(ids) == len(set(ids)), ids
    orders = [s.order for s in tabsreg.TABS]
    assert len(orders) == len(set(orders)), f"two tabs share an order: {orders}"


def test_resolve_defaults_to_the_default_enabled_set():
    got = [s.id for s in tabsreg.resolve()]
    assert got == [s.id for s in sorted(tabsreg.TABS, key=lambda s: s.order)
                   if s.default_enabled and not s.in_development], got


def test_develop_is_off_until_a_profile_asks_for_it():
    """«Develop» is the sniffers, and a panel whose owner has never reverse-engineered
    anything must not carry them (#1199).

    The test above derives what it expects FROM `default_enabled`, so it would pass just
    as happily if the flag flipped. This one names the tab: off in a fresh profile, off
    for a profile written before it existed, and on only when the profile says so.
    """
    every = [s.id for s in tabsreg.TABS]
    assert "develop" in tabsreg.BY_ID, "the tab left the registry"
    assert "develop" not in [s.id for s in tabsreg.resolve()], "on in a fresh profile"
    # A profile written before this tab existed: `develop` is in neither `enabled` nor
    # `known`, and the "a tab nobody has been offered appears" rule must not reach it.
    old = [s.id for s in tabsreg.resolve(enabled=["stats"], known=["stats"])]
    assert "develop" not in old, old
    # …and no `known` at all — the pre-`known` profile format — behaves the same.
    assert "develop" not in [s.id for s in tabsreg.resolve(enabled=["stats"])]
    # Ticking it in Settings is what puts it there, and that survives the round trip.
    on = [s.id for s in tabsreg.resolve(enabled=["stats", "develop"], known=every)]
    assert on == ["stats", "develop"], on


def test_a_tab_still_being_written_is_not_shown_without_development_mode():
    """The mark is a HIDE, and «Разработка» is the only thing that lifts it (#1273).

    A tab marked `in_development` must not reach an ordinary panel by any of the three
    doors `resolve` has: the fresh-profile defaults, a profile that names it in
    `enabled`, and the "a tab nobody has been offered appears" rule.
    """
    wip = [s.id for s in tabsreg.TABS if s.in_development]
    assert wip, "nothing is marked as still being written — did the marks go?"
    every = [s.id for s in tabsreg.TABS]

    fresh = [s.id for s in tabsreg.resolve()]
    assert not set(wip) & set(fresh), f"{sorted(set(wip) & set(fresh))} in a fresh panel"

    # A profile that ASKS for one — because it had it ticked before the mark went on —
    # still does not get it, and is not broken by asking: everything else it named is
    # built exactly as before.
    asked = [s.id for s in tabsreg.resolve(enabled=["timers", wip[0]], known=every)]
    assert asked == ["timers"], asked

    # …and the "never offered, so show it" rule does not smuggle one in either.
    old = [s.id for s in tabsreg.resolve(enabled=["timers"], known=["timers"])]
    assert not set(wip) & set(old), old


def test_development_mode_shows_them_and_is_develop_being_on():
    """The other direction: with «Разработка» ticked, the marked tabs are back.

    And what "development mode" MEANS is one thing in one place — the `develop` tab
    being among the chosen. No second switch, so there is nothing for the two to
    disagree about.
    """
    wip = [s.id for s in tabsreg.TABS if s.in_development]
    every = [s.id for s in tabsreg.TABS]

    assert not tabsreg.dev_mode(), "a fresh profile is not in development mode"
    assert tabsreg.dev_mode(enabled=["develop"], known=every)
    assert tabsreg.DEV_TAB == "develop"

    on = [s.id for s in tabsreg.resolve(enabled=every, known=every)]
    assert set(wip) <= set(on), f"{sorted(set(wip) - set(on))} still hidden"
    # …one of them alone, with the mode on, is exactly what the profile asked for.
    pair = [s.id for s in tabsreg.resolve(enabled=[wip[0], "develop"], known=every)]
    assert set(pair) == {wip[0], "develop"}, pair
    # …and a marked tab the profile switched OFF stays off in development mode too:
    # the gate hides, it does not tick.
    off = [s.id for s in tabsreg.resolve(enabled=["develop"], known=every)]
    assert off == ["develop"], off


def test_the_tabs_page_lists_what_a_profile_can_actually_have():
    """`listed()` is what «Настройки → Вкладки» offers a box for.

    A row for a tab that cannot appear whatever it says would be a control that does
    nothing; a missing row for one that CAN is a tab nobody can switch on.
    """
    wip = {s.id for s in tabsreg.TABS if s.in_development}
    every = [s.id for s in tabsreg.TABS]

    plain = {s.id for s in tabsreg.listed()}
    assert not plain & wip, sorted(plain & wip)
    assert "develop" in plain, "the way INTO development mode has to be on the page"

    full = {s.id for s in tabsreg.listed(enabled=["develop"], known=every)}
    assert full == set(every), sorted(set(every) - full)


def test_switching_a_tab_off_in_the_profile_leaves_it_out():
    """The whole point of the refactor, in one assertion: a tab the profile does not
    name is not resolved — so it is never built, contributes no settings page, and
    starts none of its captures or watchers."""
    every = [s.id for s in tabsreg.TABS]
    got = [s.id for s in tabsreg.resolve(enabled=["timers", "rally"], known=every)]
    assert got == ["timers", "rally"] or set(got) == {"timers", "rally"}, got
    # …and an EMPTY list is "none of them", not "the defaults" — an operator who wants
    # a panel with nothing but the log must be able to say so.
    assert [s.id for s in tabsreg.resolve(enabled=[], known=every)] == []
    # A tab the profile has never been offered still appears: `known` is what tells
    # "switched off" from "did not exist when this profile was written".
    fresh = [s.id for s in tabsreg.resolve(enabled=["timers"], known=["timers", "rally"])]
    assert "rally" not in fresh, fresh
    assert "secret_tasks" in fresh, fresh


def test_a_profile_naming_a_tab_that_no_longer_exists_is_survivable():
    """A profile written by a newer build must not break an older panel."""
    unknown = []
    got = [s.id for s in tabsreg.resolve(enabled=["timers", "a-tab-from-the-future"],
                                         on_unknown=unknown.append)]
    assert unknown == ["a-tab-from-the-future"], unknown
    assert "timers" in got, got
    # …and a tab the profile has never heard of still appears, at its own order.
    assert "rally" in got, got


def test_the_profile_order_wins_over_the_declared_one():
    got = [s.id for s in tabsreg.resolve(order=["rally", "timers"])]
    assert got[:2] == ["rally", "timers"], got


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


def test_every_tab_is_drawn_when_it_is_looked_at_not_when_the_page_is_made():
    """`LAZY` is the default and nothing opts out of it quietly (#1215).

    A tab that must exist before anybody looks at it may say so — but then it says WHY,
    beside the flag, exactly as the three tabs with no phone screen do. What may not
    happen is a tab drifting out of the rule without a word, because then a page is
    slow again and there is nothing in the diff to point at.
    """
    heavy = [spec.id for spec in tabsreg.TABS if not spec.load().LAZY]
    assert heavy == [], (
        f"{heavy} draw themselves when the page is made rather than when somebody "
        f"looks. That is allowed and it is a decision: write why beside `LAZY = False` "
        f"and name it here.")
    # EAGER is the other half of the same sentence: what it starts has to be running
    # before anybody clicks, so the container draws it at boot whatever LAZY says.
    assert any(spec.load().EAGER for spec in tabsreg.TABS), "no tab loads at boot"


def test_a_tab_nobody_opens_keeps_its_settings():
    """The failure `LAZY` could have caused, pinned: a save must not flatten a profile.

    `config()` reads widgets. A tab nobody has opened has none, so the container asks
    `stored_config()` instead — and an undrawn tab hands back exactly the block it was
    given. Get this wrong and a panel opened and closed without clicking anything
    writes a screenful of defaults over every tab's settings at once, which is the kind
    of loss nobody notices until the setting is needed.
    """
    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
    except Exception as exc:                                # noqa: BLE001
        _skip("no display", exc)
        return
    root.withdraw()
    try:
        for spec in tabsreg.TABS:
            cls = spec.load()
            # What this tab's own settings look like, taken from a drawn one so the
            # block is the real shape rather than something invented here.
            rt = fake_runtime.cold_runtime(root)
            rt.settings.register(cls.SETTINGS)
            drawn_frame = ttk.Frame(root)
            drawn = cls(rt, drawn_frame)
            drawn.realize()
            block = drawn.config()
            assert drawn.built, f"{spec.id}: realize() did not mark it drawn"
            drawn.shutdown()
            drawn_frame.destroy()

            rt = fake_runtime.cold_runtime(root)
            rt.settings.register(cls.SETTINGS)
            frame = ttk.Frame(root)
            tab = cls(rt, frame)
            tab.restore(block)
            assert not tab.built, f"{spec.id}: restore() drew the tab"
            assert not frame.winfo_children(), f"{spec.id}: __init__ drew widgets"
            assert tab.stored_config() == block, (
                f"{spec.id}: an unopened tab did not hand back the block it was given")
            # …and once somebody looks at it, the block is applied as part of drawing:
            # the tab must not come up on its defaults with the saved values lost.
            assert tab.realize() is True and tab.built, spec.id
            assert tab.realize() is False, f"{spec.id}: realize() is not idempotent"
            assert tab.stored_config() == tab.config(), spec.id
            tab.shutdown()
            frame.destroy()
            print(f"    · {spec.id}")
    finally:
        root.destroy()


def test_a_trigger_fires_into_a_tab_nobody_has_opened():
    """A tab's standing order is offered while the tab is in the profile — not while it
    is on screen. So its handler runs against an UNDRAWN tab and must survive that.

    Two do it today and both were already written this way: the resource tracker keeps
    tallying whether or not anybody is watching (its repaint is guarded), and the
    data tabs' `refresh_live` does nothing until the tab has been opened once. This is
    what stops the third one being written the other way.
    """
    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
    except Exception as exc:                                # noqa: BLE001
        _skip("no display", exc)
        return
    root.withdraw()
    try:
        seen = 0
        for spec in tabsreg.TABS:
            cls = spec.load()
            rt = fake_runtime.cold_runtime(root)
            rt.settings.register(cls.SETTINGS)
            frame = ttk.Frame(root)
            tab = cls(rt, frame)
            for trigger in getattr(cls, "TRIGGERS", ()):
                name = getattr(trigger, "handler", None)
                if not name:
                    continue
                seen += 1
                handler = getattr(tab, name, None)
                assert callable(handler), f"{spec.id}: no handler {name!r}"
                handler()                     # undrawn, cold game: must not raise
                assert not tab.built, (
                    f"{spec.id}: {name}() drew the tab — a push must not build a page "
                    f"nobody asked for, and it would do it off the Tk thread")
            frame.destroy()
        assert seen >= 2, f"only {seen} trigger handlers found — did the scan break?"
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
