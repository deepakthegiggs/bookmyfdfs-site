"""Decision 134 (owner, 25 Nov 2026): FDFS = Film · Deals · Friends · Seats (supersedes 042's "Date").
Run: python3 -m unittest discover -s tests -v"""
import html
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "gen"))
import fdfs_site as g  # noqa: E402
from test_generator import FIX, Base, text_files  # noqa: E402

OLD = re.compile(r"film\s*[·,]?\s*date\b|date\s*[·,]\s*friends|first day first show", re.I)


def assets():
    """Brand assets that ship or render: logo SVGs (incl. alt), the manifest, OG sources, the tagline path, site config."""
    for p in sorted((ROOT / "brand/logo").rglob("*")):
        if p.is_file() and p.suffix in (".svg", ".webmanifest", ".html", ".txt", ".json"):
            yield p
    yield ROOT / "data/site.json"
    yield ROOT / "gen/site.css"


class Rebrand134(Base):
    def test_no_built_page_or_asset_says_film_date(self):
        out, _, _ = self.build()
        for p, t in text_files(out):
            self.assertIsNone(OLD.search(html.unescape(t)), p.relative_to(out))
        for p in assets():
            self.assertIsNone(OLD.search(p.read_text(encoding="utf-8")), p.relative_to(ROOT))

    def test_kicker_spells_film_deals_friends_seats(self):
        out, _, _ = self.build()
        home = (out / "index.html").read_text(encoding="utf-8")
        beats = re.search(r'<p class="beats" aria-label="([^"]+)">(.*?)</p>', home).groups()
        self.assertEqual(beats[0], "FDFS: Film, Deals, Friends, Seats")
        self.assertEqual(re.findall(r"<span>(\w+)</span>", beats[1]), ["Film", "Deals", "Friends", "Seats"])
        self.assertIn("Film · Deals · Friends · Seats</h2>", home)
        self.assertIn('<p class="foot-tag">Film · Deals · Friends · Seats</p>', home)

    def test_hero_verdict_is_a_fact_from_the_data(self):
        """Decision 149 replaced the four tiles with one verdict line in the ticket; it stays a computed fact."""
        out, _, _ = self.build()
        home = html.unescape((out / "index.html").read_text(encoding="utf-8"))
        ans = re.sub(r"<[^>]+>", "", re.search(r'<p class="s-a">(.*?)</p>', home, re.S).group(1))
        cfg = json.loads((ROOT / "data/site.json").read_text(encoding="utf-8"))
        now, offers = g.load(ROOT / "tests/fixtures/offers-d86d5dc.json")
        movie = [o for o in offers if g.publishable(o, now, cfg)[0] and o.is_movie]
        top = max([o for o in movie if g.freshness(o, now) == "fresh"], key=lambda o: (g.cap_num(o), o.id))
        self.assertEqual(ans, f"{len(movie)} checked movie offers · highest cap ₹{g.cap_num(top):,} "
                              f"({g.short_card(top)}, {g.app_name(top)})")

    def test_what_is_fdfs_is_one_short_band(self):
        out, _, _ = self.build()
        home = (out / "index.html").read_text(encoding="utf-8")
        band = re.search(r'<section class="what what-band".*?</section>', home, re.S).group(0)
        self.assertNotIn("beat-tiles", home)
        self.assertIn("Film · Deals · Friends · Seats</h2>", band)
        self.assertEqual(len(re.findall(r'<p class="what-a">', band)), 1)
        self.assertIn('href="/how-we-check/"', band)
        self.assertIn('href="/about/"', band)

    def test_no_offers_no_verdict_clause(self):
        empty = dict(FIX, offers=[])
        out, _, _ = self.build(payload=empty, name="empty")
        self.assertNotIn("highest cap", (out / "index.html").read_text(encoding="utf-8"))

    def test_jsonld_manifest_llms_use_the_new_expansion(self):
        out, _, _ = self.build()
        home = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('"FDFS Film Deals Friends Seats"', home)
        self.assertIn("Film · Deals · Friends · Seats", json.loads((out / "site.webmanifest").read_text())["name"])
        self.assertIn("FDFS (Film · Deals · Friends · Seats)", (out / "llms.txt").read_text(encoding="utf-8"))
        for m in ("light", "dark", "mono"):
            self.assertIn('aria-label="FDFS: Film, Deals, Friends, Seats"',
                          (ROOT / f"brand/logo/fdfs-lockup-{m}.svg").read_text())


if __name__ == "__main__":
    unittest.main()
