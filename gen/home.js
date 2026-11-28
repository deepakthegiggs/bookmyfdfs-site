/* FDFS home (redesign r1, site v2): search as you type, "My cards" with exact card products (L2, handoff 009 and the
   personalised-discovery review D1-D5), live chip counts, filter state in the URL and an answer that follows the chosen
   day and cards. It reads only what the page already shows; nothing is sent anywhere. "My cards" holds product IDs in
   localStorage (fdfs.cards.v1) on this device; they never go in a URL, a share link or analytics. The generator prepends
   FDFS_BANKS {id: 'Name|alias two_words'} and FDFS_FEED {rows: {offer id: raw fields}, freshness_policy?, issuers?}.
   Without this script the page still works: the full list, CSS radio filters, and the static answer. */
(function () {
var d = document, L = location, BK = FDFS_BANKS, KEY = 'fdfs.cards.v1', FEED = window.FDFS_FEED || {rows: {}},
  DK = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'],
  DF = 'Sunday Monday Tuesday Wednesday Thursday Friday Saturday'.split(' '),
  MF = 'January February March April May June July August September October November December'.split(' '),
  qn = /[?&]fdfs_now=(\d+)/.exec(L.search), NOW = qn ? +qn[1] : Date.now(),
  T0 = new Date(NOW + 198e5), TK = DK[T0.getUTCDay()],
  G = ['bank', 'app', 'type', 'day'],
  TL = {card: 'Cards', upi: 'UPI & wallets', direct: 'Direct deals', membership: 'Memberships'},
  AL = {bms: 'BookMyShow', district: 'District', cinema: 'Cinemas'};
function $(s, r) { return (r || d).querySelector(s); }
function $$(s, r) { return [].slice.call((r || d).querySelectorAll(s)); }
function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return '&#' + c.charCodeAt(0) + ';'; }); }
function norm(s) {
  return ' ' + String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/\s*\+\s*/g, '+').replace(/[^a-z0-9+]+/g, ' ') + ' ';
}
function rupees(n) { return '₹' + n.toLocaleString('en-IN'); }

function slug(s) { return String(s).toLowerCase().normalize('NFD').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }

/* ---- THE adapter (009 A1-A5): the agreed contract fields when the feed has them, else the agreed fallbacks ---- */
var POL = {fresh_hours: 48, short_campaign_fresh_hours: 24, short_campaign_days: 14, hide_after_days: 7}, FO = ['fresh', 'needs_recheck', 'unconfirmed'];
for (var pk in FEED.freshness_policy || {}) POL[pk] = FEED.freshness_policy[pk];
function adapt(el) {
  var r = FEED.rows[el.id] || {}, bank = el.dataset.bank, va = el.dataset.validTo, vs = r.card_variants || [], sc = r.variants_scope || null, iss = r.issuer || '',
    net = r.network && vs.join(' ').toLowerCase().indexOf(r.network.toLowerCase()) < 0 ? ' ' + r.network : '',
    pr = r.card_products || (sc === 'listed' ? vs.map(function (v) {
      return {id: bank + ':' + slug(v), label: iss + ' ' + (v === v.toLowerCase() ? v.replace(/\b\w/g, function (c) { return c.toUpperCase(); }) : v) + net};
    }) : []), t = Date.parse(el.dataset.checked), age = NOW - t,
    sh = r.valid_from && va && (Date.parse(va) - Date.parse(r.valid_from)) / 864e5 + 1 < POL.short_campaign_days,
    f = !t ? 2 : age <= (sh ? POL.short_campaign_fresh_hours : POL.fresh_hours) * 36e5 ? 0 : age <= POL.hide_after_days * 864e5 ? 1 : 2,
    bogo = r.min_tickets == null && r.kind === 'bogo';
  return {sc: sc, iss: iss, pr: pr, ids: pr.reduce(function (a, p) { return a.concat([p.id], p.aliases || []); }, []),
    req: 'requires_card' in r ? r.requires_card : true,                       /* A3: unknown = card-bound */
    min: bogo ? 2 : r.min_tickets == null ? null : r.min_tickets,            /* A4: BOGO needs 2 by definition */
    max: r.max_benefit_per_booking || null, basis: r.day_basis || null,
    f: FO[Math.max(f, FO.indexOf(r.freshness))], ago: Math.max(1, Math.floor(age / 864e5))}; /* A1: the stricter of computed and published */
}

