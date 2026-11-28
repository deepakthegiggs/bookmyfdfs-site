"""Redesign round 1 (home): value-first cards, search as you type, "My cards", live counts, URL state, a reactive
answer, copy states, validity as text, the spotted look, and the filter sheet. Written before the code; the mutants at
the end prove the browser checks bite."""
import gzip
import html
import json
import re
import socket
import subprocess
import sys
import time
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
from test_generator import Base  # noqa: E402
from test_review_s1 import visible  # noqa: E402

BASE = json.loads((ROOT / "tests/fixtures/offers-spotted-base.json").read_text())   # frozen export, 25 Nov 2026
SPOTS = ROOT / "tests/fixtures/spotted-fixture.json"
NOW = int(datetime(2026, 11, 25, 15, 30, tzinfo=timezone.utc).timestamp() * 1000)   # Wed 25 Nov, 21:00 IST
VERIFIED = sorted(o["id"] for o in BASE["offers"] if o["category"] != "events")
SPOTTED = ["hdfc-bms-bogo-news", "pvr-passport", "sbi-district-code", "upi-cashback-bms", "xss-lead"]


class R1(Base):
    def site(self, name="r1", spotted=SPOTS):
        w = self.tmp / name
        w.mkdir()
        (w / "offers.json").write_text(json.dumps(BASE))
        (w / "h").mkdir()
        (w / "h/2026-11-25.json").write_text(json.dumps(BASE))
        out = w / "dist"
        g.build(w / "offers.json", w / "h", out, w / "st.json", ROOT / "data/site.json", ROOT, spotted=spotted)
        return out

    def card(self, t, oid, cls="offer"):
        return re.search(rf'<article class="{cls}[^"]*" id="{oid}".*?</article>', t, re.S).group(0)


# ------------------------------------------------------------------ static (no browser)
class Validity(unittest.TestCase):
    def test_ends_text_across_dates(self):
        end = date(2026, 12, 31)
        cases = {date(2026, 11, 25): "Ends 31 Dec", date(2026, 12, 23): "Ends 31 Dec",
                 date(2026, 12, 24): "Ends in 7 days · 31 Dec", date(2026, 12, 26): "Ends in 5 days · 31 Dec",
                 date(2026, 12, 30): "Ends in 1 day · 31 Dec", date(2026, 12, 31): "Last day · 31 Dec",
                 date(2027, 1, 1): "Ended 31 Dec 2026"}
        for today, want in cases.items():
            self.assertEqual(g.ends_text(end, today), want, today)
        self.assertEqual(g.ends_text(date(2027, 3, 31), date(2026, 11, 25)), "Ends 31 Mar 2027")
        self.assertEqual(g.ends_text(None, date(2026, 11, 25)), "No end date")

    def test_day_rule_names_the_next_day_without_today(self):
        sat = g.norm({"days": ["sat"], "day_basis": "booking"})
        self.assertEqual(g.day_rule(sat, date(2026, 11, 25)), ("wait", "Book on Saturdays only · next Sat 28 Nov"))
        self.assertEqual(g.day_rule(sat, date(2026, 11, 28)), ("wait", "Book on Saturdays only · Sat 28 Nov"))
        self.assertEqual(g.day_rule(sat, date(2026, 11, 29)), ("wait", "Book on Saturdays only · next Sat 5 Dec"))
        fri = g.norm({"days": ["fri"]})
        self.assertEqual(g.day_rule(fri, date(2026, 11, 25)), ("wait", "Fridays only · next Fri 27 Nov"))
        self.assertEqual(g.day_rule(g.norm({"days": ["sat", "fri"]}), date(2026, 11, 25)), ("wait", "Fri & Sat only"))
        self.assertEqual(g.day_rule(g.norm({"days": ["any"]}), date(2026, 11, 25)), ("ok", "Every day"))
        self.assertEqual(g.day_rule(g.norm({}), date(2026, 11, 25)), ("none", "Days not stated"))
        for k, t in (g.day_rule(sat, date(2026, 11, d)) for d in range(20, 30)):
            self.assertNotRegex(t, r"(?i)\btoday\b|\d+:\d+")              # no ticking timer, never "today"


class Banks(unittest.TestCase):
    def test_one_bank_vocabulary_for_both_tiers(self):
        cases = {"HDFC Bank": "hdfc", "HDFC": "hdfc", "SBI Card": "sbi", "Kotak <b>Bank</b>": "kotak", "Axis": "axis",
                 "Axis Bank": "axis", "AU Small Finance Bank": "au", "Bank of India": "boi", "Indian Bank": "indianbank",
                 "Union Bank of India": "union", "BOBCARD": "bob", "IDFC FIRST Bank": "idfc", "Standard Chartered": "sc",
                 "YES Bank": "yes", "City Union Bank": "cub", "IndusInd": "indusind", "HSBC": "hsbc", "Visa": "visa"}
        for issuer, want in cases.items():
            self.assertEqual(g.bank_id(issuer), want, issuer)

    def test_monograms_are_initials_in_our_own_tints(self):
        m = g.monogram("hdfc", "HDFC Bank")
        self.assertRegex(m, r'^<span class="mono mt[0-4]" aria-hidden="true">HD</span>$')
        self.assertIn(">GO<", g.monogram("gosats", "GoSats"))
        self.assertIn(">CU<", g.monogram("cityunion", "City Union"))
        self.assertNotIn("<b>", g.monogram("kotak", "Kotak <b>Bank</b>"))
        self.assertNotRegex(g.monogram("x", '<img src=x onerror=1>'), r"<img")
        self.assertEqual(g.monogram("hsbc", "HSBC"), g.monogram("hsbc", "HSBC"))     # stable


