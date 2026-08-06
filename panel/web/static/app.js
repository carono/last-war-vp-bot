/* The remote control, in about three hundred lines of plain browser JavaScript.
 *
 * It draws four things and presses four: the profile's state, its errands, its
 * scenarios and its log; a timer's switch, a timer's «run now», a scenario's «run» and
 * the client's own life — start it, close it, put it back. Every one of those is one
 * request to panel/web/api.py, which is one call onto the runtime — there is no logic
 * here that the panel does not already have, and none may be added: an ability is a
 * scenario and this plays it (CLAUDE.md).
 *
 * NOT ONE WORD IS WRITTEN IN THIS FILE. `T(key)` looks the words up in the table
 * /api/i18n hands over, which IS panel/locales — so the phone speaks the language the
 * panel is set to, and a key added for the window is on the phone in the same commit.
 */
'use strict';

const $ = (id) => document.getElementById(id);

const POLL_MS = 2500;          // how often a visible page asks for state and log
const SLOW_MS = 15000;         // …and when it is in a pocket, hidden
const TOAST_MS = 3000;

let WORDS = {};                // the locale table, straight off /api/i18n
let VIEW = 'state';
let LOG_AT = 0;                // the newest log line already drawn
let TIMER_ROWS = [];
let ACTIONS = [];
let RUNNING = '';              // the scenario the panel is playing, off /api/state
let PROFILE = '';              // which account is being looked at ('' = the server's own)
let SCREENS = [];              // the tabs of this profile that have a phone screen
let SCREEN = null;             // the one being looked at, or null
let SCREEN_NOW = 0;            // the PANEL's clock when the screen was read
let NOTIFY = false;
let POLLING = null;

/* -- words ---------------------------------------------------------------- */

function T(key, fmt) {
  let text = WORDS[key];
  if (text === undefined) return key;      // the same fallback the window makes
  if (fmt) {
    for (const name of Object.keys(fmt)) {
      text = text.split('{' + name + '}').join(String(fmt[name]));
    }
  }
  return text;
}

function paintWords(root) {
  for (const node of (root || document).querySelectorAll('[data-i18n]')) {
    node.textContent = T(node.dataset.i18n);
  }
  for (const node of (root || document).querySelectorAll('[data-i18n-placeholder]')) {
    node.placeholder = T(node.dataset.i18nPlaceholder);
  }
  document.title = T('web.ui.title');
}

/* -- talking to the panel -------------------------------------------------- */

/* WHICH ACCOUNT travels on every single request. A window may have two profiles open
 * and they are two different clients, two schedules and two logs — a page that asked
 * without saying which would be showing one of them and implying the other. */
function withProfile(path) {
  if (!PROFILE) return path;
  return path + (path.includes('?') ? '&' : '?') + 'profile=' + encodeURIComponent(PROFILE);
}

async function get(path) {
  const answer = await fetch(withProfile(path), { headers: { 'Accept': 'application/json' } });
  if (answer.status === 401) { showLogin(); throw new Error('unauthorised'); }
  if (!answer.ok) throw new Error('http ' + answer.status);
  return answer.json();
}

async function post(path, body) {
  const answer = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.assign({ profile: PROFILE }, body || {}))
  });
  if (answer.status === 401) { showLogin(); throw new Error('unauthorised'); }
  return answer.json();
}

/* -- time ------------------------------------------------------------------ */

function span(seconds) {
  const n = Math.max(0, Math.round(seconds));
  if (n < 60) return T('web.ui.unit.sec', { n: n });
  if (n < 3600) return T('web.ui.unit.min', { n: Math.round(n / 60) });
  if (n < 86400) return T('web.ui.unit.hour', { n: Math.round(n / 3600) });
  return T('web.ui.unit.day', { n: Math.round(n / 86400) });
}

/* `now` is the panel's clock, not the phone's: a tablet whose time is a minute out
 * would otherwise report every errand as overdue. */
function when(stamp, now) {
  if (!stamp) return '';
  const delta = stamp - now;
  if (Math.abs(delta) < 30) return T('web.ui.now');
  return delta > 0 ? T('web.ui.in', { span: span(delta) })
                   : T('web.ui.ago', { span: span(-delta) });
}

