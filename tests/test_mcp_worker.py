"""The hosted FDFS MCP server (gen/mcp-worker/worker.js, a Cloudflare Worker) must answer exactly like the
downloadable one (gen/fdfs_mcp.py). Owner, 26 Nov 2026: "launch fdfs as mcp ... ensure the mcp server also planned
accordingly"; built ahead of the owner's Cloudflare token, not deployed.

Runs the same JSON-RPC calls through both, on the fixture feed and on the real export, and requires identical
results, then checks the Worker's HTTP layer (POST /mcp, notifications, errors, CORS). Needs Node 18 or later;
skipped without it.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "gen/mcp-worker"))
sys.path.insert(0, str(ROOT / "tests"))
import build as worker_build  # noqa: E402
import fdfs_mcp as m  # noqa: E402
import fdfs_site as g  # noqa: E402
from test_redesign_r1 import R1  # noqa: E402

NODE = shutil.which("node")
WORKER = ROOT / "gen/mcp-worker/worker.js"
NOWS = ["2026-11-26T10:00:00+05:30", "2026-11-28T23:30:00+05:30", "2026-12-31T00:10:00+05:30"]


class _FileFeed:
    def __init__(self, data):
        self.data = data

    def get(self):
        return self.data


def calls(feed: dict) -> list:
    ids = [o["id"] for o in feed["offers"]]
    issuers = sorted({o["issuer"] for o in feed["offers"]})
    cards = [f"{o['issuer']} {v}" for o in feed["offers"] for v in (o.get("card_variants") or [])][:12]
    tc = lambda name, args: {"name": name, "arguments": args}  # noqa: E731
    out = [tc("list_banks", {}), tc("find_offers", {}), tc("find_offers", {"include_events": True}),
           tc("find_offers", {"day": "today"}), tc("find_offers", {"day": "Tomorrow", "app": "District"}),
           tc("find_offers", {"day": "sat", "app": "bookmyshow"}), tc("find_offers", {"query": "buy 1 get 1"}),
           tc("find_offers", {"query": "free_cap 250"}), tc("find_offers", {"query": "nothing-matches-this"}),
           tc("find_offers", {"day": "funday"}), tc("find_offers", {"app": "netflix"}),
           tc("match_cards", {"cards": cards or ["HSBC"]}),
           tc("match_cards", {"cards": issuers[:10], "day": "saturday", "tickets": 1}),
           tc("match_cards", {"cards": ["Axis My Zone credit", "HDFC Diners Club Privilege debit", "Visa Infinite",
                                        "RuPay", "SBI SimplyClick"], "include_events": True, "tickets": 2}),
           tc("match_cards", {"cards": []}), tc("match_cards", {"cards": "HSBC"}),
           tc("get_offer", {"id": "nope"}), tc("get_offer", {"id": "it's"}), tc("get_offer", {}),
           tc("nope", {}), {"name": "find_offers", "arguments": "x"}, {"name": "find_offers", "arguments": []}]
    out += [tc("find_offers", {"bank": i}) for i in issuers]
    out += [tc("get_offer", {"id": i}) for i in ids]
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}, {"jsonrpc": "2.0", "id": 4, "method": "ping"},
            {"jsonrpc": "2.0", "id": 5, "method": "resources/list"}, {"jsonrpc": "2.0", "id": "s", "method": "ping"}]
    return msgs + [{"jsonrpc": "2.0", "id": 100 + i, "method": "tools/call", "params": p} for i, p in enumerate(out)]


def run_worker(feed, now, messages=(), http=()) -> dict:
    r = subprocess.run([NODE, str(ROOT / "tests/mcp_worker_harness.mjs"), str(WORKER)],
                       input=json.dumps({"feed": feed, "now": now, "messages": list(messages), "http": list(http)}),
                       capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def run_python(feed, now, messages) -> list:
    old = os.environ.get("FDFS_NOW")
    os.environ["FDFS_NOW"] = now
    try:
        return [m.handle(msg, _FileFeed(feed)) for msg in messages]
    finally:
        if old is None:
            os.environ.pop("FDFS_NOW", None)
        else:
            os.environ["FDFS_NOW"] = old


class Sync(unittest.TestCase):
    def test_worker_js_is_built_from_the_python_constants(self):
        self.assertEqual(WORKER.read_text(encoding="utf-8"), worker_build.render(),
                         "worker.js is out of date: run python3 gen/mcp-worker/build.py")

    def test_wrangler_config_keeps_no_secret(self):
        t = (ROOT / "gen/mcp-worker/wrangler.toml").read_text()
        self.assertIn('main = "worker.js"', t)
        self.assertNotRegex(t, r"(?im)^\s*(account_id|api_token)\s*=")


@unittest.skipUnless(NODE, "node not installed")
class Parity(R1):
    def check(self, feed: dict):
        msgs = calls(feed)
        for now in NOWS:
            py = run_python(feed, now, msgs)
            js = run_worker(feed, now, msgs)["rpc"]
            self.assertEqual(len(py), len(js))
            for msg, a, b in zip(msgs, py, js):
                self.assertEqual(b, a, f"{now} {json.dumps(msg)[:160]}")

    def test_same_answers_on_the_fixture(self):
        self.check(json.loads((self.site() / "offers.json").read_text()))

    def test_same_answers_on_the_real_export(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            state = tmp / "state.json"
            shutil.copyfile(ROOT / "data/build-state.json", state)
            g.build(ROOT / "data/offers.json", ROOT / "data/history", tmp / "dist", state, ROOT / "data/site.json", ROOT,
                    render_og=False, spotted=ROOT / "data/spotted.json")
            self.check(json.loads((tmp / "dist/offers.json").read_text()))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(NODE, "node not installed")
class Http(R1):
    def test_streamable_http(self):
        feed = json.loads((self.site() / "offers.json").read_text())
        post = lambda body, **h: {"method": "POST", "path": "/mcp", "body": body,  # noqa: E731
                                  "headers": {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **h}}
        call = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                           "params": {"name": "match_cards", "arguments": {"cards": ["HSBC Premier"]}}})
        r = run_worker(feed, NOWS[0], http=[
            post(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})),
            post(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})),
            post(call), post("{not json"), post("x" * 70000),
            {"method": "GET", "path": "/mcp"}, {"method": "GET", "path": "/"}, {"method": "GET", "path": "/other"},
            {"method": "OPTIONS", "path": "/mcp"}, post(call)])
        init, note, called, bad, big, get, root, other, opts, again = r["http"]
        self.assertEqual(init["status"], 200)
        self.assertTrue(init["headers"]["content-type"].startswith("application/json"))
        self.assertEqual(json.loads(init["body"])["result"]["serverInfo"]["version"], m.VERSION)
        self.assertEqual((note["status"], note["body"]), (202, ""))            # a notification gets no body
        res = json.loads(called["body"])["result"]
        self.assertEqual(res["structuredContent"]["best"], "hsbc-premier-bms-bogo")
        self.assertIn("https://bookmyfdfs.in/offer/hsbc-premier-bms-bogo/", res["content"][0]["text"])
        self.assertEqual((bad["status"], json.loads(bad["body"])["error"]["code"]), (400, -32700))
        self.assertEqual(big["status"], 413)
        self.assertEqual((get["status"], get["headers"]["allow"]), (405, "POST, OPTIONS"))   # no event stream
        self.assertIn("bookmyfdfs.in/agents/", root["body"])
        self.assertEqual(other["status"], 404)
        self.assertEqual(opts["status"], 204)
        self.assertEqual(opts["headers"]["access-control-allow-origin"], "*")
        self.assertEqual(r["fetched"], 1)                                       # the feed is cached between calls
        self.assertEqual(json.loads(again["body"]), json.loads(called["body"]))

    def test_unreadable_feed_is_a_tool_error(self):
        r = run_worker(None, NOWS[0], messages=[{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                 "params": {"name": "list_banks", "arguments": {}}}])
        res = r["rpc"][0]["result"]
        self.assertTrue(res["isError"])
        self.assertIn("Couldn't read the FDFS feed", res["content"][0]["text"])

    def test_no_spotted_and_no_tracking(self):
        src = WORKER.read_text()
        self.assertNotRegex(src, r"(?i)spotted\.json|/spotted/|console\.log|localStorage|document\.cookie")
