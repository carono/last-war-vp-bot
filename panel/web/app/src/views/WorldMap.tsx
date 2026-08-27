/* THE MAP AS THE PANEL SEES IT (#2018).
 *
 * The person's ask, in their words: «нужно в отдельной вкладке перерисовывать состояние
 * игры, тайлы, объекты… достаточно схематично… пока просто нужно сравнить, что видим мы
 * с реальностью». So this is a mirror held up beside the real client — every dot is
 * something the panel believes is on the map, painted where the panel believes it is.
 *
 * READ-ONLY, and it is pinned rather than merely intended
 * (`tests/test_panel_worldscene.py`): no press reaches the game from this canvas.
 * Tapping says what the panel knows about that spot and nothing more — not a jump, not
 * a robbery, not a march.
 *
 * WHAT IS DRAWN UNDER THE DOTS IS THE POINT. Empty ground on our picture means one of
 * two opposite things — «there is nothing there» or «we have never looked there» — and
 * a comparison tool that cannot tell them apart is worse than none. So the ground we
 * have swept is tinted, the ground we have not is left dark and hatched, and a tap on
 * bare ground says when the camera was last over it. The rectangle each map reply
 * answered about has always been on the wire; the world listener simply stopped
 * throwing it away, so nothing new is asked of the game.
 *
 * WHY AN ENGINE. Thirty thousand objects redrawn on every pan is not a thing to do with
 * DOM nodes, and the person asked for a real one rather than a home-made loop. PixiJS
 * draws them as batched WebGL geometry — one `Graphics` per kind, filled in one pass.
 *
 * …AND IT IS LOADED ONLY WHEN THIS MAP IS OPENED. `import('pixi.js')` is dynamic on
 * purpose and it is a condition of the feature, not a nicety: the panel is opened from
 * a phone on a home link, and somebody who never opens this tab must not pay a byte for
 * a renderer they will not see.
 *
 * WHERE THE DATA COMES FROM. `/api/screen/data?id=<tab>&kind=map`, asked for ONCE when
 * the map is opened and again only when the person presses «перерисовать». It is not on
 * the screen's poll on purpose: the panel's rule is «read once, then listen», and a
 * canvas re-fetching a megabyte every couple of seconds would be exactly the background
 * poll that rule forbids. What it does instead is show HOW OLD the reading is.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Application, Container } from 'pixi.js'
import { get } from '../api'
import { t } from '../i18n'

/** One thing on the map. Short keys — this list is the whole payload (see the Python). */
export interface SceneObject {
  k: string
  x: number
  y: number
  s?: number
  l?: number
  n?: string
  d?: string
  t?: number
}

/** One cell of ground we have looked at: where, when, and from what height. */
export interface CoverageCell {
  s: number
  cx: number
  cy: number
  t: number
  v: number
}

export interface Scene {
  at: number
  server: number | null
  servers: number[]
  bounds: { x0: number; y0: number; x1: number; y1: number }
  objects: SceneObject[]
  coverage: { cell: number; sizes: Record<string, number>; cells: CoverageCell[] }
  counts: Record<string, number>
  hidden: Record<string, number>
  ages: Record<string, number | null>
}

/** WHAT THE CLIENT IS LOOKING AT (#2018) — the answer of `kind=live`.
 *
 * A different picture from a different source: not what the panel has gathered, but what
 * the client is holding around its camera at this second. `age` is how many seconds ago
 * it was read and it is drawn on the page, because this reading is skipped whenever the
 * bot is driving the game and a picture that has stopped must look stopped. */
export interface LiveView {
  scene?: string
  server?: number
  x?: number
  y?: number
  zoom?: number
  lod?: number
  radius?: number
  objects?: SceneObject[]
  age?: number
  reading?: boolean
  interval?: number
  skipped?: number
}

/* WHAT EACH KIND LOOKS LIKE. A colour and a size in TILES, so a dot keeps its meaning at
 * every zoom: a base is a tile, a monster is smaller because there are thousands of
 * them, and the two moving things are round so a lorry standing on a mine is still two
 * things and not one. Deliberately NOT the game's own palette — this picture is compared
 * AGAINST the game, and a copy that looked identical would hide the very differences it
 * exists to show. */
