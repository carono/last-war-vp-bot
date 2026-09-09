r"""The black box: what the panel was doing when the client died (#2678).

The person's instruction was one sentence — «давай расширенное логирование веди» — and
it comes after a day in which «клиент падает» could only be answered with arithmetic
over `debug.log`: how many fresh pids in an hour, how many panel restarts beside them.
That answers HOW OFTEN and never WHY. Every crash so far has been explained by digging
the same four things out by hand, hours later, out of a log that had already rotated.

So the panel keeps a small recorder per profile, and when the client goes away it writes
one block into that profile's own `debug.log` — never `panel.log`, which the person
reads and which has no rotation of its own.

**NOTHING HERE ASKS THE GAME ANYTHING.** That is the rule this had to be written under
(`CLAUDE.md`, «Read once, then LISTEN»): a diagnostic that costs a chunk is a chunk the
robbery did not get, and a diagnostic that costs a chunk WHILE THE CLIENT IS DYING is
worse than useless. Everything below is something the panel already knows — a counter it
keeps, a name it computed anyway, a stamp it wrote when it last polled.

What the block answers, in the order somebody reads them:

  * WHEN — the death, to the second, and how long the panel had known that pid;
  * WHAT WE WERE DOING — the last chunk: which caller, which marker, how long ago;
  * THE ATTACH — hijacks since the last block, park tries each, misses, regions
    abandoned, and the busiest labels, straight off `hijack_call.STATS`;
  * THE PANEL — its head and boot, so a death that follows a restart says so itself;
  * THE RUN-UP — the last :data:`KEEP` notes, which is the ring buffer below;
  * THE WINDOWS EVIDENCE — `tools/crash_report.py` in a thread, when it is allowed.

Three levels, switched by ``LW_CRASH_LOG``:

  ``off``   nothing at all — no recorder, no block;
  ``on``    (default) the block, and the notes the panel makes anyway;
  ``full``  …and one note per chunk, which is the only setting that costs anything per
            call, and even then it is a `deque.append`.
"""
from __future__ import annotations

import collections
import os
import threading
import time

#: How many notes are kept per profile. A crash is explained by the last minute, not by
#: the last hour, and a bounded deque is the whole of the memory cost.
KEEP = 200

#: How often the Windows evidence may be asked for, in seconds. It is a PowerShell call
#: over the event log — nothing to do with the game, but not free either, and a client
#: that dies five times in ten minutes must not spawn five of them.
REPORT_EVERY_SEC = 600.0

_OFF, _ON, _FULL = "off", "on", "full"

#: The recorder of the LINK, which is the machine's and not an account's — deliberately,
#: and it is the one exception to «a profile is a whole panel of its own». One Windows
#: session holds one client, so `LuaService` is shared by every profile open on it
#: (`panel/runtime/lua_service.py`, #2660): a chunk's caller, an attach and a refusal are
#: facts about that shared link, exactly like the port and the claim. The crash block
#: prints this beside the dying profile's own notes and says which is which.
LINK = ":link"


def level() -> str:
    """``off`` / ``on`` / ``full`` — read from the environment on every call.

    Deliberately not cached: turning the detail down is something a person does to a
    panel that is already running badly, and a value read once at import would need the
    restart this whole file exists to make unnecessary.
    """
    got = (os.environ.get("LW_CRASH_LOG") or "").strip().lower()
    return got if got in (_OFF, _ON, _FULL) else _ON


def on() -> bool:
    return level() != _OFF


def verbose() -> bool:
    return level() == _FULL


