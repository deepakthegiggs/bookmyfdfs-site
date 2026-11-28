"""Decision 170 (growth agent, 26 Nov 2026). The owner, on three ideas borrowed from another site: "Add all three".

1. Countdown: an offer within 7 days of its checked end date says so on its card and its page ("Ends in 3 days ·
   28 Nov", "Last day · 28 Nov"), recomputed for the visitor's IST day, never ticking. Shared text carries the end date.
2. Search in the header of every page, phone included: a plain form to /?q= without JS; answers as you type from
   /search.json (checked offers and our pages, never a spotted lead) with JS.
3. An MCP server agents can run (read-only, stdio, standard library), served at /mcp/fdfs_mcp.py, reading /offers.json.
"""
import copy
import gzip
import html
import json
import os
import re
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
from test_redesign_r1 import BASE, NOW, SPOTS, SPOTTED, Browser, R1  # noqa: E402

SOON = "hsbc-premier-bms-bogo"          # set to end Sat 28 Nov: 3 days after the fixture's Wed 25 Nov
MS = lambda *a: int(datetime(*a, tzinfo=timezone.utc).timestamp() * 1000)   # noqa: E731


def soon_payload():
    p = copy.deepcopy(BASE)
    for o in p["offers"]:
        if o["id"] == SOON:
            o["valid_to"] = "2026-11-28"
    return p


class Soon(R1):
    def site_soon(self, name="soon"):
        w = self.tmp / name
        w.mkdir()
        p = soon_payload()
        (w / "offers.json").write_text(json.dumps(p))
        (w / "h").mkdir()
        (w / "h/2026-11-25.json").write_text(json.dumps(p))
        out = w / "dist"
        g.build(w / "offers.json", w / "h", out, w / "st.json", ROOT / "data/site.json", ROOT, spotted=SPOTS)
        return out


class Countdown(Soon):
    def test_card_always_keeps_the_countdown_chip(self):
        t = (self.site_soon() / "index.html").read_text()
        c = self.card(t, SOON)
        ul = re.search(r'<ul class="o-chips".*?</ul>', c, re.S).group(0)
        chips = re.findall(r'<li class="([^"]*)"[^>]*>(.*?)</li>', ul)
        self.assertLessEqual(len(chips), 3)                         # the 3-chip rule (decision 149) still holds
        self.assertEqual(chips[0][1].rsplit(">", 1)[-1], "Every day")
        self.assertEqual(chips[-1], ("c-end cd", "Ends in 3 days · 28 Nov"))   # kept over the limit chip
        self.assertIn('data-end="2026-11-28"', ul)

    def test_far_end_dates_get_no_countdown(self):
        t = (self.site() / "index.html").read_text()
        self.assertNotRegex(t, r'class="[^"]*\bcd\b')               # every fixture offer ends 31 Dec or later
        self.assertNotIn('class="cd-pill"', (self.site("b") / f"offer/{SOON}/index.html").read_text())

    def test_offer_page_pill_and_share_text_carry_the_end_date(self):
        out = self.site_soon()
        t = (out / f"offer/{SOON}/index.html").read_text()
        self.assertIn('<p class="cd-pill" data-end="2026-11-28">Ends in 3 days · 28 Nov</p>', t)
        self.assertLess(t.index('class="cd-pill"'), t.index('<h1'))
        row = re.search(r'<div class="wrap shr".*?</div>', t, re.S).group(0)
        self.assertIn("Valid until 28 Nov.", html.unescape(row))
        card = self.card((out / "index.html").read_text(), SOON)
        wa = re.search(r'href="(https://wa\.me/\?text=[^"]+)"', card).group(1)
        text = parse_qs(urlparse(html.unescape(wa)).query)["text"][0]
        self.assertIn("Valid until 28 Nov.", text)
        self.assertNotRegex(text, r"(?i)ends in|\bdays? left")       # a shared message keeps the date, not a count

    def test_no_urgency_words(self):
        for p in self.site_soon().rglob("*.html"):
            self.assertIsNone(g.BANNED.search(re.sub(r"<script.*?</script>", "", p.read_text(), flags=re.S)), p)


