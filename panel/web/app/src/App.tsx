import { useCallback, useEffect, useRef, useState } from 'react'
import { get, ping, post, setProfile, Unauthorised } from './api'
import { useRoute, type Route, type ViewName } from './route'
import { loadWords, span, t, type Words } from './i18n'
import { Modal } from './ui/Modal'
import { ToastHost, useToast } from './ui/Toast'
import { applyTheme, isTheme, type Theme } from './ui/theme'
import { ActionsView } from './views/ActionsView'
import { LoginView } from './views/LoginView'
import { LogView } from './views/LogView'
import { MoreView } from './views/MoreView'
import { ScreenPage } from './views/ScreenView'
import { StateView } from './views/StateView'
import { TimersView } from './views/TimersView'
import type {
  Account,
  ActionRow,
  Header,
  LogLine,
  Profiles,
  OrderRow,
  Screen,
  State,
  TimerRow,
  TriggerRow,
} from './types'

const POLL_MS = 2500 //  how often a visible page asks for state and log
const SLOW_MS = 15000 // …and when it is in a pocket, hidden
const LOG_KEEP = 400 //  lines held for a phone that has been open all evening

/* THERE IS NO «СЦЕНАРИИ» ENTRY AND NO «ЛОГ» ENTRY, and that is the point — the person's
 * decision, in their words: «вкладки сценарии быть не должно, в панели она была в
 * разделе с разработкой, так же перенеси», and then, for the log, «журнал и сценарии
 * перенесём внутрь разработки». The window has never had either as a tab of its own:
 * both are pages INSIDE «Разработка» (`panel/tabs/develop.py`, `PAGES` = log / busy /
 * scenarios / sniff), and the phone now groups them the same way — under the develop
 * screen, whole. */
const NAV: { id: ViewName; key: string }[] = [
  { id: 'state', key: 'web.ui.nav.state' },
  { id: 'timers', key: 'web.ui.nav.timers' },
  { id: 'more', key: 'web.ui.nav.more' },
]

/* Which screen the scenarios live under — the window's own tab id, so a rename there is
 * a rename here rather than a list that quietly stops matching. */
const DEVELOP_SCREEN = 'develop'

/* THE ACCOUNT, DRAWN AS ITSELF (#2061) — the person's words: «слева выводим иконку
 * нашего аккаунта, внутри нее указываем уровень, под ней ник аккаунта. Клик по картинке
 * должен давать модалку, со списком всех доступных аккаунтов с их аватарами, уровнями и
 * никами».
 *
 * IT REPLACES THE CHIPS, and that is the point rather than a side effect. The chips were
 * themselves a replacement — for a `<select>` the same person asked to remove, «оставь
 * только пилюли с профилями» (#2025) — and keeping both would put two ways of switching
 * accounts on one screen, which is the thing that removal was about. What the chips
 * carried and a dropdown could not is carried here instead: each row in the sheet wears
 * that account's own light and says, in words, why it is that colour.
 *
 * THE FACE IS THE GAME'S OWN. It is the picture the player uploaded, found in the
 * client's own cache and served by the route every other face on this panel already uses
 * (`panel/runtime/player_card.py`). A character who never uploaded one has no picture at
 * all — the client's own object carries no head-icon id — so the tile draws the account's
 * initial rather than somebody else's art.
 */
function AccountFace({ account, size }: { account: Account; size?: 'big' }) {
  const level = account.level || 0
  const initial = (account.nick || account.name || '?').trim().slice(0, 1).toUpperCase()
  return (
    <span className={'face-badge' + (size === 'big' ? ' big' : '')}>
      {account.avatar ? (
        <img className="face-img" src={account.avatar} alt="" />
      ) : (
        <span className="face-img face-blank">{initial}</span>
      )}
      {/* THE LEVEL IS INSIDE THE PICTURE, which is where the game itself draws it. */}
      {level > 0 ? <b className="face-level">{level}</b> : null}
    </span>
  )
}

