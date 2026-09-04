/* THE CHAT AS A CONVERSATION (#2064).
 *
 * The person's words: «Интерфейс чата как в телеграм, внизу окно ввода сообщения и
 * сортировка от старых к новым, старые нужно чтобы была возможность вверх прокручивать с
 * дозагрузкой, в игре именно такой механизм». A conversation is not a card of rows — it
 * reads oldest at the top, it opens on the newest message, the box to answer in is at
 * the bottom, and going back in time is a scroll rather than a button. So the chat
 * screen says it is DRAWN (`map: {kind: "chat"}`) and this is what draws it, through the
 * same door the world map goes through (#2018).
 *
 * SCROLLING UP READS THE DATABASE FIRST, AND THE GAME ONLY WHEN THE DATABASE IS SPENT.
 * Every page comes off `/api/screen/data?kind=page`, which is this profile's own SQLite
 * history answered on an HTTP worker thread (`panel/tabs/chat.py::web_data`). No round
 * trip, so a thumb flicking upwards cannot turn a gesture into a poll — the panel's
 * «read once, then LISTEN» rule holds by construction.
 *
 * WHEN THE STORE RUNS OUT the panel asks the SERVER, once, for the slice above it
 * (the person's words: «Опрос сервера при прокрутке тоже сделай, если у нас нет
 * сообщений»). The rules that ask obeys are the person's own and they are kept on the
 * panel's side (`chat.py::_ask_server_for_older`): the store is always read first, the
 * request rides a SCROLL and never a clock, one scroll makes one request, the slice is
 * never asked for twice — the cursor is the client's own — and «there is nothing
 * earlier» is remembered per room. This side shows the two states a person has to be
 * able to tell apart: a reading is on its way (the button says so and is disabled), or
 * the history has ended (a line says so and there is no button left to press).
 *
 * THE SCROLL MUST NOT JUMP when older messages arrive above what is being read. The
 * pane's height is measured BEFORE the prepend and the same distance is added back to
 * `scrollTop` in a layout effect, so the message under the thumb stays under the thumb.
 * The opposite rule holds at the bottom: a new message scrolls the pane down only when
 * the reader was already at the bottom, never while they are reading history.
 *
 * The time on a bubble is the GAME's — the panel stamps it (`_web_row`), because a
 * stamp in the game's milliseconds judged against the machine's clock is a mistake this
 * repository has already made once.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { get, post } from '../api'
import { span, t } from '../i18n'
import { Marked } from '../ui/Coord'
import { Modal } from '../ui/Modal'
import { pressWord } from '../ui/press'
import { useToast } from '../ui/Toast'
import type { ChatRoomTab, CoordPart, PressAnswer } from '../types'

/** One piece of a message: words (possibly with places marked in them) or a sprite. */
export interface ChatPart {
  t: 'text' | 'img'
  v: string
  parts?: ({ t: string } | { c: CoordPart })[] | null
}

/** One message, as `panel/tabs/chat.py::_web_row` sends it. */
export interface ChatRow {
  id: string
  /** The message's own sequence id in its room — what a translate press names. */
  seq?: string
  /** Does the GAME offer to translate this one? Its own answer, never a guess here. */
  tr?: boolean
  /** The sender's own face, as a link — `''` for somebody who never uploaded one. */
  face?: string
  ts: number
  when: string
  /** The day this message belongs to, when it is not today: a key or a date (data). */
  day: string
  who: string
  uid: string
  alliance: string
  mine: boolean
  room: string
  parts: ChatPart[]
  photo?: { small: string; big: string } | null
  /** What this message answers, when it answers something: the quote the game draws,
   *  and the id of the row it names (#2418). */
  reply?: { id: string; who: string; text: string } | null
}

interface Page {
  rows: ChatRow[]
  more: boolean
  room: string
  type: string
  /** Is there still a point in asking the GAME for what lies above the store. */
  server?: boolean
  /** The room such an ask would name — a channel does not name its own. */
  deep_room?: string
}

/** What the deep read answers with (`chat.py::_ask_server_for_older`). */
interface Deep {
  ok?: boolean
  got?: number
  end?: boolean
  reason?: string
}

interface Contact {
  room: string
  who: string
  uid: string
  text: string
  ts: number
  when: string
  mine: boolean
  unread: number
}

