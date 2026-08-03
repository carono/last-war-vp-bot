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

sys.path.insert(0, "tools/lib")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lastwar_proto as proto  # noqa: E402
import game_paths  # noqa: E402  (the game's port and process name)
from live_sniffer import C_DIM, C_ERR, C_RESET, LiveDecoder  # noqa: E402

# Both from the resolver: the port has moved before (LW_GAME_PORT), and the
# process name is the same answer every other tool in the repo asks it for.
GAME_PORT = game_paths.game_port()
GAME_PROCESS = game_paths.game_exe().lower()
# Outbound web ports the client also opens (translation is TLS on :443,
# see docs/research/chat.md) and which are never the game stream. Dropped from
# auto-detection so a capture narrows to the game connection, not the noise.
NON_GAME_PORTS = frozenset({80, 443})


def detect_game_ports() -> set:
    """The remote TCP port(s) the game is currently connected out on.

    The endpoint IP is dialled without DNS and the port is not stable across
    builds — it was :17935 historically and is :10012 on the current client —
    so a hard-coded port is a standing way for a capture to sniff the right
    interface and hear nothing while looking exactly like "nobody was panning".
    Read the live port straight off the game's own ESTABLISHED connections
    instead: the same TCP table Task Manager shows, no handle opened. Falls back
    to an empty set (caller then uses GAME_PORT) when the process is gone or
    psutil is not installed.

    Web ports (see NON_GAME_PORTS) are excluded — the client keeps HTTP/TLS
    connections open for translation and assets that are not the game stream.
    """
    try:
        import psutil
    except ImportError:
        return set()
    try:
        pids = {p.info["pid"] for p in psutil.process_iter(["pid", "name"])
                if (p.info["name"] or "").lower() == GAME_PROCESS}
        if not pids:
            return set()
        ports = set()
        for c in psutil.net_connections(kind="tcp"):
            if (c.pid in pids and c.raddr and c.status == "ESTABLISHED"
                    and c.raddr.port not in NON_GAME_PORTS):
                ports.add(c.raddr.port)
        return ports
    except Exception:
        # psutil raises AccessDenied / OSError on some Windows setups; a failed
        # probe must degrade to the fallback port, not take down the capture.
        return set()


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


