"""Owner bugs, 25 Nov: the 'Which day?' strip must be a real filter, and its numbers must read as DATES, with the
offer count as a caption that matches the filtered list exactly."""
import json
import re
import subprocess
import sys
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
from test_accuracy_s1 import LIVE, Live  # noqa: E402

MOVIE = [o for o in LIVE["offers"] if o["category"] != "events"]
KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def visible_on(o, day):
    days = o.get("days") or []
    return not days or "any" in days or day in days          # not stated -> stays visible (labelled)


def n_on(day, offers=MOVIE):
    return sum(1 for o in offers if visible_on(o, day))


def caption(n):
    return "No offers" if n == 0 else f"{n} offer{'s' if n != 1 else ''}"


BUILD_DAY = datetime.fromisoformat(LIVE["generated_at"]).astimezone(g.IST).date()


class Static(Live):
    def strip(self, out):
        home = (out / "index.html").read_text()
        return re.search(r'<div class="days-wrap" data-days-filter.*?>All days</button>', home, re.S).group(0)

    def test_heading_and_next_seven_dates_from_build_day(self):
        out, _ = self.live()
        s = self.strip(out)
        self.assertIn("Which day are you booking?", s)
        buttons = re.findall(r'<button type="button" class="day(?: none)?"[^>]*>.*?</button>', s, re.S)
        self.assertEqual(len(buttons), 7)
        for i, b in enumerate(buttons):
            d = BUILD_DAY + timedelta(days=i)
            k = KEYS[d.weekday()]
            n = n_on(k)
            self.assertIn(f'data-date="{d.isoformat()}"', b)
            self.assertIn(f'data-day="{k}"', b)
            self.assertIn("disabled", b)                                    # no JS: static, never a fake button
            self.assertIn('aria-pressed="false"', b)
            text = re.sub(r"<[^>]+>", " ", b)
            self.assertRegex(text, rf"\b{d.day}\b")                         # the big number is the date…
            self.assertIn(f"{d:%b}", text)                                  # …with its month
            self.assertIn(caption(n), text)                                 # and the count is a caption
            self.assertIn(f'aria-label="{d:%a} {d.day} {d:%b}, {caption(n).lower() if n == 0 else caption(n)}"', b)
        self.assertIn('class="day-all"', s)
        counts = json.loads(re.search(r"data-counts='([^']+)'", s).group(1))
        self.assertEqual(counts, {k: n_on(k) for k in KEYS})

    def test_note_says_counts_include_unnamed_days(self):
        out, _ = self.live()
        home = (out / "index.html").read_text()
        unnamed = sum(1 for o in MOVIE if not (o.get("days") or []))
        self.assertRegex(re.sub(r"<[^>]+>", " ", home), rf"include {unnamed} offers? that don.t name days")

    def test_cards_carry_their_booking_days(self):
        out, _ = self.live()
        home = (out / "index.html").read_text()
        for o in MOVIE:
            want = "any" if "any" in (o.get("days") or []) else " ".join(d for d in (o.get("days") or []))
            self.assertRegex(home, rf'<article class="offer" id="{o["id"]}"[^>]*data-days="{want}"')


