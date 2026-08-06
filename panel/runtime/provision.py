"""Which client a profile drives — decided by the panel, never typed by the person.

A profile IS an account, and an account is a client of its own. Two halves make that
true (docs/research/multi-profile-panel.md §4.1, §4.5):

* **a Windows session**, because a client lives on a desktop and the process probe finds
  it by the login that owns it — `rdp_session` / `rdp_user`;
* **a daemon port**, because that is what the panel, its children and its scenarios talk
  to — `daemon_port`.

Both of them used to be typed by hand on the Settings page, and a profile created
without that visit had NEITHER: an empty `config.json` falls back to the default
profile's port, so five profiles quietly drove one client and farmed one account (#1250).
Nothing about that is visible from the outside — the lease makes them take turns rather
than collide — which is exactly what makes it worth deciding here instead.

**There are only two places a client can be** (#1252):

1. **the console** — the desktop the panel itself is on, `rdp_session` off, the default
   port. Exactly one profile may have it, because there is exactly one such desktop;
2. **a Windows session of its own** — `rdp_session` on with the login of that session,
   and a port nobody else uses. Any number of these.

So the choice is not a choice: the console goes to whoever asks for it first, and every
profile after that gets a session. The one thing the panel cannot work out for itself is
**the login of that session**, which is why creating a profile asks for that and for
nothing else. The port it works out here — :func:`free_port` — and a person never sees a
number they have to keep unique.

WHAT IS NOT HERE. Widgets, dialogs, and any opinion about how a refusal is worded: this
module reads profiles and answers questions about them, so `tests/test_panel_provision.py`
can run it with no display and no Windows. The one exception is that a refusal carries a
locale key (`panel/i18n.Message`), the same way `panel/profile.py`'s do.
"""
from __future__ import annotations

import socket
from typing import NamedTuple

import lua_client

from ..i18n import Message

#: The port of the client on THIS desktop. Not a choice: it is what `lua_client` and
#: every tool default to, so the console profile is the one that needs no port at all.
CONSOLE_PORT = lua_client.DEFAULT_PORT

#: How far above :data:`CONSOLE_PORT` a session's port may be looked for. Twenty-odd
#: accounts is far past what one machine can hold; the bound is here so a machine where
#: every probe answers cannot turn :func:`free_port` into a scan of the whole range.
PORT_SPAN = 64

#: What :func:`clients` calls the console, so a dict keyed by "which client" can hold it
#: beside the logins. A Windows login cannot look like this, so the two can never collide.
CONSOLE = ""


class Client(NamedTuple):
    """The client one profile drives: whose session it is in, and on which port.

    ``user`` is :data:`CONSOLE` (the empty string) for the client on this desktop, and a
    Windows login for one in a session of its own. Never ``None`` — it is a dict key.
    """

    user: str
    port: int

    @property
    def console(self) -> bool:
        return not self.user


class Plan(NamedTuple):
    """What a profile's client settings should become.

    ``settings`` is the three knobs, ready to be merged into a profile's config; the
    named fields beside it are for whoever wants to say what happened in words.
    """

    user: str
    port: int

    @property
    def console(self) -> bool:
        return not self.user

    @property
    def settings(self) -> dict:
        return {"daemon_port": self.port,
                "rdp_session": bool(self.user),
                "rdp_user": self.user}


def client_of(config: dict) -> Client:
    """Which client a profile's EFFECTIVE config names.

    Tolerant on purpose: a port saved as the string `"47655"` by the Settings page, a
    half-typed one, a missing key and an `rdp_user` left behind by a profile that has
    since been put back on the console all mean the same thing to the reader — the
    console, on the console's port — rather than a crash while a window is being built.
    """
    user = ""
    if config.get("rdp_session"):
        raw = config.get("rdp_user")
        user = str(raw or "").strip()
    try:
        port = int(float(str(config.get("daemon_port")).strip()))
    except (TypeError, ValueError):
        port = CONSOLE_PORT
    if not 1 <= port <= 65535:
        port = CONSOLE_PORT
    return Client(user, port)