class Search(R1):
    def test_every_page_has_the_header_search_form(self):
        out = self.site()
        for p in out.rglob("*.html"):
            t = p.read_text()
            self.assertIn('<form class="hs-f" action="/" role="search">', t, p)
            self.assertIn('<input id="hs-q" name="q" type="search"', t, p)
            self.assertIn('<script src="/assets/search.js?v=', t, p)
        self.assertLess(len(gzip.compress((out / "assets/search.js").read_bytes())), 1536)  # gzip: it carries the panel CSS too

    def test_index_holds_checked_offers_and_real_pages_only(self):
        out = self.site()
        idx = json.loads((out / "search.json").read_text())
        urls = [x["u"] for x in idx["items"]]
        feed = json.loads((out / "offers.json").read_text())
        for o in feed["offers"]:
            self.assertIn(g.offer_path(o["id"]), urls)
        for u in urls:
            self.assertTrue((out / u.strip("/") / "index.html").exists(), u)
        blob = json.dumps(idx).lower()
        for s in SPOTTED:
            self.assertNotIn(s, blob)
        self.assertNotIn("/spotted/", urls)
        for x in idx["items"]:
            self.assertEqual(set(x), {"t", "s", "u", "k"})


class Agents(R1):
    def test_server_is_served_and_documented(self):
        out = self.site()
        self.assertEqual((out / "mcp/fdfs_mcp.py").read_bytes(), (ROOT / "gen/fdfs_mcp.py").read_bytes())
        page = (out / "agents/index.html").read_text()
        self.assertIn('href="/mcp/fdfs_mcp.py" download', page)
        self.assertIn("find_offers", page)
        self.assertIn("https://bookmyfdfs.in/mcp/fdfs_mcp.py", (out / "llms.txt").read_text())
        self.assertIn("https://fdfs-mcp.deepakthegiggs.workers.dev/mcp", (out / "llms.txt").read_text())
        self.assertIn("https://fdfs-mcp.deepakthegiggs.workers.dev/mcp", page)
        self.assertIn('href="/agents/"', (out / "index.html").read_text())
        self.assertIn("https://bookmyfdfs.in/agents/", (out / "sitemap.xml").read_text())

    def test_server_uses_the_standard_library_only(self):
        src = (ROOT / "gen/fdfs_mcp.py").read_text()
        mods = set(re.findall(r"^(?:import|from) ([a-z_.]+)", src, re.M))
        self.assertLessEqual({m.split(".")[0] for m in mods},
                             {"__future__", "json", "os", "sys", "time", "urllib", "datetime", "re"})
        self.assertNotRegex(src, r"(?i)spotted\.json|/spotted/")


def rpc(feed: Path, msgs: list, now="2026-11-26T10:00:00+05:30") -> dict:
    env = {**os.environ, "FDFS_NOW": now}
    env.pop("FDFS_FEED", None)
    r = subprocess.run([sys.executable, "-I", str(ROOT / "gen/fdfs_mcp.py"), "--feed", str(feed)],
                       input="".join(json.dumps(m) + "\n" for m in msgs), capture_output=True, text=True, timeout=30, env=env)
    return {m["id"]: m for m in map(json.loads, r.stdout.splitlines())}