/* ---- what each card is (checked or spotted), read from the page ---- */
var items = $$('#offers .offer, .spot').map(function (el) {
  var v = el.classList.contains('offer'), ds = el.dataset, days = (ds.days || '').split(' ').filter(Boolean),
    t = $$('.o-head,.o-value,.sp-h,.o-chips,.sp-plat,code', el).map(function (x) { return x.textContent; }).join(' '),
    c = /₹([\d,]+)/.exec(($('.o-cap', el) || {}).textContent || '');
  if (/2nd ticket free|buy ?(1|one) get ?(1|one)|bogo|1 ticket off/i.test(t)) t += ' bogo free';
  return {el: el, v: v, type: ds.type, app: ds.app, bank: ds.bank, code: !!$('code', el), t: norm(t),
    days: !days.length || days[0] === 'any' ? null : days, cap: c ? +c[1].replace(/,/g, '') : 0,
    who: v ? $('.o-who', el).textContent : '', r: v ? adapt(el) : null};
});
/* the pickable cards: issuers with a checked card offer, each with its exact products (A2) */
var ISS = {}, PL = {};
items.forEach(function (it) {
  if (!it.v || it.r.req === false || it.bank === 'none') return;
  var x = ISS[it.bank] || (ISS[it.bank] = {pr: [], all: 0});
  if (it.r.sc === 'all') x.all = 1;
  it.r.pr.forEach(function (p) {
    if (!PL[p.id]) { PL[p.id] = p.label; x.pr.push(p.id); }
    (p.aliases || []).forEach(function (a) { PL[a] = '=' + p.id; });
  });
});
(FEED.issuers || []).forEach(function (i) { if (ISS[i.id]) ISS[i.id].label = i.label; });
/* needs_recheck (A1, D4): said on the card, never the hero's top pick */
items.forEach(function (it) {
  var p = it.v && $('.o-stale', it.el);
  if (p && it.r.f === 'needs_recheck' && p.hidden) {
    p.textContent = 'Checked ' + it.r.ago + ' day' + (it.r.ago === 1 ? '' : 's') + ' ago · check terms first';
    p.hidden = false; it.el.classList.add('recheck');
  }
});

/* ---- the search vocabulary: banks, apps, days (English and Hinglish), types, codes ---- */
var V = {}, PH = [];
/* words are space-separated; '_' joins a phrase ("book_my_show") that is matched before splitting into words */
function add(words, f, val) {
  words.split(' ').forEach(function (w) {
    var c = w.replace(/_/g, '');
    if (w.indexOf('_') > 0) PH.push([w.replace(/_/g, ' '), c]);
    V[c] = [f, val];
  });
}
Object.keys(BK).forEach(function (id) { add(id + ' ' + BK[id].split('|')[1], 'bank', id); });
add('bms bookmyshow book_my_show bookmy my_show', 'app', 'bms');
add('district zomato district_app', 'app', 'district');
add('pvr inox pvrinox pvr_inox cinepolis cinema cinemas multiplex theatre theater', 'app', 'cinema');
add('upi wallet wallets gpay googlepay google_pay phonepe paytm amazonpay amazon_pay mobikwik cred bhim', 'type', 'upi');
add('card cards credit debit credit_card debit_card creditcard debitcard', 'type', 'card');
add('pass passes membership memberships passport subscription', 'type', 'membership');
add('code codes coupon coupons promo promocode promo_code coupon_code voucher', 'code', 1);
add('mon monday somvar somwar', 'day', 'mon');
add('tue tues tuesday mangal mangalvar mangalwar', 'day', 'tue');
add('wed weds wednesday budh budhvar budhwar', 'day', 'wed');
add('thu thur thurs thursday guru guruvar guruwar', 'day', 'thu');
add('fri friday shukra shukravar shukrawar', 'day', 'fri');
add('sat saturday shani shanivar shaniwar', 'day', 'sat');
add('sun sunday ravi ravivar raviwar itvar itwar', 'day', 'sun');
add('today aaj aj tonight abhi', 'day', TK);
add('tomorrow tmrw tmr kal', 'day', DK[(T0.getUTCDay() + 1) % 7]);
add('parso', 'day', DK[(T0.getUTCDay() + 2) % 7]);
add('weekend wknd this_weekend', 'day', 'sat,sun');
add('bogo b1g1 1+1 bogof buy_1_get_1 buy_one_get_one 2nd_ticket_free second_ticket_free free', 'w', 'bogo');
PH.sort(function (a, b) { return b[0].length - a[0].length; });
var STOP = ' movie movies ticket tickets tix offer offers deal deals discount discounts on for with my the a an and or in ' +
  'of at to i have has got bank banks show shows film films book booking get se ka ke ki ko pe par mein me wala wali ' +
  'wale hai hain kya koi chahiye batao please pls plz any ';