class FrameLog:
    """Append-only JSONL transcript of every decoded frame, both directions.

    One JSON object per line — `{"seq", "ts", "direction", "name", "action",
    "payload"}` — so the file is readable with `jq` while the run is still
    going, and a truncated last line (the process was killed mid-write) costs
    one frame rather than the whole file. That is the reason for JSONL over
    one big JSON array.

    `payload` is what `proto.envelope_payload()` returns, which is where `_id`
    lives — 915 of the 1336 frames in the replayed capture carry one, and it
    is what pairs a request with its reply. The rest are server pushes, which
    have no request to pair with.

    `action` is the envelope's numeric `a`. It is kept because it is the only
    identifier on a frame the decoder could not name: 58 frames of that same
    replay had no command string, and those are precisely the ones somebody
    reading a transcript is hunting for.

    **Map traffic is most of the volume.** Over a 1336-frame sample of the
    saved captures the transcript came to 8.8 MB, of which `world.get.block`
    was 54% and `push.world.march.world.get.new` another 23% — the remaining
    862 frames, which is where an unknown command would be found, fit in 4 MB.
    So the size is reported on every progress tick, and the useful slice is
    one filter away:

        jq -c 'select(.name != "world.get.block")' dump.jsonl
        jq -r '.name' dump.jsonl | sort | uniq -c | sort -rn
    """

    def __init__(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # Buffered, not line-buffered: this is written from the sniffer thread
        # and a flush per frame would push back on packet capture. Flushed on
        # every progress tick and on close instead, so a reader tailing the
        # file is at most one tick behind.
        self.path = path
        self._fh = open(path, "w", encoding="utf-8")
        self.frames = 0
        self.failed = 0

    def write(self, direction: str, command, env) -> None:
        record = {
            "seq": self.frames,
            "ts": round(time.time(), 3),
            "direction": direction,
            "name": command,
            "action": env.get("a") if isinstance(env, dict) else None,
            "payload": proto.envelope_payload(env),
        }
        try:
            # `default=repr` rather than letting it raise: a frame carrying
            # something unserialisable must not take down a capture that is
            # otherwise fine, and repr keeps it inspectable.
            line = json.dumps(record, ensure_ascii=False, default=repr)
        except (TypeError, ValueError):
            self.failed += 1
            return
        self._fh.write(line + "\n")
        self.frames += 1

    def flush(self) -> None:
        try:
            self._fh.flush()
        except (ValueError, OSError):
            pass

    def size(self) -> int:
        """Bytes written so far, counting only what has reached the disk."""
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0

    def close(self) -> None:
        try:
            self._fh.close()
        except (ValueError, OSError):
            pass


def human_size(count: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f}{unit}" if unit == "B" else f"{count:.1f}{unit}"
        count /= 1024.0
    return f"{count:.1f}GB"


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
        # Set by start_capture() when --dump was given; see FrameLog.
        self.transcript: FrameLog | None = None

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
        if self.transcript is not None:
            # First thing, and outside every early return below: the whole
            # point of a transcript is the frames this scanner does *not*
            # otherwise care about. LiveDecoder.handle() already serialises
            # emit() under its own lock, so the writer needs none of its own.
            self.transcript.write(direction, command, env)
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


def add_capture_arguments(ap: argparse.ArgumentParser,
                          include_dump: bool = True) -> None:
    """The transport flags every scanner shares.

    `include_dump` gates the `--dump` transcript flag: only scanners built on
    `MapIndex` (whose `emit` writes the FrameLog) can honour it, so a plain
    `LiveDecoder` scanner passes `include_dump=False` rather than advertise a
    flag that would silently write nothing.
    """
    ap.add_argument("--iface", help="pin one interface; omitted = all of them")
    ap.add_argument("--list-ifaces", action="store_true",
                    help="print the interfaces scapy can see, then exit")
    ap.add_argument("--seconds", type=int, default=None,
                    help="how long to listen (default: until Ctrl+C)")
    if include_dump:
        ap.add_argument("--dump", metavar="PATH", default=None,
                        help="write every decoded frame, both directions, to "
                             "this file as JSONL — one frame per line, for "
                             "finding out what else the client and server say. "
                             "Map traffic is ~3/4 of the bytes; filter it out "
                             "with jq afterwards")
    ap.add_argument("--port", type=int, default=None, metavar="N",
                    help="capture this TCP port instead of auto-detecting the "
                         "game's live port from its own connections")
    ap.add_argument("--all-tcp", action="store_true",
                    help="capture every TCP port, not just the game's — the "
                         "catch-all if port auto-detection ever fails")
    # `--seed-server`, not `--server`: some scanners (secret_mission_capture)
    # already own a `--server` filter, and this is a different thing — the
    # initial on-screen server, not a filter.
    ap.add_argument("--seed-server", type=int, default=None, metavar="N",
                    help="seed the on-screen server id (from the running game, "
                         "e.g. read live via the Lua daemon). Without it the "
                         "server stays 'unknown yet' until the map is scrolled "
                         "and the first map response elects one; the weight-of-"
                         "traffic election still overrides this the moment real "
                         "map data disagrees.")


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
    # §1), so the port is the only durable narrowing available — but the port
    # itself moves between builds (:17935 → :10012), so it is read live off the
    # running game rather than hard-coded. Precedence: an explicit --port wins,
    # then --all-tcp, then auto-detection, then the historical GAME_PORT as a
    # last resort (with a warning, since a silent capture on the wrong port is
    # this tool's worst failure mode).
    if getattr(args, "port", None):
        bpf = f"tcp port {args.port}"
    elif args.all_tcp:
        bpf = "tcp"
    else:
        ports = detect_game_ports()
        if ports:
            bpf = " or ".join(f"tcp port {p}" for p in sorted(ports))
        else:
            bpf = f"tcp port {GAME_PORT}"
            print(f"{C_DIM}could not auto-detect the game's port "
                  f"(is {GAME_PROCESS} running, and psutil installed?) — "
                  f"falling back to :{GAME_PORT}. Pass --port N or --all-tcp "
                  f"if the capture stays silent.{C_RESET}", file=sys.stderr)
    if getattr(args, "dump", None):
        try:
            index.transcript = FrameLog(args.dump)
        except OSError as exc:
            # Refused now rather than after a long run that quietly recorded
            # nothing — the transcript is usually the reason for the run.
            print(f"{C_ERR}cannot write the transcript to {args.dump}: "
                  f"{exc}{C_RESET}", file=sys.stderr)
            raise SystemExit(1)
    # Seed the on-screen server before the sniffer threads run, so a scan that
    # has not panned the map yet still attributes tiles and prints "server N"
    # instead of "server unknown yet". This is only a starting value: the first
    # real map response re-elects by weight of traffic (see MapIndex._elect),
    # so a seed that is stale the moment the player is actually elsewhere is
    # corrected as soon as the map moves.
    if getattr(args, "seed_server", None):
        index.current_server = args.seed_server
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
