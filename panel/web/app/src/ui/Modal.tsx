import type { ReactNode } from 'react'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'
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
    /* THE PAGE BEHIND IS HELD, AND `overflow: hidden` IS NOT ENOUGH TO HOLD IT (#2061).
       On WebKit — which is every iPhone — the document goes on scrolling under a sheet
       with the body merely overflow-hidden: the list behind slides away, and closing the
       modal leaves the person somewhere they did not go. The lock that works is to pin
       the body and remember where it was, then put it back. */
    const y = window.scrollY
    document.body.style.top = `-${y}px`
    document.body.classList.add('modal-open')
    window.addEventListener('keydown', key)
    return () => {
      document.body.classList.remove('modal-open')
      document.body.style.top = ''
      window.scrollTo(0, y)
      window.removeEventListener('keydown', key)
    }
  }, [onClose])
  /* IT IS DRAWN ON THE BODY, not where it was written (#2061). A gear's modal is
     returned from inside the card it belongs to, and an errand card is a stacking
     context of its own — it has to be, that is what lets its picture sit behind its
     text (`isolation: isolate`). A `z-index: 40` inside a stacking context is 40 WITHIN
     THAT CARD, so the cards drawn after it painted straight over the sheet: the modal
     came up with the list showing through it. A portal takes it out to the body, where
     its z-index means what it says, and no future card style can reach it. */
  return createPortal(
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
    </div>,
    document.body,
  )
}
