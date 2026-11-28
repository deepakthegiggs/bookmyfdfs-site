"""Site v2 (26 Nov): the V2 visual identity without V2's claims (L3), equal platform treatment (L4).
Decisions 139-140 in docs/site-decisions.md."""
import html
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
from test_redesign_r1 import BASE, R1, SPOTS  # noqa: E402
from test_review_s1 import visible  # noqa: E402

TOKENS = (ROOT / "assets/tokens.css").read_text(encoding="utf-8")
CSS = (ROOT / "gen/site.css").read_text(encoding="utf-8")


# ------------------------------------------------------------------ colour maths (WCAG 2.2, 1.4.3 and 1.4.11)
def _rgb(hexv):
    h = hexv.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lum(c):
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _over(fg, a, bg):
    return tuple(f * a + b * (1 - a) for f, b in zip(fg, bg))


def ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _block(src, start):
    i = src.index("{", src.index(start)) + 1
    depth = 1
    j = i
    while depth:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
    return src[i:j - 1]


def theme(dark: bool) -> dict:
    """Resolve the semantic tokens for one theme to RGB (rgba is composited over the theme background)."""
    raw = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", _block(TOKENS, ":root {")))
    if dark:
        raw.update(re.findall(r"(--[\w-]+):\s*([^;]+);", _block(TOKENS, ':root[data-theme="dark"] {')))

    def res(v, depth=0):
        v = v.strip()
        m = re.fullmatch(r"var\((--[\w-]+)\)", v)
        if m:
            return res(raw[m.group(1)], depth + 1)
        return v
    out = {k: res(v) for k, v in raw.items()}
    bg = _rgb(out["--bg"])
    for k, v in out.items():
        m = re.fullmatch(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", v)
        if m:
            out[k] = _over(tuple(int(m.group(i)) / 255 for i in (1, 2, 3)), float(m.group(4)), bg)
        elif re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
            out[k] = _rgb(v)
    return out


TEXT_PAIRS = [(fg, bg) for fg in ("--text", "--text-2", "--text-3", "--accent-text") for bg in ("--bg", "--surface", "--surface-2")] + [
    ("--ok-text", "--ok-bg"), ("--ok-text", "--surface"), ("--note-text", "--note-bg"), ("--note-text", "--surface"),
    ("--on-accent", "--accent"), ("--ticket-ink", "--ticket"), ("--stage-text", "--stage-bg"), ("--stage-text-2", "--stage-bg"),
    ("--bg", "--text")]                                                        # selected chips and buttons: ink fill, page-colour text
GRAPHIC_PAIRS = [("--focus", "--bg"), ("--focus", "--surface"), ("--accent-line", "--surface"), ("--accent-line", "--bg"),
                 ("--line", "--bg")]


class Identity(unittest.TestCase):
    def test_v2_palette_is_the_light_theme(self):
        t = theme(False)
        self.assertEqual(TOKENS.count("#F6F5EE"), 1)
        self.assertEqual(t["--bg"], _rgb("#F6F5EE"))
        self.assertEqual(t["--text"], _rgb("#203229"))
        self.assertEqual(t["--accent"], _rgb("#D5F476"))
        self.assertEqual(t["--ticket"], _rgb("#D5F476"))

    def test_wcag_aa_text_contrast_both_themes(self):
        for dark in (False, True):
            t = theme(dark)
            for fg, bg in TEXT_PAIRS:
                self.assertGreaterEqual(ratio(t[fg], t[bg]), 4.5, f"{'dark' if dark else 'light'}: {fg} on {bg}")

    def test_wcag_non_text_contrast_for_focus_and_accent_lines(self):
        for dark in (False, True):
            t = theme(dark)
            for fg, bg in GRAPHIC_PAIRS[:-1]:
                self.assertGreaterEqual(ratio(t[fg], t[bg]), 3.0, f"{'dark' if dark else 'light'}: {fg} on {bg}")

    def test_never_light_green_text_on_light_surfaces(self):
        light = theme(False)
        lime = _rgb("#D5F476")
        for k in ("--text", "--text-2", "--text-3", "--accent-text", "--ok-text", "--note-text"):
            self.assertNotEqual(light[k], lime, k)
            self.assertLess(_lum(light[k]), 0.25, f"{k} is too light to be text on ivory")
        # lime is a fill: no rule paints text with the raw lime or the fill token
        for rule in re.findall(r"(?<![-\w])color:\s*([^;}]+)", CSS):
            self.assertNotRegex(rule.strip().lower(), r"var\(--(lime|accent|ticket)\)|#d5f476", rule)

    def test_motion_only_without_reduced_motion(self):
        css = CSS
        # P3 (decision 157): a second no-preference block exists, so re-search after each removal (positions shift)
        while (m := re.search(r"@media \(prefers-reduced-motion:no-preference\)\{", css)):
            css = css.replace(css[m.start():m.end() + len(_block(css[m.start():], "@media")) + 1], "")
        self.assertNotRegex(re.sub(r"@keyframes[^{]+\{([^{}]*\{[^{}]*\})*[^{}]*\}", "", css), r"(?<![-\w])animation\s*:")
        self.assertIn("prefers-reduced-motion: reduce", TOKENS)                  # transitions collapse to 0 ms
        for t in re.findall(r"transition:([^;}]+)", CSS):
            self.assertRegex(t, r"var\(--d-", t)

    def test_focus_ring_everywhere(self):
        self.assertRegex(CSS, r":focus-visible\{outline:3px solid var\(--focus\)")


class V2Pages(R1):
    def test_no_external_fonts_or_images(self):
        out = self.site()
        for p in out.rglob("*.html"):
            t = p.read_text()
            self.assertNotRegex(t, r"fonts\.(googleapis|gstatic)\.com|<img\b|<link rel=\"(stylesheet|preload)\"[^>]+href=\"https?://", p)
        css = (out / "assets/site.css").read_text()
        for u in re.findall(r"url\(([^)]*)\)", css):
            self.assertRegex(u.strip("\"'"), r"^(data:|/assets/fonts/)", u)

    def test_v2_claims_never_ship(self):
        """Owner decision 2c: no 'Compare booking apps/fees', no illustrative rupee figure, no Compare tab, and the V2
        line 'More movies. Less money.' is not used (decision 139: next to offers it reads as a savings promise)."""
        out = self.site()
        bad = re.compile(r"compare (booking )?apps|including fees|before fees|example savings|₹\s?300\b|popcorn money|"
                         r"more movies|less money|savings guide|smart move|\bwinner\b|best app", re.I)
        for p in out.rglob("*"):
            if p.suffix in (".html", ".json", ".xml", ".txt"):
                t = html.unescape(p.read_text())
                self.assertIsNone(bad.search(t), f"{p.relative_to(out)}: {bad.search(t)}")
        nav = re.search(r'<nav class="nav".*?</nav>', (out / "index.html").read_text(), re.S).group(0)
        self.assertNotIn("Compare", nav)

    def test_ticket_answer_and_stage(self):
        t = (self.site() / "index.html").read_text()
        self.assertRegex(t, r'<div class="stage"><div class="ticket answer" id="answer">')
        self.assertNotIn('class="beam"', t)


class Platforms(R1):
    def tabs(self, t):
        return re.search(r'<fieldset class="frow tabs">.*?</fieldset>', t, re.S).group(0)

    def test_all_bookmyshow_district_tabs_equal(self):
        t = (self.site() / "index.html").read_text()
        tabs = self.tabs(t)
        labels = re.findall(r'<label class="([^"]+)" for="app-(\w+)">([^<]+)<', tabs)
        self.assertEqual([x[1] for x in labels][:3], ["all", "bms", "district"])
        self.assertEqual([x[2] for x in labels][:3], ["All", "BookMyShow", "District"])
        self.assertEqual({x[0] for x in labels}, {"chip"}, "every tab looks the same: no app gets its own style")
        self.assertIn('id="app-all" value="all" checked', tabs)
        self.assertNotRegex(visible(t), r"(?i)winner|recommended app|best app|top app")

    def test_order_line_matches_the_actual_sort(self):
        t = (self.site() / "index.html").read_text()
        self.assertEqual(visible(t).count(g.ORDER_NOTE), 1)
        grid = re.search(r'<section class="wrap block" id="offers".*?</section>', t, re.S).group(0)
        got = re.findall(r'<article class="offer" id="([^"]+)"', grid)
        offers = [g.norm(o) for o in BASE["offers"] if o["category"] != "events"]
        self.assertEqual(got, [o.id for o in sorted(offers, key=g.home_order)])
        # the rule itself: newer check day first, then the soonest stated end, no end date last
        a = g.norm({"id": "a", "issuer": "X", "checked_at": "2026-11-25T10:00:00+05:30", "valid_to": "2026-12-31"})
        b = g.norm({"id": "b", "issuer": "X", "checked_at": "2026-11-25T23:00:00+05:30", "valid_to": None})
        c = g.norm({"id": "c", "issuer": "X", "checked_at": "2026-11-24T10:00:00+05:30", "valid_to": "2026-11-26"})
        d = g.norm({"id": "d", "issuer": "X", "checked_at": "2026-11-25T09:00:00+05:30", "valid_to": "2026-12-01"})
        self.assertEqual([o.id for o in sorted([a, b, c, d], key=g.home_order)], ["d", "a", "b", "c"])

    def test_app_is_not_part_of_the_order(self):
        """Swap every offer's app: the order of ids must not move."""
        def order(platform_map):
            offers = [g.norm({**o, "platform": platform_map.get(o["platform"], o["platform"])}) for o in BASE["offers"]
                      if o["category"] != "events"]
            return [o.id for o in sorted(offers, key=g.home_order)]
        self.assertEqual(order({}), order({"bms": "district", "district": "bms"}))


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------------------------ L2: My cards with exact products (browser)
import copy  # noqa: E402
from test_redesign_r1 import NOW, Browser  # noqa: E402

PICK = """function pc(d,b,id){var o=d.querySelector('[data-iss="'+b+'"]');if(o.getAttribute('aria-expanded')!='true')o.click();
var c=d.querySelector('input[value="'+id+'"]');c.checked=true;c.dispatchEvent(new Event('change',{bubbles:true}))}
function why(d,id){return txt(d.querySelector('#'+id+' .o-why'))}
function shown(e){return e&&e.offsetParent!==null}"""


class MyCards(Browser):
    def site_with(self, edit, name):
        w = self.tmp / name
        w.mkdir()
        base = copy.deepcopy(BASE)
        edit(base)
        (w / "offers.json").write_text(json.dumps(base))
        (w / "h").mkdir()
        (w / "h/2026-11-25.json").write_text(json.dumps(base))
        g.build(w / "offers.json", w / "h", w / "dist", w / "st.json", ROOT / "data/site.json", ROOT, spotted=SPOTS)
        return w / "dist"

    def test_p09_two_banks_remove_from_your_cards_targets_and_sticky(self):
        out = self.site()
        res = self.run_js(out, PICK + """var r=[],k=0,Ws=[320,390,1280];function one(){if(k==Ws.length)return done({r:r});var W=Ws[k++];
load('/?fdfs_now=%d',W,function(f,d,w){d.querySelector('[data-fbtn]').click();d.querySelector('[data-wopen]').click();pc(d,'hsbc','hsbc:premier');pc(d,'axis','axis:select');
var x={w:W,before:w.FDFS.state().W.slice()};d.querySelector('[data-rmc="hsbc:premier"]').click();
x.after=w.FDFS.state().W.slice();x.open=d.querySelector('[data-iss][aria-expanded=true]').dataset.iss;
x.yours=txt(d.querySelector('#mc .mc-row'));x.small=[];
[].forEach.call(d.querySelectorAll('#mc button,#mc .wk,[data-wallet] button'),function(e){var b=e.getBoundingClientRect();
if(shown(e)&&b.height<44)x.small.push(e.className+':'+txt(e)+':'+Math.round(b.height))});
var sh=d.getElementById('fd'),go=d.querySelector('[data-fclose]');x.mcgo=shown(d.querySelector('[data-mcgo]'));x.go=shown(go);
x.modal=sh.matches(':modal');x.sc=scroll(d);if(x.go){go.click();x.focus=d.activeElement.id;x.closed=!sh.open}r.push(x);one()},900)}one();""" % NOW,
                          budget=15000)
        for x in res["r"]:
            self.assertEqual(x["before"], ["hsbc:premier", "axis:select"], x)
            self.assertEqual(x["after"], ["axis:select"], x)
            self.assertEqual(x["open"], "axis", "removing from Your cards never switches the bank")
            self.assertEqual(x["small"], [], x)
            self.assertLessEqual(x["sc"][0], x["sc"][1], x)
            # decision 149: My cards lives in the Filters sheet at every width. The sheet is modal (nothing behind it can be
            # covered or tapped by mistake), its one sticky "Show n offers" closes it and moves focus to the results, and the
            # panel's own sticky button is not drawn inside it (never two sticky bars).
            self.assertTrue(x["modal"], x)
            self.assertFalse(x["mcgo"], x)
            self.assertTrue(x["go"], x)
            self.assertEqual((x["focus"], x["closed"]), ("h-offers", True), x)

    def test_p11_unstated_scope_is_conditional_with_the_quoted_reason_and_p12_day(self):
        out = self.site()
        res = self.run_js(out, PICK + """load('/?fdfs_now=%d',390,function(f,d,w){d.querySelector('button.day[data-day=wed]').click();
d.querySelector('[data-wopen]').click();pc(d,'hsbc','hsbc:premier');
var r={sel:why(d,'hsbc-select-bms-saturday-bogo'),prem:why(d,'hsbc-premier-bms-bogo'),vis:vis(d,'#offers .offer'),
grp:txt(d.querySelector('.grp'))};d.querySelector('button.day[data-day=sat]').click();r.selSat=why(d,'hsbc-select-bms-saturday-bogo');
done(r)});""" % NOW)
        self.assertEqual(res["sel"], "Terms say “select HSBC credit cards”. Check yours is included · Book on a Saturday")
        self.assertEqual(res["selSat"], "Terms say “select HSBC credit cards”. Check yours is included")
        self.assertEqual(res["prem"], "Matches what you picked: HSBC Premier Mastercard")
        self.assertEqual(res["vis"], ["hsbc-premier-bms-bogo", "hsbc-select-bms-saturday-bogo"])
        self.assertEqual(res["grp"], "Matches for your cards")
        self.assertNotRegex(json.dumps(res), r"(?i)eligible|guaranteed")

    def test_p10_rows_without_freshness_are_computed_never_dropped(self):
        out = self.site()
        later = NOW + 3 * 86400 * 1000        # the fixture's checks are a few hours before NOW
        res = self.run_js(out, """load('/?fdfs_now=%d&day=all',390,function(f,d,w){done({vis:vis(d,'#offers .offer'),
lines:[].map.call(d.querySelectorAll('#offers .offer .o-stale'),function(p){return p.hidden?null:txt(p)})})});""" % later)
        movie = sorted(o["id"] for o in BASE["offers"] if o["category"] != "events")
        self.assertEqual(res["vis"], movie, "no row is dropped for lacking a freshness field")
        self.assertEqual(set(res["lines"]), {"Checked 3 days ago · check terms first"})

    def test_published_needs_recheck_is_stricter_and_never_the_top_pick(self):
        def edit(b):
            for o in b["offers"]:
                if o["id"] == "hsbc-premier-bms-bogo":
                    o["freshness"] = "needs_recheck"
        out = self.site_with(edit, "rc")
        res = self.run_js(out, PICK + """load('/?fdfs_now=%d',390,function(f,d,w){var p=d.querySelector('#hsbc-premier-bms-bogo .o-stale');
var r={line:p.hidden?null:txt(p),other:d.querySelector('#axis-select-district-bogo .o-stale').hidden};
d.querySelector('[data-wopen]').click();pc(d,'hsbc','hsbc:premier');r.hero=txt(d.querySelector('#answer .s-a'));
r.why=why(d,'hsbc-premier-bms-bogo');done(r)});""" % NOW)
        # the bot's wording: whole elapsed days, minimum 1 (a published needs_recheck checked hours ago says "1 day")
        self.assertEqual(res["line"], "Checked 1 day ago · check terms first", res)
        self.assertTrue(res["other"])
        self.assertNotIn("₹750", res["hero"])
        self.assertIn("Checked 1 day ago", res["why"])

    def test_d2_no_card_group_has_an_honest_empty_state(self):
        out = self.site()
        res = self.run_js(out, PICK + """load('/?fdfs_now=%d',390,function(f,d,w){d.querySelector('[data-mode=nocard]').click();
var r={vis:vis(d,'#offers .offer'),ne:txt(d.querySelector('.grp-e')),neShown:shown(d.querySelector('.grp-e')),
empty:d.querySelector('.empty').hidden,count:txt(d.querySelector('[data-count]')),spotCard:vis(d,'.spot[data-type=card]')};
d.querySelector('[data-mode=all]').click();d.querySelector('[data-wopen]').click();pc(d,'hsbc','hsbc:premier');
d.querySelector('[data-mode=nocard]').click();r.kept=txt(d.querySelector('[data-kept]'));r.W=w.FDFS.state().W;
d.querySelector('[data-mode=mine]').click();r.countMine=txt(d.querySelector('[data-count]'));r.visMine=vis(d,'#offers .offer');
r.spotInGrid=d.querySelectorAll('#offers .grid .spot').length;done(r)});""" % NOW)
        self.assertEqual(res["vis"], [])
        self.assertTrue(res["neShown"])
        self.assertTrue(res["ne"].startswith("No checked no-card offers right now."))
        self.assertTrue(res["empty"], "not a generic 'no results'")
        self.assertEqual(res["count"], "0", "spotted leads never count")
        self.assertEqual(res["spotCard"], [])
        self.assertEqual(res["kept"], "Your 1 card is kept.")
        self.assertEqual(res["W"], ["hsbc:premier"], "switching mode never erases picks")
        self.assertEqual(int(res["countMine"]), len(res["visMine"]))
        self.assertEqual(res["spotInGrid"], 0)

    def test_d3_minimums_and_group_bookings(self):
        def edit(b):
            for o in b["offers"]:
                if o["id"] == "axis-select-district-bogo":
                    o.update(kind="flat", value={"flat": 100}, min_tickets=None)
        out = self.site_with(edit, "mins")
        res = self.run_js(out, PICK + """load('/?fdfs_now=%d',390,function(f,d,w){d.querySelector('[data-wopen]').click();
pc(d,'hsbc','hsbc:premier');pc(d,'axis','axis:select');var r={};
d.querySelector('[data-tix="1"]').click();r.one=why(d,'hsbc-premier-bms-bogo');
d.querySelector('[data-tix="2"]').click();r.flat=why(d,'axis-select-district-bogo');r.two=why(d,'hsbc-premier-bms-bogo');
d.querySelector('[data-tix="4"]').click();r.four=why(d,'hsbc-premier-bms-bogo');r.url=w.location.search;
r.page=d.body.textContent;done(r)});""" % NOW)
        self.assertEqual(res["one"], "Needs 2+ tickets")
        self.assertEqual(res["flat"], "Minimum not stated in terms", "a null minimum never passes silently")
        self.assertEqual(res["two"], "Matches what you picked: HSBC Premier Mastercard")
        self.assertEqual(res["four"], "Matches what you picked: HSBC Premier Mastercard · Terms don’t say more than 1 ticket is free")
        self.assertIn("tickets=4", res["url"])
        self.assertNotRegex(res["page"], r"Minimum null|null tickets|undefined|NaN")

    def test_d5_storage_key_unknown_ids_and_no_card_id_leaves_the_device(self):
        out = self.site()
        res = self.run_js(out, PICK + """load('/?fdfs_now=%(now)d',390,function(f,d,w){
w.localStorage.setItem('fdfs.cards.v1',JSON.stringify(['hsbc:premier','bogus:card','HSBC','indusind']));
w.localStorage.setItem('fdfs-cards','["hsbc"]');
load('/?fdfs_now=%(now)d',390,function(f2,d2,w2){var r={W:w2.FDFS.state().W,legacy:w2.localStorage.getItem('fdfs-cards'),opened:[]};
w2.open=function(u){r.opened.push(u)};d2.querySelector('[data-share-view]').click();r.href=w2.location.href;
r.links=[].map.call(d2.querySelectorAll('a[href]'),function(a){return a.href}).join(' ');
r.res=performance.getEntriesByType('resource').map(function(e){return e.name}).join(' ')+' '+
w2.performance.getEntriesByType('resource').map(function(e){return e.name}).join(' ');
d2.querySelector('[data-wopen]').click();d2.querySelector('[data-iss=other]').click();r.other=txt(d2.getElementById('mc'));
d2.querySelector('[data-wclear]').click();r.after=w2.localStorage.getItem('fdfs.cards.v1');
d2.querySelector('[data-clear]').click();r.say=txt(d2.querySelector('[data-say]'));done(r)})});""" % {"now": NOW})
        self.assertEqual(res["W"], ["hsbc:premier", "indusind"], "IDs not in today's feed are dropped quietly")
        self.assertIsNone(res["legacy"])
        for k in ("href", "links", "res"):
            self.assertNotRegex(res[k], r"hsbc(:|%3A)premier|indusind(%2C|,)", k)
        self.assertNotRegex(" ".join(res["opened"]), r"(?i)premier|indusind|my%20cards|not%20sure")
        self.assertIn("No checked offers for other banks yet.", res["other"])
        self.assertIn("never ask for card numbers, CVV or photos", res["other"])
        self.assertIsNone(res["after"], "Forget my cards deletes the key")
        self.assertEqual(res["say"], "Choices cleared · showing all offers")

    def test_never_asks_for_card_details(self):
        out = self.site()
        res = self.run_js(out, PICK + """load('/?fdfs_now=%d',390,function(f,d,w){d.querySelector('[data-wopen]').click();
var t=[];['hsbc','axis','indusind','other'].forEach(function(b){d.querySelector('[data-iss="'+b+'"]').click();
[].forEach.call(d.querySelectorAll('#mc input'),function(i){t.push(i.type)})});done({types:t,html:d.getElementById('mc').innerHTML})});""" % NOW)
        self.assertEqual(set(res["types"]), {"checkbox"})
        self.assertNotRegex(res["html"], r'type="(text|number|tel|file|password)"|capture=|cvv"|pan"')