class Recorder:
    """One profile's run-up to a crash. Every method is cheap and none may raise."""

    def __init__(self, profile: str) -> None:
        self.profile = str(profile or "")
        self._lock = threading.Lock()
        self._ring: collections.deque = collections.deque(maxlen=KEEP)
        #: The last chunk, kept as a SLOT rather than a note, so «what were we doing»
        #: costs one assignment per call at every level instead of a deque append.
        self.last_chunk = ("", "", 0.0)      # (caller, marker, when)
        #: When this pid was first seen, so the block can say how long the client lived
        #: without asking Windows for a creation time.
        self._pid = 0
        self._pid_at = 0.0
        self._hijack_was: dict = {}
        self._reported_at = 0.0

    # -- the cheap half, called from the hot paths ---------------------------
    def chunk(self, caller: str, marker: str = "") -> None:
        self.last_chunk = (str(caller or ""), str(marker or ""), time.time())
        if verbose():
            self.note("chunk", f"{caller} {marker}".strip())

    def note(self, kind: str, text: str) -> None:
        """One stamped line of the run-up. Never raises: this is a diagnostic."""
        try:
            with self._lock:
                self._ring.append((time.time(), str(kind), str(text)[:200]))
        except Exception:                     # noqa: BLE001 — a note, never the panel
            pass

    def saw_pid(self, pid) -> None:
        """The status poll's own reading, folded in: a new pid restarts the clock."""
        try:
            pid = int(pid or 0)
        except (TypeError, ValueError):
            return
        if pid and pid != self._pid:
            self._pid, self._pid_at = pid, time.time()
            self.note("client", f"pid {pid} is up")

    # -- the block, written once when the client goes ------------------------
    def died(self, rt) -> None:
        """Write the whole block into this profile's `debug.log`. Called on the edge."""
        if not on():
            return
        try:
            log = rt.dbg("crash")
        except Exception:                     # noqa: BLE001 — no logger, no block
            return
        try:
            for line in self._block(rt):
                log.info("%s", line)
        except Exception as exc:              # noqa: BLE001 — a diagnostic, never the poll
            try:
                log.warning("the crash block could not be built: %s", exc)
            except Exception:                 # noqa: BLE001
                pass
        self._ask_windows(rt)

    def _block(self, rt) -> list:
        now = time.time()
        out = ["--- КЛИЕНТ УМЕР / the client is gone "
               f"[{time.strftime('%H:%M:%S', time.localtime(now))}] "
               f"profile={self.profile} ---"]
        pid_for = (now - self._pid_at) if self._pid_at else 0.0
        out.append(f"client: pid={self._pid or '?'} known to this panel for "
                   f"{pid_for:.0f}s")
        who, marker, when = self.last_chunk
        out.append("last chunk: "
                   + (f"{who or '?'} marker={marker or '-'} {now - when:.1f}s ago"
                      if when else "none since this panel came up"))
        out.append("panel: " + self._panel(rt))
        out.append("link: " + self._link(rt))
        out.append("recovery: " + self._recovery(rt))
        out.append("hijacks: " + self._hijacks())
        out.append(f"run-up, last {KEEP} notes of this profile:")
        out.extend(self._notes())
        if self.profile != LINK:
            link = of(LINK)
            who, marker, when = link.last_chunk
            out.append("the LINK is shared by every profile on this machine; its last "
                       "chunk was " + (f"{who or '?'} marker={marker or '-'} "
                                       f"{now - when:.1f}s ago" if when else "none"))
            out.append(f"run-up, last {KEEP} notes of the link:")
            out.extend(link._notes())            # noqa: SLF001 — one module, one contract
        out.append("--- end of the crash block ---")
        return out

    def _notes(self) -> list:
        with self._lock:
            notes = list(self._ring)
        if not notes:
            return ["  (nothing recorded — LW_CRASH_LOG=full records every chunk)"]
        return [f"  {time.strftime('%H:%M:%S', time.localtime(at))} [{kind}] {text}"
                for at, kind, text in notes]

    @staticmethod
    def _panel(rt) -> str:
        try:
            from . import updates                    # noqa: PLC0415

            boot = updates.boot()
            up = time.time() - float(boot.get("at") or 0.0)
            return (f"head={boot.get('head') or '?'} pid={boot.get('pid')} "
                    f"up {up:.0f}s")
        except Exception as exc:                     # noqa: BLE001
            return f"unreadable ({exc})"

    @staticmethod
    def _link(rt) -> str:
        """The link as the panel already has it — `up`/`ready`/`error`, nothing asked.

        `ready()` reads the plumbing verdict the status poll has just written and
        `error()` is whatever last refused a chunk. Neither touches the game, which is
        the rule this whole module is written under.
        """
        try:
            game = rt.game
            return (f"up={bool(game.up())} ready={bool(game.ready())} "
                    f"attached_pid={game.client_pid()} error={game.error() or '-'}")
        except Exception as exc:                     # noqa: BLE001
            return f"unreadable ({exc})"

    @staticmethod
    def _recovery(rt) -> str:
        try:
            st = rt.recovery.state()
            keep = ("deaf_for", "strikes", "restarts", "kicks", "cooldown_left",
                    "kick_hold_left", "stalled_for")
            return " ".join(f"{k}={st.get(k)}" for k in keep if k in st)
        except Exception as exc:                     # noqa: BLE001
            return f"unreadable ({exc})"

    def _hijacks(self) -> str:
        """The attach counters, as a DELTA since the last block — never a lifetime total.

        A cumulative count over a panel that has been open all day answers a different
        question than «what was the attach doing in the minutes before this death».
        """
        try:
            import hijack_call                       # noqa: PLC0415

            now = hijack_call.stats()
        except Exception:                            # noqa: BLE001 — no link, no counters
            return "unreadable (the link has never attached)"
        was, self._hijack_was = self._hijack_was, now
        if not was:
            return "first block since this panel came up — nothing to compare against"
        n = now.get("n", 0) - was.get("n", 0)
        if n <= 0:
            return "no hijack at all since the last block"
        tries = now.get("park_tries", 0) - was.get("park_tries", 0)
        miss = now.get("misses", 0) - was.get("misses", 0)
        left = now.get("abandoned", 0) - was.get("abandoned", 0)
        by = {k: v - was.get("by_label", {}).get(k, 0)
              for k, v in (now.get("by_label") or {}).items()}
        top = sorted(((v, k) for k, v in by.items() if v > 0), reverse=True)[:6]
        return (f"{n} since the last block, {tries / n:.1f} park tries each, "
                f"{miss} gave up, {left} regions abandoned; "
                + " ".join(f"{k}={v}" for v, k in top))

    def _ask_windows(self, rt) -> None:
        """`tools/crash_report.py`, in a thread, at most once per :data:`REPORT_EVERY_SEC`.

        The event log is not the game: asking it costs the client nothing. It costs a
        PowerShell start-up, which is why it is throttled and off the poll's thread —
        the status poll must come round again whatever this does.
        """
        now = time.time()
        if now - self._reported_at < REPORT_EVERY_SEC:
            return
        self._reported_at = now
        threading.Thread(target=self._report_now, args=(rt,), daemon=True,
                         name=f"crashlog-{self.profile}").start()

    def _report_now(self, rt) -> None:
        try:
            import subprocess                        # noqa: PLC0415
            import sys                               # noqa: PLC0415
            from pathlib import Path                 # noqa: PLC0415

            tool = Path(__file__).resolve().parents[2] / "tools" / "crash_report.py"
            out = subprocess.run(
                [sys.executable, str(tool), "--days", "1", "--profile", self.profile],
                capture_output=True, text=True, timeout=120)
            log = rt.dbg("crash")
            said = (out.stdout or out.stderr or "").strip()
            if not said:
                log.info("the Windows event log said nothing about this one")
                return
            log.info("Windows evidence (tools/crash_report.py):")
            for line in said.splitlines()[:60]:
                log.info("  %s", line)
        except Exception as exc:                     # noqa: BLE001 — evidence, never the panel
            try:
                rt.dbg("crash").info("the Windows evidence could not be read: %s", exc)
            except Exception:                        # noqa: BLE001
                pass


#: One recorder per PROFILE NAME. Keyed by the name and never by «the active profile»,
#: which is the mistake `CLAUDE.md` («A profile is a whole panel of its own») names: a
#: module-level answer to «whose is this» is how one account's captures ended up
#: narrowed by another's pid list.
_BY_PROFILE: dict = {}
_LOCK = threading.Lock()


def of(profile: str) -> Recorder:
    """The recorder for ``profile``, made on first need."""
    key = str(profile or "")
    with _LOCK:
        rec = _BY_PROFILE.get(key)
        if rec is None:
            rec = _BY_PROFILE[key] = Recorder(key)
        return rec


def for_rt(rt) -> "Recorder | None":
    """The recorder of whichever profile ``rt`` belongs to, or ``None`` when switched off."""
    if not on():
        return None
    try:
        return of(str(rt.profiles.active or ""))
    except Exception:                                # noqa: BLE001 — never the caller's problem
        return None


def note(rt, kind: str, text: str) -> None:
    """One note, from anywhere, with every failure swallowed. The usual entry point."""
    rec = for_rt(rt)
    if rec is not None:
        rec.note(kind, text)
