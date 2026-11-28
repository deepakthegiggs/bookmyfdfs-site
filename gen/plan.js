/* FDFS P3 (decisions 150-157): saved offers, the sort control, the calendar's "today" label, and reflow motion.
   Saved offers are offer IDs only, in localStorage 'fdfs.saved.v1' on this device. They never go in a URL, a share
   link or analytics, and nothing is sent anywhere. Storage blocked: everything works in memory until the page closes.
   A saved ID that is no longer listed stays, marked "No longer listed", with a link to its history page.
   The generator prepends FDFS_PLAN {o: {id: [label, stated cap|null, end|null]}, g: {id: label}}. */
(function () {
var d = document, PL = window.FDFS_PLAN || {o: {}, g: {}}, KEY = 'fdfs.saved.v1', mem = null, ok = 1,
  RM = !window.matchMedia || matchMedia('(prefers-reduced-motion: reduce)').matches,
  qn = /[?&]fdfs_now=(\d+)/.exec(location.search), NOW = qn ? +qn[1] : Date.now(),
  SORT = {recent: ['Most recently checked', 'Sorted by most recent check, then soonest end date. The same rule for every app.'],
    ends: ['Soonest end date', 'The nearest end date in the terms first. Offers with no end date come last.'],
    cap: ['Highest stated cap', 'Highest rupee cap in the terms first. A cap is the most an offer can take off, not what you’ll get. Offers without one come after, marked “Cap not stated”.']};
function $(s, r) { return (r || d).querySelector(s); }
function $$(s, r) { return [].slice.call((r || d).querySelectorAll(s)); }
function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return '&#' + c.charCodeAt(0) + ';'; }); }
function okid(v) { return typeof v === 'string' && /^[a-z0-9-]{1,80}$/.test(v); }

/* ---- storage: IDs only, every access in try/catch ---- */
function load() {
  if (mem) return mem;
  mem = [];
  try {
    var v = JSON.parse(localStorage.getItem(KEY) || '[]');
    if (Array.isArray(v)) v.forEach(function (x) { if (okid(x) && mem.indexOf(x) < 0 && mem.length < 60) mem.push(x); });
  } catch (e) { ok = 0; }
  return mem;
}
function store(a) {
  mem = a;
  try { if (a.length) localStorage.setItem(KEY, JSON.stringify(a)); else localStorage.removeItem(KEY); ok = 1; }
  catch (e) { ok = 0; }
}
function has(id) { return load().indexOf(id) >= 0; }
function name(id) { return (PL.o[id] || [])[0] || PL.g[id] || 'An offer we no longer list'; }
function path(id) { return '/offer/' + id + '/'; }

/* one polite live region per page */
var say = d.createElement('p');
say.className = 'sr'; say.setAttribute('aria-live', 'polite'); say.setAttribute('data-p3-say', '');
d.body.appendChild(say);
function tell(t) { say.textContent = ''; setTimeout(function () { say.textContent = t; }, 30); }

/* ---- reflow motion (FLIP): only without prefers-reduced-motion; never on load, never looping ---- */
function snap() {
  if (RM) return null;
  var m = [];
  $$('#offers .offer, #offers .spot').forEach(function (el) { if (el.offsetParent) m.push([el, el.getBoundingClientRect()]); });
  return m;
}
function later(fn) {                     /* before the next paint; the timer covers a throttled frame (background tab) */
  var k = 0;
  function go() { if (!k) { k = 1; fn(); } }
  requestAnimationFrame(go); setTimeout(go, 16);
}
function play(m, now) {
  if (!m || !d.body.animate) return;
  var was = m.map(function (x) { return x[0]; });
  (now ? function (f) { f(); } : later)(function () {
    m.forEach(function (x) {
      var el = x[0], b = el.getBoundingClientRect(), dx = x[1].left - b.left, dy = x[1].top - b.top;
      if (el.offsetParent && (dx || dy)) el.animate([{transform: 'translate(' + dx + 'px,' + dy + 'px)'}, {transform: 'none'}],
        {duration: 240, easing: 'cubic-bezier(.2,.7,.2,1)'});
    });
    $$('#offers .offer, #offers .spot').forEach(function (el) {
      if (el.offsetParent && was.indexOf(el) < 0) el.animate([{opacity: 0}, {opacity: 1}], {duration: 200, easing: 'ease-out'});
    });
  });
}
/* filters and search belong to home.js: snapshot in the capture phase (before its handlers run), animate after */
['click', 'change', 'input'].forEach(function (t) {
  d.addEventListener(t, function (ev) {
    var x = ev.target;
    if (!x.closest || !x.closest('#offers .filters,#offers .find,#offers .days-wrap,#offers .applied,#fd,#mc,[data-wallet]')) return;
    if (t === 'click' && !x.closest('button,label')) return;
    play(snap());
  }, true);
});