function parse(q) {
  var s = norm(q), P = {bank: [], app: [], type: [], day: [], code: 0, w: [], used: []};
  PH.forEach(function (p) { s = s.split(' ' + p[0] + ' ').join(' ' + p[1] + ' '); });
  s.split(' ').forEach(function (t) {
    if (!t) return;
    var m = V[t] || (t.length > 3 && t.slice(-1) === 's' && V[t.slice(0, -1)]);
    if (m) {
      if (m[0] === 'code') P.code = 1;
      else (m[0] === 'w' ? [m[1]] : String(m[1]).split(',')).forEach(function (x) { if (P[m[0]].indexOf(x) < 0) P[m[0]].push(x); });
      P.used.push({f: m[0], v: m[1], t: t});
    } else if (STOP.indexOf(' ' + t + ' ') < 0) {
      if (P.w.indexOf(t) < 0) P.w.push(t);
      P.used.push({f: 'w', v: t, t: t});
    }
  });
  return P;
}

/* ---- "My cards" (D5): product or issuer IDs only, this device only. Storage blocked: it works until the page closes. ---- */
function okv(v) { return /^[a-z0-9-]{1,24}$/.test(v); }
function known(v) {
  var a = PL[v];
  v = a && a[0] === '=' ? a.slice(1) : v;                                    /* A2 aliases: renamed products */
  return ISS[v] || PL[v] ? v : null;                                         /* IDs not in today's feed are dropped */
}
function loadW() {
  try { localStorage.removeItem('fdfs-cards'); } catch (e) {}               /* the bank-only list of round 1 */
  try {
    var v = JSON.parse(localStorage.getItem(KEY) || '[]');
    return Array.isArray(v) ? v.map(known).filter(function (x, i, a) { return x && a.indexOf(x) === i; }).slice(0, 30) : [];
  } catch (e) { stored = 0; return []; }
}
function saveW(a) {
  try { if (a.length) localStorage.setItem(KEY, JSON.stringify(a)); else localStorage.removeItem(KEY); return true; }
  catch (e) { return false; }
}

/* ---- state: chips (S), the parsed search (P), the wallet (W). URL: ?q=&bank=&app=&day=&type= ---- */
var DB = $$('[data-days-filter] button.day'), AB = $('[data-days-filter] .day-all'),
  stored = 1, S = {bank: [], app: [], type: [], day: DB.length ? [TK] : [], n: 0, mode: 'all'}, dayX = 0, W = loadW(), mine = 0, OB = '',
  U = new URLSearchParams(L.search), q = (U.get('q') || '').slice(0, 80), P;
G.forEach(function (g) {
  var v = U.get(g);
  if (v == null) return;
  var a = v.split(',').filter(okv);
  if (g !== 'day') S[g] = a;
  else if (v === 'all') { S.day = []; dayX = 1; }
  else if ((a = a.filter(function (x) { return DK.indexOf(x) >= 0; })).length) { S.day = a; dayX = 1; }
});
if (/^[1-4]$/.test(U.get('tickets'))) S.n = +U.get('tickets');
if (!U.get('bank') && W.length) S.mode = 'mine';

