/* FDFS site v2 preview (decision 171). One script for every v2 page, copied to /assets/v2.js.
   It reads /v2/data.json (the checked offers, built with the page) and keeps My cards, Saved, the monthly-use counts
   and the movie diary in localStorage on this device. Nothing is sent anywhere, nothing goes in a URL. My cards and
   Saved use the live site's keys so a visitor's picks carry over. Pages accept ?fdfs_now=<ms> for tests.
   Without this script every page still lists every checked offer, with links to its terms. */
(function () {
'use strict';
var d = document, L = location, qn = /[?&]fdfs_now=(\d+)/.exec(L.search), NOW = qn ? +qn[1] : Date.now(),
  TODAY = new Date(NOW + 198e5).toISOString().slice(0, 10),
  DK = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'], DS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
  MS = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(' '),
  K = {cards: 'fdfs.cards.v1', saved: 'fdfs.saved.v1', snap: 'fdfs.v2.snap.v1', used: 'fdfs.v2.used.v1', diary: 'fdfs.v2.diary.v1'},
  mem = {}, DATA = null, BY = {};
function $(s, r) { return (r || d).querySelector(s); }
function $$(s, r) { return [].slice.call((r || d).querySelectorAll(s)); }
function get(k, def) {
  try { var v = localStorage.getItem(k); if (v != null) return JSON.parse(v); } catch (e) {}
  return k in mem ? mem[k] : def;
}
function put(k, v) { mem[k] = v; try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
function del(k) { delete mem[k]; try { localStorage.removeItem(k); } catch (e) {} }
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return '&#' + c.charCodeAt(0) + ';'; }); }
function rs(n) { return '₹' + Math.round(n).toLocaleString('en-IN'); }
function plus(iso, n) { var t = new Date(iso + 'T00:00:00Z'); t.setUTCDate(t.getUTCDate() + n); return t.toISOString().slice(0, 10); }
function wd(iso) { return new Date(iso + 'T00:00:00Z').getUTCDay(); }
function dlabel(iso) { var t = new Date(iso + 'T00:00:00Z'); return (iso === TODAY ? 'Today, ' : '') + DS[t.getUTCDay()] + ' ' + t.getUTCDate() + ' ' + MS[t.getUTCMonth()]; }
function arr(k) { var v = get(k, []); return Array.isArray(v) ? v : []; }

/* ---- pages built before today: hide what has ended, past days and old leads ---- */
$$('.oc[data-end],.sp[data-end]').forEach(function (el) { if (el.dataset.end && el.dataset.end < TODAY) el.hidden = true; });
$$('.sp[data-spotted]').forEach(function (el) { if (NOW - Date.parse(el.dataset.spotted) > 7 * 864e5) el.hidden = true; });
$$('.wd[data-date]').forEach(function (el) { if (el.dataset.date < TODAY) el.parentNode.hidden = true; });
$$('.day[data-date]').forEach(function (el) { if (el.dataset.date < TODAY) el.hidden = true; });

/* ---- matching an offer to the visitor's cards: 1 = fits, 2 = fits if the card is one of the bank's "select" cards ---- */
function wallet() { return arr(K.cards).filter(function (x) { return typeof x === 'string'; }); }
function fits(o, w) {
  if (!o || !w.length) return 0;
  for (var i = 0; i < o.matches.length; i++) {
    var m = o.matches[i];
    if (m.charAt(0) === '*') {
      var b = m.slice(1);
      if (w.some(function (x) { return x === b || x.indexOf(b + ':') === 0; })) return o.scope === 'unstated' ? 2 : 1;
    } else if (w.indexOf(m) > -1) return 1;
  }
  return 0;
}
function usable(o, iso) {
  if (!o.movie || (o.from && iso < o.from) || (o.to && iso > o.to)) return false;
  return !o.days.length || o.days.indexOf('any') > -1 || o.days.indexOf(DK[wd(iso)]) > -1;
}
function best(iso, w) {
  return DATA.offers.filter(function (o) { return usable(o, iso) && (!w.length || fits(o, w)); })
    .sort(function (a, b) { return b.capNum - a.capNum || (a.id < b.id ? -1 : 1); })[0];
}
function capShort(o) { return o.capNum ? 'up to ' + rs(o.capNum) : o.what; }

