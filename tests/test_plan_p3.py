"""P3 (decisions 150-157): saved offers, the sort control, /calendar/, the "Before you pay" checklist and motion.
Owner, 26 Nov: no price estimator, no price inputs, no computed rupee outcome, no "cheaper"/"better value", no platform
sort. Written alongside the code; the browser checks run in headless Chrome like the rest of the suite."""
import copy
import gzip
import html
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
import plan_pages as P  # noqa: E402
from test_redesign_r1 import BASE, HARNESS, NOW, R1, Browser  # noqa: E402
from test_redesign_v2 import TEXT_PAIRS, _rgb, ratio, theme  # noqa: E402
from test_review_s1 import ld, visible  # noqa: E402

DAY = 86400 * 1000
MOVIE = [g.norm(o) for o in BASE["offers"] if o["category"] != "events"]
TODAY = date(2026, 11, 25)   # the fixture's generated_at, in IST
OLD = {**copy.deepcopy([o for o in BASE["offers"] if o["id"] == "hsbc-premier-bms-bogo"][0]),
       "id": "kotak-old-bms-bogo", "issuer": "Kotak", "card_variants": ["League"],
       "checked_at": "2026-11-24T09:00:00+00:00", "checked_on": "2026-11-24"}


def by_id(oid):
    return next(o for o in MOVIE if o.id == oid)


class Site(R1):
    def site_p3(self, name="p3", edit=None):
        """The fixture, plus a 24 Nov snapshot holding an offer that is gone today (it keeps a history page)."""
        w = self.tmp / name
        w.mkdir()
        base = copy.deepcopy(BASE)
        if edit:
            edit(base)
        old = copy.deepcopy(BASE)
        old["generated_at"] = "2026-11-24T10:00:00+00:00"
        old["offers"] = old["offers"] + [OLD]
        (w / "offers.json").write_text(json.dumps(base))
        (w / "h").mkdir()
        (w / "h/2026-11-24.json").write_text(json.dumps(old))
        (w / "h/2026-11-25.json").write_text(json.dumps(base))
        g.build(w / "offers.json", w / "h", w / "dist", w / "st.json", ROOT / "data/site.json", ROOT,
                spotted=ROOT / "tests/fixtures/spotted-fixture.json")
        return w / "dist"


# ------------------------------------------------------------------ calendar rules (no browser)
class CalendarRules(unittest.TestCase):
    def test_book_day_and_show_day_stay_distinct(self):
        show = g.norm({**[o for o in BASE["offers"] if o["id"] == "axis-select-district-bogo"][0],
                       "id": "show-fri", "days": ["fri"], "day_basis": "show"})
        c = P.calendar_data(MOVIE + [show], TODAY)
        days = {x["date"]: x for x in c["days"]}
        self.assertEqual([x["date"] for x in c["days"]], [date(2026, 11, 25 + i) if i < 6 else date(2026, 12, 1) for i in range(7)])
        self.assertEqual([o.id for o in days[date(2026, 11, 28)]["book"]], ["hsbc-select-bms-saturday-bogo"])
        self.assertEqual([o.id for o in days[date(2026, 11, 27)]["show"]], ["show-fri"])
        self.assertEqual(days[date(2026, 11, 27)]["book"], [], "a show-day offer is never listed as a booking day")
        self.assertEqual(sorted(o.id for o in c["every"]), ["hsbc-premier-bms-bogo", "indusind-eazydiner-platinum-bms-bogo"])
        self.assertEqual(sorted(o.id for o in c["nodays"]), ["axis-myzone-district-bogo", "axis-select-district-bogo"])

    def test_resets_only_on_the_1st_and_only_for_quoted_calendar_months(self):
        c = P.calendar_data(MOVIE, TODAY)
        marked = {x["date"]: [o.id for o in x["resets"]] for x in c["days"] if x["resets"]}
        self.assertEqual(list(marked), [date(2026, 12, 1)])
        self.assertEqual(sorted(marked[date(2026, 12, 1)]),
                         ["hsbc-premier-bms-bogo", "hsbc-select-bms-saturday-bogo", "indusind-eazydiner-platinum-bms-bogo"])
        for o, q in c["resets"]:
            self.assertRegex(q, r"(?i)calendar month")
            self.assertNotRegex(q, r"(?i)spend", "a spend window is not a benefit reset")
        # "once a month" / "twice per month" without "calendar": no reset date, said plainly
        self.assertEqual(sorted(o.id for o in c["rolling"]), ["axis-myzone-district-bogo", "axis-select-district-bogo"])
        later = P.calendar_data(MOVIE, date(2026, 12, 2))
        self.assertFalse(any(x["resets"] for x in later["days"]), "no 1st in the window: no reset marker")

    def test_ends_markers_come_from_valid_to_inside_the_window(self):
        ending = g.norm({**[o for o in BASE["offers"] if o["id"] == "hsbc-premier-bms-bogo"][0], "valid_to": "2026-11-29"})
        c = P.calendar_data([ending], TODAY)
        self.assertEqual({x["date"]: [o.id for o in x["ends"]] for x in c["days"] if x["ends"]},
                         {date(2026, 11, 29): ["hsbc-premier-bms-bogo"]})
        self.assertFalse(any(x["ends"] for x in P.calendar_data(MOVIE, TODAY)["days"]))


