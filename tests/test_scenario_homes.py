r"""Every ability has a home on a themed tab — «Разработка» is never the only door.

The rule this file exists to hold (#1247). An ability is one `actions/*.md`
(`CLAUDE.md`), and the panel is what plays it — but WHERE it is played from decides
whether an ordinary player can reach it at all. The script list on «Разработка» is a
tool for working on the bot: it is `DEFAULT_ENABLED = False`, so on a panel nobody has
switched it on it does not exist. An ability whose only button is on that list is an
ability the game's player does not have.

So each shipped scenario must be NAMED somewhere a person can reach on purpose: a tab
under `panel/tabs/`, or the shell and the runtime it drives the client's lifecycle
from. It does not care whether that is a button, a row of a board or a switch — only
that «Разработка» is not the one place it lives.

**A timer and a trigger do not count as a home**, and that is the whole sharpness of
this test. `panel/timers.py` is «every half hour, by itself» and `panel/triggers.py` is
«when the game says so» — both are real ways an ability runs, and neither is a way to
say «сделай это сейчас». Three abilities sat exactly there when this was written
(#1247): the base's resource truck, the alliance gifts and the ministry application
were each in the timer catalogue and nowhere else, so a player who did not want them on
a clock had no way to press them at all. A test that accepted a schedule would have
called that finished.

**What this test cannot see**, and it is worth knowing before trusting it: it reads the
panel as TEXT. A press that is drawn nowhere still counts as a home — «Чеклист» keeps
three of its four groups switched off until their lines have been confirmed against a
live game (#1275, `docs/panel-tabs.md`), and the rows of an off group name their
scenarios exactly as before. That is accepted while the groups are coming back; a group
that is going to stay off has to give its abilities a press somewhere else.

Two kinds of file are not abilities and are skipped:

* **no DSL body.** A file with no statement in it presses nothing. There was one such
  file for a long time — `send_chat_message.md`, a page of documentation for
  `tools/chat_send.py`, on the grounds that a chat send is parameterised (who, what)
  and so could not be a fixed recipe. It is a recipe now (#1976): the parameters travel
  as `ARGS` and `CHAT_SEND` names the VARIABLES that hold them, which is what let the
  phone press a send at all. The skip stays because it is «no statements» and not a
  list of filenames.
* **`actions/dev/`.** Experimental by definition; the checkbox on «Разработка» is
  exactly where they belong until they are proven.

Pure text — no Tk, no game, no daemon. Runs under any python:

    python3 tests/test_scenario_homes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

ACTIONS = _REPO / "src" / "lastwar_bot" / "actions"
PANEL = _REPO / "panel"

#: Not homes. The script list on «Разработка» (off by default), and the two catalogues
#: that run an ability WITHOUT anybody asking — a period, and a push off the wire.
NOT_A_HOME = (
    PANEL / "tabs" / "develop.py",
    PANEL / "timers.py",
    PANEL / "triggers.py",
)

#: Runtime plumbing rather than an ability — the same list `panel/runtime/actions.py`
#: keeps the picker clean with. Named again rather than imported so this test runs with
#: no panel import at all (it must fail on a repository, not on an environment).
PLUMBING = frozenset({"watchdog"})

#: A shipped recipe that deliberately has no button, and why. «No home» has to be a
#: reason and not an oversight, which is the whole point of writing them down here.
EXEMPT = {
    # The generic form: eight posts, one commented `TAP` each, meant to be COPIED into
    # a recipe of your own. What the panel actually presses is the gated, schedulable
    # `apply_ministry_interior`, which is on «Чеклист» and in the timer catalogue.
    "submit_ministry": "a template to copy — apply_ministry_interior is the shipped press",
    # Nothing to press: it is what the panel plays when the SERVER kicks this session,
    # and the person it happens to is not at the machine. A button would be a way to
    # relog for no reason, which the client's own «Перезапустить» already is.
    "recover_from_kick": "a reaction to a kick, not something anybody presses",
    # One lap of ONE warzone: the body of the star round's loop, and a file of its own
    # only because a `{name}` is filled when a recipe is parsed and a sub-recipe is
    # parsed at every `CALL` (#1479). Pressing it alone would sweep warzone 0. What a
    # person presses is `sweep_star_servers`, on «Таймеры».
    "sweep_one_star_server": "the loop body of sweep_star_servers, never pressed alone",
    # The hunt the panel presses is `attack_golden_zombies`, with the squad as an
    # ARGUMENT («События» → «Золотые зомби»). These two are the same hunt written out:
    # one wired to the second squad, one generated by `tools/lib/golden_twin.py` to send
    # both at once. A button for each would be three buttons for one ability.
    "attack_golden_zombies2": "the same hunt wired to the second squad — the press is "
                              "attack_golden_zombies with a squad argument",
    "attack_golden_zombies_pair": "generated by tools/lib/golden_twin.py; the press is "
                                  "attack_golden_zombies",
    # A STANDING ORDER'S OWN PAIR, and its switch is the trigger's box. `watch_fireworks`
    # wraps one of the client's own functions so a firework's gift is taken the instant
    # the game hears about one; `unwatch_fireworks` takes the wrapper's ear off again.
    # Neither is a thing to press when a person feels like it — the box on the triggers
    # page is where a person says whether the watch is kept at all.
    "watch_fireworks": "the standing order itself — the trigger's box is its switch",
    "unwatch_fireworks": "the other half of watch_fireworks, played when it is unticked",
    "read_fireworks_watch": "the reading half of watch_fireworks — «События» draws it",
}


class _Skip(Exception):
    pass


# ---------------------------------------------------------------------------
# what counts as an ability
# ---------------------------------------------------------------------------
def _statements(path: Path) -> list:
    """The DSL lines of a recipe — everything that is not blank and not a comment."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            out.append(stripped)
    return out


