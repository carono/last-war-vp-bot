#!/usr/bin/env python3
"""Shared machinery for passive map scans — transport, and which server is on screen.

`secret_task_capture.py` grew all of this while there was only one scanner.
There are now two (`scan_players.py` is the other) and every line here is
about `world.get.block` in general rather than about tasks: talking to npcap
through scapy, counting what arrived, and deciding which server's map the
player is actually looking at. That last part is subtle and hard-won — see
`_elect` and `_note_jump` — so it lives in one place and is subclassed, not
copied.

A scanner subclasses `MapIndex` and implements `on_blocks()`, which is called
with the blocks of each decoded map response. Everything above it — framing,
masking, TLV — is `lastwar_proto`; nothing here reimplements any of it.

**This must run under the Windows Python, not the WSL one** — see
`check_platform()` for why.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from collections import Counter, deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lastwar_proto as proto  # noqa: E402
from live_sniffer import C_DIM, C_ERR, C_RESET, LiveDecoder  # noqa: E402

GAME_PORT = 17935


def check_platform() -> None:
    """Refuse to run where capture cannot possibly work, and say why.

    Started under the WSL interpreter a scan would sniff happily and report
    nothing forever, which looks identical to "the map was not moving" — the
    one failure these tools are otherwise careful to distinguish.
    """
    if sys.platform == "win32":
        return
    print(f"{C_ERR}This is the {sys.platform} interpreter.{C_RESET} WSL2 runs "
          f"in a NAT'd VM whose network namespace is not the Windows host's, "
          f"so it cannot see the game's packets — a capture here would sit "
          f"silent forever rather than fail.\n\n"
          f"Run it under the Windows Python instead:\n"
          f"    /mnt/c/Python312/python.exe {' '.join(sys.argv)}\n",
          file=sys.stderr)
    raise SystemExit(2)


def level_set(text: str) -> set:
    """Parse `--level` — one level or a comma-separated list of them.

    Raises argparse's own error type so a typo prints the usage line and the
    offending value rather than a traceback. Silently skipping an unparsable
    entry would be worse than refusing: the run would narrow to something the
    user did not ask for and quietly report less than it found.
    """
    levels = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            levels.add(int(part))
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"{part!r} is not a level; expected a number or a "
                f"comma-separated list like 7,8")
    if not levels:
        raise argparse.ArgumentTypeError("no level given")
    return levels


def dump_records(records: list, path: str) -> bool:
    """Write already-built records to `path`. True if the write landed.

    Called while the capture is still running so a reader can poll the file
    mid-session.

    This writes the target directly rather than renaming a temp file over it.
    A rename is the atomic option and would spare a poller from ever seeing a
    half-written file, but on Windows `os.replace` raises PermissionError
    (WinError 5) whenever anything else holds the target open — an editor, a
    poller, the indexer — and that killed whole capture sessions. A capture
    that survives is worth more than a checkpoint that is never briefly
    inconsistent, so a locked file now costs one skipped flush instead of the
    run. The next flush rewrites it whole.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2, ensure_ascii=False)
        return True
    except PermissionError:
        return False


# How much recent map traffic decides which server is on screen. Panning the
# undebounced client emits a request per frame (protocol.md §7), so the map
# actually being dragged produces a continuous stream of responses, while a
# neighbouring server prefetched at a border produces a handful. The window is
# what separates those two, so it has to be long enough to hold a normal pan.
SERVER_VOTE_WINDOW_SECONDS = 30.0
# ...and how many responses a challenger needs before it can take the screen.
# One is what the old first-past-the-post rule effectively required, and a
# single prefetch response was enough to flip it.
SERVER_VOTE_MIN = 3
# After the client announces a jump the election is held shut for this long.
# The move is instant but the socket is not: responses the old server was
# already sending keep arriving for a moment afterwards, and with the ballot
# box just emptied a handful of them is enough to clear SERVER_VOTE_MIN and
# hand the screen straight back. Long enough to outlast those stragglers,
# short enough that panning off the new map still registers normally.
SERVER_JUMP_GRACE_SECONDS = 5.0


