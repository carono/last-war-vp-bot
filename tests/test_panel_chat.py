r"""Chat: the avatar field, the SQLite history store, and the lazy-load paging.

Four things are pinned here:

  * the reader carries the sender's avatar version out of `getSenderInfo`
    (`head_pic_ver`), and the panel resolves it to the SAME on-disk ChatPhotos
    copy a message photo uses (`md5(f"{uid}_{ver}").jpg`);
  * the SQLite store (`panel/chat_history.py`) files each message under its tab,
    dedupes on identity, and pages newest→oldest;
  * a tab opens showing only the last page (`CHAT_PAGE`) read from the store, and
    scrolling to the top pages the next chunk in FROM the store — memory holds only
    what has been paged in, never the whole log;
  * paging older prepends the chunk and holds the reader's line in place; a live
    message only appends.

The parse, avatar and store blocks are pure (sqlite3 is stdlib, no Tk) and always
run. The window-math block needs the panel and so SKIPs under a python without
tkinter/PIL/Tk (e.g. the WSL python3). Run the full set under Windows:

    C:\Python312\python.exe tests\test_panel_chat.py
    python3 tests/test_panel_chat.py        # runs the pure blocks, SKIPs the rest
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "panel", _REPO / "tools", _REPO / "tools" / "lib"):
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
import chat_reader        # noqa: E402
import chat_assets        # noqa: E402
import chat_history       # noqa: E402  (panel/chat_history.py — pure sqlite3)


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


# --- the emoji / sticker catalogues (picker source) ------------------------

def test_emoji_and_sticker_catalogues():
    emojis = chat_assets.emoji_catalogue()
    stickers = chat_assets.sticker_catalogue()
    # These come from the extracted sprites; the repo ships them, so both are non-empty.
    assert emojis and stickers, (len(emojis), len(stickers))
    for e in emojis:
        assert e["id"] and e["hex"] and os.path.isfile(e["path"]), e
    ids = [int(s["id"]) for s in stickers]
    assert ids == sorted(ids)                    # stickers ordered by numeric id
    for s in stickers:
        assert s["id"] and os.path.isfile(s["path"]), s


# --- the SQLite store ------------------------------------------------------

def _rec(i, room="alliance_935"):
    return {"ts": float(i), "sender_uid": f"u{i}", "sender_name": f"n{i}",
            "msg": f"m{i}", "room_id": room, "seq_id": str(i),
            "chat_type": chat_history.classify_room(room)}


def _store(tmp):
    return chat_history.ChatHistoryStore(os.path.join(tmp, "p", "chat_history.db"))


def test_store_pages_newest_then_older():
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        for i in range(250):
            s.append(_rec(i))
        s.append(_rec(0))                      # a repeat is dropped on identity
        assert s.count() == 250 and s.count("alliance") == 250

        recent = s.recent("alliance", 100)
        assert len(recent) == 100
        assert [r["ts"] for r in recent] == [float(i) for i in range(150, 250)]  # oldest→newest

        older = s.older("alliance", recent[0]["ts"], 100)
        assert [r["ts"] for r in older] == [float(i) for i in range(50, 150)]
        assert s.has_older("alliance", 150.0) is True
        assert s.has_older("alliance", 0.0) is False
        s.close()


def test_store_files_by_tab_and_imports_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        # A legacy raw log to migrate.
        jsonl = os.path.join(tmp, "chat_log.jsonl")
        with open(jsonl, "w", encoding="utf-8") as fh:
            for i in range(5):
                fh.write(json.dumps(_rec(i, "country_1"), ensure_ascii=False) + "\n")
            for i in range(3):
                fh.write(json.dumps(_rec(100 + i, "alliance_9"), ensure_ascii=False) + "\n")
        s = _store(tmp)
        n = s.import_jsonl(jsonl)
        assert n == 8, n
        assert s.count("world") == 5 and s.count("alliance") == 3
        assert s.import_jsonl(jsonl) == 0          # idempotent — nothing new
        s.close()


# --- the DM contact list ---------------------------------------------------

def _dm(peer, i, self_uid="1000", mine=False, name=None):
    room = f"custom_{peer}_{self_uid}_v2"
    return {"ts": float(i), "sender_uid": (self_uid if mine else peer),
            "sender_name": (name or f"peer{peer}"), "msg": f"m{i}",
            "room_id": room, "chat_type": "dm",
            "head_pic_ver": ("" if mine else "7")}


def test_dm_peer_uid_from_either_room_order():
    assert chat_history.dm_peer_uid("custom_A_1000_v2", "1000") == "A"   # peer first
    assert chat_history.dm_peer_uid("custom_1000_B_v2", "1000") == "B"   # self first
    assert chat_history.dm_peer_uid("custom_A_1000_v2", "") == "A"       # fallback
    assert chat_history.dm_peer_uid("country_1", "1000") == ""           # not a DM


def test_dm_contacts_order_and_fields():
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        for i in range(1, 6):
            s.append(_dm("A", i))              # peer A: five older messages
        for i in range(10, 13):
            s.append(_dm("B", i))              # peer B: three, newer
        s.append(_dm("A", 20, mine=True))      # my reply to A — newest overall
        contacts = s.dm_contacts("1000")
        assert [c["peer_uid"] for c in contacts] == ["A", "B"]     # newest first
        a = contacts[0]
        assert a["last_ts"] == 20.0 and a["last_mine"] is True
        assert a["last_text"] == "m20"
        assert a["name"] == "peerA"            # from the peer's own message, not mine
        assert a["head_pic_ver"] == "7"
        s.close()


def test_dm_room_paging():
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        room = "custom_A_1000_v2"
        for i in range(150):
            s.append(_dm("A", i))
        s.append(_dm("B", 500))                # noise in another room
        recent = s.recent_room(room, 100)
        assert len(recent) == 100
        assert [r["ts"] for r in recent] == [float(i) for i in range(50, 150)]
        older = s.older_room(room, recent[0]["ts"], 100)
        assert [r["ts"] for r in older] == [float(i) for i in range(0, 50)]
        assert s.has_older_room(room, 50.0) is True
        assert s.has_older_room(room, 0.0) is False
        s.close()


# --- history is per character, not per profile -----------------------------

def test_chat_db_path_is_per_character():
    import profile as prof
    with tempfile.TemporaryDirectory() as tmp:
        old = prof.PROFILES_DIR
        prof.PROFILES_DIR = tmp
        try:
            pm = prof.ProfileManager()
            active = pm.active
            a = pm.chat_db("1697234600000972")
            b = pm.chat_db("1697234600000999")
            assert os.path.basename(a) == "chat_history_1697234600000972.db", a
            assert os.path.basename(b) == "chat_history_1697234600000999.db", b
            assert a != b                                   # two chars → two files
            assert os.path.dirname(a).endswith(active)      # under the profile dir
            # No uid → the legacy account-wide name (backward compatible fallback).
            assert os.path.basename(pm.chat_db()) == prof.CHAT_DB
            # A hostile uid cannot escape the directory.
            evil = pm.chat_db("../../etc/passwd")
            assert os.path.basename(evil) == "chat_history_etcpasswd.db", evil
        finally:
            prof.PROFILES_DIR = old


# --- the lazy-load render window (needs the panel) -------------------------

class _FakeText:
    """Counts rendered message lines (each ends in a bare '\n'); a clear resets it."""

    def __init__(self):
        self.lines = 0
        self.images = 0

    def configure(self, **kw):
        pass

    def delete(self, *a):
        self.lines = 0
        self.images = 0

    def insert(self, index, text, *tags):
        if text == "\n":
            self.lines += 1

    def image_create(self, *a, **k):
        self.images += 1

    def tag_add(self, *a):
        pass

    def tag_bind(self, *a, **k):
        pass

    def tag_configure(self, *a, **k):
        pass

    def tag_names(self, *a):
        return ()

    def tag_delete(self, *a):
        pass

    def index(self, *a):
        return "1.0"

    def see(self, *a):
        pass

    def yview(self):
        return (0.0, 1.0)


def _stand_in(pm, store):
    from panel import i18n as i18nmod

    P = types.SimpleNamespace()
    P._i18n = i18nmod.I18n("en")
    P._chat_store = store
    P._chat_msgs = {"world": []}
    P._chat_has_more = {"world": False}
    P._chat_tree_rows = {"world": 0}
    P._chat_img_cache = {}
    P._photo_seq = 0
    P._chat_trees = {"world": _FakeText()}
    for name in ("_t", "_render_msg_line", "_insert_chat_text", "_update_chat_tree",
                 "_rebuild_chat_view", "_chat_load_older", "_chat_type_of_view",
                 "_chat_avatar", "_chat_avatar_placeholder"):
        setattr(P, name, pm.Panel.__dict__[name].__get__(P))
    P._chat_clear_view = pm.Panel._chat_clear_view
    P._chat_view_at_bottom = pm.Panel._chat_view_at_bottom
    P._AVATAR_PX = pm.Panel._AVATAR_PX
    return P


def test_lazy_window_pages_from_store():
    try:
        import panel.__main__ as pm
    except Exception as exc:      # noqa: BLE001 -- no tkinter/PIL/Tk here
        print(f"  SKIP test_lazy_window_pages_from_store: {exc}")
        return

    page = pm.CHAT_PAGE
    total = page * 2 + 50               # 250 with the default page of 100
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        for i in range(total):
            store.append(_rec(i, "country_1"))
        P = _stand_in(pm, store)
        fake = P._chat_trees["world"]

        # Open on the newest page only.
        recent = store.recent("world", page)
        P._chat_msgs["world"] = recent
        P._chat_has_more["world"] = store.has_older("world", recent[0]["ts"])
        P._rebuild_chat_view("world")
        assert fake.lines == page, fake.lines
        assert P._chat_has_more["world"] is True

        # Scroll-up pages in the next chunk from the store; the window is redrawn.
        P._chat_load_older("world")
        assert len(P._chat_msgs["world"]) == 2 * page
        assert fake.lines == 2 * page, fake.lines
        assert P._chat_has_more["world"] is True

        # A second page reaches the very start; nothing older remains.
        P._chat_load_older("world")
        assert len(P._chat_msgs["world"]) == total
        assert fake.lines == total, fake.lines
        assert P._chat_has_more["world"] is False

        # Exhausted: another page-older is a no-op.
        P._chat_load_older("world")
        assert len(P._chat_msgs["world"]) == total

        # A live message only appends (no rebuild, one more line).
        P._chat_msgs["world"].append(_rec(total, "country_1"))
        P._update_chat_tree("world")
        assert fake.lines == total + 1, fake.lines
        store.close()


class _FakeVar:
    def __init__(self, v=""):
        self._v = v

    def set(self, v):
        self._v = v

    def get(self):
        return self._v


def _dm_stand_in(pm, store):
    from panel import i18n as i18nmod

    P = types.SimpleNamespace()
    P._i18n = i18nmod.I18n("en")
    P._chat_store = store
    P._chat_uid = "1000"
    P._chat_msgs = {"dm": []}
    P._chat_has_more = {"dm": False}
    P._chat_tree_rows = {"dm": 0}
    P._chat_img_cache = {}
    P._photo_seq = 0
    P._chat_trees = {"dm": _FakeText()}
    P._dm_list = _FakeText()
    P._dm_active_room = ""
    P._dm_active_peer = ""
    P._dm_unread = {}
    P._dm_header_var = _FakeVar()
    P._chat_room_var = _FakeVar()
    P._active_chat_type = lambda: "dm"
    P._AVATAR_PX = pm.Panel._AVATAR_PX
    for name in ("_t", "_render_msg_line", "_insert_chat_text", "_rebuild_chat_view",
                 "_chat_load_older", "_chat_type_of_view", "_chat_avatar",
                 "_chat_avatar_placeholder", "_open_dm", "_refresh_dm_contacts",
                 "_render_contact_row", "_update_chat_target", "_chat_room"):
        setattr(P, name, pm.Panel.__dict__[name].__get__(P))
    P._chat_clear_view = pm.Panel._chat_clear_view
    P._chat_view_at_bottom = pm.Panel._chat_view_at_bottom
    P._dm_contact_time = pm.Panel._dm_contact_time
    return P


def test_dm_open_contact_filters_and_pages():
    try:
        import panel.__main__ as pm
    except Exception as exc:      # noqa: BLE001 -- no tkinter/PIL/Tk here
        print(f"  SKIP test_dm_open_contact_filters_and_pages: {exc}")
        return

    page = pm.CHAT_PAGE
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        room_a = "custom_A_1000_v2"
        for i in range(page + 50):            # peer A: a page and a half
            store.append(_dm("A", i))
        store.append(_dm("B", 999))           # peer B: one, and newest overall
        P = _dm_stand_in(pm, store)
        convo = P._chat_trees["dm"]

        # Opening A filters the conversation to A's room, newest page only.
        P._open_dm({"room": room_a, "peer_uid": "A", "name": "peerA"})
        assert P._dm_active_room == room_a
        assert convo.lines == page, convo.lines
        assert P._chat_has_more["dm"] is True
        assert P._chat_room("dm") == room_a           # a reply goes to A, not to B
        assert P._dm_list.lines > 0                    # the sidebar drew contacts

        # Scroll-up pages A's older messages in — from A's room only.
        P._chat_load_older("dm")
        assert len(P._chat_msgs["dm"]) == page + 50
        assert convo.lines == page + 50, convo.lines
        assert P._chat_has_more["dm"] is False
        assert all(r["room_id"] == room_a for r in P._chat_msgs["dm"])   # no B leaked in
        store.close()


class _FakeEntry:
    def __init__(self):
        self.text = ""

    def insert(self, index, s):
        self.text += s

    def focus_set(self):
        pass


def test_emoji_picker_inserts_token_and_sticker_sends():
    try:
        import panel.__main__ as pm
    except Exception as exc:      # noqa: BLE001 -- no tkinter/PIL/Tk here
        print(f"  SKIP test_emoji_picker_inserts_token_and_sticker_sends: {exc}")
        return

    P = types.SimpleNamespace()
    P._i18n = __import__("panel.i18n", fromlist=["I18n"]).I18n("en")
    P._chat_img_cache = {}
    P._chat_entry = _FakeEntry()
    P._chat_msg_var = _FakeVar()
    P._emoji_win = None
    sent = []
    P._chat_send = lambda args, what: sent.append((args, what))
    # Stub the image loader so _fill_picker's grid logic is tested independent of PIL
    # and of the filesystem (the Windows python cannot open the WSL /mnt sprite paths).
    P._chat_image = lambda path, px: "IMG"
    for name in ("_t", "_pick_emoji", "_pick_sticker", "_fill_picker"):
        setattr(P, name, pm.Panel.__dict__[name].__get__(P))

    # An emoji drops a {e:<id>} token into the message box (chat_send resolves it).
    P._pick_emoji({"id": "101"})
    P._pick_emoji({"id": "106"})
    assert P._chat_entry.text == "{e:101}{e:106}", P._chat_entry.text

    # A sticker is sent as its own message.
    P._pick_sticker({"id": "35"})
    assert sent == [(["--sticker", "35"], "sticker 35")], sent

    # The picker actually draws sprites into its grid (one image per catalogue item).
    box = _FakeText()
    emojis = chat_assets.emoji_catalogue()
    P._fill_picker(box, emojis, "emoji", 24)
    assert box.images == len(emojis) and box.images > 0, box.images


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
