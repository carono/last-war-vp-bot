import { useEffect, useRef, useState, type ReactNode } from 'react'
import { t } from '../i18n'

/* THE ONE DRAGGABLE LIST ON THIS FRONT-END (#2670).
 *
 * The person's words: «Сортировка по приоритету, сделай драг-енд-дроп сортировку
 * элементов». Typing a priority number into a box is how the shop's order used to be
 * set, and a number is not what anybody means by «this one before that one».
 *
 * IT IS A COMPONENT AND NOT A GESTURE WRITTEN INTO ONE PAGE, for the reason `CLAUDE.md`
 * states about every control here: «A control that exists twice is written once». The
 * next list somebody wants to reorder uses THIS — improve it, never fork it.
 *
 * WHY A GRIP AND NOT THE WHOLE TILE. A phone has one gesture for two jobs: a drag down
 * the screen scrolls the page, and a drag across the tiles has to reorder them. A tile
 * that captured every touch would be a page that cannot be scrolled past the shop, and
 * one that waited for a long press would be a page that sometimes scrolls and sometimes
 * does not. So the drag lives on a small grip in the corner, which is `touch-action:
 * none` and nothing else on the page is: touching anywhere else scrolls as it always
 * did, and the tile itself stays the purchase.
 *
 * POINTER EVENTS, so a mouse and a thumb are the same code — the browser's own answer to
 * «works on the phone AND at the machine». The grip captures the pointer, so the moves
 * keep arriving even when the finger leaves the tile it started on, and what is under
 * the finger is asked of the DOM (`elementFromPoint`) rather than worked out from
 * coordinates the layout would have to be re-measured for.
 *
 * WHAT IT PROMISES THE CALLER: the order it is DRAWING follows the ids it was handed —
 * so a screen re-read that disagrees wins — and `onOrder` is called once, on release,
 * with the whole list. Never per move: what a drag produces is a list, and sending it a
 * pair at a time is how two front-ends end up disagreeing about the middle of it.
 */
export function Sortable({
  ids,
  onOrder,
  className,
  render,
}: {
  /** The items, in the order they stand in now. */
  ids: string[]
  /** Called once, on release, with the whole new order. */
  onOrder: (ids: string[]) => void
  /** The container's own class — the caller's grid, not a layout invented here. */
  className?: string
  /** One item: its id and the grip to put somewhere on it. */
  render: (id: string, grip: ReactNode) => ReactNode
}) {
  const [order, setOrder] = useState<string[]>(ids)
  const held = useRef<string | null>(null)
  const stamp = ids.join(',')
  /* THE PANEL IS THE TRUTH the moment it answers. A drag paints the new order at once —
     a list that springs back under the thumb reads as a move that did not land — and the
     next screen answer replaces it, which is what makes a rejected move visible. */
  useEffect(() => {
    if (!held.current) setOrder(ids)
     
  }, [stamp])

  const at = (event: { clientX: number; clientY: number }) => {
    const under = document.elementFromPoint(event.clientX, event.clientY)
    const box = under?.closest('[data-sort-id]')
    return box ? box.getAttribute('data-sort-id') : null
  }

  const grip = (id: string) => (
    <button
      className="grip"
      title={t('web.ui.drag')}
      aria-label={t('web.ui.drag')}
      onClick={(e) => {
        // The grip is inside a tile that is itself a press — a tap on it must not buy.
        e.stopPropagation()
        e.preventDefault()
      }}
      onPointerDown={(e) => {
        e.stopPropagation()
        e.preventDefault()
        held.current = id
        e.currentTarget.setPointerCapture(e.pointerId)
      }}
      onPointerMove={(e) => {
        if (held.current !== id) return
        const over = at(e)
        if (!over || over === id) return
        setOrder((was) => {
          const from = was.indexOf(id)
          const to = was.indexOf(over)
          if (from < 0 || to < 0) return was
          const next = was.slice()
          next.splice(to, 0, next.splice(from, 1)[0])
          return next
        })
      }}
      onPointerUp={(e) => {
        if (held.current !== id) return
        held.current = null
        e.currentTarget.releasePointerCapture(e.pointerId)
        setOrder((was) => {
          if (was.join(',') !== stamp) onOrder(was)
          return was
        })
      }}
      onPointerCancel={() => {
        held.current = null
        setOrder(ids)
      }}
    >
      {'☰'}
    </button>
  )

  return (
    <div className={className}>
      {order.map((id) => (
        <div
          className={'sortable' + (held.current === id ? ' held' : '')}
          key={id}
          data-sort-id={id}
        >
          {render(id, grip(id))}
        </div>
      ))}
    </div>
  )
}
