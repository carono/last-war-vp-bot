r"""The knobs an errand carries, and where they really live (#2017).

A standing order is never only a switch: «Автолут ★» spends the day's five robberies at
whatever minimum level it was told, and the rally auto-join sends whichever of the four
squads it was allowed. Until now every one of those knobs lived on the page holding the
LIST the order spends — so «Таймеры», the one tab that says what runs by itself, showed
a name, a box, and nothing that decides what the box DOES.

`panel/runtime/errand_options.py` is the one place that says which knobs an errand has.
It is a VIEW of the owner's value and never a copy of it, and that is the whole of what
can go wrong here:

* a knob must write where its owner's own page writes — otherwise the gear and the page
  are two answers to one question, and the first time they disagree the panel is lying;
* a half-typed box must never become a 0 — for «минимальный уровень» a 0 is not «no
  bound», it is every tile on the map (#1256);
* an unknown errand or an unknown key must be REFUSED rather than guessed at;
* and one knob that throws must not take the panel with it.

No Tk, no game, no network — the web harness's stand-in runtime and plain objects::

    python3 tests/test_panel_errand_options.py
"""
from __future__ import annotations

TIER = "offline"        # see tools/run_tests.py

import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "tests", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime import errand_options as errandopts    # noqa: E402

import test_panel_web as webtest                          # noqa: E402


class _Var:
    """A stand-in for the owner's variable — what a knob actually writes."""

    def __init__(self, value=None) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


def _api(home: str):
    """The web harness's runtime and API, with an empty register of knobs."""
    return webtest._api(home)


# ---------------------------------------------------------------------------
# one knob
# ---------------------------------------------------------------------------
def test_a_knob_reads_and_writes_the_owners_own_variable():
    var = _Var("30")
    opt = errandopts.Option("level_min", "secret.autoloot.level_min",
                            errandopts.TEXT, get=var.get, set=var.set)
    assert opt.read(None) == "30"
    assert opt.write(None, "45") is True
    assert var.value == "45", "the knob must move the owner's own value, not a copy"


def test_a_blank_box_is_never_a_zero():
    """«No bound» and «level 0» are opposite orders — see #1256."""
    var = _Var("30")
    opt = errandopts.Option("level_min", "secret.autoloot.level_min",
                            errandopts.TEXT, get=var.get, set=var.set)
    opt.write(None, "")
    assert var.value == "", var.value
    opt.write(None, None)
    assert var.value == "", var.value


def test_a_switch_is_a_bool_whatever_the_wire_said():
    var = _Var(False)
    opt = errandopts.Option("squad_1", "autorally.squad", errandopts.SWITCH,
                            get=var.get, set=var.set)
    for said in ("on", "1", "true", "YES", True):
        var.value = None
        opt.write(None, said)
        assert var.value is True, said
    for said in ("off", "0", "", False, None):
        var.value = None
        opt.write(None, said)
        assert var.value is False, said


def test_a_knob_that_throws_is_a_reading_and_never_a_crash():
    def boom(*_a):
        raise RuntimeError("the owner is half-built")

    opt = errandopts.Option("x", "timers.options", errandopts.TEXT,
                            get=boom, set=boom)
    assert opt.read(None) == ""
    assert opt.write(None, "7") is False


def test_a_knob_says_how_it_is_drawn():
    opt = errandopts.Option("min_soldiers", "rally_troops.min", errandopts.NUMBER,
                            get=lambda: 100, set=lambda v: None,
                            low=0, high=999, hint_key="rally_troops.hint")
    field = opt.as_field(None)
    assert field["key"] == "min_soldiers"
    assert field["label"] == "rally_troops.min"
    assert field["kind"] == errandopts.NUMBER
    assert field["value"] == 100
    assert field["min"] == 0 and field["max"] == 999
    assert field["hint"] == "rally_troops.hint"

    # …and the four squads are ONE key with a number in it, never four strings saying
    # the same thing in eleven files.
    squad = errandopts.Option("squad_2", "autorally.squad", errandopts.SWITCH,
                              label_fmt={"n": 2}, get=lambda: True,
                              set=lambda v: None)
    assert squad.as_field(None)["label_fmt"] == {"n": 2}


