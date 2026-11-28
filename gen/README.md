# FDFS site generator (S1)

Static, stdlib-only Python. No framework, no publish step.

```bash
python3 gen/fdfs_site.py                 # data/offers.json -> dist/ (per-page OG PNGs via headless Chrome)
python3 gen/fdfs_site.py --no-og         # same, every page uses the dateless brand card (no Chrome needed)
python3 brand/tools/build_og_brand.py    # re-render the dateless fallback card brand/logo/og-brand.png
python3 gen/fdfs_site.py --snapshot      # also file today's export under data/history/ (once per day)
python3 -m unittest discover -s tests -v # determinism, guards, stamps, copy, budgets, discovery
scripts/shoot_dist.sh dist preview/shots/s1 390 light / /bank/hsbc/   # screenshots
python3 scripts/indexnow_ping.py         # dry run; add --send only as the last step of a deploy
scripts/deploy.sh --dry-run              # build -> tests (abort on failure) -> show what would publish and be pinged
scripts/deploy.sh --branch <publish-branch> --push   # at launch only: publish dist/, push, IndexNow the changed URLs
```

**Inputs**
- `data/offers.json`: the Offer Watchdog export (`export_offers_json`, branch `claude/fdfs-offers-090`).
- `data/history/YYYY-MM-DD.json`: dated copies of that export. The changelog is the diff between them.
- `data/site.json`: config. `contact_email` and `analytics` are owner steps. Never add chat-app or product links before launch.
- `data/build-state.json`: per-URL content hash, lastmod and modified time.
- `data/indexnow-key.txt`: the public IndexNow key, published at `/<key>.txt`.

**Output:** `dist/` (git-ignored), containing:
- the pages;
- `sitemap.xml`, `robots.txt`;
- `offers.json` and `changes.json` (CC BY 4.0);
- `changes.xml` (Atom), `llms.txt`;
- the IndexNow key file;
- `site.webmanifest` and the assets;
- `.changed-urls.txt`, the input for the IndexNow ping.

**Guarantees** (each one is tested):
- **Deterministic.** The only clock is the export's `generated_at`.
- **A second validity guard.** An offer is shown only if `terms_verified`, started, not expired, checked within 7 days, and its source is https. The changelog uses the same guard on every snapshot.
- **No page without data.** Bank pages exist only for banks with an offer. The comparison page exists only with ≥1 movie offer. Card pages exist only for a card a live offer names, with its own set of offers (decision 144). Weekday pages exist only for a day a live offer's terms name (146). The guide's sections each need a live quoted example (147). There are no city pages; New this week is a noindex stub.
- **Honest dates.** Every page shows "Checked/Updated <date time> IST", equal to its JSON-LD `dateModified`. Sitemap `lastmod` moves only when the facts change, not on a re-check.
- **Clean copy.** No savings claims, urgency words, chat-app or product links, or `sameAs`.
- **OG cards (decision 158).** One idea per card, readable at thumbnail size. Offer cards show the benefit, then the card and app, then one quiet "Checked 26 Nov". Home, app, bank, card, weekday and best-card cards show the subject plus one fact from the page's own offers. Every number comes from the data, and the text never says "today". A fit step in headless Chrome shrinks any line that is too wide. Pages without a card of their own use the dateless brand card.
- **Labels never wider than the terms.** An unstated card scope always reads "Select <bank> credit cards". District's policy pages are read by a person (`manual_hosts`), and those offers say "Checked by hand".
- **Budget.** Every page is ≤ 20 KB gzip, HTML + CSS together (fonts excluded). The home page's search and "My cards" script (`gen/home.js`, inlined after a whitespace-only minify) has its own cap: ≤ 16 KB, ≤ 6.5 KB gzip.

**Discovery and plumbing:**
- `robots.txt` explicitly allows Googlebot, Bingbot, GPTBot, OAI-SearchBot, ChatGPT-User, PerplexityBot, ClaudeBot, Google-Extended, Applebot and others. It has no Disallow and no Crawl-delay, and it names the sitemap.
- The sitemap lists only real, indexable pages; lastmod comes from the content hash.
- `llms.txt` lists the key pages, the feeds, the licence and the method.
- Google finds the sitemap through robots.txt and Search Console (its ping endpoint is retired). Bing and the other IndexNow engines get a ping for the changed URLs only, after the push.
- `deploy.sh --snapshot` files the day's export under `data/history/`. Commit that file with the deploy.

**Scheduled refresh (decision 129, branch s1-refresh, not enabled yet):**
- `.github/workflows/refresh.yml` runs once a day at 08:00 IST (02:30 UTC), plus a manual trigger, one run at a time.
- It reads live with the offer engine and refresh scripts from the private `bookmyfdfs-ops` repo, which the workflow checks out with a deploy key and lays over this checkout at run time (they are not in this repo), then runs `scripts/deploy.sh --branch main --push`.
- Once a day because each run reads every page twice (read, then confirm), and 090 allows at most 2 reads per page per IST day.
- Any failure stops the run before publishing, and the last good site stays up.

**Search Console loop (decision 159):**
- `.github/workflows/gsc-gaps.yml` runs `scripts/gsc_gaps.py` every Monday at 05:30 IST, plus a manual trigger. It commits `data/gsc-gaps.json` and `docs/gsc/YYYY-MM-DD.md` to site-src. It never deploys.
- It reads 28 days of Search Analytics (web, India) against the 28 before, classifies each query, and ranks actions: `improve_page`, `rewrite_snippet` (flagged for review, never rewritten), `coverage_lead`, `new_page_candidate` (only with verified data behind it) and `won`.
- `coverage_hints` in the JSON is the hook for discovery: banks, cards and programmes people search for that have no verified offer, each with any matching Spotted lead ids and a search-shaped `discovery_focus`.
- Public outputs: impressions and clicks are buckets only, and no per-user data is written. Without `GSC_SA_JSON` the script says "not configured" and exits 0.

```bash
GSC_SA_JSON="$(cat key.json)" python3 scripts/gsc_gaps.py    # needs: pip install google-auth requests
python3 -m unittest tests.test_gsc_gaps                     # offline, fixtures in tests/fixtures/gsc/
```
