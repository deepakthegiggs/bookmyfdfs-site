"""Phase 2 pages (decisions 144-148): per-card pages, Best card by benefit type, weekday views, the pillar guide, and the
"Expired on" badge with current alternatives. Real data only: no data, no page."""
import copy
import gzip
import html
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
from test_generator import FIX, Base  # noqa: E402
from test_review_s1 import ld, pages, visible  # noqa: E402

CARDS = ("axis-my-zone", "axis-select", "hsbc-premier", "indusind-eazydiner-platinum")
NEW = [f"/card/{c}/" for c in CARDS] + ["/offers-on/saturday/", "/guide/how-movie-card-offers-work/"]


def read(out, path):
    return (out / path.strip("/") / "index.html").read_text()


def vis(t):
    return re.sub(r"\s+", " ", html.unescape(visible(t)))


def shown(r):
    held = {o.id for o in r["held"]}
    return [g.norm(o) for o in FIX["offers"] if o["id"] not in held]


class Built(Base):
    def setUp(self):
        super().setUp()
        self.out, self.r, _ = self.build()

    # ---------------------------------------------------------------- which pages exist
    def test_exactly_the_pages_the_data_supports(self):
        built = set(self.r["pages"])
        for p in NEW:
            self.assertIn(p, built)
        self.assertEqual(sorted(p for p in built if p.startswith("/card/")), sorted(f"/card/{c}/" for c in CARDS))
        # unstated ("select HSBC credit cards") and all-cards scopes never get a card page
        self.assertFalse(any(p.startswith("/card/hsbc-") and p != "/card/hsbc-premier/" for p in built))
        # only Saturday is named by a booking-day rule; every other day would equal the every-day set
        self.assertEqual([p for p in built if p.startswith("/offers-on/")], ["/offers-on/saturday/"])

    def test_unique_titles_and_descriptions(self):
        seen_t, seen_d = {}, {}
        for p, t in pages(self.out):
            if p.name == "404.html" or 'content="noindex' in t:
                continue
            ti = re.search(r"<title>(.*?)</title>", t).group(1)
            de = re.search(r'<meta name="description" content="([^"]*)"', t).group(1)
            self.assertNotIn(ti, seen_t, f"{p} repeats the title of {seen_t.get(ti)}")
            self.assertNotIn(de, seen_d, f"{p} repeats the description of {seen_d.get(de)}")
            seen_t[ti], seen_d[de] = p, p

    # ---------------------------------------------------------------- card pages
    def test_card_page_answers_first_and_treats_apps_equally(self):
        for c in CARDS:
            t = read(self.out, f"/card/{c}/")
            ans = vis(re.search(r'<p class="s-a">(.*?)</p>', t, re.S).group(1)).strip()
            self.assertTrue(ans.startswith("Yes: "), (c, ans))
            heads = re.findall(r'<h2 id="h-(bms|district)">On (BookMyShow|District)</h2>', t)
            self.assertEqual([h[1] for h in heads], ["BookMyShow", "District"], c)   # both apps, same block, same order
            v = vis(t)
            self.assertNotRegex(v, r"(?i)apply now|best app|winner")

    def test_card_page_shows_the_deciding_facts_and_links(self):
        for o in shown(self.r):
            if not (o.is_movie and o.variants_scope == "listed" and o.variants):
                continue
            for var in o.variants:
                t = read(self.out, g.card_path_of(o, var))
                v = vis(t)
                for label in ("Cap", "Days", "Minimum tickets", "Monthly limit", "Booking or show day"):
                    self.assertIn(label, v, (o.id, label))
                self.assertIn(g.cap(o), v)
                self.assertIn(f"Checked by {g.CHECKER} · {g.fmt_stamp(o.checked_at)}", v)
                label, q = g.deciding_clause(o)
                self.assertIn(f"“{q}”", v)
                self.assertIn(f'href="{g.offer_path(o.id)}"', t)
                self.assertIn(f'href="/bank/{o.slug}/"', t)
                self.assertRegex(t, rf'href="{re.escape(html.escape(o.source_url))}" target="_blank" rel="nofollow noopener noreferrer"')

    def test_card_title_date_is_the_real_check_date_and_no_year(self):
        for c in CARDS:
            t = read(self.out, f"/card/{c}/")
            title = html.unescape(re.search(r"<title>(.*?)</title>", t).group(1))
            self.assertIn("25 Nov", title)                         # the fixture's checks are on 25 Nov (IST)
            self.assertNotRegex(title, r"\b20\d\d\b", title)
            stamp = re.search(r"<time datetime=\"([^\"]+)\" data-stamp>", t).group(1)
            self.assertTrue(stamp.startswith("2026-11-25"), stamp)

    def test_card_page_scope_wording_is_never_wider_than_the_terms(self):
        t = vis(read(self.out, "/card/hsbc-premier/"))
        self.assertNotIn("live events", re.search(r"<main.*?</main>", read(self.out, "/card/hsbc-premier/"), re.S).group(0))  # QA F1
        p = copy.deepcopy(FIX)
        for o in p["offers"]:
            if o["id"] == "hsbc-allcards-bms-events-10pct":
                o["category"] = "card"                                                    # an all-cards MOVIE offer
        allc = vis(read(self.build(p, name="allc")[0], "/card/hsbc-premier/"))
        self.assertIn("The terms say all HSBC credit cards, so this card too", allc)       # scope "all": stated
        self.assertIn("don't list which: check yours is included", t)                      # scope "unstated": conditional
        main = re.search(r"<main.*?</main>", read(self.out, "/card/axis-select/"), re.S).group(0)
        self.assertNotIn("HSBC Premier", vis(main))

    def test_bank_and_offer_pages_link_the_card_pages(self):
        for c in CARDS:
            bank = c.split("-")[0]
            self.assertIn(f'href="/card/{c}/"', read(self.out, f"/bank/{bank}/"))
        self.assertIn('href="/card/hsbc-premier/"', read(self.out, "/offer/hsbc-premier-bms-bogo/"))

    # ---------------------------------------------------------------- weekday
    def test_weekday_page_says_which_day_counts(self):
        t = read(self.out, "/offers-on/saturday/")
        v = vis(t)
        self.assertIn("Movie ticket offers that work on Saturday · FDFS", t)
        self.assertIn("Booking day or show day?", v)
        self.assertIn("The day you book counts. The show can be any day", v)
        self.assertIn("1 only when you book on a Saturday", v)
        self.assertIn("2 that work every day", v)
        self.assertIn("Days not stated", v)
        # the Saturday-only offer is there, the unstated-day offers are not in the table
        self.assertIn('id="hsbc-select-bms-saturday-bogo"', t)
        tbl = re.search(r"<table.*?</table>", t, re.S).group(0)
        self.assertNotIn("axis", tbl.lower())

    # ---------------------------------------------------------------- guide
    def test_guide_quotes_only_live_terms_and_dates_each_one(self):
        t = read(self.out, "/guide/how-movie-card-offers-work/")
        live = shown(self.r)
        spans = set()
        for o in live:
            for qv in o.quotes.values():
                spans.update(qv if isinstance(qv, list) else [qv])
            spans.update(c.get("quote") for c in o.raw.get("condition_codes") or [])
        qs = re.findall(r'<blockquote class="o-quote"><p>“(.*?)”</p><cite>(.*?)</cite>', t, re.S)
        self.assertGreaterEqual(len(qs), 6)
        for q, cite in qs:
            self.assertIn(html.unescape(q), spans, "a guide quote that isn't in the live terms")
            self.assertRegex(cite, r'href="/offer/[^"]+/"')
            self.assertRegex(cite, r"Checked \d{1,2} [A-Z][a-z]{2} \d{4}")

    def test_guide_answers_questions_as_plain_headings(self):
        t = read(self.out, "/guide/how-movie-card-offers-work/")
        h2 = re.findall(r'<h2 id="g-[a-z]+">(.*?)</h2>', t)
        self.assertIn("Why did my card offer fail at checkout?", [html.unescape(x) for x in h2])
        self.assertIn("Does the booking day or the show day count?", [html.unescape(x) for x in h2])
        self.assertTrue(all(x.endswith("?") for x in h2))
        types = {x["@type"] for x in ld(t)}
        self.assertNotIn("FAQPage", types)
        self.assertNotIn("Question", t.split("</head>")[0])

    def test_guide_has_no_numbers_of_its_own(self):
        """Every ₹ amount or count in the guide's own prose comes from a quote: strip the quotes, nothing is left."""
        t = read(self.out, "/guide/how-movie-card-offers-work/")
        body = re.search(r'<div class="prose guide">(.*?)</div>', t, re.S).group(1)
        own = re.sub(r"<blockquote.*?</blockquote>", " ", body, flags=re.S)
        self.assertNotRegex(vis(own), r"₹\s?\d|\d+%|\b\d{2,}\b")

    # ---------------------------------------------------------------- Best card
    def test_best_groups_by_benefit_type_with_a_verdict_and_order_line(self):
        t = read(self.out, "/best-card-for-movie-tickets/")
        v = vis(t)
        h2 = re.findall(r'<h2 id="h-[^"]+">(.*?)</h2>', t)
        self.assertIn("2nd ticket free", h2)
        self.assertFalse([h for h in h2 if " on BookMyShow" in h or " on District" in h], h2)   # no per-app groups
        self.assertIn(g.BEST_ORDER, v)
        self.assertIn('href="/how-we-check/">How we check</a>', t)
        self.assertRegex(v, r"\d+ checked offers on BookMyShow and District\. Stated caps run from ₹200 to ₹750")
        self.assertNotRegex(v, r"(?i)apply now")
        # rows follow the stated order: highest cap first, whatever the app
        sec = re.search(r'<h2 id="h-2nd-ticket-free">.*?</table>', t, re.S).group(0)
        caps = [int(x.replace(",", "")) for x in re.findall(r'data-l="Cap"><span>up to ₹([\d,]+)', sec)]
        self.assertEqual(caps, sorted(caps, reverse=True))
        self.assertIn('href="/card/hsbc-premier/"', sec)

    # ---------------------------------------------------------------- markup, links, crawl, budget, wording
    def test_jsonld_matches_the_visible_text(self):
        for p in NEW:
            t = read(self.out, p)
            v = vis(t)
            graph = ld(t)
            self.assertNotIn("Offer", {x["@type"] for x in graph}, p)        # Offer markup lives on /offer/ pages only
            crumbs = [x for x in graph if x["@type"] == "BreadcrumbList"][0]["itemListElement"]
            self.assertEqual(crumbs[-1]["item"], "https://bookmyfdfs.in" + p)
            for c in crumbs:
                self.assertIn(c["name"], v, p)
            for il in [x for x in graph if x["@type"] == "ItemList"]:
                for it in il["itemListElement"]:
                    who_, rest = it["name"].split(" on ", 1)
                    self.assertIn(who_, v, p)
                    for part in rest.split(": ", 1)[1].split(", ", 1):
                        self.assertIn(part, v, p)
                    self.assertTrue((self.out / it["url"].replace("https://bookmyfdfs.in/", "") / "index.html").exists())
            web = [x for x in graph if x["@type"] == "WebPage"][0]
            stamp = re.search(r'<time datetime="([^"]+)" data-stamp>', t).group(1)
            self.assertEqual(web["dateModified"], stamp, p)

    def test_crawlable_with_js_off(self):
        """The answer, the tables and every link are in the static HTML: drop every script and they're all there."""
        for p in NEW:
            t = re.sub(r"<script.*?</script>", "", read(self.out, p), flags=re.S)
            self.assertIn('<p class="s-a">', t)
            self.assertGreater(len(vis(t)), 800, p)
            self.assertNotIn(" hidden>", re.search(r"<main.*?</main>", t, re.S).group(0).replace('<p class="o-stale" hidden>', ""), p)

    def test_links_open_in_a_new_tab_only_when_external(self):
        for p in NEW:
            for tag in re.findall(r"<a\s[^>]*>", read(self.out, p)):
                href = html.unescape(re.search(r'href="([^"]*)"', tag).group(1))
                host = urlparse(href).hostname or ""
                if href.startswith("http") and host != "bookmyfdfs.in":
                    self.assertIn('target="_blank"', tag, (p, tag))
                    self.assertIn("noopener noreferrer", tag)
                else:
                    self.assertNotIn("target=", tag, (p, tag))

    def test_banned_and_prelaunch_wording(self):
        bad = re.compile(g.BANNED.pattern + r"|apply now|first day first show|sameAs", re.I)
        for p in NEW:
            t = read(self.out, p)
            m = bad.search(re.sub(r'<script type="application/ld\+json">.*?</script>', "", t, flags=re.S))
            self.assertIsNone(m, (p, m and m.group(0)))
            self.assertIsNone(g.PRELAUNCH.RX.search(t), p)

    def test_page_budget(self):
        css = len(gzip.compress((self.out / "assets/site.css").read_bytes()))
        for p in NEW:
            total = len(gzip.compress(read(self.out, p).encode())) + css
            self.assertLessEqual(total, 20 * 1024, (p, total))

    def test_internal_links_footer_llms_sitemap(self):
        sm = (self.out / "sitemap.xml").read_text()
        llms = (self.out / "llms.txt").read_text()
        for p in NEW:
            self.assertIn(f"<loc>https://bookmyfdfs.in{p}</loc>", sm)
            self.assertIn(f"https://bookmyfdfs.in{p})", llms)
        for f, t in pages(self.out):
            if f.relative_to(self.out).parts[0] == "v2":
                continue                                       # decision 171: the v2 preview has its own footer and tests
            foot = re.search(r'<footer class="foot">.*?</footer>', t, re.S).group(0)
            for p in NEW:
                if p.startswith("/card/"):
                    continue                                   # card pages: linked from bank, offer and Best pages (budget)
                self.assertIn(f'href="{p}"', foot, f)
        for c in CARDS:
            self.assertIn(f'href="/card/{c}/"', read(self.out, "/best-card-for-movie-tickets/") + read(self.out, f"/bank/{c.split('-')[0]}/"))


