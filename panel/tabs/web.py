"""«Веб» — the panel, reachable from a phone (#1221).

The tab is the SWITCH and the address, nothing more: the server is `panel/web/`, the
answers it gives are `panel/web/api.py`, and neither knows this tab exists. What lives
here is what only a window can do — say whether it is running, show the link to type
into a phone, and hand over the token.

ONE SERVER, EVERY PROFILE. A window may hold two accounts open at once (#1206) and the
front-end answers for all of them (`panel/web/api.py`): the page has a switcher at the
top and every route takes a profile. So the socket belongs to the WINDOW, not to this
session — the first tab whose switch goes on binds it, and the tab of a profile opened
beside it says «обслуживает <профиль>» and shows that same address instead of starting a
second server nobody asked for.

The knobs stay per profile all the same, because a profile is where the panel keeps
anything a person can set — and because two PANELS (two processes, one per profile, which
some people run) then each have their own port and their own token.

Switching the tab off in «Настройки → Вкладки» is what turns the whole thing off — no
server, no thread, no socket (docs/panel-tabs.md).

WHAT IT IS NOT. It is not an internet service. There is no TLS here and the token
travels in a cookie over plain HTTP: this is for the phone on the same home network as
the machine that farms. The hint on the tab says so, in all eleven languages.
"""
from __future__ import annotations

import secrets
import tkinter as tk
import webbrowser
from tkinter import ttk

from ..web import server as webmod
from ..web.tunnel import Tunnel
from .base import PanelTab

#: How many characters of randomness the generated token carries. Nine bytes is twelve
#: URL-safe characters — long enough that guessing it over a home network is hopeless,
#: short enough to be typed on a phone by somebody who cannot copy and paste.
#: The panel's own address is a home network, where twelve characters typed by hand are
#: plenty. A tunnel puts the same door on the open internet, and the extra eight
#: characters cost nothing because the link carries them.
TOKEN_BYTES = 16


