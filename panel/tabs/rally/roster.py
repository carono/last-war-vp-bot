"""The banners that are standing RIGHT NOW: who is in them, what for, how much room.

The «Ралли» tab could always say that a rally had been heard of — one line in a log,
scrolled past by six other producers — and never what was standing on the map at the
moment somebody looked. That is the half a person actually wants: which banners are up,
what each is going for, who has already joined it, and whether there is a seat left.

**It lives on events, not on a clock.** The wire announces a banner
(`push.alliance.march.create`), announces every joiner (`…refresh`) and announces the
end of it (`…remove`, `{teamUuid, isCancel}` — launched or cancelled). Each of those is
one line out of the capture the tab already runs, and each is what MOVES this model. A
poll would be the wrong shape twice over: a rally lives tens of seconds, so a minute's
poll would miss most of them entirely, and a poll running all day is a client held in
front of the next banner for nothing.

**The composition is read from the GAME, not assembled from the wire.** The panel keeps
no second version of who is in a banner: a push wakes it up and it then asks
`DataCenter.WorldMarchDataManager:GetAllMarches()`, which is the client's own march
table and the same reading the join is sieved from. What the wire keeps is exactly the
three things the client's record does NOT carry (docs/research/rally-join.md — 25 of the
push's 33 fields survive into a march): the banner's seat count (`assemblyMarchMax`),
what it is going for (`targetContentId`) and where a joiner is sent. Those are the
wire's own facts, not the panel's opinion of them.

**A banner is therefore in one of three states**, and they are not the same news:

| state | what it means |
|---|---|
| `wire` | the push has landed, the client's march table has not caught up — median 10 s, and in most late cases only once somebody ELSE joined (#1301). Shown at once, with what the push said, so the screen is never behind the game. |
| `open` | the client knows it: the members, the leader and the target tile are the game's own reading. |
| `gone` | it launched, was cancelled, or simply left the march table. Kept on screen for a couple of minutes, greyed, because «what happened to that banner» is a question asked after the fact. |

**The faces come out of the client's own cache** (`tools/lib/player_faces.py`) — the
photo the player uploaded, else the built-in avatar their `headSkinId` names, else
nothing and the front-end draws an initial. Nothing is fetched from anywhere.

**Nothing here is module state.** One roster belongs to one tab, which belongs to one
profile: two accounts see two different alliances, and a banner of one of them showing
up on the other's screen would be the same class of leak `panel/runtime/claims.py` and
`game_process.capture_narrowing` exist to stop (docs/research/profile-isolation.md).
`reset()` empties it when the profile changes.
"""
from __future__ import annotations

import threading
import time

# The kinds a banner can be, as the game names them. `tools/lib` is on the path by the
# time the panel imports this (panel/runtime/paths.py), exactly as it is for
# `panel/rally_limits.py` — and this is the SAME table the per-kind budget is keyed by,
# on purpose: two ways of naming one banner is how a door and a tally start disagreeing.
import rally_kinds                                                    # noqa: E402

#: How many banners the block draws. An alliance event puts a dozen up at once and a
#: screen that scrolls for ever is a screen nobody reads; the newest are the ones a
#: person can still act on.
MAX_BANNERS = 12

#: How long a banner the wire announced may go unconfirmed by the client before it is
#: given up on. The measured lag is a median of 10 s (#1301); this is that with room.
WIRE_GRACE_SEC = 90.0

#: How long a finished banner stays on screen, greyed. «Where did that one go» is asked
#: after it has gone, and an empty block answers nothing.
GONE_KEEP_SEC = 150.0

#: The floor between two reads of the game. Every push is an event and an event-driven
#: model would otherwise read once per joiner — a busy banner is a push every couple of
#: seconds, times however many banners are up.
READ_GAP_SEC = 1.5

#: What the read writes on its line, and what the harvester picks out of the log.
MARKER = "RLYR"