function eff() {
  var e = {code: P.code, w: P.w, mode: W.length || S.mode !== 'mine' ? S.mode : 'all'};
  G.forEach(function (g) { e[g] = P[g].length ? P[g] : S[g]; });
  return e;
}
function picked(b) { return W.filter(function (w) { return w === b || w.indexOf(b + ':') === 0; }); }
function iname(b) { return (ISS[b] && ISS[b].label) || bankName(b); }
function cname(w) { return PL[w] || 'Not sure which ' + iname(w) + ' card'; }
/* one line, most important first (D4): card scope, tickets, freshness, day. [2 match | 1 conditional | 0 no, text] */
function reason(it, e) {
  var r = it.r, R = [], N = [], m = null, ds = it.days, c = S.n;
  if (r.req !== false) {
    var P2 = picked(it.bank);
    if (!P2.length) return [0, ''];
    m = P2.filter(function (w) { return r.ids.indexOf(w) >= 0; })[0];
    if (r.sc === 'listed' && !m) {
      if (P2.indexOf(it.bank) < 0) return [0, ''];
      R.push('Terms list ' + r.pr.map(function (p) { return p.label; }).join(', ') + '. Check yours is one');
    } else if (r.sc !== 'listed' && r.sc !== 'all') R.push('Terms say “select ' + r.iss + ' credit cards”. Check yours is included');
    if (r.req == null) R.push('Terms don’t say if a card is needed');
  }
  if (c) {                                                                     /* D3: a null minimum never passes silently */
    if (r.min == null) R.push('Minimum not stated in terms');
    else if (c < r.min) R.push('Needs ' + r.min + '+ tickets');
    if (c > 2) N.push(r.max ? r.max : it.t.indexOf(' bogo ') >= 0 ? 'Terms don’t say more than 1 ticket is free' : '');
  }
  if (r.f === 'needs_recheck') R.push('Checked ' + r.ago + ' day' + (r.ago === 1 ? '' : 's') + ' ago');
  if (e.day.length && ds && !e.day.some(function (k) { return ds.indexOf(k) >= 0; })) {   /* G5: the day strip */
    var dn = ds.map(function (k) { return DF[DK.indexOf(k)]; }).join(' or a ');
    R.push(r.basis === 'booking' ? 'Book on a ' + dn : r.basis === 'show' ? 'Show on a ' + dn : dn + 's only');
  }
  N = N.filter(Boolean);
  return [R.length ? 1 : 2, (R.length ? R.join(' · ') : r.req === false ? 'No card needed' : 'Matches what you picked' +
    (m ? ': ' + PL[m] : r.sc === 'all' ? ': terms cover all ' + r.iss + ' credit cards' : '')) + (N.length ? ' · ' + N.join(' · ') : '')];
}
function withF(e, g, a) { var o = {}; for (var k in e) o[k] = e[k]; o[g] = a; return o; }
function hit(it, e) {
  if (window.FDFS_X && !FDFS_X.hit(it)) return false;                        /* P3 (decision 151): the Saved view, gen/plan.js */
  var my = e.mode === 'mine' && it.v;
  if (e.mode === 'nocard' && (it.v ? it.r.req !== false : it.type === 'card')) return false;
  if (e.mode === 'mine' && (it.v ? it.r.req === false || !reason(it, e)[0] : !picked(it.bank).length)) return false;
  if (e.bank.length && e.bank.indexOf(it.bank) < 0) return false;
  if (e.app.length && e.app.indexOf(it.app) < 0) return false;
  if (e.type.length && e.type.indexOf(it.type) < 0) return false;
  if (!my && e.day.length && it.days && !e.day.some(function (k) { return it.days.indexOf(k) >= 0; })) return false;
  if (e.code && !it.code) return false;
  return e.w.every(function (w) {
    return it.t.indexOf(' ' + w) >= 0 || (w.length > 3 && w.slice(-1) === 's' && it.t.indexOf(' ' + w.slice(0, -1)) >= 0);
  });
}
function count(e) {
  var n = [0, 0];
  items.forEach(function (it) { if (!it.el.hidden && hit(it, e)) n[it.v ? 0 : 1]++; });
  return n;
}

/* ---- labels ---- */
var chipName = {};
$$('.filters input[name=bank]').forEach(function (r) {
  var l = $('label[for="' + r.id + '"]');
  if (l) chipName[r.value] = l.firstChild.textContent;
});
function bankName(id) { return BK[id] ? BK[id].split('|')[0] : chipName[id] || id.toUpperCase(); }
function dayBtn(k) { return DB.filter(function (b) { return b.dataset.day === k; })[0]; }
function dayName(k) {
  var b = dayBtn(k);
  return b ? $('.d', b).textContent + ' ' + $('.c', b).textContent + ' ' + $('.m', b).textContent : k;
}
function lab(g, v) {
  return g === 'bank' ? bankName(v) : g === 'app' ? AL[v] || v : g === 'type' ? TL[v] || v : g === 'day' ? dayName(v) : v;
}
function tags() {
  var out = [];
  G.forEach(function (g) {
    if (P[g].length) out.push([g, 'q', '', P[g].map(function (v) { return lab(g, v); }).join(' or ')]);
    else if (S[g].length && (g !== 'day' || dayX)) out.push([g, 's', '', S[g].map(function (v) { return lab(g, v); }).join(' or ')]);
  });
  if (S.mode === 'mine' && W.length) out.push(['mine', 's', '', 'My cards: ' + W.map(cname).join(' + ')]);
  if (S.mode === 'nocard') out.push(['mode', 's', '', 'No card needed']);
  if (S.n) out.push(['n', 's', '', S.n + (S.n > 3 ? '+' : '') + ' ticket' + (S.n > 1 ? 's' : '')]);
  if (P.code) out.push(['code', 'q', '', 'Has a code']);
  P.w.forEach(function (w) { out.push(['w', 'q', w, w === 'bogo' ? 'Buy 1 get 1' : '“' + w + '”']); });
  return out;
}
function dropQ(f, v) {
  q = P.used.filter(function (u) { return f === 'w' ? !(u.f === 'w' && u.v === v) : u.f !== f; })
    .map(function (u) { return u.t; }).join(' ');
  inp.value = q;
}
function url(clean) {
  var u = new URLSearchParams(clean ? '' : L.search);
  ['q', 'bank', 'app', 'day', 'type', 'tickets'].forEach(function (k) { u.delete(k); });
  if (q.trim()) u.set('q', q.trim());
  ['bank', 'app', 'type'].forEach(function (g) { if (S[g].length) u.set(g, S[g].join(',')); });
  if (S.n) u.set('tickets', S.n);
  if (dayX) u.set('day', S.day.length ? S.day.join(',') : 'all');
  var s = u.toString();
  return L.pathname + (s ? '?' + s : '') + (clean ? '' : L.hash);
}