/* ---- My cards sheet ---- */
var sheet = $('#wallet');
function openWallet() {
  if (!sheet || !DATA) return;
  var w = wallet(), byBank = {}, h = '';
  DATA.cards.forEach(function (c) { (byBank[c.bank] = byBank[c.bank] || []).push(c); });
  Object.keys(byBank).sort().forEach(function (b) {
    h += '<p class="sh-b">' + esc(DATA.banks[b] || b) + '</p>';
    byBank[b].forEach(function (c) {
      h += '<label class="sh-c"><input type="checkbox" value="' + esc(c.id) + '"' + (w.indexOf(c.id) > -1 ? ' checked' : '') + '><span>' + esc(c.label) + '</span></label>';
    });
  });
  $('[data-wl]', sheet).innerHTML = h;
  if (sheet.showModal) sheet.showModal(); else sheet.setAttribute('open', '');
}
if (sheet) sheet.addEventListener('change', function (e) {
  if (e.target.type !== 'checkbox') return;
  var w = wallet().filter(function (x) { return x !== e.target.value; });
  if (e.target.checked) w.push(e.target.value);
  if (w.length) put(K.cards, w); else del(K.cards);
  refresh();
});

/* ---- saving offers; a snapshot of the terms that matter, to flag changes later ---- */
function saved() { return arr(K.saved).filter(function (x) { return typeof x === 'string'; }); }
function snapOf(o) { return {cap: o.cap, to: o.to, days: o.days.join(' '), what: o.what}; }
function toggleSave(id) {
  var s = saved(), sn = get(K.snap, {}) || {}, i = s.indexOf(id);
  if (i > -1) { s.splice(i, 1); delete sn[id]; } else { s.push(id); if (BY[id]) sn[id] = snapOf(BY[id]); }
  if (s.length) put(K.saved, s); else del(K.saved);
  put(K.snap, sn);
  refresh();
}

/* ---- the monthly-use count (resets on the 1st) ---- */
function usedState() {
  var u = get(K.used, null), m = TODAY.slice(0, 7);
  if (!u || u.m !== m || typeof u.c !== 'object') u = {m: m, c: {}};
  return u;
}

/* ---- list pages: filter, sort, search ---- */
var tools = $('[data-tools]'), list = $('#list'), S = {f: 'all', app: '', sort: 'cap', q: ''};
var pf = /[?&]f=([a-z]+)/.exec(L.search);
if (pf && tools && $('[data-f="' + pf[1] + '"]', tools)) S.f = pf[1];
function applyList() {
  if (!tools || !list) return;
  var w = wallet(), s = saved(), words = S.q.toLowerCase().split(/\s+/).filter(Boolean), cards = $$('.oc', list), n = 0, all = 0;
  cards.forEach(function (el) {
    var ds = el.dataset, ended = ds.end && ds.end < TODAY, ok = !ended;
    if (!ended) all++;
    if (ok && S.f === 'mine') ok = fits(BY[ds.id], w) > 0;
    if (ok && S.f === 'saved') ok = s.indexOf(ds.id) > -1;
    if (ok && (S.f === 'bogo' || S.f === 'pct')) ok = ds.kind === S.f;
    if (ok && S.f === 'nospend') ok = ds.spend === '0';
    if (ok && S.f === 'events') ok = ds.movie === '0';
    if (ok && S.f === 'anyday') ok = ds.days === 'any';
    if (ok && S.app) ok = ds.app === S.app;
    if (ok && words.length) ok = words.every(function (x) { return ds.t.indexOf(x) > -1; });
    el.hidden = !ok;
    if (ok) n++;
  });
  var key = {
    cap: function (a, b) { return b.dataset.cap - a.dataset.cap; },
    end: function (a, b) { return (a.dataset.end || '9999') < (b.dataset.end || '9999') ? -1 : (a.dataset.end || '9999') > (b.dataset.end || '9999') ? 1 : 0; },
    checked: function (a, b) { return Date.parse(b.dataset.checked) - Date.parse(a.dataset.checked); },
    bank: function (a, b) { return a.dataset.bank < b.dataset.bank ? -1 : a.dataset.bank > b.dataset.bank ? 1 : b.dataset.cap - a.dataset.cap; }
  }[S.sort];
  cards.sort(function (a, b) { return key(a, b) || (a.dataset.id < b.dataset.id ? -1 : 1); }).forEach(function (el) { list.appendChild(el); });
  $$('[data-f]', tools).forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.f === S.f ? 'true' : 'false'); });
  var msg = n === all ? 'Showing all ' + all + ' checked offers' : 'Showing ' + n + ' of ' + all + ' checked offers';
  if (!n) msg = S.f === 'mine' && !w.length ? 'Add your cards to see the offers they get.' :
    S.f === 'saved' ? 'Nothing saved yet. Tap the heart on an offer.' : 'No checked offer matches. Try another filter.';
  $('[data-count]', tools).textContent = msg;
}
if (tools) {
  tools.addEventListener('click', function (e) {
    var b = e.target.closest('[data-f]');
    if (!b) return;
    S.f = b.dataset.f;
    if (S.f === 'mine' && !wallet().length) openWallet();
    applyList();
  });
  var q = $('#q', tools), ap = $('#app', tools), so = $('#sort', tools);
  q.addEventListener('input', function () { S.q = q.value.trim(); applyList(); });
  if (ap) ap.addEventListener('change', function () { S.app = ap.value; applyList(); });
  so.addEventListener('change', function () { S.sort = so.value; applyList(); });
}

