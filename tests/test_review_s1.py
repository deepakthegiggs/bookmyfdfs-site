"""Tests for the S1 marketing/SEO review fixes (scratchpad/site-marketing-review.md), written first."""
import copy
from datetime import datetime
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
from test_generator import FIX, Base, text_files  # noqa: E402


def visible(html: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>|<head>.*?</head>", " ", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", t)


def ld(html: str) -> list:
    return json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1))["@graph"]


def shown_movie(r):
    held = {o.id for o in r["held"]}
    return [o for o in FIX["offers"] if o["category"] != "events" and o["id"] not in held]


def pages(out: Path):
    return [(p, p.read_text()) for p in sorted(out.rglob("*.html"))]


class P1_OG(Base):
    def test_og_tags_and_cards_carry_real_numbers_never_today(self):
        out, r, _ = self.build()
        for p, t in pages(out):
            if p.name == "404.html":
                continue
            img = re.search(r'<meta property="og:image" content="https://bookmyfdfs\.in(/og/[^"]+\.png)"', t)
            self.assertIsNotNone(img, p)
            for tag in ('property="og:image:alt"', 'property="og:image:width" content="1200"',
                        'property="og:image:height" content="630"', 'name="twitter:card" content="summary_large_image"',
                        'property="og:locale" content="en_IN"'):
                self.assertIn(tag, t, f"{p}: {tag}")
            self.assertTrue((out / img.group(1).lstrip("/")).exists(), img.group(1))
            alt = re.search(r'property="og:image:alt" content="([^"]+)"', t).group(1)
            self.assertNotRegex(alt, r"(?i)\btoday\b")
        # decision 158: the per-page card text (what the PNG renders) is one idea, every number from the page's own data
        held = {o.id for o in r["held"]}
        movie_ids = {o["id"] for o in shown_movie(r)}
        checked = {o["id"]: datetime.fromisoformat(o["checked_at"]).astimezone(g.IST).date() for o in FIX["offers"]}
        whos = {o["id"]: g.who(g.norm(o)) for o in FIX["offers"]}
        for spec in r["og"]:
            text = " ".join(spec["lines"])
            self.assertNotRegex(text, r"(?i)\btoday\b")
            self.assertNotRegex(text, r"(?i)official terms|checked by|offer intelligence|independent|affiliated", spec["name"])
            self.assertNotRegex(text, r"\b20\d\d\b|\d{1,2}:\d{2}|\bIST\b", f"{spec['name']}: no year, no time")
            self.assertIsNone(g.BANNED.search(text), f"{spec['name']}: no claims or urgency")
            self.assertLessEqual(len(spec["hero"]), 2)
            self.assertLessEqual(len(spec["sub"]), 2)
            raw = (out / spec["page"]).read_text()
            page = visible(raw)
            for num in re.findall(r"₹[\d,]+", text):
                self.assertIn(num, page, f"{spec['page']}: OG says {num!r}, the page doesn't")
            for n in re.findall(r"\b(\d+) (?:card |movie )?offers?\b", text):   # a count is the page's own offers, each linked there
                self.assertEqual(int(n), len(spec["ids"]), spec["name"])
                for oid in spec["ids"]:
                    self.assertIn(oid, movie_ids - held, spec["name"])
                    self.assertTrue(f"/offer/{oid}/" in raw or oid in raw or whos[oid] in page, f"{spec['name']}: {oid} not on the page")
            dates = re.findall(r"\b\d{1,2} [A-Z][a-z]{2}\b", text)
            if spec["name"].startswith("offer-"):          # one quiet date, offer cards only: the offer's own check day
                (oid,) = spec["ids"]
                self.assertEqual(spec["date"], f"Checked {g.fmt_dm(checked[oid])}")
                self.assertEqual(dates, [g.fmt_dm(checked[oid])], spec["name"])
            else:
                self.assertEqual((spec["date"], dates), ("", []), spec["name"])

    def test_home_card_counts_movie_offers_not_events(self):
        _, r, _ = self.build()
        home = [s for s in r["og"] if s["page"] == "index.html"][0]
        n_movie = len(shown_movie(r))
        self.assertRegex(" ".join(home["lines"]), rf"^Movie ticket offers {n_movie} (card|movie) offers · ")
        self.assertEqual(len(home["ids"]), n_movie)