class Cards(R1):
    def test_value_first_card(self):
        t = (self.site() / "index.html").read_text()
        c = self.card(t, "hsbc-premier-bms-bogo")
        order = [c.index(x) for x in ('class="o-head"', 'class="o-value"', 'class="o-chips"', 'class="o-foot"', 'class="o-act"')]
        self.assertEqual(order, sorted(order), "who, money line, conditions, check, actions")
        self.assertRegex(c, r'<span class="mono mt\d" aria-hidden="true">HS</span>')
        chips = re.findall(r"<li[^>]*>(.*?)</li>", re.search(r'<ul class="o-chips".*?</ul>', c, re.S).group(0))
        # decision 149: at most 3 chips, decisive first; the app moved into the money line
        self.assertEqual([re.sub("<[^>]+>", "", x) for x in chips], ["Every day", "Twice a month", "Ends 31 Dec"])
        self.assertIn('<span class="o-app">BookMyShow app</span>', re.search(r'<p class="o-value">.*?</p>', c, re.S).group(0))
        for oid in VERIFIED:
            cc = self.card(t, oid)
            n = len(re.findall(r"<li", re.search(r'<ul class="o-chips".*?</ul>', cc, re.S).group(0)))
            self.assertLessEqual(n, 3, oid)
        axis = visible(re.search(r'<ul class="o-chips".*?</ul>', self.card(t, "axis-select-district-bogo"), re.S).group(0))
        self.assertIn("Needs ₹25,000", axis)                                           # the spend gate beats the limit/end
        self.assertIn("Ends 31 Dec", visible(self.card(t, "hsbc-select-bms-saturday-bogo")))   # a dropped chip is in Details
        terms = re.search(r'<details class="o-terms">.*?</details>', c, re.S).group(0)
        for x in ("Cite this", "o-quote", "For 2 tickets"):                           # proof one tap away, never removed
            self.assertIn(x, terms)
        self.assertNotIn("o-quote", c.replace(terms, ""))

    def test_key_condition_and_booking_day(self):
        t = (self.site() / "index.html").read_text()
        sat = visible(self.card(t, "hsbc-select-bms-saturday-bogo"))
        self.assertRegex(sat, r"Book on Saturdays only · next Sat\s+28 Nov")
        self.assertIn("Show can be any day", sat)
        axis = self.card(t, "axis-select-district-bogo")
        self.assertRegex(axis, r'<li class="c-key">Needs ₹25,000 card spend in the previous 3 calendar months</li>')
        self.assertIn('data-end="2026-12-31"', self.card(t, "hsbc-premier-bms-bogo"))

    def test_spotted_cards_share_the_layout_but_never_look_checked(self):
        out = self.site()
        t = (out / "index.html").read_text()
        row = self.card(t, "spot-sbi-district-code", "spot")                         # home: a compact row (decision 149)
        self.assertNotIn("Checked by", row)
        self.assertNotIn('class="o-foot"', row)
        self.assertIn("Spotted elsewhere: not yet verified", t)
        sp = self.card((out / "spotted/index.html").read_text(), "spot-sbi-district-code", "spot")   # the full card
        self.assertIn('<span class="sp-pill"><span aria-hidden="true">👀 </span>Spotted · not verified</span>', sp)
        self.assertIn('class="code sp-code"', sp)
        self.assertIn("Code (unverified)", sp)
        self.assertNotIn("Checked by", sp)
        self.assertNotIn('class="o-foot"', sp)
        for oid in VERIFIED:
            c = self.card(t, oid)
            self.assertNotIn("sp-pill", c)
            self.assertNotIn("unverified", c)
        css = (self.site("c") / "assets/site.css").read_text()
        self.assertRegex(css, r"\.spot\{[^}]*border:1\.5px dashed var\(--spot\)")
        self.assertRegex(css, r"\.code\.sp-code\{border:1\.5px dashed")
        self.assertRegex(css, r"\.code\{border-style:solid")

    def test_no_js_fallback_is_complete(self):
        t = (self.site() / "index.html").read_text()
        for marker in ("data-find hidden", "data-applied hidden"):
            self.assertIn(marker, t)                                # JS-only controls never show without JS
        find = re.search(r'<div class="find" data-find hidden>.*?</button>', t, re.S).group(0)
        self.assertIn("data-fbtn", find)                            # "Filters (n)" sits in the JS-only search row (decision 149)
        sheet = re.search(r'<dialog class="fsheet".*?</dialog>', t, re.S).group(0)
        for g_ in ("type", "bank"):
            self.assertIn(f'name="{g_}"', sheet)                    # rows exist in the HTML…
        css = (self.site("c") / "assets/site.css").read_text()
        self.assertRegex(css, r"\.fsheet:not\(\.wsheet\)\{position:static;display:grid")   # …and render inline
        self.assertRegex(css, r"\.js \.fsheet:not\(\[open\]\):not\(\.wsheet\)\{display:none\}")
        self.assertIn('body:has(#bank-hsbc:checked) .offer:not([data-bank="hsbc"])', t)      # CSS radios still filter
        self.assertEqual(len(re.findall(r'<article class="offer"', t)), len(VERIFIED))
        self.assertIn('<link rel="canonical" href="https://bookmyfdfs.in/">', t)
        self.assertRegex(t, r"5 checked movie offers</strong><span data-sat-hero[^>]*> · highest cap ₹750")   # crawlers: static answer

    def test_accessible_controls(self):
        t = (self.site() / "index.html").read_text()
        self.assertRegex(t, r'<label class="sr" for="q">[^<]+</label>')
        self.assertIn('aria-describedby="q-h"', t)
        self.assertRegex(t, r'<p class="meta" role="status" data-status>Showing <span data-count>')
        self.assertRegex(t, r'<dialog class="fsheet" id="fd" aria-labelledby="fd-h">')

    def test_script_is_private_and_modest(self):
        js = g.home_js()
        self.assertNotRegex(js, r"fetch\(|XMLHttpRequest|sendBeacon|WebSocket|document\.cookie|navigator\.geolocation")
        self.assertEqual(re.findall(r"localStorage\.(?:get|set|remove)Item\((\w+)", js), ["KEY", "KEY", "KEY"])
        self.assertIn("KEY='fdfs.cards.v1'", js)                                     # review D5: product IDs only
        self.assertEqual(re.findall(r"localStorage\.removeItem\('([^']+)'", js), ["fdfs-cards"])   # only round 1's bank list, deleted
        # Budget raised 26 Nov (site v2, decision 142): 16 KB / 6.5 KB -> 24 KB / 9.5 KB. Exact card products (A2), the
        # feed adapter with fallbacks (A1-A5), conditional reasons (D3, D4, G5), the two result groups (D2) and the inline
        # bank -> card panel (D1) replace a bank-only checkbox list. The script is inlined on the home page only and is
        # excluded from the page budget, so this raise moves no other page.
        self.assertLessEqual(len(js.encode()), 24 * 1024)
        self.assertLessEqual(len(gzip.compress(js.encode())), int(9.5 * 1024))
        if __import__("shutil").which("node"):
            f = self.tmp / "home.js"
            f.write_text(js)
            r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_minifier_keeps_strings_and_regexes(self):
        src = "var a = 'x  y', b = /2nd ticket free|buy ?(1|one)/i, c = 4 / 2 / 1;\n// note\nreturn a\n+b"
        out = g._min_js(src)
        self.assertIn("'x  y'", out)
        self.assertIn("/2nd ticket free|buy ?(1|one)/i", out)
        self.assertIn("4/2/1", out)
        self.assertNotIn("note", out)