/* ---- the answer ticket and the week strip follow the visitor's cards ---- */
function paintBest(w) {
  var v = $('[data-best]'), ww = $('[data-best-w]');
  if (!v || !ww) return;
  var label = v.previousElementSibling, b = best(TODAY, w), day = TODAY;
  if (!b && w.length) for (var i = 1; i < 7 && !b; i++) { day = plus(TODAY, i); b = best(day, w); }
  if (!b) {
    if (label) label.textContent = 'For your cards';
    v.textContent = 'No checked offer this week';
    ww.innerHTML = 'None of your cards has a checked movie offer in the next 7 days. <a href="/v2/offers/">See every offer</a>.';
    return;
  }
  if (label) label.textContent = (w.length ? 'Best for your cards, ' : 'Best checked offer, ') + (day === TODAY ? 'booking today' : dlabel(day));
  v.innerHTML = '<a href="' + esc(b.page) + '">' + esc(b.what) + ' <span>' + esc(b.cap) + '</span></a>';
  ww.textContent = b.who + ' · ' + b.where + '.' + (b.spend ? ' ' + b.spend + '.' : '') + (fits(b, w) === 2 ? ' Check your card is one of the select cards.' : '');
}
function paintWeek(w) {
  $$('.wd[data-date]').forEach(function (a) {
    var b = best(a.dataset.date, w), c = $('.wd-c', a), n = $('.wd-w', a);
    c.textContent = b ? capShort(b) : 'No offer';
    c.classList.toggle('wd-0', !b);
    n.textContent = b ? b.who : (w.length ? 'Not for your cards' : '');
  });
  $$('[data-wk-lead]').forEach(function (el) {
    el.textContent = w.length ? 'Showing only offers for your cards. Change them with My cards.' : 'The best checked offer for each day. Add your cards to see only yours.';
  });
}