class WebTab(PanelTab):
    """The switch, the address, the token — and the server behind them."""

    ID = "web"
    TITLE_KEY = "tab.web"
    ORDER = 45
    PREFERRED_SIZE = "560x480"
    LOCALE_NS = ("web",)
    # It presses what the panel presses: a scenario from the phone is `rt.play_async`
    # and a timer's switch is the schedule's. Declared so «Вкладки» can say what
    # switching it on costs.
    NEEDS = frozenset({"actions", "schedule"})
    # LOADED AT BOOT, because what it is FOR is being reachable. A remote control that
    # only came up once somebody had clicked its tab in the window would be a remote
    # control for a person who is standing at the machine.
    EAGER = True

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        self._on = None                 # BooleanVar: is the server to be running
        self._port = None               # StringVar
        self._host = None               # StringVar
        self._token = None              # StringVar
        self._state = None              # the label saying what it is doing
        self._link = None               # the address, selectable
        self._tunnel_on = None          # BooleanVar: reach it from the internet
        self._tunnel_link = None        # the public address, selectable
        self._tunnel_note = None        # …or why there is not one
        self._server = None
        self._tunnel = None

    # -- the window ---------------------------------------------------------
    def build(self) -> None:
        self._on = tk.BooleanVar(value=False)
        self._port = tk.StringVar(value=str(webmod.default_port()))
        self._host = tk.StringVar(value=webmod.DEFAULT_HOST)
        self._token = tk.StringVar(value="")

        head = ttk.Frame(self.parent)
        head.pack(fill="x", padx=10, pady=(10, 4))
        self.tr(ttk.Checkbutton(head, variable=self._on, command=self._toggled),
                "web.enabled").pack(side="left")
        self._state = ttk.Label(head, text="")
        self._state.pack(side="right")

        grid = ttk.Frame(self.parent)
        grid.pack(fill="x", padx=10, pady=4)
        self.tr(ttk.Label(grid), "web.port").grid(row=0, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self._port, width=8).grid(row=0, column=1,
                                                               sticky="w", padx=6)
        self.tr(ttk.Label(grid), "web.host").grid(row=1, column=0, sticky="w",
                                                  pady=(4, 0))
        ttk.Entry(grid, textvariable=self._host, width=16).grid(row=1, column=1,
                                                                sticky="w", padx=6,
                                                                pady=(4, 0))
        self.tr(ttk.Label(grid), "web.token").grid(row=2, column=0, sticky="w",
                                                   pady=(4, 0))
        ttk.Entry(grid, textvariable=self._token, width=24).grid(row=2, column=1,
                                                                 sticky="w", padx=6,
                                                                 pady=(4, 0))
        self.tr(ttk.Button(grid, command=self._new_token), "web.token.new").grid(
            row=2, column=2, sticky="w", pady=(4, 0))

        buttons = ttk.Frame(self.parent)
        buttons.pack(fill="x", padx=10, pady=(8, 4))
        self.tr(ttk.Button(buttons, command=self._apply_now), "web.apply").pack(
            side="left")
        self.tr(ttk.Button(buttons, command=self._copy), "web.copy").pack(
            side="left", padx=6)
        self.tr(ttk.Button(buttons, command=self._open), "web.open").pack(side="left")

        self.tr(ttk.Label(self.parent), "web.address").pack(anchor="w", padx=10,
                                                            pady=(8, 0))
        # An Entry rather than a Label so the address can be selected and copied on a
        # machine where the clipboard button is not what the person reaches for.
        self._link = ttk.Entry(self.parent)
        self._link.pack(fill="x", padx=10)
        # -- from outside the house -------------------------------------------
        outside = ttk.Frame(self.parent)
        outside.pack(fill="x", padx=10, pady=(12, 0))
        self._tunnel_on = tk.BooleanVar(value=False)
        self.tr(ttk.Checkbutton(outside, variable=self._tunnel_on,
                                command=self._tunnel_toggled),
                "web.tunnel").pack(anchor="w")
        self._tunnel_link = ttk.Entry(self.parent)
        self._tunnel_link.pack(fill="x", padx=10, pady=(4, 0))
        self._tunnel_note = ttk.Label(self.parent, wraplength=520, justify="left",
                                      text="")
        self._tunnel_note.pack(anchor="w", padx=10, pady=(4, 0))

        self.tr(ttk.Label(self.parent, wraplength=520, justify="left"),
                "web.hint").pack(anchor="w", padx=10, pady=(10, 0))
        self.tr(ttk.Label(self.parent, wraplength=520, justify="left"),
                "web.warning").pack(anchor="w", padx=10, pady=(6, 10))
        self._paint()

    # -- lifecycle ----------------------------------------------------------
    def ensure_loaded(self) -> None:
        """Bring the server — and the tunnel — up if this profile asked for them.

        Idempotent and touches no game. This is also what makes «reachable from outside»
        survive a reboot without a service of its own: the panel is started by its own
        autostart task, and the tunnel is one of its children.
        """
        self._apply()
        self._apply_tunnel()

    def on_show(self) -> None:
        """Repaint: the profile that was serving may have been closed since.

        A read of two module-level dictionaries, no game and no file — which is what
        `on_show` is for (docs/panel-tabs.md).
        """
        self._apply()

    def on_language_change(self) -> None:
        self._paint()

    def on_profile_switch(self) -> None:
        """Another account: another port, another token, another set of answers."""
        self._stop()
        self._apply()

    def panic(self) -> None:
        """«Стоп всё» leaves the remote control UP — on purpose.

        Everything panic stops is something PRESSING the game, and this presses nothing
        by itself: it is the door the person came in through. Stopping it would mean
        that the one button meant for «something is wrong, stop» is also the button that
        locks them out of the machine they are not standing at.
        """

    def shutdown(self) -> None:
        self._stop_tunnel()
        self._stop()

    # -- persistence --------------------------------------------------------
    def config(self) -> dict:
        return {"enabled": bool(self._on.get()) if self._on is not None else False,
                "port": self._port.get() if self._port is not None else "",
                "host": self._host.get() if self._host is not None else "",
                "token": self._token.get() if self._token is not None else "",
                "tunnel": bool(self._tunnel_on.get())
                if self._tunnel_on is not None else False}

    def apply_config(self, raw: dict) -> None:
        raw = raw if isinstance(raw, dict) else {}
        if self._on is None:
            return
        self._on.set(bool(raw.get("enabled")))
        self._port.set(str(raw.get("port") or webmod.default_port()))
        self._host.set(str(raw.get("host") or webmod.DEFAULT_HOST))
        self._token.set(str(raw.get("token") or ""))
        if self._tunnel_on is not None:
            self._tunnel_on.set(bool(raw.get("tunnel")))
        self._paint()

    def persist_vars(self) -> list:
        return [v for v in (self._on, self._port, self._host, self._token,
                            self._tunnel_on) if v is not None]

    # -- the switch ---------------------------------------------------------
    def _toggled(self) -> None:
        self._apply()

    def _apply_now(self) -> None:
        """«Применить» — the port or the token was retyped, so bounce the server."""
        self._stop()
        self._apply()

    def _apply(self) -> None:
        """Make the running state match the switch. The one place that starts or stops.

        Never raises at the caller: a taken port is the ordinary failure (the other
        profile is on it, or a panel that has just closed has not let go yet) and it
        belongs in the log and on the label, not in a traceback out of a checkbox.
        """
        if self._on is None:
            return
        if not self._on.get():
            self._stop()
            self._paint()
            return
        if self._server is not None and self._server.running:
            self._paint()
            return
        # A SIBLING SESSION MAY ALREADY BE SERVING. One server per window answers for
        # every open profile, so there is nothing for this one to add — and binding a
        # second socket would either fail on the port or put a second address in front
        # of the same two accounts. Say who is answering and show their address.
        held = webmod.serving_any()
        if held is not None:
            self._paint()
            return
        token = self._token.get().strip() or self._new_token(quiet=True)
        try:
            server = webmod.WebServer(self.rt, host=self._host.get().strip(),
                                      port=self._port_number(), token=token)
            server.start()
        except OSError:
            self._server = None
            self._on.set(False)
            self.say("web", "web.log.busy", port=self._port_number())
        except Exception as exc:            # noqa: BLE001 — never the window
            self._server = None
            self._on.set(False)
            self.say("web", "web.log.error", error=exc)
        else:
            self._server = server
            self.say("web", "web.log.started", port=server.bound_port())
        self._paint()

    def _stop(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        server.stop()
        self.say("web", "web.log.stopped")

    # -- from outside the house ---------------------------------------------
    def _tunnel_toggled(self) -> None:
        self._apply_tunnel()

    def _apply_tunnel(self) -> None:
        """Make the tunnel match its switch. The one place that starts or stops it.

        Only ever alongside a running server: a tunnel to a port nothing is listening on
        is a public address that answers 502, which is a worse thing to hand somebody
        than no address at all.
        """
        if self._tunnel_on is None:
            return
        want = bool(self._tunnel_on.get()) and self._serving() is not None
        if not want:
            self._stop_tunnel()
            self._paint()
            return
        if self._tunnel is not None and self._tunnel.running:
            self._paint()
            return
        if not Tunnel.available():
            # Nothing is installed and nothing will be installed on somebody's behalf —
            # the note under the switch says what to run.
            self._tunnel_on.set(False)
            self.say("web", "web.log.no_cloudflared")
            self._paint()
            return
        server = self._serving()
        self._tunnel = Tunnel(self.rt, server.bound_port(), on_url=self._tunnel_up)
        if not self._tunnel.start():
            self._tunnel = None
            self._tunnel_on.set(False)
            self.say("web", "web.log.tunnel_failed")
        self._paint()

    def _tunnel_up(self, url: str) -> None:
        """The address arrived — on the child's reader thread, so hop to Tk to draw it."""
        self.say("web", "web.log.tunnel_up")
        try:
            self.rt.root.after(0, self._paint)
        except Exception:                    # noqa: BLE001 — the window is gone
            pass

    def _stop_tunnel(self) -> None:
        tunnel, self._tunnel = self._tunnel, None
        if tunnel is None:
            return
        tunnel.stop()
        self.say("web", "web.log.tunnel_off")

    def _tunnel_address(self) -> str:
        """The public link, token and all — empty until Cloudflare has answered."""
        if self._tunnel is None or not self._tunnel.url:
            return ""
        token = self._token.get().strip()
        return self._tunnel.url + (f"/?token={token}" if token else "/")

    def _port_number(self) -> int:
        try:
            return max(1, min(65535, int(str(self._port.get()).strip())))
        except (TypeError, ValueError):
            return webmod.default_port()

    # -- the token ----------------------------------------------------------
    def _new_token(self, quiet: bool = False) -> str:
        """A fresh token. Every phone that had the old one is logged out by it."""
        token = secrets.token_urlsafe(TOKEN_BYTES)
        self._token.set(token)
        if not quiet:
            self.say("web", "web.log.token")
            if self._server is not None:
                self._apply_now()
        self._paint()
        return token

    # -- what the tab shows -------------------------------------------------
    def _serving(self):
        """The server answering for this window: mine, or a sibling profile's."""
        if self._server is not None and self._server.running:
            return self._server
        return webmod.serving_any()

    def _address(self) -> str:
        """The link to type into a phone: the machine's address, port and token.

        Of whoever is actually SERVING — a sibling profile's server has a different token
        and possibly a different port, and showing this profile's saved one would be an
        address that answers 401.
        """
        server = self._serving()
        host = webmod.addresses()[0]
        token = server.token if server is not None else self._token.get().strip()
        port = server.bound_port() if server is not None else self._port_number()
        tail = f"/?token={token}" if token else "/"
        return f"http://{host}:{port}{tail}"

    def _paint(self) -> None:
        """Three states, not two: mine, a sibling's, or nothing at all."""
        if self._state is None:
            return
        server = self._serving()
        if server is None:
            text = self.t("web.state.off")
        elif server is self._server:
            text = self.t("web.state.on", port=server.bound_port())
        else:
            text = self.t("web.state.elsewhere", profile=server.owner,
                          port=server.bound_port())
        self._state.configure(text=text)
        if self._link is not None:
            self._link.delete(0, "end")
            self._link.insert(0, self._address() if server is not None else "")
        self._paint_tunnel(server)

    def _paint_tunnel(self, server) -> None:
        """The public address, or the one sentence saying why there is not one."""
        if self._tunnel_link is None:
            return
        url = self._tunnel_address()
        self._tunnel_link.delete(0, "end")
        self._tunnel_link.insert(0, url)
        if not Tunnel.available():
            note = self.t("web.tunnel.missing", binary=Tunnel.binary())
        elif server is None:
            note = self.t("web.tunnel.needs_server")
        elif not bool(self._tunnel_on.get()):
            note = self.t("web.tunnel.off")
        elif url:
            note = self.t("web.tunnel.on")
        else:
            note = self.t("web.tunnel.waiting")
        self._tunnel_note.configure(text=note)

    def _copy(self) -> None:
        try:
            self.rt.root.clipboard_clear()
            self.rt.root.clipboard_append(self._address())
        except Exception:                    # noqa: BLE001 — no clipboard, no crash
            return
        self.say("web", "web.log.copied")

    def _open(self) -> None:
        """Open it here, on the machine the panel is on — the quickest way to look."""
        try:
            webbrowser.open(self._address())
        except Exception as exc:             # noqa: BLE001
            self.say("web", "web.log.error", error=exc)


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(WebTab))