# ------------------------------------------------------------------ browser
HARNESS = """<!doctype html><meta charset="utf-8"><body><pre id="o"></pre><script>
function done(x){document.getElementById('o').textContent=JSON.stringify(x)}
function load(src,w,cb,h){var f=document.createElement('iframe');f.width=w;f.height=h||900;f.src=src;
f.onload=function(){var d=f.contentDocument,cs=d.createElement('style');cs.textContent='::-webkit-scrollbar{width:15px;height:15px}';
d.head.appendChild(cs);setTimeout(function(){try{cb(f,d,f.contentWindow)}catch(e){done({error:String(e)})}},250)};document.body.appendChild(f);return f}
function vis(d,s){return [].filter.call(d.querySelectorAll(s||'#offers .offer,.spot'),function(e){return e.offsetParent!==null}).map(function(e){return e.id}).sort()}
function pick(d,id){var r=d.getElementById(id);r.checked=true;r.dispatchEvent(new Event('change',{bubbles:true}))}
function type(d,v){var i=d.getElementById('q');i.value=v;i.dispatchEvent(new Event('input',{bubbles:true}))}
function txt(e){return e?e.textContent.replace(/\\s+/g,' ').trim():null}
function scroll(d){var e=d.documentElement;return [e.scrollWidth,e.clientWidth]}
try{%(body)s}catch(e){done({error:String(e)+' '+e.stack})}
</script>"""


@unittest.skipUnless(g.chrome_path(), "needs headless Chrome")
class Browser(R1):
    @classmethod
    def setUpClass(cls):
        import shutil
        import tempfile
        cls.ctmp = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.ctmp, True)

    def run_js(self, out, body, budget=6000, allow_error=False):
        name = f"__h{abs(hash(body)) % 10**8}.html"
        (out / name).write_text(HARNESS % {"body": body})
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(out)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.7)
            r = subprocess.run([g.chrome_path(), "--headless=new", "--disable-gpu", f"--user-data-dir={self.tmp / name}",
                                f"--virtual-time-budget={budget}", "--window-size=1400,1000", "--dump-dom",
                                f"http://127.0.0.1:{port}/{name}"], capture_output=True, text=True, timeout=90,
                               stdin=subprocess.DEVNULL)
        finally:
            srv.terminate()
            srv.wait(timeout=10)
        m = re.search(r'<pre id="o">(.*?)</pre>', r.stdout, re.S)
        res = json.loads(html.unescape(m.group(1))) if m and m.group(1) else {"error": "no result"}
        if not allow_error:
            self.assertNotIn("error", res, res.get("error"))
        return res