class CalendarPage(Site):
    def test_crawlable_with_js_off(self):
        out = self.site_p3()
        t = (out / "calendar/index.html").read_text()
        v = re.sub(r"\s+", " ", html.unescape(visible(t)))
        cells = re.findall(r'<li class="cl-d" data-date="([\d-]+)"', t)
        self.assertEqual(cells, [f"2026-11-{d}" for d in range(25, 31)] + ["2026-12-01"], "server-rendered from generated_at")
        for wd, n, mo in (("Wed", 25, "Nov"), ("Sat", 28, "Nov"), ("Tue", 1, "Dec")):
            self.assertIn(f"{wd} {n} {mo}", v)
        for o in MOVIE:                                  # every live movie offer is reachable by a plain link
            self.assertIn(f'href="{g.offer_path(o.id)}"', t)
        self.assertIn("Book this day", v)
        self.assertIn("Select HSBC credit cards · BookMyShow 2nd ticket free, up to ₹250 show any day", v)
        self.assertIn("New calendar month: 3 monthly limits restart", v)
        self.assertIn("the terms don't say when the month starts, so we show no reset date", v)
        self.assertNotRegex(v, r"(?i)\btoday\b|\btomorrow\b", "the browser adds those, never the static page")
        self.assertRegex(t, r'<span class="cl-today" hidden></span>')
        self.assertTrue(v.index("The next 7 days") < v.index("Before you pay"))

    def test_window_follows_generated_at(self):
        def edit(b):
            b["generated_at"] = "2026-11-27T02:00:00+00:00"
        t = (self.site_p3("later", edit) / "calendar/index.html").read_text()
        self.assertEqual(re.findall(r'data-date="([\d-]+)"', t)[0], "2026-11-27")

    def test_jsonld_is_breadcrumb_only_and_matches_the_page(self):
        t = (self.site_p3() / "calendar/index.html").read_text()
        graph = ld(t)
        self.assertEqual(sorted(x["@type"] for x in graph), ["BreadcrumbList", "Organization", "WebPage", "WebSite"])
        self.assertNotRegex(json.dumps(graph), r'"(Event|Offer|FAQPage|ItemList)"')
        crumbs = [i["name"] for i in next(x for x in graph if x["@type"] == "BreadcrumbList")["itemListElement"]]
        nav = re.search(r'<nav class="crumbs wrap" aria-label="Breadcrumb">.*?</nav>', t, re.S).group(0)
        self.assertEqual(crumbs, [s.strip() for s in visible(nav).split("  ") if s.strip()])
        page = next(x for x in graph if x["@type"] == "WebPage")
        self.assertEqual(page["name"], html.unescape(re.search(r"<title>(.*?)</title>", t).group(1)))
        self.assertIn(f'datetime="{page["dateModified"]}"', t)

    def test_in_the_nav_sitemap_and_llms_txt(self):
        out = self.site_p3()
        for p in ("index.html", "calendar/index.html", "offer/hsbc-premier-bms-bogo/index.html"):
            nav = re.search(r'<nav class="nav".*?</nav>', (out / p).read_text(), re.S).group(0)
            self.assertIn('href="/calendar/"', nav)
        self.assertIn("https://bookmyfdfs.in/calendar/", (out / "sitemap.xml").read_text())
        self.assertIn("(https://bookmyfdfs.in/calendar/)", (out / "llms.txt").read_text())
        self.assertIn('<a href="/calendar/">Plan the week by day', (out / "index.html").read_text())
        self.assertEqual(re.findall(r"<title>(.*?)</title>", (out / "calendar/index.html").read_text()),
                         ["Movie ticket offers this week: plan by day · FDFS"])


# ------------------------------------------------------------------ the checklist (no browser)
class Checklist(Site):
    def test_five_checks_each_with_a_real_example(self):
        out = self.site_p3()
        for p, this in (("calendar/index.html", None), ("offer/hsbc-premier-bms-bogo/index.html", "hsbc-premier-bms-bogo")):
            t = (out / p).read_text()
            box = re.search(r'<details class="bp"[^>]*>.*?</details>', t, re.S).group(0)
            items = re.findall(r'<li data-bp="(\w+)">(.*?)</li>', box, re.S)
            self.assertEqual([k for k, _ in items], ["day", "month", "pay", "min", "see"])
            for key, body in items:
                cond = dict((k, f) for k, _, _, f in P.CHECKS)[key]
                for oid in re.findall(r'href="/offer/([^/]+)/"', body):
                    self.assertTrue(cond(by_id(oid)), f"{p}: {key} example {oid} lacks the condition")
                    self.assertNotEqual(oid, this, "an example is another offer")
            if this:
                self.assertNotIn(" open", box[:30], "compact: closed on offer pages")
                self.assertIn("This offer:</strong> Twice a month.", box)
                self.assertIn("This offer:</strong> Pay the full amount with the card. Not with wallet payments.", box)
            self.assertNotRegex(t, r"FAQPage|Question|acceptedAnswer")


