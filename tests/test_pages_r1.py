"""SEO/AEO page plan (redesign r1, section C): app hubs, bank x app pages, the weekly digest, comparison tables,
BreadcrumbList + Article with real dates, internal links, and the thin-page gates."""
import copy
import json
import re
import sys
import unittest
from collections import deque
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
from test_generator import Base  # noqa: E402
from test_review_s1 import visible  # noqa: E402

BASE = json.loads((ROOT / "tests/fixtures/offers-spotted-base.json").read_text())
SPOTS = ROOT / "tests/fixtures/spotted-fixture.json"
MOVIE = [o for o in BASE["offers"] if o["category"] != "events"]


def ld(t):
    return json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', t, re.S).group(1))["@graph"]


def page(out, path):
    return (out / path.strip("/") / "index.html").read_text() if path != "/" else (out / "index.html").read_text()


class Plan(Base):
    def make(self, payload=None, name="p", history=None, spotted=SPOTS):
        w = self.tmp / name
        w.mkdir()
        pl = payload or BASE
        (w / "offers.json").write_text(json.dumps(pl))
        (w / "h").mkdir()
        for day, x in (history or {"2026-11-25": pl}).items():
            (w / "h" / f"{day}.json").write_text(json.dumps(x))
        out = w / "dist"
        r = g.build(w / "offers.json", w / "h", out, w / "st.json", ROOT / "data/site.json", ROOT, spotted=spotted)
        return out, r


class Hubs(Plan):
    def test_hubs_only_where_a_checked_offer_exists(self):
        out, r = self.make()
        self.assertIn("/bookmyshow-offers/", r["pages"])
        self.assertIn("/district-offers/", r["pages"])
        self.assertNotIn("/pvr-inox-offers/", r["pages"])          # 1 spotted lead, 0 checked: no thin page
        no_district = copy.deepcopy(BASE)
        no_district["offers"] = [o for o in no_district["offers"] if o["platform"] != "district"]
        out2, r2 = self.make(no_district, name="nd")
        self.assertNotIn("/district-offers/", r2["pages"])
        for p in out2.rglob("*.html"):
            self.assertNotIn('href="/district-offers/"', p.read_text(), p)   # never a link to a page that isn't there

    def test_hub_answer_table_cards_and_spotted_kept_apart(self):
        out, _ = self.make()
        t = page(out, "/bookmyshow-offers/")
        bms = sorted(o["id"] for o in MOVIE if o["platform"] == "bms")
        self.assertEqual(sorted(re.findall(r'<article class="offer" id="([^"]+)"', t)), bms)
        self.assertEqual(len(re.findall(r"<tr data-checked", t)), len(bms))              # rows carry the freshness guard
        ans = visible(re.search(r'<p class="s-a">.*?</p>', t, re.S).group(0))
        self.assertIn(f"{len(bms)} movie offers on BookMyShow pass our checks on 25 Nov 2026", ans)
        self.assertNotIn("Axis", ans)
        self.assertNotIn("HDFC", ans)                                                   # a spotted lead never in the answer
        spots = re.findall(r'<li class="spot sp-row" id="spot-([^"]+)"', t)
        self.assertEqual(sorted(spots), ["hdfc-bms-bogo-news", "upi-cashback-bms"])
        self.assertIn("Spotted for BookMyShow: not yet verified", t)
        self.assertIn("data-spot-section", t)
        items = [x for x in ld(t) if x["@type"] == "ItemList"][0]["itemListElement"]
        self.assertEqual(len(items), len(bms))
        self.assertFalse(any("hdfc" in i["url"] for i in items))

    def test_titles_meta_and_markup(self):
        out, _ = self.make()
        for path, app in (("/bookmyshow-offers/", "BookMyShow"), ("/district-offers/", "District")):
            t = page(out, path)
            title = re.search(r"<title>(.*?)</title>", t).group(1)
            self.assertTrue(title.startswith(f"{app} offers: "), title)
            self.assertLessEqual(len(title), 65)
            desc = re.search(r'<meta name="description" content="([^"]+)"', t).group(1)
            self.assertTrue(desc.startswith("FDFS (Film · Deals · Friends · Seats)"), desc)
            types = [x["@type"] for x in ld(t)]
            self.assertIn("BreadcrumbList", types)
            crumbs = [x for x in ld(t) if x["@type"] == "BreadcrumbList"][0]["itemListElement"]
            self.assertEqual([c["name"] for c in crumbs], ["Offers", f"{app} offers"])

    def test_no_offer_product_or_faq_markup_anywhere(self):
        out, _ = self.make()
        for p in out.rglob("*.html"):
            offer_page = "offer" in p.relative_to(out).parts   # L1 (decision 141): Offer markup only on /offer/<id>/
            for x in ld(p.read_text()):
                self.assertNotIn(x["@type"], ("Product", "AggregateOffer", "FAQPage", "ClaimReview"), p)
                if not offer_page:
                    self.assertNotIn(x["@type"], ("Offer",), p)
                    self.assertNotIn('"Offer"', json.dumps(x), p)