PARSE = {
    "hdfc sat bms": {"bank": ["hdfc"], "day": ["sat"], "app": ["bms"]},
    "HDFC Saturday BookMyShow": {"bank": ["hdfc"], "day": ["sat"], "app": ["bms"]},
    "sbi card district": {"bank": ["sbi"], "app": ["district"]},
    "kal bms": {"day": ["thu"], "app": ["bms"]},
    "aaj ke offers": {"day": ["wed"]},
    "hdfc ka offer kal": {"bank": ["hdfc"], "day": ["thu"]},
    "sbi parso": {"bank": ["sbi"], "day": ["fri"]},
    "shanivar pvr": {"day": ["sat"], "app": ["cinema"]},
    "kotak ravivar": {"bank": ["kotak"], "day": ["sun"]},
    "icici upi": {"bank": ["icici"], "type": ["upi"]},
    "axis select": {"bank": ["axis"], "w": ["select"]},
    "bogo hsbc": {"bank": ["hsbc"], "w": ["bogo"]},
    "1 + 1 on district": {"app": ["district"], "w": ["bogo"]},
    "buy one get one": {"w": ["bogo"]},
    "weekend movie offers": {"day": ["sat", "sun"]},
    "paytm": {"type": ["upi"]},
    "gpay": {"type": ["upi"]},
    "district pass": {"app": ["district"], "type": ["membership"]},
    "coupon code": {"code": 1},
    "promo code bms": {"code": 1, "app": ["bms"]},
    "au bank": {"bank": ["au"]},
    "bank of baroda": {"bank": ["bob"]},
    "bank of india": {"bank": ["boi"]},
    "indian bank": {"bank": ["indianbank"]},
    "union bank of india": {"bank": ["union"]},
    "standard chartered bms": {"bank": ["sc"], "app": ["bms"]},
    "yes bank": {"bank": ["yes"]},
    "idfc first": {"bank": ["idfc"]},
    "hsbc premier": {"bank": ["hsbc"], "w": ["premier"]},
    "₹750": {"w": ["750"]},
    "  HDFC   ": {"bank": ["hdfc"]},
    "hdfc axis": {"bank": ["hdfc", "axis"]},
    "cinépolis": {"app": ["cinema"]},
    "inox tmrw": {"app": ["cinema"], "day": ["thu"]},
    "fridays": {"day": ["fri"]},
    "book my show": {"app": ["bms"]},
    "xyzzy": {"w": ["xyzzy"]},
    "": {},
}
SEARCH = {   # query -> what is visible (checked offers, spotted leads), at Wed 25 Nov with the default day (today)
    "hdfc sat bms": ([], ["spot-hdfc-bms-bogo-news"]),
    "axis": (["axis-myzone-district-bogo", "axis-select-district-bogo"], []),
    "code": (["axis-myzone-district-bogo", "axis-select-district-bogo"], ["spot-sbi-district-code"]),
    "sat hsbc": (["hsbc-premier-bms-bogo", "hsbc-select-bms-saturday-bogo"], []),
    "premier": (["hsbc-premier-bms-bogo"], []),
    "upi": ([], ["spot-upi-cashback-bms"]),
    "pvr": ([], ["spot-pvr-passport"]),
    "xyzzy": ([], []),
}


def check_parse(res):
    bad = []
    for q, want in PARSE.items():
        got = res["parse"][q]
        full = {"bank": [], "app": [], "type": [], "day": [], "code": 0, "w": [], **want}
        if {k: got[k] for k in full} != full:
            bad.append((q, got, full))
    return bad


def check_counts(res):
    bad = []
    for st in res["states"]:
        for c in st["chips"]:
            ns = c["ns"]
            if not c.get("fon"):
                ns = min(ns, g.SPOT_HOME)       # decision 149: un-narrowed, home shows the newest 3 rows (+ "See all N spotted")
            if [c["n"], ns] != [len(c["vis"][0]), len(c["vis"][1])]:
                bad.append((st["q"], st["day"], c))
        for c in st["days"]:
            if c["cap"] != (f"{c['n']} offer{'s' if c['n'] != 1 else ''}" if c["n"] else "No offers"):
                bad.append((st["q"], "day", c))
    return bad


PARSE_JS = """load('/?fdfs_now=%(now)d',390,function(f,d,w){var Q=%(qs)s,out={};Q.forEach(function(q){var p=w.FDFS.parse(q);
out[q]={bank:p.bank,app:p.app,type:p.type,day:p.day,code:p.code,w:p.w}});
var S=%(search)s,vs={};Object.keys(S).forEach(function(q){type(d,q);vs[q]=[vis(d,'#offers .offer'),vis(d,'.spot')]});
type(d,'hdfc sat bms');var bar=txt(d.querySelector('[data-applied]')),hid=d.querySelector('[data-applied]').hidden;
var b=d.querySelector('[data-rm^="app|q"]');b.click();var after={q:d.getElementById('q').value,bar:txt(d.querySelector('[data-ap-c]'))};
done({parse:out,vis:vs,bar:bar,barHidden:hid,after:after})});"""

COUNTS_JS = """var states=[['',''],['bms',''],['','sat'],['hdfc sat',''],['code',''],['premier','']],res=[],k=0;
function one(){if(k==states.length)return done({states:res});var s=states[k++];
load('/?fdfs_now=%(now)d'+(s[1]?'&day='+s[1]:''),390,function(f,d,w){type(d,s[0]);var st={q:s[0],day:s[1],chips:[],days:[]};
[].forEach.call(d.querySelectorAll('.filters input[type=radio]'),function(r){var l=d.querySelector('label[for="'+r.id+'"]'),
ns=l.querySelector('.ns'),c={id:r.id,n:+l.querySelector('.n').textContent,ns:ns&&!ns.hidden?+ns.textContent.replace(/\\D/g,''):0,grey:l.classList.contains('z')};
var keep=d.getElementById('q').value,was=[].filter.call(d.querySelectorAll('.filters input:checked'),function(x){return x.name==r.name})[0];
pick(d,r.id);c.vis=[vis(d,'#offers .offer'),vis(d,'.spot')];c.fon=d.body.classList.contains('f-on');
type(d,keep);if(was)pick(d,was.id);type(d,keep);st.chips.push(c)});
[].forEach.call(d.querySelectorAll('button.day'),function(b){var cap=b.querySelector('.n').textContent;b.click();
st.days.push({day:b.dataset.day,cap:cap,n:vis(d,'#offers .offer').length})});
res.push(st);one()})}one();"""


