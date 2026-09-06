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

import json
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
    assert "function useGear(" in web and "OrderItem" in web
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
    for setter in ("def set_join_squad(", "def set_join_number(", "def set_join_kind("):
        body = rally.split(setter, 1)[1].split("\n    def ", 1)[0]
        assert "self.remember(" in body, f"{setter} must save the block too"
    # …and the phone's own switch goes through that one setter rather than past it.
    assert "self.set_join_squad(squad, on)" in rally


def test_the_auto_join_carries_every_kind_of_banner_it_may_answer():
    """All sixty-eight kinds are knobs of `rally_auto_join` (#2017).

    Many for one window, and the person asked for them knowing that — «нужны,
    переключатели мы позже переделаем». Without them the page listing what runs by
    itself cannot say why a banner went unanswered: the filter was on «Ралли» alone.

    Stored as what is OFF, so a season that adds a boss is joined by default — a new
    kind must never arrive switched off for everybody.
    """
    import rally_kinds

    rally = (_REPO / "panel" / "tabs" / "rally" / "tab.py").read_text(encoding="utf-8")
    assert '"kind_%s" % kind' in rally
    assert '"rally_limit.type.%s" % kind' in rally
    body = rally.split("def set_join_kind(", 1)[1].split("\n    def ", 1)[0]
    assert '"kinds_off"' in body and "self.remember(" in body

    # …and every one of them has a name in every shipped locale, which is what makes
    # sixty-eight switches readable rather than sixty-eight keys.
    for locale in sorted((_REPO / "panel" / "locales").glob("*.json")):
        words = json.loads(locale.read_text(encoding="utf-8"))
        missing = [k for k in rally_kinds.KIND_ORDER
                   if "rally_limit.type.%s" % k not in words]
        assert not missing, f"{locale.name} lacks {missing[:3]}"


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
    import ast

    source = (_REPO / "panel" / "headless.py").read_text(encoding="utf-8")
    assert "rt.settings.on_change" in source
    # THE NAME IT CALLS MUST EXIST. This shipped once as a class that is not in the
    # file, and nothing said so: the saver is reached through a lambda, the NameError
    # surfaced as a knob answering «unknown», and every assertion about the text passed.
    tree = ast.parse(source)
    classes = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and node.attr == "_save_tab_blocks"):
            continue
        assert isinstance(node.value, ast.Name), "the saver is called off a class"
        assert node.value.id in classes, f"no class {node.value.id} in panel/headless.py"
    saver = source.split("def _save_tab_blocks", 1)[1]
    assert "set_tab_config" in saver and "rt.settings.save()" in saver
    # …and the registry's tab list is a PROPERTY. Called as one, it raised «'list'
    # object is not callable» inside the saver's own catch — so the write said «ok»,
    # the log said «save failed» and the profile kept the old value.
    assert "rt.tabs.live()" not in saver and "rt.tabs.live" in saver
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


# ---------------------------------------------------------------------------
# an errand's own ARGUMENTS (#2017)
# ---------------------------------------------------------------------------
class _Catalogue:
    """Just enough of a timer catalogue: rows by name, and one replaced."""

    def __init__(self, rows) -> None:
        self.rows = dict(rows)

    def by_name(self, name):
        return self.rows.get(name)

    def replace(self, timer):
        fresh = dict(self.rows)
        fresh[timer.name] = timer
        return _Catalogue(fresh)


class _Schedule:
    """A schedule that holds a catalogue and writes nowhere — the two calls the
    argument knobs make, and nothing else."""

    def __init__(self, args) -> None:
        import types
        self.written: list = []
        self.args = dict(args)
        self.rows = types.SimpleNamespace(name="do_radar_tasks", args=self.args)

    def timer_arg(self, errand, key, default=None):
        return self.args.get(key, default)

    def set_timer_arg(self, errand, key, value) -> bool:
        self.written.append((errand, key, value))
        self.args[key] = value
        return True


