import type { ReactNode } from 'react'
import { useEffect } from 'react'
import { t } from '../i18n'

/* A SHEET OVER THE PAGE, not a block that pushes it down (#2051).
 *
 * The person's words: «сделай, чтобы при клике на шестеренку открывалась модалка с
 * параметрами, а не коллапс, это везде». A collapse opens INSIDE the list it belongs to,
 * so the row being edited slides away under a thumb, the rows below it jump, and on a
 * phone the knobs land wherever the scroll happened to be. A sheet keeps the list where
 * it was and gives the settings the whole screen — and it is the same sheet everywhere a
 * gear exists, so the gesture is learnt once.
 *
 * IT CLOSES THREE WAYS, because a modal nobody can dismiss is a trap: the ✕, the dark
 * outside it, and Esc for whoever is at a keyboard. The content is not scrolled by the
 * page behind it — `body.modal-open` holds that still while the sheet is up.
 */
export function Modal({ title, onClose, children }: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.body.classList.add('modal-open')
    window.addEventListener('keydown', key)
    return () => {
      document.body.classList.remove('modal-open')
      window.removeEventListener('keydown', key)
    }
  }, [onClose])
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <b>{title}</b>
          <button className="go icon" aria-label={t('web.ui.close')} title={t('web.ui.close')}
                  onClick={onClose}>
            {'✕'}
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}