class NoDataNoPage(Base):
    def test_no_offers_no_new_pages(self):
        p = copy.deepcopy(FIX)
        p["offers"] = []
        out, r, _ = self.build(p, name="empty")
        self.assertFalse([x for x in r["pages"] if x.startswith(("/card/", "/offers-on/", "/guide/"))])
        self.assertNotIn("/card/", (out / "llms.txt").read_text())

    def test_unstated_and_all_scopes_make_no_card_page(self):
        p = copy.deepcopy(FIX)
        p["offers"] = [o for o in p["offers"] if o.get("variants_scope") in ("unstated", "all")]
        out, r, _ = self.build(p, name="scopes")
        self.assertFalse([x for x in r["pages"] if x.startswith("/card/")])
        self.assertFalse((out / "card").exists())

    def test_only_every_day_offers_make_no_weekday_page(self):
        p = copy.deepcopy(FIX)
        p["offers"] = [o for o in p["offers"] if o["id"] != "hsbc-select-bms-saturday-bogo"]
        out, r, _ = self.build(p, name="everyday")
        self.assertFalse([x for x in r["pages"] if x.startswith("/offers-on/")])
        self.assertNotIn("/offers-on/", (out / "index.html").read_text())

    def test_a_named_weekday_gets_its_own_page_only_for_that_day(self):
        p = copy.deepcopy(FIX)
        for o in p["offers"]:
            if o["id"] == "axis-select-district-bogo":
                o["days"], o["day_basis"] = ["fri"], "show"
        out, r, _ = self.build(p, name="fri")
        self.assertEqual(sorted(x for x in r["pages"] if x.startswith("/offers-on/")), ["/offers-on/friday/", "/offers-on/saturday/"])
        self.assertIn("1 only for Friday shows", vis(read(out, "/offers-on/friday/")))

    def test_cards_sharing_one_offer_set_get_no_page_and_long_lists_fold(self):
        """Decision 144 anti-doorway: cards whose offers are exactly the same as another card's are the same page with a
        swapped name, so neither gets one (the bank page lists them). A 3+ card list shows 2 and a count on the card."""
        p = copy.deepcopy(FIX)
        for o in p["offers"]:
            if o["id"] == "indusind-eazydiner-platinum-bms-bogo":
                o["card_variants"] = ["Eazydiner Platinum", "Legend", "Pinnacle"]
        out, r, _ = self.build(p, name="shared")
        self.assertFalse([x for x in r["pages"] if x.startswith("/card/indusind-")])
        self.assertIn("/card/hsbc-premier/", r["pages"])
        card = re.search(r'<article class="offer" id="indusind-eazydiner-platinum-bms-bogo".*?</article>',
                         (out / "index.html").read_text(), re.S).group(0)
        self.assertIn('<span aria-hidden="true">IndusInd Eazydiner Platinum / Legend + 1 more</span>', card)
        self.assertIn('<span class="sr">IndusInd Eazydiner Platinum / Legend / Pinnacle</span>', card)
        self.assertIn("Cards: Eazydiner Platinum, Legend, Pinnacle", card)               # the full list in Details

    def test_guide_sections_need_a_live_example(self):
        p = copy.deepcopy(FIX)
        p["offers"] = [o for o in p["offers"] if o["id"] != "indusind-eazydiner-platinum-bms-bogo"]   # the only min-tickets quote
        out, _, _ = self.build(p, name="nomin")
        self.assertNotIn("Do I need to buy 2 tickets?", read(out, "/guide/how-movie-card-offers-work/"))