/* The sheet the face opens: every account this panel HAS — the open ones with their own
 * light, the closed ones out of what was written down while they were open. Tapping an
 * open one looks at it; tapping a closed one opens it, which is a press the phone already
 * had on the «Профиль» screen and is played through the same route. */
function AccountSheet({
  accounts,
  profile,
  onPick,
  onOpen,
  onClose,
}: {
  accounts: Account[]
  profile: string
  onPick: (name: string) => void
  onOpen: (name: string) => void
  onClose: () => void
}) {
  const toast = useToast()
  return (
    <Modal title={t('web.ui.accounts')} onClose={onClose}>
      <div className="accounts">
        {accounts.map((account) => (
          <button
            key={account.name}
            className={'account' + (account.name === profile ? ' on' : '') +
                       (account.open ? '' : ' shut')}
            onClick={() => {
              if (!account.open) {
                onOpen(account.name)
                return
              }
              // The light's own sentence, said on the way — the chips' one gift, kept.
              if (account.tip?.length || account.text) {
                toast((account.tip || [account.text || '']).join(' · '))
              }
              onPick(account.name)
            }}
          >
            <AccountFace account={account} size="big" />
            <span className="account-who">
              <b className="account-nick">{account.nick || account.name}</b>
              <span className="muted small">
                {account.nick ? account.name + ' · ' : ''}
                {account.open
                  ? t(account.level ? 'web.ui.accounts.level' : 'web.ui.head.nothing',
                      { n: account.level })
                  : t(account.nick ? 'web.ui.accounts.closed' : 'web.ui.accounts.unread')}
              </span>
            </span>
            {account.open ? <span className={'dot ' + (account.colour || 'warn')} /> : null}
          </button>
        ))}
      </div>
    </Modal>
  )
}

/* WHO IS PLAYING AND WHERE THEY ARE STANDING — the strip under the account's name, on
 * every screen (#2016). Every value is the GAME's own answer, read once per profile and
 * paced in the panel (`panel/runtime/header.py`); nothing here works anything out.
 *
 * IT IS ONE READING WITH ITS AGE ON IT, and the age is not decoration. The panel reads
 * the game once and then waits to be told it changed (`CLAUDE.md` — «Читаем один раз,
 * дальше слушаем»), and there is no in-client signal for «the player changed screen»
 * yet, so this line can be an hour old. Saying so is what makes it honest: a strip that
 * showed «База» with no age would be asserting something nobody has checked since.
 *
 * The window's id is shown raw — `UILWAlMain` — and that is deliberate: it is the name
 * the game itself gives that screen, so it is DATA rather than a word of the panel's,
 * exactly like a player's nickname or a resource's name. Translating it would mean the
 * panel keeping a table of two thousand window ids and being wrong about the ones a new
 * season adds.
 *
 * IT GIVES HEIGHT BACK ON ONE ACCOUNT, which is the ordinary case and the one the pixels
 * of #1976 were fought for: the strip absorbs the profile's name, so the picker's whole
 * row goes and the header measures 37 px on an iPhone 13 mini against the 43 px it took
 * before this existed. With several accounts open the picker keeps its row — it is a tap
 * target and may not shrink — and the strip costs 16 px under it. */

/* The scenes the game names, each with its own key — spelled out rather than built as
 * `'web.ui.where.' + scene`, because a key nobody can grep for is a key that quietly
 * stops being translated (`tests/test_panel_web.py` checks exactly this). */
const WHERE: Record<string, string> = {
  city: 'web.ui.where.city',
  world: 'web.ui.where.world',
  pve: 'web.ui.where.pve',
}

