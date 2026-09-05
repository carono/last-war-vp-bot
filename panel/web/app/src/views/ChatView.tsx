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
import type { ChatRoomTab, CoordPart, PressAnswer, ViewAction } from '../types'

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
  /** The game's translation of this message, when auto-translation is on and the game
   *  has already answered for it. Empty otherwise — the original is never replaced. */
  trtext?: string
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

/** The breathing room under the send box — the ONLY empty pixels the page keeps. */
const GAP_PX = 6

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

/** How long a silence puts a clock between two messages, in seconds.
 *
 *  THE TIME IS A SEPARATOR, NOT A LINE ON EVERY MESSAGE (#2418). A stamp under each
 *  bubble cost a whole row — 16 px of a 95 px message — to say the same minute five
 *  times over. The game's own chat prints the clock once when the talk has paused and
 *  nothing in between; the exact moment of a single message is still there, on the
 *  bubble's `title`.
 */
const CLOCK_GAP = 300

/** Is this message a continuation of the one above — same sender, no long pause?
 *
 *  A run of messages from one person repeats that person's face and name once, not on
 *  every line. That is the other half of the density: the meta row is 20 px and a
 *  five-message run paid it five times.
 */
function joined(a: ChatRow, b: ChatRow | undefined): boolean {
  return (
    !!b && sameDay(a, b) && !!a.uid && a.uid === b.uid && !!a.mine === !!b.mine &&
    a.ts - b.ts < CLOCK_GAP
  )
}

