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
 * SCROLLING UP READS THE DATABASE AND NEVER THE GAME. Every page comes off
 * `/api/screen/data?kind=page`, which is this profile's own SQLite history answered on
 * an HTTP worker thread (`panel/tabs/chat.py::web_data`). No round trip, so a thumb
 * flicking upwards cannot turn a gesture into a poll — the panel's «read once, then
 * LISTEN» rule holds by construction. Going deeper than the store would mean asking the
 * SERVER for history, which is not done: the top of the list simply stops offering more.
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
import { t } from '../i18n'
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
}

interface Page {
  rows: ChatRow[]
  more: boolean
  room: string
  type: string
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

/** How close to the bottom still counts as «reading the newest», in pixels. */
const GLUE = 48

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
  pollKey,
}: {
  screen: string
  rooms: ChatRoomTab[]
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
  const [contacts, setContacts] = useState<Contact[]>([])
  const [text, setText] = useState('')
  const [photo, setPhoto] = useState<string | null>(null)
  const pane = useRef<HTMLDivElement | null>(null)
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
    } catch {
      /* the tick says so */
    }
  }, [link])

  useEffect(() => {
    setRows([])
    setMore(false)
    void draw()
  }, [draw])

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
      const args: Record<string, unknown> = { type, text: typed }
      if (room) args.room = room
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

  const openThread = (contact: Contact) => {
    setRoom(contact.room)
    setRows([])
  }

  const chips = (
    <div className="chips">
      {rooms.map((tab) => (
        <button
          key={tab.type}
          className={'chip' + (tab.type === type ? ' on' : '')}
          onClick={() => {
            setType(tab.type)
            setRoom('')
            setText('')
          }}
        >
          {t(tabKey(tab.type))}
          {tab.unread ? <span className="count">{tab.unread}</span> : null}
        </button>
      ))}
    </div>
  )

  /* «ЛС» WITH NO THREAD OPEN IS A LIST OF PEOPLE, not a channel. A private message is
     answered to WHOEVER SENT IT — outgoing chat cannot be unsent, so the phone never
     writes into «whatever thread was last looked at». */
  if (type === 'dm' && !room) {
    return (
      <>
        {chips}
        <div className="chat">
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
      </>
    )
  }

  return (
    <>
      {chips}
      <div className="chat">
        {room ? (
          <button className="back thread" onClick={() => setRoom('')}>
            {t('chat.dm.pick')}
          </button>
        ) : null}
        <div
          className="chatpane"
          ref={pane}
          onScroll={() => {
            const el = pane.current
            if (!el) return
            glued.current = atBottom()
            if (el.scrollTop < REACH && more && !busy) void older()
          }}
        >
          {more ? (
            <button className="go wide" disabled={busy} onClick={() => void older()}>
              {t('chat.load_more')}
            </button>
          ) : null}
          {rows.length ? (
            rows.map((row, i) => (
              <div key={row.id + i}>
                {row.day && !sameDay(row, rows[i - 1]) ? (
                  <div className="chatday">{t(row.day)}</div>
                ) : null}
                <div className={'bubble' + (row.mine ? ' mine' : '')}>
                  {!row.mine ? (
                    <div className="who">
                      {row.who}
                      {row.alliance ? <span className="muted small"> [{row.alliance}]</span> : null}
                    </div>
                  ) : null}
                  <div className="said">
                    {(row.parts || []).map((part, k) =>
                      part.t === 'img' ? (
                        <img className="chat-sprite" key={k} src={part.v} alt="" />
                      ) : (
                        <span key={k}>
                          <Marked text={part.v} parts={part.parts} />
                        </span>
                      ),
                    )}
                  </div>
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
        {/* THE BOX IS AT THE BOTTOM, which is the half of «как в телеграм» a person
            feels first. Two sends and one box: words, and the coordinate in them. */}
        <div className="chatbox">
          <input
            type="text"
            value={text}
            placeholder={t('chat.send.prompt')}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void send('send')
            }}
          />
          <button className="go icon" disabled={busy} title={t('chat.send_coords')} onClick={() => void send('coords')}>
            {'📍'}
          </button>
          <button className="go" disabled={busy} onClick={() => void send('send')}>
            {t('chat.send')}
          </button>
        </div>
      </div>
      {photo ? (
        <Modal title={t('chat.photo')} onClose={() => setPhoto(null)}>
          <img className="shot-big" src={photo} alt="" />
        </Modal>
      ) : null}
    </>
  )
}