class Search(Browser):
    def test_parser_and_search(self):
        out = self.site()
        res = self.run_js(out, PARSE_JS % {"now": NOW, "qs": json.dumps(list(PARSE)), "search": json.dumps(SEARCH)})
        self.assertGreaterEqual(len(PARSE), 20)
        self.assertEqual(check_parse(res), [])
        for q, (v, s) in SEARCH.items():
            self.assertEqual(res["vis"][q], [sorted(v), sorted(s)], q)
        self.assertFalse(res["barHidden"])
        self.assertEqual(res["bar"].replace(" ", ""), "Searching:HDFCBank✕(remove)BookMyShow✕(remove)Sat28Nov✕(remove)ClearallSharethislist")
        self.assertEqual(res["after"]["q"], "hdfc sat")                           # removing a chip edits the query
        self.assertNotIn("BookMyShow", res["after"]["bar"])

    def test_counts_equal_visible_cards_for_every_chip(self):
        out = self.site()
        res = self.run_js(out, COUNTS_JS % {"now": NOW}, budget=15000)
        self.assertEqual(len(res["states"]), 6)
        self.assertEqual(check_counts(res), [])
        chips = {c["id"]: c for c in res["states"][3]["chips"]}                   # "hdfc sat": greyed, never hidden
        self.assertTrue(chips["type-upi"]["grey"])
        self.assertEqual([chips["type-upi"]["n"], chips["type-upi"]["ns"]], [0, 0])
        self.assertFalse(chips["bank-axis"]["grey"])                              # 2 if you switch the bank to Axis


class UrlState(Browser):
    def test_round_trip_and_share(self):
        out = self.site()
        res = self.run_js(out, """load('/?fdfs_now=%d',390,function(f,d,w){type(d,'bms');pick(d,'type-card');
d.querySelector('button.day[data-day=sat]').click();var u=w.location.search,v=vis(d),s=txt(d.querySelector('[data-applied]'));
var opened=null;w.open=function(x){opened=x};d.querySelector('[data-share-view]').click();
load(w.location.pathname+u,390,function(f2,d2,w2){done({url:u,vis:v,bar:s,vis2:vis(d2),bar2:txt(d2.querySelector('[data-applied]')),
q2:d2.getElementById('q').value,pressed:d2.querySelector('button.day[aria-pressed=true]').dataset.day,
checked:d2.querySelector('#type-card').checked,canon:d2.querySelector('link[rel=canonical]').href,share:opened})})});""" % NOW)
        q = parse_qs(urlparse(res["url"]).query)
        self.assertEqual((q["q"], q["type"], q["day"]), (["bms"], ["card"], ["sat"]))
        self.assertEqual(res["vis2"], res["vis"])
        self.assertEqual(res["bar2"], res["bar"])
        self.assertEqual((res["q2"], res["pressed"], res["checked"]), ("bms", "sat", True))
        self.assertEqual(res["canon"], "https://bookmyfdfs.in/")                  # canonical stays on the base page
        self.assertTrue(res["share"].startswith("https://wa.me/?text="))
        text = unquote(res["share"].split("text=")[1])
        self.assertIn("/?q=bms&type=card&day=sat", text)
        self.assertNotIn("fdfs_now", text)
        self.assertRegex(text, r"\d+ checked")

    def test_bad_params_are_ignored(self):
        out = self.site()
        res = self.run_js(out, """load('/?fdfs_now=%d&bank=%%3Cimg%%20src=x%%3E&day=funday&app=bms',390,function(f,d,w){
done({vis:vis(d,'#offers .offer'),img:!!d.querySelector('.applied img'),bar:txt(d.querySelector('[data-ap-c]'))})});""" % NOW)
        self.assertFalse(res["img"])
        self.assertEqual(res["bar"], "BookMyShow ✕ (remove)")


WALLET_JS = """function pc(d,b,id){var o=d.querySelector('[data-iss="'+b+'"]');if(o.getAttribute('aria-expanded')!='true')o.click();
var c=d.querySelector('input[value="'+id+'"]');c.checked=true;c.dispatchEvent(new Event('change',{bubbles:true}))}
load('/?fdfs_now=%(now)d',390,function(f,d,w){var static0=txt(d.querySelector('#answer .s-a'));
d.querySelector('[data-wopen]').click();var panel=d.getElementById('mc'),modal=!panel.hidden;
pc(d,'hsbc','hsbc:premier');pc(d,'axis','axis:select');pc(d,'axis','axis:my-zone');
var r={static0:static0,modal:modal,hero:txt(d.querySelector('#answer .s-a')),
vis:vis(d),url:w.location.search,stored:null,wallet:txt(d.querySelector('[data-wallet]'))};
try{r.stored=w.localStorage.getItem('fdfs.cards.v1')}catch(e){r.stored='ERR'}
load('/?fdfs_now=%(now)d',390,function(f2,d2,w2){r.hero2=txt(d2.querySelector('#answer .s-a'));r.vis2=vis(d2);
d2.querySelector('button.day[data-day=sat]').click();r.heroSat=txt(d2.querySelector('#answer .s-a'));
d2.querySelector('[data-wclear]').click();r.after=txt(d2.querySelector('#answer .s-a'));
try{r.stored2=w2.localStorage.getItem('fdfs.cards.v1')}catch(e){r.stored2='ERR'}done(r)})});"""