/** The sprites behind the two buttons by the send box: what to write with, what to send. */
interface Sprites {
  emoji: { id: string; icon: string; token: string }[]
  stickers: { id: string; name: string; icon: string }[]
}

/** How many private conversations the list shows before folding the rest away. */
const PEOPLE_FOLD = 6

/** One face: the picture when there is one, the initial when there is not. A group has
 *  no picture at all — measured, not assumed (#2418) — and neither has a player who
 *  never uploaded one, so both draw a letter rather than borrowing anybody's art. */
function Face({ label, face }: { label: string; face?: string }) {
  if (face) return <img className="chatface" src={face} alt="" />
  return <span className="chatface letter">{(label || '?').slice(0, 1).toUpperCase()}</span>
}

/** How close to the bottom still counts as «reading the newest», in pixels. */
const GLUE = 48

/** How tall the message box may grow before it scrolls instead — about five lines. */
const GROW_MAX = 128

/** How close to the top starts fetching the page above, in pixels. */
const REACH = 80

/** A channel's own name — the key is built here rather than inside `t()`, because a key
 *  spelled by concatenation at the call site is a key the locale check cannot see. */
function tabKey(type: string): string {
  return 'chat.tab.' + type
}

function sameDay(a: ChatRow, b: ChatRow | undefined): boolean {
  return !!b && a.day === b.day
}

