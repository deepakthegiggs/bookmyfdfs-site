"""Decision 158: share cards say one thing, big, and never overflow (owner, 26 Nov: "nice and clear").
Offline checks on the card specs, plus a headless-Chrome check that every line of real and stress cards sits inside
the 1200x630 card after the fit step (long RBL multi-card names, lakh-sized rupee amounts)."""
import copy
import http.server
import json
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
from test_generator import FIX, Base  # noqa: E402

RBL6 = ["Platinum Choice", "Blockbuster", "Fun +", "MoneyTap Black", "Movies & More", "Shoprite"]


def rbl(variants, scope="listed", cap_text="up to ₹100", kind="pct", value=None):
    o = copy.deepcopy(next(x for x in FIX["offers"] if x["id"] == "hsbc-premier-bms-bogo"))
    o.update(id="rbl-test", issuer="RBL Bank", card_variants=variants, variants_scope=scope, cap_text=cap_text, kind=kind,
             value=value or {"pct": 10, "cap": 100})
    o.pop("network", None)
    return g.norm(o)


class Spec(unittest.TestCase):
    def test_offer_card_is_benefit_then_card_and_app_then_one_date(self):
        o = g.norm(next(x for x in FIX["offers"] if x["id"] == "hsbc-premier-bms-bogo"))
        s = g.og_offer(o)
        self.assertEqual(s["hero"], ["2nd ticket free", "up to ₹750"])
        self.assertEqual(s["sub"], ["HSBC Premier Mastercard · BookMyShow"])
        self.assertEqual(s["date"], f"Checked {g.fmt_dm(o.checked_at.astimezone(g.IST).date())}")
        self.assertNotRegex(s["date"], r"\d{4}|:|IST")

    def test_long_listed_card_names_are_counted_never_cut_or_widened(self):
        s = g.og_offer(rbl(RBL6))
        self.assertEqual(s["sub"], ["RBL Bank · 6 listed cards · BookMyShow"])
        self.assertIn("Platinum Choice / Blockbuster / Fun + / MoneyTap Black", s["lines"][1], "the alt keeps every name")
        short = g.og_offer(rbl(["Insignia"]))
        self.assertEqual(short["sub"], ["RBL Bank Insignia · BookMyShow"])
        sel = g.og_offer(rbl([], scope="unstated"))
        self.assertTrue(sel["sub"][0].startswith("Select RBL Bank"), "an unstated scope stays 'Select …'")

    def test_lines_wrap_to_at_most_two(self):
        long = "RBL Bank Platinum Choice Blockbuster Fun Plus MoneyTap Black Movies and More Shoprite Super Card · BookMyShow"
        s = g.og_spec("x", ["Bandhan Mastercard Platinum Plus World Elite Debit Card"], long, ["x"])
        self.assertEqual(len(s["hero"]), 2)
        self.assertEqual(len(s["sub"]), 2)
        self.assertEqual(" ".join(s["hero"]), "Bandhan Mastercard Platinum Plus World Elite Debit Card", "no word dropped")
        self.assertEqual(" ".join(s["sub"]).replace("  ", " "), long.replace(" · ", " · "), "no word dropped")

    def test_no_cap_means_no_invented_one(self):
        o = rbl(["Insignia"], cap_text="", kind="flat", value={"flat": 500})
        self.assertEqual(g.og_offer(o)["hero"], ["₹500 off"])

    def test_svg_has_no_old_strap_lines_and_one_lime_line(self):
        site = g.Site(ROOT, json.loads((ROOT / "data/site.json").read_text()), datetime.fromisoformat(FIX["generated_at"]), [])
        for spec in (g.og_offer(rbl(RBL6)), g.og_hub("home", "Movie ticket offers", [rbl(["Insignia"])])):
            svg = g.og_svg(site, spec)
            text = " ".join(re.findall(r"<text[^>]*>(.*?)</text>", svg))
            self.assertNotRegex(text, r"(?i)official terms|checked by|independent|affiliated|\b20\d\d\b|\d:\d\d")
            self.assertIn("bookmyfdfs.in", text)
            self.assertEqual(len([t for t in re.findall(r"<text\b[^>]*>", svg) if g.OG_LIME in t]), 1, spec["name"])