/* ---- My cards page ---- */
function paintMy(w) {
  var mc = $('[data-my-cards]'), sv = $('[data-saved]'), us = $('[data-used]'), sum = $('[data-my-sum]');
  if (!mc) return;
  var lab = {}, nfit = DATA.offers.filter(function (o) { return fits(o, w); }).length;
  DATA.cards.forEach(function (c) { lab[c.id] = c.label; });
  var known = w.filter(function (x) { return lab[x]; });
  mc.innerHTML = known.length ? '<ul>' + known.map(function (x) { return '<li>' + esc(lab[x]) + '</li>'; }).join('') + '</ul><p class="lead">' +
    (nfit ? nfit + ' checked offer' + (nfit > 1 ? 's fit' : ' fits') + ' your cards. <a href="/v2/offers/?f=mine">See them</a>.' : 'No checked offer fits these cards yet.') + '</p>'
    : '<p class="empty">No cards added yet.</p>';
  if (sum) sum.textContent = known.length ? known.length + ' card' + (known.length > 1 ? 's' : '') + ' · ' + nfit + ' checked offer' + (nfit === 1 ? '' : 's') + ' for them' : 'Add your cards and FDFS shows the offers they get.';
  var s = saved(), sn = get(K.snap, {}) || {};
  sv.innerHTML = s.length ? '<ul class="dl">' + s.map(function (id) {
    var o = BY[id], was = sn[id], flag = '';
    if (!o) return '<li><div><b>' + esc(was ? was.what : id) + '</b><span class="flag">No longer listed: it ended or didn\'t pass our latest check.</span></div><button class="lnk" type="button" data-save="' + esc(id) + '">Remove</button></li>';
    if (was) {
      var ch = [];
      if (was.cap !== o.cap) ch.push('cap was ' + was.cap + ', now ' + o.cap);
      if (was.to !== o.to) ch.push('end date was ' + (was.to || 'not stated') + ', now ' + (o.to || 'not stated'));
      if (was.days !== o.days.join(' ')) ch.push('the days changed');
      if (ch.length) flag = '<span class="flag">Changed since you saved it: ' + esc(ch.join('; ')) + '.</span>';
    }
    return '<li><div><a href="' + esc(o.page) + '">' + esc(o.who) + '</a> <span>' + esc(o.what + ' ' + o.cap + ' · ' + o.appName) + '</span>' + flag + '</div>' +
      '<button class="lnk" type="button" data-save="' + esc(id) + '">Remove</button></li>';
  }).join('') + '</ul>' : '<p class="empty">Nothing saved yet. Tap the heart on an offer.</p>';
  var u = usedState(), ids = Object.keys(u.c).filter(function (id) { return u.c[id] > 0 && BY[id]; });
  us.innerHTML = ids.length ? '<ul class="dl">' + ids.map(function (id) {
    var o = BY[id];
    return '<li><a href="' + esc(o.page) + '">' + esc(o.who) + '</a><span>' + u.c[id] + ' of ' + o.monthly + ' used in ' + MS[+TODAY.slice(5, 7) - 1] + '</span></li>';
  }).join('') + '</ul>' : '<p class="empty">Mark an offer as used on its page and it shows here. Counts reset on the 1st.</p>';
  paintDiary();
}
function paintDiary() {
  var box = $('[data-diary-list]');
  if (!box) return;
  var a = arr(K.diary).slice().sort(function (x, y) { return x.date < y.date ? 1 : -1; }), yr = TODAY.slice(0, 4), off = 0, n = 0;
  a.forEach(function (e) { if (String(e.date).slice(0, 4) === yr) { off += +e.off || 0; n++; } });
  box.innerHTML = a.length ? '<ul class="dl">' + a.map(function (e) {
    return '<li><div><b>' + esc(e.movie) + '</b> <span>' + esc(e.date) + ' · paid ' + rs(+e.paid || 0) + (e.off ? ' · ' + rs(+e.off) + ' off' : '') + '</span></div>' +
      '<button class="lnk" type="button" data-dd="' + esc(e.k) + '">Delete</button></li>';
  }).join('') + '</ul><p class="sum">' + n + ' movie' + (n === 1 ? '' : 's') + ' in ' + yr + (off ? ', ' + rs(off) + ' off with offers' : '') + '</p>' : '';
}
var diary = $('[data-diary]');
if (diary) {
  diary.elements.date.value = TODAY;
  diary.addEventListener('submit', function () {
    if (!diary.checkValidity()) { diary.reportValidity(); return; }
    var a = arr(K.diary);
    a.push({k: String(NOW) + a.length, date: diary.elements.date.value, movie: diary.elements.movie.value.slice(0, 60), paid: +diary.elements.paid.value || 0, off: +diary.elements.off.value || 0});
    put(K.diary, a.slice(-500));
    diary.elements.movie.value = ''; diary.elements.paid.value = ''; diary.elements.off.value = '';
    paintDiary();
  });
}