class Wallet(Browser):
    """Round 1's bank-only wallet became exact products in site v2 (L2, review D1/D5): these follow the new flow."""
    def test_persists_on_this_device_and_drives_the_answer(self):
        out = self.site()
        res = self.run_js(out, WALLET_JS % {"now": NOW}, budget=8000)
        self.assertTrue(res["modal"])
        self.assertEqual(json.loads(res["stored"]), ["hsbc:premier", "axis:select", "axis:my-zone"])
        self.assertNotIn("hsbc", res["url"])                                        # never written to the URL
        self.assertEqual(res["hero"], "With your HSBC Premier Mastercard + Axis Select + Axis MY ZONE: 3 checked offers match what "
                                      "you picked for Wed 25 Nov, 1 more may apply. Highest cap ₹750 (HSBC Premier Mastercard).")
        self.assertEqual(res["hero2"], res["hero"])                                 # a fresh visit remembers
        self.assertEqual(res["vis2"], sorted(["axis-myzone-district-bogo", "axis-select-district-bogo", "hsbc-premier-bms-bogo",
                                              "hsbc-select-bms-saturday-bogo"]))                 # unstated scope: shown, conditional
        self.assertTrue(res["heroSat"].startswith("With your HSBC Premier Mastercard + Axis Select + Axis MY ZONE: 3 checked offers match what you picked for Sat 28 Nov"), res["heroSat"])
        self.assertIsNone(res["stored2"])                                           # Forget removes it
        self.assertTrue(res["after"].startswith("Booking Sat 28 Nov: 5 checked offers"), res["after"])
        self.assertIn("My cards (3)", res["wallet"])

    def test_works_without_storage(self):
        out = self.site()
        page = (out / "index.html").read_text().replace(
            "<head>", "<head><script>Object.defineProperty(window,'localStorage',{get:function(){throw new Error('blocked')}})</script>", 1)
        (out / "nostore.html").write_text(page)
        res = self.run_js(out, """load('/nostore.html?fdfs_now=%d',390,function(f,d,w){var ok=!!w.FDFS;
d.querySelector('[data-wopen]').click();d.querySelector('[data-iss=hsbc]').click();var c=d.querySelector('input[value="hsbc:premier"]');
c.checked=true;c.dispatchEvent(new Event('change',{bubbles:true}));done({ok:ok,hero:txt(d.querySelector('#answer .s-a')),
note:txt(d.querySelector('[data-wnote]')),vis:vis(d,'#offers .offer')})});""" % NOW)
        self.assertTrue(res["ok"], "the script must survive a throwing localStorage")
        self.assertTrue(res["hero"].startswith("With your HSBC Premier Mastercard: 1 checked offer matches what you picked"), res["hero"])
        self.assertEqual(res["note"], "We can’t remember your cards on this device.")
        self.assertEqual(res["vis"], ["hsbc-premier-bms-bogo", "hsbc-select-bms-saturday-bogo"])   # + unstated scope, conditional


class Hero(Browser):
    def test_answer_follows_the_day_and_returns(self):
        out = self.site()
        res = self.run_js(out, """load('/?fdfs_now=%d',390,function(f,d,w){var a=d.querySelector('#answer .s-a'),r={s0:txt(a)};
d.querySelector('button.day[data-day=sat]').click();r.sat=txt(a);d.querySelector('button.day[data-day=mon]').click();r.mon=txt(a);
d.querySelector('[data-clear]').click();r.all=txt(a);done(r)});""" % NOW)
        self.assertTrue(res["s0"].startswith("5 checked movie offers · highest cap ₹750"), res["s0"])
        self.assertEqual(res["sat"], "Booking Sat 28 Nov: 5 checked offers. Highest cap ₹750 (HSBC Premier Mastercard). "
                                     "Plus 5 spotted, not yet verified.")
        self.assertTrue(res["mon"].startswith("Booking Mon 30 Nov: 4 checked offers."))
        self.assertEqual(res["all"], res["s0"])
        self.assertNotRegex(res["sat"] + res["mon"], r"(?i)\bbest\b|hurry|only \d+ left")


COPY_JS = """load('/?fdfs_now=%(now)d',390,function(f,d,w){var got=[],opened=0,href=w.location.href;
Object.defineProperty(w.navigator,'clipboard',{value:{writeText:function(v){got.push(v);return Promise.resolve()}},configurable:true});
w.open=function(){opened++};var b=d.querySelector('#axis-select-district-bogo .code'),l=b.querySelector('.cl'),r={};
b.click();setTimeout(function(){r.l1=l.textContent;r.done=b.classList.contains('done');r.live=l.getAttribute('aria-live');
setTimeout(function(){r.l15=l.textContent;setTimeout(function(){r.l25=l.textContent;
r.border=w.getComputedStyle(b).borderTopStyle;r.offerBorder=w.getComputedStyle(d.querySelector('.offer')).borderTopStyle;
r.got=got;r.opened=opened;r.same=w.location.href==href;
load('/spotted/?fdfs_now=%(now)d',390,function(f2,d2,w2){Object.defineProperty(w2.navigator,'clipboard',{value:undefined,configurable:true});
d2.execCommand=function(){return true};var s=d2.querySelector('#spot-sbi-district-code .code');s.click();r.sp=s.querySelector('.cl').textContent;
r.spLabel=txt(s.querySelector('.code-l'));r.spBorder=w2.getComputedStyle(s).borderTopStyle;
r.spotBorder=w2.getComputedStyle(d2.querySelector('.spot')).borderTopStyle;
r.homeSpot=w.getComputedStyle(d.querySelector('.sp-home')).borderTopStyle;done(r)})},1000)},1400)},100)});"""


class Copy(Browser):
    def test_copy_states(self):
        out = self.site()
        res = self.run_js(out, COPY_JS % {"now": NOW}, budget=8000)
        self.assertEqual(res["got"], ["AXISSELECT"])
        self.assertEqual((res["l1"], res["done"], res["live"]), ("✓ Copied", True, "polite"))
        self.assertEqual(res["l15"], "✓ Copied")                                   # still there at 1.5 s
        self.assertEqual(res["l25"], "Copy")                                       # back after 2 s
        self.assertEqual((res["opened"], res["same"]), (0, True))                  # never opens or redirects
        self.assertEqual(res["sp"], "✓ Copied")                                    # fallback path without the API
        self.assertEqual(res["spLabel"], "Code (unverified)")
        self.assertEqual((res["spBorder"], res["border"]), ("dashed", "solid"))
        self.assertEqual(res["spotBorder"], "dashed")                              # the full spotted card (/spotted/)
        self.assertEqual(res["homeSpot"], "dashed")                                # home's compact rows (decision 149)
        self.assertNotEqual(res["offerBorder"], "dashed")                          # a checked card never looks spotted


