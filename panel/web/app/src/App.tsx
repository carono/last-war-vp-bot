import { useCallback, useEffect, useRef, useState } from 'react'
import { get, ping, setProfile, Unauthorised } from './api'
import { loadWords, t, type Words } from './i18n'
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

type ViewName = 'state' | 'timers' | 'actions' | 'log' | 'more'

const NAV: { id: ViewName; key: string }[] = [
  { id: 'state', key: 'web.ui.nav.state' },
  { id: 'timers', key: 'web.ui.nav.timers' },
  { id: 'actions', key: 'web.ui.nav.actions' },
  { id: 'log', key: 'web.ui.nav.log' },
  { id: 'more', key: 'web.ui.nav.more' },
]

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
    if (view === 'actions') void refreshActions()
    if (view === 'more') void refreshScreens()
  }, [view, refreshTimers, refreshActions, refreshScreens])

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
        ) : (
          <span className="profile">{state?.profile || profile}</span>
        )}
      </header>

      <Lights lights={profiles.lights || []} profile={profile} onPick={(n) => void switchProfile(n)} />

      <main>
        {screen ? (
          <ScreenPage id={screen} pollKey={tickCount} onBack={() => setScreen(null)} />
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
        ) : view === 'actions' ? (
          <ActionsView
            actions={actions}
            running={state?.activity?.name || ''}
            refresh={() => void tick()}
          />
        ) : view === 'log' ? (
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