def clients(profiles, exclude: str | None = None) -> dict:
    """``{profile name: Client}`` for every profile on disk, ``exclude`` left out.

    Reads each profile's EFFECTIVE config (its own overrides on the default profile's),
    because that is what the running panel obeys — a profile with an empty file of its
    own really does drive the default profile's port, which is the whole bug (#1250).
    """
    out = {}
    for name in profiles.list():
        if exclude is not None and name == exclude:
            continue
        try:
            out[name] = client_of(profiles.load(name))
        except Exception:                    # noqa: BLE001 — one unreadable profile
            continue
    return out


def console_owner(profiles, exclude: str | None = None) -> str | None:
    """The profile whose client is the one on this desktop, or ``None`` if it is free.

    First by `ProfileManager.list`'s order, which puts the default profile first — so on
    a machine that has never been told anything, the console belongs to `default` and
    every profile made afterwards gets a session of its own.
    """
    for name, client in clients(profiles, exclude=exclude).items():
        if client.console:
            return name
    return None


def needs_login(profiles, exclude: str | None = None) -> bool:
    """Is the console already taken — must a new profile name a Windows session?"""
    return console_owner(profiles, exclude=exclude) is not None


def taken_ports(profiles, exclude: str | None = None) -> dict:
    """``{port: profile name}`` — the first profile claiming each port."""
    out = {}
    for name, client in clients(profiles, exclude=exclude).items():
        out.setdefault(client.port, name)
    return out


def port_in_use(port: int, timeout: float = 0.25) -> bool:
    """Is something already answering on ``port`` of this machine?

    Asked of a port no profile claims, so an answer means something that is not this
    panel's business — another program, or a daemon left behind by a profile that has
    been deleted. Either way it is not a port to hand out: a daemon binds with
    `SO_EXCLUSIVEADDRUSE` and the second one to try simply fails to start.
    """
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout):
            return True
    except OSError:
        return False


def free_port(profiles, exclude: str | None = None, probe=port_in_use) -> int:
    """A port no profile uses and nothing on this machine answers on.

    Starts one above the console's, so the console profile keeps the number every tool
    defaults to and a session profile never accidentally gets it. ``probe`` is injectable
    so a test can run without touching a socket.
    """
    taken = taken_ports(profiles, exclude=exclude)
    for port in range(CONSOLE_PORT + 1, CONSOLE_PORT + 1 + PORT_SPAN):
        if port in taken:
            continue
        if probe is not None and probe(port):
            continue
        return port
    raise ValueError(Message("profile.error.no_port",
                             "no free daemon port", first=CONSOLE_PORT + 1,
                             last=CONSOLE_PORT + PORT_SPAN))


def plan(profiles, login: str | None = None, exclude: str | None = None,
         probe=port_in_use) -> Plan:
    """What client a profile should be given — the whole answer, both halves.

    With the console free and no login asked for, the console: the ordinary first
    profile on an ordinary machine, and it needs nothing typed at all. Otherwise a
    session of its own, which needs the login and refuses without one — a session
    profile with no login looks for its client among nobody's processes and reports the
    ordinary «клиент не запущен» for ever (`panel/runtime/game_process.py`).

    ``login`` given while the console is free is honoured rather than argued with: a
    person who has said which session their client is in has said something this module
    cannot work out for itself, and the console stays free for the next profile.
    """
    user = (login or "").strip()
    if not user and not needs_login(profiles, exclude=exclude):
        return Plan(CONSOLE, CONSOLE_PORT)
    if not user:
        raise ValueError(Message("profile.error.no_login",
                                 "this profile needs the login of its Windows session",
                                 owner=console_owner(profiles, exclude=exclude) or ""))
    return Plan(user, free_port(profiles, exclude=exclude, probe=probe))