def test_a_settings_knob_is_written_where_settings_live():
    """A knob that was ALREADY a profile setting keeps living there (#2017)."""
    with tempfile.TemporaryDirectory() as home:
        rt, _ = _api(home)
        rt.settings.defaults["autoassist_star_wait_min"] = 30
        opt = errandopts.Option("autoassist_star_wait_min", "autoassist.star_wait",
                                errandopts.NUMBER, setting="autoassist_star_wait_min",
                                low=0, high=1440)
        assert opt.read(rt) == 30
        assert opt.write(rt, "45") is True
        assert rt.settings.values["autoassist_star_wait_min"] == 45


# ---------------------------------------------------------------------------
# the register
# ---------------------------------------------------------------------------
def _register(rt, var):
    opts = errandopts.ErrandOptions(rt)
    opts.register("secret_autoloot", (
        errandopts.Option("level_min", "secret.autoloot.level_min",
                          errandopts.TEXT, get=var.get, set=var.set),))
    return opts


def test_the_register_answers_for_the_errand_it_was_given_and_no_other():
    var = _Var("30")
    opts = _register(None, var)
    assert opts.has("secret_autoloot") is True
    assert opts.has("collect") is False
    assert opts.fields("collect") == []
    assert [f["key"] for f in opts.fields("secret_autoloot")] == ["level_min"]


def test_an_unknown_errand_or_key_is_refused_rather_than_guessed_at():
    var = _Var("30")
    opts = _register(None, var)
    assert opts.write("secret_autoloot", "nothing", "9") is False
    assert opts.write("nobody", "level_min", "9") is False
    assert var.value == "30", "a refused press must move nothing"
    assert opts.write("secret_autoloot", "level_min", "9") is True
    assert var.value == "9"


def test_a_tab_that_goes_away_takes_its_knobs_with_it():
    var = _Var("30")
    opts = _register(None, var)
    opts.forget("secret_autoloot")
    assert opts.has("secret_autoloot") is False


# ---------------------------------------------------------------------------
# a standing order that is in no catalogue
# ---------------------------------------------------------------------------
def _order(var, state="жду звезду"):
    return errandopts.Order("secret_autoloot", "secret.autoloot",
                            get=var.get, set=var.set, state=lambda: state)


def test_an_order_is_its_owners_switch_and_its_owners_words():
    var = _Var(False)
    order = _order(var)
    assert order.enabled() is False
    assert order.set_enabled(True) is True
    assert var.value is True, "ticking the order must tick the owner's own box"
    assert order.state_text() == "жду звезду"


def test_an_order_whose_owner_throws_is_off_rather_than_a_crash():
    def boom(*_a):
        raise RuntimeError("half-built")

    order = errandopts.Order("x", "secret.autoloot", get=boom, set=boom, state=boom)
    assert order.enabled() is False
    assert order.set_enabled(True) is False
    assert order.state_text() == ""

    # …and an order with nothing to say says nothing, rather than «None».
    quiet = errandopts.Order("q", "secret.autoloot",
                             get=lambda: True, set=lambda v: None)
    assert quiet.state_text() == ""


def test_the_orders_come_back_in_the_order_they_were_registered():
    opts = errandopts.ErrandOptions(None)
    for name in ("a", "b", "c"):
        opts.register_order(errandopts.Order(name, "secret.autoloot",
                                             get=lambda: False, set=lambda v: None))
    assert [o.name for o in opts.orders()] == ["a", "b", "c"]
    assert opts.order("b") is not None and opts.order("zz") is None


# ---------------------------------------------------------------------------
# the phone
# ---------------------------------------------------------------------------
def test_every_errand_the_phone_lists_carries_its_own_knobs():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        var = _Var("30")
        rt.schedule.options.register("collect", (
            errandopts.Option("level_min", "secret.autoloot.level_min",
                              errandopts.TEXT, get=var.get, set=var.set),))
        rows = {row["name"]: row for row in api.timers()["timers"]}
        assert [f["key"] for f in rows["collect"]["options"]] == ["level_min"]
        assert rows["upkeep"]["options"] == [], "a row with no knobs draws no gear"