@unittest.skipUnless(g.chrome_path(), "needs headless Chrome")
class Browser(Live):
    HARNESS = """<!doctype html><body><pre id="o"></pre><script>
var f=document.createElement('iframe');f.width=%(w)d;f.height=900;f.src='/?fdfs_now=%(now)d';
f.onload=function(){var d=f.contentDocument,cs=d.createElement('style');cs.textContent='::-webkit-scrollbar{width:15px;height:15px}';d.head.appendChild(cs);
setTimeout(function(){var W=d.querySelector('[data-days-filter]'),r={days:[]};
function vis(){return [].filter.call(d.querySelectorAll('.offer'),function(o){return o.offsetParent!==null}).map(function(o){return o.id}).sort()}
var B=[].slice.call(W.querySelectorAll('button.day'));
r.first={date:B[0].dataset.date,pressed:B[0].getAttribute('aria-pressed'),label:B[0].getAttribute('aria-label'),c:B[0].querySelector('.c').textContent};
r.defaultVis=vis();r.count=d.querySelector('[data-count]').textContent;
B.forEach(function(b){b.click();var rc=b.getBoundingClientRect();r.days.push({day:b.dataset.day,date:b.dataset.date,cap:b.querySelector('.n').textContent,vis:vis(),w:rc.width,h:rc.height,pressed:b.getAttribute('aria-pressed')})});
W.querySelector('.day-all').click();r.all=vis();
var h=d.getElementById('bank-hsbc');h.checked=true;h.dispatchEvent(new Event('change',{bubbles:true}));
B.forEach(function(b){if(b.dataset.day=='sat'){b.click();r.hsbcSat=vis()}if(b.dataset.day=='mon'){b.click();r.hsbcMon=vis()}});
r.pageW=d.documentElement.scrollWidth;r.clientW=d.documentElement.clientWidth;r.stripScroll=[W.querySelector('.days').scrollWidth,W.querySelector('.days').clientWidth];
document.getElementById('o').textContent=JSON.stringify(r)},500)};document.body.appendChild(f);</script>"""

    def assert_no_page_scroll(self, r, width):
        # A classic 15px scrollbar is forced in the harness (the Linux CI runner draws one; macOS overlays it),
        # so the viewport is width - 15 there. What matters: the page never scrolls sideways.
        self.assertLessEqual(r["pageW"], r["clientW"], r)
        self.assertEqual(r["clientW"], width - 15, "the forced classic scrollbar must be in effect")

    def run_harness(self, out, when, width=390):
        (out / "__h.html").write_text(self.HARNESS % {"w": width, "now": int(when.timestamp() * 1000)})
        s = __import__("socket").socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(out)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.8)
            r = subprocess.run([g.chrome_path(), "--headless=new", "--disable-gpu", f"--user-data-dir={self.tmp / 'p'}",
                                "--virtual-time-budget=4000", "--window-size=500,1000", "--dump-dom",
                                f"http://127.0.0.1:{port}/__h.html"], capture_output=True, text=True, timeout=60,
                               stdin=subprocess.DEVNULL)
        finally:
            srv.terminate()
            srv.wait(timeout=10)
        return json.loads(re.search(r'<pre id="o">(.*?)</pre>', r.stdout, re.S).group(1).replace("&quot;", '"'))

    def test_every_day_count_matches_the_filtered_list(self):
        out, _ = self.live()
        r = self.run_harness(out, datetime(2026, 11, 25, 6, tzinfo=timezone.utc))      # Wed 25 Nov, 11:30 IST
        self.assertEqual(r["first"]["date"], "2026-11-25")
        self.assertEqual(r["first"]["pressed"], "true")
        self.assertEqual(r["count"], str(n_on("wed")))
        self.assertEqual([x["date"] for x in r["days"]], [(date(2026, 11, 25) + timedelta(i)).isoformat() for i in range(7)])
        for x in r["days"]:
            self.assertEqual(x["cap"], caption(len(x["vis"])), x)              # caption == what you then see
            self.assertEqual(x["vis"], sorted(o["id"] for o in MOVIE if visible_on(o, x["day"])), x)
            self.assertEqual(x["pressed"], "true")
            self.assertGreaterEqual(x["w"], 44)
            self.assertGreaterEqual(x["h"], 44)
        self.assertEqual(r["all"], sorted(o["id"] for o in MOVIE))
        hsbc = [o for o in MOVIE if o["issuer"] == "HSBC"]
        self.assertEqual(r["hsbcSat"], sorted(o["id"] for o in hsbc if visible_on(o, "sat")))
        self.assertEqual(r["hsbcMon"], sorted(o["id"] for o in hsbc if visible_on(o, "mon")))
        self.assert_no_page_scroll(r, 390)

    def test_dates_roll_over_at_midnight_ist(self):
        out, _ = self.live()
        before = self.run_harness(out, datetime(2026, 11, 26, 18, 29, tzinfo=timezone.utc))   # 23:59 IST Thu 26 Nov
        after = self.run_harness(out, datetime(2026, 11, 26, 18, 31, tzinfo=timezone.utc))    # 00:01 IST Fri 27 Nov
        self.assertEqual(before["first"]["date"], "2026-11-26")
        self.assertEqual(before["first"]["c"], "26")
        self.assertEqual(before["first"]["label"], f"Thu 26 Nov, {caption(n_on('thu'))}")
        self.assertEqual(after["first"]["date"], "2026-11-27")
        self.assertEqual(after["first"]["c"], "27")
        self.assertEqual(after["days"][0]["day"], "fri")

    def test_360_scrolls_inside_the_strip_not_the_page(self):
        out, _ = self.live()
        r = self.run_harness(out, datetime(2026, 11, 25, 6, tzinfo=timezone.utc), width=360)
        self.assert_no_page_scroll(r, 360)
        self.assertTrue(all(x["w"] >= 44 for x in r["days"]))


if __name__ == "__main__":
    unittest.main()