const KINDS: { id: string; colour: number; size: number; shape: 'square' | 'dot' }[] = [
  { id: 'base', colour: 0x4da3ff, size: 1.6, shape: 'square' },
  { id: 'mine', colour: 0x6fcf6f, size: 1.2, shape: 'square' },
  { id: 'monster', colour: 0xd4576b, size: 1.0, shape: 'dot' },
  { id: 'secret', colour: 0xffd257, size: 2.0, shape: 'square' },
  { id: 'ghost', colour: 0xb07cff, size: 2.0, shape: 'square' },
  { id: 'treasure', colour: 0xff9f45, size: 2.0, shape: 'square' },
  { id: 'truck', colour: 0x59d6d6, size: 1.6, shape: 'dot' },
  { id: 'train', colour: 0xf07ad0, size: 2.0, shape: 'dot' },
  /* …and the three only the CLIENT'S OWN view ever carries (#2018): a stronghold, an
   * alliance city, and this account's marches in the air. */
  { id: 'stronghold', colour: 0xc9a227, size: 2.0, shape: 'square' },
  { id: 'alliance', colour: 0x7fb3ff, size: 2.4, shape: 'square' },
  { id: 'march', colour: 0xffffff, size: 1.4, shape: 'dot' },
  { id: 'camera', colour: 0xff5c5c, size: 3.0, shape: 'dot' },
]

const COLOUR: Record<string, number> = Object.fromEntries(KINDS.map((k) => [k.id, k.colour]))

/** Ground nobody has swept, and ground swept an hour / a day / longer ago. */
const UNSWEPT = 0x161b22
const SWEPT_FRESH = 0x1f6f43
const SWEPT_OLD = 0x2a3a44

/** A colour as CSS, for the legend swatches. */
function css(colour: number): string {
  return '#' + colour.toString(16).padStart(6, '0')
}

/** What a kind of object is CALLED. The key is glued together here rather than inside
 * `t(...)`, because the i18n scan reads literals out of the call and a half-key would
 * pass for one (`tests/test_panel_web.py`). Every kind drawn here has its own
 * `worldview.kind.*` key, in all eleven locales. */
function kindWord(id: string): string {
  const key = 'worldview.kind.' + id
  return t(key)
}

/** How old a reading is, as m:ss / h:mm:ss — a number, so it needs no translating. */
function ageText(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  const total = Math.max(0, Math.floor(seconds))
  const pad = (n: number) => String(n).padStart(2, '0')
  if (total >= 3600) return Math.floor(total / 3600) + ':' + pad(Math.floor((total % 3600) / 60)) + ':' + pad(total % 60)
  return Math.floor(total / 60) + ':' + pad(total % 60)
}

