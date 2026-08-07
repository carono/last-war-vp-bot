r"""What the panel must NOT accumulate while it is left open (task #1177).

The panel is meant to run for days. Two complaints started this: it got slower the
longer it stayed open, and it opened before it was ready. Both came down to things
that grew per event instead of per widget — a Tk tag with three callbacks per
coordinate ever printed, three more per pass of the mouse over a scrollable page, a
strong reference to every row any page had ever redrawn, an unbounded picture cache
— and to a boot that carried on registering all of that after the splash had gone.

So this file is a set of *growth* assertions. Each one does the same work twice and
insists the second time costs nothing extra:

  * coordinate links leave no tag behind, and still jump to the right tile;
  * the chat-picture cache evicts, and takes the click metadata with it;
  * the retranslation registry forgets a destroyed row;
  * entering and leaving a scroll area does not register new Tk callbacks;
  * the chat store's running total matches a real COUNT(*);
  * the boot gate holds the splash until the systems report in — and lets go at its
    ceiling rather than never.

The Tk cases need a display; they say SKIP without one::

    python3 tests/test_panel_leaks.py
    C:\Python312\python.exe tests\test_panel_leaks.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_SKIPPED = []


def _skip(name: str, exc=None) -> None:
    _SKIPPED.append(name)
    print(f"  SKIP {name}: {exc}" if exc else f"  SKIP {name}: no tkinter / display")


def _tk():
    """A hidden root, or None where there is no display."""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        return root
    except Exception:                                    # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Coordinate links: one binding per widget, not one per coordinate.
# ---------------------------------------------------------------------------
class _LinkHost:
    """A clickable coordinate needs no host at all now — the mechanics are shared
    (panel/widgets.py), because the log and the chat views both carry them."""

    def __init__(self):
        from panel import widgets
        self.clicked = []
        self._click = None

        def bind(w):
            # The handler is handed back so a test can aim a click without a pointer.
            self._click = widgets.bind_coord_links(w, self._jump)

        self._bind_coord_links = bind
        self._insert_coord_link = widgets.insert_coord_link

    def _jump(self, x, y, server):
        self.clicked.append((x, y, server))


def test_coordinate_links_add_no_tags_and_still_jump():
    root = _tk()
    if root is None:
        _skip("coordinate links")
        return
    try:
        import tkinter as tk
        text = tk.Text(root, width=60, height=10)
        text.pack()
        text.tag_config("coordlink", underline=True)
        host = _LinkHost()
        host._bind_coord_links(text)
        base = len(text.tag_names())

        for i in range(200):
            text.insert("end", "found something at ")
            host._insert_coord_link(text, f"@[{100 + i},{200 + i}]")
            text.insert("end", "\n")
        # The whole point: two hundred links, not two hundred tags. Before the fix
        # each one laid down a `c<N>` tag carrying three fresh callbacks, and
        # nothing took them off again when the line scrolled out of the widget.
        assert len(text.tag_names()) == base, (len(text.tag_names()), base)

        # …and the link still knows where it goes: what was clicked is read back
        # off the widget instead of out of a closure kept alive for it. The window
        # has to be on screen for that: an unmapped Text lays out no lines, so
        # there is no box to aim the click at.
        root.deiconify()
        root.update()
        span = text.tag_nextrange("coordlink", "1.0")
        assert span, "no coordinate was tagged"
        box = text.bbox(span[0])
        if box is None:                          # the line is not laid out (no display)
            _skip("coordinate click")
            return
        x, y, w, h = box
        host._click(type("E", (), {"x": x + w // 2, "y": y + h // 2})())
        assert host.clicked == [(100, 200, None)], host.clicked
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# The chat picture cache is an LRU, and the click metadata follows it out.
# ---------------------------------------------------------------------------
class _ImageHost:
    def __init__(self, cap):
        from panel.tabs import chat as chatmod
        chatmod.CHAT_IMG_CACHE_MAX = cap
        self._chat_img_cache = {}
        self._photo_meta = {}
        self._trim_chat_images = chatmod.ChatTab._trim_chat_images.__get__(self)


def test_chat_image_cache_evicts_oldest_and_keeps_the_placeholder():
    from panel.tabs import chat as pm
    was = pm.CHAT_IMG_CACHE_MAX
    try:
        host = _ImageHost(4)
        host._chat_img_cache[("__avatar_placeholder__", 20)] = "placeholder"
        for i in range(10):
            key = (f"/tmp/pic{i}.jpg", 110)
            host._chat_img_cache[key] = f"img{i}"
            host._photo_meta[f"img{i}"] = ("uid", str(i), key[0])
            host._trim_chat_images()

        assert len(host._chat_img_cache) <= 4, len(host._chat_img_cache)
        # The shared fallback avatar is never the thing that gets dropped.
        assert ("__avatar_placeholder__", 20) in host._chat_img_cache
        # What went out took its click metadata with it, or `_photo_meta` would be
        # the unbounded dict the cache no longer is.
        assert len(host._photo_meta) <= 4, len(host._photo_meta)
        assert "img0" not in host._photo_meta
        assert "img9" in host._photo_meta
    finally:
        pm.CHAT_IMG_CACHE_MAX = was


# ---------------------------------------------------------------------------
# The retranslation registry holds widgets weakly.
# ---------------------------------------------------------------------------
def test_the_translation_registry_forgets_a_destroyed_row():
    root = _tk()
    if root is None:
        _skip("translation registry")
        return
    try:
        from tkinter import ttk
        from panel import runtime

        # The registry belongs to the runtime's Translator now, which is what the
        # panel's `_tr` is a one-line face for — so this tests the owner directly.
        tr = runtime.Translator("en")
        page = ttk.Frame(root)
        for _ in range(50):
            tr.tr(ttk.Label(page), "timers.reload").pack()
        assert tr.registry_size() == 50, tr.registry_size()

        # A page repaint destroys its rows. The registry must not be what keeps
        # them alive — the Command Post redraws every nine seconds and the
        # inventory on every keystroke in its search box.
        rows = list(page.winfo_children())
        while rows:
            rows.pop().destroy()          # nothing left holding the last one
        tr.sweep()
        assert tr.registry_size() == 0, tr.registry_size()
        # The next sweep is due later, not on the very next registration.
        assert tr._watermark >= runtime.i18n.REGISTRY_SWEEP, tr._watermark
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# The wheel is routed, not re-bound on every <Enter>.
# ---------------------------------------------------------------------------
def test_hovering_a_scroll_area_registers_no_new_callbacks():
    root = _tk()
    if root is None:
        _skip("scroll wheel")
        return
    try:
        from panel.widgets import ScrollableFrame
        area = ScrollableFrame(root)
        area.pack(fill="both", expand=True)
        root.update()
        canvas = area._canvas
        before = len(canvas._tclCommands or ())

        for _ in range(40):
            area._enter()
            area._leave()

        after = len(canvas._tclCommands or ())
        # Each pass used to cost three `bind_all` registrations that `unbind_all`
        # never freed — forty crossings, a hundred and twenty dead callbacks.
        assert after == before, (before, after)

        # A second area does not steal the wheel from the first: both are routed.
        other = ScrollableFrame(root)
        other.pack()
        root.update()
        other._enter()
        import panel.widgets as w
        assert w._wheel_target is other, w._wheel_target
        other._leave()
        assert w._wheel_target is None, w._wheel_target
    finally:
        root.destroy()


# ---------------------------------------------------------------------------
# The chat store's running total is the real one.
# ---------------------------------------------------------------------------
def test_chat_store_total_tracks_count_without_rescanning():
    from panel.chat_history import ChatHistoryStore
    with tempfile.TemporaryDirectory() as tmp:
        store = ChatHistoryStore(str(Path(tmp) / "chat.db"))
        assert store.total() == 0
        for i in range(25):
            store.append({"ts": 1000.0 + i, "sender_uid": "7", "sender_name": "n",
                          "msg": f"m{i}", "room_id": "country_1", "chat_type": "world"})
        assert store.total() == store.count() == 25, (store.total(), store.count())
        # A repeat is dropped by the identity index — and must not be counted.
        store.append({"ts": 1000.0, "sender_uid": "7", "sender_name": "n",
                      "msg": "m0", "room_id": "country_1", "chat_type": "world"})
        assert store.total() == store.count() == 25, (store.total(), store.count())
        store.close()


# ---------------------------------------------------------------------------
# The boot gate: the splash holds until the systems are up.
# ---------------------------------------------------------------------------
class _Boot:
    """Enough of a Panel for `_await_boot`: a step queue, an end flag, a splash."""

    def __init__(self):
        import queue
        import panel.__main__ as pm
        self._boot_step = queue.Queue()
        self._boot_done = threading.Event()
        self.steps = []
        self.said = []
        self.updates = 0
        self._dbg = type("D", (), {"warning": lambda *a, **k: None,
                                   "info": lambda *a, **k: None})()
        self._await_boot = pm.Panel._await_boot.__get__(self)
        self._boot_at = pm.Panel._boot_at.__get__(self)

    def _splash_step(self, key, progress):
        self.steps.append((key, progress))

    def update(self):
        self.updates += 1

    def _say(self, tag, key, **fmt):
        self.said.append(key)


def test_the_boot_gate_waits_for_the_systems_and_shows_their_steps():
    boot = _Boot()

    def systems():
        for key, at in (("splash.monitors", 0.68), ("splash.chat", 0.76),
                        ("splash.daemon", 0.9)):
            time.sleep(0.05)
            boot._boot_at(key, at)
        time.sleep(0.05)
        boot._boot_at("splash.systems", 1.0)
        boot._boot_done.set()

    worker = threading.Thread(target=systems, daemon=True)
    t0 = time.time()
    worker.start()
    boot._await_boot()
    took = time.time() - t0

    assert boot._boot_done.is_set(), "the gate let go before the systems were up"
    assert took >= 0.2, f"the gate returned in {took:.2f}s — it did not wait"
    # Every phase reached the splash, the last one included: it is reported just
    # before the end flag, so a gate that stopped draining on the flag would lose it.
    assert [k for k, _ in boot.steps] == ["splash.monitors", "splash.chat",
                                          "splash.daemon", "splash.systems"], boot.steps
    assert boot.said == [], boot.said
    assert boot.updates > 0, "the gate never pumped Tk — after(0) work would stall"


def test_the_boot_gate_has_a_ceiling():
    import panel.__main__ as pm
    was = pm.BOOT_MAX_WAIT_SEC
    pm.BOOT_MAX_WAIT_SEC = 0.3
    try:
        boot = _Boot()                    # nothing ever sets _boot_done
        t0 = time.time()
        boot._await_boot()
        took = time.time() - t0
        assert took < 3.0, f"the ceiling did not fire ({took:.2f}s)"
        # …and the panel says so rather than opening silently half-started.
        assert boot.said == ["log.boot.slow"], boot.said
    finally:
        pm.BOOT_MAX_WAIT_SEC = was


# ---------------------------------------------------------------------------
# Repeating callbacks: one chain per name, whatever the call graph does.
# ---------------------------------------------------------------------------
class _Loops:
    """A counting `after`, driven through the runtime's Ticker (the panel's `_arm`)."""

    def __init__(self):
        from panel import runtime
        self.armed, self.cancelled, self.seq = [], [], 0
        self._ticker = runtime.Ticker(self)
        self._arm = self._ticker.arm
        self._disarm = self._ticker.disarm
        self._disarm_all = self._ticker.disarm_all

    @property
    def _loops(self):
        return self._ticker._loops

    def after(self, delay, func):
        # A Ticker also starts the WINDOW's hand-over pump (#1226) — one chain of its
        # own, re-arming for the life of the window, and not one of the NAMED loops
        # this class is counting. Left off the books so `pending` keeps its meaning.
        if getattr(func, "__self__", None) is getattr(self, "_lw_tk_poster", None):
            return "pump"
        self.seq += 1
        job = f"job{self.seq}"
        self.armed.append(job)
        return job

    def after_cancel(self, job):
        self.cancelled.append(job)

    @property
    def pending(self):
        return set(self.armed) - set(self.cancelled)


def test_arming_a_loop_twice_leaves_one_chain():
    loops = _Loops()
    for _ in range(20):
        loops._arm("log", 120, lambda: None)
    # Twenty starts, one live chain. This is the whole point: a loop that is
    # started from a second place — a repaint that re-arms the repaint — used to
    # double the tick rate for the rest of the session, invisibly and for ever.
    assert len(loops.pending) == 1, loops.pending
    assert len(loops.cancelled) == 19, loops.cancelled

    # Different names are different chains; they do not cancel each other.
    for name in ("status", "chat", "timer_rows"):
        loops._arm(name, 1000, lambda: None)
    assert len(loops.pending) == 4, loops.pending

    # …and the window takes all of them with it.
    loops._disarm_all()
    assert loops.pending == set(), loops.pending
    assert loops._loops == {}, loops._loops
    # Cancelling twice is not an error — a callback that has already fired is gone.
    loops._disarm("log")


def test_the_panels_repeating_callbacks_all_go_through_the_registry():
    """No bare `self.after(<delay>, <the same method>)` re-arm is left anywhere.

    A grep, deliberately: the guarantee above is only worth anything if every loop
    actually uses it, and the next one added is the one that will not.
    """
    import re
    root = Path(__file__).resolve().parents[1] / "panel"
    offenders = []
    for path in sorted(root.glob("*.py")):
        if path.name == "splash.py":            # its own window, torn down at boot
            continue
        text = path.read_text(encoding="utf-8")
        for func in re.finditer(r"\n    (?:async )?def (\w+)\(", text):
            name = func.group(1)
            body = text[func.end():]
            nxt = re.search(r"\n    (?:@|def )", body)
            body = body[:nxt.start()] if nxt else body
            # a method that schedules ITSELF is a loop
            if re.search(r"\.after\(\s*[^,]+,\s*self(?:\.app)?\.%s\b" % name, body):
                offenders.append(f"{path.name}:{name}")
    assert offenders == [], f"loops still armed with a bare after(): {offenders}"


def test_a_language_hook_is_registered_once():
    from panel import runtime

    tr = runtime.Translator("en")
    marker = []

    def repaint():
        marker.append(1)

    for _ in range(10):
        tr.hook(repaint)
    assert tr._hooks == [repaint], tr._hooks

    # A lambda can never be recognised by identity, so it is named instead —
    # rebuilding the page that registers it must not stack another copy.
    for _ in range(10):
        tr.hook(lambda: marker.append(2), key="tab-titles")
    assert len(tr._hooks) == 2, len(tr._hooks)

    for hook in tr._hooks:
        hook()
    assert marker == [1, 2], marker


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed"
          + (f" ({len(_SKIPPED)} skipped)" if _SKIPPED else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
