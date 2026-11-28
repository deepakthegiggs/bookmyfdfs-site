"""Decision 164 (growth agent, 26 Nov 2026): share an offer with friends, and save its day to the calendar.

The owner: "give easy options for folks to share it with their friends or loved ones on these offers".
Share text comes from verified fields only; no Telegram or bot link; no tracking parameter; nothing is sent anywhere
by Add to calendar (the browser builds the .ics)."""
import html
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
from test_redesign_r1 import NOW, VERIFIED, Browser, R1  # noqa: E402

BAD = re.compile(r"t\.me|telegram|utm_|fbclid|gclid|[?&]ref=|spotted|unverified", re.I)


class Static(R1):
    def test_every_verified_card_has_whatsapp_and_share(self):
        t = (self.site() / "index.html").read_text()
        for oid in VERIFIED:
            c = self.card(t, oid)
            wa = re.search(r'href="(https://wa\.me/\?text=[^"]+)"', c).group(1)
            text = parse_qs(urlparse(html.unescape(wa)).query)["text"][0]
            self.assertIn(f"https://bookmyfdfs.in/#{oid}", text)
            self.assertNotRegex(text, BAD)
            b = re.search(r'<button class="share js-only" type="button" data-share="([^"]+)" data-url="([^"]+)">', c)
            self.assertIsNotNone(b, oid)
            self.assertEqual(html.unescape(b.group(2)), f"https://bookmyfdfs.in/#{oid}")
            self.assertNotRegex(html.unescape(b.group(1)), BAD)

    def test_spotted_leads_get_no_share_button(self):
        t = (self.site() / "index.html").read_text()
        for c in re.findall(r'<article class="spot[^"]*".*?</article>', t, re.S):
            self.assertNotIn("data-share", c)

    def test_bank_and_offer_pages_have_a_share_row(self):
        out = self.site()
        bank = (out / "bank/hsbc/index.html").read_text()
        row = re.search(r'<div class="wrap shr".*?</div>', bank, re.S).group(0)
        self.assertIn("https://wa.me/?text=", row)
        self.assertIn('data-url="https://bookmyfdfs.in/bank/hsbc/"', row)
        self.assertNotRegex(html.unescape(row), BAD)
        self.assertIn("₹250 (book on a Saturday)", html.unescape(row))    # a rule never drops out of shared text
        for p in (out / "offer").glob("*/index.html"):
            t = p.read_text()
            if 'name="robots" content="noindex' in t:
                self.assertNotIn('class="wrap shr"', t, "an ended offer isn't shared")
                continue
            self.assertIn('class="wrap shr"', t, p)

    def test_add_to_calendar_only_where_a_day_or_end_date_exists(self):
        out = self.site()
        sat = (out / "offer/hsbc-select-bms-saturday-bogo/index.html").read_text()
        b = re.search(r'<button[^>]*data-ics="([a-z]+)" data-k="([a-z ]*)" data-to="([\d-]*)"', sat)
        self.assertEqual(b.groups(), ("day", "sat", "2026-12-31"))
        self.assertIn("Add to calendar", sat)
        self.assertIn("text/calendar", sat)                          # the builder ships only with offer pages
        self.assertNotIn("text/calendar", (out / "index.html").read_text())

    def test_no_js_shows_no_dead_button(self):
        css = (self.site("c") / "assets/site.css").read_text()
        self.assertIn("html:not(.js) .js-only{display:none}", css)


class Phone(Browser):
    W = (320, 360, 390, 768, 1280)

    def test_share_targets_are_44px_and_nothing_scrolls_sideways(self):
        out = self.site()
        res = self.run_js(out, """var r=[],J=[],P=['/','/bank/hsbc/','/offer/hsbc-select-bms-saturday-bogo/','/offers-on/saturday/'],W=%s;
P.forEach(function(p){W.forEach(function(w){J.push([p,w])})});var k=0;
function one(){if(k==J.length)return done({r:r});var j=J[k++];load(j[0]+'?fdfs_now=%d',j[1],function(f,d){
var s=[].filter.call(d.querySelectorAll('.share'),function(e){return e.offsetParent!==null}).map(function(e){var b=e.getBoundingClientRect();return [Math.round(b.height),Math.round(b.right)]});
var cw=d.documentElement.clientWidth,wide=[],gs=d.defaultView.getComputedStyle;function scroller(e){for(var p=e.parentElement;p&&p!==d.body;p=p.parentElement){var o=gs(p).overflowX;if(o=='auto'||o=='scroll')return true}return false}[].forEach.call(d.querySelectorAll('body *'),function(e){var b=e.getBoundingClientRect();
if(b.width&&b.right>cw&&!scroller(e))wide.push((e.tagName+'.'+(typeof e.className=='string'?e.className:'')+' '+Math.round(b.right*10)/10).slice(0,80))});
r.push({p:j[0],w:j[1],sc:scroll(d),s:s.slice(0,6),cw:cw,wide:wide.slice(0,6),label:txt(d.querySelector('[data-share] .sl'))});one()},1200)}one();""" % (list(self.W), NOW),
                          budget=30000)
        for x in res["r"]:
            self.assertLessEqual(x["sc"][0], x["sc"][1], x)
            self.assertEqual(x["wide"], [], x)       # nothing pokes past the right edge (scrolling strips and tables scroll on purpose)
            self.assertTrue(x["s"], x)
            for h, right in x["s"]:
                self.assertGreaterEqual(h, 44, x)
                self.assertLessEqual(right, x["cw"], x)
            self.assertIn(x["label"], ("Share", "Copy link"), x)   # headless Chrome has no share sheet: Copy link

    def test_best_offer_is_on_the_first_screen_of_a_phone(self):
        """Decision 162: the hero's verdict ticket (the best checked offer) shows without scrolling at 360 and 390 px."""
        out = self.site()
        res = self.run_js(out, """var r=[],W=[360,390],k=0;function one(){if(k==W.length)return done({r:r});var w=W[k++];
load('/?fdfs_now=%d',w,function(f,d){var t=d.querySelector('.ticket');var b=t.getBoundingClientRect();
r.push({w:w,top:Math.round(b.top),bottom:Math.round(b.bottom)});one()},740)}one();""" % NOW, budget=12000)
        for x in res["r"]:
            self.assertLess(x["bottom"], 740, x)

    def test_add_to_calendar_builds_the_next_saturday(self):
        out = self.site()
        res = self.run_js(out, """load('/offer/hsbc-select-bms-saturday-bogo/?fdfs_now=%d',390,function(f,d,w){
w.URL.createObjectURL=function(b){w.__b=b;return '#'};w.HTMLAnchorElement.prototype.click=function(){};d.querySelector('[data-ics]').click();
var lab=txt(d.querySelector('[data-ics] .sl'));w.__b.text().then(function(t){done({ics:t,label:lab})})});""" % NOW)
        self.assertIn("DTSTART;VALUE=DATE:20261128", res["ics"])           # Wed 25 Nov -> Sat 28 Nov
        self.assertIn("DTEND;VALUE=DATE:20261129", res["ics"])
        self.assertIn("SUMMARY:Book: Select HSBC credit cards on BookMyShow", res["ics"])
        self.assertIn("URL:https://bookmyfdfs.in/offer/hsbc-select-bms-saturday-bogo/", res["ics"])
        self.assertEqual(res["label"], "✓ Saved for 28 Nov")


if __name__ == "__main__":
    unittest.main()
