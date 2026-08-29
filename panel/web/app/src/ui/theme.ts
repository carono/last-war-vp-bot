/* DAY OR NIGHT, AND WHOSE SETTING IT IS (#2061).
 *
 * The person's decision, in their words: **«Цветовая тема, это настройка панели, не
 * аккаунта»**. So it is the PANEL's — one answer for the machine, kept where the language
 * and the remote-control block are kept, which since #2025 is the one database
 * (`panel/profile.py`, `theme()` / `set_theme()`). Nothing about it is stored in the
 * browser: this module only APPLIES what the panel answered, and moving it is a press
 * that names no profile.
 *
 * IT WAS KEPT IN THE BROWSER'S OWN STORAGE FOR A DAY, on the argument that a phone in a dark room
 * and a monitor in a bright one are two readers of one panel. That argument is answered
 * rather than dropped: `system` is one of the three values the panel stores, and it means
 * «follow whichever device is drawing me» — so a panel set that way still darkens with
 * the phone at sunset, while a panel set to `dark` is dark on every screen it is opened
 * on. What is gone is the second copy of the answer.
 */

export type Theme = 'system' | 'dark' | 'light'

export const THEMES: Theme[] = ['system', 'dark', 'light']

export function isTheme(said: unknown): said is Theme {
  return said === 'system' || said === 'dark' || said === 'light'
}

/** Put the panel's answer on `<html>` — the stylesheet does the rest (`app.css`). */
export function applyTheme(theme: Theme): void {
  const dark =
    theme === 'system'
      ? !window.matchMedia?.('(prefers-color-scheme: light)').matches
      : theme === 'dark'
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
}
