r"""The DOOR: a service that owns the port and routes to the panels (#1976, P0).

`docs/research/panel-service-and-spa-plan.md` §1. The point of it is one sentence — the
endpoint is up before anybody signs in and stays up when they sign out, so the cure stops
being locked behind the illness — and the shape that makes it possible is the other one:
**the panel dials OUT**, because a service in session 0 may not reach into an interactive
session, and a program in a session may always dial a loopback port.

What is pinned here is the whole loop, over real sockets and with no game anywhere:

  * a panel dials in, says who it is, and appears in the register;
  * an HTTP request to the service is answered BY THAT PANEL, verbatim — the service does
    not know what a screen is, and no route is written twice;
  * a request that names a profile goes to the panel that has it, and one that names none
    goes to the first that dialled in;
  * with no panel at all the door still answers, and says so in a way a page can draw —
    «нет панели» is a state of the machine, not a failure of the door;
  * a panel that goes away wakes everything waiting on it rather than hanging;
  * the token still guards everything, exactly as it does on the panel's own port.

    C:\Python312\python.exe tests\test_panel_service.py
    python3 tests/test_panel_service.py
"""
from __future__ import annotations

TIER = "offline"   # tkinter is stubbed below — sockets on ports the OS picks, no game

import json
import os
import sys
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _stub_tk() -> None:
    """A tkinter that answers everything and draws nothing (`test_panel_monster_filter`)."""
    if "tkinter" in sys.modules:
        return

    class _W:
        def __init__(self, *a, **k) -> None:
            pass

        def __getattr__(self, _n):
            return lambda *a, **k: None

    def _module(name: str):
        mod = types.ModuleType(name)
        made: dict = {}

        def _make(attr: str):
            if attr not in made:
                made[attr] = type(attr, (_W,), {})
            return made[attr]

        mod.__getattr__ = _make
        return mod

    tk = _module("tkinter")
    tk.TclError = type("TclError", (Exception,), {})
    sys.modules["tkinter"] = tk
    for sub in ("ttk", "font", "messagebox", "simpledialog", "scrolledtext",
                "filedialog"):
        child = _module(f"tkinter.{sub}")
        sys.modules[f"tkinter.{sub}"] = child
        setattr(tk, sub, child)


_stub_tk()

from panel.runtime.service_link import ServiceLink        # noqa: E402
from panel.service import self_control as selfctl         # noqa: E402
from panel.service import host as hostmod                 # noqa: E402
from panel.service.host import Service                    # noqa: E402

TOKEN = "test-token"

#: THE SUPERVISOR IS OFF IN HERE, and it is not a detail (#2002). A `Service` owns a
#: `Keeper`, and a keeper with nothing configured supervises the profiles THIS MACHINE
#: farms: starting one in a test spawned `-m panel.headless --profile default` on the live
#: account, detached, which then outlived the run and played `launch_game` at the real
#: client every five minutes. What these tests are about is the door, the register and the
#: routing; a launch is `tests/test_service_keeper.py`, with a launcher of its own.
KEEP_OFF = {"enabled": False}