def test_an_errands_arguments_are_typed_knobs_not_raw_json():
    """The five shipped errands steered by `args` carry them as controls (#2017)."""
    from panel.runtime import errand_args

    sched = _Schedule({"claim": 1, "help": 0, "duel_day": 0, "keep_free": 5})
    options = {opt.key: opt for opt in
               errand_args.options_for(sched, "do_radar_tasks")}
    assert set(options) == {"claim", "help", "duel_day", "keep_free"}
    assert options["claim"].kind == errandopts.SWITCH
    assert options["claim"].read(None) is True, "1 draws as a ticked box"
    assert options["help"].read(None) is False

    # A switch is stored as the 0/1 the recipe reads, not as a bool: the DSL has no
    # booleans, and a `true` in the row would reach the scenario as a word.
    options["help"].write(None, True)
    assert sched.args["help"] == 1
    options["claim"].write(None, False)
    assert sched.args["claim"] == 0


def test_a_number_argument_is_held_inside_its_bounds_and_never_guessed():
    """A half-typed box must not become a 0 — «claim nothing», «walk no warzones»."""
    from panel.runtime import errand_args

    sched = _Schedule({"count": 6})
    count = errand_args.options_for(sched, "sweep_star_servers")[0]
    assert count.key == "count" and count.kind == errandopts.NUMBER
    count.write(None, "9")
    assert sched.args["count"] == 9
    count.write(None, "999")                 # above the bound → the bound
    assert sched.args["count"] == 20
    count.write(None, "")                    # a blank keeps what was there
    assert sched.args["count"] == 20
    count.write(None, "not a number")
    assert sched.args["count"] == 20


def test_a_list_of_weekdays_is_seven_switches_over_one_argument():
    """`duel_days` decides which days the radar spends SQUADS on — a text box on a
    phone is a value nobody can check before it is saved."""
    from panel.runtime import errand_args

    sched = _Schedule({"duel_days": [1, 3, 5, 6], "force": 0})
    options = {opt.key: opt for opt in
               errand_args.options_for(sched, "radar_full_cycle")}
    days = [k for k in options if k.startswith("duel_days_")]
    assert len(days) == 7
    assert options["duel_days_3"].read(None) is True
    assert options["duel_days_2"].read(None) is False

    options["duel_days_2"].write(None, True)
    assert sched.args["duel_days"] == [1, 2, 3, 5, 6], "sorted, and no duplicates"
    options["duel_days_1"].write(None, False)
    assert sched.args["duel_days"] == [2, 3, 5, 6]

    # …and the mode is a CHOICE whose words are locale keys resolved when DRAWN, so a
    # knob registered at boot still speaks the language switched on after it.
    force = options["force"]
    assert force.kind == errandopts.CHOICE
    said = force.choices(_Words())
    assert [c["value"] for c in said] == [0, 1, 2]
    assert said[0]["text"] == "said:errand.arg.radar.force.day"


class _Words:
    """A runtime that only knows how to say a key."""

    def t(self, key, **_fmt):
        return "said:" + key


def test_every_argument_knob_names_a_key_that_exists_everywhere():
    from panel.runtime import errand_args

    keys = set(errand_args.DAY_KEYS)
    for specs in errand_args.SPEC.values():
        for spec in specs:
            if spec.get("label"):
                keys.add(spec["label"])
            if spec.get("hint"):
                keys.add(spec["hint"])
            for _value, text_key in spec.get("choices", ()):
                keys.add(text_key)
    for locale in sorted((_REPO / "panel" / "locales").glob("*.json")):
        words = json.loads(locale.read_text(encoding="utf-8"))
        missing = sorted(k for k in keys if k not in words)
        assert not missing, f"{locale.name} lacks {missing[:3]}"


def test_a_knob_writes_the_row_of_a_tab_nobody_has_drawn():
    """The write must land in the file with «Таймеры» unbuilt — and it did not.

    `PanelTab.built` is a PROPERTY; the first version of this called it, so every
    argument knob answered «unknown» on a live panel while every test passed. The
    refusal now says why on the debug channel, and this exercises the path the live
    press takes rather than the source it is written in.
    """
    import os
    import types
    from panel import timers as timersmod
    from panel.tabs import timers as timerstab

    with tempfile.TemporaryDirectory() as home:
        path = os.path.join(home, "timers.json")
        # The SHIPPED list rather than the template: `sweep_star_servers` is one of
        # the rows a profile adopts, and the template is the starter set.
        timersmod.save_catalogue(timersmod.default_catalogue(), path)
        catalogue = timersmod.load_catalogue(path)
        rt = types.SimpleNamespace(
            schedule=types.SimpleNamespace(timer_catalogue=catalogue),
            profiles=types.SimpleNamespace(timers_json=lambda: path))

        tab = timerstab.TimersTab.__new__(timerstab.TimersTab)
        tab.rt = rt
        tab._drawn = False
        assert tab.write_args("sweep_star_servers", {"count": 9}) is True
        assert (timersmod.load_catalogue(path)
                .by_name("sweep_star_servers").args["count"] == 9)
        # …and the schedule is holding what was written, not the catalogue it had.
        assert rt.schedule.timer_catalogue.by_name(
            "sweep_star_servers").args["count"] == 9