/* -- the state page -------------------------------------------------------- */

/* The four link states the panel can report, in the phone's two vocabularies: the word
 * on the pill, and the colour it is worn in. Same four ids as
 * panel/runtime/game_process.py and the same meaning of green — connected, and nothing
 * else. */
const LINK_WORDS = {
  online: 'web.ui.link.online',
  lost: 'web.ui.link.lost',
  unknown: 'web.ui.link.unknown',
  offline: 'web.ui.off',
};
const LINK_PILLS = { online: 'ok', lost: 'off', unknown: 'warn', offline: 'off' };

function paintState(state) {
  if ($('profile-pick').hidden) $('profile').textContent = state.profile;
  // The scenario being played right now, by NAME — the id, not the sentence, because
  // the sentence is in whatever language the panel is set to (panel/web/api.py).
  const wasRunning = RUNNING;
  RUNNING = (state.activity && state.activity.name) || '';
  if (RUNNING !== wasRunning && VIEW === 'actions') paintActions();

  /* The LINK, not the process. A client that has lost the server keeps its window and
   * its pid, so «работает» was green over an account that had been doing nothing since
   * the small hours; only an established connection is green now. Amber is «не видно» —
   * a second account's sockets cannot be read from here, which is normal and not a
   * fault (panel/runtime/game_process.py). An old panel that sends no `link` still
   * gets the running/not-running pair it always did. */
  const link = state.game.link || (state.game.running ? 'unknown' : 'offline');
  const game = $('game-dot');
  game.textContent = T(LINK_WORDS[link] || 'web.ui.off');
  game.className = 'pill ' + (LINK_PILLS[link] || 'off');
  $('game-text').textContent = state.game.text || '';
  paintGameControls(state.game.controls || []);

  const daemon = $('daemon-dot');
  daemon.textContent = state.daemon.up ? T('web.ui.on') : T('web.ui.off');
  daemon.className = 'pill ' + (state.daemon.up ? 'ok' : 'off');
  $('daemon-text').textContent = T('web.ui.port', { port: state.daemon.port });

  const busy = $('busy-dot');
  const working = !!state.activity || state.daemon.busy;
  busy.textContent = working ? T('web.ui.busy') : T('web.ui.idle');
  busy.className = 'pill ' + (working ? 'warn' : 'ok');
  $('activity').textContent = state.activity ? state.activity.text
                                             : T('web.ui.nothing');

  const on = $('timers-on');
  on.textContent = T('web.ui.timers.count', { count: state.timers.on });
  on.className = 'pill ' + (state.timers.on ? 'ok' : '');
  $('timers-next').textContent = state.timers.next
    ? T('web.ui.timers.next', { name: state.timers.next_name,
                                when: when(state.timers.next, state.time) })
    : T('web.ui.timers.none');
}

/* The client's life: start it, close it, put it back — the same three the window has
 * (panel/runtime/game_control.py). Everything about them comes off /api/state: the word
 * on each, the question it asks first, and whether it applies to the client as it is
 * right now. Nothing is decided here — a phone that worked out for itself when «Стоп»
 * makes sense is a phone that will one day disagree with the window about it.
 *
 * Rebuilt only when the row actually changes, so a button does not vanish from under a
 * thumb every 2.5 seconds when the poll comes back saying the same thing. */
let GAME_ROW = '';

function paintGameControls(controls) {
  const stamp = JSON.stringify(controls);
  if (stamp === GAME_ROW) return;
  GAME_ROW = stamp;
  const box = $('game-controls');
  box.textContent = '';
  for (const control of controls) {
    const button = document.createElement('button');
    button.className = 'go' + (control.running ? ' running' : '');
    button.textContent = T(control.label);
    button.disabled = !control.enabled || !!control.running;
    button.addEventListener('click', () => pressGame(control, button));
    box.appendChild(button);
  }
}

