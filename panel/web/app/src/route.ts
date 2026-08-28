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
 * …AND THE MAP'S OWN PICTURE, «Наша модель / Экран клиента» (#2018). It is in the
 * address for the person's own reason: «я смотрел карту клиента, обновил и попал на нашу
 * модель — тоже плохо». It passes the same test as the four above — it is WHICH picture
 * is being looked at, not how one is narrowed — and it is chosen once and left, so it
 * costs the history nothing. It rides as a query inside the fragment (`?map=live`) rather
 * than as a segment, because it belongs to the open screen and not to the path: a screen
 * without a map never carries it. Restoring it does start the live reading again, and
 * that is the point rather than a side effect — the reading exists only while somebody
 * has this page open (`WorldMap`), so a reload is that person opening it again.
 *
 * WHAT IS NOT IN IT, and why: the search box and «Показать ещё». They are how the page in
 * front of you is NARROWED, not which page it is, and they move letter by letter — put a
 * search box in the address and the back button walks a word backwards one character at a
 * time instead of going back where it came from. If one of them ever has to survive a
 * reload it belongs in storage, never in the history.
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
  /** Which picture a screen that HAS a map is drawing (#2018); ignored by the rest. */
  map: 'model' | 'live'
}

const VIEWS: ViewName[] = ['state', 'timers', 'more']

/* The stand-in for «no account chosen yet», so the first segment is always the profile
 * and the shape never depends on what is known. A real profile cannot be called this:
 * the panel names its accounts after directories. */
const NOBODY = '-'

export const HOME: Route = { profile: '', view: 'state', screen: null, part: 0, map: 'model' }

export function parseRoute(hash: string): Route {
  const [path, search] = hash.replace(/^#\/?/, '').split('?')
  const options = new URLSearchParams(search || '')
  const map = options.get('map') === 'live' ? 'live' : 'model'
  const bits = path.split('/').filter(Boolean).map(decodeURIComponent)
  const profile = bits[0] && bits[0] !== NOBODY ? bits[0] : ''
  const rest = bits.slice(1)
  if (rest[0] === 'screen' && rest[1]) {
    const part = Number(rest[2])
    return {
      profile,
      view: 'more',
      screen: rest[1],
      part: Number.isFinite(part) && part > 0 ? part : 0,
      map,
    }
  }
  const view = VIEWS.includes(rest[0] as ViewName) ? (rest[0] as ViewName) : 'state'
  return { profile, view, screen: null, part: 0, map: 'model' }
}

export function routeHash(route: Route): string {
  const bits = [encodeURIComponent(route.profile || NOBODY)]
  if (route.screen) {
    bits.push('screen', encodeURIComponent(route.screen))
    if (route.part > 0) bits.push(String(route.part))
  } else {
    bits.push(route.view)
  }
  // Only what is not the default is written down: an address is read by a person, and a
  // screen with no map has nothing to say about which picture it draws.
  const tail = route.screen && route.map === 'live' ? '?map=live' : ''
  return '#/' + bits.join('/') + tail
}

/** True when the two name the same place — so a normalising write can be skipped. */
export function sameRoute(a: Route, b: Route): boolean {
  return routeHash(a) === routeHash(b)
}

/**
 * The address bar as state.
 *
 * `go(route)` PUSHES — a tap is a step the back button can undo. `go(route, true)`
 * REPLACES, and that is for two things: the panel filling in what the person did not type
 * (the account it fell back to, a card index a shorter screen no longer has), and a
 * switch that redraws the page one is already on rather than moving to another — the
 * map's picture. Pushing the first would make the back button walk through the app's own
 * corrections; pushing the second would make it toggle a picture instead of leaving the
 * screen.
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
