"""Decision 171: the site v2 preview under /v2/. Built from the real export next to the live site, never instead of it:
noindex, out of every feed and of the build state, the live pages byte-for-byte unchanged, every owner rule the live
site keeps (no estimates, no savings line, no "today" in static HTML, Verified and Spotted apart). The browser half runs
where headless Chrome is installed (CI): no sideways scroll at 320-1280 px, 44 px targets, the answer on a phone's first
screen, My cards and filters working."""
import gzip
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
import v2_site as V2  # noqa: E402
from test_redesign_r1 import NOW, Browser  # noqa: E402

BASE = "https://bookmyfdfs.in"


def build(out: Path, tmp: Path, v2=True):
    state = tmp / f"state-{out.name}.json"
    shutil.copyfile(ROOT / "data/build-state.json", state)
    ctx = mock.patch.object(V2, "build_v2", return_value=[]) if not v2 else mock.patch.object(V2, "g", g)
    with ctx:
        r = g.build(ROOT / "data/offers.json", ROOT / "data/history", out, state, ROOT / "data/site.json", ROOT,
                    render_og=False, spotted=ROOT / "data/spotted.json")
    return r, json.loads(state.read_text(encoding="utf-8"))


class V2Static(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.out = cls.tmp / "dist"
        cls.r, cls.state = build(cls.out, cls.tmp)
        cls.pages = {p: (cls.out / p.strip("/") / "index.html").read_text(encoding="utf-8") for p in cls.r["v2"]}
        cls.feed = json.loads((cls.out / "offers.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_page_has_a_v2_twin_or_a_reason(self):
        live = set(self.r["pages"])
        want = {"/", "/this-week/", "/spotted/", "/best-card-for-movie-tickets/", g.GUIDE_PATH} | \
            {p for p in live if p.startswith(("/bank/", "/card/", "/offers-on/", "/offer/")) or p in ("/bookmyshow-offers/", "/district-offers/")}
        want = {p for p in want if p in live and p.count("/") <= 3}
        self.assertEqual({p for p in want if V2.vp(p) not in self.pages}, set(), "live pages without a v2 twin")
        for extra in (V2.OFFERS_PATH, V2.CALC_PATH, V2.MY_PATH):
            self.assertIn(V2.vp(extra), self.pages)

    def test_noindex_canonical_and_basics(self):
        for path, t in self.pages.items():
            self.assertIn('<meta name="robots" content="noindex,nofollow">', t, path)
            canon = re.search(r'<link rel="canonical" href="([^"]+)">', t).group(1)
            twin = path[len("/v2"):]
            self.assertEqual(canon, BASE + (twin if twin in self.r["pages"] else path), path)
            self.assertEqual(t.count("<h1"), 1, path)
            self.assertRegex(t, r'<meta name="description" content="[^"]{40,}">', path)
            self.assertIn('href="/assets/v2.css?v=', t)
            self.assertIn('src="/assets/v2.js?v=', t)
            self.assertNotIn('href="/assets/site.css', t, "v2 pages carry their own stylesheet only")

    def test_never_in_a_feed_the_state_or_indexnow(self):
        for name in ("sitemap.xml", "llms.txt", "llms-full.txt", "search.json", ".changed-urls.txt", "offers.json",
                     "changes.json", "changes.xml", "robots.txt"):
            self.assertNotIn("/v2/", (self.out / name).read_text(encoding="utf-8"), name)
        self.assertFalse([p for p in self.state if p.startswith("/v2")], "v2 paths in the build state")
        self.assertFalse([p for p in self.r["pages"] if p.startswith("/v2")])
        self.assertFalse([p for p in self.r["changed"] if p.startswith("/v2")])

    def test_live_site_is_byte_for_byte_unchanged(self):
        out2 = self.tmp / "nov2"
        build(out2, self.tmp, v2=False)
        skip = {"assets/v2.css", "assets/v2.js"}
        a = {p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file()}
        b = {p.relative_to(out2).as_posix() for p in out2.rglob("*") if p.is_file()}
        self.assertEqual({x for x in a if not x.startswith("v2/") and x not in skip}, b)
        for rel in sorted(b):
            if rel == ".changed-urls.txt":
                continue
            self.assertEqual((self.out / rel).read_bytes(), (out2 / rel).read_bytes(), rel)

    def test_data_is_exactly_the_checked_offers(self):
        data = json.loads((self.out / "v2/data.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(o["id"] for o in data["offers"]), sorted(o["id"] for o in self.feed["offers"]))
        held = {o.id for o in self.r["held"]}
        self.assertFalse(held & {o["id"] for o in data["offers"]})
        for o in data["offers"]:
            self.assertTrue(o["terms"].startswith("https://"), o["id"])
            self.assertEqual(o["page"], "/v2/offer/" + o["id"] + "/")
        for c in data["cards"]:
            self.assertRegex(c["id"], r"^[a-z]+(:[a-z0-9-]+)?$", "card ids match the live My cards format")

    def test_spotted_stays_apart(self):
        sp = self.pages.get("/v2/spotted/")
        if not sp:
            self.skipTest("no spotted leads in the export")
        self.assertIn('class="sp"', sp)
        self.assertNotIn('class="oc"', sp, "no checked card on the leads page")
        self.assertNotIn("data-save", re.sub(r'<header.*?</header>', "", sp, flags=re.S).split('<main id="main">')[1].split("</main>")[0])
        for path, t in self.pages.items():
            if path != "/v2/spotted/":
                self.assertNotIn('<article class="sp"', t, f"{path}: a lead next to checked offers")

    def test_markup_rules(self):
        for path, t in self.pages.items():
            for blk in re.findall(r'<script type="application/ld\+json">(.*?)</script>', t, re.S):
                types = re.findall(r'"@type":"([A-Za-z]+)"', blk)
                for bad in ("Offer", "FAQPage", "Product", "AggregateRating", "Review", "Question"):
                    self.assertNotIn(bad, types, path)
            self.assertNotRegex(t, r"<img\b|fonts\.googleapis|placeholder=", path)

    def test_weight(self):
        css = len(gzip.compress((self.out / "assets/v2.css").read_bytes()))
        js = len(gzip.compress((self.out / "assets/v2.js").read_bytes()))
        self.assertLessEqual(css, 8 * 1024, "v2.css gzip")
        self.assertLessEqual(js, 8 * 1024, "v2.js gzip")
        for path, t in self.pages.items():
            total = len(gzip.compress(t.encode("utf-8"))) + css
            self.assertLessEqual(total, 20 * 1024, f"{path}: {total} B gzip with CSS")

    def test_script_stays_on_the_device(self):
        js = (self.out / "assets/v2.js").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"fetch\('([^']+)'", js), ["/v2/data.json"])
        self.assertNotRegex(js, r"https?://(?!bookmyfdfs\.in)", "no third-party address in the script")
        self.assertIn("'fdfs.cards.v1'", js)
        self.assertIn("'fdfs.saved.v1'", js)
        code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        self.assertNotRegex(code, r"(?i)estimat|price|you save\b|save ₹|savings", "no estimate or savings wording (decisions 139, P3)")

    def test_booking_check_has_no_price_input(self):
        t = self.pages[V2.vp(V2.CALC_PATH)]
        self.assertNotRegex(t, r'name="(price|fee|amount)"')
        self.assertIn('name="n"', t)


@unittest.skipUnless(g.chrome_path(), "needs headless Chrome")
class V2Browser(Browser):
    W = (320, 360, 390, 768, 1280)
    P = ["/v2/", "/v2/offers/", "/v2/offer/hsbc-select-bms-saturday-bogo/", "/v2/this-week/", "/v2/tools/which-offer-works/",
         "/v2/my/", "/v2/bank/hsbc/"]

    def test_no_sideways_scroll_and_44px_targets(self):
        out = self.site()
        paths = [p for p in self.P if (out / p.strip("/") / "index.html").exists()]
        res = self.run_js(out, """var r=[],J=[],P=%s,W=%s;P.forEach(function(p){W.forEach(function(w){J.push([p,w])})});var k=0;
function one(){if(k==J.length)return done({r:r});var j=J[k++];load(j[0]+'?fdfs_now=%d',j[1],function(f,d){
var cw=d.documentElement.clientWidth,wide=[],small=[],gs=d.defaultView.getComputedStyle;
function scroller(e){for(var p=e.parentElement;p&&p!==d.body;p=p.parentElement){var o=gs(p).overflowX;if(o=='auto'||o=='scroll'||o=='hidden')return true}return false}
[].forEach.call(d.querySelectorAll('body *'),function(e){var b=e.getBoundingClientRect();if(e.closest('dialog'))return;
if(b.width&&b.right>cw+0.5&&!scroller(e))wide.push((e.tagName+'.'+(typeof e.className=='string'?e.className:'')+' '+Math.round(b.right)).slice(0,80))});
[].forEach.call(d.querySelectorAll('button,select,input,summary,.btn,.bn a,.hd a,.oc-what a,.tl,.wd,.ap'),function(e){
if(e.offsetParent===null||e.closest('dialog')||e.type=='checkbox')return;var b=e.getBoundingClientRect();if(b.height<44)small.push((e.tagName+'.'+e.className+' '+Math.round(b.height)).slice(0,60))});
r.push({p:j[0],w:j[1],sc:scroll(d),wide:wide.slice(0,5),small:small.slice(0,5)});one()},900)}one();""" % (json.dumps(paths), list(self.W), NOW),
                          budget=60000)
        for x in res["r"]:
            self.assertLessEqual(x["sc"][0], x["sc"][1], x)
            self.assertEqual(x["wide"], [], x)
            self.assertEqual(x["small"], [], x)

    def test_answer_on_the_first_screen_and_cards_follow(self):
        out = self.site()
        cards = json.loads((out / "v2/data.json").read_text(encoding="utf-8"))["cards"]
        card = next(c for c in cards if ":" in c["id"])
        bank = card["id"].split(":")[0]
        res = self.run_js(out, """var r=[],W=[360,390],k=0;function one(){if(k==W.length)return next();var w=W[k++];
load('/v2/?fdfs_now=%d',w,function(f,d){var b=d.getElementById('answer').getBoundingClientRect();r.push({w:w,bottom:Math.round(b.bottom)});one()},740)}
function next(){load('/v2/offers/?fdfs_now=%d',390,function(f,d,win){win.localStorage.setItem('fdfs.cards.v1',JSON.stringify([%s]));
f.onload=function(){setTimeout(function(){var dd=f.contentDocument,c=dd.querySelector('[data-f=mine]');c.click();
var v=[].filter.call(dd.querySelectorAll('#list .oc'),function(e){return e.offsetParent!==null}).map(function(e){return e.dataset.id});
done({r:r,mine:v,badge:txt(dd.querySelector('[data-wn]')),count:txt(dd.querySelector('[data-count]'))})},600)};win.location.reload()})}
one();""" % (NOW, NOW, json.dumps(card["id"])), budget=20000)
        for x in res["r"]:
            self.assertLess(x["bottom"], 740, x)
        self.assertEqual(res["badge"], "1", res)
        self.assertTrue(res["mine"], res)
        self.assertTrue(all(i.startswith(bank) for i in res["mine"]), res)


if __name__ == "__main__":
    unittest.main()
