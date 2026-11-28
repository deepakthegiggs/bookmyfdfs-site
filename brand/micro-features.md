# FDFS micro-features: one page each, more value together (decision 111)

FDFS = Film · Deals · Friends · Seats (decision 134; supersedes 042's "Date"). Each feature below has its own URL that can win a specific query, and links into the others.

**Data key:**
- ✅ = we have the data now (the Offer Watchdog, decision 090).
- 🟡 = partly; it needs a small addition.
- ❌ = data we don't have yet. A new, allowed source is needed.

**Effort:** S = under 1 day on the static generator; M = 2–4 days; L = a new data pipeline.

**Standing rules:**
- no urgency;
- names as plain text, never logos;
- poster-free;
- every fact carries "checked <date, time>" and its source;
- no showtimes page (seats.movie owns showtimes and seat views).

**Search target: branded only** (owner, 25 Nov). "FDFS offers", "bookmyfdfs" and "FDFS Film Deals Friends Seats" go to `/` and `/fdfs`. The generic "FDFS meaning" isn't targeted. Every other page targets its own non-brand query (below).

**Ranked by unique value × reach.** The research round put the booking-open log first: nobody else has it.

| # | Feature (page or module) | The query it answers | Data | Why it ranks or gets cited | Effort |
|---|---|---|---|---|---|
| 1 | **Booking-open tracker**, `/booking-open/<film>` + the module and pills on New this week. A timestamped log of *when* booking opened, by film, city, chain and cinema: "Opened 6:02 PM in Kochi; Chennai not yet", with history. **Shown as "Coming soon" in the mock** | "<film> booking open", "<film> advance booking chennai", "when will <film> booking start" | ❌ **Source under legal review.** Our ticket watchdog sees this directly, but the ticket sites' terms ban automated reads. Options: chain announcements, partner feeds, or user reports | **The market gap.** Today the only answers are one-off trade "when will booking begin?" articles that are never updated. A dated, per-city log is unique data that AI answers will cite ("opened in Bengaluru 15 h before Chennai") | L |
| 2 | **"Valid today?" live answer**, the answer box on `/offer/<id>` + `/today` | "is hsbc bookmyshow offer valid today", "hsbc saturday offer today" | ✅ days, dates and quota notes. The day is computed at the daily build (IST) | A yes/no answer in 2 lines with `dateModified` is exactly what AI answers quote. Competitors' pages are undated | S |
| 3 | **Card picker: "Which card should I use?"**, `/which-card`: tick the cards you hold, pick an app and a day | "which credit card for bookmyshow", "best card for movie tickets district" | ✅ issuer, variant, platform, days, caps, spend gates | Static result pages per card and app (`/which-card/hsbc/bms`) cover the long tail. Sorted by cap with the gates shown. Never "best" | M |
| 4 | **Offer changelog**, `/changes` + an Atom feed + the home "Expired and changed" strip | "axis select movie offer changed", "is icici bookmyshow offer still valid" | ✅ the daily diff | A freshness signal crawlers love. "Changed 1 Nov: now needs ₹25,000 spend" gets cited when people are surprised at checkout | S |
| 5 | **Premium-screen seat guides**, `/seats/<chain>/<cinema>/<screen>` for IMAX, 4DX, recliner and Dolby screens: which rows, where the centre is, the recliner price vs the offer cap | "best seats <cinema> imax", "<cinema> 4dx which row", "recliner worth it" | 🟡 format norms (back rows, middle by default) ✅. Per-screen layouts ❌ (public chain pages, a site visit, user reports) | seats.movie has seat views but **no per-premium-screen guide**. That's the gap. It's evergreen, visual (an SVG diagram), and ties to the Seats beat and the cap | M per chain |
| 6 | **"Will my card work?" checker**, inline on every offer: ticks for app, channel, day, min tickets and end date | "hsbc offer not working bookmyshow", "axis offer not applied" | ✅ the machine-checkable fields. Spend gates and quotas are shown as "can't check: depends on your spends" | Frustrated "why didn't it work" queries are huge. An honest checklist earns trust and links | S |
| 7 | **Expired-offer pages that stay up**, `/offer/<id>`: "Expired on 31 Mar 2021" | "icici bookmyshow offer 2021", any old offer name | ✅ | People search old offer names from stale blogs. An honest page catches them and routes them to live offers | S |
| 8 | **New this week, per city**, `/new-this-week/<city>` (the mock) | "new tamil movies this week chennai", "movies releasing this friday hyderabad" | ❌ a release calendar from allowed sources (distributor and producer announcements, CBFC lists) | City × language × week pages make a long tail. It's the carrier for #1. Typographic cards are copyright-safe | M |
| 9 | **This weekend**, `/this-weekend`: Fri–Sun offers per app (timing, under the Deals beat) | "movie ticket offers this weekend", "saturday movie offers" | ✅ | It answers the most common timing question in one box, rebuilt daily | S |
| 10 | **Monthly offers calendar**, `/calendar/2026-12` | "movie offers december 2026" | ✅ days, `valid_to`, monthly resets | A fresh dated URL every month. Visual, not text | S |
| 11 | **Friends maths**, `/offers-for-2`, `/offers-for-4`: which offers need 2+ tickets, which cap applies to which ticket (the Friends beat) | "bogo offer for 4 tickets", "can i use bookmyshow offer for 3 tickets" | ✅ `min_tickets`, `free_cap`, limits | A real, unanswered question. It's factual from the terms, with no savings claim | S |
| 12 | **Bank, card and app hubs**, `/bank/hsbc`, `/card/axis-magnus`, `/app/district` | "hsbc movie offers", "axis magnus bookmyshow" | ✅ | The classic entity-hub structure, with internal links between bank, card and app | S |
| 13 | **Glossary**, `/glossary/<term>`: BOGO, convenience fee, "up to", spend gate, quota, recliner | "what is bogo in bookmyshow", "convenience fee on movie tickets" | ✅ our own copy | Definitional queries are where AI answers cite the clearest page. `DefinedTerm` JSON-LD | S |
| 14 | **Membership explainer**, `/district-pass`: what the pass covers, the limits and the cities. **No "you save" figure** | "is district pass worth it", "district pass benefits" | 🟡 the terms ✅. The price and city list need a checked source | Neutral "worth it" pages rank. We show the cap and limits, never a promise | S |
| 15 | **Open feed**, `/offers.json`, `/llms.txt`, `/changes.xml` | (answer engines and agents) | ✅ the export exists | GEO: a dated, sourced feed is the easiest thing to cite, and it puts us in the citation chain | S |

**Dropped:**
- **The "FDFS timing" explainers** (state show-time rules). They were built on the retired reading of FDFS, and they drift toward showtimes.
- **A showtimes page,** which belongs to seats.movie.

**How they work together.** The four beats are the site map:
- **Film** → New this week (#8), with booking opened (#1).
- **Deals** → Valid today (#2), This weekend (#9), Calendar (#10): when each deal works.
- **Friends** → Friends maths (#11).
- **Seats** → Premium-screen guides (#5), with "premium seats can cost more than the cap".

Every page cross-links to the offers that apply (#3, #6). The changelog (#4) and the feed (#15) are the freshness spine.

**Needs data we don't have yet:**
- #1 booking-open (source under legal review);
- #5 per-screen layouts;
- #8 release calendar;
- #14 Pass price and cities.

Everything else ships from the 090 export alone.
