/* The words, and the only way this front-end is allowed to say one.
 *
 * `/api/i18n` hands over the whole locale table — which IS `panel/locales/` — so a key
 * added for the window reaches the phone in the same commit, in eleven languages, with
 * no JavaScript changing. A missing key falls back to the key itself, exactly as the
 * window does: a screen full of `secret.tasks.left` is a bug report, and a screen full
 * of English pretending to be Polish is not.
 *
 * A literal handed to a component is a bug even when it is written in the language the
 * panel happens to be showing (CLAUDE.md).
 */

export type Words = Record<string, string>

let words: Words = {}

export function loadWords(table: Words): void {
  words = table || {}
}

export function t(key: string | undefined | null, fmt?: Record<string, unknown>): string {
  if (!key) return ''
  let text = words[key]
  if (text === undefined) return key
  if (fmt) {
    for (const name of Object.keys(fmt)) {
      text = text.split('{' + name + '}').join(String(fmt[name]))
    }
  }
  return text
}

/** A span of seconds in the panel's own words — «5 мин», «2 ч». */
export function span(seconds: number): string {
  const n = Math.max(0, Math.round(seconds))
  if (n < 60) return t('web.ui.unit.sec', { n })
  if (n < 3600) return t('web.ui.unit.min', { n: Math.round(n / 60) })
  if (n < 86400) return t('web.ui.unit.hour', { n: Math.round(n / 3600) })
  return t('web.ui.unit.day', { n: Math.round(n / 86400) })
}

/* `now` is the PANEL's clock, never the phone's: a tablet whose time is a minute out
 * would otherwise report every errand as overdue. */
export function when(stamp: number | null | undefined, now: number): string {
  if (!stamp) return ''
  const delta = stamp - now
  if (Math.abs(delta) < 30) return t('web.ui.now')
  return delta > 0 ? t('web.ui.in', { span: span(delta) }) : t('web.ui.ago', { span: span(-delta) })
}