/* ---- booking check: which checked offers allow this booking. No ticket prices and no amounts worked out
   (owner decisions 139 and P3): the cap shown is the terms' own. ---- */
var calc = $('[data-calc]');
function need(o) { return o.min || (o.kind === 'bogo' ? 2 : 1); }
function dayRule(o) {
  if (!o.days.length || o.days.indexOf('any') > -1) return '';
  var names = o.days.map(function (k) { return 'Sundays Mondays Tuesdays Wednesdays Thursdays Fridays Saturdays'.split(' ')[DK.indexOf(k)]; });
  return (o.basis === 'booking' ? 'Book on ' : '') + names.join(' and ') + ' only';
}
function paintCalc(w) {
  if (!calc) return;
  var out = $('[data-calc-out]'), n = +calc.elements.n.value || 2, app = calc.elements.app.value, day = calc.elements.day.value || TODAY, rows = [];
  DATA.offers.forEach(function (o) {
    if ((app && o.app !== app) || !usable(o, day) || n < need(o)) return;
    if (calc.elements.mine.checked && !fits(o, w)) return;
    if (calc.elements.nospend.checked && o.spend) return;
    rows.push(o);
  });
  rows.sort(function (a, b) { return b.capNum - a.capNum || (a.id < b.id ? -1 : 1); });
  out.innerHTML = rows.length ? rows.map(function (o) {
    var x = [dayRule(o), o.spend, o.times].filter(Boolean);
    return '<li><a href="' + esc(o.page) + '">' + esc(o.who) + '</a> on ' + esc(o.appName) + ': <b>' + esc(o.what + ' ' + o.cap) + '</b>' +
      (x.length ? '. ' + esc(x.join('. ')) : '') + (fits(o, w) === 2 ? '. Check your card is one of the select cards' : '') + '</li>';
  }).join('') : '<li>No checked offer fits this booking. ' + (n < 2 ? 'Most need 2 tickets in one booking.' : 'Try another day or app.') + '</li>';
  var lead = calc.parentNode.querySelector('.lead');
  if (lead) lead.textContent = n + ' ticket' + (n > 1 ? 's' : '') + ' booked ' + (day === TODAY ? 'today' : 'on ' + dlabel(day)) +
    (app ? ' on ' + calc.elements.app.options[calc.elements.app.selectedIndex].text : '') + '.';
}
if (calc) {
  var opts = '';
  for (var i = 0; i < 7; i++) { var iso = plus(TODAY, i); opts += '<option value="' + iso + '">' + esc(dlabel(iso)) + '</option>'; }
  calc.elements.day.innerHTML = opts;
  calc.addEventListener('change', function () { paintCalc(wallet()); });
}
/* static pages never say "today": the browser does, for the visitor's own day */
$$('[data-dl]').forEach(function (el) { if (el.parentNode.dataset.date === TODAY) el.innerHTML = 'Today <b>' + (+TODAY.slice(8)) + '</b>'; });
$$('.day[data-date]').forEach(function (el) { var h = $('h3', el); if (h && el.dataset.date === TODAY) h.textContent = dlabel(TODAY); });