class Member:
    """One squad standing in a banner, as the client's march table has it."""

    __slots__ = ("uid", "name", "head", "power", "leader", "mine", "face")

    def __init__(self, uid: str, name: str, head: str, power: int,
                 leader: bool, mine: bool) -> None:
        self.uid = uid
        self.name = name
        self.head = head
        self.power = power
        self.leader = leader
        self.mine = mine
        #: The picture to draw, resolved off the client's cache on the read's own
        #: thread — never on the Tk thread, where the first lookup for a uid costs a
        #: few thousand md5 sums (`player_faces.face_for`).
        self.face = None


class Banner:
    """One rally request, merged from what the wire said and what the game holds."""

    __slots__ = ("team", "content", "name_key", "kind", "level", "seats_taken",
                 "seats_cap", "point", "server", "target", "members", "heard_at",
                 "read_at", "gone_at", "ending", "mine")

    def __init__(self, team: str) -> None:
        self.team = team
        #: `targetContentId` off the push — the one field that says what the banner is
        #: going for, and the client's march record does not carry it.
        self.content = ""
        #: …resolved in the game's own config: the monster's `name` key and its level.
        self.name_key = ""
        self.kind = ""
        self.level = 0
        self.seats_taken = 0
        self.seats_cap = 0
        #: Where a JOINER is sent (the leader's tile), off the push.
        self.point = 0
        self.server = 0
        #: Where the banner is GOING (the monster), off the game — `(x, y)` or None.
        self.target = None
        self.members: list = []
        self.heard_at = time.time()
        self.read_at = 0.0
        self.gone_at = 0.0
        #: How it ended, when it has: `launched` / `cancelled` / `closed`.
        self.ending = ""
        #: Is one of our own squads in it? (The game read answers; the wire cannot.)
        self.mine = False

    @property
    def state(self) -> str:
        if self.gone_at:
            return "gone"
        return "open" if self.read_at else "wire"

    @property
    def taken(self) -> int:
        """How many seats are filled — the LARGER of the two counts, never the newer.

        Both are floors of the truth and they disagree: of 21 squads sent at a banner
        the wire had last announced as 5 of 5, not one arrived, because the client's own
        count was the one that was behind (#1281). The same rule the join is sieved by.
        """
        return max(len(self.members), self.seats_taken)

    @property
    def free(self) -> int:
        """Seats left, or -1 when the wire never said how big the banner is."""
        return (self.seats_cap - self.taken) if self.seats_cap else -1