def test_the_schedule_registers_the_argument_knobs_itself():
    """Not the «Таймеры» tab: a profile with that tab off still runs the errands, and
    its phone still gets the timers screen (#2010's lesson, in a new place)."""
    source = (_REPO / "panel" / "runtime"
              / "schedule.py").read_text(encoding="utf-8")
    assert "errandargs.register(self)" in source
    assert "def set_timer_arg(" in source
    # …and the write goes through the tab when there IS one, or the row is undone by
    # the tab's next save.
    body = source.split("def set_timer_arg(", 1)[1].split("\n    def ", 1)[0]
    assert 'getattr(tab, "write_args"' in body
    timers = (_REPO / "panel" / "tabs" / "timers.py").read_text(encoding="utf-8")
    assert "def write_args(" in timers


def test_the_schedule_asks_every_tab_for_its_knobs():
    """A gear on «Таймеры» must work for a page nobody has opened (`LAZY`).

    Behaviour rather than a grep of the source: the first version of this test read
    `register()` for the two calls by name, and went red the moment they moved into a
    method of their own — while a `register()` that silently registered nothing would
    have passed it (#2020).
    """
    import types
    from panel.runtime.schedule import Schedule

    base = (_REPO / "panel" / "tabs" / "base.py").read_text(encoding="utf-8")
    assert "def errand_options(self)" in base and "def standing_orders(self)" in base

    sched = Schedule.__new__(Schedule)
    sched.options = errandopts.ErrandOptions(None)
    sched._handlers, sched._needs_game = {}, set()
    var = _Var("30")
    sched.register(types.SimpleNamespace(
        TRIGGERS=(),
        errand_options=lambda: {"collect": (
            errandopts.Option("level_min", "secret.autoloot.level_min",
                              errandopts.TEXT, get=var.get, set=var.set),)},
        standing_orders=lambda: (_order(_Var(False)),)))
    assert sched.options.has("collect")
    assert [o.name for o in sched.options.orders()] == ["secret_autoloot"]


def test_a_tab_that_declares_no_knobs_still_registers():
    """A caller with neither method is the ordinary case, not a fault.

    This is the fault #2020 found: the guard around the two calls ended in
    `self._dbg(...)`, and `_dbg` is a LOGGER. So every tab that was not a full
    `PanelTab` — and every `Schedule` built without the registry — took the whole
    registration down with a `TypeError`, which is to say the panel's entire schedule,
    with no window anywhere to say so.
    """
    import types
    from panel.runtime.schedule import Schedule

    sched = Schedule.__new__(Schedule)
    sched.options = errandopts.ErrandOptions(None)
    sched._handlers, sched._needs_game = {}, set()

    class _Tab:
        TRIGGERS = (types.SimpleNamespace(name="t1", handler="go", needs_game=False),)

        def go(self):
            return None

    tab = _Tab()
    sched.register(tab)                       # no errand_options, no standing_orders
    assert sched._handlers["t1"] == tab.go

    # …and a Schedule with no registry at all (a probe) is not a crash either.
    bare = Schedule.__new__(Schedule)
    bare._handlers, bare._needs_game = {}, set()
    bare.register(tab)
    assert bare._handlers["t1"] == tab.go

    # …nor is a tab whose own declaration throws: it costs that tab's knobs and
    # nothing else. `_dbg` is a logger here, exactly as it is on a live panel.
    import logging
    loud = Schedule.__new__(Schedule)
    loud.options = errandopts.ErrandOptions(None)
    loud._handlers, loud._needs_game = {}, set()
    loud._dbg = logging.getLogger("test.schedule")

    def _boom():
        raise RuntimeError("no")

    loud.register(types.SimpleNamespace(TRIGGERS=_Tab.TRIGGERS, go=lambda: None,
                                        errand_options=_boom))
    assert loud._handlers["t1"] is not None