MEASURE = ("<script>document.fonts.ready.then(function(){setTimeout(function(){var r=[];"
           "[].forEach.call(document.querySelectorAll('svg text'),function(t){var b=t.getBBox();"
           "r.push({t:t.textContent,x:b.x,y:b.y,w:b.width,h:b.height,s:+t.getAttribute('font-size'),k:t.getAttribute('data-fit')})});"
           "var p=document.createElement('pre');p.id='m';p.textContent=JSON.stringify(r);document.body.appendChild(p)},50)})</script>")


@unittest.skipUnless(g.chrome_path(), "needs headless Chrome")
class Fit(Base):
    def measure(self, specs):
        site = g.Site(ROOT, json.loads((ROOT / "data/site.json").read_text()), datetime.fromisoformat(FIX["generated_at"]), [])
        tmp = g.og_stage(ROOT, specs, site, MEASURE)

        class Q(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=str(tmp), **k)

            def log_message(self, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Q)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        res = {}
        for s in specs:
            prof = tempfile.mkdtemp()
            r = subprocess.run([g.chrome_path(), "--headless=new", "--disable-gpu", f"--user-data-dir={prof}",
                                "--virtual-time-budget=3000", "--window-size=1200,630", "--dump-dom",
                                f"http://127.0.0.1:{srv.server_address[1]}/{s['name']}.html"],
                               capture_output=True, text=True, timeout=60)
            m = re.search(r'<pre id="m">(.*?)</pre>', r.stdout, re.S)
            self.assertIsNotNone(m, s["name"])
            res[s["name"]] = json.loads(m.group(1).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
        return res

    def test_real_and_stress_cards_fit_inside_the_card(self):
        _, r, _ = self.build()
        specs = [x for x in r["og"] if x["name"] in ("home", "offer-hsbc-premier-bms-bogo", "best-card")]
        specs += [g.og_offer(rbl(RBL6)) | {"name": "rbl6"},
                  g.og_offer(rbl(["MoneyTap", "Paisabazaar Duet Plus"])) | {"name": "rbl2"},
                  g.og_spec("lakh", ["2nd ticket free", "up to ₹1,00,000 a month"], "HSBC Premier Mastercard · District",
                            ["x"], "Checked 26 Nov", benefit=True),
                  # far past any real cap: must still fit (it shrinks), the size floor below doesn't apply
                  g.og_spec("extreme", ["2nd ticket free", "up to ₹1,00,000 a month on each of two bookings"],
                            "RBL Bank Platinum Choice Blockbuster Fun Plus MoneyTap Black Movies and More Shoprite · BookMyShow",
                            ["x"], "Checked 26 Nov", benefit=True),
                  g.og_spec("hub-long", ["IDFC FIRST Wealth Diamond Reserve Select Classic movie offers"],
                            "26 card offers · BookMyShow, District, PVR INOX & Cinépolis", ["x"])]
        for name, boxes in self.measure(specs).items():
            self.assertTrue(boxes, name)
            for b in boxes:
                self.assertGreaterEqual(b["x"], 71, f"{name}: {b['t']!r} starts off the card")
                self.assertLessEqual(b["x"] + b["w"], 1129, f"{name}: {b['t']!r} overflows ({b['x'] + b['w']:.0f} px)")
                self.assertGreaterEqual(b["y"], 0, name)
                self.assertLessEqual(b["y"] + b["h"], 630, name)
            hero = [b for b in boxes if b["k"] == "hero"]
            self.assertTrue(hero, name)
            if name != "extreme":
                self.assertTrue(all(b["s"] >= 64 for b in hero), f"{name}: the hero stays big ({hero})")
            self.assertEqual(len({b["s"] for b in hero}), 1, f"{name}: hero lines share one size")
            stack = sorted([b for b in boxes if b["y"] < 500], key=lambda b: b["y"])
            for a, b in zip(stack, stack[1:]):            # no line sits on another
                self.assertLessEqual(a["y"] + a["h"] * 0.8, b["y"], f"{name}: {a['t']!r} overlaps {b['t']!r}")


if __name__ == "__main__":
    unittest.main()