class BankApp(Plan):
    def test_only_when_a_bank_has_checked_offers_on_two_apps(self):
        out, r = self.make()
        self.assertFalse([p for p in r["pages"] if p.count("/") > 3], "one app per bank today: the bank page is the page")
        two = copy.deepcopy(BASE)
        extra = copy.deepcopy(next(o for o in two["offers"] if o["id"] == "hsbc-premier-bms-bogo"))
        extra.update(id="hsbc-premier-district-bogo", platform="district")
        two["offers"].append(extra)
        out2, r2 = self.make(two, name="two")
        self.assertIn("/bank/hsbc/bookmyshow/", r2["pages"])
        self.assertIn("/bank/hsbc/district/", r2["pages"])
        self.assertNotIn("/bank/axis/district/", r2["pages"])
        t = page(out2, "/bank/hsbc/district/")
        self.assertEqual(re.findall(r'<article class="offer" id="([^"]+)"', t), ["hsbc-premier-district-bogo"])
        self.assertTrue(re.search(r"<title>(.*?)</title>", t).group(1).startswith("HSBC District offer: 2nd ticket free up to ₹750"))
        crumbs = [x for x in ld(t) if x["@type"] == "BreadcrumbList"][0]["itemListElement"]
        self.assertEqual([c["item"] for c in crumbs],
                         ["https://bookmyfdfs.in/", "https://bookmyfdfs.in/bank/hsbc/", "https://bookmyfdfs.in/bank/hsbc/district/"])
        self.assertIn('href="/bank/hsbc/district/"', page(out2, "/bank/hsbc/"))


def snap(day, hour=10):
    s = copy.deepcopy(BASE)
    s["generated_at"] = f"{day}T{hour:02d}:00:00+05:30"
    for o in s["offers"]:
        o["checked_at"] = f"{day}T09:00:00+05:30"
    return s


class Weekly(Plan):
    def test_this_week_article_with_real_dates(self):
        out, r = self.make()
        t = page(out, "/this-week/")
        self.assertIn("Movie ticket offers this week: 23–29 Nov 2026", t)
        art = [x for x in ld(t) if x["@type"] == "Article"][0]
        web = [x for x in ld(t) if x["@type"] == "WebPage"][0]
        vis = re.search(r'<time datetime="([^"]+)" data-stamp>', t).group(1)
        self.assertEqual(art["dateModified"], vis)
        self.assertEqual(web["dateModified"], vis)
        self.assertLessEqual(datetime.fromisoformat(art["datePublished"]), datetime.fromisoformat(art["dateModified"]))
        self.assertEqual(art["datePublished"], g.iso(g._dt(BASE["generated_at"])))       # the week's first export
        self.assertIn(f'first published <time datetime="{art["datePublished"]}">', t)
        self.assertEqual(len(re.findall(r"<tr data-checked", t)), len(MOVIE))
        self.assertIn("Also this week: 6 offers spotted on the web, not yet verified", visible(t))   # decision 168: 6, was 5
        self.assertNotIn("spot-", t)                                                     # spotted: a count and a link only

    def test_finished_weeks_keep_a_permanent_dated_page(self):
        hist = {"2026-11-18": snap("2026-11-18"), "2026-11-25": BASE}
        out, r = self.make(name="wk", history=hist)
        self.assertIn("/this-week/2026-w47/", r["pages"])
        old = page(out, "/this-week/2026-w47/")
        self.assertIn("Movie ticket offers, week of 16–22 Nov 2026", old)
        self.assertNotIn("<tr data-checked", old)                   # an archive isn't re-judged by today's freshness guard
        self.assertNotIn('<span data-next=', old)                    # …nor are its dates moved to the visitor's week
        self.assertIn("Book on Saturdays only</span>", old)
        self.assertIn('href="/this-week/">Week of 23–29 Nov 2026 →', old)
        self.assertIn('href="/this-week/2026-w47/">← Week of 16–22 Nov 2026', page(out, "/this-week/"))
        art = [x for x in ld(old) if x["@type"] == "Article"][0]
        self.assertTrue(art["datePublished"].startswith("2026-11-18T10:00"))
        sm = (out / "sitemap.xml").read_text()
        for pth in ("/this-week/", "/this-week/2026-w47/", "/bookmyshow-offers/", "/district-offers/"):
            self.assertIn(f"https://bookmyfdfs.in{pth}</loc>", sm)

    def test_no_digest_without_offers(self):
        empty = copy.deepcopy(BASE)
        empty["offers"] = []
        out, r = self.make(empty, name="e", spotted=None)
        self.assertNotIn("/this-week/", r["pages"])
        self.assertNotIn('href="/this-week/"', (out / "index.html").read_text())

    def test_week_labels(self):
        self.assertEqual(g.week_label(date(2026, 11, 23)), "23–29 Nov 2026")
        self.assertEqual(g.week_label(date(2026, 11, 30)), "30 Nov – 6 Dec 2026")
        self.assertEqual(g.week_label(date(2026, 12, 28)), "28 Dec 2026 – 3 Jan 2027")
        self.assertEqual(g.week_of(date(2026, 11, 25))[:2], (2026, 48))


