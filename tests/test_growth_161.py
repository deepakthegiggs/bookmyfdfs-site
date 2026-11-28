"""Decision 161 (growth agent, 26 Nov 2026): 'buy 1 get 1' in bank descriptions, quotable bank lines in llms.txt."""
import copy
import html
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
from test_generator import FIX, Base  # noqa: E402


def desc(out: Path, slug: str) -> str:
    t = (out / f"bank/{slug}/index.html").read_text()
    return html.unescape(re.search(r'<meta name="description" content="([^"]+)"', t).group(1))


class BuyOneGetOne(Base):
    def test_all_bogo_banks_say_buy_1_get_1_with_the_exact_benefit(self):
        out, _, _ = self.build()
        for slug in ("axis", "hsbc", "indusind"):
            d = desc(out, slug)
            self.assertRegex(d, r"^Yes: \d+ .+ buy 1 get 1 offers? on ", d)
            self.assertIn("2nd ticket free up to ₹", d)   # the precise benefit and cap stay
        # an events-only extra offer (HSBC 10% live events) doesn't block the wording: it isn't a movie offer
        self.assertIn("HSBC buy 1 get 1 offers on BookMyShow", desc(out, "hsbc"))

    def test_mixed_benefits_never_say_buy_1_get_1(self):
        fx = copy.deepcopy(FIX)
        for o in fx["offers"]:
            if o["id"] == "hsbc-premier-bms-bogo":
                o["kind"], o["value"] = "pct", {"pct": 10}
        out, _, _ = self.build(fx, name="mixed")
        d = desc(out, "hsbc")
        self.assertNotIn("buy 1 get 1", d)
        self.assertIn("buy 1 get 1", desc(out, "axis"))

    def test_titles_lead_with_the_bank_and_benefit(self):
        # 161 left titles alone; decision 172 adds the card type, so only the shape is pinned here
        out, _, _ = self.build()
        t = re.search(r"<title>(.*?)</title>", (out / "bank/hsbc/index.html").read_text()).group(1)
        self.assertRegex(t, r"^HSBC (credit card )?BookMyShow offer: 2nd ticket free", t)


class LlmsBankLines(Base):
    def test_each_bank_line_is_the_pages_own_description(self):
        out, _, _ = self.build()
        llms = (out / "llms.txt").read_text()
        for p in sorted((out / "bank").glob("*/index.html")):
            slug = p.parent.name
            line = re.search(rf"^- \[[^\]]+ offers\]\(https://bookmyfdfs\.in/bank/{slug}/\)(.*)$", llms, re.M)
            self.assertIsNotNone(line, slug)
            # decision 163: the meta holds the first whole sentences of the same text, under 160 characters
            self.assertTrue(line.group(1).startswith(": " + desc(out, slug)), (slug, line.group(1)))
            self.assertLessEqual(len(desc(out, slug)), 160, slug)

    def test_no_spotted_or_unverified_text_in_bank_lines(self):
        out, _, _ = self.build()
        for line in (out / "llms.txt").read_text().splitlines():
            if "/bank/" in line:
                self.assertNotRegex(line.lower(), r"spotted|unverified|save ₹|hurry|today only|telegram")



class MetaLength(Base):
    def test_every_meta_description_fits_a_search_snippet(self):
        """Decision 163: whole sentences, at most 160 characters, never cut mid-word."""
        out, _, _ = self.build()
        for p in out.rglob("*.html"):
            m = re.search(r'<meta name="description" content="([^"]+)"', p.read_text())
            if not m:
                continue
            d = html.unescape(m.group(1))
            self.assertLessEqual(len(d), 160, (str(p.relative_to(out)), d))
            self.assertTrue(d.endswith((".", "…", "?", "!", ")")) or len(d) < 160, (str(p.relative_to(out)), d))


if __name__ == "__main__":
    unittest.main()