class P1_Scope(Base):
    def test_unstated_scope_is_always_select(self):
        payload = copy.deepcopy(FIX)
        payload["offers"] = [o for o in payload["offers"] if o["id"] != "hsbc-allcards-bms-events-10pct"]
        out, _, _ = self.build(payload)
        for p, t in text_files(out):
            for m in re.finditer(r"(.{0,8})HSBC credit cards", t):
                self.assertRegex(m.group(1), r"(?i)select $", f"{p.relative_to(out)}: bare 'HSBC credit cards'")
        self.assertIn("Select HSBC credit cards", visible((out / "index.html").read_text()))
        self.assertIn("Select HSBC credit cards", (out / "best-card-for-movie-tickets/index.html").read_text())
        self.assertIn("Select HSBC credit cards", (out / "changes.xml").read_text())

    def test_scope_all_keeps_plain_label(self):
        o = g.norm([x for x in FIX["offers"] if x["id"] == "hsbc-allcards-bms-events-10pct"][0])
        self.assertEqual(g.who(o), "HSBC credit cards")


class OfferIntelligence(Base):
    """Owner, 25 Nov: every check line names FDFS Offer Intelligence; manual sources aren't published at launch."""

    def test_how_we_check_names_offer_intelligence_honestly(self):
        out, _, _ = self.build()
        t = (out / "how-we-check/index.html").read_text()
        self.assertIn("<title>How FDFS Offer Intelligence checks offers · FDFS</title>", t)
        how = visible(t)
        self.assertIn("reads each official terms page and confirms every detail against its exact words", how)
        self.assertIn("never read ticketing apps automatically", how)

    def test_every_card_has_the_offer_intelligence_line(self):
        out, _, _ = self.build()
        n = 0
        for p, t in pages(out):
            for card in re.findall(r'<article class="offer".*?</article>', t, re.S):
                n += 1
                self.assertIn("Checked by FDFS Offer Intelligence · ", card, p)
                self.assertRegex(card, r"Offer Intelligence · checked \d{1,2} [A-Z][a-z]{2}")
        self.assertGreater(n, 0)

    def test_manual_source_offer_not_published_at_launch(self):
        out, r, _ = self.build()
        self.assertIn("district-pass-bogo", {o.id for o in r["held"]})
        for p, t in text_files(out):
            self.assertNotIn("district-pass-bogo", t, p)

    def test_a_recorded_manual_check_is_labelled_terms_read_by_our_team(self):
        payload = copy.deepcopy(FIX)
        for o in payload["offers"]:
            if o["id"] == "district-pass-bogo":
                o["check_method"] = "manual"
        out, r, _ = self.build(payload)
        card = re.search(r'<article class="offer" id="district-pass-bogo".*?</article>',
                         (out / "index.html").read_text(), re.S).group(0)
        self.assertIn("Checked by FDFS Offer Intelligence (terms read by our team)", visible(card))

    def test_never_by_hand_never_ai(self):
        payload = copy.deepcopy(FIX)
        for o in payload["offers"]:
            if o["id"] == "district-pass-bogo":
                o["check_method"] = "manual"
        for i, pl in enumerate((FIX, payload)):
            out, _, _ = self.build(pl, name=f"x{i}")
            for p, t in text_files(out):
                self.assertNotRegex(t, r"(?i)by hand", p)
                if p.suffix == ".html":
                    copy_ = visible(t) + " ".join(re.findall(r'content="([^"]*)"', t))
                    self.assertNotRegex(copy_, r"\bAI\b|(?i:agentic|artificial intelligence)", p)