/* ---- buttons ---- */
d.addEventListener('click', function (e) {
  var t = e.target.closest('button,[data-wallet]');
  if (!t) return;
  if (t.hasAttribute('data-wallet')) { openWallet(); return; }
  if (t.dataset.save) { toggleSave(t.dataset.save); return; }
  if (t.dataset.dd) { put(K.diary, arr(K.diary).filter(function (x) { return x.k !== t.dataset.dd; })); paintDiary(); return; }
  if (t.dataset.copy) {
    var done = function () { var o = t.textContent; t.textContent = 'Copied'; setTimeout(function () { t.textContent = o; }, 1600); };
    if (navigator.clipboard) navigator.clipboard.writeText(t.dataset.copy).then(done, function () {}); return;
  }
  if (t.hasAttribute('data-ics')) {
    var day = t.dataset.to.replace(/-/g, ''), nx = plus(t.dataset.to, 1).replace(/-/g, ''),
      ics = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//FDFS//bookmyfdfs.in//EN', 'BEGIN:VEVENT', 'UID:' + day + '-' + Math.abs(t.dataset.url.length * 7919) + '@bookmyfdfs.in',
        'DTSTAMP:' + new Date(NOW).toISOString().replace(/[-:]/g, '').slice(0, 15) + 'Z', 'DTSTART;VALUE=DATE:' + day, 'DTEND;VALUE=DATE:' + nx,
        'SUMMARY:' + t.dataset.title.replace(/[,;]/g, ' '), 'URL:' + t.dataset.url, 'END:VEVENT', 'END:VCALENDAR'].join('\r\n'),
      a = d.createElement('a');
    a.href = URL.createObjectURL(new Blob([ics], {type: 'text/calendar'}));
    a.download = 'fdfs-offer.ics'; d.body.appendChild(a); a.click(); a.remove(); return;
  }
  var use = t.closest('[data-use]');
  if (use && (t.hasAttribute('data-use-add') || t.hasAttribute('data-use-undo'))) {
    var u = usedState(), id = use.dataset.use, mx = +use.dataset.max, c = u.c[id] || 0;
    u.c[id] = t.hasAttribute('data-use-add') ? Math.min(mx, c + 1) : Math.max(0, c - 1);
    put(K.used, u); refresh(); return;
  }
  if (t.hasAttribute('data-clear')) {
    if (t.dataset.armed) { [K.cards, K.saved, K.snap, K.used, K.diary].forEach(del); delete t.dataset.armed; t.textContent = 'Cleared'; refresh(); }
    else { t.dataset.armed = '1'; t.textContent = 'Tap again to clear everything'; }
  }
});

/* ---- one repaint for everything that follows the visitor's cards and saves ---- */
function refresh() {
  var w = wallet(), s = saved(), n = w.length;
  $$('[data-wn]').forEach(function (el) { el.textContent = n ? String(n) : ''; });
  $$('[data-save]').forEach(function (b) {
    var on = s.indexOf(b.dataset.save) > -1, l = $('[data-save-l]', b);
    if (b.classList.contains('lnk')) return;
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    if (l) l.textContent = on ? 'Saved' : 'Save';
  });
  if (!DATA) return;
  $$('.oc[data-id]').forEach(function (el) {
    var f = fits(BY[el.dataset.id], w), m = $('.fit', el);
    el.classList.toggle('fits', f > 0);
    if (m) { m.hidden = !f; m.textContent = f === 1 ? 'Fits your cards' : f === 2 ? 'May fit: check your card' : ''; }
  });
  $$('[data-fit]').forEach(function (el) {
    var f = fits(BY[el.dataset.fit], w);
    el.hidden = !n;
    el.textContent = f === 1 ? 'This offer fits one of your cards.' : f === 2 ? 'This may fit your card: the terms say select cards, so check yours is included.' : 'None of your cards is named in this offer.';
  });
  $$('.day[data-date]').forEach(function (el) {
    var rows = $$('li[data-id]', el), shown = 0;
    rows.forEach(function (li) { var ok = !n || fits(BY[li.dataset.id], w) > 0; li.hidden = !ok; if (ok) shown++; });
    var none = $('[data-day-none]', el);
    if (none) none.hidden = !rows.length || shown > 0;
  });
  $$('[data-use]').forEach(function (el) { var u = usedState(); $('[data-use-n]', el).textContent = u.c[el.dataset.use] || 0; });
  paintBest(w); paintWeek(w); paintMy(w); paintCalc(w); applyList();
}

refresh();
fetch('/v2/data.json').then(function (r) { return r.json(); }).then(function (j) {
  DATA = j;
  j.offers.forEach(function (o) { BY[o.id] = o; });
  if (NOW - Date.parse(j.generated) > 2 * 864e5) {
    var pv = $('.pv');
    if (pv) pv.insertAdjacentHTML('beforeend', ' <b>These offers were last updated ' + esc(dlabel(j.generated.slice(0, 10))) + '. Check the terms before you pay.</b>');
  }
  refresh();
}, function () {});
})();