class ValidityLive(Browser):
    def test_ends_text_follows_the_visitor_day(self):
        out = self.site()
        body = """var W=%s,r={},k=0;function one(){if(k==W.length)return done(r);var t=W[k++];load('/?fdfs_now='+t,390,function(f,d){
r[t]=[].map.call(d.querySelectorAll('#hsbc-premier-bms-bogo .o-more [data-end],#indusind-eazydiner-platinum-bms-bogo .o-more [data-end]'),txt);one()})}one();"""
        days = {datetime(2026, 11, 25, 15, 30, tzinfo=timezone.utc): ["Ends 31 Dec", "Ends 31 Mar 2027"],
                datetime(2026, 12, 26, 6, tzinfo=timezone.utc): ["Ends in 5 days · 31 Dec", "Ends 31 Mar 2027"],
                datetime(2026, 12, 31, 18, 31, tzinfo=timezone.utc): ["Ended 31 Dec 2026", "Ends 31 Mar"]}   # 00:01 IST 1 Jan
        ms = {int(k.timestamp() * 1000): v for k, v in days.items()}
        res = self.run_js(out, body % json.dumps(list(ms)), budget=9000)
        for t, want in ms.items():
            self.assertEqual(res[str(t)], want, t)


LAYOUT_JS = """var W=[[360,''],[390,''],[1280,''],[390,'sheet'],[1280,'sheet'],[390,'wallet'],[390,'q'],[1280,'q']],r=[],k=0;
function one(){if(k==W.length)return done({r:r});var x=W[k++];load('/?fdfs_now=%(now)d&theme=dark',x[0],function(f,d,w){
if(x[1]=='sheet')d.querySelector('[data-fbtn]').click();if(x[1]=='wallet'){d.querySelector('[data-fbtn]').click();d.querySelector('[data-wopen]').click()}if(x[1]=='q')type(d,'hdfc sat bms');
var fb=d.querySelector('[data-fbtn]'),sh=d.getElementById('fd'),small=[];
[].forEach.call(d.querySelectorAll('.chip,button.day,.day-all,.code,.o-terms summary,.share,.tag-x,.ap-x,.ap-s,.w-add,.w-b,.fbtn,.go,.wk,#q'),function(e){
var b=e.getBoundingClientRect();if(e.offsetParent!==null&&b.height<44)small.push(e.className+':'+Math.round(b.height))});
var rows=sh.querySelector('.frow').getBoundingClientRect();
r.push({w:x[0],s:x[1],sc:scroll(d),fbtn:fb.offsetParent!==null,sheetOpen:sh.open,rowsVisible:rows.height>0,small:small.slice(0,5),
bg:w.getComputedStyle(d.body).backgroundColor});one()},844)}one();"""


class Layout(Browser):
    def test_no_sideways_scroll_tap_targets_sheet_and_dark(self):
        out = self.site()
        res = self.run_js(out, LAYOUT_JS % {"now": NOW}, budget=15000)
        for x in res["r"]:
            self.assertLessEqual(x["sc"][0], x["sc"][1], x)                       # no page scroll sideways
            self.assertEqual(x["sc"][1], x["w"] - 15, "the forced classic scrollbar must be in effect")
            self.assertEqual(x["small"], [], x)                                   # every tap target >= 44 px
            self.assertEqual(x["bg"], "rgb(15, 24, 19)", "dark theme parity (V2 ink night, decision 139)")
        by = {(x["w"], x["s"]): x for x in res["r"]}
        self.assertTrue(by[(390, "")]["fbtn"])
        self.assertFalse(by[(390, "")]["rowsVisible"])                            # phone: rows live in the sheet
        self.assertTrue(by[(390, "sheet")]["sheetOpen"] and by[(390, "sheet")]["rowsVisible"])
        # decision 149: at every width only search, the app tabs and the day strip are in view; the rest is in the sheet
        self.assertTrue(by[(1280, "")]["fbtn"])
        self.assertFalse(by[(1280, "")]["rowsVisible"])
        self.assertTrue(by[(1280, "sheet")]["sheetOpen"] and by[(1280, "sheet")]["rowsVisible"])


# ------------------------------------------------------------------ mutants: the checks above must catch these
MUTANTS = {
    "counts ignore spotted": ("if (!it.el.hidden && hit(it, e)) n[it.v ? 0 : 1]++;", "if (!it.el.hidden && hit(it, e)) n[0]++;"),
    "chip counts skip the search": ("c = count(withF(e, g, r.value === 'all' ? [] : [r.value]))",
                                    "c = count(withF(withF(e, 'w', []), g, r.value === 'all' ? [] : [r.value]))"),
    "bms alias dropped": ("add('bms bookmyshow book_my_show bookmy my_show', 'app', 'bms');",
                          "add('bookmyshow book_my_show bookmy my_show', 'app', 'bms');"),
    "Hinglish kal dropped": ("add('tomorrow tmrw tmr kal',", "add('tomorrow tmrw tmr',"),
    "wallet written to the URL": ("  if (dayX) u.set('day',", "  if (W.length) u.set('cards', W.join(','));\n  if (dayX) u.set('day',"),
    "answer ignores the wallet": ("var useW = mine && W.length", "var useW = 0 && W.length"),
    "storage error not caught": ("  try { if (a.length) localStorage.setItem(KEY, JSON.stringify(a)); else localStorage.removeItem(KEY); return true; }\n  catch (e) { return false; }",
                                 "  if (a.length) localStorage.setItem(KEY, JSON.stringify(a)); else localStorage.removeItem(KEY); return true;"),
}


