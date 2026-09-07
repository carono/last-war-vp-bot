r"""The «Кодовое имя» record modal, shut in a real Lua VM — task #2604.

The game answers a hit on the event's boss with a modal of its own — «Текущий урон»
over one «Подтвердить» — and it does not arrive with the send: the squad flies to the
boss first, so the window opens minutes after the recipe has ended. The ability is
therefore an EAR (`lua_actions.codename_shut_install`), and the one thing that must
never happen — a window shut that somebody was reading — cannot be proven by reading
the chunk, so it is run here against a stand-in client.

What is pinned:

  * a listed window opening inside the deadline IS shut, through `Ctrl:CloseSelf`;
  * the same window opening after the deadline is LEFT OPEN and merely written down —
    outside our own attack the modal belongs to whoever is playing by hand;
  * a window that is not on the list is never touched, whatever else is true;
  * the event's own screens a person reads («История Боев», the rank, the rewards) are
    not on the list, and neither is the HUD;
  * the install is idempotent, chains onto an ear that is already there, and does not
    change what `OpenWindow` gives its caller back;
  * `DestroyAllWindow` is never spelled anywhere in the chunk.

    C:\Python312\python.exe tests\test_codename_shut.py
    python3 tests/test_codename_shut.py            # lupa is enough
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "tools", ROOT / "tools" / "lib", ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lua_actions  # noqa: E402

try:
    import lupa                                     # noqa: E402
except ImportError:                                 # pragma: no cover - optional
    lupa = None

#: Where the two names came from: a live scan of the client's own `UIWindowNames`
#: (#2604), written up beside the event's research. The older dump in
#: `ui-open-data/ui_window_names.json` is 2 221 names against the 2 235 the live client
#: now has, and neither of these two is in it — so the research file is what this test
#: reads, and a name invented in code without evidence fails here.
RESEARCH = ROOT / "docs" / "research" / "codename-event.md"

#: Screens of this very event that a PERSON reads, plus the HUD. None may ever be on the
#: list: closing one is the panel taking the game away from whoever is playing it.
NEVER = (
    "LWUIWorldBossRecord", "LWUIWorldBossRank", "UIWorldBossRank",
    "LWUIWorldBossReward", "LWUIWorldBossTask", "UIMain",
)

#: A round «now» in the game's own milliseconds, so the deadline is arithmetic rather
#: than whatever the clock says.
NOW_MS = 1788_780_000_000

#: As much of the client as the wrapper touches: a UI manager whose class carries
#: `OpenWindow` and `GetWindow`, the clock, and a timer that fires at once.
_CLIENT = """
NOW = 0
UITimeManager = { GetInstance = function(self)
  return { GetServerTime = function(self) return NOW end } end }

OPENED, CLOSED, GAVE = {}, {}, {}

