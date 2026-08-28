/* WHERE THE PERSON IS, WRITTEN IN THE ADDRESS BAR (#2050).
 *
 * The panel is opened on a phone, put in a pocket, and found again an hour later — and
 * a browser that has thrown the tab away reloads it. Until this existed that reload
 * landed on the first screen of whichever account the WINDOW happened to be showing, so
 * the one thing a remote control has to survive — being left alone — was the one thing
 * it did not.
 *
 * THE ADDRESS IS A HASH, deliberately. The bundle is served as plain files out of
 * `panel/web/static/app/` by a `http.server` handler that maps a path to a file
 * (`panel/web/server.py`, `_page`): a real path like `/app/main/state` would be a 404,
 * and giving the server an SPA fallback means teaching it which paths are the app's —
 * a second copy of this list, in Python, silently going stale. A fragment is never sent
 * to the server at all, so nothing there needs to know the app has screens.
 *
 * It also keeps the TOKEN out of the way. Landing with `?token=…` is answered with a
 * redirect to the bare path so the address bar never holds it (`_page`), and a browser
 * carries the fragment across that redirect by itself — so a link with a token and a
 * route in it lands on the right screen with a cookie and a clean address.
 *
 * WHAT IS IN IT: the account, the tab, the open screen and which of that screen's cards
 * is open. Those four are WHERE somebody is standing — reopen the page without them and
 * you are somewhere else.
 *
 * WHAT IS NOT, and why: the search box, «Показать ещё» and the map's «Наша модель /
 * Экран клиента» (#2018). They are how the page being looked at is DRAWN, not which page
 * it is; putting them in the address makes every keystroke a history entry, so the back
 * button walks a search word letter by letter instead of going back. If one of them ever
 * has to survive a reload, it belongs in storage, not in the history.
 */
import { useCallback, useEffect, useState } from 'react'

export type ViewName = 'state' | 'timers' | 'more'

export type Route = {
  /** The account being looked at; empty until the panel has said which ones there are. */
  profile: string
  /** Which of the three bottom-bar tabs. */
  view: ViewName
  /** The screen opened out of «Ещё», or `null` for the tab itself. */
  screen: string | null
  /** Which card of that screen is open: 0 is the summary, i+1 is card i. */
  part: number
}

const VIEWS: ViewName[] = ['state', 'timers', 'more']

/* The stand-in for «no account chosen yet», so the first segment is always the profile
 * and the shape never depends on what is known. A real profile cannot be called this:
 * the panel names its accounts after directories. */
const NOBODY = '-'

export const HOME: Route = { profile: '', view: 'state', screen: null, part: 0 }

export function parseRoute(hash: string): Route {
  const bits = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent)
  const profile = bits[0] && bits[0] !== NOBODY ? bits[0] : ''
  const rest = bits.slice(1)
  if (rest[0] === 'screen' && rest[1]) {
    const part = Number(rest[2])
    return { profile, view: 'more', screen: rest[1], part: Number.isFinite(part) && part > 0 ? part : 0 }
  }
  const view = VIEWS.includes(rest[0] as ViewName) ? (rest[0] as ViewName) : 'state'
  return { profile, view, screen: null, part: 0 }
}

export function routeHash(route: Route): string {
  const bits = [encodeURIComponent(route.profile || NOBODY)]
  if (route.screen) {
    bits.push('screen', encodeURIComponent(route.screen))
    if (route.part > 0) bits.push(String(route.part))
  } else {
    bits.push(route.view)
  }
  return '#/' + bits.join('/')
}

/** True when the two name the same place — so a normalising write can be skipped. */
export function sameRoute(a: Route, b: Route): boolean {
  return routeHash(a) === routeHash(b)
}

/**
 * The address bar as state.
 *
 * `go(route)` PUSHES — a tap is a step the back button can undo. `go(route, true)`
 * REPLACES, and that is for the panel filling in what the person did not type: the
 * account it fell back to, a screen the profile does not have. Pushing those would mean
 * the back button walked through the app's own corrections.
 *
 * The query string is carried across verbatim rather than rebuilt: nothing here puts a
 * token in the address, and nothing here takes one out of a link somebody made.
 */
export function useRoute(): [Route, (next: Route, replace?: boolean) => void] {
  const [route, setRoute] = useState<Route>(() => parseRoute(location.hash))
  useEffect(() => {
    const heard = () => setRoute(parseRoute(location.hash))
    window.addEventListener('popstate', heard)
    window.addEventListener('hashchange', heard)
    return () => {
      window.removeEventListener('popstate', heard)
      window.removeEventListener('hashchange', heard)
    }
  }, [])
  const go = useCallback((next: Route, replace = false) => {
    const url = location.pathname + location.search + routeHash(next)
    if (replace) history.replaceState(null, '', url)
    else history.pushState(null, '', url)
    setRoute(next)
  }, [])
  return [route, go]
}