async function pressGame(control, button) {
  // The question is the panel's own words, asked by the browser: closing a client or
  // replacing one is a minute of an account's evening if the thumb slipped. `confirm`
  // rather than something drawn here — it is the one dialog that is already the right
  // size for a thumb on every phone, and it cannot be mis-tapped through.
  if (control.confirm && !window.confirm(T(control.confirm))) return;
  button.disabled = true;
  try {
    const answer = await post('/api/game', { action: control.id });
    if (answer.ok) toast(T('web.ui.started', { name: T(control.label) }));
    else if (answer.unavailable) toast(T('web.ui.game.gone'));
    else toast(T('web.ui.refused'));
    // Repaint at once rather than at the next poll: a restart takes half a minute and
    // the person needs to see it took.
    GAME_ROW = '';
    tick();
  } finally { button.disabled = false; }
}

/* -- which account ---------------------------------------------------------- */

/* One profile and the header is a name; two and it is a selector. Rebuilt only when the
 * set of open profiles actually changes, so the picker does not close under a thumb
 * every time the poll comes back. */
function paintProfiles(data) {
  const names = data.profiles || [];
  const pick = $('profile-pick');
  const same = pick.options.length === names.length
    && names.every((n, i) => pick.options[i].value === n);
  if (!same) {
    pick.textContent = '';
    for (const name of names) {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      pick.appendChild(option);
    }
  }
  if (!PROFILE || !names.includes(PROFILE)) {
    // Start on the account the WINDOW is showing, and fall back to it if the one being
    // looked at was closed at the machine.
    PROFILE = names.includes(data.showing) ? data.showing : (names[0] || '');
  }
  pick.value = PROFILE;
  const many = names.length > 1;
  pick.hidden = !many;
  $('profile').hidden = many;
}

async function switchProfile(name) {
  PROFILE = name;
  // Another account is another log with its own numbering, another scenario list (the
  // titles follow that profile's language) and another everything.
  LOG_AT = 0;
  ACTIONS = [];
  SCREENS = [];
  SCREEN = null;
  RUNNING = '';
  $('log-list').textContent = '';
  await tick();
  if (VIEW === 'actions') refreshActions();
  if (VIEW === 'timers') refreshTimers();
}

/* -- the errands ----------------------------------------------------------- */

function paintTimers(data) {
  TIMER_ROWS = data.timers || [];
  const list = $('timers-list');
  list.textContent = '';
  $('timers-empty').hidden = TIMER_ROWS.length > 0;
  for (const row of TIMER_ROWS) {
    list.appendChild(timerItem(row, data.time));
  }
}

function timerItem(row, now) {
  const item = document.createElement('div');
  item.className = 'item';

  // THE WHOLE ROW IS THE TARGET. A <label> wrapping both means the title toggles the
  // errand as surely as the switch does — 48 px tall and the width of the card, where
  // the drawn control alone was 26 px of fingernail (measured at 360x640).
  const head = document.createElement('label');
  head.className = 'row switch-row';
  const title = document.createElement('span');
  title.className = 'title';
  title.textContent = row.title;
  const box = document.createElement('input');
  box.type = 'checkbox';
  box.checked = row.enabled;
  box.addEventListener('change', async () => {
    box.disabled = true;
    try {
      await post('/api/timers/set', { name: row.name, enabled: box.checked });
      await refreshTimers();
    } finally { box.disabled = false; }
  });
  head.append(title, box);

  const detail = document.createElement('p');
  detail.className = 'muted small';
  const bits = [T('web.ui.every', { span: span(row.interval_sec) })];
  if (row.enabled && row.next !== null && row.next !== undefined) {
    bits.push(T('web.ui.next', { when: when(row.next, now) }));
  }
  if (row.last_state === 'ok') bits.push(T('web.ui.last.ok', { when: when(row.last, now) }));
  else if (row.last_state === 'failed') bits.push(T('web.ui.last.failed', { when: when(row.last, now) }));
  else bits.push(T('web.ui.last.none'));
  // Only after a failure, and only then: the retry is why an hourly errand says
  // «следующий через 4 мин» — the window's own row makes the same substitution in
  // its countdown, and without this the phone shows the answer with no reason.
  if (row.last_state === 'failed' && row.retry_sec) {
    bits.push(T('web.ui.retry', { span: span(row.retry_sec) }));
  }
  detail.textContent = bits.join(' · ');

  const foot = document.createElement('div');
  foot.className = 'foot';
  // Empty and it is not drawn at all (`.pill:empty` in the stylesheet): a pill with no
  // word in it is a grey blob, and it was the first thing the eye found on this screen.
  const mark = document.createElement('span');
  mark.className = 'pill' + (row.queued ? ' warn' : '');
  mark.textContent = row.queued ? T('web.ui.queued') : '';
  const go = document.createElement('button');
  go.className = 'go';
  go.textContent = T('web.ui.run');
  go.addEventListener('click', async () => {
    go.disabled = true;
    try {
      const answer = await post('/api/timers/run', { name: row.name });
      toast(answer.queued ? T('web.ui.started', { name: row.title })
                          : T('web.ui.refused'));
      await refreshTimers();
    } finally { go.disabled = false; }
  });
  foot.append(mark, go);

  item.append(head, detail, foot);
  return item;
}

