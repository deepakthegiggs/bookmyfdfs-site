"""Owner, 25 Nov: every external link opens in a new tab (and says so to screen readers); internal links don't."""
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_accuracy_s1 import LIVE, Live  # noqa: E402

SITE = "bookmyfdfs.in"


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found, self._cur = [], None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._cur = {"attrs": dict(attrs), "text": ""}

    def handle_data(self, data):
        if self._cur is not None:
            self._cur["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self._cur is not None:
            self.found.append(self._cur)
            self._cur = None


def anchors(html):
    p = Anchors()
    p.feed(html)
    return p.found


def external(href):
    u = urlsplit(href)
    return u.scheme in ("http", "https") and (u.hostname or "").removeprefix("www.") != SITE


class NewTab(Live):
    def test_every_external_link_opens_in_a_new_tab(self):
        out, _ = self.live()
        n = 0
        for page in out.rglob("*.html"):
            for a in anchors(page.read_text()):
                href = a["attrs"].get("href", "")
                if external(href):
                    n += 1
                    self.assertEqual(a["attrs"].get("target"), "_blank", f"{page.relative_to(out)}: {href}")
                    rel = (a["attrs"].get("rel") or "").split()
                    self.assertIn("noopener", rel, href)
                    self.assertIn("noreferrer", rel, href)
                    self.assertIn("opens in a new tab", a["text"], href)
        self.assertGreater(n, 40)

    def test_bank_terms_links_keep_nofollow(self):
        out, _ = self.live()
        for page in out.rglob("*.html"):
            for a in anchors(page.read_text()):
                href = a["attrs"].get("href", "")
                if external(href) and ".bank.in" in href:
                    self.assertIn("nofollow", a["attrs"]["rel"].split(), href)

    def test_internal_links_stay_in_the_tab(self):
        out, _ = self.live()
        for page in out.rglob("*.html"):
            for a in anchors(page.read_text()):
                href = a["attrs"].get("href", "")
                if not external(href):
                    self.assertNotIn("target", a["attrs"], f"{page.relative_to(out)}: {href}")

    def test_whatsapp_share_link(self):
        out, _ = self.live()
        home = (out / "index.html").read_text()
        shares = [a for a in anchors(home) if a["attrs"].get("href", "").startswith("https://wa.me/")]
        self.assertEqual(len(shares), len([o for o in LIVE["offers"] if o["category"] != "events"]))
        for a in shares:
            self.assertEqual(a["attrs"]["target"], "_blank")
            self.assertIn("noopener", a["attrs"]["rel"])
            self.assertIn("Share on WhatsApp", a["text"])
            self.assertIn("(opens in a new tab)", a["text"])

    def test_feeds_carry_no_raw_links(self):
        out, _ = self.live()
        self.assertNotIn("<a ", (out / "changes.xml").read_text())
        self.assertNotRegex((out / "changes.xml").read_text(), r"&lt;a ")
