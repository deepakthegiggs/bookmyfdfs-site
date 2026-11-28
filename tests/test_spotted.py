"""Decision 135: the Spotted tier (leads seen on the web, not yet verified), kept apart from the verified tier."""
import html
import json
import re
import shutil
import subprocess
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
from test_generator import Base, text_files  # noqa: E402
from test_links import anchors, external  # noqa: E402

FIXTURE = ROOT / "tests/fixtures/spotted-fixture.json"
LIVE = json.loads((ROOT / "tests/fixtures/offers-spotted-base.json").read_text())   # frozen live export, 25 Nov
# decision 168 (owner: "lets not miss anything"): a lead for an issuer and app we have a checked offer on now shows,
# marked; leads past 7 days or ended are dropped from the live list but kept, collapsed, on /spotted/
SHOWN = {"hdfc-bms-bogo-news", "sbi-district-code", "upi-cashback-bms", "pvr-passport", "xss-lead", "axis-district-again"}
DROPPED = {"too-old", "ended", "hsbc-premier-bms-bogo", "urgent-copy", "indusind-eazydiner-platinum-bms-bogo"}


class Spot(Base):
    def spot_build(self, spotted=FIXTURE, name="sp"):
        w = self.tmp / name
        w.mkdir()
        (w / "offers.json").write_text(json.dumps(LIVE))
        (w / "h").mkdir()
        (w / "h/2026-11-25.json").write_text(json.dumps(LIVE))
        out = w / "dist"
        r = g.build(w / "offers.json", w / "h", out, w / "st.json", ROOT / "data/site.json", ROOT, spotted=spotted)
        return out, r

    def spots(self, html_text):
        return re.findall(r'<article class="spot(?: sp-x)?" id="spot-([^"]+)"', html_text)   # folded rows are on the page too


class Tiers(Spot):
    def test_shown_and_dropped(self):
        out, r = self.spot_build()
        home = (out / "index.html").read_text()
        self.assertEqual(set(self.spots((out / "spotted/index.html").read_text())), SHOWN)
        self.assertEqual(set(self.spots(home)), SHOWN - {"axis-district-again"})   # decision 169: near leads on /spotted/ only
        dropped = {d.split(":")[0] for d in r["spotted_dropped"]}
        self.assertEqual(dropped, DROPPED)
        self.assertIn("Spotted elsewhere: not yet verified", home)
        self.assertIn("We spotted these on the web. We haven't checked their terms yet, so open the source before you "
                      "rely on one.", html.unescape(home))

    def test_never_in_verified_surfaces(self):
        out, r = self.spot_build()
        home = (out / "index.html").read_text()
        hero = re.search(r'<p class="s-a">.*?</p>', home, re.S).group(0)
        counts = json.loads(re.search(r"data-counts='([^']+)'", home).group(1))
        n_movie = sum(1 for o in LIVE["offers"] if o["category"] != "events")
        self.assertIn(f"{n_movie} checked movie offers", hero)
        self.assertTrue(all(v <= n_movie for v in counts.values()))
        self.assertIn(f"of {n_movie}</p>", home)                                # Showing N of M counts verified only
        for sid in SHOWN:
            self.assertNotIn(sid, hero)
            for p in ("best-card-for-movie-tickets/index.html", "bank/hsbc/index.html", "bank/axis/index.html"):
                self.assertNotIn(f"spot-{sid}", (out / p).read_text(), p)
        for spec in r["og"]:
            self.assertNotRegex(" ".join(spec["lines"]), r"HDFC|SBI|PhonePe|Kotak|PVR")
        pub = json.loads((out / "offers.json").read_text())
        self.assertFalse({o["id"] for o in pub["offers"]} & SHOWN)
        for p in out.rglob("*.html"):
            ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', p.read_text(), re.S).group(1)
            if "offer" not in p.relative_to(out).parts:                     # L1: Offer markup only on checked offers' own pages
                self.assertNotIn('"Offer"', ld)
            for sid in SHOWN:
                self.assertNotIn(sid, ld)
            if "example.com" in ld or "example.org" in ld:                    # sources only in a plain ItemList of links
                graph = json.loads(ld)["@graph"]
                lists = [x for x in graph if x["@type"] == "ItemList"]
                self.assertTrue(lists, p)
                for item in lists[0]["itemListElement"]:
                    self.assertEqual(set(item) - {"@type", "position", "url", "name"}, set())

    def test_beat_tiles_and_what_is_untouched(self):
        out, _ = self.spot_build()
        what = re.search(r'<section class="what[^"]*".*?</section>', (out / "index.html").read_text(), re.S).group(0)
        self.assertNotIn("spot", what)


