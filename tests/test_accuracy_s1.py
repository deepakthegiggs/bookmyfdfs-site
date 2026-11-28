"""Tests for the final accuracy check (scratchpad/site-accuracy-check.md), written first. Run on the LIVE export."""
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
from test_generator import Base, text_files  # noqa: E402
from test_review_s1 import visible  # noqa: E402

# The frozen 25 Nov live export these checks were written against. Never data/offers.json: the daily refresh
# changes it, and live-data drift must not block publishing (data that passes the guards publishes).
LIVE = json.loads((ROOT / "tests/fixtures/offers-spotted-base.json").read_text(encoding="utf-8"))


class Live(Base):
    def live(self):
        out, r, _ = self.build(LIVE, name="live", history={"2026-11-25": LIVE})
        return out, r

    def card(self, html, oid):
        return re.search(rf'<article class="offer" id="{oid}".*?</article>', html, re.S).group(0)


class P1(Live):
    def test_day_strip_never_claims_no_day_limit(self):
        out, _ = self.live()
        home = visible((out / "index.html").read_text())
        self.assertNotIn("no day limit", home)
        self.assertRegex(home, r"include 2 offers that don.t name days: .*Check their terms\.")

    def test_best_card_says_saturday_only_not_weekday(self):
        out, _ = self.live()
        import html as h
        t = h.unescape(visible((out / "best-card-for-movie-tickets/index.html").read_text()))
        self.assertNotIn("weekday", t)
        self.assertIn("a Saturday-only booking (1)", t)
        self.assertIn("2 don't state an end date", t)

    def test_freshness_guard_script_is_small_and_wired(self):
        out, _ = self.live()
        home = (out / "index.html").read_text()
        guard = re.search(r"<script data-guard>(.*?)</script>", home, re.S)
        self.assertIsNotNone(guard)
        self.assertLess(len(guard.group(1).encode()), 1024)
        for o in LIVE["offers"]:
            m = re.search(rf'<article class="offer" id="{o["id"]}"[^>]*>', home)
            if m:
                self.assertIn(f'data-checked="{o["checked_at"][:19]}', m.group(0))
                self.assertIn('data-valid-to="', m.group(0))
        self.assertIn('data-next="sat"', home)
        self.assertIn('<p class="o-stale" hidden>', home)