class Linking(Plan):
    def test_every_indexable_page_is_two_clicks_from_home(self):
        out, _ = self.make()
        locs = re.findall(r"<loc>https://bookmyfdfs\.in(/[^<]*)</loc>", (out / "sitemap.xml").read_text())
        links = {}
        for p in out.rglob("index.html"):
            path = "/" if p == out / "index.html" else "/" + str(p.parent.relative_to(out)) + "/"
            links[path] = set(h.split("#")[0] for h in re.findall(r'<a [^>]*href="(/[^"]*)"', p.read_text()))
        depth, q = {"/": 0}, deque(["/"])
        while q:
            u = q.popleft()
            for v in links.get(u, ()):
                if v in links and v not in depth:
                    depth[v] = depth[u] + 1
                    q.append(v)
        for loc in locs:
            self.assertLessEqual(depth.get(loc, 99), 2, loc)
        for hub in ("/bookmyshow-offers/", "/district-offers/", "/this-week/"):
            inbound = [u for u, vs in links.items() if hub in vs and u != hub]
            self.assertGreaterEqual(len(inbound), 5, (hub, inbound))

    def test_llms_txt_and_best_card_link_the_hubs(self):
        out, _ = self.make()
        llms = (out / "llms.txt").read_text()
        for pth in ("/bookmyshow-offers/", "/district-offers/", "/this-week/"):
            self.assertIn(f"https://bookmyfdfs.in{pth})", llms)
        best = page(out, "/best-card-for-movie-tickets/")
        self.assertIn('href="/bookmyshow-offers/"', best)

    def test_table_cells_wrap_their_content(self):
        out, _ = self.make()
        t = page(out, "/bookmyshow-offers/")
        self.assertNotRegex(t, r'<td data-l="[^"]*">(?!<span>)')                      # the phone grid needs one child


if __name__ == "__main__":
    unittest.main()


from test_redesign_r1 import Browser, NOW  # noqa: E402


class PlanLayout(Browser, Plan):
    def test_new_pages_never_scroll_sideways(self):
        out, _ = self.make(name="lay")
        body = """var P=['/bookmyshow-offers/','/district-offers/','/this-week/'],W=[360,390,1280],r=[],k=0,J=[];
P.forEach(function(p){W.forEach(function(w){J.push([p,w])})});
function one(){if(k==J.length)return done({r:r});var x=J[k++];load(x[0]+'?fdfs_now=%d',x[1],function(f,d){var s=scroll(d);
r.push([x[0],x[1],s[0]<=s[1],s[1]==x[1]-15]);one()})}one();""" % NOW
        res = self.run_js(out, body, budget=15000)
        self.assertEqual(len(res["r"]), 9)
        for p, w, ok, bar in res["r"]:
            self.assertTrue(ok and bar, (p, w))
