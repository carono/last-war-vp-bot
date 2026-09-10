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

TIER = "ui"        # Tk and a display — see tools/run_tests.py

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
    line = ("ACT R roomId=alliance_100 seqId=42 st=1785000000000 post=0 type=1 "
            "uid=1234567 lang=ru gm=0 srv=100 hp=100 hpv=7 ismy=false alliance="
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


# --- a photograph keeps the marker that names it ---------------------------

def test_a_photograph_keeps_its_marker_and_is_not_the_word_for_one():
    """«У меня в чате просто заглушка [Изображение]» — the person, #2594.

    A photograph is `post = 633`, so #2418's post rule handed the row to
    `getMessageWithExtra()` — and for that kind the game's renderer answers its own
    localised placeholder rather than the message. The marker naming the picture
    (`<lwPhoto:<picVer>:>`) lives in `getMsg()` and nowhere else, so the rule cost every
    photograph the one field that identifies it: the panel filed the word and drew it.

    Measured on this account's history when it was found: `[photo:N]` stopped on
    04.09 17:14 and the placeholder ran from 03.09 17:12 to that minute — 39 messages,
    35 of them in the alliance room.
    """
    import chat_records

    def line(post, base, extra):
        return ("ACT R roomId=alliance_1 type=0 uid=1 st=1700000000000 seqId=9 "
                f"post={post} msg={base.encode().hex()} we={extra.encode().hex()}")

    got = chat_records.parse_record_line(line("633", "<lwPhoto:1984:>", "[Изображение]"))
    assert got["msg"] == "[photo:1984]", got["msg"]

    # …AND THE REST OF #2418 IS UNTOUCHED. The rule fires only where the two renderings
    # disagree about an inline object, so an interactive post with nothing to lose still
    # arrives the way the game draws it, and a plain message still keeps its own text.
    coords = chat_records.parse_record_line(
        line("404", "?", "[AL1] Player1 (BZ #100 X:602 Y:404)"))
    assert coords["msg"] == "[AL1] Player1 (BZ #100 X:602 Y:404)", coords["msg"]
    plain = chat_records.parse_record_line(line("0", "hello", "hello"))
    assert plain["msg"] == "hello", plain["msg"]
    # A sticker rides the same markers and must survive the same way.
    stick = chat_records.parse_record_line(line("633", "<lwSticker:12:>", "[Изображение]"))
    assert stick["msg"] == "[sticker:12]", stick["msg"]


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

def _rec(i, room="alliance_100"):
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
    # THROUGH THE PACKAGE. A bare `import profile` reached this module only because
    # `panel/` happens to be on sys.path — it shadows the standard library's `profile`,
    # and it loads the file outside its package, so the first relative import inside it
    # fails with "no known parent package". Every other test already spells it this way.
    from panel import profile as prof
    with tempfile.TemporaryDirectory() as tmp:
        old = prof.PROFILES_DIR
        prof.PROFILES_DIR = tmp
        try:
            pm = prof.ProfileManager()
            active = pm.active
            a = pm.chat_db("1000000000014972")
            b = pm.chat_db("1000000000014999")
            assert os.path.basename(a) == "chat_history_1000000000014972.db", a
            assert os.path.basename(b) == "chat_history_1000000000014999.db", b
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
    i18n = i18nmod.I18n("en")
    # The tab reads its words through the runtime now, not off the panel.
    P.rt = types.SimpleNamespace(t=i18n.t)
    P._chat_store = store
    P._chat_msgs = {"world": []}
    P._chat_has_more = {"world": False}
    P._chat_tree_rows = {"world": 0}
    P._chat_img_cache = {}
    P._photo_seq = 0
    P._chat_trees = {"world": _FakeText()}
    for name in ("t", "_render_msg_line", "_insert_chat_text", "_update_chat_tree",
                 "_rebuild_chat_view", "_chat_load_older", "_chat_type_of_view",
                 "_chat_avatar", "_chat_avatar_placeholder"):
        setattr(P, name, getattr(pm.ChatTab, name).__get__(P))
    P._chat_clear_view = pm.ChatTab._chat_clear_view
    P._chat_view_at_bottom = pm.ChatTab._chat_view_at_bottom
    P._AVATAR_PX = pm.ChatTab._AVATAR_PX
    return P


def test_lazy_window_pages_from_store():
    try:
        from panel.tabs import chat as pm
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
    i18n = i18nmod.I18n("en")
    # The tab reads its words through the runtime now, not off the panel.
    P.rt = types.SimpleNamespace(t=i18n.t)
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
    P._AVATAR_PX = pm.ChatTab._AVATAR_PX
    for name in ("t", "_render_msg_line", "_insert_chat_text", "_rebuild_chat_view",
                 "_chat_load_older", "_chat_type_of_view", "_chat_avatar",
                 "_chat_avatar_placeholder", "_open_dm", "_refresh_dm_contacts",
                 "_render_contact_row", "_update_chat_target", "_chat_room"):
        setattr(P, name, getattr(pm.ChatTab, name).__get__(P))
    P._chat_clear_view = pm.ChatTab._chat_clear_view
    P._chat_view_at_bottom = pm.ChatTab._chat_view_at_bottom
    P._dm_contact_time = pm.ChatTab._dm_contact_time
    return P


def test_dm_open_contact_filters_and_pages():
    try:
        from panel.tabs import chat as pm
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
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001 -- no tkinter/PIL/Tk here
        print(f"  SKIP test_emoji_picker_inserts_token_and_sticker_sends: {exc}")
        return

    P = types.SimpleNamespace()
    i18n = __import__("panel.i18n", fromlist=["I18n"]).I18n("en")
    P.rt = types.SimpleNamespace(t=i18n.t)
    P._chat_img_cache = {}
    P._chat_entry = _FakeEntry()
    P._chat_msg_var = _FakeVar()
    P._emoji_win = None
    sent = []
    P._chat_send = lambda args, what: sent.append((args, what))
    # Stub the image loader so _fill_picker's grid logic is tested independent of PIL
    # and of the filesystem (the Windows python cannot open the WSL /mnt sprite paths).
    P._chat_image = lambda path, px: "IMG"
    for name in ("t", "_pick_emoji", "_pick_sticker", "_fill_picker"):
        setattr(P, name, getattr(pm.ChatTab, name).__get__(P))

    # An emoji drops a {e:<id>} token into the message box (chat_send resolves it).
    P._pick_emoji({"id": "101"})
    P._pick_emoji({"id": "106"})
    assert P._chat_entry.text == "{e:101}{e:106}", P._chat_entry.text

    # A sticker is sent as its own message — as the recipe's ARGUMENTS since the send
    # became one scenario (`CHAT_SEND`), not as a command line for a spawned tool.
    P._pick_sticker({"id": "35"})
    assert sent == [({"sticker": "35"}, "sticker 35")], sent

    # The picker actually draws sprites into its grid (one image per catalogue item).
    box = _FakeText()
    emojis = chat_assets.emoji_catalogue()
    P._fill_picker(box, emojis, "emoji", 24)
    assert box.images == len(emojis) and box.images > 0, box.images


def test_coords_button_shares_what_is_written_in_the_box():
    """«📍 координаты» reads the message box, not the Main tab.

    The X/Y/server fields it used to read went with the «Навигация» block (#1183),
    so the source is now the box the message is typed into, parsed by the same
    tolerant reader the log's clickable links use. A box with no coordinate in it
    sends nothing and says so; one with a coordinate sends the pin and is cleared,
    or the next «Отправить» would post the pin's text alongside the pin.
    """
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001 -- no tkinter/PIL/Tk here
        print(f"  SKIP test_coords_button_shares_what_is_written_in_the_box: {exc}")
        return

    def stand_in(text):
        P = types.SimpleNamespace()
        P._chat_msg_var = _FakeVar(text)
        P.sent, P.said = [], []
        P._chat_send = lambda args, what: P.sent.append((args, what))
        P.say = lambda tag, key, **kw: P.said.append(key)
        P._chat_send_coords = pm.ChatTab._chat_send_coords.__get__(P)
        P._chat_send_coords()
        return P

    # The canonical token the panel itself prints, server and all.
    P = stand_in("#2305 X:568 Y:371")
    assert P.sent == [({"coords": "568,371", "server": "2305"},
                       "#2305 X:568 Y:371")], P.sent
    assert P._chat_msg_var.get() == "", P._chat_msg_var.get()

    # A bare tile, pasted in any of the forms the log links: no server on the wire.
    P = stand_in("глянь @[568,371] там шахта")
    assert P.sent == [({"coords": "568,371"}, "X:568 Y:371")], P.sent

    # Nothing to share: one line in the log, nothing sent, and the text left alone.
    P = stand_in("всем привет")
    assert P.sent == [] and P.said == ["chat.no_coords"], (P.sent, P.said)
    assert P._chat_msg_var.get() == "всем привет", P._chat_msg_var.get()


def test_the_picker_names_no_room_at_all():
    """THE LEAK, AND WHY IT CANNOT COME BACK (#2418).

    The person: «до этих доработок отправил эмодзи в личку, а оно опубликовалось в
    мировом чате». The picker was two grids on the screen and every sprite's press
    carried a channel of the PICKER's own, which defaulted to the WORLD — so an emoji
    tapped while a private conversation was open was posted where everybody read it.

    The picker hands back pictures and nothing else now. The room is decided where the
    send is made and nowhere else, and there is no default anywhere near it.
    """
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001 -- no tkinter/PIL/Tk here
        print(f"  SKIP test_the_picker_names_no_room_at_all: {exc}")
        return

    P = types.SimpleNamespace()
    P._web_picker = pm.ChatTab._web_picker.__get__(P)
    got = P._web_picker()
    assert set(got) == {"emoji", "stickers"}, got
    blob = json.dumps(got)
    assert "room" not in blob and "type" not in blob, "the picker still names a channel"
    assert "country_" not in blob and "world" not in blob, blob[:200]
    for one in got["emoji"][:5]:
        assert one["icon"].startswith("/api/chatsprite?sprite="), one
        assert one["token"].startswith("{e:") and one["token"].endswith("}"), one
    for one in got["stickers"][:5]:
        assert one["icon"].startswith("/api/chatsprite?sprite="), one
    # …and the tab keeps no channel of its own for a picker to fall back on.
    assert not hasattr(pm.ChatTab, "WEB_PICKER_DEFAULT"), \
        "the picker has a default channel again"
    assert not hasattr(pm.ChatTab, "_web_picker_type")


def test_no_send_can_fall_into_the_world():
    """Every send names its room outright, or nothing leaves (#2418).

    Four paths — text, an emoji (which is text), a sticker and a coordinate — and each
    of them is refused unless the room is said and agrees with the kind. A DM room
    arriving with `world` on it is the exact shape the leak had, so it is refused rather
    than reconciled: one of the two is wrong and there is no telling which.
    """
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001
        print(f"  SKIP test_no_send_can_fall_into_the_world: {exc}")
        return

    # Invented ids throughout — the shape is what is being pinned.
    dm = "custom_1000000000000001_1000000000000002_v2"
    world = "country_1000_11"
    P = types.SimpleNamespace()
    sent = []
    P._chat_send = lambda args, what, room="": sent.append((args, what, room)) or True
    P._chat_room = lambda kind: {"world": world}.get(kind, "")
    P._known_rooms = lambda kind: {world, dm}
    P._rooms = {world: {}, dm: {}}
    P.web_press = pm.ChatTab.web_press.__get__(P)

    # A private message goes to the private room, and only there.
    assert P.web_press("send", {"type": "dm", "room": dm, "text": "hi"}) == {"ok": True}
    assert sent[-1][2] == dm, sent[-1]
    assert P.web_press("sticker", {"type": "dm", "room": dm, "id": "35"}) == {"ok": True}
    assert sent[-1][2] == dm, sent[-1]
    assert P.web_press("coords", {"type": "dm", "room": dm,
                                  "text": "@[600,400|100]"}) == {"ok": True}
    assert sent[-1][2] == dm, sent[-1]

    # NO ROOM, NO SEND — on every path, and never a fall into the world.
    for action, args in (("send", {"text": "hi"}), ("sticker", {"id": "35"}),
                         ("coords", {"text": "@[600,400|100]"})):
        answer = P.web_press(action, dict(args, type="world"))
        assert answer == {"ok": False, "reason": "chat.no_room"}, (action, answer)
    # …and a room that disagrees with the kind it was sent under is refused too.
    answer = P.web_press("send", {"type": "world", "room": dm, "text": "hi"})
    assert answer == {"ok": False, "reason": "chat.no_room"}, answer
    answer = P.web_press("send", {"type": "dm", "room": world, "text": "hi"})
    assert answer == {"ok": False, "reason": "chat.no_room"}, answer
    # Nothing above sent anything beyond the three private ones.
    assert [row[2] for row in sent] == [dm, dm, dm], sent


def test_the_sprite_route_serves_only_the_extracted_art():
    """A name from a phone is checked, and the photographs are not reachable at all."""
    import chat_assets

    assert chat_assets.sprite_named("emoji/../../secrets.png") is None
    assert chat_assets.sprite_named("photos/whoever.jpg") is None
    assert chat_assets.sprite_named("emoji/e006.txt") is None
    assert chat_assets.sprite_named("") is None
    link = chat_assets.sprite_link("/anywhere/emoji/e006.png")
    assert link == "/api/chatsprite?sprite=emoji/e006.png", link
    assert chat_assets.sprite_link("/anywhere/photos/a.png") is None
    # …and every catalogue entry resolves back through the same check.
    for entry in chat_assets.emoji_catalogue()[:5]:
        name = chat_assets.sprite_link(entry["path"]).split("sprite=")[1]
        import urllib.parse as _url
        assert chat_assets.sprite_named(_url.unquote(name)), entry


# --- the ear is kept up, and its silence is said (#2418) --------------------

class _Var:
    """The monitor switch, without Tk."""

    def __init__(self, on: bool) -> None:
        self._on = bool(on)

    def get(self):
        return self._on

    def set(self, on) -> None:
        self._on = bool(on)


def _ear_stand_in(pm, *, wanted=True, on=True):
    """A ChatTab shaped just enough to answer for the reader's lifetime."""
    P = object.__new__(pm.ChatTab)
    P._chat_var = _Var(on)
    P._chat_proc = None
    P._chat_wanted = wanted
    P._chat_retry = 0.0
    P._chat_retry_timer = None
    P._said = []
    P.say = lambda tag, key, **fmt: P._said.append(key)
    P.post = lambda call: None
    for name in ("_on_chat_exit", "_schedule_chat_retry", "_cancel_chat_retry",
                 "_chat_retry_now", "_chat_silence"):
        setattr(P, name, getattr(pm.ChatTab, name).__get__(P))
    return P


def test_a_dead_reader_is_brought_back_and_never_switches_the_monitor_off():
    """The live failure of #2418: the reader died and the ear stayed down for days.

    The child dies with the game it listens to — a client restart, a failed hook — and
    the exit used to switch the monitor off. Nothing switches it back, and a chat that
    has stopped growing is indistinguishable from a quiet one, so the panel filed
    nothing for three days and said so once, in a line that scrolled away.
    """
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001 -- no tkinter/PIL/Tk here
        print(f"  SKIP test_a_dead_reader_is_brought_back...: {exc}")
        return

    P = _ear_stand_in(pm)
    P._on_chat_exit()
    assert P._chat_var.get() is True, "a death switched the person's monitor off"
    assert P._chat_retry_timer is not None, "nothing was scheduled to bring it back"
    assert "log.chat.retry" in P._said, "the retry is not said in the log"
    # …and the gap WIDENS, so a client that is off is not hammered.
    first = P._chat_retry
    P._chat_retry_timer.cancel()
    P._on_chat_exit()
    assert P._chat_retry > first, "the gap between attempts does not widen"
    assert P._chat_retry <= pm.ChatTab.CHAT_RETRY_MAX
    P._chat_retry_timer.cancel()

    # A monitor the PERSON switched off is left alone: no retry, no timer.
    Q = _ear_stand_in(pm, wanted=False, on=False)
    Q._on_chat_exit()
    assert Q._chat_retry_timer is None, "a monitor nobody wants is being restarted"


def test_the_chat_says_how_old_its_newest_message_is():
    """A reading with no age on it is read as fresh (#2418)."""
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001
        print(f"  SKIP test_the_chat_says_how_old...: {exc}")
        return

    import game_clock

    P = _ear_stand_in(pm)
    P._chat_msgs = {t: [] for t in pm.CHAT_TABS}
    assert P._chat_silence() is None, "an empty chat claims an age"

    was = game_clock.now_ms
    game_clock.now_ms = lambda: 1_000_000_000_000
    try:
        # The stamp is the GAME's, judged on the game's clock and never the machine's.
        P._chat_msgs["world"] = [{"ts": 1_000_000_000.0 - 90.0}]
        assert abs(P._chat_silence() - 90.0) < 1.0, P._chat_silence()
    finally:
        game_clock.now_ms = was


def test_the_reader_is_drained_by_a_panel_with_no_window():
    """#2418: the pump was armed in `build()` — the method that DRAWS.

    The live panel has no window, so nothing ever took a message off the reader's
    queue: the ear heard, the child wrote its own file, and the panel filed nothing
    into the store and showed nothing on the phone. The queue belongs to the state,
    like the reader that fills it, so `ensure_loaded` arms it.
    """
    src = (_REPO / "panel" / "tabs" / "chat.py").read_text(encoding="utf-8")
    loaded = src.split("def ensure_loaded")[1].split("def on_show")[0]
    assert "self._pump_chat()" in loaded, "the queue is drained only where it is drawn"
    # …and nothing it touches on that tick may be a widget that was never built.
    pump = src.split("def _pump_chat")[1].split("def _load_backlog")[0]
    assert "self._set_chat_count(" in pump and "_chat_count_var" not in pump, \
        "the pump writes a variable that only build() makes"
    clear = src.split("def _clear_chat")[1].split("def _load_chat_history")[0]
    assert "_chat_count_var" not in clear, \
        "clearing the chat writes a variable that only build() makes"



# --- the room list is the client's (#2418) ---------------------------------

def _rooms_stand_in(pm, rooms):
    P = object.__new__(pm.ChatTab)
    P._rooms = rooms
    P._chat_uid = ""
    P._dm_unread = {}
    P._faces = {}
    P._room_unread = {}
    P._chat_unread = {}
    P._chat_msgs = {t: [] for t in pm.CHAT_TABS}
    P._chat_store = None
    for name in ("_web_rooms", "_room_label", "_chat_room", "_parse_rooms",
                 "_web_people", "_store_for_reading", "_only_history_on_disk"):
        setattr(P, name, getattr(pm.ChatTab, name).__get__(P))
    P.ROOM_KEYS = pm.ChatTab.ROOM_KEYS
    P._read_store = None
    P._read_store_uid = ""
    return P


def test_a_custom_group_is_a_chip_of_its_own_named_by_the_client():
    """The person's report: «не вижу все контакты, там есть другие группы, кастомные».

    A player's own group is a room like any other and the client holds it by name. The
    panel knew six buckets, so the group's messages were tipped into «Другие» beside the
    cross-server and season channels and its name was nowhere on the screen.
    """
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001 -- no tkinter/PIL/Tk here
        print(f"  SKIP test_a_custom_group_is_a_chip...: {exc}")
        return

    # Invented ids and an invented group name — the shape is what the test is about.
    rooms = {
        "country_1000_11": {"name": "", "msgs": 24},
        "alliance_1000_aaaabbbbcccc": {"name": "", "msgs": 40},
        "alliance_1000_aaaabbbbcccc_Notice": {"name": "", "msgs": 0},
        "alliance_friend_aaaabbbbcccc_ddddeeeeffff": {"name": "", "msgs": 40},
        "custom_lang_xx_1000_11": {"name": "", "msgs": 0},
        "crossbattle_cross_9": {"name": "", "msgs": 40},
        "custom_group_0123456789abcdef": {"name": "Group One", "msgs": 40},
        "custom_1000000000000001_1000000000000002_v2": {"name": "PRIVATE_x_to_y",
                                                        "msgs": 0},
    }
    P = _rooms_stand_in(pm, rooms)
    chips = P._web_rooms()
    ids = [c["room"] for c in chips]
    assert "custom_group_0123456789abcdef" in ids, "the custom group has no chip"
    group = [c for c in chips if c["room"] == "custom_group_0123456789abcdef"][0]
    assert group["label"] == "Group One", "the group is not named by the client"
    assert not group["key"], "a named group must not also carry a locale key"
    # A private thread is NOT a chip: it lives behind «ЛС», with the contacts.
    assert not any(r.endswith("_v2") for r in ids), "a DM thread became a chip"
    # …and the rooms with no name of their own are still called something a person reads.
    named = {c["room"]: c["key"] for c in chips if c["key"]}
    assert named["alliance_1000_aaaabbbbcccc_Notice"] == "chat.room.notice"
    assert named["alliance_friend_aaaabbbbcccc_ddddeeeeffff"] == "chat.room.alliance_friend"
    assert named["crossbattle_cross_9"] == "chat.room.crossbattle"
    assert named["country_1000_11"] == "chat.tab.world"
    # «ЛС» and «Системные» are the two chips that are not a room.



def test_the_room_list_is_read_from_the_client_never_written_down():
    """The list comes off `read_chat_rooms`, and the name travels as hex."""
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001
        print(f"  SKIP test_the_room_list_is_read...: {exc}")
        return

    raw = "\t".join(["custom_group_00ff", "d093d180d183d0bfd0bfd0b0", "40"])
    # `;;` between rooms: the reading travels as ONE line, so a newline between them
    # is cut off at the first (measured live — 69 rooms came back as one).
    got = pm.ChatTab._parse_rooms(raw + ";;country_1000_11\t\t24")
    assert got["custom_group_00ff"]["name"] == "Группа", got
    assert got["custom_group_00ff"]["msgs"] == 40
    assert got["country_1000_11"]["name"] == "", "a nameless room invented one"
    # The scenario exists and asks the CLIENT, never the server.
    recipe = (_REPO / "src" / "lastwar_bot" / "actions" / "read_chat_rooms.md").read_text(
        encoding="utf-8")
    assert "getRoomMgr" in recipe, "the rooms are not read off the client's own manager"
    assert "ChatRoomRequestHistoryMsg" not in recipe, "the room list asks the server"



def test_a_room_read_that_answered_nothing_can_be_asked_again():
    """The boot reads before the link is up, and the answer is empty (#2418).

    The «one at a time» flag was set on the way in and cleared nowhere, so that first
    empty read locked the register shut: neither a look nor a press could ask again, and
    the chips stayed the fallback six for as long as the panel ran.
    """
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001
        print(f"  SKIP test_a_room_read_that_answered_nothing...: {exc}")
        return

    P = object.__new__(pm.ChatTab)
    P._rooms, P._rooms_read, P._rooms_busy = {}, 0.0, True
    pm.ChatTab._absorb_rooms(P, {})
    assert P._rooms_busy is False, "an empty answer locks the register for ever"
    assert P._rooms_read == 0.0, "an empty answer counts as a fresh reading"
    pm.ChatTab._absorb_rooms(P, {"country_1000_11": {"name": "", "msgs": 1}})
    assert P._rooms and P._rooms_read > 0.0



def test_pinned_rooms_come_first_and_people_go_by_their_last_message():
    """#2418: «в клиенте некоторые чаты помечены как закреплённые… сортировать сверху»
    and «чаты игроков сортируем по последнему сообщению».

    The flag is the client's own `isPin` — measured, not guessed: it is on every room and
    none of `pinTime` / `isTop` / `topTime` / `stick` / `sortWeight` exists at all, so
    there is no order BETWEEN pinned rooms to read and they go by their last message like
    the rest of the list.
    """
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001
        print(f"  SKIP test_pinned_rooms_come_first...: {exc}")
        return

    rooms = {
        "country_1000_11": {"name": "", "msgs": 24, "pin": False, "last": 100.0},
        "custom_group_0123456789abcdef": {"name": "Group One", "msgs": 40,
                                          "pin": True, "last": 300.0},
        "alliance_1000_aaaabbbbcccc": {"name": "", "msgs": 40, "pin": True,
                                       "last": 900.0},
    }
    P = _rooms_stand_in(pm, rooms)
    rows = P._web_rooms()
    assert [r["section"] for r in rows[:2]] == ["pin", "pin"], rows
    # …and inside the pinned section, the freshest first.
    assert rows[0]["room"] == "alliance_1000_aaaabbbbcccc", rows[0]
    assert rows[1]["room"] == "custom_group_0123456789abcdef", rows[1]
    # A pinned room is not ALSO in its own section.
    assert not any(r["room"] == "alliance_1000_aaaabbbbcccc" and r["section"] != "pin"
                   for r in rows)
    # The pin and the last message are read off the client's own line.
    got = pm.ChatTab._parse_rooms("country_1000_11\t\t24\t1\t1700000000000")
    assert got["country_1000_11"]["pin"] is True
    assert abs(got["country_1000_11"]["last"] - 1700000000.0) < 1.0

    # The private conversations keep the store's own order — newest first.
    P._chat_uid = "1000000000000009"

    class _Store:
        @staticmethod
        def dm_contacts(_uid):
            return [{"room": "custom_a_b_v2", "peer_uid": "1000000000000001",
                     "name": "Player1", "last_ts": 500.0, "last_text": "…"},
                    {"room": "custom_c_d_v2", "peer_uid": "1000000000000002",
                     "name": "Player2", "last_ts": 400.0, "last_text": "…"}]

    P._chat_store = _Store()
    people = [r for r in P._web_rooms() if r["section"] == "people"]
    assert [r["room"] for r in people] == ["custom_a_b_v2", "custom_c_d_v2"], people



def test_a_reply_carries_the_message_it_answers():
    """#2418: «нужно чтобы у меня в чате отображалось, что это ответ».

    The client keeps the quote on the message as `replyMsg` —
    `{seqId, uid, userName, msg, abbr, post}` — and it is the ONLY link there is:
    nothing else on a message says it is a reply. Every value below is invented; what
    is being pinned is the shape.
    """
    line = ("ACT R roomId=custom_group_00ff seqId=4058 st=1700000000000 post=0 type=0 "
            "uid=1000000000000001 lang=ru gm=0 srv=1000 hp=0 hpv=1 ismy=true "
            "rseq=4057 ruid=1000000000000001 rname=506c6179657231 rmsg=74657374 "
            "alliance= sender=506c6179657231 msg=74657374 we=74657374")
    import chat_records

    rec = chat_records.parse_record_line(line)
    assert rec["reply"] == {"seq_id": "4057", "uid": "1000000000000001",
                            "name": "Player1", "text": "test"}, rec["reply"]
    # An ordinary message has no quote at all — not an empty one.
    plain = chat_records.parse_record_line(line.replace("rseq=4057", "rseq=")
                                               .replace("ruid=1000000000000001 rname",
                                                        "ruid= rname"))
    assert plain["reply"] is None, plain["reply"]


def test_the_quote_names_the_row_it_points_at():
    """A tap on a quote has to reach a MESSAGE, so it travels as that row's own id."""
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001
        print(f"  SKIP test_the_quote_names_the_row_it_points_at: {exc}")
        return

    room = "custom_group_00ff"
    got = pm.ChatTab._web_reply({"reply": {"seq_id": "4057", "uid": "1000000000000001",
                                           "name": "Player1", "text": "test"}}, room)
    assert got["id"] == "custom_group_00ff|4057|1000000000000001", got
    assert got["who"] == "Player1" and got["text"] == "test", got
    # …and the id is built the same way the row itself is keyed, or the tap lands nowhere.
    row_id = "%s|%s|%s" % (room, "4057", "1000000000000001")
    assert got["id"] == row_id
    assert pm.ChatTab._web_reply({}, room) is None



def test_a_message_already_filed_can_still_learn_its_quote():
    """A reply on disk from before the recorder carried quotes (#2418).

    The identity index makes a re-read idempotent, which is what keeps the store honest
    — and it also means the older, poorer copy wins. The one field that can only be
    GAINED is written over it; nothing else is touched, or a re-read would be a way of
    forgetting things.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        plain = _rec(1, "custom_group_00ff")
        store.append(plain)
        rich = dict(plain, reply={"seq_id": "4057", "uid": "1000000000000001",
                                  "name": "Player1", "text": "test"})
        store.append(rich)
        rows = store.recent(plain["chat_type"], 10)
        assert len(rows) == 1, "the re-read duplicated the message"
        assert rows[0].get("reply", {}).get("seq_id") == "4057", rows[0]
        # …and a re-read that knows LESS does not take the quote away again.
        store.append(plain)
        rows = store.recent(plain["chat_type"], 10)
        assert rows[0].get("reply", {}).get("seq_id") == "4057", rows[0]
        store.close()



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


def test_the_room_list_follows_the_ear_instead_of_one_read_an_hour_old():
    """#2418, measured live: the left-hand list was read ONCE, when the screen was first
    looked at, and never again while the panel ran — every stamp on it was 96 minutes
    old on a panel whose newest message was 57 seconds old. The sections that sort by
    their last message were sorted by that hour-old answer, and a room that started
    talking after the read had no chip at all until somebody pressed «Обновить комнаты».

    A message names its own room, so the arrival is the signal: no clock, and no
    question to the game for a stamp the message already carried.
    """
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001
        print(f"  SKIP test_the_room_list_follows_the_ear...: {exc}")
        return

    asked = []
    P = object.__new__(pm.ChatTab)
    P._rooms = {"country_1000_11": {"name": "", "msgs": 24, "pin": False,
                                    "last": 1000.0}}
    P._rooms_asked = set()
    P._read_rooms = lambda force=False: asked.append(force) or True
    heard = pm.ChatTab._room_heard.__get__(P)

    heard("country_1000_11", 2000.0)
    assert P._rooms["country_1000_11"]["last"] == 2000.0, \
        "a message moves its own room's stamp"
    heard("country_1000_11", 1500.0)
    assert P._rooms["country_1000_11"]["last"] == 2000.0, "a stamp never walks backwards"
    assert asked == [], "a room already in the register asks the client nothing"

    # A room nobody has read yet: it gains a chip at once, and the client is asked ONCE
    # for the one thing only it knows — the name a person gave the group.
    heard("custom_group_00000000000000000000000000000001", 3000.0)
    heard("custom_group_00000000000000000000000000000001", 3100.0)
    assert "custom_group_00000000000000000000000000000001" in P._rooms
    assert asked == [True], "an unknown room is asked about once, not once per message"


def test_a_read_of_the_register_keeps_what_the_ear_heard():
    """The client's answer wins where it has one — the name, the pin, its own stamp —
    but a room only the ear has heard from keeps its chip, and a stamp the panel has
    seen move is not walked backwards by an older reading (#2418)."""
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001
        print(f"  SKIP test_a_read_of_the_register_keeps...: {exc}")
        return

    P = object.__new__(pm.ChatTab)
    P._rooms = {"country_1000_11": {"name": "", "msgs": 24, "pin": False, "last": 9000.0},
                "custom_group_00000000000000000000000000000001":
                    {"name": "", "msgs": 0, "pin": False, "last": 8000.0}}
    P._rooms_read, P._rooms_busy = 0.0, True
    pm.ChatTab._absorb_rooms(P, {"country_1000_11": {"name": "", "msgs": 25,
                                                     "pin": True, "last": 5000.0}})
    assert P._rooms["country_1000_11"]["pin"] is True, "the client's own flag wins"
    assert P._rooms["country_1000_11"]["last"] == 9000.0, \
        "a read older than what the ear heard must not roll the stamp back"
    assert "custom_group_00000000000000000000000000000001" in P._rooms, \
        "a read that missed a room must not take its chip away"


def test_a_row_filed_under_a_placeholder_is_repaired_by_a_re_read():
    """#2418: the reader used to file the bare word `msg` — what the client answers for
    an interactive post — as if somebody had written it. A re-read brings the rendered
    text, and the row's identity is `(room, uid, ts, text)`: without the repair the
    better copy would land BESIDE the poorer one instead of over it.

    A real message is never rewritten: only a placeholder is written over.
    """
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        poor = dict(_rec(1), msg="msg")
        s.append(poor)
        s.append(dict(poor, msg="Player1 joined"))
        rows = s.recent("alliance", 10)
        assert len(rows) == 1, "the repaired message was filed twice"
        assert rows[0]["msg"] == "Player1 joined", rows[0]["msg"]

        # …and the other way round is refused: a re-read that KNOWS less changes nothing.
        s.append(dict(poor, msg="msg"))
        rows = s.recent("alliance", 10)
        assert len(rows) == 2, "a placeholder must still be filed as its own message"
        assert "Player1 joined" in [r["msg"] for r in rows]
        s.close()


def test_the_translation_is_the_game_s_own_and_asks_it_once():
    """#2418: «в чате есть функция перевода, изучи её, сделай эту возможность».

    The recipe presses the client's own button (`OnChatTranslate`) and the press holds
    what came back, so putting the original back and reading the translation again cost
    the game nothing. Nothing leaves this machine for an outside service.
    """
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001
        print(f"  SKIP test_the_translation_is_the_game_s_own...: {exc}")
        return

    played = []

    class _Out:
        class ctx:
            vars = {"tr_text": "d0bfd180d0b8d0b2d0b5d182", "tr_lang": "ru"}

    P = object.__new__(pm.ChatTab)
    P._rooms = {"alliance_1000_aaaabbbbcccc": {"name": "", "msgs": 3}}
    P._translated = {}
    P._chat_msgs = {t: [] for t in pm.CHAT_TABS}
    P._chat_store = None
    P.TRANSLATED_MAX = pm.ChatTab.TRANSLATED_MAX
    P._known_rooms = lambda kind: set()
    P.rt = type("R", (), {"actions": type("A", (), {
        "play": staticmethod(lambda name, args, **kw: played.append((name, args)) or _Out())})()})()
    P._translate = pm.ChatTab._translate.__get__(P)

    answer = P._translate("alliance_1000_aaaabbbbcccc", "8123")
    assert answer.get("ok") and answer.get("text") == "привет", answer
    assert played == [("translate_chat_message",
                       {"room": "alliance_1000_aaaabbbbcccc", "seq": "8123"})], played

    again = P._translate("alliance_1000_aaaabbbbcccc", "8123")
    assert again.get("text") == "привет"
    assert len(played) == 1, "the game was asked twice for one translation"

    # A room this panel has never heard of is refused rather than named to the game.
    assert P._translate("alliance_9999_ffff", "1").get("error") == "unknown"
    assert P._translate("", "").get("error") == "unknown"


def test_the_offer_to_translate_is_the_game_s_own_answer():
    """#2418: the button is drawn only where the GAME draws it. Measured live: a
    coordinate share (`post = 13`) answers `isShowTranslateBtn() == false`, and an
    ordinary message answers true — so a row that carries the client's answer uses it,
    and one filed before the recorder carried it falls back to the post.

    Never on one's own message: the game does not offer it there either.
    """
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001
        print(f"  SKIP test_the_offer_to_translate...: {exc}")
        return

    can = pm.ChatTab._can_translate
    assert can({"can_translate": True}) is True
    assert can({"can_translate": False}) is False
    assert can({"can_translate": True, "is_mine": True}) is False
    # Filed before the recorder carried the flag: a plain post is offered, a share is not.
    assert can({"post": "0"}) is True
    assert can({"post": "13"}) is False
    assert can({}) is True


def test_a_message_shorter_than_five_characters_is_never_auto_translated():
    """#2705: «не переводить (отображать оригинал в панели) сообщения короче 5 символов».

    «ок», «+1», «)))» and a single sticker come back from the game's translator as
    themselves or as something worse, and a row that says «translated» over an unchanged
    «ок» tells a reader that a translation happened. So they are dropped BEFORE the
    queue: never asked for, never counted, never reported — the original simply stands.

    THE LENGTH IS WHAT A READER SEES, not what the wire carries. An emoji is written
    `[e:E006]` — eight characters of markup for one thing on screen — and a photograph is
    `[photo:3]`; each counts as ONE, and colour tags count as none. Otherwise a message
    that is a single smiley would be «eight characters long» and translated, which is the
    exact row the person named.
    """
    try:
        from panel.tabs import chat as pm
    except Exception as exc:      # noqa: BLE001
        print(f"  SKIP test_a_message_shorter_than_five...: {exc}")
        return

    long_enough = pm.ChatTab.TR_MIN_CHARS
    assert long_enough == 5, "the person said five"
    size = pm.ChatTab._tr_length
    short = pm.ChatTab._tr_short

    # The rows this exists for.
    assert size({"msg": "ок"}) == 2
    assert size({"msg": "+1"}) == 2
    assert size({"msg": ")))"}) == 3
    assert size({"msg": "  ок  "}) == 2, "the spaces round it are not characters"
    assert size({"msg": "[e:E006]"}) == 1, "an emoji is one thing on screen"
    assert size({"msg": "[photo:3]"}) == 1, "a photograph is one thing on screen"
    assert size({"msg": "<color=#fff>ок</color>"}) == 2, "a colour tag is not a character"
    for text in ("ок", "+1", ")))", "[e:E006]", "[photo:3]", "", "   "):
        assert short({"msg": text}) is True, text

    # …and the ones it must leave alone.
    assert size({"msg": "hello"}) == 5
    assert short({"msg": "hello"}) is False, "five characters is long enough"
    assert short({"msg": "привет всем"}) is False
    assert short({"msg": "[e:E006][e:E006][e:E006][e:E006][e:E006]"}) is False, \
        "five emoji are five characters"

    # A SKIPPED MESSAGE IS NOT A TRANSLATED ONE. The gate is upstream of the queue, so
    # nothing about it can reach the tally the switch reports.
    src = (_REPO / "panel" / "tabs" / "chat.py").read_text(encoding="utf-8")
    batch = src.split("def _tr_batch")[1].split("\n    def ")[0]
    assert "_tr_short" not in batch, "the count is being made where the gate is not"
    assert batch.count("self._tr_done += 1") == 1, \
        "the tally counts something other than a translation that came back"


def test_the_chat_screen_carries_no_message_cards():
    """#2418: the phone was handed 30 messages x 5 channels it throws away.

    `ScreenView.tsx` filters every card marked `drawn` off a screen that draws itself,
    so the fallback list was built, serialised and discarded on each of the chat page's
    polls — measured live at 26.6 KB of a 35.2 KB reading, 24 times a minute. The
    conversation travels on `/api/screen/data?kind=page`; the screen carries the rooms,
    the ear and the age and nothing else.
    """
    src = (_REPO / "panel" / "tabs" / "chat.py").read_text(encoding="utf-8")
    view = src.split("def web_view")[1].split("\n    def ")[0]
    assert "_web_messages" not in view and "_web_flow" not in view, \
        "the chat screen is building message cards again"
    assert "for chat_type in CHAT_TABS" not in view, \
        "the chat screen loops the channels into cards again"
    assert '"rooms": self._web_rooms()' in view, "the room list left the screen"
    assert '"silent"' in view, "the age of the reading left the screen"



def test_auto_translation_is_off_by_default_and_never_asks_on_a_clock():
    """#2418: «пусть на все новые сообщения … сразу переводить».

    THERE IS NO LANGUAGE ON A MESSAGE, and that is measured rather than assumed — the
    finding is written into `actions/translate_chat_batch.md`: `originalLang` is a field
    the server never fills (40 of 40 empty, and still empty on a message the game had
    just translated), and `isShowTranslateBtn()` answered true for 39 of those 40, so it
    is a permission and not a language. So the switch translates what the game offers,
    and everything expensive about that is pinned here:

    * OFF unless somebody turns it on — it spends the one game link;
    * fed by the ARRIVAL of a message and by nothing else, so an idle chat asks nothing;
    * a BACKLOG read is not «new messages» and must not be queued;
    * never one's own message, and never one already translated.
    """
    src = (_REPO / "panel" / "tabs" / "chat.py").read_text(encoding="utf-8")
    take = src.split("def _tr_take")[1].split("def _tr_flush")[0]
    assert 'record.get("is_mine")' in take, "auto-translation would translate my own"
    assert "self._translated" in take, "a message already translated is asked about again"
    assert "self._can_translate(record)" in take, "it asks for what the game refuses"
    # …and never a message too short to be worth it (#2705).
    assert "self._tr_short(record)" in take, "short messages are queued again"
    pump = src.split("def _pump_chat")[1].split("def _load_backlog")[0]
    assert "if not backlog:\n                    # THE ARRIVAL IS THE SIGNAL" in pump, \
        "the queue is fed by something other than an arrival, or by a backlog read"
    flush = src.split("def _tr_flush")[1].split("def _tr_batch")[0]
    assert "self._tr_at" in flush and "TR_GAP" in flush, "the batches lost their pacing"
    assert "threading.Thread" in flush, "a four-second batch would sit on the Tk thread"
    apply_cfg = src.split("def apply_config")[1].split("def persist_vars")[0]
    assert 'raw.get("chat_autotr", False)' in apply_cfg, \
        "auto-translation is not off by default"
    # …and one batch is one round trip, however many messages it carries.
    recipe = (_REPO / "src" / "lastwar_bot" / "actions"
              / "translate_chat_batch.md").read_text(encoding="utf-8")
    assert recipe.count("\nWAIT ") == 1, "a batch waits once, not once per message"


def test_the_age_over_a_conversation_is_that_conversation_s():
    """#2418: «протухшее без возраста выглядит как свежее» — and so does a stale room
    under somebody else's fresh one.

    Measured live on the panel: «Мировой» whose newest message was 14 minutes old was
    drawn «10 с назад», because the screen's `silent` is the age of the newest message
    in ANY room and a busy season group had just spoken. So the page of one room carries
    the age of what is ON it, judged on the game's clock, and the front-end says that
    over the conversation — `silent` is only the fallback for a page with no messages.

    The page ABOVE must not touch it: paging up would otherwise report the age of
    yesterday's messages as the age of the conversation.
    """
    src = (_REPO / "panel" / "tabs" / "chat.py").read_text(encoding="utf-8")
    page = src.split("def web_data")[1].split("\n    #: A store opened for READING")[0]
    assert '"age": self._age_of(rows[-1].get("ts")) if rows else None' in page, \
        "a page of one room no longer says how old it is"
    aged = src.split("def _age_of")[1].split("\n    def ")[0]
    assert "game_clock.now_ms()" in aged, "the age is judged on the machine's clock"

    view = (_REPO / "panel" / "web" / "app" / "src" / "views"
            / "ChatView.tsx").read_text(encoding="utf-8")
    assert "const [roomAge, setRoomAge]" in view, "the phone dropped the room's own age"
    assert view.count("setRoomAge(") == 2, \
        "the age is set somewhere other than the first draw and the poll"
    older = view.split("const older = useCallback")[1].split("const deeper")[0]
    assert "setRoomAge" not in older, "paging up reports the age of the page above"
    said = view.split("const state = (")[1].split("\n  )")[0]
    assert "roomAge !== null" in said and "span(roomAge)" in said, \
        "the line over the conversation is not the conversation's own age"


def test_a_photograph_the_client_never_fetched_is_said_not_swallowed():
    """#2418: «в чате изображения не грузятся» — and the bubble was EMPTY.

    Measured live on this desktop: the client's download tree holds `LocalImages`
    (14 008 files) and `NewsCenterPhotos` (123) and **no chat-photo cache at all** —
    `ChatPhotos` does not exist, so `/api/chatsprite?photo=…` answered 404 for every
    one of the 29 photo messages in the store while a sprite answered 200. The bytes
    arrive only when the game's own chat window draws the item, and the URL builder is
    unreachable from Lua (`device` is nil, so `getCustomPicUrl` raises).

    Until that is answered, the message must SAY there is a picture: the token is
    stripped whatever happens, so a picture-only message came out as a blank bubble —
    a failure with nothing on screen to explain it.
    """
    src = (_REPO / "panel" / "tabs" / "chat.py").read_text(encoding="utf-8")
    parts = src.split("def _web_parts")[1].split("\n    def ")[0]
    assert '"missing": True' in parts, "an uncached photo is silently swallowed again"

    view = (_REPO / "panel" / "web" / "app" / "src" / "views"
            / "ChatView.tsx").read_text(encoding="utf-8")
    assert "row.photo?.missing" in view and "chat.photo.missing" in view, \
        "the phone draws nothing where a photograph is missing"

    import json as _json
    for path in sorted((_REPO / "panel" / "locales").glob("*.json")):
        words = _json.loads(path.read_text(encoding="utf-8"))
        assert "chat.photo.missing" in words, f"{path.name} has no chat.photo.missing"


def test_the_panel_fetches_a_photograph_the_client_never_did():
    """#2418: nothing else was ever going to fetch it.

    The client downloads a chat photograph while its own chat window draws the message,
    and the panel reads chat without opening it — so `ChatPhotos` did not exist on this
    machine at all and every bubble was blank. The picture is named on the game's own
    CDN by the same pair that names it on disk (the sender uid and the `[photo:N]`
    number), so the route that SERVES one gets it once, itself.
    """
    import hashlib

    sys.path.insert(0, str(_REPO / "tools"))
    import chat_assets

    # The address is derived, never stored: the last six digits of the uid as a folder
    # and md5("<uid>_<ver>") as the name. Invented values of the right shape.
    uid, ver = "1000000000000001", "429"
    name = hashlib.md5(f"{uid}_{ver}".encode()).hexdigest()
    small = chat_assets.photo_url(uid, ver)
    big = chat_assets.photo_url(uid, ver, big=True)
    assert small.endswith(f"/000001/{name}.jpg"), small
    assert big.endswith(f"/000001/{name}_big.jpg"), big
    assert chat_assets.photo_url("Player1", ver) is None, \
        "a uid that is not digits became part of a filename"
    assert chat_assets.photo_url(uid, "../x") is None, \
        "a version that is not digits became part of a filename"

    src = (_REPO / "tools" / "chat_assets.py").read_text(encoding="utf-8")
    named = src.split("def photo_named")[1].split("\ndef ")[0]
    assert "photo_fetch" in named, \
        "the route serving a photo no longer fetches one this machine has not got"
    link = src.split("def photo_link")[1].split("\ndef ")[0]
    assert "photo_path" not in link, \
        "a link is gated on the disk again, so a picture that CAN be had is never asked for"
    plain = src.split("def _through_a_plain_interpreter")[1].split("\ndef ")[0]
    assert "game_paths.win_python()" in plain, \
        "the retry names an interpreter of its own instead of asking for the machine's"
    assert "CREATE_NO_WINDOW" in plain, \
        "a console window blinks on the desktop every time a chat is scrolled"

    fetch = src.split("def photo_fetch")[1].split("\ndef ")[0]
    assert "_through_a_plain_interpreter" in fetch, \
        "a process the machine keeps off the network gives up instead of asking one it lets on"
    assert "_PHOTO_MISSES" in fetch, \
        "a 404 is asked again for every bubble on every scroll"
    assert 'b"\\xff\\xd8"' in fetch, \
        "the CDN's own error document would be written to disk as a picture"

    view = (_REPO / "panel" / "web" / "app" / "src" / "views"
            / "ChatView.tsx").read_text(encoding="utf-8")
    assert "onError" in view and "setGone(" in view, \
        "a picture the panel could not get is a broken image — the blank bubble again"


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