def apply(profiles, name: str, one: Plan) -> Plan:
    """Write a plan into a profile's config, leaving everything else in it alone.

    **ONLY FOR A PROFILE NOBODY HAS OPEN.** An open profile's truth is not this file —
    it is the Tk variables its Settings page is bound to, and the panel writes the whole
    lot of them back on every save, including the one it does while closing
    (`panel/__main__.py` `_collect_settings`). So a plan written straight to disk under
    an open profile survives until the next save and is then silently replaced by the
    port and the login the widgets still hold. That is exactly what «Развести
    клиенты…» did: it wrote four profiles' clients, said so in the log, and the panel
    put every one of them back when the window closed — a fix that reported success and
    changed nothing (#1263).

    Two callers, both safe: the boot's :func:`repair_ports`, which runs before any
    session exists, and creating a profile, which happens before it is opened. A profile
    that IS open is changed through its own binder instead — «Настройки» → «Игра» →
    «Сессия Windows», where setting the bound variable is what persists it and re-points
    the link.
    """
    config = dict(profiles.load(name))
    config.update(one.settings)
    profiles.save(config, name)
    return one


def provision(profiles, name: str, login: str | None = None,
              probe=port_in_use) -> Plan:
    """Decide a profile's client and write it down — :func:`plan` then :func:`apply`."""
    return apply(profiles, name, plan(profiles, login=login, exclude=name, probe=probe))


# -- what is already broken, and which half of it can be fixed unasked ---------

def shared(profiles) -> dict:
    """``{user: [profile, …]}`` for every client MORE THAN ONE profile drives.

    Keyed by the client rather than by the port, because that is the thing there is only
    one of: two profiles both on the console are two views of one game whatever ports
    they name, since a second daemon started on this desktop finds this desktop's client
    (§4.3). Two profiles naming one login are the same story in a session.
    """
    by_client: dict = {}
    for name, client in clients(profiles).items():
        by_client.setdefault(client.user, []).append(name)
    return {user: names for user, names in by_client.items() if len(names) > 1}


def sharing_with(profiles, name: str, client: Client | None = None) -> list:
    """Which OTHER profiles drive the client ``name`` drives. ``[]`` when it is alone.

    :func:`shared` said from one profile's point of view, which is the way the Settings
    page needs it: the person is looking at ONE profile and the question is whether this
    one is farming somebody else's account.

    ``client`` overrides what is on disk for ``name``. The page reads the tick and the
    login out of its widgets, and that is the truth a moment BEFORE the save lands — so
    the warning moves with the tick instead of trailing it by one edit.
    """
    if client is None:
        client = clients(profiles).get(name)
    if client is None:
        return []
    return sorted(other for other, one in clients(profiles, exclude=name).items()
                  if one.user == client.user)


def port_clashes(profiles) -> dict:
    """``{port: [profile, …]}`` for a port claimed by two DIFFERENT clients.

    Different clients, so this is never :func:`shared` said twice: two profiles in two
    Windows sessions that happen to name one port are a real fault with a fix that needs
    nobody asked — one of them moves to a free port and drives the same client as before.
    """
    by_port: dict = {}
    for name, client in clients(profiles).items():
        by_port.setdefault(client.port, []).append((name, client.user))
    out = {}
    for port, rows in by_port.items():
        if len({user for _name, user in rows}) > 1:
            out[port] = [name for name, _user in rows]
    return out


def repair_ports(profiles, probe=port_in_use) -> list:
    """Give every client its own port. Returns ``[(profile, old, new), …]``.

    The half of a broken set-up that can be put right without asking anything: which
    client a profile drives does not change, only the number the panel reaches it on.
    The first profile on a contested port keeps it — most often the console's, whose
    port every tool defaults to.
    """
    moved = []
    for port in sorted(port_clashes(profiles)):
        names = port_clashes(profiles).get(port) or []
        for name in names[1:]:
            client = clients(profiles).get(name)
            if client is None:
                continue
            fresh = free_port(profiles, exclude=name, probe=probe)
            apply(profiles, name, Plan(client.user, fresh))
            moved.append((name, port, fresh))
    return moved


def needs_own_client(profiles) -> list:
    """Profiles sharing a client with another — the ones a login would separate.

    The first of each group keeps what it has; every name after it is a profile that
    needs a Windows session of its own, and the only thing missing is its login. Ordered
    the way `ProfileManager.list` orders them, so the answer does not move about between
    two calls and the default profile is never the one asked to move.
    """
    out = []
    for _user, names in sorted(shared(profiles).items()):
        out.extend(names[1:])
    order = profiles.list()
    return sorted(out, key=lambda n: order.index(n) if n in order else len(order))