class Expired(Base):
    def test_expired_offer_says_expired_on_and_links_alternatives(self):
        day2 = copy.deepcopy(FIX)
        day2["generated_at"] = "2027-01-02T06:00:00+00:00"
        for o in day2["offers"]:
            o["checked_at"] = "2027-01-02T11:30:00+05:30"
        out, _, _ = self.build(day2, name="exp", history={"2026-11-25": FIX, "2027-01-02": day2})
        t = read(out, "/offer/hsbc-premier-bms-bogo/")
        v = vis(t)
        self.assertIn("Expired on 31 Dec 2026", v)                       # a past year is spelled out
        self.assertIn("Current offers instead", v)
        self.assertIn('href="/offer/indusind-eazydiner-platinum-bms-bogo/"', t)   # same app (HSBC has nothing live)
        self.assertIn('content="noindex,follow"', t)
        self.assertNotIn("/card/hsbc-premier/", (out / "sitemap.xml").read_text())
        self.assertFalse((out / "card/hsbc-premier").exists())          # the card page goes with its last offer

    def test_withdrawn_offer_says_withdrawn_and_links_the_same_bank(self):
        day2 = copy.deepcopy(FIX)
        day2["offers"] = [o for o in day2["offers"] if o["id"] != "axis-select-district-bogo"]
        out, _, _ = self.build(day2, name="wd", history={"2026-11-24": FIX, "2026-11-25": day2})
        t = read(out, "/offer/axis-select-district-bogo/")
        self.assertIn("Withdrawn", vis(t))
        self.assertIn('href="/offer/axis-myzone-district-bogo/"', t)    # same bank first


from test_redesign_r1 import Browser, NOW  # noqa: E402


class Layout(Browser):
    def test_new_pages_never_scroll_sideways(self):
        out, _, _ = self.build(name="lay")
        paths = ["/card/hsbc-premier/", "/card/indusind-eazydiner-platinum/", "/offers-on/saturday/",
                 "/guide/how-movie-card-offers-work/", "/best-card-for-movie-tickets/"]
        body = """var P=%s,W=[320,390],r=[],k=0,J=[];P.forEach(function(p){W.forEach(function(w){J.push([p,w])})});
function one(){if(k==J.length)return done({r:r});var x=J[k++];load(x[0]+'?fdfs_now=%d',x[1],function(f,d){var s=scroll(d);
r.push([x[0],x[1],s[0]<=s[1],s[1]==x[1]-15]);one()})}one();""" % (str(paths).replace("'", '"'), NOW)
        res = self.run_js(out, body, budget=20000)
        self.assertEqual(len(res["r"]), len(paths) * 2)
        for p, w, ok, bar in res["r"]:
            self.assertTrue(ok and bar, (p, w))


if __name__ == "__main__":
    unittest.main()
