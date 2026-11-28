"""S1 generator tests (stdlib unittest). Run: python3 -m unittest discover -s tests -v"""
import copy
import gzip
import json
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
import fdfs_site as g  # noqa: E402

FIX = json.loads((ROOT / "tests/fixtures/offers-d86d5dc.json").read_text(encoding="utf-8"))  # frozen fixture (090 d86d5dc), not the live export


def text_files(d: Path):
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.suffix in (".html", ".xml", ".json", ".txt", ".css", ".webmanifest"):
            yield p, p.read_text(encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def build(self, payload=None, name="a", state=None, history=None):
        w = self.tmp / name
        w.mkdir(exist_ok=True)
        data = w / "offers.json"
        data.write_text(json.dumps(payload if payload is not None else FIX, ensure_ascii=False), encoding="utf-8")
        hist = w / "history"
        hist.mkdir(exist_ok=True)
        for day, pl in (history or {"2026-11-25": payload if payload is not None else FIX}).items():
            (hist / f"{day}.json").write_text(json.dumps(pl, ensure_ascii=False), encoding="utf-8")
        st = state or (w / "state.json")
        out = w / "dist"
        r = g.build(data, hist, out, st, ROOT / "data/site.json", ROOT)
        return out, r, st


class Determinism(Base):
    def test_same_inputs_same_bytes(self):
        a, _, _ = self.build(name="a")
        b, _, _ = self.build(name="b")
        fa = {p.relative_to(a): p.read_bytes() for p in a.rglob("*") if p.is_file()}
        fb = {p.relative_to(b): p.read_bytes() for p in b.rglob("*") if p.is_file()}
        self.assertEqual(fa.keys(), fb.keys())
        for k in fa:
            self.assertEqual(fa[k], fb[k], f"{k} differs between two identical builds")

    def test_rebuild_with_state_is_stable(self):
        a, _, st = self.build(name="a")
        before = {p.relative_to(a): p.read_bytes() for p in a.rglob("*") if p.is_file() and p.name != ".changed-urls.txt"}
        a2, r, _ = self.build(name="a", state=st)
        after = {p.relative_to(a2): p.read_bytes() for p in a2.rglob("*") if p.is_file() and p.name != ".changed-urls.txt"}
        self.assertEqual(before, after)
        self.assertEqual(r["changed"], [], "an unchanged rebuild must not mark pages changed (no IndexNow ping)")


class NoPageWithoutData(Base):
    def test_empty_feed(self):
        out, r, _ = self.build({"schema": 1, "generated_at": FIX["generated_at"], "offers": []})
        self.assertFalse((out / "bank").exists())
        self.assertFalse((out / "best-card-for-movie-tickets").exists())
        self.assertIn("No movie ticket offer passes our checks on 25 Nov 2026", (out / "index.html").read_text())

    def test_bank_pages_only_for_banks_with_offers(self):
        out, r, _ = self.build()
        banks = sorted(p.name for p in (out / "bank").iterdir())
        issuers = sorted({g.norm(o).slug for o in FIX["offers"] if o.get("instrument") in ("credit", "debit")})
        self.assertEqual(banks, issuers)
        self.assertNotIn("district", banks, "a membership issuer is not a bank page")

    def test_new_this_week_off_for_launch(self):
        cfg = json.loads((ROOT / "data/site.json").read_text())
        self.assertIs(cfg["features"]["new_this_week"], False)
        out, _, _ = self.build()
        self.assertFalse((out / "new-this-week").exists())
        for p, t in text_files(out):
            self.assertNotIn("new-this-week", t, f"{p.relative_to(out)} links to a page that isn't built")

    def test_new_this_week_flag_on_builds_only_the_noindex_stub(self):
        cfg = json.loads((ROOT / "data/site.json").read_text())
        cfg["features"]["new_this_week"] = True
        on = self.tmp / "site-on.json"
        on.write_text(json.dumps(cfg))
        w = self.tmp / "on"
        w.mkdir()
        (w / "offers.json").write_text(json.dumps(FIX))
        (w / "h").mkdir()
        (w / "h/2026-11-25.json").write_text(json.dumps(FIX))
        out = w / "dist"
        g.build(w / "offers.json", w / "h", out, w / "st.json", on, ROOT)
        self.assertEqual([p for p in (out / "new-this-week").iterdir() if p.is_dir()], [], "never per-city pages")
        self.assertIn('name="robots" content="noindex', (out / "new-this-week/index.html").read_text())
        self.assertNotIn("/new-this-week/", (out / "sitemap.xml").read_text())

    def test_home_ends_with_what_is_fdfs(self):
        out, _, _ = self.build()
        main = re.search(r"<main id=\"main\">(.*)</main>", (out / "index.html").read_text(), re.S).group(1)
        self.assertEqual(re.findall(r'<section[^>]*\bid="([^"]+)"', main)[-1], "what")


class NeverShownAsValid(Base):
    def test_bad_states_are_held(self):
        now = datetime.fromisoformat(FIX["generated_at"])
        good = copy.deepcopy(FIX["offers"][0])
        bad = []
        for state, patch in (("conflicting", {}), ("discovered", {}), ("expired", {}), ("stale", {}), ("withdrawn", {}),
                             ("terms_verified", {"valid_to": "2026-11-01"}),
                             ("terms_verified", {"valid_from": "2027-01-01"}),
                             ("terms_verified", {"checked_at": (now - timedelta(days=8)).isoformat()}),
                             ("terms_verified", {"checked_at": None}),
                             ("terms_verified", {"source_url": "http://insecure.example/terms"})):
            o = copy.deepcopy(good)
            o.update({"id": f"bad-{len(bad)}", "state": state, **patch})
            bad.append(o)
        payload = {"schema": 1, "generated_at": FIX["generated_at"], "offers": [good] + bad}
        out, r, _ = self.build(payload)
        held = {o.id for o in r["held"]}
        self.assertEqual(held, {o["id"] for o in bad})
        for p, t in text_files(out):
            for o in bad:
                self.assertNotIn(o["id"], t, f"{o['id']} leaked into {p.name}")


class Stamps(Base):
    def test_date_modified_equals_visible_stamp(self):
        out, _, _ = self.build()
        for p in out.rglob("*.html"):
            t = p.read_text()
            ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', t, re.S).group(1))
            web = [x for x in ld["@graph"] if x["@type"] == "WebPage"][0]
            vis = re.search(r'<time datetime="([^"]+)" data-stamp>([^<]+)</time>', t)
            self.assertIsNotNone(vis, p)
            self.assertEqual(web["dateModified"], vis.group(1), p)
            d = datetime.fromisoformat(vis.group(1))
            self.assertEqual(g.fmt_stamp(d), vis.group(2), p)

    def test_recheck_without_change_keeps_lastmod_but_moves_stamp(self):
        out, _, st = self.build(name="a")
        sm1 = (out / "sitemap.xml").read_text()
        later = copy.deepcopy(FIX)
        nxt = datetime.fromisoformat(FIX["generated_at"]) + timedelta(days=1)
        later["generated_at"] = nxt.isoformat()
        for o in later["offers"]:
            o["checked_at"] = (datetime.fromisoformat(o["checked_at"]) + timedelta(days=1)).isoformat()
        out2, r, _ = self.build(later, name="a", state=st, history={"2026-11-25": FIX})
        self.assertEqual(re.findall(r"<loc>[^<]+/bank/[^<]+</loc><lastmod>[^<]+", sm1),
                         re.findall(r"<loc>[^<]+/bank/[^<]+</loc><lastmod>[^<]+", (out2 / "sitemap.xml").read_text()))
        self.assertIn("26 Nov 2026", (out2 / "bank/hsbc/index.html").read_text())


class Copy(Base):
    def test_no_urgency_or_savings_or_product_links(self):
        out, _, _ = self.build()
        bad = re.compile(r"you save|save ₹|hurry|only \d+ left|last chance|ends soon|limited time|don.t miss|sameAs|"
                         + g.PRELAUNCH.PATTERN, re.I)
        for p, t in text_files(out):
            if p.name == "site.css":
                continue
            m = bad.search(t)
            self.assertIsNone(m, f"{p.relative_to(out)}: {m.group(0) if m else ''}")

    def test_every_page_has_the_basics(self):
        out, _, _ = self.build()
        for p in out.rglob("*.html"):
            t = p.read_text()
            if p.name != "404.html":
                self.assertRegex(t, r'<link rel="canonical" href="https://bookmyfdfs\.in/')
            for typ in ('"Organization"', '"WebSite"'):
                self.assertIn(typ, t, f"{p}: {typ}")
            if p.name != "404.html" and p != out / "index.html":
                self.assertIn('"BreadcrumbList"', t, p)
            self.assertIn(g.FOOTER_LINE, t)
            self.assertRegex(re.search(r"<title>(.*?)</title>", t).group(1), r" · FDFS$")
            self.assertLess(t.index('id="answer"'), t.index("<main"), f"{p}: answer box must come first")

    def test_spend_gate_never_reads_a_year_as_money(self):
        self.assertEqual(g.spend_gate("Effective 1st Nov 2026, access ... minimum eligible spend of 25,000 in the preceding 3 calendar months"),
                         "Needs ₹25,000 card spend in the previous 3 calendar months")
        self.assertEqual(g.spend_gate("Valid from 2026 on spends"), "Needs a minimum card spend first (see terms)")


class Budget(Base):
    def test_page_weight(self):
        """Every page: HTML + CSS <= 20 KB gzip. The home page's search/"My cards" script (redesign r1) has its own
        budget below, so a feature script can't quietly eat the content budget (or the other way round)."""
        out, _, _ = self.build()
        css = len(gzip.compress((out / "assets/site.css").read_bytes()))
        for p in out.rglob("*.html"):
            # P3 (decision 156): plan.js (Saved, Sort, the calendar's today label) has its own cap in test_plan_p3
            page = p.read_text(encoding="utf-8").replace(g.home_js(), "").replace(g.PLAN.plan_js(), "")
            total = len(gzip.compress(page.encode("utf-8"))) + css
            # Home only: 20 -> 21 KB (26 Nov, site v2, decisions 141-142). It alone carries a "Terms & history" link per
            # card (L1) and the per-offer rows the My cards adapter reads (L2, ~0.3 KB gzip). Every other page stays at 20.
            # The real-data home budget (39 live leads, 26 KB) in test_redesign_r1 is unchanged.
            # Home 21 -> 22 KB (26 Nov, decision 162): the first screen now carries the best offer, the search example is
            # built from a listed offer, and share buttons sit on each card. Every other page stays at 20.
            # 22 -> 23 KB (decisions 164-168): share buttons, the live-events section, "New since your last visit".
            cap = 23 if p == out / "index.html" else 20
            self.assertLessEqual(total, cap * 1024, f"{p.relative_to(out)}: {total} bytes gzip with CSS")

    def test_home_script_budget(self):
        js = g.home_js().encode("utf-8")
        # raised 26 Nov for L2 exact card products; the written reason is in test_redesign_r1.Cards.test_script_is_private_and_modest
        self.assertLessEqual(len(js), 24 * 1024, f"home script {len(js)} bytes")
        self.assertLessEqual(len(gzip.compress(js)), 9.5 * 1024, "home script gzip")


class Discovery(Base):
    def test_robots_sitemap_feeds(self):
        out, _, _ = self.build()
        robots = (out / "robots.txt").read_text()
        for bot in ("OAI-SearchBot", "PerplexityBot", "Bingbot", "Googlebot"):
            self.assertIn(f"User-agent: {bot}\nAllow: /", robots)
        self.assertNotIn("Disallow: /\n", robots)
        offers = json.loads((out / "offers.json").read_text())
        self.assertEqual(offers["license"], "CC-BY-4.0")
        self.assertTrue(all(o["source_url"].startswith("https://") for o in offers["offers"]))
        self.assertIn("<feed", (out / "changes.xml").read_text())
        key = (ROOT / "data/indexnow-key.txt").read_text().strip()
        self.assertEqual((out / f"{key}.txt").read_text().strip(), key)


if __name__ == "__main__":
    unittest.main()


class NoPlaceholders(Base):
    PLACEHOLDER = re.compile(r"coming soon|will be listed|to be added|placeholder|TODO|TBD|lorem", re.I)

    def test_no_placeholder_text(self):
        """No placeholder lines on any page, no exceptions."""
        out, _, _ = self.build()
        for p, t in text_files(out):
            if p.suffix != ".html":
                continue
            visible = re.sub(r"<script.*?</script>|<style.*?</style>", "", t, flags=re.S)
            m = self.PLACEHOLDER.search(visible)
            self.assertIsNone(m, f"{p.relative_to(out)}: {m.group(0) if m else ''}")

    def test_contact_is_optional(self):
        cfg = json.loads((ROOT / "data/site.json").read_text())
        self.assertNotIn("contact_email", cfg)
        out, _, _ = self.build()
        for page in ("about", "corrections", "disclosures"):
            t = (out / page / "index.html").read_text()
            self.assertNotIn("mailto:", t)
            self.assertNotRegex(t, r"(?i)\bcontact\b.*\b(email|address)\b")
        self.assertIn("logged publicly", (out / "about/index.html").read_text())


class Plumbing(Base):
    BOTS = ("Googlebot", "Bingbot", "GPTBot", "OAI-SearchBot", "ChatGPT-User", "PerplexityBot", "ClaudeBot",
            "Google-Extended", "Applebot")

    def test_robots_allows_search_and_ai_crawlers(self):
        out, _, _ = self.build()
        robots = (out / "robots.txt").read_text()
        self.assertIn("Sitemap: https://bookmyfdfs.in/sitemap.xml", robots)
        for bot in self.BOTS:
            self.assertIn(f"User-agent: {bot}\nAllow: /\n", robots)
        self.assertNotIn("Disallow", robots)
        self.assertNotIn("Crawl-delay", robots)

    def test_sitemap_lists_only_real_indexable_pages(self):
        out, _, _ = self.build()
        locs = re.findall(r"<loc>https://bookmyfdfs\.in(/[^<]*)</loc>", (out / "sitemap.xml").read_text())
        self.assertTrue(locs)
        for path in locs:
            f = out / path.strip("/") / "index.html" if path != "/" else out / "index.html"
            self.assertTrue(f.exists(), f"{path} would 404")
            self.assertNotIn("noindex", f.read_text(), path)
        self.assertNotIn("404", (out / "sitemap.xml").read_text())
        built = {"/" if p == out / "index.html" else "/" + str(p.parent.relative_to(out)) + "/"
                 for p in out.rglob("index.html") if p.relative_to(out).parts[0] != "v2"}   # decision 171: noindex preview
        self.assertFalse([x for x in locs if x.startswith("/v2/")], "the v2 preview is never in the sitemap")
        self.assertEqual(set(locs), built, "every built page is in the sitemap")

    def test_llms_txt_links_resolve(self):
        out, _, _ = self.build()
        t = (out / "llms.txt").read_text()
        links = re.findall(r"\]\((https://bookmyfdfs\.in(/[^)]*))\)", t)
        self.assertTrue(any(p == "/offers.json" for _, p in links))
        for feed in ("/changes.json", "/changes.xml", "/how-we-check/"):
            self.assertIn(feed, [p for _, p in links])
        self.assertIn("CC BY 4.0", t)
        for _, path in links:
            f = out / path.strip("/") / "index.html" if path.endswith("/") and path != "/" else \
                (out / "index.html" if path == "/" else out / path.lstrip("/"))
            self.assertTrue(f.exists(), path)


class Deploy(Base):
    def run_deploy(self, test_cmd):
        import os
        import subprocess
        src = self.tmp / "source.txt"
        if not src.exists():
            src.write_text("source: Offer Watchdog export\nmethod: live run, 25 Nov 2026\n")
        env = dict(os.environ, FDFS_SOURCE=str(src), FDFS_TEST_CMD=test_cmd, FDFS_OUT=str(self.tmp / "dist"),
                   FDFS_STATE=str(self.tmp / "state.json"), FDFS_BUILD_ARGS="--no-og --history " + str(self.tmp / "hist"))
        (self.tmp / "hist").mkdir(exist_ok=True)
        (self.tmp / "hist/2026-11-25.json").write_text(json.dumps(FIX))
        return subprocess.run(["sh", str(ROOT / "scripts/deploy.sh"), "--dry-run"], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=120)

    def test_refuses_fixture_or_replay_data(self):
        for words in ("method: the registry's pages replayed from the fixtures", "FIXTURE export", "Replay run"):
            (self.tmp / "source.txt").write_text(f"source: Offer Watchdog export\n{words}\n")
            r = self.run_deploy("true")
            self.assertNotEqual(r.returncode, 0, words)
            self.assertIn("fixture/replay, not a live check", r.stderr)
            self.assertNotIn("would publish", r.stdout)

    def test_refuses_fixture_spotted_leads(self):
        import os
        os.environ["FDFS_SPOTTED"] = str(ROOT / "tests/fixtures/spotted-fixture.json")
        try:
            r = self.run_deploy("true")
        finally:
            del os.environ["FDFS_SPOTTED"]
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("placeholder (example.*) sources", r.stderr)
        self.assertNotIn("would publish", r.stdout)

    def test_refuses_without_a_source_note(self):
        import os
        import subprocess
        env = dict(os.environ, FDFS_SOURCE=str(self.tmp / "missing.txt"), FDFS_TEST_CMD="true",
                   FDFS_OUT=str(self.tmp / "dist"), FDFS_STATE=str(self.tmp / "s.json"), FDFS_BUILD_ARGS="--no-og")
        r = subprocess.run(["sh", str(ROOT / "scripts/deploy.sh"), "--dry-run"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("is missing", r.stderr)

    def test_aborts_on_failing_tests(self):
        r = self.run_deploy("exit 1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ABORT: tests failed", r.stderr)
        self.assertNotIn("would publish", r.stdout)

    def test_dry_run_reports_changed_urls_only(self):
        r = self.run_deploy("true")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry run: would publish", r.stdout)
        self.assertIn("https://bookmyfdfs.in/", r.stdout)


class McpRegistryProof(unittest.TestCase):
    """/.well-known/mcp-registry-auth: the public key line only, checked before it can be served."""
    def root_with(self, text):
        r = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, r)
        (r / "data").mkdir()
        if text is not None:
            (r / "data/mcp-registry-auth.txt").write_text(text, encoding="utf-8")
        return r

    def test_no_file_serves_nothing(self):
        self.assertIsNone(g.mcp_registry_proof(self.root_with(None)))

    def test_public_key_line_is_served(self):
        line = "v=MCPv1; k=ed25519; p=" + "A" * 43 + "="
        self.assertEqual(g.mcp_registry_proof(self.root_with(line + "\n")), line)

    def test_anything_else_stops_the_build(self):
        for bad in ("-----BEGIN PRIVATE KEY-----\nMC4CAQAwBQYDK2VwBCIEI\n-----END PRIVATE KEY-----",
                    "v=MCPv1; k=ed25519; p=short=", "v=MCPv1; k=rsa; p=" + "A" * 43 + "=",
                    "v=MCPv1; k=ed25519; p=" + "A" * 43 + "=\nextra"):
            with self.assertRaises(ValueError):
                g.mcp_registry_proof(self.root_with(bad))

    def test_repo_file_if_present_is_valid(self):
        g.mcp_registry_proof(ROOT)   # raises if a committed proof is malformed


class CustomDomain(Base):
    def test_dist_keeps_cname_and_nojekyll(self):
        out, _, _ = self.build()
        self.assertEqual((out / "CNAME").read_bytes(), b"bookmyfdfs.in")
        self.assertEqual((ROOT / "CNAME").read_text().strip(), "bookmyfdfs.in", "matches the live file on main")
        self.assertTrue((out / ".nojekyll").exists())

    def test_deploy_aborts_if_cname_is_lost(self):
        import os
        import subprocess
        outdir = self.tmp / "dist"
        (self.tmp / "hist").mkdir(exist_ok=True)
        (self.tmp / "hist/2026-11-25.json").write_text(json.dumps(FIX))
        src = self.tmp / "source.txt"
        src.write_text("source: Offer Watchdog export\nmethod: live run\n")
        env = dict(os.environ, FDFS_SOURCE=str(src), FDFS_OUT=str(outdir), FDFS_STATE=str(self.tmp / "state.json"),
                   FDFS_BUILD_ARGS="--no-og --history " + str(self.tmp / "hist"),
                   FDFS_TEST_CMD=f"rm {outdir}/CNAME")      # simulate a build that lost the file
        r = subprocess.run(["sh", str(ROOT / "scripts/deploy.sh"), "--dry-run"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("CNAME must be exactly bookmyfdfs.in", r.stderr)


class CurrentData(Base):
    """Whatever data/offers.json holds today builds and renders by the rules (no facts about which offers exist)."""

    def test_todays_export_builds_and_every_shown_offer_renders(self):
        data = json.loads((ROOT / "data/offers.json").read_text(encoding="utf-8"))
        out, r, _ = self.build(data, name="today", history={"2026-11-25": data})
        home = (out / "index.html").read_text()
        held = {o.id for o in r["held"]}
        movie = [o for o in data["offers"] if o["category"] != "events" and o["id"] not in held]
        events = [o for o in data["offers"] if o["category"] == "events" and o["id"] not in held]
        self.assertEqual(len(re.findall(r'<article class="offer"', home)), len(movie))
        self.assertEqual(len(re.findall(r'<aside class="also"', home)), len(events))
        for o in movie:
            self.assertIn(f'id="{o["id"]}"', home)
        if movie:
            self.assertIn(f"<strong>{len(movie)} checked movie offer{'s' if len(movie) > 1 else ''}</strong>", home)
        for p in r["pages"]:
            self.assertTrue((out / (p.strip("/") + "/index.html" if p != "/" else "index.html")).exists(), p)


class LaunchExport(Base):
    """Facts about the 25 Nov launch export (a frozen copy), checked on the built site. Rules, not today's data."""

    def build_live(self):
        live = json.loads((ROOT / "tests/fixtures/offers-spotted-base.json").read_text(encoding="utf-8"))
        out, r, _ = self.build(live, name="live", history={"2026-11-25": live})
        return live, out, r

    def test_counts_come_from_the_export(self):
        live, out, r = self.build_live()
        movie = [o for o in live["offers"] if o["category"] != "events"]
        events = [o for o in live["offers"] if o["category"] == "events"]
        home = (out / "index.html").read_text()
        self.assertEqual(r["held"], [])
        self.assertEqual(len(re.findall(r'<article class="offer"', home)), len(movie))
        self.assertIn(f"<strong>{len(movie)} checked movie offers</strong>", home)
        self.assertEqual(len(re.findall(r'<aside class="also"', home)), len(events))

    def test_held_offers_appear_nowhere(self):
        _, out, _ = self.build_live()
        for p, t in text_files(out):
            if p.name == "site.css":
                continue
            t = t.replace(g.home_js(), "")   # the search vocabulary names every bank and app by design: not offer data
            for word in ("District Pass", "Magnus", "ICICI", "MobiKwik", "UPI"):
                if word == "ICICI" and p.parent.name == "best-card-for-movie-tickets":
                    continue  # named only in the 'Not on this list yet' line, by design
                self.assertNotIn(word, t, f"{p.relative_to(out)}: {word}")

    def test_check_lines_use_the_exports_checked_at(self):
        live, out, _ = self.build_live()
        home = (out / "index.html").read_text()
        n = 0
        for o in live["offers"]:
            stamp = g.fmt_stamp(datetime.fromisoformat(o["checked_at"]))
            card = re.search(rf'<article class="offer" id="{o["id"]}".*?</article>', home, re.S)
            if card:
                n += 1
                self.assertIn(f'Checked by FDFS Offer Intelligence · <span class="nw">{stamp}</span>', card.group(0))
        self.assertGreater(n, 0)

    def test_every_condition_code_in_the_export_is_worded(self):
        _, _, r = self.build_live()
        self.assertEqual([w for w in r["warnings"] if "unknown condition" in w], [])
