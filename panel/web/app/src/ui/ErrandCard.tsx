import { useState, type CSSProperties, type ReactNode } from 'react'
import { span, t } from '../i18n'
import { Modal } from './Modal'
import type { ErrandStat } from '../types'

/* THE CARD EVERY SELF-RUNNING THING IS DRAWN AS — and since #2119 every LIST is too.
 *
 * It was written for the errands («таймеры сделай так же небольшими карточками, как и
 * триггеры», 5daa8eb2) and it lived inside `views/TimersView.tsx`, which is where the
 * register of players would have grown a second one of its own. The person's rule for
 * exactly this is already written down (`CLAUDE.md`, «A control that exists twice is
 * written once»), so the card MOVED here instead: «Таймеры» draws one, and so does any
 * card of a screen whose tab asked for `layout: "cards"` (`views/ScreenView.tsx`).
 *
 * WHAT A CALLER BRINGS is only what differs between the two: the picture, the words, the
 * switch in the corner, the buttons on the bottom row and the sheets they open. What the
 * card itself owns is the SHAPE — the bubble over the picture, the name on one line, the
 * order of the rows — because that is what must not differ.
 */

/* THE «i» (#2061), and it exists because the NAME got shorter.
 *
 * The person's words: «слишком длинные названия, сократи, должны быть лаконичные, а
 * подробное описание вынеси в кнопку i». A card's head used to carry the whole sentence
 * — «Секретки: собирать по созреванию, вскрывать ящики, обновлять и отправлять» — which
 * is three lines on a phone and the reason thirty cards could not be skimmed. The panel
 * now sends both (`panel/web/api.py`): the short label as `title` and the sentence as
 * `about`. An errand whose label has no short form sends an empty `about` and draws no
 * «i» at all, rather than one that opens the title again.
 */
/* …and since #2370 the «i» also holds the line the card used to WEAR — the person's
 * words: «давай скроем описание полностью». The schedule («каждые 1 ч · следующий через
 * 31 мин · последний запуск 29 мин назад») is prose about a picture-sized card: it was
 * two of the three text rows over a picture drawn for the card, and the picture is what
 * the person asked for. It is not deleted — a schedule readable nowhere else would be a
 * fact lost — it moves under the «i», which is why the mark is drawn now even for an
 * errand that has no sentence of its own. */
export function useAbout(title: string, about?: string, extra?: ReactNode) {
  const [open, setOpen] = useState(false)
  if (!about && !extra) return { button: null, panel: null }
  return {
    button: (
      <button
        className="go icon"
        title={t('web.ui.about')}
        aria-label={t('web.ui.about')}
        onClick={() => setOpen(true)}
      >
        {'ℹ'}
      </button>
    ),
    panel: open ? (
      <Modal title={title} onClose={() => setOpen(false)}>
        {extra ? <p className="muted small">{extra}</p> : null}
        {about ? <p>{about}</p> : null}
      </Modal>
    ) : null,
  }
}

/* THE GAME'S OWN PICTURE FOR AN ERRAND (#2019), and since #2061 it is the CARD'S
 * BACKGROUND rather than a stamp beside the name — the person's words: «картинка должна
 * быть большая и фоном, чтобы аккуратно была на карточке».
 *
 * A link and not a blob: the panel sends `/api/errandicon?icon=…` and the browser fetches
 * each sprite once, exactly as it already does for a player's face. The URL rides a
 * custom property because the SIZE, the position, the fade and the scrim over it are
 * decisions of the stylesheet, not of this component — it hands over one string and
 * nothing else.
 *
 * A machine that has not extracted the art (or an errand the client has no sprite for —
 * three of thirty-six, `tools/data/errand_icons.json`) sends nothing, the card gets no
 * `art` class, and it draws exactly as a card drew before this existed. That is the
 * honest answer: a plain card, never a broken frame or a grey block where a picture
 * failed.
 *
 * IT COSTS NO HEIGHT. The picture is painted by two pseudo-elements taken out of the
 * flow, so a card is the size its text makes it, which is the size it was (#1999,
 * 5daa8eb2 — the compactness was fought for and a background is not a reason to give it
 * back). Measured on an emulated iPhone 15 over the live list: 35 cards, min 93 px,
 * average 159 px, max 241 px, before and after. */