export function ChatView({
  screen,
  rooms,
  listening,
  silent,
  waiting,
  pollKey,
  onBack,
  tools,
}: {
  screen: string
  rooms: ChatRoomTab[]
  listening: boolean
  /** Seconds since the newest message the panel has filed, or null for none at all. */
  silent: number | null
  /** The monitor is on but its reader is down and being brought back. */
  waiting: boolean
  pollKey: number
  /** The way out of the screen: the chat's own bar carries it, so there is one row. */
  onBack: () => void
  /** The screen's own presses — «Загрузить историю», «Обновить комнаты» — behind ⚙. */
  tools: ViewAction[]
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
  /* WHAT ARRIVED ALREADY TRANSLATED (#2418). With auto-translation on, the panel has
     asked the game before the phone ever saw the message, and the answer rides the row.
     It is SHOWN by default in that case — that is what the switch is for — and the same
     tap that has always put the original back still does. A row a reader has already
     toggled by hand is left exactly as they left it. */
  useEffect(() => {
    const held: Record<string, string> = {}
    for (const row of rows) if (row.trtext) held[row.id] = row.trtext
    if (!Object.keys(held).length) return
    setTr((prev) => ({ ...held, ...prev }))
    setAsTr((prev) => {
      const next = { ...prev }
      let moved = false
      for (const id of Object.keys(held)) {
        if (!(id in next)) {
          next[id] = true
          moved = true
        }
      }
      return moved ? next : prev
    })
  }, [rows])
  const [tring, setTring] = useState('')
  /* THE SERVICE PRESSES ARE BEHIND ⚙ (#2418): «кнопки загрузить историю и обновить
     убирай, можно добавить кнопку шестеренки сверху с выпадайкой». They are things a
     person does once in a while — folding what the client holds into the store, asking
     the client for its room list — and they stood permanently under the conversation.
     Reading older messages does NOT depend on them: a scroll to the top pages the store
     and then asks the server by itself (`older` / `deeper`). */
  const [toolsOpen, setToolsOpen] = useState(false)
  const [doing, setDoing] = useState('')
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

  /* NO BOTTOM BAR OVER A CONVERSATION (#2418): «на странице чатов убери футер с
     кнопками». It is the panel's own navigation — «Состояние», «Таймеры», «Ещё» — and
     nothing in it is reachable only from there: the bar above carries «Назад», which
     goes back to the page the three of them are on. What it costs is 65 px of a 844 px
     phone, directly under the box a thumb is typing in. Marked on the BODY rather than
     passed up as a prop, so it is undone by leaving the screen however one leaves it. */
  useEffect(() => {
    document.body.classList.add('chatting')
    return () => document.body.classList.remove('chatting')
  }, [])

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
      /* A BAR THAT IS NOT DRAWN RESERVES NOTHING (#2418). The person: «в чате, на
       * мобильных устройствах есть пустое место в футере, растяни окно чата». The
       * bottom bar is hidden while a conversation is open (`body.chatting nav`), so its
       * `offsetHeight` is 0 — and `0 || 64` is 64, which is how 64 px of the phone were
       * kept for furniture nobody draws. Measured, never guessed: an element that is
       * there is worth its own height and one that is not is worth nothing. The two
       * fallbacks are gone with it — a box that has not been laid out yet is measured on
       * the next pass, and inventing 56 px for it is the same mistake one line up. */
      const barH = bar && bar.offsetParent !== null ? bar.offsetHeight : 0
      /* …and the page's own clearance under the box counts too: `main` keeps 14 px for
       * the screens that end in a card, and a conversation that ignored them was 12 px
       * taller than the phone — the page itself scrolled, which is the one thing a chat
       * must never do. Read, not written down: the stylesheet may change it. */
      const main = el.closest('main') as HTMLElement | null
      const padB = main ? parseFloat(getComputedStyle(main).paddingBottom) || 0 : 0
      const room =
        seen - el.getBoundingClientRect().top - (box?.offsetHeight || 0) - barH - padB - GAP_PX
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
      {/* ONE ROW AT THE TOP (#2418), the person's words: «вверху кнопки назад и чаты в
          одну строку сделай». The way out of the screen used to be a row of its own
          above this one — two bars, 88 px of a phone, over a conversation. The screen's
          own head is not drawn for this kind at all (`ScreenView`), so this is where
          «Назад» lives now: leave, open the rooms, and read which room is open. */}
      <button className="back" onClick={onBack}>
        {t('web.ui.back')}
      </button>
      <button className="back menu" onClick={() => setOpen(true)}>
        {t('chat.list.open')}
      </button>
      <b className="room">{here ? named(here) : t(tabKey(type))}</b>
      {tools.length ? (
        <button
          className="go icon gear"
          title={t('chat.tools')}
          aria-label={t('chat.tools')}
          onClick={() => setToolsOpen(true)}
        >
          {'⚙'}
        </button>
      ) : null}
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
            rows.map((row, i) => {
              /* ONE MESSAGE IS ONE ROW, NOT FOUR (#2418): «хочу такой же лаконичный
                 интерфейс чата, сейчас много лишнего пространства съедается». The
                 bubble used to carry a face-and-name row, the words, a full-width
                 «Перевести» button and a stamp — four stacked lines for one sentence,
                 measured at 95 px on a 390x844 phone with five messages on screen. The
                 face steps OUT of the bubble and stands beside it, a run from one
                 person says who they are once, the clock is a separator rather than a
                 line on every message, and the translation is the icon the game uses. */
              const run = joined(row, rows[i - 1])
              const newDay = row.day && !sameDay(row, rows[i - 1])
              const gap = !newDay && i > 0 && row.ts - rows[i - 1].ts >= CLOCK_GAP
              return (
              <div key={row.id + i}>
                {newDay ? <div className="chatday">{t(row.day)}</div> : null}
                {gap ? <div className="chatday">{row.when}</div> : null}
                <div className={'msg' + (row.mine ? ' mine' : '') + (run ? ' run' : '')}>
                  {!row.mine && !run ? <Face label={row.who} face={row.face} /> : null}
                  <div className="col">
                    {!row.mine && !run ? (
                      <div className="who">
                        {row.who}
                        {row.alliance ? <span className="muted small"> [{row.alliance}]</span> : null}
                      </div>
                    ) : null}
                    <div className="line">
                    <div
                      id={'msg-' + row.id}
                      title={row.when}
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
                      {row.photo ? (
                        <button className="shot" onClick={() => setPhoto(row.photo?.big || row.photo?.small || '')}>
                          <img src={row.photo.small} alt={t('chat.photo')} />
                        </button>
                      ) : null}
                    </div>
                    {/* THE TIME IS ON EVERY MESSAGE, and it costs no line (#2418).
                        The person: «в чате время сообщения добавь». It had come off
                        with the tightening — a grey separator on a pause and the exact
                        minute in the bubble's tooltip, neither of which a thumb reads.
                        So it stands BESIDE the bubble, on the same row, the way the
                        translate glyph does: a bubble is at least 34 px tall and this
                        is 13, so a message with a clock is exactly as tall as one
                        without. The separator stays — it says a pause happened, which
                        a stamp on every line does not. */}
                    <span className="stamp">{row.when}</span>
                    {/* THE TRANSLATION IS A SECOND READING, never a replacement: the
                        tap that shows it is the tap that puts the original back. Not
                        offered on one's own message — the game does not offer it
                        either. It stands BESIDE the bubble, where the game puts its own
                        corner mark: the word «Перевести» used to be a full line under
                        every foreign message, and inside the bubble the glyph cut the
                        first line in half and broke words across it. */}
                    {!row.mine && row.tr && (row.seq || '') ? (
                      <button
                        className="trbtn"
                        disabled={tring === row.id}
                        title={asTr[row.id] ? t('chat.translate.back') : t('chat.translate')}
                        aria-label={asTr[row.id] ? t('chat.translate.back') : t('chat.translate')}
                        onClick={() => void translate(row)}
                      >
                        {tring === row.id ? '…' : asTr[row.id] ? '↩' : '⇄A'}
                      </button>
                    ) : null}
                    </div>
                  </div>
                </div>
              </div>
              )
            })
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
        {/* THE PICKERS ARE NO LONGER A ROW OF THEIR OWN (#2418): «кнопки смайлов
            сделай так же, как на скрине, одна кнопка прямо в поле сообщения, при клике
            модальное окно с табами выбором смайлов или стикеров». Three square buttons
            on a line above the box cost 65 px of a 844 px phone to offer what one button
            in the field offers. «Поделиться координатами» went with them, into the ⚙
            beside «Загрузить историю» — it is not a sprite to pick but a thing done to
            what is typed, which is exactly what that menu holds.
            The modal is THE modal (`ui/Modal.tsx`) with the two sets behind tabs, never
            a second sheet: `CLAUDE.md`, «The knobs open in ONE modal». */}
        <div className="chatbox">
          <button
            className="go icon sprites-open"
            disabled={busy}
            title={t('chat.picker.open')}
            aria-label={t('chat.picker.open')}
            onClick={() => void openPicker('emoji')}
          >
            {'🙂'}
          </button>
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
        <Modal title={t('chat.picker.open')} onClose={() => setPicker(null)}>
          {/* TABS, INSIDE THE ONE MODAL. The same chip strip every other list on this
              panel is cut with, so a thumb learns the gesture once. */}
          <div className="chips">
            <button
              className={'chip' + (picker === 'emoji' ? ' on' : '')}
              onClick={() => setPicker('emoji')}
            >
              {t('chat.emoji')}
            </button>
            <button
              className={'chip' + (picker === 'sticker' ? ' on' : '')}
              onClick={() => setPicker('sticker')}
            >
              {t('chat.stickers')}
            </button>
          </div>
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
      {toolsOpen ? (
        <Modal title={t('chat.tools')} onClose={() => setToolsOpen(false)}>
          <div className="menu">
            {/* «ПОДЕЛИТЬСЯ КООРДИНАТАМИ» LIVES HERE NOW (#2418), and it is drawn by the
                view rather than sent by the panel with the others on purpose: the press
                has to name the room being read, and only this side knows which that is.
                That rule cost a private message posted to the world once already. */}
            <button
              className="go wide"
              disabled={busy || !room}
              onClick={() => {
                setToolsOpen(false)
                void send('coords')
              }}
            >
              {t('chat.send_coords')}
            </button>
            {tools.map((action) => (
              <button
                key={action.id}
                className="go wide"
                disabled={doing === action.id}
                onClick={() => {
                  setDoing(action.id)
                  void (async () => {
                    try {
                      const answer = await post<PressAnswer>('/api/screen/press', {
                        id: screen,
                        action: action.id,
                        args: action.args || {},
                      })
                      toast(pressWord(answer))
                      if (answer && answer.ok) window.setTimeout(() => void draw(), 900)
                    } catch {
                      /* the tick says so */
                    } finally {
                      setDoing('')
                      setToolsOpen(false)
                    }
                  })()
                }}
              >
                {t(action.label)}
              </button>
            ))}
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