class _Api:
    """A panel's API as the service sees it: something with `dispatch`."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.asked: list = []

    def dispatch(self, method: str, path: str, query: dict, body: dict) -> tuple:
        self.asked.append((method, path, dict(query), dict(body)))
        if path == "/api/boom":
            raise RuntimeError("the tab fell over")
        return 200, {"answered_by": self.name, "path": path,
                     "profile": query.get("profile") or body.get("profile") or ""}


def _service():
    """A service on ports the operating system picks, with no config file anywhere."""
    service = Service({"port": 0, "door": 0, "host": "127.0.0.1",
                       "token": TOKEN, "keep": KEEP_OFF},
                      log=lambda line: None)
    service.start()
    return service


def _busy_port() -> tuple:
    """A port with a plain socket sitting on it — «in use» on every platform."""
    import socket as socketmod

    holder = socketmod.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    return holder, holder.getsockname()[1]


def test_the_front_door_is_waited_for_and_never_given_up_on():
    """The service owns the PERSON'S port now, so a refusal here is the whole way in.

    The ordinary reason is an overlap of a second or two — a panel still letting go of
    the port it is handing over, or Windows restarting this service while the outgoing
    one closes its socket. Answering that by not listening would be «служба жива, входа
    нет», the exact state this move exists to make impossible, so it is waited out and
    said on a clock until the port is free.
    """
    import time

    holder, port = _busy_port()
    lines: list = []
    said, hostmod.BUSY_WAIT_SEC = hostmod.BUSY_WAIT_SEC, 0.3
    retry, hostmod.BUSY_RETRY_SEC = hostmod.BUSY_RETRY_SEC, 0.05
    quiet, hostmod.BUSY_SAY_SEC = hostmod.BUSY_SAY_SEC, 0.1
    service = Service({"port": port, "door": 0, "host": "127.0.0.1",
                       "token": TOKEN, "keep": KEEP_OFF},
                      log=lines.append)
    try:
        service.start()
        assert not service.web.running, "it bound a port somebody else is holding"
        assert _wait(lambda: any("is taken by another process" in ln for ln in lines)), \
            f"nothing in the log says the machine has no way in: {lines}"
        assert _wait(lambda: any("STILL waiting" in ln for ln in lines)), \
            f"it stopped saying so after the first minute: {lines}"
        holder.close()                       # …whoever held it lets go
        assert _wait(lambda: service.web.running, tries=400), "it never took the port"
        assert service.web.bound_port() == port
    finally:
        hostmod.BUSY_WAIT_SEC, hostmod.BUSY_RETRY_SEC = said, retry
        hostmod.BUSY_SAY_SEC = quiet
        service.stop()
        try:
            holder.close()
        except OSError:
            pass


def test_a_door_this_machine_cannot_have_is_said_loudly_and_not_retried_for_ever():
    """«That is not my address» will not come free by asking again — it is SAID."""
    lines: list = []
    service = Service({"port": 0, "door": 0, "host": "203.0.113.1",
                       "token": TOKEN, "keep": KEEP_OFF},
                      log=lines.append)
    try:
        service.start()
        assert _wait(lambda: any("THE DOOR IS SHUT" in ln for ln in lines)), lines
        assert not service.web.running
        # …and the door for PANELS is up all the same: they are supervised while the
        # front door is being fought for.
        assert service.door.running
    finally:
        service.stop()


def _link(service, api, session: str, profiles) -> ServiceLink:
    link = ServiceLink(api, session=session, profiles=list(profiles),
                       version="test", boot={"pid": 4242, "at": 1.0, "head": "abc1234"},
                       log=lambda line: None,
                       address=lambda: ("127.0.0.1", service.door.port))
    link.start()
    return link


def _wait(test, tries: int = 200, pause: float = 0.02) -> bool:
    import time

    for _ in range(tries):
        if test():
            return True
        time.sleep(pause)
    return False


def _get(service, path: str, token: str = TOKEN) -> tuple:
    # `bound_port()`, not `port`: the tests bind `0` and the operating system picks.
    url = f"http://127.0.0.1:{service.web.bound_port()}{path}"
    url += ("&" if "?" in url else "?") + f"token={token}"
    try:
        with urllib.request.urlopen(url, timeout=10) as answer:
            return answer.status, json.loads(answer.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, {"raw": body}


def _post(service, path: str, body: dict, token: str = TOKEN) -> tuple:
    url = f"http://127.0.0.1:{service.web.bound_port()}{path}"
    url += ("&" if "?" in url else "?") + f"token={token}"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:
            return answer.status, json.loads(answer.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw}


# ---------------------------------------------------------------------------
def test_a_panel_dials_in_and_answers_for_itself() -> None:
    service = _service()
    api = _Api("first")
    link = _link(service, api, "console", ["default"])
    try:
        assert _wait(lambda: len(service.registry) == 1), "the panel never dialled in"
        assert _wait(lambda: service.registry.all()[0].profiles == ["default"]), \
            "the panel never said who it is"
        status, payload = _get(service, "/api/state")
        assert status == 200, (status, payload)
        assert payload["answered_by"] == "first", payload
        assert api.asked and api.asked[-1][1] == "/api/state", api.asked
    finally:
        link.stop()
        service.stop()


def test_the_request_reaches_the_panel_that_has_that_profile() -> None:
    """One machine may hold two panels — a second client lives in its own session."""
    service = _service()
    one, two = _Api("one"), _Api("two")
    a = _link(service, one, "console", ["default", "alt"])
    b = _link(service, two, "player2", ["second"])
    try:
        assert _wait(lambda: len(service.registry) == 2)
        assert _wait(lambda: all(p.profiles for p in service.registry.all()))
        _, said = _get(service, "/api/state?profile=second")
        assert said["answered_by"] == "two", said
        _, said = _get(service, "/api/state?profile=alt")
        assert said["answered_by"] == "one", said
        # …and a request that names nobody goes to the one that dialled in FIRST — which
        # is whichever of the two won the race to the door, so it is read off the register
        # rather than assumed. What is pinned is the rule, not the order two threads
        # happened to connect in.
        first = service.registry.all()[0].profiles
        _, said = _get(service, "/api/state")
        answered = said["answered_by"]
        assert ("default" in first) == (answered == "one"), (first, said)
        # …and a name NOBODY has is refused, never handed to the first panel (#2068).
        # That fallthrough is how a page asking about `default` got a test account back,
        # 200 and named as itself, on a machine that had a leftover panel up.
        status, said = _get(service, "/api/state?profile=ghost")
        assert status == 409, (status, said)
        assert said["error"] == "no_such_profile" and said["profile"] == "ghost", said
        assert sorted(said["profiles"]) == ["alt", "default", "second"], said
    finally:
        a.stop()
        b.stop()
        service.stop()


def test_a_profile_opened_AFTER_the_dial_is_routed_to() -> None:
    """The list is not a snapshot of the moment the panel connected (#2068).

    `hello` used to be said once, so the profiles the service filed were the ones the
    panel had when it dialled. A profile opened afterwards was therefore one nobody was
    known to hold: the door answered `no_such_profile` about an account that was farming,
    and the keeper counted it missing and went looking for somewhere to start a panel for
    it. The panel re-says `hello` on every open and close that worked
    (`panel/runtime/profile_control.py::_tell_the_service`), and the service simply files
    the newer list over the older one.
    """
    service = _service()
    api = _Api("one")
    held = ["default"]
    link = ServiceLink(api, session="console", profiles=lambda: list(held),
                       version="test", boot={"pid": 1, "at": 1.0, "head": "abc1234"},
                       log=lambda line: None,
                       address=lambda: ("127.0.0.1", service.door.port))
    link.start()
    try:
        assert _wait(lambda: service.registry.all() and
                     service.registry.all()[0].profiles == ["default"])
        status, said = _get(service, "/api/state?profile=later")
        assert status == 409 and said["error"] == "no_such_profile", (status, said)
        # …the person opens it, and the panel says the list again on the same socket
        held.append("later")
        assert link.announce(), "the link had nothing to say it on"
        assert _wait(lambda: "later" in service.registry.all()[0].profiles), \
            "the service is still holding the list from the dial"
        status, said = _get(service, "/api/state?profile=later")
        assert status == 200 and said["answered_by"] == "one", (status, said)
    finally:
        link.stop()
        service.stop()


def test_every_press_that_opens_a_profile_says_the_list_again() -> None:
    """Announcing is wired to the PRESS, not to a clock, and to every front-end's press.

    Both front-ends and the service itself open profiles through
    `panel/runtime/profile_control.py::carry_out`, so that is the one place it has to be
    said from — and a press that failed says nothing, because nothing moved.
    """
    from panel import profile as profilemod
    from panel.runtime import profile_control as profilectl
    from panel.runtime import service_link as linkmod

    said: list = []
    real_link = linkmod._LINK
    # A press also writes down what this machine wants farmed, and this test is not about
    # that half — stood aside so the run does not touch the machine's own standing list.
    real_add, real_drop = profilemod.keep_add, profilemod.keep_drop
    profilemod.keep_add = profilemod.keep_drop = lambda name: None

    class _Spy:
        def announce(self) -> bool:
            said.append(1)
            return True

    linkmod._LINK = _Spy()
    profilectl.set_handler(lambda action, name, text: name != "no")
    try:
        assert profilectl.carry_out(profilectl.OPEN, "yes")
        assert said == [1], said
        assert profilectl.carry_out(profilectl.CLOSE, "yes")
        assert said == [1, 1], said
        assert not profilectl.carry_out(profilectl.OPEN, "no")
        assert said == [1, 1], "a press that failed announced a list that did not move"
    finally:
        profilectl.set_handler(None)
        linkmod._LINK = real_link
        profilemod.keep_add, profilemod.keep_drop = real_add, real_drop


def test_no_panel_is_a_state_the_page_can_draw() -> None:
    """The machine is up, the door answers, and nobody has signed in yet."""
    service = _service()
    try:
        status, payload = _get(service, "/api/profiles")
        assert status == 200 and payload["profiles"] == [], (status, payload)
        status, payload = _get(service, "/api/state")
        assert status == 503 and payload["error"] == "no_panel", (status, payload)
        status, payload = _get(service, "/api/panels")
        assert status == 200 and payload["panels"] == [], payload
    finally:
        service.stop()


def test_the_register_says_who_is_there() -> None:
    service = _service()
    link = _link(service, _Api("first"), "console", ["default"])
    try:
        assert _wait(lambda: _get(service, "/api/panels")[1]["panels"])
        _, said = _get(service, "/api/panels")
        panel = said["panels"][0]
        assert panel["session"] == "console" and panel["profiles"] == ["default"]
        assert panel["pid"] and panel["version"] == "test", panel
        # WHICH CODE, not which release (#1994). A version is read off git when it is
        # asked and moves on a commit with no restart; the head is what the process
        # imported, and it is the only field here that can answer «is the fix live».
        assert panel["head"] == "abc1234" and panel["boot_at"] == 1.0, panel
        assert said["profiles"] == ["default"], said
    finally:
        link.stop()
        service.stop()


def test_one_named_panel_can_be_asked_to_go_without_anybody_killing_it() -> None:
    """The press that was missing (#1994).

    Every other route is routed by PROFILE, so with two panels answering for one name the
    second is unreachable for as long as it lives — and the only way to remove it was to
    kill it, which the person has forbidden. `POST /api/panels` names the PROCESS, and
    what it sends is the panel's own `/api/panel` press.
    """
    service = _service()
    api = _Api("first")
    link = _link(service, api, "console", ["default"])
    try:
        assert _wait(lambda: _get(service, "/api/panels")[1]["panels"])
        pid = _get(service, "/api/panels")[1]["panels"][0]["pid"]

        status, said = _post(service, "/api/panels", {"action": "quit", "pid": pid})
        assert status == 200, said
        asked = [row for row in api.asked if row[1] == "/api/panel"]
        assert asked and asked[-1][3] == {"action": "quit"}, api.asked

        # …and it is a PRESS on one process, so everything about it is named or refused.
        assert _post(service, "/api/panels", {"action": "quit"})[0] == 400
        assert _post(service, "/api/panels", {"action": "sing", "pid": pid})[0] == 400
        assert _post(service, "/api/panels", {"action": "quit", "pid": 999999})[0] == 404
    finally:
        link.stop()
        service.stop()


def test_the_service_can_be_asked_to_restart_ITSELF_and_refuses_when_it_is_not_one() -> None:
    """The door's own press (#1994).

    The panel-side half of #1994 was delivered in one restart; the service-side half could
    not be delivered at all — a service started by Windows is restarted by Windows, `sc
    stop` needs rights an ordinary session has not got, and there was no way in from the
    door the service was itself serving. So the press asks the SCM, and a service running
    in the FOREGROUND — which is every test, and anybody watching it — is answered
    `unavailable` rather than stopping a service that is not running.
    """
    asked: list = []
    watched: list = []
    said = selfctl.restart(spawn=asked.append, watch=lambda *a: watched.append(a),
                           name="not_a_registered_service")
    assert said == {"ok": False, "unavailable": True,
                    "name": "not_a_registered_service"}, said
    assert not asked, "asked Windows to restart something it does not know"

    # …and when Windows DOES know it, what goes out is one detached restarter, and it
    # waits for the stop rather than racing it (`sc stop` returns on ACCEPTED).
    real = selfctl.registered
    try:
        selfctl.registered = lambda name="", run=None: True
        said = selfctl.restart(spawn=asked.append, watch=lambda *a: watched.append(a),
                               name="whatever")
    finally:
        selfctl.registered = real
    assert said["ok"] is True and said["name"] == "whatever", said
    assert len(asked) == 1, asked
    line = " ".join(asked[0])
    assert "Restart-Service" in line and "whatever" in line and "-Force" in line, line
    # …and it asks a VERSION of Windows' PowerShell that exists rather than a name on a
    # PATH LocalSystem may not have, with nothing in the script that quoting can eat.
    assert asked[0][0].lower().endswith("powershell") or \
        asked[0][0].lower().endswith("powershell.exe"), asked[0][0]
    assert '"' not in asked[0][-1], asked[0][-1]

    # THE VERDICT IS THE POINT OF #2069. `ok` means «the ask went out», and it used to be
    # indistinguishable from «it happened»: the restarter's output went to DEVNULL and the
    # service went on running with a two-day-old pid under a door saying ok. So the ask
    # names the file the restarter writes its own verdict into, and this process arms a
    # watcher that can only fire if it was never stopped — the honest «did not».
    assert said["log"] == selfctl.restart_log_path() and said["asked"] is True, said
    assert selfctl.restart_log_path() in " ".join(asked[0]), asked[0]
    assert len(watched) == 1 and watched[0][1] == "whatever", watched


def test_a_restart_that_did_not_happen_says_so_from_the_side_that_survived_it() -> None:
    """The watcher is only ever reached by a service the SCM never stopped (#2069).

    Nothing has to be weighed up when it fires: a restart that worked ended this process
    long before the delay was up, so being alive to say the line IS the evidence for it.
    """
    lines: list = []
    selfctl._watch(lines.append, "whatever", 0.01)
    for _ in range(200):
        if lines:
            break
        time.sleep(0.01)
    assert lines and "NOT restarted" in lines[0], lines
    assert str(os.getpid()) in lines[0] and selfctl.restart_log_path() in lines[0], lines


def test_the_service_route_answers_its_state_and_refuses_a_press_it_does_not_know() -> None:
    """Both branches, and neither of them asks THIS machine what it happens to have.

    `registered()` puts the question to the live Windows SCM, so a computer that ran
    `service_install.bat` answers «yes» and one that never did answers «no» — and a test
    that reads the answer is testing the machine rather than the door (#2020). What is
    pinned instead is the rule: no service known by that name, no controls and no press;
    a service known, a control to press and a press that is accepted.
    """
    service = _service()
    real = selfctl.registered
    try:
        selfctl.registered = lambda name="", run=None: False
        status, said = _get(service, "/api/service")
        assert status == 200 and said["name"], said
        assert said["controls"] == [] and said["available"] is False, said
        assert _post(service, "/api/service", {"action": "sing"})[0] == 400
        status, said = _post(service, "/api/service", {"action": "restart"})
        assert status == 503 and said.get("unavailable") is True, said

        # …and with the SCM knowing the name, the same door offers the press.
        asked: list = []
        selfctl.registered = lambda name="", run=None: True
        real_spawn, real_watch = selfctl._spawn, selfctl._watch
        selfctl._spawn = asked.append
        selfctl._watch = lambda *a: None      # a 40s timer outliving the test says nothing
        try:
            status, said = _get(service, "/api/service")
            assert status == 200 and said["available"] is True, said
            assert [c["id"] for c in said["controls"]] == [selfctl.RESTART], said
            assert _post(service, "/api/service", {"action": "sing"})[0] == 400
            status, said = _post(service, "/api/service", {"action": "restart"})
            assert status == 200 and said.get("ok") is True, said
            assert len(asked) == 1, asked
        finally:
            selfctl._spawn, selfctl._watch = real_spawn, real_watch
    finally:
        selfctl.registered = real
        service.stop()


def test_a_panel_that_goes_away_is_forgotten_and_nothing_hangs() -> None:
    service = _service()
    api = _Api("first")
    link = _link(service, api, "console", ["default"])
    try:
        assert _wait(lambda: len(service.registry) == 1)
        link.stop()
        assert _wait(lambda: len(service.registry) == 0), "the register kept a dead panel"
        status, payload = _get(service, "/api/state")
        assert status == 503 and payload["error"] == "no_panel", (status, payload)
    finally:
        service.stop()


def test_a_panel_that_raises_answers_500_rather_than_dropping_the_request() -> None:
    """A tab that falls over is one request's problem, not the door's."""
    service = _service()
    link = _link(service, _Api("first"), "console", ["default"])
    try:
        assert _wait(lambda: len(service.registry) == 1)
        status, payload = _get(service, "/api/boom")
        assert status == 500, (status, payload)
        assert "RuntimeError" in str(payload.get("error")), payload
        # …and the link is still there afterwards.
        status, _ = _get(service, "/api/state")
        assert status == 200
    finally:
        link.stop()
        service.stop()


def test_nothing_is_readable_without_the_token() -> None:
    service = _service()
    link = _link(service, _Api("first"), "console", ["default"])
    try:
        assert _wait(lambda: len(service.registry) == 1)
        status, _payload = _get(service, "/api/state", token="wrong")
        assert status == 401, status
    finally:
        link.stop()
        service.stop()


def test_the_panels_door_is_loopback_or_nothing() -> None:
    """The world's half is the HTTP port, behind its token. This one is the inside.

    A door on an interface would be a way into every panel on the machine for anybody who
    can reach the box — so a host that is not this machine talking to itself is REFUSED
    rather than quietly corrected: a misconfiguration that did the safe thing in silence
    leaves whoever wrote it believing something else.
    """
    from panel.service import door as doormod
    from panel.service.registry import Registry

    assert doormod.DOOR_HOST == "127.0.0.1", doormod.DOOR_HOST
    for host in ("0.0.0.0", "192.168.1.10", "example.invalid", ""):
        door = doormod.Door(Registry(), host=host or "0.0.0.0", port=0)
        try:
            door.start()
        except ValueError:
            continue
        door.stop()
        raise AssertionError(f"the door listened on {host!r}")
    # …and the loopback itself is allowed, by name as well as by number.
    for host in ("127.0.0.1", "localhost"):
        door = doormod.Door(Registry(), host=host, port=0)
        door.start()
        assert door.running, host
        door.stop()


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
        else:
            print(f"  ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