class RallyRoster:
    """The live model behind the block. Fed by the capture, read from the game."""

    def __init__(self, rt, on_event=None, on_change=None) -> None:
        self.rt = rt
        #: Called with (key, fmt) for every transition worth a line in the log. The tab
        #: owns the words: everything here is a locale key and nothing is a sentence.
        self._on_event = on_event
        #: Called when the model moved and the two front-ends should be redrawn.
        self._on_change = on_change
        self._lock = threading.Lock()
        self._banners: dict = {}
        self._reading = False
        self._last_read = 0.0
        self._pending = False
        self._stopped = False

    # -- what the wire says --------------------------------------------------
    def heard(self, team: str, *, content: str = "", seats: str = "",
              point=None, count: int = 0) -> None:
        """A `create` / `refresh` push for `team` — with the fields only it carries.

        Called on the capture child's reader thread. It records the wire's own three
        facts and asks for a read; it does NOT invent a membership list out of the names
        on the line, because the game is about to be asked for the real one.
        """
        if self._stopped or not team:
            return
        fresh = False
        with self._lock:
            banner = self._banners.get(team)
            if banner is None:
                banner = self._banners[team] = Banner(team)
                fresh = True
            banner.heard_at = time.time()
            if banner.gone_at:
                # The same banner cannot come back, but a stale `gone` sitting in front
                # of a live push would hide it; the wire is the newer word.
                banner.gone_at, banner.ending = 0.0, ""
            if content:
                banner.content = str(content)
            if seats:
                taken, _, cap = str(seats).partition("/")
                if cap.isdigit():
                    banner.seats_cap = int(cap)
                if taken.isdigit():
                    banner.seats_taken = int(taken)
                elif not cap.isdigit() and str(seats).isdigit():
                    banner.seats_cap = int(seats)
            if count > banner.seats_taken:
                banner.seats_taken = int(count)
            if point:
                banner.point, banner.server = int(point[0]), int(point[1])
        if fresh:
            self._say("rally_roster.event.up", team=team)
        self.refresh_async()

    def ended(self, team: str, ending: str) -> None:
        """A `remove` push: the banner launched (`launched`) or was cancelled.

        The client's march table loses it at the same moment, so the read would notice
        anyway — but only the wire says WHICH of the two happened, and «стяг ушёл» and
        «стяг отменили» are not the same news to somebody deciding whether to send a
        squad after it.
        """
        if self._stopped or not team:
            return
        with self._lock:
            banner = self._banners.get(team)
            if banner is None or banner.gone_at:
                return
            banner.gone_at = time.time()
            banner.ending = ending or "closed"
        self._say(f"rally_roster.event.{ending or 'closed'}", team=team)
        self._changed()

    # -- what the game holds -------------------------------------------------
    def refresh_async(self) -> None:
        """Read the marches on a worker, at most one at a time and not too often.

        A busy alliance pushes several times a second; a read per push would be a
        client held in front of the next banner. One in flight, one queued, and the
        queued one runs when the floor has passed.
        """
        if self._stopped:
            return
        with self._lock:
            if self._reading:
                self._pending = True
                return
            self._reading = True
        threading.Thread(target=self._read_work, daemon=True).start()

    def _read_work(self) -> None:
        try:
            while True:
                wait = READ_GAP_SEC - (time.time() - self._last_read)
                if wait > 0:
                    time.sleep(wait)
                self._last_read = time.time()
                self._apply(self._read())
                with self._lock:
                    if not self._pending or self._stopped:
                        self._reading = False
                        return
                    self._pending = False
        except Exception:                    # noqa: BLE001 — a reading, never a run
            with self._lock:
                self._reading = False

    def _read(self) -> "list | None":
        """The banners the client holds, as parsed rows. `None` when it cannot answer.

        `None` and `[]` must never look alike: an empty list means «the game says there
        are no banners», which retires everything, and a client that cannot be reached
        must leave the screen exactly as it is.
        """
        try:
            if not self.rt.game.ready():
                return None
        except Exception:                    # noqa: BLE001
            return None
        try:
            lines = self.rt.game.evaluator().run(
                _chunk(self._target_pairs()), marker=MARKER, settle=0.6, early=True)
        except Exception:                    # noqa: BLE001
            return None
        rows, saw_end = [], False
        for line in lines or []:
            if MARKER not in line:
                continue
            body = line.split(MARKER, 1)[1].strip()
            if body == ".":
                saw_end = True
                continue
            row = _parse_row(body)
            if row is not None:
                rows.append(row)
        return rows if (rows or saw_end) else None

    def _target_pairs(self) -> str:
        """`team:contentId,…` — what the wire heard, for the config lookup in the read.

        The same shape the join is handed (`tab.target_map`), and for the same reason:
        the id is the wire's and the table that resolves it is the game's.
        """
        with self._lock:
            return ",".join(f"{b.team}:{b.content}" for b in self._banners.values()
                            if b.content and str(b.content).isdigit())

    def _apply(self, rows) -> None:
        """Merge a reading into the model and say what changed."""
        if rows is None:
            self._prune()
            return
        events = []
        now = time.time()
        seen = set()
        with self._lock:
            for row in rows:
                team = row["team"]
                seen.add(team)
                banner = self._banners.get(team)
                if banner is None:
                    banner = self._banners[team] = Banner(team)
                    events.append(("rally_roster.event.up", {"team": team}))
                before = {m.uid: m for m in banner.members}
                banner.members = row["members"]
                banner.read_at = now
                banner.gone_at, banner.ending = 0.0, ""
                banner.target = row["target"]
                if row["server"]:
                    banner.server = row["server"]
                if row["name_key"]:
                    banner.name_key = row["name_key"]
                    banner.kind = rally_kinds.KIND_OF_NAME.get(
                        row["name_key"], rally_kinds.FALLBACK_KIND)
                if row["level"]:
                    banner.level = row["level"]
                banner.mine = any(m.mine for m in banner.members)
                # WHO CAME AND WHO LEFT, by uid — a name is not an identity and two
                # players may well share one. The count is not the answer either: one
                # joiner and one leaver between two reads leave it unchanged.
                for member in banner.members:
                    if member.uid and member.uid not in before:
                        events.append(("rally_roster.event.joined",
                                       {"team": team, "who": member.name}))
                for uid, member in before.items():
                    if uid and uid not in {m.uid for m in banner.members}:
                        events.append(("rally_roster.event.left",
                                       {"team": team, "who": member.name}))
            for team, banner in self._banners.items():
                if team in seen or banner.gone_at:
                    continue
                # A banner the client HAD and no longer has is over. One it has never
                # had yet is not: the client is a median of 10 s behind the push.
                if banner.read_at:
                    banner.gone_at, banner.ending = now, "closed"
                    events.append(("rally_roster.event.closed", {"team": team}))
        self._faces()
        self._prune()
        for key, fmt in events:
            self._say(key, **fmt)
        self._changed()

    def _faces(self) -> None:
        """Put a face on every member, off the client's own cache. On THIS thread.

        The first lookup for a uid walks a few thousand md5 sums and then shrinks a
        photo; after that it is a dictionary hit, so it is done here — on the read's
        worker — and never on the Tk thread that draws the block.
        """
        try:
            import player_faces
        except Exception:                    # noqa: BLE001 — no cache is an answer
            return
        with self._lock:
            wanted = [m for b in self._banners.values() for m in b.members
                      if m.face is None]
        for member in wanted:
            try:
                member.face = player_faces.face_for(member.uid, member.head) or ""
            except Exception:                # noqa: BLE001 — a face, never the run
                member.face = ""

    # -- what the front-ends read --------------------------------------------
    def banners(self) -> list:
        """A snapshot for drawing: the live ones first, newest first, then the gone."""
        self._prune()
        with self._lock:
            rows = list(self._banners.values())
        rows.sort(key=lambda b: (bool(b.gone_at), -(b.read_at or b.heard_at)))
        return rows[:MAX_BANNERS]

    def counts(self) -> tuple:
        """`(live, gone)` — what the heading says without anybody scrolling."""
        rows = self.banners()
        live = sum(1 for b in rows if not b.gone_at)
        return live, len(rows) - live

    def _prune(self) -> None:
        now = time.time()
        with self._lock:
            for team, banner in list(self._banners.items()):
                if banner.gone_at and now - banner.gone_at > GONE_KEEP_SEC:
                    del self._banners[team]
                elif (not banner.read_at and not banner.gone_at
                        and now - banner.heard_at > WIRE_GRACE_SEC):
                    # Announced and never confirmed by the client: it was over before
                    # the client caught up. Retired quietly — there is nothing to say
                    # about a banner nobody here ever saw the inside of.
                    del self._banners[team]

    def reset(self) -> None:
        """Another account, another alliance: nothing of this one may survive."""
        with self._lock:
            self._banners.clear()
            self._pending = False
        self._changed()

    def stop(self) -> None:
        self._stopped = True

    # -- plumbing -------------------------------------------------------------
    def _say(self, key: str, **fmt) -> None:
        if self._on_event is not None:
            try:
                self._on_event(key, fmt)
            except Exception:                # noqa: BLE001 — a log line, never the run
                pass

    def _changed(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:                # noqa: BLE001 — a repaint, never the run
                pass


# --- the read itself --------------------------------------------------------------
#
# One chunk, one round trip. A call into the game VM was measured at 0.14 s with the
# daemon free and 10–19 s under the panel's ordinary background load (#1281), so a
# screen that asked four questions would be a screen four banners behind.


def _chunk(targets: str) -> str:
    """The Lua that lists every banner the client holds, one log line each.

    `targets` is `team:contentId,…` off the wire: the client's march record has no
    `targetContentId`, so what a banner is GOING for can only be resolved by handing the
    id the push carried to the game's own `lw_world_monster` table — which is exactly
    what the join's own sieve does with the same string (`lua_actions.rally_join_all`).

    The `name` key that comes back is the species, and `rally_kinds.KIND_OF_NAME` — the
    one table the per-kind budget is keyed by — turns it into the kind the panel already
    has a translated label for. There is no second classifier here.
    """
    return (
        "local function g(o,k) local ok,v=pcall(function() return o[k] end) "
        "if ok then return v end return nil end "
        "local wm=DataCenter.WorldMarchDataManager "
        "local col=wm and wm:GetAllMarches() "
        "if col==nil then CS.UnityEngine.Debug.LogError('" + MARKER + " .') return end "
        # Our own uid, so a banner can say «one of ours is in it» without the panel
        # having to guess from a name.
        "local me='' pcall(function() me=tostring(LuaEntry.Player.uid) end) "
        # The avatar a member wears. The march record carries it for some, the alliance
        # roster for the rest — and the roster is the only source for a member whose
        # march does not repeat it (docs/research/player-avatars.md).
        "local heads={} pcall(function() "
        "local list=DataCenter.AllianceMemberDataManager.allianceMembers "
        "if list~=nil then for _,m in pairs(list) do local u=g(m,'uid') "
        "if u~=nil then heads[tostring(u)]=tostring(g(m,'headSkinId') or '') end end end end) "
        # What each banner is going for, off the wire, resolved in the game's config.
        "local target_of={} "
        "pcall(function() for pair in string.gmatch('" + targets + "','[^,]+') do "
        "local t,c=string.match(pair,'(%d+):(%d+)') "
        "if t~=nil then target_of[t]=tonumber(c) end end end) "
        "local LCI=nil pcall(function() LCI=LocalController.instance() end) "
        "local function species(cid) "
        "if LCI==nil or cid==nil then return '','' end "
        "local nm,lv='','' "
        "pcall(function() nm=tostring(LCI:getValue('lw_world_monster',cid,'name',nil) or '') end) "
        "pcall(function() lv=tostring(LCI:getValue('lw_world_monster',cid,'level',nil) or '') end) "
        "return nm,lv end "
        "local R,order={},{} "
        "local e=col:GetEnumerator() "
        "while e:MoveNext() do "
        "local mo=e.Current.Value if mo==nil then mo=e.Current end "
        "local team=g(mo,'teamUuid') local ts=tostring(team) "
        "if team~=nil and ts~='0' and ts~='nil' then "
        "local r=R[ts] if r==nil then r={m={}} R[ts]=r order[#order+1]=ts end "
        "local uid=tostring(g(mo,'ownerUid') or '') "
        # The separators are ours, so a name carrying one would split a row in half.
        "local nm=tostring(g(mo,'ownerName') or '?') nm=string.gsub(nm,'[|~,]',' ') "
        "local hd=tostring(g(mo,'headSkinId') or heads[uid] or '') "
        "local pw=0 pcall(function() pw=math.floor(tonumber(g(mo,'power')) or 0) end) "
        "local lead='0' "
        "pcall(function() if tostring(g(mo,'uuid'))==tostring(team-1) then lead='1' end end) "
        "if lead=='1' then r.pt=tostring(g(mo,'targetPos') or '') "
        "r.sv=tostring(g(mo,'serverId') or g(mo,'targetServer') or '') end "
        "local mine='0' if uid~='' and uid==me then mine='1' end "
        "r.m[#r.m+1]=uid..'~'..nm..'~'..hd..'~'..tostring(pw)..'~'..lead..'~'..mine "
        "end end "
        "for _,ts in ipairs(order) do local r=R[ts] "
        "local nm,lv=species(target_of[ts]) "
        "CS.UnityEngine.Debug.LogError('" + MARKER + " '..ts..'|'..tostring(r.pt or '')"
        "..'|'..tostring(r.sv or '')..'|'..nm..'|'..lv..'|'..table.concat(r.m,',')) end "
        "CS.UnityEngine.Debug.LogError('" + MARKER + " .')"
    )


def _parse_row(body: str):
    """One `RLYR` line back into a row, or None when it is not one."""
    parts = body.split("|")
    if len(parts) < 6 or not parts[0].strip().isdigit():
        return None
    team, point, server, name_key, level, members = (p.strip() for p in parts[:6])
    return {
        "team": team,
        "target": _tile(point),
        "server": int(server) if server.isdigit() else 0,
        "name_key": name_key,
        "level": int(level) if level.isdigit() else 0,
        "members": [m for m in (_member(raw) for raw in members.split(",")) if m],
    }


def _member(raw: str):
    bits = raw.split("~")
    if len(bits) < 6:
        return None
    uid, name, head, power, leader, mine = (b.strip() for b in bits[:6])
    return Member(uid=uid, name=name or "?", head=head,
                  power=int(power) if power.isdigit() else 0,
                  leader=leader == "1", mine=mine == "1")


def face_url(path: str) -> str:
    """A face as the phone asks for it: `/api/avatar?face=<file name>`.

    Only the NAME travels, never the path — the route serves one folder
    (`game_paths.avatar_cache()`) and refuses anything that is not a plain name in it,
    so a link cannot be talked into reading somewhere else. The picture is fetched by
    the browser, cached by it, and asked for once however many polls redraw the screen.
    """
    import os as _os
    import urllib.parse as _url

    return "/api/avatar?face=" + _url.quote(_os.path.basename(path or ""))


class FaceImages:
    """The faces as Tk images, one per (file, size), bounded.

    A live Tk image is a live X resource, and an evening of an alliance event puts
    hundreds of distinct players through the block — the chat tab learned that the
    expensive way and bounds its own cache for the same reason. What falls out is what
    has not been drawn for longest; the banners on screen always keep their pictures.

    Belongs to a tab, like every other widget: one window, one Tk root, one cache.
    """

    #: Distinct pictures kept alive. A banner holds five people, the block a dozen
    #: banners, so this is several screens' worth.
    MAX = 120

    def __init__(self) -> None:
        self._cache: dict = {}

    def get(self, path: str, px: int):
        """The picture at `path` drawn `px` tall, or None when it cannot be read."""
        if not path:
            return None
        key = (path, px)
        image = self._cache.get(key)
        if image is not None:
            self._cache[key] = self._cache.pop(key)          # touch (LRU)
            return image
        try:
            from PIL import Image as _Image, ImageTk as _ImageTk
            with _Image.open(path) as raw:
                picture = raw.convert("RGBA")
                width, height = picture.size
                if height and height != px:
                    width = max(1, round(width * px / height))
                    picture = picture.resize((width, px), _Image.LANCZOS)
                image = _ImageTk.PhotoImage(picture)
        except Exception:                    # noqa: BLE001 — a face, never the run
            return None
        self._cache[key] = image
        while len(self._cache) > self.MAX:
            self._cache.pop(next(iter(self._cache)))
        return image

    def forget(self) -> None:
        self._cache.clear()


def _tile(packed: str):
    """A packed world point (`y * 1000 + x`) as `(x, y)`, or None.

    The same encoding `lastwar_proto._unpack_march_pos` decodes on the wire side; it is
    spelled out here rather than imported so that drawing a banner does not pull the
    whole protocol module into the panel.
    """
    raw = str(packed or "").strip()
    if not raw.isdigit():
        return None
    number = int(raw)
    if number <= 0:
        return None
    return number % 1000, number // 1000
