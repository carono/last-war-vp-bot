import { t } from '../i18n'
import type { PressAnswer } from '../types'

/* WHAT ONE PRESS CAME TO, in the four things it can come to (#1331). A press is not a
 * yes-or-no: it may be done; it may be ACCEPTED and still running, because a scenario
 * takes seconds and the panel answers before it ends; it may be refused for a reason the
 * tab knows; or it may name something this panel has no press for. They were all drawn
 * as «занято» once, and the accepted one was drawn as an error while the scenario it
 * started ran perfectly well — which is the one thing a panel must never say, because
 * the person presses it again.
 *
 * `reason` is a locale KEY when the tab has one and plain words when it is quoting the
 * game; `t()` hands back anything it does not know, so both read correctly. */
export function pressWord(answer: PressAnswer | null | undefined): string {
  if (!answer) return t('web.ui.refused')
  if (answer.pending) return t('web.ui.accepted')
  if (answer.ok) return t('web.ui.done')
  if (answer.error === 'unknown') return t('web.ui.unknown')
  const why = answer.reason || answer.detail || ''
  return why ? t('web.ui.refused.why', { why: t(why) }) : t('web.ui.refused')
}