# ------------------------------------------------------------------ owner rules, privacy, budgets (no browser)
class Rules(Site):
    def test_no_estimator_no_price_inputs_no_sides(self):
        out = self.site_p3()
        bad = re.compile(r"(?i)cheaper|better value|best value|you('d| would) pay|what you.d pay|your price|estimat|"
                         r"savings?\b|you save|compare (apps|prices)|ends soon|hurry|last chance")
        for p in out.rglob("*.html"):
            t = p.read_text()
            self.assertIsNone(bad.search(html.unescape(visible(t))), f"{p.relative_to(out)}: {bad.search(html.unescape(visible(t)))}")
            self.assertNotRegex(t, r'<input[^>]+(type="(number|text)"|inputmode)[^>]*(price|amount|₹)', p)
        js = P.PLAN_JS_SRC
        self.assertNotRegex(js, r"(?i)cheaper|better value|estimat|inputmode|type=.number")
        labels = re.findall(r"(\w+): \['([^']+)'", js)
        self.assertEqual(labels, [("recent", "Most recently checked"), ("ends", "Soonest end date"), ("cap", "Highest stated cap")])
        self.assertNotRegex(js, r"data-app|\.app\b|platform", "no sort or filter by app in plan.js")

    def test_sort_data_is_the_stated_cap_and_end(self):
        t = (self.site_p3() / "index.html").read_text()
        data = json.loads(re.search(r"var FDFS_PLAN=(\{.*?\});", t).group(1))
        for o in MOVIE:
            self.assertEqual(data["o"][o.id][1], P.stated_cap(o))
            self.assertEqual(data["o"][o.id][2], o.valid_to.isoformat() if o.valid_to else None)
            self.assertEqual(o.id, g.offer_slug(o.id), "plan.js builds /offer/<id>/ from the id")
        self.assertEqual(data["g"], {"kotak-old-bms-bogo": "Kotak League Mastercard on BookMyShow"})
        self.assertIsNone(P.stated_cap(g.norm({"kind": "flat", "value": {"flat": 100}})), "a flat amount is not a cap")

    def test_save_never_on_spotted_and_hidden_without_js(self):
        out = self.site_p3()
        home = (out / "index.html").read_text()
        self.assertNotIn("data-sv=", re.sub(r"<script.*?</script>", "", home, flags=re.S), "home hearts are added by the script")
        for p in (out / "offer").glob("*/index.html"):
            b = re.findall(r'<button type="button" class="sv sv-l"[^>]*>', p.read_text())
            self.assertEqual(len(b), 1, p)
            self.assertIn(" hidden>", b[0], "a control that can't work is never shown")
        gone = (out / "offer/kotak-old-bms-bogo/index.html").read_text()
        self.assertIn("data-gone", re.search(r'<button type="button" class="sv sv-l"[^>]*>', gone).group(0))
        self.assertIn('"kotak-old-bms-bogo":"Kotak League Mastercard on BookMyShow"', gone)
        js = P.PLAN_JS_SRC
        self.assertIn("$$('#offers article.offer')", js, "only checked offers get a heart, never .spot leads")

    def test_script_is_private_and_storage_is_guarded(self):
        js = P.PLAN_JS_SRC
        self.assertNotRegex(js, r"fetch\(|XMLHttpRequest|sendBeacon|WebSocket|document\.cookie|wa\.me|window\.open")
        self.assertEqual(re.findall(r"KEY = '([^']+)'", js), ["fdfs.saved.v1"])
        for m in re.finditer(r"localStorage\.\w+", js):
            pre = js[:m.start()]
            self.assertGreater(pre.rfind("try {"), pre.rfind("}\n"), f"unguarded {m.group(0)}")
        self.assertNotRegex(js, r"location\.(href|search)\s*=|set\('saved|saved=", "saved IDs never go in a URL")

    def test_budgets(self):
        js = P.plan_js()
        # plan.js is inlined on home, offer pages and /calendar/, and excluded from the page-weight test like home.js
        self.assertLessEqual(len(js.encode()), 9 * 1024)
        self.assertLessEqual(len(gzip.compress(js.encode())), 4 * 1024)
        # page-only CSS (kept out of the shared stylesheet, so no other page grows)
        self.assertLessEqual(len(gzip.compress((P.CAL_CSS + P.BP_CSS).encode())), int(1.6 * 1024))
        if shutil.which("node"):
            f = self.tmp / "plan.js"
            f.write_text(js)
            r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_page_only_css_follows_the_colour_and_motion_rules(self):
        css = (ROOT / "gen/plan-calendar.css").read_text() + (ROOT / "gen/plan-checklist.css").read_text()
        for rule in re.findall(r"(?<![-\w])color:\s*([^;}]+)", css):
            self.assertNotRegex(rule.strip().lower(), r"var\(--(lime|accent|ticket)\)|#d5f476", rule)
        stripped = css
        while (m := re.search(r"@media \(prefers-reduced-motion:no-preference\)\{", stripped)):
            i, depth, j = m.end(), 1, m.end()
            while depth:
                depth += {"{": 1, "}": -1}.get(stripped[j], 0)
                j += 1
            stripped = stripped[:m.start()] + stripped[j:]
        self.assertNotRegex(stripped, r"(?<![-\w])animation\s*:")
        for t in re.findall(r"transition:([^;}]+)", css):
            self.assertRegex(t, r"var\(--d-", t)

    def test_new_text_pairs_meet_wcag_aa_in_both_themes(self):
        # every (text, background) pair the P3 styles use; each must be a checked pair and reach 4.5:1
        used = [("--text", "--surface"), ("--text-2", "--surface"), ("--text-3", "--surface"), ("--text-2", "--surface-2"),
                ("--text-3", "--surface-2"), ("--accent-text", "--surface"), ("--accent-text", "--surface-2"),
                ("--bg", "--text"), ("--on-accent", "--accent"), ("--note-text", "--note-bg"), ("--note-text", "--bg"),
                ("--text-2", "--bg"), ("--text-3", "--bg"), ("--text", "--surface-2")]
        for dark in (False, True):
            t = theme(dark)
            for fg, bg in used:
                self.assertGreaterEqual(ratio(t[fg], t[bg]), 4.5, f"{'dark' if dark else 'light'}: {fg} on {bg}")