function StatusStrip({ header }: { header?: Header }) {
  const known = (header?.age ?? -1) >= 0
  const scene = header?.scene || ''
  const win = header?.window || ''
  const depth = header?.depth || 0
  const server = header?.server || 0
  const home = header?.home || 0
  /* NOTHING HAS BEEN READ, so the strip SAYS so in words rather than drawing empty
   * fields: a panel that had just started once announced «событие закрыто · 0 краж»
   * without having asked the game anything at all. */
  /* THE NAME AND THE LEVEL ARE NOT HERE ANY MORE (#2061). They are drawn to the LEFT of
   * this strip — the level inside the account's own face, the name under it — because the
   * person asked for that shape, and saying either twice on one line is the duplication
   * this header has already been cleaned of twice. What is left is WHERE the player is
   * standing, which is what the strip was always for. */
  if (!known) {
    return (
      <div className="status">
        <span className="where cold">{t('web.ui.head.nothing')}</span>
      </div>
    )
  }
  return (
    <div className="status">
      {server > 0 ? (
        <span className={'fact' + (home > 0 && home !== server ? ' away' : '')}>
          {t('web.ui.head.server', { n: server })}
        </span>
      ) : null}
      <span className="where">{t(WHERE[scene] || 'web.ui.where.unknown')}</span>
      {win ? <span className="win">{win}</span> : null}
      {depth > 1 ? <span className="fact">{t('web.ui.head.stacked', { n: depth - 1 })}</span> : null}
      {/* WHEN it was read. Silent for the first minute — a reading that fresh is simply
          «now» — and from then on the line carries its own age, because nothing re-takes
          it until something says the player moved. */}
      {(header?.age ?? 0) >= 60 ? (
        <span className="fact age">{t('web.ui.ago', { span: span(header?.age || 0) })}</span>
      ) : null}
    </div>
  )
}