class P1_Best(Base):
    def test_answer_states_universe_and_missing_banks(self):
        out, r, _ = self.build()
        t = (out / "best-card-for-movie-tickets/index.html").read_text()
        n = len(shown_movie(r))
        ans = visible(re.search(r'<p class="s-a">(.*?)</p>', t, re.S).group(1))
        self.assertIn(f"Of the {n} movie offers we could confirm from official terms on 25 Nov 2026", ans)
        self.assertIn("Not on this list yet:", visible(t))
        self.assertIn("HDFC", visible(t))
        title = re.search(r"<title>(.*?)</title>", t).group(1)
        self.assertIn("credit card", title.lower())


class P1_Links(Base):
    def test_home_links_every_bank_page(self):
        out, _, _ = self.build()
        home = (out / "index.html").read_text()
        banks = sorted(p.name for p in (out / "bank").iterdir())
        for b in banks:
            self.assertGreaterEqual(home.count(f'href="/bank/{b}/"'), 3, f"/bank/{b}/: card + by-bank row + footer")
        self.assertIn('class="bybank"', home)
        for p, t in pages(out):
            if p.relative_to(out).parts[0] == "v2":
                continue                                       # decision 171: the v2 preview has its own footer and tests
            foot = re.search(r'<footer class="foot">.*?</footer>', t, re.S).group(0)
            for b in banks:
                self.assertIn(f'href="/bank/{b}/"', foot, p)


class P1_Titles(Base):
    def test_titles_query_first_brand_last_short(self):
        out, _, _ = self.build()
        for p, t in pages(out):
            title = re.search(r"<title>(.*?)</title>", t).group(1)
            self.assertTrue(title.endswith(" · FDFS"), f"{p}: {title}")
            self.assertLessEqual(len(title), 65, f"{p}: {len(title)} chars: {title}")
            self.assertFalse(title.startswith("FDFS"), title)
        hsbc = re.search(r"<title>(.*?)</title>", (out / "bank/hsbc/index.html").read_text()).group(1)
        self.assertRegex(hsbc, r"^HSBC (credit card )?BookMyShow offer: 2nd ticket free", hsbc)   # card type: decision 172
        axis = (out / "bank/axis/index.html").read_text()
        self.assertRegex(re.search(r"<title>(.*?)</title>", axis).group(1), r"^Axis Bank (credit card )?District offer")
        desc = re.search(r'<meta name="description" content="([^"]+)"', axis).group(1)
        self.assertNotIn("District, District", desc)
        self.assertIn("Does HSBC have a BookMyShow offer", (out / "bank/hsbc/index.html").read_text())

    def test_no_upi_promise_without_upi_offers(self):
        out, _, _ = self.build()
        home = (out / "index.html").read_text()
        self.assertNotIn("UPI", re.search(r'<meta name="description" content="([^"]+)"', home).group(1))
        self.assertNotIn('id="type-upi"', home, "a filter chip with 0 offers is hidden")
        self.assertNotIn("UPI", visible((out / "about/index.html").read_text()))


