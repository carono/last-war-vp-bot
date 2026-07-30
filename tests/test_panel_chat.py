r"""Chat: the avatar field, and the lazy-load render window.

Three things are pinned here:

  * the reader now carries the sender's avatar version out of `getSenderInfo`
    (`head_pic_ver`), and the panel resolves it to the SAME on-disk ChatPhotos
    copy a message photo uses (`md5(f"{uid}_{ver}").jpg`);
  * a tab opens showing only the last page of its history, not the whole log —
    everything older stays in memory and pages in a chunk at a time;
  * paging in older history walks the window's top down by one page each step and
    stops at 0, and a plain live message never rebuilds the window (it only
    appends, leaving the top where the reader put it).

The first two blocks are pure (no Tk); the window-math block needs the panel and
so SKIPs under a python without customtkinter/PIL (e.g. the WSL python3). Run the
full set under the Windows Python:

    C:\Python312\python.exe tests\test_panel_chat.py
    python3 tests/test_panel_chat.py        # runs the pure blocks, SKIPs the rest
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# chat_reader imports lua_client at module load (a live-game dependency). Where the
# real module imports (the Windows Python that runs the panel), leave it be so the
# window-math block below can import the panel too; only stub it when it is missing
# (e.g. the WSL python3), which is enough to reach the pure parse function.
try:
    import lua_client   # noqa: F401
except Exception:        # noqa: BLE001
    sys.modules["lua_client"] = types.ModuleType("lua_client")
import chat_reader   # noqa: E402
import chat_assets   # noqa: E402


# --- the reader captures the avatar version --------------------------------

def test_parse_captures_avatar_version():
    line = ("ACT R roomId=alliance_935 seqId=42 st=1785000000000 post=0 type=1 "
            "uid=1234567 lang=ru gm=0 srv=935 hp=100 hpv=7 ismy=false alliance="
            + b"ABC".hex() + " sender=" + "Ник".encode().hex()
            + " msg=" + "привет".encode().hex() + " we=")
    rec = chat_reader._parse_record_line(line)
    assert rec is not None
    assert rec["head_pic"] == "100", rec
    assert rec["head_pic_ver"] == "7", rec
    assert rec["sender_name"] == "Ник" and rec["msg"] == "привет", rec


def test_parse_missing_avatar_is_blank():
    """A record with no head fields (older drain line) parses with empty avatar."""
    line = ("ACT R roomId=country_1 seqId=5 st=1785000000000 uid=9 "
            "msg=" + b"hi".hex())
    rec = chat_reader._parse_record_line(line)
    assert rec is not None
    assert rec["head_pic_ver"] == "" and rec["head_pic"] == "", rec


# --- the avatar resolves to the ChatPhotos copy ----------------------------

def test_avatar_path_matches_photo_scheme():
    uid, ver = "700123456", "12"
    h = hashlib.md5(f"{uid}_{ver}".encode()).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        old = chat_assets.PHOTOS_DIR
        chat_assets.PHOTOS_DIR = tmp
        try:
            assert chat_assets.avatar_path(uid, ver) is None      # not cached yet
            sub = os.path.join(tmp, uid[-6:])
            os.makedirs(sub, exist_ok=True)
            open(os.path.join(sub, f"{h}.jpg"), "wb").close()
            got = chat_assets.avatar_path(uid, ver)
            assert got and os.path.isfile(got), got
            assert chat_assets.avatar_path(uid, "") is None       # no version
            assert chat_assets.avatar_path("", ver) is None       # no uid
        finally:
            chat_assets.PHOTOS_DIR = old


# --- the lazy-load render window (needs the panel) -------------------------

class _FakeText:
    """A stand-in for the chat Text view that only counts rendered message lines.

    Every message line ends in a bare "\n" insert; the load-more header and the
    per-message spans carry other text, so counting exact "\n" inserts is exactly
    the number of records drawn. A clear (delete) resets the count.
    """

    def __init__(self):
        self.lines = 0

    def configure(self, **kw):
        pass

    def delete(self, *a):
        self.lines = 0

    def insert(self, index, text, *tags):
        if text == "\n":
            self.lines += 1

    def image_create(self, *a, **k):
        pass

    def tag_add(self, *a):
        pass

    def tag_bind(self, *a, **k):
        pass

    def tag_configure(self, *a, **k):
        pass

    def index(self, *a):
        return "1.0"

    def see(self, *a):
        pass

    def yview(self):
        return (0.0, 1.0)


def _stand_in(pm, msgs):
    """A Panel stand-in with just the state the window methods touch."""
    from panel import i18n as i18nmod

    P = types.SimpleNamespace()
    P._i18n = i18nmod.I18n("en")
    P._chat_msgs = {"world": list(msgs)}
    P._chat_offset = {"world": 0}
    P._chat_tree_rows = {"world": 0}
    P._chat_img_cache = {}
    P._photo_seq = 0
    P._chat_trees = {"world": _FakeText()}
    # Bound instance methods; the two staticmethods are taken as plain functions.
    for name in ("_t", "_render_msg_line", "_insert_chat_text", "_update_chat_tree",
                 "_rebuild_chat_view", "_chat_load_older", "_chat_type_of_view"):
        setattr(P, name, pm.Panel.__dict__[name].__get__(P))
    P._chat_clear_view = pm.Panel._chat_clear_view
    P._chat_view_at_bottom = pm.Panel._chat_view_at_bottom
    return P


def _records(n):
    return [{"ts": i + 1, "room_id": "country_1", "sender_uid": "",
             "head_pic_ver": "", "sender_name": f"u{i}", "alliance": "",
             "is_mine": False, "msg": f"m{i}"} for i in range(n)]


def test_lazy_window_pages_in_chunks():
    try:
        import panel.__main__ as pm
    except Exception as exc:      # noqa: BLE001 -- no customtkinter/PIL/Tk here
        print(f"  SKIP test_lazy_window_pages_in_chunks: {exc}")
        return

    page = pm.CHAT_PAGE
    total = page * 2 + 50               # 250 with the default page of 100
    P = _stand_in(pm, _records(total))
    fake = P._chat_trees["world"]

    # Open on the newest page only.
    P._chat_offset["world"] = max(0, total - page)
    P._chat_tree_rows["world"] = 0
    P._rebuild_chat_view("world")
    assert fake.lines == page, fake.lines
    assert P._chat_offset["world"] == total - page

    # Scroll-up pages in one more chunk, and the whole window is redrawn.
    P._chat_load_older("world")
    assert P._chat_offset["world"] == total - 2 * page
    assert fake.lines == 2 * page, fake.lines

    # A second page reaches the very top (offset clamps at 0) and shows everything.
    P._chat_load_older("world")
    assert P._chat_offset["world"] == 0
    assert fake.lines == total, fake.lines

    # A live message only appends; the window top (offset) does not move.
    P._chat_msgs["world"].append(_records(1)[0])
    P._update_chat_tree("world")
    assert P._chat_offset["world"] == 0
    assert fake.lines == total + 1, fake.lines


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