# ------------------------------------------------------------------ browser
class P3Browser(Site, Browser):
    def run_flags(self, out, body, flags, budget=8000):
        """run_js with extra Chrome flags (here: forced reduced motion)."""
        name = f"__m{abs(hash(body + ''.join(flags))) % 10**8}.html"
        (out / name).write_text(HARNESS % {"body": body})
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(out)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.7)
            r = subprocess.run([g.chrome_path(), "--headless=new", "--disable-gpu", f"--user-data-dir={self.tmp / name}",
                                f"--virtual-time-budget={budget}", "--window-size=1400,1000", "--dump-dom", *flags,
                                f"http://127.0.0.1:{port}/{name}"], capture_output=True, text=True, timeout=90,
                               stdin=subprocess.DEVNULL)
        finally:
            srv.terminate()
            srv.wait(timeout=10)
        m = re.search(r'<pre id="o">(.*?)</pre>', r.stdout, re.S)
        res = json.loads(html.unescape(m.group(1))) if m and m.group(1) else {"error": "no result"}
        self.assertNotIn("error", res, res.get("error"))
        return res

    def test_save_keyboard_live_region_saved_view_and_gone_ids(self):
        out = self.site_p3()
        res = self.run_js(out, """load('/?fdfs_now=%(now)d',390,function(f,d,w){
w.localStorage.setItem('fdfs.saved.v1',JSON.stringify(['kotak-old-bms-bogo','never-listed-x','BAD ID']));
load('/?fdfs_now=%(now)d&day=all',390,function(f2,d2,w2){var r={};
var b=d2.querySelector('#hsbc-premier-bms-bogo [data-sv]');r.tag=b.tagName;r.label=b.getAttribute('aria-label');
r.spotHearts=d2.querySelectorAll('.spot [data-sv]').length;r.hearts=d2.querySelectorAll('#offers .offer [data-sv]').length;
b.focus();b.click();r.pressed=b.getAttribute('aria-pressed');r.focus=d2.activeElement===b;
r.live=d2.querySelector('[data-p3-say]').getAttribute('aria-live');
d2.querySelector('#axis-select-district-bogo [data-sv]').click();
var v=d2.querySelector('[data-svview]');v.click();r.viewPressed=v.getAttribute('aria-pressed');
r.vis=vis(d2);r.count=txt(d2.querySelector('[data-count]'));r.panel=txt(d2.getElementById('svp'));
r.goneLinks=[].map.call(d2.querySelectorAll('#svp li.gone a'),function(a){return a.getAttribute('href')});
r.stored=JSON.parse(w2.localStorage.getItem('fdfs.saved.v1'));r.href=w2.location.href;
r.res=w2.performance.getEntriesByType('resource').map(function(e){return e.name}).join(' ');
r.opened=[];w2.open=function(u){r.opened.push(u)};var sv=d2.querySelector('[data-share-view]');if(sv)sv.click();
setTimeout(function(){r.say=txt(d2.querySelector('[data-p3-say]'));
var x=d2.querySelector('#svp [data-svrm="axis-select-district-bogo"]');x.click();r.after=JSON.parse(w2.localStorage.getItem('fdfs.saved.v1'));
r.focusAfter=d2.activeElement.dataset.svrm||d2.activeElement.className;v.click();r.visAll=vis(d2,'#offers .offer');done(r)},120)},900)});""" % {"now": NOW},
                          budget=12000)
        self.assertEqual(res["tag"], "BUTTON", "native button: Enter and Space work")
        self.assertEqual(res["label"], "Save HSBC Premier Mastercard on BookMyShow")
        self.assertEqual((res["spotHearts"], res["hearts"]), (0, len(MOVIE)))
        self.assertEqual(res["pressed"], "true")
        self.assertTrue(res["focus"], "focus stays on the toggle")
        self.assertEqual(res["live"], "polite")
        self.assertEqual(res["viewPressed"], "true")
        self.assertEqual(res["vis"], ["axis-select-district-bogo", "hsbc-premier-bms-bogo"], "Saved view: saved checked offers only")
        self.assertEqual(res["count"], "2")
        self.assertIn("Saved on this device (4)", res["panel"])
        self.assertIn("No longer listed Kotak League Mastercard on BookMyShow", res["panel"])
        self.assertIn("No longer listed An offer we no longer list", res["panel"], "an unknown saved ID is never dropped silently")
        self.assertEqual(res["goneLinks"], ["/offer/kotak-old-bms-bogo/", "/offer/never-listed-x/"])
        self.assertEqual(res["stored"], ["kotak-old-bms-bogo", "never-listed-x", "hsbc-premier-bms-bogo", "axis-select-district-bogo"])
        for k in ("href", "res"):
            self.assertNotRegex(res[k], r"kotak-old|never-listed|saved", k)
        self.assertNotRegex(" ".join(res["opened"]), r"kotak-old|never-listed|hsbc-premier|saved")
        self.assertTrue(res["say"].startswith("Showing saved offers: 2 still listed of 4 saved."), res["say"])
        self.assertEqual(res["after"], ["kotak-old-bms-bogo", "never-listed-x", "hsbc-premier-bms-bogo"])
        self.assertEqual(res["focusAfter"], "hsbc-premier-bms-bogo", "focus moves to a neighbour, never lost")
        self.assertEqual(len(res["visAll"]), len(MOVIE))

    def test_storage_failure_still_works_in_memory(self):
        out = self.site_p3()
        for page in ("index.html", "offer/hsbc-premier-bms-bogo/index.html"):
            t = (out / page).read_text().replace(
                "<head>", "<head><script>Object.defineProperty(window,'localStorage',{get:function(){throw new Error('blocked')}})</script>", 1)
            (out / page.replace("index.html", "nostore.html")).write_text(t)
        res = self.run_js(out, """load('/nostore.html?fdfs_now=%(now)d',390,function(f,d,w){var r={};
d.querySelector('#indusind-eazydiner-platinum-bms-bogo [data-sv]').click();setTimeout(function(){r.say=txt(d.querySelector('[data-p3-say]'));
d.querySelector('[data-svview]').click();r.vis=vis(d);r.panel=txt(d.getElementById('svp'));
load('/offer/hsbc-premier-bms-bogo/nostore.html?fdfs_now=%(now)d',390,function(f2,d2){var b=d2.querySelector('[data-sv]');
r.offerShown=!b.hidden;b.click();r.offerPressed=b.getAttribute('aria-pressed');r.offerText=txt(b);done(r)})},100)});""" % {"now": NOW},
                          budget=10000)
        self.assertEqual(res["vis"], ["indusind-eazydiner-platinum-bms-bogo"])
        self.assertIn("kept for this visit only", res["panel"])
        self.assertIn("for this visit only", res["say"])
        self.assertTrue(res["offerShown"])
        self.assertEqual((res["offerPressed"], res["offerText"]), ("true", "Saved this offer"))

    def test_sort_control_orders_labels_and_announces(self):
        def edit(b):
            for o in b["offers"]:
                if o["id"] == "axis-select-district-bogo":
                    o["value"] = {}
                    o["cap_text"] = "see terms"
        out = self.site_p3("srt", edit)
        res = self.run_js(out, """load('/?fdfs_now=%d&day=all',1280,function(f,d,w){var r={},s=d.getElementById('sort');
function ord(){return [].filter.call(d.querySelectorAll('#offers .grid article.offer'),function(e){return e.offsetParent}).map(function(e){return e.id})}
r.label=txt(d.querySelector('label[for=sort]'));r.desc=s.getAttribute('aria-describedby');r.recent=ord();r.h0=txt(d.getElementById('sort-h'));
r.noteHidden=[].every.call(d.querySelectorAll('.order-note'),function(p){return p.hidden});
r.opts=[].map.call(s.options,function(o){return o.textContent});
s.value='cap';s.dispatchEvent(new Event('change',{bubbles:true}));r.cap=ord();r.nocap=[].map.call(d.querySelectorAll('.nocap'),function(x){return x.closest('article').id});
r.url=w.location.search;r.h1=txt(d.getElementById('sort-h'));
s.value='ends';s.dispatchEvent(new Event('change',{bubbles:true}));r.ends=ord();r.nocap2=d.querySelectorAll('.nocap').length;
setTimeout(function(){r.say=txt(d.querySelector('[data-p3-say]'));done(r)},100)});""" % NOW)
        movie = sorted(MOVIE, key=g.home_order)
        self.assertEqual(res["label"], "Sort")
        self.assertEqual(res["desc"], "sort-h")
        self.assertEqual(res["opts"], ["Most recently checked", "Soonest end date", "Highest stated cap"])
        self.assertEqual(res["recent"], [o.id for o in movie], "the default is the server's order")
        self.assertEqual(res["h0"], g.ORDER_NOTE)
        self.assertTrue(res["noteHidden"], "one visible line says the active rule")
        caps = {o.id: (None if o.id == "axis-select-district-bogo" else P.stated_cap(o)) for o in movie}
        want = sorted(movie, key=lambda o: (caps[o.id] is None, -(caps[o.id] or 0), movie.index(o)))
        self.assertEqual(res["cap"], [o.id for o in want])
        self.assertEqual(res["nocap"], ["axis-select-district-bogo"])
        self.assertIn("sort=cap", res["url"])
        self.assertIn("Cap not stated", res["h1"])
        self.assertEqual(res["ends"], [o.id for o in sorted(movie, key=lambda o: (o.valid_to is None, o.valid_to or date.max, movie.index(o)))])
        self.assertEqual(res["nocap2"], 0)
        self.assertTrue(res["say"].startswith("Sorted by soonest end date."), res["say"])

    def test_sort_ignores_the_app(self):
        def swap(b):
            for o in b["offers"]:
                o["platform"] = {"bms": "district", "district": "bms"}.get(o["platform"], o["platform"])
        body = """load('/?fdfs_now=%d&day=all',1280,function(f,d){var s=d.getElementById('sort'),r={};['cap','ends'].forEach(function(k){
s.value=k;s.dispatchEvent(new Event('change',{bubbles:true}));r[k]=[].map.call(d.querySelectorAll('#offers .grid article.offer'),function(e){return e.id})});done(r)});""" % NOW
        a = self.run_js(self.site_p3("a"), body)
        b = self.run_js(self.site_p3("b", swap), body)
        self.assertEqual(a, b)

    def test_calendar_today_past_and_stale(self):
        out = self.site_p3()
        res = self.run_js(out, """load('/calendar/?fdfs_now=%d',390,function(f,d,w){var r={};
r.cells=[].map.call(d.querySelectorAll('.cl-d:not(.cl-x)'),function(c){return [c.dataset.date,txt(c.querySelector('.cl-today'))||'',c.getAttribute('aria-current')||'']});
r.stale=d.querySelector('[data-cl-stale]').hidden;
load('/calendar/?fdfs_now=%d',390,function(f2,d2){r.stale2=d2.querySelector('[data-cl-stale]').hidden;done(r)})});""" % (NOW + 2 * DAY, NOW + 9 * DAY))
        # decision 162: past days drop out of view and the 7 days start on the visitor's today
        self.assertEqual(res["cells"][:2], [["2026-11-27", "Today", "date"], ["2026-11-28", "Tomorrow", ""]])
        self.assertEqual([c[0] for c in res["cells"]], [f"2026-11-{d}" for d in range(27, 31)] + ["2026-12-01", "2026-12-02", "2026-12-03"])
        self.assertEqual(res["cells"][2][1:], ["", ""])
        self.assertTrue(res["stale"])
        self.assertFalse(res["stale2"], "a week later the page says its days have passed")

    def test_layout_agenda_on_phones_grid_on_desktop_no_sideways_scroll(self):
        out = self.site_p3()
        res = self.run_js(out, """var r=[],J=[['/calendar/',320],['/calendar/',390],['/calendar/',1100],['/',320],['/',390],
['/offer/hsbc-select-bms-saturday-bogo/',320],['/offer/hsbc-select-bms-saturday-bogo/',390]],k=0;
function one(){if(k==J.length)return done({r:r});var j=J[k++];load(j[0]+'?fdfs_now=%d',j[1],function(f,d,w){
var c=[].map.call(d.querySelectorAll('.cl-d:not(.cl-x)'),function(e){return Math.round(e.getBoundingClientRect().top)}),
n=d.querySelector('.nav').getBoundingClientRect(),wide=[];
[].forEach.call(d.querySelectorAll('body *'),function(e){var b=e.getBoundingClientRect();if(e.offsetParent&&b.right>d.documentElement.clientWidth+1&&!e.closest('.chips,.days'))wide.push(e.className||e.tagName)});
r.push({p:j[0],w:j[1],sc:scroll(d),tops:c,nav:Math.round(n.right),cw:d.documentElement.clientWidth,wide:wide.slice(0,5)});one()},1400)}one();""" % NOW,
                          budget=20000)
        for x in res["r"]:
            self.assertLessEqual(x["sc"][0], x["sc"][1], x)
            self.assertLessEqual(x["nav"], x["cw"], f"header links fit: {x}")
            self.assertEqual(x["wide"], [], x)
            if x["p"] == "/calendar/":
                self.assertEqual(len(x["tops"]), 7)
                if x["w"] >= 1024:
                    self.assertEqual(len(set(x["tops"])), 1, "7 columns in one row")
                else:
                    self.assertEqual(x["tops"], sorted(x["tops"]))
                    self.assertEqual(len(set(x["tops"])), 7, "a vertical agenda")

    def test_motion_is_off_under_reduced_motion(self):
        out = self.site_p3()
        body = """load('/?fdfs_now=%d&day=all',1280,function(f,d,w){var s=d.getElementById('sort');
var a0=w.getComputedStyle(d.querySelector('.s-q time')).animationName;s.value='cap';s.dispatchEvent(new Event('change',{bubbles:true}));
setTimeout(function(){var n=d.getAnimations().filter(function(a){return !a.animationName}).length;
d.querySelector('#hsbc-premier-bms-bogo [data-sv]').click();
done({stamp:a0,flip:n,pop:w.getComputedStyle(d.querySelector('#hsbc-premier-bms-bogo [data-sv] .sv-i')).animationName})},40)});""" % NOW
        off = self.run_flags(out, body, ["--force-prefers-reduced-motion"])
        self.assertEqual(off, {"stamp": "none", "flip": 0, "pop": "none"})
        on = self.run_js(out, body)
        self.assertEqual(on["stamp"], "stamp", "the check stamp eases in once")
        self.assertGreater(on["flip"], 0, "sort changes reflow with motion when allowed (the reduced-motion check bites)")


