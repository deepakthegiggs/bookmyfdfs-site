"""L1 (decision 141): a stable page per offer at /offer/<id>/, with every term, the exact quotes, the dated check and
the change history; Offer JSON-LD only for live offers and only with strings the page shows; ended or withdrawn offers
keep their page as a noindex record."""
import copy
import html
import json
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
from test_generator import FIX, Base  # noqa: E402
from test_review_s1 import ld, visible  # noqa: E402


def page(out, oid):
    return (out / "offer" / oid / "index.html").read_text()


def vis(t):
    return re.sub(r"\s+", " ", html.unescape(visible(t)))


class Live(Base):
    def setUp(self):
        super().setUp()
        self.out, self.r, _ = self.build()
        self.shown = [g.norm(o) for o in FIX["offers"] if o["id"] not in {h.id for h in self.r["held"]}]

    def test_every_shown_offer_has_a_page_in_the_sitemap(self):
        sm = (self.out / "sitemap.xml").read_text()
        self.assertTrue(self.shown)
        for o in self.shown:
            self.assertIn(f"<loc>https://bookmyfdfs.in/offer/{o.id}/</loc>", sm)
            t = page(self.out, o.id)
            self.assertNotIn('name="robots"', t)
            self.assertIn(f'<link rel="canonical" href="https://bookmyfdfs.in/offer/{o.id}/">', t)

    def test_receipt_states_every_term_and_unknowns_as_unknown(self):
        for o in self.shown:
            v = vis(page(self.out, o.id))
            for label in ("Benefit", "Cap", "Cards", "Days", "Booking or show day", "Valid", "Limit or quota",
                          "Minimum tickets", "Code"):
                self.assertRegex(v, rf"\b{label}\b", (o.id, label))
            self.assertIn(g.cap(o), v)
            self.assertIn(g.basis_text(o), v)
            self.assertIn(g.validity_text(o), v)
            self.assertNotIn("None None", v)
            self.assertNotRegex(v, r"\bnull\b|Minimum null")
        sel = vis(page(self.out, "hsbc-select-bms-saturday-bogo"))
        self.assertIn("Select HSBC credit cards (the terms don't list which)", sel)
        self.assertIn("The day you book counts", sel)
        ax = vis(page(self.out, "axis-myzone-district-bogo"))
        self.assertIn("No end date stated in the terms", ax)

    def test_exact_quotes_check_stamp_and_terms_link(self):
        for o in self.shown:
            t = page(self.out, o.id)
            v = vis(t)
            for qv in o.quotes.values():
                for q in qv if isinstance(qv, list) else [qv]:   # list-valued quotes: each span shown on its own
                    self.assertIn(re.sub(r"\s+", " ", q).strip(), v, o.id)
            self.assertNotIn("['", v)
            self.assertIn(f"Checked {g.fmt_stamp(o.checked_at)}", v)
            self.assertRegex(t, rf'href="{re.escape(html.escape(o.source_url))}" target="_blank" rel="nofollow noopener noreferrer"')

    def test_offer_jsonld_matches_the_visible_text(self):
        for o in self.shown:
            t = page(self.out, o.id)
            v = vis(t)
            offers = [x for x in ld(t) if x["@type"] == "Offer"]
            self.assertEqual(len(offers), 1, o.id)
            x = offers[0]
            self.assertEqual(x["url"], f"https://bookmyfdfs.in/offer/{o.id}/")
            self.assertIn(x["name"], v)
            self.assertIn(x["description"], v)
            self.assertIn(x["offeredBy"]["name"], v)
            if o.valid_to:
                self.assertEqual(x["validThrough"], o.valid_to.isoformat())
                self.assertIn(g.fmt_day(o.valid_to), v)
            else:
                self.assertNotIn("validThrough", x)
            crumbs = [y for y in ld(t) if y["@type"] == "BreadcrumbList"][0]["itemListElement"]
            self.assertEqual(crumbs[0]["name"], "Offers")
            self.assertEqual(crumbs[-1]["item"], x["url"])
            for c in crumbs:
                self.assertIn(c["name"], v)

    def test_linked_from_cards_bank_pages_and_app_hubs(self):
        home = (self.out / "index.html").read_text()
        for o in self.shown:
            link = f'href="/offer/{o.id}/"'
            self.assertIn(link, home, o.id)
            if o.is_bank:
                self.assertIn(link, (self.out / f"bank/{o.slug}/index.html").read_text(), o.id)
            k = g.app_key(o.platform)
            if o.is_movie and k:
                self.assertIn(link, (self.out / g.hub_path(k).strip("/") / "index.html").read_text(), o.id)

    def test_history_comes_through_the_one_reader(self):
        real = g.offer_history
        self.addCleanup(setattr, g, "offer_history", real)
        g.offer_history = lambda oid, changes: [{"date": "2026-11-20", "at": "x", "id": oid, "type": "changed",
                                                 "label": "Changed", "text": "Reader seam works."}]
        out, _, _ = self.build(name="seam")
        self.assertIn("Reader seam works.", page(out, "hsbc-premier-bms-bogo"))

    def test_first_check_is_in_the_history(self):
        v = vis(page(self.out, "hsbc-premier-bms-bogo"))
        self.assertIn("First checked · 25 Nov 2026", v)