/* -- the scenarios --------------------------------------------------------- */

function paintActions() {
  const needle = ($('actions-filter').value || '').toLowerCase();
  const list = $('actions-list');
  list.textContent = '';
  const shown = ACTIONS.filter((a) =>
    !needle || a.title.toLowerCase().includes(needle) || a.name.includes(needle));
  $('actions-empty').hidden = shown.length > 0;
  for (const action of shown) {
    const item = document.createElement('div');
    item.className = 'item act' + (action.name === RUNNING ? ' running' : '');
    const title = document.createElement('div');
    title.className = 'title';
    title.textContent = action.title;
    const foot = document.createElement('div');
    foot.className = 'foot';
    const name = document.createElement('span');
    name.className = 'muted small';
    name.textContent = action.name;
    const go = document.createElement('button');
    go.className = 'go';
    go.textContent = T('web.ui.run');
    go.addEventListener('click', async () => {
      go.disabled = true;
      try {
        const answer = await post('/api/actions/run', { name: action.name });
        toast(answer.ok ? T('web.ui.started', { name: action.title })
                        : T('web.ui.refused'));
        if (answer.ok) tick();          // show the running mark now, not in 2.5 s
      } finally { go.disabled = false; }
    });
    foot.append(name, go);
    item.append(title, foot);
    list.appendChild(item);
  }
}

/* -- the panel's other tabs, drawn by one renderer -------------------------- */

/* «Ещё»: the list of screens this profile's tabs offer. A tab switched off in the
 * profile is not built and therefore not here — the phone shows what this profile HAS,
 * exactly as the window does. */
function paintMore() {
  const list = $('more-list');
  list.textContent = '';
  $('more-empty').hidden = SCREENS.length > 0;
  for (const screen of SCREENS) {
    const item = document.createElement('button');
    item.className = 'item act row';
    item.style.width = '100%';
    item.textContent = T(screen.title);
    item.addEventListener('click', () => openScreen(screen.id));
    list.appendChild(item);
  }
}

async function refreshScreens() {
  try {
    SCREENS = (await get('/api/screens')).screens || [];
    paintMore();
  } catch (err) { /* the tick says so */ }
}

async function openScreen(id) {
  SCREEN = id;
  showView('screen');
  await drawScreen();
}

async function drawScreen() {
  if (!SCREEN) return;
  let view;
  try {
    view = await get('/api/screen?id=' + encodeURIComponent(SCREEN));
  } catch (err) { return; }
  SCREEN_NOW = view.now || 0;
  $('screen-title').textContent = T(view.title || '');
  const body = $('screen-body');
  body.textContent = '';
  const searchable = (view.cards || []).some((c) => c.search);
  $('screen-filter').hidden = !searchable;
  const needle = searchable ? ($('screen-filter').value || '').toLowerCase() : '';
  for (const card of view.cards || []) {
    // A card titled the same as the screen it is on says it twice — «Альянс» over
    // «Альянс». One card, one heading, and the screen's own is the one that stays.
    const solo = (view.cards || []).length === 1 && card.title === view.title;
    body.appendChild(renderCard(solo ? Object.assign({}, card, { title: null }) : card,
                                needle));
  }
  for (const action of view.actions || []) {
    const button = document.createElement('button');
    button.className = 'go';
    button.style.width = '100%';
    button.textContent = T(action.label);
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        await post('/api/screen/press', { id: SCREEN, action: action.id });
        setTimeout(drawScreen, 900);      // the tab reads on its own thread
      } finally { button.disabled = false; }
    });
    body.appendChild(button);
  }
}