@unittest.skipUnless(g.chrome_path(), "needs headless Chrome")
class Mutants(Browser):
    def mutate(self, name):
        old, new = MUTANTS[name]
        src = (ROOT / "gen/home.js").read_text()
        self.assertIn(old, src, name)
        saved = g.HOME_JS
        g.HOME_JS = g._min_js(src.replace(old, new))
        self.addCleanup(setattr, g, "HOME_JS", saved)
        return self.site(name="m" + str(abs(hash(name)) % 1000))

    def test_counts_mutants_are_caught(self):
        for name in ("counts ignore spotted", "chip counts skip the search"):
            out = self.mutate(name)
            res = self.run_js(out, COUNTS_JS % {"now": NOW}, budget=15000, allow_error=True)
            self.assertTrue("error" in res or check_counts(res), name)

    def test_parser_mutants_are_caught(self):
        for name in ("bms alias dropped", "Hinglish kal dropped"):
            out = self.mutate(name)
            res = self.run_js(out, PARSE_JS % {"now": NOW, "qs": json.dumps(list(PARSE)), "search": json.dumps(SEARCH)},
                              allow_error=True)
            self.assertTrue("error" in res or check_parse(res), name)

    def test_wallet_mutants_are_caught(self):
        for name in ("wallet written to the URL", "answer ignores the wallet"):
            out = self.mutate(name)
            r = self.run_js(out, WALLET_JS % {"now": NOW}, budget=8000, allow_error=True)
            self.assertTrue("error" in r or "hsbc" in r["url"] or not r["hero"].startswith("With your"), name)

    def test_storage_mutant_is_caught(self):
        out = self.mutate("storage error not caught")
        page = (out / "index.html").read_text().replace(
            "<head>", "<head><script>Object.defineProperty(window,'localStorage',{get:function(){throw new Error('blocked')}})</script>", 1)
        (out / "nostore.html").write_text(page)
        res = self.run_js(out, """load('/nostore.html?fdfs_now=%d',390,function(f,d,w){var ok=true;try{d.querySelector('[data-wopen]').click();
d.querySelector('[data-iss=hsbc]').click();var c=d.querySelector('input[value="hsbc:premier"]');c.checked=true;
c.dispatchEvent(new Event('change',{bubbles:true}))}catch(e){ok=false}
done({hero:txt(d.querySelector('#answer .s-a'))})});""" % NOW, allow_error=True)
        self.assertTrue("error" in res or not res["hero"].startswith("With your HSBC"))

    def test_style_mutant_is_caught(self):
        real = g.site_css
        self.addCleanup(setattr, g, "site_css", real)
        g.site_css = lambda root: real(root).replace("border:1.5px dashed var(--spot)}", "border:1px solid var(--line)}", 1)
        out = self.site(name="mstyle")
        res = self.run_js(out, COPY_JS % {"now": NOW}, budget=8000)
        self.assertEqual(res["spotBorder"], "solid", "a spotted card styled like a checked one must be visible to the test")


if __name__ == "__main__":
    unittest.main()


class Review(R1):
    """Lead review of round 1 (26 Nov): events note out of the grid, scrollable chip rows, a real-data budget."""

    def test_home_budget_with_the_reviewed_39_leads(self):
        out = self.site(spotted=ROOT / "tests/fixtures/spotted-reviewed-39.json")
        home = (out / "index.html").read_text()
        self.assertEqual(len(re.findall(r'<article class="spot', home)), 39)
        css = len(gzip.compress((out / "assets/site.css").read_bytes()))
        # P3 (decision 156): plan.js (Saved, Sort) is a feature script with its own cap in test_plan_p3, like home.js
        total = len(gzip.compress(home.replace(g.home_js(), "").replace(g.PLAN.plan_js(), "").encode())) + css
        self.assertLessEqual(total, 26 * 1024, f"home HTML + CSS {total} bytes gzip (the script has its own cap)")

    def test_live_events_offer_is_a_note_not_a_tile(self):
        t = (self.site() / "index.html").read_text()
        grid = re.search(r'<div class="grid">.*?</div>\n', t, re.S).group(0)
        self.assertNotIn('class="also"', grid)
        note = visible(re.search(r'<aside class="also".*?</aside>', t, re.S).group(0))
        # decision 166: the note sits in its own "Concerts and live events" section
        self.assertIn('<section class="wrap block" id="events" aria-labelledby="h-ev">', t)
        self.assertRegex(note, r"Live events:\s+HSBC credit cards · BookMyShow app: 10% off, up to ₹1,000 a month on live event tickets")
        self.assertNotIn("also-big", t)


@unittest.skipUnless(g.chrome_path(), "needs headless Chrome")
class ChipRows(Browser):
    def test_keyboard_focus_brings_a_clipped_chip_into_view(self):
        out = self.site(spotted=ROOT / "tests/fixtures/spotted-reviewed-39.json")
        res = self.run_js(out, """load('/?fdfs_now=%d',1280,function(f,d,w){d.documentElement.classList.remove('js');   /* the no-JS layout: rows inline (with JS they wrap in the sheet) */
var row=d.querySelector('.frow input[name=bank]').closest('.chips'),
rs=[].slice.call(row.querySelectorAll('input')),last=rs[rs.length-1],l=d.querySelector('label[for="'+last.id+'"]');
var before=l.getBoundingClientRect().right>row.getBoundingClientRect().right;last.focus();
setTimeout(function(){var a=l.getBoundingClientRect(),b=row.getBoundingClientRect();
done({before:before,inside:a.left>=b.left-1&&a.right<=b.right+1,snap:w.getComputedStyle(row).scrollSnapType,
mask:w.getComputedStyle(row).webkitMaskImage!='none',scroll:row.scrollWidth>row.clientWidth})},400)});""" % NOW)
        self.assertTrue(res["scroll"] and res["before"], "the bank row overflows at 1280 with 39 leads")
        self.assertTrue(res["inside"], "focusing a chip scrolls it fully into view")
        self.assertIn("x", res["snap"])
        self.assertTrue(res["mask"], "a fade edge says there is more")