export function artStyle(icon?: string, focus?: string): CSSProperties | undefined {
  if (!icon) return undefined
  // WHERE THE CROP LANDS (#2340) rides beside the link, because it is a fact about the
  // PICTURE: a square cover inside a wide card shows a stripe of itself, and the stylesheet
  // cannot know which stripe holds the subject. Absent, and the sheet's own default stands.
  if (focus) {
    return {
      ['--art' as string]: 'url("' + icon + '")',
      ['--art-pos' as string]: focus,
    } as CSSProperties
  }
  // `url("…")` rather than the bare link: a sprite name is the game's own file name and
  // may hold anything a file name may hold.
  return { ['--art' as string]: 'url("' + icon + '")' } as CSSProperties
}

/* THE SWITCH, AND IT IS THE TOP-RIGHT CORNER OF THE CARD (#2061) — the person's words:
 * «чекбокс включения/выключения перемести в правый верхний угол».
 *
 * It was a `SwitchRow`, which makes the WHOLE row the target: right for a form, wrong
 * for a card whose head also holds a picture and a name that may wrap. Here the box is
 * its own target and the name is not part of it — a tap meant for the title used to
 * switch the errand off. It keeps `--tap` and carries the errand's name as its
 * `aria-label`, so nothing is lost to somebody reading the page aloud. */