/* ONE renderer for every tab's screen. `title`, `label`, `empty` and `pill` are locale
 * KEYS and go through T(); `head`, `text`, `value`, `detail` and `note` are DATA — a
 * player's name, a count, a date — and are shown as they are (panel/tabs/base.py). */
function renderCard(card, needle) {
  const box = document.createElement('div');
  box.className = 'card';
  if (card.title) {
    const head = document.createElement('div');
    head.className = 'head';
    head.textContent = T(card.title);
    box.appendChild(head);
  }
  if (card.head) {
    const head = document.createElement('div');
    head.className = 'head';
    head.textContent = card.head;
    box.appendChild(head);
  }
  for (const row of card.rows || []) {
    const line = document.createElement('div');
    line.className = 'kv';
    const k = document.createElement('span');
    k.className = 'k';
    k.textContent = T(row.label);
    const v = document.createElement('span');
    v.className = 'v';
    v.textContent = row.value;
    line.append(k, v);
    box.appendChild(line);
  }
  let shown = 0;
  for (const item of card.items || []) {
    const hay = ((item.text || '') + ' ' + (item.detail || '') + ' ' +
                 (item.note || '')).toLowerCase();
    if (needle && !hay.includes(needle)) continue;
    shown += 1;
    box.appendChild(renderItem(item));
  }
  if (!shown && !(card.rows || []).length && card.empty) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = T(card.empty);
    box.appendChild(empty);
  }
  return box;
}

function renderItem(item) {
  const line = document.createElement('div');
  line.className = 'item';
  const head = document.createElement('div');
  head.className = 'row';
  const title = document.createElement('span');
  title.className = 'title';
  // `label` is a KEY (a line that IS one of the panel's own words), `text` is data.
  title.textContent = item.label ? T(item.label) : (item.text || '');
  head.appendChild(title);
  if (item.detail) {
    const detail = document.createElement('span');
    detail.className = 'muted small';
    detail.textContent = item.detail;
    head.appendChild(detail);
  }
  line.appendChild(head);
  if (item.note) {
    const note = document.createElement('p');
    note.className = 'muted small';
    note.textContent = item.note;
    line.appendChild(note);
  }
  /* Facts are a KEY and a value side by side — «Уровень 12 · Слоты 0/3» — so the words
   * stay in the locale table and only the numbers come off the panel. */
  if ((item.facts || []).length || item.until) {
    const facts = document.createElement('p');
    facts.className = 'muted small';
    const bits = (item.facts || []).map((f) => T(f.label) + ' ' + f.value);
    if (item.until) bits.push(when(item.until, SCREEN_NOW || item.until));
    facts.textContent = bits.join(' · ');
    line.appendChild(facts);
  }
  if (item.pill || (item.actions || []).length) {
    const foot = document.createElement('div');
    foot.className = 'foot';
    const pill = document.createElement('span');
    pill.className = 'pill';
    pill.textContent = item.pill ? T(item.pill) : '';
    foot.appendChild(pill);
    for (const action of item.actions || []) {
      const button = document.createElement('button');
      button.className = 'go';
      button.textContent = T(action.label);
      button.addEventListener('click', async () => {
        button.disabled = true;
        try {
          const answer = await post('/api/screen/press',
                                    { id: SCREEN, action: action.id,
                                      args: action.args || {} });
          toast(answer.ok ? T('web.ui.done') : T('web.ui.refused'));
          setTimeout(drawScreen, 900);
        } finally { button.disabled = false; }
      });
      foot.appendChild(button);
    }
    line.appendChild(foot);
  }
  return line;
}

/* -- the log --------------------------------------------------------------- */

function paintLog(data) {
  const list = $('log-list');
  if (data.reset) { list.textContent = ''; }
  for (const line of data.lines || []) {
    const row = document.createElement('div');
    row.className = line.sev || '';
    row.textContent = line.text;
    list.appendChild(row);
    if (line.sev === 'error') announce(line.text);
  }
  while (list.childNodes.length > 400) list.removeChild(list.firstChild);
  $('log-empty').hidden = list.childNodes.length > 0;
  if (VIEW === 'log' && (data.lines || []).length) {
    list.lastChild.scrollIntoView({ block: 'nearest' });
  }
  LOG_AT = data.next;
}