def block_servers(blocks) -> list:
    """The server id each block in a map response belongs to.

    Every block carries its own `serverId` — verified present on 261/261
    blocks of the saved capture, and never once disagreeing with the `f102`
    on its own tiles (0 mismatches in 8217 tiles). That makes it exact where
    reading the id off the first tile was a guess: a block whose tiles happen
    to lead with a neighbour's would have been misattributed wholesale.
    """
    out = []
    for block in blocks:
        server = block.get("serverId")
        if server:
            out.append(server)
    return out


class MapIndex(LiveDecoder):
    """LiveDecoder that tracks the server on screen and hands blocks to a subclass.

    Subclasses implement `on_blocks(payload, blocks, now)` to keep whatever
    they are scanning for. It is called with `_index_lock` held and with
    `current_server` already updated for this response, so a subclass can key
    records on it without racing the sniffer thread.
    """

    def __init__(self) -> None:
        super().__init__()
        self._index_lock = threading.Lock()
        # The server whose map the player is actually looking at. No single
        # response can say: approaching a border the client prefetches the
        # neighbouring server, and a jump fires `world.get.block` for several
        # ids at once (protocol.md §6) — each arriving as its own ordinary
        # response, indistinguishable from the one for the map on screen.
        # Deciding per response is what let a neighbour take the screen, so
        # this is decided by weight of recent traffic instead; see _elect().
        self.current_server: int | None = None
        # (timestamp, server) per block of recent map traffic — the ballots.
        self._votes: deque = deque()
        # (old, new) pairs the sniffer thread noticed, drained by the printing
        # loop so the banner lands in order with the rest of the output.
        self._server_changes: list = []
        # Until when _elect() is held shut after a declared jump; see
        # SERVER_JUMP_GRACE_SECONDS.
        self._jump_grace_until = 0.0
        # A zero result is ambiguous without these: no map data at all reads
        # exactly like map data that held nothing of interest, and the two call
        # for opposite responses from whoever is running the scan.
        self.blocks_seen = 0
        self.tiles_seen = 0
        self.tile_kinds: Counter = Counter()
        # Counted before any filtering, unlike LiveDecoder.packets which only
        # counts TCP packets carrying a payload. The gap between the two is
        # the difference between "npcap delivered nothing" and "it delivered
        # packets this decoder threw away", which need opposite fixes.
        self.delivered = 0

    # -- transport ---------------------------------------------------------

    def feed_packet(self, pkt, iface) -> None:
        """Hand one sniffed packet to the decoder, as a parsed Ethernet frame.

        npcap reports linktype 1 on these adapters, but scapy fails to map it
        to a class ("Unable to guess datalink type … Using <member 'name' of
        'Packet' objects>") and hands back an unparsed Packet with no IP or
        TCP layer, which the decoder then discards — 144 delivered, 0 decoded.
        Re-parsing the raw bytes ourselves sidesteps the guess entirely; this
        is what live_tshark.py has always done with `Ether(raw)`, and is why
        the dumpcap path never hit this.
        """
        from scapy.layers.l2 import Ether
        from scapy.layers.inet import IP

        self.delivered += 1
        if not pkt.haslayer(IP):
            try:
                pkt = Ether(bytes(pkt))
            except Exception:
                return
        self.handle(pkt, iface)

    def emit(self, direction: str, env) -> None:  # LiveDecoder hook
        command = proto.envelope_command(env)
        if direction == "up":
            if command == "meteorite.enter.world":
                self._note_jump(proto.envelope_payload(env))
            return
        if direction != "down":
            return
        if command != "world.get.block":
            # Everything else the server says, offered to the subclass. A map
            # sweep listens here for `get.user.info.multi`, which is how a
            # click on a base answers with numbers no tile carries.
            with self._index_lock:
                self.on_response(command, proto.envelope_payload(env))
            return
        payload = proto.envelope_payload(env)
        blocks = payload.get("serverPointArr") or ()
        kinds = Counter(
            (point.get("_protobuf") or {}).get("f2")
            for block in blocks
            for point in block.get("points") or ()
        )
        servers = block_servers(blocks)
        with self._index_lock:
            self.blocks_seen += 1
            self.tiles_seen += sum(kinds.values())
            self.tile_kinds.update(kinds)
            now = time.time()
            if now < self._jump_grace_until:
                # Responses the old server was already sending. Holding the
                # election shut is not enough on its own — these would sit in
                # the window and take the screen back the moment it reopened,
                # which is exactly the case a minimap click produces: the
                # viewport lands on cached ground, the new server is asked for
                # nothing, and the stragglers are the only ballots there are.
                servers = [s for s in servers if s == self.current_server]
            self._votes.extend((now, server) for server in servers)
            viewing = self._elect(now)
            if viewing is not None:
                self._switch_to(viewing)
            self.on_blocks(payload, blocks, now)

    # -- subclass hooks ----------------------------------------------------

    def on_blocks(self, payload, blocks, now: float) -> None:
        """Keep whatever this scanner is after. `_index_lock` is held."""

    def on_response(self, command: str | None, payload) -> None:
        """Any server response that is not a map block. `_index_lock` is held.

        The map is not the only thing worth listening to while a sweep runs —
        clicking something in the client makes it ask a question, and the
        answer arrives here.
        """

    def on_server_left(self, server: int) -> None:
        """The player moved off `server`. `_index_lock` is held.

        A scanner whose records go stale the moment the map stops re-sending
        them (secret tasks, whose dispatch timers keep running) drops them
        here. One that is building a database across servers (player bases)
        does nothing.
        """

    # -- which server is on screen -----------------------------------------

    def _note_jump(self, payload) -> None:
        """Take the client at its word about which server it just moved to.

        Weight of traffic (see _elect) can only follow the map, so it needs
        the map to keep talking: dragging re-requests a region every frame and
        the new server out-votes the old one within a second. A minimap click
        is not a drag. The viewport lands somewhere already cached, the client
        may not ask for a single block, and with no ballots to count the
        election never runs — the run goes on reporting on the server the
        player left, indefinitely.

        `meteorite.enter.world` closes that hole because the client sends it
        *before* it moves: 3/3 of the server changes in the saved captures are
        preceded by it, its `targetServerId` matches every `world.get.block`
        request that follows, and it never once named a server the client did
        not then go to. That makes it a statement of intent rather than
        evidence to be weighed, so it overrules the tally outright.
        """
        server = payload.get("targetServerId")
        if not server:
            return
        with self._index_lock:
            if server == self.current_server:
                return
            # The tally describes the map being left. Carried across, it is a
            # head start for the wrong server; the grace window then keeps the
            # in-flight stragglers from rebuilding it.
            self._votes.clear()
            self._jump_grace_until = time.time() + SERVER_JUMP_GRACE_SECONDS
            self._switch_to(server)

    def _switch_to(self, server: int) -> None:
        """Make `server` the map on screen. Callers hold `_index_lock`."""
        if server == self.current_server:
            return
        old = self.current_server
        self._server_changes.append((old, server))
        self.current_server = server
        if old is not None:
            self.on_server_left(old)

    def _elect(self, now: float) -> int | None:
        """Which server the recent map traffic says is on screen.

        The map being dragged is re-requested every frame, so it dominates the
        window; a server merely prefetched because the viewport neared its
        border contributes a few blocks and loses. The incumbent is only
        unseated by a challenger that both leads the window and clears
        SERVER_VOTE_MIN, so a burst of prefetches cannot hand the screen to a
        neighbour and hand it straight back — the flapping that made tiles
        from the server next door print as if they were here.

        Returns None while no server has enough traffic to claim the screen,
        which leaves the incumbent (or "unknown yet") in place.

        A jump the client declared outright is not up for election, so while
        the grace window is open nothing here can unseat it.

        Callers hold `_index_lock`.
        """
        if now < self._jump_grace_until:
            return None
        cutoff = now - SERVER_VOTE_WINDOW_SECONDS
        while self._votes and self._votes[0][0] < cutoff:
            self._votes.popleft()
        if not self._votes:
            return None
        tally = Counter(server for _ts, server in self._votes)
        leader, votes = tally.most_common(1)[0]
        if leader == self.current_server:
            return leader
        if votes < SERVER_VOTE_MIN:
            return None
        # A tie must not unseat anyone: at a border both servers stream while
        # the viewport straddles them, and whichever happened to arrive first
        # would otherwise win.
        if self.current_server is not None and votes <= tally[self.current_server]:
            return None
        return leader

    def drain_server_changes(self) -> list:
        """Server switches noticed since the last call, as (old, new) pairs."""
        with self._index_lock:
            changes, self._server_changes = self._server_changes, []
            return changes