def abilities() -> list:
    """Every shipped `actions/*.md` that actually presses something."""
    return sorted(path for path in ACTIONS.glob("*.md")
                  if path.stem not in PLUMBING and _statements(path))


def _panel_sources() -> list:
    """Every panel module a press can live in — see :data:`NOT_A_HOME` for the rest."""
    return [path for path in sorted(PANEL.rglob("*.py"))
            if path not in NOT_A_HOME and "__pycache__" not in path.parts]


def _homes(name: str) -> list:
    """The panel files that name ``name`` — as a quoted string, the way a press does."""
    needles = ('"%s"' % name, "'%s'" % name)
    out = []
    for path in _panel_sources():
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(needle in text for needle in needles):
            out.append(path.relative_to(_REPO).as_posix())
    return out


#: A tool that WRITES recipes, and therefore answers for them. `tools/lib/golden_twin.py`
#: generates the second squad's whole chain out of the first squad's — one file per step —
#: so those files are the tool's output rather than abilities anybody presses. Edit the
#: generator, run it, and the files follow; a button on each would be a button on a copy.
GENERATORS = ("tools/lib/golden_twin.py",)


def _generated(name: str) -> list:
    """The generators that write ``name``, if any — the other kind of home."""
    out = []
    for rel in GENERATORS:
        path = _REPO / rel
        if path.is_file() and name in path.read_text(encoding="utf-8", errors="replace"):
            out.append(rel)
    return out


def _callers(name: str) -> list:
    """The recipes that `CALL` ``name`` — its home, when it has one.

    A SUB-RECIPE IS NOT AN ABILITY. «Выбрать цель», «дождаться марша», «оценить убийство»
    are the steps of a hunt, in files of their own only because a `{name}` is filled when
    a recipe is parsed and a sub-recipe is parsed at every `CALL` (#1479). Pressing one
    alone does a fraction of a thing nobody wants a fraction of — so its home is the
    recipe that calls it, and the rule below asks for one rather than for a button.

    That is a RULE and not an exemption list on purpose: a chain written tomorrow gets
    the same answer with nothing to add here, and a sub-recipe whose only caller is
    deleted becomes homeless the moment it is — which is exactly when somebody should
    look at it.
    """
    import re

    out = []
    for path in ACTIONS.glob("*.md"):
        if path.stem == name:
            continue
        if re.search(r"^\s*CALL\s+%s\b" % re.escape(name),
                     path.read_text(encoding="utf-8"), re.M):
            out.append(path.stem)
    return out


# ---------------------------------------------------------------------------
# the rule
# ---------------------------------------------------------------------------
def test_there_are_abilities_to_check():
    """A glob that matched nothing would pass every test below in silence."""
    found = abilities()
    assert len(found) > 20, f"only {len(found)} action scripts found in {ACTIONS}"


def test_every_ability_is_reachable_without_the_develop_tab():
    homeless = []
    for path in abilities():
        name = path.stem
        if name in EXEMPT:
            continue
        if _homes(name) or _callers(name) or _generated(name):
            continue
        homeless.append(name)
    assert not homeless, (
        "these abilities can only be reached from the script list on «Разработка» (off "
        "by default) or from a schedule that runs them without being asked — give each "
        "a press on the tab its theme belongs to, or write the reason into EXEMPT: "
        + ", ".join(sorted(homeless)))


def test_the_three_that_moved_are_on_the_board():
    """#1247's own result, pinned: the truck, the gifts and the ministry are pressable.

    Named one by one rather than left to the sweep above, because the sweep would go on
    passing if somebody moved them back into the timer catalogue and deleted the rows —
    it only knows «somewhere», and this knows where.
    """
    model = (PANEL / "tabs" / "checklist" / "model.py").read_text(encoding="utf-8")
    for name in ("collect_truck_resources", "collect_alliance_gifts",
                 "apply_ministry_interior"):
        assert 'scenario="%s"' % name in model, f"{name} lost its row on «Чеклист»"


def test_an_exemption_names_a_scenario_that_exists():
    """An EXEMPT entry outliving its file would quietly excuse nothing for ever."""
    for name, reason in EXEMPT.items():
        assert (ACTIONS / f"{name}.md").is_file(), f"EXEMPT names a missing {name}.md"
        assert reason.strip(), f"EXEMPT[{name}] has no reason"


# ---------------------------------------------------------------------------
# the checklist's own half: a named scenario must be a real file
# ---------------------------------------------------------------------------
def test_every_scenario_the_checklist_names_is_a_real_file():
    """The board plays what it names — a typo there is a button that cannot work.

    Reads the catalogue as text rather than importing it: the model module is Tk-free,
    but its package's `__init__` is not, and this test must run under a python with no
    display.
    """
    model = (PANEL / "tabs" / "checklist" / "model.py").read_text(encoding="utf-8")
    named = set()
    for chunk in model.split('scenario="')[1:]:
        named.add(chunk.split('"', 1)[0])
    named.discard("")
    assert named, "no scenario= entries found in the checklist catalogue"
    missing = sorted(n for n in named if not (ACTIONS / f"{n}.md").is_file())
    assert not missing, f"the checklist names scenarios that do not exist: {missing}"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except _Skip as exc:
            print(f"  SKIP {test.__name__}: {exc}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
        except Exception as exc:                    # noqa: BLE001
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed or skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