/* A line that says something went wrong reaches the person even with the page in a
 * pocket — that is the whole point of a remote control. Nothing is pushed from the
 * server: the browser's own notification, raised by the poll that found the line. */
function announce(text) {
  if (!NOTIFY || Notification.permission !== 'granted') return;
  try { new Notification(T('web.ui.title'), { body: text, tag: 'lwvp' }); }
  catch (err) { /* a browser that refuses is not a reason to stop polling */ }
}

/* -- the shell ------------------------------------------------------------- */

function toast(text) {
  const node = $('toast');
  node.textContent = text;
  node.hidden = false;
  clearTimeout(toast._at);
  toast._at = setTimeout(() => { node.hidden = true; }, TOAST_MS);
}

function showView(name) {
  VIEW = name;
  for (const section of document.querySelectorAll('.view')) {
    section.hidden = section.id !== 'view-' + name;
  }
  for (const button of document.querySelectorAll('.nav')) {
    button.classList.toggle('on', button.dataset.view === name);
  }
  if (name === 'timers') refreshTimers();
  if (name === 'actions') refreshActions();
  if (name === 'more') refreshScreens();
}

function showLogin() {
  $('app').hidden = true;
  $('login').hidden = false;
  clearInterval(POLLING);
  POLLING = null;
}

async function refreshTimers() {
  try { paintTimers(await get('/api/timers')); } catch (err) { /* the tick says so */ }
}

async function refreshActions() {
  if (ACTIONS.length) return;              // the list only changes when files do
  try {
    ACTIONS = (await get('/api/actions')).actions || [];
    paintActions();
  } catch (err) { /* the tick says so */ }
}

async function tick() {
  try {
    paintProfiles(await get('/api/profiles'));
    paintState(await get('/api/state'));
    paintLog(await get('/api/log?since=' + LOG_AT));
    if (VIEW === 'timers') await refreshTimers();
    $('offline').hidden = true;
  } catch (err) {
    $('offline').hidden = false;
  }
}

function repoll() {
  clearInterval(POLLING);
  POLLING = setInterval(tick, document.hidden ? SLOW_MS : POLL_MS);
}

async function boot() {
  WORDS = (await get('/api/i18n')).words || {};
  paintWords();
  $('login').hidden = true;
  $('app').hidden = false;
  await tick();
  repoll();
}

/* -- wiring ---------------------------------------------------------------- */

document.addEventListener('DOMContentLoaded', async () => {
  for (const button of document.querySelectorAll('.nav')) {
    button.addEventListener('click', () => showView(button.dataset.view));
  }
  $('actions-filter').addEventListener('input', paintActions);
  $('profile-pick').addEventListener('change', (e) => switchProfile(e.target.value));
  $('screen-back').addEventListener('click', () => { SCREEN = null; showView('more'); });
  $('screen-filter').addEventListener('input', drawScreen);
  $('login-go').addEventListener('click', async () => {
    const token = $('login-token').value.trim();
    const answer = await post('/api/login', { token: token });
    if (answer.ok) { location.replace(location.pathname); }
    else { $('login-bad').hidden = false; }
  });
  $('login-token').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') $('login-go').click();
  });
  $('notify').addEventListener('change', async (e) => {
    NOTIFY = e.target.checked;
    if (NOTIFY && 'Notification' in window && Notification.permission !== 'granted') {
      NOTIFY = (await Notification.requestPermission()) === 'granted';
      e.target.checked = NOTIFY;
    }
  });
  document.addEventListener('visibilitychange', () => {
    if (POLLING) { repoll(); if (!document.hidden) tick(); }
  });

  const ping = await (await fetch('/api/ping')).json();
  if (ping.authorised) {
    boot();
  } else {
    // The locale table answers without a token (panel/web/server.py, PUBLIC), so the
    // login box is in the panel's language rather than in locale keys.
    try { WORDS = (await (await fetch('/api/i18n')).json()).words || {}; } catch (e) {}
    paintWords();
    $('login').hidden = false;
  }
});