export function WorldMap({ screen }: { screen: string }) {
  const host = useRef<HTMLDivElement | null>(null)
  const appRef = useRef<Application | null>(null)
  const worldRef = useRef<Container | null>(null)
  const [pixi, setPixi] = useState<typeof import('pixi.js') | null>(null)
  const [scene, setScene] = useState<Scene | null>(null)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const [server, setServer] = useState<number | 'all'>('all')
  const [off, setOff] = useState<Set<string>>(new Set())
  const [ground, setGround] = useState(true)
  const [picked, setPicked] = useState<SceneObject | null>(null)
  const [spot, setSpot] = useState<{ x: number; y: number; cell: CoverageCell | null } | null>(null)
  //: Bumped when the application is up, so the paint below runs once there is a stage.
  const [ready, setReady] = useState(0)
  /* WHICH PICTURE IS ON: the panel's own model, or the CLIENT'S OWN SCREEN (#2018). */
  const [mode, setMode] = useState<'model' | 'live'>('model')
  const [live, setLive] = useState<LiveView | null>(null)

  const load = useCallback(async () => {
    setBusy(true)
    setFailed(false)
    try {
      const answer = await get<Scene>('/api/screen/data?id=' + encodeURIComponent(screen) + '&kind=map')
      setScene(answer)
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }, [screen])

  /* ONE READ WHEN THE MAP IS OPENED. Not a poll — see the file's opening note. */
  useEffect(() => {
    void load()
  }, [load])

  /* THE LIVE READING, AND THE ONLY CLOCK THE FEATURE HAS — HERE, IN THE OPEN PAGE.
   *
   * The panel itself never ticks: `LiveScreen` reads when this route asks and at no other
   * time (`panel/runtime/screenview.py`). So the loop lives in the component, which means
   * closing the tab, switching to «our model» or locking the phone ends it — «закрыл
   * вкладку — чтений ноль» is then a property of where the loop is, not a promise
   * somebody has to keep. The interval comes back WITH the reading, because it is a field
   * the person edits on this very page.
   *
   * A tick is `setTimeout` after the answer rather than `setInterval`: a reading that
   * takes a second and a half must not have the next one queued behind it. */
  useEffect(() => {
    if (mode !== 'live') return
    let dead = false
    let timer = 0
    const tick = async (force: boolean) => {
      try {
        const answer = await get<LiveView>(
          '/api/screen/data?id=' + encodeURIComponent(screen) + '&kind=live' + (force ? '&force=1' : ''),
        )
        if (dead) return
        setLive(answer)
        const wait = Math.max(2, Number(answer.interval) || 5) * 1000
        timer = window.setTimeout(() => void tick(false), wait)
      } catch {
        if (!dead) timer = window.setTimeout(() => void tick(false), 10000)
      }
    }
    void tick(true)
    return () => {
      dead = true
      if (timer) window.clearTimeout(timer)
    }
  }, [mode, screen])

  /* THE ENGINE, FETCHED ON DEMAND. A phone that never opens this tab downloads none of
   * it: the bundler splits `pixi.js` into its own chunk because this import is dynamic. */
  useEffect(() => {
    let dead = false
    void import('pixi.js').then((mod) => {
      if (!dead) setPixi(mod)
    })
    return () => {
      dead = true
    }
  }, [])

  /* …and the application itself, made once the engine has arrived and torn down with
   * the view. `init` is async, so a view unmounted while it was still starting must not
   * leave a canvas behind — hence the flag rather than a bare await. */
  useEffect(() => {
    if (!pixi) return
    let dead = false
    const parent = host.current
    if (!parent) return
    const app = new pixi.Application()
    void app
      .init({ background: 0x0b0f14, antialias: false, resizeTo: parent, autoDensity: true })
      .then(() => {
        if (dead) {
          app.destroy(true)
          return
        }
        parent.appendChild(app.canvas)
        const world = new pixi.Container()
        app.stage.addChild(world)
        appRef.current = app
        worldRef.current = world
        setReady((n) => n + 1)
      })
    return () => {
      dead = true
      if (appRef.current) {
        appRef.current.destroy(true)
        appRef.current = null
        worldRef.current = null
      }
    }
  }, [pixi])

  /* WHAT IS ACTUALLY DRAWN: the scene, narrowed by the warzone chip and by whichever
   * kinds the legend has switched off. Kept out of the paint so a legend press costs no
   * round trip — the filtering is the browser's. */
  /* THE CLIENT'S OWN VIEW, IN THE SHAPE THE PAINT ALREADY KNOWS. The box is the camera's
   * own — radius tiles either side of where it stands — so the picture is the client's
   * window and not the warzone; there is no coverage under it, because «where we have
   * looked» is a fact about our model and says nothing about what the client is holding. */
  const liveScene = useMemo<Scene | null>(() => {
    if (!live || live.scene !== 'world' || live.x === undefined) return null
    const r = live.radius || 20
    return {
      at: Math.floor(Date.now() / 1000),
      server: live.server ?? null,
      servers: live.server ? [live.server] : [],
      bounds: { x0: live.x - r, y0: (live.y || 0) - r, x1: live.x + r, y1: (live.y || 0) + r },
      objects: [
        ...(live.objects || []),
        /* …and the camera itself, so «где мы стоим» is on the picture rather than only
         * in the card above it. */
        { k: 'camera', x: live.x, y: live.y || 0 },
      ],
      coverage: { cell: 25, sizes: {}, cells: [] },
      counts: {},
      hidden: {},
      ages: {},
    }
  }, [live])

  /* Which of the two is on screen. Everything below paints `painted` and does not care
   * which source it came from. */
  const painted = mode === 'live' ? liveScene : scene

  const shown = useMemo(() => {
    if (!painted) return []
    return painted.objects.filter(
      (o) => !off.has(o.k) && (server === 'all' || o.s === undefined || o.s === server),
    )
  }, [painted, off, server])

  const cells = useMemo(() => {
    if (!painted) return []
    return painted.coverage.cells.filter((c) => server === 'all' || c.s === server)
  }, [painted, server])

  /* THE PAINT. One `Graphics` per layer, cleared and refilled; pan and zoom move the
   * container instead of redrawing, so dragging costs nothing at all. */
  useEffect(() => {
    const app = appRef.current
    const world = worldRef.current
    if (!pixi || !app || !world || !painted) return
    world.removeChildren()

    const bounds = painted.bounds
    const width = Math.max(1, bounds.x1 - bounds.x0)
    const height = Math.max(1, bounds.y1 - bounds.y0)
    const view = app.screen
    const fit = Math.min(view.width / width, view.height / height) * 0.92
    const scale = Number.isFinite(fit) && fit > 0 ? fit : 1
    world.scale.set(scale)
    world.position.set(
      view.width / 2 - ((bounds.x0 + bounds.x1) / 2) * scale,
      view.height / 2 - ((bounds.y0 + bounds.y1) / 2) * scale,
    )

    /* THE GROUND, UNDER EVERYTHING. First the whole warzone as UNSWEPT — that is the
     * honest default and the thing this layer exists to say — then the cells we have
     * actually been over, tinted by how long ago. */
    const cell = painted.coverage.cell || 25
    if (ground && mode === 'model') {
      const floor = new pixi.Graphics()
      for (const [name, size] of Object.entries(painted.coverage.sizes)) {
        if (server !== 'all' && Number(name) !== server) continue
        floor.rect(0, 0, size, size)
      }
      floor.fill({ color: UNSWEPT })
      floor.stroke({ color: 0x30363d, width: Math.max(1 / scale, 0.5) })
      world.addChild(floor)

      const now = painted.at
      const fresh = new pixi.Graphics()
      const stale = new pixi.Graphics()
      for (const c of cells) {
        const g = now - c.t < 3600 ? fresh : stale
        g.rect(c.cx * cell, c.cy * cell, cell, cell)
      }
      fresh.fill({ color: SWEPT_FRESH, alpha: 0.55 })
      stale.fill({ color: SWEPT_OLD, alpha: 0.55 })
      world.addChild(stale)
      world.addChild(fresh)
    }

    for (const kind of KINDS) {
      const mine = shown.filter((o) => o.k === kind.id)
      if (!mine.length) continue
      const g = new pixi.Graphics()
      /* A dot must stay visible when the whole warzone is on screen, so its size has a
       * floor in SCREEN pixels — a tile at that zoom is a fraction of one. */
      const size = Math.max(kind.size, 2.5 / scale)
      for (const o of mine) {
        if (kind.shape === 'dot') g.circle(o.x, o.y, size / 2)
        else g.rect(o.x - size / 2, o.y - size / 2, size, size)
      }
      g.fill({ color: kind.colour })
      world.addChild(g)
    }
  }, [pixi, painted, shown, cells, ground, server, ready, mode])

  /* PAN, ZOOM AND ONE TAP. The tap is a READING: the nearest object, or — on bare
   * ground — when we were last over that spot. It presses nothing. Zoom is anchored at
   * the pointer, which is what makes a map feel like a map rather than a scrollbar. */
  useEffect(() => {
    const world = worldRef.current
    const parent = host.current
    if (!world || !parent) return
    let dragging = false
    let moved = 0
    let lastX = 0
    let lastY = 0

    const down = (e: PointerEvent) => {
      dragging = true
      moved = 0
      lastX = e.clientX
      lastY = e.clientY
    }
    const move = (e: PointerEvent) => {
      if (!dragging) return
      const dx = e.clientX - lastX
      const dy = e.clientY - lastY
      moved += Math.abs(dx) + Math.abs(dy)
      lastX = e.clientX
      lastY = e.clientY
      world.position.set(world.position.x + dx, world.position.y + dy)
    }
    const up = (e: PointerEvent) => {
      dragging = false
      if (moved > 6) return
      const box = parent.getBoundingClientRect()
      const wx = (e.clientX - box.left - world.position.x) / world.scale.x
      const wy = (e.clientY - box.top - world.position.y) / world.scale.y
      // Within a few screen pixels of the tap, whatever the zoom.
      const reach = 8 / world.scale.x
      let best: SceneObject | null = null
      let bestGap = reach * reach
      for (const o of shown) {
        const gap = (o.x - wx) * (o.x - wx) + (o.y - wy) * (o.y - wy)
        if (gap <= bestGap) {
          bestGap = gap
          best = o
        }
      }
      setPicked(best)
      if (best) {
        setSpot(null)
        return
      }
      // BARE GROUND IS AN ANSWER TOO: «last swept at …», or «never looked».
      const size = scene?.coverage.cell || 25
      const cx = Math.floor(wx / size)
      const cy = Math.floor(wy / size)
      const found = cells.find((c) => c.cx === cx && c.cy === cy) || null
      setSpot({ x: Math.round(wx), y: Math.round(wy), cell: found })
    }
    const wheel = (e: WheelEvent) => {
      e.preventDefault()
      const box = parent.getBoundingClientRect()
      const px = e.clientX - box.left
      const py = e.clientY - box.top
      const step = e.deltaY < 0 ? 1.2 : 1 / 1.2
      const was = world.scale.x
      const now = Math.min(40, Math.max(0.02, was * step))
      const k = now / was
      world.position.set(px - (px - world.position.x) * k, py - (py - world.position.y) * k)
      world.scale.set(now)
    }
    const leave = () => {
      dragging = false
    }

    parent.addEventListener('pointerdown', down)
    parent.addEventListener('pointermove', move)
    parent.addEventListener('pointerup', up)
    parent.addEventListener('pointerleave', leave)
    parent.addEventListener('wheel', wheel, { passive: false })
    return () => {
      parent.removeEventListener('pointerdown', down)
      parent.removeEventListener('pointermove', move)
      parent.removeEventListener('pointerup', up)
      parent.removeEventListener('pointerleave', leave)
      parent.removeEventListener('wheel', wheel)
    }
  }, [shown, cells, scene, ready])

  const counts = scene?.counts || {}
  const hidden = Object.values(scene?.hidden || {}).reduce((a, b) => a + (b || 0), 0)
  const oldest = Math.max(
    ...Object.values(scene?.ages || {}).map((a) => (a === null || a === undefined ? 0 : a)),
    0,
  )

  return (
    <div className="worldmap">
      {/* THE TWO PICTURES (#2018). «Наша модель» is everything the panel has gathered;
          «Экран клиента» is what the client is holding around its camera right now, read
          only while this view is on — switching back to the model ends the reading. */}
      <div className="chips">
        <button className={'chip' + (mode === 'model' ? ' on' : '')} onClick={() => setMode('model')}>
          {t('worldview.mode.model')}
        </button>
        <button className={'chip' + (mode === 'live' ? ' on' : '')} onClick={() => setMode('live')}>
          {t('worldview.mode.live')}
        </button>
      </div>

      <div className="row">
        <button className="go" disabled={busy} onClick={() => void load()}>
          {t('worldview.map.refresh')}
        </button>
        <span className="muted small">
          {t('worldview.map.age')}{' '}
          {mode === 'live'
            ? live && (live.age ?? -1) >= 0
              ? ageText(live.age)
              : t('worldview.live.never')
            : ageText(scene ? oldest : null)}
        </span>
        {mode === 'live' && live?.reading ? (
          <span className="muted small">{t('worldview.live.reading')}</span>
        ) : null}
        {hidden ? <span className="muted small">{t('worldview.map.hidden', { n: hidden })}</span> : null}
      </div>

      {(scene?.servers || []).length > 1 ? (
        <div className="chips">
          <button className={'chip' + (server === 'all' ? ' on' : '')} onClick={() => setServer('all')}>
            {t('worldview.map.all_servers')}
          </button>
          {(scene?.servers || []).map((s) => (
            <button key={s} className={'chip' + (server === s ? ' on' : '')} onClick={() => setServer(s)}>
              {s}
            </button>
          ))}
        </div>
      ) : null}

      <div className="worldmap-canvas" ref={host}>
        {!pixi ? <p className="muted small worldmap-wait">{t('worldview.map.loading')}</p> : null}
      </div>

      <div className="chips">
        <button className={'chip' + (ground ? ' on' : '')} onClick={() => setGround((was) => !was)}>
          <span className="swatch" style={{ background: css(SWEPT_FRESH) }} />
          {t('worldview.map.ground')}
          <span className="count">{cells.length}</span>
        </button>
        {KINDS.map((kind) => (
          <button
            key={kind.id}
            className={'chip' + (off.has(kind.id) ? '' : ' on')}
            onClick={() =>
              setOff((was) => {
                const next = new Set(was)
                if (next.has(kind.id)) next.delete(kind.id)
                else next.add(kind.id)
                return next
              })
            }
          >
            <span className="swatch" style={{ background: css(kind.colour) }} />
            {kindWord(kind.id)}
            <span className="count">{counts[kind.id] || 0}</span>
          </button>
        ))}
      </div>

      {failed ? <p className="muted">{t('worldview.map.failed')}</p> : null}
      {mode === 'live' && live && live.scene !== 'world' ? (
        <p className="muted">{t('worldview.live.empty')}</p>
      ) : null}
      {!failed && scene && !scene.objects.length && !scene.coverage.cells.length ? (
        <p className="muted">{t('worldview.map.empty')}</p>
      ) : null}

      {picked ? (
        <div className="card">
          <div className="head">
            <span className="swatch" style={{ background: css(COLOUR[picked.k] || 0x888888) }} />
            {kindWord(picked.k)}
          </div>
          <div className="kv">
            <span className="k">{t('worldview.map.place')}</span>
            <span className="v">
              {picked.x}, {picked.y}
              {picked.s === undefined ? '' : ' · ' + picked.s}
            </span>
          </div>
          {picked.l === undefined ? null : (
            <div className="kv">
              <span className="k">{t('worldview.map.level')}</span>
              <span className="v">{picked.l}</span>
            </div>
          )}
          {picked.n ? (
            <div className="kv">
              <span className="k">{t('worldview.map.name')}</span>
              <span className="v">{picked.n}</span>
            </div>
          ) : null}
          {picked.d ? (
            <div className="kv">
              <span className="k">{t('worldview.map.detail')}</span>
              <span className="v">{picked.d}</span>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* BARE GROUND, WHICH IS THE OTHER HALF OF THE COMPARISON: was there nothing
          there, or have we never been there? */}
      {!picked && spot ? (
        <div className="card">
          <div className="head">{t('worldview.map.spot')}</div>
          <div className="kv">
            <span className="k">{t('worldview.map.place')}</span>
            <span className="v">
              {spot.x}, {spot.y}
            </span>
          </div>
          <div className="kv">
            <span className="k">{t('worldview.map.swept')}</span>
            <span className="v">
              {spot.cell ? ageText(scene ? scene.at - spot.cell.t : null) : t('worldview.map.never_swept')}
            </span>
          </div>
          {spot.cell ? (
            <div className="kv">
              <span className="k">{t('worldview.map.height')}</span>
              <span className="v">{spot.cell.v}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