class MCP(R1):
    def feed(self) -> Path:
        out = self.site()
        d = json.loads((out / "offers.json").read_text())
        for o in d["offers"]:
            if o["id"] == "indusind-eazydiner-platinum-bms-bogo":
                o["valid_to"] = "2026-11-20"                           # ended: never returned as live
            if o["id"] == "axis-select-district-bogo":
                o["checked_at"] = "2026-11-10T11:30:00+05:30"          # 16 days old: flagged
        p = self.tmp / "feed.json"
        p.write_text(json.dumps(d))
        return p

    def call(self, feed, name, args, i=9):
        return rpc(feed, [{"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}])[i]

    def test_handshake_and_tool_list(self):
        res = rpc(self.feed(), [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
            {"jsonrpc": "2.0", "id": 4, "method": "resources/read"}])
        self.assertEqual(set(res), {1, 2, 3, 4})                       # the notification gets no answer
        self.assertEqual(res[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", res[1]["result"]["capabilities"])
        self.assertEqual([t["name"] for t in res[2]["result"]["tools"]], ["find_offers", "match_cards", "get_offer", "list_banks"])
        for t in res[2]["result"]["tools"]:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(t["title"])                                # directories ask for a title and a read-only hint
            self.assertEqual(t["annotations"]["readOnlyHint"], True)
        self.assertEqual(res[3]["result"], {})
        self.assertEqual(res[4]["error"]["code"], -32601)
        old = rpc(self.tmp / "feed.json", [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}}])
        self.assertIn(old[1]["result"]["protocolVersion"], ("2025-11-25", "2025-06-18"))

    def test_saturday_on_bookmyshow(self):
        r = self.call(self.feed(), "find_offers", {"day": "Saturday", "app": "BookMyShow"})["result"]
        d = r["structuredContent"]
        self.assertEqual(json.loads(r["content"][-1]["text"]), d)       # the JSON, after a short text answer
        lead = r["content"][0]["text"]
        for o in d["offers"]:                                          # the text answer links every offer's page
            self.assertIn(o["url"], lead)
            self.assertTrue(o["url"].startswith("https://bookmyfdfs.in/offer/"))
            self.assertIn(o["url"], o["plan_text"])                    # the group message carries the link too
            self.assertTrue(o["whatsapp_url"].startswith("https://wa.me/?text="))
        ids = [o["id"] for o in d["offers"]]
        self.assertEqual(sorted(ids), ["hsbc-premier-bms-bogo", "hsbc-select-bms-saturday-bogo"])   # IndusInd ended
        for o in d["offers"]:
            for k in ("cap", "source_url", "checked_at", "url"):
                self.assertTrue(o.get(k), (o["id"], k))
        self.assertIn("FDFS (bookmyfdfs.in)", d["note"])

    def test_events_only_on_request_and_stale_flagged(self):
        f = self.feed()
        no = [o["id"] for o in self.call(f, "find_offers", {"bank": "hsbc"})["result"]["structuredContent"]["offers"]]
        yes = [o["id"] for o in self.call(f, "find_offers", {"bank": "hsbc", "include_events": True})["result"]["structuredContent"]["offers"]]
        self.assertNotIn("hsbc-allcards-bms-events-10pct", no)
        self.assertIn("hsbc-allcards-bms-events-10pct", yes)
        axis = self.call(f, "find_offers", {"query": "select", "app": "district"})["result"]["structuredContent"]["offers"]
        self.assertEqual([o["id"] for o in axis], ["axis-select-district-bogo"])
        self.assertIn("Not re-checked", axis[0]["freshness"])
        bogo = self.call(f, "find_offers", {"query": "buy 1 get 1"})["result"]["structuredContent"]
        self.assertGreater(bogo["count"], 0)

    def test_match_cards(self):
        f = self.feed()
        r = self.call(f, "match_cards", {"cards": ["HSBC Premier", "HSBC Select", "Axis My Zone", "HSBC", "SBI SimplyClick"],
                                         "tickets": 2})["result"]
        rows = {x["card"]: x for x in r["structuredContent"]["cards"]}
        ids = lambda c: [(o["id"], o["card_match"]) for o in rows[c]["offers"]]
        self.assertEqual(ids("HSBC Premier"), [("hsbc-premier-bms-bogo", "named card"),        # named card first,
                                               ("hsbc-select-bms-saturday-bogo", "select cards")])  # then "select cards"
        self.assertEqual(ids("HSBC Select"), [("hsbc-select-bms-saturday-bogo", "select cards")])  # unstated: never promised
        self.assertIn("payment screen", rows["HSBC Select"]["hint"])
        self.assertEqual(ids("Axis My Zone"), [("axis-myzone-district-bogo", "named card")])       # "MY ZONE" in the terms
        self.assertEqual(dict(ids("HSBC")), {"hsbc-premier-bms-bogo": "bank only",               # a bare bank name is hedged
                                             "hsbc-select-bms-saturday-bogo": "select cards"})
        self.assertIn("payment screen", rows["HSBC"]["hint"])           # the best HSBC row is the hedged Select one
        self.assertEqual(rows["SBI SimplyClick"]["count"], 0)
        self.assertEqual(r["structuredContent"]["best"], "hsbc-premier-bms-bogo")              # named card, biggest cap
        self.assertIn("https://bookmyfdfs.in/offer/hsbc-premier-bms-bogo/", r["content"][0]["text"])
        sat = self.call(f, "match_cards", {"cards": ["HSBC Select"], "day": "monday"})["result"]["structuredContent"]
        self.assertEqual(sat["cards"][0]["count"], 0)                   # a Saturday offer isn't offered for Monday
        one = self.call(f, "match_cards", {"cards": ["IndusInd Eazydiner Platinum"]})["result"]["structuredContent"]
        self.assertEqual(one["cards"][0]["count"], 0)                   # ended offers never match
        self.assertTrue(self.call(f, "match_cards", {"cards": []})["result"]["isError"])
        self.assertTrue(self.call(f, "match_cards", {"cards": "HSBC"})["result"]["isError"])

    def test_plan_text_uses_checked_fields_only(self):
        o = self.call(self.feed(), "find_offers", {"bank": "hsbc", "query": "premier"})["result"]["structuredContent"]["offers"][0]
        self.assertEqual(o["plan_text"], "HSBC Premier Mastercard on BookMyShow, 2nd ticket free up to \u20b9750, any day. "
                                         f"Valid until 31 Dec. Terms checked {o['plan_text'].split('Terms checked ')[1].split(' by')[0]} "
                                         "by FDFS: https://bookmyfdfs.in/offer/hsbc-premier-bms-bogo/")
        self.assertIsNone(g.BANNED.search(o["plan_text"].lower()))

    def test_get_offer_and_errors(self):
        f = self.feed()
        r = self.call(f, "get_offer", {"id": "hsbc-select-bms-saturday-bogo"})["result"]["structuredContent"]
        self.assertEqual(r["status"], "current")
        self.assertTrue(r["quotes"])
        self.assertEqual(self.call(f, "get_offer", {"id": "indusind-eazydiner-platinum-bms-bogo"})["result"]["structuredContent"]["status"], "ended")
        self.assertTrue(self.call(f, "get_offer", {"id": "nope"})["result"]["isError"])
        self.assertTrue(self.call(f, "find_offers", {"day": "someday"})["result"]["isError"])
        self.assertEqual(self.call(f, "no_such_tool", {})["error"]["code"], -32602)
        banks = self.call(f, "list_banks", {})["result"]["structuredContent"]["banks"]
        self.assertIn("HSBC", [b["issuer"] for b in banks])
        bad = self.call(self.tmp / "missing.json", "list_banks", {})["result"]
        self.assertTrue(bad["isError"])                                # an unreadable feed is a tool error, not a crash

    def test_parse_error_answers_once(self):
        env = {**os.environ}
        r = subprocess.run([sys.executable, "-I", str(ROOT / "gen/fdfs_mcp.py"), "--feed", str(self.feed())],
                           input="not json\n\n", capture_output=True, text=True, timeout=30, env=env)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["error"]["code"], -32700)


class Live(Browser, Soon):
    W = (320, 360, 390, 768, 1280)

    def test_countdown_follows_the_visitor_day(self):
        out = self.site_soon()
        days = {MS(2026, 11, 26, 6): ("Ends in 2 days · 28 Nov", True, False),
                MS(2026, 11, 27, 18, 31): ("Last day · 28 Nov", True, True),          # 00:01 IST Sat 28 Nov
                MS(2026, 11, 28, 18, 31): ("Ended 28 Nov", False, False)}
        body = """var W=%s,r={},k=0;function one(){if(k==W.length)return done(r);var t=W[k++];load('/offer/%s/?fdfs_now='+t,390,function(f,d){
var p=d.querySelector('.cd-pill'),c=null;load('/?fdfs_now='+t,390,function(f2,d2){c=d2.querySelector('#%s .o-chips [data-end]');
r[t]=[txt(p),p.classList.contains('cd'),p.classList.contains('cd0'),txt(c),c.classList.contains('cd')];one()})})}one();"""
        res = self.run_js(out, body % (json.dumps(list(days)), SOON, SOON), budget=12000)
        for t, (text, cd, cd0) in days.items():
            got = res[str(t)]
            self.assertEqual(got[:3], [text, cd, cd0], t)
            self.assertEqual(got[3:], [text, cd], t)

    def test_header_search_at_every_width(self):
        out = self.site()
        res = self.run_js(out, """var r=[],W=%s,k=0;function one(){if(k==W.length)return done({r:r});var w=W[k++];
load('/bank/axis/?fdfs_now=%d',w,function(f,d,win){var cw=d.documentElement.clientWidth,s=d.querySelector('.hs-b'),b=s.getBoundingClientRect(),
nav=[].filter.call(d.querySelectorAll('.top a,.top button,.top summary'),function(e){return e.getBoundingClientRect().width>0}).map(function(e){var x=e.getBoundingClientRect();return [e.className||e.textContent.trim(),Math.round(x.left),Math.round(x.right),Math.round(x.top)]});
s.click();var i=d.getElementById('hs-q');i.value='hsbc';i.dispatchEvent(new Event('input',{bubbles:true}));
setTimeout(function(){var fm=d.querySelector('.hs-f').getBoundingClientRect(),links=[].map.call(d.querySelectorAll('.hs-r a'),function(a){return a.getAttribute('href')});
var foc=d.activeElement&&d.activeElement.id;i.value='zzzz';i.dispatchEvent(new Event('input',{bubbles:true}));var none=txt(d.querySelector('.hs-r'));
d.querySelector('.hs').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
r.push({w:w,cw:cw,sc:scroll(d),btn:[Math.round(b.height),Math.round(b.right)],nav:nav,form:[Math.round(fm.left),Math.round(fm.right)],links:links,foc:foc,none:none,open:d.querySelector('.hs').open});one()},900)},900)}one();""" % (list(self.W), NOW),
                          budget=30000)
        for x in res["r"]:
            self.assertLessEqual(x["sc"][0], x["sc"][1], x)            # no sideways scroll with the search in the header
            self.assertGreaterEqual(x["btn"][0], 36, x)
            self.assertLessEqual(x["btn"][1], x["cw"], x)
            tops = {t for _, _, _, t in x["nav"]}
            for name, left, right, _ in x["nav"]:
                self.assertGreaterEqual(left, 0, (name, x))
                self.assertLessEqual(right, x["cw"], (name, x))
            self.assertLessEqual(max(tops) - min(tops), 16, x)            # the header stays one row
            self.assertGreaterEqual(x["form"][0], 0, x)
            self.assertLessEqual(x["form"][1], x["cw"], x)
            self.assertEqual(x["foc"], "hs-q", x)
            self.assertIn("/bank/hsbc/", x["links"], x)
            self.assertIn("/offer/hsbc-select-bms-saturday-bogo/", x["links"], x)
            self.assertIn("No checked offer matches", x["none"], x)
            self.assertFalse(x["open"], x)


if __name__ == "__main__":
    unittest.main()