class Ended(Base):
    def test_withdrawn_and_expired_keep_a_noindex_record(self):
        day2 = copy.deepcopy(FIX)
        day2["generated_at"] = "2027-01-02T06:00:00+00:00"
        for o in day2["offers"]:
            o["checked_at"] = "2027-01-02T11:30:00+05:30"
        day2["offers"] = [o for o in day2["offers"] if o["id"] != "axis-select-district-bogo"]   # withdrawn
        out, _, _ = self.build(day2, name="ended", history={"2026-11-25": FIX, "2027-01-02": day2})
        sm = (out / "sitemap.xml").read_text()
        for oid, why in (("axis-select-district-bogo", "could not be re-confirmed"), ("hsbc-premier-bms-bogo", "It ended on 31 Dec 2026")):
            t = page(out, oid)
            self.assertIn('<meta name="robots" content="noindex,follow">', t, oid)
            self.assertNotIn('"Offer"', re.search(r'<script type="application/ld\+json">(.*?)</script>', t, re.S).group(1))
            self.assertNotIn(f"/offer/{oid}/", sm)
            v = vis(t)
            self.assertIn("No longer shown", v)
            self.assertIn(why, v)
            self.assertIn("Last checked", v)
        live = page(out, "indusind-eazydiner-platinum-bms-bogo")
        self.assertIn(f"/offer/indusind-eazydiner-platinum-bms-bogo/", sm)
        self.assertNotIn('name="robots"', live)

    def test_a_page_in_state_without_any_record_stays_as_a_stub(self):
        st = self.tmp / "st.json"
        st.write_text(json.dumps({"/offer/old-thing/": {"hash": "x", "lastmod": "2026-11-01", "modified": "2026-11-01T00:00:00+05:30", "noindex": False}}))
        out, r, _ = self.build(name="stub", state=st)
        t = (out / "offer/old-thing/index.html").read_text()
        self.assertIn('content="noindex,follow"', t)
        self.assertNotIn("/offer/old-thing/", (out / "sitemap.xml").read_text())


class Freshness(unittest.TestCase):
    NOW = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)

    def o(self, hours, **kw):
        return g.norm({"id": "x", "checked_at": (self.NOW - timedelta(hours=hours)).isoformat(), **kw})

    def test_policy(self):
        self.assertEqual(g.freshness(self.o(47), self.NOW), "fresh")
        self.assertEqual(g.freshness(self.o(49), self.NOW), "needs_recheck")
        self.assertEqual(g.freshness(self.o(24 * 7 + 1), self.NOW), "unconfirmed")
        short = {"valid_from": "2026-11-20", "valid_to": "2026-11-30"}       # 11 days: the 24 h rule
        self.assertEqual(g.freshness(self.o(25, **short), self.NOW), "needs_recheck")
        self.assertEqual(g.freshness(self.o(23, **short), self.NOW), "fresh")

    def test_published_value_only_makes_it_stricter_and_missing_is_computed(self):
        self.assertEqual(g.freshness(self.o(1, freshness="needs_recheck"), self.NOW), "needs_recheck")
        self.assertEqual(g.freshness(self.o(60, freshness="fresh"), self.NOW), "needs_recheck")
        self.assertEqual(g.freshness(self.o(1), self.NOW), "fresh")


class Recheck(Base):
    def test_needs_recheck_page_says_check_the_terms(self):
        p = copy.deepcopy(FIX)
        for o in p["offers"]:
            if o["id"] == "hsbc-premier-bms-bogo":
                o["checked_at"] = "2026-11-22T11:30:00+05:30"
        out, _, _ = self.build(p, name="rc")
        v = vis(page(out, "hsbc-premier-bms-bogo"))
        self.assertIn("Checked 3 days ago · check terms first", v)      # 22 Nov 11:30 -> 25 Nov 11:30 IST
        self.assertNotIn("check the terms before paying", v)              # decision 158: the bot's shorter line replaced it
        self.assertNotIn("check terms first", vis(page(out, "indusind-eazydiner-platinum-bms-bogo")))
        self.assertEqual(g.recheck_line(g.norm({"checked_at": "2026-11-24T10:00:00+05:30"}),
                                        g._dt("2026-11-25T09:00:00+05:30")), "Checked 1 day ago · check terms first")
        self.assertEqual(g.recheck_line(g.norm({"checked_at": "2026-11-20T10:00:00+05:30"}),
                                        g._dt("2026-11-25T09:00:00+05:30")), "Checked 4 days ago · check terms first")

    def test_needs_recheck_never_in_best_or_the_hero(self):
        p = copy.deepcopy(FIX)
        for o in p["offers"]:
            if o["id"] in ("hsbc-premier-bms-bogo", "hsbc-select-bms-saturday-bogo"):
                o["checked_at"] = "2026-11-22T11:30:00+05:30"
        out, _, _ = self.build(p, name="rc2")
        best = (out / "best-card-for-movie-tickets/index.html").read_text()
        self.assertNotIn("hsbc-premier-bms-bogo", best)
        self.assertNotIn("hsbc-select-bms-saturday-bogo", best)
        hero = re.search(r'<p class="s-a">.*?</p>', (out / "index.html").read_text(), re.S).group(0)
        self.assertNotIn("HSBC", hero)                       # the verdict's top pick is a fresh offer only (D4)


if __name__ == "__main__":
    unittest.main()