# ------------------------------------------------------------------ a busy week: ~20 offers a day (coordinator, 26 Nov)
BANKS8 = ("HDFC", "Axis", "ICICI", "Kotak", "RBL Bank", "IDFC FIRST", "AU", "Bandhan")


def busy(b):
    """24 extra Saturday-booking offers across 8 banks, plus 12 every-day ones: a synthetic stand-in for a full feed."""
    sat = [o for o in b["offers"] if o["id"] == "hsbc-select-bms-saturday-bogo"][0]
    prem = [o for o in b["offers"] if o["id"] == "hsbc-premier-bms-bogo"][0]
    for i in range(24):
        b["offers"].append({**copy.deepcopy(sat), "id": f"busy-sat-{i}", "issuer": BANKS8[i % 8], "variants_scope": "listed",
                            "card_variants": [f"Variant {i}"]})
    for i in range(12):
        b["offers"].append({**copy.deepcopy(prem), "id": f"busy-any-{i}", "issuer": BANKS8[i % 8], "card_variants": [f"Plus {i}"]})


class BusyWeek(Site):
    def test_a_busy_day_groups_by_bank_and_collapses(self):
        t = (self.site_p3("busy", busy) / "calendar/index.html").read_text()
        sat = re.search(r'<li class="cl-d" data-date="2026-11-28".*?<li class="cl-d" data-date="2026-11-29"', t, re.S).group(0)
        groups = re.findall(r'<details class="cl-g"><summary><span class="cl-gb">([^<]+)</span><span class="cl-gn">(\d+) offers?', sat)
        self.assertEqual(sum(int(n) for _, n in groups), 25, "every Saturday offer is still linked")
        self.assertEqual(len(groups), 9, "one closed group per bank, not 25 stacked cards")
        self.assertNotIn('<details class="cl-g" open', sat)
        for i in range(24):
            self.assertIn(f'href="/offer/busy-sat-{i}/"', sat, "links stay in the HTML for crawlers")
        ev = re.search(r'id="every-day".*?</section>', t, re.S).group(0)
        self.assertGreaterEqual(len(re.findall(r'class="cl-g"', ev)), 8)
        self.assertIn("offers depend on the day: see each day below.", visible(t))