class P2(Base):
    def test_no_today_in_static_html(self):
        out, _, _ = self.build()
        for p, t in pages(out):
            m = re.search(r"(?i)\btoday\b", visible(t) + " ".join(re.findall(r'content="([^"]*)"', t)))
            self.assertIsNone(m, f"{p.relative_to(out)} says 'today'")

    def test_bank_tables_link_in_page(self):
        out, _, _ = self.build()
        t = (out / "bank/hsbc/index.html").read_text()
        self.assertNotIn('href="/#', t)
        for oid in re.findall(r'<article class="offer" id="([^"]+)"', t):
            self.assertIn(f'href="#{oid}"', t)

    def test_no_tautological_key_condition(self):
        out, _, _ = self.build()
        self.assertNotIn("Premier cardholders only", visible((out / "best-card-for-movie-tickets/index.html").read_text()))

    def test_breadcrumbs_and_404(self):
        out, _, _ = self.build()
        for p, t in pages(out):
            crumbs = [x for x in ld(t) if x["@type"] == "BreadcrumbList"]
            if p.name == "404.html" or p == out / "index.html":
                self.assertEqual(crumbs, [], p)
            else:
                self.assertGreaterEqual(len(crumbs[0]["itemListElement"]), 2, p)
            banned = ("Product",) if "offer" in p.relative_to(out).parts else ("Offer", "Product")   # L1: Offer only on offer pages
            self.assertFalse(any(x["@type"] in banned for x in ld(t)), p)
        self.assertNotIn('rel="canonical"', (out / "404.html").read_text())

    def test_dataset_markup_for_open_data(self):
        out, _, _ = self.build()
        ds = [x for x in ld((out / "how-we-check/index.html").read_text()) if x["@type"] == "Dataset"]
        self.assertEqual(len(ds), 1)
        d = ds[0]
        self.assertEqual(d["license"], "https://creativecommons.org/licenses/by/4.0/")
        self.assertEqual(d["distribution"][0]["contentUrl"], "https://bookmyfdfs.in/offers.json")
        self.assertRegex(d["dateModified"], r"T\d\d:\d\d:\d\d")

    def test_corrections_meta_promises_no_channel(self):
        out, _, _ = self.build()
        t = (out / "corrections/index.html").read_text()
        desc = re.search(r'<meta name="description" content="([^"]+)"', t).group(1)
        self.assertNotRegex(desc, r"(?i)report|contact|email")

    def test_changes_copy_and_atom(self):
        out, _, _ = self.build()
        ch = visible((out / "changes/index.html").read_text())
        self.assertIn("Tracking since 25 Nov 2026.", ch)
        self.assertNotIn("Terms verified on", ch)
        atom = (out / "changes.xml").read_text()
        for title in re.findall(r"<entry>.*?<title>(.*?)</title>", atom):
            self.assertFalse(title.rstrip().endswith((" on", " the", " a", ",")), title)
        self.assertNotIn("T00:00:00", atom)
        self.assertIn("T11:30:00+05:30", atom)

    def test_home_latest_changes_collapses_first_checks(self):
        out, _, _ = self.build()
        home = visible((out / "index.html").read_text())
        self.assertNotIn("First checked ·", home)
        self.assertRegex(home, r"\d+ offers first checked on 25 Nov 2026")

    def test_bank_page_has_its_own_cards_block(self):
        out, _, _ = self.build()
        t = visible((out / "bank/indusind/index.html").read_text())
        self.assertIn("Which IndusInd cards?", t)
        self.assertNotIn("BIN ranges", t)


class Levers(Base):
    def test_whatsapp_share_and_cite(self):
        out, _, _ = self.build()
        home = (out / "index.html").read_text()
        for oid in re.findall(r'<article class="offer" id="([^"]+)"', home):
            card = re.search(rf'<article class="offer" id="{oid}".*?</article>', home, re.S).group(0)
            self.assertRegex(card, r'href="https://wa\.me/\?text=[^"]+"', oid)
            self.assertIn("Cite this", card)
            self.assertIn("bookmyfdfs.in", re.search(r'data-copy="([^"]*bookmyfdfs[^"]*)"', card).group(1))
        for p, t in text_files(out):
            self.assertIsNone(g.PRELAUNCH.RX.search(t), p)

    def test_which_day_strip(self):
        out, r, _ = self.build()
        home = (out / "index.html").read_text()
        counts = json.loads(re.search(r"data-counts='([^']+)'", home).group(1))
        movie = shown_movie(r)
        any_day = sum(1 for o in movie if "any" in (o.get("days") or []))
        sat_only = sum(1 for o in movie if o.get("days") == ["sat"])
        unnamed = sum(1 for o in movie if not (o.get("days") or []))
        self.assertEqual(counts["sat"], any_day + sat_only + unnamed)
        self.assertEqual(counts["mon"], any_day + unnamed)
        self.assertEqual(len(re.findall(r'<button type="button" class="day(?: none)?" data-day=', home)), 7)

    def test_tickets_line_is_honest(self):
        out, _, _ = self.build()
        home = visible((out / "index.html").read_text())
        self.assertIn("For 2 tickets: 1 free, up to ₹750", home)
        self.assertNotRegex(home, r"(?i)you save|save ₹")