def sniff_forever(index: MapIndex, iface, bpf: str, stop: threading.Event) -> None:
    from scapy.sendrecv import sniff

    try:
        sniff(
            filter=bpf,
            iface=iface,
            prn=lambda pkt: index.feed_packet(pkt, iface),
            store=False,
            # Checked per packet, so a silent interface stays parked here
            # until traffic arrives; the deadline is enforced by the caller,
            # which is why this thread is a daemon.
            stop_filter=lambda _p: stop.is_set(),
        )
    except Exception as exc:  # one dead interface must not end the run
        if not stop.is_set():
            print(f"{C_DIM}iface {iface}: {exc}{C_RESET}", file=sys.stderr)


def add_capture_arguments(ap: argparse.ArgumentParser) -> None:
    """The transport flags every scanner shares."""
    ap.add_argument("--iface", help="pin one interface; omitted = all of them")
    ap.add_argument("--list-ifaces", action="store_true",
                    help="print the interfaces scapy can see, then exit")
    ap.add_argument("--seconds", type=int, default=None,
                    help="how long to listen (default: until Ctrl+C)")
    ap.add_argument("--all-tcp", action="store_true",
                    help="capture every TCP port, not just %d — use if the "
                         "game ever moves off it" % GAME_PORT)


def start_capture(index: MapIndex, args) -> tuple:
    """Start the sniffer threads. Returns `(stop_event, bpf)`.

    Exits the process on `--list-ifaces` or a missing scapy, so a caller can
    treat the return as "capture is running".
    """
    try:
        from scapy.arch import get_if_list
    except ImportError as exc:
        print(f"{C_ERR}scapy is not installed on this interpreter: {exc}{C_RESET}\n"
              f"  {sys.executable} -m pip install scapy zstandard", file=sys.stderr)
        raise SystemExit(1)

    if args.list_ifaces:
        for name in get_if_list():
            print(f"  {name}")
        raise SystemExit(0)

    # The endpoint IP is not stable and is dialled without DNS (protocol.md
    # §1), so the port is the only durable narrowing available; --all-tcp is
    # the escape hatch if even that changes.
    bpf = "tcp" if args.all_tcp else f"tcp port {GAME_PORT}"
    stop = threading.Event()
    for iface in ([args.iface] if args.iface else [None]):
        threading.Thread(target=sniff_forever, args=(index, iface, bpf, stop),
                         daemon=True).start()
    return stop, bpf


def diagnose(index: MapIndex, found: int, empty_hint: str) -> None:
    """Explain a thin result, so "nothing found" is never ambiguous."""
    if index.delivered and not index.packets:
        print(f"{C_ERR}npcap delivered {index.delivered} packet(s) but none "
              f"decoded as TCP-with-payload.{C_RESET} That is scapy failing to "
              f"map the datalink type — check for an 'Unable to guess datalink "
              f"type' warning above.")
    elif not index.delivered:
        print(f"{C_ERR}No packets at all.{C_RESET} Either the game is not "
              f"running, or npcap cannot see this interface — try "
              f"--list-ifaces and pin one with --iface.")
    elif not index.blocks_seen:
        print(f"{C_ERR}Packets arrived but no map data.{C_RESET} The game "
              f"sends it only while the map scrolls — keep dragging the map "
              f"for the whole run, not just at the start.")
    elif not found:
        print(f"{C_DIM}{empty_hint}{C_RESET}")
