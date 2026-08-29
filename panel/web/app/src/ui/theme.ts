/* DAY OR NIGHT, AND WHOSE SETTING IT IS (#2061).
 *
 * The person asked for «переключение дневной/ночной темы». The question that had to be
 * answered before writing it was WHERE the answer lives, and it is neither of the two
 * places this panel usually keeps things:
 *
 *   * not the MACHINE's (`profiles/settings.json`, beside the port and the language) —
 *     one panel is read from a phone in a dark bedroom and from a monitor in a bright
 *     office in the same minute, and a machine-wide answer makes those two fight;
 *   * not the ACCOUNT's — switching profiles must not change the light in the room.
 *
 * It belongs to the BROWSER that draws the page, so it is kept there and nothing about
 * it travels to the panel: no route, no locale-shaped state, no profile field. What it
 * starts from is what the device itself says (`prefers-color-scheme`), which is the
 * answer a phone on an evening schedule already has.
 *
 * Three choices rather than two, and the third is the default: «как на телефоне» follows
 * the device, so a phone that darkens at sunset darkens this page with it.
 */

export type Theme = 'system' | 'dark' | 'light'

const KEY = 'lwvp.theme'

export function readTheme(): Theme {
  try {
    const said = localStorage.getItem(KEY)
    if (said === 'dark' || said === 'light' || said === 'system') return said
  } catch {
    /* a browser with storage switched off simply follows the device */
  }
  return 'system'
}

export function saveTheme(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    /* …and forgets it on the next visit, which is better than not switching at all */
  }
}

/** Put the choice on `<html>` — the stylesheet does the rest (`app.css`). */
export function applyTheme(theme: Theme): void {
  const dark =
    theme === 'system'
      ? !window.matchMedia?.('(prefers-color-scheme: light)').matches
      : theme === 'dark'
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
}