if __name__ == "__main__":
    unittest.main()


class FinalP2(Base):
    def test_og_card_names_the_variant_that_owns_the_cap(self):
        _, r, _ = self.build()
        offers = [g.norm(o) for o in FIX["offers"]]
        for spec in r["og"]:
            if spec["name"] == "home":
                continue
            text = " ".join(spec["lines"])
            for amt in re.findall(r"up to (₹[\d,]+)", text):  # caps; a spend gate's ₹ isn't a cap
                # decision 158: the cap's own offer is on the card, named by its card (or it is that card's own page)
                owners = [o for o in offers if o.id in spec["ids"] and amt in g.cap(o)
                          and (g.who(o) in text or spec["name"].startswith("card-"))]
                self.assertTrue(owners, f"{spec['name']}: {amt} is shown without the card that owns it: {text}")

    def test_og_alt_joins_lines_with_full_stops(self):
        out, r, _ = self.build()
        # alt text is what og_meta would emit for a rendered card
        site = g.Site(ROOT, json.loads((ROOT / "data/site.json").read_text()), datetime.fromisoformat(FIX["generated_at"]), [])
        for spec in r["og"]:
            alt = g.og_alt(spec["lines"])
            # decision 158: the alt says what the image says: the hero (as one phrase), the fact line, the date if any
            self.assertEqual(alt, ". ".join(p.rstrip(":,. ") for p in spec["lines"] if p.strip()) + ".")
            self.assertTrue(alt.startswith(spec["lines"][0]), alt)
            self.assertNotIn(":.", alt)
            self.assertNotRegex(alt, r"\b(for|the|a|on)\. ", "a headline split mid-phrase")

    def test_by_bank_counts_match_filter_counts(self):
        out, _, _ = self.build()
        home = (out / "index.html").read_text()
        row = re.search(r'<p class="bybank">(.*?)</p>', home, re.S).group(1)
        for slug, n in re.findall(r'href="/bank/([a-z-]+)/">[^<(]+\((\d+)\)', row):
            chip = re.search(rf'for="bank-{slug}">[^<]+<span class="n">(\d+)</span>', home)
            self.assertIsNotNone(chip, slug)
            self.assertEqual(n, chip.group(1), f"{slug}: by-bank {n} vs filter {chip.group(1)}")

    def test_bank_titles_all_dated_or_none(self):
        out, _, _ = self.build()
        titles = [re.search(r"<title>(.*?)</title>", p.read_text()).group(1) for p in (out / "bank").rglob("index.html")]
        dated = [bool(re.search(r"\(\d{1,2} [A-Z][a-z]{2}\)", t)) for t in titles]
        self.assertTrue(all(dated) or not any(dated), titles)
        self.assertTrue(all(len(t) <= 65 for t in titles), titles)

    def test_cite_and_share_name_offer_intelligence_the_share_image_does_not(self):
        from urllib.parse import unquote
        out, _, _ = self.build()
        home = (out / "index.html").read_text()
        card = re.search(r'<article class="offer" id="hsbc-premier-bms-bogo".*?</article>', home, re.S).group(0)
        cite = re.search(r'class="cite" type="button" data-copy="([^"]+)"', card).group(1)
        wa = unquote(re.search(r'href="https://wa\.me/\?text=([^"]+)"', card).group(1))
        self.assertIn("checked by FDFS Offer Intelligence", cite)
        self.assertIn("Checked by FDFS Offer Intelligence", wa)
        # decision 158: the share IMAGE no longer names the checker (owner: "nice and clear"); the page, the cite
        # line and the WhatsApp text above still do. The alt text describes the image, so it doesn't either.
        _, r, _ = self.build(name="og")
        for spec in r["og"]:
            self.assertNotIn("Offer Intelligence", g.og_alt(spec["lines"]), spec["name"])