export function ChatView({
  screen,
  rooms,
  listening,
  silent,
  waiting,
  pollKey,
}: {
  screen: string
  rooms: ChatRoomTab[]
  listening: boolean
  /** Seconds since the newest message the panel has filed, or null for none at all. */
  silent: number | null
  /** The monitor is on but its reader is down and being brought back. */
  waiting: boolean
  pollKey: number
}) {
  const toast = useToast()
  const [type, setType] = useState('world')
  //: The private thread being read, when one is open. A channel has no thread: it IS
  //: its room, and the panel resolves that itself.
  const [room, setRoom] = useState('')
  const [rows, setRows] = useState<ChatRow[]>([])
  const [more, setMore] = useState(false)
  const [busy, setBusy] = useState(false)
  //: Is the SERVER still worth asking for what lies above the store, and which room
  //: such an ask would name. Both come off the page the panel just served.
  const [server, setServer] = useState(false)
  const [deepRoom, setDeepRoom] = useState('')
  //: The ask is in the game right now — a round trip, so it is shown rather than
  //: hidden: the button says it and stays disabled until the answer lands.
  const [deep, setDeep] = useState(false)
  //: How many messages have arrived while the reader was NOT at the bottom. They are
  //: put in place immediately — the list is a conversation, not a feed — but the view
  //: is not dragged down under a thumb that is reading history; this is what says they
  //: are there, and pressing it goes to them.
  const [unseen, setUnseen] = useState(0)
  const [contacts, setContacts] = useState<Contact[]>([])
  //: Is the drawer out? Only ever true on a narrow screen — the wide one draws the
  //: list beside the conversation and this does nothing.
  const [open, setOpen] = useState(false)
  //: Are all the private conversations shown, or the newest handful?
  const [all, setAll] = useState(false)
  //: Which picker is open — the emoji to write with, or the stickers to send — and what
  //: came back for it. Fetched when it is opened: a chat nobody is decorating costs
  //: nothing, and two hundred sprites are not something to carry on every draw.
  //: The message a quote was tapped to reach — highlighted for a moment when it is
  //: found, so a jump into the middle of a conversation is visible.
  const [lit, setLit] = useState('')
  const [picker, setPicker] = useState<'emoji' | 'sticker' | null>(null)
  const [sprites, setSprites] = useState<Sprites>({ emoji: [], stickers: [] })
  const [text, setText] = useState('')
  const [photo, setPhoto] = useState<string | null>(null)
  /* WHAT THE GAME TRANSLATED, per message id, and which rows are showing it (#2418).
     Both are kept here rather than on the row: the original must never be lost — a
     translation is a second reading of a message, not a replacement for it — so a tap
     puts it back with nothing asked of the game. */
  const [tr, setTr] = useState<Record<string, string>>({})
  const [asTr, setAsTr] = useState<Record<string, boolean>>({})
  const [tring, setTring] = useState('')
  const pane = useRef<HTMLDivElement | null>(null)
  //: The message box, so a send that empties it puts it back to one line.
  const box = useRef<HTMLTextAreaElement | null>(null)
  //: The pane's height just before older messages were put above what is on screen.
  const held = useRef(0)
  //: Was the reader at the bottom when this page was asked for? Decides whether a new
  //: message pulls the view down or is left waiting below.
  const glued = useRef(true)

  const link = useCallback(
    (before?: number) =>
      '/api/screen/data?id=' +
      encodeURIComponent(screen) +
      '&kind=page&type=' +
      encodeURIComponent(type) +
      (room ? '&room=' + encodeURIComponent(room) : '') +
      (before ? '&before=' + encodeURIComponent(String(before)) : ''),
    [screen, type, room],
  )

  /* A SENT MESSAGE PUTS THE BOX BACK TO ONE LINE. Without this the field keeps the
     height of what was just sent, and the conversation stays four lines shorter. */
  useEffect(() => {
    const el = box.current
    if (el && !text) el.style.height = 'auto'
  }, [text])

  /** A message box that follows the message: one line, then more, capped at five. */
  const grew = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, GROW_MAX) + 'px'
  }

  const atBottom = () => {
    const el = pane.current
    if (!el) return true
    return el.scrollHeight - el.scrollTop - el.clientHeight < GLUE
  }

  /** The newest page of this channel or thread — what opening it shows. */
  const draw = useCallback(async () => {
    try {
      const page = await get<Page>(link())
      held.current = 0
      glued.current = true
      setRows(page.rows || [])
      setMore(!!page.more)
      setServer(!!page.server)
      setDeepRoom(String(page.deep_room || ''))
    } catch {
      /* the tick says so */
    }
  }, [link])

  useEffect(() => {
    setRows([])
    setMore(false)
    setServer(false)
    setDeepRoom('')
    setUnseen(0)
    void draw()
  }, [draw])

  /* WHAT IS OPEN WHEN NOTHING HAS BEEN CHOSEN YET (#2418). The first row of the
     client's own list — never «the world», which is what a default cost last time. The
     bar over the conversation says which room it is, and the send names it outright. */
  useEffect(() => {
    if (room || !rooms.length) return
    const first = rooms.find((r) => r.room)
    if (first) {
      setType(first.type)
      setRoom(first.room)
    }
  }, [rooms, room])

  /* THE CONTACT LIST IS ITS OWN READING, and it is asked for only while «ЛС» is open
     with no thread chosen — a channel has no contacts and must not fetch a list. */
  useEffect(() => {
    if (type !== 'dm' || room) return
    let alive = true
    void (async () => {
      try {
        const answer = await get<{ contacts: Contact[] }>(
          '/api/screen/data?id=' + encodeURIComponent(screen) + '&kind=contacts',
        )
        if (alive) setContacts(answer.contacts || [])
      } catch {
        /* an empty list is what a closed store looks like */
      }
    })()
    return () => {
      alive = false
    }
  }, [screen, type, room, pollKey])

  /* WHAT ARRIVED SINCE. The screen's own poll is the beat — it is the panel's database
     being read, not the game being asked — and what comes back is MERGED rather than
     swapped in, so history somebody has scrolled up to is not thrown away under them. */
  useEffect(() => {
    if (!pollKey) return
    glued.current = atBottom()
    void (async () => {
      try {
        const page = await get<Page>(link())
        const fresh = page.rows || []
        setRows((prev) => {
          if (!prev.length) return fresh
          const seen = new Set(prev.map((r) => r.id))
          const added = fresh.filter((r) => !seen.has(r.id))
          if (!added.length) return prev
          // NOT AT THE BOTTOM = do not drag them there. The rows go in either way —
          // scrolling down must find them already in place — and the counter is what
          // tells the reader something arrived while they were up in the history.
          if (!glued.current) setUnseen((n) => n + added.length)
          return [...prev, ...added].sort((a, b) => a.ts - b.ts)
        })
      } catch {
        /* the tick says so */
      }
    })()
     
  }, [pollKey])

  /** The page above the one being read — the store, and only ever the store. */
  const older = useCallback(async () => {
    const el = pane.current
    if (busy || !more || !rows.length) return
    setBusy(true)
    held.current = el ? el.scrollHeight : 0
    try {
      const page = await get<Page>(link(rows[0].ts))
      const above = page.rows || []
      setMore(!!page.more)
      setServer(!!page.server)
      setDeepRoom(String(page.deep_room || ''))
      if (above.length) {
        const seen = new Set(rows.map((r) => r.id))
        setRows((prev) => [...above.filter((r) => !seen.has(r.id)), ...prev])
      } else {
        held.current = 0
      }
    } catch {
      held.current = 0
    } finally {
      setBusy(false)
    }
  }, [busy, more, rows, link])

  /** The slice ABOVE the store — the one reading in this screen that costs a round trip.
   *
   *  Ordered the way the person asked for it: the store is spent (`more` is false)
   *  BEFORE this can run at all, the ask is one press, and what comes back is read out
   *  of the database like every other page — the panel has already filed it by the time
   *  it answers. An answer of «nothing arrived» closes the room for good, so a thumb
   *  that keeps going up asks nobody a second time. */
  const deeper = useCallback(async () => {
    const el = pane.current
    if (deep || busy || more || !server) return
    setDeep(true)
    held.current = el ? el.scrollHeight : 0
    try {
      const answer = await post<Deep>('/api/screen/press', {
        id: screen,
        action: 'older',
        args: { type, room: room || deepRoom },
      })
      if (!answer || !answer.ok) {
        setServer(false)
        held.current = 0
        if (answer && answer.reason) toast(t(answer.reason))
        return
      }
      if (answer.end) setServer(false)
      if (!answer.got) {
        held.current = 0
        return
      }
      const page = await get<Page>(link(rows.length ? rows[0].ts : undefined))
      const above = page.rows || []
      setMore(!!page.more)
      if (above.length) {
        const seen = new Set(rows.map((r) => r.id))
        setRows((prev) => [...above.filter((r) => !seen.has(r.id)), ...prev])
      } else {
        held.current = 0
      }
    } catch {
      held.current = 0
    } finally {
      setDeep(false)
    }
  }, [deep, busy, more, server, screen, type, room, deepRoom, rows, link, toast])

  /* THE PANE IS EXACTLY THE ROOM THERE IS, measured rather than guessed (#2064).
   *
   * The person's report was «футер налезает на окно чата, и я не вижу окно ввода»: the
   * pane was a share of the viewport (`62vh`), the send box came after it, and on a
   * phone the two together were taller than the screen — so the box sat under the fixed
   * bottom bar. A share of ANY unit is a guess, because what stands above the pane (the
   * account strip, the title, the chip row, and whether the chips wrapped) is not known
   * to the stylesheet. So it is read off the page: what the visible viewport has, less
   * where the pane starts, less the box and the bar under it.
   *
   * `visualViewport` is what shrinks when the keyboard comes up, so the same measure
   * keeps the box off the keyboard as well; it is re-taken on resize, on rotation and
   * when the browser's own furniture rolls away. */
  useLayoutEffect(() => {
    const fit = () => {
      const el = pane.current
      if (!el) return
      const seen = window.visualViewport?.height || window.innerHeight
      const box = el.parentElement?.querySelector('.chatbox') as HTMLElement | null
      const bar = document.querySelector('nav') as HTMLElement | null
      const glue = atBottom()
      const room =
        seen - el.getBoundingClientRect().top - (box?.offsetHeight || 56) - (bar?.offsetHeight || 64) - 16
      el.style.height = Math.max(160, Math.round(room)) + 'px'
      if (glue) el.scrollTop = el.scrollHeight
    }
    fit()
    const vv = window.visualViewport
    window.addEventListener('resize', fit)
    window.addEventListener('orientationchange', fit)
    vv?.addEventListener('resize', fit)
    vv?.addEventListener('scroll', fit)
    return () => {
      window.removeEventListener('resize', fit)
      window.removeEventListener('orientationchange', fit)
      vv?.removeEventListener('resize', fit)
      vv?.removeEventListener('scroll', fit)
    }
     
  }, [type, room, rows.length])

  useLayoutEffect(() => {
    const el = pane.current
    if (!el) return
    if (held.current) {
      /* Older messages went in above: put the reader back on the line they were on. */
      el.scrollTop += el.scrollHeight - held.current
      held.current = 0
      return
    }
    if (glued.current) el.scrollTop = el.scrollHeight
  }, [rows])

  const send = async (action: 'send' | 'coords') => {
    const typed = text.trim()
    if (!typed || busy) return
    setBusy(true)
    try {
      /* THE ROOM ALWAYS TRAVELS (#2418). A private message once went to the WORLD
         chat because the press carried a channel rather than the conversation; the
         panel refuses a send with no room now, and this is the side that names it. */
      const args: Record<string, unknown> = { type, room, text: typed }
      const answer = await post<PressAnswer>('/api/screen/press', {
        id: screen,
        action,
        args,
      })
      toast(pressWord(answer))
      if (answer && answer.ok) {
        setText('')
        glued.current = true
        // The message travels through the game and comes back as an ordinary one.
        window.setTimeout(() => void draw(), 900)
      }
    } finally {
      setBusy(false)
    }
  }

  /* THE EAR, AS A SWITCH (#2064). Nothing is filed while the monitor is stopped, so a
     chat that has quietly stopped growing looks exactly like a quiet one — and the only
     switch used to be the window's tick. Held locally so the chip answers the thumb at
     once; the screen's own poll brings back what the panel really did, which is what
     shows a monitor that refused to start. */
  const [ear, setEar] = useState(listening)
  useEffect(() => setEar(listening), [listening])
  const hear = useCallback(
    async (on: boolean) => {
      setEar(on)
      try {
        const answer = await post<PressAnswer>('/api/screen/press', {
          id: screen,
          action: 'listen',
          args: { on },
        })
        if (answer && !answer.ok) setEar(!on)
      } catch {
        setEar(!on)
      }
    },
    [screen],
  )

  /* THE PICKER IS A MODAL NOW (#2418), and it is THE modal — `ui/Modal.tsx`, the one
     this panel has. It used to be two grids of two hundred sprites laid out under the
     conversation, which is «огромные таблицы под чатом» and also what made the screen a
     many-card one and put a pager over the chat. An emoji goes INTO the message; a
     sticker is sent on the tap, because the game allows no text beside one. */
  const openPicker = async (which: 'emoji' | 'sticker') => {
    setPicker(which)
    if (sprites.emoji.length || sprites.stickers.length) return
    try {
      setSprites(
        await get<Sprites>('/api/screen/data?id=' + encodeURIComponent(screen) + '&kind=picker'),
      )
    } catch {
      /* nothing extracted is an empty picker, which is what the window shows too */
    }
  }

  const sendSticker = async (id: string) => {
    setPicker(null)
    try {
      const answer = await post<PressAnswer>('/api/screen/press', {
        id: screen,
        action: 'sticker',
        args: { type, room, id },
      })
      toast(pressWord(answer))
      if (answer && answer.ok) window.setTimeout(() => void draw(), 900)
    } catch {
      /* the tick says so */
    }
  }

  /* A TAP ON A QUOTE GOES TO WHAT IT QUOTES (#2418). The row may not be on screen —
     a reply to something said yesterday — so the history above is paged in until the
     message turns up, and only when the store (and then the server) is spent does it
     say the message cannot be reached. Bounded on purpose: a quote of something a
     thousand messages back must not turn one tap into a minute of reading. */
  const REACHES = 6

  const goToQuoted = async (id: string) => {
    for (let step = 0; step <= REACHES; step += 1) {
      const found = document.getElementById('msg-' + id)
      if (found) {
        found.scrollIntoView({ block: 'center' })
        setLit(id)
        window.setTimeout(() => setLit(''), 1600)
        return
      }
      if (step === REACHES) break
      if (more) await older()
      else if (server && !deep) await deeper()
      else break
      await new Promise((go) => window.setTimeout(go, 120))
    }
    toast(t('chat.reply.gone'))
  }

  /* THE GAME'S OWN TRANSLATOR (#2418), never an outside service: the client has the
     button and `translate_chat_message` is the recipe that presses it. Asked once per
     message — the answer is held here — and a second tap puts the original back. */
  const translate = async (row: ChatRow) => {
    if (asTr[row.id]) {
      setAsTr((was) => ({ ...was, [row.id]: false }))
      return
    }
    if (tr[row.id]) {
      setAsTr((was) => ({ ...was, [row.id]: true }))
      return
    }
    setTring(row.id)
    try {
      const answer = await post<PressAnswer & { text?: string }>('/api/screen/press', {
        id: screen,
        action: 'translate',
        args: { room: row.room || room, seq: row.seq || '' },
      })
      if (answer && answer.ok && answer.text) {
        setTr((was) => ({ ...was, [row.id]: answer.text as string }))
        setAsTr((was) => ({ ...was, [row.id]: true }))
      } else {
        toast(pressWord(answer))
      }
    } catch {
      toast(t('chat.translate.failed'))
    } finally {
      setTring('')
    }
  }

  const openThread = (contact: Contact) => {
    setRoom(contact.room)
    setRows([])
  }

  const here = rooms.find((r) => (r.room ? r.room === room : !room && r.type === type))

  const chosenRow = (tab: ChatRoomTab) =>
    tab.room ? tab.room === room : !room && tab.type === type

  /* THE LIST IS ON THE LEFT, AND IN THE PERSON'S OWN ORDER (#2418): «сначала общие
     группы, мир, альянс, национальный и т.д., потом кастомные группы, потом лички с
     игроками». The order is the PANEL's — each row says which section it is in — so a
     new kind of room lands in the right place without this file learning about it.

     ON A NARROW SCREEN IT IS A DRAWER. 390 px cannot hold a column of rooms beside a
     conversation without the conversation becoming a gutter, and «слева» is where it
     still comes from: the strip slides in from the left over the page, and the button
     that opens it carries the room being read, so the first screen is the chat.

     SIXTY PRIVATE CONVERSATIONS ARE NOT A FIRST SCREEN either, so the people fold: the
     newest few are shown — they are the ones somebody is talking in, «чаты игроков
     сортируем по последнему сообщению» — and the rest are one press away, with every row
     carrying its own unread count. The sorting is the PANEL's, in every section. */
  const named = (tab: ChatRoomTab) => tab.label || t(tab.key || tabKey(tab.type))

  const line = (tab: ChatRoomTab) => (
    <button
      key={tab.room || tab.type}
      className={'chatrow' + (chosenRow(tab) ? ' on' : '')}
      onClick={() => {
        setType(tab.type)
        setRoom(tab.room || '')
        setText('')
        setOpen(false)
      }}
    >
      <Face label={named(tab)} face={tab.face} />
      <span className="name">{named(tab)}</span>
      {tab.unread ? <span className="count">{tab.unread}</span> : null}
    </button>
  )

  const people = rooms.filter((r) => r.section === 'people')
  const shown = all ? people : people.slice(0, PEOPLE_FOLD)
  const section = (id: string, key: string, list: ChatRoomTab[]) =>
    list.length ? (
      <div className="chatsect" key={id}>
        <div className="muted small head">{t(key)}</div>
        {list.map(line)}
      </div>
    ) : null

  const sidebar = (
    <aside className={'chatlist' + (open ? ' open' : '')}>
      {/* PINNED FIRST — the client's own `isPin`, so what the person pinned in the game
          is what is at the top here (#2418). */}
      {section('pin', 'chat.list.pinned', rooms.filter((r) => r.section === 'pin'))}
      {section('channel', 'chat.list.channels', rooms.filter((r) => r.section === 'channel'))}
      {section('group', 'chat.list.groups', rooms.filter((r) => r.section === 'group'))}
      {section('people', 'chat.list.people', shown)}
      {people.length > PEOPLE_FOLD ? (
        <button className="go wide" onClick={() => setAll(!all)}>
          {all ? t('chat.list.fold') : t('chat.list.more', { n: people.length - PEOPLE_FOLD })}
        </button>
      ) : null}
      {/* …and the ear LAST: the rooms are what a thumb reaches for. */}
      <button className={'chip ear' + (ear ? ' on' : '')} onClick={() => void hear(!ear)}>
        {t('chat.monitor')}
      </button>
    </aside>
  )

  /** The strip over the conversation: what is open, and the way back to the list. */
  const bar = (
    <div className="chatbar">
      <button className="back menu" onClick={() => setOpen(true)}>
        {t('chat.list.open')}
      </button>
      <b>{here ? named(here) : t(tabKey(type))}</b>
    </div>
  )

  /* HOW OLD WHAT IS ON SCREEN IS (#2418). A conversation whose newest message is an hour
     old and one whose ear has been down since Tuesday are drawn identically, and the
     second is the one somebody reports as «чат не обновляется». So the age is said, and
     with it the one thing that explains it: whether anything is listening at all. */
  const state = (
    <p className="muted small chatstate">
      {!ear
        ? t('chat.ear.off')
        : waiting
          ? t('chat.ear.waiting')
          : silent !== null
            ? t('chat.silent', { span: span(silent) })
            : ''}
    </p>
  )

  /* «ЛС» WITH NO THREAD OPEN IS A LIST OF PEOPLE, not a channel. A private message is
     answered to WHOEVER SENT IT — outgoing chat cannot be unsent, so the phone never
     writes into «whatever thread was last looked at». */
  if (type === 'dm' && !room) {
    return (
      <div className="chatwrap">
        {sidebar}
        {open ? <div className="chatscrim" onClick={() => setOpen(false)} /> : null}
        <div className="chat">
          {bar}
          {state}
          <div className="chatpane" ref={pane}>
            {contacts.length ? (
              contacts.map((contact) => (
                <button className="contact" key={contact.room} onClick={() => openThread(contact)}>
                  <span className="who">{contact.who}</span>
                  <span className="muted small last">
                    {contact.mine ? t('chat.you') + ' ' : ''}
                    {contact.text}
                  </span>
                  <span className="muted small stamp">{contact.when}</span>
                  {contact.unread ? <span className="count">{contact.unread}</span> : null}
                </button>
              ))
            ) : (
              <p className="muted small">{t('chat.contacts.empty')}</p>
            )}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="chatwrap">
      {sidebar}
      {open ? <div className="chatscrim" onClick={() => setOpen(false)} /> : null}
      <div className="chat">
        {bar}
        {state}
        <div
          className="chatpane"
          ref={pane}
          onScroll={() => {
            const el = pane.current
            if (!el) return
            glued.current = atBottom()
            if (glued.current && unseen) setUnseen(0)
            if (el.scrollTop >= REACH) return
            // THE STORE FIRST, ALWAYS. Only a scroll that finds it spent reaches the
            // game, which is the person's own rule: «если у нас нет сообщений».
            if (more && !busy) void older()
            else if (!more && server && !deep && !busy) void deeper()
          }}
        >
          {more ? (
            <button className="go wide" disabled={busy} onClick={() => void older()}>
              {t('chat.load_more')}
            </button>
          ) : server ? (
            <button className="go wide" disabled={deep} onClick={() => void deeper()}>
              {deep ? t('chat.deep_busy') : t('chat.older_from_game')}
            </button>
          ) : rows.length ? (
            <div className="chatday">{t('chat.history_end')}</div>
          ) : null}
          {rows.length ? (
            rows.map((row, i) => (
              <div key={row.id + i}>
                {row.day && !sameDay(row, rows[i - 1]) ? (
                  <div className="chatday">{t(row.day)}</div>
                ) : null}
                <div
                  id={'msg-' + row.id}
                  className={
                    'bubble' + (row.mine ? ' mine' : '') + (lit === row.id ? ' lit' : '')
                  }
                >
                  {row.reply ? (
                    <button className="quote" onClick={() => void goToQuoted(row.reply!.id)}>
                      <span className="who">{row.reply.who || t('chat.reply.someone')}</span>
                      <span className="said">{row.reply.text || t('chat.reply.gone')}</span>
                    </button>
                  ) : null}
                  {!row.mine ? (
                    <div className="who">
                      <Face label={row.who} face={row.face} />
                      {row.who}
                      {row.alliance ? <span className="muted small"> [{row.alliance}]</span> : null}
                    </div>
                  ) : null}
                  <div className="said">
                    {asTr[row.id] && tr[row.id] ? (
                      <span className="tr">{tr[row.id]}</span>
                    ) : (
                      (row.parts || []).map((part, k) =>
                        part.t === 'img' ? (
                          <img className="chat-sprite" key={k} src={part.v} alt="" />
                        ) : (
                          <span key={k}>
                            <Marked text={part.v} parts={part.parts} />
                          </span>
                        ),
                      )
                    )}
                  </div>
                  {/* THE TRANSLATION IS A SECOND READING, never a replacement: the tap
                      that shows it is the tap that puts the original back (#2418). Not
                      offered on one's own message — the game does not offer it either. */}
                  {!row.mine && row.tr && (row.seq || '') ? (
                    <button
                      className="trbtn"
                      disabled={tring === row.id}
                      onClick={() => void translate(row)}
                    >
                      {tring === row.id
                        ? t('chat.translate.doing')
                        : asTr[row.id]
                          ? t('chat.translate.back')
                          : t('chat.translate')}
                    </button>
                  ) : null}
                  {row.photo ? (
                    <button className="shot" onClick={() => setPhoto(row.photo?.big || row.photo?.small || '')}>
                      <img src={row.photo.small} alt={t('chat.photo')} />
                    </button>
                  ) : null}
                  <div className="stamp muted small">{row.when}</div>
                </div>
              </div>
            ))
          ) : (
            <p className="muted small">{t('chat.empty')}</p>
          )}
        </div>
        {/* WHAT ARRIVED WHILE YOU WERE READING HISTORY. It sits between the pane and
            the box, says how many, and takes you to them — the view is never dragged
            down under a thumb that did not ask to go there. */}
        {unseen ? (
          <button
            className="go wide"
            onClick={() => {
              const el = pane.current
              if (el) el.scrollTop = el.scrollHeight
              glued.current = true
              setUnseen(0)
            }}
          >
            {t('chat.new_below', { n: unseen })}
          </button>
        ) : null}
        {/* THE BOX IS AT THE BOTTOM, which is the half of «как в телеграм» a person
            feels first. Two sends and one box: words, and the coordinate in them. */}
        {/* THE BOX IS AT THE BOTTOM, and on a 390 px phone it is ONE ROW (#2418). The
            person's report: «поле для сообщения маленькое, кнопки смайлов занимают
            половину строки, кнопка отправить не влезает». So the field takes every
            pixel the icons leave and GROWS DOWNWARDS as the message does (a textarea
            capped at five lines, never a scrollbar in a one-line box), the three
            pickers are square icons of one tap each, and «Отправить» is an icon with
            its word as the label a screen-reader and a long press get. Nothing here
            carries text that a locale can widen, so no translation can push the send
            off the screen. */}
        <div className="chatbox">
          <textarea
            className="grow"
            ref={box}
            rows={1}
            value={text}
            placeholder={t('chat.send.prompt')}
            /* THE KEYBOARD MUST NOT SWALLOW THE BOX. The page says
               `interactive-widget=resizes-content`, which the newer phones honour by
               shrinking the page instead of sliding it — but a browser that only
               shrinks the VISUAL viewport leaves the box where it was, under the
               keyboard. Asking for it after the keyboard has finished coming up costs
               nothing and covers both. */
            onFocus={(e) => {
              const el = e.currentTarget
              window.setTimeout(() => el.scrollIntoView({ block: 'center' }), 350)
            }}
            onChange={(e) => {
              setText(e.target.value)
              grew(e.currentTarget)
            }}
            onKeyDown={(e) => {
              // Enter sends, Shift+Enter is a new line — the gesture every chat has.
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send('send')
              }
            }}
          />
          <button
            className="go icon"
            disabled={busy}
            title={t('chat.emoji')}
            aria-label={t('chat.emoji')}
            onClick={() => void openPicker('emoji')}
          >
            {'🙂'}
          </button>
          <button
            className="go icon"
            disabled={busy}
            title={t('chat.stickers')}
            aria-label={t('chat.stickers')}
            onClick={() => void openPicker('sticker')}
          >
            {'🏷'}
          </button>
          <button
            className="go icon"
            disabled={busy}
            title={t('chat.send_coords')}
            aria-label={t('chat.send_coords')}
            onClick={() => void send('coords')}
          >
            {'📍'}
          </button>
          <button
            className="go icon send"
            disabled={busy}
            title={t('chat.send')}
            aria-label={t('chat.send')}
            onClick={() => void send('send')}
          >
            {'➤'}
          </button>
        </div>
      </div>
      {picker ? (
        <Modal
          title={t(picker === 'emoji' ? 'chat.picker.emoji' : 'chat.picker.sticker')}
          onClose={() => setPicker(null)}
        >
          <div className="sprites">
            {(picker === 'emoji' ? sprites.emoji : sprites.stickers).map((one) => (
              <button
                key={one.id}
                className="sprite"
                onClick={() => {
                  if (picker === 'emoji') {
                    setText(text + ('token' in one ? one.token : ''))
                    setPicker(null)
                  } else {
                    void sendSticker(one.id)
                  }
                }}
              >
                <img src={one.icon} alt="" />
              </button>
            ))}
            {!(picker === 'emoji' ? sprites.emoji : sprites.stickers).length ? (
              <p className="muted small">{t('chat.picker.empty')}</p>
            ) : null}
          </div>
        </Modal>
      ) : null}
      {photo ? (
        <Modal title={t('chat.photo')} onClose={() => setPhoto(null)}>
          <img className="shot-big" src={photo} alt="" />
        </Modal>
      ) : null}
    </div>
  )
}