class BusyBrowser(Site, Browser):
    def test_busy_week_readable_at_phone_and_desktop(self):
        out = self.site_p3("busy", busy)
        res = self.run_js(out, """var r=[],W=[320,390,1100],k=0;function one(){if(k==W.length)return done({r:r});var w=W[k++];
load('/calendar/?fdfs_now=%d',w,function(f,d){var c=[].map.call(d.querySelectorAll('.cl-d:not(.cl-x)'),function(e){var b=e.getBoundingClientRect();return [Math.round(b.top),Math.round(b.height)]});
r.push({w:w,sc:scroll(d),c:c,open:d.querySelectorAll('.cl-g[open]').length});one()},1400)}one();""" % NOW, budget=15000)
        for x in res["r"]:
            self.assertLessEqual(x["sc"][0], x["sc"][1], x)
            self.assertEqual(x["open"], 0)
            self.assertLess(x["c"][3][1], 900, f"Saturday stays short when collapsed: {x}")
            if x["w"] >= 1024:
                self.assertEqual(len({t for t, _ in x["c"]}), 1, "still 7 columns")


# ------------------------------------------------------------------ QA 26 Nov: F2 focus, F6 label in name (browser)
class QAFocusAndNames(Site, Browser):
    def test_f2_my_cards_keeps_focus_and_escape_closes(self):
        out = self.site_p3()
        res = self.run_js(out, """load('/?fdfs_now=%d',390,function(f,d,w){var r={};function key(){var a=d.activeElement;
return a===d.body?'BODY':(a.getAttribute('data-wopen')!=null?'wopen':a.dataset.iss?'iss:'+a.dataset.iss:a.dataset.rmc?'rmc:'+a.dataset.rmc:
a.dataset.pc?'pc:'+a.value:a.dataset.tix?'tix:'+a.dataset.tix:a.className)}
function act(el){el.focus();el.click()}
act(d.querySelector('[data-fbtn]'));act(d.querySelector('[data-wopen]'));r.open=key();   /* decision 149: My cards is in the Filters sheet */act(d.querySelector('[data-iss=hsbc]'));r.bank=key();
var c=d.querySelector('input[value="hsbc:premier"]');c.focus();c.click();r.check=key();
act(d.querySelector('[data-iss=axis]'));c=d.querySelector('input[value="axis:select"]');c.focus();c.click();
act(d.querySelector('[data-tix="2"]'));r.tix=key();
act(d.querySelector('[data-rmc="hsbc:premier"]'));r.removed=key();r.inPanel=d.getElementById('mc').contains(d.activeElement);
d.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
r.closed=d.getElementById('mc').hidden;r.esc=key();r.expanded=d.querySelector('[data-wopen]').getAttribute('aria-expanded');
d.getElementById('fd').close();var s=d.querySelector('#axis-select-district-bogo [data-sv]');act(s);r.heart=d.activeElement===s;
var so=d.getElementById('sort');so.focus();so.value='cap';so.dispatchEvent(new Event('change',{bubbles:true}));r.sort=d.activeElement===so;
done(r)});""" % NOW)
        self.assertEqual(res["open"], "wopen")
        self.assertEqual(res["bank"], "iss:hsbc")
        self.assertEqual(res["check"], "pc:hsbc:premier")
        self.assertEqual(res["tix"], "tix:2")
        self.assertNotEqual(res["removed"], "BODY", "a removed chip hands focus to its neighbour")
        self.assertTrue(res["inPanel"])
        self.assertTrue(res["closed"])
        self.assertEqual((res["esc"], res["expanded"]), ("wopen", "false"))
        self.assertTrue(res["heart"], "the save toggle keeps focus")
        self.assertTrue(res["sort"], "the sort select keeps focus")

    def test_f6_accessible_names_start_with_the_visible_text(self):
        out = self.site_p3()
        res = self.run_js(out, """var r=[],J=['/','/offer/axis-select-district-bogo/','/calendar/','/spotted/'],k=0;
function n(s){return s.toLowerCase().replace(/[^a-z0-9₹]+/g,' ').trim()}
function one(){if(k==J.length)return done({r:r});load(J[k++]+'?fdfs_now=%d',1280,function(f,d){
[].forEach.call(d.querySelectorAll('button[aria-label],a[aria-label],[role=button][aria-label]'),function(e){
if(!e.offsetParent)return;var v=n(e.innerText||''),l=n(e.getAttribute('aria-label'));
r.push({v:v,l:l,ok:!v||l.indexOf(v)===0})});
[].forEach.call(d.querySelectorAll('button.code'),function(e){r.push({v:n(e.innerText),l:e.getAttribute('aria-label')||'',code:1,ok:!e.getAttribute('aria-label')})});
one()})}one();""" % NOW, budget=12000)
        bad = [x for x in res["r"] if not x["ok"]]
        self.assertEqual(bad, [])
        days = [x for x in res["r"] if x["l"].startswith(("wed 25 nov", "sat 28 nov"))]
        self.assertTrue(days, "day buttons are checked")
        self.assertTrue(any(x.get("code") and x["v"] == "code axisselect copy" for x in res["r"]), res["r"])


if __name__ == "__main__":
    unittest.main()