/* ---- Save toggles: injected on checked offer cards (never on Spotted leads); server-rendered on offer pages ---- */
var HEART = '<svg class="ic sv-i" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 13.6S1.8 9.9 1.8 5.7A3.1 3.1 0 0 1 8 4.4a3.1 3.1 0 0 1 6.2 1.3C14.2 9.9 8 13.6 8 13.6z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>';
$$('#offers article.offer').forEach(function (el) {
  if (!PL.o[el.id] || $('[data-sv]', el)) return;
  var h = $('.o-head', el);
  if (!h) return;
  h.insertAdjacentHTML('afterend', '<button type="button" class="sv" data-sv="' + esc(el.id) + '" aria-pressed="false" aria-label="Save ' +
    esc(name(el.id)) + '" title="Save on this device">' + HEART + '</button>');
  el.setAttribute('data-has-sv', '');
});
function paint() {
  $$('[data-sv]').forEach(function (b) {
    var on = has(b.dataset.sv);
    b.setAttribute('aria-pressed', String(on));
    if (b.hasAttribute('data-gone')) b.hidden = !on;
    else b.hidden = false;
    var t = $('.sv-t', b);
    if (t) t.textContent = on ? (b.hasAttribute('data-gone') ? 'Saved · remove' : 'Saved') : 'Save';
  });
  var n = load().length;
  $$('[data-svn]').forEach(function (x) { x.textContent = n; });
  drawPanel();
}
function toggle(id) {
  var a = load().slice(), i = a.indexOf(id), on = i < 0;
  if (on) a.push(id); else a.splice(i, 1);
  store(a);
  $$('[data-sv="' + id + '"]').forEach(function (b) {                       /* the heart pops once; CSS gates it on motion */
    b.classList.toggle('pop', false); void b.offsetWidth; b.classList.toggle('pop', on);
  });
  var m = snap();
  paint();
  if (view) rerender();
  play(m, 1);
  tell((on ? 'Saved: ' : 'Removed from saved: ') + name(id) + '. ' + a.length + ' saved' +
    (ok ? ' on this device.' : ' for this visit only: this browser won’t let us store it.'));
}