def _undrawn_card(saved, *, refuses=False):
    """A `LAZY` tab whose state is made in `apply_config`, handed a block and NOT drawn.

    The shape of every card behind a gear: an attribute per knob, restored from the
    profile's block. `panel/tabs/events/tab.py` is the live one.
    """
    import types

    from panel.tabs import base as basemod

    said = []

    class _Card(basemod.PanelTab):
        ID = "cardtest"
        LAZY = True

        def __init__(self, rt, parent) -> None:
            super().__init__(rt, parent)
            self.tickets = 0
            self.carriage = 1
            self.draws = 0

        def build(self) -> None:
            self.draws += 1

        def config(self) -> dict:
            return {"tickets": self.tickets, "carriage": self.carriage}

        def apply_config(self, raw) -> None:
            if refuses:
                raise RuntimeError("this one only exists after build()")
            raw = raw if isinstance(raw, dict) else {}
            self.tickets = int(raw.get("tickets", 0))
            self.carriage = int(raw.get("carriage", 1))

    logger = types.SimpleNamespace(warning=lambda *a, **k: said.append(a))
    rt = types.SimpleNamespace(dbg=lambda _c="panel": logger)
    tab = _Card(rt, None)
    tab.restore(saved)
    return tab, said


def test_a_knob_of_a_tab_nobody_opened_reads_the_saved_value_and_not_the_default():
    """The state arrives with the BLOCK, not with the drawing (#2063).

    Live: `train_tickets` was `1` in `panel.db` and the gear on «Таймеры» drew `0`,
    because the tab that owns it had never been looked at and its attributes were still
    the ones `__init__` gave them. A knob is a VIEW of the owner's value, so a view of
    a default is a second answer to the one question the register exists to have one
    answer to.
    """
    tab, _said = _undrawn_card({"tickets": 3, "carriage": 2})
    assert tab.tickets == 3 and tab.carriage == 2, \
        "an undrawn tab must hold what the profile says, not what __init__ guessed"
    knob = errandopts.Option("tickets", "x", errandopts.NUMBER,
                             get=lambda: tab.tickets, set=lambda v: None)
    assert knob.read(None) == 3


def test_the_saved_block_reaches_an_undrawn_tab_without_drawing_it():
    """…and `LAZY` is untouched by that (#1215).

    A page used to draw fifteen tabs so that one could be read, and the cure was to
    wait for a look. Applying a block is not a look: nothing here builds, and the
    promise that a tab nobody opened costs nothing has to survive the fix.
    """
    tab, _said = _undrawn_card({"tickets": 3})
    assert tab.built is False, "restoring a block must not mark the tab as drawn"
    assert tab.draws == 0, "restoring a block must not build anything"


def test_a_neighbour_knob_does_not_write_the_default_over_the_restored_one():
    """The second symptom the person reported: «сбрасываются на предыдущие».

    A card saves all of its knobs together (`_train_knob_saved`), so while the others
    read defaults, moving ONE of them wrote the defaults of the rest into the profile.
    """
    tab, _said = _undrawn_card({"tickets": 3, "carriage": 2})
    tab.carriage = 4                        # the neighbour a person just moved
    tab.remember({"tickets": tab.tickets, "carriage": tab.carriage})
    assert tab.stored_config()["tickets"] == 3, \
        "moving one knob must not write another's default down"
    assert tab.stored_config()["carriage"] == 4


def test_a_tab_that_cannot_take_its_block_undrawn_is_said_and_never_a_crash():
    """One tab's `apply_config` reaching for a widget must not take the boot with it.

    It is SAID, because the knobs of that tab go on reading defaults and the log is
    the only way anybody finds out which tab it is — and `realize` applies the same
    block again the moment somebody opens it.
    """
    tab, said = _undrawn_card({"tickets": 3}, refuses=True)
    assert tab.tickets == 0, "the refusing tab keeps its defaults"
    assert said, "a refused block must be said on the debug channel"


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