@unittest.skipUnless(g.chrome_path(), "needs headless Chrome")
class P1Browser(Live):
    """The guard really runs: a visitor 8 days later sees 'Not re-checked recently' and today's next Saturday."""

    def run_page(self, out, query):
        port = __import__("socket").socket()
        port.bind(("127.0.0.1", 0))
        p = port.getsockname()[1]
        port.close()
        srv = subprocess.Popen([sys.executable, "-m", "http.server", str(p), "--bind", "127.0.0.1", "--directory", str(out)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            import time
            time.sleep(0.8)
            prof = self.tmp / "prof"
            r = subprocess.run([g.chrome_path(), "--headless=new", "--disable-gpu", f"--user-data-dir={prof}",
                                "--virtual-time-budget=3000", "--dump-dom", f"http://127.0.0.1:{p}/{query}"],
                               capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
            return r.stdout
        finally:
            srv.terminate()
            srv.wait(timeout=10)

    def ms(self, *args):
        return int(datetime(*args, tzinfo=timezone.utc).timestamp() * 1000)

    def test_fresh_after_the_saturday_moves_to_the_next_one(self):
        out, _ = self.live()
        dom = self.run_page(out, f"?fdfs_now={self.ms(2026, 11, 29, 6)}")    # Sun 29 Nov: still fresh (< 7 days)
        self.assertNotIn(" stale", dom)
        self.assertIn(">5 Dec<", dom)
        self.assertNotIn(">28 Nov<", dom)

    def test_stale_hides_the_hero_rule_marks_rows_and_freezes_dates(self):
        out, _ = self.live()
        q = f"?fdfs_now={self.ms(2026, 12, 3, 12)}"                         # 8+ days after the check
        dom = self.run_page(out, q)
        self.assertIn('class="offer stale"', dom)
        self.assertIn("Not re-checked recently · see terms", dom)
        self.assertRegex(dom, r'<span data-sat-hero[^>]*hidden')
        self.assertNotIn(">5 Dec<", dom, "a stale offer's date must not be rewritten")
        bank = self.run_page(out, "bank/hsbc/" + q)
        rows = re.findall(r"<tr[^>]*data-checked[^>]*>", bank)
        self.assertTrue(rows)
        self.assertTrue(all('class="stale"' in r for r in rows), rows)
        self.assertIn("<small> · Not re-checked recently</small>", bank)

    def test_ended_wins_after_valid_to(self):
        out, _ = self.live()
        dom = self.run_page(out, "bank/hsbc/" + f"?fdfs_now={self.ms(2027, 1, 2, 6)}")   # HSBC offers end 31 Dec 2026
        self.assertIn("Ended · see terms", dom)
        self.assertIn("<small> · Ended</small>", dom)

    def test_fresh_visit_keeps_build_text(self):
        out, _ = self.live()
        dom = self.run_page(out, f"?fdfs_now={self.ms(2026, 11, 26, 6)}")
        self.assertNotIn(" stale", dom)
        self.assertIn(">28 Nov<", dom)


class P2(Live):
    def test_events_card_makes_no_day_claim(self):
        out, _ = self.live()
        card = self.card((out / "bank/hsbc/index.html").read_text(), "hsbc-allcards-bms-events-10pct")
        self.assertNotIn("Days not stated", card)

    def test_no_other_cards_contradiction(self):
        out, _ = self.live()
        self.assertNotIn("Other HSBC cards: not in these terms", (out / "bank/hsbc/index.html").read_text())

    def test_premier_names_mastercard(self):
        out, _ = self.live()
        self.assertIn("HSBC Premier Mastercard", visible((out / "index.html").read_text()))

    def test_spend_gate_says_calendar_months(self):
        out, _ = self.live()
        home = visible((out / "index.html").read_text())
        self.assertNotIn("in the past 3 months", home)
        self.assertIn("in the previous 3 calendar months", home)

    def test_hsbc_meta_and_axis_og_carry_the_key_rule(self):
        out, r = self.live()
        desc = re.search(r'<meta name="description" content="([^"]+)"', (out / "bank/hsbc/index.html").read_text()).group(1)
        # decision 163: the meta is clipped to whole sentences under 160 characters. It may leave the Saturday offer out,
        # but it never states it without its rule, and llms.txt carries the full line
        if "₹250" in desc:
            self.assertIn("book on a Saturday", desc)
        self.assertRegex((out / "llms.txt").read_text(), r"bank/hsbc/\):.*₹250 \(book on a Saturday\)")
        # decision 158: the share card is one idea (subject + count); the key rule lives on the page it links to
        axis = [s for s in r["og"] if s["name"] == "bank-axis"][0]
        self.assertEqual(axis["hero"], ["Axis movie offers"])
        self.assertIn("₹25,000", visible((out / "bank/axis/index.html").read_text()))

    def test_saturday_quota_is_on_the_saturday_page(self):
        # decision 149: the home hero is one verdict line; the Saturday rule and its quota live on /offers-on/saturday/
        out, _ = self.live()
        sat = visible((out / "offers-on/saturday/index.html").read_text())
        self.assertIn("Only the first 2,000 HSBC Credit Cardholders booking on a Saturday can avail the offer", sat)
        self.assertIn('href="/offers-on/saturday/"', (out / "index.html").read_text())

    def test_events_strip_says_app(self):
        out, _ = self.live()
        strip = visible(re.search(r'<aside class="also".*?</aside>', (out / "index.html").read_text(), re.S).group(0))
        self.assertIn("BookMyShow app", strip)

    def test_changes_and_404_say_updated(self):
        out, _ = self.live()
        for p in ("changes/index.html", "404.html"):
            self.assertRegex((out / p).read_text(), r"Updated <time", p)

    def test_licence_excludes_quoted_terms(self):
        out, _ = self.live()
        note = "Quoted terms remain their owners'"
        for p in ("index.html", "disclosures/index.html"):
            self.assertIn(note, visible((out / p).read_text()).replace("&#x27;", "'"), p)
        self.assertIn(note, (out / "llms.txt").read_text())
        self.assertIn("license_note", json.loads((out / "offers.json").read_text()))

    def test_grammar_plural_cards_get(self):
        out, _ = self.live()
        t = visible((out / "bank/hsbc/index.html").read_text())
        self.assertNotIn("credit cards gets", t)
        self.assertIn("credit cards get", t)


if __name__ == "__main__":
    unittest.main()
