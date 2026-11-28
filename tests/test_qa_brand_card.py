"""The dateless fallback share card (brand/logo/og-brand.png) uses the V2 palette (decision 139; QA 26 Nov: it still
had the old navy/amber card). Decision 158: it is drawn like the per-page cards (ink stage, one lime line, no
"checked against the official terms", no "Independent" strip). Offline: checks the committed SVG and PNG, no Chrome."""
import re
import struct
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2 = {"#F6F5EE", "#203229", "#435349", "#D5F476", "#4B6629"}
LIME = "#D5F476"


class BrandCard(unittest.TestCase):
    def setUp(self):
        self.svg = (ROOT / "brand/logo/og-brand.svg").read_text(encoding="utf-8")

    def test_svg_uses_only_v2_tokens(self):
        colours = {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}\b", self.svg)}
        self.assertTrue(colours, "no colours found")
        self.assertEqual(colours - V2, set(), "colours outside the V2 palette")
        self.assertIn('<rect width="1200" height="630" fill="#203229"/>', self.svg, "ink stage")

    def test_one_lime_line_on_ink(self):
        # lime text reads on ink (it failed contrast on the old ivory card, hence the old fill-only rule)
        lime = [el for el in re.findall(r"<text\b[^>]*>", self.svg) if LIME in el.upper()]
        self.assertEqual(len(lime), 1, lime)

    def test_says_one_thing_without_the_old_strap_lines(self):
        text = " ".join(re.findall(r"<text[^>]*>(.*?)</text>", self.svg))
        self.assertIn("Movie ticket offers", text)
        self.assertIn("bookmyfdfs.in", text)
        self.assertNotRegex(text, r"(?i)official terms|independent|affiliated|checked")

    def test_dateless_and_countless(self):
        text = " ".join(re.findall(r"<text[^>]*>(.*?)</text>", self.svg))
        self.assertNotRegex(text, r"\d{4}|\btoday\b|\b\d+ offers?\b|₹")

    def test_png_is_1200x630_and_ivory(self):
        data = (ROOT / "brand/logo/og-brand.png").read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        w, h, depth, ctype = struct.unpack(">IIBB", data[16:26])
        self.assertEqual((w, h), (1200, 630))
        # decode the first scanline's first pixel (filter byte + RGB[A]); top-left corner is the ivory page
        idat, i = b"", 8
        while i < len(data):
            n, kind = struct.unpack(">I4s", data[i:i + 8])
            if kind == b"IDAT":
                idat += data[i + 8:i + 8 + n]
            i += 12 + n
        raw = zlib.decompress(idat)
        self.assertEqual(depth, 8)
        # every PNG filter leaves the first pixel of the first scanline as stored (no left/up neighbours)
        self.assertEqual(raw[1:4].hex().upper(), "203229", "top-left pixel is the ink stage")

class Icons(unittest.TestCase):
    """favicon and app icons follow the V2 logo tokens (QA 26 Nov: they were still navy/marigold)."""
    OLD = {"#17142B", "#F2A12E", "#E08A12", "#F5EFE3", "#0E0C1D"}

    def test_no_old_palette_in_icons(self):
        for name in ("favicon.svg", "app-icon-180.svg", "app-icon-192.svg", "app-icon-512.svg"):
            colours = {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}\b", (ROOT / "brand/logo" / name).read_text())}
            self.assertEqual(colours & self.OLD, set(), name)
            self.assertIn("#203229", colours, f"{name}: ink")

    def test_icon_pngs_are_the_ink_tile(self):
        for name, size in (("apple-touch-icon.png", 180), ("app-icon-192.png", 192), ("app-icon-512.png", 512)):
            data = (ROOT / "brand/logo" / name).read_bytes()
            self.assertEqual(struct.unpack(">II", data[16:24]), (size, size), name)
            idat, i = b"", 8
            while i < len(data):
                n, kind = struct.unpack(">I4s", data[i:i + 8])
                if kind == b"IDAT":
                    idat += data[i + 8:i + 8 + n]
                i += 12 + n
            self.assertEqual(zlib.decompress(idat)[1:4].hex().upper(), "203229", f"{name}: ink corner")


if __name__ == "__main__":
    unittest.main()