local uiclass = {}
uiclass.OpenWindow = function(self, name, ...)
  OPENED[#OPENED + 1] = tostring(name)
  return 'window:' .. tostring(name), 'second'
end
uiclass.GetWindow = function(self, name)
  return { Ctrl = { CloseSelf = function(ctrl)
    CLOSED[#CLOSED + 1] = tostring(name)
  end } }
end
UIManager = { Instance = setmetatable({}, {__index = uiclass}) }

TimerManager = { GetInstance = function(self)
  return { DelayInvoke = function(self, fn, _sec) fn() end } end }

DataCenter = {}
"""


def _vm():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_CLIENT)
    return lua


def _open(lua, name):
    lua.execute("A, B = UIManager.Instance:OpenWindow('%s')" % name)
    return lua.eval("A"), lua.eval("B")


def _arm(lua, minutes=None):
    chunk = (lua_actions.codename_shut_install() if minutes is None
             else lua_actions.codename_shut_install(minutes))
    lua.execute(chunk)


def _rows(lua):
    return list(lua.eval("DataCenter.__lw_cnshut.rows").values())


def test_shuts_the_record_modal_inside_the_deadline():
    lua = _vm()
    lua.execute("NOW = %d" % NOW_MS)
    _arm(lua)
    lua.execute("NOW = %d" % (NOW_MS + 5 * 60 * 1000))     # the march is still flying
    _open(lua, "UIBossDamageTip")
    assert list(lua.eval("CLOSED").values()) == ["UIBossDamageTip"]
    assert _rows(lua) == ["closed|UIBossDamageTip"]
    assert lua.eval("DataCenter.__lw_cnshut.closed") == 1


def test_leaves_the_modal_alone_once_the_deadline_has_passed():
    lua = _vm()
    lua.execute("NOW = %d" % NOW_MS)
    _arm(lua)
    lua.execute("NOW = %d" % (NOW_MS + 31 * 60 * 1000))    # somebody is playing by hand
    _open(lua, "UIBossDamageTip")
    assert list(lua.eval("CLOSED").values()) == []
    assert _rows(lua) == ["left|UIBossDamageTip"]


def test_never_touches_a_window_that_is_not_on_the_list():
    lua = _vm()
    lua.execute("NOW = %d" % NOW_MS)
    _arm(lua)
    for name in NEVER:
        _open(lua, name)
    assert list(lua.eval("CLOSED").values()) == []
    assert _rows(lua) == []
    assert lua.eval("DataCenter.__lw_cnshut.seen") == 0


def test_the_caller_still_gets_everything_openwindow_returned():
    lua = _vm()
    lua.execute("NOW = %d" % NOW_MS)
    _arm(lua)
    first, second = _open(lua, "UIBossDamageTip")
    assert first == "window:UIBossDamageTip"
    assert second == "second"


def test_the_install_is_idempotent_and_chains_onto_an_ear_already_there():
    lua = _vm()
    lua.execute("NOW = %d" % NOW_MS)
    # somebody else's ear first — the reward one does exactly this rawset
    lua.execute("""
      local mgr = UIManager.Instance
      local orig = getmetatable(mgr).__index.OpenWindow
      HEARD = {}
      rawset(mgr, 'OpenWindow', function(self, name, ...)
        HEARD[#HEARD + 1] = tostring(name) return orig(self, name, ...) end)
    """)
    _arm(lua)
    lua.execute("WRAPPER = rawget(UIManager.Instance, 'OpenWindow')")
    _arm(lua)                                            # a second attack re-arms
    assert lua.eval("rawget(UIManager.Instance, 'OpenWindow') == WRAPPER") is True
    _open(lua, "UIBossDamageTip")
    assert list(lua.eval("HEARD").values()) == ["UIBossDamageTip"]
    assert list(lua.eval("CLOSED").values()) == ["UIBossDamageTip"]


def test_re_arming_moves_the_deadline_forward():
    lua = _vm()
    lua.execute("NOW = %d" % NOW_MS)
    _arm(lua)
    lua.execute("NOW = %d" % (NOW_MS + 29 * 60 * 1000))
    _arm(lua)                                            # the next attack
    lua.execute("NOW = %d" % (NOW_MS + 50 * 60 * 1000))
    _open(lua, "UIBossDamageTip")
    assert list(lua.eval("CLOSED").values()) == ["UIBossDamageTip"]


def test_every_name_on_the_list_was_read_off_a_live_client():
    text = RESEARCH.read_text(encoding="utf-8")
    for name in lua_actions.CODENAME_SHUT_WINDOWS:
        assert name in text, name


def test_the_screens_a_person_reads_are_not_on_the_list():
    for name in NEVER:
        assert name not in lua_actions.CODENAME_SHUT_WINDOWS


def test_the_hud_is_never_taken_down():
    assert "DestroyAllWindow" not in lua_actions.codename_shut_install()
    assert "CloseSelf" in lua_actions.codename_shut_install()


def _main() -> int:
    if lupa is None:
        print("SKIP: lupa is not installed")
        return 0
    bad = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print("ok   %s" % name)
        except Exception as exc:                          # noqa: BLE001
            bad += 1
            print("FAIL %s: %s" % (name, exc))
    print("%d failed" % bad if bad else "all good")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())