class Expiry(Spot):
    def test_build_time_expiry_and_dedupe(self):
        out, r = self.spot_build()
        reasons = dict(d.split(":", 1) for d in r["spotted_dropped"])
        self.assertIn("older than 7 days", reasons["too-old"])
        self.assertIn("ended", reasons["ended"])
        self.assertIn("verified", reasons["hsbc-premier-bms-bogo"])
        self.assertNotIn("axis-district-again", reasons)
        near = re.search(r'<article class="spot[^"]*" id="spot-axis-district-again".*?</article>',
                         (out / "spotted/index.html").read_text(), re.S).group(0)
        self.assertIn("We list a checked Axis Bank offer on District", near)
        home = (out / "index.html").read_text()                         # decision 169: near leads only on /spotted/
        self.assertNotIn("spot-axis-district-again", home)
        self.assertNotIn("spot-axis-district-again", (out / "district-offers/index.html").read_text())
        n = (out / "spotted/index.html").read_text().count('<article class="spot')
        self.assertIn(f"See all {n} spotted", home)
        arch = re.search(r'<h2 id="h-old">.*?</section>', (out / "spotted/index.html").read_text(), re.S).group(0)
        self.assertNotIn('class="spot', arch)                          # never counted, filtered or shared
        self.assertNotIn("data-copy", arch)
        self.assertIn("verified", reasons["indusind-eazydiner-platinum-bms-bogo"])   # same id, different issuer
        self.assertIn("banned wording", reasons["urgent-copy"])

    @unittest.skipUnless(g.chrome_path(), "needs headless Chrome")
    def test_browser_hides_expired_spots(self):
        out, _ = self.spot_build()
        s = __import__("socket").socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        harness = ("<!doctype html><body><pre id='o'></pre><script>var f=document.createElement('iframe');f.width=390;"
                   "f.src='/?fdfs_now=%d';f.onload=function(){setTimeout(function(){var d=f.contentDocument;"
                   "document.getElementById('o').textContent=JSON.stringify({vis:[].filter.call(d.querySelectorAll('.spot'),"
                   "function(e){return !e.hidden&&(e.offsetParent!==null||e.classList.contains('sp-x'))}).map(function(e){return e.id}).sort(),"
                   "sec:d.querySelector('[data-spot-section]').hidden})},300)};document.body.appendChild(f)</script>")
        res = {}
        for name, when in (("fresh", datetime(2026, 11, 25, 12, tzinfo=timezone.utc)),
                           ("later", datetime(2026, 12, 1, 6, tzinfo=timezone.utc)),
                           ("gone", datetime(2026, 12, 9, 6, tzinfo=timezone.utc))):
            (out / f"__{name}.html").write_text(harness % int(when.timestamp() * 1000))
        srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(out)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.8)
            for name in ("fresh", "later", "gone"):
                r = subprocess.run([g.chrome_path(), "--headless=new", "--disable-gpu", f"--user-data-dir={self.tmp / name}",
                                    "--virtual-time-budget=3000", "--dump-dom", f"http://127.0.0.1:{port}/__{name}.html"],
                                   capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
                res[name] = json.loads(html.unescape(re.search(r"<pre id=\"o\">(.*?)</pre>", r.stdout, re.S).group(1)))
        finally:
            srv.terminate()
            srv.wait(timeout=10)
        self.assertEqual(set(res["fresh"]["vis"]), {f"spot-{i}" for i in SHOWN - {"axis-district-again"}})   # 169: home
        # 1 Dec 11:30 IST: spotted 23 Nov (upi) and 24 Nov 08:00 (pvr), 10:00 (hdfc) are > 7 days old;
        # xss-lead (spotted 24 Nov 18:00) is within 7 days but ended 27 Nov; sbi (25 Nov, ends 31 Dec) stays
        self.assertEqual(set(res["later"]["vis"]), {"spot-sbi-district-code"})
        self.assertEqual(res["gone"]["vis"], [])
        self.assertTrue(res["gone"]["sec"], "an empty spotted section hides itself")


class Links(Spot):
    def test_source_links_new_tab_and_no_platform_deep_links(self):
        out, _ = self.spot_build()
        home = (out / "spotted/index.html").read_text()
        for sid in SHOWN:
            card = re.search(rf'<article class="spot(?: sp-x)?" id="spot-{re.escape(sid)}".*?</article>', home, re.S).group(0)
            links = [a for a in anchors(card) if external(a["attrs"].get("href", ""))]
            self.assertTrue(links, sid)
            for a in links:
                self.assertEqual(a["attrs"]["target"], "_blank")
                self.assertEqual(set(a["attrs"]["rel"].split()), {"nofollow", "noopener", "noreferrer"})
                self.assertIn("opens in a new tab", a["text"])
        pvr = re.search(r'<article class="spot(?: sp-x)?" id="spot-pvr-passport".*?</article>', home, re.S).group(0)
        hrefs = [a["attrs"]["href"] for a in anchors(pvr) if a["attrs"].get("href", "").startswith("http")]
        self.assertEqual(hrefs, ["https://www.pvrcinemas.com/"])

    def test_pvr_offer_cited_elsewhere_links_its_source(self):
        leads = json.loads(FIXTURE.read_text())["leads"]
        pvr = dict(next(l for l in leads if l["id"] == "pvr-passport"), id="pvr-news",
                   source_url="https://news.example.com/pvr-weekday", source_name="Example News")
        p = self.tmp / "pvrnews.json"
        p.write_text(json.dumps({"leads": [pvr]}))
        out, _ = self.spot_build(p, name="pvrnews")
        card = re.search(r'<article class="spot(?: sp-x)?" id="spot-pvr-news".*?</article>', (out / "index.html").read_text(), re.S).group(0)
        self.assertEqual([a["attrs"]["href"] for a in anchors(card) if a["attrs"].get("href", "").startswith("http")],
                         ["https://news.example.com/pvr-weekday"])

    def test_aggregator_leads_go_last(self):
        leads = json.loads(FIXTURE.read_text())["leads"]
        agg = dict(next(l for l in leads if l["id"] == "upi-cashback-bms"), spotted_at="2026-11-25T10:00:00+05:30")
        off = dict(next(l for l in leads if l["id"] == "hdfc-bms-bogo-news"), spotted_at="2026-11-24T09:00:00+05:30")
        p = self.tmp / "agg.json"
        p.write_text(json.dumps({"leads": [agg, off]}))
        out, _ = self.spot_build(p, name="agg")
        self.assertEqual(self.spots((out / "index.html").read_text()), ["hdfc-bms-bogo-news", "upi-cashback-bms"])

    def test_code_is_labelled_unverified(self):
        out, _ = self.spot_build()
        # the full card (code, quote) is on /spotted/; home shows a compact row (decision 149)
        card = re.search(r'<article class="spot" id="spot-sbi-district-code".*?</article>',
                         (out / "spotted/index.html").read_text(), re.S).group(0)
        self.assertIn("Code (unverified)", card)
        self.assertIn('data-copy="SBIMOVIE150"', card)
        self.assertIn("Spotted on SBI Card · 25 Nov 2026", html.unescape(re.sub(r"<[^>]+>", "", card)))


class Escaping(Spot):
    def test_scraped_text_is_inert(self):
        out, _ = self.spot_build()
        for p in (out / "index.html", out / "spotted/index.html"):
            t = p.read_text()
            card = re.search(r'<article class="spot(?: sp-x)?" id="spot-xss-lead".*?</article>', t, re.S).group(0)
            self.assertNotIn("<script", card)
            self.assertNotIn("<img", card)
            self.assertNotIn("<b>", card)
            self.assertIn("&lt;script&gt;", card)
            self.assertNotRegex(card, r'href="[^"]*"><script')
        t = (out / "spotted/index.html").read_text()
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', t, re.S)
        self.assertEqual(len(blocks), 1)
        self.assertNotIn("<", blocks[0])                                       # a scraped </script> can't end the block
        # QA F3: unverified leads are never structured data; the scraped URL survives only as an escaped href
        self.assertNotIn("ItemList", blocks[0])
        self.assertNotIn("example.net", blocks[0])
        self.assertIn('href="https://blog.example.net/kotak?x=&quot;&gt;&lt;script&gt;alert(2)&lt;/script&gt;"', t)
        self.assertEqual(t.count("<script"), t.count("</script>"))


class Filters(Spot):
    def test_chips_filter_spots_with_a_separate_count(self):
        out, _ = self.spot_build()
        home = (out / "index.html").read_text()
        self.assertRegex(home, r'for="type-upi">UPI &amp; wallets<span class="n">0</span><span class="ns">\+ 1 spotted</span>')
        self.assertRegex(home, r'<article class="spot(?: sp-x)?" id="spot-upi-cashback-bms"[^>]*data-type="upi"[^>]*data-app="bms"')
        self.assertIn('body:has(#type-upi:checked) .spot:not([data-type="upi"])', home)
        self.assertNotIn("data-days", re.search(r'<article class="spot".*?</article>', home, re.S).group(0))


class SpottedPage(Spot):
    def test_page_title_meta_noindex_until_ten(self):
        out, _ = self.spot_build()
        t = (out / "spotted/index.html").read_text()
        self.assertRegex(t, r"<title>Spotted movie ticket offers, not yet verified · FDFS</title>")
        self.assertIn('name="robots" content="noindex', t)                     # 5 leads < 10
        self.assertNotIn("/spotted/", (out / "sitemap.xml").read_text())
        self.assertIn("/spotted/", (out / "llms.txt").read_text())
        self.assertEqual(set(self.spots(t)), SHOWN)

    def test_indexable_with_ten_leads(self):
        leads = json.loads(FIXTURE.read_text())["leads"]
        base = next(x for x in leads if x["id"] == "hdfc-bms-bogo-news")
        many = [dict(base, id=f"lead-{i}", issuer=f"Bank {chr(65 + i)}") for i in range(10)]
        p = self.tmp / "many.json"
        p.write_text(json.dumps({"leads": many}))
        out, _ = self.spot_build(p, name="many")
        self.assertNotIn("noindex", (out / "spotted/index.html").read_text())
        self.assertIn("/spotted/", (out / "sitemap.xml").read_text())

    def test_home_folds_after_three_and_filters_reveal(self):
        leads = json.loads(FIXTURE.read_text())["leads"]
        base = next(x for x in leads if x["id"] == "hdfc-bms-bogo-news")
        many = [dict(base, id=f"lead-{i}", issuer=f"Bank {chr(65 + i)}") for i in range(9)]
        p = self.tmp / "nine.json"
        p.write_text(json.dumps({"leads": many}))
        out, _ = self.spot_build(p, name="nine")
        home = (out / "index.html").read_text()
        self.assertEqual(len(re.findall(r'<article class="spot sp-x"', home)), 6)            # 3 rows in view (decision 149)
        self.assertIn('href="/spotted/">See all 9 spotted', home)
        self.assertNotIn("sp-code", re.search(r'<div class="sp-list sp-home">.*?</div>', home, re.S).group(0))   # rows, not cards
        self.assertNotIn("sp-x", (out / "spotted/index.html").read_text())      # the page lists every lead
        css = (out / "assets/site.css").read_text()
        self.assertIn('body:has(.filters input:not([value="all"]):checked) .spot.sp-x{display:flex}', css)

    def test_block_list_by_id_and_by_issuer_and_card(self):
        leads = json.loads(FIXTURE.read_text())["leads"]
        base = next(x for x in leads if x["id"] == "hdfc-bms-bogo-news")
        rows = [dict(base, id="icici-sapphiro", issuer="ICICI Bank", headline="ICICI Sapphiro: buy 1 get 1 on BookMyShow"),
                dict(base, id="icici-coral", issuer="ICICI Bank", headline="ICICI Coral: 25% off on BookMyShow"),
                dict(base, id="some-lead", issuer="Kotak", headline="Kotak cards on BookMyShow")]
        w = self.tmp / "blk"
        w.mkdir()
        (w / "spotted.json").write_text(json.dumps(rows))
        (w / "spotted-block.json").write_text(json.dumps([
            {"issuer": "ICICI", "card": "Sapphiro", "reason": "ended 31 March 2021 per ICICI's terms"},
            {"id": "some-lead", "reason": "duplicate"}]))
        out, r = self.spot_build(w / "spotted.json", name="blkbuild")
        self.assertEqual(self.spots((out / "index.html").read_text()), ["icici-coral"])
        self.assertIn("icici-sapphiro: blocked: ended 31 March 2021 per ICICI's terms", r["spotted_dropped"])
        self.assertIn("some-lead: blocked: duplicate", r["spotted_dropped"])

    def test_real_block_file_is_well_formed(self):
        rules = g.load_block(ROOT / "data/spotted-block.json")
        self.assertEqual(len(rules), len(json.loads((ROOT / "data/spotted-block.json").read_text())))
        self.assertTrue(all(r.get("reason") for r in rules))

    def test_no_page_without_leads(self):
        out, _ = self.spot_build(self.tmp / "missing.json", name="none")
        self.assertFalse((out / "spotted").exists())
        self.assertNotIn("data-spot-section", (out / "index.html").read_text())

    def test_corrections_mentions_spotted(self):
        out, _ = self.spot_build()
        self.assertIn("Spotted offers", html.unescape((out / "corrections/index.html").read_text()))


@unittest.skipUnless(g.chrome_path(), "needs headless Chrome")
class Layout(Spot):
    def test_no_horizontal_scroll(self):
        out, _ = self.spot_build()
        s = __import__("socket").socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        (out / "__m.html").write_text(
            "<!doctype html><body><pre id='o'></pre><script>var P=['/','/spotted/'],W=[360,390],out=[],n=0;"
            "P.forEach(function(p){W.forEach(function(w){var f=document.createElement('iframe');f.width=w;f.height=800;"
            "f.src=p+'?fdfs_now=1795600000000';f.onload=function(){var d=f.contentDocument,cs=d.createElement('style');"
            "cs.textContent='::-webkit-scrollbar{width:15px;height:15px}';d.head.appendChild(cs);setTimeout(function(){"
            "var e=d.documentElement;out.push(p+'@'+w+'='+(e.scrollWidth<=e.clientWidth?'ok':'scroll'+e.scrollWidth)+'/'+e.clientWidth);"
            "if(++n==4)document.getElementById('o').textContent=out.sort().join(',')},300)};"
            "document.body.appendChild(f)})})</script>")
        srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(out)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.8)
            r = subprocess.run([g.chrome_path(), "--headless=new", "--disable-gpu", f"--user-data-dir={self.tmp / 'm'}",
                                "--virtual-time-budget=5000", "--window-size=900,900", "--dump-dom",
                                f"http://127.0.0.1:{port}/__m.html"], capture_output=True, text=True, timeout=60,
                               stdin=subprocess.DEVNULL)
        finally:
            srv.terminate()
            srv.wait(timeout=10)
        got = re.search(r'<pre id="o">(.*?)</pre>', r.stdout).group(1)
        # no sideways page scroll, with a forced classic 15px scrollbar (as on the Linux CI runner)
        self.assertEqual(got, "/@360=ok/345,/@390=ok/375,/spotted/@360=ok/345,/spotted/@390=ok/375")


if __name__ == "__main__":
    unittest.main()