def test_the_standing_orders_travel_beside_the_listeners():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        var, level = _Var(False), _Var("30")
        rt.schedule.options.register_order(_order(var))
        rt.schedule.options.register("secret_autoloot", (
            errandopts.Option("level_min", "secret.autoloot.level_min",
                              errandopts.TEXT, get=level.get, set=level.set),))
        # The stand-in schedule has no catalogue of listeners — this file is about the
        # orders that are in NO catalogue, so an empty one is exactly right.
        rt.schedule.trigger_catalogue = ()
        rt.schedule.triggers = type("_Ears", (), {"watching": lambda self: ()})()
        answer = api.triggers()
        assert "orders" in answer, "the phone draws them among the listeners"
        order = answer["orders"][0]
        assert order["name"] == "secret_autoloot"
        assert order["enabled"] is False
        assert order["state"] == "жду звезду"
        assert [f["key"] for f in order["options"]] == ["level_min"]


def test_a_press_off_the_phone_moves_the_owners_value():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        var = _Var("30")
        rt.schedule.options.register("collect", (
            errandopts.Option("level_min", "secret.autoloot.level_min",
                              errandopts.TEXT, get=var.get, set=var.set),))
        status, answer = api.dispatch("POST", "/api/errand/option", {}, {
            "errand": "collect", "key": "level_min", "value": "45"})
        assert status == 200 and answer.get("ok") is True, answer
        assert var.value == "45"

        # …and a press naming something nobody declared is answered, never obeyed.
        status, answer = api.dispatch("POST", "/api/errand/option", {}, {
            "errand": "collect", "key": "nothing", "value": "1"})
        assert answer.get("error") == "unknown", answer
        status, answer = api.dispatch("POST", "/api/errand/option", {}, {
            "errand": "nobody", "key": "level_min", "value": "1"})
        assert answer.get("error") == "unknown", answer
        assert var.value == "45"
        # And asking never pressed the game.
        assert rt.game.claimed == [], rt.game.claimed


def test_a_standing_order_is_switched_from_the_phone_too():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        var = _Var(False)
        rt.schedule.options.register_order(_order(var))
        status, answer = api.dispatch("POST", "/api/orders/set", {}, {
            "name": "secret_autoloot", "enabled": True})
        assert status == 200 and answer.get("ok") is True, answer
        assert var.value is True
        status, answer = api.dispatch("POST", "/api/orders/set", {}, {
            "name": "nobody", "enabled": True})
        assert answer.get("error") == "unknown", answer


# ---------------------------------------------------------------------------
# both front-ends, and the owners
# ---------------------------------------------------------------------------
def test_the_window_draws_the_gear_and_the_orders_too():
    """An edit travels both ways: the gear is on the phone AND in the window."""
    source = (_REPO / "panel" / "tabs" / "timers.py").read_text(encoding="utf-8")
    assert "errand_gear" in source, "the window must open a knob window too"
    assert "_order_cell" in source, "the orders are drawn among the listeners"
    assert source.count("GEAR_GLYPH") >= 4, "a timer, a listener and an order each"

    web = (_REPO / "panel" / "web" / "app" / "src" / "views"
           / "TimersView.tsx").read_text(encoding="utf-8")
    assert "function Gear(" in web and "OrderItem" in web
    assert "/api/errand/option" in web and "/api/orders/set" in web


def test_the_knobs_are_declared_by_whoever_owns_the_value():
    """A tab declares them; nothing under `panel/runtime/` knows one errand's names."""
    registry = (_REPO / "panel" / "runtime"
                / "errand_options.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in registry.splitlines()
                     if not line.lstrip().startswith("#"))
    for owned in ("autoloot", "rally_auto_join", "ghost_", "squad_",
                  "panel.tabs", "from ..tabs"):
        assert owned not in code.split('"""')[-1], \
            f"the register must not know «{owned}» — the owning tab declares it"

    for tab, names in ((_REPO / "panel" / "tabs" / "secret_tasks" / "tab.py",
                        ("standing_orders", "errand_options", "ghost_autoloot")),
                       (_REPO / "panel" / "tabs" / "rally" / "tab.py",
                        ("errand_options", "AUTOJOIN_TRIGGER", "set_join_squad"))):
        source = tab.read_text(encoding="utf-8")
        for name in names:
            assert name in source, f"{tab.name} must declare {name}"