/* ---- home: the Saved view and the sort control, inserted just above the offer grid ---- */
var grid = $('#offers .grid'), view = 0, sort = 'recent', bar = null, panel = null, idx = {};
function rerender() { if (window.FDFS && FDFS.render) FDFS.render(); }
if (grid && window.FDFS) {
  $$('article.offer', grid).forEach(function (el, i) { idx[el.id] = i; });
  var s0 = /[?&]sort=(recent|ends|cap)\b/.exec(location.search);
  if (s0) sort = s0[1];
  bar = d.createElement('div');
  bar.className = 'pbar';
  bar.innerHTML = '<button type="button" class="w-add sv-view" data-svview aria-pressed="false" aria-controls="svp">' + HEART +
    '<span>Saved (<span data-svn>0</span>)</span></button>' +
    '<div class="srt"><label for="sort">Sort</label><select id="sort" aria-describedby="sort-h">' +
    Object.keys(SORT).map(function (k) { return '<option value="' + k + '">' + SORT[k][0] + '</option>'; }).join('') +
    '</select></div><p class="srt-h" id="sort-h"></p>';
  panel = d.createElement('div');
  panel.className = 'svp'; panel.id = 'svp'; panel.hidden = true;
  grid.insertAdjacentElement('beforebegin', bar);
  grid.insertAdjacentElement('beforebegin', panel);
  $$('#offers .order-note').forEach(function (p) { p.hidden = true; });   /* the bar's line says the active rule */
  window.FDFS_X = {hit: function (it) { return !view || (it.v && has(it.el.id)); }};
  $('#sort', bar).value = sort;
  $('#sort', bar).addEventListener('change', function (ev) {
    sort = ev.target.value;
    var m = snap();
    order();
    play(m, 1);
    try { var u = new URLSearchParams(location.search); if (sort === 'recent') u.delete('sort'); else u.set('sort', sort);
      var q = u.toString(); history.replaceState(history.state, '', location.pathname + (q ? '?' + q : '') + location.hash); } catch (x) {}
    tell('Sorted by ' + SORT[sort][0].toLowerCase() + '. ' + SORT[sort][1]);
  });
  order();
}
function key(el) {
  var o = PL.o[el.id] || [], i = idx[el.id] || 0;
  if (sort === 'ends') return [o[2] ? 0 : 1, o[2] || '', i];
  if (sort === 'cap') return [o[1] ? 0 : 1, -(o[1] || 0), i];
  return [0, 0, i];
}
function order() {
  if (!grid) return;
  var els = $$('article.offer', grid);
  els.sort(function (a, b) {
    var x = key(a), y = key(b);
    for (var k = 0; k < 3; k++) if (x[k] !== y[k]) return x[k] < y[k] ? -1 : 1;
    return 0;
  }).forEach(function (el) {
    grid.appendChild(el);
    var nc = $('.nocap', el), need = sort === 'cap' && PL.o[el.id] && !PL.o[el.id][1];
    if (need && !nc) $('.o-value', el).insertAdjacentHTML('beforeend', '<span class="nocap">Cap not stated</span>');
    if (!need && nc) nc.remove();
  });
  $('#sort-h', bar).textContent = SORT[sort][1];
}
function drawPanel() {
  if (!panel) return;
  var a = load(), btn = $('[data-svview]', bar);
  btn.setAttribute('aria-pressed', String(!!view));
  btn.setAttribute('aria-expanded', String(!!view));
  panel.hidden = !view;
  d.body.classList.toggle('p3-saved', !!view);
  if (!view) return;
  var live = a.filter(function (id) { return PL.o[id]; }), gone = a.filter(function (id) { return !PL.o[id]; });
  panel.innerHTML = '<p class="svp-h">Saved on this device (' + a.length + ')</p>' +
    (a.length ? '<ul class="svp-l">' + a.map(function (id) {
      var g = !PL.o[id];
      return '<li' + (g ? ' class="gone"' : '') + '>' + (g ? '<span class="svp-g">No longer listed</span> <a href="' + esc(path(id)) + '">' + esc(name(id)) +
        '</a><span class="svp-n"> · see what its terms said</span>' : '<a href="' + esc(path(id)) + '">' + esc(name(id)) + '</a>') +
        '<button type="button" class="w-b svp-x" data-svrm="' + esc(id) + '">Remove<span class="sr"> ' + esc(name(id)) + '</span></button></li>';
    }).join('') + '</ul>' : '<p class="svp-e">Nothing saved yet. Tap the heart on an offer to keep it here.</p>') +
    '<p class="w-h">' + (ok ? 'Saved on this device only. Never sent anywhere.' : 'This browser won’t let us store them: kept for this visit only.') +
    (live.length ? ' The list below shows the ones still listed; your other filters and day still apply.' : '') + '</p>';
}
d.addEventListener('click', function (ev) {
  var t = ev.target.closest && ev.target.closest('[data-sv],[data-svview],[data-svrm]');
  if (!t) return;
  if (t.dataset.sv) toggle(t.dataset.sv);
  else if (t.dataset.svrm) { var nx = t.closest('li'); nx = nx && (nx.nextElementSibling || nx.previousElementSibling);
    var id = nx && $('[data-svrm]', nx) && $('[data-svrm]', nx).dataset.svrm; toggle(t.dataset.svrm);
    var f = id && $('[data-svrm="' + id + '"]', panel); (f || $('[data-svview]', bar)).focus(); }
  else {
    var m = snap();
    view = view ? 0 : 1;
    drawPanel(); rerender(); play(m, 1);
    var n = $('[data-count]');
    tell(view ? 'Showing saved offers: ' + (n ? n.textContent : '0') + ' still listed of ' + load().length + ' saved.' : 'Showing all offers.');
  }
});

/* ---- /calendar/: the server wrote 14 dates from our check, the last 7 out of view. The browser shows the 7 days from
   the visitor's IST today (decision 162), marks today and tomorrow, and says so once our checked week has passed ---- */
var cells = $$('.cal .cl-d');
if (cells.length) {
  var y = new Date(NOW + 198e5).toISOString().slice(0, 10), past = 0, shown = 0;
  cells.forEach(function (c, i) {
    var on = c.dataset.date >= y && shown < 7;
    if (on) shown++;
    c.classList.toggle('cl-x', !on);
    var dt = c.dataset.date, tl = $('.cl-today', c), nx = new Date(Date.parse(y) + 864e5).toISOString().slice(0, 10);
    c.classList.toggle('is-today', dt === y);
    c.classList.toggle('is-past', dt < y);
    if (dt < y && i < 7) past++;
    tl.textContent = dt === y ? 'Today' : dt === nx ? 'Tomorrow' : dt < y ? 'Past' : '';
    tl.hidden = !tl.textContent;
    if (dt === y) c.setAttribute('aria-current', 'date');
  });
  var st = $('[data-cl-stale]');
  if (st) st.hidden = past < 7;
}
paint();
})();