function Panel() {
  /* WHERE WE ARE IS THE ADDRESS BAR (#2050) — the account, the tab, the open screen and
   * which of its cards, so a reload comes back to the same place rather than to the
   * first screen of whichever account the window is showing. `panel/web/app/src/route.ts`
   * says what is in it and what deliberately is not. */
  const [route, go] = useRoute()
  const { view, screen, profile } = route
  const [profiles, setProfiles] = useState<Profiles>({ profiles: [] })
  const [state, setState] = useState<State | null>(null)
  const [timers, setTimers] = useState<TimerRow[]>([])
  const [triggers, setTriggers] = useState<TriggerRow[]>([])
  /* The watchers that are in no catalogue, drawn among the listeners (#2017). */
  const [orders, setOrders] = useState<OrderRow[]>([])
  const [actions, setActions] = useState<ActionRow[]>([])
  const [screens, setScreens] = useState<Screen[]>([])
  const [lines, setLines] = useState<LogLine[]>([])
  const [offline, setOffline] = useState(false)
  /* THE ACCOUNT A LINK NAMED AND THIS PANEL HAS NOT GOT (#2050). A link is sent to
   * oneself and opened a week later, by which time that profile may have been closed at
   * the machine — or the link may have come from another computer altogether. Falling
   * back silently would show one account's numbers under the expectation of another's,
   * which is the one mistake a multi-account panel must never make, so the page SAYS
   * whose link it was and which account it is showing instead. The web front-end cannot
   * open a profile — that is the window's own doing (`Workspace`), and it is deliberately
   * not a press the phone has. */
  const [stray, setStray] = useState('')
  const [notify, setNotify] = useState(false)
  /* Whether the account sheet is up. The face in the header is the only way in (#2061). */
  const [picking, setPicking] = useState(false)
  /* DAY OR NIGHT (#2061). The PANEL's setting and not the browser's — «Цветовая тема,
     это настройка панели, не аккаунта» — so it arrives on `/api/profiles`, which is the
     one answer on this front-end that is about the machine rather than about an account.
     Held here only to draw it. */
  const [theme, setTheme] = useState<Theme>('system')
  const [tickCount, setTickCount] = useState(0)
  const logAt = useRef(0)
  const notifyRef = useRef(false)
  const viewRef = useRef<ViewName>('state')
  viewRef.current = view
  /* The poll runs on its own clock and may finish after the person has moved, so it
   * reads the route through a ref rather than through the closure it was made in. */
  const routeRef = useRef<Route>(route)
  routeRef.current = route

  /* A line that says something went wrong reaches the person with the page in a pocket —
   * that is the whole point of a remote control. Nothing is pushed from the server: the
   * browser's own notification, raised by the poll that found the line. */
  const announce = useCallback((text: string) => {
    if (!notifyRef.current || Notification.permission !== 'granted') return
    try {
      new Notification(t('web.ui.title'), { body: text, tag: 'lwvp' })
    } catch {
      /* a browser that refuses is not a reason to stop polling */
    }
  }, [])

  const refreshTimers = useCallback(async () => {
    try {
      const answer = await get<{ timers?: TimerRow[]; triggers?: TriggerRow[] }>('/api/timers')
      setTimers(answer.timers || [])
    } catch {
      /* the tick says so */
    }
    try {
      const answer = await get<{ triggers?: TriggerRow[]; orders?: OrderRow[] }>('/api/triggers')
      setTriggers(answer.triggers || [])
      setOrders(answer.orders || [])
    } catch {
      /* the tick says so */
    }
  }, [])

  const refreshActions = useCallback(async () => {
    try {
      setActions((await get<{ actions?: ActionRow[] }>('/api/actions')).actions || [])
    } catch {
      /* the tick says so */
    }
  }, [])

  const refreshScreens = useCallback(async () => {
    try {
      setScreens((await get<{ screens?: Screen[] }>('/api/screens')).screens || [])
    } catch {
      /* the tick says so */
    }
  }, [])

  const tick = useCallback(async () => {
    try {
      // The account named in the address goes on the request itself, before the first
      // one is made: a reload asks about the profile it came back to, not about the
      // session's own.
      setProfile(profile)
      const who = await get<Profiles>('/api/profiles')
      setProfiles(who)
      // The palette follows the panel, not the tab that is open: a poll is what carries
      // a change made on the machine (or on another phone) to this one.
      if (isTheme(who.theme)) setTheme(who.theme)
      const names = who.profiles || []
      if (!profile || !names.includes(profile)) {
        // Start on the account the WINDOW is showing, and fall back to it if the one
        // being looked at was closed at the machine — or if the address names one this
        // panel does not have. That is the app correcting the person rather than the
        // person navigating, so it REPLACES: the back button must not walk through it.
        const want = names.includes(who.showing || '') ? who.showing! : names[0] || ''
        setProfile(want)
        // Only a profile that was ASKED FOR and is missing is worth a word. The empty
        // start — a first visit, no account in the address — is not a mistake anybody
        // made and gets no message.
        if (profile && want !== profile) setStray(profile)
        if (want !== profile) go({ ...routeRef.current, profile: want }, true)
      }
      setState(await get<State>('/api/state'))
      const log = await get<{ lines?: LogLine[]; next: number; reset?: boolean }>(
        '/api/log?since=' + logAt.current,
      )
      const fresh = log.lines || []
      if (fresh.length || log.reset) {
        setLines((old) => (log.reset ? fresh : [...old, ...fresh]).slice(-LOG_KEEP))
        for (const line of fresh) if (line.sev === 'error') announce(line.text)
      }
      logAt.current = log.next
      if (viewRef.current === 'timers') await refreshTimers()
      setOffline(false)
      setTickCount((n) => n + 1)
    } catch (err) {
      if (err instanceof Unauthorised) location.reload()
      setOffline(true)
    }
  }, [announce, go, profile, refreshTimers])

  useEffect(() => {
    applyTheme(theme)
    // …and «как на телефоне» means exactly that: a device that darkens at sunset darkens
    // this page with it, without anybody reopening the app.
    const media = window.matchMedia?.('(prefers-color-scheme: light)')
    if (theme !== 'system' || !media) return
    const follow = () => applyTheme('system')
    media.addEventListener('change', follow)
    return () => media.removeEventListener('change', follow)
  }, [theme])

  // The poll: quick while somebody is looking, slow while the phone is in a pocket.
  useEffect(() => {
    void tick()
    const every = document.hidden ? SLOW_MS : POLL_MS
    const id = window.setInterval(() => void tick(), every)
    const wake = () => {
      window.clearInterval(id)
      if (!document.hidden) void tick()
    }
    document.addEventListener('visibilitychange', wake)
    return () => {
      window.clearInterval(id)
      document.removeEventListener('visibilitychange', wake)
    }
  }, [tick])

  useEffect(() => {
    if (view === 'timers') void refreshTimers()
    if (view === 'more') void refreshScreens()
  }, [view, refreshTimers, refreshScreens])

  // The scenario list is fetched when the develop screen is opened — it used to be
  // fetched when its own tab was, and that tab is gone (see `NAV`).
  useEffect(() => {
    if (screen === DEVELOP_SCREEN) void refreshActions()
  }, [screen, refreshActions])

  /* Another account is another log with its own numbering, another scenario list (the
   * titles follow that profile's language) and another everything — so what was read for
   * the last one is dropped rather than shown under the new name. It hangs off the route
   * because the account can change without a chip being tapped: a reload, a link, the
   * back button. */
  useEffect(() => {
    logAt.current = 0
    setLines([])
    setActions([])
    setScreens([])
  }, [profile])

  /* The word about a link's missing account stands until somebody moves ON PURPOSE —
   * tapping a chip answers it, and the fallback that raised it must not clear it. */
  const leave = useCallback(
    (next: Route, replace?: boolean) => {
      setStray('')
      go(next, replace)
    },
    [go],
  )

  const switchProfile = useCallback(
    (name: string) => {
      // The open screen does not travel: a tab switched on for one profile need not
      // exist on the next, and «Ещё» is where the two lists differ.
      leave({ profile: name, view: view === 'more' ? 'more' : view, screen: null, part: 0, map: 'model' })
    },
    [leave, view],
  )

  const accounts = profiles.accounts || []
  const me = accounts.find((one) => one.name === profile) || { name: profile }

  /* Opening a CLOSED profile is the press the «Профиль» screen already offers, played
     through the same route — the front-end does not learn a second way to do it. Once
     the panel has it open the poll brings it back in `accounts`, and the page moves. */
  const openProfile = useCallback(
    async (name: string) => {
      setPicking(false)
      try {
        await post('/api/screen/press', { id: 'profiles', action: 'open', args: { name } })
      } catch {
        /* the offline mark says so */
      }
      switchProfile(name)
    },
    [switchProfile],
  )

  return (
    <div className="app">
      <header>
        {/* THE PICKER THAT USED TO BE HERE IS GONE (#2025). There were two ways to move
            between accounts — a `<select>` in this line and the chips below — and the
            person asked for one: «оставь только пилюли с профилями, а вверху дропдаун
            убери». Two controls for one thing is two places to look and two states to
            keep in step.
            The chips win because they are the richer of the two: each carries that
            account's own light and says, on a tap, WHY it is that colour. A `<select>`
            can carry a name and nothing else.
            What it costs the header is nothing and what it gives back is 48 px on an
            iPhone 13 mini — the row and its gap — measured 85.3 px before and 37.3 px
            after with four accounts open. The pixels of #1976 are given back rather
            than spent. */}
        {/* THE ACCOUNT IS THE HEADER'S LEFT-HAND SIDE (#2061): its face with its HQ
            level inside, the character's name under it, and the strip of readings to the
            right. The chips that used to sit under this line are GONE — see
            `AccountFace`: one control for one thing, and the sheet the face opens is
            richer than the chips were. */}
        <div className="head-row">
          <button className="head-me" onClick={() => setPicking(true)}
                  aria-label={t('web.ui.accounts.pick')} title={t('web.ui.accounts.pick')}>
            <AccountFace account={me} />
            <span className="head-nick">{me.nick || me.name}</span>
          </button>
          <StatusStrip header={state?.header} />
        </div>
      </header>

      {picking ? (
        <AccountSheet
          accounts={accounts.length ? accounts : [{ name: profile, open: true }]}
          profile={profile}
          onPick={(name) => {
            setPicking(false)
            if (name !== profile) switchProfile(name)
          }}
          onOpen={(name) => void openProfile(name)}
          onClose={() => setPicking(false)}
        />
      ) : null}

      {stray ? (
        <p className="stray">{t('web.ui.route.gone', { name: stray, shown: profile })}</p>
      ) : null}

      <main>
        {screen ? (
          <>
            <ScreenPage
              id={screen}
              pollKey={tickCount}
              part={route.part}
              onPart={(n) => leave({ ...route, part: n })}
              map={route.map}
              onMap={(mode) => leave({ ...route, map: mode }, true)}
              onBack={() => leave({ ...route, screen: null, part: 0, map: 'model' })}
            />
            {screen === DEVELOP_SCREEN ? (
              <>
                {/* The log's page comes first in the window's own order (`PAGES`,
                    `DEFAULT_PAGE = "log"`) — it is what a profile without a saved
                    choice lands on, so it is what the phone shows first too. */}
                <h3 className="screen-part">{t('develop.page.log')}</h3>
                <LogView
                  lines={lines}
                  notify={notify}
                  onNotify={async (want) => {
                    let on = want
                    if (on && 'Notification' in window && Notification.permission !== 'granted') {
                      on = (await Notification.requestPermission()) === 'granted'
                    }
                    notifyRef.current = on
                    setNotify(on)
                  }}
                />
                <h3 className="screen-part">{t('develop.page.scenarios')}</h3>
                <ActionsView
                  actions={actions}
                  running={state?.activity?.name || ''}
                  refresh={() => void tick()}
                />
              </>
            ) : null}
          </>
        ) : view === 'state' ? (
          state ? (
            <StateView
              state={state}
              refresh={() => void tick()}
              onGone={() => setOffline(true)}
            />
          ) : null
        ) : view === 'timers' ? (
          <TimersView
            timers={timers}
            triggers={triggers}
            orders={orders}
            now={state?.time || 0}
            refresh={refreshTimers}
          />
        ) : (
          <MoreView
            screens={screens}
            onOpen={(id) => leave({ ...route, view: 'more', screen: id, part: 0, map: 'model' })}
            theme={theme}
            /* Drawn at once and written for the whole panel — the poll above brings
               the panel's own answer back a moment later, so a refusal corrects it. */
            onTheme={(want) => {
              setTheme(want)
              void post('/api/theme', { theme: want }).then(() => void tick())
            }}
          />
        )}
      </main>

      {offline ? <p className="offline">{t('web.ui.offline')}</p> : null}

      <nav>
        {NAV.map((entry) => (
          <button
            key={entry.id}
            className={'nav' + (view === entry.id && !screen ? ' on' : '')}
            onClick={() => leave({ ...route, view: entry.id, screen: null, part: 0, map: 'model' })}
          >
            {t(entry.key)}
          </button>
        ))}
      </nav>
    </div>
  )
}

export function App() {
  const [ready, setReady] = useState(false)
  const [signedIn, setSignedIn] = useState(false)

  useEffect(() => {
    void (async () => {
      // The locale table answers without a token (`PUBLIC` in panel/web/server.py), so
      // the login box is in the panel's language rather than in locale keys.
      try {
        const answer = await fetch('/api/i18n')
        loadWords(((await answer.json()) as { words?: Words }).words || {})
      } catch {
        /* the key is its own fallback */
      }
      document.title = t('web.ui.title')
      setSignedIn(await ping())
      setReady(true)
    })()
  }, [])

  if (!ready) return null
  return <ToastHost>{signedIn ? <Panel /> : <LoginView />}</ToastHost>
}