def test_a_knob_moved_from_anywhere_is_saved_where_an_unbuilt_tab_will_find_it():
    """One setter per value — the gear, the tab's page and the phone all call it.

    A write that moved the widget alone is gone at the next restart: an unbuilt tab
    hands its SAVED block back on save (#2010), so every setter has to `remember` too.
    """
    secret = (_REPO / "panel" / "tabs" / "secret_tasks"
              / "tab.py").read_text(encoding="utf-8")
    for setter in ("def set_autoloot(", "def set_autoassist(", "def set_ghost_autoloot(",
                   "def set_autoloot_level(", "def set_assist_level(",
                   "def set_ghost_level("):
        body = secret.split(setter, 1)[1].split("\n    def ", 1)[0]
        assert "self.remember(" in body, f"{setter} must save the block too"

    rally = (_REPO / "panel" / "tabs" / "rally" / "tab.py").read_text(encoding="utf-8")
    for setter in ("def set_join_squad(", "def set_join_number("):
        body = rally.split(setter, 1)[1].split("\n    def ", 1)[0]
        assert "self.remember(" in body, f"{setter} must save the block too"
    # …and the phone's own switch goes through that one setter rather than past it.
    assert "self.set_join_squad(squad, on)" in rally


def test_the_sweep_left_no_errand_with_its_rules_off_its_row():
    """Every errand whose rules lived on somebody's page declares them here (#2017).

    The person asked for the whole list, not for the two the task was named after: the
    piece exchange's rules were on «Кусочки», the train's three knobs on «События», and
    both errands' rows on «Таймеры» said a name and nothing else.
    """
    secret = (_REPO / "panel" / "tabs" / "secret_tasks"
              / "tab.py").read_text(encoding="utf-8")
    assert '"exchange_treasure_pieces": (' in secret
    assert "def set_pieces_option(" in secret
    body = secret.split("def set_pieces_option(", 1)[1].split("\n    def ", 1)[0]
    assert "self.remember(" in body, "a rule moved from the phone must survive a restart"
    # …and the day's five, which was a profile setting nowhere near the order.
    assert '"autoloot_limit", "opt.autoloot_limit"' in secret

    events = (_REPO / "panel" / "tabs" / "events" / "tab.py").read_text(encoding="utf-8")
    assert '"alliance_train_board": (' in events
    assert "def set_train_option(" in events
    # ONE PATH: the gear presses the card's own handler rather than a second copy of it.
    assert 'self.web_press("set"' in events
    # …and the card's own press saves too, which is the hole #2010 found.
    assert "_train_knob_saved" in events


def test_a_panel_with_no_window_writes_a_moved_knob_down():
    """`settings.changed()` reaches a saver in a headless panel too (#2017).

    It is how every tab says «this belongs to the profile now», and it does nothing at
    all until a container answers it. The window has answered since it had tabs; a
    machine with no window had nobody, so a knob moved from the phone was gone at the
    next restart — the hole #2010 found in one tab, in all of them.
    """
    source = (_REPO / "panel" / "headless.py").read_text(encoding="utf-8")
    assert "rt.settings.on_change" in source
    saver = source.split("def _save_tab_blocks", 1)[1]
    assert "set_tab_config" in saver and "rt.settings.save()" in saver
    # …and only the tabs' blocks: a headless panel writing `tabs.enabled` off a list it
    # did not build is how a tab somebody switched off comes back.
    assert "enabled" not in saver.split("def ", 1)[0]


def test_a_panel_with_no_window_registers_its_tabs_too():
    """The gear must work on the front-end that actually runs (#2017).

    `panel.headless` is what a machine with no window runs, and it never made the call
    the window makes — so every gear was empty there, and every trigger a tab binds a
    handler to was listening to nothing.
    """
    source = (_REPO / "panel" / "headless.py").read_text(encoding="utf-8")
    where = source.split("def _build_tabs", 1)[1]
    assert "rt.schedule.register(tab)" in where


def test_the_schedule_asks_every_tab_for_its_knobs():
    """A gear on «Таймеры» must work for a page nobody has opened (`LAZY`)."""
    source = (_REPO / "panel" / "runtime" / "schedule.py").read_text(encoding="utf-8")
    where = source.split("    def register(self, tab)", 1)[1]
    assert "tab.errand_options()" in where and "tab.standing_orders()" in where
    base = (_REPO / "panel" / "tabs" / "base.py").read_text(encoding="utf-8")
    assert "def errand_options(self)" in base and "def standing_orders(self)" in base


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
        except Exception as exc:      # noqa: BLE001 — a raise is a failure too
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
