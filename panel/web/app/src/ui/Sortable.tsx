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
 * «works on the phone AND at the machine». The moves are listened for on the WINDOW for
 * as long as a drag lasts (see the effect below for what a pointer capture cost here),
 * and what is under the finger is asked of the DOM (`elementFromPoint`) rather than
 * worked out from coordinates the layout would have to be re-measured for.
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
  /* THE ORDER AS IT STANDS RIGHT NOW, beside the state that draws it. A drag reads it
     on every move and the release SENDS it, and neither may go through a state updater:
     React batches those and may run one twice, so a side effect inside one is a press
     that sometimes fires twice and sometimes not at all. Measured live (#2670): the
     tiles swapped under the finger and the panel never heard about it. */
  const live = useRef<string[]>(ids)
  const held = useRef<string | null>(null)
  const [dragging, setDragging] = useState<string | null>(null)
  const stamp = ids.join(',')
  const put = (next: string[]) => {
    live.current = next
    setOrder(next)
  }
  /* THE PANEL IS THE TRUTH the moment it answers. A drag paints the new order at once —
     a list that springs back under the thumb reads as a move that did not land — and the
     next screen answer replaces it, which is what makes a rejected move visible. */
  useEffect(() => {
    if (!held.current) put(ids)
     
  }, [stamp])

  /* THE MOVES ARE LISTENED FOR ON THE WINDOW, AND THEY ARE HOOKED UP INSIDE THE PRESS
   * ITSELF (#2670). Two measured mistakes are pinned here, both of which looked like the
   * drag working — the tiles moved under the finger — while the panel heard nothing:
   *
   * 1. THE GRIP TOOK A POINTER CAPTURE. The first reorder MOVES the grip's own tile in
   *    the DOM, and after that WebKit delivered nothing more to it: no `pointermove`, no
   *    `pointerup`, so the release that sends the order never ran.
   * 2. THE WINDOW LISTENERS WERE ARMED BY AN EFFECT on a piece of state. React commits
   *    state a tick later, so a drag whose first move lands in the same tick as the press
   *    — every synthetic one, and a fast thumb — moved with no listener attached.
   *
   * So the press hooks the window up itself, synchronously, and the state it also sets is
   * only what draws the tile as lifted. A window cannot be moved out from under a drag,
   * and it ends one on `pointerup` wherever the finger happens to be — including outside
   * the grid, which is where a thumb lets go about half the time. */
  const undo = useRef<(() => void) | null>(null)
  useEffect(() => () => undo.current?.(), [])

  const start = (id: string) => {
    undo.current?.()
    held.current = id
    setDragging(id)
    const at = (event: PointerEvent) => {
      const under = document.elementFromPoint(event.clientX, event.clientY)
      const box = under?.closest('[data-sort-id]')
      return box ? box.getAttribute('data-sort-id') : null
    }
    const move = (event: PointerEvent) => {
      if (event.cancelable) event.preventDefault()
      const over = at(event)
      if (!over || over === id) return
      const was = live.current
      const from = was.indexOf(id)
      const to = was.indexOf(over)
      if (from < 0 || to < 0) return
      const next = was.slice()
      next.splice(to, 0, next.splice(from, 1)[0])
      put(next)
    }
    const off = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', drop)
      undo.current = null
      held.current = null
      setDragging(null)
    }
    function stop() {
      const want = live.current
      off()
      // Only a move that CHANGED something is a press: letting go where you picked up is
      // not an order, and a press per touch would be a press per accidental tap.
      if (want.join(',') !== stamp) onOrder(want)
    }
    function drop() {
      off()
      put(ids)
    }
    window.addEventListener('pointermove', move, { passive: false })
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', drop)
    undo.current = off
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
        if (e.cancelable) e.preventDefault()
        start(id)
      }}
    >
      {'\u2630'}
    </button>
  )

  return (
    <div className={className}>
      {order.map((id) => (
        <div
          className={'sortable' + (dragging === id ? ' held' : '')}
          key={id}
          data-sort-id={id}
        >
          {render(id, grip(id))}
        </div>
      ))}
    </div>
  )
}
