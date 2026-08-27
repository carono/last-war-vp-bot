import { useCallback, useEffect, useRef, useState } from 'react'
import { get, ping, setProfile, Unauthorised } from './api'
import { loadWords, span, t, type Words } from './i18n'
import { ToastHost, useToast } from './ui/Toast'
import { ActionsView } from './views/ActionsView'
import { LoginView } from './views/LoginView'
import { LogView } from './views/LogView'
import { MoreView } from './views/MoreView'
import { ScreenPage } from './views/ScreenView'
import { StateView } from './views/StateView'
import { TimersView } from './views/TimersView'
import type {
  ActionRow,
  Header,
  Light,
  LogLine,
  Profiles,
  Screen,
  State,
  TimerRow,
  TriggerRow,
} from './types'

const POLL_MS = 2500 //  how often a visible page asks for state and log
const SLOW_MS = 15000 // …and when it is in a pocket, hidden
const LOG_KEEP = 400 //  lines held for a phone that has been open all evening

type ViewName = 'state' | 'timers' | 'more'

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

/* One light per open account, drawn from the verdict the window's status poll already
 * made (`panel/runtime/health.py`). The words are said by the PANEL, in each account's
 * own language, and arrive ready: nothing here formats a sentence, because a browser
 * wording a reading is the second copy of it. */
function Lights({
  lights,
  profile,
  onPick,
}: {
  lights: Light[]
  profile: string
  onPick: (name: string) => void
}) {
  const toast = useToast()
  if (lights.length < 2) return null
  return (
    <div className="lights">
      {lights.map((light) => (
        <button
          key={light.name}
          className={'chip' + (light.name === profile ? ' on' : '')}
          onClick={() => {
            // Tap = look at that account AND say why its light is that colour. Both,
            // because a chip that only explained would be the one thing on the page that
            // looks like a switch and is not.
            toast((light.tip || [light.text || '']).join(' · '))
            if (light.name !== profile) onPick(light.name)
          }}
        >
          <span className={'dot ' + (light.colour || 'warn')} />
          {light.name}
        </button>
      ))}
    </div>
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

function StatusStrip({ header, account }: { header?: Header; account?: string }) {
  const known = (header?.age ?? -1) >= 0
  const nick = header?.nick || ''
  const scene = header?.scene || ''
  const win = header?.window || ''
  const depth = header?.depth || 0
  const server = header?.server || 0
  const home = header?.home || 0
  const level = header?.level || 0
  /* NOTHING HAS BEEN READ, so the strip SAYS so in words. It does not draw a name-shaped
   * dash beside a zero of a warzone: a header that shows empty fields reads as «этот
   * аккаунт has nothing», and a panel that had just started once announced «событие
   * закрыто · 0 краж» without having asked the game anything at all. */
  /* THE ACCOUNT'S OWN NAME RIDES THIS LINE when there is only one profile open, and
   * that is what pays for the strip: with nothing to pick between, the picker's whole row
   * goes, and the header comes out SHORTER than it was before this existed (37 px against
   * 43 on an iPhone 13 mini, measured). With several accounts open the picker keeps its
   * row, because it is a tap target and the one control that must not be cramped. */
  const who = account ? <span className="profile small">{account}</span> : null
  if (!known && !nick) {
    return (
      <div className="status">
        {who}
        <span className="where cold">{t('web.ui.head.nothing')}</span>
      </div>
    )
  }
  return (
    <div className="status">
      {who}
      {nick ? <span className="who">{nick}</span> : null}
      {level > 0 ? <span className="fact">{t('web.ui.head.level', { n: level })}</span> : null}
      {server > 0 ? (
        <span className={'fact' + (home > 0 && home !== server ? ' away' : '')}>
          {t('web.ui.head.server', { n: server })}
        </span>
      ) : null}
      <span className={'where' + (known ? '' : ' cold')}>
        {t(known ? WHERE[scene] || 'web.ui.where.unknown' : 'web.ui.head.nothing')}
      </span>
      {known && win ? <span className="win">{win}</span> : null}
      {known && depth > 1 ? (
        <span className="fact">{t('web.ui.head.stacked', { n: depth - 1 })}</span>
      ) : null}
      {/* WHEN it was read. Silent for the first minute — a reading that fresh is simply
          «now» — and from then on the line carries its own age, because nothing re-takes
          it until something says the player moved. */}
      {known && (header?.age ?? 0) >= 60 ? (
        <span className="fact age">{t('web.ui.ago', { span: span(header?.age || 0) })}</span>
      ) : null}
    </div>
  )
}

function Panel() {
  const [view, setView] = useState<ViewName>('state')
  const [screen, setScreen] = useState<string | null>(null)
  const [profile, setProfileName] = useState('')
  const [profiles, setProfiles] = useState<Profiles>({ profiles: [] })
  const [state, setState] = useState<State | null>(null)
  const [timers, setTimers] = useState<TimerRow[]>([])
  const [triggers, setTriggers] = useState<TriggerRow[]>([])
  const [actions, setActions] = useState<ActionRow[]>([])
  const [screens, setScreens] = useState<Screen[]>([])
  const [lines, setLines] = useState<LogLine[]>([])
  const [offline, setOffline] = useState(false)
  const [notify, setNotify] = useState(false)
  const [tickCount, setTickCount] = useState(0)
  const logAt = useRef(0)
  const notifyRef = useRef(false)
  const viewRef = useRef<ViewName>('state')
  viewRef.current = view

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
      const answer = await get<{ triggers?: TriggerRow[] }>('/api/triggers')
      setTriggers(answer.triggers || [])
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
      const who = await get<Profiles>('/api/profiles')
      setProfiles(who)
      const names = who.profiles || []
      if (!profile || !names.includes(profile)) {
        // Start on the account the WINDOW is showing, and fall back to it if the one
        // being looked at was closed at the machine.
        const want = names.includes(who.showing || '') ? who.showing! : names[0] || ''
        setProfile(want)
        setProfileName(want)
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
  }, [announce, profile, refreshTimers])

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

  const switchProfile = useCallback(
    async (name: string) => {
      // Another account is another log with its own numbering, another scenario list (the
      // titles follow that profile's language) and another everything.
      setProfile(name)
      setProfileName(name)
      logAt.current = 0
      setLines([])
      setActions([])
      setScreens([])
      setScreen(null)
      await tick()
    },
    [tick],
  )

  const names = profiles.profiles || []
  const many = names.length > 1

  return (
    <div className="app">
      <header>
        {many ? (
          <div className="head-line">
            <select
              className="profile picker"
              value={profile}
              onChange={(e) => void switchProfile(e.target.value)}
            >
              {names.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <StatusStrip
          header={state?.header}
          account={many ? '' : state?.profile || profile}
        />
      </header>

      <Lights lights={profiles.lights || []} profile={profile} onPick={(n) => void switchProfile(n)} />

      <main>
        {screen ? (
          <>
            <ScreenPage id={screen} pollKey={tickCount} onBack={() => setScreen(null)} />
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
            now={state?.time || 0}
            refresh={refreshTimers}
          />
        ) : (
          <MoreView screens={screens} onOpen={(id) => setScreen(id)} />
        )}
      </main>

      {offline ? <p className="offline">{t('web.ui.offline')}</p> : null}

      <nav>
        {NAV.map((entry) => (
          <button
            key={entry.id}
            className={'nav' + (view === entry.id && !screen ? ' on' : '')}
            onClick={() => {
              setScreen(null)
              setView(entry.id)
            }}
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
