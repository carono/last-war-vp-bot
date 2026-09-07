/* Talking to the panel: two verbs, one rule.
 *
 * WHICH ACCOUNT TRAVELS ON EVERY REQUEST. A window may hold four profiles open and they
 * are four clients, four schedules and four logs — a page that asked without saying
 * which would show one of them and imply the others (`panel/web/api.py`). A GET carries
 * it in the query, a POST in the BODY: the API ignores `?profile=` on a POST.
 *
 * Nothing here decides anything. Every call is one route, and a route is one call onto
 * the runtime — an ability is a scenario and this plays it (CLAUDE.md).
 */

let profile = ''

/** Whose panel is being looked at. Empty means «the session the server came up with». */
export function currentProfile(): string {
  return profile
}

export function setProfile(name: string): void {
  profile = name
}

/** Raised when the panel says the token is not good — the caller shows the login box. */
export class Unauthorised extends Error {}

/** Raised when this panel has not got the account the request named (#2593).
 *
 * A link is sent to oneself and opened a week later, by which time that profile may have
 * been closed at the machine — or the link came from another computer altogether. The
 * refusal carries the accounts there ARE, so the page can re-point itself in silence
 * instead of sitting on «нет связи с панелью» for ever: every route it draws itself with
 * names the account, so without this the poll only ever failed. */
export class NoSuchProfile extends Error {
  constructor(readonly profiles: string[]) {
    super('no_such_profile')
  }
}

function withProfile(path: string): string {
  if (!profile) return path
  return path + (path.includes('?') ? '&' : '?') + 'profile=' + encodeURIComponent(profile)
}

export async function get<T>(path: string): Promise<T> {
  const answer = await fetch(withProfile(path), { headers: { Accept: 'application/json' } })
  if (answer.status === 401) throw new Unauthorised('unauthorised')
  if (answer.status === 409) {
    const said = (await answer.json().catch(() => ({}))) as { error?: string; profiles?: string[] }
    if (said.error === 'no_such_profile') throw new NoSuchProfile(said.profiles || [])
  }
  if (!answer.ok) throw new Error('http ' + answer.status)
  return (await answer.json()) as T
}

export async function post<T>(path: string, body?: Record<string, unknown>): Promise<T> {
  const answer = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile, ...(body || {}) }),
  })
  if (answer.status === 401) throw new Unauthorised('unauthorised')
  return (await answer.json()) as T
}

/** Is this browser already carrying a good token? Answered without one. */
export async function ping(): Promise<boolean> {
  try {
    const answer = await fetch('/api/ping')
    return !!(await answer.json()).authorised
  } catch {
    return false
  }
}