export function ErrandSwitch({ title, on, onToggle }: {
  title: string
  on: boolean
  onToggle: (want: boolean) => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  /* The LABEL is the target and the box is what is drawn: a checkbox 28 px tall is
     under half a fingertip, and every other control on this front-end is `--tap`. */
  return (
    <label className="errand-switch">
    <input
      type="checkbox"
      checked={on}
      disabled={busy}
      aria-label={title}
      title={title}
      onChange={async (e) => {
        const want = e.target.checked
        setBusy(true)
        try {
          await onToggle(want)
        } finally {
          setBusy(false)
        }
      }}
    />
    </label>
  )
}

/* ONE LIVE LINE UNDER THE BLOCK (#2019) — «+377 023 ждёт сбора», «12 стягов сегодня».
 *
 * IT COST NOTHING TO KNOW. Every number here came off something the panel already had
 * (`panel/runtime/errand_stats.py`); nothing on this page asks the game, which is the
 * rule a screen of a dozen polled blocks must obey above all others.
 *
 * SO IT SAYS HOW OLD IT IS. A reading with an age is a reading a person can judge; one
 * without is a number that might be from yesterday and looks like now. A source with no
 * clock of its own — a day's tally — sends `age: null` and says nothing, because
 * «сегодня» is already the whole truth about when it is from. */
export function Stat({ stat }: { stat?: ErrandStat | null }) {
  if (!stat || !stat.key) return null
  const age = stat.age
  const old = typeof age === 'number' && age >= 0 ? t('timers.stat.age', { span: span(age) }) : ''
  return (
    <p className="stat small">
      <b>{t(stat.key, stat.fmt)}</b>
      {old ? <span className="muted"> · {old}</span> : null}
    </p>
  )
}

/* THE CARD ITSELF. Three rows and the order of them is the point (#2061): the name with
 * its switch in the corner, what it is waiting for and what it has brought in, and —
 * last — the signs that ACT. The buttons used to sit on the head row beside the switch,
 * and at 280 px (the narrowest a card gets in the grid) three of them and a switch left
 * the name about thirty pixels.
 *
 * A CARD THAT IS OFF LOOKS OFF (#2061) — «когда чекбокс выключен, вся карточка должна
 * менять цвет». A screen of thirty cards is read by its colour before it is read by its
 * switches, and a small grey box in the corner is not a colour. A card with nothing to
 * switch is never «off»: `on` defaults to true, so a player's card is simply a card.
 */
export function ErrandCard({
  icon,
  cover,
  focus,
  title,
  about,
  badge,
  infoNode,
  on = true,
  facts,
  queued,
  pill,
  state,
  stat,
  switchNode,
  acts,
  sheets,
  factsInSheet,
}: {
  icon?: string
  /** THE PICTURE WAS DRAWN FOR THE CARD (#2340) — full colour, no wash, «i» at the name. */
  cover?: boolean
  /** Where the card crops that picture — a CSS vertical position (#2340). */
  focus?: string
  title: string
  about?: string
  /** A MARK WORN AT THE NAME (#2308) — a player's own note, beside the title. */
  badge?: string
  /** The «i» in the top-right corner (#2308), beside the switch when there is one. */
  infoNode?: ReactNode
  on?: boolean
  facts?: ReactNode
  queued?: boolean
  /** A word of the panel's about this row — a locale KEY, drawn before the facts. */
  pill?: string
  /** What this row is DOING, already in the panel's words — data, never a key (#2068). */
  state?: string
  stat?: ErrandStat | null
  /** The one switch this card is about, drawn in the top-right corner. */
  switchNode?: ReactNode
  /** The row of signs at the bottom: «⚙», «▶», a press of the list's own. */
  acts?: ReactNode[]
  /** Whatever those signs open — a modal belongs under the whole block. */
  sheets?: ReactNode
  /** THE SCHEDULE LINE GOES UNDER THE «i» INSTEAD OF ON THE CARD (#2370). Set by the
   *  errands, whose card is a picture; a list that draws its facts on the row — the
   *  register of players — leaves it alone and keeps them. */
  factsInSheet?: boolean
}) {
  const info = useAbout(title, about, factsInSheet ? facts : undefined)
  /* THE «i» LEADS THE NAME ON A COVER CARD (#2340) — the person's words: «кнопку i
     ставим перед названием и переделываем в иконку». On a card whose picture is a
     sprite it stays where it has been since #2061, first in the row of signs: the two
     drawings are told apart by the PICTURE, not by the row, so nothing else changes
     under a card that has no cover yet. */
  const lead = cover ? info.button : null
  const row = (cover ? (acts || []) : [info.button, ...(acts || [])]).filter(Boolean)
  return (
    <div
      className={'item errand' + (icon ? ' art' : '') + (cover ? ' cover' : '') +
                 (on ? '' : ' off')}
      style={artStyle(icon, focus)}
    >
      {/* ONE BUBBLE, NOT FOUR (#2061). The picture is at full brightness behind it, so
          the words need a panel of their own — and it is a single element around all of
          them rather than a background on each row: four paddings cost four times the
          height, and this card's height is fought for (#1999). A card with no picture
          gets no bubble at all and draws exactly as it did. */}
      <div className="errand-body">
        <div className="errand-head">
          {lead}
          <span className="title">{title}</span>
          {/* THE MARK RIDES THE NAME (#2308): it is the reason somebody looks a row up,
              and on the line of facts underneath it was one word among six. */}
          {badge ? <span className="badge">{badge}</span> : null}
          {infoNode || switchNode ? (
            /* ONE CORNER, whatever stands in it — the switch a card is about, the «i»
               that opens everything else, or both. */
            <span className="errand-corner">
              {infoNode}
              {switchNode}
            </span>
          ) : null}
        </div>
        {/* «Сейчас в очереди» and a word of the panel's own are NOT the schedule and
            stay where they are: they say what is happening to this errand this minute,
            which is the one thing a card must answer without being opened (#2370). */}
        {queued || pill || (facts && !factsInSheet) ? (
          <p className="muted small facts">
            {queued ? <span className="pill warn">{t('web.ui.queued')}</span> : null}
            {pill ? <span className="pill">{t(pill)}</span> : null}
            {factsInSheet ? null : facts}
          </p>
        ) : null}
        {state ? <p className="muted small">{state}</p> : null}
        {/* THE READING SHARES THE FOOT WITH THE SIGNS ON A COVER CARD (#2340) — the
            person's words: «данные со статистикой давай перенесем в линию, где кнопка
            запуска, пусть будет слева». It is a line of its own on every other card, and
            it stays one there: the foot row exists on a cover because the picture is the
            card and every empty line is picture that could have been seen. The signs keep
            their own width (`flex: 0 0 auto`), so a long reading is cut rather than
            pushed under «▶». */}
        {cover ? null : <Stat stat={stat} />}
        {row.length || (cover && stat && stat.key) ? (
          <div className="errand-acts">
            {cover ? <Stat stat={stat} /> : null}
            {row}
          </div>
        ) : null}
      </div>
      {sheets}
      {info.panel}
    </div>
  )
}
