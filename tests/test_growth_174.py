"""Decision 174 (growth agent, 28 Nov 2026): bank titles keep the benefit, "SBI credit card" not "SBI Card credit card",
"movie ticket offer" in bank descriptions, and no "cap: see terms" after a flat rupee amount in running text."""
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


def page(out: Path, slug: str) -> str:
    return (out / f"bank/{slug}/index.html").read_text()


def title(out: Path, slug: str) -> str:
    return html.unescape(re.search(r"<title>(.*?)</title>", page(out, slug)).group(1))


def desc(out: Path, slug: str) -> str:
    return html.unescape(re.search(r'<meta name="description" content="(.*?)"', page(out, slug)).group(1))


def answer(out: Path, slug: str) -> str:
    return html.unescape(re.search(r"<strong>Yes\.</strong>(.*?)</", page(out, slug), re.S).group(1))


def sbi_offer(base: dict, oid: str, instrument: str) -> dict:
    o = copy.deepcopy(base)
    o.update(id=oid, issuer="SBI Card", display_name="AURUM Card", instrument=instrument, kind="complimentary",
             value={"free_cap": 250, "free_tickets": 4, "period": "month", "worth": 1000}, cap_text="up to ₹250",
             cap_type="per_ticket", card_variants=["AURUM"], variants_scope="listed", code=None, slug=None)
    return o


def hsbc_premier(fx: dict) -> dict:
    return next(o for o in fx["offers"] if o["id"] == "hsbc-premier-bms-bogo")


class SbiTitle(Base):
    def test_card_issuer_reads_sbi_credit_card(self):
        fx = copy.deepcopy(FIX)
        fx["offers"].append(sbi_offer(hsbc_premier(fx), "sbicard-aurum-bms-complimentary", "credit"))
        out, _, _ = self.build(fx, name="sbi174")
        t = title(out, "sbi-card")
        self.assertTrue(t.startswith("SBI credit card BookMyShow offer: 4 free tickets a month"), t)
        self.assertNotIn("Card credit card", t)

    def test_benefit_stays_when_only_the_cap_is_too_long(self):
        # mixed card types: no card-type title; the capped title is 67 chars, so the benefit alone must stay
        fx = copy.deepcopy(FIX)
        fx["offers"] += [sbi_offer(hsbc_premier(fx), "sbicard-aurum-bms-complimentary", "credit"),
                         sbi_offer(hsbc_premier(fx), "sbicard-aurum-debit-bms-complimentary", "debit")]
        out, _, _ = self.build(fx, name="sbimixed174")
        t = title(out, "sbi-card")
        self.assertEqual(t, "SBI Card BookMyShow offer: 4 free tickets a month · FDFS")


class TitleGuard(Base):
    def test_every_bank_title_is_within_65_as_escaped(self):
        out, _, _ = self.build()
        for p in sorted((out / "bank").glob("*/index.html")):
            raw = re.search(r"<title>(.*?)</title>", p.read_text()).group(1)
            self.assertLessEqual(len(raw), 65, raw)


class Description(Base):
    def test_bank_description_says_movie_ticket_offers_and_counts_movie_offers_only(self):
        out, _, _ = self.build()
        d = desc(out, "hsbc")   # the fixture's HSBC page has 2 movie offers and 1 events offer
        self.assertTrue(d.startswith("Yes: 2 HSBC buy 1 get 1 movie ticket offers on BookMyShow"), d)
        self.assertLessEqual(len(d), 160, d)


class FlatAmount(Base):
    def test_flat_amount_without_a_stated_cap_reads_as_a_sentence(self):
        fx = copy.deepcopy(FIX)
        o = hsbc_premier(fx)
        o.update(kind="flat", value={"flat": 500}, cap_text="cap: see terms", cap_type="unstated")
        out, _, _ = self.build(fx, name="flat174")
        self.assertIn("₹500 off", desc(out, "hsbc"))
        self.assertNotIn("off cap: see terms", desc(out, "hsbc"))
        self.assertIn("gets ₹500 off", answer(out, "hsbc"))
        self.assertNotIn("off cap: see terms", answer(out, "hsbc"))

    def test_other_benefits_keep_their_cap(self):
        out, _, _ = self.build()
        self.assertIn("2nd ticket free up to ₹750", desc(out, "hsbc"))


if __name__ == "__main__":
    unittest.main()
