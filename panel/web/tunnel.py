"""Reaching the panel from OUTSIDE the home network, without opening a port (#1221).

The web front-end listens on the machine's own address, which is exactly right for the
phone on the sofa and useless from anywhere else. The three ways out of that are not
equal:

* **Forwarding a port on the router** — a control panel for a game account, on the open
  internet, behind one token and no TLS. Not offered here, and deliberately not made
  easy.
* **A VPN** — the best answer by a distance, and not one this repository can set up for
  somebody: it is their router, their client, their keys.
* **An outbound tunnel** — this file. `cloudflared` opens a connection OUT to
  Cloudflare and is handed a public `https://…trycloudflare.com` address that is proxied
  back down it. Nothing is opened in the perimeter, the certificate is Cloudflare's, and
  a machine behind carrier-grade NAT with no public address at all still works.

WHY THE QUICK TUNNEL. `cloudflared tunnel --url …` needs no account, no domain and no
login — which is what makes it something the panel can offer rather than something the
person must first go and arrange. The price is that the address is random and changes
every time it starts, so the tab shows the CURRENT one and the phone is handed a fresh
link; a person who wants a permanent address configures a named tunnel of their own and
this file does not stand in their way.

THE BINARY IS NOT OURS. `cloudflared` is a separate signed executable from Cloudflare.
The panel never downloads, bundles or installs it: it looks for one on the PATH
(`tools/lib/game_paths.py`) and, finding none, refuses to switch the tunnel on and says
what to install. A bot that fetches executables on its own behalf is a bot nobody can
audit.

IT IS ONE OF THE PANEL'S CHILDREN, which is what makes it survive the things that matter:
the factory owns it, writes it down, stops it when the window closes and reaps it if the
panel was killed rather than closed (#1212). Nothing else has to be arranged for it to
come back after a reboot — the panel's own autostart brings the panel, the panel brings
this.
"""
from __future__ import annotations

import re
import threading

import game_paths

#: What cloudflared prints when the tunnel is up. It arrives on stderr, in a box drawn
#: out of plus signs, and this is the only line of it worth anything.
URL_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")

#: …and a named tunnel's own address, for somebody who has configured one: the same
#: binary prints it the same way.
NAMED_RE = re.compile(r"https://[a-z0-9][a-z0-9.-]*\.cfargotunnel\.com")

#: How long to wait for the address before saying it did not come. Cloudflare usually
#: answers in two or three seconds; a machine on a bad line takes longer, and a machine
#: with no route at all never answers at all.
URL_TIMEOUT_SEC = 30.0


class Tunnel:
    """One `cloudflared` process, and the public address it was given."""

    def __init__(self, rt, port: int, on_url=None) -> None:
        self.rt = rt
        self.port = int(port)
        #: Called with the address the moment it is known — on the CHILD's reader
        #: thread, so whoever listens hops to the Tk thread itself.
        self._on_url = on_url
        self._url = ""
        self._child = None
        self._ready = threading.Event()

    # -- what it is -----------------------------------------------------------
    @property
    def url(self) -> str:
        """The public address, or ``""`` until Cloudflare has handed one over."""
        return self._url

    @property
    def running(self) -> bool:
        return self._child is not None

    @staticmethod
    def available() -> bool:
        """Is there a binary to run at all?"""
        return game_paths.cloudflared_installed()

    @staticmethod
    def binary() -> str:
        return game_paths.cloudflared()

    def command(self) -> list:
        """The whole command line, so a test can read it without spawning anything.

        `--no-autoupdate` because a binary that replaces itself under a running panel is
        not a thing to discover at three in the morning; updating it is the person's
        business, exactly as installing it was.
        """
        return [self.binary(), "tunnel", "--no-autoupdate",
                "--url", f"http://127.0.0.1:{self.port}"]

    # -- lifecycle ------------------------------------------------------------
    def start(self) -> bool:
        """Spawn it. ``False`` if there is no binary or it would not start.

        Returns as soon as the process is up — the ADDRESS arrives later, on the child's
        own output, and :meth:`wait_for_url` is there for a caller that must have it.
        """
        if self.running:
            return True
        if not self.available():
            return False
        self._ready.clear()
        self._url = ""
        child = self.rt.children.spawn("tunnel", self.command(),
                                       on_line=self._read, on_exit=self._exited)
        if not child.start():
            return False
        self._child = child
        return True

    def wait_for_url(self, timeout: float = URL_TIMEOUT_SEC) -> str:
        """Block until the address is known, or the timeout runs out. ``""`` on failure."""
        self._ready.wait(timeout)
        return self._url

    def stop(self) -> None:
        child, self._child = self._child, None
        self._url = ""
        self._ready.clear()
        if child is not None:
            child.stop()

    # -- reading the child ----------------------------------------------------
    def _read(self, line: str):
        """Catch the address; let everything else through into the log.

        cloudflared is chatty and most of it is of no interest to anybody looking at a
        panel, so only the line carrying the address is kept — the rest is dropped
        rather than filling the window with a tunnel's own bookkeeping. Returning
        ``False`` is how a reader says «swallow this line» (panel/childmon.py).
        """
        found = URL_RE.search(line) or NAMED_RE.search(line)
        if found and not self._url:
            self._url = found.group(0)
            self._ready.set()
            if self._on_url is not None:
                try:
                    self._on_url(self._url)
                except Exception:            # noqa: BLE001 — a painter, never the child
                    pass
            return None                      # this one line IS worth logging
        # Errors are worth seeing; the rest is the tunnel talking to itself.
        return None if _interesting(line) else False

    def _exited(self) -> None:
        """It died on its own — the address is gone with it."""
        self._child = None
        self._url = ""
        self._ready.set()                    # unblock anyone waiting; the answer is ""
        try:
            self.rt.say("web", "web.log.tunnel_died")
        except Exception:                    # noqa: BLE001 — closing, never the panel
            pass


def _interesting(line: str) -> bool:
    """Is this line of cloudflared's output worth a person's attention?"""
    low = line.lower()
    return any(word in low for word in ("err", "fail", "unable", "refused", "fatal"))
