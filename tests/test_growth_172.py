"""Decision 172 (growth agent, 27 Nov 2026): bank titles name the card type when every movie offer shares it."""
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


def title(out: Path, slug: str) -> str:
    t = (out / f"bank/{slug}/index.html").read_text()
    return html.unescape(re.search(r"<title>(.*?)</title>", t).group(1))


class CardTypeInTitle(Base):
    def test_all_credit_bank_says_credit_card(self):
        out, _, _ = self.build()
        t = title(out, "hsbc")
        self.assertTrue(t.startswith("HSBC credit card BookMyShow offer: 2nd ticket free"), t)
        self.assertLessEqual(len(t), 65, t)

    def test_every_bank_title_stays_within_65_and_says_card_type_only_when_true(self):
        out, _, _ = self.build()
        offers = {o["id"]: o for o in FIX["offers"]}
        for p in sorted((out / "bank").glob("*/index.html")):
            raw = re.search(r"<title>(.*?)</title>", p.read_text()).group(1)
            self.assertLessEqual(len(raw), 65, raw)
            t = html.unescape(raw)
            for word in ("credit", "debit"):
                if f" {word} card " in t:
                    slug = p.parent.name
                    page = p.read_text()
                    ids = [i for i in offers if f'id="{i}"' in page]
                    movie = [offers[i] for i in ids if offers[i].get("category") != "events"]
                    self.assertTrue(movie, slug)
                    self.assertTrue(all(o.get("instrument") == word for o in movie), f"{slug}: {t}")

    def test_mixed_card_types_say_neither(self):
        fx = copy.deepcopy(FIX)
        hs = [o for o in fx["offers"] if o["issuer"] == "HSBC" and o.get("category") != "events"]
        self.assertGreaterEqual(len(hs), 2)
        hs[-1]["instrument"] = "debit"
        out, _, _ = self.build(fx, name="mixed172")
        t = title(out, "hsbc")
        self.assertNotIn("credit card", t)
        self.assertNotIn("debit card", t)
        self.assertTrue(t.startswith("HSBC BookMyShow offer"), t)

    def test_all_debit_bank_says_debit_card(self):
        fx = copy.deepcopy(FIX)
        for o in fx["offers"]:
            if o["issuer"] == "HSBC":
                o["instrument"] = "debit"
        out, _, _ = self.build(fx, name="debit172")
        self.assertTrue(title(out, "hsbc").startswith("HSBC debit card BookMyShow offer"), title(out, "hsbc"))

    def test_which_cards_line_follows_the_card_type(self):
        fx = copy.deepcopy(FIX)
        for o in fx["offers"]:
            if o["issuer"] == "HSBC":
                o["instrument"], o["variants_scope"], o["card_variants"] = "debit", "all", []
        out, _, _ = self.build(fx, name="debitall172")
        page = html.unescape((out / "bank/hsbc/index.html").read_text())
        self.assertIn("all HSBC debit cards, per the terms.", page)
        self.assertNotIn("all HSBC credit cards", page)


if __name__ == "__main__":
    unittest.main()
