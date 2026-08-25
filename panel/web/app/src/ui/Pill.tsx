import type { Colour } from '../types'

/* One reading, worn in a colour. The colour is the PANEL's verdict — never worked out
 * here — so the pill on the phone and the dot in the window cannot disagree (#1911). */
export function Pill({ tone, children }: { tone?: Colour; children: React.ReactNode }) {
  const cls = tone === 'ok' ? 'ok' : tone === 'warn' ? 'warn' : tone === 'bad' ? 'off' : ''
  return <b className={'pill ' + cls}>{children}</b>
}