/* ---- render: cards, counts on every chip and day, the applied bar, the answer, the URL ---- */
var inp = $('#q'), bar = $('[data-applied]'), cnt = $('[data-count]'), ans = $('#answer .s-a'), ans0 = ans && ans.innerHTML,
  spMeta = $('#spotted .sec-head .meta'), spMeta0 = spMeta && spMeta.textContent, nSp = $$('.spot').length;
var GR = $('#offers .grid'), H1 = mk('h3', 'grp'), H2 = mk('h3', 'grp'), NE = mk('p', 'grp-e');
function mk(t, c) { var x = d.createElement(t); x.className = c; x.hidden = true; if (GR) GR.appendChild(x); return x; }
H2.textContent = 'No card needed';
NE.innerHTML = 'No checked no-card offers right now. UPI, wallet and code deals we’ve only seen on the web are under ' +
  '<a href="#spotted">Spotted, not yet verified</a>.';
H1.style.order = 0; H2.style.order = 4; NE.style.order = 5;
function render(user) {
  P = parse(q);
  mine = S.mode === 'mine' ? 1 : 0;
  var say = $('[data-say]');
  if (say) say.textContent = '';
  var e = eff(), n = [0, 0], tg = tags(), act = tg.length > 0, gr = W.length > 0 || e.mode !== 'all', nc = 0;
  items.forEach(function (it) {
    var ok = !it.el.hidden && hit(it, e);
    it.el.classList.toggle('out', !ok);
    if (ok) n[it.v ? 0 : 1]++;
    if (!it.v) return;
    var w = W.length || S.n ? reason(it, e) : [0, ''], y = $('.o-why', it.el);
    it.w = w;
    if (ok && it.r.req === false) nc++;
    it.el.style.order = !gr ? '' : it.r.req === false ? 5 : w[0] === 2 ? 1 : w[0] === 1 ? 2 : 3;
    if (!y) { y = d.createElement('p'); $('.o-head', it.el).insertAdjacentElement('afterend', y); }
    y.className = 'o-why' + (w[0] === 2 ? ' ok' : '');
    y.textContent = w[1];
    y.hidden = !w[1];
  });
  H1.textContent = e.mode === 'mine' ? 'Matches for your cards' : 'Card offers';
  H1.hidden = !gr || e.mode === 'nocard';
  H2.hidden = !gr || e.mode === 'mine';
  NE.hidden = H2.hidden || nc > 0;
  $$('[data-mode]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.mode === S.mode)); });
  $$('[data-tix]').forEach(function (b) { b.setAttribute('aria-pressed', String(+b.dataset.tix === S.n)); });
  var kept = $('[data-kept]');
  if (kept) { kept.hidden = !W.length || S.mode === 'mine'; kept.textContent = 'Your ' + W.length + ' card' + (W.length > 1 ? 's are' : ' is') + ' kept.'; }
  if (cnt) cnt.textContent = n[0];
  if (spMeta) spMeta.textContent = act ? 'Showing ' + n[1] + ' of ' + nSp + ' spotted' : spMeta0;
  d.body.classList.toggle('f-on', !!q.trim() || act && tg.some(function (t) { return t[0] !== 'day'; }));   /* any search unfolds spotted rows */
  $$('.filters input[type=radio]').forEach(function (r) {
    var g = r.name, c = count(withF(e, g, r.value === 'all' ? [] : [r.value])), l = $('label[for="' + r.id + '"]'),
      ns = $('.ns', l) || l.appendChild(d.createElement('span'));
    ns.className = 'ns';
    $('.n', l).textContent = c[0];
    ns.textContent = c[1] ? '+ ' + c[1] + ' spotted' : '';
    ns.hidden = !c[1];
    l.classList.toggle('z', !c[0] && !c[1]);
    var one = e[g].length === 1 && d.getElementById(g + '-' + e[g][0]);
    r.checked = one ? r.value === e[g][0] : r.value === 'all';
  });
  DB.forEach(function (b) {
    var k = b.dataset.day, c = count(withF(e, 'day', [k]))[0], cap = c ? c + ' offer' + (c > 1 ? 's' : '') : 'No offers';
    $('.n', b).textContent = cap;
    b.classList.toggle('none', !c);
    b.setAttribute('aria-label', b._l + ', ' + (c ? cap : 'no offers'));
    b.setAttribute('aria-pressed', String(e.day.length === 1 && e.day[0] === k));
  });
  if (AB) AB.setAttribute('aria-pressed', String(!e.day.length));
  if (bar) {
    bar.hidden = !act;
    $('[data-ap-l]', bar).textContent = q.trim() ? 'Searching:' : 'Showing:';
    $('[data-ap-c]', bar).innerHTML = tg.map(function (t) {
      return '<button type="button" class="tag-x" data-rm="' + esc(t[0] + '|' + t[1] + '|' + t[2]) + '">' + esc(t[3]) +
        '<span aria-hidden="true"> ✕</span><span class="sr"> (remove)</span></button>';
    }).join('');
  }
  var em = $('.empty');
  if (em) {
    em.hidden = n[0] > 0 || e.mode === 'nocard';
    var why = $('[data-why]'), best = null;
    if (e.day.length) DB.forEach(function (b) {
      var c = count(withF(e, 'day', [b.dataset.day]))[0];
      if (c && (!best || c > best[1])) best = [b.dataset.day, c];
    });
    why.textContent = (n[1] ? n[1] + ' spotted offer' + (n[1] > 1 ? 's' : '') + ' below might apply. They are not verified. ' : '') +
      (best ? 'Or try ' + dayName(best[0]) + ' (' + best[1] + ').' : '');
    why.hidden = !why.textContent;
  }
  var fn = $('[data-fn]'), nf = (e.type.length ? 1 : 0) + (e.bank.length ? 1 : 0) + (S.mode !== 'all' ? 1 : 0);
  if (fn) { fn.textContent = nf; fn.hidden = !nf; }
  var fc = $('[data-fclose]');
  if (fc) fc.textContent = 'Show ' + n[0] + ' offer' + (n[0] === 1 ? '' : 's') + (n[1] ? ' + ' + n[1] + ' spotted' : '');
  hero(e);
  if (user) try { history.replaceState(history.state, '', url()); } catch (x) {}
}

/* the answer box: crawlers and no-JS visitors keep the static sentence; this follows the chosen day and cards */
function hero(e) {
  if (!ans) return;
  var useW = mine && W.length && !S.bank.length && !P.bank.length, dayPick = (dayX || P.day.length) && e.day.length;
  if (!useW && !dayPick) { ans.innerHTML = ans0; return; }
  var live = items.filter(function (it) { return it.v && !it.el.classList.contains('stale') && hit(it, e); }),
    sp = items.filter(function (it) { return !it.v && !it.el.hidden && hit(it, e); }).length,
    full = useW ? live.filter(function (it) { return it.w[0] === 2; }) : live,
    n = full.length, dl = e.day.length ? e.day.map(dayName).join(' or ') : 'any day',
    h = '<strong>' + esc(useW ? 'With your ' + W.map(cname).join(' + ') + ': ' : 'Booking ' + dl + ': ') +
      n + ' checked offer' + (n === 1 ? '' : 's') + (useW ? ' match' + (n === 1 ? 'es' : '') + ' what you picked' : '') + '</strong>' +
      (useW ? ' for ' + esc(dl) + (live.length > n ? ', ' + (live.length - n) + ' more may apply' : '') : '') + '.',
    top = full.filter(function (it) { return it.r.f === 'fresh'; }).sort(function (a, b) { return b.cap - a.cap; })[0];
  if (top && top.cap) h += ' ' + (n > 1 ? 'Highest cap ' : 'Cap ') + rupees(top.cap) + ' (' + esc(top.who) + ').';
  if (sp) h += ' Plus ' + sp + ' spotted, not yet verified.';
  ans.innerHTML = h;
}

/* ---- wiring ---- */
function clearAll() {
  q = ''; inp.value = ''; S = {bank: [], app: [], type: [], day: [], n: 0, mode: 'all'}; dayX = 1; render(1);
  var st = $('[data-say]');
  if (st) st.textContent = ' Choices cleared · showing all offers';                /* G6: said once, in the status line */
}
if (DB.length) {
  DB.forEach(function (b, i) {
    var x = new Date(NOW + 198e5 + i * 864e5), w = x.getUTCDay();
    b.dataset.day = DK[w];
    b.dataset.date = x.toISOString().slice(0, 10);
    $('.d', b).textContent = DF[w].slice(0, 3);
    $('.c', b).textContent = x.getUTCDate();
    $('.m', b).textContent = MF[x.getUTCMonth()].slice(0, 3);
    b._l = DF[w].slice(0, 3) + ' ' + x.getUTCDate() + ' ' + MF[x.getUTCMonth()].slice(0, 3);   /* WCAG 2.5.3: the name starts with the visible text */
    b.disabled = false;
    b.addEventListener('click', function () {
      if (P.day.length) dropQ('day');
      S.day = [b.dataset.day]; dayX = 1; render(1);
    });
  });
  AB.disabled = false;
  AB.addEventListener('click', function () { if (P.day.length) dropQ('day'); S.day = []; dayX = 1; render(1); });
  $('[data-days-filter]').classList.add('days-on');
}
$('[data-find]').hidden = false;
inp.value = q;
inp.placeholder = 'Try: ' + ($('[data-eg]').dataset.eg || 'sat bms');
inp.addEventListener('input', function () { q = inp.value.slice(0, 80); render(1); });
var form = $('#ff');
form.addEventListener('change', function (ev) {
  var r = ev.target, g = r.name;
  if (r.type !== 'radio') return;
  if (P[g] && P[g].length) dropQ(g);
  S[g] = r.value === 'all' ? [] : [r.value];
  if (g === 'bank' && S.mode === 'mine') S.mode = 'all';
  render(1);
});
form.addEventListener('reset', function () { setTimeout(clearAll, 0); });
form.addEventListener('focusin', function (ev) {
  var l = ev.target.id && $('label[for="' + ev.target.id + '"]');
  if (l && l.scrollIntoView) l.scrollIntoView({block: 'nearest', inline: 'nearest'});
});
d.addEventListener('click', function (ev) {
  var t = ev.target.closest('[data-rm],[data-clear],[data-share-view],[data-wopen],[data-wclear],[data-iss],[data-rmc],[data-mode],[data-tix],[data-fbtn],[data-fclose]');
  if (!t) return;
  var ds = t.dataset;
  if (ds.rm) {
    var x = ds.rm.split('|');
    if (x[1] === 'q') dropQ(x[0], x[2]);
    else if (x[0] === 'mine' || x[0] === 'mode') S.mode = 'all';
    else if (x[0] === 'n') S.n = 0;
    else { S[x[0]] = []; if (x[0] === 'day') dayX = 1; }
    render(1);
  } else if ('clear' in ds) clearAll();
  else if ('shareView' in ds) {
    var c = count(withF(eff(), 'mode', S.mode === 'mine' ? 'all' : S.mode)), tl = tags().filter(function (t) { return t[0] !== 'mine'; }).map(function (t) { return t[3]; }).join(' · ');   /* D5: cards never in a share */
    window.open('https://wa.me/?text=' + encodeURIComponent('Movie ticket offers' + (tl ? ' (' + tl + ')' : '') + ': ' + c[0] +
      ' checked' + (c[1] ? ', ' + c[1] + ' spotted (not yet verified)' : '') + '\n' + L.origin + url(1)), '_blank', 'noopener');
  } else if ('wopen' in ds) { mc.hidden = !mc.hidden; drawW(); }
  else if ('wclear' in ds) { W = []; stored = saveW(W); S.mode = 'all'; OB = ''; drawW(); render(1); }
  else if (ds.iss) { OB = OB === ds.iss ? '' : ds.iss; drawW(); }
  else if (ds.rmc) { setW(W.filter(function (w) { return w !== ds.rmc; })); }
  else if (ds.mode) { if (ds.mode === 'mine' && !W.length) mc.hidden = false; S.mode = ds.mode; drawW(); render(1); }
  else if (ds.tix) { S.n = S.n === +ds.tix ? 0 : +ds.tix; render(1); }
  else if ('fbtn' in ds) show($('#fd'));
  else if ('fclose' in ds) { $('#fd').close(); var h2 = $('#h-offers'); h2.tabIndex = -1; h2.focus(); }
});
function show(dl) { if (dl.showModal) dl.showModal(); else dl.setAttribute('open', ''); }

/* ---- the My cards panel (D1): bank chips open that bank's exact cards inline; "Your cards (n)" chips remove with x;
   on <= 650 px a sticky "Show n offers" closes it and moves focus to the results. Never a card number, CVV or photo. ---- */
var wb = $('[data-wallet]'), mc = d.createElement('div');
mc.className = 'mc'; mc.id = 'mc'; mc.hidden = true;
wb.insertAdjacentElement('afterend', mc);
function setW(a) {
  if (a.length && !W.length && S.mode === 'all') S.mode = 'mine';           /* the first card shows its matches */
  W = a; stored = saveW(W);
  if (!W.length && S.mode === 'mine') S.mode = 'all';
  drawW(); render(1);
}
mc.addEventListener('change', function (ev) {
  var c = ev.target;
  if (!c.dataset.pc) return;
  var a = W.filter(function (w) { return w !== c.value; });
  if (c.checked) a.push(c.value);
  setW(a);
});
function chip(attrs, label, cls) { return '<button type="button" class="' + (cls || 'chip') + '" ' + attrs + '>' + label + '</button>'; }
/* F2 (QA 26 Nov): every redraw puts keyboard focus back on the same logical control (its data-* key), or on the
   control now at its place (the neighbour of a chip that went away). Escape closes the panel, focus to "My cards". */
var FK = ['wopen', 'wclear', 'iss', 'rmc', 'mode', 'tix', 'pc'];
function fkey(el) {
  for (var i = 0; i < FK.length; i++) if (el.hasAttribute('data-' + FK[i]))
    return FK[i] === 'pc' ? 'input[data-pc][value="' + el.value + '"]' : '[data-' + FK[i] + (el.getAttribute('data-' + FK[i]) ? '="' + el.getAttribute('data-' + FK[i]) + '"' : '') + ']';
  return null;
}
function drawW() {
  var a = d.activeElement, box = a && (wb.contains(a) ? wb : mc.contains(a) ? mc : null), k = box && fkey(a),
    at = box ? $$('button,input', box).indexOf(a) : -1;
  drawW0();
  if (!box || d.activeElement !== d.body && box.contains(d.activeElement)) return;
  var t = k && $(k, box), L = $$('button,input', box).filter(function (x) { return x.offsetParent !== null; });
  if (!t || t.offsetParent === null) t = L[Math.min(at, L.length - 1)] || $('[data-wopen]');
  if (t) t.focus();
}
d.addEventListener('keydown', function (ev) {
  if (ev.key !== 'Escape' || mc.hidden) return;
  mc.hidden = true; drawW0(); $('[data-wopen]').focus();
});
function drawW0() {
  var n = W.length, ids = Object.keys(ISS).sort(function (a, b) { return iname(a).localeCompare(iname(b)); });
  wb.innerHTML = chip('data-wopen aria-controls="mc" aria-expanded="' + !mc.hidden + '"', n ? 'My cards (' + n + ')' : '+ Add my cards', 'w-add') +
    (n ? chip('data-wclear', 'Forget my cards', 'w-b') : '') +
    (stored ? n ? '' : '<p class="w-h">Saved on this device only.</p>' : '<p class="w-h" data-wnote>We can’t remember your cards on this device.</p>') +
    '<div class="modes" role="group" aria-label="Show">' + [['mine', 'My cards'], ['nocard', 'No card needed'], ['all', 'Everything']].map(function (m) {
      return chip('data-mode="' + m[0] + '" aria-pressed="' + (S.mode === m[0]) + '"', m[1]);
    }).join('') + '</div><p class="w-h" data-kept hidden></p>';
  if (mc.hidden) return;
  var pl = '';
  if (OB === 'other') pl = '<p class="w-p">No checked offers for other banks yet. ' + chip('data-mode="nocard"', 'No card needed', 'w-b') +
    chip('data-mode="all"', 'Browse everything', 'w-b') + '</p>';
  else if (OB) pl = '<fieldset class="wl"><legend class="w-p">Which ' + esc(iname(OB)) + ' card?</legend>' +
    ISS[OB].pr.concat([OB]).map(function (id) {
      return '<label class="wk"><input type="checkbox" data-pc="1" value="' + esc(id) + '"' + (W.indexOf(id) >= 0 ? ' checked' : '') + '><span>' +
        esc(id === OB ? (ISS[OB].all ? 'Any other ' + iname(OB) + ' credit card' : 'Not sure which card?') : PL[id]) + '</span></label>';
    }).join('') + '</fieldset>';
  mc.innerHTML = '<p class="w-p">Pick your bank, then your exact card. Saved on this device only and never sent anywhere. ' +
    'We never ask for card numbers, CVV or photos.</p>' +
    '<p class="mc-l">Your cards (' + n + ')</p><div class="mc-row">' + (n ? W.map(function (w) {
      return chip('data-rmc="' + esc(w) + '"', esc(cname(w)) + '<span aria-hidden="true"> ✕</span><span class="sr"> (remove)</span>', 'tag-x');
    }).join('') : '<span class="w-h">None yet.</span>') + '</div>' +
    '<p class="mc-l">Banks with a checked offer</p><div class="mc-row">' + ids.map(function (b) {
      return chip('data-iss="' + b + '" aria-expanded="' + (OB === b) + '"', esc(iname(b)));
    }).join('') + chip('data-iss="other" aria-expanded="' + (OB === 'other') + '"', 'Other bank') + '</div>' + pl +
    '<p class="mc-l">Tickets in one booking</p><div class="mc-row" role="group" aria-label="Tickets">' + [1, 2, 3, 4].map(function (k) {
      return chip('data-tix="' + k + '" aria-pressed="' + (S.n === k) + '"', k + (k > 3 ? '+' : ''));
    }).join('') + '</div>';
}
drawW();
var fb = $('[data-fbtn]');
if (fb) fb.hidden = false;
render(0);
window.FDFS = {parse: parse, render: function () { render(1); }, state: function () { return {S: S, P: P, W: W, mine: mine, dayX: dayX, q: q, stored: stored}; }};
var st0 = $('[data-status]');
if (st0) st0.insertAdjacentHTML('beforeend', '<span class="sr" data-say></span>');
})();
